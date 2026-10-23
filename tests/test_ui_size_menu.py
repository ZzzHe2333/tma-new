"""Actual menu activation and slow setting writes must not block the GUI."""
import json
import threading
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from test_feature_ui import ui
from tma_app import ui_size, path_settings
from tma_app.batch_qa import wait_until


def click_native_menu(ui,key):
    menu=ui.ui_size_menu
    action=next(a for a in menu.actions() if a.data()==key)
    QTimer.singleShot(40,lambda:QTest.mouseClick(menu,Qt.MouseButton.LeftButton,pos=menu.actionGeometry(action).center()))
    menu.exec(ui.mapToGlobal(ui.rect().center()))


def test_menu_closes_and_heartbeat_continues_during_blocked_save(ui,monkeypatch):
    entered,release=threading.Event(),threading.Event();threads=[]
    original=ui_size.save_size
    def blocked(*args,**kwargs):
        threads.append(threading.get_ident());entered.set();release.wait(10);return original(*args,**kwargs)
    monkeypatch.setattr(ui_size,'save_size',blocked)
    ticks=[];timer=QTimer();timer.timeout.connect(lambda:ticks.append(1));timer.start(5)
    try:
        started=time.monotonic();click_native_menu(ui,'large')
        assert time.monotonic()-started<1 and not ui.ui_size_menu.isVisible()
        wait_until(entered.is_set)
        baseline=len(ticks);wait_until(lambda:len(ticks)>baseline+10)
        assert ui._ui_size_controller.busy and ui_size.active_size()=='standard'
        assert ui_size.saved_size()=='standard'
        assert threads[0]!=threading.get_ident()
    finally:release.set();timer.stop()
    wait_until(lambda:not ui._ui_size_controller.busy)
    assert ui_size.saved_size()=='large' and '已保存' in ui.statusBar().currentMessage()


def test_menu_about_to_show_does_not_read_configuration(ui,monkeypatch):
    def forbidden():raise AssertionError('No configuration I/O in native menu callbacks')
    monkeypatch.setattr(ui_size,'saved_size',forbidden)
    ui.ui_size_menu.aboutToShow.emit()
    controller=ui._ui_size_controller
    assert controller.selected=='standard'


def test_multiple_choices_finish_with_latest_and_preserve_other_configuration(ui,monkeypatch):
    path_settings.save_paths({'m':'C:/mass.xlsx','open_folder':'C:/samples'})
    before=path_settings.config_path().read_bytes()
    entered,release=threading.Event(),threading.Event();original=ui_size.save_size;calls=[]
    def blocked(key,**kwargs):
        calls.append(key)
        if len(calls)==1:entered.set();release.wait(10)
        return original(key,**kwargs)
    monkeypatch.setattr(ui_size,'save_size',blocked)
    controller=ui._ui_size_controller
    ui_size.change_from_menu(ui,'large');wait_until(entered.is_set)
    try:
        ui_size.change_from_menu(ui,'extra_large');ui_size.change_from_menu(ui,'standard')
    finally:release.set()
    wait_until(lambda:not controller.busy and controller.desired is None and not controller.dispatch.isActive())
    assert calls==['large','standard'] and ui_size.saved_size()=='standard'
    assert path_settings.config_path().read_bytes()==before
    assert json.loads(path_settings.config_path().with_name('appearance.json').read_text())['size']=='standard'


def test_save_failure_keeps_old_setting_and_gui_usable(ui,monkeypatch):
    ui_size.save_size('standard')
    def failed(*args,**kwargs):raise PermissionError('fixture write denied')
    monkeypatch.setattr(ui_size,'save_size',failed)
    click_native_menu(ui,'extra_large')
    wait_until(lambda:not ui._ui_size_controller.busy and not ui._ui_size_controller.dispatch.isActive())
    assert ui_size.saved_size()=='standard'
    assert '失败' in ui.statusBar().currentMessage()
    ui.ui_size_menu.aboutToShow.emit()
    assert next(a for a in ui.ui_size_menu.actions() if a.data()=='standard').isChecked()


def test_denied_primary_reports_success_for_portable_save(ui,monkeypatch,tmp_path):
    from tma_app import atomic_files
    primary=ui._ui_size_controller.path;portable=tmp_path/'portable/appearance.json'
    original=atomic_files.write_json
    def denied(path,data):
        if path==primary:raise PermissionError('fixture primary write denied')
        return original(path,data)
    monkeypatch.setattr(atomic_files,'write_json',denied)
    monkeypatch.setattr(ui_size,'fallback_path',lambda path:portable)
    click_native_menu(ui,'extra_large')
    wait_until(lambda:not ui._ui_size_controller.busy and not ui._ui_size_controller.dispatch.isActive())
    assert ui_size.saved_size()=='extra_large'
    assert '已保存' in ui.statusBar().currentMessage() and '程序目录' in ui.statusBar().currentMessage()


def test_stalled_write_has_explicit_notice_and_can_complete_later(ui,monkeypatch):
    entered,release=threading.Event(),threading.Event();original=ui_size.save_size
    def blocked(*args,**kwargs):
        entered.set();release.wait(10);return original(*args,**kwargs)
    monkeypatch.setattr(ui_size,'save_size',blocked)
    controller=ui._ui_size_controller;controller.notice.setInterval(30)
    try:
        click_native_menu(ui,'extra_large');wait_until(entered.is_set)
        wait_until(lambda:'尚未确认保存' in ui.statusBar().currentMessage())
        assert ui_size.saved_size()=='standard' and controller.busy
    finally:release.set()
    wait_until(lambda:not controller.busy)
    assert '已保存' in ui.statusBar().currentMessage() and ui_size.saved_size()=='extra_large'
