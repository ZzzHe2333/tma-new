"""Local, frozen-capable regression for Test -> Save while a sheet is locked."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import threading
import time
import traceback
import uuid

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog

from . import __version__, mass_lookup as mass, path_settings as settings
from .batch_qa import wait_until
from .reader import read_dataset


def verify(window, output, paths):
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'failed', 'version': __version__, 'checks': []}
    previous_appdata = os.environ.get('LOCALAPPDATA')
    previous_mass = os.environ.get('TMA_MASS_XLSX')
    os.environ['LOCALAPPDATA'] = str(output.parent / ('mass-settings-fixture-' + uuid.uuid4().hex[:8]))
    os.environ.pop('TMA_MASS_XLSX', None)
    rows = mass._rows
    entered, release = threading.Event(), threading.Event()
    heartbeat = QTimer(); ticks = []; threads = []
    heartbeat.timeout.connect(lambda: ticks.append(time.monotonic())); heartbeat.start(10)
    try:
        source_hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        window.finish_import([read_dataset(path) for path in paths], [])
        window.show_overlay(); QApplication.processEvents()
        curve = window.selected(); document = window.active_document()
        source = output.with_suffix('.weights.csv')
        with source.open('w', encoding='utf-8-sig', newline='') as file:
            writer = csv.writer(file); writer.writerow(['样品名', 'M (mg)'])
            for sample in dict.fromkeys(c.sample_name for c in window.curves): writer.writerow([sample, .49])
        def blocked_rows(path):
            threads.append(threading.get_ident()); entered.set(); release.wait(20)
            yield from rows(path)
        mass._rows = blocked_rows; mass.clear_cache()
        dialog = window.show_path_settings(); dialog.paths.item(0, 1).setText(str(source))
        started = time.monotonic(); dialog.test_mass(); report['test_return_seconds'] = time.monotonic()-started
        wait_until(entered.is_set)
        assert not dialog.test_button.isEnabled()
        started = time.monotonic(); dialog.accept(); report['save_return_seconds'] = time.monotonic()-started
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert settings.load_paths()['m'] == str(source)
        start_ticks = len(ticks); wait_until(lambda: len(ticks) >= start_ticks+15)
        assert window._mass_refresh_job is not None and not release.is_set()
        assert report['test_return_seconds'] < 1 and report['save_return_seconds'] < 1
        assert window.selected() is curve and window.active_document() is document
        report['checks'].append('test_and_save_return_immediately_while_workbook_read_is_blocked')
        report['checks'].append('gui_heartbeat_continues_while_mass_refresh_waits_on_same_table_lock')
        release.set(); wait_until(lambda: window._mass_refresh_job is None)
        assert all(c.dataset.metadata.get('LookupMass') == ['0.49'] for c in window.curves)
        assert len(threads) == 1 and threads[0] != threading.get_ident()
        assert window.selected() is curve and window.active_document() is document
        report['checks'].append('background_refresh_updates_all_m_preserves_selection_and_reuses_table_revision')
        dialog = window.show_path_settings(); dialog.test_mass(); wait_until(lambda: dialog.mass_job is None)
        assert '0.49 mg' in dialog.feedback.text()
        dialog.grab().save(str(output.with_suffix('.settings.png')))
        dialog.accept(); wait_until(lambda: window._mass_refresh_job is None)
        assert len(threads) == 1
        window.grab().save(str(output.with_suffix('.main.png')))
        report['checks'].append('completed_test_then_save_reuses_cache_without_another_excel_read')
        assert source_hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        report.update(status='passed', source_sha256=source_hashes, gui_heartbeats=len(ticks))
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        release.set(); heartbeat.stop(); mass._rows = rows; mass.clear_cache()
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        window.dirty = False; window.close()
        if previous_appdata is None: os.environ.pop('LOCALAPPDATA', None)
        else: os.environ['LOCALAPPDATA'] = previous_appdata
        if previous_mass is None: os.environ.pop('TMA_MASS_XLSX', None)
        else: os.environ['TMA_MASS_XLSX'] = previous_mass
    if report['status'] != 'passed': raise SystemExit(1)
