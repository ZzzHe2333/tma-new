"""Shared, persistent weighing snapshots with deliberately infrequent I/O."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
from weakref import WeakValueDictionary

from .path_settings import config_path, _settings_data, _save_data

MISS_RECHECK_SECONDS = 300
FAILURE_RETRY_SECONDS = 60
_entries = OrderedDict()
_locks = WeakValueDictionary()
_guard = threading.RLock()
_clear_epoch = 0


def refresh_hours():
    config = _settings_data().get('mass_cache', {})
    value = config.get('refresh_hours', 24) if isinstance(config, dict) else 24
    return float(value) if type(value) in (int, float) and math.isfinite(value) and 1 <= value <= 720 else 24.


def save_refresh_hours(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 1 <= value <= 720:
        raise ValueError('m 缓存有效期须为 1–720 小时')
    data = _settings_data(); data['mass_cache'] = {'refresh_hours': float(value)}; _save_data(data)


def folder(): return config_path().parent / 'cache' / 'mass'


def identity(source):
    source = str(source).strip()
    value = source if source.startswith('cloud://') else os.path.normcase(os.path.abspath(source))
    return str(folder().absolute()), value


def disk_path(key): return Path(key[0]) / (hashlib.sha256(key[1].encode('utf-8')).hexdigest() + '.json')


@dataclass
class Snapshot:
    records: list
    loaded: float
    checked: float
    error: str = ''
    exact: dict = field(default_factory=dict)
    aliases: dict = field(default_factory=dict)

    def __post_init__(self):
        from .mass_lookup import _normalize, _batch_keys
        def add(index, key, position):
            previous = index.get(key)
            if previous is None:
                index[key] = position
            elif isinstance(previous, int):
                index[key] = [previous, position]
            else:
                previous.append(position)
        for position, record in enumerate(self.records):
            add(self.exact, _normalize(record[0]), position)
            for key in _batch_keys(record[0]): add(self.aliases, key, position)

    def find(self, sample):
        from .mass_lookup import _normalize, _batch_candidates, _batch_keys, MassMatch
        names = {_normalize(c) for c in _batch_candidates(str(sample))}
        def records_for(index, keys):
            for key in keys:
                value = index.get(key)
                if value is None: continue
                positions = (value,) if isinstance(value, int) else value
                for position in positions: yield self.records[position]
        found = list(records_for(self.exact, names))
        if not found:
            keys = set().union(*(_batch_keys(c) for c in names)) if names else set()
            found = list(records_for(self.aliases, keys))
        if not found: return None
        if len({(row[1], row[2]) for row in found}) != 1:
            return MassMatch(message=f'样品“{sample}”存在不同重量或单位，未自动选取')
        _, value, unit, origin = found[0]
        return MassMatch(value, origin, unit, '使用缓存（源暂不可用）' if self.error else '匹配成功（缓存）')


def _read_disk(key):
    try:
        path = disk_path(key)
        if path.stat().st_size > 32 * 1024 * 1024: return None
        value = json.loads(path.read_text(encoding='utf-8'))
        if value['version'] != 1 or value['source'] != key[1]: return None
        loaded = float(value['loaded'])
        if not math.isfinite(loaded) or not 0 < loaded <= time.time()+300: return None
        records = value['records']
        if not isinstance(records, list): return None
        for row in records:
            if (not isinstance(row, list) or len(row) != 4 or not isinstance(row[0], str)
                or type(row[1]) not in (int, float) or not math.isfinite(row[1]) or row[1] <= 0
                or not isinstance(row[2], str) or not isinstance(row[3], str)): return None
        return Snapshot(records, loaded, loaded)
    except (OSError, ValueError, KeyError, TypeError, OverflowError): return None


def _write_disk(key, entry):
    temporary = None
    try:
        path = disk_path(key); path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='mass-', suffix='.tmp', dir=path.parent)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump({'version': 1, 'source': key[1], 'loaded': entry.loaded, 'records': entry.records}, handle, ensure_ascii=False)
        os.replace(temporary, path)
    except OSError: pass  # Memory reuse still works when local storage is unavailable.
    finally:
        if temporary is not None:
            try: Path(temporary).unlink(missing_ok=True)
            except OSError: pass


def _get(key):
    with _guard:
        entry = _entries.get(key)
        if entry is not None:
            _entries.move_to_end(key)
            return entry
        lock = _locks.setdefault(key, threading.RLock())
    # Keep disk I/O outside the global lock. The per-source reentrant lock
    # prevents duplicate reads and also protects against a concurrent reload.
    with lock:
        with _guard:
            entry = _entries.get(key)
            if entry is not None:
                _entries.move_to_end(key)
                return entry
            epoch = _clear_epoch
        entry = _read_disk(key)
        with _guard:
            current = _entries.get(key)
            if current is not None:
                _entries.move_to_end(key)
                return current
            if epoch != _clear_epoch: return None
            if entry is not None:
                _entries[key] = entry
                while len(_entries) > 16: _entries.popitem(last=False)
            return entry


def peek(sample, source=None):
    """Look in local cache, loading its persistent snapshot if necessary."""
    from .mass_lookup import configured_source
    source = configured_source() if source is None else str(source).strip()
    entry = _get(identity(source)) if source else None
    return entry.find(sample) if entry is not None else None


def peek_memory(sample):
    """Best-effort GUI prefill: never wait for disk, a network, or cache locks."""
    from .path_settings import cached_mass_source
    source = cached_mass_source()
    if not source: return None
    key = identity(source)
    if not _guard.acquire(blocking=False): return None
    try:
        entry = _entries.get(key)
        if entry is not None: _entries.move_to_end(key)
    finally:
        _guard.release()
    return entry.find(sample) if entry is not None else None


def lookup(sample, source, *, force=False):
    from .mass_lookup import MassMatch, _load_source_records
    key = identity(source); now = time.time(); hours = refresh_hours()
    def reusable(entry):
        if entry is None: return False
        if entry.error and now-entry.checked < FAILURE_RETRY_SECONDS: return True
        # Unknown samples may be newly weighed: check at most once per five
        # minutes for the whole source, rather than once per missing sample.
        return now-entry.loaded < hours*3600 and (entry.find(sample) is not None or now-entry.checked < MISS_RECHECK_SECONDS)
    entry = _get(key)
    if force or not reusable(entry):
        with _guard: lock = _locks.setdefault(key, threading.RLock())
        with lock:
            entry = _get(key)
            if force or not reusable(entry):
                try:
                    records = _load_source_records(source, force=force)
                    entry = Snapshot(records, time.time(), time.time())
                    _write_disk(key, entry)
                except Exception:
                    entry = Snapshot(entry.records if entry is not None else [], entry.loaded if entry else 0,
                                     time.time(), 'm 数据源暂不可用，稍后重试或手动刷新')
                with _guard:
                    _entries[key] = entry
                    _entries.move_to_end(key)
                    while len(_entries) > 16: _entries.popitem(last=False)
    found = entry.find(sample)
    if found is not None:
        return found if found.source else MassMatch(source=source, message=found.message)
    return MassMatch(source=source, message=entry.error or f'未找到样品“{sample}”的有效重量（可手动刷新 m 缓存）',
                     unavailable=bool(entry.error))


def clear(*, disk=True):
    global _clear_epoch
    with _guard:
        _clear_epoch += 1
        _entries.clear()
    if disk:
        import re
        for path in folder().glob('*.json'):
            if re.fullmatch(r'[0-9a-f]{64}\.json', path.name):
                try: path.unlink()
                except OSError: pass
