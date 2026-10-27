"""Reading another file must never depend on an outstanding weighing lookup."""
import threading

import numpy as np
from test_point_interaction import ui
from test_import_instances import datafile
from tma_app.batch_qa import wait_until
from tma_app.mass_lookup import MassMatch


def test_import_after_processing_does_not_wait_for_previous_mass(ui, tmp_path, monkeypatch):
    import tma_app.mass_lookup as mass
    ui.close_all_documents()
    first = datafile(tmp_path)
    second = tmp_path / 'next.001'
    second.write_bytes(first.read_bytes().replace(b'Sample repeated', b'Sample next'))
    entered, release = threading.Event(), threading.Event()

    def slow_mass(sample, source=None):
        entered.set()
        release.wait(8)
        return MassMatch(.47, 'test-only.csv', 'mg', 'matched')

    monkeypatch.setattr(mass, 'configured_source', lambda: 'test-only.csv')
    monkeypatch.setattr(mass, 'lookup_record', slow_mass)
    try:
        ui.import_files([first])
        wait_until(lambda: len(ui.curves) == 1 and entered.is_set(), timeout=3000)
        ui.start_point_measurement('dimension_change')
        ui.confirm_measurement()
        ui.process('smooth')
        original = ui.curves[0]
        expected = original.working.copy()
        ui.import_files([second])
        wait_until(lambda: len(ui.curves) == 2, timeout=1500)
        assert not release.is_set(), 'The second file must open while m is still waiting'
        assert ui.selected().dataset.path == second
        np.testing.assert_array_equal(original.working, expected)
        assert len(ui.results) == 1
    finally:
        release.set()
        wait_until(lambda: ui.worker is None)
        if ui._import_mass_job is not None:
            wait_until(lambda: ui._import_mass_job.pending == 0)


def test_many_reopens_share_one_mass_worker_and_keep_independent_metadata(ui, tmp_path, monkeypatch):
    import tma_app.mass_lookup as mass
    ui.close_all_documents();path = datafile(tmp_path)
    entered, release = threading.Event(), threading.Event();calls = []

    def slow_mass(sample, source=None):
        calls.append(threading.get_ident());entered.set();release.wait(8)
        return MassMatch(.48, 'test.csv', 'mg', 'matched')

    monkeypatch.setattr(mass, 'configured_source', lambda: 'test.csv')
    monkeypatch.setattr(mass, 'lookup_record', slow_mass)
    try:
        ui.import_files([path]);wait_until(lambda: entered.is_set() and len(ui.curves) == 1)
        job = ui._import_mass_job;thread = job.worker_thread
        for count in range(2, 7):
            ui.import_files([path]);wait_until(lambda: len(ui.curves) == count, timeout=1500)
            assert ui._import_mass_job is job and job.worker_thread is thread
        assert len(calls) == 1 and job.pending == 6
        assert len({c.dataset.document_key for c in ui.curves}) == 6
        assert len({id(c.dataset.metadata) for c in ui.curves}) == 6
        release.set();wait_until(lambda: job.pending == 0)
        assert len(calls) == 6 and len(set(calls)) == 1
        assert all(c.dataset.metadata['LookupMass'] == ['0.48'] for c in ui.curves)
        assert not getattr(ui, '_import_mass_targets', {}) and not job.timer.isActive()
    finally:release.set()


def test_failed_mass_request_does_not_lose_following_requests(ui, tmp_path, monkeypatch):
    import tma_app.mass_lookup as mass
    ui.close_all_documents();path=datafile(tmp_path);calls=[]
    def lookup(sample, source=None):
        calls.append(sample)
        if len(calls)==1:raise OSError('offline test source')
        return MassMatch(.49, 'test.csv', 'mg', 'matched')
    monkeypatch.setattr(mass,'configured_source',lambda:'test.csv')
    monkeypatch.setattr(mass,'lookup_record',lookup)
    ui.import_files([path,path],batch_results=False)
    wait_until(lambda: len(ui.curves)==2 and ui._import_mass_job.pending==0)
    assert 'LookupMass' not in ui.curves[0].dataset.metadata
    assert ui.curves[1].dataset.metadata['LookupMass']==['0.49']
    ui.import_files([path]);wait_until(lambda:len(ui.curves)==3 and ui._import_mass_job.pending==0)
    assert ui.curves[2].dataset.metadata['LookupMass']==['0.49']
