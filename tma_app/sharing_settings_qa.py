"""Offline checks of settings I/O, cancellation and preference merging."""
import json
import os
import threading
import time
import traceback
import uuid

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QDialog
from shiboken6 import isValid

from . import __version__, path_settings, sharing
from .batch_qa import wait_until


def verify(window, output):
    output = output.absolute(); output.parent.mkdir(parents=True, exist_ok=True)
    previous = os.environ.get('LOCALAPPDATA')
    os.environ['LOCALAPPDATA'] = str(output.parent / ('sharing-settings-fixture-' + uuid.uuid4().hex[:8]))
    report = dict(status='failed', version=__version__, checks=[])
    read, write = path_settings._read_settings, path_settings._write_settings
    maintenance = window.start_cloud_maintenance; window.start_cloud_maintenance = lambda **kwargs: None
    entered, release = threading.Event(), threading.Event()
    ticks, dialogs, threads, writes = [], [], [], []
    timer = QTimer(); timer.timeout.connect(lambda: ticks.append(1)); timer.start(5)
    fresh = None
    def blocked_read(*args, **kwargs):
        assert threading.current_thread() is not threading.main_thread()
        entered.set(); assert release.wait(15)
        return read(*args, **kwargs)
    def open_form(owner):
        dialog = owner.show_sharing_settings(); dialogs.append(dialog)
        return dialog
    try:
        path_settings._save_data({'paths': {'m': 'before.xlsx'}, 'cloud': {'mounts': [], 'retention_hours': 72}})
        sharing.save_settings('', '/before', False,
            'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=fixture-only')
        wait_until(lambda: not window._startup_services_pending)
        path_settings._read_settings = blocked_read
        started = time.perf_counter(); dialog = open_form(window)
        report['open_with_blocked_read_seconds'] = time.perf_counter() - started
        assert report['open_with_blocked_read_seconds'] < .5
        wait_until(entered.is_set)
        baseline = len(ticks); wait_until(lambda: len(ticks) >= baseline + 8)
        assert not dialog.save_button.isEnabled()
        worker = dialog._job.thread; threads.append(worker)
        dialog.close(); assert not dialog.isVisible()
        release.set(); wait_until(lambda: not worker.is_alive())
        assert dialog._closed
        report['checks'].append('settings_open_and_gui_heartbeat_continue_while_read_blocked_close_discards_late_form')

        path_settings._read_settings = read
        dialog = open_form(window); wait_until(dialog.save_button.isEnabled)
        path_settings._update_data(lambda data: data['paths'].update(m='after.xlsx'))
        secret = read()[1]['sharing']['webhook']
        entered.clear(); release.clear()
        def blocked_write(data, primary):
            assert threading.current_thread() is not threading.main_thread()
            writes.append(data['sharing']['folder']); entered.set(); assert release.wait(15)
            return write(data, primary)
        path_settings._write_settings = blocked_write
        dialog.folder.setText('/saved-on-worker')
        started = time.perf_counter(); dialog.accept(); dialog.accept()
        report['enqueue_save_with_blocked_write_seconds'] = time.perf_counter() - started
        assert report['enqueue_save_with_blocked_write_seconds'] < .5
        wait_until(entered.is_set)
        worker = dialog._job.thread; threads.append(worker)
        baseline = len(ticks); wait_until(lambda: len(ticks) >= baseline + 8)
        assert len(writes) == 1 and not dialog.save_button.isEnabled()
        release.set(); wait_until(lambda: dialog.result() == QDialog.DialogCode.Accepted)
        wait_until(lambda: not worker.is_alive())
        data = read()[1]
        assert data['paths']['m'] == 'after.xlsx' and data['sharing']['folder'] == '/saved-on-worker'
        assert data['sharing']['webhook'] == secret
        report['checks'].append('save_is_background_duplicate_click_writes_once_retains_newer_paths_and_encrypted_webhook')

        path_settings._write_settings = write
        old = open_form(window); wait_until(old.save_button.isEnabled)
        entered.clear(); release.clear(); writes.clear()
        def first_read_waits(*args, **kwargs):
            if not entered.is_set():
                assert threading.current_thread() is not threading.main_thread()
                entered.set(); assert release.wait(15)
            return read(*args, **kwargs)
        def track_write(data, primary):
            writes.append(data['sharing']['folder']); return write(data, primary)
        path_settings._read_settings, path_settings._write_settings = first_read_waits, track_write
        old.folder.setText('/cancelled-old'); old.accept(); wait_until(entered.is_set)
        old_worker = old._job.thread; threads.append(old_worker)
        old.close()
        newer = open_form(window); wait_until(newer.save_button.isEnabled)
        newer.folder.setText('/newest'); newer.accept(); threads.append(newer._job.thread)
        release.set(); wait_until(lambda: newer.result() == QDialog.DialogCode.Accepted)
        wait_until(lambda: not old_worker.is_alive())
        assert writes == ['/newest'] and read()[1]['sharing']['folder'] == '/newest'
        report['checks'].append('cancelled_save_waiting_for_read_cannot_commit_after_new_form_saves')

        path_settings._read_settings, path_settings._write_settings = read, write
        from . import cloud_dialog
        mount_type = cloud_dialog.MountDialog
        mount = dict(id='c'*32, name='离线验证云盘', url='http://127.0.0.1:19876/dav/',
                     username='fixture', password='', verify_tls=True)
        class FixtureMount:
            def __init__(self, parent): self.value = mount
            def exec(self): return QDialog.DialogCode.Accepted
        dialog = open_form(window); wait_until(dialog.save_button.isEnabled)
        dialog.folder.setText('/unsaved-folder'); dialog.webhook.setText('typed-only')
        entered.clear(); release.clear(); path_settings._read_settings = blocked_read
        try:
            cloud_dialog.MountDialog = FixtureMount
            started = time.perf_counter(); dialog.add_mount()
            report['enqueue_add_mount_seconds'] = time.perf_counter() - started
            assert report['enqueue_add_mount_seconds'] < .5
            wait_until(entered.is_set); worker = dialog._job.thread; threads.append(worker)
            baseline = len(ticks); wait_until(lambda: len(ticks) >= baseline + 8)
            release.set(); wait_until(lambda: not dialog.busy)
            wait_until(lambda: not worker.is_alive())
            assert dialog.mounts.currentData() == mount['id']
            assert dialog.folder.text() == '/unsaved-folder' and dialog.webhook.text() == 'typed-only'
            data = read()[1]
            assert data['cloud']['mounts'] == [mount] and data['sharing']['folder'] == '/newest'
            dialog.close()
        finally:
            cloud_dialog.MountDialog = mount_type
        report['checks'].append('add_mount_saves_only_cloud_off_gui_without_network_and_preserves_unsaved_form_edits')

        path_settings._read_settings = read
        from .classic import ClassicMainWindow
        fresh = ClassicMainWindow(); fresh.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        fresh.start_cloud_maintenance = lambda **kwargs: None
        fresh.show(); wait_until(lambda: not fresh._startup_services_pending)
        dialog = open_form(fresh); wait_until(dialog.save_button.isEnabled)
        entered.clear(); release.clear(); path_settings._read_settings = blocked_read
        dialog.folder.setText('/closed-main'); dialog.accept(); wait_until(entered.is_set)
        worker = dialog._job.thread; threads.append(worker)
        started = time.perf_counter(); fresh.close()
        report['close_during_save_read_seconds'] = time.perf_counter() - started
        assert report['close_during_save_read_seconds'] < .5 and not dialog.isVisible()
        release.set(); wait_until(lambda: not worker.is_alive())
        assert read()[1]['sharing']['folder'] == '/newest'
        report['checks'].append('main_close_cancels_settings_save_before_commit_and_returns_promptly')
        report.update(status='passed', gui_heartbeats=len(ticks), real_network_used=False,
                      real_scheduled_task_registered=False)
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        release.set(); timer.stop()
        for dialog in dialogs:
            if isValid(dialog): dialog.close()
        if fresh is not None: fresh.close()
        for thread in threads: thread.join(3)
        path_settings._read_settings, path_settings._write_settings = read, write
        window.start_cloud_maintenance = maintenance; window.close()
        if previous is None: os.environ.pop('LOCALAPPDATA', None)
        else: os.environ['LOCALAPPDATA'] = previous
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if report['status'] != 'passed': raise SystemExit(1)
