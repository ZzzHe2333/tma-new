"""Repeated actions stay bounded, cancelable and display the current data."""
import queue
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication,QEvent,QEventLoop,QTimer,Qt
from PySide6.QtWidgets import QApplication

from test_feature_ui import ui,source
from tma_app.batch_qa import wait_until


def settle(milliseconds=120):
    loop=QEventLoop();QTimer.singleShot(milliseconds,loop.quit);loop.exec()


def test_switch_and_select_only_build_one_plot_and_keep_current_curve(ui,tmp_path,monkeypatch):
    ui.finish_import([source(tmp_path/'a.001'),source(tmp_path/'b.001')],[])
    settle();calls=[];original=ui.redraw
    def draw(*args):calls.append(ui.active_document().key);return original(*args)
    monkeypatch.setattr(ui,'redraw',draw)
    for curve in ui.curves*3:
        calls.clear();ui._show_document(curve.dataset.document_key);settle()
        assert calls==[curve.dataset.document_key]
        assert ui.selected() is curve and ui.table.model().curve is curve
        assert ui._plot_artists[0][0] is curve
    target=next(c for c in ui.curves if c is not ui.selected())
    calls.clear();ui.files.setCurrentItem(ui.files.topLevelItem(ui.curves.index(target)));settle()
    assert calls==[target.dataset.document_key] and ui.selected() is target


def test_resize_only_rebuilds_when_current_canvas_dimensions_changed(ui,tmp_path,monkeypatch):
    ui.finish_import([source(tmp_path/'a.001')],[]);settle()
    calls=[];original=ui.redraw
    def draw(*args):calls.append(1);return original(*args)
    monkeypatch.setattr(ui,'redraw',draw)
    ui.canvas_resized(SimpleNamespace(canvas=ui.canvas));settle()
    assert not calls
    ui.resize(ui.width()-160,ui.height()-120);settle(250)
    assert len(calls)==1
    assert ui.active_document().layout_size==ui.canvas.get_width_height(physical=True)


def test_closing_graphs_releases_hidden_navigation_with_their_canvases(ui,tmp_path):
    from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
    from shiboken6 import isValid
    initial=len(ui.findChildren(NavigationToolbar2QT))
    for _ in range(3):
        ui.finish_import([source(tmp_path/'a.001'),source(tmp_path/'b.001')],[])
        controls=[(doc,doc.navigation,doc.canvas) for doc in ui.documents.values()]
        assert len(ui.findChildren(NavigationToolbar2QT))==initial+2
        ui.close_all_documents()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        assert all(not isValid(obj) for group in controls for obj in group)
        assert len(ui.findChildren(NavigationToolbar2QT))==initial


def test_repeated_native_activation_skips_focus_redraw_but_explicit_refresh_works(ui,tmp_path,monkeypatch):
    ui.finish_import([source(tmp_path/'a.001')],[]);settle()
    calls=[];original=ui.redraw
    def draw(*args):calls.append(1);return original(*args)
    monkeypatch.setattr(ui,'redraw',draw);doc=ui.active_document()
    ui.mdi.subWindowActivated.emit(None)
    ui.mdi.subWindowActivated.emit(doc);settle()
    assert not calls
    ui._show_document(doc.key);settle();assert calls==[1]


def test_sort_requests_are_coalesced_and_shutdown_never_waits(ui,tmp_path,monkeypatch):
    from tma_app import async_data_picker as picker
    entered=threading.Event();release=threading.Event();requests=[]
    def blocked(*args):
        requests.append(args);entered.set();release.wait(8)
        picker_prepare(*args)
    picker_prepare=picker.prepare_rows
    monkeypatch.setattr(picker,'prepare_rows',blocked)
    entries=[(f's-{i:04}.001',str(tmp_path/f's-{i:04}.001'),False,i,i) for i in range(2000)]
    monkeypatch.setattr(picker,'scan_directory',lambda directory,cancelled,events:events.put(('rows',entries)))
    dialog=picker.DataFileDialog(ui,'导入',str(tmp_path),'TMA (*.001);;CSV (*.csv)');dialog.show()
    try:
        wait_until(entered.is_set)
        worker=dialog._view_worker;thread=worker.thread
        for _ in range(100):
            dialog.tree.sortByColumn(0,Qt.SortOrder.AscendingOrder)
            dialog.tree.sortByColumn(3,Qt.SortOrder.DescendingOrder)
        assert worker.thread is thread and len(requests)==1
        assert worker.pending[-3]==dialog._view_token and requests[0][-2].is_set()
        release.set();wait_until(lambda:dialog.model.rowCount()==2000)
        assert len(requests)==2 and dialog.model.rows[0][0]=='s-1999.001'
        entered.clear();release.clear();dialog.filters.setCurrentIndex(1);wait_until(entered.is_set)
        dialog.reject();assert worker.closed and not dialog.isVisible()
        # A blocked plain worker may finish later, but owns no Qt objects.
        dialog.deleteLater();QApplication.processEvents()
        release.set();worker.thread.join(2);assert not worker.thread.is_alive()
    finally:release.set();dialog.reject()


def test_sort_failure_is_reported_and_next_request_recovers(ui,tmp_path,monkeypatch):
    from tma_app import async_data_picker as picker
    entries=[('a.001',str(tmp_path/'a.001'),False,1,1)]
    monkeypatch.setattr(picker,'scan_directory',lambda directory,cancelled,events:events.put(('rows',entries)))
    original=picker.prepare_rows
    def fail(*args):raise RuntimeError('fixture sort error')
    monkeypatch.setattr(picker,'prepare_rows',fail)
    dialog=picker.DataFileDialog(ui,'导入',str(tmp_path),'TMA (*.001)');dialog.show()
    try:
        wait_until(lambda:'fixture sort error' in dialog.feedback.text())
        monkeypatch.setattr(picker,'prepare_rows',original);dialog.sort_by_time()
        wait_until(lambda:dialog.model.rowCount()==1)
    finally:dialog.reject()


@pytest.mark.parametrize('section,value',[('ui',[]),('mass_cache',None),('paths',{'m':123})])
def test_bad_form_config_is_reported_without_crashing_or_writing(ui,section,value):
    from tma_app import path_settings as settings,atomic_files
    path=settings.config_path();data={'paths':{'m':''},section:value}
    atomic_files.write_json(path,data);before=path.read_bytes();settings._read_settings()
    dialog=ui.show_path_settings()
    try:
        wait_until(lambda:not dialog._loading)
        assert '设置未能刷新' in dialog.feedback.text()
        assert path.read_bytes()==before and not dialog.saving
    finally:dialog.reject()


def test_unexpected_settings_worker_error_finishes_save_state(ui,monkeypatch):
    from tma_app import path_settings as settings
    settings.save_paths({'m':''});dialog=ui.show_path_settings()
    try:
        wait_until(lambda:not dialog._loading)
        def fail(*args,**kwargs):raise RuntimeError('fixture unexpected save failure')
        monkeypatch.setattr(settings,'save_settings',fail)
        dialog.accept();wait_until(lambda:not dialog.saving)
        assert 'fixture unexpected save failure' in dialog.feedback.text()
        assert dialog.save_button.isEnabled() and dialog.isVisible()
    finally:dialog.reject()
