"""Local per-process diagnostics, with a writable portable fallback."""
from __future__ import annotations
import atexit
from datetime import datetime
import faulthandler
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import traceback

_events = None
_native = None
_folder = None
_lock = threading.Lock()


def record_event(event, **fields):
    if _events is None: return
    try:
        with _lock:
            _events.write(json.dumps({'time': datetime.now().astimezone().isoformat(),
                                     'event': event, 'thread': threading.get_ident(), **fields}, ensure_ascii=False, default=str) + '\n')
            _events.flush()
    except (OSError, ValueError):
        pass


def install():
    global _events, _native, _folder
    if _events is not None: return _folder
    from . import __version__
    candidates = [Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ZzzHeTMA/logs']
    if getattr(sys, 'frozen', False): candidates.append(Path(sys.executable).parent / 'logs')
    candidates.append(Path(tempfile.gettempdir()) / 'ZzzHeTMA/logs')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + str(os.getpid())
    for folder in candidates:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            events = (folder / ('run-' + stamp + '.jsonl')).open('a', encoding='utf-8')
            native = (folder / ('native-' + stamp + '.log')).open('a', encoding='utf-8')
            _events, _native, _folder = events, native, folder
            break
        except OSError:
            if 'events' in locals(): events.close()
    if _events is None: return None
    # Rebind even if a parent/runtime already enabled faulthandler elsewhere.
    try: faulthandler.enable(file=_native, all_threads=True)
    except (OSError, RuntimeError, ValueError) as exc: record_event('native_logger.error', error=str(exc))
    record_event('startup', version=__version__, pid=os.getpid(), executable=sys.executable,
                 frozen=bool(getattr(sys, 'frozen', False)), log_folder=str(_folder))
    previous = sys.excepthook
    def exception(kind, value, tb):
        record_event('unhandled_exception', traceback=''.join(traceback.format_exception(kind, value, tb)))
        previous(kind, value, tb)
    sys.excepthook = exception
    atexit.register(lambda: record_event('process.exit'))
    return _folder
