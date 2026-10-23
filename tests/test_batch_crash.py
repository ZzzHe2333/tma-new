"""Regress worker-triggered Qt wrapper GC and weighing-blocked batch values."""
import gc
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import weakref

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QWidget

from test_batch_analysis import ui, samples, wait_until, ROOT
from tma_app import batch_analysis as backend
from tma_app.mass_lookup import MassMatch
from PySide6.QtCore import Qt


def test_all_numerical_rows_arrive_before_slow_first_mass(ui, samples, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    calculate = backend.calculate_file
    def tracked(path):
        calls.append(str(path))
        return calculate(path)
    def slow_mass(*args, **kwargs):
        entered.set()
        release.wait(10)
        return MassMatch(.47, 'test.csv', 'mg', 'matched')
    monkeypatch.setattr(backend, 'calculate_file', tracked)
    monkeypatch.setattr(backend, 'lookup_record', slow_mass)
    inputs = samples * 3
    dialog = ui.show_batch_analysis(inputs)
    try:
        wait_until(entered.is_set)
        wait_until(lambda: all(row.get('T1') is not None for row in dialog.rows))
        assert len(calls) == len(inputs) and len(dialog.rows) == len(inputs)
        assert all(row.get('M') is None for row in dialog.rows)
        assert all(button.isEnabled() for button in (dialog.CopyBatch, dialog.ExportBatchPlots, dialog.ExportBatchXlsx))
        dialog.CopyBatch.click()
        assert len(QApplication.clipboard().text().splitlines()) == len(inputs) + 1
        assert len(dialog._job_completed) == len(inputs)
    finally:
        release.set()
    wait_until(lambda: dialog.job is None)
    assert all(row['M'] == .47 for row in dialog.rows)


def test_cancel_during_mass_does_not_accept_late_reply(ui, samples, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def slow_mass(*args, **kwargs):
        entered.set(); release.wait(10)
        return MassMatch(.47, 'test.csv', 'mg', 'matched')
    monkeypatch.setattr(backend, 'lookup_record', slow_mass)
    dialog = ui.show_batch_analysis(samples)
    try:
        wait_until(entered.is_set)
        wait_until(lambda: all(row.get('T1') is not None for row in dialog.rows))
        dialog.cancel_processing()
    finally:
        release.set()
    wait_until(lambda: dialog.job is None)
    assert all(row['T1'] is not None and row.get('M') is None and row['state'] == '已取消' for row in dialog.rows)


def test_cyclic_widget_finalizers_and_gc_run_on_gui_thread(ui):
    application = QApplication.instance()
    from tma_app.gui_gc import ensure_gui_gc
    collector = ensure_gui_gc(application)
    assert collector is ensure_gui_gc(application) and not gc.isenabled()
    assert collector.thread() == application.thread()
    main = threading.get_ident()
    collected, finalized = [], []
    def gc_event(phase, info):
        if phase == 'start': collected.append(threading.get_ident())
    gc.callbacks.append(gc_event)
    for _ in range(50):
        widget = QWidget()
        widget.cycle = widget
        weakref.finalize(widget, lambda: finalized.append(threading.get_ident()))
    del widget
    stop = threading.Event()
    def allocate():
        while not stop.is_set():
            cycles = [[] for _ in range(1000)]
            for cycle in cycles: cycle.append(cycle)
            time.sleep(.005)
    worker = threading.Thread(target=allocate)
    old_interval = collector.timer.interval()
    collector.timer.setInterval(10)
    worker.start()
    try:
        wait_until(lambda: len(finalized) == 50)
        assert collected and set(collected) == {main}
        assert set(finalized) == {main}
        assert collector.last_thread == QThread.currentThread()
    finally:
        stop.set(); worker.join(3)
        collector.timer.setInterval(old_interval)
        gc.callbacks.remove(gc_event)


def test_local_batch_cold_start_does_not_load_http_transport(samples, tmp_path):
    target = tmp_path / 'cold.json'
    code = "from tma_app.batch_analysis import calculate_file; import json,sys,time; s=time.perf_counter(); r=calculate_file(sys.argv[1]); open(sys.argv[2],'w').write(json.dumps({'error':r['error'],'httpx_loaded':'httpx' in sys.modules,'elapsed':time.perf_counter()-s,'T1':r['T1']}))"
    result = subprocess.run([sys.executable, '-c', code, str(samples[0]), str(target)], cwd=ROOT, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    data = json.loads(target.read_text())
    assert not data['error'] and data['T1'] is not None and data['httpx_loaded'] is False


def test_weighing_source_path_is_not_resolved_per_record(tmp_path, monkeypatch):
    from tma_app import mass_lookup as mass
    source = tmp_path / 'large.csv'
    source.write_text('sample,M (mg)\n' + ''.join(f's{i},0.47\n' for i in range(1000)), encoding='utf-8')
    resolve = Path.resolve
    calls = []
    def tracked(path, *args, **kwargs):
        if path == source: calls.append(1)
        return resolve(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'resolve', tracked)
    mass.clear_cache()
    match = mass.lookup_record('s999', str(source))
    assert match.value == .47 and len(calls) < 8


def test_simultaneous_curve_and_batch_mass_requests_read_workbook_once(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from tma_app import mass_lookup as mass
    source = tmp_path / 'shared.csv'
    source.write_text('sample,M (mg)\ns1,0.47\ns2,0.55\n', encoding='utf-8')
    entered, release = threading.Event(), threading.Event()
    reads = []
    rows = mass._rows
    def slow_rows(path):
        reads.append(1); entered.set(); release.wait(10)
        yield from rows(path)
    monkeypatch.setattr(mass, '_rows', slow_rows)
    mass.clear_cache()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(mass.lookup_record, 's1', str(source))
        assert entered.wait(5)
        second = pool.submit(mass.lookup_record, 's2', str(source))
        release.set()
        assert first.result(10).value == .47 and second.result(10).value == .55
    assert len(reads) == 1


def test_worker_results_are_emitted_only_from_gui_thread(ui, samples, monkeypatch):
    from tma_app.batch_dialog import BatchJob
    main = threading.get_ident(); calculated, delivered = [], []
    original = backend.calculate_file
    def calculate(path):
        calculated.append(threading.get_ident()); return original(path)
    monkeypatch.setattr(backend, 'calculate_file', calculate)
    job = BatchJob('calculate', [('one', str(samples[0]))], '')
    job.row_ready.connect(lambda key, row: delivered.append(threading.get_ident()), Qt.ConnectionType.DirectConnection)
    ended = []
    job.finished.connect(lambda: ended.append(threading.get_ident()), Qt.ConnectionType.DirectConnection)
    job.start()
    wait_until(lambda: bool(ended))
    assert calculated and all(value != main for value in calculated)
    assert delivered and set(delivered + ended) == {main}
    job.deleteLater()


def test_normal_import_applies_curves_on_gui_thread(ui, samples, monkeypatch):
    main = threading.get_ident(); applied = []
    original = ui.finish_import
    def finish(datasets, failures):
        applied.append(threading.get_ident()); return original(datasets, failures)
    monkeypatch.setattr(ui, 'finish_import', finish)
    ui.import_files(samples[:2])
    wait_until(lambda: ui.worker is None and ui.batch_dialog.job is None)
    assert applied and set(applied) == {main} and len(ui.curves) == 2


def test_model_updates_keep_selection_and_expose_four_values(ui, samples, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def slow(*args, **kwargs):
        entered.set(); release.wait(10); return MassMatch(.47, 'fixture.csv', 'mg', 'matched')
    monkeypatch.setattr(backend, 'lookup_record', slow)
    dialog = ui.show_batch_analysis(samples)
    try:
        wait_until(entered.is_set)
        wait_until(lambda: dialog.table.model().data(dialog.table.model().index(1, 0)) not in (None, ''))
        dialog.table.selectRow(1)
        chosen = dialog.selected_rows()[0]['id']
    finally: release.set()
    wait_until(lambda: dialog.job is None)
    assert [row['id'] for row in dialog.selected_rows()] == [chosen]
    assert dialog.table.model().data(dialog.table.model().index(1, 2)) == '0.4700'
    assert dialog.table.model().headerData(1, Qt.Orientation.Vertical).endswith(samples[1].name)


def test_switching_to_smaller_batch_clears_old_selection_safely(ui, samples):
    dialog = ui.show_batch_analysis(samples * 3)
    wait_until(lambda: dialog.job is None)
    dialog.table.selectRow(len(dialog.rows)-1)
    dialog.enqueue_files([samples[0]])
    wait_until(lambda: dialog.job is None)
    assert dialog.table.rowCount() == 1 and len(dialog.selected_rows()) == 1
    dialog.CopyBatch.click()
    assert len(QApplication.clipboard().text().splitlines()) == 2


def test_diagnostics_rebinds_existing_fault_handler_and_falls_back(tmp_path):
    blocked = tmp_path / 'not-a-directory'
    blocked.write_text('keep', encoding='utf-8')
    code = "import os,sys,tempfile,faulthandler,json; os.environ['LOCALAPPDATA']=sys.argv[1]; tempfile.gettempdir=lambda:sys.argv[2]; faulthandler.enable(); from tma_app.diagnostics import install,record_event; p=install(); record_event('test.ready'); print(json.dumps({'folder':str(p),'enabled':faulthandler.is_enabled()}))"
    result = subprocess.run([sys.executable, '-c', code, str(blocked), str(tmp_path/'fallback')], cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data['enabled'] and Path(data['folder']).is_relative_to(tmp_path/'fallback')
    folder = Path(data['folder'])
    records = [json.loads(line) for line in next(folder.glob('run-*.jsonl')).read_text(encoding='utf-8').splitlines()]
    assert records[0]['event'] == 'startup' and records[1]['event'] == 'test.ready'
    assert next(folder.glob('native-*.log')).exists() and blocked.read_text() == 'keep'
