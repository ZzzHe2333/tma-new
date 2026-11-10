"""Frozen regression: add overlay sources while I/O is delayed or cancelled."""
import hashlib
import json
from pathlib import Path
import threading
import time
import traceback

from PySide6.QtCore import Qt, QTimer, QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog
from shiboken6 import isValid

from . import __version__, classic_dialogs as dialogs, data_file_dialog as picker, path_settings
from .batch_qa import wait_until
from .reader import read_dataset


def verify(window, output, paths):
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'version': __version__, 'status': 'failed', 'checks': []}
    original_picker, original_exec = picker.DataFileDialog.exec, dialogs.AddCurvesDialog.exec
    original_reader = dialogs.read_dataset
    entered, release = threading.Event(), threading.Event()
    timer, ticks, workers = QTimer(), [], []
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    timer.start(5)
    pending = []
    try:
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        folder = (output.parent / 'overlay-additional-fixtures').absolute()
        folder.mkdir(exist_ok=True)
        extra, cancelled, following = [folder / name for name in ('extra.007', 'cancelled.001', 'following.002')]
        for path in (extra, cancelled, following):
            path.write_bytes(paths[1].read_bytes())
        path_settings.save_paths({'m': '', 'open_folder': str(paths[0].parent)})
        window._last_data_directory = ''
        window.finish_import([read_dataset(paths[0])], [])
        original_curve = window.selected()
        original_values = original_curve.dataset.values.copy()
        read_gate = {extra, cancelled}
        def reader(path):
            workers.append(threading.get_ident())
            if Path(path) in read_gate:
                entered.set()
                assert release.wait(15)
            return original_reader(path)
        dialogs.read_dataset = reader
        def choose_file(dialog):
            path, expected_start = pending.pop(0)
            assert Path(dialog.directory().absolutePath()) == expected_start
            dialog.setDirectory(str(path.parent))
            dialog.selectFile(str(path))
            return QDialog.DialogCode.Accepted
        picker.DataFileDialog.exec = choose_file

        parent = window.show_overlay_options(new=True)
        def choose_curves(dialog):
            assert dialog.empty_selection and not dialog.checked_datasets()
            dialog.show()
            dialog.files.item(0).setCheckState(Qt.CheckState.Checked)
            dialog.compatible.setChecked(False)
            dialog.signals.setCurrentRow(next(i for i in range(dialog.signals.count())
                if dialog.signals.item(i).text().startswith('Temperature')))
            pending.append((extra, paths[0].parent))
            started = time.perf_counter()
            dialog.open_files()
            report['overlay_open_return_seconds'] = time.perf_counter() - started
            wait_until(entered.is_set)
            assert report['overlay_open_return_seconds'] < 1
            baseline = len(ticks)
            wait_until(lambda: len(ticks) >= baseline + 10)
            assert not release.is_set() and not dialog.apply_button.isEnabled()
            release.set()
            wait_until(lambda: dialog.file_job is None)
            assert len(dialog.datasets) == 2
            assert dialog.files.item(0).checkState() == Qt.CheckState.Checked
            assert dialog.files.item(1).checkState() == Qt.CheckState.Unchecked
            assert dialog.signals.currentItem().text().startswith('Temperature')
            dialog.files.item(1).setCheckState(Qt.CheckState.Checked)
            wanted = original_curve.dataset.signals[original_curve.y_index].label
            dialog.signals.setCurrentRow(next(i for i in range(dialog.signals.count())
                if dialog.signals.item(i).text() == wanted))
            dialog.accept()
            return dialog.result()
        dialogs.AddCurvesDialog.exec = choose_curves
        parent.add_curves()
        parent.accept()
        assert parent.result() == QDialog.DialogCode.Accepted, parent.error.text()
        assert len(window.visible_curves()) == 2
        assert window._last_data_directory == str(folder.absolute())
        image = output.with_suffix('.overlay.png')
        window.write_plot(image)
        assert image.stat().st_size > 500
        report['checks'].append('real_overlay_add_and_export_uses_background_reader_and_shared_recent_folder')
        report['checks'].append('gui_heartbeat_while_read_blocked_manual_signal_and_checks_preserved')

        release.clear(); entered.clear()
        pending.append((cancelled, folder.absolute()))
        old = dialogs.AddCurvesDialog(window, window.curves, 0, empty_selection=True)
        old.show(); old.open_files(); wait_until(entered.is_set)
        thread = old.file_job.worker_thread
        started = time.perf_counter(); old.close()
        report['overlay_close_return_seconds'] = time.perf_counter() - started
        assert report['overlay_close_return_seconds'] < .5 and thread.is_alive()
        old.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not isValid(old)
        pending.append((following, folder.absolute()))
        fresh = dialogs.AddCurvesDialog(window, window.curves, 0, empty_selection=True)
        fresh.show(); fresh.open_files()
        wait_until(lambda: fresh.file_job is None)
        assert len(fresh.datasets) == 3 and not release.is_set()
        release.set(); wait_until(lambda: not thread.is_alive())
        QApplication.processEvents()
        assert len(fresh.datasets) == 3 and len(window.visible_curves()) == 2
        fresh.reject()
        report['checks'].append('closed_dialog_deleted_during_slow_io_next_dialog_loads_late_result_ignored')
        assert workers and all(t != threading.get_ident() for t in workers)
        assert (original_curve.dataset.values == original_values).all()
        assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in before.items())
        report['checks'].append('reader_never_on_gui_thread_original_arrays_and_source_files_unchanged')
        assert not pending
        report.update(status='passed', gui_heartbeats=len(ticks), source_sha256=before)
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        release.set(); timer.stop()
        picker.DataFileDialog.exec = original_picker
        dialogs.AddCurvesDialog.exec = original_exec
        dialogs.read_dataset = original_reader
        window.dirty = False; window.close()
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if report['status'] != 'passed':
        raise SystemExit(1)
