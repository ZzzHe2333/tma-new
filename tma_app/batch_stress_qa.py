"""Repeat full multi-file imports under cyclic-GC/table-update pressure."""
from __future__ import annotations

import csv
import gc
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import traceback

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from . import __version__
from . import batch_analysis as backend
from .batch_qa import wait_until
from .gui_gc import ensure_gui_gc


def verify(window, output, paths):
    output = Path(output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'failed', 'version': __version__, 'checks': []}
    original_lookup = backend.lookup_record
    original_mass = os.environ.get('TMA_MASS_XLSX')
    stop = threading.Event(); release_mass = threading.Event(); mass_entered = threading.Event()
    ticks, gc_threads, rounds = [], [], []
    main_thread = threading.get_ident()
    collector = ensure_gui_gc(QApplication.instance())
    old_interval = collector.timer.interval(); collector.timer.setInterval(30)
    before_collections = collector.collections
    pressure = None
    def gc_event(phase, info):
        if phase == 'start': gc_threads.append(threading.get_ident())
    def allocate():
        while not stop.is_set():
            cycles = [[] for _ in range(600)]
            for cycle in cycles: cycle.append(cycle)
            time.sleep(.005)
    def slow_mass(*args, **kwargs):
        mass_entered.set(); release_mass.wait(45)
        return original_lookup(*args, **kwargs)
    timer = QTimer(); timer.setInterval(20)
    def tick():
        ticks.append(time.perf_counter())
        dialog = getattr(window, 'batch_dialog', None)
        if dialog is not None and len(ticks) % 3 == 0:
            dialog.refresh_view()
    timer.timeout.connect(tick)
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    try:
        assert len(paths) >= 5 and not gc.isenabled()
        weights = output.with_suffix('.weights.csv')
        with weights.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream); writer.writerow(['样品名', 'M (mg)'])
            for path in paths: writer.writerow([path.stem, .47])
        os.environ['TMA_MASS_XLSX'] = str(weights)
        backend.lookup_record = slow_mass
        gc.callbacks.append(gc_event)
        pressure = threading.Thread(target=allocate, name='QA-allocation-pressure', daemon=True)
        pressure.start(); timer.start()
        for index in range(3):
            started = time.perf_counter()
            window.import_files(paths)
            dialog = window.batch_dialog
            wait_until(lambda: any(row.get('T1') is not None for row in dialog.view_rows), timeout=60000)
            first = time.perf_counter()-started
            wait_until(lambda: all(row.get('T1') is not None for row in dialog.view_rows), timeout=60000)
            all_values = time.perf_counter()-started
            wait_until(mass_entered.is_set)
            if index == 0:
                assert not release_mass.is_set() and all(row.get('M') is None for row in dialog.view_rows)
                dialog.CopyBatch.click()
                assert len(QApplication.clipboard().text().splitlines()) == len(paths)+1
                assert dialog.ExportBatchPlots.isEnabled() and dialog.ExportBatchXlsx.isEnabled()
                report['checks'].append('all_T1_T2_H_and_copy_available_before_blocked_mass_returns')
                release_mass.set()
            wait_until(lambda: dialog.job is None and window.worker is None, timeout=60000)
            assert all(row['M'] == .47 and not row.get('error') for row in dialog.view_rows)
            assert len(window.curves) == len(paths)*(index+1)
            rounds.append({'files': len(paths), 'first_values_seconds': first, 'all_values_seconds': all_values,
                           'complete_seconds': time.perf_counter()-started})
        wait_until(lambda: collector.collections > before_collections and bool(gc_threads))
        assert set(gc_threads) == {main_thread}, gc_threads
        assert all(hashlib.sha256(path.read_bytes()).hexdigest() == hashes[str(path)] for path in paths)
        dialog.all_button.click(); assert len(dialog.view_rows) == len(paths)*3
        dialog.grab().save(str(output.with_suffix('.table.png')))
        report['checks'] += ['three_full_multi_imports_with_concurrent_table_rebuild_and_allocating_worker',
                             'cyclic_GC_only_on_GUI_thread', 'duplicate_openings_and_session_rows_independent',
                             'input_sha256_unchanged']
        report.update(status='passed', rows=len(dialog.rows), curves=len(window.curves), rounds=rounds,
                      gc_collections=collector.collections-before_collections, gc_thread_ids=sorted(set(gc_threads)),
                      main_thread_id=main_thread, ui_timer_ticks=len(ticks),
                      max_ui_tick_gap_seconds=max((b-a for a,b in zip(ticks,ticks[1:])), default=0),
                      input_sha256=hashes)
    except BaseException:
        report['error'] = traceback.format_exc()
        raise
    finally:
        release_mass.set(); stop.set(); timer.stop()
        if pressure is not None: pressure.join(5)
        if gc_event in gc.callbacks: gc.callbacks.remove(gc_event)
        collector.timer.setInterval(old_interval)
        backend.lookup_record = original_lookup
        if original_mass is None: os.environ.pop('TMA_MASS_XLSX', None)
        else: os.environ['TMA_MASS_XLSX'] = original_mass
        window.dirty = False
        if window.worker is None: window.close()
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report
