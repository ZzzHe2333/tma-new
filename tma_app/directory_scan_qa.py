"""Hidden, offline checks of actual helper lifetimes and picker responsiveness."""
import gc
import json
import os
from pathlib import Path
import queue
import threading
import time
import traceback
import uuid
import weakref

from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtWidgets import QApplication

from . import __version__, directory_scan as scan
from .async_data_picker import DataFileDialog
from .batch_qa import wait_until


def verify(window, output):
    output = output.absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    fixture = output.parent / ('directory-fixture-' + uuid.uuid4().hex[:8]); fixture.mkdir()
    report = {'status': 'failed', 'version': __version__, 'checks': []}
    launch, idle = scan._launch, scan.SCAN_IDLE_SECONDS
    processes, threads, cancellations, dialogs, ticks = [], [], [], [], []
    gate = threading.Event(); gate.set()
    timer = QTimer(); timer.timeout.connect(lambda: ticks.append(1)); timer.start(5)
    fresh = None
    def controlled(request, result):
        directory = json.loads(request.read_text(encoding='utf-8'))['directory']
        if Path(directory).name.startswith('slow-'):
            marker = request.with_name('probe.ready')
            process = scan.start_process(scan.command('--verify-directory-scan-wait', marker), request.parent)
            processes.append((process, marker))
            assert gate.wait(15)
            return process
        return launch(request, result)
    try:
        wait_until(lambda: not window._startup_services_pending)
        folder = fixture / '中文 文件夹'; folder.mkdir()
        for name, stamp in [('old.001', 1500000000), ('new.001', 1700000000), ('样品 #9.007', 1600000000)]:
            path = folder / name; path.write_text('offline fixture', encoding='utf-8')
            os.utime(path, (stamp, stamp))
        (folder / 'ignored.txt').write_text('filtered out')
        started = time.perf_counter()
        dialog = DataFileDialog(window, '离线目录验证', str(folder), 'TMA (*.001 *.007)')
        dialogs.append(dialog); dialog.show()
        report['picker_construct_seconds'] = time.perf_counter() - started
        baseline = len(ticks)
        wait_until(lambda: dialog.model.rowCount() == 3, timeout=10000)
        report['first_local_list_seconds'] = time.perf_counter() - started
        assert report['picker_construct_seconds'] < .5
        assert report['first_local_list_seconds'] < 5
        assert len(ticks) > baseline
        assert [row[0] for row in dialog.model.rows] == ['new.001', '样品 #9.007', 'old.001']
        dialog.selectFile(str(folder / '样品 #9.007')); dialog.accept()
        assert dialog.selectedFiles() == [str(folder / '样品 #9.007')]
        wait_until(lambda: not dialog._scan_worker.thread.is_alive())
        report['checks'].append('real_helper_lists_unicode_files_newest_first_filters_and_accepts_without_gui_enumeration')

        large = fixture / 'many-files'; large.mkdir()
        for index in range(1000):
            path = large / f'{index:04}.001'; path.write_bytes(b'fixture')
            os.utime(path, (1700000000 + index, 1700000000 + index))
        started = time.perf_counter()
        dialog = DataFileDialog(window, '千文件目录验证', str(large), 'TMA (*.001)')
        dialogs.append(dialog); dialog.show()
        wait_until(lambda: dialog.model.rowCount() == 1000, timeout=10000)
        report['local_1000_entries_seconds'] = time.perf_counter() - started
        assert report['local_1000_entries_seconds'] < 5
        assert dialog.model.rows[0][0] == '0999.001' and dialog.model.rows[-1][0] == '0000.001'
        dialog.reject(); wait_until(lambda: not dialog._scan_worker.thread.is_alive())
        report['checks'].append('real_helper_and_background_sort_load_1000_local_entries_with_newest_first')

        scan._launch = controlled
        for index in range(4):
            cancelled = threading.Event(); cancellations.append(cancelled)
            thread = threading.Thread(target=scan.scan_directory,
                args=(str(fixture / f'slow-{index}'), cancelled, queue.Queue()), daemon=True)
            threads.append(thread); thread.start()
        wait_until(lambda: len(processes) == 4 and all(marker.exists() for _, marker in processes), timeout=10000)
        assert all(process.poll() is None for process, _ in processes)
        if os.name == 'nt': assert all(hasattr(process, '_directory_job') for process, _ in processes)
        baseline = len(ticks); wait_until(lambda: len(ticks) >= baseline + 8)
        for cancelled in cancellations: cancelled.set()
        started = time.perf_counter()
        dialog = DataFileDialog(window, '取消慢任务后打开本地目录', str(folder), 'TMA (*.001 *.007)')
        dialogs.append(dialog); dialog.show()
        wait_until(lambda: dialog.model.rowCount() == 3, timeout=10000)
        report['cancel_four_then_local_list_seconds'] = time.perf_counter() - started
        assert report['cancel_four_then_local_list_seconds'] < 5
        wait_until(lambda: all(not thread.is_alive() for thread in threads))
        report['cancelled_helpers'] = [dict(pid=process.pid, returncode=process.poll(),
            ipc_exists=marker.parent.exists(),
            ipc_files=[p.name for p in marker.parent.iterdir()] if marker.parent.exists() else [])
            for process, marker in processes]
        assert all(process.poll() is not None and not marker.parent.exists() for process, marker in processes)
        dialog.reject(); wait_until(lambda: not dialog._scan_worker.thread.is_alive())
        report['checks'].append('four_actual_waiting_children_keep_gui_alive_cancel_terminates_all_slots_and_ipc_are_released_local_picker_recovers')

        offset = len(processes); gate.clear()
        dialog = DataFileDialog(window, '连续切换目录', str(fixture / 'slow-first'), 'TMA (*.001 *.007)')
        dialogs.append(dialog); dialog.show()
        wait_until(lambda: len(processes) == offset + 1 and processes[-1][1].exists(), timeout=10000)
        worker, thread = dialog._scan_worker, dialog._scan_worker.thread
        started = time.perf_counter()
        for index in range(100): dialog.setDirectory(str(fixture / f'slow-nav-{index}'))
        dialog.setDirectory(str(folder))
        report['navigate_101_seconds'] = time.perf_counter() - started
        assert worker.thread is thread and len(processes) == offset + 1
        assert worker.pending[0] == str(folder) and worker.current[1].is_set()
        gate.set(); wait_until(lambda: dialog.model.rowCount() == 3, timeout=10000)
        assert len(processes) == offset + 1 and processes[-1][0].poll() is not None
        assert dialog._directory == str(folder)
        dialog.reject(); wait_until(lambda: not thread.is_alive())
        report['checks'].append('101_navigations_reuse_one_coordinator_replace_pending_paths_and_only_launch_latest_directory')

        scan.SCAN_IDLE_SECONDS = 2
        dialog = DataFileDialog(window, '读取超时', str(fixture / 'slow-timeout'), 'TMA (*.001 *.007)')
        dialogs.append(dialog); dialog.show()
        wait_until(lambda: '超时' in dialog.feedback.text(), timeout=10000)
        assert processes[-1][0].poll() is not None
        dialog.setDirectory(str(folder)); wait_until(lambda: dialog.model.rowCount() == 3, timeout=10000)
        dialog.reject(); wait_until(lambda: not dialog._scan_worker.thread.is_alive())
        scan.SCAN_IDLE_SECONDS = idle
        report['checks'].append('idle_timeout_terminates_actual_child_and_next_local_directory_still_loads')

        from .classic import ClassicMainWindow
        fresh = ClassicMainWindow(); fresh.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        fresh.show(); wait_until(lambda: not fresh._startup_services_pending)
        offset = len(processes)
        dialog = DataFileDialog(fresh, '主窗口关闭', str(fixture / 'slow-close'), 'TMA (*.001)'); dialog.show()
        wait_until(lambda: len(processes) == offset + 1 and processes[-1][1].exists(), timeout=10000)
        worker = dialog._scan_worker
        started = time.perf_counter(); fresh.close()
        report['close_during_scan_seconds'] = time.perf_counter() - started
        assert report['close_during_scan_seconds'] < .5 and worker.closed
        dialog.deleteLater(); reference = weakref.ref(dialog)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        del dialog; gc.collect()
        assert reference() is None
        wait_until(lambda: not worker.thread.is_alive())
        assert processes[-1][0].poll() is not None
        report['final_helpers'] = [dict(pid=process.pid, returncode=process.poll(),
            ipc_exists=marker.parent.exists(),
            ipc_files=[p.name for p in marker.parent.iterdir()] if marker.parent.exists() else [])
            for process, marker in processes]
        assert all(not marker.parent.exists() for _, marker in processes)
        with scan._guard: assert not scan._children and not scan._retired
        report['checks'].append('parent_close_returns_promptly_picker_wrapper_released_and_no_helper_children_or_ipc_remain')
        report.update(status='passed', gui_heartbeats=len(ticks), waiting_helpers_tested=len(processes),
                      physical_disconnected_share_tested=False)
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        gate.set(); timer.stop()
        for cancelled in cancellations: cancelled.set()
        for dialog in dialogs: dialog.reject()
        if fresh is not None: fresh.close()
        scan._launch, scan.SCAN_IDLE_SECONDS = launch, idle
        for thread in threads: thread.join(3)
        window.close()
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if report['status'] != 'passed': raise SystemExit(1)
