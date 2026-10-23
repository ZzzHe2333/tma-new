"""Named data-source paths kept separately from sessions and raw instruments."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path


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


def _read_settings():
    # Keep config_path() as the logical profile identity: caches, appearance,
    # user activation and scheduled cleanup all derive their own paths from it.
    from .ui_size import fallback_paths
    candidates = list(dict.fromkeys([config_path(), *fallback_paths(config_path())]))
    existing, errors = [], []
    for path in candidates:
        try: existing.append((path.stat().st_mtime_ns, path))
        except FileNotFoundError: continue
        except OSError as exc: errors.append(exc)
    for _, path in sorted(existing, key=lambda item: item[0], reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict): raise ValueError("配置文件格式无效")
            return path, data
        except (OSError, ValueError) as exc: errors.append(exc)
    if errors: raise errors[0]
    return None, {"version": 1, "paths": {"m": ""}}


def _save_data(data):
    from .atomic_files import write_json
    from .ui_size import fallback_path
    primary = config_path()
    try:
        write_json(primary, data)
        return primary
    except OSError as exc:
        backup = fallback_path(primary)
        if backup is None or backup == primary: raise
        try: write_json(backup, data)
        except OSError as backup_exc:
            raise OSError(f"配置保存失败。用户目录：{exc}；备用目录：{backup_exc}") from backup_exc
        return backup


def save_settings(paths, *, batch_popup, cache_hours):
    """Save the data-path dialog as one transaction, retaining other sections."""
    if not isinstance(paths, dict) or any(not isinstance(k, str) or not k.strip() or not isinstance(v, str) for k, v in paths.items()):
        raise ValueError("路径名称和路径必须为文字")
    if type(batch_popup) is not bool: raise ValueError("批量窗口设置必须为开或关")
    if type(cache_hours) not in (int, float) or not math.isfinite(cache_hours) or not 1 <= cache_hours <= 720:
        raise ValueError("m 缓存有效期须为 1–720 小时")
    data = _settings_data()
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
