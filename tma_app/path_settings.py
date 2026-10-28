"""Named data-source paths kept separately from sessions and raw instruments."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
from copy import deepcopy
import threading

# Snapshots are small local preferences, never instrument/table data. GUI
# readers use these without stat/glob/read calls; disk readers publish updates.
_snapshot_lock = threading.Lock()
_snapshots = {}
_refreshing = set()
_revisions = {}


def _publish(path, data, *, identity=None, expected=None, written=False):
    key = str(config_path() if identity is None else identity)
    with _snapshot_lock:
        if expected is not None and _revisions.get(key,0)!=expected:return
        if written:_revisions[key]=_revisions.get(key,0)+1
        _snapshots[key] = (path, deepcopy(data))
        while len(_snapshots) > 16: _snapshots.pop(next(iter(_snapshots)))


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


def refresh_in_background():
    key = str(config_path())
    with _snapshot_lock:
        if key in _refreshing: return
        _refreshing.add(key)
    def work():
        try: _read_settings(primary=Path(key))
        except (OSError, ValueError): pass
        finally:
            with _snapshot_lock: _refreshing.discard(key)
    threading.Thread(target=work,name='TMA-config-read',daemon=True).start()


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
    data = _settings_data()
    data.update(version=1, paths={"m": "", **paths})
    _save_data(data)


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
    from .atomic_files import write_json
    from .ui_size import fallback_path
    primary = config_path()
    try:
        write_json(primary, data)
        _publish(primary, data, written=True)
        return primary
    except OSError as exc:
        backup = fallback_path(primary)
        if backup is None or backup == primary: raise
        try: write_json(backup, data)
        except OSError as backup_exc:
            raise OSError(f"配置保存失败。用户目录：{exc}；备用目录：{backup_exc}") from backup_exc
        _publish(backup, data, written=True)
        return backup


def save_settings(paths, *, batch_popup, cache_hours):
    """Save the data-path dialog as one transaction, retaining other sections."""
    if not isinstance(paths, dict) or any(not isinstance(k, str) or not k.strip() or not isinstance(v, str) for k, v in paths.items()):
        raise ValueError("路径名称和路径必须为文字")
    if type(batch_popup) is not bool: raise ValueError("批量窗口设置必须为开或关")
    if type(cache_hours) not in (int, float) or not math.isfinite(cache_hours) or not 1 <= cache_hours <= 720:
        raise ValueError("m 缓存有效期须为 1–720 小时")
    data = _settings_data()
    validate_dialog_settings(data)
    data.update(version=1, paths={"m": "", **paths})
    data['ui'] = {**data.get('ui', {}), 'batch_popup': batch_popup}
    data['mass_cache'] = {**data.get('mass_cache', {}), 'refresh_hours': float(cache_hours)}
    return _save_data(data)


def batch_popup_enabled():
    try:
        return _settings_data().get("ui", {}).get("batch_popup", True) is not False
    except (OSError, ValueError, AttributeError):
        return True


def save_batch_popup(enabled):
    if type(enabled) is not bool:
        raise ValueError("批量窗口设置必须为开或关")
    data = _settings_data()
    data["ui"] = {**data.get("ui", {}), "batch_popup": enabled}
    _save_data(data)


def ensure_config():
    path, data = _read_settings()
    return path if path is not None else _save_data(data)


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
    paths = load_paths()
    save_paths({**paths, "particle_folder": str(path).strip()})
