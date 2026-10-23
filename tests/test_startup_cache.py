import sys
from pathlib import Path

from tma_app import startup_cache


def frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path/'install/_internal'), raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path/'install/app.exe'))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path/'profile'))
    monkeypatch.setenv('SystemRoot', str(tmp_path/'windows'))
    monkeypatch.setenv('MPLCONFIGDIR', str(tmp_path/'temporary'))


def test_reuses_directory_and_keeps_cache(monkeypatch, tmp_path):
    frozen(monkeypatch, tmp_path)
    first = startup_cache.configure()
    data = first/'fontlist-v390.json'
    data.write_text('{"cached": true}')
    assert startup_cache.configure() == first
    assert data.read_text() == '{"cached": true}'
    assert not list(first.glob('.write-*'))
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path/'new-install/_internal'))
    assert startup_cache.configure() != first


def test_font_directory_change_invalidates_key(monkeypatch, tmp_path):
    frozen(monkeypatch, tmp_path)
    old = startup_cache.cache_key()
    (tmp_path/'profile/Microsoft/Windows/Fonts').mkdir(parents=True)
    assert startup_cache.cache_key() != old


def test_primary_denied_uses_portable_and_profiles_stay_isolated(monkeypatch, tmp_path):
    frozen(monkeypatch, tmp_path)
    original = Path.mkdir
    def mkdir(path, *args, **kwargs):
        if path.is_relative_to(tmp_path/'profile'): raise PermissionError('denied')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'mkdir', mkdir)
    first = startup_cache.configure()
    assert first.is_relative_to(tmp_path/'install/ZzzHeTMA')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path/'profile/second'))
    assert startup_cache.configure() != first


def test_both_locations_denied_leave_temporary_cache(monkeypatch, tmp_path):
    frozen(monkeypatch, tmp_path)
    def denied(*args, **kwargs): raise PermissionError('denied')
    monkeypatch.setattr(Path, 'open', denied)
    assert startup_cache.configure() is None
    import os
    assert os.environ['MPLCONFIGDIR'] == str(tmp_path/'temporary')


def test_source_keeps_existing_matplotlib_configuration(monkeypatch):
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    monkeypatch.setenv('MPLCONFIGDIR', 'unchanged')
    assert startup_cache.configure() is None
    import os
    assert os.environ['MPLCONFIGDIR'] == 'unchanged'
