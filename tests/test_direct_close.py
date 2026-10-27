"""Closing is immediate and optional saves never block a data processor."""
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from test_feature_ui import ui, imported
from tma_app.batch_qa import wait_until


def no_prompt(*args,**kwargs):
    raise AssertionError('Closing must not ask to save or wait')


@pytest.mark.parametrize('with_data',[False,True])
def test_dirty_close_never_prompts_or_saves(ui,tmp_path,monkeypatch,with_data):
    if with_data:
        imported(ui,tmp_path,1);ui.start_point_measurement('dimension_change');ui.confirm_measurement()
    ui.touch();assert '*' not in ui.windowTitle() and '未保存' not in ui.windowTitle()
    monkeypatch.setattr(QMessageBox,'question',no_prompt)
    monkeypatch.setattr(ui,'warn',no_prompt);monkeypatch.setattr(ui,'save',no_prompt)
    before=sorted(tmp_path.rglob('*.tmas'))
    started=time.perf_counter();assert ui.close()
    assert time.perf_counter()-started<.5
    assert ui._closing and ui._mcp_closed and not ui.isVisible()
    assert sorted(tmp_path.rglob('*.tmas'))==before


@pytest.mark.parametrize('phase',['file','mass'])
def test_close_cancels_slow_import_without_waiting_or_applying_late_events(ui,tmp_path,monkeypatch,phase):
    import tma_app.app as module
    import tma_app.mass_lookup as mass
    path=tmp_path/'slow.001'
    path.write_text('Sample slow\nNsig 3\nSig1 Time (min)\nSig2 Temperature (°C)\nSig3 Dimension Change (µm)\nStartOfData\n0 100 0\n1 101 5\n',encoding='utf-8')
    entered=threading.Event();release=threading.Event();reads=[]
    real_read=module.read_dataset;real_mass=mass.lookup_record
    def reader(file):
        reads.append(file)
        if phase=='file':entered.set();release.wait(5)
        return real_read(file)
    def lookup(*args,**kwargs):
        if phase=='mass':entered.set();release.wait(5)
        return real_mass(*args,**kwargs)
    monkeypatch.setattr(module,'read_dataset',reader);monkeypatch.setattr(mass,'lookup_record',lookup)
    monkeypatch.setattr(QMessageBox,'question',no_prompt);monkeypatch.setattr(ui,'warn',no_prompt)
    ui.import_files([path]);job=ui.worker
    try:
        wait_until(entered.is_set)
        if phase=='mass':
            wait_until(lambda:len(ui.curves)==1 and ui.worker is None)
            job=ui._import_mass_job
        ui.import_files([path])
        if phase=='file':assert ui._pending_import_paths
        before=list(ui.curves);started=time.perf_counter()
        assert ui.close() and time.perf_counter()-started<.5
        assert job.cancelled.is_set() and not job.timer.isActive()
        assert ui.worker is None and ui._pending_import_paths==[]
        assert job.worker_thread.daemon and job.worker_thread.is_alive()
        release.set();job.worker_thread.join(3);QApplication.processEvents()
        assert ui.curves==before and (len(reads)==1 if phase=='file' else len(reads)<=2)
    finally:
        release.set();job.worker_thread.join(3)


def test_busy_children_and_batch_are_cancelled_instead_of_vetoing_exit(ui,tmp_path,monkeypatch):
    imported(ui,tmp_path,1)
    from tma_app.share_dialog import ShareDialog
    share=ui.share_dialog=ShareDialog(ui);share.busy=True;share.timer.start();share.show()
    batch=ui.show_batch_analysis(popup=False)
    report_job=SimpleNamespace(cancelled=threading.Event())
    dialog=QDialog(ui);dialog.job=report_job;dialog.show()
    monkeypatch.setattr(QMessageBox,'question',no_prompt)
    assert ui.close()
    assert not share.isVisible() and not share.timer.isActive()
    assert batch._shutdown and not dialog.isVisible() and report_job.cancelled.is_set()


def test_nonblocking_mcp_stop_signals_shutdown_without_joining():
    from tma_app.mcp_service import McpService
    service=McpService();service.active.set()
    def joined(*args,**kwargs):raise AssertionError('Application close must not join background threads')
    thread=SimpleNamespace(is_alive=lambda:True,join=joined)
    stopped=threading.Event()
    service.jobs=SimpleNamespace(shutdown=stopped.set,worker=thread)
    service.server=SimpleNamespace(should_exit=False);service.thread=thread
    service.stop(wait=False)
    assert stopped.is_set() and not service.active.is_set() and service.server.should_exit
    assert service.state=='stopping'
