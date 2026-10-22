"""Nonmodal, automatically processing four-column batch result table."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import threading
import uuid

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (QApplication, QAbstractItemView, QComboBox, QDialog, QFileDialog,
    QHeaderView, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout)

from . import batch_analysis as backend
from .path_settings import import_folder, mass_source
from .theme import app_icon


class BatchJob(QObject):
    row_ready = Signal(str, object)
    finished = Signal()

    def __init__(self, action, requests, source=""):
        super().__init__()
        self.action, self.requests, self.source = action, requests, source
        self.cancelled = threading.Event()

    def start(self):
        # A daemon prevents a stalled network share from blocking application exit.
        # Only signals cross into Qt; this thread never reads or edits widgets.
        self.thread = threading.Thread(target=self.run, name="TMA-batch-" + self.action, daemon=True)
        self.thread.start()

    def emit_result(self, key, result):
        try:
            self.row_ready.emit(key, result)
        except RuntimeError:
            self.cancelled.set()  # Qt has already shut down.

    def run(self):
        try:
            for key, request in self.requests:
                if self.cancelled.is_set():
                    break
                try:
                    if self.action == "calculate":
                        result = backend.calculate_file(request)
                        self.emit_result(key, result)
                        if not self.cancelled.is_set():
                            self.emit_result(key, backend.match_mass(result, self.source))
                    elif self.action == "plot":
                        row, path = request
                        self.emit_result(key, {"png": backend.write_plot(row, path), "export_error": ""})
                    elif self.action == "xlsx":
                        rows, path = request
                        self.emit_result(key, {"xlsx": backend.write_xlsx(rows, path)})
                    elif self.action == "history":
                        self.emit_result(key, {"history": backend.save_history(request)})
                except Exception as exc:
                    self.emit_result(key, {"export_error": str(exc)})
        finally:
            try:
                self.finished.emit()
            except RuntimeError:
                pass


class ResultsTable(QTableWidget):
    copy_requested = Signal()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_requested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class BatchDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.rows = []
        self.view_rows = []
        self.latest_batch_id = None
        self.history_dirty = False
        self.view_mode = "latest"
        self.job = None
        self._job_total = 0
        self._job_completed = set()
        self.setObjectName("BatchAnalysisDialog")
        self.setWindowTitle("批量处理 · T1 / T2 / M / H")
        self.setWindowIcon(app_icon())
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self.resize(940, 570)
        self.setMinimumSize(760, 450)
        layout = QVBoxLayout(self)
        self.hint = QLabel("导入即计算 · V233 算法\n温度单位 °C；M 单位 mg；H 单位 µm。M 使用「设置 → 数据路径 → m」，未匹配则留空。")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        filters = QHBoxLayout()
        self.latest_button = QPushButton("本次导入")
        self.all_button = QPushButton("全部记录")
        self.issue_button = QPushButton("仅看异常")
        for button in (self.latest_button, self.all_button, self.issue_button):
            button.setCheckable(True)
            button.setFixedHeight(27)
            filters.addWidget(button)
        self.latest_button.setObjectName("BatchLatest")
        self.all_button.setObjectName("BatchAll")
        self.issue_button.setObjectName("BatchIssues")
        self.latest_button.clicked.connect(self.show_latest)
        self.all_button.clicked.connect(self.show_all)
        self.issue_button.toggled.connect(self.refresh_view)
        filters.addSpacing(8)
        filters.addWidget(QLabel("导入批次"))
        self.batch_filter = QComboBox()
        self.batch_filter.setObjectName("BatchFilter")
        self.batch_filter.currentIndexChanged.connect(self.filter_changed)
        filters.addWidget(self.batch_filter, 1)
        self.count_label = QLabel("0 条")
        filters.addWidget(self.count_label)
        layout.addLayout(filters)
        self.table = ResultsTable(0, 4)
        self.table.setObjectName("BatchResultsTable")
        self.table.setHorizontalHeaderLabels(backend.HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.verticalHeader().setFixedWidth(260)
        self.table.verticalHeader().setStyleSheet("QHeaderView { background: #fcf7fd; }")
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.copy_requested.connect(self.copy_selection)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        layout.addWidget(self.table, 1)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(16)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.feedback = QLabel("选择多个文件后自动读取，无需再点开始。文件名在左侧行标识，单击行可查看状态。")
        self.feedback.setMinimumHeight(35)
        self.feedback.setWordWrap(True)
        self.feedback.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.feedback)
        buttons = QHBoxLayout()
        for caption, name, callback in (
            ("导入文件…", "ImportBatch", self.choose_files),
            ("读取已打开文件", "UseOpened", self.use_opened),
            ("出图…", "ExportBatchPlots", self.export_plots),
            ("导出 XLSX…", "ExportBatchXlsx", self.export_xlsx),
            ("复制到 Excel", "CopyBatch", self.copy_selection),
            ("取消处理", "CancelBatch", self.cancel_processing),
            ("关闭", "CloseBatch", self.reject),
        ):
            button = QPushButton(caption)
            button.setObjectName(name)
            button.clicked.connect(callback)
            buttons.addWidget(button)
            setattr(self, name, button)
        layout.addLayout(buttons)
        try:
            self.rows = backend.load_history()
        except (OSError, ValueError) as exc:
            self.feedback.setText(f"历史记录未载入：{exc}")
        if self.rows:
            self.latest_batch_id = self.rows[-1]["batch_id"]
        self.update_batch_filter()
        self.refresh_view()
        self.update_buttons()

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "批量导入 TMA 文件", import_folder(),
            "TMA 数据 (*.0?? *.1?? *.2?? *.3?? *.4?? *.5?? *.6?? *.7?? *.8?? *.9??);;所有文件 (*)")
        if paths:
            self.enqueue_files(paths)

    def use_opened(self):
        datasets = {}
        for curve in self.owner.curves:
            datasets.setdefault(curve.dataset.document_key, curve.dataset)
        self.enqueue_files([ds.path for ds in datasets.values()])

    def enqueue_files(self, paths):
        paths = [str(Path(path).resolve()) for path in paths]
        if not paths:
            self.feedback.setText("请先导入文件。")
            return
        try:
            source = mass_source()
        except (OSError, ValueError) as exc:
            self.feedback.setText(f"m 路径配置未读取：{exc}")
            source = ""
        stamp = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
        batch_id = uuid.uuid4().hex
        number = len({row["batch_id"] for row in self.rows}) + 1
        batch_label = f"第 {number} 批 · {stamp[:19].replace('T', ' ')} · {len(paths)} 个文件"
        self.latest_batch_id = batch_id
        for path in paths:
            row = dict(id=uuid.uuid4().hex, file=path, name=Path(path).name,
                       state="排队中", mass_config=source, error="", warning="",
                       batch_id=batch_id, batch_label=batch_label, imported_at=stamp)
            self.rows.append(row)
        self.history_dirty = True
        self.update_batch_filter()
        self.show_latest()
        self.feedback.setText(f"已加入 {len(paths)} 个文件，按导入顺序处理；可继续追加文件。")
        self.start_pending()

    def update_batch_filter(self):
        previous = self.batch_filter.currentData()
        self.batch_filter.blockSignals(True)
        self.batch_filter.clear()
        self.batch_filter.addItem("全部批次", None)
        batches = {}
        for row in self.rows:
            batches.setdefault(row["batch_id"], row["batch_label"])
        for key, label in reversed(list(batches.items())):
            self.batch_filter.addItem(label, key)
        index = self.batch_filter.findData(previous)
        self.batch_filter.setCurrentIndex(max(0, index))
        self.batch_filter.blockSignals(False)

    def show_latest(self):
        self.view_mode = "latest"
        self.batch_filter.blockSignals(True)
        self.batch_filter.setCurrentIndex(max(0, self.batch_filter.findData(self.latest_batch_id)))
        self.batch_filter.blockSignals(False)
        self.issue_button.setChecked(False)
        self.refresh_view()

    def show_all(self):
        self.view_mode = "all"
        self.batch_filter.blockSignals(True)
        self.batch_filter.setCurrentIndex(0)
        self.batch_filter.blockSignals(False)
        self.issue_button.setChecked(False)
        self.refresh_view()

    def filter_changed(self):
        self.view_mode = "filter" if self.batch_filter.currentData() else "all"
        self.refresh_view()

    def refresh_view(self):
        key = self.latest_batch_id if self.view_mode == "latest" else self.batch_filter.currentData()
        rows = [row for row in self.rows if key is None or row["batch_id"] == key]
        if self.issue_button.isChecked():
            rows = [row for row in rows if row.get("error") or row.get("warning") or row.get("export_error") or row["state"] in ("未完成", "已取消")]
        self.view_rows = rows
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        for index in range(len(rows)):
            self.render_row(index)
        self.latest_button.setChecked(self.view_mode == "latest")
        self.all_button.setChecked(self.view_mode == "all")
        self.count_label.setText(f"{len(rows)} / {len(self.rows)} 条")
        self.update_buttons()

    def start_pending(self):
        if self.job is not None:
            return
        pending = [row for row in self.rows if row["state"] == "排队中"]
        if not pending:
            if self.history_dirty:
                self.history_dirty = False
                self.start_job(BatchJob("history", [("history", backend.history_snapshot(self.rows))]))
                return
            self.update_buttons()
            return
        # Separate queues when the weighing source changes between imports.
        source = pending[0]["mass_config"]
        pending = [row for row in pending if row["mass_config"] == source]
        for row in pending:
            row["state"] = "计算中"
        self.start_job(BatchJob("calculate", [(row["id"], row["file"]) for row in pending], source))

    def start_job(self, job):
        self.job = job
        self._job_total = len(job.requests)
        self._job_completed = set()
        job.row_ready.connect(self.row_ready)
        job.finished.connect(self.job_finished)
        self.progress.setRange(0, self._job_total)
        self.progress.setValue(0)
        self.progress.show()
        self.update_buttons()
        job.start()

    @Slot(str, object)
    def row_ready(self, key, result):
        if self.job is None or self.job.cancelled.is_set():
            return
        if self.job.action == "history":
            if result.get("export_error"):
                self.feedback.setText("历史记录未保存：" + result["export_error"])
        elif self.job.action == "xlsx":
            self.feedback.setText("XLSX 已保存：" + result["xlsx"] if "xlsx" in result else "导出失败：" + result.get("export_error", ""))
            self._job_completed.add(key)
        else:
            index = next((i for i, row in enumerate(self.rows) if row["id"] == key), None)
            if index is None:
                return
            self.rows[index].update(result)
            self.history_dirty = True
            if self.issue_button.isChecked():
                self.refresh_view()
            else:
                visible = next((i for i, row in enumerate(self.view_rows) if row["id"] == key), None)
                if visible is not None:
                    self.render_row(visible)
            if self.job.action == "plot" or result.get("state") in ("完成", "M 未匹配", "读取失败"):
                self._job_completed.add(key)
        self.progress.setValue(len(self._job_completed))

    @Slot()
    def job_finished(self):
        job = self.job
        self.job = None
        if job is not None:
            if job.action == "plot":
                keys = {key for key, _ in job.requests}
                failed = sum(bool(row.get("export_error")) for row in self.rows if row["id"] in keys)
                self.feedback.setText(f"出图完成：{len(self._job_completed)-failed} 张；失败 {failed} 张。" if not job.cancelled.is_set() else "已取消出图。")
            elif job.action == "calculate":
                failed = sum(bool(row.get("error")) for row in self.rows)
                missing = sum(row.get("state") == "M 未匹配" for row in self.rows)
                self.feedback.setText(f"历史共 {len(self.rows)} 个文件；读取失败 {failed} 个；M 未匹配 {missing} 个。未选中行时，出图/导出/复制仅处理当前筛选结果。")
            job.deleteLater()
        self.progress.hide()
        self.start_pending()
        self.update_buttons()

    def render_row(self, index):
        row = self.view_rows[index]
        tooltip = f"{row['batch_label']}\n{row['file']}\n{row['state']}"
        for key in ("error", "warning", "mass_source", "export_error", "png"):
            if row.get(key):
                tooltip += "\n" + str(row[key])
        header = QTableWidgetItem(f"{index+1}  {row['name']}")
        header.setToolTip(tooltip)
        if row.get("error"):
            header.setForeground(QColor("#ad526c"))
        self.table.setVerticalHeaderItem(index, header)
        for column, key in enumerate(backend.KEYS):
            item = QTableWidgetItem(backend.display_value(row, key))
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item.setToolTip(tooltip)
            if row.get("error") or (key == "M" and row.get("warning")):
                item.setBackground(QColor("#fff0e6"))
            self.table.setItem(index, column, item)

    def selected_rows(self):
        indices = sorted({item.row() for item in self.table.selectedIndexes()})
        return [self.view_rows[i] for i in indices] if indices else list(self.view_rows)

    def selection_changed(self):
        indices = sorted({item.row() for item in self.table.selectedIndexes()})
        if not indices:
            return
        if indices[0] >= len(self.view_rows):
            return
        row = self.view_rows[indices[0]]
        self.feedback.setText(f"已选 {len(indices)} 行 · {row['name']} · {row['state']}" +
                              ("\n" + str(row.get("error") or row.get("warning") or row.get("png") or row["file"])))

    def update_buttons(self):
        ready = bool(self.view_rows) and self.job is None
        for button in (self.ExportBatchPlots, self.ExportBatchXlsx, self.CopyBatch):
            button.setEnabled(ready)
        self.CancelBatch.setEnabled(self.job is not None)

    def copy_selection(self):
        if self.job is not None:
            return
        rows = self.selected_rows()
        if rows:
            QApplication.clipboard().setText(backend.table_text(rows))
            self.feedback.setText(f"已复制 {len(rows)} 行 × 4 列（含表头），可直接粘贴到 Excel / WPS。")

    def export_xlsx(self):
        if self.job is not None or not self.rows:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出批量结果", "TMA批量结果.xlsx", "Excel 工作簿 (*.xlsx)")
        if path:
            if not path.lower().endswith(".xlsx"):
                path += ".xlsx"
            self.start_job(BatchJob("xlsx", [("xlsx", (deepcopy(self.selected_rows()), path))]))

    def export_plots(self):
        if self.job is not None:
            return
        rows = [row for row in self.selected_rows() if row.get("T1") is not None and not row.get("error")]
        if not rows:
            self.feedback.setText("所选行没有可出图的结果。")
            return
        directory = QFileDialog.getExistingDirectory(self, "选择图片输出文件夹", import_folder())
        if directory:
            # Name reservation/filesystem access stays on the worker as well.
            self.start_plot_job(rows, directory)

    def start_plot_job(self, rows, directory):
        # Existence checks on a user-selected output share run in the background.
        class PlotJob(BatchJob):
            def run(job):
                try:
                    paths = backend.plot_paths(rows, directory)
                    job.requests = [(row["id"], (dict(row), path)) for row, path in zip(rows, paths)]
                except Exception as exc:
                    for row in rows:
                        job.emit_result(row["id"], {"export_error": str(exc)})
                    job.finished.emit()
                    return
                super().run()
        for row in rows:
            row.pop("export_error", None)
        self.start_job(PlotJob("plot", [(row["id"], None) for row in rows]))

    def cancel_processing(self):
        if self.job is not None:
            self.job.cancelled.set()
        for row in self.rows:
            if row["state"] in ("排队中", "计算中", "匹配 M…"):
                row["state"] = "已取消"
                self.history_dirty = True
        self.refresh_view()
        self.feedback.setText("已取消，已完成结果保留；正在进行的文件读取返回后停止。")

    def prepare_shutdown(self):
        self.cancel_processing()
        try:
            backend.save_history(self.rows)
        except (OSError, ValueError):
            pass

    def reject(self):
        self.cancel_processing()
        super().reject()

    def closeEvent(self, event):
        self.cancel_processing()
        super().closeEvent(event)
