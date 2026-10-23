"""General preferences survive restricted EXEs and version-folder updates."""
import json
import os
from pathlib import Path

import pytest

from test_point_interaction import ui
from tma_app import atomic_files, path_settings as settings, ui_size


@pytest.fixture
def storage(tmp_path, monkeypatch):
    primary = settings.config_path()
    backup = tmp_path/'portable/settings.json'
    monkeypatch.setattr(ui_size, 'fallback_path', lambda path: backup)
    return primary, backup


def deny_primary(monkeypatch, primary):
    original = atomic_files.write_json
    calls = []
    def write(path, data):
        calls.append(Path(path))
        if Path(path) == primary: raise PermissionError('fixture restricted EXE')
        original(path, data)
    monkeypatch.setattr(atomic_files, 'write_json', write)
    return calls


def test_denied_save_preserves_all_sections_and_reads_backup(storage, monkeypatch):
    primary, backup = storage
    original = {'paths': {'m': 'mass.xlsx'}, 'ui': {'other': 12}, 'mass_cache': {'other': 7},
                'sharing': {'encrypted_token': 'fixture'}, 'mcp': {'enabled': False}, 'cloud': {'mounts': []}}
    atomic_files.write_json(primary, original)
    before = primary.read_bytes()
    calls = deny_primary(monkeypatch, primary)
    saved = settings.save_settings({'m': 'mass.xlsx', 'open_folder': '//server/current'}, batch_popup=False, cache_hours=48)
    assert saved == backup and calls == [primary, backup]
    assert primary.read_bytes() == before
    assert settings.ensure_config() == backup
    assert settings.import_folder() == '//server/current'
    assert not settings.batch_popup_enabled()
    data = settings._settings_data()
    assert data['mass_cache'] == {'other': 7, 'refresh_hours': 48.}
    assert data['ui'] == {'other': 12, 'batch_popup': False}
    for name in ('sharing', 'mcp', 'cloud'): assert data[name] == original[name]
    # Subsequent independent writers must merge the backup, not stale primary.
    settings.save_batch_popup(True)
    settings.save_particle_folder('W:/particle')
    assert settings.import_folder() == '//server/current' and settings.particle_folder() == 'W:/particle'


def test_dialog_saves_once_and_restart_file_picker_uses_backup(ui, storage, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QDialog
    from tma_app.classic import ClassicMainWindow
    primary, backup = storage
    settings.save_paths({'m': ''})
    calls = deny_primary(monkeypatch, primary)
    def unexpected(*args, **kwargs): pytest.fail('Folder-only save must not read m')
    monkeypatch.setattr(ui, 'refresh_mass_lookup', unexpected)
    dialog = ui.show_path_settings()
    dialog.paths.item(1, 1).setText('//server/ta/Data/TMA/实验室样品/2026')
    dialog.batch_popup.setChecked(False); dialog.cache_hours.setValue(72)
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted and calls == [primary, backup]
    assert str(backup) in ui.statusBar().currentMessage()
    dialog = ui.show_path_settings()
    assert str(backup) in dialog.location.text()
    assert not dialog.batch_popup.isChecked() and dialog.cache_hours.value() == 72
    dialog.reject()
    folders = []
    def choose(owner, title, folder, *args): folders.append(folder); return [], ''
    monkeypatch.setattr(QFileDialog, 'getOpenFileNames', choose)
    restarted = ClassicMainWindow()
    try: restarted.open_files()
    finally: restarted.dirty = False; restarted.close()
    assert folders == ['//server/ta/Data/TMA/实验室样品/2026']


def test_all_locations_denied_keep_old_settings_and_dialog_open(ui, storage, monkeypatch):
    from PySide6.QtWidgets import QDialog
    primary, backup = storage
    settings.save_paths({'m': '', 'open_folder': 'original'})
    before = primary.read_bytes()
    def denied(*args): raise PermissionError('fixture all locations denied')
    monkeypatch.setattr(atomic_files, 'write_json', denied)
    dialog = ui.show_path_settings(); dialog.paths.item(1, 1).setText('changed'); dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted and dialog.isVisible()
    assert '配置保存失败' in dialog.feedback.text()
    assert primary.read_bytes() == before and not backup.exists()
    assert settings.import_folder() == 'original'
    dialog.reject()


def test_newest_valid_copy_and_primary_recovery(storage):
    primary, backup = storage
    atomic_files.write_json(primary, {'paths': {'m': '', 'open_folder': 'old'}})
    atomic_files.write_json(backup, {'paths': {'m': '', 'open_folder': 'new'}})
    os.utime(primary, ns=(100, 100)); os.utime(backup, ns=(200, 200))
    assert settings.import_folder() == 'new'
    settings.save_paths({'m': '', 'open_folder': 'recovered'})
    assert settings.ensure_config() == primary and settings.import_folder() == 'recovered'
    backup.write_text('broken JSON'); os.utime(backup, ns=(primary.stat().st_mtime_ns+1,)*2)
    assert settings.import_folder() == 'recovered'
    primary.write_text('[]')
    with pytest.raises(ValueError): settings.save_paths({'m': ''})


def test_new_profile_creation_and_validation(storage, monkeypatch):
    primary, backup = storage
    deny_primary(monkeypatch, primary)
    assert settings.ensure_config() == backup and settings.load_paths() == {'m': ''}
    before = backup.read_bytes()
    with pytest.raises(ValueError): settings.save_settings({'m': ''}, batch_popup=False, cache_hours=0)
    assert backup.read_bytes() == before


def test_version_folder_update_keeps_default_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_size.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(ui_size.sys, 'executable', str(tmp_path/'dist-before/ZzzHe TMA Analysis/app.exe'))
    primary = settings.config_path()
    deny_primary(monkeypatch, primary)
    settings.save_paths({'m': 'mass.xlsx', 'open_folder': 'saved-directory'})
    saved = settings.ensure_config()
    monkeypatch.setattr(ui_size.sys, 'executable', str(tmp_path/'dist-after/ZzzHe TMA Analysis/app.exe'))
    assert settings.config_path() == primary and settings.ensure_config() == saved
    assert settings.import_folder() == 'saved-directory'
