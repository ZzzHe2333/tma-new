from copy import deepcopy
from datetime import date
import hashlib
import io

from PIL import Image
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton
from shiboken6 import isValid

from test_feature_ui import ui, imported
from tma_app.classic_dialogs import AddCurvesDialog
from tma_app.batch_qa import wait_until
from tma_app import user_account as user


def test_manual_entry_starts_empty_adds_only_chosen_curves_and_can_export_share(ui,tmp_path,monkeypatch):
    imported(ui,tmp_path,3);original=ui.active_document();uids=list(original.curve_uids)
    ui.classic_actions['ManualSetup1'].trigger();dialog=ui.dialogs['overlay_options']
    assert dialog.blank_start and dialog.key!=original.key
    assert not any(c.overlay_enabled for c in dialog.draft)
    dialog.accept();assert dialog.result()!=QDialog.DialogCode.Accepted and '添加曲线' in dialog.error.text()
    assert ui.active_document() is original and original.curve_uids==uids
    def choose(picker):
        assert all(picker.files.item(i).checkState()==Qt.CheckState.Unchecked for i in range(picker.files.count()))
        picker.files.item(0).setCheckState(Qt.CheckState.Checked)
        picker.files.item(2).setCheckState(Qt.CheckState.Checked)
        assert picker.signals.currentItem().text().startswith('Dimension Change')
        picker.accept();return picker.result()
    monkeypatch.setattr(AddCurvesDialog,'exec',choose)
    dialog.add_curves();dialog.accept();assert dialog.result()==QDialog.DialogCode.Accepted,dialog.error.text()
    active=ui.active_document();assert active.key!=original.key and len(ui.visible_curves())==2
    assert original.curve_uids==uids
    path=tmp_path/'selected-overlay.png';ui.write_plot(path)
    with Image.open(path) as image:assert image.width>500 and image.info['Author']=='Power By ZzzHe'
    share=ui.show_share();wait_until(lambda:bool(share.png))
    assert ui.active_document() is active and len(ui.visible_curves())==2
    with Image.open(io.BytesIO(share.png)) as image:assert image.width>500
    share.reject()
    edit=ui.show_overlay_options();assert not edit.blank_start and len(edit.axis_curves())==2;edit.reject()
    ui.classic_actions['ManualSetup1'].trigger();new=ui.dialogs['overlay_options']
    assert not any(c.overlay_enabled for c in new.draft);new.reject()


@pytest.mark.parametrize('name', ['Dimension Change', '尺寸变化', '变化量'])
def test_manual_default_change_signal_allows_override_and_preserves_it(ui,tmp_path,name):
    from tma_app.reader import Signal
    imported(ui,tmp_path,2)
    for curve in ui.curves: curve.dataset.signals[2] = Signal(name, 'µm')
    dialog = ui.show_overlay_options(new=True)
    picker = AddCurvesDialog(dialog, dialog.draft, 0, empty_selection=True)
    assert picker.signals.currentItem() is None
    assert all(picker.files.item(i).checkState()==Qt.CheckState.Unchecked for i in range(picker.files.count()))
    picker.files.item(0).setCheckState(Qt.CheckState.Checked)
    assert picker.signals.currentItem().text()==f'{name} (µm)'
    picker.compatible.setChecked(False)
    picker.signals.setCurrentRow(next(i for i in range(picker.signals.count()) if picker.signals.item(i).text().startswith('Temperature')))
    picker.files.item(1).setCheckState(Qt.CheckState.Checked)
    assert picker.signals.currentItem().text().startswith('Temperature')
    picker.accept()
    assert picker.result()==QDialog.DialogCode.Accepted
    assert len(picker.selected_curves)==2 and all(c.y_index==1 for c in picker.selected_curves)
    dialog.reject()


def test_manual_without_change_signal_requires_manual_choice(ui,tmp_path):
    from tma_app.reader import Signal
    imported(ui,tmp_path,2)
    for curve in ui.curves: curve.dataset.signals[2] = Signal('Force', 'N')
    picker=AddCurvesDialog(ui,ui.curves,0,empty_selection=True)
    picker.files.item(0).setCheckState(Qt.CheckState.Checked)
    assert picker.signals.currentItem() is None
    picker.signals.setCurrentRow(next(i for i in range(picker.signals.count()) if picker.signals.item(i).text()=='Force (N)'))
    picker.accept();assert picker.result()==QDialog.DialogCode.Accepted
    assert picker.selected_curves[0].y_index==2


def test_auto_entry_starts_empty_and_honors_individual_curve_selection(ui,tmp_path):
    imported(ui,tmp_path,3);original=ui.active_document();uids=list(original.curve_uids)
    ui.classic_actions['AutoConfigure1'].trigger();dialog=ui.dialogs['auto_configure']
    assert dialog.blank_start and dialog.key!=original.key
    assert all(item.checkState()==Qt.CheckState.Unchecked for item in dialog.file_items)
    assert not dialog.auto_boxes['file_selection'].isChecked()
    dialog.accept();assert dialog.result()!=QDialog.DialogCode.Accepted
    assert original.curve_uids==uids
    selected=[ui.curves[0].uid,ui.curves[2].uid]
    for uid in selected:dialog.curve_items[uid].setCheckState(Qt.CheckState.Checked)
    dialog.accept();assert dialog.result()==QDialog.DialogCode.Accepted,dialog.error.text()
    assert [c.uid for c in ui.visible_curves()]==selected
    assert original.curve_uids==uids
    ui.classic_actions['AutoConfigure1'].trigger();fresh=ui.dialogs['auto_configure']
    assert all(item.checkState()==Qt.CheckState.Unchecked for item in fresh.file_items);fresh.reject()


def test_cancel_blank_overlay_preserves_source_views_and_current_document(ui,tmp_path):
    imported(ui,tmp_path,2);active=ui.active_document();views=deepcopy([c.overlay_views for c in ui.curves]);options=deepcopy(ui.plot_options)
    for name,key in [('ManualSetup1','overlay_options'),('AutoConfigure1','auto_configure')]:
        ui.classic_actions[name].trigger();ui.dialogs[key].reject()
        assert ui.active_document() is active and [c.overlay_views for c in ui.curves]==views and ui.plot_options==options


@pytest.mark.parametrize('automatic',[False,True])
def test_same_pair_can_be_overlaid_repeatedly_with_independent_windows(ui,tmp_path,monkeypatch,automatic):
    imported(ui,tmp_path,3)
    selected=[ui.curves[0].uid,ui.curves[1].uid]
    def choose(picker):
        for i in (0,1):picker.files.item(i).setCheckState(Qt.CheckState.Checked)
        picker.signals.setCurrentRow(next(i for i in range(picker.signals.count()) if picker.signals.item(i).text().startswith('Dimension Change')))
        picker.accept();return picker.result()
    monkeypatch.setattr(AddCurvesDialog,'exec',choose)
    created=[]
    for index in range(2):
        ui.classic_actions['AutoConfigure1' if automatic else 'ManualSetup1'].trigger()
        dialog=ui.dialogs['auto_configure' if automatic else 'overlay_options']
        if automatic:
            for uid in selected:dialog.curve_items[uid].setCheckState(Qt.CheckState.Checked)
        else:dialog.add_curves()
        dialog.accept();assert dialog.result()==QDialog.DialogCode.Accepted,dialog.error.text()
        document=ui.active_document();created.append(document)
        assert [c.uid for c in ui.visible_curves()]==selected
        next(c for c in ui.curves if c.uid==selected[0]).color='#ff0000' if index==0 else '#0000ff'
        ui.plot_options[document.key]['title']=f'叠图 {index+1}'
    assert created[0].key!=created[1].key and created[0] is not created[1]
    ui._show_document(created[0].key)
    assert next(c for c in ui.visible_curves() if c.uid==selected[0]).color=='#ff0000'
    assert ui.plot_options[created[0].key]['title']=='叠图 1'
    ui._show_document(created[1].key)
    assert next(c for c in ui.visible_curves() if c.uid==selected[0]).color=='#0000ff'
    assert ui.plot_options[created[1].key]['title']=='叠图 2'


def test_toolbar_and_dialog_buttons_explain_their_purpose(ui,tmp_path):
    imported(ui,tmp_path)
    for name in ('ManualSetup1','AutoConfigure1'):
        action=ui.classic_actions[name]
        assert '叠图' in action.text() and '分享' in action.toolTip() and '导出' in action.toolTip()
    for action in ui.classic_toolbar.actions():
        if action.text() and not action.isSeparator():assert len(action.toolTip())>10,(action.text(),action.toolTip())
    ui.classic_actions['ManualSetup1'].trigger();dialog=ui.dialogs['overlay_options'];QApplication.processEvents()
    for button in dialog.findChildren(QPushButton):
        assert button.toolTip(),button.text()
    assert ui.user_badge.isVisible();dialog.reject()


def test_user_login_activation_red_nickname_and_purchase_message(ui,monkeypatch):
    file_menu=next(a.menu() for a in ui.menuBar().actions() if a.text()=='文件')
    assert all(a.text()!='登录' for a in file_menu.actions())
    assert [a.text() for a in ui.user_menu.actions()]==['登录','我的会员','购买会员']
    ui.user_actions['login'].trigger();login=ui._user_dialogs['login']
    login.nickname.setText('测试昵称');login.submit.click()
    assert user.load_account()['nickname']=='测试昵称' and not user.is_member()
    assert 'd62839' not in ui.user_badge.styleSheet();login.reject()
    availability={key:action.isEnabled() for key,action in ui.classic_actions.items() if isValid(action)}
    ui.user_actions['membership'].trigger();member=ui._user_dialogs['membership']
    member.code.setText(hashlib.sha256(date.today().strftime('%Y%m%d').encode()).hexdigest());member.submit.click()
    assert member.state.text()=='永久激活' and 'd62839' in member.nickname_label.styleSheet()
    assert user.is_member() and 'd62839' in ui.user_badge.styleSheet()
    assert availability=={key:action.isEnabled() for key,action in ui.classic_actions.items() if isValid(action)}
    member.reject();messages=[]
    monkeypatch.setattr(QMessageBox,'information',lambda *args:messages.append(args[2]))
    ui.user_actions['purchase'].trigger();assert messages==['请联系销售人员']
    monkeypatch.setattr(user,'machine_code',lambda:'DIFFERENT-MACHINE');ui.refresh_user_badge()
    assert 'd62839' not in ui.user_badge.styleSheet()
