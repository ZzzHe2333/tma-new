"""Offline notification checks for the frozen application, using an isolated profile."""
import builtins
import json
import os
import sys
import threading
import time
import traceback
import uuid

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QInputDialog, QDialog

from . import __version__, notifications as module, notify_guard
from .path_settings import config_path


def _verify_lazy_transport(window, report):
    """Exercise the first SDK import on a worker, with every request intercepted."""
    QApplication.processEvents()
    from .batch_qa import wait_until
    wait_until(lambda: not window._startup_services_pending)
    assert 'httpx' not in sys.modules
    target = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=qa-fixture-only'
    from .sharing import webhook_url
    assert webhook_url(target) == module.normalize_target('wecom', target)
    assert not module.settings()['enabled'] and 'httpx' not in sys.modules
    module.save_settings('wecom', target, enabled=True, attach_image=False)
    assert 'httpx' not in sys.modules
    report['checks'].append('empty_window_and_notification_configuration_do_not_import_http_sdk')
    original_import = builtins.__import__
    original_queue, original_error = module._delivery_queue, module._last_error
    dispatcher = module._DeliveryQueue(module._deliver, idle_seconds=.03)
    module._delivery_queue = dispatcher
    entered, release, delivered = threading.Event(), threading.Event(), threading.Event()
    imports, ticks, requests, clients = [], [], [], []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    def importer(name, *args, **kwargs):
        if name == 'httpx' and name not in sys.modules:
            imports.append(threading.get_ident())
            entered.set()
            assert release.wait(10)
            http = original_import(name, *args, **kwargs)
            client = http.Client
            clients.append((http, client))
            def response(request):
                requests.append(request)
                delivered.set()
                return http.Response(200, json={'errcode': 0})
            http.Client = lambda **kw: client(transport=http.MockTransport(response), **kw)
            return http
        return original_import(name, *args, **kwargs)
    try:
        builtins.__import__ = importer
        timer.start(5)
        started = time.perf_counter()
        window.notify_usage('导入数据', 'qa-fixture')
        report['first_notification_enqueue_seconds'] = time.perf_counter() - started
        assert report['first_notification_enqueue_seconds'] < 1
        deadline = time.monotonic() + 4
        while (not entered.is_set() or len(ticks) < 8) and time.monotonic() < deadline:
            QApplication.processEvents()
        assert entered.is_set() and len(ticks) >= 8 and not delivered.is_set()
        assert imports and all(t != threading.get_ident() for t in imports)
        release.set()
        deadline = time.monotonic() + 6
        while (dispatcher.pending or dispatcher.workers) and time.monotonic() < deadline:
            QApplication.processEvents()
        assert delivered.is_set() and not dispatcher.pending and not dispatcher.workers
        assert not module.last_error() and len(requests) == 1
        request = requests[0]
        assert request.method == 'POST' and str(request.url) == target
        assert json.loads(request.content)['msgtype'] == 'text'
        assert request.extensions['timeout'] == {'connect': 10, 'read': 30, 'write': 30, 'pool': 30}
        report['checks'].append('blocked_first_http_import_keeps_gui_alive_then_mocked_notification_delivers')
    finally:
        release.set()
        timer.stop()
        builtins.__import__ = original_import
        for http, client in clients:
            http.Client = client
        module._delivery_queue, module._last_error = original_queue, original_error
        module.save_settings('wecom', '', enabled=False, attach_image=False, clear_target=True)


def _verify_runtime_preferences(window, report):
    """Warm UI checks remain available while a preference refresh is blocked."""
    from . import path_settings
    read = path_settings._read_settings
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    calls, ticks = [], []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    key = str(path_settings.config_path())
    def blocked(*args, **kwargs):
        calls.append(threading.get_ident())
        assert threading.current_thread() is not threading.main_thread()
        entered.set()
        try:
            assert release.wait(10)
            return read(*args, **kwargs)
        finally:
            done.set()
    try:
        path_settings._read_settings = blocked
        with path_settings._snapshot_lock:
            path_settings._refresh_checked[key] = time.monotonic() - 31
        timer.start(5)
        started = time.perf_counter()
        for _ in range(100):
            window.notify_usage('导入数据', 'qa-fixture', with_plot=True)
            assert path_settings.batch_popup_enabled()
        report['runtime_preference_checks_100_seconds'] = time.perf_counter() - started
        assert report['runtime_preference_checks_100_seconds'] < .5
        deadline = time.monotonic() + 3
        while (not entered.is_set() or len(ticks) < 8) and time.monotonic() < deadline:
            QApplication.processEvents()
        assert entered.is_set() and len(ticks) >= 8 and len(calls) == 1
        assert calls[0] != threading.get_ident() and not done.is_set()
        report['checks'].append('100_notification_and_batch_checks_reuse_preferences_while_one_refresh_is_blocked_gui_alive')
    finally:
        timer.stop(); release.set()
        path_settings._read_settings = read
        if entered.is_set():
            assert done.wait(3)


def verify(window, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'version': __version__, 'status': 'failed', 'checks': []}
    previous = os.environ.get('LOCALAPPDATA')
    os.environ['LOCALAPPDATA'] = str(output.parent / ('notification-fixture-' + uuid.uuid4().hex[:8]))
    names = ('machine_code', 'public_ip', 'lan_ip', 'computer_name', 'settings', 'runtime_settings', 'save_settings')
    originals = {name: getattr(module, name) for name in names}
    original_node = module.uuid.getnode
    original_queue = module._delivery_queue
    release = threading.Event()
    timer = QTimer()
    prompt, warn = QInputDialog.getText, window.warn
    try:
        _verify_lazy_transport(window, report)
        _verify_runtime_preferences(window, report)
        # Only the local mock above uses a transport. Never contact a real service.
        module.public_ip = lambda: ''
        module.lan_ip = lambda: 'fixture-lan'
        module.computer_name = lambda: 'fixture-host'
        actual = module.machine_code()
        assert actual == module.machine_code()
        module.uuid.getnode = lambda: 0x001122334455
        first_host = module.machine_code()
        module.uuid.getnode = lambda: 0x001122334466
        assert module.machine_code() != first_host
        module.uuid.getnode = original_node
        report['checks'].append('same_windows_guid_distinguished_by_hardware_and_local_code_stable')
        module._write_machine_cache({'machine_code': 'copied-from-another-pc',
            'public_ip': 'previous-pc', 'checked_at': time.time()})
        assert dict(module.machine_details()) == {'机器码': actual}
        assert module._read_machine_cache() == {'machine_code': actual}
        module._write_machine_cache({'machine_code': 'copied-from-another-pc',
            'public_ip': 'previous-pc', 'checked_at': time.time()})
        details = dict(module.machine_details(full=True))
        assert details == {'机器码': actual, '内网': 'fixture-lan', '公网': '获取失败', '名字': 'fixture-host'}
        report['checks'].append('copied_cache_replaced_without_reusing_foreign_addresses')
        module._write_machine_cache({'machine_code': actual, 'checked_at': time.time(),
                                     'public_ip': 'fixture-public'})
        def forbidden(*args, **kwargs):
            raise AssertionError('Forbidden before entry authentication or unnecessary network access')
        module.public_ip = forbidden
        assert dict(module.machine_details(full=True))['公网'] == 'fixture-public'
        report['checks'].append('same_host_reuses_fresh_address_cache_without_network')

        notify_guard._create_guard('qa-local-notification-password')
        module.settings = forbidden
        warnings = []
        window.warn = warnings.append
        QInputDialog.getText = staticmethod(lambda *a: ('wrong-password', True))
        assert window.show_notification_settings() is None and warnings
        QInputDialog.getText = staticmethod(lambda *a: ('', False))
        assert window.show_notification_settings() is None
        assert getattr(window, 'notification_settings_dialog', None) is None
        report['checks'].append('wrong_or_cancelled_password_never_reads_or_opens_settings')

        module.settings = originals['settings']
        prompts, saves = [], []
        QInputDialog.getText = staticmethod(lambda *a: (prompts.append(1) or 'qa-local-notification-password', True))
        module.save_settings = lambda *a, **k: saves.append(k)
        dialog = window.show_notification_settings()
        assert dialog.isVisible() and len(prompts) == 1
        assert window.show_notification_settings() is dialog and len(prompts) == 1
        dialog.accept()
        assert dialog.result() == QDialog.DialogCode.Accepted and len(saves) == 1 and len(prompts) == 1
        dialog = window.show_notification_settings()
        assert dialog.isVisible() and len(prompts) == 2
        dialog.reject()
        report['checks'].append('correct_password_opens_save_without_reprompt_reopening_requires_password')

        received, detail_threads, ticks = [], [], []
        def delivery(config, event, batch, png, details, path, separated):
            assert release.wait(10)
            details()
            received.append(int(batch))
        dispatcher = module._DeliveryQueue(delivery, idle_seconds=.03)
        module._delivery_queue = dispatcher
        module.runtime_settings = lambda: {'enabled': True, 'target': 'fixture-only', 'provider': 'wecom',
            'events': {'import': True}, 'attach_image': False}
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        timer.start(10)
        started = time.monotonic()
        accepted = [index for index in range(1000) if module.notify('导入数据', str(index),
            details=lambda: detail_threads.append(threading.get_ident()))]
        report['notification_enqueue_1000_seconds'] = time.monotonic() - started
        assert len(accepted) == 64 and len(dispatcher.workers) == 2
        assert not detail_threads and report['notification_enqueue_1000_seconds'] < 1
        deadline = time.monotonic() + 3
        while len(ticks) < 5 and time.monotonic() < deadline:
            QApplication.processEvents()
        assert len(ticks) >= 5 and not release.is_set()
        release.set()
        deadline = time.monotonic() + 3
        while dispatcher.workers and time.monotonic() < deadline:
            QApplication.processEvents()
        assert not dispatcher.workers
        assert sorted(received) == accepted
        assert dispatcher.pending == dispatcher.retained_bytes == 0
        assert len(detail_threads) == 64 and all(t != threading.get_ident() for t in detail_threads)
        report.update(queued_notifications=len(accepted), rejected_notifications=1000-len(accepted),
                      gui_heartbeats=len(ticks))
        report['checks'].append('1000_slow_notifications_bounded_two_threads_gui_alive_all_accepted_delivered_idle_released')
        report.update(status='passed', isolated_profile=str(config_path().parent), real_transport_used=False)
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        release.set()
        timer.stop()
        module._delivery_queue = original_queue
        module.uuid.getnode = original_node
        for name, value in originals.items():
            setattr(module, name, value)
        QInputDialog.getText, window.warn = prompt, warn
        window.dirty = False
        window.close()
        if previous is None:
            os.environ.pop('LOCALAPPDATA', None)
        else:
            os.environ['LOCALAPPDATA'] = previous
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if report['status'] != 'passed':
        raise SystemExit(1)
