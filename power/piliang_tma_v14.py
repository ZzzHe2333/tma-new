# -*- coding: utf-8 -*-
# 第十四代 TMA 批量处理脚本；文件尾号标识符：V14；内置算法标识：V233。
# 下面这些变量集中管理界面显示、出图角标、文件版本标识，后续改名/升版优先改这里。
GENERATION = 14
GENERATION_LABEL = "第十四代"
FILE_VERSION_TAG = "V14"
ALGORITHM_VERSION = "V233"
ALGORITHM_LABEL = "内置V233算法（T1寻找算法）"
ALGORITHM_SOURCE = "单批生成混批一件神器（1）.py"

# 兼容旧代码变量名
VISION = GENERATION
VERSION = ALGORITHM_VERSION

f"""
TMA 批量处理脚本 {FILE_VERSION_TAG}（{GENERATION_LABEL}）
─────────────────────────────────────────────────────────────────────
· 原神风浅色 GUI（米白 / 金色 / 青蓝配色）
· 带时间戳 + 彩色等级的日志面板（队列批量刷新，高性能）
· 内嵌结果表格（实时刷新）
· 文件列表支持单条删除
· 可自定义图片输出目录（默认 ./tp）
· 启动时显示图片 Splash（内置角色图 + 批量TMA处理神器）
· 算法内置：不再从 tma_super_max_v219.py 导入识别函数
· T1：使用 V233 软起发脚尖识别算法
· T2：保持固定算法，不做额外改动
· V13：在 V12 功能基础上定版保存；标题可切换单/多线程，完成后打印看板娘文字图
· V14：仅升级主界面 UI 质感与交互反馈；加载界面、算法和处理逻辑不变
"""



import os
import base64
import sys
import re
import csv
import math
import logging
import datetime
import threading
import concurrent.futures
import traceback
import time
import random
import struct
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
from matplotlib.ticker import MultipleLocator, NullFormatter, FixedLocator
import numpy as np

matplotlib.rcParams["font.family"] = "sans-serif"
matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei", "SimHei", "SimSun", "Arial Unicode MS", "DejaVu Sans"
]
matplotlib.rcParams["axes.unicode_minus"] = False

# ── 运行基准目录（源码 / EXE 双模式自动切换）────────────────────────
# PyInstaller 打包后 sys.frozen=True，sys.executable 是 exe 本体路径。
# sys._MEIPASS 是解压临时目录（只放 .pyd/.dll），不适合存用户数据。
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SCRIPT_DIR = BASE_DIR          # 兼容旧代码中对 SCRIPT_DIR 的引用

# ── 内置核心算法（不再 import tma_super_max_v219）────────────────────────
# 算法标识：V233。
# T1：采用《单批生成混批一件神器（1）.py》的 V233 寻找算法；
# T2：沿用固定 T2 逻辑，不做额外最高点校验或升级处理。

# --- format_height_um ---
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

# --- format_plot_temp_c ---
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

# --- _tajm_find_header_end ---
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

# --- _tajm_find_data_start_by_first_time ---
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

# --- _tajm_parse_rows ---
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

# --- try_tajm_decrypt_to_text ---
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

# --- load_text_prefer_tajm ---
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

# --- START_TEMP_FOR_T1 ---
START_TEMP_FOR_T1 = 60.0   # 你说“数据开始(60℃附近)”，默认从>=60开始找T1

# --- FALLBACK_TEMP_MIN ---
FALLBACK_TEMP_MIN = 40.0

# --- FALLBACK_TEMP_MAX ---
FALLBACK_TEMP_MAX = 400.0

# --- FLOAT_FIND_RE ---
FLOAT_FIND_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")

# --- ParsedLine ---
@dataclass
class ParsedLine:
    raw: str
    nums: List[float]               # 本行所有“数字token”
    spans: List[Tuple[int, int]]    # 每个数字token在原行中的 (start,end)

# --- read_text_auto ---
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

# --- parse_lines ---
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

# --- extract_xy_from_file ---
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

# --- _robust_mad ---
def _robust_mad(arr: np.ndarray) -> float:
    """返回 MAD（乘 1.4826 后的稳健标准差近似）。"""
    a = np.asarray(arr, dtype=float)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return 0.0
    med = float(np.median(a))
    mad = float(np.median(np.abs(a - med)))
    return 1.4826 * mad

# --- _gaussian_smooth_1d ---
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

# --- _find_local_extrema ---
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

# --- _prepare_xy_for_detection ---
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

# --- _estimate_step ---
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

# --- _fine_search_extreme ---
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

# --- _refine_triplet_onset ---
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

# --- _refine_early_foot_onset ---
def _refine_early_foot_onset(
    xp: np.ndarray,
    yp: np.ndarray,
    T1_seed: float,
    T2: float,
) -> Tuple[float, Dict[str, Any]]:
    """
    识别"软起发脚尖"：适合 20260609-1#.001 这种
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

    # 2.10 μm 是"脚尖偏离基线"的下限；后面 gain 防止噪声误触发
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

# --- detect_T2_T1_robust ---
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
    T1_new, early_meta = _refine_early_foot_onset(xp, yp, T1, T2)
    if early_meta.get("early_foot_used"):
        T1 = T1_new
        H1 = float(np.interp(T1, xp, yp))
        mode = str(mode) + "+early_foot"
        meta["confidence"] = max(float(meta.get("confidence", 0.0)), 0.90)

    meta.update(early_meta)
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

# --- detect_T2_T1 ---
def detect_T2_T1(xs: List[float], ys: List[float], logger) -> Tuple[float, float]:
    """默认入口：直接走稳健版。"""
    T1, T2, _meta = detect_T2_T1_robust(xs, ys, logger, debug=False)
    return float(T1), float(T2)

# --- detect_T2_T1_precise ---
def detect_T2_T1_precise(xs: List[float], ys: List[float], logger, debug: bool = False) -> Tuple[float, float, Dict[str, Any]]:
    """保留原接口，但内部改成稳健版。

    说明：
    - 原先的多峰逻辑会把搜索上限设到 left_peak，导致谷底型 T1 永远选不到。
    - 这里直接返回稳健版结果即可。
    """
    return detect_T2_T1_robust(xs, ys, logger, debug=debug)

# --- detect_T2_T1_super_gradient ---
def detect_T2_T1_super_gradient(xs: List[float], ys: List[float], logger, debug: bool = False) -> Tuple[float, float, Dict[str, Any]]:
    """V233 超级梯度接口：在稳健版基础上做 0.01℃ 精修。

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

# --- aggregate_duplicates ---
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

# --- build_curve_cache ---
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

# --- interpolate_curve_height ---
def interpolate_curve_height(x: float, curve_cache: Dict[str, Any]) -> float:
    """基于曲线缓存，对任意温度 x 做一次线性插值。"""
    xp = np.asarray(curve_cache.get("xp", []), dtype=float)
    yp = np.asarray(curve_cache.get("yp", []), dtype=float)
    if xp.size == 0 or yp.size == 0:
        raise ValueError("曲线缓存为空，无法插值。")
    return float(np.interp(float(x), xp, yp))

try:
    import openpyxl
    _HAS_OPENPYXL = True
except ImportError:
    _HAS_OPENPYXL = False

# ── 常量 ──────────────────────────────────────────────────────────────
WEIGHT_XLSX_DEFAULT = r"\\WIN-EK6CSI67PON\SanMingShuJuHuiZong\TMA称量数据.xlsx"
# V12：称量数据内部路径映射。
# UI 仍显示 WEIGHT_XLSX_DEFAULT；实际读取时若主机名 UNC 不可访问，则自动尝试 IP UNC。
WEIGHT_XLSX_FALLBACK = r"\\192.168.0.105\SanMingShuJuHuiZong\TMA称量数据.xlsx"
WEIGHT_XLSX_INTERNAL_MAP = {
    WEIGHT_XLSX_DEFAULT: WEIGHT_XLSX_FALLBACK,
}
TP_DIR_DEFAULT      = os.path.join(SCRIPT_DIR, "tp")

# V12：原神模式运行语录（工作日志用）。
# 注意：这里使用“角色风格短句”，避免依赖外部资源；随机调用。
# element_tag 用于把当前样品批次号染成对应元素色。
GENSHIN_ELEMENT_TAGS = {
    "火": "element_pyro",
    "水": "element_hydro",
    "风": "element_anemo",
    "雷": "element_electro",
    "冰": "element_cryo",
    "岩": "element_geo",
    "草": "element_dendro",
}
GENSHIN_ELEMENT_COLORS = {
    "element_pyro":    "#D86A3A",  # 火：火焰橙红
    "element_hydro":   "#3B8FD9",  # 水：清蓝
    "element_anemo":   "#42A88B",  # 风：青绿
    "element_electro": "#8E63D6",  # 雷：紫
    "element_cryo":    "#5AAFC8",  # 冰：冰蓝
    "element_geo":     "#C59B4B",  # 岩：岩金
    "element_dendro":  "#5EA85A",  # 草：草绿
}
GENSHIN_CHARACTER_QUOTES = [
    # 蒙德
    {"region": "蒙德", "character": "温迪", "element": "风", "quotes": [
        "风会把好消息带到这里。",
        "欸嘿，今天也适合顺风而行。",
        "让数据像蒲公英一样轻快。",
        "慢慢来，风不会催促旅人。",
        "愿这次处理一路顺风。",
    ]},
    {"region": "蒙德", "character": "可莉", "element": "火", "quotes": [
        "哒哒哒，开始工作啦！",
        "这一次也要做得亮晶晶！",
        "火花骑士会认真看结果。",
        "小心一点，别把数据炸飞啦。",
        "向着完成，出发！",
    ]},
    {"region": "蒙德", "character": "琴", "element": "风", "quotes": [
        "保持节奏，逐项完成。",
        "严谨是可靠结果的前提。",
        "按流程推进，不要遗漏。",
        "我会关注每一个细节。",
        "愿风指引正确的方向。",
    ]},
    # 璃月
    {"region": "璃月", "character": "钟离", "element": "岩", "quotes": [
        "凡事自有其契机。",
        "稳妥处理，方得可信之数。",
        "契约既成，便按步骤完成。",
        "沉着一些，结果自会显现。",
        "以岩之稳，定此一批。",
    ]},
    {"region": "璃月", "character": "刻晴", "element": "雷", "quotes": [
        "机会稍纵即逝，开始吧。",
        "效率和准确性都不能少。",
        "不要等待，直接行动。",
        "把每个样品都处理清楚。",
        "雷光一闪，任务推进。",
    ]},
    {"region": "璃月", "character": "甘雨", "element": "冰", "quotes": [
        "今日的工作也要认真完成。",
        "请按顺序核对每一项。",
        "我会把记录整理清楚。",
        "冷静分析，结果会更稳定。",
        "这一批，也辛苦了。",
    ]},
    # 稻妻
    {"region": "稻妻", "character": "雷电将军", "element": "雷", "quotes": [
        "此刻，处理开始。",
        "以不变之心审视数据。",
        "无需迟疑，执行即可。",
        "雷鸣之下，误差当止。",
        "此批结果，当归于秩序。",
    ]},
    {"region": "稻妻", "character": "神里绫华", "element": "冰", "quotes": [
        "请从这一项开始吧。",
        "愿这份结果清澈如雪。",
        "细致一些，总不会错。",
        "每一步都值得认真对待。",
        "那么，开始解析吧。",
    ]},
    {"region": "稻妻", "character": "宵宫", "element": "火", "quotes": [
        "热热闹闹地开始啦！",
        "这一批要像烟花一样漂亮。",
        "别担心，先把它跑起来。",
        "火光一亮，结果就来。",
        "今天也要干劲满满！",
    ]},
]

# V12：明日方舟模式运行语录（工作日志用）。
# 使用角色风格短句；attribute_tag 用于把当前样品批次号染成对应职业色。
ARKNIGHTS_ATTRIBUTE_TAGS = {
    "先锋": "ak_vanguard",
    "近卫": "ak_guard",
    "重装": "ak_defender",
    "狙击": "ak_sniper",
    "术师": "ak_caster",
    "医疗": "ak_medic",
    "辅助": "ak_supporter",
    "特种": "ak_specialist",
}
ARKNIGHTS_ATTRIBUTE_COLORS = {
    "ak_vanguard":   "#D9A441",  # 先锋：金黄
    "ak_guard":      "#C94F4F",  # 近卫：战斗红
    "ak_defender":   "#8B8F9A",  # 重装：钢灰
    "ak_sniper":     "#6B8FD6",  # 狙击：冷蓝
    "ak_caster":     "#8F5FD0",  # 术师：紫
    "ak_medic":      "#5FAF8A",  # 医疗：绿
    "ak_supporter":  "#4BA9A6",  # 辅助：青
    "ak_specialist": "#D07A3F",  # 特种：橙
}
ARKNIGHTS_CHARACTER_QUOTES = [
    {"region": "罗德岛", "character": "阿米娅", "attribute": "术师", "quotes": [
        "博士，这一批数据也请交给我。",
        "请保持冷静，我们会找到结果。",
        "每个样品都值得认真对待。",
        "准备完成，开始解析。",
        "我会和大家一起完成这项工作。",
    ]},
    {"region": "罗德岛", "character": "凯尔希", "attribute": "医疗", "quotes": [
        "开始吧，记录必须准确。",
        "不要被表象干扰，先看数据。",
        "每一步都需要可追溯。",
        "执行流程，不要擅自省略。",
        "结果会说明问题。",
    ]},
    {"region": "企鹅物流", "character": "德克萨斯", "attribute": "先锋", "quotes": [
        "任务开始，保持效率。",
        "这批样品，我会盯着。",
        "路线已确认，继续推进。",
        "别浪费时间，直接处理。",
        "按顺序来，很快结束。",
    ]},
    {"region": "喀兰贸易", "character": "银灰", "attribute": "近卫", "quotes": [
        "局势已明，开始行动。",
        "稳住节奏，结果自然会出现。",
        "这一步值得谨慎。",
        "让我看看这一批的表现。",
        "判断之前，先完成分析。",
    ]},
    {"region": "拉特兰", "character": "能天使", "attribute": "狙击", "quotes": [
        "目标确认，开工开工！",
        "这批数据会很顺利的。",
        "别紧张，先跑起来！",
        "节奏加快，但别丢精度。",
        "这一枪，瞄准结果。",
    ]},
    {"region": "莱茵生命", "character": "塞雷娅", "attribute": "重装", "quotes": [
        "我会确保流程稳定。",
        "先建立边界，再分析结果。",
        "任何异常都要记录。",
        "稳固的处理才有可靠结论。",
        "继续，别让误差扩散。",
    ]},
]

# V12：王者荣耀模式运行语录（工作日志用）。
# 使用角色风格短句；role_tag 用于把当前样品批次号染成对应定位色。
HONOR_ATTRIBUTE_TAGS = {
    "战士": "honor_fighter",
    "法师": "honor_mage",
    "射手": "honor_marksman",
    "刺客": "honor_assassin",
    "辅助": "honor_support",
    "坦克": "honor_tank",
}
HONOR_ATTRIBUTE_COLORS = {
    "honor_fighter":  "#D07A3F",  # 战士：橙
    "honor_mage":     "#7D63D6",  # 法师：紫蓝
    "honor_marksman": "#D6A23B",  # 射手：金
    "honor_assassin": "#C94A67",  # 刺客：玫红
    "honor_support":  "#4BAE78",  # 辅助：绿
    "honor_tank":     "#607D8B",  # 坦克：蓝灰
}
HONOR_CHARACTER_QUOTES = [
    {"region": "长安", "character": "李白", "attribute": "刺客", "quotes": [
        "剑已出鞘，数据也该亮相了。",
        "这一批，且看我一气呵成。",
        "步骤如行云，结果自流水。",
        "别停，先把曲线看清。",
        "处理完成前，不必回头。",
    ]},
    {"region": "长安", "character": "妲己", "attribute": "法师", "quotes": [
        "主人，开始解析这一批吧。",
        "数据也需要一点魔法。",
        "别担心，我会认真看着。",
        "异常出现的话，我会提醒你。",
        "这一项马上就会有结果。",
    ]},
    {"region": "稷下", "character": "鲁班七号", "attribute": "射手", "quotes": [
        "鲁班大师，智商二百五，开始工作！",
        "样品锁定，准备处理。",
        "小个子也能跑大批量。",
        "目标明确，输出结果。",
        "这批数据，交给机关来算。",
    ]},
    {"region": "王者峡谷", "character": "亚瑟", "attribute": "战士", "quotes": [
        "为了结果，开始推进。",
        "稳住阵线，逐个处理。",
        "这一批不会拖延。",
        "按流程前进。",
        "任务在前，执行即可。",
    ]},
    {"region": "三分之地", "character": "蔡文姬", "attribute": "辅助", "quotes": [
        "不要急，我来给流程加点节奏。",
        "这批样品要乖乖出结果哦。",
        "先处理，再庆祝。",
        "小心记录，别漏掉啦。",
        "继续继续，马上就好。",
    ]},
    {"region": "楚汉之地", "character": "项羽", "attribute": "坦克", "quotes": [
        "阵线已立，开始处理。",
        "再大的批量，也要一项一项来。",
        "稳住，不要让错误越线。",
        "这一批，我来扛住。",
        "完成之前，不退。",
    ]},
]

# 游戏模式汇总：所有游戏模式共用“样品前先播报语录 + 批次号按属性着色”的规则。
GAME_MODE_DEFS = {
    "genshin": {
        "display": "原神模式",
        "var_name": "var_genshin_mode",
        "quotes": GENSHIN_CHARACTER_QUOTES,
        "attr_key": "element",
        "tag_map": GENSHIN_ELEMENT_TAGS,
    },
    "arknights": {
        "display": "明日方舟模式",
        "var_name": "var_arknights_mode",
        "quotes": ARKNIGHTS_CHARACTER_QUOTES,
        "attr_key": "attribute",
        "tag_map": ARKNIGHTS_ATTRIBUTE_TAGS,
    },
    "honor": {
        "display": "王者荣耀模式",
        "var_name": "var_honor_mode",
        "quotes": HONOR_CHARACTER_QUOTES,
        "attr_key": "attribute",
        "tag_map": HONOR_ATTRIBUTE_TAGS,
    },
}
GAME_MODE_TAG_COLORS = {}
GAME_MODE_TAG_COLORS.update(GENSHIN_ELEMENT_COLORS)
GAME_MODE_TAG_COLORS.update(ARKNIGHTS_ATTRIBUTE_COLORS)
GAME_MODE_TAG_COLORS.update(HONOR_ATTRIBUTE_COLORS)

# V12：处理完成后的看板娘文字图。
# 日志框只支持文本，因此使用轻量 ASCII/Unicode 文字图；按当前游戏模式展示对应看板娘。
MASCOT_BOARD_LINES = {
    "genshin": ['        ✦  (=^･ω･^=)  ✦', '           つ  □  つ   派蒙看板娘', '   ┌──────────────────┐', '   │  这批处理完成啦！ │', '   │  CSV 和图片都要收好 │', '   └──────────────────┘'],
    "arknights": ['        RI  ( •̀ω•́ )  RI', '            つ □ つ   阿米娅看板娘', '   ┌──────────────────┐', '   │  作战记录已归档。 │', '   │  请博士检查结果。 │', '   └──────────────────┘'],
    "honor": ['        KOG  ᕦ(ò_óˇ)ᕤ', '             □        鲁班看板娘', '      ┌──────────────┐', '      │  批量输出完成！ │', '      │  结果已经就位。 │', '      └──────────────┘'],
}

# V12：派蒙师傅线路检查/维修语录。
# 用于称量数据主线路不可访问或响应过慢时的 0.5s 周期检查日志。
PAIMON_REPAIR_QUOTES = [
    "派蒙把工具箱翻出来啦，先看看主线路有没有睡着。",
    "唔……这个线路不太听话，派蒙再敲一敲。",
    "别急别急，派蒙正在检查称量数据入口。",
    "好像有点堵，派蒙换个角度再试一次。",
    "派蒙正在确认文件是不是还在原来的地方。",
    "这条路有点绕，派蒙正在找能走的方向。",
    "派蒙没有偷懒，真的在检查连接状态。",
    "再给派蒙一点点时间，马上判断能不能走。",
    "主线路好像在装死，派蒙准备看看备用办法。",
    "派蒙先记下这个问题，马上继续尝试。",
]

_logger = logging.getLogger("piliang")
_logger.setLevel(logging.DEBUG)
if not _logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    _logger.addHandler(_h)

# ── 配色主题 ──────────────────────────────────────────────────────────
THEME = {
    # V14 主界面视觉层：暖米白底、岩金强调、青蓝交互、柔和阴影感
    "bg":        "#F3E7CF",  # 主背景：柔和暖米白
    "bg2":       "#FFF8EA",  # 面板：纸张白
    "bg3":       "#F1E1BD",  # 输入框/列表底：浅羊皮纸
    "accent":    "#B8872E",  # 主强调：岩金
    "accent2":   "#4F9BAA",  # 选中/辅助：青蓝
    "success":   "#3F8F5B",
    "warning":   "#B86B24",
    "error":     "#B3453D",
    "text":      "#34291F",  # 主文字：深棕
    "text_dim":  "#7B6A55",  # 次级文字：灰褐
    "border":    "#D8B978",  # 边框：浅金
    "border_light":"#F7E8BD",
    "frame_border": "#C9A45E",
    "panel_shadow": "#E2CFA6",
    "btn_bg":    "#4F9BAA",
    "btn_hover": "#65B3C0",
    "btn_press": "#3C8390",
    "run_bg":    "#5E9D68",
    "run_hover": "#74B87A",
    "run_press": "#447B50",
    "log_bg":    "#FFFDF5",
    "header_bg": "#E8D0A0",
    "title_bg":  "#EFDBB3",
    "title_glow":"#FFF2C9",
    "status_bg": "#E8D2A9",
    "danger_bg": "#B3453D",
    "danger_hover":"#C8574F",
    "muted_btn": "#9A7B4F",
    "muted_hover":"#B09463",
    "delete_bg": "#8E5B4A",
    "delete_hover":"#A76D58",
    "entry_focus":"#4F9BAA",
    "entry_hover":"#FAEBCB",
    "radio_bg":"#F7E8C9",
    "radio_hover":"#FFF2C9",
    "radio_active":"#B8872E",
}

FONT_MONO   = ("Consolas", 9)
FONT_MONO_S = ("Consolas", 8)
FONT_UI     = ("Microsoft YaHei UI", 9)
FONT_UI_B   = ("Microsoft YaHei UI", 9, "bold")
FONT_TITLE  = ("Microsoft YaHei UI", 14, "bold")
FONT_SMALL  = ("Microsoft YaHei UI", 8)


def _hex_to_rgb(color: str):
    color = str(color or "#000000").strip()
    if not color.startswith("#") or len(color) != 7:
        return (0, 0, 0)
    return tuple(int(color[i:i+2], 16) for i in (1, 3, 5))


def _rgb_to_hex(rgb):
    r, g, b = [max(0, min(255, int(v))) for v in rgb]
    return f"#{r:02X}{g:02X}{b:02X}"


def _blend_color(color: str, target: str, amount: float = 0.18) -> str:
    r1, g1, b1 = _hex_to_rgb(color)
    r2, g2, b2 = _hex_to_rgb(target)
    amount = max(0.0, min(1.0, float(amount)))
    return _rgb_to_hex((
        r1 + (r2 - r1) * amount,
        g1 + (g2 - g1) * amount,
        b1 + (b2 - b1) * amount,
    ))


def _shade_color(color: str, amount: float = -0.10) -> str:
    target = "#000000" if amount < 0 else "#FFFFFF"
    return _blend_color(color, target, abs(amount))


def _bind_click_feedback(widget, normal_bg: str, hover_bg: str = None, press_bg: str = None,
                         normal_fg: str = None, hover_fg: str = None):
    """给按钮/标签加轻量 hover + pressed 反馈，不改变原 command 逻辑。"""
    hover_bg = hover_bg or _shade_color(normal_bg, 0.10)
    press_bg = press_bg or _shade_color(normal_bg, -0.12)
    normal_fg = normal_fg or widget.cget("fg")
    hover_fg = hover_fg or normal_fg

    def _enter(_):
        try:
            widget.config(bg=hover_bg, fg=hover_fg)
        except Exception:
            pass

    def _leave(_):
        try:
            widget.config(bg=normal_bg, fg=normal_fg)
        except Exception:
            pass

    def _press(_):
        try:
            widget.config(bg=press_bg, fg=hover_fg)
        except Exception:
            pass

    def _release(_):
        try:
            widget.config(bg=hover_bg, fg=hover_fg)
        except Exception:
            pass

    widget.bind("<Enter>", _enter, add="+")
    widget.bind("<Leave>", _leave, add="+")
    widget.bind("<ButtonPress-1>", _press, add="+")
    widget.bind("<ButtonRelease-1>", _release, add="+")
    return widget


# ══════════════════════════════════════════════════════════════════════
# 启动 Splash 界面
# ══════════════════════════════════════════════════════════════════════

SPLASH_TITLE = "批量TMA处理神器"
SPLASH_STATUS_TEXT = "正在加载"
SPLASH_IMAGE_PNG_B64 = """
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
yeCeHH8Ncv9//XaQsFFIh2YAAAAASUVORK5CYII=
"""


class SplashScreen:
    """
    极简启动画面。
    - 只显示图片
    - 标题：批量TMA处理神器
    - 进度条
    - DURATION_MS 毫秒后自动关闭；点击任意处提前关闭
    """
    DURATION_MS = 2600
    W, H = 320, 390
    BG = "#fffaf6"
    PANEL_BG = "#fffdfb"
    BORDER = "#e7d4bb"
    ACCENT = "#c89f68"
    ACCENT_LIGHT = "#f2e1c7"
    TEXT = "#5a4631"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.closed = False
        self._start_ms = time.monotonic()
        self._photo = None

        self.top = tk.Toplevel(root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.configure(bg=self.BG)

        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x = (sw - self.W) // 2
        y = (sh - self.H) // 2
        self.top.geometry(f"{self.W}x{self.H}+{x}+{y}")

        self.panel = tk.Frame(
            self.top, bg=self.PANEL_BG, bd=0,
            highlightthickness=1, highlightbackground=self.BORDER
        )
        self.panel.pack(fill="both", expand=True, padx=10, pady=10)

        self.top.bind("<Button-1>", lambda _: self.close())
        self.panel.bind("<Button-1>", lambda _: self.close())

        self._load_image()
        self._build_widgets()
        self._tick()

    def _load_image(self):
        try:
            self._photo = tk.PhotoImage(data=SPLASH_IMAGE_PNG_B64)
        except Exception:
            self._photo = None

    def _build_widgets(self):
        p = self.panel

        tk.Frame(p, bg=self.PANEL_BG, height=12).pack(fill="x")

        if self._photo is not None:
            self.image_label = tk.Label(p, image=self._photo, bg=self.PANEL_BG, bd=0)
            self.image_label.pack(pady=(10, 10))
            self.image_label.bind("<Button-1>", lambda _: self.close())
        else:
            self.image_label = tk.Label(
                p, text="[图片加载失败]",
                bg=self.PANEL_BG, fg=self.TEXT,
                font=("Microsoft YaHei UI", 10)
            )
            self.image_label.pack(pady=(40, 24))

        self.title_label = tk.Label(
            p, text=SPLASH_TITLE,
            bg=self.PANEL_BG, fg=self.TEXT,
            font=("Microsoft YaHei UI", 18, "bold")
        )
        self.title_label.pack(pady=(0, 20))

        self.progress = tk.Canvas(
            p, width=240, height=16, bg=self.PANEL_BG,
            highlightthickness=0, bd=0
        )
        self.progress.pack(pady=(0, 18))
        self._pb = (8, 3, 232, 13)
        self.progress.create_rectangle(
            self._pb[0], self._pb[1], self._pb[2], self._pb[3],
            outline=self.BORDER, fill=self.ACCENT_LIGHT, width=1, tags="pb_frame"
        )

    def _tick(self):
        if self.closed:
            return
        elapsed = (time.monotonic() - self._start_ms) * 1000.0
        frac = min(elapsed / self.DURATION_MS, 1.0)
        self._update_pb(frac)
        if frac >= 1.0:
            self.root.after(120, self.close)
            return
        self.top.after(40, self._tick)

    def _update_pb(self, frac: float):
        self.progress.delete("pb_fill")
        self.progress.delete("pb_text")
        x0, y0, x1, y1 = self._pb
        fx = x0 + (x1 - x0) * max(0.0, min(1.0, frac))
        if fx > x0:
            self.progress.create_rectangle(
                x0 + 1, y0 + 1, fx, y1 - 1,
                outline="", fill=self.ACCENT, tags="pb_fill"
            )
        self.progress.create_text(
            (x0 + x1) // 2, (y0 + y1) // 2 + 1,
            text=f"{int(frac * 100)}%",
            fill=("#ffffff" if frac > 0.48 else self.TEXT),
            font=("Consolas", 8, "bold"), tags="pb_text"
        )

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.top.destroy()
        except tk.TclError:
            pass


# ══════════════════════════════════════════════════════════════════════
# M 匹配逻辑（完全与 v3 一致）
# ══════════════════════════════════════════════════════════════════════

def _name_candidates(name: str) -> set:
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
        cands.update({f"{d8}{seq:02d}", f"{d8}-{seq}", f"{d8}-{seq}#"})
    m2 = re.match(r"^(\d{8})(\d{2})$", base)
    if m2:
        d8, seq = m2.group(1), int(m2.group(2))
        cands.update({f"{d8}-{seq}", f"{d8}-{seq}#", f"{d8}{seq:02d}"})
    return cands



def _norm_case_path(p: str) -> str:
    """用于内部路径映射比较：统一分隔符与大小写，不改变 UI 显示。"""
    return str(p or "").strip().replace("/", "\\").lower()


def _paimon_safe_isfile(path: str, log_cb=None, route_name: str = "线路",
                        timeout: float = 3.0, interval: float = 0.5,
                        emit_progress: bool = False):
    """带超时的文件可访问性检查。

    目的：避免 UNC 路径不可访问时 os.path.isfile 长时间卡死主处理流程。
    返回：True=文件存在；False=检查完成但不存在；None=超时未响应。
    """
    result = {"done": False, "exists": False, "error": None}

    def _cb(msg, level="dim"):
        if log_cb:
            try:
                log_cb(msg, level)
            except Exception:
                pass

    def _worker():
        try:
            result["exists"] = bool(os.path.isfile(path))
        except Exception as e:
            result["error"] = e
            result["exists"] = False
        finally:
            result["done"] = True

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    start = time.monotonic()
    quote_i = random.randrange(len(PAIMON_REPAIR_QUOTES)) if PAIMON_REPAIR_QUOTES else 0

    if emit_progress:
        _cb(f"派蒙师傅在检查中：正在确认{route_name}状态……", "accent")

    while True:
        if result["done"]:
            return bool(result["exists"])
        elapsed = time.monotonic() - start
        if elapsed >= timeout:
            if emit_progress:
                _cb(f"派蒙师傅：{route_name}响应太慢，先不继续等它了。", "warn")
            return None
        time.sleep(interval)
        if emit_progress and not result["done"]:
            quote = PAIMON_REPAIR_QUOTES[quote_i % len(PAIMON_REPAIR_QUOTES)]
            quote_i += 1
            _cb(f"派蒙师傅：{quote}", "accent")


def resolve_weight_xlsx_runtime_path(xlsx_path: str, log_cb=None) -> str:
    """返回实际用于读取的称量 XLSX 路径。

    V12 派蒙线路规则：
    - UI 输入框保持用户看到的路径；
    - 若主机名 UNC 不可访问/响应过慢，不输出具体 IP；
    - 每 0.5s 输出派蒙师傅检查日志；
    - 自动尝试备用线路，成功后继续处理。
    """
    display_path = str(xlsx_path or "").strip() or WEIGHT_XLSX_DEFAULT

    def _cb(msg, level="dim"):
        if log_cb:
            try:
                log_cb(msg, level)
            except Exception:
                pass

    display_norm = _norm_case_path(display_path)
    default_norm = _norm_case_path(WEIGHT_XLSX_DEFAULT)
    fallback_norm = _norm_case_path(WEIGHT_XLSX_FALLBACK)

    # 用户已经明确选择/切换到备用线路：直接使用输入框路径，不做主线路映射提示。
    if display_norm == fallback_norm:
        ok = _paimon_safe_isfile(display_path, log_cb=log_cb,
                                 route_name="备用线路", timeout=4.0,
                                 interval=0.5, emit_progress=False)
        if ok is False:
            _cb("派蒙：备用线路暂时没有找到称量数据文件，请检查输入框路径。", "warn")
        elif ok is None:
            _cb("派蒙：备用线路响应较慢，先继续尝试读取。", "warn")
        return display_path

    # 用户自定义路径：不参与主/备用线路映射。
    if display_norm != default_norm:
        return display_path

    # 默认主线路：使用带超时检查，避免主机名 UNC 卡死。
    main_ok = _paimon_safe_isfile(WEIGHT_XLSX_DEFAULT, log_cb=log_cb,
                                  route_name="主线路", timeout=3.0,
                                  interval=0.5, emit_progress=True)
    if main_ok is True:
        _cb("派蒙：主线路检查成功，称量数据可以读取。", "ok")
        return WEIGHT_XLSX_DEFAULT

    # 主线路不可达/超时：隐藏具体 IP，只提示备用线路。
    _cb("派蒙：我真的弄不好了，我只能试用一下备用线路进行尝试", "warn")
    _cb("派蒙师傅在检查中：备用线路测试中……", "accent")

    fallback_ok = _paimon_safe_isfile(WEIGHT_XLSX_FALLBACK, log_cb=log_cb,
                                      route_name="备用线路", timeout=5.0,
                                      interval=0.5, emit_progress=True)
    if fallback_ok is True:
        _cb("派蒙：备用线路测试成功，继续前进！", "ok")
        return WEIGHT_XLSX_FALLBACK

    _cb("派蒙：备用线路也没有成功，请检查称量数据文件路径。", "error" if fallback_ok is False else "warn")
    return WEIGHT_XLSX_DEFAULT


def lookup_mass(filepath: str, xlsx_path: str):
    if not _HAS_OPENPYXL:
        return None, "openpyxl 未安装，请执行: pip install openpyxl"
    stem       = os.path.splitext(os.path.basename(filepath))[0]
    file_cands = _name_candidates(stem)
    try:
        wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
        ws = wb.active
        all_rows = []
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
# 出图（完全与 v3 一致）
# ══════════════════════════════════════════════════════════════════════

def _get_plot_mg_text(mg_val) -> str:
    s = str(mg_val).strip() if mg_val is not None else ""
    if not s:
        return "x"
    try:
        float(s)
    except Exception:
        return s
    if "e" in s.lower():
        try:
            return f"{float(s):.2f}"
        except Exception:
            return s
    if "." in s:
        frac = s.split(".", 1)[1]
        if len(frac) == 1:
            try:
                return f"{float(s):.2f}"
            except Exception:
                return s
        return s
    try:
        return f"{float(s):.2f}"
    except Exception:
        return s


def _build_method_note(mg_val) -> str:
    mg_s = _get_plot_mg_text(mg_val)
    a = "方法日志：30°C平衡，施加 0.06 N；\n"
    b = " " * 17 + "20°C/min加热至 250°C；\n"
    c = f"称取质量：{mg_s}mg。"
    return a + b + c


def save_plot_png(filepath, xs, ys, T1, T2, curve_cache, M_val, out_dir: str) -> str:
    stem     = os.path.splitext(os.path.basename(filepath))[0]
    out_path = os.path.join(out_dir, stem + ".png")

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
    x1_pt   = float(T1)
    x2_pt   = float(T2)
    y1_pt   = interpolate_curve_height(x1_pt, curve_cache)
    y2_pt   = interpolate_curve_height(x2_pt, curve_cache)

    def _ann_margin(cy0, cy1):
        return max(80.0, (cy1 - cy0) * 0.04)

    ann_margin = _ann_margin(y0_plot, y1_plot)
    if y2_pt + ann_margin > y1_plot:
        y1_plot   += 200.0
        ann_margin = _ann_margin(y0_plot, y1_plot)
    while y1_pt - ann_margin < y0_plot:
        y0_plot   -= 100.0
        ann_margin = _ann_margin(y0_plot, y1_plot)
    if y1_plot <= y0_plot:
        y1_plot = y0_plot + 500.0

    y_ticks_major = [float(y0_plot), 0.0]
    if y0_plot < -500.0 - 1e-9:
        y_ticks_major.append(-500.0)
    y_ticks_major.extend([float(v) for v in range(500, int(y1_base) + 1, 500)])
    y_ticks_major = sorted({v for v in y_ticks_major
                             if y0_plot - 1e-9 <= v <= y1_base + 1e-9})
    y_minor_start = int(math.floor(y0_plot / 100.0) * 100)
    y_minor_end   = int(math.ceil(y1_plot  / 100.0) * 100)
    y_ticks_minor = list(range(y_minor_start, y_minor_end + 1, 100))

    fig = Figure(figsize=(12.8, 7.2), dpi=150)
    ax  = fig.add_subplot(111)
    ax.plot(xs, ys, color="black", linewidth=1.5)

    x_left, x_right = 0.0, 300.0
    ax.set_xlim(x_left, x_right)
    ax.xaxis.set_major_locator(MultipleLocator(50))
    ax.xaxis.set_minor_locator(MultipleLocator(10))
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.set_xlabel("温度(°C)", fontsize=12)
    ax.tick_params(axis="x", which="major", length=6)
    ax.tick_params(axis="x", which="minor", length=3)

    for gx in range(0, 301, 10):
        ax.axvline(gx, linestyle="--", linewidth=0.4,
                   color="#999999", alpha=0.35, zorder=0)

    y_grid_start = int(math.floor(y0_plot / 100.0)) * 100
    y_grid_end   = int(math.ceil(y1_plot  / 100.0)) * 100
    for gy in range(y_grid_start, y_grid_end + 1, 100):
        ax.axhline(gy, linestyle="--", linewidth=0.4,
                   color="#999999", alpha=0.35, zorder=0)

    try:
        ax.plot([0, 500, 500, 0, 0], [0, 0, 500, 500, 0],
                linestyle=(0, (1, 3)), linewidth=0.5, color="0.8", zorder=0)
    except Exception:
        pass

    ax.set_ylim(y0_plot, y1_plot)
    ax.yaxis.set_major_locator(FixedLocator(y_ticks_major))
    ax.yaxis.set_minor_locator(FixedLocator(y_ticks_minor))
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.set_ylabel("尺寸变化(μm)", fontsize=12)
    ax.tick_params(axis="y", which="major", length=6)
    ax.tick_params(axis="y", which="minor", length=3)

    fig.suptitle("TMA", fontsize=16, fontweight="bold")
    ax.text(x_left + 10, y1_plot - 100, _build_method_note(M_val),
            ha="left", va="top", fontsize=12)

    y_range     = y1_plot - y0_plot
    tick_half_y = max(10.0, y_range * 0.02)
    tick_half_x = 2.0
    tick_lw     = 1.2

    def _draw_cross(xc, yc):
        ax.vlines(xc, yc - tick_half_y, yc + tick_half_y,
                  colors="black", linewidth=tick_lw, zorder=5)
        ax.hlines(yc, max(0.0, xc - tick_half_x), min(300.0, xc + tick_half_x),
                  colors="black", linewidth=tick_lw, zorder=5)

    _draw_cross(x1_pt, y1_pt)
    _draw_cross(x2_pt, y2_pt)

    ax.annotate(f"{format_plot_temp_c(x1_pt)}℃", (x1_pt, y1_pt),
                xytext=(0, -10), textcoords="offset points",
                ha="center", va="top", fontsize=12, color="black")
    ax.annotate(f"{format_plot_temp_c(x2_pt)}℃", (x2_pt, y2_pt),
                xytext=(0, 10), textcoords="offset points",
                ha="center", va="bottom", fontsize=12, color="black")

    ax.plot([x1_pt, x2_pt], [y1_pt, y1_pt], color="black", lw=0.8, zorder=4)
    ax.annotate("", xy=(x2_pt, y2_pt), xytext=(x2_pt, y1_pt),
                arrowprops=dict(arrowstyle="<->", color="black",
                                linewidth=1.0, shrinkA=0, shrinkB=0))

    dh      = abs(y2_pt - y1_pt)
    x_text  = min(300.0, x2_pt + 15.0)
    y_curve = float(np.interp(x_text, curve_cache["xp"], curve_cache["yp"]))
    margin  = max(15.0, (y1_plot - y0_plot) * 0.03)
    y_text  = min(y_curve + margin, y1_plot - margin * 0.2)
    ax.text(x_text, y_text, f"{format_height_um(dh)} μm",
            fontsize=12, ha="left", va="bottom", color="black")

    fig.text(0.99, 0.01, f"{FILE_VERSION_TAG} · {ALGORITHM_VERSION}", ha="right", va="bottom", fontsize=10)

    from matplotlib.backends.backend_agg import FigureCanvasAgg
    FigureCanvasAgg(fig)
    fig.savefig(out_path, dpi=150, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    fig.clear()
    del fig
    return out_path


# ══════════════════════════════════════════════════════════════════════
# 单文件处理
# ══════════════════════════════════════════════════════════════════════

def process_one(filepath: str, tp_dir: str, xlsx_path: str,
                log_cb=None) -> dict:
    """
    处理单个 TMA 文件。
    log_cb(msg, level) 用于向 GUI 推送步骤日志；不传则静默。
    """
    def _cb(msg, level="info"):
        if log_cb:
            log_cb(msg, level)

    stem   = os.path.splitext(os.path.basename(filepath))[0]
    result = dict(stem=stem, file=filepath,
                  T1=None, T2=None, H=None, M=None,
                  png=None, error=None, M_warn=None)
    try:
        # ── 步骤 1：解密 / 读取原始文本 ──────────────────────────────
        _cb("  ├─ 开始解密…", "dim")
        text, _meta = load_text_prefer_tajm(filepath, _logger)
        _cb("  ├─ 解密成功", "ok")

        # ── 步骤 2：解析 + 提取数据点 ────────────────────────────────
        _cb("  ├─ 分析数据…", "dim")
        parsed    = parse_lines(text)
        xs, ys, _ = extract_xy_from_file(parsed, _logger)
        if len(xs) < 5:
            result["error"] = f"有效数据点不足（{len(xs)} 行）"
            _cb(f"  └─ ✗ 数据点不足（{len(xs)} 行）", "error")
            return result

        # ── 步骤 3：内置 V233 算法识别 T1；T2 保持固定算法 → H ─────
        T1, T2, meta = detect_T2_T1_super_gradient(xs, ys, _logger)
        try:
            _cb(f"  ├─ 算法标识  {ALGORITHM_LABEL}；T1模式={meta.get('mode', 'NA')}", "dim")
        except Exception:
            _cb(f"  ├─ 算法标识  {ALGORITHM_LABEL}", "dim")
        curve_cache = build_curve_cache(xs, ys)
        H1 = interpolate_curve_height(T1, curve_cache)
        H2 = interpolate_curve_height(T2, curve_cache)
        H  = H2 - H1
        result["T1"], result["T2"], result["H"] = T1, T2, H

        T1s = format_plot_temp_c(T1)
        T2s = format_plot_temp_c(T2)
        Hs  = format_height_um(H)
        _cb(f"  ├─ 数据结果  T1={T1s}°C  T2={T2s}°C  H={Hs} μm", "accent")

        # ── 步骤 4：查称量 M ─────────────────────────────────────────
        M_val, M_info = lookup_mass(filepath, xlsx_path)
        result["M"] = M_val
        if M_val is None:
            result["M_warn"] = M_info
            _cb(f"  ├─ ⚠ M 未匹配：{M_info}", "warn")
        else:
            try:
                Ms = f"{float(M_val):.4f}"
            except Exception:
                Ms = str(M_val)
            _cb(f"  ├─ 称量 M={Ms} mg", "dim")

        # ── 步骤 5：出图 ─────────────────────────────────────────────
        png_path = save_plot_png(
            filepath, xs, ys, T1, T2, curve_cache, M_val, tp_dir)
        result["png"] = png_path
        _cb(f"  └─ 图片已保存", "dim")

    except Exception as e:
        result["error"] = f"{e}\n{traceback.format_exc()}"
        _cb(f"  └─ ✗ 异常：{e}", "error")
    return result


# ══════════════════════════════════════════════════════════════════════
# 辅助 UI 函数
# ══════════════════════════════════════════════════════════════════════

class TooltipHelper:
    def __init__(self, widget, text):
        self.widget, self.text, self.tw = widget, text, None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _=None):
        x = self.widget.winfo_rootx() + 24
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tw = tk.Toplevel(self.widget)
        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tw, text=self.text, justify="left",
                 bg=THEME["bg3"], fg=THEME["accent"],
                 font=FONT_SMALL, relief="flat", padx=6, pady=4).pack()

    def _hide(self, _=None):
        if self.tw:
            self.tw.destroy()
            self.tw = None


def _sep(parent):
    # V14：更柔和的分隔线，避免硬切割
    tk.Frame(parent, bg=THEME["panel_shadow"], height=1).pack(fill="x", padx=10, pady=4)


def _btn(parent, text, cmd, bg=None, width=None, **kw):
    normal_bg = bg or THEME["btn_bg"]
    hover_bg = kw.pop("hover_bg", None) or (
        THEME.get("delete_hover") if normal_bg == THEME.get("delete_bg") else
        THEME.get("muted_hover") if normal_bg == THEME.get("muted_btn") else
        THEME.get("btn_hover")
    )
    press_bg = kw.pop("press_bg", None) or _shade_color(normal_bg, -0.14)
    kargs = dict(text=text, command=cmd,
                 bg=normal_bg, fg="white",
                 activebackground=press_bg, activeforeground="white",
                 font=FONT_UI, relief="flat", bd=0,
                 padx=10, pady=5, cursor="hand2")
    if width:
        kargs["width"] = width
    kargs.update(kw)
    btn = tk.Button(parent, **kargs)
    _bind_click_feedback(btn, normal_bg, hover_bg, press_bg, "white", "white")
    return btn


def _entry_row(parent, label: str, var: tk.StringVar,
               browse_cmd=None, browse_label: str = "浏览…"):
    """标签 + 输入框 [+ 浏览按钮] 一行。"""
    row = tk.Frame(parent, bg=THEME["bg2"])
    row.pack(fill="x", padx=10, pady=4)
    tk.Label(row, text=label, font=FONT_UI_B, bg=THEME["bg2"],
             fg=THEME["accent"], anchor="w", width=12).pack(side="left")
    e = tk.Entry(row, textvariable=var,
                 bg=THEME["bg3"], fg=THEME["text"],
                 insertbackground=THEME["accent"],
                 font=FONT_MONO_S, relief="flat", bd=5,
                 highlightthickness=1,
                 highlightbackground=THEME["border"],
                 highlightcolor=THEME["entry_focus"])
    e.pack(side="left", fill="x", expand=True, padx=5)

    def _entry_focus(_):
        e.config(bg=THEME["log_bg"], highlightbackground=THEME["entry_focus"], highlightcolor=THEME["entry_focus"])

    def _entry_blur(_):
        e.config(bg=THEME["bg3"], highlightbackground=THEME["border"], highlightcolor=THEME["entry_focus"])

    def _entry_enter(_):
        if e.focus_get() is not e:
            e.config(bg=THEME["entry_hover"], highlightbackground=THEME["accent"])

    def _entry_leave(_):
        if e.focus_get() is not e:
            e.config(bg=THEME["bg3"], highlightbackground=THEME["border"])

    e.bind("<FocusIn>", _entry_focus)
    e.bind("<FocusOut>", _entry_blur)
    e.bind("<Enter>", _entry_enter)
    e.bind("<Leave>", _entry_leave)

    if browse_cmd:
        _btn(row, browse_label, browse_cmd,
             bg=THEME["btn_bg"], width=6).pack(side="left", padx=(0, 2))
    return row


# ══════════════════════════════════════════════════════════════════════
# 主 GUI
# ══════════════════════════════════════════════════════════════════════

class PiliangApp:
    _LOG_FLUSH_INTERVAL = 80   # ms：日志队列批量刷新间隔

    def __init__(self, root: tk.Tk):
        self.root  = root
        self.root.title(f"TMA 批量处理  ·  V14 交互增强 UI  ·  {GENERATION_LABEL}  ·  {FILE_VERSION_TAG}  ·  算法{ALGORITHM_VERSION}")
        self.root.configure(bg=THEME.get("frame_border", THEME["border"]))
        self.root.resizable(False, False)   # overrideredirect 下由手动缩放接管
        self.files: list = []

        # 日志队列（性能优化）
        self._log_queue:   list = []
        self._log_flush_id      = None

        # 自定义标题栏 — 窗口拖动状态
        self._drag_x: int = 0
        self._drag_y: int = 0

        # 最大化 / 还原状态
        self._maximized:   bool = False
        self._restore_geo: str  = ""

        # 右下角缩放
        self._resize_x: int = 0
        self._resize_y: int = 0
        self._resize_w: int = 0
        self._resize_h: int = 0

        self._build_ui()
        self._animate_title()

    # ── 标题闪烁（2s 一次，降低无谓重绘）────────────────────────────
    def _animate_title(self):
        colors = [THEME["accent"], THEME["accent2"], THEME["title_glow"], THEME["accent"]]
        idx    = [0]
        def _tick():
            try:
                self.lbl_title.config(fg=colors[idx[0] % len(colors)])
            except tk.TclError:
                return
            idx[0] += 1
            self.root.after(2000, _tick)
        _tick()

    # ── UI 骨架 ───────────────────────────────────────────────────────
    def _build_ui(self):
        # 整体内容 Frame，内缩 1px 露出根窗口背景色作为细边框
        outer = tk.Frame(self.root, bg=THEME["bg"],
                         highlightthickness=0, bd=0)
        outer.place(x=1, y=1, relwidth=1.0, relheight=1.0,
                    width=-2, height=-2)

        # ── 自绘标题栏（替代原生）────────────────────────────────────
        self._build_titlebar(outer)

        # 主体左右分栏
        body = tk.Frame(outer, bg=THEME["bg"])
        body.pack(fill="both", expand=True)

        left = tk.Frame(body, bg=THEME["bg2"], width=300,
                        highlightbackground=THEME["panel_shadow"], highlightthickness=1)
        left.pack(side="left", fill="y", padx=(10, 5), pady=10)
        left.pack_propagate(False)
        self._build_left(left)

        right = tk.Frame(body, bg=THEME["bg"])
        right.pack(side="left", fill="both", expand=True, padx=(5, 10), pady=10)
        self._build_right(right)

        # ── 底部状态栏（含右下角缩放把手）───────────────────────────
        sb = tk.Frame(outer, bg=THEME["status_bg"], height=26)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)

        self.lbl_status_bar = tk.Label(sb, text="● 就绪", font=FONT_SMALL,
                                       bg=THEME["status_bg"], fg=THEME["success"],
                                       anchor="w", padx=12)
        self.lbl_status_bar.pack(side="left", fill="y")

        self.lbl_csv_hint = tk.Label(sb, text="", font=FONT_SMALL,
                                     bg=THEME["status_bg"], fg=THEME["text_dim"],
                                     anchor="e", padx=4)
        self.lbl_csv_hint.pack(side="right", fill="y")

        # 右下角缩放把手（cursor 用跨平台通用名）
        grip = tk.Canvas(sb, width=18, height=18,
                         bg=THEME["status_bg"], highlightthickness=0,
                         cursor="bottom_right_corner")
        grip.pack(side="right", padx=(0, 2))
        for i in (5, 9, 13):
            grip.create_line(i, 16, 16, i, fill=THEME["text_dim"], width=1)
        grip.bind("<ButtonPress-1>", self._resize_press)
        grip.bind("<B1-Motion>",     self._resize_drag)

        self.root.geometry("1060x700")

    # ── 自绘标题栏 ────────────────────────────────────────────────────
    def _build_titlebar(self, parent):
        TB_H   = 46
        BG     = THEME["title_bg"]
        ACCENT = THEME["accent"]

        bar = tk.Frame(parent, bg=BG, height=TB_H)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        # ── 左侧：装饰菱形 + 标题文字 ────────────────────────────────
        left_box = tk.Frame(bar, bg=BG)
        left_box.pack(side="left", fill="y")

        # 装饰性 Canvas 菱形 icon
        ico = tk.Canvas(left_box, width=36, height=TB_H,
                        bg=BG, highlightthickness=0, cursor="hand2")
        ico.pack(side="left")
        cx, cy = 18, TB_H // 2
        r = 10
        ico_outer = ico.create_polygon(
            cx, cy-r, cx+r, cy, cx, cy+r, cx-r, cy,
            fill="", outline=ACCENT, width=1.8)
        ico_inner = ico.create_polygon(
            cx, cy-r+4, cx+r-4, cy, cx, cy+r-4, cx-r+4, cy,
            fill=ACCENT, outline="")
        def _ico_enter(_):
            ico.itemconfig(ico_outer, outline=THEME["accent2"], width=2.4)
            ico.itemconfig(ico_inner, fill=THEME["accent2"])
        def _ico_leave(_):
            ico.itemconfig(ico_outer, outline=ACCENT, width=1.8)
            ico.itemconfig(ico_inner, fill=ACCENT)
        ico.bind("<Enter>", _ico_enter)
        ico.bind("<Leave>", _ico_leave)
        ico.bind("<ButtonRelease-1>", self._toggle_weight_xlsx_route)

        self.lbl_title = tk.Label(
            left_box, text=f"{GENERATION_LABEL}TMA 批量处理系统 · {FILE_VERSION_TAG}",
            font=FONT_TITLE, bg=BG, fg=ACCENT, padx=6,
            cursor="hand2")
        self.lbl_title.pack(side="left", fill="y")

        # ── 右侧：控制按钮区 ──────────────────────────────────────────
        right_box = tk.Frame(bar, bg=BG)
        right_box.pack(side="right", fill="y")

        # 时钟
        self.lbl_clock = tk.Label(
            right_box, text="", font=FONT_MONO,
            bg=BG, fg=THEME["text_dim"], padx=10)
        self.lbl_clock.pack(side="left", fill="y")
        self._update_clock()

        # 版本
        tk.Label(right_box, text=f"算法 {ALGORITHM_VERSION}",
                 font=FONT_SMALL, bg=BG,
                 fg=THEME["text_dim"], padx=6).pack(side="left", fill="y")

        # 分隔线
        tk.Frame(right_box, bg=THEME["border"], width=1).pack(
            side="left", fill="y", pady=10, padx=4)

        # 三个控制按钮
        self._btn_min = self._make_ctrl_btn(
            right_box, text="─",
            hover_bg=THEME["border"], cmd=self._win_minimize)
        self._btn_max = self._make_ctrl_btn(
            right_box, text="□",
            hover_bg=THEME["border"], cmd=self._win_toggle_maximize)
        self._btn_cls = self._make_ctrl_btn(
            right_box, text="✕",
            hover_bg=THEME.get("danger_hover", THEME["danger_bg"]), cmd=self._win_close)

        # ── 底部装饰分隔线（扫光效果用静态渐变代替）─────────────────
        sep_cv = tk.Canvas(bar, height=1, bg=BG, highlightthickness=0)
        sep_cv.pack(fill="x", side="bottom")
        # 用多段线模拟从暗→亮→暗的渐变分隔线
        seg_colors = [
            "#D9C08A", "#E7D1A3", "#F0DFBD", "#C59B4B",
            ACCENT,
            "#C59B4B", "#F0DFBD", "#E7D1A3", "#D9C08A",
        ]
        bar.update_idletasks()

        def _draw_sep(event=None):
            sep_cv.delete("all")
            w = sep_cv.winfo_width() or 1060
            n = len(seg_colors)
            seg_w = w / n
            for i, clr in enumerate(seg_colors):
                sep_cv.create_line(
                    int(i*seg_w), 0, int((i+1)*seg_w), 0,
                    fill=clr, width=1)
        sep_cv.bind("<Configure>", _draw_sep)
        self.root.after(50, _draw_sep)

        # ── 拖动绑定（标题栏所有子控件都绑）────────────────────────
        for w in (bar, left_box, self.lbl_title, right_box, self.lbl_clock):
            w.bind("<ButtonPress-1>",  self._titlebar_press)
            w.bind("<B1-Motion>",      self._titlebar_drag)
            w.bind("<Double-Button-1>", lambda _: self._win_toggle_maximize())
        self.lbl_title.bind("<ButtonRelease-1>", self._enable_hidden_threads_from_title, add="+")

    def _enable_hidden_threads_from_title(self, event=None):
        """隐藏开关：点击标题在单线程/多线程之间切换；界面不显示多线程复选框。"""
        try:
            moved = abs(event.x_root - getattr(self, "_press_x_root", event.x_root)) + abs(event.y_root - getattr(self, "_press_y_root", event.y_root))
        except Exception:
            moved = 0
        if moved > 8:
            return
        if not hasattr(self, "var_enable_threads"):
            return
        try:
            now_enabled = bool(self.var_enable_threads.get())
            self.var_enable_threads.set(not now_enabled)
            if now_enabled:
                self._log("派蒙：隐藏多线程模式已关闭，后续处理回到单线程。", "accent")
            else:
                self._log("派蒙：隐藏多线程模式已启用，后续处理会使用多线程。", "accent")
        except Exception:
            pass

    def _toggle_weight_xlsx_route(self, event=None):
        """左上角菱形：在主线路/备用线路之间切换称量数据输入框。"""
        if not hasattr(self, "var_xlsx"):
            return "break"
        current = _norm_case_path(self.var_xlsx.get())
        if current == _norm_case_path(WEIGHT_XLSX_FALLBACK):
            target = WEIGHT_XLSX_DEFAULT
            label = "主线路"
        else:
            target = WEIGHT_XLSX_FALLBACK
            label = "备用线路"

        # 按要求：先清空输入框，再写入目标路径。
        self.var_xlsx.set("")
        def _write():
            try:
                self.var_xlsx.set(target)
                self._log(f"派蒙：已切换为{label}，称量数据路径已重写。", "accent")
            except Exception:
                pass
        self.root.after(30, _write)
        return "break"

    def _make_ctrl_btn(self, parent, text, hover_bg, cmd):
        """创建带 hover/press 反馈的控制按钮（使用 Label 模拟，更易定制样式）。"""
        BG = THEME["title_bg"]
        lbl = tk.Label(parent, text=text,
                       font=("Consolas", 11),
                       bg=BG, fg=THEME["text_dim"],
                       width=3, cursor="hand2",
                       anchor="center")
        lbl.pack(side="left", fill="y", ipadx=2)
        press_bg = _shade_color(hover_bg, -0.12)
        def _on_enter(_):
            fg = "white" if hover_bg in (THEME.get("danger_bg"), THEME.get("danger_hover")) else THEME["text"]
            lbl.config(bg=hover_bg, fg=fg)
        def _on_leave(_):
            lbl.config(bg=BG, fg=THEME["text_dim"])
        def _on_press(_):
            lbl.config(bg=press_bg, fg="white" if hover_bg == THEME.get("danger_bg") else THEME["text"])
        def _on_release(_):
            _on_enter(_)
            cmd()
        lbl.bind("<Enter>", _on_enter)
        lbl.bind("<Leave>", _on_leave)
        lbl.bind("<ButtonPress-1>", _on_press)
        lbl.bind("<ButtonRelease-1>", _on_release)
        return lbl

    # ── 窗口控制 ──────────────────────────────────────────────────────
    def _titlebar_press(self, event):
        self._press_x_root = event.x_root
        self._press_y_root = event.y_root
        self._drag_x = event.x_root - self.root.winfo_x()
        self._drag_y = event.y_root - self.root.winfo_y()

    def _titlebar_drag(self, event):
        if self._maximized:
            return
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def _win_minimize(self):
        # overrideredirect 窗口无法用 iconify，需先恢复再最小化
        self.root.overrideredirect(False)
        self.root.iconify()
        # 还原时重新套上 overrideredirect
        self.root.bind("<Map>", self._on_restore_from_minimize)

    def _on_restore_from_minimize(self, event=None):
        self.root.unbind("<Map>")
        self.root.overrideredirect(True)

    def _win_toggle_maximize(self):
        if self._maximized:
            self.root.geometry(self._restore_geo)
            self._btn_max.config(text="□")
            self._maximized = False
        else:
            self._restore_geo = self.root.geometry()
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            # 留出任务栏高度（Windows 通用做法：取 maxsize 的高）
            try:
                _, max_h = self.root.wm_maxsize()
                wh = min(sh, max_h)
            except Exception:
                wh = sh - 40
            self.root.geometry(f"{sw}x{wh}+0+0")
            self._btn_max.config(text="❐")
            self._maximized = True

    def _win_close(self):
        self.root.destroy()

    # ── 右下角缩放 ────────────────────────────────────────────────────
    def _resize_press(self, event):
        self._resize_x = event.x_root
        self._resize_y = event.y_root
        self._resize_w = self.root.winfo_width()
        self._resize_h = self.root.winfo_height()

    def _resize_drag(self, event):
        if self._maximized:
            return
        dw = event.x_root - self._resize_x
        dh = event.y_root - self._resize_y
        nw = max(800, self._resize_w + dw)
        nh = max(560, self._resize_h + dh)
        x  = self.root.winfo_x()
        y  = self.root.winfo_y()
        self.root.geometry(f"{nw}x{nh}+{x}+{y}")

    # ── 左栏 ─────────────────────────────────────────────────────────
    def _build_left(self, parent):
        tk.Label(parent, text="📁  数据文件队列",
                 font=FONT_UI_B, bg=THEME["bg2"],
                 fg=THEME["accent"], anchor="w", padx=12, pady=9
                 ).pack(fill="x")
        _sep(parent)

        lf = tk.Frame(parent, bg=THEME["bg3"],
                      highlightbackground=THEME["border_light"],
                      highlightthickness=1)
        lf.pack(fill="both", expand=True, padx=10, pady=(6, 0))

        sb_y = tk.Scrollbar(lf, bg=THEME["bg3"], troughcolor=THEME["bg"])
        sb_y.pack(side="right", fill="y")
        sb_x = tk.Scrollbar(lf, orient="horizontal",
                             bg=THEME["bg3"], troughcolor=THEME["bg"])
        sb_x.pack(side="bottom", fill="x")

        self.lb_files = tk.Listbox(
            lf, bg=THEME["bg3"], fg=THEME["text"],
            selectbackground=THEME["accent2"], selectforeground="#ffffff",
            activestyle="none", font=FONT_MONO_S,
            bd=0, highlightthickness=0,
            relief="flat",
            yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)
        self.lb_files.pack(side="left", fill="both", expand=True)
        sb_y.config(command=self.lb_files.yview)
        sb_x.config(command=self.lb_files.xview)

        br = tk.Frame(parent, bg=THEME["bg2"])
        br.pack(fill="x", padx=10, pady=8)
        _btn(br, "＋ 添加",     self._select_files,    bg=THEME["btn_bg"], width=8 ).pack(side="left",  padx=(0,4))
        _btn(br, "－ 删除选中",  self._remove_selected, bg=THEME["muted_btn"],       width=10).pack(side="left",  padx=(0,4))
        _btn(br, "清空",        self._clear_files,     bg=THEME["delete_bg"],       width=5 ).pack(side="right")

        self.lbl_file_count = tk.Label(parent, text="共 0 个文件",
                                       font=FONT_SMALL, bg=THEME["bg2"],
                                       fg=THEME["text_dim"], anchor="w", padx=12)
        self.lbl_file_count.pack(fill="x")

        _sep(parent)

        # 运行按钮
        rf = tk.Frame(parent, bg=THEME["bg2"])
        rf.pack(fill="x", padx=10, pady=10)
        self.btn_run = tk.Button(
            rf, text="▶  开始批量处理", font=FONT_UI_B,
            bg=THEME["run_bg"], fg="white",
            activebackground=THEME["run_press"], activeforeground="white",
            relief="flat", bd=0, padx=14, pady=9,
            cursor="hand2", command=self._run)
        self.btn_run.pack(fill="x")
        _bind_click_feedback(self.btn_run, THEME["run_bg"], THEME["run_hover"], THEME.get("run_press", _shade_color(THEME["run_bg"], -0.14)), "white", "white")
        TooltipHelper(self.btn_run, "选择文件后点击开始处理，结果保存至同目录 CSV")

        style = ttk.Style()
        style.theme_use("default")
        style.configure("Tech.Horizontal.TProgressbar",
                        troughcolor=THEME["bg3"],
                        background=THEME["accent"],
                        darkcolor=THEME["accent"],
                        lightcolor=THEME["accent"],
                        bordercolor=THEME["bg3"],
                        thickness=10)
        self.progress = ttk.Progressbar(
            parent, style="Tech.Horizontal.TProgressbar",
            mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=10, pady=(0, 4))

        self.lbl_pct = tk.Label(parent, text="0 %", font=FONT_MONO_S,
                                bg=THEME["bg2"], fg=THEME["text_dim"])
        self.lbl_pct.pack()

    # ── 右栏 ─────────────────────────────────────────────────────────
    def _build_right(self, parent):
        # 配置区
        cfg = tk.Frame(parent, bg=THEME["bg2"],
                       highlightbackground=THEME["panel_shadow"], highlightthickness=1)
        cfg.pack(fill="x", pady=(0, 8))

        tk.Label(cfg, text="⚙  路径配置",
                 font=FONT_UI_B, bg=THEME["bg2"],
                 fg=THEME["accent"], padx=8, pady=6).pack(fill="x")
        _sep(cfg)

        self.var_xlsx   = tk.StringVar(value=WEIGHT_XLSX_DEFAULT)
        self.var_tp_dir = tk.StringVar(value=TP_DIR_DEFAULT)
        self.var_enable_threads = tk.BooleanVar(value=False)  # 隐藏开关：默认单线程
        self.var_game_mode = tk.StringVar(value="genshin")   # 游戏模式三选一：默认原神模式

        _entry_row(cfg, "称量数据 XLSX", self.var_xlsx,   browse_cmd=self._browse_xlsx)
        _entry_row(cfg, "图片输出目录",  self.var_tp_dir, browse_cmd=self._browse_tp_dir)
        self._build_run_options(cfg)

        # 结果表格
        tk.Label(parent, text="📊  处理结果", font=FONT_UI_B,
                 bg=THEME["bg"], fg=THEME["accent"],
                 anchor="w", pady=2).pack(fill="x")

        tbl = tk.Frame(parent, bg=THEME["bg3"], bd=1,
                       highlightbackground=THEME["border"],
                       highlightthickness=1)
        tbl.pack(fill="x", pady=(0, 8))

        cols = ("#", "文件名", "T1 (℃)", "T2 (℃)", "H (μm)", "M (mg)", "状态")
        self.tree = ttk.Treeview(tbl, columns=cols, show="headings",
                                 height=6, selectmode="browse")

        ts = ttk.Style()
        ts.configure("Tech.Treeview",
                     background=THEME["bg3"], fieldbackground=THEME["bg3"],
                     foreground=THEME["text"], font=FONT_MONO_S,
                     rowheight=24, borderwidth=0)
        ts.configure("Tech.Treeview.Heading",
                     background=THEME["header_bg"], foreground=THEME["accent"],
                     font=FONT_UI_B, relief="flat")
        ts.map("Tech.Treeview",
               background=[("selected", THEME["accent2"])],
               foreground=[("selected", "#ffffff")])
        self.tree.config(style="Tech.Treeview")

        for col, w in zip(cols, [32, 180, 72, 72, 80, 72, 130]):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w, anchor="center",
                             stretch=(col == "文件名"))
        self.tree.column("文件名", anchor="w")
        self.tree.tag_configure("ok",    foreground=THEME["success"])
        self.tree.tag_configure("error", foreground=THEME["error"])
        self.tree.tag_configure("warn",  foreground=THEME["warning"])

        tsb = ttk.Scrollbar(tbl, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tsb.pack(side="right", fill="y")

        # 日志面板
        tk.Label(parent, text="🖥  运行日志", font=FONT_UI_B,
                 bg=THEME["bg"], fg=THEME["accent"],
                 anchor="w", pady=2).pack(fill="x")

        log_outer = tk.Frame(parent, bg=THEME["bg3"], bd=1,
                             highlightbackground=THEME["border"],
                             highlightthickness=1)
        log_outer.pack(fill="both", expand=True)

        log_sb = tk.Scrollbar(log_outer, bg=THEME["bg2"],
                              troughcolor=THEME["bg"])
        log_sb.pack(side="right", fill="y")

        self.log_text = tk.Text(
            log_outer, bg=THEME["log_bg"], fg=THEME["text"],
            font=FONT_MONO, wrap="none",
            insertbackground=THEME["accent"],
            selectbackground=THEME["accent2"],
            relief="flat", bd=0, padx=6, pady=5, state="disabled",
            yscrollcommand=log_sb.set)
        self.log_text.pack(side="left", fill="both", expand=True, padx=4, pady=2)
        log_sb.config(command=self.log_text.yview)

        for tag, clr in [
            ("ts",     THEME["text_dim"]), ("info",   THEME["text"]),
            ("ok",     THEME["success"]),  ("warn",   THEME["warning"]),
            ("error",  THEME["error"]),    ("sep",    THEME["accent2"]),
            ("dim",    THEME["text_dim"]), ("accent", THEME["accent"]),
        ]:
            self.log_text.tag_config(tag, foreground=clr)
        for tag, clr in GAME_MODE_TAG_COLORS.items():
            self.log_text.tag_config(tag, foreground=clr)

        lb = tk.Frame(parent, bg=THEME["bg"])
        lb.pack(fill="x", pady=(2, 0))
        _btn(lb, "清空日志", self._clear_log, bg=THEME["muted_btn"], width=10).pack(side="right")

    # ── 时钟 ─────────────────────────────────────────────────────────
    def _update_clock(self):
        try:
            self.lbl_clock.config(
                text=datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
        except tk.TclError:
            return
        self.root.after(1000, self._update_clock)

    # ════════════════════════════════════════════════════════════════
    # 日志系统（队列批量刷新）
    # ════════════════════════════════════════════════════════════════
    _BADGES = {
        "info":  " INFO ", "ok":    "  OK  ",
        "warn":  " WARN ", "error": "ERROR ",
        "sep":   "──────", "dim":   "      ",
        "accent":"  >>  ",
        "element_pyro":    "  >>  ",
        "element_hydro":   "  >>  ",
        "element_anemo":   "  >>  ",
        "element_electro": "  >>  ",
        "element_cryo":    "  >>  ",
        "element_geo":     "  >>  ",
        "element_dendro":  "  >>  ",
        "ak_vanguard":     "  >>  ",
        "ak_guard":        "  >>  ",
        "ak_defender":     "  >>  ",
        "ak_sniper":       "  >>  ",
        "ak_caster":       "  >>  ",
        "ak_medic":        "  >>  ",
        "ak_supporter":    "  >>  ",
        "ak_specialist":   "  >>  ",
        "honor_fighter":   "  >>  ",
        "honor_mage":      "  >>  ",
        "honor_marksman":  "  >>  ",
        "honor_assassin":  "  >>  ",
        "honor_support":   "  >>  ",
        "honor_tank":      "  >>  ",
    }

    def _log(self, msg: str, level: str = "info"):
        ts    = datetime.datetime.now().strftime("%H:%M:%S.%f")[:12]
        badge = self._BADGES.get(level, " INFO ")
        self._log_queue.append((ts, badge, msg, level))
        if self._log_flush_id is None:
            self._log_flush_id = self.root.after(
                self._LOG_FLUSH_INTERVAL, self._flush_log)

    def _flush_log(self):
        self._log_flush_id = None
        if not self._log_queue:
            return
        items = self._log_queue[:]
        self._log_queue.clear()
        self.log_text.config(state="normal")
        for ts, badge, msg, level in items:
            self.log_text.insert("end", f"[{ts}]", "ts")
            self.log_text.insert("end", f" [{badge}] ", level)
            if isinstance(msg, (list, tuple)):
                for chunk, tag in msg:
                    self.log_text.insert("end", str(chunk), tag or level)
                self.log_text.insert("end", "\n", level)
            else:
                self.log_text.insert("end", str(msg) + "\n", level)
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _clear_log(self):
        self._log_queue.clear()
        if self._log_flush_id is not None:
            try:
                self.root.after_cancel(self._log_flush_id)
            except Exception:
                pass
            self._log_flush_id = None
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    # ── 进度 / 状态 ──────────────────────────────────────────────────
    def _set_progress(self, val: float):
        def _do():
            self.progress.config(value=val)
            self.lbl_pct.config(
                text=f"{val:.0f} %",
                fg=THEME["accent"] if val < 100 else THEME["success"])
        self.root.after(0, _do)

    def _set_status_bar(self, msg: str, color: str = None):
        c = color or THEME["text_dim"]
        self.root.after(0, lambda: self.lbl_status_bar.config(text=msg, fg=c))

    # ── 文件操作 ─────────────────────────────────────────────────────
    def _select_files(self):
        files = filedialog.askopenfilenames(
            title="选择 TMA 数据文件（可多选）",
            filetypes=[("所有文件", "*.*"), ("TAJM 001", "*.001"),
                       ("TAJM 002", "*.002"), ("文本文件", "*.txt")])
        if not files:
            return
        existing = set(self.files)
        added    = [f for f in files if f not in existing]
        self.files.extend(added)
        for f in added:
            self.lb_files.insert("end", os.path.basename(f))
        self._refresh_file_count()
        if added:
            self._log(f"新增 {len(added)} 个文件", "accent")
            for f in added:
                self._log(f"  ↳ {os.path.basename(f)}", "dim")

    def _remove_selected(self):
        sel = self.lb_files.curselection()
        if not sel:
            return
        idx  = sel[0]
        name = os.path.basename(self.files[idx])
        self.files.pop(idx)
        self.lb_files.delete(idx)
        self._refresh_file_count()
        self._log(f"已移除：{name}", "warn")

    def _clear_files(self):
        self.files.clear()
        self.lb_files.delete(0, "end")
        self._refresh_file_count()
        self._log("已清空文件列表", "warn")

    def _refresh_file_count(self):
        n = len(self.files)
        self.lbl_file_count.config(
            text=f"共 {n} 个文件",
            fg=THEME["accent"] if n > 0 else THEME["text_dim"])

    def _build_run_options(self, parent):
        """路径配置下方的游戏模式单选项。多线程模式为隐藏开关，不在界面显示。"""
        opt = tk.Frame(parent, bg=THEME["bg2"])
        opt.pack(fill="x", padx=10, pady=(5, 9))

        tk.Label(opt, text="看板模式", font=FONT_UI_B,
                 bg=THEME["bg2"], fg=THEME["text_dim"],
                 padx=0).pack(side="left", padx=(0, 8))

        self._mode_radios = []

        def _refresh_mode_buttons():
            for rb, value in getattr(self, "_mode_radios", []):
                selected = (self.var_game_mode.get() == value)
                rb.config(
                    bg=THEME["radio_active"] if selected else THEME["radio_bg"],
                    fg="#FFFFFF" if selected else THEME["text"],
                    activebackground=THEME["radio_hover"],
                    activeforeground=THEME["accent"],
                )

        def _mode_radio(text, value, pad=(0, 8)):
            rb = tk.Radiobutton(
                opt, text=text, value=value, variable=self.var_game_mode,
                indicatoron=False, command=_refresh_mode_buttons,
                bg=THEME["radio_bg"], fg=THEME["text"],
                selectcolor=THEME["radio_active"],
                activebackground=THEME["radio_hover"], activeforeground=THEME["accent"],
                font=FONT_UI, relief="flat", bd=0, highlightthickness=0,
                padx=12, pady=5, cursor="hand2"
            )
            rb.pack(side="left", padx=pad)
            self._mode_radios.append((rb, value))

            def _enter(_):
                if self.var_game_mode.get() != value:
                    rb.config(bg=THEME["radio_hover"], fg=THEME["accent"])

            def _leave(_):
                _refresh_mode_buttons()

            def _press(_):
                rb.config(bg=_shade_color(THEME["radio_active"], -0.10), fg="#FFFFFF")

            rb.bind("<Enter>", _enter, add="+")
            rb.bind("<Leave>", _leave, add="+")
            rb.bind("<ButtonPress-1>", _press, add="+")
            rb.bind("<ButtonRelease-1>", lambda e: self.root.after(10, _refresh_mode_buttons), add="+")
            return rb

        _mode_radio("原神", "genshin")
        _mode_radio("明日方舟", "arknights")
        _mode_radio("王者荣耀", "honor", pad=(0, 0))
        self.root.after(0, _refresh_mode_buttons)

    def _emit_genshin_quote(self):
        """游戏模式：按当前单选模式随机输出一条语录，并返回角色/属性信息。"""
        mode_key = "genshin"
        try:
            mode_key = str(self.var_game_mode.get() or "genshin")
        except Exception:
            mode_key = "genshin"
        if mode_key not in GAME_MODE_DEFS:
            mode_key = "genshin"
            try:
                self.var_game_mode.set(mode_key)
            except Exception:
                pass

        mode_def = GAME_MODE_DEFS[mode_key]
        item = random.choice(mode_def.get("quotes") or [])
        quote = random.choice(item.get("quotes") or [""])
        attr_key = mode_def.get("attr_key") or "attribute"
        attr = str(item.get(attr_key) or item.get("element") or item.get("attribute") or "")
        tag = (mode_def.get("tag_map") or {}).get(attr, "accent")
        character = str(item.get("character") or "角色")
        region = str(item.get("region") or "")

        # 日志格式不显示模式前缀：角色：语录
        self._log(f"{character}：{quote}", tag)
        return {
            "mode": mode_key,
            "mode_display": mode_def.get("display", "游戏模式"),
            "region": region,
            "character": character,
            "attribute": attr,
            "element": attr,
            "tag": tag,
            "quote": quote,
        }

    def _log_parts(self, parts, level: str = "info"):
        """插入可局部着色的日志行。parts=[(text, tag), ...]。"""
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:12]
        badge = self._BADGES.get(level, " INFO ")
        self._log_queue.append((ts, badge, list(parts), level))
        if self._log_flush_id is None:
            self._log_flush_id = self.root.after(
                self._LOG_FLUSH_INTERVAL, self._flush_log)

    def _log_sample_header(self, idx: int, total: int, stem: str, quote_meta=None, prefix: str = ""):
        """样品开始处理日志；批次号按刚发送的角色元素色显示。"""
        tag = (quote_meta or {}).get("tag") or "info"
        parts = [(f"[{idx}/{total}]  ", "info")]
        if prefix:
            parts.append((prefix, "info"))
        parts.append((str(stem), tag))
        self._log_parts(parts, "info")

    def _browse_xlsx(self):
        p = filedialog.askopenfilename(
            title="选择 TMA称量数据.xlsx",
            filetypes=[("Excel 文件", "*.xlsx *.xls")])
        if p:
            self.var_xlsx.set(p)

    def _browse_tp_dir(self):
        p = filedialog.askdirectory(
            title="选择图片输出目录",
            initialdir=self.var_tp_dir.get())
        if p:
            self.var_tp_dir.set(p)
            self._log(f"图片输出目录 → {p}", "accent")

    # ── 运行 ─────────────────────────────────────────────────────────
    def _run(self):
        if not self.files:
            messagebox.showwarning("提示", "请先选择要处理的文件。",
                                   parent=self.root)
            return
        if not _HAS_OPENPYXL:
            messagebox.showwarning(
                "缺少依赖",
                "未安装 openpyxl，无法读取称量数据。\n"
                "可执行：pip install openpyxl\n\n"
                "将继续处理，M 列全部填 N/A。",
                parent=self.root)
        for row in self.tree.get_children():
            self.tree.delete(row)
        self.btn_run.config(state="disabled")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            self._run_inner()
        except Exception as e:
            self._log(f"未预期的异常：{e}", "error")
            self._log(traceback.format_exc(), "error")
            self._set_status_bar("● 异常终止", THEME["error"])
        finally:
            self.root.after(0, lambda: self.btn_run.config(state="normal"))

    def _run_inner(self):
        tp_dir    = self.var_tp_dir.get().strip() or TP_DIR_DEFAULT
        xlsx_display_path = self.var_xlsx.get().strip() or WEIGHT_XLSX_DEFAULT
        xlsx_path = resolve_weight_xlsx_runtime_path(xlsx_display_path, log_cb=self._log)
        os.makedirs(tp_dir, exist_ok=True)

        ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join(SCRIPT_DIR, f"Piliang_{ts}.csv")
        files    = list(self.files)
        n        = len(files)
        use_threads = bool(self.var_enable_threads.get())

        self._log("━" * 52, "sep")
        self._log(f"批量处理开始 · 共 {n} 个文件", "accent")
        self._log(f"图片输出目录：{tp_dir}",        "dim")
        self._log(f"CSV 输出：    {csv_path}",      "dim")
        self._log(f"称量数据：    {xlsx_display_path}", "dim")
        if _norm_case_path(xlsx_path) == _norm_case_path(WEIGHT_XLSX_FALLBACK) and _norm_case_path(xlsx_display_path) == _norm_case_path(WEIGHT_XLSX_DEFAULT):
            self._log("派蒙：当前已切换为备用线路读取称量数据。", "warn")
        game_mode_key = self.var_game_mode.get() if hasattr(self, "var_game_mode") else "genshin"
        game_mode_display = GAME_MODE_DEFS.get(game_mode_key, GAME_MODE_DEFS["genshin"]).get("display", "原神模式")
        self._log(f"处理模式：    {'多线程' if use_threads else '单线程'}", "dim")
        self._log(f"游戏模式：    {game_mode_display}", "dim")
        self._log("━" * 52, "sep")
        self._set_progress(0)
        self._set_status_bar("● 处理中…", THEME["warning"])

        headers = ["文件名", "T1 (℃)", "T2 (℃)", "H (μm)", "M (mg)", "图片路径", "备注"]
        rows    = []

        def _record_result(i, fp, result):
            stem = os.path.splitext(os.path.basename(fp))[0]
            if result["error"]:
                first_line = result["error"].split("\n")[0]
                rows.append([stem, "ERROR", "ERROR", "ERROR", "ERROR", "", first_line])
                self._add_tree_row(i, stem, "ERROR", "ERROR", "ERROR", "ERROR",
                                   f"✗ {first_line}", "error")
            else:
                T1s   = format_plot_temp_c(result["T1"]) if result["T1"] is not None else "N/A"
                T2s   = format_plot_temp_c(result["T2"]) if result["T2"] is not None else "N/A"
                Hs    = format_height_um(result["H"])    if result["H"]  is not None else "N/A"
                M_raw = result["M"]
                try:
                    Ms = f"{float(M_raw):.4f}" if M_raw is not None else "N/A"
                except Exception:
                    Ms = str(M_raw)
                warn = result["M_warn"] or ""
                png  = result["png"]    or ""

                tag  = "warn" if warn else "ok"
                stat = "⚠ M未匹配" if warn else "✓ 完成"
                rows.append([stem, T1s, T2s, Hs, Ms, png, warn])
                self._add_tree_row(i, stem, T1s, T2s, Hs, Ms, stat, tag)

        if use_threads and n > 1:
            max_workers = min(4, n)
            self._log(f"多线程启动：workers={max_workers}", "accent")
            done_count = 0
            future_map = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
                for i, fp in enumerate(files, 1):
                    stem = os.path.splitext(os.path.basename(fp))[0]
                    quote_meta = self._emit_genshin_quote()
                    self._log_sample_header(i, n, stem, quote_meta, prefix="入队：")
                    fut = ex.submit(process_one, fp, tp_dir, xlsx_path, self._log)
                    future_map[fut] = (i, fp)
                for fut in concurrent.futures.as_completed(future_map):
                    i, fp = future_map[fut]
                    stem = os.path.splitext(os.path.basename(fp))[0]
                    self._set_status_bar(f"● 多线程处理中  {done_count + 1}/{n}：{stem}", THEME["warning"])
                    try:
                        result = fut.result()
                    except Exception as e:
                        result = dict(error=f"{e}\n{traceback.format_exc()}", M_warn=None, T1=None, T2=None, H=None, M=None, png=None)
                    _record_result(i, fp, result)
                    done_count += 1
                    self._set_progress(done_count / n * 100)
        else:
            for i, fp in enumerate(files, 1):
                if i > 1:
                    self._log("━" * 52, "sep")
                stem = os.path.splitext(os.path.basename(fp))[0]
                self._set_status_bar(f"● 处理中  {i}/{n}：{stem}", THEME["warning"])
                quote_meta = self._emit_genshin_quote()
                self._log_sample_header(i, n, stem, quote_meta)

                # 传入 log_cb，process_one 内部会逐步打印解密/分析/结果日志
                result = process_one(fp, tp_dir, xlsx_path, log_cb=self._log)
                _record_result(i, fp, result)
                self._set_progress(i / n * 100)

        try:
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerows([headers] + rows)
            self._log(f"CSV 已保存：{csv_path}", "ok")
            self.root.after(0, lambda: self.lbl_csv_hint.config(
                text=f"CSV → {os.path.basename(csv_path)}",
                fg=THEME["success"]))
        except Exception as e:
            self._log(f"CSV 保存失败：{e}", "error")

        self._set_progress(100)
        self._set_status_bar(f"● 完成  {n}/{n}", THEME["success"])
        self._log("━" * 52, "sep")
        self._log("批量处理完成！", "accent")
        self._emit_mascot_board()
        self._log("━" * 52, "sep")

    def _emit_mascot_board(self):
        """每次批量处理完成后，在日志框输出当前模式的看板娘文字图。"""
        try:
            mode_key = str(self.var_game_mode.get() or "genshin")
        except Exception:
            mode_key = "genshin"
        lines = MASCOT_BOARD_LINES.get(mode_key) or MASCOT_BOARD_LINES.get("genshin") or []
        tag = {
            "genshin": "element_anemo",
            "arknights": "ak_caster",
            "honor": "honor_marksman",
        }.get(mode_key, "accent")
        self._log("看板娘文字图：", "accent")
        for line in lines:
            self._log(line, tag)

    def _add_tree_row(self, idx, stem, t1, t2, h, m, status, tag):
        # after_idle：主循环空闲时执行，避免堆积阻塞
        self.root.after_idle(
            lambda: self.tree.insert("", "end",
                                     values=(idx, stem, t1, t2, h, m, status),
                                     tags=(tag,)))


# ══════════════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════════════

def main():
    root = tk.Tk()
    root.withdraw()                    # 先隐藏，避免闪白框
    root.overrideredirect(True)        # 去掉原生标题栏/边框
    # 根窗口背景色 = 边框色，子 Frame 内缩 1px 即可形成细边框视觉
    root.configure(bg=THEME["border"])

    app    = PiliangApp(root)
    splash = SplashScreen(root)

    # Splash 结束后居中显示主窗口
    # ⚠ withdraw 状态下 winfo_width/height 返回 1，不能用来定位
    #   直接用 _build_ui 里设定的目标尺寸
    _W, _H = 1060, 700

    def _show():
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x  = (sw - _W) // 2
        y  = max(0, (sh - _H) // 2)
        root.geometry(f"{_W}x{_H}+{x}+{y}")
        root.deiconify()
        root.lift()
        root.focus_force()

    root.after(SplashScreen.DURATION_MS + 160, _show)
    root.mainloop()


if __name__ == "__main__":
    main()
