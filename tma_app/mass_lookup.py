"""Read-only sample mass (M) lookup from configured CSV/XLSX/XLS sources.

The sheet is opened strictly read-only (``read_only=True, data_only=True``) so the
original file is never modified or locked for other writers. Headers identify sample and mass columns; without recognized headers the layout
is B = batch/sample, C = mass. The existing batch normalization below is retained.

Batch-number recognition is intentionally internal (a pure function) and is never
surfaced in the UI. The weighing sheet uses production writing ``型号-批次号`` with
three batch-number families:

* A 类 (7 位): ``H906-2510001`` = 型号 + 年份月份(4 位) + 3 位序号；
* B 类 (8 位，L301N/L302N/H708/JL708P): ``L301N-26081209`` = 型号 + 年月日(6 位) + 2 位序号；
* 其它 (10 位): ``H906-1126081207``。

此外还有日期式批次 ``YYYYMMDD-R`` / ``-R#`` / 补零 ``YYYYMMDD0R``，三者等价。

The lookup never raises for a missing/unreachable sheet or a missing match; it
returns ``None`` so the caller can fall back gracefully. The remote path can be
overridden with the ``TMA_MASS_XLSX`` environment variable; setting it to an
empty string disables the lookup entirely.
"""
from __future__ import annotations

import math
import os
import re
from pathlib import Path
import csv
import codecs
from io import BytesIO, TextIOWrapper
from dataclasses import dataclass
import threading
from collections import OrderedDict
from weakref import WeakValueDictionary
from contextlib import closing
from itertools import chain, islice

MASS_XLSX = os.environ.get("TMA_MASS_XLSX", "//192.168.0.105/TMA称量数据.xlsx")

_unavailable = False
_table_cache = OrderedDict()
_table_cache_guard = threading.RLock()
_table_locks = WeakValueDictionary()
_table_locks_guard = threading.Lock()


@dataclass(frozen=True)
class MassMatch:
    value: float | None = None
    source: str = ""
    unit: str = ""
    message: str = ""
    unavailable: bool = False


def _normalize(text: object) -> str:
    if isinstance(text, float) and text.is_integer(): text = int(text)
    return "".join(str(text).split()).casefold().lstrip("\ufeff")


def _batch_candidates(filename: str | Path) -> list[str]:
    """Derive the identifiers that may name a batch in column B."""
    name = Path(filename).name
    stem = Path(filename).stem
    candidates = [name, stem]
    # ".001/.002" are volume numbers; a trailing "#N" or "#" often marks a run.
    for value in list(candidates):
        if "#" in value:
            base = value.rsplit("#", 1)[0].rstrip()
            if base and base not in candidates:
                candidates.append(base)
    return [c for c in candidates if c.strip()]


_BATCH_RUN_RE = re.compile(r"^(\d{8})-(\d{1,3})$")
_BATCH_ZEROPAD_RE = re.compile(r"^(\d{8})(\d{2,3})$")


def _valid_date(ymd: str) -> bool:
    """``ymd`` is ``YYYYMMDD``; require a plausible full (4-digit) year so that
    10 位批次（如 ``1126081207``）不会被误拆成日期＋运行号。"""
    if not re.fullmatch(r"\d{8}", ymd):
        return False
    year, month, day = int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8])
    return 2000 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31


def _canonical_batch(text: object) -> str | None:
    """Canonicalize ``YYYYMMDD-R`` / ``-R#`` / ``YYYYMMDD0R`` to one key.

    ``20251225-7#``、``20251225-7`` 和 ``2025122507`` 是同一个批次；统一映射为
    ``20251225-7``（运行号去掉前导零）。其它格式（含 A/B/10 位批次）返回 ``None``，
    交由原样/拆型号匹配，避免把 10 位批次误拆成日期。
    """
    value = str(text).strip().casefold()
    if value.endswith("#"):
        value = value[:-1].rstrip()
    match = _BATCH_RUN_RE.fullmatch(value)
    if match and _valid_date(match.group(1)):
        return f"{match.group(1)}-{int(match.group(2))}"
    match = _BATCH_ZEROPAD_RE.fullmatch(value)
    if match and _valid_date(match.group(1)):
        return f"{match.group(1)}-{int(match.group(2))}"
    if re.fullmatch(r"\d{8}", value) and _valid_date(value):
        return value
    return None


def _batch_keys(text: object) -> set[str]:
    """All normalized identifiers one batch string can be written as.

    Covers ``型号-批次号``（同时保留去型号的纯批次号，便于一侧缺型号时也能对上）、
    尾部 ``#``、以及日期式等价的规范形式。纯内部使用，不进 UI。
    """
    value = str(text).strip()
    if not value:
        return set()
    norm = _normalize(value)
    keys = {norm}
    if norm.endswith("#"):
        keys.add(norm[:-1])
    canon = _canonical_batch(norm)
    if canon is not None:
        keys.add(canon)
    if "-" in norm:
        prefix, _, rest = norm.partition("-")
        rest = rest.strip()
        # 型号前缀是非数字（H906 / L301N / W456…）时才拆出纯批次号；
        # 日期式（20251225-7）的前缀是数字，保持整体匹配。
        if prefix and not prefix.isdigit() and len(rest) >= 6:
            keys.add(rest)
            if rest.endswith("#"):
                keys.add(rest[:-1])
            rest_canon = _canonical_batch(rest)
            if rest_canon is not None:
                keys.add(rest_canon)
    return {key for key in keys if key}


def _to_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value).strip().replace(",", "")
    match = re.fullmatch(r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(?:mg|g|毫克|克)?", text, re.I)
    return float(match.group(1)) if match else None




def configured_source():
    from .path_settings import mass_source
    return mass_source()


def clear_cache(*, disk=True):
    global _unavailable
    with _table_cache_guard: _table_cache.clear()
    _unavailable = False
    from .mass_cache import clear
    clear(disk=disk)


def _rows(path):
    """Read every worksheet without changing or keeping the source open."""
    suffix = path.suffix.lower()
    if suffix in ('.csv', '.cvs'):
        raw = path.read_bytes()
        encoding = 'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
        # Validate incrementally so a late non-UTF-8 byte still selects the
        # same GB18030 fallback, without keeping a second full decoded copy.
        decoder = codecs.getincrementaldecoder(encoding)()
        try:
            view = memoryview(raw)
            for offset in range(0, len(raw), 65536):
                decoder.decode(view[offset:offset+65536], final=False)
            decoder.decode(b'', final=True)
        except UnicodeDecodeError:
            encoding = 'gb18030'
        with TextIOWrapper(BytesIO(raw), encoding=encoding, newline='\n') as stream:
            sample = stream.read(8192)
            try: dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
            except csv.Error: dialect = csv.excel
            stream.seek(0)
            yield '', csv.reader(stream, dialect)
    elif suffix == '.xlsx':
        from openpyxl import load_workbook
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            for sheet in book.worksheets: yield sheet.title, sheet.iter_rows(values_only=True)
        finally: book.close()
    elif suffix == '.xls':
        import xlrd
        book = xlrd.open_workbook(str(path), on_demand=True)
        try:
            for index in range(book.nsheets):
                sheet = book.sheet_by_index(index)
                yield sheet.name, (sheet.row_values(i) for i in range(sheet.nrows))
        finally: book.release_resources()
    else: raise ValueError('m 数据源仅支持 CSV、XLSX、XLS 文件或包含这些文件的文件夹')


def _header(text):
    return re.sub(r'[\s_()（）\[\]：:/\\-]', '', str(text)).casefold().lstrip('\ufeff')


def _records(path, *, force=False):
    # Curve import and the batch table can request the same workbook together.
    # Read each revision once; unrelated sources never wait on this file's I/O.
    key = os.path.normcase(str(path.absolute()))
    with _table_locks_guard:
        lock = _table_locks.setdefault(key, threading.Lock())
    with lock:
        if force:
            with _table_cache_guard:
                for cached in list(_table_cache):
                    if os.path.normcase(cached[0]) == key: _table_cache.pop(cached, None)
        return _read_records(path)


def _read_records(path):
    stamp = path.stat()
    cache_key = (str(path.resolve()), stamp.st_mtime_ns, stamp.st_size)
    with _table_cache_guard:
        cached = _table_cache.get(cache_key)
        if cached is not None:
            _table_cache.move_to_end(cache_key)
            return cached
    names = {'样品', '样品名', '样品名称', '样本名', '批次', '批次号', '批号', '编号', 'samplename', 'sample', 'batch', 'batchnumber', '批次编号'}
    masses = {'m', '重量', '质量', '称量重量', '样品重量', '样品质量', 'mass', 'weight'}
    records = []
    with closing(_rows(path)) as sheets:
        for sheet_name, rows in sheets:
            origin = cache_key[0] + (f' [{sheet_name}]' if sheet_name else '')
            name_col, mass_col, start, unit = 1, 2, 0, ''
            row_iterator = iter(rows)
            first_rows = list(islice(row_iterator, 20))
            for index, row in enumerate(first_rows):
                headers = [_header(v) for v in row]
                ni = next((i for i,h in enumerate(headers) if h in names), None)
                mi = next((i for i,h in enumerate(headers) if h in masses or any(h == base+u for base in masses for u in ('mg','g'))), None)
                if ni is not None and mi is not None:
                    name_col, mass_col, start = ni, mi, index+1
                    explicit_unit = re.search(r'[（(\[]\s*(mg|g)\s*[）)\]]', str(row[mi]), re.I)
                    unit = explicit_unit.group(1).lower() if explicit_unit else 'mg' if headers[mi].endswith('mg') else 'g' if headers[mi].endswith('g') else ''
                    break
            for row in chain(first_rows[start:], row_iterator):
                if len(row) <= max(name_col, mass_col) or row[name_col] is None: continue
                value = _to_number(row[mass_col])
                if value is None or not math.isfinite(value) or value <= 0: continue
                raw_unit = re.search(r'\b(mg|g)\s*$', str(row[mass_col]), re.I)
                record_unit = raw_unit.group(1).lower() if raw_unit else unit
                records.append((row[name_col], value, record_unit, origin))
    # Keep only the current revision of this file in memory.
    with _table_cache_guard:
        for key in list(_table_cache):
            if key[0] == cache_key[0]: _table_cache.pop(key, None)
        _table_cache[cache_key] = records
        while len(_table_cache) > 16: _table_cache.popitem(last=False)
    return records


def _load_source_records(source, *, force=False):
    from .cloud_storage import resolve_source
    path = resolve_source(source)
    files = sorted((p for p in path.iterdir() if p.is_file() and p.suffix.lower() in ('.csv','.cvs','.xlsx','.xls') and not p.name.startswith('~$')), key=lambda p:p.name.casefold()) if path.is_dir() else [path]
    if not files: raise ValueError('文件夹中未找到称量表')
    return [(_normalize(batch), value, unit, origin) for file in files
            for batch, value, unit, origin in _records(file, force=force)]


def lookup_record(sample, source=None, *, force=False):
    global _unavailable
    try:
        source = configured_source() if source is None else str(source).strip()
        if not source: return MassMatch(message='未配置 m 数据源')
        from .mass_cache import lookup
        result = lookup(sample, source, force=force)
        _unavailable = '暂不可用' in result.message
        return result
    except Exception as exc:
        _unavailable = True
        return MassMatch(source=str(source or ''), message=f'm 数据源未读取：{exc}', unavailable=True)


def lookup_mass(filename):
    """Compatibility wrapper returning the matched source value without unit conversion."""
    return lookup_record(filename).value


def default_note_text(sample):
    match = lookup_record(sample)
    # The requested note expresses m in mg; unlabelled weighing values use mg.
    mass = 0.50 if match.value is None else match.value * (1000 if match.unit == 'g' else 1)
    return format_note_text(mass)


def format_note_text(mass=0.50):
    return ("方法日志：30 ℃ 平衡，施加 0.06 N\n"
            "                    20 ℃/min加热至 250 ℃\n"
            f"称取质量：{mass:.2f} mg")


def note_text_for_curve(curve):
    """GUI prefill: use already imported metadata, never wait for SMB/Excel."""
    metadata = curve.dataset.metadata
    if metadata.get('LookupMassSample') == [curve.sample_name]:
        try:
            value = float(metadata['LookupMass'][0])
            unit = metadata.get('LookupMassUnit', ['mg'])[0]
            mass = value * (1000 if unit == 'g' else 1)
            if math.isfinite(mass) and mass > 0 and unit in ('', 'mg', 'g'):
                return format_note_text(mass)
        except (ValueError, TypeError, KeyError, IndexError): pass
    # Opening a note is an editing operation. The import worker continues its
    # existing mass lookup independently; do not issue another lookup here.
    return format_note_text()
