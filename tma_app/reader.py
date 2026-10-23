"""Independent TA text and verified Q400 TMA binary readers.

The binary profile is grounded in the supplied Q400 files: a UTF-16LE
metadata header, ``0c 00 05``, five little-endian float32 channels, and a
``(-100, 20, 0, 0, 0)`` terminator. Other binary TA modules are deliberately
rejected. Extensions do not determine the format.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import unicodedata
from collections import OrderedDict
from copy import deepcopy
import threading

import numpy as np

_DATASET_CACHE = OrderedDict()
_DATASET_LOCK = threading.RLock()


class ParseError(ValueError):
    """The input does not contain a supported, identifiable TA dataset."""


@dataclass(frozen=True)
class Signal:
    name: str
    unit: str = ""

    @property
    def label(self) -> str:
        return f"{self.name} ({self.unit})" if self.unit else self.name


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().strip()


@dataclass
class Dataset:
    path: Path
    signals: list[Signal]
    values: np.ndarray
    metadata: dict[str, list[str]]
    warnings: list[str]
    sha256: str
    instance_id: str = ""
    opening_index: int = 1

    @property
    def document_key(self):
        return str(self.path) + (f"::open::{self.instance_id}" if self.instance_id else "")

    @property
    def display_name(self):
        return self.path.name + (f" [{self.opening_index}]" if self.opening_index > 1 else "")

    @property
    def name(self) -> str:
        return next((v.strip() for k, vs in self.metadata.items()
                     if k.casefold() == "sample" for v in vs if v.strip()), self.path.name)

    def index_for(self, keyword: str) -> int:
        query = _fold(keyword)
        if not query:
            raise ValueError("信号名称不能为空")
        for i, signal in enumerate(self.signals):
            if query in (_fold(signal.name), _fold(signal.label)):
                return i
        for i, signal in enumerate(self.signals):
            if query in _fold(signal.name):
                return i
        raise ValueError(f"未找到信号：{keyword}")

    @property
    def time_index(self) -> int | None:
        try:
            return self.index_for("Time")
        except ValueError:
            return None

    @property
    def temperature_index(self) -> int | None:
        try:
            return self.index_for("Temperature")
        except ValueError:
            return None


def _metadata(header: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for line in header.lstrip("\ufeff").splitlines():
        parts = line.strip().split(maxsplit=1)
        if parts:
            result.setdefault(parts[0], []).append(parts[1] if len(parts) > 1 else "")
    # Preserve exact text as well as parsed repeated fields and their order.
    result["_raw_header"] = [header.lstrip("\ufeff")]
    return result


def _field(metadata: dict[str, list[str]], name: str, default: str = "") -> str:
    return next((v[0] for k, v in metadata.items() if k.casefold() == name.casefold()), default)


def _signals(metadata: dict[str, list[str]], *, allow_missing_tail=False) -> list[Signal]:
    try:
        count = int(_field(metadata, "Nsig"))
    except ValueError as exc:
        raise ParseError("缺少或无效的 Nsig 信号数量") from exc
    if not 1 <= count <= 128:
        raise ParseError(f"不支持的信号数量：{count}")
    result = []
    for i in range(1, count + 1):
        label = _field(metadata, f"Sig{i}").strip()
        if not label:
            # Historical edited StartOfData exports can keep Nsig and all data
            # columns while omitting trailing Sig definitions. Preserve those
            # numeric columns with explicit unknown identities; do not infer a
            # gas channel or shift later columns into missing definitions.
            if allow_missing_tail and result and not any(_field(metadata, f'Sig{j}').strip() for j in range(i+1, count+1)):
                result.extend(Signal(f'Unnamed Signal {j}') for j in range(i, count+1))
                break
            raise ParseError(f"缺少 Sig{i} 信号定义")
        match = re.fullmatch(r"(.+?)\s*\((.*)\)\s*", label)
        result.append(Signal(match[1].strip(), match[2].strip()) if match else Signal(label))
    return result


def _text_encoding(buf: bytes) -> str:
    if buf.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    if len(buf) > 20 and buf[1:40:2].count(0) >= 15:
        return "utf-16le"
    return "utf-8-sig"


def _read_text(buf: bytes, encoding: str):
    try:
        text = buf.decode(encoding)
    except UnicodeDecodeError as exc:
        raise ParseError(f"文本编码无效（{encoding}）") from exc
    match = re.search(r"(?im)^\s*StartOfData\s*\r?$", text)
    if not match:
        raise ParseError("不是支持的 TA StartOfData 文本或 Q400 TMA 二进制文件")
    metadata = _metadata(text[:match.start()])
    signals = _signals(metadata, allow_missing_tail=True)
    rows = []
    warnings = []
    missing = [str(i) for i in range(1, len(signals)+1) if not _field(metadata, f'Sig{i}').strip()]
    if missing:
        metadata['_undefined_signals'] = missing
        warnings.append('文本头缺少 ' + '、'.join('Sig'+i for i in missing) + ' 定义；对应数据列完整保留为未命名信号，单位未知，未推断其含义。')
    for line_number, line in enumerate(text[match.end():].splitlines(),
                                       text[:match.end()].count("\n") + 1):
        line = line.strip()
        if not line:
            continue
        if line.casefold() == "endofdata":
            break
        fields = line.split()
        try:
            if len(fields) != len(signals):
                raise ValueError(f"需要 {len(signals)} 列，实际 {len(fields)} 列")
            row = [float(x.replace("D", "E").replace("d", "e")) for x in fields]
            if not np.isfinite(row).all():
                raise ValueError("包含 NaN 或无穷值")
        except ValueError as exc:
            if not rows:
                raise ParseError(f"第 {line_number} 行数据无效：{exc}") from exc
            warnings.append(f"数据不完整：第 {line_number} 行无效，已在该行前停止读取（{exc}）。")
            break
        rows.append(row)
    if not rows:
        raise ParseError("StartOfData 后没有有效数据")
    values = np.asarray(rows, dtype=np.float64)
    metadata["_format"] = ["TA StartOfData text"]
    time_index = next((i for i, s in enumerate(signals) if _fold(s.name) == "time"), None)
    if time_index is not None and np.any(np.diff(values[:, time_index]) < 0):
        warnings.append("时间信号存在倒退；已保留文件原始行顺序。")
    return signals, values, metadata, warnings


def _binary_header(buf: bytes) -> tuple[str, int]:
    """Consume complete metadata lines, without decoding binary bytes as text."""
    pos = 2 if buf.startswith(b"\xff\xfe") else 0
    last = pos
    while pos < min(len(buf), 1_048_576):
        end = buf.find(b"\r\x00\n\x00", pos)
        if end < 0 or (end - pos) % 2:
            break
        try:
            line = buf[pos:end].decode("utf-16le")
        except UnicodeDecodeError:
            break
        if not re.match(r"^[A-Za-z][A-Za-z0-9]*(?:\s|$)", line):
            break
        if any(ord(c) < 32 and c != "\t" for c in line):
            break
        last = end + 4
        pos = last
    if last < 20:
        raise ParseError("未找到有效 UTF-16LE TA 头部")
    return buf[:last].decode("utf-16le").lstrip("\ufeff"), last


def _valid_binary_rows(values: np.ndarray) -> np.ndarray:
    return (np.isfinite(values).all(axis=1)
            & (values[:, 0] >= 0) & (values[:, 0] <= 1e6)
            & (values[:, 1] >= -500) & (values[:, 1] <= 2000)
            & (np.abs(values[:, 2]) <= 1e7)
            & (np.abs(values[:, 3]) <= 1e6)
            & (np.abs(values[:, 4]) <= 1e6))


def _read_binary(buf: bytes):
    header, header_end = _binary_header(buf)
    metadata = _metadata(header)
    signals = _signals(metadata)
    if (_field(metadata, "Module").strip().casefold() != "tma standard"
            or len(signals) != 5
            or [_fold(s.name) for s in signals] != [
                "time", "temperature", "dimension change", "force", "sample purge flow"]):
        raise ParseError("当前二进制读取器仅支持已验证的 TMA Standard 五信号格式；请导出 StartOfData 文本")
    # The prefix is an observed format boundary, not an unvalidated search for
    # float32(0.004). A repeated time value in header/footer cannot select it.
    if buf[header_end:header_end + 3] != b"\x0c\x00\x05":
        raise ParseError("未知 TMA 二进制数据前导；拒绝猜测数据区位置")
    start = header_end + 3
    n_complete = (len(buf) - start) // 20
    if n_complete < 2:
        raise ParseError("TMA 二进制数据不足两条完整记录，无法验证布局")
    raw = np.frombuffer(buf, dtype="<f4", count=n_complete * 5, offset=start).reshape(-1, 5)
    valid = _valid_binary_rows(raw)
    check_count = min(8, n_complete)
    # A valid marker may occur after a very short synthetic/acquired dataset.
    markers = np.all(raw == np.asarray([-100, 20, 0, 0, 0], dtype=np.float32), axis=1)
    invalid = np.flatnonzero(~valid)
    end = int(invalid[0]) if len(invalid) else len(raw)
    check_count = min(check_count, end)
    if check_count < 2 or not valid[:check_count].all():
        raise ParseError("TMA 数据起点未通过多行数值验证")
    steps = np.diff(raw[:check_count, 0].astype(float))
    if not (steps >= 0).all() or not (steps > 1e-8).any():
        raise ParseError("TMA 数据起点未通过多行时间递增验证")
    backwards = np.flatnonzero(np.diff(raw[:end, 0].astype(float)) < -1e-3)
    warnings = []
    normal_end = end < len(raw) and markers[end]
    if len(backwards):
        end = int(backwards[0]) + 1
        normal_end = False
        warnings.append(f"数据不完整：第 {end + 1} 条记录时间倒退，已停止读取。")
    elif not normal_end:
        if end < len(raw):
            warnings.append(f"数据不完整：第 {end + 1} 条记录数值无效，已停止读取（字节偏移 {start + end * 20}）。")
        else:
            warnings.append("数据可能截断：未找到已验证的 TMA 结束标记。")
        remainder = (len(buf) - start) % 20
        if remainder:
            warnings.append(f"数据尾部有 {remainder} 字节不足一条完整记录。")
    if normal_end:
        # Method-event footer is deliberately retained opaquely. Its semantics
        # are not required to read the measured channels and are not inferred.
        metadata["_binary_footer_hex"] = [buf[start + end * 20 + 20:].hex()]
        if len(buf) - (start + end * 20 + 20) < 60:
            warnings.append("二进制方法尾部短于参考样本；测量结束标记完整。")
    metadata["_format"] = ["TA UTF-16LE TMA Standard float32 x 5"]
    metadata["_data_offset"] = [str(start)]
    metadata["_record_count"] = [str(end)]
    return signals, raw[:end].astype(np.float64), metadata, warnings


def read_dataset(path: str | Path) -> Dataset:
    """Read a supported file without altering, sorting, or resampling it.

    Partial recognized data returns the intact prefix with explicit warnings.
    Unrecognized binary layouts raise :class:`ParseError` instead of returning
    plausible-looking guessed data.
    """
    from .cloud_storage import resolve_source
    path = resolve_source(path)
    stat = path.stat()
    key = (str(path.absolute()), stat.st_mtime_ns, stat.st_size, stat.st_ino, stat.st_ctime_ns)
    with _DATASET_LOCK:
        cached = _DATASET_CACHE.get(key)
        if cached is not None:
            _DATASET_CACHE.move_to_end(key)
            return deepcopy(cached)
    buf = path.read_bytes()
    if not buf:
        raise ParseError("文件为空")
    encoding = _text_encoding(buf)
    marker = "StartOfData".encode("utf-16le" if encoding in ("utf-16", "utf-16le")
                                   and not buf.startswith(b"\xfe\xff") else
                                   "utf-16be" if encoding == "utf-16" else "utf-8")
    if marker in buf:
        signals, values, metadata, warnings = _read_text(buf, encoding)
    elif encoding in ("utf-16", "utf-16le") and not buf.startswith(b"\xfe\xff"):
        signals, values, metadata, warnings = _read_binary(buf)
    else:
        raise ParseError("未知文件格式；支持已验证的 Q400 TMA 二进制或含 Nsig/Sig/StartOfData 的 TA 文本")
    dataset = Dataset(path, signals, values, metadata, warnings, hashlib.sha256(buf).hexdigest())
    after = path.stat()
    if (after.st_mtime_ns, after.st_size, after.st_ino, after.st_ctime_ns) != key[1:]:
        raise ParseError('数据文件在读取期间发生变化，请重试')
    with _DATASET_LOCK:
        for old in list(_DATASET_CACHE):
            if old[0] == key[0]:_DATASET_CACHE.pop(old,None)
        # Cache independent originals only; opening twice still gets separate
        # arrays, metadata, analysis state and document identities.
        if dataset.values.nbytes <= 64*1024*1024:_DATASET_CACHE[key] = deepcopy(dataset)
        while len(_DATASET_CACHE)>8 or sum(c.values.nbytes for c in _DATASET_CACHE.values())>128*1024*1024:
            _DATASET_CACHE.popitem(last=False)
    return dataset
