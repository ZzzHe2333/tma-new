# -*- coding: utf-8 -*-
"""
TMA 数据分析处理器（TMA Super Max）- v218

本脚本用于处理 TA Instruments / TA Trios 导出的 TMA 数据文件，提供以下能力：
1) 读取文本数据（.txt 等）并解析 StartOfData 后的数值区段。
2) 对常见的 TAJM 二进制导出（常见扩展名 .001~.999）尝试解密并转为可读文本。
3) 自动识别 T1/T2：
   - T2：高度（第 3 列）最大值对应的温度（第 2 列）
   - T1：在 x>=START_TEMP_FOR_T1 且 x<=T2 的区间内，高度最小值对应的温度
4) 曲线“温度轴拉伸/压缩”(warp)：根据用户输入的 T1n/T2n 调整曲线形状。
   - 使用“逆映射”(inverse mapping) 方式，避免锚点贴边导致的插值平台/异常折线。
   - 可选在 [T1,T2] 区间做单调修复，避免单点掉落造成“裂开点”。
5) 按 mg 对高度缩放，并输出 LG 列表。
6) Tkinter GUI：日志、梯度/超级梯度算法、绘图与 TIFF 导出。
7) v216：新增 GUI【显示积分值】按钮，并优化底部进度条逐节点刷新。
8) v218：绘图窗口新增【录入数据】按钮，可按批次号把当前绘图对应的 T1/T2/M/H/TMA图位置 写入 sp.csv；【显示积分值】仅写入 log，不再弹窗。

代码维护约定（v207 起）：
- 尽量为每个函数补齐 docstring（用途/参数/返回/异常/注意事项）。
- 关键变量（全局常量、类成员、重要中间量）增加解释性注释，方便后续迭代与排错。
"""
VERSION = "v218"  # 脚本版本号：用于窗口标题、日志、导出图右下角等显示
# ------------ 公告内容 ------------
Gonggao_Message_by_thisone = ("快速上手：\n"  # 启动/Soft Log 输出的“快速上手”说明文本（多行拼接）
"  (1) 点击【选择文件】读取 .txt 或 .001~.999 文件：自动识别 T1/T2，计算 H=H2-H1，并输出 LG 列表。\n"
"      * v208：输入路径支持下拉预制文件夹（仅用于快速定位），也支持手动粘贴/输入文件全路径。\n"
"      * 会尝试解密 .001 系列文件；解密失败会提示错误。\n"
"  (2) 如需手动修正：修改 T1/T2/mg 后点击【执行调整】生成新文件（不影响原文件）。\n"
"  (3) 若 T1 识别不准：点击【梯度算法】或【超级梯度算法】重新计算 T1（T2 始终取最大值）。\n"
"      * 两者差异主要在扫描步长/精度。\n"
"  (4) 点击【使用绘图】打开绘图窗口：可单独修改 mg（仅影响图中备注），并导出 .tif /【仿生输出】。\n"
"      * 默认导出到原文件同路径；也可勾选【启用新路径】后导出到下拉框目录。\n"
"  (5) 软件如出现异常：勾选【⚠️ DEBUG信息模式】可查看更细的函数级日志、耗时/内存等。")
# ------------ usually ------------
import os
import re
import csv
import math
import time
import struct
import logging
import datetime
import tracemalloc
import numpy as np
from dataclasses import dataclass
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple
# ------------ thinter ------------
import tkinter as tk
from tkinter import font as tkfont
from tkinter.scrolledtext import ScrolledText
from tkinter import ttk, filedialog, messagebox
# ------------ plotting ------------
import matplotlib
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.ticker import MultipleLocator, NullFormatter, FixedLocator

# Try to make Chinese text display correctly on Windows.
matplotlib.rcParams['font.family'] = 'sans-serif'
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'SimSun', 'Arial Unicode MS', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False
# -------------------------
# 路径分隔符修正（Windows/Tk 常见：UNC 以 //server/share/.. 形式返回）
# 目的：避免出现 “.../dir\file” 这种混合分隔符，导致部分环境下读写失败。
# -------------------------
def normalize_path_separators(p: str) -> str:
    """把路径中的分隔符统一成一种风格，并清理可能导致系统报错的控制字符。

    规则：
    - 先移除复制/粘贴时可能混入的控制字符（\r、\n、\t、Unicode 换行符等）
      否则在 Windows 写文件时可能出现: [Errno 22] Invalid argument
    - 若以 '//' 开头（Tk 下 UNC 常见写法），或 '/' 数量 >= '\\' 数量：统一为 '/'
    - 否则统一为 '\\'
    """
    if p is None:
        return ""
    p = str(p)
    if not p:
        return p

    # 1) 清理控制字符（常见就是不小心粘贴了换行导致 ...\n.001）
    p = re.sub(r"[\r\n\t\v\f\u2028\u2029]", "", p)
    # 2) 进一步移除 ASCII 控制字符 (0-31) 与 DEL(127)
    p = "".join(ch for ch in p if (ord(ch) >= 32 and ord(ch) != 127))

    if not p:
        return p

    # Tk 的 UNC 网络路径常为 //SERVER/Share/...
    if p.startswith("//") or (p.count("/") >= p.count("\\")):
        return p.replace("\\", "/")
    return p.replace("/", "\\")
# -------------------------
def join_keep_style(dir_path: str, name: str) -> str:
    """按 dir_path 的分隔符风格进行拼接，避免 join 造成混合分隔符。"""
    dir_path = normalize_path_separators(dir_path or "")
    if not dir_path:
        return name
    if dir_path.startswith("//") or (dir_path.count("/") >= dir_path.count("\\")):
        # 统一 '/'
        dp = dir_path.replace("\\", "/").rstrip("/")
        return dp + "/" + name
    # 统一 '\'
    dp = dir_path.replace("/", "\\").rstrip("\\")
    return dp + "\\" + name


def resolve_sp_csv_path() -> str:
    """返回 sp.csv 路径：优先桌面固定路径，找不到则回退到 .\\excal\\sp.csv。"""
    if os.path.isfile(PREFERRED_SP_CSV):
        return os.path.abspath(PREFERRED_SP_CSV)
    os.makedirs(os.path.dirname(FALLBACK_SP_CSV), exist_ok=True)
    return os.path.abspath(FALLBACK_SP_CSV)


def extract_batch_info_any(file_name: str) -> Tuple[str, str]:
    """从文件名任意位置提取连续 10 位或 8 位数字，返回 (批次号, 排列号)。

    规则：
    - 优先 10 位连续数字：批次号=10位，排列号=后8位
    - 否则 8 位连续数字：批次号=8位，排列号=8位
    - 都没有：返回空字符串
    """
    base = os.path.splitext(os.path.basename(str(file_name or "")))[0]
    m10 = re.search(r"(?<!\d)(\d{10})(?!\d)", base)
    if m10:
        batch = m10.group(1)
        return batch, batch[2:10]
    m8 = re.search(r"(?<!\d)(\d{8})(?!\d)", base)
    if m8:
        batch = m8.group(1)
        return batch, batch
    return "", ""


def _read_csv_rows_auto(csv_path: str) -> Tuple[List[Dict[str, str]], List[str]]:
    if not os.path.isfile(csv_path):
        return [], []

    last_err = None
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with open(csv_path, "r", newline="", encoding=enc) as f:
                reader = csv.DictReader(f)
                rows = []
                for row in reader:
                    rows.append({str(k or ""): str(v or "") for k, v in (row or {}).items()})
                return rows, list(reader.fieldnames or [])
        except Exception as exc:
            last_err = exc
    if last_err is not None:
        raise last_err
    return [], []


def _normalize_sp_headers(headers: List[str]) -> List[str]:
    out: List[str] = []
    for h in headers or []:
        hs = str(h or "").strip()
        if hs and hs not in out:
            out.append(hs)
    for h in SP_FULL_HEADERS:
        if h not in out:
            out.append(h)
    if ("TMA位置" not in out) and ("TMA图位置" not in out):
        out.append("TMA位置")
    return out


def _ensure_row_headers(row: Dict[str, str], headers: List[str]) -> Dict[str, str]:
    out = {str(k or ""): str(v or "") for k, v in (row or {}).items()}
    for h in headers:
        out.setdefault(h, "")
    return out


def _pick_tma_path_headers(headers: List[str]) -> List[str]:
    cols = [h for h in TMA_PATH_CANDIDATE_HEADERS if h in headers]
    if not cols:
        headers.append("TMA位置")
        cols = ["TMA位置"]
    return cols


def _sort_sp_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    def _key(row: Dict[str, str]):
        s = str((row or {}).get("排列号", "") or "").strip()
        return int(s) if s.isdigit() else float("inf")
    return sorted(rows, key=_key)


def _write_sp_csv(csv_path: str, rows: List[Dict[str, str]], headers: List[str]) -> None:
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    norm_headers = _normalize_sp_headers(headers)
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=norm_headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(_ensure_row_headers(row, norm_headers))


def format_height_um(v: float) -> str:
    """高度显示规则（μm，不含单位）：

    - |v| > 1000：保留到个位（无小数）
    - |v| <= 1000：保留 1 位小数
    """
    try:
        if v is None:return "NA"
        v = float(v)
        if not math.isfinite(v):return "NA"
        if abs(v) > 1000.0:return f"{v:.0f}"
        return f"{v:.1f}"
    except Exception:return "NA"

def format_plot_temp_c(v: float) -> str:
    """温度在绘图/录入时的统一显示规则（°C，不含单位）：保留 2 位小数。"""
    try:
        if v is None:
            return "NA"
        v = float(v)
        if not math.isfinite(v):
            return "NA"
        return f"{v:.2f}"
    except Exception:
        return "NA"


def build_plot_display_metrics(metrics: Dict[str, Any]) -> Dict[str, str]:
    """把当前计算值转换为与绘图标注完全一致的显示字符串。"""
    m = dict(metrics or {})
    return {
        "T1": format_plot_temp_c(m.get("T1")),
        "T2": format_plot_temp_c(m.get("T2")),
        "H": format_height_um(m.get("H")),
    }


# =========================
# 解密核心
# 说明：不做后缀检测；只要“能解密”就解密。
# 核心逻辑 UTF-16LE 头部 + float32(<5f>) 数据表解析，输出为可读的 StartOfData + 5列纯数字。
# =========================

def _tajm_find_header_end(buf: bytes, log=None) -> int:
    """
    头部是 UTF-16LE 文本（常见 ASCII+0 的形式），通常以 CRLF 结束，然后进入二进制区。
    从前 64KB 内寻找最后一个仍然像“文本头部”的 CRLF 位置作为头部结束。
    """
    crlf = b"\r\x00\n\x00"
    scan_limit = min(len(buf), 65536)

    last_good = None
    pos = 0
    hits = 0

    while True:
        p = buf.find(crlf, pos, scan_limit)
        if p == -1:break
        hits += 1
        candidate = p + len(crlf)
        window = buf[candidate:candidate + 512]
        if len(window) < 64:break
        odd = window[1::2]  # UTF-16LE 高字节
        zero_ratio = odd.count(0) / max(1, len(odd))
        if log:log(f"[tajm][header-scan] CRLF@{p} -> candidate={candidate}, odd_zero_ratio={zero_ratio:.3f}")
        if zero_ratio >= 0.55:
            last_good = candidate
            pos = candidate
        else:break
    if log:log(f"[tajm][header-scan] scanned_bytes={scan_limit}, crlf_hits={hits}, header_end={last_good}")
    if last_good is None:raise RuntimeError("TAJM: 未能定位 UTF-16LE 头部结束位置（找不到可靠的 CRLF 终点）。")
    return last_good


def _tajm_find_data_start_by_first_time(buf: bytes, search_from: int, log=None) -> int:
    """
    数据区通常为 5 个 little-endian float32 组成的记录（20 字节/行）。
    优先寻找 time=0.004 的 float32；找不到则用启发式扫描。
    """
    needle = struct.pack("<f", 0.004)
    p = buf.find(needle, search_from)

    if log:log(f"[tajm][data-find] try needle float32(0.004) from offset {search_from} -> pos={p}")

    if p != -1:return p

    scan_to = min(len(buf) - 40, search_from + 4096)
    if log:log(f"[tajm][data-find] fallback scan range [{search_from}, {scan_to}]")

    for start in range(search_from, scan_to):
        try:t, temp, dim, force, flow = struct.unpack_from("<5f", buf, start)
        except struct.error:break
        if not all(map(math.isfinite, [t, temp, dim, force, flow])):continue

        # 粗略范围约束（参考 TAJM.py）
        if not (0 <= t <= 1e6 and -500 <= temp <= 2000 and -1e7 <= dim <= 1e7 and
                -1e6 <= force <= 1e6 and -1e6 <= flow <= 1e6):
            continue

        # 再看下一行 time 是否非递减
        try:t2 = struct.unpack_from("<f", buf, start + 20)[0]
        except struct.error:continue

        if math.isfinite(t2) and t2 >= t:
            if log:log(f"[tajm][data-find] fallback hit at offset {start} -> first_row=(t={t}, temp={temp}, ..), next_t={t2}")
            return start
    raise RuntimeError("TAJM: 未能定位数据区起点（float32 表）。")


def _tajm_parse_rows(buf: bytes, start: int, log=None, max_rows: int = 200000):
    """
    从 start 开始按 <5f> 读取记录，直到遇到不合理数据停止。
    """
    rows = []
    pos = start
    prev_t = -1e18
    stops = 0

    while pos + 20 <= len(buf) and len(rows) < max_rows:
        t, temp, dim, force, flow = struct.unpack_from("<5f", buf, pos)

        if not all(map(math.isfinite, [t, temp, dim, force, flow])):
            stops += 1
            if log:
                log(f"[tajm][parse] stop(non-finite) at pos={pos}, row_index={len(rows)}")
            break

        if not (0 <= t <= 1e6 and -500 <= temp <= 2000 and -1e7 <= dim <= 1e7 and
                -1e6 <= force <= 1e6 and -1e6 <= flow <= 1e6):
            stops += 1
            if log:
                log(f"[tajm][parse] stop(out-of-range) at pos={pos}, row_index={len(rows)} "
                    f"values=(t={t}, temp={temp}, dim={dim}, force={force}, flow={flow})")
            break

        if t < prev_t - 1e-3:
            stops += 1
            if log:
                log(f"[tajm][parse] stop(time-not-monotonic) at pos={pos}, row_index={len(rows)} t={t} prev_t={prev_t}")
            break

        prev_t = t
        rows.append((t, temp, dim, force, flow))
        pos += 20

        if log and len(rows) in (1, 2, 3, 10, 100, 500, 1000, 2000, 5000, 10000):
            log(f"[tajm][parse] progress rows={len(rows)} latest=(t={t}, temp={temp}, dim={dim}, force={force}, flow={flow}) pos={pos}")

    if log:
        log(f"[tajm][parse] done rows={len(rows)}, start={start}, end_pos={pos}, stops={stops}")

    return rows


def try_tajm_decrypt_to_text(in_path: str, log=None) -> dict:
    """
    尝试用 TAJM 解密思路把“二进制/不可读”文件转成可读取的文本。
    - 不做后缀检测（按你的要求）
    - 只判断能否成功解密：成功则返回 ok=True + text + rows 等信息；失败返回 ok=False
    """
    t0 = datetime.datetime.now()
    r = {"ok": False, "input": in_path}

    try:
        if log:
            log(f"[tajm] try decrypt: {in_path}")

        if not os.path.isfile(in_path):
            raise FileNotFoundError(f"找不到文件：{in_path}")

        with open(in_path, "rb") as f:buf = f.read()

        if len(buf) < 64:raise RuntimeError("文件太小，疑似不是 TAJM 可解密格式。")

        if log:
            log(f"[tajm][io] file_size={len(buf)} bytes; leading_bytes={buf[:8].hex(' ')}")

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

        dt = (datetime.datetime.now() - t0).total_seconds()
        r.update({
            "ok": True,
            "text": out_text,
            "rows": len(rows),
            "header_end": header_end,
            "data_start": data_start,
            "elapsed": dt,
        })
        if log:
            log(f"[tajm] ✅ decrypt ok rows={len(rows)} header_end={header_end} data_start={data_start} elapsed={dt:.3f}s")
        return r

    except Exception as e:
        if log:
            log(f"[tajm] ❌ decrypt failed: {e}")
        r["err"] = str(e)
        return r


def load_text_prefer_tajm(in_path: str, logger: logging.Logger) -> Tuple[str, dict]:
    """统一入口（V206 更稳）：

    处理顺序：
    1) 先探测文件头是否已经是“可读文本 + 含 StartOfData + 有连续数据行”。
       - 若是：直接按文本读取（避免误触发 TAJM 解密）
       - ✅ 修复 v205：UTF-16LE 无 BOM 的纯文本，有概率被误当成二进制去解密，导致曲线数据异常
    2) 否则尝试 TAJM 解密（不做后缀判断；能解密就解密）
    3) 解密失败再回退到自动文本读取

    返回：(text, meta)
      meta: {"used": "tajm"/"plain", ...}
    """
    # --- 0) 快速探测：是否“像纯文本数据文件” ---
    probe_meta: Dict[str, Any] = {"ok": False}

    try:
        with open(in_path, "rb") as f:
            head = f.read(512 * 1024)  # 512KB 足够判断 StartOfData + 前几百行数据
    except Exception as e:
        head = b""
        probe_meta = {"ok": False, "err": f"head_read_failed: {e}"}

    if head:
        float_re = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")

        def _count_data_lines_after_marker(text: str, max_scan: int = 300) -> int:
            """统计 StartOfData 之后的“连续数据行”数量。
            
            用途：
                load_text_prefer_tajm() 在决定“把文件当纯文本处理”还是“尝试 TAJM 解密”时，
                需要一个快速且低成本的探测方法：如果 StartOfData 后面确实跟着一段连续的数字表，
                就更可能是可读文本；反之才考虑走二进制解密。
            
            参数：
                text: 已解码文本。
                max_scan: 最大扫描行数（避免巨大文件扫描过慢）。
            
            返回：
                int：连续数据行的数量（用于做阈值判断）。
            """
            
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
            for line in lines[marker_idx + 1 : marker_idx + 1 + max_scan]:
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

        decode_attempts: List[Tuple[str, str]] = []
        try:
            if head.startswith(b"\xff\xfe") or head.startswith(b"\xfe\xff"):
                decode_attempts.append(("utf-16(BOM)", head.decode("utf-16", errors="ignore")))
        except Exception:
            pass

        # 无 BOM 也尝试（errors=ignore 仅用于“探测”，真实读取交给 read_text_auto）
        for enc in ("utf-16le", "utf-16be", "utf-8", "gbk"):
            try:
                decode_attempts.append((enc, head.decode(enc, errors="ignore")))
            except Exception:
                continue

        best = {"enc": None, "data_lines": 0}
        for enc, s in decode_attempts:
            n = _count_data_lines_after_marker(s)
            if n > best["data_lines"]:
                best = {"enc": enc, "data_lines": n}

        # 经验阈值：>=5 行基本可判定为真实数据
        if best["data_lines"] >= 5:
            probe_meta = {
                "ok": True,
                "enc": best["enc"],
                "data_lines": int(best["data_lines"]),
                "reason": "plain_text_probe",
            }

    if probe_meta.get("ok"):
        try:
            text = read_text_auto(in_path, logger)
            return text, {"used": "plain", **probe_meta}
        except Exception as e:
            # 探测认为是纯文本，但完整读取失败：继续走后续流程（不直接报错）
            logger.debug(f"纯文本探测命中但读取失败，将继续尝试 TAJM 解密：{e}")

    # --- 1) 再尝试解密（不做后缀判断） ---
    r = try_tajm_decrypt_to_text(in_path, log=logger.debug)
    if r.get("ok"):
        return r["text"], {"used": "tajm", **r}

    # --- 2) 回退到自动文本读取 ---
    text = read_text_auto(in_path, logger)
    return text, {"used": "plain", "reason": "fallback_after_tajm_failed", "tajm_err": r.get("err")}


# =========================
# 可调参数
# =========================
START_TEMP_FOR_T1 = 60.0   # 你说“数据开始(60℃附近)”，默认从>=60开始找T1
MONOTONIC_FIX_T1_T2 = True  # 修复：强制在[T1,T2]区间高度单调不下降，避免出现“裂开点”
MONOTONIC_METHOD = "bridge"  # bridge(线性桥接掉点) / isotonic(平滑) / cummax(硬钳制)
# 如果文件没有 StartOfData 标记（极少数情况），用温度范围过滤掉头部乱入的数字。
FALLBACK_TEMP_MIN = 40.0
FALLBACK_TEMP_MAX = 400.0
NUM_EXT_PATTERNS = tuple(f"*.{i:03d}" for i in range(1, 1000))  # 兼容 Windows 文件对话框过滤
FLOAT_FIND_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")

# =========================
# 输入路径下拉框（v208）
# 说明：这些是“预制的常用文件夹路径”，用于更快定位网络盘目录。
# 用户仍需在该目录内选择具体文件（.txt / .001~.999）。
# =========================
PRESET_INPUT_DIRS = (
    r"//192.168.0.105/ta/Data/TMA/三明样品",
    r"//192.168.0.105/ta/Data/TMA",
    r"//192.168.0.105/ta/Data/TMA/实验室样品/",
)

PREFERRED_SP_CSV = r"C:\Users\Administrator\Desktop\super_afk_bg\excal\sp.csv"
FALLBACK_SP_CSV = os.path.abspath(os.path.join(".", "excal", "sp.csv"))
SP_FULL_HEADERS = [
    "批次号", "D50", "Span", "T1", "T2", "M", "H", "面积", "TMA位置", "水分", "粒径图位置", "排列号"
]
TMA_PATH_CANDIDATE_HEADERS = ("TMA图位置", "TMA位置")


def get_desktop_path() -> str:
    r"""尽可能返回当前电脑桌面绝对路径（用于出图路径下拉项）。

    - 优先 ~/Desktop
    - Windows 常见 OneDrive 桌面：%OneDrive%\Desktop / %OneDriveConsumer%\Desktop
    """
    home = os.path.expanduser("~")
    cand = os.path.abspath(os.path.join(home, "Desktop"))
    if os.path.isdir(cand):
        return cand

    onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    if onedrive:
        cand2 = os.path.abspath(os.path.join(onedrive, "Desktop"))
        if os.path.isdir(cand2):
            return cand2

    return cand


def place_window_top_right(win: tk.Misc, width: int, height: int, margin: int = 20) -> None:
    """Place a Tk window at the top-right corner of the screen."""
    try:
        win.update_idletasks()
        sw = int(win.winfo_screenwidth())
        x = max(0, sw - int(width) - int(margin))
        y = max(0, int(margin))
        win.geometry(f"{int(width)}x{int(height)}+{x}+{y}")
    except Exception:
        try:
            win.geometry(f"{int(width)}x{int(height)}")
        except Exception:
            pass


def place_window_bottom_right(win: tk.Misc, width: int, height: int, margin_x: int = 20, margin_y: int = 60) -> None:
    """Place a Tk window at the bottom-right corner of the screen.

    margin_y is slightly larger to avoid overlapping with taskbar on Windows.
    """
    try:
        win.update_idletasks()
        sw = int(win.winfo_screenwidth())
        sh = int(win.winfo_screenheight())
        x = max(0, sw - int(width) - int(margin_x))
        y = max(0, sh - int(height) - int(margin_y))
        win.geometry(f"{int(width)}x{int(height)}+{x}+{y}")
    except Exception:
        try:
            win.geometry(f"{int(width)}x{int(height)}")
        except Exception:
            pass



@dataclass
class ParsedLine:
    raw: str
    nums: List[float]               # 本行所有“数字token”
    spans: List[Tuple[int, int]]    # 每个数字token在原行中的 (start,end)


def read_utf16le_no_bom(path: str) -> str:
    """强制按 UTF-16LE 读取，并去掉文件开头的 BOM（若存在）。"""
    with open(path, "rb") as f:
        data = f.read()
    # UTF-16LE BOM: FF FE
    if data[:2] == bytes((255, 254)):
        data = data[2:]
    text = data.decode("utf-16le", errors="strict")
    # 保险：极少数情况下解码后仍残留 BOM 字符
    bom = chr(65279)
    if text.startswith(bom):
        text = text[len(bom):]
    return text


def write_utf16le_with_bom(path: str, text: str) -> None:
    """以 UTF-16LE 写入，并写入 BOM(FF FE)。

    说明：
    - 你之前要求“去除 BOM”时，我们输出的是“UTF-16LE 无 BOM”。
      但不少 Windows 软件/编辑器会因为没有 BOM 而把文件显示成 ANSI/ASCII。
    - 如果你希望它被稳定识别为“UTF-16 LE”，就需要保留 BOM。
    """
    bom_char = chr(65279)
    if text.startswith(bom_char):
        text = text[len(bom_char):]

    data = b"\xff\xfe" + text.encode("utf-16le")
    with open(path, "wb") as f:
        f.write(data)




def read_text_auto(path: str, logger: Optional[logging.Logger] = None) -> str:
    """尽量自动识别编码读取文本（V206 更稳）。

    识别优先级：
    1) BOM：UTF-16(LE/BE) / UTF-8-SIG
    2) 无 BOM：通过采样判断是否像 UTF-16 文本（NUL 比例 + 奇偶位 0 比例）
    3) 否则依次尝试 UTF-8、GBK

    返回：
    - 解码后的文本（如文本首字符为 BOM 字符，会被移除）
    """
    with open(path, "rb") as f:
        data = f.read()

    if not data:
        return ""

    def _strip_bom_char(s: str) -> str:
        """移除字符串开头的 BOM 字符（U+FEFF）。
        
        说明：
            某些解码路径会把 BOM 保留为文本第一个字符，
            后续字符串匹配（如 StartOfData）会受到影响，因此统一剥离。
        """
        
        bom_char = chr(65279)  # U+FEFF
        return s[len(bom_char):] if s.startswith(bom_char) else s

    # 1) UTF-8 BOM
    if data.startswith(b"\xef\xbb\xbf"):
        try:
            text = data.decode("utf-8-sig", errors="strict")
            text = _strip_bom_char(text)
            if logger:
                logger.debug(f"读取文件成功：编码=utf-8-sig（含BOM），字节数={len(data)}")
            return text
        except Exception as e:
            if logger:
                logger.debug(f"尝试 utf-8-sig 读取失败：{e}")

    # 2) UTF-16 BOM（Python 会依据 BOM 选择端序）
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        try:
            text = data.decode("utf-16", errors="strict")
            text = _strip_bom_char(text)
            if logger:
                logger.debug(f"读取文件成功：编码=utf-16（由BOM决定端序），字节数={len(data)}")
            return text
        except Exception as e:
            if logger:
                logger.debug(f"尝试 utf-16(BOM) 读取失败：{e}")

    # 3) 无 BOM：判定是否“像 UTF-16 文本”
    sample = data[:4096]
    if len(sample) >= 4 and (sample.count(0) / len(sample)) > 0.15:
        even = sample[0::2]
        odd = sample[1::2]
        even_zero = even.count(0) / max(1, len(even))
        odd_zero = odd.count(0) / max(1, len(odd))

        # UTF-16LE 常见：odd_zero 高；UTF-16BE 常见：even_zero 高
        if max(even_zero, odd_zero) >= 0.55:
            enc_guess = "utf-16le" if odd_zero >= even_zero else "utf-16be"
            try:
                text = data.decode(enc_guess, errors="strict")
                text = _strip_bom_char(text)
                if logger:
                    logger.debug(
                        f"读取文件成功：编码={enc_guess}（无BOM启发式），"
                        f"nul_ratio={sample.count(0)/len(sample):.3f}, odd_zero={odd_zero:.3f}, even_zero={even_zero:.3f}"
                    )
                return text
            except Exception as e:
                if logger:
                    logger.debug(f"尝试 {enc_guess}(无BOM启发式) 读取失败：{e}")

    # 4) 其他编码：utf-8 / gbk
    for enc in ("utf-8", "gbk"):
        try:
            text = data.decode(enc, errors="strict")
            text = _strip_bom_char(text)
            if logger:
                logger.debug(f"读取文件成功：编码={enc}，字节数={len(data)}")
            return text
        except Exception as e:
            if logger:
                logger.debug(f"尝试 {enc} 读取失败：{e}")

    raise UnicodeDecodeError("unknown", b"", 0, 1, "无法识别文件编码（utf-16/utf-8/gbk 均失败）")


def write_utf16le_no_bom(path: str, text: str) -> None:
    """以 UTF-16LE 写入（不写 BOM），与 ces.py 的输出方式一致。"""
    bom_char = chr(65279)
    if text.startswith(bom_char):
        text = text[len(bom_char):]
    with open(path, "w", encoding="utf-16le", newline="") as f:
        f.write(text)

def parse_lines(text: str) -> List[ParsedLine]:
    """把整段文本按行解析为 ParsedLine 列表。
    
    解析规则：
        - 保留原始行内容 raw（含换行符，便于回写时不破坏格式）。
        - 使用 FLOAT_FIND_RE 在每行提取所有数字 token，并记录其在原行中的 span（start,end）。
    
    返回：
        List[ParsedLine]：每行对应一个 ParsedLine（raw/nums/spans）。
    
    注意：
        该函数只负责“提取数字 token”，不判断该行是否为真正数据行。
        数据行判定由 extract_xy_from_file() 负责。
    """
    
    out = []
    for line in text.splitlines(keepends=True):
        spans = []
        nums = []
        for m in FLOAT_FIND_RE.finditer(line):
            spans.append((m.start(), m.end()))
            try:
                nums.append(float(m.group()))
            except ValueError:
                nums.append(math.nan)
        out.append(ParsedLine(raw=line, nums=nums, spans=spans))
    return out


def extract_xy_from_file(parsed: List[ParsedLine], logger: logging.Logger) -> Tuple[List[float], List[float], List[int]]:
    """从 ParsedLine 中提取 (温度x, 高度y) 以及对应的行索引。

    ✅ 兼容 3/4/5 列及以上：
    - 至少 3 个数字 token：nums[1] 视为温度(℃)，nums[2] 视为高度(μm)
    - 为避免把 header/注释行当成数据行：
        * 若行内包含除 e/E 之外的英文字母，通常不是纯数据行 -> 直接排除
        * 温度需落在合理范围（-500~2000℃）

    ✅ 数据块提取策略：
    - 先定位包含 'StartOfData' 的行（忽略大小写）。
    - 从其下一行开始，只读取“看起来像真实数据行”的连续区段。
      一旦在已开始读取数据后遇到非数据行，就认为数据块结束并停止
      （避免尾部/二段 header 继续污染 T1/T2）。
    - 若文件没有 StartOfData（极少数）：回退到温度范围过滤
      x∈[FALLBACK_TEMP_MIN, FALLBACK_TEMP_MAX]。
    """
    xs: List[float] = []
    ys: List[float] = []
    line_idxs: List[int] = []

    marker_idx: Optional[int] = None
    for i, pl in enumerate(parsed):
        if "startofdata" in (pl.raw or "").lower():
            marker_idx = i
            break

    # 匹配“除 e/E 外的字母”：用于排除 header/单位行
    non_e_letter_re = re.compile(r"[A-DF-Za-df-z]")

    def is_data_line(pl: ParsedLine) -> bool:
        """判断一行 ParsedLine 是否可以视为“数据行”。
        
        判定依据（偏保守，目的是避免 header 数字污染）：
            - 行不能为空；
            - 行内不能包含除 e/E 之外的字母（避免单位/标题行）；
            - 至少包含 3 个数字 token（保证能取到第2列温度与第3列高度）。
        
        返回：
            bool：True=可作为数据行；False=跳过。
        """
        
        if pl is None:
            return False
        raw = (pl.raw or "").strip()
        if not raw:
            return False
        # 行内含除 e/E 外字母：通常不是纯数据
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

        logger.debug(f"检测到 StartOfData：数据起始行={marker_idx + 1}，数据行数={len(xs)}")
        return xs, ys, line_idxs

    # ❗极少数文件没有 StartOfData：回退过滤（按温度范围）
    for idx, pl in enumerate(parsed):
        if is_data_line(pl):
            x = pl.nums[1]
            if FALLBACK_TEMP_MIN <= x <= FALLBACK_TEMP_MAX:
                xs.append(x)
                ys.append(pl.nums[2])
                line_idxs.append(idx)

    logger.debug(f"未检测到 StartOfData：使用温度范围过滤 [{FALLBACK_TEMP_MIN},{FALLBACK_TEMP_MAX}]，数据行数={len(xs)}")
    return xs, ys, line_idxs


def _robust_mad(arr: np.ndarray) -> float:
    """返回 MAD（乘 1.4826 后的稳健标准差近似）。"""
    a = np.asarray(arr, dtype=float)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return 0.0
    med = float(np.median(a))
    mad = float(np.median(np.abs(a - med)))
    return 1.4826 * mad



def _gaussian_smooth_1d(y: np.ndarray, sigma_pts: float) -> np.ndarray:
    """纯 NumPy 的一维高斯平滑，避免额外依赖 scipy。"""
    y = np.asarray(y, dtype=float)
    if y.size <= 2 or sigma_pts <= 0:
        return y.copy()

    radius = max(1, int(round(4.0 * float(sigma_pts))))
    xx = np.arange(-radius, radius + 1, dtype=float)
    kernel = np.exp(-0.5 * (xx / float(sigma_pts)) ** 2)
    kernel /= np.sum(kernel)

    y_pad = np.pad(y, (radius, radius), mode="edge")
    y_sm = np.convolve(y_pad, kernel, mode="same")
    return y_sm[radius:-radius]



def _find_local_extrema(y: np.ndarray) -> Tuple[List[int], List[int]]:
    """返回 (局部峰索引列表, 局部谷索引列表)。"""
    y = np.asarray(y, dtype=float)
    peaks: List[int] = []
    valleys: List[int] = []
    if y.size < 3:
        return peaks, valleys

    for i in range(1, len(y) - 1):
        # 峰
        if ((y[i] >= y[i - 1]) and (y[i] > y[i + 1])) or ((y[i] > y[i - 1]) and (y[i] >= y[i + 1])):
            peaks.append(i)
        # 谷
        if ((y[i] <= y[i - 1]) and (y[i] < y[i + 1])) or ((y[i] < y[i - 1]) and (y[i] <= y[i + 1])):
            valleys.append(i)

    return peaks, valleys



def _prepare_xy_for_detection(xs: List[float], ys: List[float]) -> Tuple[np.ndarray, np.ndarray]:
    """排序 + 去重（同温度取平均），返回严格递增的 xp/yp。"""
    bucket: Dict[float, List[float]] = {}
    for x, y in zip(xs, ys):
        try:
            xf = float(x)
            yf = float(y)
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
    """估计温度步长（正相邻差的中位数）。"""
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
    center_x: float,
    radius: float,
    step: float,
    xp: np.ndarray,
    yp: np.ndarray,
    mode: str = "min",
) -> Tuple[float, float]:
    """在 center_x 附近做局部细搜索，返回 (温度, 对应高度)。"""
    xp = np.asarray(xp, dtype=float)
    yp = np.asarray(yp, dtype=float)
    if xp.size == 0:
        raise ValueError("xp 为空，无法精修极值。")

    left = max(float(xp[0]), float(center_x) - float(radius))
    right = min(float(xp[-1]), float(center_x) + float(radius))
    if right <= left:
        y0 = float(np.interp(float(center_x), xp, yp))
        return float(center_x), y0

    step = max(0.005, float(step))
    grid = np.arange(left, right + step * 0.5, step, dtype=float)
    vals = np.interp(grid, xp, yp)

    if mode.lower() == "max":
        idx = int(np.argmax(vals))
    else:
        idx = int(np.argmin(vals))
    return float(grid[idx]), float(vals[idx])



def _refine_triplet_onset(
    center_x: float,
    xp: np.ndarray,
    yp: np.ndarray,
    delta_thr: float,
    left_radius: float = 4.0,
    right_radius: float = 2.0,
    step: float = 0.01,
) -> Tuple[float, int]:
    """在单峰/台阶型样品上，用“三点差分”细化起涨点。

    规则：
    - 在 center_x 附近做细步长扫描（默认 0.01℃）
    - 若同时满足：
        y(x+1) - y(x) > delta_thr
        y(x)   - y(x-1) < delta_thr
      则认为 x 处于“左侧仍较平、右侧已明显抬升”的起涨带
    - 若存在多个候选，取最靠右的那个，避免结果回吸到更早的平直基线

    返回：
    - (refined_x, hit_count)
      hit_count 为命中候选数量，便于调试日志判断该规则是否真正生效。
    """
    xp = np.asarray(xp, dtype=float)
    yp = np.asarray(yp, dtype=float)
    if xp.size < 3:
        return float(center_x), 0

    left = max(float(xp[0]) + 1.01, float(center_x) - float(left_radius))
    right = min(float(xp[-1]) - 1.01, float(center_x) + float(right_radius))
    if right <= left + float(step):
        return float(center_x), 0

    grid = np.arange(left, right + float(step) * 0.5, float(step), dtype=float)
    y0 = np.interp(grid, xp, yp)
    ym1 = np.interp(grid - 1.0, xp, yp)
    yp1 = np.interp(grid + 1.0, xp, yp)

    mask = ((yp1 - y0) > float(delta_thr)) & ((y0 - ym1) < float(delta_thr))
    cand = grid[mask]
    if cand.size > 0:
        return float(cand[-1]), int(cand.size)
    return float(center_x), 0



def _refine_early_foot_onset(
    xp: np.ndarray,
    yp: np.ndarray,
    T1_seed: float,
    T2: float,
) -> Tuple[float, Dict[str, Any]]:
    """v233 early-foot correction: move T1 earlier only when the curve has a stable early lift."""

    xp = np.asarray(xp, dtype=float)
    yp = np.asarray(yp, dtype=float)
    if xp.size < 20 or not math.isfinite(T1_seed):
        return float(T1_seed), {"early_foot_used": False}

    left = max(float(xp[0]), float(T1_seed) - 45.0)
    right = min(float(T1_seed) + 1.0, float(T2) - 5.0)

    # Most curves can use the original seed-relative baseline. For a long,
    # soft early lift, however, that window can already contain tens of
    # microns of real expansion and inflate the noise estimate enough to
    # suppress the early-foot correction. Detect that shape first and fit
    # the baseline immediately before the initial sustained lift instead.
    probe_right = min(float(T1_seed) - 1.0, right)
    probe_grid = np.arange(left, probe_right + 0.005, 0.01, dtype=float)
    probe_y = np.interp(probe_grid, xp, yp)
    probe_gain3 = np.interp(probe_grid + 3.0, xp, yp) - probe_y
    probe_gain5 = np.interp(probe_grid + 5.0, xp, yp) - probe_y
    early_signal = probe_grid[(probe_gain3 >= 4.0) & (probe_gain5 >= 10.0)]

    baseline_mode = "seed_relative"
    residual_floor = 2.10
    if early_signal.size > 0 and float(T1_seed) - float(early_signal[0]) >= 15.0:
        baseline_mode = "pre_early_lift"
        base_right = max(left + 8.0, float(early_signal[0]) - 2.0)
        base_left = max(float(xp[0]), base_right - 25.0)
        # This branch sees a much flatter fitted baseline. A slightly higher
        # absolute residual floor avoids moving T1 to a weak shoulder.
        residual_floor = 3.0
    else:
        base_right = max(left + 8.0, float(T1_seed) - 12.0)
        base_left = max(float(xp[0]), base_right - 35.0)

    base_mask = (xp >= base_left) & (xp <= base_right)
    if int(np.sum(base_mask)) < 10:
        return float(T1_seed), {"early_foot_used": False}

    bx = xp[base_mask]
    by = yp[base_mask]
    coef = np.polyfit(bx, by, 1)
    base_res = by - np.polyval(coef, bx)
    noise = max(float(_robust_mad(base_res)), 0.05)

    grid = np.arange(left, right + 0.005, 0.01, dtype=float)
    yg = np.interp(grid, xp, yp)
    baseline = np.polyval(coef, grid)
    residual = yg - baseline
    residual_thr = max(residual_floor, 5.0 * noise)
    gain3 = np.interp(grid + 3.0, xp, yp) - yg
    gain5 = np.interp(grid + 5.0, xp, yp) - yg

    mask = (
        (residual >= residual_thr)
        & (gain3 >= max(6.0, 15.0 * noise))
        & (gain5 >= max(12.0, 25.0 * noise))
    )
    common_meta = {
        "early_foot_noise": float(noise),
        "early_foot_thr": float(residual_thr),
        "early_foot_base_left": float(base_left),
        "early_foot_base_right": float(base_right),
        "early_foot_baseline_mode": baseline_mode,
        "early_foot_signal_temp": float(early_signal[0]) if early_signal.size > 0 else None,
    }
    cand = grid[mask]
    if cand.size == 0:
        return float(T1_seed), {"early_foot_used": False, **common_meta}

    T1_new = float(cand[0])
    if T1_new < T1_seed - 1.0:
        return T1_new, {
            "early_foot_used": True,
            "early_foot_from": float(T1_seed),
            "early_foot_to": float(T1_new),
            **common_meta,
        }
    return float(T1_seed), {"early_foot_used": False, **common_meta}


def detect_T2_T1_robust(
    xs: List[float],
    ys: List[float],
    logger,
    debug: bool = False,
) -> Tuple[float, float, Dict[str, Any]]:
    """稳健版 T1/T2 识别：兼容单峰与多峰。

    规则：
    1) 先轻度平滑，T2 取主峰（平滑后最大值）。
    2) 若主峰左侧存在“显著前峰”，则 T1 取“该前峰与主峰之间的谷底”。
       - 这是修复多峰失效的关键：T1 应该是主峰前最后一个显著谷底，而不是左峰之前的点。
    3) 若没有显著前峰，则回退到“持续上升起点”的导数法。
    4) H1/H2/H 最终都用原始曲线插值得到，避免平滑后幅值被压低。
    """
    meta: Dict[str, Any] = {"type": "mono", "confidence": 0.0}

    if len(xs) < 5 or len(ys) < 5:
        raise ValueError("数据点过少，无法稳健识别 T1/T2。")

    xp, yp = _prepare_xy_for_detection(xs, ys)
    if xp.size < 5:
        raise ValueError("有效数据点过少，无法稳健识别 T1/T2。")

    step = _estimate_step(xp)
    grid = np.arange(float(xp[0]), float(xp[-1]) + step * 0.5, step, dtype=float)
    y_grid = np.interp(grid, xp, yp)

    # 平滑宽度按“温度”定义，而不是按点数硬编码，适应不同采样步长
    sigma_temp = max(0.8, min(2.5, 8.0 * step))
    sigma_pts = max(1.0, sigma_temp / step)
    y_s = _gaussian_smooth_1d(y_grid, sigma_pts)

    idx2 = int(np.argmax(y_s))
    T2_coarse = float(grid[idx2])

    peaks, valleys = _find_local_extrema(y_s)

    amp = float(np.max(y_s) - np.min(y_s))

    # 基线噪声：优先取主峰前的一段“较平坦”区域做估计
    base_mask = (grid >= START_TEMP_FOR_T1) & (grid <= min(T2_coarse - 15.0, START_TEMP_FOR_T1 + 30.0))
    if int(np.sum(base_mask)) < 8:
        base_mask = (grid >= grid[0]) & (grid <= min(T2_coarse - 10.0, grid[0] + 30.0))
    noise_y = _robust_mad(y_s[base_mask]) if int(np.sum(base_mask)) > 0 else _robust_mad(np.diff(y_s))

    # 自适应阈值：不要再用固定 100 μm
    valley_drop_min = max(5.0, 5.0 * noise_y, 0.02 * amp)   # 左峰 -> 谷底 至少要有这么深
    valley_rise_min = max(20.0, 8.0 * noise_y, 0.06 * amp)  # 谷底 -> 主峰 至少要有这么高
    peak_sep_min = max(4.0, 5.0 * step)                     # 左峰与主峰至少分开这么多温度

    left_peak_idx: Optional[int] = None
    valley_idx: Optional[int] = None

    # 从右往左找“主峰左侧最近的显著峰”
    left_peaks = [p for p in peaks if (grid[p] >= START_TEMP_FOR_T1 and p < idx2 - 2)]
    for p in reversed(left_peaks):
        cands = [v for v in valleys if p < v < idx2 - 1]
        if not cands:
            continue

        # 取该峰和主峰之间最深的谷
        v = min(cands, key=lambda i: y_s[i])
        drop = float(y_s[p] - y_s[v])
        rise = float(y_s[idx2] - y_s[v])
        sep = float(grid[idx2] - grid[p])

        if drop >= valley_drop_min and rise >= valley_rise_min and sep >= peak_sep_min:
            left_peak_idx = p
            valley_idx = v
            break

    if valley_idx is not None:
        # -------- 多峰：T1 直接取主峰前谷底 --------
        T1_coarse = float(grid[valley_idx])
        mode = "multi_peak_valley"
        meta["type"] = "multi"
        meta["confidence"] = 0.92
        meta["left_peak_temp"] = float(grid[left_peak_idx]) if left_peak_idx is not None else None
        meta["valley_depth_um"] = float(y_s[left_peak_idx] - y_s[valley_idx]) if left_peak_idx is not None else 0.0
        meta["T1_search_end_temp"] = float(grid[valley_idx])
    else:
        # -------- 单峰 / 无显著前峰：优先取“持续上升起点”，避免回吸到更早基线最低点 --------
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
        consec = max(3, int(round(2.0 / step)))  # 至少连续 ~2℃ 维持上升

        left_start = int(np.searchsorted(grid, START_TEMP_FOR_T1))
        hit_i: Optional[int] = None
        for i in range(left_start, idx2 - consec):
            if np.all(dy[i:i + consec] > dy_thr):
                # 再加一层“未来 5℃ 有明显增量”，防止慢漂移误触发
                j = min(idx2, i + max(consec, int(round(5.0 / step))))
                if (y_s[j] - y_s[i]) >= max(8.0, 6.0 * noise_y, 0.03 * amp):
                    hit_i = i
                    break

        if hit_i is None:
            # 极少数情况下仍找不到明确起涨点：退化为区间最小值
            cand = np.where((grid >= START_TEMP_FOR_T1) & (grid <= T2_coarse))[0]
            if cand.size == 0:
                cand = np.arange(0, idx2 + 1)
            valley_idx = int(cand[np.argmin(y_s[cand])])
            T1_coarse = float(grid[valley_idx])
            mode = "single_peak_fallback_min"
            meta["confidence"] = 0.45
        else:
            # 先得到“持续上升起点”的种子，再用原始曲线做三点差分细化。
            # 这里不再盲目回看 8℃ 取谷底，否则像 20260128-1 这类单峰台阶样品，
            # 会被吸回到更早的平直基线最低点（例如 82℃），而不是更合理的 ~90℃ 起涨点。
            onset_seed = float(grid[hit_i])
            onset_delta_thr = max(1.0, 0.0009 * amp)  # 强起涨阈值：用于大幅跃迁/主阶跃
            onset_triplet, onset_triplet_hits = _refine_triplet_onset(
                onset_seed,
                xp,
                yp,
                delta_thr=onset_delta_thr,
                left_radius=4.0,
                right_radius=2.0,
                step=0.01,
            )

            # 若起涨点前方存在“很近、且确实有深度”的局部谷底，则仍允许取近谷；
            # 但若谷底距离过远/太浅，则直接使用起涨点，避免回吸到更早基线。
            near_back = max(3, int(round(3.0 / step)))
            lo = max(left_start, hit_i - near_back)
            local_valley_i = int(lo + np.argmin(y_s[lo:hit_i + 1]))
            local_valley_gap = float(onset_triplet - grid[local_valley_i])
            local_valley_jump = float(np.interp(onset_triplet, grid, y_s) - y_s[local_valley_i])

            use_local_valley = (
                local_valley_gap <= 2.5 and
                local_valley_jump >= max(3.0, 4.0 * noise_y, 0.003 * amp)
            )

            # v215：补充“软肩部起涨”修正。
            # 适配 20250611/20260611-1 这类：主阶跃前存在较长的、贴近基线的小幅抬升。
            # 旧版会把 T1 锁在强阶跃开始处（约 161.5℃），而更合理的 T1 应落在前方软起涨点（约 155.77℃）。
            soft_delta_thr = max(0.45, 1.5 * noise_y, 0.00015 * amp)
            soft_onset, soft_onset_hits = _refine_triplet_onset(
                onset_seed,
                xp,
                yp,
                delta_thr=soft_delta_thr,
                left_radius=6.0,
                right_radius=0.8,
                step=0.01,
            )
            soft_gap = float(onset_seed - soft_onset)
            soft_gain = float(np.interp(onset_seed, xp, yp) - np.interp(soft_onset, xp, yp))
            soft_pre_lo = max(float(xp[0]), float(onset_seed) - 12.0)
            soft_pre_mask = (xp >= soft_pre_lo) & (xp <= onset_seed)
            soft_base_min = float(np.min(yp[soft_pre_mask])) if int(np.sum(soft_pre_mask)) > 0 else float(np.min(yp))
            soft_level = float(np.interp(soft_onset, xp, yp) - soft_base_min)
            use_soft_onset = (
                int(soft_onset_hits) > 0 and
                soft_gap >= 4.0 and
                soft_gain >= max(20.0, 20.0 * noise_y, 0.012 * amp) and
                soft_level <= max(2.0, 8.0 * noise_y, 0.01 * amp)
            )

            if use_local_valley:
                valley_idx = local_valley_i
                T1_coarse = float(grid[local_valley_i])
                mode = "single_peak_local_valley"
                meta["confidence"] = 0.79
            elif use_soft_onset:
                T1_coarse = float(soft_onset)
                mode = "single_peak_soft_triplet"
                meta["confidence"] = 0.91
                onset_delta_thr = float(soft_delta_thr)
                onset_triplet = float(soft_onset)
                onset_triplet_hits = int(soft_onset_hits)
            else:
                T1_coarse = float(onset_triplet)
                mode = "single_peak_step_onset"
                meta["confidence"] = 0.89

            meta["onset_seed_temp"] = float(onset_seed)
            meta["onset_triplet_temp"] = float(onset_triplet)
            meta["onset_triplet_hits"] = int(onset_triplet_hits)
            meta["onset_delta_thr"] = float(onset_delta_thr)
            meta["local_valley_gap_temp"] = float(local_valley_gap)
            meta["local_valley_jump_um"] = float(local_valley_jump)
            meta["soft_triplet_temp"] = float(soft_onset)
            meta["soft_triplet_hits"] = int(soft_onset_hits)
            meta["soft_delta_thr"] = float(soft_delta_thr)
            meta["soft_gap_temp"] = float(soft_gap)
            meta["soft_gain_um"] = float(soft_gain)
            meta["soft_level_um"] = float(soft_level)

        meta["dy_thr"] = float(dy_thr)
        meta["dy_med"] = float(dy_med)
        meta["dy_mad"] = float(dy_mad)
        meta["T1_search_end_temp"] = float(T1_coarse)

    # ----- 局部精修 -----
    fine_step = max(0.01, step / 5.0)

    if mode == "multi_peak_valley":
        # 多峰时，T1 就是谷底，所以局部找最小值最合理
        T1, H1 = _fine_search_extreme(T1_coarse, radius=1.5, step=fine_step, xp=xp, yp=yp, mode="min")
    elif mode in ("single_peak_local_valley", "single_peak_fallback_min"):
        # 单峰但起涨点前有近谷 / 或退化场景：仍按局部谷底精修
        T1, H1 = _fine_search_extreme(T1_coarse, radius=0.6, step=fine_step, xp=xp, yp=yp, mode="min")
    else:
        # 单峰台阶型样品：T1 代表“起涨点”而不是谷底，不能再做局部最小值精修
        T1 = float(T1_coarse)
        H1 = float(np.interp(T1, xp, yp))

    T2, H2 = _fine_search_extreme(T2_coarse, radius=1.5, step=fine_step, xp=xp, yp=yp, mode="max")

    meta["mode"] = mode
    meta["T1_temp"] = float(T1)
    meta["T2_temp"] = float(T2)
    meta["H1_um"] = float(H1)
    meta["H2_um"] = float(H2)
    meta["H_um"] = float(H2 - H1)
    meta["T2_height_um"] = float(H2)
    meta["noise_y_um"] = float(noise_y)
    meta["valley_drop_min_um"] = float(valley_drop_min)
    meta["valley_rise_min_um"] = float(valley_rise_min)
    meta["smooth_sigma_temp"] = float(sigma_temp)

    if debug:
        try:
            logger.debug(
                f"[robust] mode={mode}, T1={T1:.4f}℃, T2={T2:.4f}℃, "
                f"H1={H1:.4f}μm, H2={H2:.4f}μm, H={H2-H1:.4f}μm, "
                f"noise={noise_y:.4f}, drop_min={valley_drop_min:.4f}, rise_min={valley_rise_min:.4f}"
            )
            if left_peak_idx is not None and valley_idx is not None:
                logger.debug(
                    f"[robust] left_peak={grid[left_peak_idx]:.4f}℃, valley={grid[valley_idx]:.4f}℃, "
                    f"valley_depth={y_s[left_peak_idx]-y_s[valley_idx]:.4f}μm"
                )
        except Exception:
            pass

    return float(T1), float(T2), meta



def detect_T2_T1(xs: List[float], ys: List[float], logger) -> Tuple[float, float]:
    """默认入口：直接走稳健版。"""
    T1, T2, _meta = detect_T2_T1_robust(xs, ys, logger, debug=False)
    return float(T1), float(T2)



def detect_T2_T1_precise(xs: List[float], ys: List[float], logger, debug: bool = False) -> Tuple[float, float, Dict[str, Any]]:
    """保留原接口，但内部改成稳健版。

    说明：
    - 原先的多峰逻辑会把搜索上限设到 left_peak，导致谷底型 T1 永远选不到。
    - 这里直接返回稳健版结果即可。
    """
    return detect_T2_T1_robust(xs, ys, logger, debug=debug)



def detect_T2_T1_super_gradient(xs: List[float], ys: List[float], logger, debug: bool = False) -> Tuple[float, float, Dict[str, Any]]:
    """V233 超级梯度接口：精修主起点，并校正可信的早期足点。

    v214 规则：
    - 多峰/近谷场景：T1 仍按“谷底”精修
    - 单峰台阶样品：T1 代表“起涨点”，继续沿用三点差分细化，不再强行找局部最小值
    """
    T1, T2, meta = detect_T2_T1_robust(xs, ys, logger, debug=debug)

    xp, yp = _prepare_xy_for_detection(xs, ys)
    if xp.size < 5:
        return float(T1), float(T2), meta

    # T2 始终取局部最大
    T2f, H2f = _fine_search_extreme(T2, radius=1.0, step=0.01, xp=xp, yp=yp, mode="max")

    mode = str(meta.get("mode") or "")
    if mode in ("multi_peak_valley", "single_peak_local_valley", "single_peak_fallback_min"):
        t1_radius = 1.0 if mode == "multi_peak_valley" else 0.4
        T1f, H1f = _fine_search_extreme(T1, radius=t1_radius, step=0.01, xp=xp, yp=yp, mode="min")
        meta["super_window_T1"] = float(t1_radius)
    else:
        amp = float(np.max(yp) - np.min(yp)) if yp.size > 0 else 0.0
        onset_delta_thr = float(meta.get("onset_delta_thr", max(1.0, 0.0009 * amp)))
        T1f, super_hits = _refine_triplet_onset(
            T1,
            xp,
            yp,
            delta_thr=onset_delta_thr,
            left_radius=1.2,
            right_radius=0.6,
            step=0.01,
        )
        H1f = float(np.interp(T1f, xp, yp))
        meta["super_triplet_hits"] = int(super_hits)
        meta["super_window_T1"] = 1.2

    early_t1, early_meta = _refine_early_foot_onset(xp, yp, T1f, T2f)
    meta.update(early_meta)
    if early_meta.get("early_foot_used"):
        T1f = float(early_t1)
        H1f = float(np.interp(T1f, xp, yp))
        meta["mode"] = f"{mode}+early_foot"

    meta["algo_version"] = "v233"
    meta["T1_temp"] = float(T1f)
    meta["T2_temp"] = float(T2f)
    meta["T1_super"] = float(T1f)
    meta["T2_super"] = float(T2f)
    meta["H1_um"] = float(H1f)
    meta["H2_um"] = float(H2f)
    meta["H_um"] = float(H2f - H1f)
    meta["super_step"] = 0.01
    meta["super_window_T2"] = 1.0

    if debug:
        try:
            logger.debug(
                f"[super] T1: {T1:.4f} -> {T1f:.4f}, T2: {T2:.4f} -> {T2f:.4f}, "
                f"H={H2f - H1f:.4f}μm"
            )
        except Exception:
            pass

    return float(T1f), float(T2f), meta


def piecewise_map(x: float, xmin: float, xmax: float, T1o: float, T2o: float, T1n: float, T2n: float) -> float:
    """分段线性映射：原温度 x_old -> 新温度 x_new。

    目标锚点（理想情况）：
        [xmin, T1o] -> [xmin, T1n]
        [T1o, T2o] -> [T1n, T2n]
        [T2o, xmax] -> [T2n, xmax]

    ⚠️ 真实数据里，可能出现 T1o≈xmin 或 T2o≈xmax（锚点落在边界）。
    这会导致区间长度趋近 0，引发数值不稳定/曲线异常（比如尾部被夹成一段“平台”）。
    因此这里做“安全降级”：
    - 始终保证 xmin->xmin, xmax->xmax（不再用“整体平移”破坏边界）
    - 对退化区间（分母≈0），使用更稳妥的回退（尽量保持原 x）
    """
    try:
        x = float(x)
        xmin = float(xmin)
        xmax = float(xmax)
        T1o = float(T1o)
        T2o = float(T2o)
        T1n = float(T1n)
        T2n = float(T2n)
    except Exception:
        return x

    # 先把 x 限定在有效范围内
    if x <= xmin:
        return xmin
    if x >= xmax:
        return xmax

    # 端点优先（避免浮点抖动导致 x==xmax 却被映射到 T2n）
    if abs(x - xmin) < 1e-12:
        return xmin
    if abs(x - xmax) < 1e-12:
        return xmax

    # 1) 左段
    if x <= T1o:
        denom = (T1o - xmin)
        if abs(denom) < 1e-12:
            # 退化：无法稳定拉伸，尽量保持原值（不整体平移）
            return x
        return xmin + (x - xmin) * (T1n - xmin) / denom

    # 2) 中段
    if x <= T2o:
        denom = (T2o - T1o)
        if abs(denom) < 1e-12:
            return T1n
        return T1n + (x - T1o) * (T2n - T1n) / denom

    # 3) 右段
    denom = (xmax - T2o)
    if abs(denom) < 1e-12:
        # 退化：无法稳定拉伸，尽量保持原值
        return x
    return T2n + (x - T2o) * (xmax - T2n) / denom


def _estimate_temp_step(xs: List[float]) -> float:
    """估计温度步长（用于判断锚点是否“贴边”导致区间退化）。

    使用排序后“正的相邻差值”的中位数；若无法估计，则返回一个极小正数。
    """
    try:
        xs_u = sorted({round(float(x), 8) for x in xs if math.isfinite(x)})
        if len(xs_u) < 2:
            return 1e-6
        diffs = [xs_u[i + 1] - xs_u[i] for i in range(len(xs_u) - 1) if (xs_u[i + 1] - xs_u[i]) > 0]
        if not diffs:
            return max(1e-6, (xs_u[-1] - xs_u[0]) / max(1, len(xs_u) - 1))
        d = float(np.median(np.asarray(diffs, dtype=float)))
        if not math.isfinite(d) or d <= 0:
            d = float(diffs[0])
        return max(1e-6, d)
    except Exception:
        return 1e-6


def sanitize_warp_anchors(
    xs: List[float],
    T1o: float,
    T2o: float,
    xmin: float,
    xmax: float,
    logger: Optional[logging.Logger] = None,
) -> Tuple[float, float, Dict[str, Any]]:
    """修复/规避“锚点贴边”导致的曲线异常。

    典型异常场景：
    - T2o 恰好等于 xmax（最大值落在最后一个温度点），用户又把 T2n 往左移；
      旧实现会让 x' 的最大值变成 T2n，随后插值时尾部被 clamp 成一段“平台”，看起来像异常。

    处理策略：
    - 计算一个“温度步长” step（中位数）
    - 若 T1o 距 xmin 太近：把 T1o 向右挪到第二个唯一温度点（或最近可用点）
    - 若 T2o 距 xmax 太近：把 T2o 向左挪到倒数第二个唯一温度点（或最近可用点）
    - 挪动后必须保持 T1o < T2o，否则回退到原值

    返回：(T1o_used, T2o_used, meta)
    """
    meta: Dict[str, Any] = {"adjusted": False, "reasons": []}

    try:
        xs_u = sorted({round(float(x), 8) for x in xs if math.isfinite(x)})
    except Exception:
        xs_u = []

    step = _estimate_temp_step(xs_u if xs_u else xs)
    eps = max(1e-6, step * 0.51)

    t1 = float(T1o)
    t2 = float(T2o)

    # 贴近 xmin：向右挪
    if xs_u and (t1 - xmin) < eps and len(xs_u) >= 2:
        cand = None
        for v in xs_u:
            if v > xmin + eps * 0.1:
                cand = float(v)
                break
        if cand is not None and cand < t2 - eps:
            if abs(cand - t1) > 1e-12:
                meta["adjusted"] = True
                meta["reasons"].append(f"T1o贴边({t1:.6g}≈xmin) -> {cand:.6g}")
                t1 = cand

    # 贴近 xmax：向左挪
    if xs_u and (xmax - t2) < eps and len(xs_u) >= 2:
        cand = None
        for v in reversed(xs_u):
            if v < xmax - eps * 0.1:
                cand = float(v)
                break
        if cand is not None and cand > t1 + eps:
            if abs(cand - t2) > 1e-12:
                meta["adjusted"] = True
                meta["reasons"].append(f"T2o贴边({t2:.6g}≈xmax) -> {cand:.6g}")
                t2 = cand

    # 最终校验
    if not (xmin <= t1 <= xmax and xmin <= t2 <= xmax) or (t1 >= t2):
        meta["reasons"].append("调整后不合法，已回退到原始锚点")
        t1, t2 = float(T1o), float(T2o)
        meta["adjusted"] = False

    if meta["adjusted"] and logger is not None:
        try:
            logger.debug(f"锚点修正: {'; '.join(meta['reasons'])} (eps≈{eps:.6g})")
        except Exception:
            pass

    meta["eps"] = float(eps)
    meta["step"] = float(step)
    meta["T1o_used"] = float(t1)
    meta["T2o_used"] = float(t2)
    return float(t1), float(t2), meta


def piecewise_inverse_map(x_new: float, xmin: float, xmax: float, T1o: float, T2o: float, T1n: float, T2n: float) -> float:
    """分段线性映射的“逆映射”：给定 x_new（目标温度），求对应的原温度 x_old。

    对应 forward 映射锚点：
        xmin->xmin, T1o->T1n, T2o->T2n, xmax->xmax

    说明：
    - 当某段区间退化（例如 T2n==xmax 或 T2o==xmax）时，逆映射可能不是一一对应；
      本函数会优先保证端点一致性：x_new≈xmin -> xmin, x_new≈xmax -> xmax。
    """
    try:
        x_new = float(x_new)
        xmin = float(xmin)
        xmax = float(xmax)
        T1o = float(T1o)
        T2o = float(T2o)
        T1n = float(T1n)
        T2n = float(T2n)
    except Exception:
        return x_new

    # 范围外直接夹到边界
    if x_new <= xmin:
        return xmin
    if x_new >= xmax:
        return xmax

    # 端点优先
    if abs(x_new - xmin) < 1e-12:
        return xmin
    if abs(x_new - xmax) < 1e-12:
        return xmax

    # 左段
    if x_new <= T1n:
        denom = (T1n - xmin)
        if abs(denom) < 1e-12:
            return xmin
        x_old = xmin + (x_new - xmin) * (T1o - xmin) / denom
        return max(xmin, min(xmax, x_old))

    # 中段
    if x_new <= T2n:
        denom = (T2n - T1n)
        if abs(denom) < 1e-12:
            return T1o
        x_old = T1o + (x_new - T1n) * (T2o - T1o) / denom
        return max(xmin, min(xmax, x_old))

    # 右段
    denom = (xmax - T2n)
    if abs(denom) < 1e-12:
        return xmax
    x_old = T2o + (x_new - T2n) * (xmax - T2o) / denom
    return max(xmin, min(xmax, x_old))

def piecewise_inverse_map_array(x_new_arr, xmin: float, xmax: float, T1o: float, T2o: float, T1n: float, T2n: float) -> np.ndarray:
    """piecewise_inverse_map() 的向量化版本（用于批量温度映射提速）。"""
    x_new = np.asarray(x_new_arr, dtype=float)
    if x_new.size == 0:
        return x_new.copy()

    xmin = float(xmin)
    xmax = float(xmax)
    T1o = float(T1o)
    T2o = float(T2o)
    T1n = float(T1n)
    T2n = float(T2n)

    x_clip = np.clip(x_new, xmin, xmax)
    out = x_clip.copy()

    near_left = np.isclose(x_clip, xmin, atol=1e-12)
    near_right = np.isclose(x_clip, xmax, atol=1e-12)
    out[near_left] = xmin
    out[near_right] = xmax

    normal_mask = (~near_left) & (~near_right)

    # 左段
    mask_left = normal_mask & (x_clip <= T1n)
    denom_left = (T1n - xmin)
    if abs(denom_left) >= 1e-12 and np.any(mask_left):
        out[mask_left] = xmin + (x_clip[mask_left] - xmin) * (T1o - xmin) / denom_left
    elif np.any(mask_left):
        out[mask_left] = xmin

    # 中段
    mask_mid = normal_mask & (x_clip > T1n) & (x_clip <= T2n)
    denom_mid = (T2n - T1n)
    if abs(denom_mid) >= 1e-12 and np.any(mask_mid):
        out[mask_mid] = T1o + (x_clip[mask_mid] - T1n) * (T2o - T1o) / denom_mid
    elif np.any(mask_mid):
        out[mask_mid] = T1o

    # 右段
    mask_right = normal_mask & (x_clip > T2n)
    denom_right = (xmax - T2n)
    if abs(denom_right) >= 1e-12 and np.any(mask_right):
        out[mask_right] = T2o + (x_clip[mask_right] - T2n) * (xmax - T2o) / denom_right
    elif np.any(mask_right):
        out[mask_right] = xmax

    return np.clip(out, xmin, xmax)


def linear_interp(x: float, xp: List[float], fp: List[float]) -> float:
    # xp 递增；越界夹到边界
    """一维线性插值（带边界夹取）。
    
    参数：
        x: 需要插值的自变量。
        xp: 自变量序列（必须单调递增）。
        fp: 因变量序列（与 xp 等长）。
    
    返回：
        float：插值结果；当 x 越界时返回端点值（clamp）。
    
    注意：
        - 本实现使用二分查找定位区间，避免 O(n) 扫描。
        - 若 xp 出现重复值会导致除零风险，因此调用前建议先 aggregate_duplicates()。
    """
    
    if x <= xp[0]:return fp[0]
    if x >= xp[-1]:return fp[-1]

    lo, hi = 0, len(xp) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if xp[mid] <= x:lo = mid
        else:hi = mid

    x0, x1 = xp[lo], xp[lo + 1]
    y0, y1 = fp[lo], fp[lo + 1]
    if abs(x1 - x0) < 1e-12:
        return y0
    t = (x - x0) / (x1 - x0)
    return y0 + t * (y1 - y0)

def aggregate_duplicates(xp: List[float], fp: List[float], ndigits: int = 8) -> Tuple[List[float], List[float]]:
    # 合并近似相同x（避免插值xp非严格递增）
    """合并近似重复的 x 值，保证 xp 严格递增。
    
    用途：
        TMA 数据中偶尔会出现温度重复/抖动（例如同一温度多条记录），
        这会让插值算法出现“分母为 0”或区间定位异常。
    
    参数：
        xp: x 列表。
        fp: y 列表。
        ndigits: 把 x 四舍五入到多少位后视为同一个桶。
    
    返回：
        (xs, ys)：去重后的 x（排序后）与 y（同桶平均）。
    """
    
    bucket = {}
    for x, y in zip(xp, fp):
        k = round(x, ndigits)
        bucket.setdefault(k, []).append(y)
    xs = sorted(bucket.keys())
    ys = [sum(bucket[k]) / len(bucket[k]) for k in xs]
    return xs, ys


def build_curve_cache(xs: List[float], ys: List[float]) -> Dict[str, Any]:
    """构建可复用的曲线缓存（排序/去重/插值/积分）。"""
    pairs: List[Tuple[float, float]] = []
    for x, y in zip(xs or [], ys or []):
        try:
            xf = float(x)
            yf = float(y)
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
    """基于曲线缓存，对任意温度 x 做一次线性插值。"""
    xp = np.asarray(curve_cache.get("xp", []), dtype=float)
    yp = np.asarray(curve_cache.get("yp", []), dtype=float)
    if xp.size == 0 or yp.size == 0:
        raise ValueError("曲线缓存为空，无法插值。")
    return float(np.interp(float(x), xp, yp))


def integrate_curve_interval_from_cache(curve_cache: Dict[str, Any], x1: float, x2: float) -> float:
    """对 T1~T2 区间曲线做梯形积分（只针对数值曲线，不包含文字/单位标注）。"""
    xp = np.asarray(curve_cache.get("xp", []), dtype=float)
    yp = np.asarray(curve_cache.get("yp", []), dtype=float)
    if xp.size == 0 or yp.size == 0:
        raise ValueError("曲线缓存为空，无法积分。")

    left = float(min(x1, x2))
    right = float(max(x1, x2))
    left = max(float(xp[0]), left)
    right = min(float(xp[-1]), right)
    if not (math.isfinite(left) and math.isfinite(right)):
        raise ValueError("积分区间无效。")
    if right <= left + 1e-12:
        return 0.0

    mask = (xp > left) & (xp < right)
    x_seg = np.concatenate(([left], xp[mask], [right]))
    y_seg = np.concatenate(([
        float(np.interp(left, xp, yp))
    ], yp[mask], [
        float(np.interp(right, xp, yp))
    ]))

    x_unique, idx = np.unique(x_seg, return_index=True)
    y_unique = y_seg[idx]
    if hasattr(np, "trapezoid"):
        area = np.trapezoid(y_unique, x_unique)
    else:
        area = np.trapz(y_unique, x_unique)
    return float(area)


def integrate_curve_interval(xs: List[float], ys: List[float], x1: float, x2: float) -> float:
    """对原始曲线数据在 [x1, x2] 内做梯形积分。"""
    return integrate_curve_interval_from_cache(build_curve_cache(xs, ys), x1, x2)


class _NullLogger:
    def debug(self, *args, **kwargs):
        pass
    info = warning = error = exception = debug


def _ensure_logger(logger=None):
    return logger if logger is not None else _NullLogger()


def _resolve_xy_source(source, ys=None, logger=None) -> Tuple[List[float], List[float]]:
    """统一解析外部接口的输入源。

    支持两种调用方式：
    1) get_...(xs, ys)
    2) get_...(file_path)
    """
    logger = _ensure_logger(logger)

    if ys is not None:
        xs_out = list(source or [])
        ys_out = list(ys or [])
    elif isinstance(source, str):
        file_path = normalize_path_separators(str(source).strip())
        text, _meta = load_text_prefer_tajm(file_path, logger)
        parsed = parse_lines(text)
        xs_out, ys_out, _ = extract_xy_from_file(parsed, logger)
    elif isinstance(source, (tuple, list)) and len(source) == 2:
        xs_out = list(source[0] or [])
        ys_out = list(source[1] or [])
    else:
        raise TypeError("source 必须是文件路径，或 xs + ys 两个序列。")

    if len(xs_out) != len(ys_out):
        raise ValueError("xs 与 ys 长度不一致。")
    if len(xs_out) < 5:
        raise ValueError("有效数据点过少，无法识别 T1/T2。")
    return xs_out, ys_out


def _compute_t1_t2_h_integral_details(xs: List[float], ys: List[float], logger=None, use_super: bool = True):
    """统一计算 T1/T2/H/H1/H2/积分，供外部接口与 GUI 复用。"""
    logger = _ensure_logger(logger)
    curve_cache = build_curve_cache(xs, ys)

    if use_super:
        T1, T2, meta = detect_T2_T1_super_gradient(xs, ys, logger, debug=False)
    else:
        T1, T2, meta = detect_T2_T1_precise(xs, ys, logger, debug=False)

    if not (math.isfinite(T1) and math.isfinite(T2)):
        raise ValueError("T1 或 T2 无法识别。")

    H1 = interpolate_curve_height(T1, curve_cache)
    H2 = interpolate_curve_height(T2, curve_cache)
    H = H2 - H1
    area = integrate_curve_interval_from_cache(curve_cache, T1, T2)
    return float(T1), float(T2), float(H), float(area), float(H1), float(H2), meta


def get_t1_t2_h_integral(source, ys=None, logger=None, use_super: bool = True):
    """外部接口1：返回 (T1, T2, 高度差, T1到T2的积分)。

    异常约定：
    - 当输入数据无效或 T1/T2 无法识别时，抛出 ValueError/TypeError。
    """
    xs, ys_out = _resolve_xy_source(source, ys=ys, logger=logger)
    T1, T2, H, area, _H1, _H2, _meta = _compute_t1_t2_h_integral_details(xs, ys_out, logger=logger, use_super=use_super)
    return (T1, T2, H, area)


def get_t1_t2_h_integral_h1_h2(source, ys=None, logger=None, use_super: bool = True):
    """外部接口2：返回 (T1, T2, 高度差, T1到T2的积分, H1, H2)。

    异常约定：
    - 当输入数据无效或 T1/T2 无法识别时，抛出 ValueError/TypeError。
    """
    xs, ys_out = _resolve_xy_source(source, ys=ys, logger=logger)
    T1, T2, H, area, H1, H2, _meta = _compute_t1_t2_h_integral_details(xs, ys_out, logger=logger, use_super=use_super)
    return (T1, T2, H, area, H1, H2)


def isotonic_regression(y, eps: float = 1e-12):
    """PAV isotonic regression (non-decreasing). Returns a new list."""
    n = len(y)
    if n <= 1:
        return list(y)

    # blocks: [start, end, weight, avg]
    blocks = []
    for i, yi in enumerate(y):
        blocks.append([i, i, 1.0, float(yi)])
        while len(blocks) >= 2 and blocks[-2][3] > blocks[-1][3] + eps:
            b2 = blocks.pop()
            b1 = blocks.pop()
            w = b1[2] + b2[2]
            avg = (b1[3] * b1[2] + b2[3] * b2[2]) / w
            blocks.append([b1[0], b2[1], w, avg])

    out = [0.0] * n
    for s, e, w, avg in blocks:
        for k in range(s, e + 1):
            out[k] = avg
    return out

def bridge_dropouts(x_seg, y_seg, tol):
    """    在已按温度升序排列的序列上修复“掉点”：
    - 找到低于历史最高值的连续区段
    - 用区段左右两端的正常点做线性插值抬高填补

    只抬高，不降低；最后再做一次非递减保证。
    """
    n = len(y_seg)
    if n == 0:
        return []

    y = list(y_seg)
    running_max = y[0]
    bad_start = None

    for j in range(1, n):
        if y[j] < running_max - tol:
            if bad_start is None:
                bad_start = j
        else:
            if bad_start is not None:
                L = bad_start - 1
                R = j
                xL, yL = x_seg[L], y[L]
                xR, yR = x_seg[R], y[R]
                if yR < yL:
                    yR = yL
                denom = (xR - xL)
                for k in range(bad_start, R):
                    if abs(denom) < 1e-12:
                        y_target = yL
                    else:
                        t = (x_seg[k] - xL) / denom
                        y_target = yL + t * (yR - yL)
                    if y[k] < y_target:
                        y[k] = y_target
                bad_start = None
            running_max = max(running_max, y[j])

    # 掉点到末尾：没有右锚点，只能抬到 running_max
    if bad_start is not None:
        for k in range(bad_start, n):
            if y[k] < running_max:
                y[k] = running_max

    # 最终保证非递减
    m = -float('inf')
    for j in range(n):
        if y[j] > m:m = y[j]
        else:y[j] = m
    return y


def enforce_monotonic_between(xs: List[float], ys: List[float], x1: float, x2: float, logger: logging.Logger):
    """
    修复“裂开点”：在温度区间 [x1, x2] 内强制高度 ys 随温度 xs 单调不下降。
    - xs/ys 为同长度列表（按文件行顺序）。
    - 只对区间内的点做修正；区间外保持不变。
    """
    if x1 >= x2:return ys

    idxs = [i for i, x in enumerate(xs) if x1 <= x <= x2]
    if len(idxs) < 2:return ys

    # 按温度升序做单调修正（避免温度不严格递增导致误判）
    idxs_sorted = sorted(idxs, key=lambda i: xs[i])
    seg = [ys[i] for i in idxs_sorted]

    tol = max(1e-9, (max(seg) - min(seg)) * 1e-6)
    method = (MONOTONIC_METHOD or "isotonic").lower()
    if method == "cummax":
        fixed = []
        m = -float('inf')
        for v in seg:
            if v > m:m = v
            fixed.append(m)
    elif method in ("bridge", "interp", "linear"):  # 线性桥接掉点
        xseg = [xs[i] for i in idxs_sorted]
        fixed = bridge_dropouts(xseg, seg, tol)
    else:
        fixed = isotonic_regression(seg)

    ys2 = list(ys)
    changed = 0
    max_abs_delta = 0.0
    for i, v in zip(idxs_sorted, fixed):
        d = v - ys2[i]
        if abs(d) > 1e-10:
            changed += 1
            if abs(d) > max_abs_delta:
                max_abs_delta = abs(d)
        ys2[i] = v

    if changed:logger.debug(f"单调修复已应用：区间[{x1}, {x2}] 内修改点数={changed}, 最大改变量={max_abs_delta}")
    else:logger.debug(f"单调修复检查：区间[{x1}, {x2}] 内无需修改")
    return ys2


def format_like(original_num_str: str, value: float) -> str:
    # 尽量保留原数字的小数位风格
    """把数值 value 格式化成“尽量接近原数字字符串 original_num_str 的风格”。
    
    规则：
        - 原字符串为科学计数法（含 e/E）：输出科学计数法；
        - 原字符串含小数点：保留相同小数位数；
        - 否则：尽量输出整数（若接近整数）。
    
    用途：
        apply_warp() 回写第 3 列高度时，希望尽量不改变文件整体排版，
        以免第三方软件对列宽/格式敏感。
    """
    
    if "e" in original_num_str.lower():
        return f"{value:.8e}"
    if "." in original_num_str:
        decimals = len(original_num_str.split(".")[-1])
        return f"{value:.{decimals}f}"
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def apply_warp(
    parsed: List[ParsedLine],
    T1n: float,
    T2n: float,
    mg: float,
    logger: logging.Logger,
    T1o_override: Optional[float] = None,
    T2o_override: Optional[float] = None,
    xy_data: Optional[Tuple[List[float], List[float], List[int]]] = None,
    progress_cb=None,
) -> Tuple[str, float, float]:
    """
    ✅ 规则核验：
    - 一行有 5 个数字：取第2/第3个数字（index 1/2）
    - 一行有 4 个数字：取第2/第3个数字（index 1/2）
    - 一行有 3 个数字：取第2/第3个数字（index 1/2）
    - 少于 3 个数字：不处理该行

    ✅ V215 性能优化：
    - 支持传入已提取好的 xy_data，避免重复 extract_xy_from_file()
    - 使用 piecewise_inverse_map_array() + np.interp() 做批量温度映射，明显减少 Python 循环开销
    - 支持 progress_cb(value, text) 动态回报处理进度，配合 GUI 底部进度条减少“卡死感”
    """
    def _progress(value: float, text_msg: Optional[str] = None) -> None:
        try:
            if callable(progress_cb):
                progress_cb(float(value), text_msg or "")
        except Exception:
            pass

    _progress(2.0, "提取数据")
    if xy_data is None:
        xs, ys, data_line_indices = extract_xy_from_file(parsed, logger)
    else:
        xs, ys, data_line_indices = xy_data

    if not xs:
        raise ValueError("没有找到有效数据行：每行至少要有3个数字，才能取第2列温度和第3列高度。")

    xmin, xmax = min(xs), max(xs)

    _progress(8.0, "识别基准点")
    override_t1 = None
    override_t2 = None
    if T1o_override is not None:
        try:
            _t1o = float(T1o_override)
            if xmin <= _t1o <= xmax:
                override_t1 = _t1o
            else:
                logger.debug(f"T1o_override={_t1o} 超出范围 [{xmin},{xmax}]，忽略覆盖")
        except Exception:
            logger.debug("T1o_override 无法转换为 float，忽略覆盖")

    if T2o_override is not None:
        try:
            _t2o = float(T2o_override)
            if xmin <= _t2o <= xmax:
                override_t2 = _t2o
            else:
                logger.debug(f"T2o_override={_t2o} 超出范围 [{xmin},{xmax}]，忽略覆盖")
        except Exception:
            logger.debug("T2o_override 无法转换为 float，忽略覆盖")

    if override_t1 is not None and override_t2 is not None and override_t1 < override_t2:
        T1o, T2o = float(override_t1), float(override_t2)
        logger.debug(f"直接使用缓存基准点：T1o={T1o}, T2o={T2o}")
    else:
        T1o, T2o = detect_T2_T1(xs, ys, logger)
        if override_t1 is not None:
            T1o = float(override_t1)
        if override_t2 is not None:
            T2o = float(override_t2)
        if T1o >= T2o:
            logger.debug("覆盖后的基准点不合法（T1o>=T2o），回退到自动识别值")
            T1o, T2o = detect_T2_T1(xs, ys, logger)

    logger.debug(f"数据点统计：点数={len(xs)}，温度范围=[{xmin}, {xmax}]")
    logger.debug(f"原始高度范围：[{min(ys)}, {max(ys)}]")

    # 校验新T1/T2
    if not (xmin <= T1n <= xmax and xmin <= T2n <= xmax):
        raise ValueError(f"新T1/T2必须在温度范围内 [{xmin}, {xmax}]，当前 T1={T1n}, T2={T2n}")
    if T1n >= T2n:
        raise ValueError(f"新T1必须小于新T2，当前 T1={T1n}, T2={T2n}")

    _progress(15.0, "修正锚点")
    T1o_used, T2o_used, meta = sanitize_warp_anchors(xs, T1o, T2o, xmin, xmax, logger)
    if meta.get("adjusted"):
        logger.debug(f"warp锚点已修正: T1o {T1o} -> {T1o_used}, T2o {T2o} -> {T2o_used}")

    _progress(22.0, "建立插值")
    curve_cache = build_curve_cache(xs, ys)
    xp0 = np.asarray(curve_cache["xp"], dtype=float)
    fp0 = np.asarray(curve_cache["yp"], dtype=float)

    _progress(30.0, "温度映射")
    xs_arr = np.asarray(xs, dtype=float)
    x_old_arr = piecewise_inverse_map_array(xs_arr, xmin, xmax, T1o_used, T2o_used, T1n, T2n)
    y_new_arr = np.interp(x_old_arr, xp0, fp0)

    _progress(58.0, "单调修复")
    y_new = y_new_arr.tolist()
    if MONOTONIC_FIX_T1_T2:
        y_new = enforce_monotonic_between(xs, y_new, T1n, T2n, logger)

    _progress(72.0, "质量缩放")
    if mg <= 0:
        raise ValueError(f"mg 必须大于0,当前 mg={mg}")
    scale = 0.5 / mg
    y_new = (np.asarray(y_new, dtype=float) * scale).tolist()
    logger.debug(f"已应用 mg 缩放:mg={mg}，缩放系数=0.5/mg={scale}")

    _progress(80.0, "写回文件")
    new_lines = [pl.raw for pl in parsed]
    total_lines = max(1, len(data_line_indices))
    update_step = max(1, total_lines // 25)
    for local_i, line_idx in enumerate(data_line_indices):
        pl = parsed[line_idx]
        span = pl.spans[2]  # 第3个数字的原始位置
        old_str = pl.raw[span[0]:span[1]]
        new_str = format_like(old_str, y_new[local_i])
        new_lines[line_idx] = pl.raw[:span[0]] + new_str + pl.raw[span[1]:]
        if (local_i + 1) % update_step == 0 or (local_i + 1) == total_lines:
            frac = (local_i + 1) / total_lines
            _progress(80.0 + frac * 18.0, "写回文件")

    logger.debug(f"修改后高度范围：[{min(y_new)}, {max(y_new)}]")
    _progress(100.0, "写回完成")
    return "".join(new_lines), T1o_used, T2o_used

# =========================
# GUI 日志 Handler
# =========================

# 日志中需要将“路径部分”标红的常见前缀。
# 注意：这里故意只列出会紧跟文件/目录路径的前缀，避免误标普通文本。
PATH_PREFIXES = (
    "选择文件位置:",
    "输出文件位置:",
    "选择输出路径:",
    "输入文件:",
    "输出文件:",
    "输入文件位置:",
    "输入文件夹位置:",
    "输出文件位置:",
    "当前输出路径:",
    "已生成TIFF图:",
    "已生成仿生TIFF图:",
)


class TextHandler(logging.Handler):
    """Write logs to a Tk ScrolledText with colored segments.

    - 默认只显示 INFO / ERROR（以及 CRITICAL）
    - 当 is_debug_mode() 为 True 时，额外显示 DEBUG / WARNING
    - 选择新文件时，可先写入黄色分隔符 "=========="（无时间/函数名前缀）
    - 函数名：蓝色；文件路径：红色；LG 列表：绿色
    """

    def __init__(self, text_widget: ScrolledText, is_debug_mode=None):
        """TextHandler 构造函数：把 logging 输出重定向到 Tkinter 的 ScrolledText。
        
        参数：
            text_widget: 用于展示日志的 ScrolledText 控件。
            is_debug_mode: 回调函数/可调用对象，用于判断当前 UI 是否开启 DEBUG 显示。
        
        说明：
            - DEBUG 模式下显示更详细的日志；非 DEBUG 时过滤掉低等级日志以免刷屏。
            - 同时初始化多种 tag（颜色/加粗）用于高亮函数名、路径、LG 列表等。
        """
        
        super().__init__()
        self.text_widget = text_widget  # Tk 的 ScrolledText 控件：日志最终写入这里
        self.is_debug_mode = is_debug_mode  # 回调：返回 True 表示 UI 处于 DEBUG 详细显示模式
        self._init_tags()

    def _init_tags(self):
        """初始化 Tkinter Text 的 tag（颜色/字体）。
        
        tag 用途：
            - SEPARATOR：黄色分隔线
            - FUNC：函数名（蓝色）
            - PATH：路径（红色）
            - LG：LG 列表（绿色）
            - UNCHANGED：标注“未更改”的深红加粗
            - INFO/DEBUG/WARNING/ERROR/CRITICAL：按日志级别着色
        """
        
        try:
            tw = self.text_widget
            tw.tag_configure("SEPARATOR", foreground="#D4A000")        # 黄
            tw.tag_configure("FUNC", foreground="#1E5AA8")       # 蓝
            tw.tag_configure("PATH", foreground="#C00000")       # 红
            tw.tag_configure("LG", foreground="#0B7D0B")         # 绿

            tw.tag_configure("INFO", foreground="#000000")
            tw.tag_configure("DEBUG", foreground="#666666")
            tw.tag_configure("WARNING", foreground="#CC7A00")
            tw.tag_configure("ERROR", foreground="#C00000")
            tw.tag_configure("CRITICAL", foreground="#FFFFFF", background="#C00000")
            self._bold_font = tkfont.Font(font=tw.cget("font"))
            self._bold_font.configure(weight="bold")
            tw.tag_configure("UNCHANGED", foreground="#8B0000", font=self._bold_font)

        except Exception:
            pass
    def _level_tag(self, levelno: int) -> str:
        """把 logging 的 levelno 映射为 TextHandler 使用的 tag 名称。
        
        参数：
            levelno: logging 级别数字（如 logging.INFO）。
        
        返回：
            str：对应的 tag 名称。
        """
        
        if levelno >= logging.CRITICAL:
            return "CRITICAL"
        if levelno >= logging.ERROR:
            return "ERROR"
        if levelno >= logging.WARNING:
            return "WARNING"
        if levelno >= logging.INFO:
            return "INFO"
        return "DEBUG"

    def _insert_colored_message_line(self, line: str, base_tag: str):
        """
        将一行消息插入到 Text，并进行简单的关键词/路径着色：
        - "=========="：黄色分隔符
        - 行以 PATH_PREFIXES 开头：冒号后面的内容标红（路径）
        - 行内包含 Windows/UNC 路径：路径标红（即使不以 prefix 开头也能识别）
        - "LG=[...]"：整行绿色
        - "（未更改）"：深红加粗（路径仍保持红色）
        """
        tw = self.text_widget
        marker_unchanged = "（未更改）"

        def insert_with_paths(text: str):
            """在不自动换行的情况下，插入 text，并把其中的路径标红。"""
            path_re = re.compile(r'(\\\\[^\s]+|[A-Za-z]:[\\/][^\s]+)')
            last = 0
            any_path = False
            for m in path_re.finditer(text):
                any_path = True
                if m.start() > last:
                    tw.insert("end", text[last:m.start()], base_tag)
                tw.insert("end", text[m.start():m.end()], "PATH")
                last = m.end()
            if any_path and last < len(text):
                tw.insert("end", text[last:], base_tag)
            if not any_path:
                tw.insert("end", text, base_tag)

        if line.strip() == "==========":
            tw.insert("end", "==========" + "\n", "SEPARATOR")
            return

        stripped = line.strip()
        if stripped.startswith("LG=") or stripped.startswith("LG=["):
            tw.insert("end", line + "\n", "LG")
            return

        # LG 多行列表：形如 "{ 0.45,   9.526}," 的行也标绿
        if re.match(r'^\{\s*[-+]?\d+(?:\.\d+)?\s*,\s*[-+]?\d+(?:\.\d+)?\s*\}\s*,?$', stripped):
            tw.insert("end", line + "\n", "LG")
            return

        # 1) 以固定前缀开头：冒号后面路径标红
        for prefix in PATH_PREFIXES:
            if line.startswith(prefix):
                rest = line[len(prefix):].lstrip()
                tw.insert("end", prefix + (" " if not prefix.endswith(" ") else ""), base_tag)

                if marker_unchanged in rest:
                    before, after = rest.split(marker_unchanged, 1)
                    if before:
                        tw.insert("end", before, "PATH")
                    tw.insert("end", marker_unchanged, "UNCHANGED")
                    if after:
                        tw.insert("end", after, "PATH")
                else:
                    if rest:
                        tw.insert("end", rest, "PATH")

                tw.insert("end", "\n", base_tag)
                return

        # 2) 非前缀行：既要支持路径标红，也要支持“未更改”深红加粗
        if marker_unchanged in line:
            before, after = line.split(marker_unchanged, 1)
            insert_with_paths(before)
            tw.insert("end", marker_unchanged, "UNCHANGED")
            insert_with_paths(after)
            tw.insert("end", "\n", base_tag)
            return

        # 3) 默认：做一次路径高亮（若无路径则普通插入）
        insert_with_paths(line)
        tw.insert("end", "\n", base_tag)
        return

    def _append_record(self, header_prefix: str, func_name: str, msg: str, base_tag: str) -> None:
        """把一条日志追加到 Tk 的 ScrolledText 中（线程安全）。"""
        tw = self.text_widget

        def append():
            """内部回调：实际把一条日志写入到 Tk Text 控件。
            
            说明：
                - 该函数通过 tw.after(0, ...) 在 Tk 主线程执行，
                  避免后台线程直接操作 Tk 控件导致崩溃。
                - 同时负责分隔符/路径高亮/LG 高亮等显示细节。
            """
            
            try:
                tw.configure(state="normal")

                # 分隔符：只显示黄色“==========”
                if str(msg).strip() == "==========":
                    tw.insert("end", "==========\n", "SEPARATOR")
                    tw.configure(state="disabled")
                    tw.see("end")
                    return

                # Header：时间+级别 + 函数名（蓝色）
                tw.insert("end", header_prefix, base_tag)
                tw.insert("end", str(func_name), "FUNC")
                tw.insert("end", "\n", base_tag)

                # Body：逐行写入（路径/LG/未更改等做局部高亮）
                body = str(msg) if msg is not None else ""
                if body:
                    for line in body.splitlines():
                        self._insert_colored_message_line(line, base_tag)
                else:
                    self._insert_colored_message_line("", base_tag)

                tw.configure(state="disabled")
                tw.see("end")
            except Exception:
                # UI 日志不能影响主流程
                try:
                    tw.configure(state="disabled")
                except Exception:
                    pass

        try:
            tw.after(0, append)  # 保证在 Tk 主线程执行
        except Exception:
            append()

    def emit(self, record: logging.LogRecord) -> None:
        """logging.Handler 接口：根据 DEBUG 开关决定输出粒度。"""
        try:
            debug_mode = bool(self.is_debug_mode()) if callable(self.is_debug_mode) else False

            # UI 非 DEBUG：只显示 INFO / ERROR（以及 WARNING 视为 INFO）
            if (not debug_mode) and record.levelno < logging.INFO:
                return

            base_tag = "ERROR" if record.levelno >= logging.ERROR else ("INFO" if record.levelno >= logging.INFO else "DEBUG")
            ts = datetime.datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
            header_prefix = f"[{ts}] {record.levelname} - "
            func_name = getattr(record, "funcName", "")

            msg = record.getMessage()

            # 异常：DEBUG 模式输出完整堆栈；INFO 模式只补充异常信息
            if record.exc_info:
                if debug_mode:
                    import traceback
                    msg = (msg + "\n" if msg else "") + "".join(traceback.format_exception(*record.exc_info))
                else:
                    _exc_type, exc_val, _tb = record.exc_info
                    if exc_val is not None:
                        extra = str(exc_val)
                        if extra and extra not in (msg or ""):
                            msg = (msg + "： " if msg else "") + extra

            self._append_record(header_prefix, func_name, msg, base_tag)
        except Exception:
            pass


@contextmanager
def _scoped_ui_debug(app, enabled: bool):
    """Temporarily enable verbose log display in UI for one action."""
    old = getattr(app, "_ui_debug_active", False)
    try:
        app._ui_debug_active = bool(enabled)
        yield
    finally:
        app._ui_debug_active = old


def compute_lg_list(mg_values: List[float], H: float, logger: Optional[logging.Logger] = None) -> str:
    """按给定 mg 列表与高度差 H(μm) 计算 LG 列表（保留 3 位小数）。

    公式（用户约定）：
        LG = 1000 * mg / (π * 3.35 * 3.35 * H / 1000)

    其中：
      - mg：质量（mg）
      - H：高度差（μm），H = H2 - H1
      - π：圆周率

    说明：
    - 理论上 H 应为正数；若 H<0（曲线方向相反），V206 会使用 |H| 继续计算，
      并在日志中给出 WARNING（避免算法/批处理直接失败）。
    """
    try:
        H = float(H)
    except Exception:
        raise ValueError(f"H 不是有效数字：{H!r}")

    if H == 0:
        raise ValueError("H 不能为 0（H=H2-H1）。")
    if H < 0:
        if logger is not None:
            try:
                logger.warning(f"H 为负({H:.6g})：已按 |H| 计算 LG。")
            except Exception:
                pass
        H = abs(H)

    out_lines = ["LG=["]
    for mg in mg_values:
        lg = 1000.0 * float(mg) / (math.pi * 3.35 * 3.35 * H / 1000.0)
        out_lines.append(f"  {{{float(mg):>5.2f}, {lg:>8.3f}}},")
    if len(out_lines) > 1:
        out_lines[-1] = out_lines[-1].rstrip(",")  # 最后一行不带逗号
    out_lines.append("]")
    return "\n".join(out_lines)


class App:
    def __init__(self, root: tk.Tk):
        """主应用构造函数：初始化 GUI、日志系统以及运行时缓存。
        
        参数：
            root: Tk 根窗口。
        
        关键成员变量（概览）：
            - input_path/output_path：输入/输出路径。
            - t1_var/t2_var/mg_var：用户可编辑参数。
            - _cached_parsed：缓存解析后的 ParsedLine，避免重复读取与解析。
            - _warp_base_t1/_warp_base_t2：warp 使用的“原始基准点”（会被梯度算法更新）。
            - _last_output_*：最近一次执行调整后的文本/解析结果（供绘图复用）。
        """
        
        self.root = root  # Tk 根窗口引用（用于创建子窗口/对话框等）
        self.root.title(f"TMA数据分析处理器 ({VERSION})")

        self.input_path = tk.StringVar()  # 输入文件路径（用户选择的原始数据文件）
        self.output_path = tk.StringVar()  # 输出文件路径（执行调整后写出的新文件）
        self.t1_var = tk.StringVar()  # T1 输入框变量（℃）
        self.t2_var = tk.StringVar()  # T2 输入框变量（℃）
        self.mg_var = tk.StringVar(value="0.50")  # mg 输入框变量（mg，决定高度缩放系数 0.5/mg）

        # UI debug 显示开关：仅对单次动作生效（执行/选择文件时临时置 True）
        self._ui_debug_active = False  # 内部开关：本次操作是否向 UI 输出 DEBUG 日志（避免日常刷屏）
        self.debug_var = tk.BooleanVar(value=False)  # 复选框变量：用户是否勾选 DEBUG 模式

        # 绘图导出路径（绘图窗口复用）
        self.export_use_newpath_var = tk.BooleanVar(value=False)  # 绘图导出：是否启用自定义出图目录
        self.export_newpath_var = tk.StringVar(value=r"\\192.168.0.105\TMAresult\LS")  # 绘图导出：自定义出图目录（网络盘/本地目录）

        self._recent_export_paths: List[str] = []  # 近期使用的出图目录（最多 3 个，用于下拉框）

        # ---------------------------

        # 输入路径下拉框（v208）

        # ---------------------------

        # 预制目录：用于“更快抵达”常用网络路径（下拉框选择后，再点击【文件路径】选择具体文件）

        self._preset_input_dirs: List[str] = [normalize_path_separators(p) for p in PRESET_INPUT_DIRS]

        # 桌面路径：本机常用（也放到下拉里）

        self._desktop_path: str = normalize_path_separators(get_desktop_path())

        # 最近 3 个手动选择过的输入文件夹（仅记录“文件对话框选择文件”的目录）

        self._recent_input_dirs: List[str] = []

        # 输入路径 Combobox 控件引用（用于动态刷新 values）

        self._input_path_combo = None

        self._build_ui()
        self.logger = self._setup_logger()  # 应用 logger（输出到 GUI 日志框）

        self._log_tutorial()
        self._cached_parsed: Optional[List[ParsedLine]] = None  # 缓存：当前输入文件解析后的 ParsedLine 列表（避免重复解析）
        self._cached_xy_data: Optional[Tuple[List[float], List[float], List[int]]] = None  # 当前输入文件的 (x, y, 行号) 缓存
        self._cached_curve_cache: Optional[Dict[str, Any]] = None  # 当前输入文件的排序/去重插值缓存
        # 拉伸算法使用的“原始”T1/T2基准点（可被梯度算法更新）
        self._warp_base_t1: Optional[float] = None  # warp 基准点：原始/梯度算法得到的 T1（用于 piecewise warp）
        self._warp_base_t2: Optional[float] = None  # warp 基准点：原始/梯度算法得到的 T2（用于 piecewise warp）


        # 最近一次“执行修改”产生的文本/解析结果（用于绘图）
        self._last_output_text: Optional[str] = None  # 最近一次执行调整后的完整文本（供绘图/复用）
        self._last_output_parsed: Optional[List[ParsedLine]] = None  # 最近一次执行调整后的解析结果（供绘图/复用）
        self._last_output_xy_data: Optional[Tuple[List[float], List[float], List[int]]] = None  # 最近一次执行调整后的 (x, y, 行号) 缓存
        self._last_output_curve_cache: Optional[Dict[str, Any]] = None  # 最近一次执行调整后的排序/去重插值缓存
        self._last_run_mg: Optional[float] = None  # 最近一次执行调整使用的 mg（用于绘图副标题/备注）

        # 绘图窗口缓存
        self._plot_win: Optional[tk.Toplevel] = None  # 绘图窗口（Toplevel）引用，用于复用/避免重复创建
        self._plot_canvas: Optional[FigureCanvasTkAgg] = None  # Matplotlib 画布（FigureCanvasTkAgg）引用
        self._plot_fig: Optional[Figure] = None  # Matplotlib Figure 引用（用于导出/刷新）
        self._plot_toolbar: Optional[ttk.Frame] = None  # 绘图窗口工具栏 Frame（放导出按钮等）
        # 绘图窗口专用 mg（仅影响图中备注，不影响主界面 mg）
        self._plot_mg_var = tk.StringVar(value='')  # 绘图窗口 mg(标注) 输入框变量（仅影响图中文字）
        self._plot_method_artist = None  # 绘图左上角“方法日志”文本对象（用于动态刷新 mg）
        self._plot_note_x_left = None  # 为避免备注遮挡曲线，左上角备注会向左挪：该变量记录 x 轴左边界
        self._plot_ax = None  # 绘图坐标轴 Axes 引用（用于刷新标注）

    def _build_ui(self):
        """构建主界面 UI（按钮、输入框、日志框等）。
        
        说明：
            - 这里只做控件布局，不做业务逻辑。
            - 业务逻辑由 on_choose_file/on_execute/on_plot 等事件处理函数负责。
        """
        
        frm = ttk.Frame(self.root, padding=10)
        frm.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)

        # 第1行：输入路径（v208：可下拉、可手打）
        ttk.Button(frm, text="文件路径", command=self.on_choose_file).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)

        # 输入路径改为 Combobox：
        # - 可手动输入完整文件路径（.txt / .001~.999）
        # - 下拉可选择“预制文件夹路径/桌面/最近目录”，用于更快定位目录
        self._input_path_combo = ttk.Combobox(frm, textvariable=self.input_path, state="normal")
        self._input_path_combo.grid(row=0, column=1, sticky="ew", pady=4)

        # 初始化下拉项，并绑定事件（提示 + 自动清理分隔符/控制字符）
        self._refresh_input_path_choices()
        try:
            self._input_path_combo.bind("<<ComboboxSelected>>", self._on_input_path_combo_selected)
            self._input_path_combo.bind("<Return>", self._on_input_path_enter)
            self._input_path_combo.bind("<FocusOut>", self._on_input_path_focus_out)
        except Exception:
            # 某些精简 Tk 环境可能不支持 bind；忽略不影响主流程
            pass

        # 第2行
        ttk.Button(frm, text="输出路径", command=self.on_choose_output).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(frm, textvariable=self.output_path).grid(row=1, column=1, sticky="ew", pady=4)

        # 第3行
        row3 = ttk.Frame(frm)
        row3.grid(row=2, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Label(row3, text="T1=").grid(row=0, column=0, padx=(0, 6))
        ttk.Entry(row3, width=12, textvariable=self.t1_var).grid(row=0, column=1, padx=(0, 16))
        ttk.Label(row3, text="T2=").grid(row=0, column=2, padx=(0, 6))
        ttk.Entry(row3, width=12, textvariable=self.t2_var).grid(row=0, column=3, padx=(0, 16))
        ttk.Label(row3, text="Mg=").grid(row=0, column=4, padx=(0, 6))
        ttk.Entry(row3, width=8, textvariable=self.mg_var).grid(row=0, column=5)

        # 第4行
        row4 = ttk.Frame(frm)
        row4.grid(row=3, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Button(row4, text="执行调整", command=self.on_execute).grid(row=0, column=0, padx=(0, 10))
        ttk.Button(row4, text="使用绘图", command=self.on_plot).grid(row=0, column=1, padx=(0, 10))
        ttk.Button(row4, text="梯度算法", command=self.on_precise_read).grid(row=0, column=2, padx=(0, 10))
        ttk.Button(row4, text="超级梯度算法", command=self.on_super_gradient_read).grid(row=0, column=3, padx=(0, 10))
        ttk.Button(row4, text="显示积分值", command=self.on_show_integral).grid(row=0, column=4, padx=(0, 10))
        ttk.Button(row4, text="退出软件", command=self.root.destroy).grid(row=0, column=5)
        ttk.Button(frm, text="Soft Log", command=self.on_soft_log).grid(row=4, column=0, sticky="w")
        tk.Checkbutton(frm, text="DeBug Mode", variable=self.debug_var, fg="orange").grid(row=4, column=1, sticky="w", padx=8)
        self.log_box = ScrolledText(frm, height=14)
        self.log_box.grid(row=5, column=0, columnspan=2, sticky="nsew", pady=(4, 0))
        self.log_box.configure(state="disabled")

        status_fr = ttk.Frame(frm)
        status_fr.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        status_fr.columnconfigure(1, weight=1)
        self.progress_text_var = tk.StringVar(value="就绪")
        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Label(status_fr, textvariable=self.progress_text_var, width=18).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.progress_bar = ttk.Progressbar(status_fr, orient="horizontal", mode="determinate", maximum=100.0, variable=self.progress_var)
        self.progress_bar.grid(row=0, column=1, sticky="ew")

        frm.rowconfigure(5, weight=1)

    def _setup_logger(self) -> logging.Logger:
        """初始化应用 logger，并把输出绑定到 GUI 的日志框。
        
        返回：
            logging.Logger：配置好的 logger（级别 DEBUG，具体显示由 UI debug 开关控制）。
        """
        
        logger = logging.getLogger("curve_warp")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        logger.propagate = False
    
        handler = TextHandler(self.log_box, is_debug_mode=lambda: self._ui_debug_active)
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter("[%(asctime)s] %(levelname)s - %(funcName)s\n%(message)s", datefmt="%H:%M:%S")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    def _set_progress(self, value: float, text: str = "") -> None:
        """更新主界面底部进度条与状态文本，并立即推动 UI 刷新。

        v216：相比仅调用 update_idletasks()，这里额外执行一次轻量 update()，
        让每个处理节点都能及时把进度条绘制出来，降低“像卡死”的观感。
        """
        try:
            v = max(0.0, min(100.0, float(value)))
        except Exception:
            v = 0.0
        try:
            if hasattr(self, "progress_var"):
                old_v = float(self.progress_var.get())
                if abs(v - old_v) < 1e-9 and v < 100.0:
                    v = min(100.0, v + 0.1)
                self.progress_var.set(v)
            if hasattr(self, "progress_text_var"):
                if text:
                    self.progress_text_var.set(f"{text} ({int(round(v))}%)")
                else:
                    self.progress_text_var.set(f"{int(round(v))}%")
            self.root.update_idletasks()
            try:
                self.root.update()
            except tk.TclError:
                pass
        except Exception:
            pass

    def _bump_progress(self, delta: float = 1.0, text: str = "") -> None:
        """在当前进度基础上小步推进，用于“每执行一个节点就动一下”。"""
        try:
            cur = float(self.progress_var.get()) if hasattr(self, "progress_var") else 0.0
        except Exception:
            cur = 0.0
        try:
            delta = float(delta)
        except Exception:
            delta = 1.0
        if delta <= 0:
            delta = 0.5
        self._set_progress(min(99.0, cur + delta), text)

    def _finish_progress(self, text: str = "完成", delay_ms: int = 800) -> None:
        """把进度条置为 100%，并在短暂停留后恢复到“就绪”状态。"""
        self._set_progress(100.0, text)
        try:
            self.root.after(int(delay_ms), lambda: self._set_progress(0.0, "就绪"))
        except Exception:
            pass

    def _reset_progress(self, text: str = "就绪") -> None:
        """立即清空进度条。"""
        self._set_progress(0.0, text)

    def _invalidate_input_curve_cache(self) -> None:
        self._cached_xy_data = None
        self._cached_curve_cache = None

    def _invalidate_output_curve_cache(self) -> None:
        self._last_output_xy_data = None
        self._last_output_curve_cache = None

    def _get_input_xy_data(self) -> Tuple[List[float], List[float], List[int]]:
        if self._cached_parsed is None:
            raise ValueError("当前没有已加载的输入数据。")
        if self._cached_xy_data is None:
            self._cached_xy_data = extract_xy_from_file(self._cached_parsed, self.logger)
        return self._cached_xy_data

    def _get_output_xy_data(self) -> Tuple[List[float], List[float], List[int]]:
        if self._last_output_parsed is None:
            raise ValueError("当前没有修改后的输出数据。")
        if self._last_output_xy_data is None:
            self._last_output_xy_data = extract_xy_from_file(self._last_output_parsed, self.logger)
        return self._last_output_xy_data

    def _get_input_curve_cache(self) -> Dict[str, Any]:
        if self._cached_curve_cache is None:
            xs, ys, _ = self._get_input_xy_data()
            self._cached_curve_cache = build_curve_cache(xs, ys)
        return self._cached_curve_cache

    def _get_output_curve_cache(self) -> Dict[str, Any]:
        if self._last_output_curve_cache is None:
            xs, ys, _ = self._get_output_xy_data()
            self._last_output_curve_cache = build_curve_cache(xs, ys)
        return self._last_output_curve_cache

    def _get_active_curve_bundle(self, prefer_output: bool = True):
        """返回当前 GUI 应使用的曲线数据包。

        返回：
            (src_tag, parsed, xs, ys, curve_cache)

        说明：
            - prefer_output=True 时，若存在最近一次“执行调整”的结果，则优先返回修改后曲线；
            - 否则回退到当前输入文件对应的原始曲线。
        """
        in_path = normalize_path_separators(self.input_path.get().strip())
        if prefer_output and self._last_output_parsed is not None:
            parsed = self._last_output_parsed
            src_tag = "修改后"
            xs, ys, _line_idxs = self._get_output_xy_data()
            curve_cache = self._get_output_curve_cache()
            return src_tag, parsed, xs, ys, curve_cache

        if self._cached_parsed is None:
            text, meta = load_text_prefer_tajm(in_path, self.logger)
            self.logger.debug(
                f"读取来源: {meta.get('used')}"
                + (f" rows={meta.get('rows')}" if meta.get('used') == 'tajm' else "")
            )
            self._cached_parsed = parse_lines(text)
            self._invalidate_input_curve_cache()

        parsed = self._cached_parsed
        src_tag = "原始"
        xs, ys, _line_idxs = self._get_input_xy_data()
        curve_cache = self._get_input_curve_cache()
        return src_tag, parsed, xs, ys, curve_cache

    def _compute_current_interval_metrics(self, prefer_output: bool = True):
        """基于当前 GUI 的 T1/T2 与当前曲线，计算 H1/H2/H/积分。"""
        src_tag, _parsed, xs, ys, curve_cache = self._get_active_curve_bundle(prefer_output=prefer_output)
        if not xs or not ys:
            raise ValueError("当前曲线为空，无法计算积分。")
        try:
            t1 = float((self.t1_var.get() or '').strip())
            t2 = float((self.t2_var.get() or '').strip())
        except Exception as exc:
            raise ValueError("请先设置有效的 T1/T2。") from exc
        if not (math.isfinite(t1) and math.isfinite(t2)):
            raise ValueError("T1/T2 不是有效数字。")
        if t1 >= t2:
            raise ValueError("T1 必须小于 T2。")
        h1 = interpolate_curve_height(t1, curve_cache)
        h2 = interpolate_curve_height(t2, curve_cache)
        area = integrate_curve_interval_from_cache(curve_cache, t1, t2)
        return {
            "src_tag": src_tag,
            "T1": float(t1),
            "T2": float(t2),
            "H1": float(h1),
            "H2": float(h2),
            "H": float(h2 - h1),
            "area": float(area),
            "curve_cache": curve_cache,
        }


    def _log_tutorial(self) -> None:
        """启动时在日志栏打印简明教程（INFO 级别）。"""
        try:
            self.logger.info("==========")
            self.logger.info(f"欢迎使用【TMA】数据分析处理器（{VERSION}）")

            tutorial = Gonggao_Message_by_thisone  # 统一使用全局公告文本，避免多处维护
            self.logger.info(tutorial)
        except Exception:
            # 教程打印失败不影响主流程
            try:
                self.logger.info("==========")
                self.logger.info("教程打印失败（已忽略）。")
            except Exception:
                pass

    def on_soft_log(self) -> None:
        """重新打印启动时写入日志栏的教程/初始化信息（不弹窗）。"""
        try:
            self._log_tutorial()
        except Exception:
            # Soft Log 重新打印失败不影响主流程
            try:
                self.logger.error("Soft Log 重新打印失败（已忽略）。")
            except Exception:
                pass

    # 兼容旧版本：保留方法名，但不再弹出公告框
    def show_announcement(self) -> None:
        """旧版本兼容：等价于 Soft Log 重新打印，不再弹窗。"""
        self.on_soft_log()

    # ---------------------------
    # 输入路径下拉框相关（v208）
    # ---------------------------
    def _norm_dir_for_dropdown(self, p: str) -> str:
        """规范化目录字符串，用于输入路径下拉框的去重/存储。

        规则：
            1) 调用 normalize_path_separators() 统一分隔符，并清理控制字符；
            2) 去除末尾多余的 '/' 或 '\\'（避免同一目录出现 ".../dir" 与 ".../dir/" 两条）；
               但保留盘符根目录（如 "C:\\"）。
        """
        p = normalize_path_separators((p or "").strip())
        if not p:
            return ""

        p2 = p.rstrip("/\\")
        if re.fullmatch(r"[A-Za-z]:", p2):
            # Windows 盘符根目录需要保留分隔符
            return p2 + "\\"
        return p2

    def _input_dir_dropdown_values(self) -> List[str]:
        """返回输入路径下拉框应展示的目录列表（去重后）。

        顺序：
            1) 预制目录（3 个网络路径）
            2) 桌面目录
            3) 最近 3 个手动选择过的目录（最新在前）

        说明：
            - 下拉项主要是“目录”，用于快速定位 initialdir；
            - 真正运行时仍需要输入“文件路径”（.txt / .001~.999）。
        """
        values: List[str] = []

        # 1) 预制目录
        for p in getattr(self, "_preset_input_dirs", []) or []:
            pp = self._norm_dir_for_dropdown(p)
            if pp and pp not in values:
                values.append(pp)

        # 2) 桌面目录
        dp = self._norm_dir_for_dropdown(getattr(self, "_desktop_path", ""))
        if dp and dp not in values:
            values.append(dp)

        # 3) 最近目录
        for p in getattr(self, "_recent_input_dirs", []) or []:
            pp = self._norm_dir_for_dropdown(p)
            if pp and pp not in values:
                values.append(pp)

        return values

    def _refresh_input_path_choices(self) -> None:
        """刷新输入路径下拉框的可选项（values）。

        注意：该函数不依赖 logger，可在 _build_ui() 里调用。
        """
        try:
            if self._input_path_combo is None:
                return
            self._input_path_combo["values"] = self._input_dir_dropdown_values()
        except Exception:
            pass

    def _remember_input_dir(self, dir_path: str) -> None:
        """记录用户“手动选择文件”所在的目录到输入路径下拉框（最多 3 个）。

        触发时机：
            - 用户通过 on_choose_file() 的文件对话框选择了某个文件。

        规则：
            - 若目录已在预制目录/桌面目录中，则不重复添加；
            - 最近目录插入到最前面，最多保留 3 个；
            - 记录/刷新时在日志栏给出提示。
        """
        d = self._norm_dir_for_dropdown(dir_path)
        if not d:
            return

        d_key = d.lower()
        preset_keys = {self._norm_dir_for_dropdown(p).lower() for p in getattr(self, "_preset_input_dirs", []) if p}
        desktop_key = self._norm_dir_for_dropdown(getattr(self, "_desktop_path", "")).lower()

        # 预制目录/桌面目录无需加入“最近”
        if d_key in preset_keys or (desktop_key and d_key == desktop_key):
            return

        if not hasattr(self, "_recent_input_dirs") or self._recent_input_dirs is None:
            self._recent_input_dirs = []

        # 已存在则移到最前
        for i, old in enumerate(list(self._recent_input_dirs)):
            if self._norm_dir_for_dropdown(old).lower() == d_key:
                try:
                    self._recent_input_dirs.pop(i)
                except Exception:
                    pass
                break

        self._recent_input_dirs.insert(0, d)
        del self._recent_input_dirs[3:]  # 最多保留 3 个

        self._refresh_input_path_choices()

        # log：提示已加入/刷新
        try:
            if hasattr(self, "logger") and self.logger is not None:
                self.logger.info(
                    "已记录输入文件夹到下拉框（最多保留3个）：\n"
                    f"输入文件夹位置: {d}\n"
                    "提示：输入路径下拉仅用于快速跳转到目录；执行/识别仍需要具体文件路径。"
                )
        except Exception:
            pass

    def _on_input_path_combo_selected(self, _event=None) -> None:
        """输入路径下拉框选择事件：给出提示（下拉仅用于快速定位目录）。"""
        try:
            p = self._norm_dir_for_dropdown(self.input_path.get())
            if p:
                self.input_path.set(p)

            if hasattr(self, "logger") and self.logger is not None and p:
                self.logger.info(
                    "已选择输入文件夹路径（用于快速定位）：\n"
                    f"输入文件夹位置: {p}\n"
                    "下一步：请点击【文件路径】选择具体文件，或在输入框手动输入完整文件路径（.txt / .001~.999）。"
                )
        except Exception:
            pass

    def _on_input_path_enter(self, _event=None) -> None:
        """输入路径框按回车：清理路径并在必要时提示。

        说明：
            - 不会自动弹出文件对话框（避免误触打断操作）；
            - 若用户手动输入的是“目录”，会提示需要选择具体文件。
        """
        try:
            raw = self.input_path.get() or ""
            clean = normalize_path_separators(raw.strip())
            if clean != raw.strip():
                self.input_path.set(clean)

            if clean and os.path.isdir(clean):
                if hasattr(self, "logger") and self.logger is not None:
                    self.logger.info(
                        "检测到输入路径为文件夹：\n"
                        f"输入文件夹位置: {clean}\n"
                        "提示：请点击【文件路径】选择具体文件，或直接输入文件全路径（例如 .../xxx.001）。"
                    )
        except Exception:
            pass

    def _on_input_path_focus_out(self, _event=None) -> None:
        """输入路径框失去焦点：清理控制字符与混合分隔符，避免后续读写报错。"""
        try:
            raw = self.input_path.get() or ""
            clean = normalize_path_separators(raw.strip())
            if clean != raw.strip():
                self.input_path.set(clean)
        except Exception:
            pass

    def _get_initialdir_for_open_file(self) -> Optional[str]:
        """推导文件对话框的 initialdir（用于更快定位目录）。

        规则：
            - 输入框是目录 -> 直接使用；
            - 输入框是文件 -> 使用其所在目录；
            - 输入框为空 -> 优先最近目录，其次预制目录，再次桌面。
        """
        try:
            cur = normalize_path_separators((self.input_path.get() or "").strip())
        except Exception:
            cur = ""

        if cur:
            try:
                if os.path.isdir(cur):
                    return cur
            except Exception:
                pass
            try:
                if os.path.isfile(cur):
                    d = normalize_path_separators(os.path.dirname(cur))
                    return d if d else None
            except Exception:
                pass
            try:
                d = normalize_path_separators(os.path.dirname(cur))
                if d and os.path.isdir(d):
                    return d
            except Exception:
                pass

        # fallback
        try:
            if getattr(self, "_recent_input_dirs", None):
                return self._norm_dir_for_dropdown(self._recent_input_dirs[0])
        except Exception:
            pass
        try:
            if getattr(self, "_preset_input_dirs", None):
                return self._norm_dir_for_dropdown(self._preset_input_dirs[0])
        except Exception:
            pass
        try:
            dp = self._norm_dir_for_dropdown(getattr(self, "_desktop_path", ""))
            return dp if dp else None
        except Exception:
            return None

    def _check_input_file_exists(self, in_path: str) -> bool:
        """检查输入路径是否为“存在的文件”。

        v208 新增：
            - 若输入路径是文件夹（目录），会在日志栏提示如何修改：
              * 下拉框选择的多为“目录”，仅用于更快定位；
              * 需要点击【文件路径】选择具体文件，或在输入框手动填写完整文件路径。

        返回：
            - True：输入路径是一个存在的文件；
            - False：输入路径为空/不存在/是文件夹。
        """
        in_path = normalize_path_separators((in_path or "").strip())
        if not in_path:
            self.logger.error(
                "输入文件路径为空：\n"
                "  - 你可以点击【文件路径】选择文件；\n"
                "  - 也可以在输入框手动输入完整文件路径（.txt / .001~.999）；\n"
                "  - 下拉框主要用于快速定位预制文件夹路径。"
            )
            return False

        # 输入是目录（文件夹）
        try:
            if os.path.isdir(in_path):
                self.logger.error(
                    "检测到输入路径是文件夹（不是文件）：\n"
                    f"输入文件夹位置: {in_path}\n"
                    "请修改为具体文件路径：\n"
                    "  1) 点击【文件路径】在该文件夹内选择文件；或\n"
                    "  2) 直接在输入框粘贴/手动输入文件全路径（例如 .../xxx.001 或 .../xxx.txt）。"
                )
                return False
        except Exception:
            # os.path.isdir 出错时忽略（继续走文件判断）
            pass

        # v208 额外判断：
        # 如果用户从下拉框选择了“预制/桌面/最近目录”，即便该目录此刻不可达（例如网络盘断开），
        # 也应该提示“你当前输入的是目录，需要选择具体文件”。
        try:
            dir_key = self._norm_dir_for_dropdown(in_path).lower()
            dropdown_keys = {self._norm_dir_for_dropdown(p).lower() for p in self._input_dir_dropdown_values()}
            if dir_key and dir_key in dropdown_keys:
                self.logger.error(
                    "检测到输入路径为文件夹（来自下拉项）：\n"
                    f"输入文件夹位置: {in_path}\n"
                    "请修改为具体文件路径：\n"
                    "  1) 点击【文件路径】在该目录内选择文件；或\n"
                    "  2) 直接在输入框粘贴/手动输入文件全路径（例如 .../xxx.001 或 .../xxx.txt）。"
                )
                return False
        except Exception:
            pass

        if not os.path.isfile(in_path):
            self.logger.error(f"输入文件不存在：{in_path}")
            return False
        return True

    def on_choose_file(self):
        """GUI 事件：选择输入文件。"""
        debug_enabled = bool(self.debug_var.get())
        self._set_progress(0.0, "选择文件")
        with _scoped_ui_debug(self, debug_enabled):
            self.logger.debug("进入 on_choose_file")
            initialdir = self._get_initialdir_for_open_file()
            if initialdir:
                path = filedialog.askopenfilename(
                    title="选择输入文件",
                    initialdir=initialdir,
                    filetypes=[("全部文件", "*.*"),
                               ("TMA 文件", "*.001"),
                               ("TXT 文件", "*.txt"),
                               ("广义tma文件", NUM_EXT_PATTERNS)]
                )
            else:
                path = filedialog.askopenfilename(
                    title="选择输入文件",
                    filetypes=[("全部文件", "*.*"),
                               ("TMA 文件", "*.001"),
                               ("TXT 文件", "*.txt"),
                               ("广义tma文件", NUM_EXT_PATTERNS)]
                )
            if not path:
                self._reset_progress("就绪")
                return

            if not os.path.isfile(path):
                self._reset_progress("就绪")
                self.logger.error(f"输入文件不存在：{path}")
                return

            path = normalize_path_separators(path)
            self.input_path.set(path)
            try:
                self._remember_input_dir(os.path.dirname(path))
            except Exception:
                pass
            self.mg_var.set("0.50")

            # 切换文件后，清空上一份样品与输出缓存
            self._cached_parsed = None
            self._invalidate_input_curve_cache()
            self._warp_base_t1 = None
            self._warp_base_t2 = None
            self._last_output_text = None
            self._last_output_parsed = None
            self._invalidate_output_curve_cache()
            self._last_run_mg = None

            base, ext = os.path.splitext(path)
            out_default = base + "_new" + (ext if ext else ".txt")
            self.output_path.set(out_default)
            self.logger.info("==========")
            self.logger.info(f"选择文件位置: {path}.\n输出文件位置: {out_default}")

            try:
                self._set_progress(12.0, "读取文件")
                text, meta = load_text_prefer_tajm(path, self.logger)
                self._bump_progress(8.0, "读取完成")
                self.logger.debug(f"读取来源: {meta.get('used')}" + (f" rows={meta.get('rows')}" if meta.get('used')=='tajm' else ""))

                self._set_progress(28.0, "解析文本")
                parsed = parse_lines(text)
                self._cached_parsed = parsed
                self._invalidate_input_curve_cache()
                self._bump_progress(10.0, "解析完成")

                self._set_progress(46.0, "提取曲线")
                xs, ys, line_idxs = extract_xy_from_file(parsed, self.logger)
                self._cached_xy_data = (xs, ys, line_idxs)
                self._set_progress(60.0, "建立缓存")
                self._cached_curve_cache = build_curve_cache(xs, ys)

                self._set_progress(76.0, "识别T1/T2")
                T1o, T2o = detect_T2_T1(xs, ys, self.logger)
                self._bump_progress(8.0, "识别完成")
                self._warp_base_t1 = T1o
                self._warp_base_t2 = T2o
                self.t1_var.set(f"{T1o:.6g}")
                self.t2_var.set(f"{T2o:.6g}")

                try:
                    debug_enabled = bool(self.debug_var.get()) if hasattr(self, 'debug_var') else False
                except Exception:
                    debug_enabled = False
                if not debug_enabled:
                    try:
                        curve_cache = self._cached_curve_cache if self._cached_curve_cache is not None else build_curve_cache(xs, ys)
                        H1 = interpolate_curve_height(T1o, curve_cache)
                        H2 = interpolate_curve_height(T2o, curve_cache)
                        H = H2 - H1
                        h_message = f"""信息Message
    T1={T1o} °C
    T2={T2o} °C
    T1对应高度(H1): {format_height_um(H1)} μm
    T2对应高度(H2): {format_height_um(H2)} μm
    高度差H=H2-H1: {format_height_um(H)} μm"""
                        self.logger.info(f"{h_message}")
                        self._set_progress(92.0, "计算LG")
                        mg_values = [round(0.45 + 0.01 * i, 2) for i in range(11)]
                        lg_s = compute_lg_list(mg_values, H, logger=self.logger)
                        self.logger.info(lg_s)
                        self._bump_progress(4.0, "更新界面")
                    except Exception as _e:
                        self.logger.error(f"LG计算失败：{_e}")

                self._finish_progress("文件读取完成")
            except Exception as e:
                self._reset_progress("就绪")
                self.logger.exception("读取/识别 T1/T2 失败")
                messagebox.showerror("错误", f"读取/识别T1/T2失败：\n{e}")

    def on_choose_output(self):
        """GUI 事件：选择输出文件路径（保存为新文件，不覆盖原始数据）。
        
        说明：
            - 输出文本默认使用 UTF-16LE + BOM，便于 Windows 软件稳定识别编码。
        """
        
        debug_enabled = bool(self.debug_var.get()) if hasattr(self, 'debug_var') else False
        with _scoped_ui_debug(self, debug_enabled):
            self.logger.debug("进入 on_choose_output")
            path = filedialog.asksaveasfilename(
                title="选择输出保存路径",
                defaultextension=".txt",
                filetypes=[("文本文件", "*.txt"),
                           ("全部文件", "*.*"),
                           ("欲问酒家何处有", "*.001"),
                           ("牧童遥指杏花村", "*.002")]
            )
            if not path:
                return
            path = normalize_path_separators(path)
            self.output_path.set(path)
            self.logger.info(f"选择输出路径: {path}")

    def on_precise_read(self):
        """梯度算法（原“精密读取”）：仅更新 T1；T2 始终取最大峰。"""
        in_path = normalize_path_separators(self.input_path.get().strip())
        if not self._check_input_file_exists(in_path):
            return

        debug_enabled = bool(self.debug_var.get()) if hasattr(self, "debug_var") else False
        self.logger.info("==========")
        self.logger.info("开始梯度算法（仅更新T1，T2=最大峰不变）")
        self._set_progress(0.0, "梯度算法")

        with _scoped_ui_debug(self, debug_enabled):
            try:
                if self._cached_parsed is None:
                    self._set_progress(12.0, "读取文件")
                    self.logger.debug("调用 load_text_prefer_tajm()")
                    text, meta = load_text_prefer_tajm(in_path, self.logger)
                    src_used = meta.get("used")
                    rows = meta.get("rows")
                    if debug_enabled:
                        self.logger.debug(f"读取来源: {src_used}" + (f" rows={rows}" if src_used == "tajm" else ""))
                    self._cached_parsed = parse_lines(text)
                    self._invalidate_input_curve_cache()

                self._set_progress(38.0, "提取曲线")
                xs, ys, _line_idxs = self._get_input_xy_data()
                if not xs:
                    raise ValueError("未提取到数据行（StartOfData 后未发现连续 5 列数值数据）。")
                self._set_progress(52.0, "建立缓存")
                curve_cache = self._get_input_curve_cache()

                self._set_progress(72.0, "识别T1")
                T1_new, T2, meta = detect_T2_T1_precise(xs, ys, self.logger, debug=debug_enabled)
                self._bump_progress(12.0, "识别完成")

                T1_old = float(self.t1_var.get().strip()) if self.t1_var.get().strip() else T1_new
                self.t1_var.set(f"{T1_new:.6g}")
                self.t2_var.set(f"{T2:.6g}")
                self._warp_base_t1 = T1_new
                self._warp_base_t2 = T2

                self._set_progress(88.0, "计算H/积分")
                H1 = interpolate_curve_height(T1_new, curve_cache)
                H2 = interpolate_curve_height(T2, curve_cache)
                H = H2 - H1

                self._set_progress(94.0, "计算LG")
                mg_values = [round(0.45 + 0.01 * i, 2) for i in range(11)]
                lg_s = compute_lg_list(mg_values, H, logger=self.logger)
                info_block = (
                    f"梯度算法完成：\n"
                    f"    T1: {T1_old:.6g} → {T1_new:.6g} °C\n"
                    f"    T2: {T2:.6g} °C（最大峰）\n"
                    f"    H1: {format_height_um(H1)}\n"
                    f"    H2: {format_height_um(H2)}\n"
                    f"    H=H2-H1: {format_height_um(H)}"
                )
                self.logger.info(info_block)
                self.logger.info(lg_s)
                if debug_enabled:
                    self.logger.debug(f"precise_meta: {meta}")
                self._finish_progress("梯度算法完成")
            except Exception as e:
                self._reset_progress("就绪")
                self.logger.exception("梯度算法失败")
                messagebox.showerror("错误", f"梯度算法失败：\n{e}")

    def on_super_gradient_read(self):
        """超级梯度算法：仅更新 T1；T2 始终取最大峰。"""
        in_path = normalize_path_separators(self.input_path.get().strip())
        if not self._check_input_file_exists(in_path):
            return

        debug_enabled = bool(self.debug_var.get()) if hasattr(self, "debug_var") else False
        self.logger.info("==========")
        self.logger.info("开始超级梯度算法（仅更新T1，T2=最大峰不变）")
        self._set_progress(0.0, "超级梯度算法")

        with _scoped_ui_debug(self, debug_enabled):
            try:
                if self._cached_parsed is None:
                    self._set_progress(12.0, "读取文件")
                    self.logger.debug("调用 load_text_prefer_tajm()")
                    text, meta = load_text_prefer_tajm(in_path, self.logger)
                    src_used = meta.get("used")
                    rows = meta.get("rows")
                    if debug_enabled:
                        self.logger.debug(f"读取来源: {src_used}" + (f" rows={rows}" if src_used == "tajm" else ""))
                    self._cached_parsed = parse_lines(text)
                    self._invalidate_input_curve_cache()

                self._set_progress(38.0, "提取曲线")
                xs, ys, _line_idxs = self._get_input_xy_data()
                if not xs:
                    raise ValueError("未提取到数据行（StartOfData 后未发现连续 5 列数值数据）。")
                self._set_progress(52.0, "建立缓存")
                curve_cache = self._get_input_curve_cache()

                self._set_progress(72.0, "识别T1")
                T1_new, T2, meta = detect_T2_T1_super_gradient(xs, ys, self.logger, debug=debug_enabled)
                self._bump_progress(12.0, "识别完成")

                T1_old = float(self.t1_var.get().strip()) if self.t1_var.get().strip() else T1_new
                self.t1_var.set(f"{T1_new:.6g}")
                self.t2_var.set(f"{T2:.6g}")
                self._warp_base_t1 = T1_new
                self._warp_base_t2 = T2

                self._set_progress(88.0, "计算H/积分")
                H1 = interpolate_curve_height(T1_new, curve_cache)
                H2 = interpolate_curve_height(T2, curve_cache)
                H = H2 - H1

                self._set_progress(94.0, "计算LG")
                mg_values = [round(0.45 + 0.01 * i, 2) for i in range(11)]
                lg_s = compute_lg_list(mg_values, H, logger=self.logger)
                info_block = (
                    f"超级梯度算法完成：\n"
                    f"    T1: {T1_old:.6g} → {T1_new:.6g} °C\n"
                    f"    T2: {T2:.6g} °C（最大峰）\n"
                    f"    H1: {format_height_um(H1)}\n"
                    f"    H2: {format_height_um(H2)}\n"
                    f"    H=H2-H1: {format_height_um(H)}"
                )
                self.logger.info(info_block)
                self.logger.info(lg_s)
                if debug_enabled:
                    self.logger.debug(f"super_meta: {meta}")
                self._finish_progress("超级梯度算法完成")
            except Exception as e:
                self._reset_progress("就绪")
                self.logger.exception("超级梯度算法失败")
                messagebox.showerror("错误", f"超级梯度算法失败：\n{e}")

    def on_show_integral(self):
        """GUI 事件：把当前 T1~T2 区间的 H1/H2/H 与积分值写入 log。"""
        in_path = normalize_path_separators(self.input_path.get().strip())
        if not self._check_input_file_exists(in_path):
            return

        debug_enabled = bool(self.debug_var.get()) if hasattr(self, "debug_var") else False
        self._set_progress(0.0, "显示积分值")
        with _scoped_ui_debug(self, debug_enabled):
            try:
                self._set_progress(12.0, "准备数据")
                metrics = self._compute_current_interval_metrics(prefer_output=True)
                self._set_progress(55.0, "计算积分")
                msg = (
                    f"数据来源：{metrics['src_tag']}\n"
                    f"T1：{metrics['T1']:.5f} °C\n"
                    f"T2：{metrics['T2']:.5f} °C\n"
                    f"H1：{metrics['H1']:.5f} μm\n"
                    f"H2：{metrics['H2']:.5f} μm\n"
                    f"高度差H=H2-H1：{metrics['H']:.5f} μm\n"
                    f"T1~T2积分：{metrics['area']:.5f} μm·°C"
                )
                self._set_progress(82.0, "写入日志")
                self.logger.info("当前区间积分：\n" + msg)
                self._finish_progress("积分计算完成")
            except Exception:
                self._reset_progress("就绪")
                self.logger.exception("显示积分值失败")

    def on_execute(self):
        """GUI 事件：执行曲线调整并写出新文件。"""
        raw_in = self.input_path.get()
        raw_out = self.output_path.get()
        in_path = normalize_path_separators((raw_in or "").strip())
        out_path = normalize_path_separators((raw_out or "").strip())

        try:
            if (raw_in or "").strip() != in_path:
                self.logger.info(f"检测到输入路径包含异常字符（如换行）\n已自动清理\n现->[{in_path}]\n原->[{raw_in}]")
                self.input_path.set(in_path)
            if (raw_out or "").strip() != out_path:
                self.logger.info(f"检测到输出路径包含异常字符（如换行）\n已自动清理.\n现->[{out_path}]\n原->[{raw_out}]")
                self.output_path.set(out_path)
        except Exception:
            pass

        if not self._check_input_file_exists(in_path):
            return
        if not out_path:
            self.logger.error("输出文件路径为空：请先选择输出文件路径。")
            return

        debug_enabled = bool(self.debug_var.get())
        self._set_progress(0.0, "执行调整")
        if debug_enabled:
            self.logger.info("⚠️ DEBUG信息模式已开启：显示详细日志")
        t0 = time.perf_counter()
        tracemalloc_started = False
        if debug_enabled:
            try:
                tracemalloc.start()
                tracemalloc_started = True
            except Exception:
                tracemalloc_started = False

        try:
            with _scoped_ui_debug(self, debug_enabled):
                try:
                    T1n = float(self.t1_var.get().strip())
                    T2n = float(self.t2_var.get().strip())
                    mg = float(self.mg_var.get().strip())
                except ValueError:
                    self._reset_progress("就绪")
                    messagebox.showerror("错误", "T1/T2/mg 输入必须是数字。")
                    return

                self.logger.info(f"开始执行修改：T1={T1n}  T2={T2n}  mg={mg}")
                self.logger.debug("========== 开始执行修改 ==========")
                self.logger.debug(f"输入文件: {in_path}")
                self.logger.debug(f"输出文件: {out_path}")

                self._set_progress(8.0, "准备数据")
                if self._cached_parsed is None:
                    self._set_progress(10.0, "读取文件")
                    text, meta = load_text_prefer_tajm(in_path, self.logger)
                    self.logger.debug(
                        f"执行时读取来源: {meta.get('used')}"
                        + (f" rows={meta.get('rows')}" if meta.get('used') == 'tajm' else "")
                    )
                    self._set_progress(12.0, "解析文本")
                    self._cached_parsed = parse_lines(text)
                    self._invalidate_input_curve_cache()

                parsed = self._cached_parsed
                self._set_progress(14.0, "提取曲线")
                xy_data = self._get_input_xy_data()

                new_text, T1o, T2o = apply_warp(
                    parsed,
                    T1n=T1n,
                    T2n=T2n,
                    mg=mg,
                    logger=self.logger,
                    T1o_override=self._warp_base_t1,
                    T2o_override=self._warp_base_t2,
                    xy_data=xy_data,
                    progress_cb=lambda p, msg='': self._set_progress(15.0 + 0.70 * float(p), msg or "执行调整"),
                )

                self._set_progress(86.0, "准备写文件")
                self._bump_progress(2.0, "写入文件")
                try:
                    out_dir = os.path.dirname(out_path)
                    if out_dir and (not os.path.isdir(out_dir)):
                        os.makedirs(out_dir, exist_ok=True)
                except Exception:
                    pass
                write_utf16le_with_bom(out_path, new_text)

                self._set_progress(92.0, "写入完成")
                self._set_progress(95.0, "缓存结果")
                self._last_output_text = new_text
                try:
                    self._last_output_parsed = parse_lines(new_text)
                    self._invalidate_output_curve_cache()
                    self._last_output_xy_data = extract_xy_from_file(self._last_output_parsed, self.logger)
                    self._last_output_curve_cache = build_curve_cache(self._last_output_xy_data[0], self._last_output_xy_data[1])
                except Exception:
                    self._last_output_parsed = None
                    self._invalidate_output_curve_cache()
                self._last_run_mg = mg

                self.logger.info(f"✅ 修改完成：{out_path}")
                self._finish_progress("执行完成")
        except Exception as e:
            self._reset_progress("就绪")
            self.logger.exception("执行修改失败")
            messagebox.showerror("错误", f"执行修改失败：\n{e}")

        finally:
            if debug_enabled:
                elapsed = time.perf_counter() - t0
                mem_info = ""
                if tracemalloc_started:
                    try:
                        cur, peak = tracemalloc.get_traced_memory()
                        mem_info = f" | 内存(Tracemalloc): current={cur/1024:.1f}KB, peak={peak/1024:.1f}KB"
                    except Exception:
                        pass
                    try:
                        tracemalloc.stop()
                    except Exception:
                        pass
                self.logger.info(f"⚠️ DEBUG指标: 执行耗时={elapsed:.3f}s{mem_info}")

    def on_plot(self):
        """GUI 事件：打开/刷新绘图窗口。
        
        绘图数据来源：
            - 优先使用最近一次“执行调整”的结果（更符合用户看到的曲线）；
            - 若尚未执行调整，则绘制原始输入文件。
        
        功能：
            - 绘制曲线与网格；
            - 标注 T1/T2 与高度差；
            - 支持导出 TIFF 与“仿生输出”。
        """
        
        in_path = normalize_path_separators(self.input_path.get().strip())
        out_path = normalize_path_separators(self.output_path.get().strip())
        if not self._check_input_file_exists(in_path):
            return

        # 仅对本次“开始绘图”流程生效：执行前读取一次复选框状态
        debug_enabled = bool(self.debug_var.get())
        if debug_enabled:
            self.logger.info("⚠️ DEBUG信息模式已开启：显示详细日志")

        with _scoped_ui_debug(self, debug_enabled):
            try:
                self._set_progress(6.0, "准备绘图")
                # 选择数据源：优先使用最近一次“执行修改”的结果；否则使用原始输入文件
                self._set_progress(14.0, "加载曲线")
                src_tag, parsed, xs, ys, curve_cache = self._get_active_curve_bundle(prefer_output=True)
                mg_for_title = self._last_run_mg if src_tag == "修改后" else None
                self._bump_progress(8.0, "曲线就绪")

                if not xs or not ys:
                    raise ValueError("未提取到绘图数据（请确认 StartOfData 后存在 5 列数据，且第2/3列为温度/高度）。")

                # 读取当前 UI 的 T1/T2（用于标注）
                self._set_progress(24.0, "读取T1/T2")

                try:
                    t1 = float(self.t1_var.get().strip())
                    t2 = float(self.t2_var.get().strip())
                except Exception:
                    messagebox.showwarning("提示", "请先正确设置 T1/T2。")
                    return

                # INFO：绘图参数汇总（便于复核；路径会自动标红）
                mg_for_log = self._format_mg_for_note(self.mg_var.get())
                self.logger.info(
                    "绘图参数：\n"
                    f"    数据来源: {src_tag}\n"
                    f"    输入文件位置: {in_path}\n"
                    f"    输出文件位置: {out_path}\n"
                    f"    T1={t1:.6g} °C, T2={t2:.6g} °C, mg={mg_for_log} mg"
                )

                # subtitle 质量：优先使用最近一次执行修改的 mg；否则用当前输入框 mg
                mg_val = None
                if mg_for_title is not None:
                    mg_val = mg_for_title
                else:
                    try:
                        mg_val = float(self.mg_var.get().strip())
                    except Exception:
                        mg_val = None


                # 初始化绘图窗口 mg 输入框（仅用于图中备注，不影响主界面 mg）
                if mg_val is not None:
                    mg_raw = self.mg_var.get().strip()
                    self._plot_mg_var.set(mg_raw if mg_raw else f"{mg_val:.2f}")  # 绘图窗口 mg(标注) 输入框变量（仅影响图中文字）
                else:
                    self._plot_mg_var.set("")  # 绘图窗口 mg(标注) 输入框变量（仅影响图中文字）

                self._set_progress(34.0, "计算坐标范围")
                # ---- 计算 y 轴范围（新规则）----
                y_min_data = float(min(ys))
                y_max_data = float(max(ys))

                # 基础下限：若最小值 > -200 μm，则下限固定为 -200；否则向下取整到 500 的整数倍
                if y_min_data > -200.0:
                    y0_base = -200.0
                else:
                    y0_base = math.floor(y_min_data / 500.0) * 500.0

                # 基础上限：向上取整到 500 的整数倍
                y1_base = math.ceil(y_max_data / 500.0) * 500.0
                if y1_base < 0:
                    y1_base = 0.0
                if y1_base <= y0_base:
                    y1_base = y0_base + 500.0

                # 实际绘图范围（会因标注超框而动态调整）
                y0_plot = float(y0_base)
                y1_plot = float(y1_base)

                # 找到 T1/T2 对应的点（用于判断标注是否会超框）
                # v215：直接用插值后的精确曲线位置，避免“最近点”导致标点偏左/偏右。
                x1_pt = float(t1)
                x2_pt = float(t2)
                y1_pt = interpolate_curve_height(x1_pt, curve_cache)
                y2_pt = interpolate_curve_height(x2_pt, curve_cache)

                def _ann_margin(cur_y0: float, cur_y1: float) -> float:
                    # 用于估计“文字标注”在 y 方向可能占用的空间（经验值）
                    """估算标注文字在 y 方向占用的空间（经验值）。
                    
                    用途：
                        绘图时需要判断 T1/T2 标注是否会超出坐标轴范围，
                        通过该函数给出一个与 y 轴范围相关的 margin。
                    """
                    
                    yr = max(1.0, cur_y1 - cur_y0)
                    return max(80.0, yr * 0.04)

                ann_margin = _ann_margin(y0_plot, y1_plot)

                # 若 T2 温度标注会超出框，则上限抬高 200（标注刻度仍以 y1_base 为准）
                if y2_pt + ann_margin > y1_plot:
                    y1_plot += 200.0
                    ann_margin = _ann_margin(y0_plot, y1_plot)

                # 若 T1 温度标注（点下方）会超出框：y 轴下限每次额外降低 100，直到不超出
                while y1_pt - ann_margin < y0_plot:
                    y0_plot -= 100.0
                    ann_margin = _ann_margin(y0_plot, y1_plot)

                if y1_plot <= y0_plot:
                    y1_plot = y0_plot + 500.0

                # y 轴刻度：
                # - 若下限 > -500：标注“当前下限、0、500、1000...”
                # - 若下限 <= -500：在上述基础上额外增加 -500
                y_ticks_major = [float(y0_plot), 0.0]
                if y0_plot < -500.0 - 1e-9:
                    y_ticks_major.append(-500.0)
                y_ticks_major.extend([float(v) for v in range(500, int(y1_base) + 1, 500)])
                # 过滤并去重排序
                y_ticks_major = sorted({v for v in y_ticks_major if y0_plot - 1e-9 <= v <= y1_base + 1e-9})

                # 小刻度：每 100 一个（覆盖绘图范围，便于虚线背景/小刻度显示）
                y_minor_start = int(math.floor(y0_plot / 100.0) * 100)
                y_minor_end = int(math.ceil(y1_plot / 100.0) * 100)
                y_ticks_minor = list(range(y_minor_start, y_minor_end + 1, 100))
# ---- 创建/复用绘图窗口 ----
                if self._plot_win is not None and self._plot_win.winfo_exists():  # 绘图窗口（Toplevel）引用，用于复用/避免重复创建
                    win = self._plot_win  # 绘图窗口（Toplevel）引用，用于复用/避免重复创建
                    # 清理旧 canvas
                    if self._plot_canvas is not None:  # Matplotlib 画布（FigureCanvasTkAgg）引用
                        try:self._plot_canvas.get_tk_widget().destroy()  # Matplotlib 画布（FigureCanvasTkAgg）引用
                        except Exception:pass
                        self._plot_canvas = None  # Matplotlib 画布（FigureCanvasTkAgg）引用
                else:
                    win = tk.Toplevel(self.root)
                    win.title("TMA - 绘图")
                    place_window_bottom_right(win, 1000, 650)
                    self._plot_win = win  # 绘图窗口（Toplevel）引用，用于复用/避免重复创建

                                # 窗口定位：右下角（每次绘图都重置位置）
                place_window_bottom_right(win, 1000, 650)

# 工具栏（导出 TIFF）
                self._set_progress(48.0, "准备窗口")
                if self._plot_toolbar is not None:  # 绘图窗口工具栏 Frame（放导出按钮等）
                    try:
                        self._plot_toolbar.destroy()  # 绘图窗口工具栏 Frame（放导出按钮等）
                    except Exception:
                        pass
                    self._plot_toolbar = None  # 绘图窗口工具栏 Frame（放导出按钮等）
                toolbar = ttk.Frame(win)
                toolbar.pack(fill='x', padx=6, pady=6)
                self._plot_toolbar = toolbar  # 绘图窗口工具栏 Frame（放导出按钮等）

                def _save_plot_tiff(universal: bool = False, show_message: bool = True, log_label: Optional[str] = None) -> str:
                    """保存当前绘图为 TIFF，并返回绝对路径。"""
                    try:
                        _refresh_method_note()
                    except Exception:
                        pass

                    if self._plot_fig is None:
                        raise RuntimeError('未找到可导出的图像。')

                    base = os.path.splitext(os.path.basename(in_path))[0]
                    out_dir = _current_output_dir()
                    file_name = (('Universal - ' + base) if universal else base) + '.tif'
                    tif_path = join_keep_style(out_dir, file_name)

                    fig = self._plot_fig
                    from io import BytesIO
                    from PIL import Image, TiffImagePlugin
                    old_size = tuple(fig.get_size_inches())

                    try:
                        fig.set_size_inches(12.8, 7.2, forward=True)
                        buf = BytesIO()
                        fig.savefig(buf, format='tiff', dpi=300)
                        buf.seek(0)
                    finally:
                        try:
                            fig.set_size_inches(old_size[0], old_size[1], forward=True)
                            if self._plot_canvas is not None:
                                try:
                                    self._plot_canvas.draw_idle()
                                except Exception:
                                    pass
                        except Exception:
                            pass

                    img = Image.open(buf)
                    tiffinfo = TiffImagePlugin.ImageFileDirectory_v2()
                    tiffinfo[315] = 'TMAmax'
                    dt_str = datetime.datetime.now().astimezone().strftime('%Y:%m:%d %H:%M:%S')
                    tiffinfo[306] = dt_str
                    tiffinfo[282] = TiffImagePlugin.IFDRational(300, 1)
                    tiffinfo[283] = TiffImagePlugin.IFDRational(300, 1)
                    tiffinfo[296] = 2
                    img.save(
                        tif_path,
                        compression='tiff_adobe_deflate',
                        tiffinfo=tiffinfo,
                        dpi=(300, 300),
                    )

                    label = log_label or ('已生成仿生TIFF图' if universal else '已生成TIFF图')
                    self.logger.info(f'{label}: {tif_path}')
                    if show_message:
                        messagebox.showinfo('完成', f'{label}：\n{tif_path}')
                    return os.path.abspath(tif_path)

                def _export_tiff():
                    try:
                        _save_plot_tiff(universal=False, show_message=True, log_label='已生成TIFF图')
                    except Exception as ee:
                        self.logger.exception('生成TIFF失败')
                        messagebox.showerror('错误', f'生成TIFF失败：\n{ee}')

                def _export_tiff_universal():
                    try:
                        _save_plot_tiff(universal=True, show_message=False, log_label='已生成仿生TIFF图')
                    except Exception as ee:
                        self.logger.exception('生成仿生TIFF失败')
                        messagebox.showerror('错误', f'生成仿生TIFF失败：\n{ee}')

                def _record_plot_data():
                    try:
                        self._set_progress(0.0, '录入数据')
                        metrics = self._compute_current_interval_metrics(prefer_output=True)
                        self._set_progress(32.0, '导出TMA图')
                        tif_path = _save_plot_tiff(universal=False, show_message=False, log_label='已生成TMA图')

                        batch_no, sort_key = extract_batch_info_any(in_path)
                        if not batch_no:
                            raise ValueError('未能从当前文件名中识别连续的 10 位或 8 位批次号。')

                        csv_path = resolve_sp_csv_path()
                        rows, headers = _read_csv_rows_auto(csv_path)
                        headers = _normalize_sp_headers(headers)
                        tma_cols = _pick_tma_path_headers(headers)

                        mg_text = self._format_mg_for_note((self._plot_mg_var.get() or self.mg_var.get() or '').strip())
                        row_index = None
                        for i, row in enumerate(rows):
                            if str((row or {}).get('批次号', '') or '').strip() == batch_no:
                                row_index = i
                                break

                        row = _ensure_row_headers(rows[row_index], headers) if row_index is not None else {h: '' for h in headers}
                        display_metrics = build_plot_display_metrics(metrics)

                        row['批次号'] = batch_no
                        row['T1'] = display_metrics['T1']
                        row['T2'] = display_metrics['T2']
                        row['M'] = mg_text
                        row['H'] = display_metrics['H']
                        if '面积' in headers:
                            row['面积'] = f"{metrics['area']:.5f}"
                        if sort_key:
                            row['排列号'] = sort_key
                        for col in tma_cols:
                            row[col] = normalize_path_separators(str(os.path.abspath(tif_path)))

                        if row_index is None:
                            rows.append(row)
                        else:
                            rows[row_index] = row

                        rows = _sort_sp_rows([_ensure_row_headers(r, headers) for r in rows])
                        self._set_progress(72.0, '写入CSV')
                        _write_sp_csv(csv_path, rows, headers)

                        self.logger.info(
                            '录入数据完成：\n'
                            f'    批次号: {batch_no}\n'
                            f'    T1={display_metrics["T1"]} °C\n'
                            f'    T2={display_metrics["T2"]} °C\n'
                            f'    M={mg_text}\n'
                            f'    H={display_metrics["H"]} μm\n'
                            f'    TMA图位置: {tif_path}\n'
                            f'    sp.csv: {csv_path}'
                        )
                        self._finish_progress('录入完成')
                    except Exception:
                        self._reset_progress('就绪')
                        self.logger.exception('录入数据失败')

                ttk.Button(toolbar, text='生成TIFF图(.tif)', command=_export_tiff).pack(side='left')
                ttk.Button(toolbar, text='仿生输出', command=_export_tiff_universal).pack(side='left', padx=(8, 0))
                ttk.Button(toolbar, text='显示积分值', command=self.on_show_integral).pack(side='left', padx=(8, 0))
                ttk.Button(toolbar, text='录入数据', command=_record_plot_data).pack(side='left', padx=(8, 0))

                # 仅用于绘图备注的 mg（不会修改主界面 mg）
                ttk.Label(toolbar, text='mg(标注):').pack(side='left', padx=(16, 4))
                mg_entry = ttk.Entry(toolbar, textvariable=self._plot_mg_var, width=8)  # 绘图窗口 mg(标注) 输入框变量（仅影响图中文字）
                mg_entry.pack(side='left')

                # 第二行：出图路径设置
                pathbar = ttk.Frame(win)
                pathbar.pack(fill="x", padx=6, pady=(0, 6))

                # 记录上一次已写入日志的出图路径，避免焦点事件导致重复刷屏
                _last_export_path_logged = {"v": (self.export_newpath_var.get() or "").strip()}

                # 当前实际输出目录（考虑“启用新路径”和目录是否存在）
                def _current_output_dir() -> str:
                    """返回当前实际会输出到的目录（考虑“启用新路径”和目录是否存在）。"""
                    in_path_now = (self.input_path.get() or "").strip()
                    base_dir = normalize_path_separators(os.path.dirname(in_path_now)) if in_path_now else normalize_path_separators(os.getcwd())
                    if bool(self.export_use_newpath_var.get()):
                        cand = (self.export_newpath_var.get() or "").strip()
                        if cand and os.path.isdir(cand):
                            return cand
                    return base_dir

                def _log_current_output_dir(unchanged: bool = False):
                    """在日志框中输出“当前实际出图目录”。
                    
                    参数：
                        unchanged: True 时会在日志中追加“（未更改）”，用于提示用户当前仍使用默认目录。
                    """
                    
                    out_dir = _current_output_dir()
                    msg = f"当前输出路径: {out_dir}"
                    if unchanged:
                        msg += "（未更改）"
                    self.logger.info(msg)

                def _log_export_path_if_changed(new_val: str):
                    """当出图路径发生变化时才写日志，避免 FocusOut/Return 等事件导致刷屏。"""
                    
                    p = (new_val or "").strip()
                    if p == _last_export_path_logged.get("v", ""):
                        return
                    _last_export_path_logged["v"] = p
                    if bool(self.export_use_newpath_var.get()):
                        _log_current_output_dir(unchanged=False)
                    else:
                        _log_current_output_dir(unchanged=True)

                def _on_toggle_newpath():
                    """切换“启用新路径”复选框后的回调：更新日志并刷新当前输出目录提示。"""
                    
                    self.logger.info(
                        f"启用新路径: {'开启' if self.export_use_newpath_var.get() else '关闭'}"
                    )
                    _log_current_output_dir(unchanged=False)

                ttk.Checkbutton(
                    pathbar,
                    text="启用新路径",
                    variable=self.export_use_newpath_var,
                    command=_on_toggle_newpath,
                ).pack(side="left")

                base_paths = [
                    r"\\192.168.0.105\TMAresult\LS",
                    r"\\192.168.0.105\TMAresult\三明样品",
                    r"\\192.168.0.105\TMAresult\BC",
                ]
                desktop_path = get_desktop_path()

                export_path_combo = ttk.Combobox(
                    pathbar,
                    textvariable=self.export_newpath_var,
                    width=60,
                    state='normal',
                )
                export_path_combo.pack(side='left', padx=8, fill='x', expand=True)

                def _refresh_export_path_choices():
                    """刷新出图路径下拉框的可选项。
                    
                    来源：
                        - 固定的 base_paths
                        - 桌面路径
                        - 用户最近手动输入的路径（最多保留 3 个）
                    """
                    
                    values: List[str] = []
                    for p in base_paths + [desktop_path] + getattr(self, '_recent_export_paths', []):
                        if p and p not in values:
                            values.append(p)
                    export_path_combo['values'] = values

                def _remember_export_path(p: str):
                    """把用户输入的出图路径加入“最近路径”列表（LRU，最多 3 个），并刷新下拉框选项。"""
                    
                    p = (p or '').strip()
                    if not p:
                        return
                    if p in base_paths or p == desktop_path:
                        return
                    if not hasattr(self, '_recent_export_paths'):
                        self._recent_export_paths = []
                    if p in self._recent_export_paths:
                        self._recent_export_paths.remove(p)
                    self._recent_export_paths.insert(0, p)
                    del self._recent_export_paths[3:]
                    _refresh_export_path_choices()

                _refresh_export_path_choices()
                export_path_combo.bind(
                    '<<ComboboxSelected>>',
                    lambda _e: (
                        _remember_export_path(self.export_newpath_var.get()),
                        _log_export_path_if_changed(self.export_newpath_var.get()),
                    ),
                )
                export_path_combo.bind(
                    '<Return>',
                    lambda _e: (
                        _remember_export_path(self.export_newpath_var.get()),
                        _log_export_path_if_changed(self.export_newpath_var.get()),
                    ),
                )
                export_path_combo.bind(
                    '<FocusOut>',
                    lambda _e: (
                        _remember_export_path(self.export_newpath_var.get()),
                        _log_export_path_if_changed(self.export_newpath_var.get()),
                    ),
                )

                def _choose_export_dir():
                    """弹出文件夹选择框，让用户选择出图目录，并更新下拉框与日志。"""
                    
                    try:
                        d = filedialog.askdirectory(title='选择出图文件夹')
                    except Exception:
                        d = ''
                    if d:
                        self.export_newpath_var.set(d)
                        _remember_export_path(d)
                        _last_export_path_logged["v"] = d
                        _log_current_output_dir(unchanged=(not bool(self.export_use_newpath_var.get())))

                ttk.Button(pathbar, text='调整出图路径', command=_choose_export_dir).pack(side='left', padx=(8, 0))

                self._set_progress(58.0, "创建图形")

                # ---- 绘图 ----
                fig = Figure(figsize=(12.8, 7.2), dpi=100)
                ax = fig.add_subplot(111)
                self._plot_fig = fig  # Matplotlib Figure 引用（用于导出/刷新）

                self._set_progress(66.0, "绘制曲线")
                # 曲线（线宽适中）- matplotlib linewidth 单位为 points
                ax.plot(xs, ys, color="black", linewidth=1.5)

                # x 轴范围 0~300（带标尺：大刻度50，小刻度10）
                x_left = 0.0
                x_right = 300.0
                ax.set_xlim(x_left, x_right)
                ax.xaxis.set_major_locator(MultipleLocator(50))
                ax.xaxis.set_minor_locator(MultipleLocator(10))
                ax.xaxis.set_minor_formatter(NullFormatter())
                ax.set_xlabel("温度(°C)", fontsize=12)
                ax.tick_params(axis='x', which='major', length=6)
                ax.tick_params(axis='x', which='minor', length=3)

                # y 轴：500 的倍数（大刻度500，小刻度100）
                ax.set_ylim(y0_plot, y1_plot)

                # 背景网格：x 每隔 10、y 每隔 100 画细虚线（作为背景）
                for gx in range(0, 301, 10):
                    ax.axvline(gx, linestyle="--", linewidth=0.4, color="#999999", alpha=0.35, zorder=0)
                y_grid_start = int(math.floor(y0_plot / 100.0)) * 100
                y_grid_end = int(math.ceil(y1_plot / 100.0)) * 100
                for gy in range(y_grid_start, y_grid_end + 1, 100):
                    ax.axhline(gy, linestyle="--", linewidth=0.4, color="#999999", alpha=0.35, zorder=0)
                ax.yaxis.set_major_locator(FixedLocator(y_ticks_major))

                ax.yaxis.set_minor_locator(FixedLocator(y_ticks_minor))

                ax.yaxis.set_minor_formatter(NullFormatter())
                ax.set_ylabel("尺寸变化(μm)", fontsize=12)
                ax.tick_params(axis='y', which='major', length=6)
                ax.tick_params(axis='y', which='minor', length=3)


                # 背景：500×500 正方形（(0,0)~(500,500)），最细虚线

                try:

                    ax.plot([0, 500, 500, 0, 0], [0, 0, 500, 500, 0], linestyle=(0, (1, 3)), linewidth=0.5, color='0.8', zorder=0)

                except Exception:

                    pass


                self._set_progress(74.0, "绘制坐标轴")
                # 标题/副标题
                fig.suptitle("TMA", fontsize=16, fontweight="bold")

                def _get_plot_mg_text() -> str:
                    """读取绘图窗口中的 mg(标注) 字符串，并尽量保持用户输入格式。
                    
                    说明：
                        - 该 mg 仅影响图中“方法日志”的文字，不会修改主界面 mg。
                    """
                    
                    s = (self._plot_mg_var.get() or '').strip()  # 绘图窗口 mg(标注) 输入框变量（仅影响图中文字）
                    if not s:
                        return 'x'
                    # 保留用户输入的小数位（例如 0.50 不要变成 0.5）
                    try:
                        float(s)
                    except Exception:
                        return s
                    # 若用户输入为整数形式（如 1），则统一补两位小数
                    if ('.' not in s) and ('e' not in s.lower()):
                        return f"{float(s):.2f}"
                    return s


                def _build_method_note() -> str:
                    """构建绘图左上角的“方法日志”备注文本（包含 mg）。"""
                    
                    mg_s = _get_plot_mg_text()
                    a = "方法日志：30°C平衡，施加 0.06 N；\n"
                    b = " " * 17 + "20°C/min加热至 250°C；\n"
                    c = f"称取质量：{mg_s}mg。"
                    d = a + b + c
                    return d

                # 副标题隐藏，方法日志作为绘图备注显示

                # 标注信息（INFO）
                self.logger.info("开始绘图")
                self.logger.info(f"{src_tag}数据: 点数={len(xs)}")

                self._set_progress(82.0, "绘制标注")
                # T1/T2 标注：用“黑色十字短线”与曲线相交表示点
                y_range = (y1_plot - y0_plot)
                tick_half_y = max(10.0, y_range * 0.02)   # 竖向半长（数据坐标）
                tick_half_x = 2.0                         # 横向半长（℃）
                tick_lw = 1.2

                def _draw_cross(xc: float, yc: float):
                    """在 (x,y) 数据点处绘制一个小十字，用于视觉上标记 T1/T2 点。"""
                    
                    x_left = max(0.0, xc - tick_half_x)
                    x_right = min(300.0, xc + tick_half_x)
                    ax.vlines(xc, yc - tick_half_y, yc + tick_half_y, colors="black", linewidth=tick_lw)
                    ax.hlines(yc, x_left, x_right, colors="black", linewidth=tick_lw)

                if x1_pt is not None and y1_pt is not None:
                    _draw_cross(x1_pt, y1_pt)
                    ax.annotate(
                        f"{format_plot_temp_c(x1_pt)}℃", (x1_pt, y1_pt),
                        xytext=(0, -10), textcoords="offset points",
                        ha="center", va="top", fontsize=12, color="black"
                    )

                if x2_pt is not None and y2_pt is not None:
                    _draw_cross(x2_pt, y2_pt)
                    ax.annotate(
                        f"{format_plot_temp_c(x2_pt)}℃", (x2_pt, y2_pt),
                        xytext=(0, 10), textcoords="offset points",
                        ha="center", va="bottom", fontsize=12, color="black"
                    )

                # 高度差：T1 点向右延出平行线（到 T2 的 x 位置），箭头指向 T1 延长线与 T2 点
                if (x1_pt is not None and y1_pt is not None and x2_pt is not None and y2_pt is not None):
                    # 仅延出 T1 的水平线：从 T1 到 T2 的 x
                    ax.plot([x1_pt, x2_pt], [y1_pt, y1_pt], color="black", lw=0.8)

                    # 双向箭头：在 T2 的 x 位置，从 T1 水平线(y1) 到 T2 点(y2)
                    ax.annotate(
                        "",
                        xy=(x2_pt, y2_pt),
                        xytext=(x2_pt, y1_pt),
                        arrowprops=dict(arrowstyle="<->", color="black", linewidth=1.0, shrinkA=0, shrinkB=0),
                    )
                    # 只标注“多少 μm”（避免与曲线重叠：取 T2 右侧一点，并把文字的左下角放在曲线之上）
                    dh = abs(y2_pt - y1_pt)

                    def _interp_y(xq: float) -> float:
                        """在给定 x（温度）处对曲线做一次线性插值，返回对应 y。"""
                        return interpolate_curve_height(xq, curve_cache)

                    x_text = min(300.0, x2_pt + 15.0)
                    y_curve = _interp_y(x_text)
                    margin = max(15.0, (y1_plot - y0_plot) * 0.03)
                    y_text = y_curve + margin
                    y_text = min(y_text, y1_plot - margin * 0.2) # 防止顶到上边界

                    ax.text(
                        x_text, y_text,
                        f"{format_height_um(dh)} μm",
                        fontsize=12, ha="left", va="bottom", color="black"
                    )
                self._set_progress(88.0, "渲染图形")
                canvas = FigureCanvasTkAgg(fig, master=win)
                # 绘图完成后添加“方法日志”备注：放置在左上角，且尽量避免与曲线重叠
                x_left_final = x_left
                method_artist = None
                for _ in range(20):
                    ax.set_xlim(x_left_final, x_right)
                    if method_artist is not None:
                        try:
                            method_artist.remove()
                        except Exception:
                            pass
                    method_artist = ax.text(
                        x_left_final + 10,
                        y1_plot - 100,
                        _build_method_note(),
                        ha='left',
                        va='top',
                        fontsize=12,
                    )
                    canvas.draw()
                    overlap = False
                    try:
                        renderer = canvas.get_renderer()
                        bbox = method_artist.get_window_extent(renderer=renderer)
                        pts = ax.transData.transform(list(zip(xs, ys)))
                        overlap = any((bbox.x0 <= px <= bbox.x1 and bbox.y0 <= py <= bbox.y1) for px, py in pts)
                    except Exception:
                        overlap = False
                    if not overlap:
                        break
                    x_left_final -= 20.0

                # 若向左扩展了 x 轴，补齐负区间的背景虚线（每 10°C 一条）
                if x_left_final < 0:
                    gx_start = int(math.floor(x_left_final / 10.0)) * 10
                    for gx in range(gx_start, 0, 10):
                        ax.axvline(gx, linestyle=(0, (2, 2)), linewidth=0.5, color='0.8', zorder=0)

                # 右下角版本号
                fig.text(0.99, 0.01, VERSION, ha='right', va='bottom', fontsize=10)
                
                # 缓存绘图对象（用于 mg(标注) 修改后刷新备注）
                self._plot_method_artist = method_artist  # 绘图左上角“方法日志”文本对象（用于动态刷新 mg）
                self._plot_note_x_left = x_left_final  # 为避免备注遮挡曲线，左上角备注会向左挪：该变量记录 x 轴左边界
                self._plot_ax = ax  # 绘图坐标轴 Axes 引用（用于刷新标注）

                def _refresh_method_note(_evt=None):
                    """刷新绘图备注（方法日志中的 mg），并尽量避免与曲线/点重叠。"""
                    try:
                        if self._plot_ax is None or self._plot_method_artist is None:  # 绘图坐标轴 Axes 引用（用于刷新标注）
                            return
                        self._plot_method_artist.set_text(_build_method_note())  # 绘图左上角“方法日志”文本对象（用于动态刷新 mg）

                        # 如文字与点区域重叠，则继续向左扩展 x 轴
                        xlf = self._plot_note_x_left if self._plot_note_x_left is not None else x_left_final  # 为避免备注遮挡曲线，左上角备注会向左挪：该变量记录 x 轴左边界
                        for _ in range(30):
                            ax.set_xlim(xlf, x_right)
                            self._plot_method_artist.set_position((xlf + 10, y1_plot - 100))  # 绘图左上角“方法日志”文本对象（用于动态刷新 mg）
                            fig.canvas.draw()
                            bbox = self._plot_method_artist.get_window_extent(renderer=fig.canvas.get_renderer())  # 绘图左上角“方法日志”文本对象（用于动态刷新 mg）
                            overlap = False
                            for _x, _y in [(x1_pt, y1_pt), (x2_pt, y2_pt)]:
                                if _x is None or _y is None:
                                    continue
                                px, py = ax.transData.transform((_x, _y))
                                if bbox.contains(px, py):
                                    overlap = True
                                    break
                            if not overlap:
                                break
                            xlf -= 20
                        self._plot_note_x_left = xlf  # 为避免备注遮挡曲线，左上角备注会向左挪：该变量记录 x 轴左边界

                        # 若向左扩展到负数区域，补画背景虚线
                        if xlf < 0:
                            start_gx = int(math.floor(xlf / 10.0) * 10)
                            for gx in range(start_gx, 0, 10):
                                ax.axvline(gx, linestyle='--', linewidth=0.4, alpha=0.18, zorder=0)

                        fig.canvas.draw_idle()
                    except Exception:
                        pass

                # mg 输入框：回车/失焦时刷新备注
                try:
                    mg_entry.bind('<Return>', _refresh_method_note)
                    mg_entry.bind('<FocusOut>', _refresh_method_note)
                except Exception:
                    pass

                self._set_progress(94.0, "完成绘制")
                # 最终再 draw 一次，确保布局刷新
                canvas.draw()
                canvas.get_tk_widget().pack(fill="both", expand=True)
                self._plot_canvas = canvas  # Matplotlib 画布（FigureCanvasTkAgg）引用
                self._finish_progress("绘图完成")
            except Exception as e:
                self._reset_progress("就绪")
                self.logger.exception("绘图失败")
                messagebox.showerror("错误", f"绘图失败：\n{e}")


    def _format_mg_for_note(self, mg_s: str) -> str:
        """用于绘图备注的 mg 字符串格式：
        - 若可解析为数值：尽量保留两位小数（例如 0.50）
        - 否则：原样返回（去首尾空白）
        """
        s = (mg_s or "").strip()
        if not s:
            return "0.50"

        # 指数形式：尽量按数值格式化
        if "e" in s.lower():
            try:
                return f"{float(s):.2f}"
            except Exception:
                return s

        # 普通小数
        if "." in s:
            frac = s.split(".", 1)[1]
            # 只有 1 位小数：补足到 2 位（0.5 -> 0.50）
            if len(frac) == 1:
                try:
                    return f"{float(s):.2f}"
                except Exception:
                    return s
            # >=2 位小数：尊重用户输入（不强制四舍五入）
            return s

        # 整数：补足到两位
        try:
            return f"{float(s):.2f}"
        except Exception:
            return s

def main():
    """程序入口：创建 Tk 根窗口并启动主循环。"""
    
    root = tk.Tk()
    App(root)
    place_window_top_right(root, 600, 450)
    root.mainloop()


if __name__ == "__main__":
    main()
