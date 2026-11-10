"""Offline EXE checks: imports and exports while preferences are unavailable."""
import csv
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import threading
import time
import traceback

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFileDialog

from . import __version__, notifications, path_settings
from .batch_qa import wait_until


def verify(window, output, paths):
    from openpyxl import Workbook, load_workbook
    from PIL import Image
    output = output.absolute(); output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'failed', 'version': __version__, 'checks': []}
    read, notify = path_settings._read_settings, notifications.notify
    choose_file, choose_folder = QFileDialog.getSaveFileName, QFileDialog.getExistingDirectory
    previous_mass = os.environ.pop('TMA_MASS_XLSX', None)
    entered, release = threading.Event(), threading.Event()
    calls, ticks, sends = [], [], []
    timer = QTimer(); timer.timeout.connect(lambda: ticks.append(1)); timer.start(5)
    def paused(*args, **kwargs):
        calls.append(threading.get_ident())
        assert threading.current_thread() is not threading.main_thread()
        entered.set(); assert release.wait(25)
        return read(*args, **kwargs)
    try:
        wait_until(lambda: not window._startup_services_pending)
        sources = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        weights = output.with_suffix('.weights.xlsx')
        book = Workbook(); sheet = book.active; sheet.append(['样品名', 'M (mg)'])
        for index, path in enumerate(paths): sheet.append([path.stem, .47 + index * .01])
        book.save(weights); book.close(); original_weights = weights.read_bytes()
        path_settings._save_data({'paths': {'m': str(weights)}, 'ui': {'batch_popup': False},
                                 'notifications': {'enabled': False}})
        with path_settings._snapshot_lock:
            key = str(path_settings.config_path())
            path_settings._snapshots.pop(key, None); path_settings._refresh_checked.pop(key, None)
        path_settings._read_settings = paused
        notifications.notify = lambda *a, **k: sends.append(a)
        started = time.perf_counter(); window.import_files(paths)
        report['cold_import_return_seconds'] = time.perf_counter() - started
        assert report['cold_import_return_seconds'] < 1
        dialog = window.batch_dialog
        wait_until(lambda: window.worker is None and len(dialog.rows) == len(paths)
                   and all(row.get('T1') is not None for row in dialog.rows))
        wait_until(entered.is_set)
        baseline = len(ticks); wait_until(lambda: len(ticks) >= baseline + 8)
        assert len(window.curves) == len(paths) and dialog.job is not None and not dialog.isVisible()
        assert not sends and not release.is_set()
        report['checks'].append('cold_multi_import_and_all_numeric_results_finish_while_configuration_reads_stay_blocked_gui_alive')
        dialog.copy_selection()
        copied = list(csv.reader(StringIO(QApplication.clipboard().text()), delimiter='\t'))
        assert [row[0] for row in copied[1:]] == [path.stem for path in paths]
        assert all(len(row) == 5 for row in copied) and all(row[3] == '' for row in copied[1:])
        output.with_suffix('.clipboard.tsv').write_text(QApplication.clipboard().text(), encoding='utf-8-sig')
        target = output.with_suffix('.results.xlsx')
        target.unlink(missing_ok=True)
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(target), ''))
        dialog.export_xlsx(); wait_until(lambda: dialog.export_job is None)
        book = load_workbook(target, data_only=True)
        try:
            assert abs(book.active.cell(2, 1).value - dialog.rows[0]['T1']) < 1e-9
            assert book.active.cell(2, 3).value is None
        finally:
            book.close()
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(weights), ''))
        dialog.export_xlsx(); wait_until(lambda: dialog.export_job is None)
        assert '新文件名' in dialog.feedback.text() and weights.read_bytes() == original_weights
        folder = output.parent / 'cold-exports'; folder.mkdir(exist_ok=True)
        QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(folder))
        dialog.export_plots(); wait_until(lambda: dialog.export_job is None)
        assert all(row.get('png') for row in dialog.rows) and not release.is_set()
        for row in dialog.rows:
            with Image.open(row['png']) as image:
                assert image.info['Author'] == 'Power By ZzzHe'
                assert image.convert('RGB').getpixel((0, 0)) == (255, 255, 255)
        assert all(thread != threading.get_ident() for thread in calls)
        report['checks'].append('five_column_copy_new_xlsx_and_png_exports_complete_before_configuration_returns_existing_weights_protected')
        release.set(); wait_until(lambda: dialog.job is None)
        wait_until(lambda: not window.deferred_preferences().notices and window.deferred_preferences().popup is None)
        assert all(abs(row['M'] - (.47 + index * .01)) < 1e-9 for index, row in enumerate(dialog.rows))
        assert all(row['mass_config'] == str(weights) for row in dialog.rows)
        assert not dialog.isVisible() and not sends and weights.read_bytes() == original_weights
        assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == value for path, value in sources.items())
        report['checks'].append('configured_hidden_popup_and_disabled_notifications_preserved_late_weights_match_original_rows_sources_unchanged')
        png = window._current_plot_png()
        target = output.with_suffix('.notice.png'); target.write_bytes(png)
        with Image.open(target) as image:
            assert image.info['Author'] == image.info['Software'] == 'Power By ZzzHe'
        report['checks'].append('notification_picture_renders_in_memory_with_export_credit')
        report.update(status='passed', gui_heartbeats=len(ticks), source_sha256=sources,
                      real_notification_sent=False)
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        release.set(); timer.stop()
        path_settings._read_settings, notifications.notify = read, notify
        QFileDialog.getSaveFileName, QFileDialog.getExistingDirectory = choose_file, choose_folder
        if previous_mass is not None: os.environ['TMA_MASS_XLSX'] = previous_mass
        window.close()
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if report['status'] != 'passed': raise SystemExit(1)
