"""Find month-specific particle datasets without scanning entire network drives."""
from datetime import datetime
import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

DEFAULT_ROOT = Path("W:/微胶囊/本厂")


def sample_date(sample):
    name = Path(unquote(urlsplit(str(sample)).path)).stem.strip()
    # A complete date/run identifier is required; never infer from today's date.
    match = re.fullmatch(r"(\d{8})(?:-(\d{1,3})#?|(\d{2,3})#?)", name)
    if not match:
        raise ValueError("编号需含完整日期，例如 20261017-5#、20261017-5 或 2026101705")
    try:
        date = datetime.strptime(match[1], "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError("样品编号中的年月日无效") from exc
    return date


def candidate_files(sample, folder="", *, cancelled=None):
    date = sample_date(sample)
    configured = Path(os.path.expandvars(os.path.expanduser(folder))) if folder else DEFAULT_ROOT
    roots = [configured]
    # A saved year/range folder (e.g. 本厂/2020-2028) may sit beside the
    # actual monthly datasets; its parent is an explicitly bounded fallback.
    if configured.suffix.lower() == ".p9m": roots = [configured.parent]
    elif re.fullmatch(r"\d{4}(?:[-–至]\d{4})?年?", configured.name): roots.append(configured.parent)
    roots += [base / year for base in list(roots) for year in (str(date.year), f"{date.year}年")]
    names = list(dict.fromkeys([f"{date.year}年{date.month:02d}月份实验.p9m", f"{date.year}年{date.month}月份实验.p9m",
                               f"{date.year}年{date.month:02d}月实验.p9m", f"{date.year}年{date.month}月实验.p9m"]))
    found, seen = [], set()
    def add(path):
        key = os.path.normcase(str(path.absolute()))
        if key not in seen:
            seen.add(key); found.append(str(path.absolute()))
    # Exact known monthly names first; do not enumerate unrelated months.
    for root in roots:
        if cancelled and cancelled.is_set(): return []
        if not root.is_dir(): continue
        for name in names:
            path = root / name
            if path.is_file(): add(path)
        if found: return found
    pattern = re.compile(rf"^{date.year}年0?{date.month}月(?:份)?.*\.p9m$", re.I)
    for root in roots:
        if cancelled and cancelled.is_set(): return []
        if not root.is_dir(): continue
        with os.scandir(root) as entries:
            for entry in entries:
                if cancelled and cancelled.is_set(): return []
                if pattern.fullmatch(entry.name) and entry.is_file(): add(Path(entry.path))
        if found: return found
    return found


def recommend(sample, folder="", *, cancelled=None, progress=None):
    from .single_report import read_particle
    files = candidate_files(sample, folder, cancelled=cancelled)
    if not files:
        date = sample_date(sample)
        raise ValueError(f"未找到 {date.year}年{date.month:02d}月份实验.p9m。请在设置中核对粒径默认目录，或手动选择文件。")
    candidates, errors = [], []
    for file in files:
        if cancelled and cancelled.is_set(): return None
        if progress: progress("正在匹配粒径数据：" + Path(file).name)
        try:
            data = read_particle(file, sample, require_match=True)
            data["recommended_path"] = str(Path(file).absolute())
            if data.get("matched_indices"): candidates.append(data)
        except Exception as exc:
            errors.append(Path(file).name + "：" + str(exc))
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise ValueError("多个数据集包含该编号，未自动替换；请手动选择：\n" + "\n".join(row["file"] for row in candidates))
    message = "已找到月份数据集，但未匹配到该样品编号；原有粒径选择保持不变。"
    raise ValueError(message + "\n候选文件：" + "、".join(files) + ("\n" + "\n".join(errors) if errors else ""))
