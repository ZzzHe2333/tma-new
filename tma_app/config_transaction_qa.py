"""Isolated concurrent settings-save checks, including a second executable."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback

from . import __version__, atomic_files, path_settings as settings


def side_writer(output):
    from .mass_cache import save_refresh_hours
    report = {'status': 'failed', 'version': __version__}
    output.parent.mkdir(parents=True, exist_ok=True)
    def work():
        try:
            output.with_suffix('.ready').write_text('ready', encoding='utf-8')
            save_refresh_hours(96)
            report.update(status='passed')
        except Exception:
            report['error'] = traceback.format_exc()
    thread = threading.Thread(target=work, name='TMA-QA-config-write', daemon=True)
    thread.start(); thread.join(35)
    if thread.is_alive():
        report['error'] = 'Config write did not complete'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['status'] == 'passed' else 1


def verify(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog
    from .batch_qa import wait_until
    output = output.absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'version': __version__, 'status': 'failed', 'checks': []}
    write = atomic_files.write_json
    entered, release = threading.Event(), threading.Event()
    ticks, child = [], None
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: ticks.append(time.perf_counter()))
    heartbeat.start(5)
    try:
        settings._save_data({'paths': {'m': '', 'open_folder': 'old-directory'},
                             'mass_cache': {'refresh_hours': 24}, 'extension': {'keep': [1, 2, 3]}})
        primary = settings.config_path()
        before = primary.read_bytes()
        def blocked(path, data, **kwargs):
            if Path(path) == primary and not entered.is_set():
                entered.set()
                assert release.wait(20)
            return write(path, data, **kwargs)
        atomic_files.write_json = blocked
        dialog = window.show_path_settings()
        wait_until(lambda: not dialog._loading)
        dialog.paths.item(1, 1).setText('new-directory')
        started = time.perf_counter(); dialog.accept()
        report['save_return_seconds'] = time.perf_counter() - started
        assert report['save_return_seconds'] < .5
        wait_until(entered.is_set)
        assert dialog.saving and settings.cached_settings()[1]['paths']['open_folder'] == 'old-directory'
        helper = output.with_suffix('.worker.json')
        for path in (helper, helper.with_suffix('.ready')):
            path.unlink(missing_ok=True)
        command = [sys.executable]
        if not getattr(sys, 'frozen', False):
            command.append(str(Path(__file__).resolve().parents[1] / 'run.py'))
        command += ['--verify-config-write', str(helper)]
        child = subprocess.Popen(command, env=dict(os.environ), stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        wait_until(lambda: helper.with_suffix('.ready').exists(), timeout=10000)
        baseline = len(ticks)
        wait_until(lambda: len(ticks) >= baseline + 10)
        assert child.poll() is None and not helper.exists()
        started = time.perf_counter()
        try:
            settings.save_batch_popup(False)
            raise AssertionError('Synchronous GUI save must report a busy profile')
        except BlockingIOError:
            report['busy_return_seconds'] = time.perf_counter() - started
        assert report['busy_return_seconds'] < .25 and primary.read_bytes() == before
        report['checks'].append('gui_save_returns_promptly_snapshots_and_heartbeat_available_while_second_process_waits')
        release.set()
        wait_until(lambda: not dialog.saving and child.poll() is not None, timeout=10000)
        assert dialog.result() == QDialog.DialogCode.Accepted, dialog.feedback.text()
        assert child.returncode == 0 and json.loads(helper.read_text(encoding='utf-8'))['status'] == 'passed'
        data = settings._settings_data()
        assert data['paths']['open_folder'] == 'new-directory' and data['mass_cache']['refresh_hours'] == 96
        assert data['extension'] == {'keep': [1, 2, 3]}
        assert settings.cached_settings()[1] == data
        report['checks'].append('two_process_writes_preserve_both_sections_and_unknown_fields')
        settings.save_batch_popup(False)
        assert not settings.batch_popup_enabled()
        report['checks'].append('busy_gui_edit_can_be_retried_after_transaction_and_other_sections_stay_saved')
        report.update(status='passed', gui_heartbeats=len(ticks), separate_executable=bool(getattr(sys, 'frozen', False)))
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        release.set(); heartbeat.stop()
        atomic_files.write_json = write
        if child is not None and child.poll() is None:
            child.kill(); child.wait(timeout=5)
        window.dirty = False; window.close()
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if report['status'] != 'passed':
        raise SystemExit(1)
