"""Local SQLite counters for explicitly invoked interface commands."""
from concurrent.futures import ThreadPoolExecutor
import logging
import sqlite3
from contextlib import closing


_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='tma-usage')
_LOG = logging.getLogger(__name__)


def database_path():
    from .path_settings import config_path
    return config_path().with_name('feature-usage.sqlite3')


def _connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path, timeout=2)


def _increment(path, feature, label):
    with closing(_connect(path)) as database, database:
        database.execute('''CREATE TABLE IF NOT EXISTS feature_usage (
            feature TEXT PRIMARY KEY, label TEXT NOT NULL, uses INTEGER NOT NULL)''')
        database.execute('''INSERT INTO feature_usage (feature, label, uses) VALUES (?, ?, 1)
            ON CONFLICT(feature) DO UPDATE SET label=excluded.label, uses=uses+1''', (feature, label))


def _report_write(future):
    try:
        future.result()
    except (sqlite3.Error, OSError):
        _LOG.warning('Unable to save local feature usage', exc_info=True)


def record(feature, label):
    _worker.submit(_increment, database_path(), feature, label).add_done_callback(_report_write)


def _read(path):
    if not path.exists():
        return []
    with closing(_connect(path)) as database:
        return database.execute('SELECT label, uses FROM feature_usage ORDER BY uses DESC, label').fetchall()


def read_usage(cancelled, path):
    if cancelled.is_set():
        return []
    return _worker.submit(_read, path).result()


def track(action, feature, label):
    action.triggered.connect(lambda checked=False: record(feature, label))
