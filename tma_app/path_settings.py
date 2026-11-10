"""Named data-source paths kept separately from sessions and raw instruments."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
from copy import deepcopy
import threading
import time

# Snapshots are small local preferences, never instrument/table data. GUI
# readers use these without stat/glob/read calls; disk readers publish updates.
_snapshot_lock = threading.Lock()
_snapshots = {}
_refreshing = set()
_revisions = {}
_refresh_checked = {}
RUNTIME_REFRESH_SECONDS = 30


def _publish(path, data, *, identity=None, expected=None, written=False):
    key = str(config_path() if identity is None else identity)
    with _snapshot_lock:
        if expected is not None and _revisions.get(key,0)!=expected:return
        if written:_revisions[key]=_revisions.get(key,0)+1
        _snapshots[key] = (path, deepcopy(data))
        _refresh_checked[key] = time.monotonic()
        while len(_snapshots) > 16:
            expired = next(iter(_snapshots))
            _snapshots.pop(expired)
            _refresh_checked.pop(expired, None)


def cached_settings():
    """Return an independent in-memory copy, or None; no filesystem access."""
    with _snapshot_lock:
        value = _snapshots.get(str(config_path()))
        return deepcopy(value) if value is not None else None


def cached_mass_source():
    """Return an in-memory source or None without waiting for disk or locks."""
    if 'TMA_MASS_XLSX' in os.environ: return os.environ['TMA_MASS_XLSX'].strip()
    if not _snapshot_lock.acquire(blocking=False): return None
    try:
        snapshot = _snapshots.get(str(config_path()))
        if snapshot is None: return None
        paths = snapshot[1].get('paths')
        if not isinstance(paths, dict): return None
        source = paths.get('m', '')
        return source.strip() if isinstance(source, str) else None
    finally:
        _snapshot_lock.release()


def settings_revision():
    """In-process save revision; a single dictionary read never waits on I/O."""
    key = str(config_path())
    return key, _revisions.get(key, 0), os.environ.get('TMA_MASS_XLSX')


def refresh_in_background(*, min_interval=0):
    key = str(config_path())
    stamp = time.monotonic()
    with _snapshot_lock:
        previous = _refresh_checked.get(key)
        if key in _refreshing or (previous is not None and stamp - previous < min_interval):
            return False
        _refreshing.add(key)
        _refresh_checked[key] = stamp
        while len(_refresh_checked) > 16:
            _refresh_checked.pop(next(iter(_refresh_checked)))
    def work():
        try: _read_settings(primary=Path(key))
        except (OSError, ValueError): pass
        finally:
            with _snapshot_lock: _refreshing.discard(key)
    try:
        threading.Thread(target=work,name='TMA-config-read',daemon=True).start()
    except RuntimeError:
        with _snapshot_lock:
            _refreshing.discard(key)
            if _refresh_checked.get(key) == stamp:
                _refresh_checked.pop(key, None)
        return False
    return True


def runtime_settings_data():
    """Reuse loaded preferences for frequent GUI decisions; refresh off-thread.

    Disk readers and the first read of a cold profile keep their existing fresh
    read behavior. Saves publish immediately. External edits are checked on use
    at most once per interval, even when a previous refresh has failed.
    """
    if threading.current_thread() is threading.main_thread():
        snapshot = cached_settings()
        if snapshot is not None:
            refresh_in_background(min_interval=RUNTIME_REFRESH_SECONDS)
            return snapshot[1]
    return _settings_data()


def config_path():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "ZzzHeTMA" / "settings.json"


def load_paths():
    data = _settings_data()
    paths = data.get("paths") if isinstance(data, dict) else None
    if not isinstance(paths, dict) or any(not isinstance(k, str) or not k.strip() or not isinstance(v, str) for k, v in paths.items()):
        raise ValueError("路径配置文件格式无效")
    return {"m": "", **paths}


def save_paths(paths):
    if not isinstance(paths, dict) or any(not isinstance(k, str) or not k.strip() or not isinstance(v, str) for k, v in paths.items()):
        raise ValueError("路径名称和路径必须为文字")
    value = {"m": "", **paths}
    _update_data(lambda data: data.update(version=1, paths=value))


def _settings_data():
    return _read_settings()[1]


def validate_dialog_settings(data):
    """Reject malformed form sections before handing them to Qt widgets."""
    for name in ('paths', 'ui', 'mass_cache'):
        if not isinstance(data.get(name, {}), dict):
            raise ValueError(f'配置中的 {name} 格式无效，应为对象')
    if any(not isinstance(k,str) or not k.strip() or not isinstance(v,str)
           for k,v in data.get('paths', {}).items()):
        raise ValueError('路径名称和路径必须为文字')


def _read_settings(*, primary=None):
    # Keep config_path() as the logical profile identity: caches, appearance,
    # user activation and scheduled cleanup all derive their own paths from it.
    from .ui_size import fallback_paths
    primary=config_path() if primary is None else Path(primary)
    with _snapshot_lock:revision=_revisions.get(str(primary),0)
    candidates = list(dict.fromkeys([primary, *fallback_paths(primary)]))
    existing, errors = [], []
    for path in candidates:
        try: existing.append((path.stat().st_mtime_ns, path))
        except FileNotFoundError: continue
        except OSError as exc: errors.append(exc)
    for _, path in sorted(existing, key=lambda item: item[0], reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict): raise ValueError("配置文件格式无效")
            _publish(path, data, identity=primary, expected=revision)
            return path, data
        except (OSError, ValueError) as exc: errors.append(exc)
    if errors: raise errors[0]
    data = {"version": 1, "paths": {"m": ""}}
    _publish(None, data, identity=primary, expected=revision)
    return None, data


def _save_data(data):
    """Replace a complete document; section writers should use _update_data."""
    from .config_transaction import settings_transaction
    primary = config_path()
    with settings_transaction(primary):
        return _write_settings(data, primary)


def _update_data(update):
    """Read/modify/write one profile atomically; update only mutates plain data."""
    from .config_transaction import settings_transaction
    primary = config_path()
    with settings_transaction(primary):
        data = _read_settings(primary=primary)[1]
        update(data)
        return _write_settings(data, primary)


def _write_settings(data, primary):
    from .atomic_files import write_json
    from .ui_size import fallback_path
    try:
        write_json(primary, data)
        _publish(primary, data, identity=primary, written=True)
        return primary
    except OSError as exc:
        backup = fallback_path(primary)
        if backup is None or backup == primary: raise
        try: write_json(backup, data)
        except OSError as backup_exc:
            raise OSError(f"配置保存失败。用户目录：{exc}；备用目录：{backup_exc}") from backup_exc
        _publish(backup, data, identity=primary, written=True)
        return backup


def save_settings(paths, *, batch_popup, cache_hours):
    """Save the data-path dialog as one transaction, retaining other sections."""
    if not isinstance(paths, dict) or any(not isinstance(k, str) or not k.strip() or not isinstance(v, str) for k, v in paths.items()):
        raise ValueError("路径名称和路径必须为文字")
    if type(batch_popup) is not bool: raise ValueError("批量窗口设置必须为开或关")
    if type(cache_hours) not in (int, float) or not math.isfinite(cache_hours) or not 1 <= cache_hours <= 720:
        raise ValueError("m 缓存有效期须为 1–720 小时")
    value = {"m": "", **paths}
    def update(data):
        validate_dialog_settings(data)
        data.update(version=1, paths=value)
        data['ui'] = {**data.get('ui', {}), 'batch_popup': batch_popup}
        data['mass_cache'] = {**data.get('mass_cache', {}), 'refresh_hours': float(cache_hours)}
    return _update_data(update)


def batch_popup_enabled():
    try:
        return runtime_settings_data().get("ui", {}).get("batch_popup", True) is not False
    except (OSError, ValueError, AttributeError):
        return True


def save_batch_popup(enabled):
    if type(enabled) is not bool:
        raise ValueError("批量窗口设置必须为开或关")
    def update(data):
        data["ui"] = {**data.get("ui", {}), "batch_popup": enabled}
    _update_data(update)


def ensure_config():
    from .config_transaction import settings_transaction
    primary = config_path()
    with settings_transaction(primary):
        path, data = _read_settings(primary=primary)
        return path if path is not None else _write_settings(data, primary)


def mass_source():
    if "TMA_MASS_XLSX" in os.environ: return os.environ["TMA_MASS_XLSX"]
    return load_paths().get("m", "").strip()


def import_folder():
    """Read each time, so a saved folder applies immediately and after restart."""
    try:
        paths = load_paths()
        value = paths.get("open_folder", paths.get("默认打开文件夹", "")).strip()
        return os.path.expandvars(os.path.expanduser(value)) if value else ""
    except (ValueError, OSError):
        return ""


def particle_folder():
    """Independent start folder for single-report particle file selection."""
    try:
        value = load_paths().get("particle_folder", "").strip()
        return os.path.expandvars(os.path.expanduser(value)) if value else ""
    except (ValueError, OSError):
        return ""


def save_particle_folder(path):
    value = str(path).strip()
    def update(data):
        paths = data.get('paths')
        if not isinstance(paths, dict) or any(not isinstance(k,str) or not k.strip() or not isinstance(v,str) for k,v in paths.items()):
            raise ValueError('路径配置文件格式无效')
        data.update(version=1, paths={"m": "", **paths, "particle_folder": value})
    _update_data(update)
