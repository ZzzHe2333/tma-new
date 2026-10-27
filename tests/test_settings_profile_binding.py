"""A fresh process reproduces first import under an earlier path provider."""
from pathlib import Path
import os,subprocess,sys


def test_settings_form_uses_current_provider_after_lazy_import(tmp_path):
    code=r'''
import json,os
from pathlib import Path
from tma_app import path_settings
base=Path(os.environ['LOCALAPPDATA'])
old=base/'earlier/settings.json';current=base/'current/settings.json'
for path in (old,current):path.parent.mkdir(parents=True,exist_ok=True)
old.write_text(json.dumps({'paths':{'m':'older.xlsx'},'ui':{}}),encoding='utf-8')
current.write_text(json.dumps({'paths':{'m':''},'ui':[]}),encoding='utf-8');before=current.read_bytes()
path_settings.config_path=lambda:old
from tma_app.settings_dialog import SettingsDialog
path_settings.config_path=lambda:current
from PySide6.QtWidgets import QApplication
from tma_app.classic import ClassicMainWindow
from tma_app.batch_qa import wait_until
app=QApplication([]);window=ClassicMainWindow();dialog=SettingsDialog(window)
wait_until(lambda:not dialog._loading)
assert '设置未能刷新' in dialog.feedback.text(),dialog.feedback.text()
assert str(current) in dialog.location.text(),dialog.location.text()
assert current.read_bytes()==before
dialog.reject();window.close();app.processEvents()
'''
    env=dict(os.environ,LOCALAPPDATA=str(tmp_path),QT_QPA_PLATFORM='offscreen',TMA_MASS_XLSX='',ZZZHE_TMA_ACCOUNT_REGISTRY='0')
    result=subprocess.run([sys.executable,'-X','utf8','-c',code],cwd=Path(__file__).resolve().parents[1],env=env,
                          capture_output=True,text=True,encoding='utf-8',timeout=45)
    assert result.returncode==0,result.stdout+result.stderr
