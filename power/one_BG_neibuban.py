# -*- coding: utf-8 -*-
"""
one_BG_neibuban.py
单次出报告神器-内部版 v9.4.1
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
      reportlab（简版 COA / P9M 粒径报告） / cryptography（P9M）
"""

VERSION = "v9.4.1"

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
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import shutil

# ── Tk ──────────────────────────────────────────────────────────────
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
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
P9M_DIR_DEFAULT      = "\\\\192.168.0.200\\激光粒度测定仪"

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



# ══════════════════════════════════════════════════════════════════════
# §P9M  欧美克 LS-POP(9) 粒径数据读取 + 多选粒径报告
# ══════════════════════════════════════════════════════════════════════
#
# 工作流：
#   主界面点击【粒径报告】→ 弹出 P9M 窗口
#   → 选择 .p9m → 解析 Record → 可单选/多选
#   → 生成所选粒度测试报告 PDF
#   → 指定其中一条为“当前粒径数据”后，自动回填主界面：
#       粒径报告路径 = 生成的 PDF
#       D50 粒径     = P9M 原始 D50（不再依赖 OCR）
#
# 依赖（仅使用 P9M 功能时需要）：
#   pip install cryptography reportlab
# matplotlib 已是本程序原有依赖。


_P9M_AES_KEY = bytes.fromhex(
    "D3 E8 C2 E2 BF B5 CC 7A 0D 1A C3 F6 F2 14 FA C5 "
    "AF 1C 1B 70 20 05 6C 45 60 4E 65 3F 1B 24 5D 57"
)
_P9M_AES_IV = bytes.fromhex(
    "DA A6 2B EB D2 EE E2 4E D8 18 CE 0F 3B 85 DE B2"
)


@dataclass
class _P9MPoint:
    size: float
    freq_ratio: Optional[float]
    under_ratio: Optional[float]
    over_ratio: Optional[float]


@dataclass
class _P9MRecord:
    source_file: str
    record_id: str
    is_average: bool
    sample_name: str
    sample_no: str
    sop_name: str
    tester: str
    measurement_time: str
    sample_time_ms: Optional[float]
    background_time_ms: Optional[float]
    result_type: str
    material_name: str
    material_ri: str
    material_ai: str
    dispersant_name: str
    dispersant_ri: str
    range_min: str
    range_max: str
    obscuration: Optional[float]
    difference: Optional[float]
    d10: Optional[float]
    d25: Optional[float]
    d50: Optional[float]
    d75: Optional[float]
    d90: Optional[float]
    d97: Optional[float]
    d32: Optional[float]
    d43: Optional[float]
    span: Optional[float]
    ssaw: Optional[float]
    instrument_id: str
    software_version: str
    points: List[_P9MPoint]


def _p9m_float(v) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None


def _p9m_n3(v) -> str:
    return "" if v is None else f"{float(v):.3f}"


def _p9m_pct(v) -> str:
    return "" if v is None else f"{float(v) * 100.0:.2f}%"


def _p9m_ms_to_s(v) -> str:
    return "" if v is None else f"{float(v) / 1000.0:.1f} 秒"


def _p9m_safe_filename(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*]', "_", str(s or "")).strip().rstrip(". ")
    return s or "粒度测试报告"


def _p9m_sop_basename(s: str) -> str:
    if not s:
        return ""
    return re.split(r"[\\/]", s)[-1]


def _p9m_decrypt(path: str) -> str:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7
    except ImportError as e:
        raise RuntimeError(
            "P9M 功能缺少 cryptography。\n"
            "请执行：pip install cryptography"
        ) from e

    with open(path, "rb") as f:
        data = f.read()

    if not data:
        raise ValueError("P9M 文件为空。")
    if len(data) % 16 != 0:
        raise ValueError("P9M 文件长度异常，可能不是当前支持的 LS-POP(9) P9M。")

    dec = Cipher(algorithms.AES(_P9M_AES_KEY), modes.CBC(_P9M_AES_IV)).decryptor()
    padded = dec.update(data) + dec.finalize()

    unpad = PKCS7(128).unpadder()
    plain = unpad.update(padded) + unpad.finalize()

    xml_text = plain.decode("utf-8-sig")
    if not xml_text.lstrip().startswith("<"):
        raise ValueError("P9M 解密结果不是可识别 XML。")
    return xml_text


def _p9m_distribution_map(rec, tag: str) -> Dict[float, float]:
    out: Dict[float, float] = {}
    parent = rec.find(tag)
    if parent is None:
        return out
    for db in parent.findall("Db"):
        try:
            out[float(db.attrib["ParticleSize"])] = float(db.attrib["Distribution"])
        except Exception:
            continue
    return out


def _p9m_parse_points(rec) -> List[_P9MPoint]:
    freq = _p9m_distribution_map(rec, "FrequencyDistributionList")
    under = _p9m_distribution_map(rec, "UnderSizeCumulativeDistributionList")
    over = _p9m_distribution_map(rec, "OverSizeCumulativeDistributionList")
    sizes = sorted(set(freq) | set(under) | set(over))
    return [
        _P9MPoint(
            size=s,
            freq_ratio=freq.get(s),
            under_ratio=under.get(s),
            over_ratio=over.get(s),
        )
        for s in sizes
    ]


def _p9m_parse_records(path: str) -> List[_P9MRecord]:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(_p9m_decrypt(path))
    recs = root.findall("Record")
    if not recs:
        recs = root.findall(".//Record")
    if not recs:
        raise ValueError("P9M 中没有找到测量记录 Record。")

    rows: List[_P9MRecord] = []
    for rec in recs:
        sop = rec.find("SopConfig")
        if sop is None:
            sop = rec.find(".//SopConfig")
        sa = sop.attrib if sop is not None else {}

        result_type = sa.get("ResultType", "")
        if result_type.lower() == "volume":
            result_type = "体积(V)"

        rows.append(_P9MRecord(
            source_file=path,
            record_id=rec.attrib.get("ID", ""),
            is_average=(rec.attrib.get("IsAverageResult", "").strip().lower() == "true"),
            sample_name=sa.get("SampleName", ""),
            sample_no=sa.get("SampleSerialNumber", ""),
            sop_name=_p9m_sop_basename(rec.attrib.get("SopName", "")),
            tester=rec.attrib.get("Tester", ""),
            measurement_time=rec.attrib.get("MeasurementTime", ""),
            sample_time_ms=_p9m_float(sa.get("TimeForMeasuringSample")),
            background_time_ms=_p9m_float(sa.get("TimeForMeasuringLightBackground")),
            result_type=result_type,
            material_name=sa.get("MaterialName", ""),
            material_ri=sa.get("MaterialRefractiveIndex", ""),
            material_ai=sa.get("MaterialAbsorptionIndex", ""),
            dispersant_name=sa.get("DispersantName", ""),
            dispersant_ri=sa.get("DispersantRefractiveIndex", ""),
            range_min=sa.get("ResultRangeMin", "0.1"),
            range_max=sa.get("ResultRangeMax", "750"),
            obscuration=_p9m_float(rec.attrib.get("Obscuration")),
            difference=_p9m_float(rec.attrib.get("Difference")),
            d10=_p9m_float(rec.attrib.get("D10")),
            d25=_p9m_float(rec.attrib.get("D25")),
            d50=_p9m_float(rec.attrib.get("D50")),
            d75=_p9m_float(rec.attrib.get("D75")),
            d90=_p9m_float(rec.attrib.get("D90")),
            d97=_p9m_float(rec.attrib.get("D97")),
            d32=_p9m_float(rec.attrib.get("D32V")),
            d43=_p9m_float(rec.attrib.get("D43V")),
            span=_p9m_float(rec.attrib.get("Span")),
            ssaw=_p9m_float(rec.attrib.get("Ssaw")),
            instrument_id=rec.attrib.get("InstrumentId", ""),
            software_version=rec.attrib.get("SoftwareVersion", ""),
            points=_p9m_parse_points(rec),
        ))

    return rows


_P9M_FONT_CACHE = None


def _p9m_register_pdf_fonts():
    """返回 (正文, 粗体, 是否需要模拟粗体)。"""
    global _P9M_FONT_CACHE
    if _P9M_FONT_CACHE is not None:
        return _P9M_FONT_CACHE

    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    except ImportError as e:
        raise RuntimeError(
            "P9M 报告功能缺少 reportlab。\n"
            "请执行：pip install reportlab"
        ) from e

    def first_existing(paths):
        for p in paths:
            if p and os.path.exists(p):
                return p
        return None

    regular_path = first_existing([
        r"C:\Windows\Fonts\simsun.ttf",
        r"C:\Windows\Fonts\Deng.ttf",
        r"C:\Windows\Fonts\simhei.ttf",
    ])
    bold_path = first_existing([
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\Dengb.ttf",
        r"C:\Windows\Fonts\msyhbd.ttf",
    ])

    regular_name = None
    bold_name = None

    if regular_path:
        try:
            pdfmetrics.registerFont(TTFont("P9MCNRegular", regular_path))
            regular_name = "P9MCNRegular"
        except Exception:
            pass

    if bold_path:
        try:
            pdfmetrics.registerFont(TTFont("P9MCNBold", bold_path))
            bold_name = "P9MCNBold"
        except Exception:
            pass

    if regular_name is None:
        try:
            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
            regular_name = "STSong-Light"
        except Exception:
            regular_name = "Helvetica"

    if bold_name is None:
        bold_name = regular_name
        simulate_bold = True
    else:
        simulate_bold = False

    _P9M_FONT_CACHE = (regular_name, bold_name, simulate_bold)
    return _P9M_FONT_CACHE


def _p9m_draw_distribution_png(points: List[_P9MPoint], out_png: str):
    from matplotlib.ticker import LogLocator, NullFormatter
    from matplotlib.font_manager import FontProperties

    # 显式寻找中文字体，避免粒径图坐标轴在部分环境出现方框乱码。
    font_path = None
    for fp in [
        r"C:\\Windows\\Fonts\\msyh.ttf",
        r"C:\\Windows\\Fonts\\simhei.ttf",
        r"C:\\Windows\\Fonts\\Deng.ttf",
        "/usr/share/fonts/truetype/arphic-gbsn00lp/gbsn00lp.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]:
        if os.path.exists(fp):
            font_path = fp
            break
    cn_font = FontProperties(fname=font_path) if font_path else None

    xs = [p.size for p in points if p.freq_ratio is not None]
    ys = [(p.freq_ratio or 0.0) * 100.0 for p in points if p.freq_ratio is not None]

    fig = Figure(figsize=(8.5, 3.2), dpi=180)
    ax = fig.add_subplot(111)
    ax.set_xscale("log")
    ax.plot(xs, ys, linewidth=2.0, color="blue")
    ax.set_xlim(0.1, 1000)

    ymax = max(ys) if ys else 0.0
    ytop = max(30.0, math.ceil(max(ymax, 1.0) / 10.0) * 10.0)
    ax.set_ylim(0, ytop)
    ax.set_yticks(list(range(0, int(ytop) + 1, 10)))

    ax.xaxis.set_major_locator(LogLocator(base=10.0, numticks=5))
    ax.xaxis.set_minor_locator(
        LogLocator(base=10.0, subs=tuple(range(2, 10)), numticks=100)
    )
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.grid(True, which="major", linewidth=0.7, alpha=0.65)
    ax.grid(True, which="minor", linewidth=0.45, alpha=0.35)

    if cn_font is not None:
        ax.set_xlabel("粒径（μm）", fontproperties=cn_font)
        ax.set_ylabel("微分分布（%）", fontproperties=cn_font)
    else:
        ax.set_xlabel("粒径（μm）")
        ax.set_ylabel("微分分布（%）")

    fig.patch.set_alpha(0.0)
    ax.set_facecolor("none")
    fig.tight_layout(pad=0.8)

    agg = FigureCanvasAgg(fig)
    agg.print_png(out_png)


def _p9m_generate_pdf(rec: _P9MRecord, out_pdf: str):
    import tempfile
    try:
        from reportlab.lib import colors as rl_colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas as rl_canvas
    except ImportError as e:
        raise RuntimeError(
            "P9M 报告功能缺少 reportlab。\n"
            "请执行：pip install reportlab"
        ) from e

    regular_font, bold_font, simulate_bold = _p9m_register_pdf_fonts()

    BLUE = rl_colors.HexColor("#1135C6")
    RED = rl_colors.HexColor("#FF2222")
    YELLOW = rl_colors.HexColor("#FFD100")
    GRAY_LINE = rl_colors.HexColor("#D0D0D0")

    def draw_text(c, x, y, s, size=9, color=rl_colors.black, bold=False):
        font = bold_font if bold else regular_font
        c.setFont(font, size)
        c.setFillColor(color)
        c.drawString(x, y, str(s))
        if bold and simulate_bold:
            c.drawString(x + 0.35, y, str(s))

    def draw_center(c, x, y, s, size=9, color=rl_colors.black, bold=False):
        font = bold_font if bold else regular_font
        c.setFont(font, size)
        c.setFillColor(color)
        c.drawCentredString(x, y, str(s))
        if bold and simulate_bold:
            c.drawCentredString(x + 0.35, y, str(s))

    def label_value(c, x, y, label, value, label_size=9, value_size=9):
        draw_text(c, x, y, label, label_size, BLUE, bold=True)
        draw_text(c, x, y - 12, value, value_size, rl_colors.black, bold=False)

    def split3(points):
        n = int(math.ceil(len(points) / 3.0)) if points else 0
        return [points[0:n], points[n:2*n], points[2*n:3*n]]

    W, H = A4
    c = rl_canvas.Canvas(out_pdf, pagesize=A4)
    c.setTitle("粒度测试报告")

    # 白色页面，不绘制信息区蓝色外框。
    c.setFillColor(rl_colors.white)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    left = 38
    bw = W - 76

    # 页眉
    c.setFont("Helvetica-Bold", 26)
    c.setFillColor(BLUE)
    c.drawString(left, 795, "OMEC")
    draw_text(c, left + 2, 778, "欧 美 克", 13, BLUE, bold=False)

    draw_center(c, W / 2, 790, "粒度测试报告", 18, RED, bold=True)

    c.setFillColor(YELLOW)
    c.ellipse(W - 142, 780, W - 28, 808, fill=1, stroke=0)
    c.setFont("Helvetica-BoldOblique", 14)
    c.setFillColor(rl_colors.black)
    c.drawCentredString(W - 85, 789, "LS-POP (9)")

    cx = [left + 16, left + 207, left + 398]

    # 基本信息（无蓝色边框）
    y1, h1 = 680, 84
    top = y1 + h1 - 18
    label_value(c, cx[0], top, "样品名称：", rec.sample_name)
    label_value(c, cx[0], top - 28, "样品编号：", rec.sample_no)
    label_value(c, cx[0], top - 56, "单次采样时间：", _p9m_ms_to_s(rec.sample_time_ms))

    label_value(c, cx[1], top, "Sop名称：", rec.sop_name)
    label_value(c, cx[1], top - 28, "测试者：", rec.tester)
    label_value(c, cx[1], top - 56, "结果类型：", rec.result_type)

    label_value(c, cx[2], top, "测量时间：", rec.measurement_time)
    label_value(c, cx[2], top - 28, "背景采样时间：", _p9m_ms_to_s(rec.background_time_ms))

    # 材料信息（无蓝色边框）
    y2, h2 = 590, 80
    top2 = y2 + h2 - 18
    label_value(c, cx[0], top2, "样品材质：", rec.material_name)
    label_value(c, cx[0], top2 - 28, "分散介质：", rec.dispersant_name)
    label_value(c, cx[0], top2 - 56, "遮光比：", _p9m_pct(rec.obscuration))

    label_value(c, cx[1], top2, "样品材质折射率：", rec.material_ri)
    label_value(c, cx[1], top2 - 28, "分散介质折射率：", rec.dispersant_ri)
    label_value(
        c, cx[1], top2 - 56, "分析范围：",
        f"{rec.range_min} μm to {rec.range_max} μm"
    )

    label_value(c, cx[2], top2, "样品材质吸收率：", rec.material_ai)
    label_value(c, cx[2], top2 - 28, "分析模式：", "通用模式")
    label_value(c, cx[2], top2 - 56, "拟合残余：", _p9m_n3(rec.difference))

    # 关键指标（标题加粗，无蓝色边框）
    y3, h3 = 522, 54
    mx = [left + 18, left + 116, left + 214, left + 312, left + 410]
    for x, lab, val in zip(
        mx,
        ["D10：", "D25：", "D50：", "D75：", "D90："],
        [rec.d10, rec.d25, rec.d50, rec.d75, rec.d90]
    ):
        label_value(c, x, y3 + 36, lab, f"{_p9m_n3(val)} μm")

    label_value(c, mx[0], y3 + 9, "D97：", f"{_p9m_n3(rec.d97)} μm")
    label_value(c, mx[1], y3 + 9, "D(3,2)：", f"{_p9m_n3(rec.d32)} μm")
    label_value(c, mx[2], y3 + 9, "D(4,3)：", f"{_p9m_n3(rec.d43)} μm")
    label_value(c, mx[3], y3 + 9, "Span：", _p9m_n3(rec.span))
    label_value(
        c, mx[4], y3 + 9, "重量比表面积：",
        f"{_p9m_n3(rec.ssaw)} m²/kg"
    )

    # 粒径分布图
    y4, h4 = 310, 198
    draw_center(c, W / 2, y4 + h4 - 16, "粒度分布图", 12, BLUE, bold=True)

    with tempfile.TemporaryDirectory() as td:
        plot_png = os.path.join(td, "p9m_distribution.png")
        _p9m_draw_distribution_png(rec.points, plot_png)
        c.drawImage(
            ImageReader(plot_png),
            left + 28, y4 + 12,
            width=bw - 56, height=150,
            preserveAspectRatio=True,
            anchor="c",
            mask="auto",
        )

    # 下方三栏分布表，仅保留浅灰辅助线
    y5, h5 = 92, 202
    colw = bw / 3.0
    for i in (1, 2):
        c.setStrokeColor(GRAY_LINE)
        c.setLineWidth(0.45)
        c.line(left + i * colw, y5, left + i * colw, y5 + h5)

    cols = split3(rec.points)
    header_y = y5 + h5 - 18
    row_h = 12.2

    for j, pts in enumerate(cols):
        bx = left + j * colw
        draw_text(c, bx + 7, header_y, "粒径（μm）", 8, bold=True)
        draw_text(c, bx + 70, header_y, "微分（%）", 8, bold=True)
        draw_text(c, bx + 126, header_y, "累积（%）", 8, bold=True)

        c.setStrokeColor(GRAY_LINE)
        c.setLineWidth(0.45)
        c.line(bx, header_y - 4, bx + colw, header_y - 4)

        for i, p in enumerate(pts):
            yy = header_y - 17 - i * row_h
            draw_text(c, bx + 8, yy, f"{p.size:.3f}", 7.5)
            fv = "" if p.freq_ratio is None else f"{p.freq_ratio * 100.0:.2f}"
            uv = "" if p.under_ratio is None else f"{p.under_ratio * 100.0:.2f}"
            draw_text(c, bx + 76, yy, fv, 7.5)
            draw_text(c, bx + 133, yy, uv, 7.5)

    # 页脚
    fy = 54
    draw_text(c, left, fy + 12, "仪器提供：珠海欧美克仪器有限公司", 6.5)
    draw_text(c, left, fy, f"仪器编号：{rec.instrument_id}", 6.5)
    draw_text(c, left, fy - 12, f"文件名称：{os.path.basename(rec.source_file)}", 6.5)

    draw_text(c, W / 2 - 70, fy + 12, "公司网址：www.omec-instruments.com", 6.5)
    draw_text(c, W / 2 - 70, fy, f"软件版本：{rec.software_version}", 6.5)

    draw_text(c, W - 165, fy + 12, "公司电话：(0756) 3391999 3395365", 6.5)
    draw_text(c, W - 165, fy, f"记录编号：{rec.record_id}", 6.5)

    c.showPage()
    c.save()


class _P9MReportDialog:
    """主程序内嵌的 P9M 多选粒径报告窗口。"""

    def __init__(self, owner):
        self.owner = owner
        self.win = tk.Toplevel(owner.root)
        self.win.title("P9M 粒径数据选择")
        self.win.geometry("1240x660")
        self.win.minsize(980, 520)
        self.win.configure(bg=_C.BG)
        self.win.transient(owner.root)

        self.p9m_path: Optional[str] = None
        self.records: List[_P9MRecord] = []
        self.active_index: Optional[int] = None

        self.file_var = tk.StringVar(value="尚未选择 P9M")
        self.status_var = tk.StringVar(value="先选择 P9M 文件。")
        self.selection_var = tk.StringVar(value="已选择 0 条")
        self.active_var = tk.StringVar(value="当前粒径数据：未指定")

        self._build()

    def _build(self):
        root = self.win

        header = tk.Frame(root, bg=_C.PANEL, height=48)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Frame(header, width=4, bg=_C.ORANGE).pack(side="left", fill="y")
        tk.Label(
            header, text="P9M 粒径数据选择",
            bg=_C.PANEL, fg=_C.FG,
            font=_C.FONT_TITLE
        ).pack(side="left", padx=14, pady=10)

        body = tk.Frame(root, bg=_C.BG, padx=12, pady=10)
        body.pack(fill="both", expand=True)

        bar = tk.Frame(body, bg=_C.BG)
        bar.pack(fill="x", pady=(0, 8))

        tk.Button(
            bar, text="选择 P9M",
            command=self.open_p9m,
            bg=_C.BTN_ACCENT, fg=_C.FG,
            relief="flat", padx=12, pady=5
        ).pack(side="left")

        tk.Button(
            bar, text="全选",
            command=self.select_all,
            bg=_C.INPUT_BG, fg=_C.FG,
            relief="flat", padx=10, pady=5
        ).pack(side="left", padx=(8, 0))

        tk.Button(
            bar, text="只选平均结果",
            command=self.select_averages,
            bg=_C.INPUT_BG, fg=_C.FG,
            relief="flat", padx=10, pady=5
        ).pack(side="left", padx=(8, 0))

        tk.Button(
            bar, text="清除选择",
            command=self.clear_selection,
            bg=_C.INPUT_BG, fg=_C.FG,
            relief="flat", padx=10, pady=5
        ).pack(side="left", padx=(8, 0))

        self.generate_btn = tk.Button(
            bar, text="确认所选记录",
            command=self.confirm_selected,
            bg=_C.BTN_SUCCESS, fg=_C.FG,
            relief="flat", padx=14, pady=5,
            state="disabled"
        )
        self.generate_btn.pack(side="right")

        info_panel = tk.Frame(
            body, bg=_C.PANEL,
            highlightthickness=1,
            highlightbackground=_C.BORDER
        )
        info_panel.pack(fill="x", pady=(0, 8))

        tk.Label(
            info_panel, textvariable=self.file_var,
            bg=_C.PANEL, fg=_C.FG2,
            font=_C.FONT_MONO,
            anchor="w", justify="left"
        ).pack(fill="x", padx=8, pady=(6, 2))

        line2 = tk.Frame(info_panel, bg=_C.PANEL)
        line2.pack(fill="x", padx=8, pady=(0, 6))
        tk.Label(
            line2, text="Ctrl/Shift 可多选；焦点记录作为当前大报告的 D50/SPAN 数据。",
            bg=_C.PANEL, fg=_C.FG3,
            font=_C.FONT_UI
        ).pack(side="left")
        tk.Label(
            line2, textvariable=self.active_var,
            bg=_C.PANEL, fg=_C.CYAN,
            font=(_C.FONT_UI[0], 9, "bold")
        ).pack(side="left", padx=(18, 0))
        tk.Label(
            line2, textvariable=self.selection_var,
            bg=_C.PANEL, fg=_C.FG2,
            font=(_C.FONT_UI[0], 9, "bold")
        ).pack(side="right")

        table_wrap = tk.Frame(body, bg=_C.BG)
        table_wrap.pack(fill="both", expand=True)
        table_wrap.rowconfigure(0, weight=1)
        table_wrap.columnconfigure(0, weight=1)

        cols = (
            "id", "avg", "sample", "sample_no", "time",
            "d50", "d75", "d90", "span", "obsc", "ssaw", "diff"
        )
        self.tree = ttk.Treeview(
            table_wrap,
            columns=cols,
            show="headings",
            selectmode="extended"
        )

        heads = {
            "id": "ID",
            "avg": "平均",
            "sample": "样品名称",
            "sample_no": "样品编号",
            "time": "测量时间",
            "d50": "D50 (μm)",
            "d75": "D75 (μm)",
            "d90": "D90 (μm)",
            "span": "Span",
            "obsc": "遮光比",
            "ssaw": "重量比表面积",
            "diff": "拟合残余",
        }
        widths = {
            "id": 52, "avg": 52, "sample": 165, "sample_no": 82,
            "time": 150, "d50": 85, "d75": 85, "d90": 85,
            "span": 68, "obsc": 78, "ssaw": 105, "diff": 80,
        }

        for k in cols:
            self.tree.heading(k, text=heads[k])
            anchor = "w" if k in ("sample", "time") else "center"
            self.tree.column(
                k, width=widths[k], minwidth=45,
                anchor=anchor, stretch=True
            )

        ysb = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(table_wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")

        self.tree.tag_configure("p9m_avg", foreground="#20c65a")
        self.tree.bind("<<TreeviewSelect>>", self._on_selection)
        self.tree.bind("<Double-1>", self._set_active_from_event)

        footer = tk.Frame(body, bg=_C.BG)
        footer.pack(fill="x", pady=(8, 0))

        tk.Button(
            footer, text="设为当前记录",
            command=self.set_active,
            bg="#1a3d5c", fg=_C.FG,
            relief="flat", padx=12, pady=5
        ).pack(side="left")

        tk.Button(
            footer, text="关闭",
            command=self.win.destroy,
            bg=_C.BTN_DANGER, fg="#ffb3b0",
            relief="flat", padx=12, pady=5
        ).pack(side="right")

        tk.Label(
            footer, textvariable=self.status_var,
            bg=_C.BG, fg=_C.FG3,
            font=_C.FONT_UI,
            anchor="w"
        ).pack(side="left", padx=(12, 0), fill="x", expand=True)

    def open_p9m(self):
        init = self.owner.last_lj_dir or P9M_DIR_DEFAULT
        f = filedialog.askopenfilename(
            parent=self.win,
            title="选择 OMEC LS-POP(9) P9M",
            initialdir=init,
            filetypes=[("P9M 文件", "*.p9m"), ("全部文件", "*.*")]
        )
        if not f:
            return

        try:
            self.status_var.set("正在解析 P9M…")
            self.win.update_idletasks()

            self.p9m_path = normalize_path_separators(f.strip())
            self.records = _p9m_parse_records(self.p9m_path)
            self.file_var.set(self.p9m_path)

            try:
                self.owner.last_lj_dir = os.path.dirname(self.p9m_path)
            except Exception:
                pass

            self._refresh_tree()
            self.generate_btn.config(state="normal")

            avg_count = sum(1 for r in self.records if r.is_average)
            self.status_var.set(
                f"解析完成：{len(self.records)} 条记录，平均结果 {avg_count} 条。"
            )
            self.owner.logger.ok(
                f"✅ P9M 已解析：{os.path.basename(self.p9m_path)}，"
                f"{len(self.records)} 条记录"
            )

        except Exception as e:
            self.p9m_path = None
            self.records = []
            self._refresh_tree()
            self.generate_btn.config(state="disabled")
            self.status_var.set("P9M 读取失败。")
            messagebox.showerror("P9M 读取失败", str(e), parent=self.win)

    def _refresh_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        self.active_index = None

        if not self.records:
            self.selection_var.set("已选择 0 条")
            self.active_var.set("当前粒径数据：未指定")
            return

        avg_iids = []
        for i, r in enumerate(self.records):
            iid = str(i)
            vals = (
                r.record_id,
                "是" if r.is_average else "否",
                r.sample_name,
                r.sample_no,
                r.measurement_time,
                _p9m_n3(r.d50),
                _p9m_n3(r.d75),
                _p9m_n3(r.d90),
                _p9m_n3(r.span),
                _p9m_pct(r.obscuration),
                _p9m_n3(r.ssaw),
                _p9m_n3(r.difference),
            )
            self.tree.insert(
                "", "end",
                iid=iid,
                values=vals,
                tags=("p9m_avg",) if r.is_average else ()
            )
            if r.is_average:
                avg_iids.append(iid)

        # 默认选平均记录；同时把最后一个平均记录设成当前粒径数据
        if avg_iids:
            self.tree.selection_set(avg_iids)
            self.tree.focus(avg_iids[-1])
            self.tree.see(avg_iids[-1])
            self.active_index = int(avg_iids[-1])
        else:
            self.tree.selection_set("0")
            self.tree.focus("0")
            self.active_index = 0

        self._update_active_label()
        self._on_selection()

    def _on_selection(self, _event=None):
        self.selection_var.set(f"已选择 {len(self.tree.selection())} 条")
        # 单选时自动将该条视作当前粒径数据，减少额外点击
        sel = self.tree.selection()
        if len(sel) == 1:
            try:
                self.active_index = int(sel[0])
                self._update_active_label()
            except Exception:
                pass

    def _set_active_from_event(self, _event=None):
        self.set_active()

    def _update_active_label(self):
        if self.active_index is None or not (0 <= self.active_index < len(self.records)):
            self.active_var.set("当前粒径数据：未指定")
            return
        r = self.records[self.active_index]
        extra = " / 平均" if r.is_average else ""
        self.active_var.set(
            f"当前粒径数据：ID {r.record_id}{extra}，D50={_p9m_n3(r.d50)} μm"
        )

    def set_active(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择至少一条记录。", parent=self.win)
            return
        focus = self.tree.focus()
        iid = focus if focus in sel else sel[0]
        try:
            self.active_index = int(iid)
        except Exception:
            return
        self._update_active_label()
        self.status_var.set("已指定当前记录；点击“确认所选记录”后回填 D50/SPAN。")

    def select_all(self):
        items = self.tree.get_children()
        if items:
            self.tree.selection_set(items)
            self._on_selection()

    def select_averages(self):
        iids = [str(i) for i, r in enumerate(self.records) if r.is_average]
        self.tree.selection_remove(self.tree.selection())
        if iids:
            self.tree.selection_set(iids)
            self.tree.focus(iids[-1])
            self.active_index = int(iids[-1])
            self._update_active_label()
        self._on_selection()

    def clear_selection(self):
        self.tree.selection_remove(self.tree.selection())
        self._on_selection()

    def choose_existing(self):
        # 保留原程序 PDF / PNG 粒径报告选择方式
        self.owner._choose_existing_lj()
        if (self.owner.lj_path.get() or "").strip():
            self.win.destroy()

    def _selected_records(self) -> List[Tuple[int, _P9MRecord]]:
        selected_ids = set(self.tree.selection())
        out = []
        for i, r in enumerate(self.records):
            if str(i) in selected_ids:
                out.append((i, r))
        return out

    def confirm_selected(self):
        """只保存 P9M 数据位置 + Record ID/索引，不生成粒径报告文件。"""
        if not self.p9m_path or not self.records:
            messagebox.showwarning("提示", "请先选择 P9M 文件。", parent=self.win)
            return

        selected = self._selected_records()
        if not selected:
            messagebox.showwarning("提示", "请至少选择一条记录。", parent=self.win)
            return

        selected_indices = [idx for idx, _ in selected]
        selected_ids = [r.record_id for _, r in selected]

        focus = self.tree.focus()
        try:
            active_idx = int(focus) if focus and int(focus) in selected_indices else selected_indices[0]
        except Exception:
            active_idx = selected_indices[0]
        active_rec = self.records[active_idx]

        self.owner._p9m_source_path = normalize_path_separators(self.p9m_path)
        self.owner._p9m_selected_indices = list(selected_indices)
        self.owner._p9m_selected_record_ids = list(selected_ids)
        self.owner._p9m_active_index = int(active_idx)
        self.owner._p9m_active_record_id = str(active_rec.record_id)
        self.owner._p9m_current_record = active_rec
        self.owner._p9m_current_report = ""

        # 主界面的“粒径报告路径”现在保存 P9M 本身，不再保存临时 PDF。
        self.owner.lj_path.set(self.owner._p9m_source_path)
        if active_rec.d50 is not None:
            self.owner.lj_value.set(_p9m_n3(active_rec.d50))
        if active_rec.span is not None:
            self.owner.span_value.set(_p9m_n3(active_rec.span))

        try:
            self.owner.last_lj_dir = os.path.dirname(self.owner._p9m_source_path) or P9M_DIR_DEFAULT
            self.owner._remember_dir_in_combo(
                self.owner.lj_combo,
                self.owner.lj_dir_presets,
                self.owner.last_lj_dir
            )
        except Exception:
            pass

        self.owner.logger.sep()
        self.owner.logger.ok(
            f"✅ 已记录 P9M：{os.path.basename(self.owner._p9m_source_path)}"
        )
        self.owner.logger.info(
            f"已选 {len(selected)} 条 Record；当前 ID={active_rec.record_id}"
            + ("（平均）" if active_rec.is_average else "")
        )
        self.owner.logger.info(
            f"D50={_p9m_n3(active_rec.d50)} μm  "
            f"SPAN={_p9m_n3(active_rec.span)}  "
            f"测量时间={active_rec.measurement_time}"
        )
        self.owner._set_status(
            f"P9M ID {active_rec.record_id}  "
            f"D50={_p9m_n3(active_rec.d50)}  SPAN={_p9m_n3(active_rec.span)}"
        )

        self.status_var.set("选择已保存；未生成任何独立粒径报告。")
        self.win.destroy()


def _normalize_datetime_seconds(value: str) -> str:
    """把常见仪器日期时间统一为 YYYY-MM-DD HH:MM:SS。"""
    s = str(value or "").strip()
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s).strip().strip(",;")
    fmts = [
        "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y.%m.%d %H:%M:%S",
        "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S",
        "%d-%b-%Y %H:%M:%S", "%d-%B-%Y %H:%M:%S",
        "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y.%m.%d %H:%M",
        "%m/%d/%Y %H:%M", "%d/%m/%Y %H:%M",
        "%d-%b-%Y %H:%M", "%d-%B-%Y %H:%M",
    ]
    for fmt in fmts:
        try:
            dt = datetime.datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    patterns = [
        r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?\b",
        r"\b\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?\b",
        r"\b\d{1,2}-[A-Za-z]{3,9}-\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?\b",
    ]
    for pat in patterns:
        m = re.search(pat, s)
        if m:
            out = _normalize_datetime_seconds(m.group(0))
            if out:
                return out
    return ""


def _extract_tma_internal_datetime(tma_path: str, logger=None) -> str:
    """
    从 .001 文件自身的未加密文本头读取真正的检测时间。

    TA Instruments Q400 的 .001 文件头是 UTF-16 文本，例如：
        Date 2026-08-29
        Time 15:06:12

    只匹配独立的 Date / Time 行，因此不会把
    InstCalDate Cell / Probe / Force 的校准时间误当成检测时间。
    也不会使用 Windows 文件修改时间。
    """
    path = normalize_path_separators((tma_path or "").strip())
    if not path or not os.path.isfile(path):
        return ""

    ext = os.path.splitext(path)[1].lower()
    if ext in (".png", ".tif", ".tiff", ".jpg", ".jpeg"):
        return ""

    try:
        with open(path, "rb") as f:
            raw = f.read(128 * 1024)
    except Exception as e:
        if logger is not None:
            try:
                logger.warn(f".001 时间读取失败：{e}")
            except Exception:
                pass
        return ""

    if not raw:
        return ""

    # 当前 Q400 .001：FF FE / UTF-16LE；0C 00 之后进入二进制数据区。
    if raw.startswith(b"\xff\xfe"):
        enc = "utf-16le"
        body = raw[2:]
        cut = body.find(b"\x0c\x00")
        if cut >= 0:
            body = body[:cut]
    elif raw.startswith(b"\xfe\xff"):
        enc = "utf-16be"
        body = raw[2:]
        cut = body.find(b"\x00\x0c")
        if cut >= 0:
            body = body[:cut]
    else:
        probe = raw[:512]
        odd_nuls = sum(
            1 for i in range(1, len(probe), 2) if probe[i] == 0
        )
        even_nuls = sum(
            1 for i in range(0, len(probe), 2) if probe[i] == 0
        )

        if odd_nuls > even_nuls * 2:
            enc = "utf-16le"
            body = raw
            cut = body.find(b"\x0c\x00")
            if cut >= 0:
                body = body[:cut]
        elif even_nuls > odd_nuls * 2:
            enc = "utf-16be"
            body = raw
            cut = body.find(b"\x00\x0c")
            if cut >= 0:
                body = body[:cut]
        else:
            enc = "utf-8"
            body = raw
            cut = body.find(b"\x0c")
            if cut >= 0:
                body = body[:cut]

    try:
        header = body.decode(enc, errors="ignore")
    except Exception:
        return ""

    # 行首锚定是关键：避免命中 InstCalDate ... Time: ...
    date_match = re.search(
        r"(?im)^\s*Date\s+"
        r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"
        r"|\d{1,2}/\d{1,2}/\d{4}"
        r"|\d{1,2}-[A-Za-z]{3,9}-\d{4})\s*$",
        header,
    )
    time_match = re.search(
        r"(?im)^\s*Time\s+"
        r"(\d{1,2}:\d{2}(?::\d{2})?)\s*$",
        header,
    )

    if date_match and time_match:
        result = _normalize_datetime_seconds(
            f"{date_match.group(1)} {time_match.group(1)}"
        )
        if result:
            if logger is not None:
                try:
                    logger.info(f".001 内部检测时间：{result}")
                except Exception:
                    pass
            return result

    # 兼容少数版本 Date 与 Time 在同一行。
    m = re.search(
        r"(?im)^\s*(?:Run\s+)?Date\s*[:=]?\s*"
        r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})"
        r".*?\bTime\s*[:=]?\s*"
        r"(\d{1,2}:\d{2}(?::\d{2})?)\s*$",
        header,
    )
    if m:
        result = _normalize_datetime_seconds(f"{m.group(1)} {m.group(2)}")
        if result:
            return result

    if logger is not None:
        try:
            logger.warn(".001 内未识别到独立的 Date / Time 检测时间。")
        except Exception:
            pass

    return ""


# ══════════════════════════════════════════════════════════════════════
# §FINAL PDF  内置三页最终版（完全不依赖外部 template.pdf）
# ══════════════════════════════════════════════════════════════════════

def _coa_fit_image_box(image_path: str, max_w: float, max_h: float) -> Tuple[float, float]:
    """按原始宽高比计算图片在指定盒子内的最大尺寸。"""
    with Image.open(image_path) as im:
        iw, ih = im.size
    if iw <= 0 or ih <= 0:
        raise ValueError(f"图片尺寸异常：{image_path}")
    scale = min(float(max_w) / float(iw), float(max_h) / float(ih))
    return float(iw) * scale, float(ih) * scale


_JINLANG_LOGO_B64 = """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"""


def _coa_embedded_logo_reader():
    """把内置 Base64 Logo 在需要时解码成 ReportLab ImageReader。"""
    import base64
    import io
    from reportlab.lib.utils import ImageReader
    raw = base64.b64decode(_JINLANG_LOGO_B64.encode("ascii"))
    return ImageReader(io.BytesIO(raw))


def build_final_pdf_internal(
    out_pdf: str,
    values: Dict[str, str],
    tma_img: str,
    lj_img: str,
    logger: Optional[UILogger] = None,
    root=None,
):
    """
    直接生成最终 3 页 PDF，不读取任何外部 PDF 模板。

    第 1 页：内置 COA，按用户提供的最终版第一页重绘；
             Logo 使用程序内嵌 Base64，运行时解码。
    第 2 页：TMA 图，最大宽/高为页面 80%，下方标题。
    第 3 页：粒径报告图，最大宽/高为页面 80%，下方标题。
    """
    try:
        from reportlab.pdfgen import canvas as rl_canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors as rl_colors
        from reportlab.lib.utils import ImageReader
    except Exception as e:
        raise RuntimeError(
            "最终 PDF 生成功能需要 reportlab，请执行：pip install reportlab"
        ) from e

    regular_font, bold_font, simulate_bold = _p9m_register_pdf_fonts()

    W, H = A4
    out_dir = os.path.dirname(os.path.abspath(out_pdf))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    c = rl_canvas.Canvas(out_pdf, pagesize=A4)
    c.setTitle("Certificate of Analysis")

    BLUE = rl_colors.HexColor("#006FE8")
    BLUE_DARK = rl_colors.HexColor("#1841B2")
    GRID = rl_colors.HexColor("#161616")
    TEXT = rl_colors.HexColor("#111111")

    def txt(x, y, s, size=9, color=TEXT, bold=False, font=None):
        s = "" if s is None else str(s)
        use_font = font or (bold_font if bold else regular_font)
        c.setFont(use_font, size)
        c.setFillColor(color)
        c.drawString(x, y, s)
        if bold and font is None and simulate_bold:
            c.drawString(x + 0.30, y, s)

    def ctr(x, y, s, size=9, color=TEXT, bold=False, font=None):
        s = "" if s is None else str(s)
        use_font = font or (bold_font if bold else regular_font)
        c.setFont(use_font, size)
        c.setFillColor(color)
        c.drawCentredString(x, y, s)
        if bold and font is None and simulate_bold:
            c.drawCentredString(x + 0.30, y, s)

    def line(x1, y1, x2, y2, width=0.72):
        c.setStrokeColor(GRID)
        c.setLineWidth(width)
        c.line(x1, y1, x2, y2)

    def rect(x, y, w, h, width=0.72):
        c.setStrokeColor(GRID)
        c.setLineWidth(width)
        c.rect(x, y, w, h, stroke=1, fill=0)

    def cn_en_cell(x0, y0, x1, y1, zh, en, zh_size=9.0, en_size=7.6):
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        ctr(cx, cy + 5.5, zh, zh_size, TEXT)
        if en:
            ctr(cx, cy - 8.0, f"({en})", en_size, TEXT, font="Times-Roman")

    # ────────────────────────────────────────────────────────────────
    # PAGE 1 — 最终 COA（按用户最新第一页示意图）
    # ────────────────────────────────────────────────────────────────
    c.setFillColor(rl_colors.white)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # 左上角 Logo：Base64 内置，运行时解码，不依赖外部图片
    logo = _coa_embedded_logo_reader()
    c.drawImage(
        logo,
        48.0, 747.0,
        width=35.0, height=42.0,
        preserveAspectRatio=True,
        anchor="c",
        mask="auto",
    )

    # 公司抬头：中文与英文均以页面中心线居中
    ctr(W / 2, 779.0, "福建省锦浪新材料科技有限公司", 18.8, BLUE, True)
    ctr(W / 2, 753.0, "Fujian Jinlang New Material Technology Co., Ltd.",
        12.2, BLUE, True, font="Times-Bold")
    c.setStrokeColor(BLUE)
    c.setLineWidth(1.8)
    c.line(52.0, 744.0, W - 52.0, 744.0)

    # 主标题
    ctr(W / 2, 702.0, "内部检测报告", 20.5, BLUE, True)
    ctr(W / 2, 668.0, "Certificate of Analysis", 18.0, BLUE, True, font="Times-Bold")

    GRID = rl_colors.HexColor("#202020")
    TEXT = rl_colors.HexColor("#161616")

    def line(x1, y1, x2, y2, width=0.75):
        c.setStrokeColor(GRID)
        c.setLineWidth(width)
        c.line(x1, y1, x2, y2)

    def rect(x, y, w, h, width=0.75):
        c.setStrokeColor(GRID)
        c.setLineWidth(width)
        c.rect(x, y, w, h, stroke=1, fill=0)

    def put_center(x0, y0, w, h, s, size=8.7, bold=False):
        lines = str(s).split("\n")
        if len(lines) == 1:
            ctr(x0 + w/2, y0 + h/2 - 2, lines[0], size, TEXT, bold)
        else:
            ctr(x0 + w/2, y0 + h/2 + 5, lines[0], size, TEXT, bold)
            ctr(x0 + w/2, y0 + h/2 - 9, lines[1], size, TEXT, bold)

    # 表 1：产品名称 / 检测日期
    x1 = 46.0
    table1_w = W - 92.0
    y1_top = 631.0
    row1_h = [36.0, 36.0]
    table1_h = sum(row1_h)
    y1 = y1_top - table1_h
    label1_w = 112.0

    rect(x1, y1, table1_w, table1_h)
    line(x1, y1_top - row1_h[0], x1 + table1_w, y1_top - row1_h[0])
    line(x1 + label1_w, y1, x1 + label1_w, y1_top)

    put_center(x1, y1_top - row1_h[0], label1_w, row1_h[0], "产品名称\n(Product Name)", size=9.4)
    txt(x1 + label1_w + 8, y1_top - row1_h[0] + 9, values.get("tmaname", ""), 10.8, TEXT, False)

    put_center(x1, y1, label1_w, row1_h[1], "检测日期\n(Date)", size=9.4)
    txt(x1 + label1_w + 8, y1 + 9, values.get("shengchan", ""), 10.8, TEXT, False)

    # 表 2：分析项目（四列）
    x2 = 46.0
    table2_w = W - 92.0
    y2_top = 548.0
    header_h = 42.0
    data_h = 33.0
    row_count = 5
    table2_h = header_h + row_count * data_h
    y2 = y2_top - table2_h

    # 列宽：分析项目 / 分析结果 / 单位 / 检测时间
    col_ws = [120.0, 95.0, 95.0, table2_w - 120.0 - 95.0 - 95.0]
    xs = [x2]
    for cw in col_ws:
        xs.append(xs[-1] + cw)

    rect(x2, y2, table2_w, table2_h)
    for xx in xs[1:-1]:
        line(xx, y2, xx, y2_top)

    header_bottom = y2_top - header_h
    line(x2, header_bottom, x2 + table2_w, header_bottom)
    for i in range(1, row_count):
        yy = header_bottom - i * data_h
        line(x2, yy, x2 + table2_w, yy)

    headers = [
        ("分析项目", "Analysis Item"),
        ("分析结果", "Analysis Result"),
        ("单位", "Unit"),
        ("检测时间", "Test Time"),
    ]
    for i, (zh, en) in enumerate(headers):
        cx = (xs[i] + xs[i+1]) / 2
        ctr(cx, header_bottom + header_h / 2 + 7, zh, 10.2, TEXT, True)
        ctr(cx, header_bottom + header_h / 2 - 10, f"({en})", 8.2, TEXT, False, font="Times-Roman")

    p9m_time = values.get("p9m_time", "")
    tma_time = values.get("tma_time", "")

    data_rows = [
        ("D50", values.get("lijing", ""), "μm", p9m_time),
        ("SPAN", values.get("span", ""), "", p9m_time),
        ("T1", values.get("qifawd", ""), "℃", tma_time),
        ("T2", values.get("zuidawd", ""), "℃", tma_time),
        ("TMA", values.get("tmamd", ""), "kg/m3", tma_time),
    ]

    for r_i, (name, result, unit, ctime) in enumerate(data_rows):
        top_y = header_bottom - r_i * data_h
        bot_y = top_y - data_h
        cy = (top_y + bot_y) / 2 - 1
        ctr((xs[0] + xs[1]) / 2, cy, name, 10.2, TEXT, True)
        ctr((xs[1] + xs[2]) / 2, cy, result, 10.2, TEXT, False)
        ctr((xs[2] + xs[3]) / 2, cy, unit, 9.8, TEXT, False)
        ctr((xs[3] + xs[4]) / 2, cy, ctime, 8.8, TEXT, False)

    # 页脚
    footer_x = 52.0
    txt(footer_x, 92.0, "地址：福建省晋江市池店镇仕春工业区", 6.6, BLUE_DARK)
    txt(footer_x, 80.0, "Address: Shichun Industrial Area, Chidian, Jinjiang, Fujian, China.", 5.8, BLUE_DARK)
    txt(footer_x, 68.0, "电话：+86 595-82988888; Phone: +86 595-82988888", 5.8, BLUE_DARK)
    txt(footer_x, 56.0, "传真：+86 595-85057711; Fax: +86 595-85057711", 5.8, BLUE_DARK)

    c.showPage()

    # ────────────────────────────────────────────────────────────────
    # PAGE 2 / PAGE 3 — 图片 80% + 底部标题
    # ────────────────────────────────────────────────────────────────
    def figure_page(image_path: str, title: str, *, portrait_like: bool):
        c.setFillColor(rl_colors.white)
        c.rect(0, 0, W, H, fill=1, stroke=0)

        max_w = W * 0.80
        max_h = H * 0.80
        dw, dh = _coa_fit_image_box(image_path, max_w, max_h)

        if portrait_like:
            x = (W - dw) / 2
            y = max(82.0, (H - dh) / 2 + 20.0)
        else:
            x = (W - dw) / 2
            y = max(120.0, H * 0.90 - dh)

        c.drawImage(
            ImageReader(image_path),
            x, y,
            width=dw, height=dh,
            preserveAspectRatio=True,
            anchor="c",
            mask="auto",
        )

        ctr(W / 2, 42.0, title, 10.5, TEXT, False)
        c.showPage()

    figure_page(tma_img, "图 1：样品 TMA 测试图", portrait_like=False)
    figure_page(lj_img, "图 2：样品粒径分布图", portrait_like=True)

    c.save()

    if logger is not None:
        try:
            if root is not None:
                root.after(
                    0,
                    lambda: logger.ok(f"✅ 最终三页报告已生成：{out_pdf}")
                )
            else:
                logger.ok(f"✅ 最终三页报告已生成：{out_pdf}")
        except Exception:
            pass


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
            P9M_DIR_DEFAULT,
            r"\\192.168.0.200\粒度报告",
            r"\\192.168.0.105\SanMingLiJing",
            r"\\化工检测2\粒度报告",
            r"\\WIN-EK6CSI67PON\SanMingLiJing",
        ]
        self.last_tma_dir: Optional[str] = None
        self.last_lj_dir:  Optional[str] = P9M_DIR_DEFAULT
        self.last_out_dir: Optional[str] = OUTPUT_DIR_DEFAULT

        try:
            self.tma_path.set(self.tma_dir_presets[0])
            self.lj_path.set(self.lj_dir_presets[0])
        except Exception:
            pass

        # 参数变量
        self.lj_value       = tk.StringVar()
        self.span_value     = tk.StringVar()
        self.t1_value       = tk.StringVar()
        self.t2_value       = tk.StringVar()
        self.m_value        = tk.StringVar()
        self.h_value        = tk.StringVar()
        self.tma_value      = tk.StringVar()
        self.tmaname_value  = tk.StringVar()
        self._tmaname_source_path = ""

        # m 或 H 一旦由用户填写/自动读取完成，即自动重算 TMA。
        self.m_value.trace_add("write", self._on_mh_value_changed)
        self.h_value.trace_add("write", self._on_mh_value_changed)
        self.weight_xlsx_var  = tk.StringVar(value=WEIGHT_XLSX_DEFAULT)
        self.template_pdf_var = tk.StringVar(value="内置三页版式（无需模板）")

        # P9M 粒径集成状态：只保存“数据位置 + Record ID/索引”，
        # 选择阶段不生成任何粒径 PDF。
        self._p9m_source_path = ""
        self._p9m_selected_record_ids: List[str] = []
        self._p9m_selected_indices: List[int] = []
        self._p9m_active_record_id = ""
        self._p9m_active_index: Optional[int] = None
        self._p9m_current_record = None
        self._p9m_current_report = ""
        self._p9m_dialog = None

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
                            label="粒径报告",
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

        # 最终 PDF：内置三页版式，不依赖外部模板
        tk.Label(
            path_panel,
            text="  最终 PDF",
            bg=_C.PANEL, fg=_C.FG2,
            font=_C.FONT_LABEL,
            anchor="w"
        ).grid(row=4, column=0, sticky="w", padx=(8, 6), pady=3)
        tk.Label(
            path_panel,
            text="内置三页版式（第一页 COA + 第二页 TMA + 第三页粒径）",
            bg=_C.INPUT_BG, fg=_C.GREEN,
            font=_C.FONT_MONO,
            anchor="w", padx=8, pady=4
        ).grid(row=4, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=3)

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
                     row=0, column=0, columnspan=4,
                     sticky="w", padx=8, pady=(6, 4))

        # 参数字段定义：(label, var, accent_color, entry_width)
        # 第一行新增 SPAN；D50 / SPAN 均来自已确认的 P9M Record。
        fields_row1 = [
            ("D50 粒径", self.lj_value,   _C.ORANGE, 10),
            ("SPAN",     self.span_value, _C.ORANGE, 10),
            ("T1  °C",   self.t1_value,   _C.CYAN,   10),
            ("T2  °C",   self.t2_value,   _C.CYAN,   10),
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

        # tmaname 同时驱动 PDF 和默认输出文件名，可由用户手动覆盖。
        tmaname_box = _FieldBox(
            param_panel, "报告名称（tmaname，可修改）",
            self.tmaname_value, entry_width=48, accent=_C.CYAN)
        tmaname_box.grid(
            row=3, column=0, columnspan=4,
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
        """粒径入口：选择 P9M，并只保存数据位置与 Record ID；不立即出粒径报告。"""
        try:
            dlg = _P9MReportDialog(self)
            self._p9m_dialog = dlg
        except Exception as e:
            self.logger.error(f"P9M 粒径窗口打开失败：{e}")
            messagebox.showerror("粒径报告", str(e), parent=self.root)

    def _choose_existing_lj(self):
        """保留旧版：直接选择已有 PDF / PNG 粒径报告。"""
        init = self._pick_initialdir(
            self.lj_path.get(), self.last_lj_dir, self.lj_dir_presets
        )
        path = filedialog.askopenfilename(
            parent=self.root,
            title="选择现有粒径 PDF / PNG",
            initialdir=init,
            filetypes=[
                ("粒径 PDF/PNG", "*.pdf;*.png"),
                ("全部文件", "*.*"),
            ]
        )
        if not path:
            return

        path = normalize_path_separators(path.strip())
        self.lj_path.set(path)

        # 切回传统 PDF/PNG 时，不再把之前的 P9M Record 当作当前来源。
        self._p9m_source_path = ""
        self._p9m_selected_record_ids = []
        self._p9m_selected_indices = []
        self._p9m_active_record_id = ""
        self._p9m_active_index = None
        self._p9m_current_record = None
        self._p9m_current_report = ""
        self.span_value.set("")

        try:
            self.last_lj_dir = os.path.dirname(path)
            self._remember_dir_in_combo(
                self.lj_combo, self.lj_dir_presets, self.last_lj_dir
            )
        except Exception:
            pass

        self.logger.sep()
        self.logger.info(f"粒径文件: {path}")
        self._set_status(f"已选粒径: {os.path.basename(path)}")

        ext = os.path.splitext(path)[1].lower()
        if ext == ".png":
            self.logger.warn("png 粒径：请手动填入或点【读取D50 OCR】")
        elif ext == ".pdf":
            self.logger.info("pdf 粒径：生成报告时自动转 PNG 并触发 OCR")

    def _reload_current_p9m_record(self, update_fields: bool = True):
        """按已保存的 P9M 路径 + Record ID/索引重新解析当前记录。"""
        path = normalize_path_separators(
            (getattr(self, "_p9m_source_path", "") or "").strip()
        )
        if not path or not os.path.isfile(path):
            return None

        try:
            records = _p9m_parse_records(path)
        except Exception as e:
            self._log_safe("warn", f"P9M 重新解析失败：{e}")
            return None

        rec = None
        active_id = str(getattr(self, "_p9m_active_record_id", "") or "")
        active_idx = getattr(self, "_p9m_active_index", None)

        if active_id:
            for r in records:
                if str(r.record_id) == active_id:
                    rec = r
                    break

        if rec is None and isinstance(active_idx, int) and 0 <= active_idx < len(records):
            rec = records[active_idx]

        if rec is None:
            return None

        self._p9m_current_record = rec

        if update_fields:
            if rec.d50 is not None:
                self.root.after(0, lambda v=_p9m_n3(rec.d50): self.lj_value.set(v))
            if rec.span is not None:
                self.root.after(0, lambda v=_p9m_n3(rec.span): self.span_value.set(v))

        return rec

    def _sync_p9m_d50_span(self) -> bool:
        rec = self._reload_current_p9m_record(update_fields=True)
        if rec is None:
            self._log_safe("warn", "尚未确认 P9M Record，D50/SPAN 未读取。")
            return False
        self._log_safe(
            "ok",
            f"✅ P9M ID {rec.record_id} → D50={_p9m_n3(rec.d50)}  SPAN={_p9m_n3(rec.span)}"
        )
        return True


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
                        self.span_value.set(str(_s or "")),
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
                self.span_value.set("" if _sp == "—" else str(_sp)),
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
            if getattr(self, "_p9m_source_path", ""):
                self._sync_p9m_d50_span()
                return
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
            return T1, T2, H

        except Exception as e:
            self._cached_tma_data = None
            self._log_safe("error", f"读取/识别失败：{e}")
            self._set_status_safe("读取失败")
            return None

    def _on_mh_value_changed(self, *_args):
        """m 或 H 改变后自动计算 TMA；手工填写 M 也会立即生效。"""
        try:
            self.root.after_idle(lambda: self._try_update_tma_from_mh(force=True))
        except Exception:
            pass

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
        """
        一键读取：
          1) 从 .001/TMA 文件读取并计算 T1、T2、H；
          2) 按已保存的 P9M 路径 + Record ID 读取 D50、SPAN；
          3) M 已手工填写则保留；为空时尝试从称量表获取；
          4) M + H 齐全后自动计算 TMA。
        """
        def _worker():
            self._log_safe("sep", "")
            self._log_safe("info", "═══ 一键读取开始 ═══")
            self._set_status_safe("一键读取中…")

            # 1. .001 / TMA -> T1 / T2 / H
            try:
                self._read_tma_and_fill(mode="auto")
            except Exception as e:
                self._log_safe("error", f"TMA 读取异常：{e}")

            # 2. P9M -> D50 / SPAN
            try:
                self._sync_p9m_d50_span()
            except Exception as e:
                self._log_safe("error", f"P9M D50/SPAN 读取异常：{e}")

            # 3. M：用户已填写则不覆盖；否则尝试从称量表读取。
            if not (self.m_value.get() or "").strip():
                try:
                    self._read_m_and_fill(force=False)
                except Exception as e:
                    self._log_safe("error", f"M 读取异常：{e}")
            else:
                self._log_safe("info", f"保留已填写 M={self.m_value.get().strip()}")

            # m/H 的 trace 会在字段回填后自动计算 TMA；这里再安排一次兜底。
            try:
                self.root.after(100, lambda: self._try_update_tma_from_mh(force=True))
            except Exception:
                pass

            self._log_safe("info", "═══ 一键读取完成 ═══")
            self._set_status_safe("一键读取完成")

        self._run_in_thread(_worker)


    def on_auto_read(self):
        def _worker():
            self._log_safe("sep", "")
            self._set_status_safe("自动读取中…")
            self._read_tma_and_fill(mode="auto")
            self._sync_p9m_d50_span()
            self._try_update_tma_from_mh(force=True)
            if not (self.m_value.get() or "").strip():
                self._read_m_and_fill(force=False)
            self._try_update_tma_from_mh(force=False)
        self._run_in_thread(_worker)

    def on_super_read(self):
        def _worker():
            self._log_safe("sep", "")
            self._set_status_safe("超级梯度中…")
            self._read_tma_and_fill(mode="super")
            self._sync_p9m_d50_span()
            self._try_update_tma_from_mh(force=True)
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
        # P9M 模式不在选择阶段生成任何独立粒径报告。
        if getattr(self, "_p9m_source_path", ""):
            return None
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

        # 每次生成前按“P9M位置 + Record ID/索引”重新读取，避免依赖中间粒径PDF。
        p9m_rec = self._reload_current_p9m_record(update_fields=False)

        if not tma_path:
            miss.append("TMA路径")
        if p9m_rec is None:
            miss.append("P9M粒径记录")

        if p9m_rec is not None:
            lj = _p9m_n3(p9m_rec.d50)
            span_value = _p9m_n3(p9m_rec.span)
            p9m_time = _normalize_datetime_seconds(p9m_rec.measurement_time)
        else:
            lj = (self.lj_value.get() or "").strip()
            span_value = (self.span_value.get() or "").strip()
            p9m_time = ""

        t1 = (self.t1_value.get() or "").strip()
        t2 = (self.t2_value.get() or "").strip()
        m = (self.m_value.get() or "").strip()
        H = (self.h_value.get() or "").strip()
        tma = (self.tma_value.get() or "").strip()

        if not lj: miss.append("D50")
        if not span_value: miss.append("SPAN")
        if not t1: miss.append("T1")
        if not t2: miss.append("T2")

        has_tma = bool(tma)
        has_mh = bool(m) and bool(H)
        if not has_tma and not has_mh:
            miss.append("TMA（或 M+H）")

        if miss:
            self._log_safe("error", "信息不全，无法生成报告。缺少项如下：")
            for x in miss:
                self._log_safe("miss", x)
            return False, {}

        if not has_tma:
            try:
                tma_calc = calc_tma_from_m_h(float(m), float(H))
                tma = f"{tma_calc:.3f}"
                self.root.after(0, lambda v=tma: self.tma_value.set(v))
                self._log_safe("ok", f"TMA = {tma}（由 M/H 计算）")
            except Exception as e:
                self._log_safe("error", f"TMA 计算失败：{e}")
                return False, {}

        tmaname = self._sync_tmaname_from_tma_path()
        if not tmaname:
            tmaname = _default_tmaname_from_path(tma_path)
        if not tmaname:
            self._log_safe("error", "报告名称（tmaname）不能为空。")
            return False, {}

        report_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # T1/T2/TMA：读取 TMA 文件内部测试时间。
        tma_time = _extract_tma_internal_datetime(tma_path, self._algo_logger)
        if not tma_time:
            self._log_safe(
                "warn",
                "未从 TMA 文件内部识别到测试时间；T1/T2/TMA 的检测时间将留空。"
            )

        def _fmt(v, nd):
            try:
                return f"{float(v):.{nd}f}"
            except Exception:
                return v

        return True, {
            "lijing":    _fmt(lj, 3),
            "span":      _fmt(span_value, 3),
            "qifawd":    _fmt(t1, 2),
            "zuidawd":   _fmt(t2, 2),
            "tmamd":     _fmt(tma, 3),
            "shengchan": report_time,
            "p9m_time":  p9m_time,
            "tma_time":  tma_time,
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

                p9m_rec = self._reload_current_p9m_record(update_fields=False)

                # 只有旧 PDF/PNG 模式才需要提前准备粒径图片。
                lj_png = None
                if p9m_rec is None:
                    lj_png = self._ensure_lj_png()
                    if not lj_png:
                        self.root.after(0, lambda: _TechButton.set_all_enabled(True))
                        return

                tma_tif = self._ensure_tma_tif(values)
                if not tma_tif:
                    self.root.after(0, lambda: _TechButton.set_all_enabled(True))
                    return

                _v, _lj, _tif, _rec = values, lj_png, tma_tif, p9m_rec
                self.root.after(
                    0,
                    lambda: self._generate_save_dialog(_v, _lj, _tif, _rec)
                )

            except Exception as e:
                self.root.after(0, lambda: self.logger.error(f"生成异常：{e}"))
                self.root.after(0, lambda: _TechButton.set_all_enabled(True))

        _TechButton.set_all_enabled(False)
        threading.Thread(target=_worker, daemon=True).start()


    def _generate_save_dialog(self, values: dict, lj_png: Optional[str], tma_tif: str, p9m_rec=None):
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
            self._do_generate_pdf(values, lj_png, tma_tif, out_pdf, p9m_rec=p9m_rec)
            self.root.after(0, lambda: _TechButton.set_all_enabled(True))
            self.root.after(0, lambda: self._set_status("就绪"))
        t = threading.Thread(target=_gen_worker, daemon=True)
        t.start()

    def _do_generate_pdf(
        self,
        values: dict,
        lj_png: Optional[str],
        tma_tif: str,
        out_pdf: str,
        p9m_rec=None,
    ):
        """
        最终阶段一次性生成大报告。
        P9M 模式下只在临时目录里生成粒径页素材，退出后自动删除，
        不产生类似 *_粒度测试报告.pdf 的独立文件。
        """
        try:
            self._log_safe("info", "使用内置三页最终版式生成 PDF…")

            if p9m_rec is not None:
                with tempfile.TemporaryDirectory(prefix="one_bg_p9m_") as td:
                    tmp_pdf = os.path.join(td, "particle_report.pdf")
                    tmp_png = os.path.join(td, "particle_report.png")

                    _p9m_generate_pdf(p9m_rec, tmp_pdf)

                    doc = fitz.open(tmp_pdf)
                    try:
                        page = doc.load_page(0)
                        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
                        pix.save(tmp_png)
                    finally:
                        doc.close()

                    build_final_pdf_internal(
                        out_pdf=out_pdf,
                        values=values,
                        tma_img=tma_tif,
                        lj_img=tmp_png,
                        logger=self.logger,
                        root=self.root,
                    )
            else:
                if not lj_png:
                    raise ValueError("缺少粒径页面素材。")
                build_final_pdf_internal(
                    out_pdf=out_pdf,
                    values=values,
                    tma_img=tma_tif,
                    lj_img=lj_png,
                    logger=self.logger,
                    root=self.root,
                )

            self._log_safe("ok", f"✅ 报告已生成: {out_pdf}")
            self._set_status_safe(f"✅ {os.path.basename(out_pdf)}")

        except Exception as e:
            self._log_safe("error", f"最终 PDF 生成失败：{e}")
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
