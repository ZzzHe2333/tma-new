"""Slow network tables/locks must not block Test, Save, Cancel or GUI timers."""
import threading
import time

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog

from test_point_interaction import ui
from tma_app import mass_lookup as mass, path_settings as settings
from tma_app.batch_qa import wait_until
from tma_app.mass_jobs import MassLookupJob


@pytest.fixture(autouse=True)
def no_mass_override(monkeypatch):
    monkeypatch.delenv('TMA_MASS_XLSX', raising=False)
    mass.clear_cache()
    yield
    mass.clear_cache()


def table(tmp_path, name='weights.csv', value=.47):
    path = tmp_path / name
    path.write_text(f'样品名,M (mg)\npoint,{value}\n', encoding='utf-8-sig')
    return str(path)


def test_test_then_save_during_locked_network_read_keeps_gui_live(ui, tmp_path, monkeypatch):
    source = table(tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = mass._rows; threads = []
    def slow_rows(path):
        threads.append(threading.get_ident()); entered.set(); release.wait(10)
        yield from original(path)
    monkeypatch.setattr(mass, '_rows', slow_rows)
    dialog = ui.show_path_settings(); dialog.paths.item(0, 1).setText(source)
    curve = ui.selected(); doc = ui.active_document()
    ticks = []; timer = QTimer(); timer.timeout.connect(lambda: ticks.append(1)); timer.start(5)
    try:
        started = time.monotonic(); dialog.test_mass()
        assert time.monotonic() - started < .5
        wait_until(entered.is_set)
        assert not dialog.test_button.isEnabled()
        started = time.monotonic(); dialog.accept()
        assert time.monotonic() - started < .5
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert settings.load_paths()['m'] == source
        assert ui._mass_refresh_job is not None
        wait_until(lambda: len(ticks) >= 6)
        assert ui.selected() is curve and ui.active_document() is doc
        assert ui._mass_refresh_job is not None
    finally:
        release.set(); timer.stop()
    wait_until(lambda: ui._mass_refresh_job is None)
    assert curve.dataset.metadata['LookupMass'] == ['0.47']
    assert len(threads) == 1 and threads[0] != threading.get_ident()
    assert ui.selected() is curve and ui.active_document() is doc


def test_completed_test_save_reuses_table_revision_without_cache_clear(ui, tmp_path, monkeypatch):
    source = table(tmp_path); calls = []; original = mass._rows
    def rows(path): calls.append(str(path)); yield from original(path)
    monkeypatch.setattr(mass, '_rows', rows)
    dialog = ui.show_path_settings(); dialog.paths.item(0, 1).setText(source); dialog.test_mass()
    wait_until(lambda: dialog.mass_job is None)
    assert '0.47 mg' in dialog.feedback.text()
    assert 'LookupMass' not in ui.selected().dataset.metadata
    dialog.accept()
    assert ui.selected().dataset.metadata['LookupMass'] == ['0.47']
    wait_until(lambda: ui._mass_refresh_job is None)
    assert calls == [source]


def test_real_xlsx_test_and_save_read_workbook_once_off_gui(ui, tmp_path, monkeypatch):
    from openpyxl import Workbook
    source = tmp_path / '称量数据.xlsx'
    book = Workbook(); book.active.append(['样品名', '重量 (mg)']); book.active.append(['point', .49])
    book.save(source); book.close()
    calls = []; original = mass._rows
    def rows(path):
        calls.append(threading.get_ident()); yield from original(path)
    monkeypatch.setattr(mass, '_rows', rows)
    dialog = ui.show_path_settings(); dialog.paths.item(0, 1).setText(str(source)); dialog.test_button.click()
    wait_until(lambda: dialog.mass_job is None)
    assert '0.49 mg' in dialog.feedback.text()
    dialog.accept(); wait_until(lambda: ui._mass_refresh_job is None)
    assert len(calls) == 1 and calls[0] != threading.get_ident()
    assert ui.selected().dataset.metadata['LookupMass'] == ['0.49']


@pytest.mark.parametrize('action', ['reject', 'close'])
def test_test_cancel_or_close_does_not_wait_or_apply_late_result(ui, tmp_path, monkeypatch, action):
    entered, release = threading.Event(), threading.Event(); done = threading.Event()
    def lookup(sample, source):
        entered.set(); release.wait(10); done.set(); return mass.MassMatch(.91, source, 'mg', 'matched')
    monkeypatch.setattr(mass, 'lookup_record', lookup)
    dialog = ui.show_path_settings(); dialog.paths.item(0, 1).setText(table(tmp_path)); dialog.test_mass()
    wait_until(entered.is_set)
    try:
        started = time.monotonic(); getattr(dialog, action)()
        assert time.monotonic() - started < .5 and not dialog.isVisible()
        assert settings.load_paths()['m'] == ''
    finally: release.set()
    wait_until(done.is_set); QApplication.processEvents()
    assert 'LookupMass' not in ui.selected().dataset.metadata


def test_editing_m_discards_old_test_but_other_path_keeps_test(ui, tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event(); original = mass.lookup_record
    old, new = table(tmp_path, 'old.csv', .47), table(tmp_path, 'new.csv', .58)
    def lookup(sample, source):
        if source == old: entered.set(); release.wait(10)
        return original(sample, source)
    monkeypatch.setattr(mass, 'lookup_record', lookup)
    dialog = ui.show_path_settings(); dialog.paths.item(0, 1).setText(old); dialog.test_mass()
    wait_until(entered.is_set)
    try:
        dialog.paths.item(1, 1).setText(str(tmp_path))
        assert dialog.mass_job is not None
        dialog.paths.item(0, 1).setText(new)
        assert dialog.mass_job is None and dialog.test_button.isEnabled()
        dialog.test_mass(); wait_until(lambda: dialog.mass_job is None)
        assert '0.58 mg' in dialog.feedback.text()
        dialog.accept(); wait_until(lambda: ui._mass_refresh_job is None)
    finally: release.set()
    wait_until(lambda: not any(t.name == 'TMA-mass-lookup' and t.is_alive() for t in threading.enumerate()))
    QApplication.processEvents()
    assert ui.selected().dataset.metadata['LookupMass'] == ['0.58']


def test_new_save_supersedes_older_mass_refresh_and_import_result(ui, tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event(); original = mass.lookup_record
    old, new = table(tmp_path, 'old.csv', .47), table(tmp_path, 'new.csv', .58)
    curve = ui.selected(); curve.dataset._mass_stale_ticket = 'irrelevant'
    ui._import_mass_targets = {'old-ticket': curve.dataset.document_key}
    def lookup(sample, source):
        if source == old: entered.set(); release.wait(10)
        return original(sample, source)
    monkeypatch.setattr(mass, 'lookup_record', lookup)
    settings.save_paths({'m': old}); ui.refresh_mass_lookup(); wait_until(entered.is_set)
    try:
        assert 'old-ticket' not in ui._import_mass_targets
        settings.save_paths({'m': new}); ui.refresh_mass_lookup()
        wait_until(lambda: ui._mass_refresh_job is None)
        assert curve.dataset.metadata['LookupMass'] == ['0.58']
        ui.import_mass_ready('old-ticket', curve.sample_name, old, mass.MassMatch(.91, old, 'mg'))
        assert curve.dataset.metadata['LookupMass'] == ['0.58']
    finally: release.set()
    wait_until(lambda: not any(t.name == 'TMA-mass-lookup' and t.is_alive() for t in threading.enumerate()))
    QApplication.processEvents(); assert curve.dataset.metadata['LookupMass'] == ['0.58']


def test_mass_results_and_signals_are_delivered_on_gui_thread(ui, tmp_path, monkeypatch):
    main = threading.get_ident(); worker_threads = []; gui_threads = []
    original = mass.lookup_record
    def lookup(*args): worker_threads.append(threading.get_ident()); return original(*args)
    monkeypatch.setattr(mass, 'lookup_record', lookup)
    job = MassLookupJob([('a', 'point'), ('b', 'point')], table(tmp_path), ui)
    finished = []
    job.row_ready.connect(lambda *args: gui_threads.append(threading.get_ident()), Qt.ConnectionType.DirectConnection)
    job.finished.connect(lambda: finished.append(1)); job.start(); wait_until(lambda: bool(finished))
    assert worker_threads == [job.worker_thread.ident] and worker_threads[0] != main
    assert gui_threads == [main, main]


def test_unreachable_source_finishes_without_overwriting_raw_mass(ui, tmp_path):
    curve = ui.selected(); curve.dataset.metadata['Mass'] = ['original instrument mass']
    settings.save_paths({'m': str(tmp_path / 'missing.xlsx')}); ui.refresh_mass_lookup()
    wait_until(lambda: ui._mass_refresh_job is None)
    assert 'LookupMass' not in curve.dataset.metadata
    assert curve.dataset.metadata['Mass'] == ['original instrument mass']
    assert '0/1' in ui.statusBar().currentMessage()


def test_folder_only_save_during_test_does_not_cancel_valid_request(ui, tmp_path):
    source = table(tmp_path); settings.save_paths({'m': source})
    dialog = ui.show_path_settings(); dialog.test_mass(); wait_until(lambda: dialog.mass_job is None)
    dialog.paths.item(1, 1).setText(str(tmp_path)); dialog.accept()
    wait_until(lambda: ui._mass_refresh_job is None)
    assert settings.import_folder() == str(tmp_path)
    assert ui.selected().dataset.metadata['LookupMass'] == ['0.47']
