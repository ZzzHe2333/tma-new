"""Frozen regression for slow source-path resolution during batch admission."""
import csv
import hashlib
from io import StringIO
import json
from pathlib import Path
import threading
import time
import traceback

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from . import __version__
from .batch_qa import wait_until


def verify(window, output, paths):
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'failed', 'version': __version__, 'checks': []}
    resolve, read = Path.resolve, Path.read_bytes
    entered, release = threading.Event(), threading.Event()
    threads, ticks, reads = [], [], []
    gui = threading.get_ident()
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    timer.start(5)
    try:
        sources = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        def slow(path, *args, **kwargs):
            if path == paths[0]:
                threads.append(threading.get_ident())
                entered.set()
                assert release.wait(15)
            return resolve(path, *args, **kwargs)
        Path.resolve = slow
        started = time.perf_counter()
        window.import_files(paths[:2])
        report['first_import_return_seconds'] = time.perf_counter() - started
        assert report['first_import_return_seconds'] < 1
        dialog = window.batch_dialog
        wait_until(entered.is_set)
        baseline = len(ticks)
        wait_until(lambda: len(ticks) >= baseline + 10)
        started = time.perf_counter(); dialog.enqueue_files([paths[0]])
        report['append_return_seconds'] = time.perf_counter() - started
        assert report['append_return_seconds'] < .5 and len(dialog.rows) == 3
        assert threads and all(t != gui for t in threads)
        release.set()
        wait_until(lambda: dialog.job is None and window.worker is None)
        assert len(window.curves) == 2
        assert all(row.get('T1') is not None for row in dialog.rows)
        report['checks'].append('real_multi_import_and_batch_append_return_while_source_resolution_is_blocked')
        report['checks'].append('path_resolution_only_on_workers_gui_heartbeat_and_duplicate_rows_preserved')
        dialog.show_all(); dialog.CopyBatch.click()
        copied = list(csv.reader(StringIO(QApplication.clipboard().text()), delimiter='\t'))
        assert len(copied) == 4 and all(len(row) == 5 for row in copied)
        assert [row[0] for row in copied[1:]] == [paths[0].stem, paths[1].stem, paths[0].stem]
        assert '5 列' in dialog.feedback.text()
        output.with_suffix('.clipboard.tsv').write_text(QApplication.clipboard().text(), encoding='utf-8-sig')
        report['checks'].append('five_column_clipboard_names_order_and_ui_feedback_match')
        entered.clear(); release.clear()
        def observed(path):
            if path == paths[0]:
                reads.append(1)
            return read(path)
        Path.read_bytes = observed
        dialog.enqueue_files([paths[0]])
        wait_until(entered.is_set)
        started = time.perf_counter(); dialog.cancel_processing()
        report['cancel_return_seconds'] = time.perf_counter() - started
        assert report['cancel_return_seconds'] < .5
        release.set(); wait_until(lambda: dialog.job is None)
        assert not reads and dialog.rows[-1]['state'] == '已取消' and dialog.rows[-1].get('T1') is None
        report['checks'].append('cancelled_path_resolution_does_not_read_decode_or_apply_late_values')
        dialog.enqueue_files([paths[1]])
        wait_until(lambda: dialog.job is None)
        assert dialog.rows[-1].get('T1') is not None
        assert len(window.curves) == 2
        assert all(hashlib.sha256(read(Path(path))).hexdigest() == digest for path, digest in sources.items())
        report['checks'].append('subsequent_batch_still_works_and_source_bytes_unchanged')
        report.update(status='passed', gui_heartbeats=len(ticks), source_sha256=sources)
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        release.set(); timer.stop()
        Path.resolve, Path.read_bytes = resolve, read
        window.dirty = False; window.close()
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if report['status'] != 'passed':
        raise SystemExit(1)
