"""UI size persistence, startup scaling and screen-fit safeguards."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QApplication, QScrollArea

from test_feature_ui import ui
from tma_app import ui_size, path_settings
from tma_app.batch_qa import wait_until


@pytest.fixture
def scale_env(monkeypatch):
    for key in ('QT_SCALE_FACTOR','ZZZHE_TMA_BASE_QT_SCALE','ZZZHE_TMA_UI_SIZE_ACTIVE'):
        monkeypatch.setenv(key,'')
        monkeypatch.delenv(key)


def test_presets_save_preserves_other_settings():
    path_settings.save_paths({'m':'C:/mass.xlsx','open_folder':'C:/samples'})
    path_settings.save_batch_popup(False)
    assert ui_size.saved_size()=='standard'
    ui_size.save_size('extra_large')
    assert ui_size.saved_size()=='extra_large'
    assert path_settings.load_paths()['m']=='C:/mass.xlsx' and not path_settings.batch_popup_enabled()
    with pytest.raises(ValueError):ui_size.save_size('huge')


@pytest.mark.parametrize('key,scale',[('standard',1.),('large',1.25),('extra_large',1.5)])
def test_startup_scale_is_process_local_and_does_not_compound(key,scale,scale_env,monkeypatch):
    monkeypatch.setenv('QT_SCALE_FACTOR','1.25')
    ui_size.save_size(key)
    ui_size.configure_environment();ui_size.configure_environment()
    assert float(os.environ['QT_SCALE_FACTOR'])==pytest.approx(1.25*scale)
    assert ui_size.active_size()==key


def test_settings_selector_and_menu_save_next_startup_choice(ui):
    dialog=ui.show_path_settings()
    assert dialog.ui_size.currentData()=='standard'
    dialog.ui_size.setCurrentIndex(dialog.ui_size.findData('large'));dialog.accept()
    wait_until(lambda: ui_size.saved_size()=='large')
    wait_until(lambda: not ui._ui_size_controller.busy)
    assert ui_size.saved_size()=='large' and ui_size.active_size()=='standard'
    menu=ui.ui_size_menu
    menu.aboutToShow.emit()
    action=next(action for action in menu.actions() if action.data()=='large')
    assert action.isChecked()
    next(action for action in menu.actions() if action.data()=='extra_large').trigger()
    wait_until(lambda: ui_size.saved_size()=='extra_large')
    wait_until(lambda: not ui._ui_size_controller.busy)
    assert ui_size.saved_size()=='extra_large' and '重新打开' in ui.statusBar().currentMessage()


def test_oversized_dialog_wraps_in_scroll_area_and_can_close(ui,monkeypatch):
    monkeypatch.setenv('ZZZHE_TMA_UI_SIZE_ACTIVE','extra_large')
    dialog=QDialog(ui);layout=QVBoxLayout(dialog)
    label=QLabel('oversized');label.setFixedSize(2200,1800);layout.addWidget(label)
    dialog.resize(2300,1900);ui_size.fit_window(dialog)
    scroll=dialog.findChild(QScrollArea,'UiSizeScrollArea')
    assert scroll is not None and dialog.property('tma-size-scroll')
    available=dialog.screen().availableGeometry()
    assert dialog.width()<=available.width() and dialog.height()<=available.height()
    dialog.show();QApplication.processEvents();dialog.close()
    assert not dialog.isVisible()


def test_native_context_coordinates_follow_canvas_pixel_ratio():
    from types import SimpleNamespace
    canvas=SimpleNamespace(device_pixel_ratio=1.5,figure=SimpleNamespace(bbox=SimpleNamespace(height=900)))
    assert ui_size.canvas_point(canvas,QPoint(200,100))==(300,750)


@pytest.mark.parametrize('key,scale',[('standard',1.),('large',1.25),('extra_large',1.5)])
def test_real_qt_subprocess_fonts_icons_geometry_and_images_scale(tmp_path,key,scale):
    profile=tmp_path/key/'ZzzHeTMA';profile.mkdir(parents=True)
    (profile/'settings.json').write_text(json.dumps({'paths':{'m':''},'ui':{'size':key}}),encoding='utf-8')
    output=tmp_path/(key+'.json')
    code="""from tma_app.ui_size import configure_environment
configure_environment()
from PySide6.QtWidgets import QApplication,QPushButton
from PySide6.QtCore import QSize
from tma_app.theme import CUTE_STYLE,app_icon
import json,sys
app=QApplication([]);app.setStyleSheet(CUTE_STYLE)
button=QPushButton('字体测试');button.setIcon(app_icon());button.setIconSize(QSize(24,24));button.setFixedSize(160,40);button.show();app.processEvents()
image=button.grab()
json.dump({'dpr':button.devicePixelRatioF(),'width':image.width(),'height':image.height(),'font_pixels':button.font().pixelSize(),'icon':button.iconSize().width()},open(sys.argv[1],'w'))
"""
    env=os.environ.copy();env['LOCALAPPDATA']=str(profile.parent);env['QT_QPA_PLATFORM']='offscreen'
    for name in ('QT_SCALE_FACTOR','ZZZHE_TMA_BASE_QT_SCALE','ZZZHE_TMA_UI_SIZE_ACTIVE'):env.pop(name,None)
    result=subprocess.run([sys.executable,'-c',code,str(output)],env=env,capture_output=True,timeout=30)
    assert result.returncode==0,result.stderr
    data=json.loads(output.read_text())
    assert data['dpr']==pytest.approx(scale)
    assert data['width']==pytest.approx(160*scale) and data['height']==pytest.approx(40*scale)
    assert data['font_pixels']==12 and data['icon']==24
