"""Nonmodal, automatically processing four-column batch result table."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import threading
import queue
import uuid

from PySide6.QtCore import QObject, Qt, Signal, Slot, QTimer, QSignalBlocker
from PySide6.QtWidgets import (QApplication, QAbstractItemView, QComboBox, QDialog, QFileDialog,
    QHeaderView, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout)

from . import batch_analysis as backend
from .path_settings import import_folder, mass_source
from .theme import app_icon
from .batch_jobs import run_batch_job
from .batch_table import ResultsTable
from .diagnostics import record_event


class BatchJob(QObject):
    row_ready = Signal(str, object)
    finished = Signal()

    def __init__(self, action, requests, source="", directory=""):
        super().__init__()
        self.action, self.requests, self.source = action, requests, source
        self.directory = directory
        self.cancelled = threading.Event()
        self.events = queue.Queue()
        self.timer = QTimer(self)
        self.timer.setInterval(25)
        self.timer.timeout.connect(self.drain)

    def start(self):
        # The worker target is a module function with plain arguments. It has
        # no reference to this QObject and never calls the Qt bindings.
        self.worker_thread = threading.Thread(target=run_batch_job,
            args=(self.action, self.requests, self.source, self.directory, self.cancelled, self.events),
            name="TMA-batch-" + self.action, daemon=True)
        self.timer.start()
        self.worker_thread.start()

    @Slot()
    def drain(self):
        # Limit each GUI turn so a large batch cannot starve painting/input.
        for _ in range(32):
            try: kind, key, value = self.events.get_nowait()
            except queue.Empty: return
            if kind == 'row': self.row_ready.emit(key, value)
            else:
                self.timer.stop(); self.finished.emit(); return


class BatchDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        if not hasattr(owner,'_batch_session_rows'):owner._batch_session_rows=[]
        self.rows = owner._batch_session_rows
        self.view_rows = []
        self.latest_batch_id = None
        self.view_mode = "latest"
        self.job = None
        self.export_job = None
        self._shutdown = False
        self._export_completed = set()
        self._export_total = 0
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
        self.hint = QLabel("导入即计算 · V233 算法 · 批次仅保留到本次应用关闭\n先显示全部 T1 / T2 / H，再匹配 M（mg）；M 未匹配时留空，已算出的结果仍可出图、导出和复制。")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        filters = QHBoxLayout()
        self.latest_button = QPushButton("本次导入")
        self.all_button = QPushButton("本次运行全部")
        self.issue_button = QPushButton("仅看异常")
        for button in (self.latest_button, self.all_button, self.issue_button):
            button.setCheckable(True)
            button.setAutoDefault(False)
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
        self.table = ResultsTable(self)
        self.table.setObjectName("BatchResultsTable")
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
        self.table.selectionModel().selectionChanged.connect(self.selection_changed)
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
            ("云盘导入…", "CloudBatch", lambda: self.owner.show_cloud(target="batch")),
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
        if self.rows:
            self.latest_batch_id = self.rows[-1]["batch_id"]
        self.update_batch_filter()
        self.refresh_view()
        self.update_buttons()

    def choose_files(self):
        from .data_file_dialog import get_data_files
        paths, _ = get_data_files(self, "批量导入 TMA 文件",
            "TMA 数据 (*.0?? *.1?? *.2?? *.3?? *.4?? *.5?? *.6?? *.7?? *.8?? *.9??);;所有文件 (*)",owner=self.owner)
        if paths:
            self.enqueue_files(paths)

    def use_opened(self):
        datasets = {}
        for curve in self.owner.curves:
            datasets.setdefault(curve.dataset.document_key, curve.dataset)
        self.enqueue_files([ds.path for ds in datasets.values()])

    def enqueue_files(self, paths):
        if self._shutdown:return
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
        blocker = QSignalBlocker(self.table.selectionModel())
        self.table.result_model.set_rows(rows)
        del blocker
        self.latest_button.setChecked(self.view_mode == "latest")
        self.all_button.setChecked(self.view_mode == "all")
        self.count_label.setText(f"{len(rows)} / {len(self.rows)} 条")
        self.update_buttons()

    def start_pending(self):
        if self._shutdown or self.job is not None:
            return
        pending = [row for row in self.rows if row["state"] == "排队中"]
        if not pending:
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
        job.row_ready.connect(self.row_ready, Qt.ConnectionType.QueuedConnection)
        job.finished.connect(self.job_finished, Qt.ConnectionType.QueuedConnection)
        self.update_progress()
        self.update_buttons()
        job.start()

    def start_export_job(self,job):
        if self._shutdown or self.export_job is not None:return
        self.export_job=job
        self._export_total=len(job.requests)
        self._export_completed=set()
        job.row_ready.connect(self.row_ready, Qt.ConnectionType.QueuedConnection)
        job.finished.connect(self.job_finished, Qt.ConnectionType.QueuedConnection)
        self.update_progress();self.update_buttons()
        job.start()

    def update_progress(self):
        if self.export_job is not None:
            total,done=self._export_total,len(self._export_completed)
        elif self.job is not None:
            total,done=self._job_total,len(self._job_completed)
        else:self.progress.hide();return
        if self.export_job is not None:self.progress.setFormat("导出 %v / %m")
        elif done == total:self.progress.setFormat("已计算 %v / %m · 正在匹配 M")
        else:self.progress.setFormat("已计算 %v / %m")
        self.progress.setRange(0,total);self.progress.setValue(done);self.progress.show()

    @Slot(str, object)
    def row_ready(self, key, result):
        job=self.sender()
        if self._shutdown or job not in (self.job,self.export_job) or job is None or job.cancelled.is_set():
            return
        if job.action == "xlsx":
            if result.get('xlsx') and key not in self._export_completed:
                from .achievement_ui import record
                record(self.owner, 'tables')
            self.feedback.setText("XLSX 已保存：" + result["xlsx"] if "xlsx" in result else "导出失败：" + result.get("export_error", ""))
            self._export_completed.add(key)
        else:
            index = next((i for i, row in enumerate(self.rows) if row["id"] == key), None)
            if index is None:
                return
            from .achievement_ui import record
            if job.action == 'plot' and result.get('png') and not result.get('export_error') and key not in self._export_completed:
                record(self.owner, 'images')
            if job.action == 'calculate' and all(result.get(k) is not None for k in ('T1','T2','H')) and not result.get('error') and key not in self._job_completed:
                record(self.owner, 'batch')
            self.rows[index].update(result)
            if self.issue_button.isChecked():
                self.refresh_view()
            else:
                visible = next((i for i, row in enumerate(self.view_rows) if row["id"] == key), None)
                if visible is not None:
                    self.render_row(visible)
            if job.action == "plot":self._export_completed.add(key)
            elif result.get("T1") is not None or result.get("error"):self._job_completed.add(key)
        self.update_progress();self.update_buttons()
        record_event('batch.gui.row', row=key, action=job.action)

    @Slot()
    def job_finished(self):
        job=self.sender()
        if job is None or job not in (self.job,self.export_job):return
        if job is self.export_job:
            self.export_job=None
            if job.action == "plot":
                keys = {key for key, _ in job.requests}
                failed = sum(bool(row.get("export_error")) for row in self.rows if row["id"] in keys)
                self.feedback.setText(f"出图完成：{len(self._export_completed)-failed} 张；失败 {failed} 张。" if not job.cancelled.is_set() else "已取消出图。")
        elif job is self.job:
            self.job=None
            if not self._shutdown:
                failed = sum(bool(row.get("error")) for row in self.rows)
                missing = sum(row.get("state") == "M 未匹配" for row in self.rows)
                self.feedback.setText(f"本次运行共 {len(self.rows)} 个文件；读取失败 {failed} 个；M 未匹配 {missing} 个。未选中行时处理当前筛选结果；关闭应用后清空批次。")
        else:return
        job.deleteLater()
        self.start_pending()
        self.update_progress();self.update_buttons()

    def render_row(self, index):
        self.table.result_model.refresh_row(index)

    def selected_rows(self):
        indices = sorted({item.row() for item in self.table.selectedIndexes() if 0 <= item.row() < len(self.view_rows)})
        return [self.view_rows[i] for i in indices] if indices else list(self.view_rows)

    def selection_changed(self):
        self.update_buttons()
        indices = sorted({item.row() for item in self.table.selectedIndexes()})
        if not indices:
            return
        if indices[0] >= len(self.view_rows):
            return
        row = self.view_rows[indices[0]]
        self.feedback.setText(f"已选 {len(indices)} 行 · {row['name']} · {row['state']}" +
                              ("\n" + str(row.get("error") or row.get("warning") or row.get("png") or row["file"])))

    def update_buttons(self):
        if not hasattr(self,'ExportBatchPlots'):return
        rows=self.exportable_rows()
        ready=bool(rows) and not self._shutdown
        self.CopyBatch.setEnabled(ready)
        self.ExportBatchXlsx.setEnabled(ready and self.export_job is None)
        self.ExportBatchPlots.setEnabled(any(r.get('T1') is not None and not r.get('error') for r in rows) and not self._shutdown and self.export_job is None)
        self.CancelBatch.setEnabled(not self._shutdown and (self.job is not None or self.export_job is not None))

    def exportable_rows(self):
        return [row for row in self.selected_rows() if row.get('T1') is not None or row.get('error')]

    def copy_selection(self):
        if self._shutdown:return
        rows = self.exportable_rows()
        if rows:
            QApplication.clipboard().setText(backend.table_text(rows))
            from .achievement_ui import record
            record(self.owner, 'tables')
            self.feedback.setText(f"已复制 {len(rows)} 行 × 4 列（含表头），可直接粘贴到 Excel / WPS。未匹配的 M 留空，尚未计算的行暂不包含。")

    def export_xlsx(self):
        if self._shutdown or self.export_job is not None or not self.exportable_rows():
            return
        rows=deepcopy(backend.history_snapshot(self.exportable_rows()))
        path, _ = QFileDialog.getSaveFileName(self, "导出批量结果", "TMA批量结果.xlsx", "Excel 工作簿 (*.xlsx)")
        if path:
            if not path.lower().endswith(".xlsx"):
                path += ".xlsx"
            self.start_export_job(BatchJob("xlsx", [("xlsx", (rows, path))]))

    def export_plots(self):
        if self._shutdown or self.export_job is not None:
            return
        rows = [dict(row) for row in self.exportable_rows() if row.get("T1") is not None and not row.get("error")]
        if not rows:
            self.feedback.setText("所选行没有可出图的结果。")
            return
        directory = QFileDialog.getExistingDirectory(self, "选择图片输出文件夹", import_folder())
        if directory:
            # Name reservation/filesystem access stays on the worker as well.
            self.start_plot_job(rows, directory)

    def start_plot_job(self, rows, directory):
        keys={row['id'] for row in rows}
        for row in self.rows:
            if row['id'] in keys:row.pop("export_error",None)
        self.start_export_job(BatchJob("plot", [(row["id"], dict(row)) for row in rows], directory=directory))

    def cancel_processing(self):
        for job in (self.job,self.export_job):
            if job is not None:job.cancelled.set()
        for row in self.rows:
            if row["state"] in ("排队中", "计算中", "匹配 M…"):
                row["state"] = "已取消"
        self.refresh_view()
        self.feedback.setText("已取消，已完成结果保留；正在进行的文件读取返回后停止。")

    def prepare_shutdown(self):
        self._shutdown=True
        self.cancel_processing()
        self.rows.clear();self.latest_batch_id=None
        self.update_batch_filter();self.refresh_view()

    def reject(self):
        self.cancel_processing()
        super().reject()

    def closeEvent(self, event):
        self.cancel_processing()
        super().closeEvent(event)
