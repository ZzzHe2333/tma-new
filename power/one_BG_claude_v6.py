# -*- coding: utf-8 -*-
"""
one_BG_claude_v6.py
单次出报告神器 v8
════════════════════════════════════════════════════════
v4 全量功能 + 修复启动崩溃 Bug：
  · [BUG FIX] _TechButton.__init__ 中 self._draw() 改为
    self.after_idle(self._draw)，解决 Tcl 报
    "invalid command name '52'" 的问题。
    原因：super().__init__() 之后 Python Canvas 对象已创建，
    但 Tcl/Tk 内部尚未将 widget 注册为有效命令，此时同步调用
    self.delete("all") 会使用尚不存在的 Tcl 命令名导致崩溃。
    after_idle() 将绘制推迟到事件循环空闲后执行，widget 已
    完整注册，问题彻底消除。
  · 所有 v4 算法逻辑（v219 TMA / D50 OCR / M xlsx）完全保留。
════════════════════════════════════════════════════════
依赖：tkinter / numpy / matplotlib / PyMuPDF(fitz) / Pillow
      openpyxl（M 查询） / cv2 + pytesseract（D50 OCR，可选）
      reportlab（简版 COA，可选）
"""

VERSION = "v8"

# ── 标准库 ──────────────────────────────────────────────────────────
import os
import re
import json
import math
import struct
import logging
import datetime
import secrets
import string
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import shutil

# ── Tk ──────────────────────────────────────────────────────────────
import tkinter as tk
from tkinter import ttk, filedialog
from tkinter.scrolledtext import ScrolledText

# ── 科学计算 ────────────────────────────────────────────────────────
import numpy as np

# ── PDF / 图像 ──────────────────────────────────────────────────────
import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont, ImageTk

# ── 绘图 ────────────────────────────────────────────────────────────
import matplotlib
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.ticker import MultipleLocator, NullFormatter, FixedLocator

matplotlib.rcParams["font.family"] = "sans-serif"
matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei", "SimHei", "SimSun", "Arial Unicode MS", "DejaVu Sans"
]
matplotlib.rcParams["axes.unicode_minus"] = False

# ── OCR 依赖（可选）────────────────────────────────────────────────
try:
    import cv2 as _cv2
    import pytesseract as _tess
    # Windows 默认安装路径；若已加入 PATH 可注释此行
    _tess.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    _HAS_OCR = True
except ImportError:
    _HAS_OCR = False


# ══════════════════════════════════════════════════════════════════════
# §1  全局常量
# ══════════════════════════════════════════════════════════════════════

START_TEMP_FOR_T1   = 60.0    # T1 搜索起始温度（℃）
FALLBACK_TEMP_MIN   = 40.0    # 无 StartOfData 时的温度过滤下限
FALLBACK_TEMP_MAX   = 400.0   # 无 StartOfData 时的温度过滤上限
MONOTONIC_FIX_T1_T2 = True   # 是否在 [T1,T2] 区间强制高度单调不下降
MONOTONIC_METHOD    = "bridge"
FLOAT_FIND_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")

# ── 网络路径：IP 主线路，原主机名保留为备用线路 ──────────────────────
WEIGHT_XLSX_DEFAULT  = r"\\192.168.0.105\SanMingShuJuHuiZong\TMA称量数据.xlsx"
WEIGHT_XLSX_FALLBACK = r"\\WIN-EK6CSI67PON\SanMingShuJuHuiZong\TMA称量数据.xlsx"
OUTPUT_DIR_DEFAULT   = r"\\192.168.0.105\coa"
OUTPUT_DIR_FALLBACK  = r"\\Win-ek6csi67pon\coa"

# ── 粒径图 OCR 坐标（来自 lijing_pdf_png_ocr.py）─────────────────────
# 基准分辨率 1413 × 2000（运行时按实际图片尺寸等比缩放）
_LJ_BASE_W, _LJ_BASE_H = 1413, 2000
_LJ_VALUE_REGIONS: Dict[str, Tuple[int, int, int, int]] = {
    "D50":  (568, 565, 842, 635),
    "Span": (842, 640, 1090, 720),
}


# ══════════════════════════════════════════════════════════════════════
# §2  小工具
# ══════════════════════════════════════════════════════════════════════

def _rand_suffix4() -> str:
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))


def normalize_path_separators(p: str) -> str:
    """统一路径分隔符并清理控制字符。"""
    if p is None:
        return ""
    p = str(p)
    if not p:
        return p
    p = re.sub(r"[\r\n\t\v\f\u2028\u2029]", "", p)
    p = "".join(ch for ch in p if (ord(ch) >= 32 and ord(ch) != 127))
    if not p:
        return p
    if p.startswith("//") or (p.count("/") >= p.count("\\")):
        return p.replace("\\", "/")
    return p.replace("/", "\\")


def _default_tmaname_from_path(path: str) -> str:
    """从 TMA 文件路径提取默认的 PDF tmaname。"""
    path = normalize_path_separators((path or "").strip())
    if not path:
        return ""
    return os.path.splitext(os.path.basename(path))[0].strip()


def _first_available_path(paths: List[str], *, file_only: bool = False) -> str:
    """按顺序选取首个可用路径；均不可用时仍返回第一条主线路。"""
    first = ""
    seen = set()
    checker = os.path.isfile if file_only else os.path.isdir
    for raw_path in paths:
        path = normalize_path_separators((raw_path or "").strip())
        if not path:
            continue
        if not first:
            first = path
        key = os.path.normcase(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            if checker(path):
                return path
        except OSError:
            continue
    return first


def format_height_um(v: float) -> str:
    try:
        if v is None:
            return "NA"
        v = float(v)
        if not math.isfinite(v):
            return "NA"
        if abs(v) > 1000.0:
            return f"{v:.0f}"
        return f"{v:.1f}"
    except Exception:
        return "NA"


def format_plot_temp_c(v: float) -> str:
    try:
        if v is None:
            return "NA"
        v = float(v)
        if not math.isfinite(v):
            return "NA"
        return f"{v:.2f}"
    except Exception:
        return "NA"


# ══════════════════════════════════════════════════════════════════════
# §3  TAJM 二进制解密
# ══════════════════════════════════════════════════════════════════════

def _tajm_find_header_end(buf: bytes, log=None) -> int:
    crlf = b"\r\x00\n\x00"
    scan_limit = min(len(buf), 65536)
    last_good = None
    pos = 0
    while True:
        p = buf.find(crlf, pos, scan_limit)
        if p == -1:
            break
        candidate = p + len(crlf)
        window = buf[candidate:candidate + 512]
        if len(window) < 64:
            break
        odd = window[1::2]
        zero_ratio = odd.count(0) / max(1, len(odd))
        if zero_ratio >= 0.55:
            last_good = candidate
            pos = candidate
        else:
            break
    if last_good is None:
        raise RuntimeError("TAJM: 未能定位 UTF-16LE 头部结束位置。")
    return last_good


def _tajm_find_data_start_by_first_time(buf: bytes, search_from: int, log=None) -> int:
    needle = struct.pack("<f", 0.004)
    p = buf.find(needle, search_from)
    if p != -1:
        return p
    scan_to = min(len(buf) - 40, search_from + 4096)
    for start in range(search_from, scan_to):
        try:
            t, temp, dim, force, flow = struct.unpack_from("<5f", buf, start)
        except struct.error:
            break
        if not all(map(math.isfinite, [t, temp, dim, force, flow])):
            continue
        if not (0 <= t <= 1e6 and -500 <= temp <= 2000 and -1e7 <= dim <= 1e7 and
                -1e6 <= force <= 1e6 and -1e6 <= flow <= 1e6):
            continue
        try:
            t2 = struct.unpack_from("<f", buf, start + 20)[0]
        except struct.error:
            continue
        if math.isfinite(t2) and t2 >= t:
            return start
    raise RuntimeError("TAJM: 未能定位数据区起点（float32 表）。")


def _tajm_parse_rows(buf: bytes, start: int, log=None, max_rows: int = 200000):
    rows = []
    pos = start
    prev_t = -1e18
    while pos + 20 <= len(buf) and len(rows) < max_rows:
        t, temp, dim, force, flow = struct.unpack_from("<5f", buf, pos)
        if not all(map(math.isfinite, [t, temp, dim, force, flow])):
            break
        if not (0 <= t <= 1e6 and -500 <= temp <= 2000 and -1e7 <= dim <= 1e7 and
                -1e6 <= force <= 1e6 and -1e6 <= flow <= 1e6):
            break
        if t < prev_t - 1e-3:
            break
        prev_t = t
        rows.append((t, temp, dim, force, flow))
        pos += 20
    return rows


def try_tajm_decrypt_to_text(in_path: str, log=None) -> dict:
    r = {"ok": False, "input": in_path}
    try:
        if not os.path.isfile(in_path):
            raise FileNotFoundError(f"找不到文件：{in_path}")
        with open(in_path, "rb") as f:
            buf = f.read()
        if len(buf) < 64:
            raise RuntimeError("文件太小，疑似不是 TAJM 可解密格式。")
        header_end = _tajm_find_header_end(buf, log=log)
        header_text = buf[:header_end].decode("utf-16le", errors="ignore")
        data_start = _tajm_find_data_start_by_first_time(buf, header_end, log=log)
        rows = _tajm_parse_rows(buf, data_start, log=log)
        if not rows:
            raise RuntimeError("TAJM: 未解析到任何数据记录。")
        if not header_text.endswith("\r\n"):
            header_text += "\r\n"
        out_lines = [header_text.rstrip("\r\n"), "StartOfData"]
        for t, temp, dim, force, flow in rows:
            out_lines.append(f"{t:.6f}\t{temp:.5f}\t{dim:.6f}\t{force:.8f}\t{flow:.5f}")
        out_text = "\r\n".join(out_lines) + "\r\n"
        r.update({"ok": True, "text": out_text, "rows": len(rows),
                  "header_end": header_end, "data_start": data_start})
        return r
    except Exception as e:
        r["err"] = str(e)
        return r


# ══════════════════════════════════════════════════════════════════════
# §4  文本读取（v219 probe-based）
# ══════════════════════════════════════════════════════════════════════

def read_text_auto(path: str, logger=None) -> str:
    with open(path, "rb") as f:
        data = f.read()
    if not data:
        return ""

    def _strip_bom(s: str) -> str:
        bom = chr(65279)
        return s[len(bom):] if s.startswith(bom) else s

    if data.startswith(b"\xef\xbb\xbf"):
        try:
            return _strip_bom(data.decode("utf-8-sig", errors="strict"))
        except Exception:
            pass
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        try:
            return _strip_bom(data.decode("utf-16", errors="strict"))
        except Exception:
            pass
    sample = data[:4096]
    if len(sample) >= 4 and (sample.count(0) / len(sample)) > 0.15:
        even = sample[0::2]
        odd  = sample[1::2]
        even_zero = even.count(0) / max(1, len(even))
        odd_zero  = odd.count(0)  / max(1, len(odd))
        if max(even_zero, odd_zero) >= 0.55:
            enc_guess = "utf-16le" if odd_zero >= even_zero else "utf-16be"
            try:
                return _strip_bom(data.decode(enc_guess, errors="strict"))
            except Exception:
                pass
    for enc in ("utf-8", "gbk"):
        try:
            return _strip_bom(data.decode(enc, errors="strict"))
        except Exception:
            pass
    raise UnicodeDecodeError("unknown", b"", 0, 1, "无法识别文件编码")


def load_text_prefer_tajm(in_path: str, logger=None) -> Tuple[str, dict]:
    probe_meta: Dict[str, Any] = {"ok": False}
    try:
        with open(in_path, "rb") as f:
            head = f.read(512 * 1024)
    except Exception as e:
        head = b""
        probe_meta = {"ok": False, "err": f"head_read_failed: {e}"}

    if head:
        float_re = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")

        def _count_data_lines(text: str, max_scan: int = 300) -> int:
            if not text or "StartOfData" not in text:
                return 0
            lines = text.splitlines()
            marker_idx = None
            for i, line in enumerate(lines):
                if "startofdata" in (line or "").lower():
                    marker_idx = i
                    break
            if marker_idx is None:
                return 0
            good = 0
            started = False
            for line in lines[marker_idx + 1: marker_idx + 1 + max_scan]:
                nums = [m.group(0) for m in float_re.finditer(line)]
                if len(nums) >= 3:
                    try:
                        t = float(nums[1])
                        h = float(nums[2])
                    except Exception:
                        continue
                    if math.isfinite(t) and math.isfinite(h) and (-500.0 <= t <= 2000.0):
                        good += 1
                        started = True
                        continue
                if started:
                    break
            return good

        attempts = []
        try:
            if head.startswith(b"\xff\xfe") or head.startswith(b"\xfe\xff"):
                attempts.append(("utf-16(BOM)", head.decode("utf-16", errors="ignore")))
        except Exception:
            pass
        for enc in ("utf-16le", "utf-16be", "utf-8", "gbk"):
            try:
                attempts.append((enc, head.decode(enc, errors="ignore")))
            except Exception:
                continue

        best = {"enc": None, "data_lines": 0}
        for enc, s in attempts:
            n = _count_data_lines(s)
            if n > best["data_lines"]:
                best = {"enc": enc, "data_lines": n}

        if best["data_lines"] >= 5:
            probe_meta = {"ok": True, "enc": best["enc"],
                          "data_lines": int(best["data_lines"]), "reason": "plain_text_probe"}

    if probe_meta.get("ok"):
        try:
            text = read_text_auto(in_path, logger)
            return text, {"used": "plain", **probe_meta}
        except Exception:
            pass

    r = try_tajm_decrypt_to_text(in_path, log=(logger.debug if logger else None))
    if r.get("ok"):
        return r["text"], {"used": "tajm", **r}

    text = read_text_auto(in_path, logger)
    return text, {"used": "plain", "reason": "fallback_after_tajm_failed",
                  "tajm_err": r.get("err")}


# ══════════════════════════════════════════════════════════════════════
# §5  数据解析（v219）
# ══════════════════════════════════════════════════════════════════════

@dataclass
class ParsedLine:
    raw:   str
    nums:  List[float]
    spans: List[Tuple[int, int]]


def parse_lines(text: str) -> List[ParsedLine]:
    out = []
    for line in text.splitlines(keepends=True):
        spans = []
        nums  = []
        for m in FLOAT_FIND_RE.finditer(line):
            spans.append((m.start(), m.end()))
            try:
                nums.append(float(m.group()))
            except ValueError:
                nums.append(math.nan)
        out.append(ParsedLine(raw=line, nums=nums, spans=spans))
    return out


def extract_xy_from_file(
    parsed: List[ParsedLine],
    logger=None,
) -> Tuple[List[float], List[float], List[int]]:
    non_e_letter_re = re.compile(r"[A-DF-Za-df-z]")

    def is_data_line(pl: ParsedLine) -> bool:
        if pl is None:
            return False
        raw = (pl.raw or "").strip()
        if not raw:
            return False
        if non_e_letter_re.search(raw):
            return False
        if len(pl.nums) < 3:
            return False
        t = pl.nums[1]
        h = pl.nums[2]
        if not (math.isfinite(t) and math.isfinite(h)):
            return False
        if not (-500.0 <= t <= 2000.0):
            return False
        return True

    xs: List[float] = []
    ys: List[float] = []
    line_idxs: List[int] = []

    marker_idx: Optional[int] = None
    for i, pl in enumerate(parsed):
        if "startofdata" in (pl.raw or "").lower():
            marker_idx = i
            break

    if marker_idx is not None:
        started = False
        for idx in range(marker_idx + 1, len(parsed)):
            pl = parsed[idx]
            if is_data_line(pl):
                started = True
                xs.append(pl.nums[1])
                ys.append(pl.nums[2])
                line_idxs.append(idx)
            else:
                if started:
                    break
        return xs, ys, line_idxs

    for idx, pl in enumerate(parsed):
        if is_data_line(pl):
            x = pl.nums[1]
            if FALLBACK_TEMP_MIN <= x <= FALLBACK_TEMP_MAX:
                xs.append(x)
                ys.append(pl.nums[2])
                line_idxs.append(idx)
    return xs, ys, line_idxs


# ══════════════════════════════════════════════════════════════════════
# §6  算法核心（v219）
# ══════════════════════════════════════════════════════════════════════

def aggregate_duplicates(
    xp: List[float], fp: List[float], ndigits: int = 8
) -> Tuple[List[float], List[float]]:
    bucket: Dict[float, List[float]] = {}
    for x, y in zip(xp, fp):
        k = round(float(x), ndigits)
        bucket.setdefault(k, []).append(float(y))
    xs = sorted(bucket.keys())
    ys = [sum(bucket[k]) / len(bucket[k]) for k in xs]
    return xs, ys


def build_curve_cache(xs: List[float], ys: List[float]) -> Dict[str, Any]:
    pairs = []
    for x, y in zip(xs or [], ys or []):
        try:
            xf, yf = float(x), float(y)
        except Exception:
            continue
        if math.isfinite(xf) and math.isfinite(yf):
            pairs.append((xf, yf))
    if not pairs:
        raise ValueError("未找到有效数值点，无法构建曲线缓存。")
    pairs.sort(key=lambda t: t[0])
    xp = [p[0] for p in pairs]
    yp = [p[1] for p in pairs]
    xp, yp = aggregate_duplicates(xp, yp, ndigits=8)
    if len(xp) < 2:
        raise ValueError("有效曲线点过少，无法构建曲线缓存。")
    return {
        "xp": np.asarray(xp, dtype=float),
        "yp": np.asarray(yp, dtype=float),
        "count": int(len(xp)),
        "x_min": float(xp[0]),
        "x_max": float(xp[-1]),
    }


def interpolate_curve_height(x: float, curve_cache: Dict[str, Any]) -> float:
    xp = np.asarray(curve_cache.get("xp", []), dtype=float)
    yp = np.asarray(curve_cache.get("yp", []), dtype=float)
    if xp.size == 0 or yp.size == 0:
        raise ValueError("曲线缓存为空，无法插值。")
    return float(np.interp(float(x), xp, yp))


def _robust_mad(arr: np.ndarray) -> float:
    a = np.asarray(arr, dtype=float)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return 0.0
    med = float(np.median(a))
    mad = float(np.median(np.abs(a - med)))
    return 1.4826 * mad


def _gaussian_smooth_1d(y: np.ndarray, sigma_pts: float) -> np.ndarray:
    y = np.asarray(y, dtype=float)
    if y.size <= 2 or sigma_pts <= 0:
        return y.copy()
    radius = max(1, int(round(4.0 * float(sigma_pts))))
    xx = np.arange(-radius, radius + 1, dtype=float)
    kernel = np.exp(-0.5 * (xx / float(sigma_pts)) ** 2)
    kernel /= np.sum(kernel)
    y_pad = np.pad(y, (radius, radius), mode="edge")
    y_sm  = np.convolve(y_pad, kernel, mode="same")
    return y_sm[radius:-radius]


def _find_local_extrema(y: np.ndarray) -> Tuple[List[int], List[int]]:
    y = np.asarray(y, dtype=float)
    peaks:   List[int] = []
    valleys: List[int] = []
    if y.size < 3:
        return peaks, valleys
    for i in range(1, len(y) - 1):
        if ((y[i] >= y[i-1]) and (y[i] > y[i+1])) or ((y[i] > y[i-1]) and (y[i] >= y[i+1])):
            peaks.append(i)
        if ((y[i] <= y[i-1]) and (y[i] < y[i+1])) or ((y[i] < y[i-1]) and (y[i] <= y[i+1])):
            valleys.append(i)
    return peaks, valleys


def _prepare_xy_for_detection(
    xs: List[float], ys: List[float]
) -> Tuple[np.ndarray, np.ndarray]:
    bucket: Dict[float, List[float]] = {}
    for x, y in zip(xs, ys):
        try:
            xf, yf = float(x), float(y)
        except Exception:
            continue
        if not (math.isfinite(xf) and math.isfinite(yf)):
            continue
        bucket.setdefault(round(xf, 8), []).append(yf)
    if not bucket:
        return np.asarray([], dtype=float), np.asarray([], dtype=float)
    xp = np.asarray(sorted(bucket.keys()), dtype=float)
    yp = np.asarray([sum(bucket[k]) / len(bucket[k]) for k in xp], dtype=float)
    return xp, yp


def _estimate_step(xp: np.ndarray) -> float:
    xp = np.asarray(xp, dtype=float)
    if xp.size < 2:
        return 0.1
    diffs = np.diff(xp)
    diffs = diffs[np.isfinite(diffs) & (diffs > 1e-9)]
    if diffs.size == 0:
        return 0.1
    step = float(np.median(diffs))
    if not math.isfinite(step) or step <= 0:
        return 0.1
    return step


def _fine_search_extreme(
    center_x: float, radius: float, step: float,
    xp: np.ndarray, yp: np.ndarray, mode: str = "min",
) -> Tuple[float, float]:
    xp = np.asarray(xp, dtype=float)
    yp = np.asarray(yp, dtype=float)
    if xp.size == 0:
        raise ValueError("xp 为空，无法精修极值。")
    left  = max(float(xp[0]),  float(center_x) - float(radius))
    right = min(float(xp[-1]), float(center_x) + float(radius))
    if right <= left:
        y0 = float(np.interp(float(center_x), xp, yp))
        return float(center_x), y0
    step = max(0.005, float(step))
    grid = np.arange(left, right + step * 0.5, step, dtype=float)
    vals = np.interp(grid, xp, yp)
    idx  = int(np.argmax(vals)) if mode.lower() == "max" else int(np.argmin(vals))
    return float(grid[idx]), float(vals[idx])


def _refine_triplet_onset(
    center_x: float, xp: np.ndarray, yp: np.ndarray,
    delta_thr: float,
    left_radius: float = 4.0, right_radius: float = 2.0, step: float = 0.01,
) -> Tuple[float, int]:
    xp = np.asarray(xp, dtype=float)
    yp = np.asarray(yp, dtype=float)
    if xp.size < 3:
        return float(center_x), 0
    left  = max(float(xp[0]) + 1.01, float(center_x) - float(left_radius))
    right = min(float(xp[-1]) - 1.01, float(center_x) + float(right_radius))
    if right <= left + float(step):
        return float(center_x), 0
    grid  = np.arange(left, right + float(step) * 0.5, float(step), dtype=float)
    y0    = np.interp(grid,       xp, yp)
    ym1   = np.interp(grid - 1.0, xp, yp)
    yp1   = np.interp(grid + 1.0, xp, yp)
    mask  = ((yp1 - y0) > float(delta_thr)) & ((y0 - ym1) < float(delta_thr))
    cand  = grid[mask]
    if cand.size > 0:
        return float(cand[-1]), int(cand.size)
    return float(center_x), 0
def _refine_early_foot_onset(
    xp: np.ndarray,
    yp: np.ndarray,
    T1_seed: float,
    T2: float,
) -> Tuple[float, Dict[str, Any]]:
    """
    识别“软起发脚尖”：适合 20260609-1#.001 这种
    116℃ 已经开始偏离基线，但 124℃ 才进入强斜率的曲线。
    """
    xp = np.asarray(xp, dtype=float)
    yp = np.asarray(yp, dtype=float)

    if xp.size < 20 or not math.isfinite(T1_seed):
        return float(T1_seed), {"early_foot_used": False}

    left = max(float(xp[0]), float(T1_seed) - 45.0)
    right = min(float(T1_seed) + 1.0, float(T2) - 5.0)

    base_right = max(left + 8.0, float(T1_seed) - 12.0)
    base_left = max(float(xp[0]), base_right - 35.0)

    base_mask = (xp >= base_left) & (xp <= base_right)
    if int(np.sum(base_mask)) < 10:
        return float(T1_seed), {"early_foot_used": False}

    bx = xp[base_mask]
    by = yp[base_mask]

    # 线性基线：避免把升温漂移误判成起发
    coef = np.polyfit(bx, by, 1)
    base_res = by - np.polyval(coef, bx)
    noise = max(float(_robust_mad(base_res)), 0.05)

    grid = np.arange(left, right + 0.005, 0.01, dtype=float)
    yg = np.interp(grid, xp, yp)
    baseline = np.polyval(coef, grid)
    residual = yg - baseline

    # 2.10 μm 是“脚尖偏离基线”的下限；后面 gain 防止噪声误触发
    residual_thr = max(2.10, 5.0 * noise)
    gain3 = np.interp(grid + 3.0, xp, yp) - yg
    gain5 = np.interp(grid + 5.0, xp, yp) - yg

    mask = (
        (residual >= residual_thr) &
        (gain3 >= max(6.0, 15.0 * noise)) &
        (gain5 >= max(12.0, 25.0 * noise))
    )

    cand = grid[mask]
    if cand.size == 0:
        return float(T1_seed), {
            "early_foot_used": False,
            "early_foot_noise": float(noise),
            "early_foot_thr": float(residual_thr),
        }

    T1_new = float(cand[0])

    # 只允许往前修，不允许乱跳
    if T1_new < T1_seed - 1.0:
        return T1_new, {
            "early_foot_used": True,
            "early_foot_from": float(T1_seed),
            "early_foot_to": float(T1_new),
            "early_foot_noise": float(noise),
            "early_foot_thr": float(residual_thr),
            "early_foot_base_left": float(base_left),
            "early_foot_base_right": float(base_right),
        }

    return float(T1_seed), {"early_foot_used": False}

def detect_T2_T1_robust(
    xs: List[float], ys: List[float],
    logger=None, debug: bool = False,
) -> Tuple[float, float, Dict[str, Any]]:
    """稳健版 T1/T2 识别（v219）。"""
    meta: Dict[str, Any] = {"type": "mono", "confidence": 0.0}

    if len(xs) < 5 or len(ys) < 5:
        raise ValueError("数据点过少，无法稳健识别 T1/T2。")

    xp, yp = _prepare_xy_for_detection(xs, ys)
    if xp.size < 5:
        raise ValueError("有效数据点过少，无法稳健识别 T1/T2。")

    step  = _estimate_step(xp)
    grid  = np.arange(float(xp[0]), float(xp[-1]) + step * 0.5, step, dtype=float)
    y_grid = np.interp(grid, xp, yp)

    sigma_temp = max(0.8, min(2.5, 8.0 * step))
    sigma_pts  = max(1.0, sigma_temp / step)
    y_s = _gaussian_smooth_1d(y_grid, sigma_pts)

    idx2 = int(np.argmax(y_s))
    T2_coarse = float(grid[idx2])

    peaks, valleys = _find_local_extrema(y_s)
    amp = float(np.max(y_s) - np.min(y_s))

    base_mask = (grid >= START_TEMP_FOR_T1) & (grid <= min(T2_coarse - 15.0, START_TEMP_FOR_T1 + 30.0))
    if int(np.sum(base_mask)) < 8:
        base_mask = (grid >= grid[0]) & (grid <= min(T2_coarse - 10.0, grid[0] + 30.0))
    noise_y = _robust_mad(y_s[base_mask]) if int(np.sum(base_mask)) > 0 else _robust_mad(np.diff(y_s))

    valley_drop_min = max(5.0,  5.0 * noise_y, 0.02 * amp)
    valley_rise_min = max(20.0, 8.0 * noise_y, 0.06 * amp)
    peak_sep_min    = max(4.0,  5.0 * step)

    left_peak_idx: Optional[int] = None
    valley_idx:    Optional[int] = None

    left_peaks = [p for p in peaks if (grid[p] >= START_TEMP_FOR_T1 and p < idx2 - 2)]
    for p in reversed(left_peaks):
        cands = [v for v in valleys if p < v < idx2 - 1]
        if not cands:
            continue
        v    = min(cands, key=lambda i: y_s[i])
        drop = float(y_s[p] - y_s[v])
        rise = float(y_s[idx2] - y_s[v])
        sep  = float(grid[idx2] - grid[p])
        if drop >= valley_drop_min and rise >= valley_rise_min and sep >= peak_sep_min:
            left_peak_idx = p
            valley_idx    = v
            break

    if valley_idx is not None:
        T1_coarse = float(grid[valley_idx])
        mode      = "multi_peak_valley"
        meta["type"]       = "multi"
        meta["confidence"] = 0.92
        meta["left_peak_temp"]    = float(grid[left_peak_idx]) if left_peak_idx is not None else None
        meta["valley_depth_um"]   = float(y_s[left_peak_idx] - y_s[valley_idx]) if left_peak_idx is not None else 0.0
        meta["T1_search_end_temp"] = float(grid[valley_idx])
    else:
        dy = np.gradient(y_s, grid)
        base_d_mask = (grid >= START_TEMP_FOR_T1) & (grid <= min(T2_coarse - 15.0, START_TEMP_FOR_T1 + 25.0))
        if int(np.sum(base_d_mask)) < 8:
            base_d_mask = (grid >= grid[0]) & (grid <= min(T2_coarse - 10.0, grid[0] + 25.0))
        if int(np.sum(base_d_mask)) > 0:
            dy_med = float(np.median(dy[base_d_mask]))
            dy_mad = float(_robust_mad(dy[base_d_mask]))
        else:
            dy_med = float(np.median(dy))
            dy_mad = float(_robust_mad(dy))

        dy_thr = max(dy_med + 4.0 * dy_mad, dy_med + 0.2)
        consec = max(3, int(round(2.0 / step)))
        left_start = int(np.searchsorted(grid, START_TEMP_FOR_T1))
        hit_i: Optional[int] = None

        for i in range(left_start, idx2 - consec):
            if np.all(dy[i:i + consec] > dy_thr):
                j = min(idx2, i + max(consec, int(round(5.0 / step))))
                if (y_s[j] - y_s[i]) >= max(8.0, 6.0 * noise_y, 0.03 * amp):
                    hit_i = i
                    break

        if hit_i is None:
            cand = np.where((grid >= START_TEMP_FOR_T1) & (grid <= T2_coarse))[0]
            if cand.size == 0:
                cand = np.arange(0, idx2 + 1)
            valley_idx = int(cand[np.argmin(y_s[cand])])
            T1_coarse  = float(grid[valley_idx])
            mode       = "single_peak_fallback_min"
            meta["confidence"] = 0.45
        else:
            onset_seed      = float(grid[hit_i])
            onset_delta_thr = max(1.0, 0.0009 * amp)
            onset_triplet, onset_triplet_hits = _refine_triplet_onset(
                onset_seed, xp, yp, delta_thr=onset_delta_thr,
                left_radius=4.0, right_radius=2.0, step=0.01,
            )
            near_back = max(3, int(round(3.0 / step)))
            lo = max(left_start, hit_i - near_back)
            local_valley_i    = int(lo + np.argmin(y_s[lo:hit_i + 1]))
            local_valley_gap  = float(onset_triplet - grid[local_valley_i])
            local_valley_jump = float(np.interp(onset_triplet, grid, y_s) - y_s[local_valley_i])
            use_local_valley  = (
                local_valley_gap  <= 2.5 and
                local_valley_jump >= max(3.0, 4.0 * noise_y, 0.003 * amp)
            )

            soft_delta_thr = max(0.45, 1.5 * noise_y, 0.00015 * amp)
            soft_onset, soft_onset_hits = _refine_triplet_onset(
                onset_seed, xp, yp, delta_thr=soft_delta_thr,
                left_radius=6.0, right_radius=0.8, step=0.01,
            )
            soft_gap   = float(onset_seed - soft_onset)
            soft_gain  = float(np.interp(onset_seed, xp, yp) - np.interp(soft_onset, xp, yp))
            soft_pre_lo   = max(float(xp[0]), float(onset_seed) - 12.0)
            soft_pre_mask = (xp >= soft_pre_lo) & (xp <= onset_seed)
            soft_base_min = float(np.min(yp[soft_pre_mask])) if int(np.sum(soft_pre_mask)) > 0 else float(np.min(yp))
            soft_level    = float(np.interp(soft_onset, xp, yp) - soft_base_min)
            use_soft_onset = (
                int(soft_onset_hits) > 0 and
                soft_gap  >= 4.0 and
                soft_gain >= max(20.0, 20.0 * noise_y, 0.012 * amp) and
                soft_level <= max(2.0,  8.0 * noise_y, 0.01 * amp)
            )

            if use_local_valley:
                valley_idx = local_valley_i
                T1_coarse  = float(grid[local_valley_i])
                mode       = "single_peak_local_valley"
                meta["confidence"] = 0.79
            elif use_soft_onset:
                T1_coarse       = float(soft_onset)
                mode            = "single_peak_soft_triplet"
                onset_delta_thr = float(soft_delta_thr)
                meta["confidence"] = 0.91
            else:
                T1_coarse = float(onset_triplet)
                mode      = "single_peak_step_onset"
                meta["confidence"] = 0.89

            meta.update({
                "onset_seed_temp":       float(onset_seed),
                "onset_triplet_temp":    float(onset_triplet),
                "onset_triplet_hits":    int(onset_triplet_hits),
                "onset_delta_thr":       float(onset_delta_thr),
                "local_valley_gap_temp": float(local_valley_gap),
                "local_valley_jump_um":  float(local_valley_jump),
                "soft_triplet_temp":     float(soft_onset),
                "soft_triplet_hits":     int(soft_onset_hits),
                "soft_delta_thr":        float(soft_delta_thr),
                "soft_gap_temp":         float(soft_gap),
                "soft_gain_um":          float(soft_gain),
                "soft_level_um":         float(soft_level),
            })

        meta["dy_thr"]             = float(dy_thr)
        meta["dy_med"]             = float(dy_med)
        meta["dy_mad"]             = float(dy_mad)
        meta["T1_search_end_temp"] = float(T1_coarse)

    fine_step = max(0.01, step / 5.0)
    if mode == "multi_peak_valley":
        T1, H1 = _fine_search_extreme(T1_coarse, radius=1.5, step=fine_step, xp=xp, yp=yp, mode="min")
    elif mode in ("single_peak_local_valley", "single_peak_fallback_min"):
        T1, H1 = _fine_search_extreme(T1_coarse, radius=0.6, step=fine_step, xp=xp, yp=yp, mode="min")
    else:
        T1 = float(T1_coarse)
        H1 = float(np.interp(T1, xp, yp))
    T2, H2 = _fine_search_extreme(T2_coarse, radius=1.5, step=fine_step, xp=xp, yp=yp, mode="max")
    T1_new, early_meta = _refine_early_foot_onset(xp, yp, T1, T2)
    if early_meta.get("early_foot_used"):
        T1 = T1_new
        H1 = float(np.interp(T1, xp, yp))
        mode = str(mode) + "+early_foot"
        meta["confidence"] = max(float(meta.get("confidence", 0.0)), 0.90)

    meta.update(early_meta)
    meta.update({
        "mode":              mode,
        "T1_temp":           float(T1),
        "T2_temp":           float(T2),
        "H1_um":             float(H1),
        "H2_um":             float(H2),
        "H_um":              float(H2 - H1),
        "T2_height_um":      float(H2),
        "noise_y_um":        float(noise_y),
        "valley_drop_min_um": float(valley_drop_min),
        "valley_rise_min_um": float(valley_rise_min),
        "smooth_sigma_temp":  float(sigma_temp),
    })
    return float(T1), float(T2), meta


def detect_T2_T1(xs: List[float], ys: List[float], logger=None) -> Tuple[float, float]:
    T1, T2, _meta = detect_T2_T1_robust(xs, ys, logger, debug=False)
    return float(T1), float(T2)


def detect_T2_T1_precise(
    xs: List[float], ys: List[float], logger=None, debug: bool = False
) -> Tuple[float, float, Dict[str, Any]]:
    return detect_T2_T1_robust(xs, ys, logger, debug=debug)



def detect_T2_T1_super_gradient(
    xs: List[float], ys: List[float], logger=None, debug: bool = False
) -> Tuple[float, float, Dict[str, Any]]:
    T1, T2, meta = detect_T2_T1_robust(xs, ys, logger, debug=debug)
    xp, yp = _prepare_xy_for_detection(xs, ys)
    if xp.size < 5:
        return float(T1), float(T2), meta

    T2f, H2f = _fine_search_extreme(T2, radius=1.0, step=0.01, xp=xp, yp=yp, mode="max")
    mode_str = str(meta.get("mode") or "")

    if mode_str in ("multi_peak_valley", "single_peak_local_valley", "single_peak_fallback_min"):
        t1_radius = 1.0 if mode_str == "multi_peak_valley" else 0.4
        T1f, H1f  = _fine_search_extreme(T1, radius=t1_radius, step=0.01, xp=xp, yp=yp, mode="min")
        meta["super_window_T1"] = float(t1_radius)
    else:
        amp           = float(np.max(yp) - np.min(yp)) if yp.size > 0 else 0.0
        onset_delta   = float(meta.get("onset_delta_thr", max(1.0, 0.0009 * amp)))
        T1f, sup_hits = _refine_triplet_onset(
            T1, xp, yp, delta_thr=onset_delta,
            left_radius=1.2, right_radius=0.6, step=0.01,
        )
        H1f = float(np.interp(T1f, xp, yp))
        meta["super_triplet_hits"] = int(sup_hits)
        meta["super_window_T1"]    = 1.2

    meta.update({
        "T1_super":       float(T1f),
        "T2_super":       float(T2f),
        "H1_um":          float(H1f),
        "H2_um":          float(H2f),
        "H_um":           float(H2f - H1f),
        "super_step":      0.01,
        "super_window_T2": 1.0,
    })
    return float(T1f), float(T2f), meta


def calc_tma_from_m_h(mg: float, H_um: float) -> float:
    if mg <= 0:
        raise ValueError("G(m) 必须大于0")
    if H_um <= 0:
        raise ValueError("H 必须大于0")
    return 1000.0 * mg / (math.pi * 3.35 * 3.35 * (H_um / 1000.0))


# ══════════════════════════════════════════════════════════════════════
# §6.5  D50/Span（OCR）+ M（xlsx）+ 缓存
# ══════════════════════════════════════════════════════════════════════

# ── 批次号等价候选集（来自 piliang_tma_v3，完整复刻）──────────────────

def _name_candidates(name: str) -> set:
    """生成批次名称的所有等价形式，用于与 xlsx B 列进行模糊匹配。

    规则（与 piliang_tma_v3._name_candidates 完全一致）：
      H906-2509001.001   <->  H906-2509001
      20260323-1#.001    <->  20260323-1  /  20260323-1#  /  2026032301
    """
    name = str(name or "").strip()
    if not name:
        return set()

    cands = {name}

    if name.endswith("#"):
        base = name[:-1].strip()
        cands.add(base)
    else:
        base = name
        cands.add(name + "#")

    m = re.match(r"^(\d{8})-(\d{1,2})#?$", base)
    if m:
        d8, seq = m.group(1), int(m.group(2))
        cands.update({
            f"{d8}{seq:02d}",
            f"{d8}-{seq}",
            f"{d8}-{seq}#",
        })

    m2 = re.match(r"^(\d{8})(\d{2})$", base)
    if m2:
        d8, seq = m2.group(1), int(m2.group(2))
        cands.update({
            f"{d8}-{seq}",
            f"{d8}-{seq}#",
            f"{d8}{seq:02d}",
        })

    return cands


# ── 缓存文件路径辅助 ──────────────────────────────────────────────────

def _safe_stem(stem: str) -> str:
    """清理文件名中的非法字符，用于构造缓存文件名。"""
    return re.sub(r'[\\/:*?"<>|]', "_", stem)


def _lj_cache_path(cache_dir: str, lj_stem: str) -> str:
    """粒径 OCR 缓存路径：./cache/<safe_lj_stem>_lj.json"""
    return os.path.join(cache_dir, f"{_safe_stem(lj_stem)}_lj.json")


def _m_cache_path(cache_dir: str, tma_stem: str) -> str:
    """M 缓存路径：./cache/<safe_tma_stem>_m.json"""
    return os.path.join(cache_dir, f"{_safe_stem(tma_stem)}_m.json")


def _load_json_cache(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _save_json_cache(path: str, record: Dict[str, Any]) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


# ── D50/Span：切图 OCR（来自 lijing_pdf_png_ocr.py）──────────────────

def _scale_box(
    box: Tuple[int, int, int, int], img_w: int, img_h: int
) -> Tuple[int, int, int, int]:
    """按实际图片尺寸等比缩放坐标（与 lijing_pdf_png_ocr.scale_box 一致）。"""
    sx = img_w / _LJ_BASE_W
    sy = img_h / _LJ_BASE_H
    l, u, r, d = box
    return int(l * sx), int(u * sy), int(r * sx), int(d * sy)


def _preprocess_for_ocr(pil_img: Image.Image) -> Image.Image:
    """灰度 → 3× 放大 → Otsu 二值化（与 lijing_pdf_png_ocr.preprocess 一致）。"""
    arr = np.array(pil_img.convert("L"))
    arr = _cv2.resize(arr, None, fx=3, fy=3, interpolation=_cv2.INTER_CUBIC)
    _, arr = _cv2.threshold(arr, 0, 255, _cv2.THRESH_BINARY + _cv2.THRESH_OTSU)
    return Image.fromarray(arr)


def _ocr_number(pil_img: Image.Image) -> str:
    """Tesseract OCR 数字识别（与 lijing_pdf_png_ocr.ocr_number 一致）。"""
    processed = _preprocess_for_ocr(pil_img)
    raw = _tess.image_to_string(
        processed,
        config="--psm 6 -c tessedit_char_whitelist=0123456789."
    )
    numbers = re.findall(r"\d+\.\d+|\d+", raw)
    return numbers[-1] if numbers else ""


def extract_d50_span_from_png(
    png_path: str,
    cache_dir: str,
) -> Tuple[Optional[str], Optional[str], Dict[str, str]]:
    """从粒径图 PNG 切图 OCR 提取 D50 和 Span。

    区域坐标与 lijing_pdf_png_ocr.py 的 VALUE_REGIONS 完全一致：
      D50:  (568, 565, 842, 635)  → 基准 1413×2000
      Span: (842, 640, 1090, 720) → 基准 1413×2000

    切片图保存到 ./cache/<safe_stem>_D50.png / _Span.png 供肉眼核查。

    返回: (d50_str, span_str, crop_paths)
      识别失败时对应字段为 None；crop_paths 是切片保存路径字典。
    """
    if not _HAS_OCR:
        return None, None, {}

    try:
        img = Image.open(png_path)
        img_w, img_h = img.size
        stem = os.path.splitext(os.path.basename(png_path))[0]
        safe  = _safe_stem(stem)
        os.makedirs(cache_dir, exist_ok=True)

        results: Dict[str, Optional[str]] = {}
        crop_paths: Dict[str, str] = {}

        for key, region in _LJ_VALUE_REGIONS.items():
            box = _scale_box(region, img_w, img_h)
            cropped = img.crop(box)
            # 保存切片供核查
            crop_path = os.path.join(cache_dir, f"{safe}_{key}.png")
            try:
                cropped.save(crop_path)
                crop_paths[key] = crop_path
            except Exception:
                pass
            val = _ocr_number(cropped)
            results[key] = val if val else None

        return results.get("D50"), results.get("Span"), crop_paths

    except Exception:
        return None, None, {}


# ── M（质量）：xlsx 查询（来自 piliang_tma_v3.lookup_mass，完整复刻）──

def lookup_mass(
    filepath: str,
    xlsx_path: str,
) -> Tuple[Optional[Any], str]:
    """从 TMA称量数据.xlsx 中查找质量值。

    完整复刻 piliang_tma_v3.lookup_mass：
      · 只读模式打开（read_only=True, data_only=True）
      · B 列（index=1）= 批次号，C 列（index=2）= 重量
      · 自后向前遍历，重复批次取行号最大（最后出现）的那条
      · 文件名 stem → _name_candidates() 双向匹配

    返回: (mass_value, matched_B_value_or_error_str)
      未找到或出错时 mass_value=None，第二项描述原因。
    """
    try:
        import openpyxl as _opx
    except ImportError:
        return None, "openpyxl 未安装，请执行: pip install openpyxl"

    stem       = os.path.splitext(os.path.basename(filepath))[0]
    file_cands = _name_candidates(stem)

    try:
        wb = _opx.load_workbook(xlsx_path, read_only=True, data_only=True)
        ws = wb.active

        all_rows: List[Tuple[str, Any]] = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            b = str(row[1] if len(row) > 1 and row[1] is not None else "").strip()
            c = row[2] if len(row) > 2 else None
            all_rows.append((b, c))

        try:
            wb.close()
        except Exception:
            pass

        for b_val, c_val in reversed(all_rows):
            if not b_val:
                continue
            if file_cands & _name_candidates(b_val):
                return c_val, b_val

        return None, f"未匹配：文件名 '{stem}' 在 B 列中找不到对应记录"

    except FileNotFoundError:
        return None, f"称量数据文件不存在：{xlsx_path}"
    except PermissionError:
        return None, f"无权访问：{xlsx_path}"
    except Exception as e:
        return None, f"读取称量数据异常：{e}"


# ══════════════════════════════════════════════════════════════════════
# §7  UILogger + logging.Logger 桥接器
# ══════════════════════════════════════════════════════════════════════

class UILogger:
    def __init__(self, text: ScrolledText):
        self.text = text
        self._init_tags()

    def _init_tags(self):
        tw = self.text
        tw.tag_configure("INFO",  foreground="#000000")
        tw.tag_configure("WARN",  foreground="#CC7A00")
        tw.tag_configure("ERROR", foreground="#C00000")
        tw.tag_configure("OK",    foreground="#0B7D0B")
        tw.tag_configure("PATH",  foreground="#C00000")
        tw.tag_configure("TIME",  foreground="#0B7D0B")
        tw.tag_configure("SEP",   foreground="#D4A000")
        tw.tag_configure("MISS",  foreground="#FFFFFF", background="#C00000")

    def _append(self, msg: str, tag: str = "INFO"):
        try:
            self.text.configure(state="normal")
            self.text.insert("end", msg + "\n", tag)
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.text.insert("end", ts + "\n", "TIME")
            self.text.insert("end", "----------------------------------------\n", "SEP")
            self.text.see("end")
            self.text.configure(state="disabled")
        except Exception:
            pass

    def sep(self):                self._append("==========", "SEP")
    def info(self, msg: str):     self._append(msg, "INFO")
    def ok(self, msg: str):       self._append(msg, "OK")
    def warn(self, msg: str):     self._append(msg, "WARN")
    def error(self, msg: str):    self._append(msg, "ERROR")
    def miss(self, label: str):   self._append(f"缺少：{label}", "MISS")
    def path(self, prefix: str, p: str):
        self._append(f"{prefix} {p}", "INFO")
        self._append(p, "PATH")


class _UILoggerBridgeHandler(logging.Handler):
    def __init__(self, ui_logger: UILogger, tk_root=None):
        super().__init__()
        self._ui = ui_logger
        self._root = tk_root

    def emit(self, record: logging.LogRecord):
        try:
            msg = record.getMessage()
            if record.exc_info:
                import traceback as _tb
                msg = (msg + "\n" if msg else "") + "".join(
                    _tb.format_exception(*record.exc_info)
                )
            if record.levelno >= logging.ERROR:
                fn, m = self._ui.error, msg
            elif record.levelno >= logging.WARNING:
                fn, m = self._ui.warn, msg
            elif record.levelno >= logging.INFO:
                fn, m = self._ui.info, msg
            else:
                return
            if self._root:
                self._root.after(0, lambda: fn(m))
            else:
                fn(m)
        except Exception:
            pass


def _make_algo_logger(ui_logger: UILogger, name: str = "one_bg_algo",
                      tk_root=None) -> logging.Logger:
    logger = logging.getLogger(name + "_" + str(id(ui_logger)))
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False
    h = _UILoggerBridgeHandler(ui_logger, tk_root=tk_root)
    h.setLevel(logging.INFO)
    logger.addHandler(h)
    return logger


# ══════════════════════════════════════════════════════════════════════
# §8  图像 / PDF 工具
# ══════════════════════════════════════════════════════════════════════

def pdf_first_page_to_png(pdf_path: str, out_png: str, zoom: float = 2.0) -> str:
    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(0)
        mat  = fitz.Matrix(zoom, zoom)
        pix  = page.get_pixmap(matrix=mat, alpha=False)
        os.makedirs(os.path.dirname(out_png), exist_ok=True)
        pix.save(out_png)
        return out_png
    finally:
        doc.close()


def generate_tma_tif(
    xs: List[float], ys: List[float],
    T1: float, T2: float, H: float,
    mg_text: str, out_tif: str,
    version: str = VERSION,
) -> str:
    """生成 TMA 曲线图（3840×2160 @300dpi TIFF，对齐 piliang_tma_v3）。"""
    os.makedirs(os.path.dirname(out_tif), exist_ok=True)
    xs = [float(x) for x in xs]
    ys = [float(y) for y in ys]

    y_min_data = float(min(ys))
    y_max_data = float(max(ys))
    y0_base = -200.0 if y_min_data > -200.0 else math.floor(y_min_data / 500.0) * 500.0
    y1_base = math.ceil(y_max_data / 500.0) * 500.0
    if y1_base < 0:
        y1_base = 0.0
    if y1_base <= y0_base:
        y1_base = y0_base + 500.0

    y0_plot = float(y0_base)
    y1_plot = float(y1_base)

    try:
        curve_cache = build_curve_cache(xs, ys)
        x1_pt, y1_pt = float(T1), interpolate_curve_height(float(T1), curve_cache)
        x2_pt, y2_pt = float(T2), interpolate_curve_height(float(T2), curve_cache)
    except Exception:
        idx1 = min(range(len(xs)), key=lambda i: abs(xs[i] - T1))
        idx2 = min(range(len(xs)), key=lambda i: abs(xs[i] - T2))
        x1_pt, y1_pt = float(xs[idx1]), float(ys[idx1])
        x2_pt, y2_pt = float(xs[idx2]), float(ys[idx2])

    def _ann_margin(cy0: float, cy1: float) -> float:
        return max(80.0, (cy1 - cy0) * 0.04)

    ann = _ann_margin(y0_plot, y1_plot)
    if y2_pt + ann > y1_plot:
        y1_plot += 200.0
        ann = _ann_margin(y0_plot, y1_plot)
    while y1_pt - ann < y0_plot:
        y0_plot -= 100.0
        ann = _ann_margin(y0_plot, y1_plot)
    if y1_plot <= y0_plot:
        y1_plot = y0_plot + 500.0

    y_ticks_major = [float(y0_plot), 0.0]
    if y0_plot < -500.0 - 1e-9:
        y_ticks_major.append(-500.0)
    y_ticks_major.extend([float(v) for v in range(500, int(y1_base) + 1, 500)])
    y_ticks_major = sorted({v for v in y_ticks_major if y0_plot - 1e-9 <= v <= y1_base + 1e-9})
    y_minor_start = int(math.floor(y0_plot / 100.0)) * 100
    y_minor_end   = int(math.ceil(y1_plot / 100.0)) * 100
    y_ticks_minor = list(range(y_minor_start, y_minor_end + 1, 100))

    fig = Figure(figsize=(12.8, 7.2), dpi=100)
    ax  = fig.add_subplot(111)
    ax.plot(xs, ys, color="black", linewidth=1.5)
    ax.set_xlim(0.0, 300.0)
    ax.xaxis.set_major_locator(MultipleLocator(50))
    ax.xaxis.set_minor_locator(MultipleLocator(10))
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.set_xlabel("温度(°C)", fontsize=12)
    ax.tick_params(axis="x", which="major", length=6)
    ax.tick_params(axis="x", which="minor", length=3)
    ax.set_ylim(y0_plot, y1_plot)
    ax.yaxis.set_major_locator(FixedLocator(y_ticks_major))
    ax.yaxis.set_minor_locator(FixedLocator(y_ticks_minor))
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.set_ylabel("尺寸变化(μm)", fontsize=12)
    ax.tick_params(axis="y", which="major", length=6)
    ax.tick_params(axis="y", which="minor", length=3)

    for gx in range(0, 301, 10):
        ax.axvline(gx, linestyle="--", linewidth=0.4, color="#999999", alpha=0.35, zorder=0)
    for gy in range(int(math.floor(y0_plot / 100.0)) * 100,
                    int(math.ceil(y1_plot / 100.0)) * 100 + 1, 100):
        ax.axhline(gy, linestyle="--", linewidth=0.4, color="#999999", alpha=0.35, zorder=0)
    try:
        ax.plot([0, 500, 500, 0, 0], [0, 0, 500, 500, 0],
                linestyle=(0, (1, 3)), linewidth=0.5, color="0.8", zorder=0)
    except Exception:
        pass

    fig.suptitle("TMA", fontsize=16, fontweight="bold")
    mg_s = str(mg_text).strip() if mg_text else "x"
    ax.text(10, y1_plot - 100,
            "方法日志：30°C平衡，施加 0.06 N；\n"
            + " " * 17 + "20°C/min加热至 250°C；\n"
            + f"称取质量：{mg_s}mg。",
            ha="left", va="top", fontsize=12, color="black")

    y_range     = y1_plot - y0_plot
    tick_half_y = max(10.0, y_range * 0.02)
    tick_half_x = 2.0
    tick_lw     = 1.2

    def _draw_cross(xc: float, yc: float):
        ax.vlines(xc, yc - tick_half_y, yc + tick_half_y,
                  colors="black", linewidth=tick_lw, zorder=5)
        ax.hlines(yc, max(0.0, xc - tick_half_x), min(300.0, xc + tick_half_x),
                  colors="black", linewidth=tick_lw, zorder=5)

    _draw_cross(x1_pt, y1_pt)
    ax.annotate(f"{format_plot_temp_c(x1_pt)}℃", (x1_pt, y1_pt),
                xytext=(0, -10), textcoords="offset points",
                ha="center", va="top", fontsize=12, color="black")
    _draw_cross(x2_pt, y2_pt)
    ax.annotate(f"{format_plot_temp_c(x2_pt)}℃", (x2_pt, y2_pt),
                xytext=(0, 10), textcoords="offset points",
                ha="center", va="bottom", fontsize=12, color="black")

    ax.plot([x1_pt, x2_pt], [y1_pt, y1_pt], color="black", lw=0.8, zorder=4)
    ax.annotate("", xy=(x2_pt, y2_pt), xytext=(x2_pt, y1_pt),
                arrowprops=dict(arrowstyle="<->", color="black",
                                linewidth=1.0, shrinkA=0, shrinkB=0))
    try:
        dh_show = abs(float(H))
    except Exception:
        dh_show = abs(y2_pt - y1_pt)
    x_text  = min(300.0, x2_pt + 15.0)
    margin  = max(15.0, (y1_plot - y0_plot) * 0.03)
    y_curve = float(np.interp(x_text, np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)))
    y_text  = min(y_curve + margin, y1_plot - margin * 0.2)
    ax.text(x_text, y_text, f"{format_height_um(dh_show)} μm",
            fontsize=12, ha="left", va="bottom", color="black")

    fig.text(0.99, 0.01, version, ha="right", va="bottom", fontsize=10, color="black")
    fig.set_size_inches(12.8, 7.2, forward=True)
    fig.savefig(out_tif, format="tiff", dpi=300)
    return out_tif


class PDFTemplateEditor:
    def __init__(self, template_pdf: str, logger: UILogger):
        self.template_pdf = template_pdf
        self.doc    = fitz.open(template_pdf)
        self.logger = logger

    def close(self):
        try:
            self.doc.close()
        except Exception:
            pass

    def replace_image_centered(self, page_index: int, image_path: str):
        if page_index < 0:
            return
        while self.doc.page_count <= page_index:
            self.doc.new_page()
        page = self.doc.load_page(page_index)
        for img in page.get_images(full=True):
            try:
                page.delete_image(img[0])
            except Exception:
                pass
        try:
            page.clean_contents()
        except Exception:
            pass
        image = Image.open(image_path)
        import io
        bio = io.BytesIO()
        fmt = (image.format or "PNG").upper()
        if fmt == "JPG":
            fmt = "JPEG"
        image.save(bio, format=fmt)
        img_bytes = bio.getvalue()
        bio.close()
        rect   = page.rect
        new_w  = rect.width * 0.75
        aspect = image.width / max(1, image.height)
        new_h  = new_w / aspect
        x0 = (rect.width  - new_w) / 2
        y0 = (rect.height - new_h) / 2
        page.insert_image(fitz.Rect(x0, y0, x0 + new_w, y0 + new_h), stream=img_bytes)

    def replace_label(self, search_text: str, to_value: str,
                      page_index: int = 0, fontsize: int = 11) -> int:
        search_text = str(search_text)
        to_value    = str(to_value)
        if page_index < 0 or page_index >= self.doc.page_count:
            return 0
        page = self.doc.load_page(page_index)
        insts = page.search_for(search_text)
        if not insts:
            return 0
        for inst in insts:
            page.add_redact_annot(inst)
        page.apply_redactions()
        for inst in insts:
            page.insert_text((inst.x0, inst.y0), to_value,
                             fontsize=fontsize, fontname="Times-Roman")
        return len(insts)

    def save(self, out_pdf: str):
        os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
        self.doc.save(out_pdf, garbage=4, deflate=True)


def build_simple_pdf(
    out_pdf: str, values: Dict[str, str],
    tma_img: str, lj_img: str, logger: UILogger, root=None
):
    try:
        from reportlab.pdfgen import canvas as rl_canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader
    except Exception as e:
        raise RuntimeError(f"缺少 reportlab，且未找到 template.pdf：{e}")
    w, h = A4
    os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
    c = rl_canvas.Canvas(out_pdf, pagesize=A4)
    c.setFont("Helvetica", 14)
    c.drawString(50, h - 60, "COA Report (Simple)")
    c.setFont("Helvetica", 11)
    y = h - 100
    for k in ["tmaname", "lijing", "qifawd", "zuidawd", "tmamd", "shengchan"]:
        c.drawString(50, y, f"{k}: {values.get(k, '')}")
        y -= 18
    c.showPage()
    c.setFont("Helvetica", 12)
    c.drawString(50, h - 60, "TMA Curve")
    c.drawImage(ImageReader(tma_img), 50, 80, width=w-100, height=h-160,
                preserveAspectRatio=True, anchor="c")
    c.showPage()
    c.setFont("Helvetica", 12)
    c.drawString(50, h - 60, "Particle Size")
    c.drawImage(ImageReader(lj_img), 50, 80, width=w-100, height=h-160,
                preserveAspectRatio=True, anchor="c")
    c.showPage()
    c.save()
    if root:
        root.after(0, lambda: logger.ok(f"✅ 已生成简版报告：{out_pdf}"))
    else:
        logger.ok(f"✅ 已生成简版报告：{out_pdf}")


# ══════════════════════════════════════════════════════════════════════
# §9  GUI 主程序
# ══════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════
# §9  GUI — 科技感深色主题（v4 新增）
# ══════════════════════════════════════════════════════════════════════

# ── 调色板 ──────────────────────────────────────────────────────────
class _C:
    """全局调色板（GitHub Dark 风格 + 青色荧光点缀）"""
    BG          = "#0d1117"   # 根窗口 / 最深背景
    PANEL       = "#161b22"   # 卡片 / 面板背景
    INPUT_BG    = "#21262d"   # 输入框背景
    BORDER      = "#30363d"   # 边框 / 分隔线
    BORDER_LIT  = "#58a6ff"   # 激活/焦点边框（蓝）

    FG          = "#e6edf3"   # 主文字
    FG2         = "#8b949e"   # 次要文字
    FG3         = "#6e7681"   # 占位 / 弱文字

    CYAN        = "#00d4ff"   # 品牌青
    CYAN_DIM    = "#0891a8"   # 暗青
    GREEN       = "#3fb950"   # 成功
    YELLOW      = "#d29922"   # 警告
    RED         = "#f85149"   # 错误
    ORANGE      = "#db6d28"   # 强调橙

    # 按钮组颜色
    BTN_PRIMARY  = "#1f6feb"  # 主操作（蓝）
    BTN_SUCCESS  = "#238636"  # 生成报告（绿）
    BTN_ACCENT   = "#2a6458"  # 读取类（深青）
    BTN_NEUTRAL  = "#2d333b"  # 中性操作
    BTN_DANGER   = "#6e2a2a"  # 退出（暗红）

    FONT_MONO   = ("Consolas", 9)
    FONT_UI     = ("Microsoft YaHei UI", 9)
    FONT_LABEL  = ("Microsoft YaHei UI", 9)
    FONT_TITLE  = ("Microsoft YaHei UI", 13, "bold")
    FONT_VER    = ("Consolas", 8)


def _setup_ttk_style(root: tk.Tk):
    """配置 ttk 控件的深色主题（Combobox / Scrollbar）。"""
    style = ttk.Style(root)
    style.theme_use("clam")

    # ── Combobox ─────────────────────────────────────────────────────
    style.configure("Tech.TCombobox",
        fieldbackground=_C.INPUT_BG,
        background=_C.INPUT_BG,
        foreground=_C.FG,
        selectforeground=_C.FG,
        selectbackground=_C.BORDER_LIT,
        insertcolor=_C.CYAN,
        bordercolor=_C.BORDER,
        arrowcolor=_C.FG2,
        arrowsize=12,
        padding=(6, 4),
        relief="flat",
    )
    style.map("Tech.TCombobox",
        fieldbackground=[("focus", _C.INPUT_BG), ("readonly", _C.INPUT_BG)],
        bordercolor=[("focus", _C.BORDER_LIT), ("hover", _C.BORDER_LIT)],
    )

    # ── Vertical Scrollbar ────────────────────────────────────────────
    style.configure("Tech.Vertical.TScrollbar",
        gripcount=0,
        background=_C.BORDER,
        troughcolor=_C.PANEL,
        bordercolor=_C.PANEL,
        arrowcolor=_C.FG2,
        arrowsize=11,
        width=10,
        relief="flat",
    )
    style.map("Tech.Vertical.TScrollbar",
        background=[("active", _C.BORDER_LIT), ("pressed", _C.CYAN)],
    )


class _TechButton(tk.Canvas):
    """Canvas 实现的科技感按钮，支持 hover 发光效果。"""

    _RADIUS = 5  # 圆角半径
    _all_buttons: list = []  # 全局按钮注册表

    def __init__(self, parent, text: str, command=None,
                 fg: str = _C.FG, bg: str = _C.BTN_NEUTRAL,
                 accent: str = _C.BORDER_LIT,
                 width_px: int = 0, height_px: int = 28, **kw):
        self._bg      = bg
        self._fg      = fg
        self._accent  = accent
        self._cmd     = command
        self._text    = text
        self._hover   = False
        self._pressed = False

        # 估算宽度
        if width_px == 0:
            width_px = max(90, len(text) * 13 + 20)

        super().__init__(parent, width=width_px, height=height_px,
                         bg=_C.PANEL, highlightthickness=0, **kw)

        # ✅ v5 真正修复：
        # self._w 是 Tkinter 内部保留属性（widget 的 Tcl 路径），
        # super().__init__() 已将其设为正确的 Tcl 路径（如 ".!frame.!canvas"）。
        # 若用 self._w = width_px 覆盖，所有后续 Tk 操作都会把 "52" 当作
        # 窗口名传给 Tcl，引发 "bad argument '52': must be name of window"。
        # 解决：改用 self._btn_w / self._btn_h 存储按钮尺寸。
        self._btn_w = width_px
        self._btn_h = height_px

        # super().__init__() 完成后 widget 已完整注册，可直接绘制。
        self._draw()

        self.bind("<Enter>",           self._on_enter)
        self.bind("<Leave>",           self._on_leave)
        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

        _TechButton._all_buttons.append(self)

    # ── 绘制 ─────────────────────────────────────────────────────────
    def _rounded_rect(self, x1, y1, x2, y2, r, **kw):
        """在 Canvas 上绘制圆角矩形。"""
        self.create_arc(x1, y1, x1+2*r, y1+2*r, start=90,  extent=90, style="pieslice", **kw)
        self.create_arc(x2-2*r, y1, x2, y1+2*r, start=0,   extent=90, style="pieslice", **kw)
        self.create_arc(x2-2*r, y2-2*r, x2, y2, start=270, extent=90, style="pieslice", **kw)
        self.create_arc(x1, y2-2*r, x1+2*r, y2, start=180, extent=90, style="pieslice", **kw)
        self.create_rectangle(x1+r, y1, x2-r, y2, **kw)
        self.create_rectangle(x1, y1+r, x2, y2-r, **kw)

    def _draw(self):
        self.delete("all")
        r  = self._RADIUS
        w, h = self._btn_w, self._btn_h

        # 底色
        fill_color = self._lighter(self._bg, 18) if self._hover else self._bg
        if self._pressed:
            fill_color = self._darker(self._bg, 15)

        self._rounded_rect(1, 1, w-1, h-1, r,
                            fill=fill_color, outline="")

        # 边框（hover 时高亮）
        border_col = self._accent if self._hover else self._darker(self._bg, 8)
        self._rounded_rect(0, 0, w, h, r,
                            fill="", outline=border_col)

        # 顶部发光线（hover 专属）
        if self._hover:
            self.create_line(r+2, 1, w-r-2, 1, fill=self._accent, width=1)

        # 文字
        txt_y = h // 2 + (1 if self._pressed else 0)
        self.create_text(w // 2, txt_y, text=self._text,
                         fill=self._fg,
                         font=(_C.FONT_UI[0], _C.FONT_UI[1]),
                         anchor="center")

    @staticmethod
    def _lighter(hex_color: str, amount: int) -> str:
        """把十六进制颜色变亮。"""
        try:
            c = hex_color.lstrip("#")
            r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
            r = min(255, r + amount)
            g = min(255, g + amount)
            b = min(255, b + amount)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color

    @staticmethod
    def _darker(hex_color: str, amount: int) -> str:
        """把十六进制颜色变暗。"""
        try:
            c = hex_color.lstrip("#")
            r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
            r = max(0, r - amount)
            g = max(0, g - amount)
            b = max(0, b - amount)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color

    def _on_enter(self, _e=None):
        self._hover = True
        self._draw()
        self.config(cursor="hand2")

    def _on_leave(self, _e=None):
        self._hover   = False
        self._pressed = False
        self._draw()
        self.config(cursor="")

    def _on_press(self, _e=None):
        self._pressed = True
        self._draw()

    def _on_release(self, _e=None):
        self._pressed = False
        self._draw()
        if self._cmd:
            try:
                self._cmd()
            except Exception:
                pass

    def config_state(self, enabled: bool):
        """启用 / 禁用按钮（视觉灰化）。"""
        if enabled:
            self._fg = _C.FG
        else:
            self._fg = _C.FG3
        self._draw()

    @classmethod
    def set_all_enabled(cls, enabled: bool):
        for btn in cls._all_buttons:
            try:
                btn.config_state(enabled)
            except Exception:
                pass


def _tech_entry(parent, var: tk.StringVar, width: int = 20) -> tk.Entry:
    """创建深色风格 Entry。"""
    e = tk.Entry(parent, textvariable=var, width=width,
                 bg=_C.INPUT_BG, fg=_C.FG,
                 insertbackground=_C.CYAN,
                 selectbackground=_C.BORDER_LIT,
                 selectforeground=_C.FG,
                 relief="flat",
                 highlightthickness=1,
                 highlightcolor=_C.BORDER_LIT,
                 highlightbackground=_C.BORDER,
                 font=_C.FONT_UI)
    return e


def _tech_label(parent, text: str, color: str = _C.FG2,
                font=None) -> tk.Label:
    """创建深色风格 Label。"""
    return tk.Label(parent, text=text,
                    bg=_C.PANEL, fg=color,
                    font=font or _C.FONT_LABEL)


def _section_sep(parent) -> tk.Frame:
    """1px 水平分隔线。"""
    return tk.Frame(parent, height=1, bg=_C.BORDER)


class _FieldBox(tk.Frame):
    """带标签 + 彩色左边框的参数输入框组件。"""
    def __init__(self, parent, label: str, var: tk.StringVar,
                 entry_width: int = 10, accent: str = _C.CYAN,
                 **kw):
        super().__init__(parent, bg=_C.PANEL, **kw)

        # 左侧色条
        bar = tk.Frame(self, width=3, bg=accent)
        bar.pack(side="left", fill="y")

        inner = tk.Frame(self, bg=_C.PANEL, padx=6, pady=2)
        inner.pack(side="left", fill="both", expand=True)

        tk.Label(inner, text=label, bg=_C.PANEL, fg=_C.FG2,
                 font=(_C.FONT_LABEL[0], 8)).pack(anchor="w")

        self._entry = _tech_entry(inner, var, entry_width)
        self._entry.pack(fill="x")

    @property
    def entry(self):
        return self._entry


class UILogger:
    """科技风彩色日志器（v4 重写：深色背景 + 等宽字体）。"""

    _TAGS = {
        "INFO":  {"foreground": _C.FG},
        "WARN":  {"foreground": _C.YELLOW},
        "ERROR": {"foreground": _C.RED},
        "OK":    {"foreground": _C.GREEN},
        "PATH":  {"foreground": _C.CYAN},
        "TIME":  {"foreground": _C.FG3},
        "SEP":   {"foreground": _C.BORDER_LIT},
        "MISS":  {"foreground": _C.BG, "background": _C.RED},
    }

    def __init__(self, text_widget):
        self.text = text_widget
        self._init_tags()

    def _init_tags(self):
        for tag, cfg in self._TAGS.items():
            self.text.tag_configure(tag, **cfg)

    def _append(self, msg: str, tag: str = "INFO"):
        try:
            self.text.configure(state="normal")
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self.text.insert("end", f"[{ts}] ", "TIME")
            self.text.insert("end", msg + "\n", tag)
            self.text.see("end")
            self.text.configure(state="disabled")
        except Exception:
            pass

    def sep(self):                self._append("══════════════", "SEP")
    def info(self, msg: str):     self._append(msg, "INFO")
    def ok(self, msg: str):       self._append(msg, "OK")
    def warn(self, msg: str):     self._append(msg, "WARN")
    def error(self, msg: str):    self._append(msg, "ERROR")
    def miss(self, label: str):   self._append(f"[缺少] {label}", "MISS")
    def path(self, prefix: str, p: str):
        self._append(f"{prefix} {p}", "PATH")


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"单次出报告神器  {VERSION}")
        self.root.configure(bg=_C.BG)

        # 路径变量
        self.tma_path = tk.StringVar()
        self.lj_path  = tk.StringVar()

        self.tma_dir_presets = [
            r"\\192.168.0.105\ta\Data\TMA",
            r"\\192.168.0.105\ta\Data\TMA\实验室样品",
            r"\\192.168.0.105\ta\Data\TMA\三明样品",
            r"\\Win-ek6csi67pon\ta\Data\TMA",
            r"\\Win-ek6csi67pon\ta\Data\TMA\实验室样品",
            r"\\Win-ek6csi67pon\ta\Data\TMA\三明样品",
        ]
        self.lj_dir_presets = [
            r"\\192.168.0.200\粒度报告",
            r"\\192.168.0.105\SanMingLiJing",
            r"\\化工检测2\粒度报告",
            r"\\WIN-EK6CSI67PON\SanMingLiJing",
        ]
        self.last_tma_dir: Optional[str] = None
        self.last_lj_dir:  Optional[str] = None
        self.last_out_dir: Optional[str] = OUTPUT_DIR_DEFAULT

        try:
            self.tma_path.set(self.tma_dir_presets[0])
            self.lj_path.set(self.lj_dir_presets[0])
        except Exception:
            pass

        # 参数变量
        self.lj_value       = tk.StringVar()
        self.t1_value       = tk.StringVar()
        self.t2_value       = tk.StringVar()
        self.m_value        = tk.StringVar()
        self.h_value        = tk.StringVar()
        self.tma_value      = tk.StringVar()
        self.tmaname_value  = tk.StringVar()
        self._tmaname_source_path = ""
        self.weight_xlsx_var  = tk.StringVar(value=WEIGHT_XLSX_DEFAULT)
        self.template_pdf_var = tk.StringVar()

        # 状态变量（供状态栏）
        self._status_var = tk.StringVar(value="就绪")

        _setup_ttk_style(root)
        self._build_ui()

        self._algo_logger: logging.Logger = _make_algo_logger(self.logger, tk_root=self.root)

        self.script_dir = os.path.abspath(os.path.dirname(__file__))
        self.ls_dir     = os.path.join(self.script_dir, "ls")
        self.cache_dir  = os.path.join(self.script_dir, "cache")
        os.makedirs(self.ls_dir,    exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)

        # 自动探测 PDF 模板
        auto_tpl = self._auto_detect_template()
        if auto_tpl:
            self.template_pdf_var.set(auto_tpl)

        self._cached_tma_data: Optional[Tuple[List[float], List[float]]] = None

        ocr_tip = "OCR ✔" if _HAS_OCR else "OCR ✘ (缺 cv2/pytesseract)"
        self._status_var.set(f"就绪  |  {ocr_tip}")

        self.logger.sep()
        self.logger.info(f"单次出报告神器 {VERSION}  算法：tma_super_max_v219")
        self.logger.info("D50 OCR 可用（cv2 + pytesseract 已加载）" if _HAS_OCR
                         else "⚠ D50 OCR 不可用 — 请安装 opencv-python 与 pytesseract")

    # ══════════════════════════════════════════════════════════════════
    # 界面构建
    # ══════════════════════════════════════════════════════════════════

    def _build_ui(self):
        root = self.root

        # ── 顶部标题栏 ────────────────────────────────────────────────
        header = tk.Frame(root, bg=_C.PANEL, height=48)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        # 左侧青色竖条
        tk.Frame(header, width=4, bg=_C.CYAN).pack(side="left", fill="y")

        tk.Label(header, text="单次出报告神器",
                 bg=_C.PANEL, fg=_C.FG,
                 font=_C.FONT_TITLE).pack(side="left", padx=(14, 6), pady=10)

        # 版本徽章
        ver_badge = tk.Label(header, text=f" {VERSION} ",
                             bg=_C.CYAN_DIM, fg=_C.BG,
                             font=(_C.FONT_VER[0], 8, "bold"),
                             padx=4, pady=1)
        ver_badge.pack(side="left", pady=16)

        # 右侧：OCR 指示灯
        ocr_color = _C.GREEN if _HAS_OCR else _C.YELLOW
        ocr_text  = "● OCR" if _HAS_OCR else "● OCR ✘"
        tk.Label(header, text=ocr_text, bg=_C.PANEL, fg=ocr_color,
                 font=(_C.FONT_UI[0], 8)).pack(side="right", padx=14)

        # 分隔线
        tk.Frame(root, height=1, bg=_C.BORDER).pack(fill="x")

        # ── 主体区域 ──────────────────────────────────────────────────
        body = tk.Frame(root, bg=_C.BG)
        body.pack(fill="both", expand=True, padx=0, pady=0)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        # ── 上半：控制区（固定高度）──────────────────────────────────
        ctrl = tk.Frame(body, bg=_C.BG, padx=12, pady=8)
        ctrl.pack(fill="x", side="top")
        ctrl.columnconfigure(1, weight=1)

        # ─── 路径区 ───────────────────────────────────────────────────
        path_panel = tk.Frame(ctrl, bg=_C.PANEL,
                              highlightthickness=1,
                              highlightbackground=_C.BORDER)
        path_panel.grid(row=0, column=0, columnspan=3, sticky="ew",
                        pady=(0, 6))
        path_panel.columnconfigure(1, weight=1)

        tk.Label(path_panel, text="  数据路径",
                 bg=_C.PANEL, fg=_C.FG2,
                 font=(_C.FONT_LABEL[0], 8, "bold")).grid(
                     row=0, column=0, columnspan=3,
                     sticky="w", padx=8, pady=(6, 2))

        # TMA 行
        self._make_path_row(path_panel, row=1,
                            label="TMA 文件",
                            var=self.tma_path,
                            presets=self.tma_dir_presets,
                            btn_cmd=self.on_choose_tma,
                            combo_attr="tma_combo",
                            accent=_C.CYAN)
        self.tma_combo.bind("<<ComboboxSelected>>",
                            self._sync_tmaname_from_tma_path, add="+")
        self.tma_combo.bind("<FocusOut>",
                            self._sync_tmaname_from_tma_path, add="+")
        self.tma_combo.bind("<Return>",
                            self._sync_tmaname_from_tma_path, add="+")

        # 粒径行
        self._make_path_row(path_panel, row=2,
                            label="粒径文件",
                            var=self.lj_path,
                            presets=self.lj_dir_presets,
                            btn_cmd=self.on_choose_lj,
                            combo_attr="lj_combo",
                            accent=_C.ORANGE)

        # 称量 xlsx 行
        self._make_path_row(path_panel, row=3,
                            label="称量 xlsx",
                            var=self.weight_xlsx_var,
                            presets=[WEIGHT_XLSX_DEFAULT, WEIGHT_XLSX_FALLBACK],
                            btn_cmd=self._on_choose_weight_xlsx,
                            combo_attr=None,
                            is_entry=True,
                            accent=_C.YELLOW)

        # PDF 模板行
        self._make_path_row(path_panel, row=4,
                            label="PDF 模板",
                            var=self.template_pdf_var,
                            presets=[],
                            btn_cmd=self._on_choose_template_pdf,
                            combo_attr="template_combo",
                            is_entry=True,
                            accent=_C.GREEN)

        tk.Frame(path_panel, height=6, bg=_C.PANEL).grid(
            row=5, column=0, columnspan=3)

        # ─── 参数区 ───────────────────────────────────────────────────
        param_panel = tk.Frame(ctrl, bg=_C.PANEL,
                               highlightthickness=1,
                               highlightbackground=_C.BORDER)
        param_panel.grid(row=1, column=0, columnspan=3,
                         sticky="ew", pady=(0, 6))

        tk.Label(param_panel, text="  计算参数",
                 bg=_C.PANEL, fg=_C.FG2,
                 font=(_C.FONT_LABEL[0], 8, "bold")).grid(
                     row=0, column=0, columnspan=6,
                     sticky="w", padx=8, pady=(6, 4))

        # 参数字段定义：(label, var, accent_color, entry_width)
        fields_row1 = [
            ("D50 粒径", self.lj_value,  _C.ORANGE, 10),
            ("T1  °C",   self.t1_value,  _C.CYAN,   10),
            ("T2  °C",   self.t2_value,  _C.CYAN,   10),
        ]
        fields_row2 = [
            ("m   mg",   self.m_value,   _C.YELLOW, 10),
            ("H   μm",   self.h_value,   _C.GREEN,  10),
            ("TMA",      self.tma_value, _C.BTN_PRIMARY, 12),
        ]

        for col, (lbl, var, accent, ew) in enumerate(fields_row1):
            fb = _FieldBox(param_panel, lbl, var,
                           entry_width=ew, accent=accent)
            fb.grid(row=1, column=col, padx=(8, 4), pady=(0, 6), sticky="ew")
            param_panel.columnconfigure(col, weight=1)

        for col, (lbl, var, accent, ew) in enumerate(fields_row2):
            fb = _FieldBox(param_panel, lbl, var,
                           entry_width=ew, accent=accent)
            fb.grid(row=2, column=col, padx=(8, 4), pady=(0, 8), sticky="ew")

        # tmaname 同时驱动 PDF 占位符和默认输出文件名，可由用户手动覆盖。
        tmaname_box = _FieldBox(
            param_panel, "报告名称（tmaname，可修改）",
            self.tmaname_value, entry_width=48, accent=_C.CYAN)
        tmaname_box.grid(
            row=3, column=0, columnspan=3,
            padx=(8, 4), pady=(0, 8), sticky="ew")

        # ─── 操作按钮区 ───────────────────────────────────────────────
        btn_panel = tk.Frame(ctrl, bg=_C.BG)
        btn_panel.grid(row=2, column=0, columnspan=3,
                       sticky="ew", pady=(0, 4))

        # 按钮定义：(text, cmd, bg, accent, fg)
        btn_defs = [
            ("🚀 一键读取",       self.on_one_click_read,
             "#1a3a1a", "#56d364", _C.FG),
            ("⚡ 读取TMA",       self.on_auto_read,
             _C.BTN_PRIMARY, _C.BORDER_LIT, _C.FG),
            ("🔬 梯度计算",      self.on_super_read,
             "#1a3d5c", "#58c7ff", _C.FG),
            ("🔍 读取D50",       self.on_read_d50,
             _C.BTN_ACCENT, "#3dd6c0", _C.FG),
            ("⚖  读取重量",      self.on_read_m,
             "#3a2f10", _C.YELLOW, _C.FG),
            ("🖼  预览TMA图",     self.on_preview,
             _C.BTN_NEUTRAL, _C.BORDER_LIT, _C.FG),
            ("📄 生成报告",      self.on_generate,
             _C.BTN_SUCCESS, "#56d364", _C.FG),
            ("✕ 退出",           self.root.destroy,
             _C.BTN_DANGER, _C.RED, "#ffb3b0"),
        ]

        for i, (text, cmd, bg, accent, fg) in enumerate(btn_defs):
            b = _TechButton(btn_panel, text=text, command=cmd,
                            bg=bg, fg=fg, accent=accent,
                            height_px=30)
            b.pack(side="left", padx=(0, 6))

        # ── 下半：日志区 ──────────────────────────────────────────────
        log_header = tk.Frame(body, bg=_C.PANEL, height=24)
        log_header.pack(fill="x", padx=0)
        log_header.pack_propagate(False)

        tk.Frame(log_header, width=3, bg=_C.CYAN_DIM).pack(
            side="left", fill="y")
        tk.Label(log_header, text="  系统日志",
                 bg=_C.PANEL, fg=_C.FG2,
                 font=(_C.FONT_LABEL[0], 8, "bold")).pack(
                     side="left", pady=4)

        # 清空按钮
        clr = tk.Label(log_header, text="清空",
                       bg=_C.PANEL, fg=_C.FG3,
                       font=(_C.FONT_LABEL[0], 8),
                       cursor="hand2")
        clr.pack(side="right", padx=10)
        clr.bind("<Button-1>", lambda _: self._clear_log())
        clr.bind("<Enter>",    lambda _: clr.config(fg=_C.RED))
        clr.bind("<Leave>",    lambda _: clr.config(fg=_C.FG3))

        # 日志文本框（深色 + 等宽）
        log_frame = tk.Frame(body, bg=_C.BG)
        log_frame.pack(fill="both", expand=True, padx=0, pady=0)

        vsb = ttk.Scrollbar(log_frame, orient="vertical",
                            style="Tech.Vertical.TScrollbar")
        vsb.pack(side="right", fill="y")

        self.log_box = tk.Text(
            log_frame,
            bg=_C.BG,
            fg=_C.FG,
            insertbackground=_C.CYAN,
            selectbackground=_C.BORDER_LIT,
            selectforeground=_C.FG,
            font=_C.FONT_MONO,
            relief="flat",
            highlightthickness=0,
            wrap="word",
            height=12,
            yscrollcommand=vsb.set,
            padx=10,
            pady=6,
        )
        self.log_box.pack(side="left", fill="both", expand=True)
        self.log_box.configure(state="disabled")
        vsb.config(command=self.log_box.yview)

        # ── 底部状态栏 ────────────────────────────────────────────────
        tk.Frame(root, height=1, bg=_C.BORDER).pack(fill="x")
        status_bar = tk.Frame(root, bg=_C.PANEL, height=22)
        status_bar.pack(fill="x", side="bottom")
        status_bar.pack_propagate(False)

        tk.Frame(status_bar, width=3, bg=_C.CYAN_DIM).pack(
            side="left", fill="y")
        tk.Label(status_bar, textvariable=self._status_var,
                 bg=_C.PANEL, fg=_C.FG3,
                 font=(_C.FONT_VER[0], 8)).pack(side="left", padx=8)

        # 右侧：路径快捷提示
        tk.Label(status_bar,
                 text=f"./ls  ./cache",
                 bg=_C.PANEL, fg=_C.BORDER,
                 font=(_C.FONT_VER[0], 8)).pack(side="right", padx=8)

        # ── 绑定 UILogger（必须最后）─────────────────────────────────
        self.logger = UILogger(self.log_box)

    # ── 路径行构建辅助 ────────────────────────────────────────────────
    def _make_path_row(self, parent, row: int,
                       label: str, var: tk.StringVar,
                       presets: list, btn_cmd,
                       combo_attr: Optional[str],
                       accent: str = _C.CYAN,
                       is_entry: bool = False):
        """在 parent 网格中创建一行路径选择控件。"""
        # 彩色标签点
        dot_frame = tk.Frame(parent, bg=_C.PANEL, width=28)
        dot_frame.grid(row=row, column=0, sticky="ns", padx=(8, 0), pady=3)
        dot_frame.pack_propagate(False)
        tk.Label(dot_frame, text="●", bg=_C.PANEL, fg=accent,
                 font=(_C.FONT_LABEL[0], 7)).pack(pady=8)

        # 标签文字
        tk.Label(parent, text=label, bg=_C.PANEL, fg=_C.FG2,
                 width=9, anchor="e",
                 font=_C.FONT_LABEL).grid(
                     row=row, column=0, sticky="e", padx=(0, 6), pady=3)

        # 输入控件（Combobox 或 Entry）
        if is_entry:
            inp = _tech_entry(parent, var, width=60)
            inp.grid(row=row, column=1, sticky="ew", padx=(0, 6), pady=3)
        else:
            inp = ttk.Combobox(parent, textvariable=var,
                               values=presets, style="Tech.TCombobox",
                               state="normal")
            inp.grid(row=row, column=1, sticky="ew", padx=(0, 6), pady=3)
            if combo_attr:
                setattr(self, combo_attr, inp)

        parent.columnconfigure(1, weight=1)

        # 选择按钮
        btn = _TechButton(parent, text="选择",
                          command=btn_cmd,
                          bg=_C.BTN_NEUTRAL, fg=_C.FG,
                          accent=accent,
                          width_px=52, height_px=24)
        btn.grid(row=row, column=2, padx=(0, 8), pady=3)

    # ── 日志清空 ──────────────────────────────────────────────────────
    def _clear_log(self):
        try:
            self.log_box.configure(state="normal")
            self.log_box.delete("1.0", "end")
            self.log_box.configure(state="disabled")
        except Exception:
            pass

    # ── 状态栏更新 ────────────────────────────────────────────────────
    def _set_status(self, msg: str):
        try:
            self._status_var.set(msg)
        except Exception:
            pass

    # ── 后台线程支持 ──────────────────────────────────────────────────
    def _set_status_safe(self, msg: str):
        """线程安全的状态栏更新。"""
        try:
            self.root.after(0, lambda: self._set_status(msg))
        except Exception:
            pass

    def _log_safe(self, method: str, msg: str = ""):
        """线程安全的日志写入。"""
        try:
            if method == "sep":
                self.root.after(0, lambda: self.logger.sep())
            else:
                self.root.after(0, lambda: getattr(self.logger, method)(msg))
        except Exception:
            pass

    def _run_in_thread(self, target, *args, **kwargs):
        """在后台线程执行 target，执行期间禁用所有按钮，完成后恢复。"""
        def _worker():
            try:
                target(*args, **kwargs)
            except Exception as e:
                self.root.after(0, lambda: self.logger.error(f"后台异常：{e}"))
            finally:
                self.root.after(0, lambda: _TechButton.set_all_enabled(True))
                self.root.after(0, lambda: self._set_status("就绪"))
        _TechButton.set_all_enabled(False)
        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    # ══════════════════════════════════════════════════════════════════
    # 以下方法与 v3 完全一致，仅增加状态栏更新调用
    # ══════════════════════════════════════════════════════════════════

    def _pick_initialdir(self, cur: str, last_dir: Optional[str],
                         presets: List[str]) -> str:
        cur = normalize_path_separators((cur or "").strip())
        try:
            if cur:
                if os.path.isdir(cur):   return cur
                if os.path.isfile(cur):  return os.path.dirname(cur)
            if last_dir and os.path.isdir(last_dir): return last_dir
        except Exception:
            pass
        return _first_available_path(presets) or os.getcwd()

    def _remember_dir_in_combo(self, combo, preset_list: List[str], new_dir: str):
        nd = (new_dir or "").strip()
        if not nd or nd in preset_list: return
        preset_list.insert(0, nd)
        if len(preset_list) > 12: del preset_list[12:]
        try:
            combo.configure(values=preset_list)
        except Exception:
            pass

    def _sync_tmaname_from_tma_path(self, _event=None, *, force: bool = False) -> str:
        """TMA 路径变化时填入默认名称；同一路径上的人工修改保持不变。"""
        path = normalize_path_separators((self.tma_path.get() or "").strip())
        default_name = _default_tmaname_from_path(path)
        current_name = (self.tmaname_value.get() or "").strip()
        if not default_name:
            return current_name

        # 下拉预设是目录，不应把目录名误写成 tmaname。
        has_file_extension = bool(os.path.splitext(os.path.basename(path))[1])
        if not force and not has_file_extension:
            return current_name

        source_key = os.path.normcase(os.path.normpath(path))
        source_changed = source_key != self._tmaname_source_path
        if force or source_changed or not current_name:
            self._tmaname_source_path = source_key
            if threading.current_thread() is threading.main_thread():
                self.tmaname_value.set(default_name)
            else:
                self.root.after(
                    0, lambda name=default_name: self.tmaname_value.set(name))
            return default_name
        return current_name

    def on_choose_tma(self):
        init = self._pick_initialdir(self.tma_path.get(), self.last_tma_dir, self.tma_dir_presets)
        path = filedialog.askopenfilename(
            title="选择 TMA 文件", initialdir=init,
            filetypes=[("全部文件", "*.*"),
                       ("TMA 数据/图片", "*.txt;*.001;*.002;*.003;*.004;*.005;*.png;*.tif;*.tiff")])
        if not path: return
        path = normalize_path_separators(path.strip())
        self.tma_path.set(path)
        self._sync_tmaname_from_tma_path(force=True)
        self._cached_tma_data = None
        try:
            self.last_tma_dir = os.path.dirname(path)
            self._remember_dir_in_combo(self.tma_combo, self.tma_dir_presets, self.last_tma_dir)
        except Exception: pass
        self.logger.sep()
        self.logger.info(f"TMA 文件: {path}")
        self._set_status(f"已选 TMA: {os.path.basename(path)}")
        if os.path.splitext(path)[1].lower() in [".png", ".tif", ".tiff"]:
            self.logger.warn("选的是图片：T1/T2/TMA/m/H 需要手动填入")

    def on_choose_lj(self):
        init = self._pick_initialdir(self.lj_path.get(), self.last_lj_dir, self.lj_dir_presets)
        path = filedialog.askopenfilename(
            title="选择粒径文件", initialdir=init,
            filetypes=[("全部文件", "*.*"), ("粒径PDF/PNG", "*.pdf;*.png")])
        if not path: return
        path = normalize_path_separators(path.strip())
        self.lj_path.set(path)
        try:
            self.last_lj_dir = os.path.dirname(path)
            self._remember_dir_in_combo(self.lj_combo, self.lj_dir_presets, self.last_lj_dir)
        except Exception: pass
        self.logger.sep()
        self.logger.info(f"粒径文件: {path}")
        self._set_status(f"已选粒径: {os.path.basename(path)}")
        ext = os.path.splitext(path)[1].lower()
        if ext == ".png":
            self.logger.warn("png 粒径：请手动填入或点【读取D50 OCR】")
        elif ext == ".pdf":
            self.logger.info("pdf 粒径：生成报告时自动转 PNG 并触发 OCR")

    def _on_choose_weight_xlsx(self):
        cur  = (self.weight_xlsx_var.get() or "").strip()
        init = os.path.dirname(cur) if cur and os.path.isfile(cur) else os.getcwd()
        path = filedialog.askopenfilename(
            title="选择 TMA称量数据 xlsx", initialdir=init,
            filetypes=[("Excel", "*.xlsx *.xls"), ("全部文件", "*.*")])
        if path:
            self.weight_xlsx_var.set(normalize_path_separators(path.strip()))
            self.logger.info(f"称量xlsx: {path}")
            self._set_status(f"M 数据源: {os.path.basename(path)}")

    # ── PDF 模板 ─────────────────────────────────────────────────────
    def _auto_detect_template(self) -> Optional[str]:
        """自动探测脚本目录下的 PDF 模板，优先 w456，其次 template.pdf。"""
        try:
            pdfs = [f for f in os.listdir(self.script_dir) if f.lower().endswith(".pdf")]
            w456 = sorted([f for f in pdfs if "w456" in f.lower()])
            if w456:
                return os.path.join(self.script_dir, w456[0])
            fb = os.path.join(self.script_dir, "template.pdf")
            if os.path.isfile(fb):
                return fb
        except Exception:
            pass
        return None

    def _on_choose_template_pdf(self):
        cur  = (self.template_pdf_var.get() or "").strip()
        init = os.path.dirname(cur) if cur and os.path.isfile(cur) else self.script_dir
        path = filedialog.askopenfilename(
            title="选择 PDF 模板", initialdir=init,
            filetypes=[("PDF 模板", "*.pdf"), ("全部文件", "*.*")])
        if path:
            self.template_pdf_var.set(normalize_path_separators(path.strip()))
            self.logger.info(f"PDF 模板: {path}")
            self._set_status(f"模板: {os.path.basename(path)}")

    # ── D50 OCR（线程安全版）─────────────────────────────────────────
    def _ocr_d50_span_from_lj_png(self, png_path: str, force: bool = False) -> bool:
        if not _HAS_OCR:
            self._log_safe("warn", "D50 OCR 不可用（缺少 cv2/pytesseract）。")
            return False
        if not force and (self.lj_value.get() or "").strip():
            return True
        stem       = os.path.splitext(os.path.basename(png_path))[0]
        cache_path = _lj_cache_path(self.cache_dir, stem)
        if not force:
            cached = _load_json_cache(cache_path)
            if cached and cached.get("source_png") == png_path:
                d50  = cached.get("d50")
                span = cached.get("span")
                if d50:
                    _d, _s = str(d50), span
                    self.root.after(0, lambda: (
                        self.lj_value.set(_d),
                        self._set_status(f"D50={_d}（缓存）"),
                    ))
                    self._log_safe("ok",
                        f"✅ D50 命中缓存（{cached.get('timestamp','')}）"
                        f"：D50={d50}" + (f"  Span={span}" if span else ""))
                    return True
        self._log_safe("info", f"OCR 识别粒径图: {os.path.basename(png_path)}")
        self._set_status_safe("OCR 识别中…")
        d50_str, span_str, crop_paths = extract_d50_span_from_png(png_path, self.cache_dir)
        record = {
            "d50": d50_str, "span": span_str,
            "source_png": png_path,
            "timestamp":  datetime.datetime.now().isoformat(timespec="seconds"),
            "crop_d50":   crop_paths.get("D50", ""),
            "crop_span":  crop_paths.get("Span", ""),
        }
        _save_json_cache(cache_path, record)
        if d50_str:
            _d50, _sp = d50_str, span_str or "—"
            self.root.after(0, lambda: (
                self.lj_value.set(_d50),
                self._set_status(f"D50={_d50}  Span={_sp}"),
            ))
            self._log_safe("ok",
                f"✅ OCR → D50={d50_str}"
                + (f"  Span={span_str}" if span_str else "")
                + f"  切片: {crop_paths.get('D50','N/A')}")
            return True
        else:
            self._log_safe("warn", f"OCR 未识别到有效 D50，切片: {crop_paths.get('D50','N/A')}")
            self._set_status_safe("OCR 未识别到 D50")
            return False

    def on_read_d50(self):
        def _worker():
            self._log_safe("sep", "")
            lj_path = normalize_path_separators((self.lj_path.get() or "").strip())
            if not lj_path or not os.path.isfile(lj_path):
                self._log_safe("error", "请先选择有效的粒径文件（PDF 或 PNG）。")
                return
            ext = os.path.splitext(lj_path)[1].lower()
            if ext == ".pdf":
                png_path = self._pdf_to_png_only(lj_path)
                if not png_path: return
            elif ext == ".png":
                png_path = lj_path
            else:
                self._log_safe("warn", "粒径文件不是 pdf/png，无法执行 OCR。")
                return
            self._ocr_d50_span_from_lj_png(png_path, force=True)
        self._run_in_thread(_worker)

    # ── M 查询 ────────────────────────────────────────────────────────
    def _read_m_and_fill(self, force: bool = False) -> bool:
        if not force and (self.m_value.get() or "").strip():
            return True
        tma_path = normalize_path_separators((self.tma_path.get() or "").strip())
        if not tma_path or not os.path.isfile(tma_path):
            self._log_safe("warn", "TMA 路径无效，跳过 M 查询。")
            return False
        stem       = os.path.splitext(os.path.basename(tma_path))[0]
        xlsx_path  = normalize_path_separators((self.weight_xlsx_var.get() or "").strip())
        if not xlsx_path: xlsx_path = WEIGHT_XLSX_DEFAULT
        if xlsx_path == WEIGHT_XLSX_DEFAULT:
            selected_xlsx = _first_available_path(
                [WEIGHT_XLSX_DEFAULT, WEIGHT_XLSX_FALLBACK], file_only=True)
            if selected_xlsx != xlsx_path:
                xlsx_path = selected_xlsx
                self.weight_xlsx_var.set(xlsx_path)
                self._log_safe("warn", "IP 称量路径不可用，已切换到原主机名备用线路。")
        cache_path = _m_cache_path(self.cache_dir, stem)
        if not force:
            cached = _load_json_cache(cache_path)
            if cached and cached.get("xlsx_path") == xlsx_path:
                m_val   = cached.get("m")
                matched = cached.get("matched_key", "")
                ts      = cached.get("timestamp", "")
                if m_val is not None:
                    _m = str(m_val)
                    self.root.after(0, lambda: (
                        self.m_value.set(_m),
                        self._set_status(f"M={_m}（缓存）"),
                    ))
                    self._log_safe("ok", f"✅ M 命中缓存（{ts}）：M={m_val}  [{matched}]")
                    return True
        self._log_safe("info", f"查询 M: {xlsx_path}")
        self._set_status_safe("查询 M 中…")
        m_val, info = lookup_mass(tma_path, xlsx_path)
        record = {
            "m": m_val, "matched_key": info if m_val is not None else "",
            "info": info,
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "xlsx_path": xlsx_path, "stem": stem,
        }
        _save_json_cache(cache_path, record)
        if m_val is None:
            self._log_safe("warn", f"M 未找到：{info}")
            self._set_status_safe("M 未找到")
            return False
        try:
            m_str = f"{float(m_val):.4f}".rstrip("0").rstrip(".")
        except Exception:
            m_str = str(m_val)
        self.root.after(0, lambda: (
            self.m_value.set(m_str),
            self._set_status(f"M={m_str}"),
        ))
        self._log_safe("ok", f"✅ M={m_str}  匹配：{info}")
        return True

    def on_read_m(self):
        def _worker():
            self._log_safe("sep", "")
            self._read_m_and_fill(force=True)
        self._run_in_thread(_worker)

    # ── 核心 TMA 读取（线程安全版）────────────────────────────────────
    def _read_tma_and_fill(self, mode: str):
        in_path = normalize_path_separators((self.tma_path.get() or "").strip())
        if not in_path or not os.path.isfile(in_path):
            self._log_safe("error", "TMA 路径无效，请先选择文件。")
            return
        ext = os.path.splitext(in_path)[1].lower()
        if ext in [".png", ".tif", ".tiff"]:
            self._log_safe("warn", "TMA 选的是图片：请手填 T1/T2/H/TMA/m。")
            return
        self._log_safe("info", "读取 TMA 数据中…")
        self._set_status_safe("读取 TMA 中…")
        try:
            text, meta = load_text_prefer_tajm(in_path, self._algo_logger)
            if meta.get("used") == "tajm":
                self._log_safe("ok", f"✅ 解密读取（rows={meta.get('rows')}）")
            else:
                if meta.get("tajm_err"):
                    self._log_safe("warn", f"TAJM 解密失败，已回退纯文本：{meta.get('tajm_err')}")
                self._log_safe("ok", "✅ 文本读取完成")

            parsed = parse_lines(text)
            xs, ys, _idxs = extract_xy_from_file(parsed, self._algo_logger)
            if not xs:
                raise ValueError("没有提取到 StartOfData 数据段，请确认文件格式。")
            self._log_safe("info", f"数据点：{len(xs)}  温度：{min(xs):.1f}~{max(xs):.1f}°C")
            self._cached_tma_data = (xs, ys)

            if mode == "super":
                T1, T2, meta2 = detect_T2_T1_super_gradient(xs, ys, self._algo_logger)
                alg = "超级梯度"
            else:
                T1, T2, meta2 = detect_T2_T1_precise(xs, ys, self._algo_logger)
                alg = "梯度"

            self._log_safe("ok",
                f"✅ {alg}  T1={T1:.4f}°C  T2={T2:.4f}°C"
                f"  分支={meta2.get('mode','?')}  置信={meta2.get('confidence',0):.2f}")

            cc = build_curve_cache(xs, ys)
            H1 = interpolate_curve_height(T1, cc)
            H2 = interpolate_curve_height(T2, cc)
            H  = H2 - H1
            self._log_safe("info",
                f"H1={format_height_um(H1)}  H2={format_height_um(H2)}  H={format_height_um(H)} μm")

            _t1s, _t2s, _hs = f"{T1:.2f}", f"{T2:.2f}", format_height_um(H)
            _status = f"T1={T1:.2f}  T2={T2:.2f}  H={_hs}μm"
            self.root.after(0, lambda: (
                self.t1_value.set(_t1s),
                self.t2_value.set(_t2s),
                self.h_value.set(_hs),
                self._set_status(_status),
            ))

        except Exception as e:
            self._cached_tma_data = None
            self._log_safe("error", f"读取/识别失败：{e}")
            self._set_status_safe("读取失败")

    def _try_update_tma_from_mh(self, force: bool = False):
        m_str = (self.m_value.get() or "").strip()
        h_str = (self.h_value.get() or "").strip()
        if not m_str or not h_str: return
        try:
            mg = float(m_str)
            H  = float(h_str)
            if mg <= 0 or H <= 0:
                self._log_safe("warn", "m 或 H 非正数，跳过 TMA 计算。")
                return
            cur = (self.tma_value.get() or "").strip()
            if (not force) and cur: return
            tma = calc_tma_from_m_h(mg, H)
            _t = f"{tma:.3f}"
            self.root.after(0, lambda: (
                self.tma_value.set(_t),
                self._set_status(f"TMA={_t}"),
            ))
            self._log_safe("ok", f"TMA = {tma:.3f}  (m={mg}, H={H})")
        except Exception as e:
            self._log_safe("warn", f"TMA 计算失败：{e}")

    def on_one_click_read(self):
        """一键读取 TMA + D50 + M，并自动回填所有字段。"""
        def _worker():
            self._log_safe("info", "═══ 一键读取开始 ═══")
            self._set_status_safe("一键读取中…")

            # 1. 读取 TMA（自动模式）
            try:
                self._read_tma_and_fill(mode="auto")
            except Exception as e:
                self._log_safe("error", f"TMA 读取异常：{e}")

            # 2. 读取 D50 OCR
            lj_path = normalize_path_separators((self.lj_path.get() or "").strip())
            if lj_path and os.path.isfile(lj_path):
                try:
                    ext = os.path.splitext(lj_path)[1].lower()
                    if ext == ".pdf":
                        png_path = self._pdf_to_png_only(lj_path)
                        if png_path:
                            self._ocr_d50_span_from_lj_png(png_path, force=True)
                        else:
                            self._log_safe("error", "D50：PDF 转 PNG 失败。")
                    elif ext == ".png":
                        self._ocr_d50_span_from_lj_png(lj_path, force=True)
                    else:
                        self._log_safe("warn", "D50：粒径文件不是 pdf/png，跳过 OCR。")
                except Exception as e:
                    self._log_safe("error", f"D50 读取异常：{e}")
            else:
                self._log_safe("warn", "D50：未选择粒径文件，跳过。")

            # 3. 读取 M
            try:
                self._read_m_and_fill(force=True)
            except Exception as e:
                self._log_safe("error", f"M 读取异常：{e}")

            # 4. 尝试自动计算 TMA
            self._try_update_tma_from_mh()

            self._log_safe("info", "═══ 一键读取完成 ═══")
            self._set_status_safe("一键读取完成")

        self._run_in_thread(_worker)

    def on_auto_read(self):
        def _worker():
            self._log_safe("sep", "")
            self._set_status_safe("自动读取中…")
            self._read_tma_and_fill(mode="auto")
            self._try_update_tma_from_mh(force=True)
            _ = self._ensure_lj_png()
            if not (self.m_value.get() or "").strip():
                self._read_m_and_fill(force=False)
            self._try_update_tma_from_mh(force=False)
        self._run_in_thread(_worker)

    def on_super_read(self):
        def _worker():
            self._log_safe("sep", "")
            self._set_status_safe("超级梯度中…")
            self._read_tma_and_fill(mode="super")
            self._try_update_tma_from_mh(force=True)
            _ = self._ensure_lj_png()
            if not (self.m_value.get() or "").strip():
                self._read_m_and_fill(force=False)
            self._try_update_tma_from_mh(force=False)
        self._run_in_thread(_worker)

    def on_preview(self):
        def _worker():
            self._log_safe("sep", "")
            tma_path = normalize_path_separators((self.tma_path.get() or "").strip())
            if not tma_path or not os.path.exists(tma_path):
                self._log_safe("error", "未选择有效的 TMA 文件路径，无法预览。")
                return
            ext = os.path.splitext(tma_path)[1].lower()
            if ext not in [".png", ".tif", ".tiff"]:
                if not (self.t1_value.get().strip() and
                        self.t2_value.get().strip() and
                        self.h_value.get().strip()):
                    self._log_safe("info", "T1/T2/H 未填写，先自动读取…")
                    self._read_tma_and_fill(mode="auto")
            values = {
                "qifawd":  (self.t1_value.get() or "").strip(),
                "zuidawd": (self.t2_value.get() or "").strip(),
            }
            if ext in [".tif", ".tiff"]:
                tif_path = tma_path
            else:
                tif_path = self._ensure_tma_tif(
                    {**values, "lijing": "", "tmamd": "", "shengchan": "", "tmaname": ""})
            if not tif_path or not os.path.exists(tif_path):
                self._log_safe("error", "未能生成预览 tif。")
                return
            # 预览窗口必须在主线程创建
            _tif = tif_path
            self.root.after(0, lambda: self._show_preview_window(_tif))
        self._run_in_thread(_worker)

    def _cleanup_temp_preview_files(self):
        """及时清理 _preview_cache 里的 temp_ 预览文件。"""
        try:
            preview_dir = os.path.join(self.ls_dir, "_preview_cache")
            if not os.path.isdir(preview_dir):return
            removed = 0
            for fn in os.listdir(preview_dir):
                if not fn.lower().startswith("temp_"):continue
                if not fn.lower().endswith((".tif", ".tiff", ".png", ".jpg", ".jpeg")):continue
                p = os.path.join(preview_dir, fn)
                if not os.path.isfile(p):continue
                try:
                    os.remove(p)
                    removed += 1
                except Exception:
                    # 如果文件正被系统或旧窗口占用，就跳过，下次再清
                    pass

            if removed > 0:self.logger.info(f"已清理临时预览文件：{removed} 个")
        except Exception as e:
            try:self.logger.warn(f"清理临时预览文件失败：{e}")
            except Exception:pass

    def _show_preview_window(self, tif_path: str):
        """在主线程中创建预览窗口（先复制预览副本，再打开副本）。"""
        try:
            src_path = os.path.abspath(tif_path)
            # 预览副本目录
            preview_dir = os.path.join(self.ls_dir, "_preview_cache")
            os.makedirs(preview_dir, exist_ok=True)
            # 每次生成新预览前，先清理旧 temp_ 文件
            self._cleanup_temp_preview_files()
            # 给预览副本一个唯一文件名，避免和正在显示的旧预览冲突
            stem = os.path.splitext(os.path.basename(src_path))[0]
            safe_stem = _safe_stem(stem).replace("#", "")
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            preview_path = os.path.join(
                preview_dir,
                f"temp_{safe_stem}_{stamp}_{_rand_suffix4()}.tif")
            # 先复制一份，再预览复制件
            shutil.copy2(src_path, preview_path)
            win = tk.Toplevel(self.root)
            win.title("TMA 预览")
            win.configure(bg=_C.BG)
            # 打开的是“预览副本”，不是原文件
            with Image.open(preview_path) as img:
                img.load()
                scale = min(1100 / img.width, 650 / img.height, 1.0)
                img2 = img.resize(
                    (max(1, int(img.width * scale)),max(1, int(img.height * scale))),
                    resample=Image.LANCZOS)
            photo = ImageTk.PhotoImage(img2)
            lbl = tk.Label(win, image=photo, bg=_C.BG)
            lbl.image = photo
            lbl.pack(padx=10, pady=10)
            # 显示原始文件路径
            tk.Label(
                win,
                text=f"原文件：{src_path}",
                bg=_C.BG,
                fg=_C.FG3,
                font=_C.FONT_MONO,
                wraplength=1080,
                justify="left"
            ).pack(padx=10, pady=(0, 4))

            # 显示预览副本路径（可选）
            tk.Label(
                win,
                text=f"预览副本：{preview_path}",
                bg=_C.BG,
                fg=_C.FG3,
                font=_C.FONT_MONO,
                wraplength=1080,
                justify="left"
            ).pack(padx=10, pady=(0, 10))

            def _on_close():
                try:lbl.image = None
                except Exception:pass
                try:win.destroy()
                except Exception:pass
                # 关闭窗口后尝试删除预览副本
                try:
                    if os.path.exists(preview_path):os.remove(preview_path)
                except Exception:
                    pass
            win.protocol("WM_DELETE_WINDOW", _on_close)
            self.logger.ok(f"✅ 预览: {src_path}")
            self.logger.info(f"预览副本: {preview_path}")
        except Exception as e:self.logger.error(f"预览失败：{e}")

    def _pdf_to_png_only(self, pdf_path: str) -> Optional[str]:
        base    = os.path.splitext(os.path.basename(pdf_path))[0]
        out_png = os.path.join(self.ls_dir, f"{base}.png")
        self._log_safe("info", "粒径 PDF → PNG…")
        self._set_status_safe("PDF 转 PNG…")
        try:
            png_path = pdf_first_page_to_png(pdf_path, out_png, zoom=2.0)
            self._log_safe("ok", f"✅ PNG: {png_path}")
            self.root.after(0, lambda: self.lj_path.set(png_path))
            return png_path
        except Exception as e:
            self._log_safe("error", f"PDF 转 PNG 失败：{e}")
            return None

    def _ensure_lj_png(self) -> Optional[str]:
        path = normalize_path_separators((self.lj_path.get() or "").strip())
        if not path or not os.path.isfile(path):
            self._log_safe("error", "粒径路径无效")
            return None
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            png_path = self._pdf_to_png_only(path)
            if not png_path: return None
            if not (self.lj_value.get() or "").strip():
                self._ocr_d50_span_from_lj_png(png_path, force=False)
            return png_path
        if ext == ".png":
            if not (self.lj_value.get() or "").strip():
                self._ocr_d50_span_from_lj_png(path, force=False)
            return path
        self._log_safe("warn", "粒径文件不是 pdf/png。")
        return None

    def _ensure_tma_tif(self, values: Dict[str, str]) -> Optional[str]:
        tma_path = normalize_path_separators((self.tma_path.get() or "").strip())
        ext = os.path.splitext(tma_path)[1].lower()
        if ext in [".tif", ".tiff"]: return tma_path
        if ext == ".png":
            try:
                base    = os.path.splitext(os.path.basename(tma_path))[0]
                out_tif = os.path.join(self.ls_dir, f"{base}.tif")
                img     = Image.open(tma_path).convert("RGB")
                tw, th  = 3840, 2160
                scale   = min(tw / img.width, th / img.height)
                new_w   = max(1, int(img.width  * scale))
                new_h   = max(1, int(img.height * scale))
                img2    = img.resize((new_w, new_h), resample=Image.LANCZOS)
                canvas  = Image.new("RGB", (tw, th), (255, 255, 255))
                canvas.paste(img2, ((tw - new_w) // 2, (th - new_h) // 2))
                draw = ImageDraw.Draw(canvas)
                try:   font = ImageFont.truetype("arial.ttf", 36)
                except Exception: font = ImageFont.load_default()
                try:
                    bbox = draw.textbbox((0, 0), VERSION, font=font)
                    tw2, th2 = bbox[2]-bbox[0], bbox[3]-bbox[1]
                except Exception:
                    tw2, th2 = 30, 12
                draw.text((tw - tw2 - 20, th - th2 - 12), VERSION,
                          fill=(0, 0, 0), font=font)
                canvas.save(out_tif, format="TIFF", dpi=(300, 300))
                self._log_safe("ok", f"✅ TMA png → tif: {out_tif}")
                return out_tif
            except Exception as e:
                self._log_safe("error", f"TMA png 转 tif 失败：{e}")
                return None
        if self._cached_tma_data is None:
            self._log_safe("info", "无 TMA 缓存，重新读取…")
            self._read_tma_and_fill(mode="auto")
        if self._cached_tma_data is None:
            self._log_safe("error", "无 TMA 数据，无法生成 tif")
            return None
        xs, ys = self._cached_tma_data
        try:
            T1 = float(values["qifawd"])
            T2 = float(values["zuidawd"])
            H  = float(self.h_value.get().strip())
        except Exception as e:
            self._log_safe("error", f"T1/T2/H 解析失败：{e}")
            return None
        base    = os.path.splitext(os.path.basename(tma_path))[0]
        out_tif = os.path.join(self.ls_dir, f"{base}.tif")
        mg_text = (self.m_value.get() or "x").strip() or "x"
        self._log_safe("info", "生成 TMA tif 图…")
        self._set_status_safe("生成 TMA 图…")
        try:
            generate_tma_tif(xs, ys, T1, T2, H, mg_text, out_tif, version=VERSION)
            self._log_safe("ok", f"✅ TMA tif: {out_tif}")
            return out_tif
        except Exception as e:
            self._log_safe("error", f"生成 TMA tif 失败：{e}")
            return None

    def _validate_and_collect(self) -> Tuple[bool, Dict[str, str]]:
        miss = []
        tma_path = normalize_path_separators((self.tma_path.get() or "").strip())
        lj_path  = normalize_path_separators((self.lj_path.get()  or "").strip())
        if not tma_path: miss.append("tma路径")
        if not lj_path:  miss.append("粒径路径")
        lj  = (self.lj_value.get()  or "").strip()
        t1  = (self.t1_value.get()  or "").strip()
        t2  = (self.t2_value.get()  or "").strip()
        m   = (self.m_value.get()   or "").strip()
        H   = (self.h_value.get()   or "").strip()
        tma = (self.tma_value.get() or "").strip()
        if not lj:  miss.append("粒径（D50）")
        if not t1:  miss.append("T1")
        if not t2:  miss.append("T2")
        has_tma = bool(tma)
        has_mh  = bool(m) and bool(H)
        if not has_tma and not has_mh: miss.append("TMA（或 m+H）")
        if miss:
            self._log_safe("error", "信息不全，无法生成报告。缺少项如下：")
            for x in miss: self._log_safe("miss", x)
            return False, {}
        if not has_tma:
            try:
                tma_calc = calc_tma_from_m_h(float(m), float(H))
                tma = f"{tma_calc:.3f}"
                self.root.after(0, lambda: self.tma_value.set(tma))
                self._log_safe("ok", f"TMA = {tma}（由 m/H 计算）")
            except Exception as e:
                self._log_safe("error", f"TMA 计算失败：{e}")
                return False, {}
        tmaname = self._sync_tmaname_from_tma_path()
        if not tmaname:
            tmaname = _default_tmaname_from_path(tma_path)
        if not tmaname:
            self._log_safe("error", "报告名称（tmaname）不能为空。")
            return False, {}
        today   = datetime.datetime.now().strftime("%Y/%m/%d")
        def _fmt(v, nd):
            try: return f"{float(v):.{nd}f}"
            except Exception: return v
        return True, {
            "lijing":    lj,
            "qifawd":    _fmt(t1,  2),
            "zuidawd":   _fmt(t2,  2),
            "tmamd":     _fmt(tma, 3),
            "shengchan": today,
            "tmaname":   tmaname,
        }

    def on_generate(self):
        def _worker():
            try:
                self._log_safe("sep", "")
                self._log_safe("info", "准备生成 COA 报告…")
                self._set_status_safe("生成报告中…")
                ok, values = self._validate_and_collect()
                if not ok:
                    self.root.after(0, lambda: _TechButton.set_all_enabled(True))
                    return
                lj_png  = self._ensure_lj_png()
                if not lj_png:
                    self.root.after(0, lambda: _TechButton.set_all_enabled(True))
                    return
                tma_tif = self._ensure_tma_tif(values)
                if not tma_tif:
                    self.root.after(0, lambda: _TechButton.set_all_enabled(True))
                    return
                # 文件对话框必须在主线程执行，传入预计算结果
                _v, _lj, _tif = values, lj_png, tma_tif
                self.root.after(0, lambda: self._generate_save_dialog(_v, _lj, _tif))
            except Exception as e:
                self.root.after(0, lambda: self.logger.error(f"生成异常：{e}"))
                self.root.after(0, lambda: _TechButton.set_all_enabled(True))
        _TechButton.set_all_enabled(False)
        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _generate_save_dialog(self, values: dict, lj_png: str, tma_tif: str):
        """在主线程中弹出保存对话框，再在后台线程中执行生成。"""
        report_name = (values.get("tmaname") or "").strip()
        safe_report_name = _safe_stem(report_name).strip().rstrip(". ") or "COA"
        default_nm = f"{safe_report_name}_{_rand_suffix4()}.pdf"
        initial_out_dir = _first_available_path([
            self.last_out_dir or "",
            OUTPUT_DIR_DEFAULT,
            OUTPUT_DIR_FALLBACK,
        ]) or OUTPUT_DIR_DEFAULT
        out_pdf    = filedialog.asksaveasfilename(
            title="保存 COA 报告",
            defaultextension=".pdf",
            initialdir=initial_out_dir,
            initialfile=default_nm,
            filetypes=[("PDF", "*.pdf")])
        if not out_pdf:
            self.logger.warn("已取消保存")
            self._set_status("就绪")
            _TechButton.set_all_enabled(True)
            return
        try:
            out_dir = os.path.dirname(out_pdf)
            if out_dir: self.last_out_dir = out_dir
        except Exception: pass
        # PDF 生成放到后台线程
        _TechButton.set_all_enabled(False)
        def _gen_worker():
            self._do_generate_pdf(values, lj_png, tma_tif, out_pdf)
            self.root.after(0, lambda: _TechButton.set_all_enabled(True))
            self.root.after(0, lambda: self._set_status("就绪"))
        t = threading.Thread(target=_gen_worker, daemon=True)
        t.start()

    def _do_generate_pdf(self, values: dict, lj_png: str, tma_tif: str, out_pdf: str):
        """后台线程：生成 PDF。"""
        # 优先使用用户手动选择的模板
        template_pdf = (self.template_pdf_var.get() or "").strip()
        if template_pdf and os.path.isfile(template_pdf):
            self._log_safe("info", f"使用指定模板: {template_pdf}")
        else:
            # 自动探测
            template_pdf = self._auto_detect_template()
        if template_pdf and os.path.isfile(template_pdf):
            self._log_safe("ok", f"模板: {template_pdf}")
            editor = PDFTemplateEditor(template_pdf, self.logger)
            try:
                self._log_safe("info", "替换占位符…")
                hit_total = 0
                for k, v in values.items():
                    hits = editor.replace_label(k, v, page_index=0, fontsize=11)
                    hit_total += hits
                if hit_total == 0:
                    self._log_safe("warn", "⚠ 第1页没有命中任何占位符。")
                editor.replace_image_centered(1, tma_tif)
                editor.replace_image_centered(2, lj_png)
                editor.save(out_pdf)
                self._log_safe("ok", f"✅ 报告已生成: {out_pdf}")
                self._set_status_safe(f"✅ {os.path.basename(out_pdf)}")
            except Exception as e:
                self._log_safe("error", f"模板模式失败：{e}")
                try: build_simple_pdf(out_pdf, values, tma_tif, lj_png, self.logger, root=self.root)
                except Exception as e2: self._log_safe("error", f"简版也失败：{e2}")
            finally:
                editor.close()
        else:
            self._log_safe("warn", "未找到模板，生成简版 pdf")
            try:
                build_simple_pdf(out_pdf, values, tma_tif, lj_png, self.logger, root=self.root)
                self._set_status_safe(f"✅ {os.path.basename(out_pdf)}")
            except Exception as e:
                self._log_safe("error", f"简版生成失败：{e}")
                self._set_status_safe("生成失败")


# ══════════════════════════════════════════════════════════════════════
# §10  入口
# ══════════════════════════════════════════════════════════════════════

def main():
    root = tk.Tk()
    root.geometry("1000x680")
    root.minsize(860, 580)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
