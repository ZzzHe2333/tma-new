"""Frozen save/restart check; caller supplies an isolated Windows profile."""
from pathlib import Path
import json
import time
import traceback

from PySide6.QtWidgets import QApplication, QFileDialog, QDialog

from . import __version__, path_settings as settings
from . import data_file_dialog as picker_module
from .batch_qa import wait_until

FOLDER = '//192.168.0.105/ta/Data/TMA/实验室样品/2026'


def verify(window, output, *, restart=False):
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'failed', 'version': __version__, 'restart': restart}
    primary = settings.config_path()
    before = primary.read_bytes()
    original_picker = picker_module.get_data_files
    try:
        dialog = window.show_path_settings(); QApplication.processEvents()
        if not restart:
            dialog.paths.item(1, 1).setText(FOLDER)
            dialog.batch_popup.setChecked(False); dialog.cache_hours.setValue(48)
            started = time.monotonic(); dialog.accept()
            report['save_seconds'] = time.monotonic()-started
            wait_until(lambda:not dialog.saving)
            assert dialog.result() == QDialog.DialogCode.Accepted, dialog.feedback.text()
            assert report['save_seconds'] < 2
            dialog = window.show_path_settings(); QApplication.processEvents()
        assert dialog.paths.item(1, 1).text() == FOLDER
        assert not dialog.batch_popup.isChecked() and dialog.cache_hours.value() == 48
        saved = settings.ensure_config()
        assert saved != primary and str(saved) in dialog.location.text()
        assert primary.read_bytes() == before
        assert settings._settings_data()['sharing'] == {'fixture': 'preserved'}
        dialog.grab().save(str(output.with_suffix('.png'))); dialog.reject()
        folders = []
        def picker(parent,*args,owner=None,**kwargs):folders.append(picker_module.start_folder(owner or parent));return [],''
        picker_module.get_data_files = picker
        window.open_files()
        assert folders == [FOLDER], folders
        report.update(status='passed', primary_unchanged=True, fallback=str(saved),
                      saved_folder=FOLDER, import_picker_uses_saved_folder=True)
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        picker_module.get_data_files = original_picker
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        window.dirty = False; window.close()
    if report['status'] != 'passed': raise SystemExit(1)
