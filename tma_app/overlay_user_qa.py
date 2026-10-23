"""Frozen-EXE checks for blank overlay setup and local user membership."""
from copy import deepcopy
import hashlib
import io
import json
import traceback

from PIL import Image
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from . import __version__, user_account
from .batch_qa import wait_until
from .reader import read_dataset
from .classic_dialogs import AddCurvesDialog


def verify(window, output, paths, *, restart=False):
    output.parent.mkdir(parents=True, exist_ok=True)
    report={'status':'failed','version':__version__,'checks':[]}
    original_exec=AddCurvesDialog.exec
    original_machine=user_account.machine_code
    try:
        if restart:
            data=user_account.load_account()
            assert data['nickname']=='测试会员' and user_account.is_member(data)
            assert '#d62839' in window.user_badge.styleSheet()
            window.user_actions['membership'].trigger();dialog=window._user_dialogs['membership']
            assert dialog.state.text()=='永久激活'
            QApplication.processEvents();dialog.grab().save(str(output.with_suffix('.member.png')));dialog.reject()
            report['checks'].append('membership_survives_restart_without_reentering_authorization')
        else:
            sources={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
            window.finish_import([read_dataset(path) for path in paths],[])
            assert len(window.curves)>=2
            selected=[window.curves[0].uid,window.curves[1].uid]
            signal=window.curves[0].dataset.signals[window.curves[0].y_index].label
            def picker_exec(picker):
                assert all(picker.files.item(i).checkState()==Qt.CheckState.Unchecked for i in range(picker.files.count()))
                def choose():
                    for i in (0,1):picker.files.item(i).setCheckState(Qt.CheckState.Checked)
                    assert picker.signals.currentItem().text()==signal
                    # Users can still override the default, and adding another
                    # file retains that explicit selection.
                    temperature=next(i for i in range(picker.signals.count()) if picker.signals.item(i).text().startswith('Temperature'))
                    picker.signals.setCurrentRow(temperature)
                    picker.compatible.setChecked(False)
                    assert picker.signals.currentItem().text().startswith('Temperature')
                    picker.signals.setCurrentRow(next(i for i in range(picker.signals.count()) if picker.signals.item(i).text()==signal))
                    picker.accept()
                QTimer.singleShot(100,choose)
                return original_exec(picker)
            AddCurvesDialog.exec=picker_exec
            for automatic in (False,True):
                created=[]
                for index in range(2):
                    window.classic_actions['AutoConfigure1' if automatic else 'ManualSetup1'].trigger()
                    dialog=window.dialogs['auto_configure' if automatic else 'overlay_options']
                    assert dialog.blank_start
                    if automatic:
                        assert all(item.checkState()==Qt.CheckState.Unchecked for item in dialog.file_items)
                        if index==0:dialog.grab().save(str(output.with_suffix('.auto-empty.png')))
                        for uid in selected:dialog.curve_items[uid].setCheckState(Qt.CheckState.Checked)
                    else:
                        assert not any(c.overlay_enabled for c in dialog.draft)
                        if index==0:dialog.grab().save(str(output.with_suffix('.manual-empty.png')))
                        dialog.add_curves()
                    dialog.accept();assert dialog.result()==QDialog.DialogCode.Accepted,dialog.error.text()
                    doc=window.active_document();created.append(doc)
                    assert [c.uid for c in window.visible_curves()]==selected
                    next(c for c in window.visible_curves() if c.uid==selected[0]).color='#ff0000' if index==0 else '#0000ff'
                    window.plot_options[doc.key]['title']=f'{"自动" if automatic else "手动"}叠图 {index+1}'
                assert created[0] is not created[1] and created[0].key!=created[1].key
                window._show_document(created[0].key)
                assert next(c for c in window.visible_curves() if c.uid==selected[0]).color=='#ff0000'
                window._show_document(created[1].key)
                assert next(c for c in window.visible_curves() if c.uid==selected[0]).color=='#0000ff'
            assert len([key for key in window.documents if window._is_overlay(key)])==4
            report['checks'].append('manual_and_auto_start_blank_repeat_same_pair_in_four_independent_windows')
            report['checks'].append('manual_defaults_to_dimension_change_signal_and_allows_manual_override')
            window.write_plot(output.with_suffix('.overlay.png'))
            with Image.open(output.with_suffix('.overlay.png')) as image:assert image.info['Author']=='Power By ZzzHe'
            sharing=window.show_share();wait_until(lambda:bool(sharing.png))
            with Image.open(io.BytesIO(sharing.png)) as image:assert image.width>500
            sharing.grab().save(str(output.with_suffix('.sharing.png')));sharing.reject()
            report['checks'].append('new_overlay_exports_and_generates_share_preview_without_sending')
            assert all('登录'!=a.text() for a in window.classic_menus['File1'].actions())
            window.user_actions['login'].trigger();login=window._user_dialogs['login']
            login.nickname.setText('测试会员');login.submit.click();login.reject()
            window.user_actions['membership'].trigger();member=window._user_dialogs['membership']
            member.code.setText(user_account.authorization_code());member.submit.click()
            assert member.state.text()=='永久激活' and '#d62839' in window.user_badge.styleSheet()
            QApplication.processEvents();member.grab().save(str(output.with_suffix('.member.png')));member.reject()
            assert window.user_badge.isVisible()
            window.grab().save(str(output.with_suffix('.main.png')))
            report['registry_mirrored']=bool(user_account.read_registry())
            report['registry_key']=user_account.registry_key()
            user_account.machine_code=lambda:'OTHER-MACHINE';window.refresh_user_badge()
            assert not user_account.is_member() and '#d62839' not in window.user_badge.styleSheet()
            user_account.machine_code=original_machine;window.refresh_user_badge()
            assert user_account.is_member()
            messages=[]
            def close_purchase():
                dialog=QApplication.activeModalWidget()
                if isinstance(dialog,QMessageBox):messages.append(dialog.text());dialog.accept()
            QTimer.singleShot(100,close_purchase);window.user_actions['purchase'].trigger()
            assert messages==['请联系销售人员']
            report['checks'].append('user_menu_login_permanent_activation_red_nickname_machine_binding_purchase_prompt')
            assert sources=={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        report['status']='passed'
    except Exception:report['error']=traceback.format_exc()
    finally:
        AddCurvesDialog.exec=original_exec;user_account.machine_code=original_machine
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        window.dirty=False;window.close()
    if report['status']!='passed':raise SystemExit(1)
