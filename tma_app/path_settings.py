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
    path = config_path(); path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "paths": {"m": "", **paths}}, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists(): Path(temporary).unlink()


def ensure_config():
    if not config_path().exists(): save_paths({"m": ""})
    return config_path()


def mass_source():
    if "TMA_MASS_XLSX" in os.environ: return os.environ["TMA_MASS_XLSX"]
    return load_paths().get("m", "").strip()
