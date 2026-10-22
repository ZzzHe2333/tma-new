"""Named data-source paths kept separately from sessions and raw instruments."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile


def config_path():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "ZzzHeTMA" / "settings.json"


def load_paths():
    path = config_path()
    if not path.exists(): return {"m": ""}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
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
    path = config_path()
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {"version": 1, "paths": {"m": ""}}


def _save_data(data):
    path = config_path(); path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists(): Path(temporary).unlink()


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
    if not config_path().exists(): save_paths({"m": ""})
    return config_path()


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
