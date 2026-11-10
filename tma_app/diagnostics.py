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
_install_lock = threading.Lock()


def record_event(event, **fields):
    sink = _events
    if sink is None: return
    try:
        # Serialize on the caller so mutable fields or Qt wrappers never cross
        # into the daemon. Only immutable UTF-8 bytes enter the bounded queue.
        data = json.dumps({'time': datetime.now().astimezone().isoformat(),
                           'event': event, 'thread': threading.get_ident(), **fields},
                          ensure_ascii=False, default=str).encode('utf-8') + b'\n'
        sink.submit(data)
    except Exception:
        pass


def flush_events(timeout=.2):
    sink = _events
    return True if sink is None else sink.flush(timeout)


def _shutdown_events():
    record_event('process.exit')
    sink = _events
    if sink is not None:
        sink.close(timeout=.25)


def install():
    with _install_lock:
        return _install()


def _install():
    global _events, _native, _folder
    if _events is not None: return _folder
    from . import __version__
    from .diagnostic_writer import EventWriter
    candidates = [Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ZzzHeTMA/logs']
    if getattr(sys, 'frozen', False): candidates.append(Path(sys.executable).parent / 'logs')
    candidates.append(Path(tempfile.gettempdir()) / 'ZzzHeTMA/logs')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '-' + str(os.getpid())
    for attempt, folder in enumerate(candidates):
        descriptor, native = None, None
        # Keep fallback basenames distinct even if cleanup of an earlier
        # empty file is denied. Collecting logs must never overwrite the
        # successful fallback with that earlier file.
        attempt_stamp = stamp + '-' + str(attempt)
        event_path = folder / ('run-' + attempt_stamp + '.jsonl')
        native_path = folder / ('native-' + attempt_stamp + '.log')
        created_event = created_native = False
        try:
            folder.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(event_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
            created_event = True
            native = native_path.open('x', encoding='utf-8')
            created_native = True
            # Raw writes avoid Python buffered-file locks during interpreter
            # shutdown if an OS write remains blocked beyond the close budget.
            events = EventWriter(lambda data, fd=descriptor, write=os.write: write(fd, data),
                                 lambda fd=descriptor, close=os.close: close(fd))
            _events, _native, _folder = events, native, folder
            break
        except (OSError, RuntimeError):
            if descriptor is not None:
                try: os.close(descriptor)
                except OSError: pass
            if native is not None:
                try: native.close()
                except OSError: pass
            # Remove only files this failed attempt created. An empty earlier
            # log must not replace the real fallback log during log collection.
            for path, owned in ((event_path, created_event), (native_path, created_native)):
                if owned:
                    try: path.unlink()
                    except OSError: pass
    if _events is None: return None
    # Rebind even if a parent/runtime already enabled faulthandler elsewhere.
    try: faulthandler.enable(file=_native, all_threads=True)
    except (OSError, RuntimeError, ValueError) as exc: record_event('native_logger.error', error=str(exc))
    record_event('startup', version=__version__, pid=os.getpid(), executable=sys.executable,
                 frozen=bool(getattr(sys, 'frozen', False)), log_folder=str(_folder))
    previous = sys.excepthook
    def exception(kind, value, tb):
        record_event('unhandled_exception', traceback=''.join(traceback.format_exception(kind, value, tb)))
        flush_events(timeout=.2)
        previous(kind, value, tb)
    sys.excepthook = exception
    atexit.register(_shutdown_events)
    return _folder
