# -*- coding: utf-8 -*-
"""
TMA 鏁版嵁鍒嗘瀽澶勭悊鍣紙TMA Super Max锛? v208

鏈剼鏈敤浜庡鐞?TA Instruments / TA Trios 瀵煎嚭鐨?TMA 鏁版嵁鏂囦欢锛屾彁渚涗互涓嬭兘鍔涳細
1) 璇诲彇鏂囨湰鏁版嵁锛?txt 绛夛級骞惰В鏋?StartOfData 鍚庣殑鏁板€煎尯娈点€?2) 瀵瑰父瑙佺殑 TAJM 浜岃繘鍒跺鍑猴紙甯歌鎵╁睍鍚?.001~.999锛夊皾璇曡В瀵嗗苟杞负鍙鏂囨湰銆?3) 鑷姩璇嗗埆 T1/T2锛?   - T2锛氶珮搴︼紙绗?3 鍒楋級鏈€澶у€煎搴旂殑娓╁害锛堢 2 鍒楋級
   - T1锛氬湪 x>=START_TEMP_FOR_T1 涓?x<=T2 鐨勫尯闂村唴锛岄珮搴︽渶灏忓€煎搴旂殑娓╁害
4) 鏇茬嚎鈥滄俯搴﹁酱鎷変几/鍘嬬缉鈥?warp)锛氭牴鎹敤鎴疯緭鍏ョ殑 T1n/T2n 璋冩暣鏇茬嚎褰㈢姸銆?   - 浣跨敤鈥滈€嗘槧灏勨€?inverse mapping) 鏂瑰紡锛岄伩鍏嶉敋鐐硅创杈瑰鑷寸殑鎻掑€煎钩鍙?寮傚父鎶樼嚎銆?   - 鍙€夊湪 [T1,T2] 鍖洪棿鍋氬崟璋冧慨澶嶏紝閬垮厤鍗曠偣鎺夎惤閫犳垚鈥滆寮€鐐光€濄€?5) 鎸?mg 瀵归珮搴︾缉鏀撅紝骞惰緭鍑?LG 鍒楄〃銆?6) Tkinter GUI锛氭棩蹇椼€佹搴?瓒呯骇姊害绠楁硶銆佺粯鍥句笌 TIFF 瀵煎嚭銆?
浠ｇ爜缁存姢绾﹀畾锛坴207 璧凤級锛?- 灏介噺涓烘瘡涓嚱鏁拌ˉ榻?docstring锛堢敤閫?鍙傛暟/杩斿洖/寮傚父/娉ㄦ剰浜嬮」锛夈€?- 鍏抽敭鍙橀噺锛堝叏灞€甯搁噺銆佺被鎴愬憳銆侀噸瑕佷腑闂撮噺锛夊鍔犺В閲婃€ф敞閲婏紝鏂逛究鍚庣画杩唬涓庢帓閿欍€?"""
VERSION = "v208"  # 鑴氭湰鐗堟湰鍙凤細鐢ㄤ簬绐楀彛鏍囬銆佹棩蹇椼€佸鍑哄浘鍙充笅瑙掔瓑鏄剧ず
# ------------ 鍏憡鍐呭 ------------
Gonggao_Message_by_thisone = ("蹇€熶笂鎵嬶細\n"  # 鍚姩/Soft Log 杈撳嚭鐨勨€滃揩閫熶笂鎵嬧€濊鏄庢枃鏈紙澶氳鎷兼帴锛?"  (1) 鐐瑰嚮銆愰€夋嫨鏂囦欢銆戣鍙?.txt 鎴?.001~.999 鏂囦欢锛氳嚜鍔ㄨ瘑鍒?T1/T2锛岃绠?H=H2-H1锛屽苟杈撳嚭 LG 鍒楄〃銆俓n"
"      * v208锛氳緭鍏ヨ矾寰勬敮鎸佷笅鎷夐鍒舵枃浠跺す锛堜粎鐢ㄤ簬蹇€熷畾浣嶏級锛屼篃鏀寔鎵嬪姩绮樿创/杈撳叆鏂囦欢鍏ㄨ矾寰勩€俓n"
"      * 浼氬皾璇曡В瀵?.001 绯诲垪鏂囦欢锛涜В瀵嗗け璐ヤ細鎻愮ず閿欒銆俓n"
"  (2) 濡傞渶鎵嬪姩淇锛氫慨鏀?T1/T2/mg 鍚庣偣鍑汇€愭墽琛岃皟鏁淬€戠敓鎴愭柊鏂囦欢锛堜笉褰卞搷鍘熸枃浠讹級銆俓n"
"  (3) 鑻?T1 璇嗗埆涓嶅噯锛氱偣鍑汇€愭搴︾畻娉曘€戞垨銆愯秴绾ф搴︾畻娉曘€戦噸鏂拌绠?T1锛圱2 濮嬬粓鍙栨渶澶у€硷級銆俓n"
"      * 涓よ€呭樊寮備富瑕佸湪鎵弿姝ラ暱/绮惧害銆俓n"
"  (4) 鐐瑰嚮銆愪娇鐢ㄧ粯鍥俱€戞墦寮€缁樺浘绐楀彛锛氬彲鍗曠嫭淇敼 mg锛堜粎褰卞搷鍥句腑澶囨敞锛夛紝骞跺鍑?.tif /銆愪豢鐢熻緭鍑恒€戙€俓n"
"      * 榛樿瀵煎嚭鍒板師鏂囦欢鍚岃矾寰勶紱涔熷彲鍕鹃€夈€愬惎鐢ㄦ柊璺緞銆戝悗瀵煎嚭鍒颁笅鎷夋鐩綍銆俓n"
"  (5) 杞欢濡傚嚭鐜板紓甯革細鍕鹃€夈€愨殸锔?DEBUG淇℃伅妯″紡銆戝彲鏌ョ湅鏇寸粏鐨勫嚱鏁扮骇鏃ュ織銆佽€楁椂/鍐呭瓨绛夈€?)
# ------------ usually ------------
import os
import re
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
# 璺緞鍒嗛殧绗︿慨姝ｏ紙Windows/Tk 甯歌锛歎NC 浠?//server/share/.. 褰㈠紡杩斿洖锛?# 鐩殑锛氶伩鍏嶅嚭鐜?鈥?../dir\file鈥?杩欑娣峰悎鍒嗛殧绗︼紝瀵艰嚧閮ㄥ垎鐜涓嬭鍐欏け璐ャ€?# -------------------------
def normalize_path_separators(p: str) -> str:
    """鎶婅矾寰勪腑鐨勫垎闅旂缁熶竴鎴愪竴绉嶉鏍硷紝骞舵竻鐞嗗彲鑳藉鑷寸郴缁熸姤閿欑殑鎺у埗瀛楃銆?
    瑙勫垯锛?    - 鍏堢Щ闄ゅ鍒?绮樿创鏃跺彲鑳芥贩鍏ョ殑鎺у埗瀛楃锛圽r銆乗n銆乗t銆乁nicode 鎹㈣绗︾瓑锛?      鍚﹀垯鍦?Windows 鍐欐枃浠舵椂鍙兘鍑虹幇: [Errno 22] Invalid argument
    - 鑻ヤ互 '//' 寮€澶达紙Tk 涓?UNC 甯歌鍐欐硶锛夛紝鎴?'/' 鏁伴噺 >= '\\' 鏁伴噺锛氱粺涓€涓?'/'
    - 鍚﹀垯缁熶竴涓?'\\'
    """
    if p is None:
        return ""
    p = str(p)
    if not p:
        return p

    # 1) 娓呯悊鎺у埗瀛楃锛堝父瑙佸氨鏄笉灏忓績绮樿创浜嗘崲琛屽鑷?...\n.001锛?    p = re.sub(r"[\r\n\t\v\f\u2028\u2029]", "", p)
    # 2) 杩涗竴姝ョЩ闄?ASCII 鎺у埗瀛楃 (0-31) 涓?DEL(127)
    p = "".join(ch for ch in p if (ord(ch) >= 32 and ord(ch) != 127))

    if not p:
        return p

    # Tk 鐨?UNC 缃戠粶璺緞甯镐负 //SERVER/Share/...
    if p.startswith("//") or (p.count("/") >= p.count("\\")):
        return p.replace("\\", "/")
    return p.replace("/", "\\")
# -------------------------
def join_keep_style(dir_path: str, name: str) -> str:
    """鎸?dir_path 鐨勫垎闅旂椋庢牸杩涜鎷兼帴锛岄伩鍏?join 閫犳垚娣峰悎鍒嗛殧绗︺€?""
    dir_path = normalize_path_separators(dir_path or "")
    if not dir_path:
        return name
    if dir_path.startswith("//") or (dir_path.count("/") >= dir_path.count("\\")):
        # 缁熶竴 '/'
        dp = dir_path.replace("\\", "/").rstrip("/")
        return dp + "/" + name
    # 缁熶竴 '\'
    dp = dir_path.replace("/", "\\").rstrip("\\")
    return dp + "\\" + name


def format_height_um(v: float) -> str:
    """楂樺害鏄剧ず瑙勫垯锛埼糾锛屼笉鍚崟浣嶏級锛?
    - |v| > 1000锛氫繚鐣欏埌涓綅锛堟棤灏忔暟锛?    - |v| <= 1000锛氫繚鐣?1 浣嶅皬鏁?    """
    try:
        if v is None:return "NA"
        v = float(v)
        if not math.isfinite(v):return "NA"
        if abs(v) > 1000.0:return f"{v:.0f}"
        return f"{v:.1f}"
    except Exception:return "NA"


# =========================
# 瑙ｅ瘑鏍稿績
# 璇存槑锛氫笉鍋氬悗缂€妫€娴嬶紱鍙鈥滆兘瑙ｅ瘑鈥濆氨瑙ｅ瘑銆?# 鏍稿績閫昏緫 UTF-16LE 澶撮儴 + float32(<5f>) 鏁版嵁琛ㄨВ鏋愶紝杈撳嚭涓哄彲璇荤殑 StartOfData + 5鍒楃函鏁板瓧銆?# =========================

def _tajm_find_header_end(buf: bytes, log=None) -> int:
    """
    澶撮儴鏄?UTF-16LE 鏂囨湰锛堝父瑙?ASCII+0 鐨勫舰寮忥級锛岄€氬父浠?CRLF 缁撴潫锛岀劧鍚庤繘鍏ヤ簩杩涘埗鍖恒€?    浠庡墠 64KB 鍐呭鎵炬渶鍚庝竴涓粛鐒跺儚鈥滄枃鏈ご閮ㄢ€濈殑 CRLF 浣嶇疆浣滀负澶撮儴缁撴潫銆?    """
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
        odd = window[1::2]  # UTF-16LE 楂樺瓧鑺?        zero_ratio = odd.count(0) / max(1, len(odd))
        if log:log(f"[tajm][header-scan] CRLF@{p} -> candidate={candidate}, odd_zero_ratio={zero_ratio:.3f}")
        if zero_ratio >= 0.55:
            last_good = candidate
            pos = candidate
        else:break
    if log:log(f"[tajm][header-scan] scanned_bytes={scan_limit}, crlf_hits={hits}, header_end={last_good}")
    if last_good is None:raise RuntimeError("TAJM: 鏈兘瀹氫綅 UTF-16LE 澶撮儴缁撴潫浣嶇疆锛堟壘涓嶅埌鍙潬鐨?CRLF 缁堢偣锛夈€?)
    return last_good


def _tajm_find_data_start_by_first_time(buf: bytes, search_from: int, log=None) -> int:
    """
    鏁版嵁鍖洪€氬父涓?5 涓?little-endian float32 缁勬垚鐨勮褰曪紙20 瀛楄妭/琛岋級銆?    浼樺厛瀵绘壘 time=0.004 鐨?float32锛涙壘涓嶅埌鍒欑敤鍚彂寮忔壂鎻忋€?    """
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

        # 绮楃暐鑼冨洿绾︽潫锛堝弬鑰?TAJM.py锛?        if not (0 <= t <= 1e6 and -500 <= temp <= 2000 and -1e7 <= dim <= 1e7 and
                -1e6 <= force <= 1e6 and -1e6 <= flow <= 1e6):
            continue

        # 鍐嶇湅涓嬩竴琛?time 鏄惁闈為€掑噺
        try:t2 = struct.unpack_from("<f", buf, start + 20)[0]
        except struct.error:continue

        if math.isfinite(t2) and t2 >= t:
            if log:log(f"[tajm][data-find] fallback hit at offset {start} -> first_row=(t={t}, temp={temp}, ..), next_t={t2}")
            return start
    raise RuntimeError("TAJM: 鏈兘瀹氫綅鏁版嵁鍖鸿捣鐐癸紙float32 琛級銆?)


def _tajm_parse_rows(buf: bytes, start: int, log=None, max_rows: int = 200000):
    """
    浠?start 寮€濮嬫寜 <5f> 璇诲彇璁板綍锛岀洿鍒伴亣鍒颁笉鍚堢悊鏁版嵁鍋滄銆?    """
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
    灏濊瘯鐢?TAJM 瑙ｅ瘑鎬濊矾鎶娾€滀簩杩涘埗/涓嶅彲璇烩€濇枃浠惰浆鎴愬彲璇诲彇鐨勬枃鏈€?    - 涓嶅仛鍚庣紑妫€娴嬶紙鎸変綘鐨勮姹傦級
    - 鍙垽鏂兘鍚︽垚鍔熻В瀵嗭細鎴愬姛鍒欒繑鍥?ok=True + text + rows 绛変俊鎭紱澶辫触杩斿洖 ok=False
    """
    t0 = datetime.datetime.now()
    r = {"ok": False, "input": in_path}

    try:
        if log:
            log(f"[tajm] try decrypt: {in_path}")

        if not os.path.isfile(in_path):
            raise FileNotFoundError(f"鎵句笉鍒版枃浠讹細{in_path}")

        with open(in_path, "rb") as f:buf = f.read()

        if len(buf) < 64:raise RuntimeError("鏂囦欢澶皬锛岀枒浼间笉鏄?TAJM 鍙В瀵嗘牸寮忋€?)

        if log:
            log(f"[tajm][io] file_size={len(buf)} bytes; leading_bytes={buf[:8].hex(' ')}")

        header_end = _tajm_find_header_end(buf, log=log)
        header_text = buf[:header_end].decode("utf-16le", errors="ignore")

        data_start = _tajm_find_data_start_by_first_time(buf, header_end, log=log)
        rows = _tajm_parse_rows(buf, data_start, log=log)

        if not rows:
            raise RuntimeError("TAJM: 鏈В鏋愬埌浠讳綍鏁版嵁璁板綍銆?)

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
            log(f"[tajm] 鉁?decrypt ok rows={len(rows)} header_end={header_end} data_start={data_start} elapsed={dt:.3f}s")
        return r

    except Exception as e:
        if log:
            log(f"[tajm] 鉂?decrypt failed: {e}")
        r["err"] = str(e)
        return r


def load_text_prefer_tajm(in_path: str, logger: logging.Logger) -> Tuple[str, dict]:
    """缁熶竴鍏ュ彛锛圴206 鏇寸ǔ锛夛細

    澶勭悊椤哄簭锛?    1) 鍏堟帰娴嬫枃浠跺ご鏄惁宸茬粡鏄€滃彲璇绘枃鏈?+ 鍚?StartOfData + 鏈夎繛缁暟鎹鈥濄€?       - 鑻ユ槸锛氱洿鎺ユ寜鏂囨湰璇诲彇锛堥伩鍏嶈瑙﹀彂 TAJM 瑙ｅ瘑锛?       - 鉁?淇 v205锛歎TF-16LE 鏃?BOM 鐨勭函鏂囨湰锛屾湁姒傜巼琚褰撴垚浜岃繘鍒跺幓瑙ｅ瘑锛屽鑷存洸绾挎暟鎹紓甯?    2) 鍚﹀垯灏濊瘯 TAJM 瑙ｅ瘑锛堜笉鍋氬悗缂€鍒ゆ柇锛涜兘瑙ｅ瘑灏辫В瀵嗭級
    3) 瑙ｅ瘑澶辫触鍐嶅洖閫€鍒拌嚜鍔ㄦ枃鏈鍙?
    杩斿洖锛?text, meta)
      meta: {"used": "tajm"/"plain", ...}
    """
    # --- 0) 蹇€熸帰娴嬶細鏄惁鈥滃儚绾枃鏈暟鎹枃浠垛€?---
    probe_meta: Dict[str, Any] = {"ok": False}

    try:
        with open(in_path, "rb") as f:
            head = f.read(512 * 1024)  # 512KB 瓒冲鍒ゆ柇 StartOfData + 鍓嶅嚑鐧捐鏁版嵁
    except Exception as e:
        head = b""
        probe_meta = {"ok": False, "err": f"head_read_failed: {e}"}

    if head:
        float_re = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")

        def _count_data_lines_after_marker(text: str, max_scan: int = 300) -> int:
            """缁熻 StartOfData 涔嬪悗鐨勨€滆繛缁暟鎹鈥濇暟閲忋€?            
            鐢ㄩ€旓細
                load_text_prefer_tajm() 鍦ㄥ喅瀹氣€滄妸鏂囦欢褰撶函鏂囨湰澶勭悊鈥濊繕鏄€滃皾璇?TAJM 瑙ｅ瘑鈥濇椂锛?                闇€瑕佷竴涓揩閫熶笖浣庢垚鏈殑鎺㈡祴鏂规硶锛氬鏋?StartOfData 鍚庨潰纭疄璺熺潃涓€娈佃繛缁殑鏁板瓧琛紝
                灏辨洿鍙兘鏄彲璇绘枃鏈紱鍙嶄箣鎵嶈€冭檻璧颁簩杩涘埗瑙ｅ瘑銆?            
            鍙傛暟锛?                text: 宸茶В鐮佹枃鏈€?                max_scan: 鏈€澶ф壂鎻忚鏁帮紙閬垮厤宸ㄥぇ鏂囦欢鎵弿杩囨參锛夈€?            
            杩斿洖锛?                int锛氳繛缁暟鎹鐨勬暟閲忥紙鐢ㄤ簬鍋氶槇鍊煎垽鏂級銆?            """
            
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

        # 鏃?BOM 涔熷皾璇曪紙errors=ignore 浠呯敤浜庘€滄帰娴嬧€濓紝鐪熷疄璇诲彇浜ょ粰 read_text_auto锛?        for enc in ("utf-16le", "utf-16be", "utf-8", "gbk"):
            try:
                decode_attempts.append((enc, head.decode(enc, errors="ignore")))
            except Exception:
                continue

        best = {"enc": None, "data_lines": 0}
        for enc, s in decode_attempts:
            n = _count_data_lines_after_marker(s)
            if n > best["data_lines"]:
                best = {"enc": enc, "data_lines": n}

        # 缁忛獙闃堝€硷細>=5 琛屽熀鏈彲鍒ゅ畾涓虹湡瀹炴暟鎹?        if best["data_lines"] >= 5:
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
            # 鎺㈡祴璁や负鏄函鏂囨湰锛屼絾瀹屾暣璇诲彇澶辫触锛氱户缁蛋鍚庣画娴佺▼锛堜笉鐩存帴鎶ラ敊锛?            logger.debug(f"绾枃鏈帰娴嬪懡涓絾璇诲彇澶辫触锛屽皢缁х画灏濊瘯 TAJM 瑙ｅ瘑锛歿e}")

    # --- 1) 鍐嶅皾璇曡В瀵嗭紙涓嶅仛鍚庣紑鍒ゆ柇锛?---
    r = try_tajm_decrypt_to_text(in_path, log=logger.debug)
    if r.get("ok"):
        return r["text"], {"used": "tajm", **r}

    # --- 2) 鍥為€€鍒拌嚜鍔ㄦ枃鏈鍙?---
    text = read_text_auto(in_path, logger)
    return text, {"used": "plain", "reason": "fallback_after_tajm_failed", "tajm_err": r.get("err")}


# =========================
# 鍙皟鍙傛暟
# =========================
START_TEMP_FOR_T1 = 60.0   # 浣犺鈥滄暟鎹紑濮?60鈩冮檮杩?鈥濓紝榛樿浠?=60寮€濮嬫壘T1
MONOTONIC_FIX_T1_T2 = True  # 淇锛氬己鍒跺湪[T1,T2]鍖洪棿楂樺害鍗曡皟涓嶄笅闄嶏紝閬垮厤鍑虹幇鈥滆寮€鐐光€?MONOTONIC_METHOD = "bridge"  # bridge(绾挎€фˉ鎺ユ帀鐐? / isotonic(骞虫粦) / cummax(纭挸鍒?
# 濡傛灉鏂囦欢娌℃湁 StartOfData 鏍囪锛堟瀬灏戞暟鎯呭喌锛夛紝鐢ㄦ俯搴﹁寖鍥磋繃婊ゆ帀澶撮儴涔卞叆鐨勬暟瀛椼€?FALLBACK_TEMP_MIN = 40.0
FALLBACK_TEMP_MAX = 400.0
NUM_EXT_PATTERNS = tuple(f"*.{i:03d}" for i in range(1, 1000))  # 鍏煎 Windows 鏂囦欢瀵硅瘽妗嗚繃婊?FLOAT_FIND_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")

# =========================
# 杈撳叆璺緞涓嬫媺妗嗭紙v208锛?# 璇存槑锛氳繖浜涙槸鈥滈鍒剁殑甯哥敤鏂囦欢澶硅矾寰勨€濓紝鐢ㄤ簬鏇村揩瀹氫綅缃戠粶鐩樼洰褰曘€?# 鐢ㄦ埛浠嶉渶鍦ㄨ鐩綍鍐呴€夋嫨鍏蜂綋鏂囦欢锛?txt / .001~.999锛夈€?# =========================
PRESET_INPUT_DIRS = (
    r"//192.168.0.105/ta/Data/TMA/涓夋槑鏍峰搧",
    r"//192.168.0.105/ta/Data/TMA",
    r"//192.168.0.105/ta/Data/TMA/瀹為獙瀹ゆ牱鍝?",
)



def get_desktop_path() -> str:
    r"""灏藉彲鑳借繑鍥炲綋鍓嶇數鑴戞闈㈢粷瀵硅矾寰勶紙鐢ㄤ簬鍑哄浘璺緞涓嬫媺椤癸級銆?
    - 浼樺厛 ~/Desktop
    - Windows 甯歌 OneDrive 妗岄潰锛?OneDrive%\Desktop / %OneDriveConsumer%\Desktop
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
    nums: List[float]               # 鏈鎵€鏈夆€滄暟瀛梩oken鈥?    spans: List[Tuple[int, int]]    # 姣忎釜鏁板瓧token鍦ㄥ師琛屼腑鐨?(start,end)


def read_utf16le_no_bom(path: str) -> str:
    """寮哄埗鎸?UTF-16LE 璇诲彇锛屽苟鍘绘帀鏂囦欢寮€澶寸殑 BOM锛堣嫢瀛樺湪锛夈€?""
    with open(path, "rb") as f:
        data = f.read()
    # UTF-16LE BOM: FF FE
    if data[:2] == bytes((255, 254)):
        data = data[2:]
    text = data.decode("utf-16le", errors="strict")
    # 淇濋櫓锛氭瀬灏戞暟鎯呭喌涓嬭В鐮佸悗浠嶆畫鐣?BOM 瀛楃
    bom = chr(65279)
    if text.startswith(bom):
        text = text[len(bom):]
    return text


def write_utf16le_with_bom(path: str, text: str) -> None:
    """浠?UTF-16LE 鍐欏叆锛屽苟鍐欏叆 BOM(FF FE)銆?
    璇存槑锛?    - 浣犱箣鍓嶈姹傗€滃幓闄?BOM鈥濇椂锛屾垜浠緭鍑虹殑鏄€淯TF-16LE 鏃?BOM鈥濄€?      浣嗕笉灏?Windows 杞欢/缂栬緫鍣ㄤ細鍥犱负娌℃湁 BOM 鑰屾妸鏂囦欢鏄剧ず鎴?ANSI/ASCII銆?    - 濡傛灉浣犲笇鏈涘畠琚ǔ瀹氳瘑鍒负鈥淯TF-16 LE鈥濓紝灏遍渶瑕佷繚鐣?BOM銆?    """
    bom_char = chr(65279)
    if text.startswith(bom_char):
        text = text[len(bom_char):]

    data = b"\xff\xfe" + text.encode("utf-16le")
    with open(path, "wb") as f:
        f.write(data)




def read_text_auto(path: str, logger: Optional[logging.Logger] = None) -> str:
    """灏介噺鑷姩璇嗗埆缂栫爜璇诲彇鏂囨湰锛圴206 鏇寸ǔ锛夈€?
    璇嗗埆浼樺厛绾э細
    1) BOM锛歎TF-16(LE/BE) / UTF-8-SIG
    2) 鏃?BOM锛氶€氳繃閲囨牱鍒ゆ柇鏄惁鍍?UTF-16 鏂囨湰锛圢UL 姣斾緥 + 濂囧伓浣?0 姣斾緥锛?    3) 鍚﹀垯渚濇灏濊瘯 UTF-8銆丟BK

    杩斿洖锛?    - 瑙ｇ爜鍚庣殑鏂囨湰锛堝鏂囨湰棣栧瓧绗︿负 BOM 瀛楃锛屼細琚Щ闄わ級
    """
    with open(path, "rb") as f:
        data = f.read()

    if not data:
        return ""

    def _strip_bom_char(s: str) -> str:
        """绉婚櫎瀛楃涓插紑澶寸殑 BOM 瀛楃锛圲+FEFF锛夈€?        
        璇存槑锛?            鏌愪簺瑙ｇ爜璺緞浼氭妸 BOM 淇濈暀涓烘枃鏈涓€涓瓧绗︼紝
            鍚庣画瀛楃涓插尮閰嶏紙濡?StartOfData锛変細鍙楀埌褰卞搷锛屽洜姝ょ粺涓€鍓ョ銆?        """
        
        bom_char = chr(65279)  # U+FEFF
        return s[len(bom_char):] if s.startswith(bom_char) else s

    # 1) UTF-8 BOM
    if data.startswith(b"\xef\xbb\xbf"):
        try:
            text = data.decode("utf-8-sig", errors="strict")
            text = _strip_bom_char(text)
            if logger:
                logger.debug(f"璇诲彇鏂囦欢鎴愬姛锛氱紪鐮?utf-8-sig锛堝惈BOM锛夛紝瀛楄妭鏁?{len(data)}")
            return text
        except Exception as e:
            if logger:
                logger.debug(f"灏濊瘯 utf-8-sig 璇诲彇澶辫触锛歿e}")

    # 2) UTF-16 BOM锛圥ython 浼氫緷鎹?BOM 閫夋嫨绔簭锛?    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        try:
            text = data.decode("utf-16", errors="strict")
            text = _strip_bom_char(text)
            if logger:
                logger.debug(f"璇诲彇鏂囦欢鎴愬姛锛氱紪鐮?utf-16锛堢敱BOM鍐冲畾绔簭锛夛紝瀛楄妭鏁?{len(data)}")
            return text
        except Exception as e:
            if logger:
                logger.debug(f"灏濊瘯 utf-16(BOM) 璇诲彇澶辫触锛歿e}")

    # 3) 鏃?BOM锛氬垽瀹氭槸鍚︹€滃儚 UTF-16 鏂囨湰鈥?    sample = data[:4096]
    if len(sample) >= 4 and (sample.count(0) / len(sample)) > 0.15:
        even = sample[0::2]
        odd = sample[1::2]
        even_zero = even.count(0) / max(1, len(even))
        odd_zero = odd.count(0) / max(1, len(odd))

        # UTF-16LE 甯歌锛歰dd_zero 楂橈紱UTF-16BE 甯歌锛歟ven_zero 楂?        if max(even_zero, odd_zero) >= 0.55:
            enc_guess = "utf-16le" if odd_zero >= even_zero else "utf-16be"
            try:
                text = data.decode(enc_guess, errors="strict")
                text = _strip_bom_char(text)
                if logger:
                    logger.debug(
                        f"璇诲彇鏂囦欢鎴愬姛锛氱紪鐮?{enc_guess}锛堟棤BOM鍚彂寮忥級锛?
                        f"nul_ratio={sample.count(0)/len(sample):.3f}, odd_zero={odd_zero:.3f}, even_zero={even_zero:.3f}"
                    )
                return text
            except Exception as e:
                if logger:
                    logger.debug(f"灏濊瘯 {enc_guess}(鏃燘OM鍚彂寮? 璇诲彇澶辫触锛歿e}")

    # 4) 鍏朵粬缂栫爜锛歶tf-8 / gbk
    for enc in ("utf-8", "gbk"):
        try:
            text = data.decode(enc, errors="strict")
            text = _strip_bom_char(text)
            if logger:
                logger.debug(f"璇诲彇鏂囦欢鎴愬姛锛氱紪鐮?{enc}锛屽瓧鑺傛暟={len(data)}")
            return text
        except Exception as e:
            if logger:
                logger.debug(f"灏濊瘯 {enc} 璇诲彇澶辫触锛歿e}")

    raise UnicodeDecodeError("unknown", b"", 0, 1, "鏃犳硶璇嗗埆鏂囦欢缂栫爜锛坲tf-16/utf-8/gbk 鍧囧け璐ワ級")


def write_utf16le_no_bom(path: str, text: str) -> None:
    """浠?UTF-16LE 鍐欏叆锛堜笉鍐?BOM锛夛紝涓?ces.py 鐨勮緭鍑烘柟寮忎竴鑷淬€?""
    bom_char = chr(65279)
    if text.startswith(bom_char):
        text = text[len(bom_char):]
    with open(path, "w", encoding="utf-16le", newline="") as f:
        f.write(text)

def parse_lines(text: str) -> List[ParsedLine]:
    """鎶婃暣娈垫枃鏈寜琛岃В鏋愪负 ParsedLine 鍒楄〃銆?    
    瑙ｆ瀽瑙勫垯锛?        - 淇濈暀鍘熷琛屽唴瀹?raw锛堝惈鎹㈣绗︼紝渚夸簬鍥炲啓鏃朵笉鐮村潖鏍煎紡锛夈€?        - 浣跨敤 FLOAT_FIND_RE 鍦ㄦ瘡琛屾彁鍙栨墍鏈夋暟瀛?token锛屽苟璁板綍鍏跺湪鍘熻涓殑 span锛坰tart,end锛夈€?    
    杩斿洖锛?        List[ParsedLine]锛氭瘡琛屽搴斾竴涓?ParsedLine锛坮aw/nums/spans锛夈€?    
    娉ㄦ剰锛?        璇ュ嚱鏁板彧璐熻矗鈥滄彁鍙栨暟瀛?token鈥濓紝涓嶅垽鏂琛屾槸鍚︿负鐪熸鏁版嵁琛屻€?        鏁版嵁琛屽垽瀹氱敱 extract_xy_from_file() 璐熻矗銆?    """
    
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
    """浠?ParsedLine 涓彁鍙?(娓╁害x, 楂樺害y) 浠ュ強瀵瑰簲鐨勮绱㈠紩銆?
    鉁?鍏煎 3/4/5 鍒楀強浠ヤ笂锛?    - 鑷冲皯 3 涓暟瀛?token锛歯ums[1] 瑙嗕负娓╁害(鈩?锛宯ums[2] 瑙嗕负楂樺害(渭m)
    - 涓洪伩鍏嶆妸 header/娉ㄩ噴琛屽綋鎴愭暟鎹锛?        * 鑻ヨ鍐呭寘鍚櫎 e/E 涔嬪鐨勮嫳鏂囧瓧姣嶏紝閫氬父涓嶆槸绾暟鎹 -> 鐩存帴鎺掗櫎
        * 娓╁害闇€钀藉湪鍚堢悊鑼冨洿锛?500~2000鈩冿級

    鉁?鏁版嵁鍧楁彁鍙栫瓥鐣ワ細
    - 鍏堝畾浣嶅寘鍚?'StartOfData' 鐨勮锛堝拷鐣ュぇ灏忓啓锛夈€?    - 浠庡叾涓嬩竴琛屽紑濮嬶紝鍙鍙栤€滅湅璧锋潵鍍忕湡瀹炴暟鎹鈥濈殑杩炵画鍖烘銆?      涓€鏃﹀湪宸插紑濮嬭鍙栨暟鎹悗閬囧埌闈炴暟鎹锛屽氨璁や负鏁版嵁鍧楃粨鏉熷苟鍋滄
      锛堥伩鍏嶅熬閮?浜屾 header 缁х画姹℃煋 T1/T2锛夈€?    - 鑻ユ枃浠舵病鏈?StartOfData锛堟瀬灏戞暟锛夛細鍥為€€鍒版俯搴﹁寖鍥磋繃婊?      x鈭圼FALLBACK_TEMP_MIN, FALLBACK_TEMP_MAX]銆?    """
    xs: List[float] = []
    ys: List[float] = []
    line_idxs: List[int] = []

    marker_idx: Optional[int] = None
    for i, pl in enumerate(parsed):
        if "startofdata" in (pl.raw or "").lower():
            marker_idx = i
            break

    # 鍖归厤鈥滈櫎 e/E 澶栫殑瀛楁瘝鈥濓細鐢ㄤ簬鎺掗櫎 header/鍗曚綅琛?    non_e_letter_re = re.compile(r"[A-DF-Za-df-z]")

    def is_data_line(pl: ParsedLine) -> bool:
        """鍒ゆ柇涓€琛?ParsedLine 鏄惁鍙互瑙嗕负鈥滄暟鎹鈥濄€?        
        鍒ゅ畾渚濇嵁锛堝亸淇濆畧锛岀洰鐨勬槸閬垮厤 header 鏁板瓧姹℃煋锛夛細
            - 琛屼笉鑳戒负绌猴紱
            - 琛屽唴涓嶈兘鍖呭惈闄?e/E 涔嬪鐨勫瓧姣嶏紙閬垮厤鍗曚綅/鏍囬琛岋級锛?            - 鑷冲皯鍖呭惈 3 涓暟瀛?token锛堜繚璇佽兘鍙栧埌绗?鍒楁俯搴︿笌绗?鍒楅珮搴︼級銆?        
        杩斿洖锛?            bool锛歍rue=鍙綔涓烘暟鎹锛汧alse=璺宠繃銆?        """
        
        if pl is None:
            return False
        raw = (pl.raw or "").strip()
        if not raw:
            return False
        # 琛屽唴鍚櫎 e/E 澶栧瓧姣嶏細閫氬父涓嶆槸绾暟鎹?        if non_e_letter_re.search(raw):
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

        logger.debug(f"妫€娴嬪埌 StartOfData锛氭暟鎹捣濮嬭={marker_idx + 1}锛屾暟鎹鏁?{len(xs)}")
        return xs, ys, line_idxs

    # 鉂楁瀬灏戞暟鏂囦欢娌℃湁 StartOfData锛氬洖閫€杩囨护锛堟寜娓╁害鑼冨洿锛?    for idx, pl in enumerate(parsed):
        if is_data_line(pl):
            x = pl.nums[1]
            if FALLBACK_TEMP_MIN <= x <= FALLBACK_TEMP_MAX:
                xs.append(x)
                ys.append(pl.nums[2])
                line_idxs.append(idx)

    logger.debug(f"鏈娴嬪埌 StartOfData锛氫娇鐢ㄦ俯搴﹁寖鍥磋繃婊?[{FALLBACK_TEMP_MIN},{FALLBACK_TEMP_MAX}]锛屾暟鎹鏁?{len(xs)}")
    return xs, ys, line_idxs


def detect_T2_T1(xs: List[float], ys: List[float], logger: logging.Logger) -> Tuple[float, float]:
    """鎸夌敤鎴峰畾涔夎嚜鍔ㄨ瘑鍒?T1/T2锛圫tartOfData 鍚庢瘡琛?>=3 涓暟瀛楋細绗?涓?娓╁害锛岀3涓?楂樺害锛夈€?
    閫昏緫涓?tma_tem_right_v1.py 淇濇寔涓€鑷达細
    - T2锛氱涓夊垪(楂樺害)鐨勬渶澶у€兼墍瀵瑰簲鐨勭浜屽垪(娓╁害)銆?    - T1锛氬湪 x>=START_TEMP_FOR_T1 涓?x<=T2 鐨勮寖鍥村唴锛岀涓夊垪(楂樺害)鐨勬渶灏忓€兼墍瀵瑰簲鐨勭浜屽垪(娓╁害)銆?      鑻ヨ鑼冨洿鍐呮病鏈夌偣锛屽垯閫€鍖栦负 x<=T2 鐨勮寖鍥村唴瀵绘壘鏈€灏忓€笺€?    """
    if not xs:raise ValueError("鏂囦欢涓病鏈夊彲鐢ㄦ暟鎹偣锛堟棤娉曡В鏋愭俯搴?楂樺害锛夈€?)

    # T2锛氶珮搴︽渶澶у€煎搴旀俯搴?    max_i = max(range(len(ys)), key=lambda i: ys[i])
    T2 = xs[max_i]
    y_max = ys[max_i]

    # T1锛氫粠 x>=START_TEMP_FOR_T1 鍒?x<=T2 鑼冨洿鍐呯殑楂樺害鏈€灏忓€煎搴旀俯搴?    candidates = [i for i in range(len(xs)) if xs[i] >= START_TEMP_FOR_T1 and xs[i] <= T2]
    if not candidates:
        # 濡傛灉娌℃湁>=60鐨勭偣锛堟瘮濡傛暟鎹粠50寮€濮嬩笖寰堢煭锛夛紝閫€鍖栦负浠庢渶灏忔俯搴﹀埌T2
        candidates = [i for i in range(len(xs)) if xs[i] <= T2]
    if not candidates:
        # 鐞嗚鍏滃簳锛氬叏閲忔渶灏?        candidates = list(range(len(xs)))

    min_i = min(candidates, key=lambda i: ys[i])
    T1 = xs[min_i]
    y_min = ys[min_i]

    logger.debug(f"T2: max(height) 绱㈠紩={max_i}, 娓╁害={T2}, 楂樺害={y_max}")
    logger.debug(
        f"T1: min(height) 绱㈠紩={min_i}, 娓╁害={T1}, 楂樺害={y_min} "
        f"(鎼滅储鍖洪棿: x>= {START_TEMP_FOR_T1} 涓?x<=T2, 鍊欓€夌偣鏁?{len(candidates)})"
    )
    return T1, T2




def detect_T2_T1_precise(xs: List[float], ys: List[float], logger: logging.Logger, debug: bool = False) -> Tuple[float, float, Dict[str, Any]]:
    """姊害绠楁硶锛坴173锛?
    鐩爣锛氬湪鈥滃父瑙勨€漈1/T2 璇嗗埆涓嶇ǔ瀹氭椂锛岀敤鏇寸洿鎺ョ殑瑙勫垯鍋氫簩娆¤瘑鍒€?
    鏁版嵁瀹氫箟锛?    - x=娓╁害(鈩?, y=灏哄鍙樺寲(渭m)锛堝師楂樺害锛?    - T2锛氫粛鎸夋渶澶?y锛堟渶澶у嘲锛夌‘瀹氾紙閫昏緫涓嶅彉锛?    - T1锛堝崟宄板瀷锛夛細閬嶅巻鏁存暟娓╁害 x锛堟闀?1鈩冿級锛岃绠?        z = y(x-1), y0 = y(x), c = y(x+1)
      鑻ユ弧瓒筹細
        (c - y0) > 1 渭m  涓? (y0 - z) < 1 渭m
      鍒欒 (x, y0) 鍒ゅ畾涓?T1锛堝彇鏈€鍏堟弧瓒崇殑 x锛?
    - 澶氬嘲鍨嬶細鑻ユ渶澶у嘲涓庡叾宸︿晶鏈€杩戝嘲涔嬮棿瀛樺湪鏄庢樉宄拌胺锛屼笖宄拌胺娣卞害 > 100 渭m锛?      鍒欎互鈥滃乏渚у嘲鈥濅綔涓哄崟宄板瀷鐨勬悳绱笂闄愶紝璁＄畻 T1锛汿2 浠嶄负鏈€澶у嘲銆?    """

    meta: Dict[str, Any] = {"type": "mono", "confidence": 0.0}

    if len(xs) < 5 or len(ys) < 5:
        raise ValueError("鏁版嵁鐐硅繃灏戯紝鏃犳硶姊害绠楁硶")

    # 鍘婚噸銆佹帓搴忥紙閬垮厤閲嶅娓╁害瀵艰嚧鎻掑€煎紓甯革級
    xs2, ys2 = aggregate_duplicates(xs, ys)  # 鑱氬悎閲嶅 x
    pairs = [(x, y) for x, y in zip(xs2, ys2) if math.isfinite(x) and math.isfinite(y)]
    pairs.sort(key=lambda t: t[0])
    xp = [p[0] for p in pairs]
    yp = [p[1] for p in pairs]

    if len(xp) < 5:
        raise ValueError("鏈夋晥鏁版嵁鐐硅繃灏戯紝鏃犳硶姊害绠楁硶")

    # 绠€鍗曞钩婊戯紝鍑忓皯鍣０瀵瑰嘲/璋风殑褰卞搷
    y_arr = np.asarray(yp, dtype=float)
    if len(y_arr) >= 9:
        kernel = np.ones(9, dtype=float) / 9.0
        y_s = np.convolve(y_arr, kernel, mode="same")
    else:
        y_s = y_arr.copy()

    # T2锛氭渶澶у嘲
    idx2 = int(np.argmax(y_s))
    T2 = float(xp[idx2])
    H2 = float(y_arr[idx2])

    # 鏌ユ壘 T2 宸︿晶鏈€杩戠殑灞€閮ㄥ嘲锛岀敤浜庡宄板垽瀹?    peaks: List[int] = []
    for i in range(1, len(y_s) - 1):
        if (y_s[i] >= y_s[i - 1]) and (y_s[i] > y_s[i + 1]):
            peaks.append(i)
        elif (y_s[i] > y_s[i - 1]) and (y_s[i] >= y_s[i + 1]):
            peaks.append(i)

    left_peak_idx: Optional[int] = None
    for i in reversed(peaks):
        if i < idx2 - 1:
            left_peak_idx = i
            break

    is_multi = False
    valley_depth = 0.0
    end_temp = T2

    if left_peak_idx is not None:
        valley_min = float(np.min(y_s[left_peak_idx:idx2 + 1]))
        valley_depth = float(min(y_s[left_peak_idx], y_s[idx2]) - valley_min)
        if valley_depth > 100.0:
            is_multi = True
            end_temp = float(xp[left_peak_idx])
            meta["type"] = "multi"

    meta["valley_depth_um"] = float(valley_depth)
    meta["T2_height_um"] = float(H2)
    meta["T2_temp"] = float(T2)
    meta["T1_search_end_temp"] = float(end_temp)

    if debug:
        logger.debug(f"[precise] T2@x={T2:.4g}鈩? H2={H2:.4g}渭m, left_peak={xp[left_peak_idx]:.4g}鈩? valley_depth={valley_depth:.4g}渭m" if left_peak_idx is not None else f"[precise] T2@x={T2:.4g}鈩? H2={H2:.4g}渭m, no left peak")
        if is_multi:
            logger.debug(f"[precise] multi-peak detected -> T1 search end temp={end_temp:.4g}鈩?)

    # 绾挎€ф彃鍊艰幏寰?y(x)锛堜互骞虫粦鏇茬嚎涓哄噯锛?    def y_at(temp_c: float) -> float:
        """鎻掑€艰緟鍔╁嚱鏁帮細缁欏畾娓╁害锛堚剝锛夎繑鍥炲搴旂殑楂樺害 y銆?        
        璇存槑锛?            - 澶栧眰鍑芥暟浼氬厛鍑嗗濂?xp/fp锛堟垨鑱氬悎鍚庣殑 xs/ys锛夛紝杩欓噷浠呭仛绾挎€ф彃鍊煎皝瑁呫€?            - 杩欐牱鍐欑殑濂藉鏄妸鎻掑€肩粏鑺傞泦涓埌涓€涓嚱鏁帮紝渚夸簬璋冭瘯涓庢浛鎹€?        """
        
        return float(linear_interp(temp_c, xp, y_s.tolist()))

    # 鍗曞嘲鍨嬭鍒欙細鎸夋暣鏁版俯搴︽壂鎻?    t_start = int(math.ceil(xp[0])) + 1
    t_end = int(math.floor(end_temp)) - 1
    T1: Optional[float] = None

    if t_end >= t_start:
        for t in range(t_start, t_end + 1):
            z = y_at(t - 1.0)
            y0 = y_at(float(t))
            c = y_at(t + 1.0)
            if (c - y0) > 1.0 and (y0 - z) < 1.0:
                T1 = float(t)
                meta["confidence"] = 0.90 if not is_multi else 0.85
                if debug:
                    logger.debug(f"[precise] T1 hit @ {T1:.4g}鈩? z={z:.4g}, y={y0:.4g}, c={c:.4g} (c-y={c-y0:.4g}, y-z={y0-z:.4g})")
                break

    # 鍏滃簳锛氳嫢鏈懡涓鍒欙紝鍥為€€鍒扳€滃湪 end_temp 涔嬪墠鐨勬渶灏?y鈥?
    # 鉁?浜屾绮剧粏鎼滅储锛氬湪閫変腑鐨勬暣鏁扮偣闄勮繎 (T1-0.5 ~ T1+0.5) 鎸?0.1掳C 姝ラ暱婊戝姩锛?    # 鐢ㄥ悓鏍风殑 (x-1, x, x+1) 鍒ゅ畾鏉′欢绛涢€夋洿绮剧‘鐨?T1锛涜嫢澶氱偣婊¤冻锛屽彇 x 鏈€澶х殑閭ｄ釜銆?    if T1 is not None:
        fine_hits: List[float] = []
        fine_start = T1 - 0.5
        fine_end = T1 + 0.5
        # 0.1 姝ラ暱锛屽寘鍚鐐?        k = 0
        while True:
            tt = round(fine_start + 0.1 * k, 1)
            if tt > fine_end + 1e-9:
                break
            y_prev = y_at(tt - 1.0)
            y_mid = y_at(tt)
            y_next = y_at(tt + 1.0)
            if (y_next - y_mid) > 1.0 and (y_mid - y_prev) < 1.0:
                fine_hits.append(tt)
            k += 1

        if fine_hits:
            T1 = max(fine_hits)
            logger.debug(f"[precise] fine-scan hit count={len(fine_hits)} -> T1={T1:.3f}")

    if T1 is None:
        # 鍙?end_temp 涔嬪墠鐨勭偣锛堣嚦灏戜繚鐣?5鈩?浣欓噺锛岄伩鍏嶈创鐫€宄伴《锛?        end_x = end_temp - 5.0
        cand_idx = [i for i, x in enumerate(xp) if x <= end_x]
        if not cand_idx:
            cand_idx = list(range(max(0, idx2 - 50), idx2))  # 閫€鍖栵細鐢?T2 宸︿晶涓€灏忔
        i_min = min(cand_idx, key=lambda i: y_s[i])
        T1 = float(xp[i_min])
        meta["confidence"] = 0.40
        if debug:
            logger.debug(f"[precise] fallback T1=min y before end_temp -> T1={T1:.4g}鈩?(idx={i_min})")

    return float(T1), float(T2), meta
def detect_T2_T1_super_gradient(
    xs: List[float],
    ys: List[float],
    logger: logging.Logger,
    debug: bool = False,
) -> Tuple[float, float, Dict[str, Any]]:
    """
    瓒呯骇姊害绠楁硶锛氬湪鈥滄搴︾畻娉曗€濈殑缁撴灉鍩虹涓婏紝杩藉姞 0.01 姝ラ暱鐨勬渶鍚庢敹鏁涖€?    - 鍏堣皟鐢?detect_T2_T1_precise锛堟暣鏁扮偣 + 0.1 姝ラ暱绮句慨锛?    - 鍐嶅湪 seed卤0.1 鍐呯敤 0.01 姝ラ暱澶嶆牳鏉′欢锛屽彇婊¤冻鏉′欢鐨勬渶澶?x
    - T2 浠嶄负鏈€澶у嘲锛堜笌鏅€?姊害绠楁硶涓€鑷达級
    """
    T1_seed, T2, meta = detect_T2_T1_precise(xs, ys, logger, debug=debug)

    # 涓烘彃鍊煎噯澶囧崟璋?x锛堥伩鍏嶅師濮嬫暟鎹腑娓╁害閲嶅/涔卞簭瀵艰嚧鎻掑€煎紓甯革級
    pairs = sorted(zip(xs, ys), key=lambda t: t[0])
    xs_sorted, ys_sorted = zip(*pairs)
    xs_agg, ys_agg = aggregate_duplicates(list(xs_sorted), list(ys_sorted))

    window = 0.1
    step = 0.01

    def y_at(x: float) -> float:
        """鎻掑€艰緟鍔╁嚱鏁帮細缁欏畾娓╁害锛堚剝锛夎繑鍥炲搴旂殑楂樺害 y銆?        
        璇存槑锛?            - 澶栧眰鍑芥暟浼氬厛鍑嗗濂?xp/fp锛堟垨鑱氬悎鍚庣殑 xs/ys锛夛紝杩欓噷浠呭仛绾挎€ф彃鍊煎皝瑁呫€?            - 杩欐牱鍐欑殑濂藉鏄妸鎻掑€肩粏鑺傞泦涓埌涓€涓嚱鏁帮紝渚夸簬璋冭瘯涓庢浛鎹€?        """
        
        return linear_interp(x, xs_agg, ys_agg)

    candidates: List[float] = []
    x = T1_seed - window
    while x <= T1_seed + window + 1e-12:
        y = y_at(x)
        y_l = y_at(x - 1.0)
        y_r = y_at(x + 1.0)
        if (y_r - y) > 1.0 and (y - y_l) < 1.0:
            candidates.append(x)
        x = round(x + step, 12)

    meta["super_candidates"] = len(candidates)
    meta["super_step"] = step
    meta["super_window"] = window

    if candidates:
        T1 = max(candidates)
        meta["T1_super"] = T1
        if debug:
            logger.debug(f"瓒呯骇姊害锛?.01 绮句慨鍛戒腑 {len(candidates)} 涓€欓€夛紝鍙栨渶澶?x={T1}")
        return T1, T2, meta

    # 鍥為€€鍒?0.1 绮句慨缁撴灉
    meta["T1_super"] = T1_seed
    if debug:
        logger.debug("瓒呯骇姊害锛?.01 绮句慨鏈懡涓€欓€夛紝鍥為€€鍒?0.1 绮句慨缁撴灉")
    return T1_seed, T2, meta

def piecewise_map(x: float, xmin: float, xmax: float, T1o: float, T2o: float, T1n: float, T2n: float) -> float:
    """鍒嗘绾挎€ф槧灏勶細鍘熸俯搴?x_old -> 鏂版俯搴?x_new銆?
    鐩爣閿氱偣锛堢悊鎯虫儏鍐碉級锛?        [xmin, T1o] -> [xmin, T1n]
        [T1o, T2o] -> [T1n, T2n]
        [T2o, xmax] -> [T2n, xmax]

    鈿狅笍 鐪熷疄鏁版嵁閲岋紝鍙兘鍑虹幇 T1o鈮坸min 鎴?T2o鈮坸max锛堥敋鐐硅惤鍦ㄨ竟鐣岋級銆?    杩欎細瀵艰嚧鍖洪棿闀垮害瓒嬭繎 0锛屽紩鍙戞暟鍊间笉绋冲畾/鏇茬嚎寮傚父锛堟瘮濡傚熬閮ㄨ澶规垚涓€娈碘€滃钩鍙扳€濓級銆?    鍥犳杩欓噷鍋氣€滃畨鍏ㄩ檷绾р€濓細
    - 濮嬬粓淇濊瘉 xmin->xmin, xmax->xmax锛堜笉鍐嶇敤鈥滄暣浣撳钩绉烩€濈牬鍧忚竟鐣岋級
    - 瀵归€€鍖栧尯闂达紙鍒嗘瘝鈮?锛夛紝浣跨敤鏇寸ǔ濡ョ殑鍥為€€锛堝敖閲忎繚鎸佸師 x锛?    """
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

    # 鍏堟妸 x 闄愬畾鍦ㄦ湁鏁堣寖鍥村唴
    if x <= xmin:
        return xmin
    if x >= xmax:
        return xmax

    # 绔偣浼樺厛锛堥伩鍏嶆诞鐐规姈鍔ㄥ鑷?x==xmax 鍗磋鏄犲皠鍒?T2n锛?    if abs(x - xmin) < 1e-12:
        return xmin
    if abs(x - xmax) < 1e-12:
        return xmax

    # 1) 宸︽
    if x <= T1o:
        denom = (T1o - xmin)
        if abs(denom) < 1e-12:
            # 閫€鍖栵細鏃犳硶绋冲畾鎷変几锛屽敖閲忎繚鎸佸師鍊硷紙涓嶆暣浣撳钩绉伙級
            return x
        return xmin + (x - xmin) * (T1n - xmin) / denom

    # 2) 涓
    if x <= T2o:
        denom = (T2o - T1o)
        if abs(denom) < 1e-12:
            return T1n
        return T1n + (x - T1o) * (T2n - T1n) / denom

    # 3) 鍙虫
    denom = (xmax - T2o)
    if abs(denom) < 1e-12:
        # 閫€鍖栵細鏃犳硶绋冲畾鎷変几锛屽敖閲忎繚鎸佸師鍊?        return x
    return T2n + (x - T2o) * (xmax - T2n) / denom


def _estimate_temp_step(xs: List[float]) -> float:
    """浼拌娓╁害姝ラ暱锛堢敤浜庡垽鏂敋鐐规槸鍚︹€滆创杈光€濆鑷村尯闂撮€€鍖栵級銆?
    浣跨敤鎺掑簭鍚庘€滄鐨勭浉閭诲樊鍊尖€濈殑涓綅鏁帮紱鑻ユ棤娉曚及璁★紝鍒欒繑鍥炰竴涓瀬灏忔鏁般€?    """
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
    """淇/瑙勯伩鈥滈敋鐐硅创杈光€濆鑷寸殑鏇茬嚎寮傚父銆?
    鍏稿瀷寮傚父鍦烘櫙锛?    - T2o 鎭板ソ绛変簬 xmax锛堟渶澶у€艰惤鍦ㄦ渶鍚庝竴涓俯搴︾偣锛夛紝鐢ㄦ埛鍙堟妸 T2n 寰€宸︾Щ锛?      鏃у疄鐜颁細璁?x' 鐨勬渶澶у€煎彉鎴?T2n锛岄殢鍚庢彃鍊兼椂灏鹃儴琚?clamp 鎴愪竴娈碘€滃钩鍙扳€濓紝鐪嬭捣鏉ュ儚寮傚父銆?
    澶勭悊绛栫暐锛?    - 璁＄畻涓€涓€滄俯搴︽闀库€?step锛堜腑浣嶆暟锛?    - 鑻?T1o 璺?xmin 澶繎锛氭妸 T1o 鍚戝彸鎸埌绗簩涓敮涓€娓╁害鐐癸紙鎴栨渶杩戝彲鐢ㄧ偣锛?    - 鑻?T2o 璺?xmax 澶繎锛氭妸 T2o 鍚戝乏鎸埌鍊掓暟绗簩涓敮涓€娓╁害鐐癸紙鎴栨渶杩戝彲鐢ㄧ偣锛?    - 鎸姩鍚庡繀椤讳繚鎸?T1o < T2o锛屽惁鍒欏洖閫€鍒板師鍊?
    杩斿洖锛?T1o_used, T2o_used, meta)
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

    # 璐磋繎 xmin锛氬悜鍙虫尓
    if xs_u and (t1 - xmin) < eps and len(xs_u) >= 2:
        cand = None
        for v in xs_u:
            if v > xmin + eps * 0.1:
                cand = float(v)
                break
        if cand is not None and cand < t2 - eps:
            if abs(cand - t1) > 1e-12:
                meta["adjusted"] = True
                meta["reasons"].append(f"T1o璐磋竟({t1:.6g}鈮坸min) -> {cand:.6g}")
                t1 = cand

    # 璐磋繎 xmax锛氬悜宸︽尓
    if xs_u and (xmax - t2) < eps and len(xs_u) >= 2:
        cand = None
        for v in reversed(xs_u):
            if v < xmax - eps * 0.1:
                cand = float(v)
                break
        if cand is not None and cand > t1 + eps:
            if abs(cand - t2) > 1e-12:
                meta["adjusted"] = True
                meta["reasons"].append(f"T2o璐磋竟({t2:.6g}鈮坸max) -> {cand:.6g}")
                t2 = cand

    # 鏈€缁堟牎楠?    if not (xmin <= t1 <= xmax and xmin <= t2 <= xmax) or (t1 >= t2):
        meta["reasons"].append("璋冩暣鍚庝笉鍚堟硶锛屽凡鍥為€€鍒板師濮嬮敋鐐?)
        t1, t2 = float(T1o), float(T2o)
        meta["adjusted"] = False

    if meta["adjusted"] and logger is not None:
        try:
            logger.debug(f"閿氱偣淇: {'; '.join(meta['reasons'])} (eps鈮坽eps:.6g})")
        except Exception:
            pass

    meta["eps"] = float(eps)
    meta["step"] = float(step)
    meta["T1o_used"] = float(t1)
    meta["T2o_used"] = float(t2)
    return float(t1), float(t2), meta


def piecewise_inverse_map(x_new: float, xmin: float, xmax: float, T1o: float, T2o: float, T1n: float, T2n: float) -> float:
    """鍒嗘绾挎€ф槧灏勭殑鈥滈€嗘槧灏勨€濓細缁欏畾 x_new锛堢洰鏍囨俯搴︼級锛屾眰瀵瑰簲鐨勫師娓╁害 x_old銆?
    瀵瑰簲 forward 鏄犲皠閿氱偣锛?        xmin->xmin, T1o->T1n, T2o->T2n, xmax->xmax

    璇存槑锛?    - 褰撴煇娈靛尯闂撮€€鍖栵紙渚嬪 T2n==xmax 鎴?T2o==xmax锛夋椂锛岄€嗘槧灏勫彲鑳戒笉鏄竴涓€瀵瑰簲锛?      鏈嚱鏁颁細浼樺厛淇濊瘉绔偣涓€鑷存€э細x_new鈮坸min -> xmin, x_new鈮坸max -> xmax銆?    """
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

    # 鑼冨洿澶栫洿鎺ュす鍒拌竟鐣?    if x_new <= xmin:
        return xmin
    if x_new >= xmax:
        return xmax

    # 绔偣浼樺厛
    if abs(x_new - xmin) < 1e-12:
        return xmin
    if abs(x_new - xmax) < 1e-12:
        return xmax

    # 宸︽
    if x_new <= T1n:
        denom = (T1n - xmin)
        if abs(denom) < 1e-12:
            return xmin
        x_old = xmin + (x_new - xmin) * (T1o - xmin) / denom
        return max(xmin, min(xmax, x_old))

    # 涓
    if x_new <= T2n:
        denom = (T2n - T1n)
        if abs(denom) < 1e-12:
            return T1o
        x_old = T1o + (x_new - T1n) * (T2o - T1o) / denom
        return max(xmin, min(xmax, x_old))

    # 鍙虫
    denom = (xmax - T2n)
    if abs(denom) < 1e-12:
        return xmax
    x_old = T2o + (x_new - T2n) * (xmax - T2o) / denom
    return max(xmin, min(xmax, x_old))

def linear_interp(x: float, xp: List[float], fp: List[float]) -> float:
    # xp 閫掑锛涜秺鐣屽す鍒拌竟鐣?    """涓€缁寸嚎鎬ф彃鍊硷紙甯﹁竟鐣屽す鍙栵級銆?    
    鍙傛暟锛?        x: 闇€瑕佹彃鍊肩殑鑷彉閲忋€?        xp: 鑷彉閲忓簭鍒楋紙蹇呴』鍗曡皟閫掑锛夈€?        fp: 鍥犲彉閲忓簭鍒楋紙涓?xp 绛夐暱锛夈€?    
    杩斿洖锛?        float锛氭彃鍊肩粨鏋滐紱褰?x 瓒婄晫鏃惰繑鍥炵鐐瑰€硷紙clamp锛夈€?    
    娉ㄦ剰锛?        - 鏈疄鐜颁娇鐢ㄤ簩鍒嗘煡鎵惧畾浣嶅尯闂达紝閬垮厤 O(n) 鎵弿銆?        - 鑻?xp 鍑虹幇閲嶅鍊间細瀵艰嚧闄ら浂椋庨櫓锛屽洜姝よ皟鐢ㄥ墠寤鸿鍏?aggregate_duplicates()銆?    """
    
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
    # 鍚堝苟杩戜技鐩稿悓x锛堥伩鍏嶆彃鍊紉p闈炰弗鏍奸€掑锛?    """鍚堝苟杩戜技閲嶅鐨?x 鍊硷紝淇濊瘉 xp 涓ユ牸閫掑銆?    
    鐢ㄩ€旓細
        TMA 鏁版嵁涓伓灏斾細鍑虹幇娓╁害閲嶅/鎶栧姩锛堜緥濡傚悓涓€娓╁害澶氭潯璁板綍锛夛紝
        杩欎細璁╂彃鍊肩畻娉曞嚭鐜扳€滃垎姣嶄负 0鈥濇垨鍖洪棿瀹氫綅寮傚父銆?    
    鍙傛暟锛?        xp: x 鍒楄〃銆?        fp: y 鍒楄〃銆?        ndigits: 鎶?x 鍥涜垗浜斿叆鍒板灏戜綅鍚庤涓哄悓涓€涓《銆?    
    杩斿洖锛?        (xs, ys)锛氬幓閲嶅悗鐨?x锛堟帓搴忓悗锛変笌 y锛堝悓妗跺钩鍧囷級銆?    """
    
    bucket = {}
    for x, y in zip(xp, fp):
        k = round(x, ndigits)
        bucket.setdefault(k, []).append(y)
    xs = sorted(bucket.keys())
    ys = [sum(bucket[k]) / len(bucket[k]) for k in xs]
    return xs, ys


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
    """    鍦ㄥ凡鎸夋俯搴﹀崌搴忔帓鍒楃殑搴忓垪涓婁慨澶嶁€滄帀鐐光€濓細
    - 鎵惧埌浣庝簬鍘嗗彶鏈€楂樺€肩殑杩炵画鍖烘
    - 鐢ㄥ尯娈靛乏鍙充袱绔殑姝ｅ父鐐瑰仛绾挎€ф彃鍊兼姮楂樺～琛?
    鍙姮楂橈紝涓嶉檷浣庯紱鏈€鍚庡啀鍋氫竴娆￠潪閫掑噺淇濊瘉銆?    """
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

    # 鎺夌偣鍒版湯灏撅細娌℃湁鍙抽敋鐐癸紝鍙兘鎶埌 running_max
    if bad_start is not None:
        for k in range(bad_start, n):
            if y[k] < running_max:
                y[k] = running_max

    # 鏈€缁堜繚璇侀潪閫掑噺
    m = -float('inf')
    for j in range(n):
        if y[j] > m:m = y[j]
        else:y[j] = m
    return y


def enforce_monotonic_between(xs: List[float], ys: List[float], x1: float, x2: float, logger: logging.Logger):
    """
    淇鈥滆寮€鐐光€濓細鍦ㄦ俯搴﹀尯闂?[x1, x2] 鍐呭己鍒堕珮搴?ys 闅忔俯搴?xs 鍗曡皟涓嶄笅闄嶃€?    - xs/ys 涓哄悓闀垮害鍒楄〃锛堟寜鏂囦欢琛岄『搴忥級銆?    - 鍙鍖洪棿鍐呯殑鐐瑰仛淇锛涘尯闂村淇濇寔涓嶅彉銆?    """
    if x1 >= x2:return ys

    idxs = [i for i, x in enumerate(xs) if x1 <= x <= x2]
    if len(idxs) < 2:return ys

    # 鎸夋俯搴﹀崌搴忓仛鍗曡皟淇锛堥伩鍏嶆俯搴︿笉涓ユ牸閫掑瀵艰嚧璇垽锛?    idxs_sorted = sorted(idxs, key=lambda i: xs[i])
    seg = [ys[i] for i in idxs_sorted]

    tol = max(1e-9, (max(seg) - min(seg)) * 1e-6)
    method = (MONOTONIC_METHOD or "isotonic").lower()
    if method == "cummax":
        fixed = []
        m = -float('inf')
        for v in seg:
            if v > m:m = v
            fixed.append(m)
    elif method in ("bridge", "interp", "linear"):  # 绾挎€фˉ鎺ユ帀鐐?        xseg = [xs[i] for i in idxs_sorted]
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

    if changed:logger.debug(f"鍗曡皟淇宸插簲鐢細鍖洪棿[{x1}, {x2}] 鍐呬慨鏀圭偣鏁?{changed}, 鏈€澶ф敼鍙橀噺={max_abs_delta}")
    else:logger.debug(f"鍗曡皟淇妫€鏌ワ細鍖洪棿[{x1}, {x2}] 鍐呮棤闇€淇敼")
    return ys2


def format_like(original_num_str: str, value: float) -> str:
    # 灏介噺淇濈暀鍘熸暟瀛楃殑灏忔暟浣嶉鏍?    """鎶婃暟鍊?value 鏍煎紡鍖栨垚鈥滃敖閲忔帴杩戝師鏁板瓧瀛楃涓?original_num_str 鐨勯鏍尖€濄€?    
    瑙勫垯锛?        - 鍘熷瓧绗︿覆涓虹瀛﹁鏁版硶锛堝惈 e/E锛夛細杈撳嚭绉戝璁℃暟娉曪紱
        - 鍘熷瓧绗︿覆鍚皬鏁扮偣锛氫繚鐣欑浉鍚屽皬鏁颁綅鏁帮紱
        - 鍚﹀垯锛氬敖閲忚緭鍑烘暣鏁帮紙鑻ユ帴杩戞暣鏁帮級銆?    
    鐢ㄩ€旓細
        apply_warp() 鍥炲啓绗?3 鍒楅珮搴︽椂锛屽笇鏈涘敖閲忎笉鏀瑰彉鏂囦欢鏁翠綋鎺掔増锛?        浠ュ厤绗笁鏂硅蒋浠跺鍒楀/鏍煎紡鏁忔劅銆?    """
    
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
) -> Tuple[str, float, float]:
    """
    鉁?瑙勫垯鏍搁獙锛?    - 涓€琛屾湁 5 涓暟瀛楋細鍙栫2/绗?涓暟瀛楋紙index 1/2锛?    - 涓€琛屾湁 4 涓暟瀛楋細鍙栫2/绗?涓暟瀛楋紙index 1/2锛?    - 涓€琛屾湁 3 涓暟瀛楋細鍙栫2/绗?涓暟瀛楋紙index 1/2锛?    - 灏戜簬 3 涓暟瀛楋細涓嶅鐞嗚琛?
    鉁?V205 淇鐐癸紙鏍稿績锛夛細
    - 鏃у疄鐜扮敤 x' 杞村啀鎻掑€硷細褰?T1o鈮坸min 鎴?T2o鈮坸max锛堥敋鐐硅创杈癸級鏃讹紝
      x' 鐨勮寖鍥村彲鑳界缉鐭紝瀵艰嚧鎻掑€煎湪杈圭晫鍙戠敓 clamp锛堟洸绾垮嚭鐜扳€滃钩鍙?寮傚父鎶樼嚎鈥濓級銆?    - 鏂板疄鐜版敼涓猴細鍏堢敤鍘熷鏁版嵁寤虹珛 y(T) 鎻掑€硷紝鍐嶅姣忎釜鐩爣娓╁害 x 璁＄畻
      鈥滈€嗘槧灏勨€濆緱鍒板師娓╁害 x_old锛屽苟鍙?y(x_old) 浣滀负鏂伴珮搴︺€?      鍚屾椂澧炲姞閿氱偣璐磋竟淇锛坰anitize_warp_anchors锛夛紝澶у箙闄嶄綆寮傚父姒傜巼銆?    """
    # 鉁?鍙粠 StartOfData 鍚庢彁鍙栫湡瀹炴暟鎹锛岄伩鍏?header 鏁板瓧骞叉壈
    xs, ys, data_line_indices = extract_xy_from_file(parsed, logger)

    if not xs:
        raise ValueError("娌℃湁鎵惧埌鏈夋晥鏁版嵁琛岋細姣忚鑷冲皯瑕佹湁3涓暟瀛楋紝鎵嶈兘鍙栫2鍒楁俯搴﹀拰绗?鍒楅珮搴︺€?)

    xmin, xmax = min(xs), max(xs)

    # 鍘熷鍩哄噯鐐?    T1o, T2o = detect_T2_T1(xs, ys, logger)

    # 鍏佽涓婂眰锛堟搴︾畻娉曪級鎸囧畾鈥滃師濮嬪熀鍑嗙偣鈥?    if T1o_override is not None:
        try:
            _t1o = float(T1o_override)
            if xmin <= _t1o <= xmax:
                T1o = _t1o
            else:
                logger.debug(f"T1o_override={_t1o} 瓒呭嚭鑼冨洿 [{xmin},{xmax}]锛屽拷鐣ヨ鐩?)
        except Exception:
            logger.debug("T1o_override 鏃犳硶杞崲涓?float锛屽拷鐣ヨ鐩?)

    if T2o_override is not None:
        try:
            _t2o = float(T2o_override)
            if xmin <= _t2o <= xmax:
                T2o = _t2o
            else:
                logger.debug(f"T2o_override={_t2o} 瓒呭嚭鑼冨洿 [{xmin},{xmax}]锛屽拷鐣ヨ鐩?)
        except Exception:
            logger.debug("T2o_override 鏃犳硶杞崲涓?float锛屽拷鐣ヨ鐩?)

    if T1o >= T2o:
        logger.debug("瑕嗙洊鍚庣殑鍩哄噯鐐逛笉鍚堟硶锛圱1o>=T2o锛夛紝鍥為€€鍒拌嚜鍔ㄨ瘑鍒€?)
        T1o, T2o = detect_T2_T1(xs, ys, logger)

    logger.debug(f"鏁版嵁鐐圭粺璁★細鐐规暟={len(xs)}锛屾俯搴﹁寖鍥?[{xmin}, {xmax}]")
    logger.debug(f"鍘熷楂樺害鑼冨洿锛歔{min(ys)}, {max(ys)}]")

    # 鏍￠獙鏂癟1/T2
    if not (xmin <= T1n <= xmax and xmin <= T2n <= xmax):
        raise ValueError(f"鏂癟1/T2蹇呴』鍦ㄦ俯搴﹁寖鍥村唴 [{xmin}, {xmax}]锛屽綋鍓?T1={T1n}, T2={T2n}")
    if T1n >= T2n:
        raise ValueError(f"鏂癟1蹇呴』灏忎簬鏂癟2锛屽綋鍓?T1={T1n}, T2={T2n}")

    # 鉁?V205锛氶敋鐐硅创杈逛慨姝ｏ紙閬垮厤鍖洪棿閫€鍖栧鑷存洸绾垮紓甯革級
    T1o_used, T2o_used, meta = sanitize_warp_anchors(xs, T1o, T2o, xmin, xmax, logger)
    if meta.get("adjusted"):
        logger.debug(f"warp閿氱偣宸蹭慨姝? T1o {T1o} -> {T1o_used}, T2o {T2o} -> {T2o_used}")

    # 鉁?鍏堝缓绔嬪師濮?y(T) 鐨勬彃鍊硷紙鎸夋俯搴︽帓搴?+ 鍘婚噸锛?    pairs0 = sorted(zip(xs, ys), key=lambda p: p[0])
    xp0 = [p[0] for p in pairs0]
    fp0 = [p[1] for p in pairs0]
    xp0, fp0 = aggregate_duplicates(xp0, fp0, ndigits=8)

    # 鉁?鐢ㄢ€滈€嗘槧灏勨€濈敓鎴愭柊楂樺害锛歽_new(x) = y_orig( f^{-1}(x) )
    y_new: List[float] = []
    for x in xs:
        x_old = piecewise_inverse_map(x, xmin, xmax, T1o_used, T2o_used, T1n, T2n)
        y_new.append(linear_interp(x_old, xp0, fp0))

    # 鉁?纭繚浠嶵1鍒癟2鍗曡皟涓婂崌锛堥潪涓嬮檷锛夛紝閬垮厤鍑虹幇鍗曠偣涓嬪嚬瀵艰嚧鏇茬嚎鈥樿寮€鈥?    if MONOTONIC_FIX_T1_T2:
        y_new = enforce_monotonic_between(xs, y_new, T1n, T2n, logger)

    # 鉁?鎸?mg 鍋氶珮搴︾缉鏀撅紙鍙傝€?ces.py锛歯ew_h = h * 0.5 / mg锛?    if mg <= 0:
        raise ValueError(f"mg 蹇呴』澶т簬0,褰撳墠 mg={mg}")
    scale = 0.5 / mg
    y_new = [v * scale for v in y_new]
    logger.debug(f"宸插簲鐢?mg 缂╂斁:mg={mg}锛岀缉鏀剧郴鏁?0.5/mg={scale}")

    # 鉁?鍐欏洖锛氬彧鏇挎崲鈥滅3涓暟瀛梩oken鈥濓紙楂樺害锛?    new_lines = [pl.raw for pl in parsed]
    for local_i, line_idx in enumerate(data_line_indices):
        pl = parsed[line_idx]
        span = pl.spans[2]  # 绗?涓暟瀛楃殑鍘熷浣嶇疆
        old_str = pl.raw[span[0]:span[1]]
        new_str = format_like(old_str, y_new[local_i])
        new_lines[line_idx] = pl.raw[:span[0]] + new_str + pl.raw[span[1]:]

    logger.debug(f"淇敼鍚庨珮搴﹁寖鍥达細[{min(y_new)}, {max(y_new)}]")

    return "".join(new_lines), T1o_used, T2o_used

# =========================
# GUI 鏃ュ織 Handler
# =========================

# 鏃ュ織涓渶瑕佸皢鈥滆矾寰勯儴鍒嗏€濇爣绾㈢殑甯歌鍓嶇紑銆?# 娉ㄦ剰锛氳繖閲屾晠鎰忓彧鍒楀嚭浼氱揣璺熸枃浠?鐩綍璺緞鐨勫墠缂€锛岄伩鍏嶈鏍囨櫘閫氭枃鏈€?PATH_PREFIXES = (
    "閫夋嫨鏂囦欢浣嶇疆:",
    "杈撳嚭鏂囦欢浣嶇疆:",
    "閫夋嫨杈撳嚭璺緞:",
    "杈撳叆鏂囦欢:",
    "杈撳嚭鏂囦欢:",
    "杈撳叆鏂囦欢浣嶇疆:",
    "杈撳叆鏂囦欢澶逛綅缃?",
    "杈撳嚭鏂囦欢浣嶇疆:",
    "褰撳墠杈撳嚭璺緞:",
    "宸茬敓鎴怲IFF鍥?",
    "宸茬敓鎴愪豢鐢烼IFF鍥?",
)


class TextHandler(logging.Handler):
    """Write logs to a Tk ScrolledText with colored segments.

    - 榛樿鍙樉绀?INFO / ERROR锛堜互鍙?CRITICAL锛?    - 褰?is_debug_mode() 涓?True 鏃讹紝棰濆鏄剧ず DEBUG / WARNING
    - 閫夋嫨鏂版枃浠舵椂锛屽彲鍏堝啓鍏ラ粍鑹插垎闅旂 "=========="锛堟棤鏃堕棿/鍑芥暟鍚嶅墠缂€锛?    - 鍑芥暟鍚嶏細钃濊壊锛涙枃浠惰矾寰勶細绾㈣壊锛汱G 鍒楄〃锛氱豢鑹?    """

    def __init__(self, text_widget: ScrolledText, is_debug_mode=None):
        """TextHandler 鏋勯€犲嚱鏁帮細鎶?logging 杈撳嚭閲嶅畾鍚戝埌 Tkinter 鐨?ScrolledText銆?        
        鍙傛暟锛?            text_widget: 鐢ㄤ簬灞曠ず鏃ュ織鐨?ScrolledText 鎺т欢銆?            is_debug_mode: 鍥炶皟鍑芥暟/鍙皟鐢ㄥ璞★紝鐢ㄤ簬鍒ゆ柇褰撳墠 UI 鏄惁寮€鍚?DEBUG 鏄剧ず銆?        
        璇存槑锛?            - DEBUG 妯″紡涓嬫樉绀烘洿璇︾粏鐨勬棩蹇楋紱闈?DEBUG 鏃惰繃婊ゆ帀浣庣瓑绾ф棩蹇椾互鍏嶅埛灞忋€?            - 鍚屾椂鍒濆鍖栧绉?tag锛堥鑹?鍔犵矖锛夌敤浜庨珮浜嚱鏁板悕銆佽矾寰勩€丩G 鍒楄〃绛夈€?        """
        
        super().__init__()
        self.text_widget = text_widget  # Tk 鐨?ScrolledText 鎺т欢锛氭棩蹇楁渶缁堝啓鍏ヨ繖閲?        self.is_debug_mode = is_debug_mode  # 鍥炶皟锛氳繑鍥?True 琛ㄧず UI 澶勪簬 DEBUG 璇︾粏鏄剧ず妯″紡
        self._init_tags()

    def _init_tags(self):
        """鍒濆鍖?Tkinter Text 鐨?tag锛堥鑹?瀛椾綋锛夈€?        
        tag 鐢ㄩ€旓細
            - SEPARATOR锛氶粍鑹插垎闅旂嚎
            - FUNC锛氬嚱鏁板悕锛堣摑鑹诧級
            - PATH锛氳矾寰勶紙绾㈣壊锛?            - LG锛歀G 鍒楄〃锛堢豢鑹诧級
            - UNCHANGED锛氭爣娉ㄢ€滄湭鏇存敼鈥濈殑娣辩孩鍔犵矖
            - INFO/DEBUG/WARNING/ERROR/CRITICAL锛氭寜鏃ュ織绾у埆鐫€鑹?        """
        
        try:
            tw = self.text_widget
            tw.tag_configure("SEPARATOR", foreground="#D4A000")        # 榛?            tw.tag_configure("FUNC", foreground="#1E5AA8")       # 钃?            tw.tag_configure("PATH", foreground="#C00000")       # 绾?            tw.tag_configure("LG", foreground="#0B7D0B")         # 缁?
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
        """鎶?logging 鐨?levelno 鏄犲皠涓?TextHandler 浣跨敤鐨?tag 鍚嶇О銆?        
        鍙傛暟锛?            levelno: logging 绾у埆鏁板瓧锛堝 logging.INFO锛夈€?        
        杩斿洖锛?            str锛氬搴旂殑 tag 鍚嶇О銆?        """
        
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
        灏嗕竴琛屾秷鎭彃鍏ュ埌 Text锛屽苟杩涜绠€鍗曠殑鍏抽敭璇?璺緞鐫€鑹诧細
        - "=========="锛氶粍鑹插垎闅旂
        - 琛屼互 PATH_PREFIXES 寮€澶达細鍐掑彿鍚庨潰鐨勫唴瀹规爣绾紙璺緞锛?        - 琛屽唴鍖呭惈 Windows/UNC 璺緞锛氳矾寰勬爣绾紙鍗充娇涓嶄互 prefix 寮€澶翠篃鑳借瘑鍒級
        - "LG=[...]"锛氭暣琛岀豢鑹?        - "锛堟湭鏇存敼锛?锛氭繁绾㈠姞绮楋紙璺緞浠嶄繚鎸佺孩鑹诧級
        """
        tw = self.text_widget
        marker_unchanged = "锛堟湭鏇存敼锛?

        def insert_with_paths(text: str):
            """鍦ㄤ笉鑷姩鎹㈣鐨勬儏鍐典笅锛屾彃鍏?text锛屽苟鎶婂叾涓殑璺緞鏍囩孩銆?""
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

        # LG 澶氳鍒楄〃锛氬舰濡?"{ 0.45,   9.526}," 鐨勮涔熸爣缁?        if re.match(r'^\{\s*[-+]?\d+(?:\.\d+)?\s*,\s*[-+]?\d+(?:\.\d+)?\s*\}\s*,?$', stripped):
            tw.insert("end", line + "\n", "LG")
            return

        # 1) 浠ュ浐瀹氬墠缂€寮€澶达細鍐掑彿鍚庨潰璺緞鏍囩孩
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

        # 2) 闈炲墠缂€琛岋細鏃㈣鏀寔璺緞鏍囩孩锛屼篃瑕佹敮鎸佲€滄湭鏇存敼鈥濇繁绾㈠姞绮?        if marker_unchanged in line:
            before, after = line.split(marker_unchanged, 1)
            insert_with_paths(before)
            tw.insert("end", marker_unchanged, "UNCHANGED")
            insert_with_paths(after)
            tw.insert("end", "\n", base_tag)
            return

        # 3) 榛樿锛氬仛涓€娆¤矾寰勯珮浜紙鑻ユ棤璺緞鍒欐櫘閫氭彃鍏ワ級
        insert_with_paths(line)
        tw.insert("end", "\n", base_tag)
        return

    def _append_record(self, header_prefix: str, func_name: str, msg: str, base_tag: str) -> None:
        """鎶婁竴鏉℃棩蹇楄拷鍔犲埌 Tk 鐨?ScrolledText 涓紙绾跨▼瀹夊叏锛夈€?""
        tw = self.text_widget

        def append():
            """鍐呴儴鍥炶皟锛氬疄闄呮妸涓€鏉℃棩蹇楀啓鍏ュ埌 Tk Text 鎺т欢銆?            
            璇存槑锛?                - 璇ュ嚱鏁伴€氳繃 tw.after(0, ...) 鍦?Tk 涓荤嚎绋嬫墽琛岋紝
                  閬垮厤鍚庡彴绾跨▼鐩存帴鎿嶄綔 Tk 鎺т欢瀵艰嚧宕╂簝銆?                - 鍚屾椂璐熻矗鍒嗛殧绗?璺緞楂樹寒/LG 楂樹寒绛夋樉绀虹粏鑺傘€?            """
            
            try:
                tw.configure(state="normal")

                # 鍒嗛殧绗︼細鍙樉绀洪粍鑹测€?=========鈥?                if str(msg).strip() == "==========":
                    tw.insert("end", "==========\n", "SEPARATOR")
                    tw.configure(state="disabled")
                    tw.see("end")
                    return

                # Header锛氭椂闂?绾у埆 + 鍑芥暟鍚嶏紙钃濊壊锛?                tw.insert("end", header_prefix, base_tag)
                tw.insert("end", str(func_name), "FUNC")
                tw.insert("end", "\n", base_tag)

                # Body锛氶€愯鍐欏叆锛堣矾寰?LG/鏈洿鏀圭瓑鍋氬眬閮ㄩ珮浜級
                body = str(msg) if msg is not None else ""
                if body:
                    for line in body.splitlines():
                        self._insert_colored_message_line(line, base_tag)
                else:
                    self._insert_colored_message_line("", base_tag)

                tw.configure(state="disabled")
                tw.see("end")
            except Exception:
                # UI 鏃ュ織涓嶈兘褰卞搷涓绘祦绋?                try:
                    tw.configure(state="disabled")
                except Exception:
                    pass

        try:
            tw.after(0, append)  # 淇濊瘉鍦?Tk 涓荤嚎绋嬫墽琛?        except Exception:
            append()

    def emit(self, record: logging.LogRecord) -> None:
        """logging.Handler 鎺ュ彛锛氭牴鎹?DEBUG 寮€鍏冲喅瀹氳緭鍑虹矑搴︺€?""
        try:
            debug_mode = bool(self.is_debug_mode()) if callable(self.is_debug_mode) else False

            # UI 闈?DEBUG锛氬彧鏄剧ず INFO / ERROR锛堜互鍙?WARNING 瑙嗕负 INFO锛?            if (not debug_mode) and record.levelno < logging.INFO:
                return

            base_tag = "ERROR" if record.levelno >= logging.ERROR else ("INFO" if record.levelno >= logging.INFO else "DEBUG")
            ts = datetime.datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
            header_prefix = f"[{ts}] {record.levelname} - "
            func_name = getattr(record, "funcName", "")

            msg = record.getMessage()

            # 寮傚父锛欴EBUG 妯″紡杈撳嚭瀹屾暣鍫嗘爤锛汭NFO 妯″紡鍙ˉ鍏呭紓甯镐俊鎭?            if record.exc_info:
                if debug_mode:
                    import traceback
                    msg = (msg + "\n" if msg else "") + "".join(traceback.format_exception(*record.exc_info))
                else:
                    _exc_type, exc_val, _tb = record.exc_info
                    if exc_val is not None:
                        extra = str(exc_val)
                        if extra and extra not in (msg or ""):
                            msg = (msg + "锛?" if msg else "") + extra

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
    """鎸夌粰瀹?mg 鍒楄〃涓庨珮搴﹀樊 H(渭m) 璁＄畻 LG 鍒楄〃锛堜繚鐣?3 浣嶅皬鏁帮級銆?
    鍏紡锛堢敤鎴风害瀹氾級锛?        LG = 1000 * mg / (蟺 * 3.35 * 3.35 * H / 1000)

    鍏朵腑锛?      - mg锛氳川閲忥紙mg锛?      - H锛氶珮搴﹀樊锛埼糾锛夛紝H = H2 - H1
      - 蟺锛氬渾鍛ㄧ巼

    璇存槑锛?    - 鐞嗚涓?H 搴斾负姝ｆ暟锛涜嫢 H<0锛堟洸绾挎柟鍚戠浉鍙嶏級锛孷206 浼氫娇鐢?|H| 缁х画璁＄畻锛?      骞跺湪鏃ュ織涓粰鍑?WARNING锛堥伩鍏嶇畻娉?鎵瑰鐞嗙洿鎺ュけ璐ワ級銆?    """
    try:
        H = float(H)
    except Exception:
        raise ValueError(f"H 涓嶆槸鏈夋晥鏁板瓧锛歿H!r}")

    if H == 0:
        raise ValueError("H 涓嶈兘涓?0锛圚=H2-H1锛夈€?)
    if H < 0:
        if logger is not None:
            try:
                logger.warning(f"H 涓鸿礋({H:.6g})锛氬凡鎸?|H| 璁＄畻 LG銆?)
            except Exception:
                pass
        H = abs(H)

    out_lines = ["LG=["]
    for mg in mg_values:
        lg = 1000.0 * float(mg) / (math.pi * 3.35 * 3.35 * H / 1000.0)
        out_lines.append(f"  {{{float(mg):>5.2f}, {lg:>8.3f}}},")
    if len(out_lines) > 1:
        out_lines[-1] = out_lines[-1].rstrip(",")  # 鏈€鍚庝竴琛屼笉甯﹂€楀彿
    out_lines.append("]")
    return "\n".join(out_lines)


class App:
    def __init__(self, root: tk.Tk):
        """涓诲簲鐢ㄦ瀯閫犲嚱鏁帮細鍒濆鍖?GUI銆佹棩蹇楃郴缁熶互鍙婅繍琛屾椂缂撳瓨銆?        
        鍙傛暟锛?            root: Tk 鏍圭獥鍙ｃ€?        
        鍏抽敭鎴愬憳鍙橀噺锛堟瑙堬級锛?            - input_path/output_path锛氳緭鍏?杈撳嚭璺緞銆?            - t1_var/t2_var/mg_var锛氱敤鎴峰彲缂栬緫鍙傛暟銆?            - _cached_parsed锛氱紦瀛樿В鏋愬悗鐨?ParsedLine锛岄伩鍏嶉噸澶嶈鍙栦笌瑙ｆ瀽銆?            - _warp_base_t1/_warp_base_t2锛歸arp 浣跨敤鐨勨€滃師濮嬪熀鍑嗙偣鈥濓紙浼氳姊害绠楁硶鏇存柊锛夈€?            - _last_output_*锛氭渶杩戜竴娆℃墽琛岃皟鏁村悗鐨勬枃鏈?瑙ｆ瀽缁撴灉锛堜緵缁樺浘澶嶇敤锛夈€?        """
        
        self.root = root  # Tk 鏍圭獥鍙ｅ紩鐢紙鐢ㄤ簬鍒涘缓瀛愮獥鍙?瀵硅瘽妗嗙瓑锛?        self.root.title(f"TMA鏁版嵁鍒嗘瀽澶勭悊鍣?({VERSION})")

        self.input_path = tk.StringVar()  # 杈撳叆鏂囦欢璺緞锛堢敤鎴烽€夋嫨鐨勫師濮嬫暟鎹枃浠讹級
        self.output_path = tk.StringVar()  # 杈撳嚭鏂囦欢璺緞锛堟墽琛岃皟鏁村悗鍐欏嚭鐨勬柊鏂囦欢锛?        self.t1_var = tk.StringVar()  # T1 杈撳叆妗嗗彉閲忥紙鈩冿級
        self.t2_var = tk.StringVar()  # T2 杈撳叆妗嗗彉閲忥紙鈩冿級
        self.mg_var = tk.StringVar(value="0.50")  # mg 杈撳叆妗嗗彉閲忥紙mg锛屽喅瀹氶珮搴︾缉鏀剧郴鏁?0.5/mg锛?
        # UI debug 鏄剧ず寮€鍏筹細浠呭鍗曟鍔ㄤ綔鐢熸晥锛堟墽琛?閫夋嫨鏂囦欢鏃朵复鏃剁疆 True锛?        self._ui_debug_active = False  # 鍐呴儴寮€鍏筹細鏈鎿嶄綔鏄惁鍚?UI 杈撳嚭 DEBUG 鏃ュ織锛堥伩鍏嶆棩甯稿埛灞忥級
        self.debug_var = tk.BooleanVar(value=False)  # 澶嶉€夋鍙橀噺锛氱敤鎴锋槸鍚﹀嬀閫?DEBUG 妯″紡

        # 缁樺浘瀵煎嚭璺緞锛堢粯鍥剧獥鍙ｅ鐢級
        self.export_use_newpath_var = tk.BooleanVar(value=False)  # 缁樺浘瀵煎嚭锛氭槸鍚﹀惎鐢ㄨ嚜瀹氫箟鍑哄浘鐩綍
        self.export_newpath_var = tk.StringVar(value=r"\\192.168.0.105\TMAresult\LS")  # 缁樺浘瀵煎嚭锛氳嚜瀹氫箟鍑哄浘鐩綍锛堢綉缁滅洏/鏈湴鐩綍锛?
        self._recent_export_paths: List[str] = []  # 杩戞湡浣跨敤鐨勫嚭鍥剧洰褰曪紙鏈€澶?3 涓紝鐢ㄤ簬涓嬫媺妗嗭級

        # ---------------------------

        # 杈撳叆璺緞涓嬫媺妗嗭紙v208锛?
        # ---------------------------

        # 棰勫埗鐩綍锛氱敤浜庘€滄洿蹇姷杈锯€濆父鐢ㄧ綉缁滆矾寰勶紙涓嬫媺妗嗛€夋嫨鍚庯紝鍐嶇偣鍑汇€愭枃浠惰矾寰勩€戦€夋嫨鍏蜂綋鏂囦欢锛?
        self._preset_input_dirs: List[str] = [normalize_path_separators(p) for p in PRESET_INPUT_DIRS]

        # 妗岄潰璺緞锛氭湰鏈哄父鐢紙涔熸斁鍒颁笅鎷夐噷锛?
        self._desktop_path: str = normalize_path_separators(get_desktop_path())

        # 鏈€杩?3 涓墜鍔ㄩ€夋嫨杩囩殑杈撳叆鏂囦欢澶癸紙浠呰褰曗€滄枃浠跺璇濇閫夋嫨鏂囦欢鈥濈殑鐩綍锛?
        self._recent_input_dirs: List[str] = []

        # 杈撳叆璺緞 Combobox 鎺т欢寮曠敤锛堢敤浜庡姩鎬佸埛鏂?values锛?
        self._input_path_combo = None

        self._build_ui()
        self.logger = self._setup_logger()  # 搴旂敤 logger锛堣緭鍑哄埌 GUI 鏃ュ織妗嗭級

        self._log_tutorial()
        self._cached_parsed: Optional[List[ParsedLine]] = None  # 缂撳瓨锛氬綋鍓嶈緭鍏ユ枃浠惰В鏋愬悗鐨?ParsedLine 鍒楄〃锛堥伩鍏嶉噸澶嶈В鏋愶級
        # 鎷変几绠楁硶浣跨敤鐨勨€滃師濮嬧€漈1/T2鍩哄噯鐐癸紙鍙姊害绠楁硶鏇存柊锛?        self._warp_base_t1: Optional[float] = None  # warp 鍩哄噯鐐癸細鍘熷/姊害绠楁硶寰楀埌鐨?T1锛堢敤浜?piecewise warp锛?        self._warp_base_t2: Optional[float] = None  # warp 鍩哄噯鐐癸細鍘熷/姊害绠楁硶寰楀埌鐨?T2锛堢敤浜?piecewise warp锛?

        # 鏈€杩戜竴娆♀€滄墽琛屼慨鏀光€濅骇鐢熺殑鏂囨湰/瑙ｆ瀽缁撴灉锛堢敤浜庣粯鍥撅級
        self._last_output_text: Optional[str] = None  # 鏈€杩戜竴娆℃墽琛岃皟鏁村悗鐨勫畬鏁存枃鏈紙渚涚粯鍥?澶嶇敤锛?        self._last_output_parsed: Optional[List[ParsedLine]] = None  # 鏈€杩戜竴娆℃墽琛岃皟鏁村悗鐨勮В鏋愮粨鏋滐紙渚涚粯鍥?澶嶇敤锛?        self._last_run_mg: Optional[float] = None  # 鏈€杩戜竴娆℃墽琛岃皟鏁翠娇鐢ㄧ殑 mg锛堢敤浜庣粯鍥惧壇鏍囬/澶囨敞锛?
        # 缁樺浘绐楀彛缂撳瓨
        self._plot_win: Optional[tk.Toplevel] = None  # 缁樺浘绐楀彛锛圱oplevel锛夊紩鐢紝鐢ㄤ簬澶嶇敤/閬垮厤閲嶅鍒涘缓
        self._plot_canvas: Optional[FigureCanvasTkAgg] = None  # Matplotlib 鐢诲竷锛團igureCanvasTkAgg锛夊紩鐢?        self._plot_fig: Optional[Figure] = None  # Matplotlib Figure 寮曠敤锛堢敤浜庡鍑?鍒锋柊锛?        self._plot_toolbar: Optional[ttk.Frame] = None  # 缁樺浘绐楀彛宸ュ叿鏍?Frame锛堟斁瀵煎嚭鎸夐挳绛夛級
        # 缁樺浘绐楀彛涓撶敤 mg锛堜粎褰卞搷鍥句腑澶囨敞锛屼笉褰卞搷涓荤晫闈?mg锛?        self._plot_mg_var = tk.StringVar(value='')  # 缁樺浘绐楀彛 mg(鏍囨敞) 杈撳叆妗嗗彉閲忥紙浠呭奖鍝嶅浘涓枃瀛楋級
        self._plot_method_artist = None  # 缁樺浘宸︿笂瑙掆€滄柟娉曟棩蹇椻€濇枃鏈璞★紙鐢ㄤ簬鍔ㄦ€佸埛鏂?mg锛?        self._plot_note_x_left = None  # 涓洪伩鍏嶅娉ㄩ伄鎸℃洸绾匡紝宸︿笂瑙掑娉ㄤ細鍚戝乏鎸細璇ュ彉閲忚褰?x 杞村乏杈圭晫
        self._plot_ax = None  # 缁樺浘鍧愭爣杞?Axes 寮曠敤锛堢敤浜庡埛鏂版爣娉級

    def _build_ui(self):
        """鏋勫缓涓荤晫闈?UI锛堟寜閽€佽緭鍏ユ銆佹棩蹇楁绛夛級銆?        
        璇存槑锛?            - 杩欓噷鍙仛鎺т欢甯冨眬锛屼笉鍋氫笟鍔￠€昏緫銆?            - 涓氬姟閫昏緫鐢?on_choose_file/on_execute/on_plot 绛変簨浠跺鐞嗗嚱鏁拌礋璐ｃ€?        """
        
        frm = ttk.Frame(self.root, padding=10)
        frm.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)

        # 绗?琛岋細杈撳叆璺緞锛坴208锛氬彲涓嬫媺銆佸彲鎵嬫墦锛?        ttk.Button(frm, text="鏂囦欢璺緞", command=self.on_choose_file).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)

        # 杈撳叆璺緞鏀逛负 Combobox锛?        # - 鍙墜鍔ㄨ緭鍏ュ畬鏁存枃浠惰矾寰勶紙.txt / .001~.999锛?        # - 涓嬫媺鍙€夋嫨鈥滈鍒舵枃浠跺す璺緞/妗岄潰/鏈€杩戠洰褰曗€濓紝鐢ㄤ簬鏇村揩瀹氫綅鐩綍
        self._input_path_combo = ttk.Combobox(frm, textvariable=self.input_path, state="normal")
        self._input_path_combo.grid(row=0, column=1, sticky="ew", pady=4)

        # 鍒濆鍖栦笅鎷夐」锛屽苟缁戝畾浜嬩欢锛堟彁绀?+ 鑷姩娓呯悊鍒嗛殧绗?鎺у埗瀛楃锛?        self._refresh_input_path_choices()
        try:
            self._input_path_combo.bind("<<ComboboxSelected>>", self._on_input_path_combo_selected)
            self._input_path_combo.bind("<Return>", self._on_input_path_enter)
            self._input_path_combo.bind("<FocusOut>", self._on_input_path_focus_out)
        except Exception:
            # 鏌愪簺绮剧畝 Tk 鐜鍙兘涓嶆敮鎸?bind锛涘拷鐣ヤ笉褰卞搷涓绘祦绋?            pass

        # 绗?琛?        ttk.Button(frm, text="杈撳嚭璺緞", command=self.on_choose_output).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(frm, textvariable=self.output_path).grid(row=1, column=1, sticky="ew", pady=4)

        # 绗?琛?        row3 = ttk.Frame(frm)
        row3.grid(row=2, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Label(row3, text="T1=").grid(row=0, column=0, padx=(0, 6))
        ttk.Entry(row3, width=12, textvariable=self.t1_var).grid(row=0, column=1, padx=(0, 16))
        ttk.Label(row3, text="T2=").grid(row=0, column=2, padx=(0, 6))
        ttk.Entry(row3, width=12, textvariable=self.t2_var).grid(row=0, column=3, padx=(0, 16))
        ttk.Label(row3, text="Mg=").grid(row=0, column=4, padx=(0, 6))
        ttk.Entry(row3, width=8, textvariable=self.mg_var).grid(row=0, column=5)

        # 绗?琛?        row4 = ttk.Frame(frm)
        row4.grid(row=3, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Button(row4, text="鎵ц璋冩暣", command=self.on_execute).grid(row=0, column=0, padx=(0, 10))
        ttk.Button(row4, text="浣跨敤缁樺浘", command=self.on_plot).grid(row=0, column=1, padx=(0, 10))
        ttk.Button(row4, text="姊害绠楁硶", command=self.on_precise_read).grid(row=0, column=2, padx=(0, 10))
        ttk.Button(row4, text="瓒呯骇姊害绠楁硶", command=self.on_super_gradient_read).grid(row=0, column=3, padx=(0, 10))
        ttk.Button(row4, text="閫€鍑鸿蒋浠?, command=self.root.destroy).grid(row=0, column=4)
        ttk.Button(frm, text="Soft Log", command=self.on_soft_log).grid(row=4, column=0, sticky="w")
        tk.Checkbutton(frm, text="DeBug Mode", variable=self.debug_var, fg="orange").grid(row=4, column=1, sticky="w", padx=8)
        self.log_box = ScrolledText(frm, height=14)
        self.log_box.grid(row=5, column=0, columnspan=2, sticky="nsew", pady=(4, 0))
        self.log_box.configure(state="disabled")
        frm.rowconfigure(5, weight=1)

    def _setup_logger(self) -> logging.Logger:
        """鍒濆鍖栧簲鐢?logger锛屽苟鎶婅緭鍑虹粦瀹氬埌 GUI 鐨勬棩蹇楁銆?        
        杩斿洖锛?            logging.Logger锛氶厤缃ソ鐨?logger锛堢骇鍒?DEBUG锛屽叿浣撴樉绀虹敱 UI debug 寮€鍏虫帶鍒讹級銆?        """
        
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


    def _log_tutorial(self) -> None:
        """鍚姩鏃跺湪鏃ュ織鏍忔墦鍗扮畝鏄庢暀绋嬶紙INFO 绾у埆锛夈€?""
        try:
            self.logger.info("==========")
            self.logger.info(f"娆㈣繋浣跨敤銆怲MA銆戞暟鎹垎鏋愬鐞嗗櫒锛坽VERSION}锛?)

            tutorial = Gonggao_Message_by_thisone  # 缁熶竴浣跨敤鍏ㄥ眬鍏憡鏂囨湰锛岄伩鍏嶅澶勭淮鎶?            self.logger.info(tutorial)
        except Exception:
            # 鏁欑▼鎵撳嵃澶辫触涓嶅奖鍝嶄富娴佺▼
            try:
                self.logger.info("==========")
                self.logger.info("鏁欑▼鎵撳嵃澶辫触锛堝凡蹇界暐锛夈€?)
            except Exception:
                pass

    def on_soft_log(self) -> None:
        """閲嶆柊鎵撳嵃鍚姩鏃跺啓鍏ユ棩蹇楁爮鐨勬暀绋?鍒濆鍖栦俊鎭紙涓嶅脊绐楋級銆?""
        try:
            self._log_tutorial()
        except Exception:
            # Soft Log 閲嶆柊鎵撳嵃澶辫触涓嶅奖鍝嶄富娴佺▼
            try:
                self.logger.error("Soft Log 閲嶆柊鎵撳嵃澶辫触锛堝凡蹇界暐锛夈€?)
            except Exception:
                pass

    # 鍏煎鏃х増鏈細淇濈暀鏂规硶鍚嶏紝浣嗕笉鍐嶅脊鍑哄叕鍛婃
    def show_announcement(self) -> None:
        """鏃х増鏈吋瀹癸細绛変环浜?Soft Log 閲嶆柊鎵撳嵃锛屼笉鍐嶅脊绐椼€?""
        self.on_soft_log()

    # ---------------------------
    # 杈撳叆璺緞涓嬫媺妗嗙浉鍏筹紙v208锛?    # ---------------------------
    def _norm_dir_for_dropdown(self, p: str) -> str:
        """瑙勮寖鍖栫洰褰曞瓧绗︿覆锛岀敤浜庤緭鍏ヨ矾寰勪笅鎷夋鐨勫幓閲?瀛樺偍銆?
        瑙勫垯锛?            1) 璋冪敤 normalize_path_separators() 缁熶竴鍒嗛殧绗︼紝骞舵竻鐞嗘帶鍒跺瓧绗︼紱
            2) 鍘婚櫎鏈熬澶氫綑鐨?'/' 鎴?'\\'锛堥伩鍏嶅悓涓€鐩綍鍑虹幇 ".../dir" 涓?".../dir/" 涓ゆ潯锛夛紱
               浣嗕繚鐣欑洏绗︽牴鐩綍锛堝 "C:\\"锛夈€?        """
        p = normalize_path_separators((p or "").strip())
        if not p:
            return ""

        p2 = p.rstrip("/\\")
        if re.fullmatch(r"[A-Za-z]:", p2):
            # Windows 鐩樼鏍圭洰褰曢渶瑕佷繚鐣欏垎闅旂
            return p2 + "\\"
        return p2

    def _input_dir_dropdown_values(self) -> List[str]:
        """杩斿洖杈撳叆璺緞涓嬫媺妗嗗簲灞曠ず鐨勭洰褰曞垪琛紙鍘婚噸鍚庯級銆?
        椤哄簭锛?            1) 棰勫埗鐩綍锛? 涓綉缁滆矾寰勶級
            2) 妗岄潰鐩綍
            3) 鏈€杩?3 涓墜鍔ㄩ€夋嫨杩囩殑鐩綍锛堟渶鏂板湪鍓嶏級

        璇存槑锛?            - 涓嬫媺椤逛富瑕佹槸鈥滅洰褰曗€濓紝鐢ㄤ簬蹇€熷畾浣?initialdir锛?            - 鐪熸杩愯鏃朵粛闇€瑕佽緭鍏モ€滄枃浠惰矾寰勨€濓紙.txt / .001~.999锛夈€?        """
        values: List[str] = []

        # 1) 棰勫埗鐩綍
        for p in getattr(self, "_preset_input_dirs", []) or []:
            pp = self._norm_dir_for_dropdown(p)
            if pp and pp not in values:
                values.append(pp)

        # 2) 妗岄潰鐩綍
        dp = self._norm_dir_for_dropdown(getattr(self, "_desktop_path", ""))
        if dp and dp not in values:
            values.append(dp)

        # 3) 鏈€杩戠洰褰?        for p in getattr(self, "_recent_input_dirs", []) or []:
            pp = self._norm_dir_for_dropdown(p)
            if pp and pp not in values:
                values.append(pp)

        return values

    def _refresh_input_path_choices(self) -> None:
        """鍒锋柊杈撳叆璺緞涓嬫媺妗嗙殑鍙€夐」锛坴alues锛夈€?
        娉ㄦ剰锛氳鍑芥暟涓嶄緷璧?logger锛屽彲鍦?_build_ui() 閲岃皟鐢ㄣ€?        """
        try:
            if self._input_path_combo is None:
                return
            self._input_path_combo["values"] = self._input_dir_dropdown_values()
        except Exception:
            pass

    def _remember_input_dir(self, dir_path: str) -> None:
        """璁板綍鐢ㄦ埛鈥滄墜鍔ㄩ€夋嫨鏂囦欢鈥濇墍鍦ㄧ殑鐩綍鍒拌緭鍏ヨ矾寰勪笅鎷夋锛堟渶澶?3 涓級銆?
        瑙﹀彂鏃舵満锛?            - 鐢ㄦ埛閫氳繃 on_choose_file() 鐨勬枃浠跺璇濇閫夋嫨浜嗘煇涓枃浠躲€?
        瑙勫垯锛?            - 鑻ョ洰褰曞凡鍦ㄩ鍒剁洰褰?妗岄潰鐩綍涓紝鍒欎笉閲嶅娣诲姞锛?            - 鏈€杩戠洰褰曟彃鍏ュ埌鏈€鍓嶉潰锛屾渶澶氫繚鐣?3 涓紱
            - 璁板綍/鍒锋柊鏃跺湪鏃ュ織鏍忕粰鍑烘彁绀恒€?        """
        d = self._norm_dir_for_dropdown(dir_path)
        if not d:
            return

        d_key = d.lower()
        preset_keys = {self._norm_dir_for_dropdown(p).lower() for p in getattr(self, "_preset_input_dirs", []) if p}
        desktop_key = self._norm_dir_for_dropdown(getattr(self, "_desktop_path", "")).lower()

        # 棰勫埗鐩綍/妗岄潰鐩綍鏃犻渶鍔犲叆鈥滄渶杩戔€?        if d_key in preset_keys or (desktop_key and d_key == desktop_key):
            return

        if not hasattr(self, "_recent_input_dirs") or self._recent_input_dirs is None:
            self._recent_input_dirs = []

        # 宸插瓨鍦ㄥ垯绉诲埌鏈€鍓?        for i, old in enumerate(list(self._recent_input_dirs)):
            if self._norm_dir_for_dropdown(old).lower() == d_key:
                try:
                    self._recent_input_dirs.pop(i)
                except Exception:
                    pass
                break

        self._recent_input_dirs.insert(0, d)
        del self._recent_input_dirs[3:]  # 鏈€澶氫繚鐣?3 涓?
        self._refresh_input_path_choices()

        # log锛氭彁绀哄凡鍔犲叆/鍒锋柊
        try:
            if hasattr(self, "logger") and self.logger is not None:
                self.logger.info(
                    "宸茶褰曡緭鍏ユ枃浠跺す鍒颁笅鎷夋锛堟渶澶氫繚鐣?涓級锛歕n"
                    f"杈撳叆鏂囦欢澶逛綅缃? {d}\n"
                    "鎻愮ず锛氳緭鍏ヨ矾寰勪笅鎷変粎鐢ㄤ簬蹇€熻烦杞埌鐩綍锛涙墽琛?璇嗗埆浠嶉渶瑕佸叿浣撴枃浠惰矾寰勩€?
                )
        except Exception:
            pass

    def _on_input_path_combo_selected(self, _event=None) -> None:
        """杈撳叆璺緞涓嬫媺妗嗛€夋嫨浜嬩欢锛氱粰鍑烘彁绀猴紙涓嬫媺浠呯敤浜庡揩閫熷畾浣嶇洰褰曪級銆?""
        try:
            p = self._norm_dir_for_dropdown(self.input_path.get())
            if p:
                self.input_path.set(p)

            if hasattr(self, "logger") and self.logger is not None and p:
                self.logger.info(
                    "宸查€夋嫨杈撳叆鏂囦欢澶硅矾寰勶紙鐢ㄤ簬蹇€熷畾浣嶏級锛歕n"
                    f"杈撳叆鏂囦欢澶逛綅缃? {p}\n"
                    "涓嬩竴姝ワ細璇风偣鍑汇€愭枃浠惰矾寰勩€戦€夋嫨鍏蜂綋鏂囦欢锛屾垨鍦ㄨ緭鍏ユ鎵嬪姩杈撳叆瀹屾暣鏂囦欢璺緞锛?txt / .001~.999锛夈€?
                )
        except Exception:
            pass

    def _on_input_path_enter(self, _event=None) -> None:
        """杈撳叆璺緞妗嗘寜鍥炶溅锛氭竻鐞嗚矾寰勫苟鍦ㄥ繀瑕佹椂鎻愮ず銆?
        璇存槑锛?            - 涓嶄細鑷姩寮瑰嚭鏂囦欢瀵硅瘽妗嗭紙閬垮厤璇Е鎵撴柇鎿嶄綔锛夛紱
            - 鑻ョ敤鎴锋墜鍔ㄨ緭鍏ョ殑鏄€滅洰褰曗€濓紝浼氭彁绀洪渶瑕侀€夋嫨鍏蜂綋鏂囦欢銆?        """
        try:
            raw = self.input_path.get() or ""
            clean = normalize_path_separators(raw.strip())
            if clean != raw.strip():
                self.input_path.set(clean)

            if clean and os.path.isdir(clean):
                if hasattr(self, "logger") and self.logger is not None:
                    self.logger.info(
                        "妫€娴嬪埌杈撳叆璺緞涓烘枃浠跺す锛歕n"
                        f"杈撳叆鏂囦欢澶逛綅缃? {clean}\n"
                        "鎻愮ず锛氳鐐瑰嚮銆愭枃浠惰矾寰勩€戦€夋嫨鍏蜂綋鏂囦欢锛屾垨鐩存帴杈撳叆鏂囦欢鍏ㄨ矾寰勶紙渚嬪 .../xxx.001锛夈€?
                    )
        except Exception:
            pass

    def _on_input_path_focus_out(self, _event=None) -> None:
        """杈撳叆璺緞妗嗗け鍘荤劍鐐癸細娓呯悊鎺у埗瀛楃涓庢贩鍚堝垎闅旂锛岄伩鍏嶅悗缁鍐欐姤閿欍€?""
        try:
            raw = self.input_path.get() or ""
            clean = normalize_path_separators(raw.strip())
            if clean != raw.strip():
                self.input_path.set(clean)
        except Exception:
            pass

    def _get_initialdir_for_open_file(self) -> Optional[str]:
        """鎺ㄥ鏂囦欢瀵硅瘽妗嗙殑 initialdir锛堢敤浜庢洿蹇畾浣嶇洰褰曪級銆?
        瑙勫垯锛?            - 杈撳叆妗嗘槸鐩綍 -> 鐩存帴浣跨敤锛?            - 杈撳叆妗嗘槸鏂囦欢 -> 浣跨敤鍏舵墍鍦ㄧ洰褰曪紱
            - 杈撳叆妗嗕负绌?-> 浼樺厛鏈€杩戠洰褰曪紝鍏舵棰勫埗鐩綍锛屽啀娆℃闈€?        """
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
        """妫€鏌ヨ緭鍏ヨ矾寰勬槸鍚︿负鈥滃瓨鍦ㄧ殑鏂囦欢鈥濄€?
        v208 鏂板锛?            - 鑻ヨ緭鍏ヨ矾寰勬槸鏂囦欢澶癸紙鐩綍锛夛紝浼氬湪鏃ュ織鏍忔彁绀哄浣曚慨鏀癸細
              * 涓嬫媺妗嗛€夋嫨鐨勫涓衡€滅洰褰曗€濓紝浠呯敤浜庢洿蹇畾浣嶏紱
              * 闇€瑕佺偣鍑汇€愭枃浠惰矾寰勩€戦€夋嫨鍏蜂綋鏂囦欢锛屾垨鍦ㄨ緭鍏ユ鎵嬪姩濉啓瀹屾暣鏂囦欢璺緞銆?
        杩斿洖锛?            - True锛氳緭鍏ヨ矾寰勬槸涓€涓瓨鍦ㄧ殑鏂囦欢锛?            - False锛氳緭鍏ヨ矾寰勪负绌?涓嶅瓨鍦?鏄枃浠跺す銆?        """
        in_path = normalize_path_separators((in_path or "").strip())
        if not in_path:
            self.logger.error(
                "杈撳叆鏂囦欢璺緞涓虹┖锛歕n"
                "  - 浣犲彲浠ョ偣鍑汇€愭枃浠惰矾寰勩€戦€夋嫨鏂囦欢锛沑n"
                "  - 涔熷彲浠ュ湪杈撳叆妗嗘墜鍔ㄨ緭鍏ュ畬鏁存枃浠惰矾寰勶紙.txt / .001~.999锛夛紱\n"
                "  - 涓嬫媺妗嗕富瑕佺敤浜庡揩閫熷畾浣嶉鍒舵枃浠跺す璺緞銆?
            )
            return False

        # 杈撳叆鏄洰褰曪紙鏂囦欢澶癸級
        try:
            if os.path.isdir(in_path):
                self.logger.error(
                    "妫€娴嬪埌杈撳叆璺緞鏄枃浠跺す锛堜笉鏄枃浠讹級锛歕n"
                    f"杈撳叆鏂囦欢澶逛綅缃? {in_path}\n"
                    "璇蜂慨鏀逛负鍏蜂綋鏂囦欢璺緞锛歕n"
                    "  1) 鐐瑰嚮銆愭枃浠惰矾寰勩€戝湪璇ユ枃浠跺す鍐呴€夋嫨鏂囦欢锛涙垨\n"
                    "  2) 鐩存帴鍦ㄨ緭鍏ユ绮樿创/鎵嬪姩杈撳叆鏂囦欢鍏ㄨ矾寰勶紙渚嬪 .../xxx.001 鎴?.../xxx.txt锛夈€?
                )
                return False
        except Exception:
            # os.path.isdir 鍑洪敊鏃跺拷鐣ワ紙缁х画璧版枃浠跺垽鏂級
            pass

        # v208 棰濆鍒ゆ柇锛?        # 濡傛灉鐢ㄦ埛浠庝笅鎷夋閫夋嫨浜嗏€滈鍒?妗岄潰/鏈€杩戠洰褰曗€濓紝鍗充究璇ョ洰褰曟鍒讳笉鍙揪锛堜緥濡傜綉缁滅洏鏂紑锛夛紝
        # 涔熷簲璇ユ彁绀衡€滀綘褰撳墠杈撳叆鐨勬槸鐩綍锛岄渶瑕侀€夋嫨鍏蜂綋鏂囦欢鈥濄€?        try:
            dir_key = self._norm_dir_for_dropdown(in_path).lower()
            dropdown_keys = {self._norm_dir_for_dropdown(p).lower() for p in self._input_dir_dropdown_values()}
            if dir_key and dir_key in dropdown_keys:
                self.logger.error(
                    "妫€娴嬪埌杈撳叆璺緞涓烘枃浠跺す锛堟潵鑷笅鎷夐」锛夛細\n"
                    f"杈撳叆鏂囦欢澶逛綅缃? {in_path}\n"
                    "璇蜂慨鏀逛负鍏蜂綋鏂囦欢璺緞锛歕n"
                    "  1) 鐐瑰嚮銆愭枃浠惰矾寰勩€戝湪璇ョ洰褰曞唴閫夋嫨鏂囦欢锛涙垨\n"
                    "  2) 鐩存帴鍦ㄨ緭鍏ユ绮樿创/鎵嬪姩杈撳叆鏂囦欢鍏ㄨ矾寰勶紙渚嬪 .../xxx.001 鎴?.../xxx.txt锛夈€?
                )
                return False
        except Exception:
            pass

        if not os.path.isfile(in_path):
            self.logger.error(f"杈撳叆鏂囦欢涓嶅瓨鍦細{in_path}")
            return False
        return True

    def on_choose_file(self):
        """GUI 浜嬩欢锛氶€夋嫨杈撳叆鏂囦欢銆?        
        娴佺▼锛?            1) 寮瑰嚭鏂囦欢閫夋嫨妗嗭紱
            2) 璇诲彇鏂囦欢锛堜紭鍏堣瘑鍒枃鏈紱蹇呰鏃跺皾璇?TAJM 瑙ｅ瘑锛夛紱
            3) 瑙ｆ瀽 StartOfData 鏁版嵁鍧楋紝鑷姩璇嗗埆 T1/T2锛?            4) 璁＄畻 H 涓?LG 鍒楄〃锛堝湪闈?DEBUG 妯″紡涓嬭緭鍑哄埌鏃ュ織锛夈€?        
        鍓綔鐢細
            - 鏇存柊 input_path/output_path/t1_var/t2_var/mg_var锛?            - 鍒锋柊缂撳瓨 _cached_parsed 涓?warp 鍩哄噯鐐广€?        """
        
        debug_enabled = bool(self.debug_var.get())
        with _scoped_ui_debug(self, debug_enabled):
            self.logger.debug("杩涘叆 on_choose_file")
            # v208锛氭枃浠跺璇濇鍒濆鐩綍锛坕nitialdir锛変紭鍏堜娇鐢ㄨ緭鍏ユ褰撳墠鐩綍/鏈€杩戠洰褰?棰勫埗鐩綍
            initialdir = self._get_initialdir_for_open_file()
            if initialdir:
                path = filedialog.askopenfilename(
                    title="閫夋嫨杈撳叆鏂囦欢",
                    initialdir=initialdir,
                    filetypes=[("鍏ㄩ儴鏂囦欢", "*.*"),
                               ("TMA 鏂囦欢", "*.001"),
                               ("TXT 鏂囦欢", "*.txt"),
                               ("骞夸箟tma鏂囦欢", NUM_EXT_PATTERNS)]
                )
            else:
                path = filedialog.askopenfilename(
                    title="閫夋嫨杈撳叆鏂囦欢",
                    filetypes=[("鍏ㄩ儴鏂囦欢", "*.*"),
                               ("TMA 鏂囦欢", "*.001"),
                               ("TXT 鏂囦欢", "*.txt"),
                               ("骞夸箟tma鏂囦欢", NUM_EXT_PATTERNS)]
                )
            if not path:return

            # 鍏堟鏌ユ枃浠舵槸鍚﹀瓨鍦紙鍏佽鐢ㄦ埛鎵嬪姩绮樿创璺緞鎴栫綉缁滅洏鐭殏鏂紑锛?            if not os.path.isfile(path):
                self.logger.error(f"杈撳叆鏂囦欢涓嶅瓨鍦細{path}")
                return

            path = normalize_path_separators(path)
            self.input_path.set(path)
            # v208锛氳褰曗€滄墜鍔ㄩ€夋嫨鏂囦欢鈥濇墍鍦ㄦ枃浠跺す鍒颁笅鎷夋锛堟渶澶氫繚鐣?3 涓級
            try:
                self._remember_input_dir(os.path.dirname(path))
            except Exception:
                pass
            # 姣忔鎵撳紑鏂版枃浠讹紝鍒锋柊 mg 榛樿鍊?            self.mg_var.set("0.50")

            # 鍒囨崲鏂囦欢鍚庯紝娓呯┖涓婁竴娆′慨鏀?缁樺浘缂撳瓨
            self._last_output_text = None  # 鏈€杩戜竴娆℃墽琛岃皟鏁村悗鐨勫畬鏁存枃鏈紙渚涚粯鍥?澶嶇敤锛?            self._last_output_parsed = None  # 鏈€杩戜竴娆℃墽琛岃皟鏁村悗鐨勮В鏋愮粨鏋滐紙渚涚粯鍥?澶嶇敤锛?            self._last_run_mg = None  # 鏈€杩戜竴娆℃墽琛岃皟鏁翠娇鐢ㄧ殑 mg锛堢敤浜庣粯鍥惧壇鏍囬/澶囨敞锛?
            base, ext = os.path.splitext(path)
            out_default = base + "_new" + (ext if ext else ".txt")
            self.output_path.set(out_default)
            self.logger.info("==========")
            self.logger.info(f"閫夋嫨鏂囦欢浣嶇疆: {path}.\n杈撳嚭鏂囦欢浣嶇疆: {out_default}")

            try:
                text, meta = load_text_prefer_tajm(path, self.logger)
                self.logger.debug(f"璇诲彇鏉ユ簮: {meta.get('used')}" + (f" rows={meta.get('rows')}" if meta.get('used')=='tajm' else ""))
                parsed = parse_lines(text)
                self._cached_parsed = parsed

                # 鉁?鍙粠 StartOfData 鍚庢彁鍙栫湡瀹炴暟鎹锛岄伩鍏?header 鏁板瓧骞叉壈 T2
                xs, ys, _line_idxs = extract_xy_from_file(parsed, self.logger)
                T1o, T2o = detect_T2_T1(xs, ys, self.logger)
                # 鏇存柊鎷変几绠楁硶鐨勫熀鍑嗙偣锛堥粯璁ゅ彇鑷姩璇嗗埆鍊硷級
                self._warp_base_t1 = T1o  # warp 鍩哄噯鐐癸細鍘熷/姊害绠楁硶寰楀埌鐨?T1锛堢敤浜?piecewise warp锛?                self._warp_base_t2 = T2o  # warp 鍩哄噯鐐癸細鍘熷/姊害绠楁硶寰楀埌鐨?T2锛堢敤浜?piecewise warp锛?                self.t1_var.set(f"{T1o:.6g}")
                self.t2_var.set(f"{T2o:.6g}")


                # INFO妯″紡涓嬶紝棰濆杈撳嚭T2瀵瑰簲楂樺害(H2)浠ュ強LG鍒楄〃
                try:
                    debug_enabled = bool(self.debug_var.get()) if hasattr(self, 'debug_var') else False
                except Exception:
                    debug_enabled = False
                if not debug_enabled:
                    # INFO 妯″紡鍙緭鍑哄叧閿粨鏋滐細H1/H2/H 涓?LG 鍒楄〃
                    try:
                        if not xs or not ys:
                            raise ValueError("鏈彁鍙栧埌鏈夋晥鏁版嵁琛岋紝鏃犳硶璁＄畻 H1/H2/LG銆?)
                        # H2锛歍2(宄板€兼渶澶?瀵瑰簲楂樺害
                        i_max = max(range(len(ys)), key=lambda i: ys[i])
                        H2 = float(ys[i_max])
                        # H1锛歍1 瀵瑰簲楂樺害锛堝彇鏈€鎺ヨ繎 T1 鐨勬暟鎹偣锛?                        i_t1 = min(range(len(xs)), key=lambda i: abs(xs[i] - T1o))
                        H1 = float(ys[i_t1])
                        H = H2 - H1
                        h_message = f"""淇℃伅Message
    T1={T1o} 掳C
    T2={T2o} 掳C
    T1瀵瑰簲楂樺害(H1): {format_height_um(H1)} 渭m
    T2瀵瑰簲楂樺害(H2): {format_height_um(H2)} 渭m
    楂樺害宸瓾=H2-H1: {format_height_um(H)} 渭m"""

                        self.logger.info(f"{h_message}")
                        mg_values = [round(0.45 + 0.01 * i, 2) for i in range(11)]
                        lg_s = compute_lg_list(mg_values, H, logger=self.logger)
                        self.logger.info(lg_s)
                    except Exception as _e:
                        self.logger.error(f"LG璁＄畻澶辫触锛歿_e}")
                        
                    #self.logger.info(f"鑷姩璇嗗埆骞跺～鍏? T1={T1o}, T2={T2o}")

            except Exception as e:
                self.logger.exception("璇诲彇/璇嗗埆 T1/T2 澶辫触")
                messagebox.showerror("閿欒", f"璇诲彇/璇嗗埆T1/T2澶辫触锛歕n{e}")

    def on_choose_output(self):
        """GUI 浜嬩欢锛氶€夋嫨杈撳嚭鏂囦欢璺緞锛堜繚瀛樹负鏂版枃浠讹紝涓嶈鐩栧師濮嬫暟鎹級銆?        
        璇存槑锛?            - 杈撳嚭鏂囨湰榛樿浣跨敤 UTF-16LE + BOM锛屼究浜?Windows 杞欢绋冲畾璇嗗埆缂栫爜銆?        """
        
        debug_enabled = bool(self.debug_var.get()) if hasattr(self, 'debug_var') else False
        with _scoped_ui_debug(self, debug_enabled):
            self.logger.debug("杩涘叆 on_choose_output")
            path = filedialog.asksaveasfilename(
                title="閫夋嫨杈撳嚭淇濆瓨璺緞",
                defaultextension=".txt",
                filetypes=[("鏂囨湰鏂囦欢", "*.txt"),
                           ("鍏ㄩ儴鏂囦欢", "*.*"),
                           ("娆查棶閰掑浣曞鏈?, "*.001"),
                           ("鐗х閬ユ寚鏉忚姳鏉?, "*.002")]
            )
            if not path:
                return
            path = normalize_path_separators(path)
            self.output_path.set(path)
            self.logger.info(f"閫夋嫨杈撳嚭璺緞: {path}")

    def on_precise_read(self):
        """姊害绠楁硶锛堝師鈥滅簿瀵嗚鍙栤€濓級锛氫粎鏇存柊 T1锛汿2 濮嬬粓鍙栨渶澶у嘲銆?""
        in_path = normalize_path_separators(self.input_path.get().strip())
        if not self._check_input_file_exists(in_path):
            return

        debug_enabled = bool(self.debug_var.get()) if hasattr(self, "debug_var") else False

        # 鍒嗛殧绗?        self.logger.info("==========")
        self.logger.info("寮€濮嬫搴︾畻娉曪紙浠呮洿鏂癟1锛孴2=鏈€澶у嘲涓嶅彉锛?)

        with _scoped_ui_debug(self, debug_enabled):
            try:
                # 璇诲彇/瑙ｆ瀽
                if self._cached_parsed is None:
                    self.logger.debug("璋冪敤 load_text_prefer_tajm()")
                    text, meta = load_text_prefer_tajm(in_path, self.logger)
                    src_used = meta.get("used")
                    rows = meta.get("rows")
                    if debug_enabled:
                        self.logger.debug(f"璇诲彇鏉ユ簮: {src_used}" + (f" rows={rows}" if src_used == "tajm" else ""))
                    parsed = parse_lines(text)
                else:
                    parsed = self._cached_parsed

                self.logger.debug("璋冪敤 extract_xy_from_file()")
                xs, ys, _line_idxs = extract_xy_from_file(parsed, self.logger)
                if not xs:
                    raise ValueError("鏈彁鍙栧埌鏁版嵁琛岋紙StartOfData 鍚庢湭鍙戠幇杩炵画 5 鍒楁暟鍊兼暟鎹級銆?)

                # 姊害绠楁硶
                self.logger.debug("璋冪敤 detect_T2_T1_precise()")
                T1_new, T2, _meta = detect_T2_T1_precise(xs, ys, self.logger, debug=debug_enabled)

                # 鍙洿鏂?T1锛圱2 淇濇寔鏈€澶у嘲锛?                T1_old = float(self.t1_var.get().strip()) if self.t1_var.get().strip() else T1_new
                self.t1_var.set(f"{T1_new:.6g}")
                self.t2_var.set(f"{T2:.6g}")

                # 鍏抽敭锛氬悗缁墽琛岃皟鏁翠互鈥滄柊T1鈥濅负鍩哄噯锛堜慨澶嶏細鎸夋棫T1鏀剧缉锛?                self._warp_base_t1 = T1_new  # warp 鍩哄噯鐐癸細鍘熷/姊害绠楁硶寰楀埌鐨?T1锛堢敤浜?piecewise warp锛?                self._warp_base_t2 = T2  # warp 鍩哄噯鐐癸細鍘熷/姊害绠楁硶寰楀埌鐨?T2锛堢敤浜?piecewise warp锛?
                # H1/H2/H 涓?LG锛圚=H2-H1锛?                i1 = min(range(len(xs)), key=lambda i: abs(xs[i] - T1_new))
                i2 = min(range(len(xs)), key=lambda i: abs(xs[i] - T2))
                H1 = ys[i1]
                H2 = ys[i2]
                H = H2 - H1

                mg_values = [round(0.45 + 0.01 * i, 2) for i in range(11)]
                lg_s = compute_lg_list(mg_values, H, logger=self.logger)

                info_block = (
                    f"姊害绠楁硶瀹屾垚锛歕n"
                    f"    T1: {T1_old:.6g} 鈫?{T1_new:.6g} 掳C\n"
                    f"    T2: {T2:.6g} 掳C锛堟渶澶у嘲锛塡n"
                    f"    H1: {format_height_um(H1)}\n"
                    f"    H2: {format_height_um(H2)}\n"
                    f"    H=H2-H1: {format_height_um(H)}"
                )
                self.logger.info(info_block)
                self.logger.info(lg_s)

            except Exception as e:
                self.logger.exception("姊害绠楁硶澶辫触")


    def on_super_gradient_read(self):
        """瓒呯骇姊害绠楁硶锛氫粎鏇存柊 T1锛汿2 濮嬬粓鍙栨渶澶у嘲銆?""
        in_path = normalize_path_separators(self.input_path.get().strip())
        if not self._check_input_file_exists(in_path):
            return

        debug_enabled = bool(self.debug_var.get()) if hasattr(self, "debug_var") else False

        self.logger.info("==========")
        self.logger.info("寮€濮嬭秴绾ф搴︾畻娉曪紙浠呮洿鏂癟1锛孴2=鏈€澶у嘲涓嶅彉锛?)

        with _scoped_ui_debug(self, debug_enabled):
            try:
                if self._cached_parsed is None:
                    self.logger.debug("璋冪敤 load_text_prefer_tajm()")
                    text, meta = load_text_prefer_tajm(in_path, self.logger)
                    src_used = meta.get("used")
                    rows = meta.get("rows")
                    if debug_enabled:
                        self.logger.debug(f"璇诲彇鏉ユ簮: {src_used}" + (f" rows={rows}" if src_used == "tajm" else ""))
                    parsed = parse_lines(text)
                else:
                    parsed = self._cached_parsed

                self.logger.debug("璋冪敤 extract_xy_from_file()")
                xs, ys, _line_idxs = extract_xy_from_file(parsed, self.logger)
                if not xs:
                    raise ValueError("鏈彁鍙栧埌鏁版嵁琛岋紙StartOfData 鍚庢湭鍙戠幇杩炵画 5 鍒楁暟鍊兼暟鎹級銆?)

                self.logger.debug("璋冪敤 detect_T2_T1_super_gradient()")
                T1_new, T2, meta = detect_T2_T1_super_gradient(xs, ys, self.logger, debug=debug_enabled)

                T1_old = float(self.t1_var.get().strip()) if self.t1_var.get().strip() else T1_new
                self.t1_var.set(f"{T1_new:.6g}")
                self.t2_var.set(f"{T2:.6g}")

                self._warp_base_t1 = T1_new  # warp 鍩哄噯鐐癸細鍘熷/姊害绠楁硶寰楀埌鐨?T1锛堢敤浜?piecewise warp锛?                self._warp_base_t2 = T2  # warp 鍩哄噯鐐癸細鍘熷/姊害绠楁硶寰楀埌鐨?T2锛堢敤浜?piecewise warp锛?
                i1 = min(range(len(xs)), key=lambda i: abs(xs[i] - T1_new))
                i2 = min(range(len(xs)), key=lambda i: abs(xs[i] - T2))
                H1 = ys[i1]
                H2 = ys[i2]
                H = H2 - H1

                mg_values = [round(0.45 + 0.01 * i, 2) for i in range(11)]
                lg_s = compute_lg_list(mg_values, H, logger=self.logger)

                info_block = (
                    f"瓒呯骇姊害绠楁硶瀹屾垚锛歕n"
                    f"    T1: {T1_old:.6g} 鈫?{T1_new:.6g} 掳C\n"
                    f"    T2: {T2:.6g} 掳C锛堟渶澶у嘲锛塡n"
                    f"    H1: {format_height_um(H1)}\n"
                    f"    H2: {format_height_um(H2)}\n"
                    f"    H=H2-H1: {format_height_um(H)}"
                )
                self.logger.info(info_block)
                self.logger.info(lg_s)

                if debug_enabled:
                    self.logger.debug(f"super_meta: {meta}")

            except Exception as e:
                self.logger.exception("瓒呯骇姊害绠楁硶澶辫触")


    def on_execute(self):
        """GUI 浜嬩欢锛氭墽琛屾洸绾胯皟鏁村苟鍐欏嚭鏂版枃浠躲€?        
        涓昏姝ラ锛?            1) 璇诲彇 UI 杈撳叆鐨?T1n/T2n/mg锛?            2) 璋冪敤 apply_warp() 杩涜娓╁害杞?warp + 鍗曡皟淇 + mg 缂╂斁锛?            3) 鍐欏嚭鍒?output_path锛涘苟缂撳瓨淇敼鍚庢枃鏈緵缁樺浘澶嶇敤銆?        
        娉ㄦ剰锛?            - DEBUG 妯″紡涓嬩細棰濆杈撳嚭鑰楁椂涓?tracemalloc 鍐呭瓨宄板€笺€?        """
        
        raw_in = self.input_path.get()
        raw_out = self.output_path.get()
        in_path = normalize_path_separators((raw_in or "").strip())
        out_path = normalize_path_separators((raw_out or "").strip())

        # 鑻ョ敤鎴风矘璐?鑴氭湰鍐欏叆鏃舵贩鍏ヤ簡鎹㈣绛夋帶鍒跺瓧绗︼紝鍚屾娓呯悊鍚庣殑缁撴灉鍥炶緭鍏ユ
        try:
            if (raw_in or "").strip() != in_path:
                self.logger.info(f"妫€娴嬪埌杈撳叆璺緞鍖呭惈寮傚父瀛楃锛堝鎹㈣锛塡n宸茶嚜鍔ㄦ竻鐞哱n鐜?>[{in_path}]\n鍘?>[{raw_in}]")
                self.input_path.set(in_path)
            if (raw_out or "").strip() != out_path:
                self.logger.info(f"妫€娴嬪埌杈撳嚭璺緞鍖呭惈寮傚父瀛楃锛堝鎹㈣锛塡n宸茶嚜鍔ㄦ竻鐞?\n鐜?>[{out_path}]\n鍘?>[{raw_out}]")
                self.output_path.set(out_path)
        except Exception:
            pass
    
        if not self._check_input_file_exists(in_path):
            return
        if not out_path:
            self.logger.error("杈撳嚭鏂囦欢璺緞涓虹┖锛氳鍏堥€夋嫨杈撳嚭鏂囦欢璺緞銆?)
            return
    
        # 浠呭鏈鈥滄墽琛屼慨鏀光€濇祦绋嬬敓鏁堬細鎵ц鍓嶈鍙栦竴娆″閫夋鐘舵€?        debug_enabled = bool(self.debug_var.get())
        if debug_enabled:
            # 杩欐潯鏄?INFO锛圲I 鍙锛?            self.logger.info("鈿狅笍 DEBUG淇℃伅妯″紡宸插紑鍚細鏄剧ず璇︾粏鏃ュ織")
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
                    messagebox.showerror("閿欒", "T1/T2/mg 杈撳叆蹇呴』鏄暟瀛椼€?)
                    return
    
                # UI 閲屽彧鏄剧ず鍏抽敭 INFO
                self.logger.info(f"寮€濮嬫墽琛屼慨鏀癸細T1={T1n}  T2={T2n}  mg={mg}")
    
                # 璇︾粏淇℃伅锛堜粎鍐欏叆 debug_log锛?                self.logger.debug("========== 寮€濮嬫墽琛屼慨鏀?==========")
                self.logger.debug(f"杈撳叆鏂囦欢: {in_path}")
                self.logger.debug(f"杈撳嚭鏂囦欢: {out_path}")
    
                if self._cached_parsed is None:
                    text, meta = load_text_prefer_tajm(in_path, self.logger)
                    self.logger.debug(
                        f"鎵ц鏃惰鍙栨潵婧? {meta.get('used')}"
                        + (f" rows={meta.get('rows')}" if meta.get('used') == 'tajm' else "")
                    )
                    parsed = parse_lines(text)
                    self._cached_parsed = parsed
                else:
                    parsed = self._cached_parsed
    
                new_text, T1o, T2o = apply_warp(
                    parsed, T1n=T1n, T2n=T2n, mg=mg, logger=self.logger,
                    T1o_override=self._warp_base_t1,  # warp 鍩哄噯鐐癸細鍘熷/姊害绠楁硶寰楀埌鐨?T1锛堢敤浜?piecewise warp锛?                    T2o_override=self._warp_base_t2,  # warp 鍩哄噯鐐癸細鍘熷/姊害绠楁硶寰楀埌鐨?T2锛堢敤浜?piecewise warp锛?                )
                # 纭繚杈撳嚭鐩綍瀛樺湪锛堢敤鎴锋墜鍔ㄨ緭鍏ユ柊鐩綍鏃舵洿绋筹級
                try:
                    out_dir = os.path.dirname(out_path)
                    if out_dir and (not os.path.isdir(out_dir)):
                        os.makedirs(out_dir, exist_ok=True)
                except Exception:
                    pass
                write_utf16le_with_bom(out_path, new_text)

                # 缂撳瓨鏈淇敼缁撴灉锛堜緵鈥滃紑濮嬬粯鍥锯€濈洿鎺ヤ娇鐢級
                self._last_output_text = new_text  # 鏈€杩戜竴娆℃墽琛岃皟鏁村悗鐨勫畬鏁存枃鏈紙渚涚粯鍥?澶嶇敤锛?                try:self._last_output_parsed = parse_lines(new_text)  # 鏈€杩戜竴娆℃墽琛岃皟鏁村悗鐨勮В鏋愮粨鏋滐紙渚涚粯鍥?澶嶇敤锛?                except Exception:self._last_output_parsed = None  # 鏈€杩戜竴娆℃墽琛岃皟鏁村悗鐨勮В鏋愮粨鏋滐紙渚涚粯鍥?澶嶇敤锛?                self._last_run_mg = mg  # 鏈€杩戜竴娆℃墽琛岃皟鏁翠娇鐢ㄧ殑 mg锛堢敤浜庣粯鍥惧壇鏍囬/澶囨敞锛?    
                self.logger.info(f"鉁?淇敼瀹屾垚锛歿out_path}")
        except Exception as e:
            self.logger.exception("鎵ц淇敼澶辫触")
            messagebox.showerror("閿欒", f"鎵ц淇敼澶辫触锛歕n{e}")
        finally:
            if debug_enabled:
                elapsed = time.perf_counter() - t0
                mem_info = ""
                if tracemalloc_started:
                    try:
                        cur, peak = tracemalloc.get_traced_memory()
                        mem_info = f" | 鍐呭瓨(Tracemalloc): current={cur/1024:.1f}KB, peak={peak/1024:.1f}KB"
                    except Exception:
                        pass
                    try:
                        tracemalloc.stop()
                    except Exception:
                        pass
                # DEBUG 妯″紡涓嬫樉绀衡€滄墽琛岃€楁椂 / 鍐呭瓨鍗犵敤鈥濓紙INFO 杈撳嚭锛孶I 鍙锛?                self.logger.info(f"鈿狅笍 DEBUG鎸囨爣: 鎵ц鑰楁椂={elapsed:.3f}s{mem_info}")

    def on_plot(self):
        """GUI 浜嬩欢锛氭墦寮€/鍒锋柊缁樺浘绐楀彛銆?        
        缁樺浘鏁版嵁鏉ユ簮锛?            - 浼樺厛浣跨敤鏈€杩戜竴娆♀€滄墽琛岃皟鏁粹€濈殑缁撴灉锛堟洿绗﹀悎鐢ㄦ埛鐪嬪埌鐨勬洸绾匡級锛?            - 鑻ュ皻鏈墽琛岃皟鏁达紝鍒欑粯鍒跺師濮嬭緭鍏ユ枃浠躲€?        
        鍔熻兘锛?            - 缁樺埗鏇茬嚎涓庣綉鏍硷紱
            - 鏍囨敞 T1/T2 涓庨珮搴﹀樊锛?            - 鏀寔瀵煎嚭 TIFF 涓庘€滀豢鐢熻緭鍑衡€濄€?        """
        
        in_path = normalize_path_separators(self.input_path.get().strip())
        out_path = normalize_path_separators(self.output_path.get().strip())
        if not self._check_input_file_exists(in_path):
            return

        # 浠呭鏈鈥滃紑濮嬬粯鍥锯€濇祦绋嬬敓鏁堬細鎵ц鍓嶈鍙栦竴娆″閫夋鐘舵€?        debug_enabled = bool(self.debug_var.get())
        if debug_enabled:
            self.logger.info("鈿狅笍 DEBUG淇℃伅妯″紡宸插紑鍚細鏄剧ず璇︾粏鏃ュ織")

        with _scoped_ui_debug(self, debug_enabled):
            try:
                # 閫夋嫨鏁版嵁婧愶細浼樺厛浣跨敤鏈€杩戜竴娆♀€滄墽琛屼慨鏀光€濈殑缁撴灉锛涘惁鍒欎娇鐢ㄥ師濮嬭緭鍏ユ枃浠?                if self._last_output_parsed is not None:  # 鏈€杩戜竴娆℃墽琛岃皟鏁村悗鐨勮В鏋愮粨鏋滐紙渚涚粯鍥?澶嶇敤锛?                    parsed = self._last_output_parsed  # 鏈€杩戜竴娆℃墽琛岃皟鏁村悗鐨勮В鏋愮粨鏋滐紙渚涚粯鍥?澶嶇敤锛?                    src_tag = "淇敼鍚?
                    mg_for_title = self._last_run_mg  # 鏈€杩戜竴娆℃墽琛岃皟鏁翠娇鐢ㄧ殑 mg锛堢敤浜庣粯鍥惧壇鏍囬/澶囨敞锛?                else:
                    if self._cached_parsed is None:
                        text, meta = load_text_prefer_tajm(in_path, self.logger)
                        self.logger.debug(
                            f"缁樺浘鏃惰鍙栨潵婧? {meta.get('used')}"
                            + (f" rows={meta.get('rows')}" if meta.get('used') == 'tajm' else "")
                        )
                        parsed = parse_lines(text)
                        self._cached_parsed = parsed
                    else:
                        parsed = self._cached_parsed
                    src_tag = "鍘熷"
                    mg_for_title = None

                xs, ys, _line_idxs = extract_xy_from_file(parsed, self.logger)
                if not xs or not ys:
                    raise ValueError("鏈彁鍙栧埌缁樺浘鏁版嵁锛堣纭 StartOfData 鍚庡瓨鍦?5 鍒楁暟鎹紝涓旂2/3鍒椾负娓╁害/楂樺害锛夈€?)

                # 璇诲彇褰撳墠 UI 鐨?T1/T2锛堢敤浜庢爣娉級

                try:
                    t1 = float(self.t1_var.get().strip())
                    t2 = float(self.t2_var.get().strip())
                except Exception:
                    messagebox.showwarning("鎻愮ず", "璇峰厛姝ｇ‘璁剧疆 T1/T2銆?)
                    return

                # INFO锛氱粯鍥惧弬鏁版眹鎬伙紙渚夸簬澶嶆牳锛涜矾寰勪細鑷姩鏍囩孩锛?                mg_for_log = self._format_mg_for_note(self.mg_var.get())
                self.logger.info(
                    "缁樺浘鍙傛暟锛歕n"
                    f"    鏁版嵁鏉ユ簮: {src_tag}\n"
                    f"    杈撳叆鏂囦欢浣嶇疆: {in_path}\n"
                    f"    杈撳嚭鏂囦欢浣嶇疆: {out_path}\n"
                    f"    T1={t1:.6g} 掳C, T2={t2:.6g} 掳C, mg={mg_for_log} mg"
                )

                # subtitle 璐ㄩ噺锛氫紭鍏堜娇鐢ㄦ渶杩戜竴娆℃墽琛屼慨鏀圭殑 mg锛涘惁鍒欑敤褰撳墠杈撳叆妗?mg
                mg_val = None
                if mg_for_title is not None:
                    mg_val = mg_for_title
                else:
                    try:
                        mg_val = float(self.mg_var.get().strip())
                    except Exception:
                        mg_val = None


                # 鍒濆鍖栫粯鍥剧獥鍙?mg 杈撳叆妗嗭紙浠呯敤浜庡浘涓娉紝涓嶅奖鍝嶄富鐣岄潰 mg锛?                if mg_val is not None:
                    mg_raw = self.mg_var.get().strip()
                    self._plot_mg_var.set(mg_raw if mg_raw else f"{mg_val:.2f}")  # 缁樺浘绐楀彛 mg(鏍囨敞) 杈撳叆妗嗗彉閲忥紙浠呭奖鍝嶅浘涓枃瀛楋級
                else:
                    self._plot_mg_var.set("")  # 缁樺浘绐楀彛 mg(鏍囨敞) 杈撳叆妗嗗彉閲忥紙浠呭奖鍝嶅浘涓枃瀛楋級

                # ---- 璁＄畻 y 杞磋寖鍥达紙鏂拌鍒欙級----
                y_min_data = float(min(ys))
                y_max_data = float(max(ys))

                # 鍩虹涓嬮檺锛氳嫢鏈€灏忓€?> -200 渭m锛屽垯涓嬮檺鍥哄畾涓?-200锛涘惁鍒欏悜涓嬪彇鏁村埌 500 鐨勬暣鏁板€?                if y_min_data > -200.0:
                    y0_base = -200.0
                else:
                    y0_base = math.floor(y_min_data / 500.0) * 500.0

                # 鍩虹涓婇檺锛氬悜涓婂彇鏁村埌 500 鐨勬暣鏁板€?                y1_base = math.ceil(y_max_data / 500.0) * 500.0
                if y1_base < 0:
                    y1_base = 0.0
                if y1_base <= y0_base:
                    y1_base = y0_base + 500.0

                # 瀹為檯缁樺浘鑼冨洿锛堜細鍥犳爣娉ㄨ秴妗嗚€屽姩鎬佽皟鏁达級
                y0_plot = float(y0_base)
                y1_plot = float(y1_base)

                # 鎵惧埌 T1/T2 瀵瑰簲鐨勭偣锛堢敤浜庡垽鏂爣娉ㄦ槸鍚︿細瓒呮锛?                idx1 = int(min(range(len(xs)), key=lambda i: abs(xs[i] - t1)))
                idx2 = int(min(range(len(xs)), key=lambda i: abs(xs[i] - t2)))
                x1_pt, y1_pt = float(xs[idx1]), float(ys[idx1])
                x2_pt, y2_pt = float(xs[idx2]), float(ys[idx2])

                def _ann_margin(cur_y0: float, cur_y1: float) -> float:
                    # 鐢ㄤ簬浼拌鈥滄枃瀛楁爣娉ㄢ€濆湪 y 鏂瑰悜鍙兘鍗犵敤鐨勭┖闂达紙缁忛獙鍊硷級
                    """浼扮畻鏍囨敞鏂囧瓧鍦?y 鏂瑰悜鍗犵敤鐨勭┖闂达紙缁忛獙鍊硷級銆?                    
                    鐢ㄩ€旓細
                        缁樺浘鏃堕渶瑕佸垽鏂?T1/T2 鏍囨敞鏄惁浼氳秴鍑哄潗鏍囪酱鑼冨洿锛?                        閫氳繃璇ュ嚱鏁扮粰鍑轰竴涓笌 y 杞磋寖鍥寸浉鍏崇殑 margin銆?                    """
                    
                    yr = max(1.0, cur_y1 - cur_y0)
                    return max(80.0, yr * 0.04)

                ann_margin = _ann_margin(y0_plot, y1_plot)

                # 鑻?T2 娓╁害鏍囨敞浼氳秴鍑烘锛屽垯涓婇檺鎶珮 200锛堟爣娉ㄥ埢搴︿粛浠?y1_base 涓哄噯锛?                if y2_pt + ann_margin > y1_plot:
                    y1_plot += 200.0
                    ann_margin = _ann_margin(y0_plot, y1_plot)

                # 鑻?T1 娓╁害鏍囨敞锛堢偣涓嬫柟锛変細瓒呭嚭妗嗭細y 杞翠笅闄愭瘡娆￠澶栭檷浣?100锛岀洿鍒颁笉瓒呭嚭
                while y1_pt - ann_margin < y0_plot:
                    y0_plot -= 100.0
                    ann_margin = _ann_margin(y0_plot, y1_plot)

                if y1_plot <= y0_plot:
                    y1_plot = y0_plot + 500.0

                # y 杞村埢搴︼細
                # - 鑻ヤ笅闄?> -500锛氭爣娉ㄢ€滃綋鍓嶄笅闄愩€?銆?00銆?000...鈥?                # - 鑻ヤ笅闄?<= -500锛氬湪涓婅堪鍩虹涓婇澶栧鍔?-500
                y_ticks_major = [float(y0_plot), 0.0]
                if y0_plot < -500.0 - 1e-9:
                    y_ticks_major.append(-500.0)
                y_ticks_major.extend([float(v) for v in range(500, int(y1_base) + 1, 500)])
                # 杩囨护骞跺幓閲嶆帓搴?                y_ticks_major = sorted({v for v in y_ticks_major if y0_plot - 1e-9 <= v <= y1_base + 1e-9})

                # 灏忓埢搴︼細姣?100 涓€涓紙瑕嗙洊缁樺浘鑼冨洿锛屼究浜庤櫄绾胯儗鏅?灏忓埢搴︽樉绀猴級
                y_minor_start = int(math.floor(y0_plot / 100.0) * 100)
                y_minor_end = int(math.ceil(y1_plot / 100.0) * 100)
                y_ticks_minor = list(range(y_minor_start, y_minor_end + 1, 100))
# ---- 鍒涘缓/澶嶇敤缁樺浘绐楀彛 ----
                if self._plot_win is not None and self._plot_win.winfo_exists():  # 缁樺浘绐楀彛锛圱oplevel锛夊紩鐢紝鐢ㄤ簬澶嶇敤/閬垮厤閲嶅鍒涘缓
                    win = self._plot_win  # 缁樺浘绐楀彛锛圱oplevel锛夊紩鐢紝鐢ㄤ簬澶嶇敤/閬垮厤閲嶅鍒涘缓
                    # 娓呯悊鏃?canvas
                    if self._plot_canvas is not None:  # Matplotlib 鐢诲竷锛團igureCanvasTkAgg锛夊紩鐢?                        try:self._plot_canvas.get_tk_widget().destroy()  # Matplotlib 鐢诲竷锛團igureCanvasTkAgg锛夊紩鐢?                        except Exception:pass
                        self._plot_canvas = None  # Matplotlib 鐢诲竷锛團igureCanvasTkAgg锛夊紩鐢?                else:
                    win = tk.Toplevel(self.root)
                    win.title("TMA - 缁樺浘")
                    place_window_bottom_right(win, 1000, 650)
                    self._plot_win = win  # 缁樺浘绐楀彛锛圱oplevel锛夊紩鐢紝鐢ㄤ簬澶嶇敤/閬垮厤閲嶅鍒涘缓

                                # 绐楀彛瀹氫綅锛氬彸涓嬭锛堟瘡娆＄粯鍥鹃兘閲嶇疆浣嶇疆锛?                place_window_bottom_right(win, 1000, 650)

# 宸ュ叿鏍忥紙瀵煎嚭 TIFF锛?                if self._plot_toolbar is not None:  # 缁樺浘绐楀彛宸ュ叿鏍?Frame锛堟斁瀵煎嚭鎸夐挳绛夛級
                    try:
                        self._plot_toolbar.destroy()  # 缁樺浘绐楀彛宸ュ叿鏍?Frame锛堟斁瀵煎嚭鎸夐挳绛夛級
                    except Exception:
                        pass
                    self._plot_toolbar = None  # 缁樺浘绐楀彛宸ュ叿鏍?Frame锛堟斁瀵煎嚭鎸夐挳绛夛級
                toolbar = ttk.Frame(win)
                toolbar.pack(fill='x', padx=6, pady=6)
                self._plot_toolbar = toolbar  # 缁樺浘绐楀彛宸ュ叿鏍?Frame锛堟斁瀵煎嚭鎸夐挳绛夛級

                def _export_tiff():
                    # 鑻ョ敤鎴峰湪缁樺浘绐楀彛淇敼浜?mg(鏍囨敞)锛屽厛鍒锋柊澶囨敞鏂囨湰
                    """瀵煎嚭褰撳墠缁樺浘涓?.tif锛堟爣鍑嗗懡鍚嶏細<鍘熸枃浠跺悕>.tif锛夈€?                    
                    璇存槑锛?                        - 杈撳嚭鍒嗚鲸鐜囧浐瀹氫负 3840x2160锛?6:9锛堾300dpi锛?                        - 鍐欏叆 TIFF 鍏冧俊鎭細浣滆€?Artist)銆丏ateTime銆丷esolution銆?                        - 鏀寔鈥滃惎鐢ㄦ柊璺緞鈥濇椂杈撳嚭鍒版寚瀹氱洰褰曘€?                    """
                    
                    try:
                        _refresh_method_note()
                    except Exception:
                        pass
                    try:
                        if self._plot_fig is None:  # Matplotlib Figure 寮曠敤锛堢敤浜庡鍑?鍒锋柊锛?                            raise RuntimeError('鏈壘鍒板彲瀵煎嚭鐨勫浘鍍忋€?)
                        # 杈撳嚭璺緞锛氬師鏂囦欢鍚?tif锛岃矾寰勪笉鍙?                        base = os.path.splitext(os.path.basename(in_path))[0]
                        out_dir = normalize_path_separators(os.path.dirname(in_path))

                        try:

                            if getattr(self, 'export_use_newpath_var', None) is not None and bool(self.export_use_newpath_var.get()):

                                cand = (self.export_newpath_var.get() or '').strip()

                                if cand and os.path.isdir(cand):

                                    out_dir = cand

                        except Exception:

                            pass

                        tif_path = join_keep_style(out_dir, base + '.tif')
                        fig = self._plot_fig  # Matplotlib Figure 寮曠敤锛堢敤浜庡鍑?鍒锋柊锛?                        # 浠?16:9 杈撳嚭 3840x2160锛宲pi=300锛?.4x3.6 inch @ 300dpi锛?                        from io import BytesIO
                        from PIL import Image, TiffImagePlugin
                        old_size = tuple(fig.get_size_inches())

                        try:
                            fig.set_size_inches(12.8, 7.2, forward=True)
                            buf = BytesIO()
                            fig.savefig(buf, format='tiff', dpi = 300)
                            buf.seek(0)
                        finally:
                            # 杩樺師鐢诲竷灏哄锛岄伩鍏嶅奖鍝嶇獥鍙ｆ樉绀?                            try:
                                fig.set_size_inches(old_size[0], old_size[1], forward=True)
                                if self._plot_canvas is not None:  # Matplotlib 鐢诲竷锛團igureCanvasTkAgg锛夊紩鐢?                                    try:
                                        self._plot_canvas.draw_idle()  # Matplotlib 鐢诲竷锛團igureCanvasTkAgg锛夊紩鐢?                                    except Exception:pass
                            except Exception:pass
                        img = Image.open(buf)
                        # TIFF 鍏冧俊鎭細浣滆€?鎷嶆憚鏃ユ湡/ppi
                        tiffinfo = TiffImagePlugin.ImageFileDirectory_v2()
                        tiffinfo[315] = "TMAmax"  # Artist/浣滆€?                        # 鏈湴鏃堕棿锛圷YYY:MM:DD HH:MM:SS锛?                        dt_str = datetime.datetime.now().astimezone().strftime("%Y:%m:%d %H:%M:%S")
                        tiffinfo[306] = dt_str  # DateTime
                        # 300 ppi
                        tiffinfo[282] = TiffImagePlugin.IFDRational(300, 1)  # XResolution
                        tiffinfo[283] = TiffImagePlugin.IFDRational(300, 1)  # YResolution
                        tiffinfo[296] = 2         # ResolutionUnit: inch
                        # 鏃犳崯鍘嬬缉淇濆瓨锛堜綋绉洿灏忥級
                        img.save(
                            tif_path,
                            compression='tiff_adobe_deflate',
                            tiffinfo=tiffinfo,
                            dpi=(300, 300),)
                        self.logger.info(f'宸茬敓鎴怲IFF鍥? {tif_path}')
                        messagebox.showinfo('瀹屾垚', f'宸茬敓鎴怲IFF鍥撅細\n{tif_path}')
                    except Exception as ee:
                        self.logger.exception('鐢熸垚TIFF澶辫触')
                        messagebox.showerror('閿欒', f'鐢熸垚TIFF澶辫触锛歕n{ee}')
                def _export_tiff_universal():
                    # 鑻ョ敤鎴峰湪缁樺浘绐楀彛淇敼浜?mg(鏍囨敞)锛屽厛鍒锋柊澶囨敞鏂囨湰
                    """瀵煎嚭褰撳墠缁樺浘涓衡€滀豢鐢熻緭鍑衡€漈IFF锛堝懡鍚嶏細Universal - <鍘熸枃浠跺悕>.tif锛夈€?                    
                    璇存槑锛?                        - 涓?_export_tiff() 鍚屽弬鏁?鍚屽厓淇℃伅锛屽彧鏄枃浠跺悕鍓嶇紑涓嶅悓銆?                        - 甯哥敤浜庨渶瑕佸尯鍒嗏€滄爣鍑嗚緭鍑?浠跨敓杈撳嚭鈥濈殑涓氬姟娴佺▼銆?                    """
                    
                    try:
                        _refresh_method_note()
                    except Exception:
                        pass
                    try:
                        if self._plot_fig is None:  # Matplotlib Figure 寮曠敤锛堢敤浜庡鍑?鍒锋柊锛?                            raise RuntimeError('鏈壘鍒板彲瀵煎嚭鐨勫浘鍍忋€?)
                        # 杈撳嚭璺緞锛歎niversal - 鍘熸枃浠跺悕.tif锛岃矾寰勪笉鍙?                        base = os.path.splitext(os.path.basename(in_path))[0]
                        out_dir = normalize_path_separators(os.path.dirname(in_path))

                        try:

                            if getattr(self, 'export_use_newpath_var', None) is not None and bool(self.export_use_newpath_var.get()):

                                cand = (self.export_newpath_var.get() or '').strip()

                                if cand and os.path.isdir(cand):

                                    out_dir = cand

                        except Exception:

                            pass

                        tif_path = join_keep_style(out_dir, 'Universal - ' + base + '.tif')
                        fig = self._plot_fig  # Matplotlib Figure 寮曠敤锛堢敤浜庡鍑?鍒锋柊锛?                        from io import BytesIO
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
                                if self._plot_canvas is not None:  # Matplotlib 鐢诲竷锛團igureCanvasTkAgg锛夊紩鐢?                                    try:
                                        self._plot_canvas.draw_idle()  # Matplotlib 鐢诲竷锛團igureCanvasTkAgg锛夊紩鐢?                                    except Exception:
                                        pass
                            except Exception:
                                pass
                        img = Image.open(buf)
                        # TIFF 鍏冧俊鎭細浣滆€?鎷嶆憚鏃ユ湡/ppi
                        tiffinfo = TiffImagePlugin.ImageFileDirectory_v2()
                        tiffinfo[315] = "TMAmax"  # Artist/浣滆€?                        dt_str = datetime.datetime.now().astimezone().strftime("%Y:%m:%d %H:%M:%S")
                        tiffinfo[306] = dt_str  # DateTime
                        tiffinfo[282] = TiffImagePlugin.IFDRational(300, 1)  # XResolution
                        tiffinfo[283] = TiffImagePlugin.IFDRational(300, 1)  # YResolution
                        tiffinfo[296] = 2         # ResolutionUnit: inch
                        img.save(
                            tif_path,
                            compression='tiff_adobe_deflate',
                            tiffinfo=tiffinfo,
                            dpi=(300, 300),
                        )
                        self.logger.info(f'宸茬敓鎴愪豢鐢烼IFF鍥? {tif_path}')
                        #messagebox.showinfo('瀹屾垚', f'宸茬敓鎴愪豢鐢烼IFF鍥撅細\n{tif_path}')
                    except Exception as ee:
                        self.logger.exception('鐢熸垚浠跨敓TIFF澶辫触')
                        messagebox.showerror('閿欒', f'鐢熸垚浠跨敓TIFF澶辫触锛歕n{ee}')

                ttk.Button(toolbar, text='鐢熸垚TIFF鍥?.tif)', command=_export_tiff).pack(side='left')
                ttk.Button(toolbar, text='浠跨敓杈撳嚭', command=_export_tiff_universal).pack(side='left', padx=(8, 0))

                # 浠呯敤浜庣粯鍥惧娉ㄧ殑 mg锛堜笉浼氫慨鏀逛富鐣岄潰 mg锛?                ttk.Label(toolbar, text='mg(鏍囨敞):').pack(side='left', padx=(16, 4))
                mg_entry = ttk.Entry(toolbar, textvariable=self._plot_mg_var, width=8)  # 缁樺浘绐楀彛 mg(鏍囨敞) 杈撳叆妗嗗彉閲忥紙浠呭奖鍝嶅浘涓枃瀛楋級
                mg_entry.pack(side='left')

                # 绗簩琛岋細鍑哄浘璺緞璁剧疆
                pathbar = ttk.Frame(win)
                pathbar.pack(fill="x", padx=6, pady=(0, 6))

                # 璁板綍涓婁竴娆″凡鍐欏叆鏃ュ織鐨勫嚭鍥捐矾寰勶紝閬垮厤鐒︾偣浜嬩欢瀵艰嚧閲嶅鍒峰睆
                _last_export_path_logged = {"v": (self.export_newpath_var.get() or "").strip()}

                # 褰撳墠瀹為檯杈撳嚭鐩綍锛堣€冭檻鈥滃惎鐢ㄦ柊璺緞鈥濆拰鐩綍鏄惁瀛樺湪锛?                def _current_output_dir() -> str:
                    """杩斿洖褰撳墠瀹為檯浼氳緭鍑哄埌鐨勭洰褰曪紙鑰冭檻鈥滃惎鐢ㄦ柊璺緞鈥濆拰鐩綍鏄惁瀛樺湪锛夈€?""
                    in_path_now = (self.input_path.get() or "").strip()
                    base_dir = normalize_path_separators(os.path.dirname(in_path_now)) if in_path_now else normalize_path_separators(os.getcwd())
                    if bool(self.export_use_newpath_var.get()):
                        cand = (self.export_newpath_var.get() or "").strip()
                        if cand and os.path.isdir(cand):
                            return cand
                    return base_dir

                def _log_current_output_dir(unchanged: bool = False):
                    """鍦ㄦ棩蹇楁涓緭鍑衡€滃綋鍓嶅疄闄呭嚭鍥剧洰褰曗€濄€?                    
                    鍙傛暟锛?                        unchanged: True 鏃朵細鍦ㄦ棩蹇椾腑杩藉姞鈥滐紙鏈洿鏀癸級鈥濓紝鐢ㄤ簬鎻愮ず鐢ㄦ埛褰撳墠浠嶄娇鐢ㄩ粯璁ょ洰褰曘€?                    """
                    
                    out_dir = _current_output_dir()
                    msg = f"褰撳墠杈撳嚭璺緞: {out_dir}"
                    if unchanged:
                        msg += "锛堟湭鏇存敼锛?
                    self.logger.info(msg)

                def _log_export_path_if_changed(new_val: str):
                    """褰撳嚭鍥捐矾寰勫彂鐢熷彉鍖栨椂鎵嶅啓鏃ュ織锛岄伩鍏?FocusOut/Return 绛変簨浠跺鑷村埛灞忋€?""
                    
                    p = (new_val or "").strip()
                    if p == _last_export_path_logged.get("v", ""):
                        return
                    _last_export_path_logged["v"] = p
                    if bool(self.export_use_newpath_var.get()):
                        _log_current_output_dir(unchanged=False)
                    else:
                        _log_current_output_dir(unchanged=True)

                def _on_toggle_newpath():
                    """鍒囨崲鈥滃惎鐢ㄦ柊璺緞鈥濆閫夋鍚庣殑鍥炶皟锛氭洿鏂版棩蹇楀苟鍒锋柊褰撳墠杈撳嚭鐩綍鎻愮ず銆?""
                    
                    self.logger.info(
                        f"鍚敤鏂拌矾寰? {'寮€鍚? if self.export_use_newpath_var.get() else '鍏抽棴'}"
                    )
                    _log_current_output_dir(unchanged=False)

                ttk.Checkbutton(
                    pathbar,
                    text="鍚敤鏂拌矾寰?,
                    variable=self.export_use_newpath_var,
                    command=_on_toggle_newpath,
                ).pack(side="left")

                base_paths = [
                    r"\\192.168.0.105\TMAresult\LS",
                    r"\\192.168.0.105\TMAresult\涓夋槑鏍峰搧",
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
                    """鍒锋柊鍑哄浘璺緞涓嬫媺妗嗙殑鍙€夐」銆?                    
                    鏉ユ簮锛?                        - 鍥哄畾鐨?base_paths
                        - 妗岄潰璺緞
                        - 鐢ㄦ埛鏈€杩戞墜鍔ㄨ緭鍏ョ殑璺緞锛堟渶澶氫繚鐣?3 涓級
                    """
                    
                    values: List[str] = []
                    for p in base_paths + [desktop_path] + getattr(self, '_recent_export_paths', []):
                        if p and p not in values:
                            values.append(p)
                    export_path_combo['values'] = values

                def _remember_export_path(p: str):
                    """鎶婄敤鎴疯緭鍏ョ殑鍑哄浘璺緞鍔犲叆鈥滄渶杩戣矾寰勨€濆垪琛紙LRU锛屾渶澶?3 涓級锛屽苟鍒锋柊涓嬫媺妗嗛€夐」銆?""
                    
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
                    """寮瑰嚭鏂囦欢澶归€夋嫨妗嗭紝璁╃敤鎴烽€夋嫨鍑哄浘鐩綍锛屽苟鏇存柊涓嬫媺妗嗕笌鏃ュ織銆?""
                    
                    try:
                        d = filedialog.askdirectory(title='閫夋嫨鍑哄浘鏂囦欢澶?)
                    except Exception:
                        d = ''
                    if d:
                        self.export_newpath_var.set(d)
                        _remember_export_path(d)
                        _last_export_path_logged["v"] = d
                        _log_current_output_dir(unchanged=(not bool(self.export_use_newpath_var.get())))

                ttk.Button(pathbar, text='璋冩暣鍑哄浘璺緞', command=_choose_export_dir).pack(side='left', padx=(8, 0))

                # ---- 缁樺浘 ----
                fig = Figure(figsize=(12.8, 7.2), dpi=100)
                ax = fig.add_subplot(111)
                self._plot_fig = fig  # Matplotlib Figure 寮曠敤锛堢敤浜庡鍑?鍒锋柊锛?
                # 鏇茬嚎锛堢嚎瀹介€備腑锛? matplotlib linewidth 鍗曚綅涓?points
                ax.plot(xs, ys, color="black", linewidth=1.5)

                # x 杞磋寖鍥?0~300锛堝甫鏍囧昂锛氬ぇ鍒诲害50锛屽皬鍒诲害10锛?                x_left = 0.0
                x_right = 300.0
                ax.set_xlim(x_left, x_right)
                ax.xaxis.set_major_locator(MultipleLocator(50))
                ax.xaxis.set_minor_locator(MultipleLocator(10))
                ax.xaxis.set_minor_formatter(NullFormatter())
                ax.set_xlabel("娓╁害(掳C)", fontsize=12)
                ax.tick_params(axis='x', which='major', length=6)
                ax.tick_params(axis='x', which='minor', length=3)

                # y 杞达細500 鐨勫€嶆暟锛堝ぇ鍒诲害500锛屽皬鍒诲害100锛?                ax.set_ylim(y0_plot, y1_plot)

                # 鑳屾櫙缃戞牸锛歺 姣忛殧 10銆亂 姣忛殧 100 鐢荤粏铏氱嚎锛堜綔涓鸿儗鏅級
                for gx in range(0, 301, 10):
                    ax.axvline(gx, linestyle="--", linewidth=0.4, color="#999999", alpha=0.35, zorder=0)
                y_grid_start = int(math.floor(y0_plot / 100.0)) * 100
                y_grid_end = int(math.ceil(y1_plot / 100.0)) * 100
                for gy in range(y_grid_start, y_grid_end + 1, 100):
                    ax.axhline(gy, linestyle="--", linewidth=0.4, color="#999999", alpha=0.35, zorder=0)
                ax.yaxis.set_major_locator(FixedLocator(y_ticks_major))

                ax.yaxis.set_minor_locator(FixedLocator(y_ticks_minor))

                ax.yaxis.set_minor_formatter(NullFormatter())
                ax.set_ylabel("灏哄鍙樺寲(渭m)", fontsize=12)
                ax.tick_params(axis='y', which='major', length=6)
                ax.tick_params(axis='y', which='minor', length=3)


                # 鑳屾櫙锛?00脳500 姝ｆ柟褰紙(0,0)~(500,500)锛夛紝鏈€缁嗚櫄绾?
                try:

                    ax.plot([0, 500, 500, 0, 0], [0, 0, 500, 500, 0], linestyle=(0, (1, 3)), linewidth=0.5, color='0.8', zorder=0)

                except Exception:

                    pass


                # 鏍囬/鍓爣棰?                fig.suptitle("TMA", fontsize=16, fontweight="bold")

                def _get_plot_mg_text() -> str:
                    """璇诲彇缁樺浘绐楀彛涓殑 mg(鏍囨敞) 瀛楃涓诧紝骞跺敖閲忎繚鎸佺敤鎴疯緭鍏ユ牸寮忋€?                    
                    璇存槑锛?                        - 璇?mg 浠呭奖鍝嶅浘涓€滄柟娉曟棩蹇椻€濈殑鏂囧瓧锛屼笉浼氫慨鏀逛富鐣岄潰 mg銆?                    """
                    
                    s = (self._plot_mg_var.get() or '').strip()  # 缁樺浘绐楀彛 mg(鏍囨敞) 杈撳叆妗嗗彉閲忥紙浠呭奖鍝嶅浘涓枃瀛楋級
                    if not s:
                        return 'x'
                    # 淇濈暀鐢ㄦ埛杈撳叆鐨勫皬鏁颁綅锛堜緥濡?0.50 涓嶈鍙樻垚 0.5锛?                    try:
                        float(s)
                    except Exception:
                        return s
                    # 鑻ョ敤鎴疯緭鍏ヤ负鏁存暟褰㈠紡锛堝 1锛夛紝鍒欑粺涓€琛ヤ袱浣嶅皬鏁?                    if ('.' not in s) and ('e' not in s.lower()):
                        return f"{float(s):.2f}"
                    return s


                def _build_method_note() -> str:
                    """鏋勫缓缁樺浘宸︿笂瑙掔殑鈥滄柟娉曟棩蹇椻€濆娉ㄦ枃鏈紙鍖呭惈 mg锛夈€?""
                    
                    mg_s = _get_plot_mg_text()
                    a = "鏂规硶鏃ュ織锛?0掳C骞宠　锛屾柦鍔?0.06 N锛沑n"
                    b = " " * 17 + "20掳C/min鍔犵儹鑷?250掳C锛沑n"
                    c = f"绉板彇璐ㄩ噺锛歿mg_s}mg銆?
                    d = a + b + c
                    return d

                # 鍓爣棰橀殣钘忥紝鏂规硶鏃ュ織浣滀负缁樺浘澶囨敞鏄剧ず

                # 鏍囨敞淇℃伅锛圛NFO锛?                self.logger.info("寮€濮嬬粯鍥?)
                self.logger.info(f"{src_tag}鏁版嵁: 鐐规暟={len(xs)}")

                # T1/T2 鏍囨敞锛氱敤鈥滈粦鑹插崄瀛楃煭绾库€濅笌鏇茬嚎鐩镐氦琛ㄧず鐐?                y_range = (y1_plot - y0_plot)
                tick_half_y = max(10.0, y_range * 0.02)   # 绔栧悜鍗婇暱锛堟暟鎹潗鏍囷級
                tick_half_x = 2.0                         # 妯悜鍗婇暱锛堚剝锛?                tick_lw = 1.2

                def _draw_cross(xc: float, yc: float):
                    """鍦?(x,y) 鏁版嵁鐐瑰缁樺埗涓€涓皬鍗佸瓧锛岀敤浜庤瑙変笂鏍囪 T1/T2 鐐广€?""
                    
                    x_left = max(0.0, xc - tick_half_x)
                    x_right = min(300.0, xc + tick_half_x)
                    ax.vlines(xc, yc - tick_half_y, yc + tick_half_y, colors="black", linewidth=tick_lw)
                    ax.hlines(yc, x_left, x_right, colors="black", linewidth=tick_lw)

                if x1_pt is not None and y1_pt is not None:
                    _draw_cross(x1_pt, y1_pt)
                    ax.annotate(
                        f"{x1_pt:.2f}鈩?, (x1_pt, y1_pt),
                        xytext=(0, -10), textcoords="offset points",
                        ha="center", va="top", fontsize=12, color="black"
                    )

                if x2_pt is not None and y2_pt is not None:
                    _draw_cross(x2_pt, y2_pt)
                    ax.annotate(
                        f"{x2_pt:.2f}鈩?, (x2_pt, y2_pt),
                        xytext=(0, 10), textcoords="offset points",
                        ha="center", va="bottom", fontsize=12, color="black"
                    )

                # 楂樺害宸細T1 鐐瑰悜鍙冲欢鍑哄钩琛岀嚎锛堝埌 T2 鐨?x 浣嶇疆锛夛紝绠ご鎸囧悜 T1 寤堕暱绾夸笌 T2 鐐?                if (x1_pt is not None and y1_pt is not None and x2_pt is not None and y2_pt is not None):
                    # 浠呭欢鍑?T1 鐨勬按骞崇嚎锛氫粠 T1 鍒?T2 鐨?x
                    ax.plot([x1_pt, x2_pt], [y1_pt, y1_pt], color="black", lw=0.8)

                    # 鍙屽悜绠ご锛氬湪 T2 鐨?x 浣嶇疆锛屼粠 T1 姘村钩绾?y1) 鍒?T2 鐐?y2)
                    ax.annotate(
                        "",
                        xy=(x2_pt, y2_pt),
                        xytext=(x2_pt, y1_pt),
                        arrowprops=dict(arrowstyle="<->", color="black", linewidth=1.0, shrinkA=0, shrinkB=0),
                    )
                    # 鍙爣娉ㄢ€滃灏?渭m鈥濓紙閬垮厤涓庢洸绾块噸鍙狅細鍙?T2 鍙充晶涓€鐐癸紝骞舵妸鏂囧瓧鐨勫乏涓嬭鏀惧湪鏇茬嚎涔嬩笂锛?                    dh = abs(y2_pt - y1_pt)

                    def _interp_y(xq: float) -> float:
                        """鍦ㄧ粰瀹?x锛堟俯搴︼級澶勫鏇茬嚎鍋氫竴娆＄嚎鎬ф彃鍊硷紝杩斿洖瀵瑰簲 y銆?                        
                        鐢ㄩ€旓細
                            鏀剧疆鈥滈珮搴﹀樊 渭m鈥濇枃瀛楁爣娉ㄦ椂锛岄渶瑕佷及璁¤浣嶇疆鏇茬嚎鐨?y 鍊硷紝
                            浠ラ伩鍏嶆枃瀛楃洊浣忔洸绾裤€?                        """
                        
                        pts = sorted(zip(xs, ys), key=lambda t: t[0])
                        xs_s = [p[0] for p in pts]
                        ys_s = [p[1] for p in pts]
                        if xq <= xs_s[0]:return float(ys_s[0])
                        if xq >= xs_s[-1]:return float(ys_s[-1])
                        # 绾挎€ф彃鍊?                        import bisect
                        j = bisect.bisect_left(xs_s, xq)
                        xL, yL = xs_s[j - 1], ys_s[j - 1]
                        xR, yR = xs_s[j], ys_s[j]
                        if xR == xL:return float(yL)
                        t = (xq - xL) / (xR - xL)
                        return float(yL + (yR - yL) * t)

                    x_text = min(300.0, x2_pt + 15.0)
                    y_curve = _interp_y(x_text)
                    margin = max(15.0, (y1_plot - y0_plot) * 0.03)
                    y_text = y_curve + margin
                    y_text = min(y_text, y1_plot - margin * 0.2) # 闃叉椤跺埌涓婅竟鐣?
                    ax.text(
                        x_text, y_text,
                        f"{format_height_um(dh)} 渭m",
                        fontsize=12, ha="left", va="bottom", color="black"
                    )
                canvas = FigureCanvasTkAgg(fig, master=win)
                # 缁樺浘瀹屾垚鍚庢坊鍔犫€滄柟娉曟棩蹇椻€濆娉細鏀剧疆鍦ㄥ乏涓婅锛屼笖灏介噺閬垮厤涓庢洸绾块噸鍙?                x_left_final = x_left
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

                # 鑻ュ悜宸︽墿灞曚簡 x 杞达紝琛ラ綈璐熷尯闂寸殑鑳屾櫙铏氱嚎锛堟瘡 10掳C 涓€鏉★級
                if x_left_final < 0:
                    gx_start = int(math.floor(x_left_final / 10.0)) * 10
                    for gx in range(gx_start, 0, 10):
                        ax.axvline(gx, linestyle=(0, (2, 2)), linewidth=0.5, color='0.8', zorder=0)

                # 鍙充笅瑙掔増鏈彿
                fig.text(0.99, 0.01, VERSION, ha='right', va='bottom', fontsize=10)
                
                # 缂撳瓨缁樺浘瀵硅薄锛堢敤浜?mg(鏍囨敞) 淇敼鍚庡埛鏂板娉級
                self._plot_method_artist = method_artist  # 缁樺浘宸︿笂瑙掆€滄柟娉曟棩蹇椻€濇枃鏈璞★紙鐢ㄤ簬鍔ㄦ€佸埛鏂?mg锛?                self._plot_note_x_left = x_left_final  # 涓洪伩鍏嶅娉ㄩ伄鎸℃洸绾匡紝宸︿笂瑙掑娉ㄤ細鍚戝乏鎸細璇ュ彉閲忚褰?x 杞村乏杈圭晫
                self._plot_ax = ax  # 缁樺浘鍧愭爣杞?Axes 寮曠敤锛堢敤浜庡埛鏂版爣娉級

                def _refresh_method_note(_evt=None):
                    """鍒锋柊缁樺浘澶囨敞锛堟柟娉曟棩蹇椾腑鐨?mg锛夛紝骞跺敖閲忛伩鍏嶄笌鏇茬嚎/鐐归噸鍙犮€?""
                    try:
                        if self._plot_ax is None or self._plot_method_artist is None:  # 缁樺浘鍧愭爣杞?Axes 寮曠敤锛堢敤浜庡埛鏂版爣娉級
                            return
                        self._plot_method_artist.set_text(_build_method_note())  # 缁樺浘宸︿笂瑙掆€滄柟娉曟棩蹇椻€濇枃鏈璞★紙鐢ㄤ簬鍔ㄦ€佸埛鏂?mg锛?
                        # 濡傛枃瀛椾笌鐐瑰尯鍩熼噸鍙狅紝鍒欑户缁悜宸︽墿灞?x 杞?                        xlf = self._plot_note_x_left if self._plot_note_x_left is not None else x_left_final  # 涓洪伩鍏嶅娉ㄩ伄鎸℃洸绾匡紝宸︿笂瑙掑娉ㄤ細鍚戝乏鎸細璇ュ彉閲忚褰?x 杞村乏杈圭晫
                        for _ in range(30):
                            ax.set_xlim(xlf, x_right)
                            self._plot_method_artist.set_position((xlf + 10, y1_plot - 100))  # 缁樺浘宸︿笂瑙掆€滄柟娉曟棩蹇椻€濇枃鏈璞★紙鐢ㄤ簬鍔ㄦ€佸埛鏂?mg锛?                            fig.canvas.draw()
                            bbox = self._plot_method_artist.get_window_extent(renderer=fig.canvas.get_renderer())  # 缁樺浘宸︿笂瑙掆€滄柟娉曟棩蹇椻€濇枃鏈璞★紙鐢ㄤ簬鍔ㄦ€佸埛鏂?mg锛?                            overlap = False
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
                        self._plot_note_x_left = xlf  # 涓洪伩鍏嶅娉ㄩ伄鎸℃洸绾匡紝宸︿笂瑙掑娉ㄤ細鍚戝乏鎸細璇ュ彉閲忚褰?x 杞村乏杈圭晫

                        # 鑻ュ悜宸︽墿灞曞埌璐熸暟鍖哄煙锛岃ˉ鐢昏儗鏅櫄绾?                        if xlf < 0:
                            start_gx = int(math.floor(xlf / 10.0) * 10)
                            for gx in range(start_gx, 0, 10):
                                ax.axvline(gx, linestyle='--', linewidth=0.4, alpha=0.18, zorder=0)

                        fig.canvas.draw_idle()
                    except Exception:
                        pass

                # mg 杈撳叆妗嗭細鍥炶溅/澶辩劍鏃跺埛鏂板娉?                try:
                    mg_entry.bind('<Return>', _refresh_method_note)
                    mg_entry.bind('<FocusOut>', _refresh_method_note)
                except Exception:
                    pass

                # 鏈€缁堝啀 draw 涓€娆★紝纭繚甯冨眬鍒锋柊
                canvas.draw()
                canvas.get_tk_widget().pack(fill="both", expand=True)
                self._plot_canvas = canvas  # Matplotlib 鐢诲竷锛團igureCanvasTkAgg锛夊紩鐢?            except Exception as e:
                self.logger.exception("缁樺浘澶辫触")
                messagebox.showerror("閿欒", f"缁樺浘澶辫触锛歕n{e}")


    def _format_mg_for_note(self, mg_s: str) -> str:
        """鐢ㄤ簬缁樺浘澶囨敞鐨?mg 瀛楃涓叉牸寮忥細
        - 鑻ュ彲瑙ｆ瀽涓烘暟鍊硷細灏介噺淇濈暀涓や綅灏忔暟锛堜緥濡?0.50锛?        - 鍚﹀垯锛氬師鏍疯繑鍥烇紙鍘婚灏剧┖鐧斤級
        """
        s = (mg_s or "").strip()
        if not s:
            return "0.50"

        # 鎸囨暟褰㈠紡锛氬敖閲忔寜鏁板€兼牸寮忓寲
        if "e" in s.lower():
            try:
                return f"{float(s):.2f}"
            except Exception:
                return s

        # 鏅€氬皬鏁?        if "." in s:
            frac = s.split(".", 1)[1]
            # 鍙湁 1 浣嶅皬鏁帮細琛ヨ冻鍒?2 浣嶏紙0.5 -> 0.50锛?            if len(frac) == 1:
                try:
                    return f"{float(s):.2f}"
                except Exception:
                    return s
            # >=2 浣嶅皬鏁帮細灏婇噸鐢ㄦ埛杈撳叆锛堜笉寮哄埗鍥涜垗浜斿叆锛?            return s

        # 鏁存暟锛氳ˉ瓒冲埌涓や綅
        try:
            return f"{float(s):.2f}"
        except Exception:
            return s

def main():
    """绋嬪簭鍏ュ彛锛氬垱寤?Tk 鏍圭獥鍙ｅ苟鍚姩涓诲惊鐜€?""
    
    root = tk.Tk()
    App(root)
    place_window_top_right(root, 600, 450)
    root.mainloop()


if __name__ == "__main__":
    main()

