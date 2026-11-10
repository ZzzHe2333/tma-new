"""Offline checks for stalled event logging and bounded executable shutdown."""
import faulthandler
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback

from . import __version__, diagnostics
from .diagnostic_writer import EventWriter


def blocked_exit(output):
    output.parent.mkdir(parents=True, exist_ok=True)
    if diagnostics._events is not None:
        assert diagnostics._events.close(timeout=1)
    read_fd, write_fd = os.pipe()
    entered = threading.Event()
    def write(data):
        entered.set()
        os.write(write_fd, b'x' * (2 * 1024 * 1024))
        return len(data)
    diagnostics._events = sink = EventWriter(write, lambda: os.close(write_fd))
    diagnostics.record_event('qa.blocked_exit')
    assert entered.wait(2) and not sink.flush(timeout=.03)
    output.write_text(json.dumps({'status': 'passed', 'version': __version__, 'raw_write_blocked': True,
                                 'pending': sink.stats()['pending']}), encoding='utf-8')
    # Keep the read end open and unread until process exit, so the raw write
    # really remains blocked when the registered shutdown handler runs.
    return 0


def verify(window, output, paths):
    from PySide6.QtCore import QTimer
    from .batch_qa import wait_until
    output = output.absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'failed', 'version': __version__, 'checks': []}
    original = diagnostics._events
    entered, release = threading.Event(), threading.Event()
    chunks, threads, ticks = [], [], []
    sink, child = None, None
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    timer.start(5)
    try:
        sources = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        assert diagnostics.flush_events(timeout=2)
        def write(data):
            entered.set()
            assert release.wait(15)
            threads.append(threading.get_ident())
            chunks.append(bytes(data))
            return len(data)
        sink = EventWriter(write, lambda: None, max_records=64, max_bytes=128 * 1024)
        diagnostics._events = sink
        diagnostics.record_event('qa.blocked')
        wait_until(entered.is_set)
        started = time.perf_counter()
        window.import_files(paths[:2])
        report['import_return_seconds'] = time.perf_counter() - started
        assert report['import_return_seconds'] < 1
        wait_until(lambda: window.worker is None and window.batch_dialog.job is None)
        assert len(window.curves) == 2 and all(row.get('T1') is not None for row in window.batch_dialog.rows)
        baseline = len(ticks)
        wait_until(lambda: len(ticks) >= baseline + 10)
        assert not release.is_set()
        report['checks'].append('imports_and_batch_calculation_finish_while_event_log_write_remains_blocked_gui_alive')
        started = time.perf_counter()
        for index in range(1000):
            diagnostics.record_event('qa.burst', index=index)
        report['enqueue_1000_seconds'] = time.perf_counter() - started
        value = {'sample': ['original']}
        diagnostics.record_event('qa.last', value=value)
        value['sample'][0] = 'edited'
        before = sink.stats()
        assert before['pending'] <= 64 and before['retained_bytes'] <= 128 * 1024 and before['dropped'] > 0
        # The native stack file is independent of the stalled event writer.
        assert diagnostics._native is not None and faulthandler.is_enabled()
        faulthandler.dump_traceback(file=diagnostics._native, all_threads=True)
        assert Path(diagnostics._native.name).stat().st_size > 100
        report['checks'].append('bounded_event_queue_keeps_latest_context_native_stack_channel_still_available')
        release.set()
        assert sink.flush(timeout=3)
        assert sink.close(timeout=2)
        diagnostics._events = original
        records = [json.loads(line) for line in b''.join(chunks).decode('utf-8').splitlines()]
        latest = next(item for item in records if item['event'] == 'qa.last')
        assert latest['value'] == {'sample': ['original']} and latest['thread'] == threading.get_ident()
        assert threads and all(t != threading.get_ident() for t in threads)
        assert sum(item['count'] for item in records if item['event'] == 'diagnostics.events_dropped') == before['dropped']
        output.with_suffix('.events.jsonl').write_bytes(b''.join(chunks))
        report['checks'].append('caller_fields_are_immutable_snapshot_thread_identity_preserved_drop_count_reported')
        target = output.with_suffix('.exit.json')
        command = [sys.executable]
        if not getattr(sys, 'frozen', False):
            command.append(str(Path(__file__).resolve().parents[1] / 'run.py'))
        command += ['--verify-diagnostics-exit', str(target)]
        env = dict(os.environ, LOCALAPPDATA=str(output.parent / 'diagnostics-exit-profile'))
        started = time.perf_counter()
        child = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        wait_until(lambda: child.poll() is not None, timeout=8000)
        report['blocked_exit_process_seconds'] = time.perf_counter() - started
        assert child.returncode == 0 and json.loads(target.read_text(encoding='utf-8'))['raw_write_blocked']
        report['checks'].append('second_executable_with_blocked_raw_os_write_exits_without_buffer_lock_crash_or_hang')
        assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in sources.items())
        report.update(status='passed', gui_heartbeats=len(ticks), queue_before_release=before,
                      source_sha256=sources, separate_executable=bool(getattr(sys, 'frozen', False)))
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        release.set(); timer.stop()
        if sink is not None:
            sink.close(timeout=2)
        diagnostics._events = original
        if child is not None and child.poll() is None:
            child.kill(); child.wait(timeout=5)
        window.dirty = False; window.close()
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if report['status'] != 'passed':
        raise SystemExit(1)
