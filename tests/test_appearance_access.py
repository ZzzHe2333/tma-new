"""Restricted Windows EXEs must not spin on denied temporary-file creation."""
import json
import os
from pathlib import Path

import pytest

from tma_app import atomic_files, path_settings, ui_size


def test_access_denied_does_not_retry_or_modify_existing_file(tmp_path, monkeypatch):
    target = tmp_path/'appearance.json'; target.write_text('original')
    calls = []
    def denied(*args, **kwargs):
        calls.append(args[0]); raise PermissionError('restricted executable write denied')
    monkeypatch.setattr(atomic_files.os, 'open', denied)
    with pytest.raises(PermissionError): atomic_files.write_json(target, {'size': 'extra_large'})
    assert len(calls) == 1 and target.read_text() == 'original'


def test_name_collisions_are_bounded(tmp_path, monkeypatch):
    calls = []
    def collision(*args, **kwargs):
        calls.append(args[0]); raise FileExistsError('fixture collision')
    monkeypatch.setattr(atomic_files.os, 'open', collision)
    with pytest.raises(FileExistsError): atomic_files.write_json(tmp_path/'config.json', {})
    assert len(calls) == 4


def test_denied_primary_uses_portable_and_reads_it_on_restart(tmp_path, monkeypatch):
    primary = path_settings.config_path().with_name('appearance.json')
    portable = tmp_path/'portable/ZzzHeTMA/appearance.json'
    monkeypatch.setattr(ui_size, 'fallback_path', lambda path: portable)
    original = atomic_files.write_json
    def denied(path, data):
        if Path(path) == primary: raise PermissionError('fixture primary denied')
        return original(path, data)
    monkeypatch.setattr(atomic_files, 'write_json', denied)
    assert ui_size.save_size('extra_large') == portable
    assert ui_size.saved_size() == 'extra_large'
    assert not primary.exists()
    assert json.loads(portable.read_text())['size'] == 'extra_large'
    monkeypatch.setattr(atomic_files, 'write_json', original)
    for name in ('QT_SCALE_FACTOR', 'ZZZHE_TMA_BASE_QT_SCALE', 'ZZZHE_TMA_UI_SIZE_ACTIVE'):
        monkeypatch.setenv(name, os.environ.get(name, '1' if name != 'ZZZHE_TMA_UI_SIZE_ACTIVE' else 'standard'))
    ui_size.configure_environment()
    assert ui_size.active_size() == 'extra_large'


def test_newest_valid_appearance_wins_after_primary_recovers(tmp_path, monkeypatch):
    primary = path_settings.config_path().with_name('appearance.json')
    portable = tmp_path/'portable/appearance.json'
    monkeypatch.setattr(ui_size, 'fallback_path', lambda path: portable)
    atomic_files.write_json(primary, {'size': 'standard'})
    atomic_files.write_json(portable, {'size': 'extra_large'})
    os.utime(primary, ns=(100,100)); os.utime(portable, ns=(200,200))
    assert ui_size.saved_size() == 'extra_large'
    ui_size.save_size('large')
    assert ui_size.saved_size() == 'large'
    portable.write_text('invalid JSON')
    os.utime(portable, ns=(primary.stat().st_mtime_ns+100,)*2)
    assert ui_size.saved_size() == 'large'


def test_both_locations_denied_keep_previous_value(tmp_path, monkeypatch):
    primary = path_settings.config_path().with_name('appearance.json')
    portable = tmp_path/'portable/appearance.json'
    atomic_files.write_json(primary, {'size': 'standard'})
    monkeypatch.setattr(ui_size, 'fallback_path', lambda path: portable)
    def denied(path, data): raise PermissionError('fixture all locations denied')
    monkeypatch.setattr(atomic_files, 'write_json', denied)
    with pytest.raises(PermissionError): ui_size.save_size('extra_large')
    assert ui_size.saved_size() == 'standard'


def test_frozen_fallback_is_separate_for_each_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_size.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(ui_size.sys, 'executable', str(tmp_path/'App/app.exe'))
    first = ui_size.fallback_path(tmp_path/'user-a/appearance.json')
    assert first == ui_size.fallback_path(tmp_path/'user-a/appearance.json')
    assert first != ui_size.fallback_path(tmp_path/'user-b/appearance.json')
    assert tmp_path/'App/ZzzHeTMA' in first.parents


def test_general_settings_save_reports_denied_creation_once(tmp_path, monkeypatch):
    path_settings.save_paths({'m': 'original.xlsx'})
    before = path_settings.config_path().read_bytes(); calls=[]
    def denied(*args, **kwargs):
        calls.append(args[0]); raise PermissionError('fixture creation denied')
    monkeypatch.setattr(atomic_files.os, 'open', denied)
    with pytest.raises(PermissionError): path_settings.save_paths({'m': 'new.xlsx'})
    assert len(calls) == 1 and path_settings.config_path().read_bytes() == before


def test_replace_failure_preserves_old_file_and_removes_temporary(tmp_path, monkeypatch):
    target=tmp_path/'appearance.json';target.write_text('original')
    def denied(*args):raise PermissionError('fixture replacement denied')
    monkeypatch.setattr(atomic_files.os,'replace',denied)
    with pytest.raises(PermissionError):atomic_files.write_json(target,{'size':'extra_large'})
    assert target.read_text()=='original'
    assert list(tmp_path.iterdir())==[target]


def test_versioned_releases_share_appearance_and_recover_legacy_file(tmp_path,monkeypatch):
    monkeypatch.setattr(ui_size.sys,'frozen',True,raising=False)
    first=tmp_path/'dist-previous/ZzzHe TMA Analysis/app.exe'
    second=tmp_path/'dist-current/ZzzHe TMA Analysis/app.exe'
    primary=path_settings.config_path().with_name('appearance.json')
    monkeypatch.setattr(ui_size.sys,'executable',str(first))
    stable=ui_size.fallback_path(primary)
    legacy=first.parent/'ZzzHeTMA'/stable.parent.name/'appearance.json'
    atomic_files.write_json(legacy,{'size':'extra_large'})
    monkeypatch.setattr(ui_size.sys,'executable',str(second))
    assert ui_size.fallback_path(primary)==stable and ui_size.saved_size()=='extra_large'
    atomic_files.write_json(stable,{'size':'large'})
    assert ui_size.saved_size()=='large'
