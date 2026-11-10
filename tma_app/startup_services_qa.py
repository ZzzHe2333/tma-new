"""Hidden, offline checks for stalled startup preferences and late callbacks."""
import gc
import json
import threading
import time
import traceback
import weakref

from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtWidgets import QApplication

from . import __version__, path_settings, cloud_storage, cloud_schedule
from .batch_qa import wait_until
from .service_jobs import ServiceJob


def verify(window, output):
    from .classic import ClassicMainWindow
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'failed', 'version': __version__, 'checks': []}
    read = path_settings._read_settings
    cleanup, install = cloud_storage.cleanup, cloud_schedule.install_daily_task
    entered, release = threading.Event(), threading.Event()
    calls, ticks, starts, notices, effects = [], [], [], [], []
    fresh, worker = None, None
    timer = QTimer(); timer.timeout.connect(lambda: ticks.append(1)); timer.start(5)
    def paused(*args, **kwargs):
        calls.append(threading.get_ident())
        assert threading.current_thread() is not threading.main_thread()
        entered.set(); assert release.wait(15)
        return read(*args, **kwargs)
    try:
        wait_until(lambda: not window._startup_services_pending)
        data = {'paths': {'m': ''}, 'notifications': {'enabled': False},
                'mcp': {'enabled': True, 'port': 18765, 'token': 'fixture-only-token-for-testing'}}
        path_settings._save_data(data)
        with path_settings._snapshot_lock:
            path_settings._snapshots.pop(str(path_settings.config_path()), None)
        path_settings._read_settings = paused
        started = time.perf_counter()
        fresh = ClassicMainWindow()
        fresh.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        fresh.mcp_service.start = lambda options: starts.append((options, threading.get_ident()))
        fresh.notify_usage = lambda *a, **k: notices.append((a, k))
        fresh.show(); QApplication.processEvents()
        report['cold_constructor_and_first_events_seconds'] = time.perf_counter() - started
        assert report['cold_constructor_and_first_events_seconds'] < 1
        wait_until(entered.is_set)
        worker = fresh._mcp_settings_job.thread
        baseline = len(ticks); wait_until(lambda: len(ticks) >= baseline + 8)
        assert fresh._startup_services_pending and not starts and not notices
        assert len(calls) == 1
        release.set(); wait_until(lambda: not fresh._startup_services_pending)
        assert len(starts) == len(notices) == 1 and starts[0][1] == threading.get_ident()
        assert notices[0][1] == {'startup': True}
        wait_until(lambda: not worker.is_alive())
        report['checks'].append('cold_window_and_size_menu_paint_while_config_read_is_blocked_then_startup_runs_once')

        entered.clear(); release.clear(); calls.clear()
        fresh.start_saved_mcp(); wait_until(entered.is_set)
        worker = fresh._mcp_settings_job.thread
        started = time.perf_counter()
        for _ in range(100): fresh.start_saved_mcp()
        report['enqueue_100_restart_requests_seconds'] = time.perf_counter() - started
        assert report['enqueue_100_restart_requests_seconds'] < .5 and len(calls) == 1
        fresh.mcp_service.stop(wait=False)
        release.set(); wait_until(lambda: fresh._mcp_settings_job is None)
        wait_until(lambda: not worker.is_alive())
        assert len(starts) == 1 and fresh.mcp_service.state == 'stopped' and len(calls) == 1
        report['checks'].append('restart_requests_coalesce_and_manual_stop_cannot_be_undone_by_old_load')

        path_settings._read_settings = read
        path_settings._save_data({**data, 'cloud': {'mounts': [], 'retention_hours': 72}})
        cloud_storage.cleanup = lambda: effects.append('cleanup')
        cloud_schedule.install_daily_task = lambda: effects.append('schedule')
        entered.clear(); release.clear(); calls.clear()
        path_settings._read_settings = paused
        fresh.start_cloud_maintenance(schedule=True); wait_until(entered.is_set)
        worker = fresh.cloud_maintenance.thread
        started = time.perf_counter(); fresh.close()
        report['close_while_cloud_config_blocked_seconds'] = time.perf_counter() - started
        assert report['close_while_cloud_config_blocked_seconds'] < .5 and not fresh.isVisible()
        release.set(); wait_until(lambda: not worker.is_alive())
        QApplication.processEvents()
        assert not effects and len(calls) == 1
        report['checks'].append('cloud_config_read_is_background_close_returns_without_wait_late_cleanup_and_schedule_skipped')

        path_settings._read_settings = read
        entered.clear(); release.clear()
        def plain(cancelled):
            entered.set(); assert release.wait(15)
        job = ServiceJob(plain)
        job.start(); wait_until(entered.is_set)
        worker, reference = job.thread, weakref.ref(job)
        job.cancel(); job.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        del job; gc.collect()
        assert reference() is None and worker.is_alive()
        release.set(); wait_until(lambda: not worker.is_alive())
        report['checks'].append('cancelled_qt_wrapper_is_released_while_plain_worker_remains_blocked')
        report.update(status='passed', gui_heartbeats=len(ticks), real_mcp_listener_started=False,
                      real_cloud_cleanup_or_scheduled_task_used=False)
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        release.set(); timer.stop()
        path_settings._read_settings = read
        cloud_storage.cleanup, cloud_schedule.install_daily_task = cleanup, install
        if fresh is not None: fresh.close()
        window.close()
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if report['status'] != 'passed':
        raise SystemExit(1)
