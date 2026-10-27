"""A small, themed, nonmodal window for one-sample PDF reports."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import threading

from PySide6.QtCore import QObject, Qt, Signal, Slot, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QVBoxLayout, QWidget)

from .path_settings import import_folder, mass_source, particle_folder
from .theme import app_icon


class ReportJob(QObject):
    completed = Signal(object)
    progress = Signal(str)

    def __init__(self, action, request, data=None, parts=("tma", "particle"), force_internal=False):
        super().__init__()
        self.action, self.request, self.data = action, request, data
        self.parts, self.force_internal = parts, force_internal
        self.cancelled = threading.Event()

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True, name="TMA-single-report")
        self.thread.start()

    def notify(self, message):
        if not self.cancelled.is_set():
            try:
                self.progress.emit(message)
            except RuntimeError:
                self.cancelled.set()

    def run(self):
        backend = None
        try:
            from . import single_report as backend
            if self.action == "read":
                data = backend.read_sources(self.request["tma_path"], self.request["particle_path"], self.request["mass_source"],
                    algorithm=self.request["algorithm"], record_index=self.request["record_index"],
                    particle_revision=self.request.get("particle_revision"), progress=self.notify, parts=self.parts)
                result = dict(kind="read", data=data, parts=self.parts)
            elif self.action == "recommend":
                from .particle_recommendation import recommend
                data = recommend(self.request["sample"], self.request["folder"], cancelled=self.cancelled, progress=self.notify)
                result = dict(kind="recommended", data=data)
            else:
                result = dict(kind="generated", result=backend.generate_report(self.request, self.data,
                    force_internal=self.force_internal, progress=self.notify, cancelled=self.cancelled))
        except Exception as exc:
            result = dict(kind="template_error" if backend is not None and isinstance(exc, backend.TemplateError) else "error", error=str(exc))
        if not self.cancelled.is_set():
            try:
                self.completed.emit(result)
            except RuntimeError:
                pass
        else:
            try:
                self.completed.emit({"kind": "cancelled"})
            except RuntimeError:
                pass


class SingleReportDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.job = None
        self.data = dict(fields={}, tma=None, particle=None, errors=[], warnings=[])
        self.last_output = ""
        self._temperature_edited = False
        self.setObjectName("SingleReportDialog")
        self.setWindowTitle("单样品报告 · ZzzHe TMA Analysis")
        self.setWindowIcon(app_icon())
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self.resize(860, 660)
        self.setMinimumSize(790, 620)
        layout = QVBoxLayout(self)
        heading = QLabel("单样品报告")
        heading.setStyleSheet("font-size: 17px; color: #795982;")
        layout.addWidget(heading)
        hint = QLabel("默认生成内部版三页 PDF。模板栏留空即可；选择模板后按模板填充，异常时可选择内部版兜底。")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.inputs_group = QGroupBox("选择文件")
        files = QGridLayout(self.inputs_group)
        self.tma_path = self._path_row(files, 0, "TMA 文件", self.choose_tma, "ReportTmaPath")
        current = QPushButton("当前选中")
        current.setObjectName("ReportUseSelected")
        current.clicked.connect(self.use_selected)
        files.addWidget(current, 0, 3)
        self.particle_path = self._path_row(files, 1, "粒径文件", self.choose_particle, "ReportParticlePath")
        self.recommend_button = QPushButton("推荐数据")
        self.recommend_button.setObjectName("ReportRecommendParticle")
        self.recommend_button.clicked.connect(self.recommend_particle)
        files.addWidget(self.recommend_button, 1, 3)
        self.folder_hint = QLabel()
        self.folder_hint.setObjectName("muted")
        self.folder_hint.setTextFormat(Qt.TextFormat.PlainText)
        self.folder_hint.setWordWrap(True)
        files.addWidget(self.folder_hint, 2, 1, 1, 3)
        self.update_folder_hint()
        self.record_row = QWidget()
        record_layout = QHBoxLayout(self.record_row)
        record_layout.setContentsMargins(0, 0, 0, 0)
        record_layout.addWidget(QLabel("粒径记录"))
        self.record_box = QComboBox()
        self.record_box.setObjectName("ReportParticleRecord")
        self.record_box.currentIndexChanged.connect(self.record_changed)
        record_layout.addWidget(self.record_box, 1)
        files.addWidget(self.record_row, 3, 1, 1, 3)
        self.record_row.hide()
        self.template_path = self._path_row(files, 4, "PDF 模板", self.choose_template, "ReportTemplatePath", span=2)
        self.template_path.setPlaceholderText("可选，留空使用内部版（不自动查找模板）")
        self.template_path.setClearButtonEnabled(True)
        self.output_path = self._path_row(files, 5, "保存位置", self.choose_output, "ReportOutputPath", span=2)
        self.output_path.setPlaceholderText("选择输出 PDF 的位置")
        layout.addWidget(self.inputs_group)

        self.info_group = QGroupBox("报告信息 · 可核对和修改")
        fields_layout = QGridLayout(self.info_group)
        self.fields = {}
        self.fields["sample_name"] = QLineEdit()
        self.fields["sample_name"].setObjectName("ReportSampleName")
        fields_layout.addWidget(QLabel("编号 / 名称"), 0, 0)
        fields_layout.addWidget(self.fields["sample_name"], 0, 1, 1, 5)
        fields_layout.addWidget(QLabel("TMA 识别"), 1, 0)
        self.algorithm = QComboBox()
        self.algorithm.setObjectName("ReportAlgorithm")
        self.algorithm.addItem("原内部版默认", "auto")
        self.algorithm.addItem("超级梯度", "super")
        self.algorithm.currentIndexChanged.connect(self.algorithm_changed)
        fields_layout.addWidget(self.algorithm, 1, 1, 1, 2)
        method_hint = QLabel("M 从已配置称量表匹配；未匹配可手动填写。")
        method_hint.setObjectName("muted")
        fields_layout.addWidget(method_hint, 1, 3, 1, 3)
        for row, specs in ((2, (("T1", "T1 (°C)"), ("T2", "T2 (°C)"), ("M", "M (mg)"))),
                           (3, (("H", "H (µm)"), ("D50", "D50 (µm)"), ("SPAN", "SPAN")))):
            for column, (key, caption) in enumerate(specs):
                edit = self.fields[key] = QLineEdit()
                edit.setObjectName("Report" + key)
                fields_layout.addWidget(QLabel(caption), row, column*2)
                fields_layout.addWidget(edit, row, column*2+1)
        for key, caption, row, column, span in (("TMA", "TMA (kg/m³)", 4, 0, 1),
                ("tma_time", "TMA 时间", 4, 2, 3), ("particle_time", "粒径时间", 5, 0, 5)):
            edit = self.fields[key] = QLineEdit()
            edit.setObjectName("Report" + key)
            fields_layout.addWidget(QLabel(caption), row, column)
            fields_layout.addWidget(edit, row, column+1, 1, span)
        for column in (1, 3, 5):
            fields_layout.setColumnStretch(column, 1)
        self.fields["M"].textEdited.connect(self.update_density)
        self.fields["H"].textEdited.connect(self.update_density)
        self.fields["T1"].editingFinished.connect(self.update_height)
        self.fields["T2"].editingFinished.connect(self.update_height)
        self.fields["T1"].textEdited.connect(self.temperature_edited)
        self.fields["T2"].textEdited.connect(self.temperature_edited)
        layout.addWidget(self.info_group)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("ReportLog")
        self.log.setMaximumHeight(88)
        self.log.setPlaceholderText("选择文件后读取信息；生成前可核对编号、粒径和质量。")
        layout.addWidget(self.log, 1)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(14)
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        bottom = QHBoxLayout()
        self.status = QLabel("就绪 · 模板未选择时使用内部版")
        self.status.setObjectName("muted")
        bottom.addWidget(self.status, 1)
        self.read_button = QPushButton("读取信息")
        self.read_button.setObjectName("ReadSingleReport")
        self.read_button.clicked.connect(self.read_information)
        self.generate_button = QPushButton("生成 PDF")
        self.generate_button.setObjectName("primary")
        self.generate_button.clicked.connect(self.generate)
        self.open_button = QPushButton("打开报告")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_report)
        close = QPushButton("关闭")
        close.clicked.connect(self.reject)
        for button in (self.read_button, self.generate_button, self.open_button, close):
            button.setAutoDefault(False)
            bottom.addWidget(button)
        layout.addLayout(bottom)
        self.tma_path.textChanged.connect(lambda: self.source_changed("tma"))
        self.particle_path.textChanged.connect(lambda: self.source_changed("particle"))

    def _path_row(self, layout, row, caption, callback, name, span=1):
        layout.addWidget(QLabel(caption), row, 0)
        edit = QLineEdit()
        edit.setObjectName(name)
        layout.addWidget(edit, row, 1, 1, span)
        button = QPushButton("选择…")
        button.setObjectName(name + "Browse")
        button.clicked.connect(callback)
        if name != "ReportOutputPath":
            from PySide6.QtWidgets import QMenu
            menu = QMenu(button)
            menu.addAction("本地文件…", callback)
            def selected(path):
                edit.setText(path)
                if name == "ReportTmaPath": self.read_information(parts=("tma",))
                elif name == "ReportParticlePath": self.read_information(parts=("particle",))
            menu.addAction("云盘文件…", lambda: self.owner.show_cloud(selected_callback=selected))
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(lambda point: menu.exec(button.mapToGlobal(point)))
            button.setText("选择… ▾")
            # Left click opens the same clear local/cloud choices.
            button.clicked.disconnect(callback)
            button.clicked.connect(lambda: menu.exec(button.mapToGlobal(button.rect().bottomLeft())))
        layout.addWidget(button, row, 1+span)
        return edit

    def update_folder_hint(self):
        folder = particle_folder()
        self.folder_hint.setText("粒径默认目录：" + (folder or "未配置，可在设置中单独指定"))

    def choose_tma(self):
        from .data_file_dialog import get_data_files
        paths, _ = get_data_files(self, "选择单个 TMA 文件",
            "TMA 数据 (*.0?? *.1?? *.2?? *.3?? *.4?? *.5?? *.6?? *.7?? *.8?? *.9?? *.txt);;所有文件 (*)",owner=self.owner,multiple=False)
        path=paths[0] if paths else ''
        if path:
            self.tma_path.setText(path)
            self.read_information(parts=("tma", "particle") if self.particle_path.text().lower().endswith(".p9m") else ("tma",))

    def use_selected(self):
        curve = self.owner.selected()
        if curve is None:
            self.log.appendPlainText("主窗口尚未选中数据，请选择一个 TMA 文件。")
            return
        self.tma_path.setText(str(curve.dataset.path))
        self.read_information(parts=("tma", "particle") if self.particle_path.text().lower().endswith(".p9m") else ("tma",))

    def choose_particle(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择粒径文件", particle_folder(),
            "粒径文件 (*.p9m *.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp);;所有文件 (*)")
        if path:
            self.particle_path.setText(path)
            self.read_information(parts=("particle",))

    def recommend_particle(self):
        if self.job is not None: return
        sample = self.fields["sample_name"].text().strip() or Path(self.tma_path.text()).stem
        try:
            from .particle_recommendation import sample_date
            sample_date(sample)
            self.start_job(ReportJob("recommend", {"sample": sample, "folder": particle_folder()}))
        except (ValueError, OSError) as exc: self.log.appendPlainText(str(exc))

    def choose_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 PDF 模板（可留空）", "", "PDF 模板 (*.pdf)")
        if path:
            self.template_path.setText(path)

    def choose_output(self):
        source = self.tma_path.text().strip()
        default = self.output_path.text().strip() or (str(Path(source).with_name(Path(source).stem + "_报告.pdf")) if source else str(Path(import_folder() or Path.home()) / "单样品报告.pdf"))
        path, _ = QFileDialog.getSaveFileName(self, "保存单样品报告", default, "PDF 报告 (*.pdf)")
        if path:
            self.output_path.setText(path if path.lower().endswith(".pdf") else path + ".pdf")

    def source_changed(self, part):
        self.data[part] = None
        keys = ("T1", "T2", "M", "H", "TMA", "tma_time") if part == "tma" else ("D50", "SPAN", "particle_time")
        for key in keys:
            self.fields[key].clear()
        if part == "tma":
            path = self.tma_path.text().strip().strip('"')
            self.fields["sample_name"].setText(Path(path).stem if path else "")
            if self.particle_path.text().strip().lower().endswith(".p9m"):
                self.source_changed("particle")
        else:
            self.record_box.blockSignals(True)
            self.record_box.clear()
            self.record_box.blockSignals(False)
            self.record_row.hide()
        self.last_output = ""
        self.open_button.setEnabled(False)

    def algorithm_changed(self):
        self.data["tma"] = None
        for key in ("T1", "T2", "H", "TMA"):
            self.fields[key].clear()

    def request(self):
        particle = self.data.get("particle")
        return dict(tma_path=self.tma_path.text().strip().strip('"'), particle_path=self.particle_path.text().strip().strip('"'),
                    template_path=self.template_path.text().strip().strip('"'), output_path=self.output_path.text().strip().strip('"'),
                    mass_source=mass_source(), algorithm=self.algorithm.currentData(), record_index=self.record_box.currentData(),
                    particle_revision=particle.get("sha256") if particle and particle.get("records") else None,
                    fields={key: edit.text().strip() for key, edit in self.fields.items()})

    def record_changed(self):
        if self.job is not None: return
        if self.record_box.currentData() is not None:
            self.read_information(parts=("particle",))
        else:
            particle = self.data.get("particle")
            if particle and particle.get("records"):
                particle["selected_index"] = None
                particle["fields"] = {}
                for key in ("D50", "SPAN", "particle_time"):
                    self.fields[key].clear()
                    self.data.get("fields", {}).pop(key, None)
                self.last_output = ""
                self.open_button.setEnabled(False)
                self.status.setText("请选择测量记录")

    def restore_particle_selection(self):
        """An interrupted read never changes which loaded record is displayed."""
        particle = self.data.get("particle")
        if particle and particle.get("records"):
            self.record_box.blockSignals(True)
            self.record_box.setCurrentIndex(max(0, self.record_box.findData(particle["selected_index"])))
            self.record_box.blockSignals(False)

    def read_information(self, checked=False, *, parts=("tma", "particle")):
        if self.job is not None:
            return
        try:
            request = self.request()
            if not request["tma_path"] and not request["particle_path"]:
                raise ValueError("请先选择 TMA 或粒径文件")
            self.start_job(ReportJob("read", request, parts=parts))
        except (ValueError, OSError) as exc:
            self.log.appendPlainText(str(exc))

    def start_job(self, job):
        self.job = job
        job.progress.connect(self.show_progress)
        job.completed.connect(self.job_completed)
        self.inputs_group.setEnabled(False)
        self.info_group.setEnabled(False)
        self.read_button.setEnabled(False)
        self.generate_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.progress.show()
        self.status.setText("处理中…")
        job.start()

    @Slot(str)
    def show_progress(self, message):
        self.status.setText(message)
        self.log.appendPlainText(message)

    def apply_data(self, data, parts=("tma", "particle")):
        self.last_output = ""
        self.open_button.setEnabled(False)
        for key in parts:
            self.data[key] = data.get(key)
            # Clearing is required even when the path text did not change,
            # e.g. a new ambiguous recommendation for the same monthly file.
            keys = ("T1", "T2", "M", "H", "TMA", "tma_time") if key == "tma" else ("D50", "SPAN", "particle_time")
            for field in keys: self.fields[field].clear()
            if key == "tma": self._temperature_edited = False
        self.data["errors"] = []
        for key, value in data.get("fields", {}).items():
            if key in self.fields:
                self.fields[key].setText(str(value))
        self.data["fields"] = {key: edit.text() for key, edit in self.fields.items()}
        particle = self.data.get("particle")
        self.record_box.blockSignals(True)
        self.record_box.clear()
        if particle and particle["records"]:
            self.record_box.addItem("请选择测量记录", None)
            indices = particle.get("matched_indices") or list(range(len(particle["records"])))
            if particle["selected_index"] is not None and particle["selected_index"] not in indices:
                indices = [*indices, particle["selected_index"]]
            for index in indices:
                record = particle["records"][index]
                label = f"{record.record_id or index+1} · {record.sample_name or record.sample_no} · {record.measurement_time}"
                if record.is_average:
                    label += " · 平均"
                self.record_box.addItem(label, index)
            self.record_box.setCurrentIndex(max(0, self.record_box.findData(particle["selected_index"])))
            self.record_row.show()
        else:
            self.record_row.hide()
        self.record_box.blockSignals(False)

    @Slot(object)
    def job_completed(self, result):
        job = self.job
        self.job = None
        self.inputs_group.setEnabled(True)
        self.info_group.setEnabled(True)
        self.read_button.setEnabled(True)
        self.generate_button.setEnabled(True)
        self.open_button.setEnabled(bool(self.last_output))
        self.progress.hide()
        self.status.setText("就绪")
        if result["kind"] == "cancelled":
            if job.action == "read" and "particle" in job.parts: self.restore_particle_selection()
            self.status.setText("已取消")
        elif result["kind"] == "read":
            self.apply_data(result["data"], result["parts"])
            for message in result["data"]["errors"] + result["data"]["warnings"]:
                self.log.appendPlainText(message)
            self.log.appendPlainText("读取完成，请核对信息。")
        elif result["kind"] == "recommended":
            particle = result["data"]
            self.particle_path.setText(particle.get("recommended_path", particle["file"]))
            self.apply_data({"particle": particle, "fields": particle["fields"]}, ("particle",))
            self.log.appendPlainText("已推荐：" + particle["file"])
            if particle.get("warning"): self.log.appendPlainText(particle["warning"])
        elif result["kind"] == "error":
            if job.action == "read" and "particle" in job.parts: self.restore_particle_selection()
            self.log.appendPlainText(("未找到推荐数据：" if job.action == "recommend" else "操作未完成：") + result["error"])
            self.status.setText("请检查输入信息")
        elif result["kind"] == "generated":
            output = result["result"]
            self.apply_data({**output["data"], "fields": output["fields"]})
            self.last_output = output["path"]
            self.open_button.setEnabled(True)
            mode = "指定模板" if output["mode"] == "template" else "内部版三页报告"
            self.log.appendPlainText(f"已生成（{mode}）：{output['path']}")
            self.status.setText("报告已生成")
            from .achievement_ui import record
            record(self.owner, 'reports')
        elif result["kind"] == "template_error":
            self.log.appendPlainText("模板不可用：" + result["error"])
            answer = QMessageBox.question(self, "模板无法使用", result["error"] + "\n\n是否使用内部版三页报告作为兜底？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                self.start_job(ReportJob("generate", job.request, job.data, force_internal=True))
            else:
                self.status.setText("已取消，未使用兜底方式")
        if job is not None:
            job.deleteLater()

    def update_density(self):
        from . import single_report as backend
        try:
            self.fields["TMA"].setText(f"{backend.core.calc_tma_from_m_h(float(self.fields['M'].text()), float(self.fields['H'].text())):.3f}")
        except (ValueError, TypeError):
            self.fields["TMA"].clear()

    def update_height(self):
        if not self._temperature_edited:
            return
        self._temperature_edited = False
        data = self.data.get("tma")
        if data is None:
            return
        from . import single_report as backend
        try:
            t1, t2 = float(self.fields["T1"].text()), float(self.fields["T2"].text())
            if not min(data["xs"]) <= t1 < t2 <= max(data["xs"]):
                return
            cache = backend.core.build_curve_cache(data["xs"], data["ys"])
            height = backend.core.interpolate_curve_height(t2, cache) - backend.core.interpolate_curve_height(t1, cache)
            self.fields["H"].setText(backend.core.format_height_um(height))
            self.update_density()
        except (ValueError, TypeError):
            pass

    def temperature_edited(self):
        self._temperature_edited = True

    def generate(self):
        if self.job is not None:
            return
        if not self.output_path.text().strip():
            self.choose_output()
            if not self.output_path.text().strip():
                return
        try:
            request = self.request()
            data = deepcopy(self.data) if self.data.get("tma") is not None and self.data.get("particle") is not None else None
            self.start_job(ReportJob("generate", request, data))
        except (ValueError, OSError) as exc:
            self.log.appendPlainText(str(exc))

    def open_report(self):
        if self.last_output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_output))

    def shutdown(self):
        if self.job is not None:
            self.job.cancelled.set()

    def reject(self):
        self.shutdown()
        super().reject()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
