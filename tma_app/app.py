"""Qt desktop workspace; numerical work stays in independent Python modules."""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import sys
from copy import deepcopy

import numpy as np
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QTimer, QThread, Signal as QtSignal
from PySide6.QtGui import QAction, QColor, QKeySequence, QFontDatabase, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QTreeWidget, QTreeWidgetItem, QSplitter,
    QTabWidget, QTableView, QTableWidget, QTableWidgetItem, QHeaderView,
    QPlainTextEdit, QComboBox, QDoubleSpinBox, QSpinBox, QFormLayout,
    QGroupBox, QMessageBox, QColorDialog, QScrollArea, QCheckBox,QDialog,
)
import matplotlib

matplotlib.use("QtAgg")
matplotlib.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Microsoft YaHei", "DejaVu Sans"],
                          "axes.unicode_minus": False, "font.size": 9, "svg.fonttype": "none"})
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.widgets import SpanSelector
from matplotlib.text import Text

from . import __version__
from .reader import read_dataset
from .numerics import analyze, process_signal
from .workspace import Curve, PALETTE, save_session, load_session
from .measurement import MeasurementArtists,initial_indices,point_values,initial_y_point
from .point_labels import CURVE_VALUE_KINDS
from .peak_integration import KINDS as INTEGRATION_KINDS
from .legacy_t1_t2_h import format_plot_temp_c
from .graph_options import render_style


STYLE = """
QMainWindow, QWidget { background: #f5f7fb; color: #25334a; font-family: 'Microsoft YaHei'; font-size: 12px; }
QMenuBar, QMenu, QToolBar { background: white; }
QPushButton { background: white; border: 1px solid #d8dfeb; border-radius: 5px; padding: 7px 10px; }
QPushButton:hover { background: #eaf1ff; border-color: #a2bdec; }
QPushButton#primary { background: #2469d9; color: white; border: none; font-weight: 600; }
QPushButton#primary:hover { background: #195abe; }
QPushButton:disabled { color: #a7b0bf; }
QTreeWidget, QTableView, QPlainTextEdit { background: white; border: 1px solid #e0e5ef; border-radius: 5px; selection-background-color: #e4efff; selection-color: #17498f; }
QHeaderView::section { background: #f0f4fa; border: none; border-bottom: 1px solid #e0e5ef; padding: 7px; }
QGroupBox { background: white; border: 1px solid #e0e5ef; border-radius: 6px; margin-top: 14px; padding: 13px 10px 10px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QComboBox, QDoubleSpinBox, QSpinBox { background: white; border: 1px solid #d8dfeb; border-radius: 4px; padding: 5px; min-height: 18px; }
QTabWidget::pane { border: 1px solid #e0e5ef; background: white; }
QTabBar::tab { background: #edf1f7; padding: 9px 18px; margin-right: 2px; }
QTabBar::tab:selected { background: white; color: #2469d9; }
QStatusBar { background: white; color: #617087; }
QSplitter::handle { background: #e7ebf2; }
QLabel#muted { color: #78859a; }
"""


def number(minimum=-1e12, maximum=1e12, value=0, decimals=4):
    widget = QDoubleSpinBox()
    widget.setRange(minimum, maximum)
    widget.setDecimals(decimals)
    widget.setValue(value)
    widget.setKeyboardTracking(False)
    return widget


def button(text, callback, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("primary")
    widget.clicked.connect(callback)
    return widget


class DataModel(QAbstractTableModel):
    def __init__(self, curve=None, domain="temperature",display_x_offset=0.):
        super().__init__()
        self.curve, self.domain = curve, domain
        self.rows = np.array([],dtype=int) if curve is None else curve.active_rows
        self.source_data = None if curve is None else curve.logical_dataset
        self.display_xy = None
        if curve is not None:
            try:
                self.display_xy = curve.xy(domain)
                self.display_xy=(self.display_xy[0]+display_x_offset,self.display_xy[1])
            except ValueError:
                pass

    def rowCount(self, parent=QModelIndex()):
        return 0 if self.curve is None or parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if self.curve is None or parent.isValid() else len(self.curve.dataset.signals) + 2

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and index.isValid():
            c = self.curve
            column = index.column()
            if column < len(c.dataset.signals):
                val = self.source_data.values[self.rows[index.row()], column]
            else:
                if self.display_xy is None:
                    return "—"
                val = self.display_xy[column - len(c.dataset.signals)][index.row()]
            return f"{val:.8g}"

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Vertical:
                return str(int(self.rows[section]) + 1)
            labels = [s.label for s in self.source_data.signals] + ["显示 X", "显示 Y"]
            return labels[section]


class ImportWorker(QThread):
    completed = QtSignal(object, object)

    def __init__(self, paths):
        super().__init__()
        self.paths = paths

    def run(self):
        datasets, failures = [], []
        for path in self.paths:
            try:
                datasets.append(read_dataset(path))
            except Exception as exc:
                failures.append(f"{Path(path).name}: {exc}")
        self.completed.emit(datasets, failures)


class MainWindow(QMainWindow):
    def __init__(self):
        # Windows' offscreen Qt plugin has no system-font enumeration. Register
        # the OS font explicitly; keep the same readable font in GUI and QA.
        if "Microsoft YaHei" not in QFontDatabase.families():
            font_path = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts" / "msyh.ttc"
            if font_path.exists():
                QFontDatabase.addApplicationFont(str(font_path))
                QApplication.instance().setFont(QFont("Microsoft YaHei", 9))
        super().__init__()
        self.setWindowTitle(f"TMA Studio  {__version__}")
        self.resize(1500, 950)
        self.setMinimumSize(1080, 720)
        self.setAcceptDrops(True)
        self.curves = []
        self.results = []
        self.plot_options = {}
        self.domain = "temperature"
        self.dirty = False
        self.session_path = None
        self.worker = None
        self._updating = False
        self._plot_artists = []
        self._result_annotations = []
        self._drag_annotation = None
        self._measurement_artists = []
        self._drag_measurement = None
        self._pending_measurement = None
        self._editing_measurement = None
        self._menu()
        self._build()
        self._build_measurement_controls()
        self.statusBar().showMessage("就绪 · 拖入 TA 数据文件，或点击「导入数据」")
        self.redraw()

    def _menu(self):
        filemenu = self.menuBar().addMenu("文件")
        actions = [
            ("导入数据…", self.open_files, "Ctrl+O"),
            ("打开会话…", self.open_session, "Ctrl+Shift+O"),
            ("保存会话…", self.save, "Ctrl+S"),
            ("导出图像…", self.export_plot, "Ctrl+E"),
            ("导出当前数据 CSV…", self.export_data, ""),
            ("导出分析结果 CSV…", self.export_results, ""),
            ("导出分析报告 HTML…", self.export_report, ""),
        ]
        for title, callback, shortcut in actions:
            action = QAction(title, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            filemenu.addAction(action)
        viewmenu = self.menuBar().addMenu("视图")
        action = viewmenu.addAction("全图适配")
        action.triggered.connect(self.redraw)
        helpmenu = self.menuBar().addMenu("帮助")
        helpmenu.addAction("关于与算法说明").triggered.connect(self.about)

    def _build(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 14, 18, 12)
        layout.setSpacing(12)
        header = QHBoxLayout()
        brand = QLabel("TMA <b>Studio</b>")
        brand.setStyleSheet("font-size: 26px; color: #183458;")
        header.addWidget(brand)
        caption = QLabel("热分析工作台  /  数据 · 曲线 · 分析")
        caption.setObjectName("muted")
        header.addWidget(caption)
        header.addStretch()
        header.addWidget(button("打开会话", self.open_session))
        header.addWidget(button("保存会话", self.save))
        header.addWidget(button("＋ 导入数据", self.open_files, True))
        layout.addLayout(header)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 4, 0)
        title = QLabel("数据文件")
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        ll.addWidget(title)
        self.count_label = QLabel("0 个文件 · 勾选曲线进行叠加")
        self.count_label.setObjectName("muted")
        ll.addWidget(self.count_label)
        self.files = QTreeWidget()
        self.files.setHeaderLabels(["样本 / 文件", "点数"])
        self.files.setRootIsDecorated(False)
        self.files.setColumnWidth(0, 180)
        self.files.itemSelectionChanged.connect(self.selection_changed)
        self.files.itemChanged.connect(self.visibility_changed)
        ll.addWidget(self.files)
        row = QHBoxLayout()
        row.addWidget(button("全部显示", lambda: self.set_all_visible(True)))
        row.addWidget(button("移除", self.remove_selected))
        ll.addLayout(row)
        ll.addWidget(button("添加同文件的另一信号", self.duplicate_curve))
        hint = QLabel("支持 .001–.999、TA 文本导出\n拖放文件即可添加；源文件只读。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        ll.addWidget(hint)
        split.addWidget(left)
        center = QSplitter(Qt.Orientation.Vertical)
        center.setChildrenCollapsible(False)
        self.tabs = QTabWidget()
        plotpage = QWidget()
        pl = QVBoxLayout(plotpage)
        pl.setContentsMargins(8, 5, 8, 6)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("X 轴"))
        self.domain_box = QComboBox()
        self.domain_box.addItems(["温度", "时间", "指定信号"])
        self.domain_box.currentIndexChanged.connect(self.change_domain)
        controls.addWidget(self.domain_box)
        self.single = QCheckBox("仅显示选中曲线")
        self.single.toggled.connect(self.redraw)
        controls.addWidget(self.single)
        self.show_results = QCheckBox("结果标注")
        self.show_results.setChecked(True)
        self.show_results.toggled.connect(self.redraw)
        controls.addWidget(self.show_results)
        self.range_enabled = QCheckBox("拖拽选择分析区间")
        self.range_enabled.toggled.connect(self.enable_range)
        controls.addWidget(self.range_enabled)
        controls.addStretch()
        controls.addWidget(button("导出图像", self.export_plot))
        pl.addLayout(controls)
        self.figure = Figure(facecolor="white")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setMinimumHeight(260)
        self.canvas.mpl_connect("motion_notify_event", self.cursor_motion)
        self.canvas.mpl_connect("button_press_event", self.result_press)
        self.canvas.mpl_connect("motion_notify_event", self.result_motion)
        self.canvas.mpl_connect("button_release_event", self.result_release)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        pl.addWidget(self.toolbar)
        pl.addWidget(self.canvas, 1)
        self.tabs.addTab(plotpage, "曲线叠加")
        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.tabs.addTab(self.table, "数据表")
        self.metadata = QPlainTextEdit()
        self.metadata.setReadOnly(True)
        self.tabs.addTab(self.metadata, "样本信息 / 方法")
        center.addWidget(self.tabs)
        bottom = QTabWidget()
        self.result_table = QTableWidget(0, 5)
        self.result_table.setHorizontalHeaderLabels(["文件", "分析", "X 区间", "结果", "信号 / 处理"])
        self.result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        bottom.addTab(self.result_table, "分析结果")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        bottom.addTab(self.log, "导入与操作记录")
        center.addWidget(bottom)
        center.setSizes([630, 180])
        split.addWidget(center)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(260)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(7, 0, 0, 0)
        prop = QGroupBox("曲线设置")
        form = QFormLayout(prop)
        self.y_box = QComboBox()
        self.y_box.currentIndexChanged.connect(self.y_changed)
        form.addRow("Y 信号", self.y_box)
        self.axis_box = QComboBox()
        self.axis_box.addItems(["Y1 · 左", "Y2 · 右", "Y3 · 右外", "Y4 · 左外"])
        self.axis_box.currentIndexChanged.connect(self.properties_changed)
        form.addRow("坐标轴", self.axis_box)
        self.color_button = button("曲线颜色", self.choose_color)
        form.addRow(self.color_button)
        self.width_box = number(.3, 8, 1.8, 1)
        self.style_box = QComboBox()
        for label, style in (("实线", "-"), ("虚线", "--"), ("点划线", "-."), ("点线", ":"), ("仅符号", "None"), ("长虚线", "long_dash"), ("断续线", "broken_dash"), ("双断续线", "broken_double_dash")):
            self.style_box.addItem(label, style)
        self.xshift_box, self.scale_box, self.offset_box = number(), number(value=1), number()
        for label, widget in (("线宽", self.width_box), ("线型", self.style_box), ("X 平移", self.xshift_box), ("Y 倍率", self.scale_box), ("Y 偏移", self.offset_box)):
            form.addRow(label, widget)
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self.properties_changed)
            else:
                widget.valueChanged.connect(self.properties_changed)
        rl.addWidget(prop)
        analysis = QGroupBox("区间分析")
        af = QFormLayout(analysis)
        self.analysis_box = QComboBox()
        for label, key in [("线性拟合 / 斜率", "slope"), ("最大值 / 最小值", "peak"), ("信号最大", "signal_max"), ("信号变化", "signal_change"), ("直线基线积分", "integral"), ("信号变化量（旧版）", "change"), ("热膨胀系数 CTE", "cte"), ("切线交点 Onset", "onset")]:
            self.analysis_box.addItem(label, key)
        af.addRow(self.analysis_box)
        self.lo_box, self.hi_box = number(), number(value=250)
        af.addRow("X 起点", self.lo_box)
        af.addRow("X 终点", self.hi_box)
        self.length_box = number(0, 1e6, 0, 5)
        self.length_box.setSpecialValueText("请填写实测长度")
        af.addRow("初始长度 / mm", self.length_box)
        self.batch_check = QCheckBox("对全部可见曲线分析")
        af.addRow(self.batch_check)
        af.addRow(button("计算并记录结果", self.run_analysis, True))
        note = QLabel("CTE 需尺寸信号 µm、温度 °C 和正的初始长度。分析使用当前显示数据，结果记录变换参数。")
        note.setWordWrap(True)
        note.setObjectName("muted")
        af.addRow(note)
        rl.addWidget(analysis)
        tools = QGroupBox("信号处理")
        tf = QFormLayout(tools)
        self.smooth_window = QSpinBox()
        self.smooth_window.setRange(3, 10001)
        self.smooth_window.setSingleStep(2)
        self.smooth_window.setValue(11)
        tf.addRow("平滑窗口 / 点", self.smooth_window)
        tf.addRow(button("Savitzky–Golay 平滑", lambda: self.process("smooth")))
        tf.addRow(button("对当前 X 求导", lambda: self.process("derivative")))
        tf.addRow(button("首点归一化 / %", lambda: self.process("normalize")))
        tf.addRow(button("撤销上次处理", self.undo))
        tf.addRow(button("恢复原始曲线", self.reset_curve))
        rl.addWidget(tools)
        self.operation_label = QLabel("选择一个文件查看曲线设置")
        self.operation_label.setWordWrap(True)
        self.operation_label.setObjectName("muted")
        rl.addWidget(self.operation_label)
        rl.addStretch()
        for combo in right.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
            combo.setMinimumWidth(90)
        scroll.setWidget(right)
        split.addWidget(scroll)
        split.setSizes([235, 955, 285])
        layout.addWidget(split, 1)
        self.setCentralWidget(root)

    def selected(self):
        item = self.files.currentItem()
        if item is None:
            return None
        i = self.files.indexOfTopLevelItem(item)
        return self.curves[i] if 0 <= i < len(self.curves) else None

    def warn(self, message):
        self.log.appendPlainText(str(message))
        QMessageBox.warning(self, "TMA Studio", str(message))

    def touch(self):
        self.dirty = True
        self.setWindowTitle(f"TMA Studio {__version__}  • 未保存")

    def protect_output(self, *paths):
        sources = {str(c.dataset.path.resolve()).casefold() for c in self.curves}
        for path in paths:
            if str(Path(path).resolve()).casefold() in sources:
                raise ValueError("输出路径与原始数据相同，请选择新的文件名。")

    def open_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "导入 TA 数据", "", "TA 数据 (*.0?? *.1?? *.2?? *.3?? *.4?? *.5?? *.6?? *.7?? *.8?? *.9?? *.tai *.txt *.csv);;所有文件 (*)")
        if paths:
            self.import_files(paths)

    def import_files(self, paths, synchronous=False):
        known = {str(c.dataset.path.resolve()).casefold() for c in self.curves}
        unique = []
        for p in paths:
            key = str(Path(p).resolve()).casefold()
            if key not in known:
                known.add(key)
                unique.append(str(p))
        if not unique:
            return
        if synchronous:
            datasets, failures = [], []
            for path in unique:
                try:
                    datasets.append(read_dataset(path))
                except Exception as exc:
                    failures.append(f"{Path(path).name}: {exc}")
            self.finish_import(datasets, failures)
            return
        if self.worker is not None:
            self.warn("正在导入数据，请等待当前导入结束。")
            return
        self.worker = ImportWorker(unique)
        self.worker.completed.connect(self.finish_import)
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()
        self.statusBar().showMessage(f"正在解析 {len(unique)} 个文件…")

    def worker_finished(self):
        self.worker.deleteLater()
        self.worker = None

    def finish_import(self, datasets, failures):
        for ds in datasets:
            yi = next((i for i, s in enumerate(ds.signals) if "dimension" in s.name.lower()), min(2, len(ds.signals) - 1))
            curve = Curve(ds, y_index=yi, color=PALETTE[len(self.curves) % len(PALETTE)])
            from .dimension_units import dimension_index
            if dimension_index(ds) is not None or ds.time_index is not None or ds.temperature_index is not None:
                from .preferences import load_defaults
                try:curve.unit_options=deepcopy(load_defaults('units')['options'].get('unit_defaults'))
                except (ValueError,OSError) as exc:self.log.appendPlainText(f'单位默认设置未载入：{exc}')
            self.curves.append(curve)
            self.log.appendPlainText(f"导入 {ds.path.name} · {len(ds.values):,} 点 · SHA256 {ds.sha256}")
            self.update_curve_mass(curve)
            for warning in ds.warnings:
                self.log.appendPlainText(f"  提示: {warning}")
        if datasets:
            self.touch()
            self.rebuild_files()
            if not self.files.selectedItems():
                self.files.setCurrentItem(self.files.topLevelItem(0))
            self.redraw()
        self.statusBar().showMessage(f"已导入 {len(datasets)} 个文件；失败 {len(failures)} 个")
        if failures:
            self.warn("以下文件未能导入：\n" + "\n".join(failures))

    def update_curve_mass(self, curve):
        from .mass_lookup import lookup_record
        result = lookup_record(curve.sample_name)
        metadata = curve.dataset.metadata
        for key in ("LookupMass", "LookupMassUnit", "LookupMassSource", "LookupMassSample"): metadata.pop(key, None)
        if result.value is not None:
            metadata.update(LookupMass=[str(result.value)], LookupMassUnit=[result.unit], LookupMassSource=[result.source], LookupMassSample=[curve.sample_name])
            self.log.appendPlainText(f"  m = {result.value:g} {result.unit} · {curve.sample_name} · {result.source}")
        else: self.log.appendPlainText(f"  m：{result.message}")
        return result

    def refresh_mass_lookup(self):
        seen = set(); matched = 0
        for curve in self.curves:
            if id(curve.dataset) in seen: continue
            seen.add(id(curve.dataset)); matched += self.update_curve_mass(curve).value is not None
        if seen: self.touch(); self.rebuild_files()
        self.statusBar().showMessage(f"m 数据源已更新：{matched}/{len(seen)} 个样品匹配成功")

    def rebuild_files(self):
        previous = self.selected()
        self._updating = True
        self.files.clear()
        for curve in self.curves:
            item = QTreeWidgetItem([curve.dataset.path.name, f"{curve.sample_count:,}"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if curve.visible else Qt.CheckState.Unchecked)
            item.setForeground(0, QColor(curve.color))
            tooltip = str(curve.dataset.path) + "\n" + curve.sample_name
            mass = next((str(v).strip() for v in curve.dataset.metadata.get("LookupMass", curve.dataset.metadata.get("Mass", [])) if str(v).strip()), None)
            if mass:
                unit = " ".join(curve.dataset.metadata.get("LookupMassUnit", []))
                tooltip += f"\n质量 m = {mass} {unit}"
                tooltip += "\n" + " ".join(curve.dataset.metadata.get("LookupMassSource", []))
            item.setToolTip(0, tooltip)
            self.files.addTopLevelItem(item)
            if previous is not None and curve.uid == previous.uid:
                self.files.setCurrentItem(item)
        source_count = len({str(c.dataset.path) for c in self.curves})
        self.count_label.setText(f"{source_count} 个文件 · {len(self.curves)} 条曲线")
        self._updating = False
        self.selection_changed()

    def selection_changed(self):
        if self._updating:
            return
        c = self.selected()
        self._updating = True
        self.y_box.clear()
        if c:
            self.y_box.addItems([s.label for s in c.logical_dataset.signals])
            self.y_box.setEnabled(c.derived is None)
            self.y_box.setCurrentIndex(c.y_index)
            self.axis_box.setCurrentIndex(c.axis)
            self.width_box.setValue(c.width)
            self.style_box.setCurrentIndex(self.style_box.findData(c.style))
            for field,factor in ((self.xshift_box,c.x_unit_factor(self.domain)),(self.offset_box,c.y_unit_factor())):
                field.setDecimals(max(4,min(14,4+int(np.ceil(max(0.,-np.log10(factor)))))))
            self.xshift_box.setValue(c.display_x_shift(self.domain))
            self.scale_box.setValue(c.scale)
            self.offset_box.setValue(c.display_y_offset())
            self.color_button.setStyleSheet(f"color: {c.color}; font-weight: 600;")
            self.operation_label.setText("处理记录：" + (" → ".join(c.operations) or (c.derived['label'] if c.derived is not None else "原始信号")))
            from .file_information import snapshot
            self.metadata.setPlainText(json.dumps({"文件信息":snapshot(c),"来源": str(c.dataset.path), "SHA256": c.dataset.sha256, "警告": c.dataset.warnings, "参数": c.dataset.metadata}, ensure_ascii=False, indent=2))
            try:
                x, _ = c.xy(self.domain)
                self.lo_box.setValue(float(np.min(x)))
                self.hi_box.setValue(float(np.max(x)))
            except ValueError:
                pass
        else:
            self.metadata.clear()
        self.table.setModel(DataModel(c,self.domain,self.display_x_offset(c)))
        self._updating = False
        self.redraw()

    def visibility_changed(self, item, column):
        if self._updating:
            return
        self.curves[self.files.indexOfTopLevelItem(item)].visible = item.checkState(0) == Qt.CheckState.Checked
        self.touch()
        self.redraw()

    def set_all_visible(self, value):
        for c in self.curves:
            c.visible = value
        self.touch()
        self.rebuild_files()
        self.redraw()

    def remove_selected(self):
        c = self.selected()
        if c:
            if self._pending_measurement is not None and self._pending_measurement["curve_id"] == c.uid:
                self.cancel_measurement(redraw=False)
            self.curves.remove(c)
            self.touch()
            self.rebuild_files()
            if self.curves:
                self.files.setCurrentItem(self.files.topLevelItem(0))
            self.redraw()

    def duplicate_curve(self):
        c = self.selected()
        if c is None:
            return
        index = (c.y_index + 1) % len(c.dataset.signals)
        used = {curve.axis for curve in self.curves}
        axis = next((i for i in range(4) if i not in used), c.axis)
        curve = Curve(c.dataset, y_index=index, axis=axis, color=PALETTE[len(self.curves) % len(PALETTE)])
        curve.sample_size_mm=c.sample_size_mm;curve.file_info=deepcopy(c.file_info);curve.unit_options=deepcopy(c.unit_options)
        curve.data_indices=deepcopy(c.data_indices if c.derived is None else c.derived['source_rows']);curve.data_limit_spec=deepcopy(c.data_limit_spec) if c.derived is None else None;curve.reset_time=c.reset_time
        curve.x_signal_index,curve.x_signal_type,curve.x_smooth_width=c.x_signal_index,c.x_signal_type,c.x_smooth_width
        self.curves.append(curve)
        self.touch()
        self.rebuild_files()
        self.files.setCurrentItem(self.files.topLevelItem(len(self.curves) - 1))

    def properties_changed(self, *_):
        c = self.selected()
        if not c or self._updating:
            return
        sender=self.sender()
        widgets=(self.axis_box,self.width_box,self.style_box,self.xshift_box,self.scale_box,self.offset_box)
        all_fields=sender not in widgets
        if all_fields or sender is self.axis_box:c.axis=self.axis_box.currentIndex()
        if all_fields or sender is self.width_box:c.width=self.width_box.value()
        if all_fields or sender is self.style_box:c.style=self.style_box.currentData()
        if all_fields or sender is self.xshift_box:c.x_shift=self.xshift_box.value()/c.x_unit_factor(self.domain)
        if all_fields or sender is self.scale_box:c.scale=self.scale_box.value()
        if all_fields or sender is self.offset_box:c.offset=self.offset_box.value()/c.y_unit_factor()
        self.touch()
        self.table.setModel(DataModel(c,self.domain,self.display_x_offset(c)))
        self.redraw()

    def y_changed(self, index):
        c = self.selected()
        if c and c.derived is None and not self._updating and index >= 0:
            c.y_index = index
            c.working = None
            c.working_rows,c.smooth_source_rows=None,None
            c.operations.clear()
            c.y_type, c.smooth_width = "normal", 0.
            c.smooth_domain,c.smooth_reuse,c.smooth_source,c.smooth_base_ops,c.smooth_x_config=None,False,None,[],None
            c.history.clear()
            c.scale, c.offset = 1., 0.
            self.touch()
            self.selection_changed()

    def choose_color(self):
        c = self.selected()
        if c:
            color = QColorDialog.getColor(QColor(c.color), self)
            if color.isValid():
                c.color = color.name()
                self.touch()
                self.rebuild_files()

    def change_domain(self, index):
        domain = ("temperature", "time", "signal")[index]
        if domain == self.domain:
            return
        if any(any(op.startswith("derivative:") for op in c.operations) for c in self.curves):
            self.warn("已有求导曲线，其单位依赖当前 X 轴。请先恢复原始曲线，再切换 X 轴。")
            self.domain_box.blockSignals(True)
            self.domain_box.setCurrentIndex(("temperature", "time", "signal").index(self.domain))
            self.domain_box.blockSignals(False)
            return
        self.domain = domain
        self.cancel_measurement(redraw=False)
        self.touch()
        self.selection_changed()

    def visible_curves(self):
        return [c for c in self.curves if c.visible and (not self.single.isChecked() or c is self.selected())]

    def display_x_offset(self,curve):
        return 0.

    def redraw(self, *_):
        if not hasattr(self, "figure"):
            return
        if hasattr(self, "span"):
            self.span.disconnect_events()
        self.figure.clear()
        base = self.figure.add_subplot(111)
        self.axes = {0: base}
        visible = self.visible_curves()
        used = {c.axis for c in visible}
        self.figure.subplots_adjust(left=.16 if 3 in used else .10, right=.77 if 2 in used else .87, top=.89, bottom=.14)
        for axis_id in sorted(used - {0}):
            axis = base.twinx()
            if axis_id == 2:
                axis.spines["right"].set_position(("axes", 1.14))
            elif axis_id == 3:
                axis.spines["left"].set_position(("axes", -.15))
                axis.spines["left"].set_visible(True)
                axis.spines["right"].set_visible(False)
                axis.yaxis.set_label_position("left")
                axis.yaxis.tick_left()
            self.axes[axis_id] = axis
        handles, labels, units, axis_labels = [], [], {}, {}
        self._plot_artists = []
        self._result_annotations = []
        self._drag_annotation = None
        self._measurement_artists = []
        self._drag_measurement = None
        skipped = []
        x_description = None
        for c in visible:
            try:
                x, y = c.xy(self.domain)
            except ValueError as exc:
                skipped.append(str(exc))
                continue
            if self.domain == "signal":
                description = (c.x_unit(self.domain).replace("μ", "µ"), c.x_signal_type)
                if x_description is not None and description != x_description:
                    skipped.append(f"{c.dataset.path.name}: X信号单位或类型不同，未叠加"); continue
                x_description = description
            unit = c.result_unit
            axis = self.axes[c.axis]
            if c.axis in units and units[c.axis] != unit:
                skipped.append(f"{c.dataset.path.name}: Y{c.axis + 1} 信号单位不一致，请分配其它轴")
                continue
            units[c.axis] = unit
            axis_labels.setdefault(c.axis, c.plot_label)
            label = c.legend_text or c.dataset.path.name
            style = render_style(c.style)
            gaps=np.flatnonzero(np.diff(c.active_rows)!=1)+1
            dx=self.display_x_offset(c)
            px,py=np.insert(x+dx,gaps,np.nan),np.insert(y,gaps,np.nan)
            line, = axis.plot(px, py, color=c.color, lw=c.width, ls=style, marker=c.marker or ("." if c.style == "None" else ""), markevery=max(1, len(x)//60), ms=3, label=label if c.show_legend else "_nolegend_")
            line._tma_curve_uid = c.uid
            if c.show_legend:
                handles.append(line)
                labels.append(label)
            self._plot_artists.append((c, x, y))
            if self.show_results.isChecked():
                entries = [r for r in self.results if r is not self._editing_measurement]
                if self._pending_measurement is not None: entries.append(self._pending_measurement)
                matching = [r for r in entries if not r.get("annotation", {}).get("hidden", False) and r["sha256"] == c.dataset.sha256 and r["domain"] == self.domain
                            and r.get("curve_id", c.uid) == c.uid
                            and r["signal"] == c.result_label and r["operations"] == c.operations
                            and r["transform"] == c.result_transform(self.domain)]
                for result in matching[-6:]:
                    if "interactive" in result:
                        editor = MeasurementArtists(axis,c,result,self.domain,display_x_offset=dx)
                        self._measurement_artists.append(editor)
                        self._result_annotations.append((result, editor.annotation))
                        self._result_annotations.extend((result, text) for text in editor.details)
                        self._result_annotations.extend((result, text) for text in editor.temps)
                        continue
                    vals = result["values"]
                    options = result.get("annotation", {})
                    if result["kind"] == "note":
                        annotation = axis.annotate(vals["text"], (vals["x"]+dx, vals["y"]), xytext=options.get("offset", (0, 0)), textcoords="offset points", fontsize=10, color=c.color)
                        self._result_annotations.append((result, annotation))
                    if result["kind"] == "signal_max":
                        px, py = vals["max_x"], vals["max_y"]
                        axis.plot([px+dx], [py], "o", color=c.color, ms=4)
                        text = f"{format_plot_temp_c(px)} {c.x_unit(self.domain)}" if self.domain == "temperature" else f"{px:.6g} {c.x_unit(self.domain)}"
                        annotation = axis.annotate(text, (px+dx, py), xytext=options.get("offset", (8, 16)), textcoords="offset points", fontsize=8, color=c.color,
                                                   arrowprops={"arrowstyle": "-", "color": c.color, "lw": .7})
                        self._result_annotations.append((result, annotation))
                    elif result["kind"] == "signal_change":
                        sx, sy, ex, ey = (vals[k] for k in ("start_x", "start_y", "stop_x", "stop_y"))
                        axis.plot([sx+dx, ex+dx], [sy, ey], "o", color=c.color, ms=4)
                        texts = []
                        if options.get("change", True):
                            change = vals["change"] if options.get("signed", True) else abs(vals["change"])
                            texts.append(f"ΔY = {change:.6g}")
                        if options.get("y_limits", True):
                            texts.append(f"Y: {sy:.6g} → {ey:.6g}")
                        if options.get("x_limits", True):
                            texts.append(f"X: {sx:.6g} → {ex:.6g}")
                        if texts:
                            from .measurement import ResultAnnotation, split_result_lines
                            annotation = ResultAnnotation("\n".join(texts), (ex+dx, ey), xytext=options.get("offset", (8, 16)), textcoords="offset points", fontsize=8, color=c.color,
                                                       arrowprops={"arrowstyle": "-", "color": c.color, "lw": .7})
                            axis.add_artist(annotation)
                            self._result_annotations.append((result, annotation))
                            self._result_annotations.extend((result, text) for text in split_result_lines(annotation, result, [], c.color))
                        axis.plot([sx+dx, ex+dx], [sy, sy], ":", color=c.color, lw=.6)
                        axis.annotate("", (ex+dx, ey), (ex+dx, sy), arrowprops={"arrowstyle": "<->", "color": c.color, "lw": .7})
                    for xkey, ykey, title in (("peak_x", "peak_y", "Max"), ("onset_x", "onset_y", "Onset")):
                        if xkey in vals:
                            axis.plot([vals[xkey]+dx], [vals[ykey]], "o", color=c.color, ms=4)
                            axis.annotate(f"{title} {vals[xkey]:.3f}", (vals[xkey]+dx, vals[ykey]), xytext=(8, 14), textcoords="offset points", fontsize=8, color=c.color,
                                          arrowprops={"arrowstyle": "-", "color": c.color, "lw": .7})
                    if result["kind"] in ("slope", "cte"):
                        fitx = np.array([vals["x_start"], vals["x_end"]])
                        axis.plot(fitx+dx, vals["slope"] * fitx + vals["intercept"], "--", color=c.color, lw=1, alpha=.8)
                    elif result["kind"] == "onset":
                        for prefix in ("baseline", "tangent"):
                            fitx = np.array([min(vals[prefix + "_x_start"], vals["onset_x"]), max(vals[prefix + "_x_end"], vals["onset_x"])])
                            axis.plot(fitx+dx, vals[prefix + "_slope"] * fitx + vals[prefix + "_intercept"], ":", color=c.color, lw=1, alpha=.7)
        for idx, axis in self.axes.items():
            axis.set_ylabel(axis_labels.get(idx, "信号") if idx == 0 or idx in units else "")
            axis.tick_params(colors="#6b788c", labelsize=8)
            for spine in axis.spines.values():
                spine.set_color("#ccd5e3")
        base.set_xlabel(self._plot_artists[0][0].x_label(self.domain) if self._plot_artists else self.domain)
        base.grid(True, color="#e7edf5", lw=.7)
        base.set_axisbelow(True)
        base.set_title("THERMAL ANALYSIS  /  " + (f"{len(handles)} curves" if handles else "Workspace"), loc="left", fontsize=10, color="#4d607c", pad=16)
        if self._plot_artists:
            if handles:
                base.legend(handles, labels, loc="best", fontsize=8, framealpha=.94, edgecolor="#e3e9f2")
        else:
            base.text(.5, .54, "从原始数据开始", ha="center", transform=base.transAxes, fontsize=22, color="#365778")
            base.text(.5, .44, "导入 .001 / .002 / .003 等 TA 数据\n选择信号、叠加曲线，并在区间内进行分析", ha="center", va="center", transform=base.transAxes, fontsize=11, color="#8392a5", linespacing=1.8)
        if skipped:
            base.text(.01, .01, "\n".join(skipped[:3]), transform=base.transAxes, color="#ad6235", fontsize=8)
        self.span = SpanSelector(base, self.range_selected, "horizontal", useblit=False, props={"alpha": .14, "facecolor": "#2671de"}, interactive=True)
        self.span.set_active(self.range_enabled.isChecked())
        self.canvas.draw_idle()

    def enable_range(self, active):
        if active and self.toolbar.mode:
            if "pan" in str(self.toolbar.mode).lower():
                self.toolbar.pan()
            else:
                self.toolbar.zoom()
        self.span.set_active(active)

    def range_selected(self, lo, hi):
        self.lo_box.setValue(lo)
        self.hi_box.setValue(hi)
        self.statusBar().showMessage(f"分析区间 {lo:.4f} → {hi:.4f}")

    def cursor_motion(self, event):
        if event.xdata is None:
            return
        c = self.selected()
        for curve, x, y in self._plot_artists:
            if curve is c:
                i = int(np.argmin(np.abs(x-(event.xdata-self.display_x_offset(curve)))))
                self.statusBar().showMessage(f"{c.dataset.path.name}  |  X {x[i]:.6g}  |  Y {y[i]:.6g}  |  采样点 {int(curve.active_rows[i])+1:,}")
                break

    def layout_result_annotations(self):
        """Place result text inside the plot, avoiding other result text boxes."""
        if not self._result_annotations: return
        self.canvas.draw()
        renderer = self.canvas.get_renderer()
        occupied = [Text.get_window_extent(text, renderer).expanded(1.04, 1.12)
                    for editor in self._measurement_artists for text in editor.temps if text.get_visible()]
        for result, annotation in self._result_annotations:
            if not annotation.get_visible() or not annotation.get_text(): continue
            if getattr(annotation, "_tma_offset_key", None) is not None:
                continue  # Temperature labels retain their independent offsets.
            bounds = annotation.axes.bbox
            if "offset" not in result.get("annotation", {}):
                candidates = [(dx, dy) for dy in (18, 75, -65, 135, -125, 195, -185, 250) for dx in (12, -140, 150, -270, 280)]
                chosen = None
                for offset in candidates:
                    annotation.xyann = offset
                    annotation.update_positions(renderer)
                    box = Text.get_window_extent(annotation, renderer).expanded(1.04, 1.12)
                    inside = box.x0 >= bounds.x0 + 4 and box.x1 <= bounds.x1 - 4 and box.y0 >= bounds.y0 + 4 and box.y1 <= bounds.y1 - 4
                    if inside and not any(box.overlaps(other) for other in occupied):
                        chosen = offset; break
                annotation.xyann = chosen or (12, 18)
            annotation.update_positions(renderer)
            occupied.append(Text.get_window_extent(annotation, renderer).expanded(1.04, 1.12))
        for editor in self._measurement_artists:
            offsets = editor.entry.get("annotation", {}).get("label_offsets", {})
            for index, text in enumerate(editor.details, 1):
                if f"info{index}" not in offsets:
                    origin = editor.annotation.xyann
                    text.xyann = (origin[0], origin[1]-18*index)

    def result_press(self, event):
        if event.button != 1 or self.range_enabled.isChecked() or self.toolbar.mode:
            return
        if event.x is None or event.y is None: return
        if getattr(event, "dblclick", False) and self._pending_measurement is not None:
            for editor in self._measurement_artists:
                if editor.entry is self._pending_measurement and editor.axis.bbox.contains(event.x,event.y):
                    point = editor.entry["interactive"].get("active_point", 0)
                    x,y=editor.axis.transData.inverted().transform((event.x,event.y))
                    target=float(y) if editor.entry["kind"]=="curve_value_y" else float(x)-editor.display_x_offset
                    try:editor.move(point,target)
                    except ValueError as exc:self.statusBar().showMessage(str(exc),5000);return
                    point = (point+1) % len(editor.indices)
                    editor.entry["interactive"]["active_point"] = point
                    editor.update(active=point); self._update_measurement_controls(); self.canvas.draw_idle()
                    return
        for editor in reversed(self._measurement_artists):
            hit = editor.hit(event.x, event.y)
            if hit is not None:
                self._drag_measurement = (editor, hit)
                editor.entry["interactive"]["active_point"] = hit
                editor.update(active=hit)
                self.canvas.draw_idle()
                return
        if not self._result_annotations: return
        renderer = self.canvas.get_renderer()
        for result, annotation in reversed(self._result_annotations):
            if annotation.get_visible() and annotation.get_text() and Text.get_window_extent(annotation, renderer).contains(event.x, event.y):
                self._drag_annotation = (result, annotation, event.x, event.y, annotation.xyann)
                return

    def measurement_key(self, event):
        pending = self._pending_measurement
        if pending is None or not any(editor.entry is pending for editor in self._measurement_artists): return
        if event.key in ("enter", "return"):
            self.confirm_measurement(); return
        if str(event.key).lower() in ("tab","shift+tab","backtab"):
            direction=-1 if str(event.key).lower()!="tab" else 1
            point=(pending["interactive"].get("active_point",0)+direction)%len(pending["interactive"]["indices"])
            pending["interactive"]["active_point"]=point
            for editor in self._measurement_artists:
                if editor.entry is pending:editor.update(active=point)
            self.canvas.draw_idle()
            return
        parts = str(event.key).lower().split("+")
        allowed=("left","right","up","down") if pending["kind"]=="curve_value_y" else ("left","right")
        if parts[-1] not in allowed:return
        for editor in self._measurement_artists:
            if editor.entry is pending:
                point = pending["interactive"].get("active_point", 0)
                pixels = (10 if "ctrl" in parts or "control" in parts or "shift" in parts else 1) * (1 if parts[-1] in ("right","up") else -1)
                try:editor.nudge(point, pixels)
                except ValueError as exc:
                    self.statusBar().showMessage(str(exc),5000);return
                self._update_measurement_controls(); self.canvas.draw_idle()
                return

    def result_motion(self, event):
        if self._drag_measurement is not None:
            editor, point = self._drag_measurement
            if event.x is None or event.y is None: return
            x,y=editor.axis.transData.inverted().transform((event.x,event.y))
            target=float(y) if editor.entry["kind"]=="curve_value_y" else float(x)-editor.display_x_offset
            try:editor.move(point,target)
            except ValueError as exc:self.statusBar().showMessage(str(exc),5000);return
            values = editor.entry["values"]
            actual_x,actual_y=editor.coords[point]
            self.statusBar().showMessage(f"点 {point+1}: X {actual_x:.6g}，Y {actual_y:.6g}" + (f"  |  H {values['change']:.6g}" if "change" in values else ""))
            self.refresh_results()
            self._update_measurement_controls()
            self.canvas.draw_idle()
            return
        if self._drag_annotation is None or event.x is None or event.y is None: return
        result, annotation, x, y, offset = self._drag_annotation
        points = 72 / self.figure.dpi
        annotation.xyann = (offset[0] + (event.x - x)*points, offset[1] + (event.y - y)*points)
        self.canvas.draw_idle()

    def result_release(self, event):
        if self._drag_measurement is not None:
            editor, _ = self._drag_measurement
            self._drag_measurement = None
            self.refresh_results(); self._update_measurement_controls()
            return
        if self._drag_annotation is None: return
        result, annotation, *_ = self._drag_annotation
        options = result.setdefault("annotation", {})
        key = getattr(annotation, "_tma_offset_key", None)
        if key is not None:
            options.setdefault("label_offsets", {})[key] = [float(v) for v in annotation.xyann]
        else:
            options["offset"] = [float(v) for v in annotation.xyann]
        self._drag_annotation = None
        if result is not self._pending_measurement: self.touch()

    def run_analysis(self, annotation_options=None, *, bounds=None):
        targets = self.visible_curves() if self.batch_check.isChecked() else [self.selected()]
        lo, hi = bounds if bounds is not None else (self.lo_box.value(), self.hi_box.value())
        failures = []
        for c in targets:
            if c is None:
                continue
            try:
                x, y = c.xy(self.domain)
                c.assert_contiguous_analysis(self.domain,lo,hi)
                kind = self.analysis_box.currentData()
                if kind == "cte":
                    unit = c.result_unit.replace("μ", "µ").strip()
                    if self.domain != "temperature" or unit not in ("µm", "um","mm") or any(o == "normalize" or o.startswith("derivative:") for o in c.operations):
                        raise ValueError("CTE 需要温度 X 轴和未求导/归一化的 µm/mm 尺寸信号")
                    from .alpha import positive
                    length=positive(self.length_box.value(),'试样原始长度(mm)')
                    result=analyze(x,y,'slope',lo,hi)
                    from .general_units import displayed_delta_per_c
                    coefficient=result['slope']/length*(1e6 if unit=='mm' else 1000)*displayed_delta_per_c(c.x_unit(self.domain))
                    if not np.isfinite(coefficient):raise ValueError('CTE结果超出有限范围')
                    result.update(method='cte',reference_length_mm=length,cte_ppm_per_k=coefficient,algorithm=f'OLS slope [{unit}/{c.x_unit(self.domain)}] normalized by explicit length [mm] and Celsius temperature delta')
                else:result = analyze(x, y, kind, lo, hi, reference_length_mm=self.length_box.value() or None)
                entry = {"file": c.dataset.path.name, "sha256": c.dataset.sha256, "curve_id": c.uid, "kind": kind,
                         "domain": self.domain, "lo": lo, "hi": hi,
                         "signal": c.result_label, "axis": c.axis + 1, "operations": list(c.operations),
                         "transform": c.result_transform(self.domain),
                         "reference_length_mm": self.length_box.value() or None, "values": result,
                         "annotation": annotation_options if isinstance(annotation_options, dict) else {}}
                self.results.append(entry)
                self.log.appendPlainText(f"分析 {entry['file']} {kind}: {json.dumps(result, ensure_ascii=False)}")
                self.touch()
            except Exception as exc:
                failures.append(f"{c.dataset.path.name}: {exc}")
        self.refresh_results()
        self.redraw()
        if failures:
            self.warn("\n".join(failures))

    def refresh_results(self):
        self.result_table.setRowCount(len(self.results))
        for row, entry in enumerate(self.results):
            values = "; ".join(f"{k}={v:.7g}" if isinstance(v, (float, int)) else f"{k}={v}" for k, v in entry["values"].items())
            title = {"signal_max": "信号最大", "signal_change": "信号变化", "dimension_change": "尺寸变化", "height_change": "高度差", "note": "批注","curve_value":"曲线值于X轴","curve_value_y":"曲线值于Y轴","alpha_at_x":"Alpha于X","alpha_secant":"Alpha X1至X2","alpha_fit":"拟合Alpha X1至X2","step_transition":"步阶转变","glass_transition":"玻璃化转变","peak_max":"峰最大","onset_point":"始点","peak_linear":"线性峰值积分","peak_sigmoid":"水平S形峰值积分"}.get(entry["kind"], entry["kind"])
            cols = [entry["file"], title, f"{entry['lo']:.5g} → {entry['hi']:.5g}", values, entry["signal"] + " / " + " → ".join(entry["operations"])]
            for col, value in enumerate(cols):
                item = QTableWidgetItem(value)
                item.setToolTip(json.dumps(entry, ensure_ascii=False, indent=2))
                self.result_table.setItem(row, col, item)
        self.result_table.scrollToBottom()

    def start_point_measurement(self, kind, analysis_config=None):
        visible = self.visible_curves()
        c = self.selected()
        if c not in visible: c = visible[0] if visible else None
        if c is None: return
        try:
            if kind == "dimension_change" and (c.derived is not None or c.dataset.signals[c.y_index].unit.replace("μ", "µ") not in ("µm", "um")):
                raise ValueError("尺寸变化需要选择 µm 尺寸信号")
            self.range_enabled.setChecked(False)
            if self.toolbar.mode:
                if "pan" in str(self.toolbar.mode).lower(): self.toolbar.pan()
                else: self.toolbar.zoom()
            from .transitions import KINDS as TRANSITION_KINDS,validate as validate_transition
            from .peak_onset import KINDS as PEAK_ONSET_KINDS,validate as validate_peak
            transition_config=validate_transition(analysis_config) if kind in TRANSITION_KINDS else validate_peak(analysis_config) if kind in PEAK_ONSET_KINDS else None
            if kind in INTEGRATION_KINDS:
                from .peak_integration import validate as validate_integration
                transition_config=dict(peak_onset=validate_peak(analysis_config['peak_onset']),integration=validate_integration(analysis_config['integration']))
                if kind=='peak_sigmoid':
                    from .sigmoidal import validate as validate_sigmoid
                    transition_config['sigmoid']=validate_sigmoid(analysis_config.get('sigmoid'))
            indices = initial_indices(c, self.domain, kind,transition_config)
            x, y = c.xy(self.domain)
            positions=None;initial_target=None
            if kind=="curve_value_y":
                position,initial_target=initial_y_point(y,c.active_rows);positions=[position];indices=[int(round(position))]
            values = point_values(x,y,kind,indices,positions)
            coords = [float(x[i]) for i in indices]
            entry = {"file": c.dataset.path.name, "sha256": c.dataset.sha256, "curve_id": c.uid, "kind": kind,
                     "domain": self.domain, "lo": min(coords), "hi": max(coords), "signal": c.result_label,
                     "axis": c.axis+1, "operations": list(c.operations),
                     "transform": c.result_transform(self.domain),
                     "values": values, "interactive": {"indices": list(indices), "initial_indices": list(indices), "confirmed": False},
                     "annotation": {"change": True, "signed": kind != "height_change", "x_limits": kind != "height_change"}}
            if kind=='signal_change' and hasattr(self,'signal_change_settings'):entry['annotation']=self.signal_change_settings()
            if kind=='slope':
                from .slope import values as compute
                try:entry['values'].update(compute(c,entry,indices))
                except ValueError as exc:entry['values']['fit_error']=str(exc)
            if kind in INTEGRATION_KINDS:
                from .peak_integration import values as compute
                from .point_labels import signal_snapshot
                entry.update(transition_config,point_signal=signal_snapshot(c))
                try:entry['values'].update(compute(c,entry,indices))
                except ValueError as exc:entry['values']['fit_error']=str(exc)
            if kind in PEAK_ONSET_KINDS:
                from .peak_onset import values as compute
                from .point_labels import signal_snapshot
                entry['peak_onset']=transition_config;entry['point_signal']=signal_snapshot(c)
                try:entry['values'].update(compute(c,entry,indices))
                except ValueError as exc:entry['values']['fit_error']=str(exc)
            if kind in TRANSITION_KINDS:
                from .transitions import values as transition_values
                entry['transition']=transition_config
                try:entry['values'].update(transition_values(c,entry,indices))
                except ValueError as exc:entry['values']['fit_error']=str(exc)
            if kind in ("alpha_at_x","alpha_secant","alpha_fit"):
                from .alpha import alpha_values,validate_config
                entry["alpha"]=validate_config(analysis_config)
                entry["values"].update(alpha_values(c,entry,indices if positions is None else positions))
            if kind=="curve_value_y":entry["interactive"].update(positions=positions,initial_positions=list(positions),target_y=initial_target,initial_target_y=initial_target)
            if kind in CURVE_VALUE_KINDS:
                from .point_labels import default_options,validate_options,signal_snapshot
                from .preferences import load_defaults
                try:saved=load_defaults("analysis")["options"].get("point_label_options")
                except (ValueError,OSError) as exc:
                    saved=None;self.log.appendPlainText(f"标记点默认选项未载入：{exc}")
                options=default_options() if saved is None else validate_options(saved)
                if saved is None and self.domain!="temperature":options.update(temperature=False,**{("time" if self.domain=="time" else "signal"):True})
                entry["point_signal"]=signal_snapshot(c)
                if c.dataset.time_index is None:options["time"]=False
                if c.dataset.temperature_index is None:options["temperature"]=False
                if entry["point_signal"] is None:options["signal"]=False
                entry["annotation"]["point_label"]=options
            self.cancel_measurement(redraw=False)
            self._pending_measurement = entry
            self.show_results.setChecked(True)
            self._update_measurement_controls(); self.redraw()
            for editor in self._measurement_artists:
                if editor.entry is entry: editor.update(active=0)
            self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)
            self.statusBar().showMessage("上下拖动水平标记；右键确定、编辑Y或取消。" if kind=="curve_value_y" else "左右拖动红色十字；右键确定、编辑界限或取消。")
            return entry
        except ValueError as exc:
            self.warn(str(exc))

    def _build_measurement_controls(self):
        self.measurement_confirm = QAction("确定", self)
        self.measurement_cancel = QAction("取消", self)
        self.measurement_cancel.setShortcut("Esc")
        self.measurement_confirm.triggered.connect(lambda: self.confirm_measurement())
        self.measurement_cancel.triggered.connect(lambda: self.cancel_measurement())
        self.addAction(self.measurement_cancel)
        self._update_measurement_controls()

    def _update_measurement_controls(self):
        if not hasattr(self, "measurement_confirm"): return
        pending = self._pending_measurement
        self.measurement_confirm.setEnabled(pending is not None)
        self.measurement_cancel.setEnabled(pending is not None)
        if pending is not None:
            values = pending["values"]
            label = "选点："
            if pending.get("purpose")=="data_limits":
                label=f"数据界限：{values['start_x']:.6g} 至 {values['stop_x']:.6g}"
            elif pending.get('purpose')=='delete_peak':label='删除峰：选择已有峰积分范围内的点'
            elif pending["kind"] in ("alpha_at_x","alpha_secant","alpha_fit"):label=f"Alpha {values['alpha']:.6g} µm/m/°C"
            elif pending['kind']=='slope':label=values.get('fit_error',f"斜率 {values.get('slope',0):.6g} {values.get('slope_unit','')}")
            elif pending['kind'] in INTEGRATION_KINDS:label=values.get('fit_error',f"峰面积 {values.get('integral',0):.6g} {values.get('area_unit','')}")
            elif pending['kind'] in ('peak_max','onset_point'):
                label=values.get('fit_error','峰最大' if pending['kind']=='peak_max' else '始点')
            elif pending['kind'] in ('step_transition','glass_transition'):
                label=values.get('fit_error',f"转变：{values.get('onset_x',0):.6g} 至 {values.get('end_x',0):.6g}")
            elif pending["kind"] in CURVE_VALUE_KINDS:label=f"选点：X {values['start_x']:.6g}，Y {values['start_y']:.6g}"
            elif "change" in values:
                prefix = dict(temperature="T", time="t", signal="X")[pending["domain"]]
                label += f"{prefix}1 {values['start_x']:.2f}，{prefix}2 {values['stop_x']:.2f}，H {values['change']:.6g}"
            else: label += f"{dict(temperature='温度', time='时间', signal='X')[pending['domain']]} {values['max_x']:.2f}"
            self.statusBar().showMessage(label + "；右键：确定 / 编辑 / 取消")

    def confirm_measurement(self):
        entry = self._pending_measurement
        if entry is None: return
        if entry['kind']=='slope':
            from .slope import values as compute
            curve=next(c for c in self.curves if c.uid==entry['curve_id'])
            try:
                entry['values'].update(compute(curve,entry,entry['interactive'].get('positions',entry['interactive']['indices'])))
                entry['values'].pop('fit_error',None)
            except ValueError as exc:self.statusBar().showMessage(str(exc),8000);return
        if entry['kind'] in INTEGRATION_KINDS:
            from .peak_integration import values as compute
            curve=next(c for c in self.curves if c.uid==entry['curve_id'])
            try:
                entry['values'].update(compute(curve,entry,entry['interactive'].get('positions',entry['interactive']['indices'])))
                entry['values'].pop('fit_error',None)
                entry['values'].pop('sigmoid_failure',None)
            except ValueError as exc:self.statusBar().showMessage(str(exc),8000);return
        if entry['kind'] in ('peak_max','onset_point'):
            from .peak_onset import values as compute
            curve=next(c for c in self.curves if c.uid==entry['curve_id'])
            try:
                entry['values'].update(compute(curve,entry,entry['interactive'].get('positions',entry['interactive']['indices'])))
                entry['values'].pop('fit_error',None)
            except ValueError as exc:self.statusBar().showMessage(str(exc),8000);return
        if entry['kind'] in ('step_transition','glass_transition'):
            from .transitions import values as transition_values
            curve=next(c for c in self.curves if c.uid==entry['curve_id'])
            try:
                entry['values'].update(transition_values(curve,entry,entry['interactive'].get('positions',entry['interactive']['indices'])))
                entry['values'].pop('fit_error',None)
            except ValueError as exc:self.statusBar().showMessage(str(exc),8000);return
        entry["interactive"]["confirmed"] = True
        index = next((i for i, original in enumerate(self.results) if original is self._editing_measurement), None)
        if index is not None: self.results[index] = entry
        else: self.results.append(entry)
        self._pending_measurement = self._editing_measurement = None
        self._drag_measurement = self._drag_annotation = None
        self._update_measurement_controls()
        self.touch(); self.refresh_results(); self.redraw()
        self.statusBar().showMessage("分析已确定。温度和高度文字可单独拖动。")

    def cancel_measurement(self, redraw=True):
        pending = self._pending_measurement
        self._pending_measurement = self._editing_measurement = None
        self._drag_measurement = self._drag_annotation = None
        self._update_measurement_controls()
        if pending is not None and redraw: self.redraw()

    def edit_measurement(self, entry=None):
        if entry is None:
            entry = next((editor.entry for editor in reversed(self._measurement_artists) if any(editor.entry is result for result in self.results)), None)
        if entry is None: return
        self.cancel_measurement(redraw=False)
        self._editing_measurement = entry
        self._pending_measurement = deepcopy(entry)
        self._pending_measurement["interactive"]["confirmed"] = False
        self.range_enabled.setChecked(False)
        if self.toolbar.mode:
            if "pan" in str(self.toolbar.mode).lower(): self.toolbar.pan()
            else: self.toolbar.zoom()
        self._update_measurement_controls(); self.redraw()
        for editor in self._measurement_artists:
            if editor.entry is self._pending_measurement: editor.update(active=0)
        self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def process(self, kind):
        c = self.selected()
        if c is None:
            return
        try:
            c.xy(self.domain)
            x = c.x_values(self.domain,canonical=True)
            y = c.base_y if c.working is None else c.working
            if c.derived is not None and kind=='smooth':raise ValueError('积分曲线不能平滑')
            if kind in ("smooth","derivative") and np.any(np.diff(c.active_rows)!=1):raise ValueError("请先选择单一连续采集片段再处理信号")
            reset_y=c.derived is None and c.reset_time and c.y_index==c.dataset.time_index and not any(op=="normalize" or op.startswith("derivative:") for op in c.operations)
            input_y=y[c.active_rows]-(c.time_origin if reset_y else 0.)
            processed = process_signal(x, input_y, kind, parameter=self.smooth_window.value())
            if reset_y and kind=="smooth":processed+=c.time_origin
            c.checkpoint()
            c.working = y.astype(float).copy();c.working[c.active_rows]=processed
            c.working_rows=deepcopy(c.data_indices);c.smooth_source_rows=None
            c.y_type = "custom"
            c.smooth_domain,c.smooth_width,c.smooth_reuse,c.smooth_source,c.smooth_base_ops,c.smooth_x_config=None,0.,False,None,[],None
            from .signal_processing import type_label
            canonical_label=type_label(c.dataset,c.x_signal_index,c.x_signal_type)[0] if self.domain=="signal" else c.dataset.signals[c.dataset.time_index if self.domain=="time" else c.dataset.temperature_index].label
            c.operations.append(f"derivative:{canonical_label}" if kind == "derivative" else (f"smooth:{self.smooth_window.value()}" if kind == "smooth" else kind))
            self.touch()
            self.selection_changed()
        except Exception as exc:
            self.warn(str(exc))

    def undo(self):
        c = self.selected()
        if c and c.history:
            c.undo()
            self.touch()
            self.selection_changed()

    def reset_curve(self):
        c = self.selected()
        if c:
            c.checkpoint()
            c.working = None
            c.operations = []
            c.working_rows,c.smooth_source_rows=None,None
            c.y_type, c.smooth_width = "normal", 0.
            c.smooth_domain,c.smooth_reuse,c.smooth_source,c.smooth_base_ops,c.smooth_x_config=None,False,None,[],None
            c.x_shift, c.scale, c.offset = 0., 1., 0.
            self.touch()
            self.selection_changed()

    def save(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存完整会话（内嵌数据）", str(self.session_path or "未命名.tmas"), "TMA Studio 会话 (*.tmas)")
        if not path:
            return False
        try:
            if Path(path).suffix.lower() != ".tmas":
                path += ".tmas"
            self.protect_output(path)
            save_session(path, self.curves, self.domain, self.results, plot_options=self.plot_options)
            self.session_path = Path(path)
            self.dirty = False
            self.setWindowTitle(f"TMA Studio {__version__}  ·  {Path(path).name}")
            self.statusBar().showMessage(f"会话已保存：{path}")
            return True
        except Exception as exc:
            self.warn(str(exc))
            return False

    def confirm_discard(self):
        if not self.dirty:
            return True
        answer = QMessageBox.question(self, "保存当前会话", "当前工作尚未保存。是否先保存会话？", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    def open_session(self):
        if self.worker is not None:
            self.warn("正在导入数据，请等待完成后打开会话。")
            return
        path, _ = QFileDialog.getOpenFileName(self, "打开会话", "", "TMA Studio 会话 (*.tmas)")
        if not path or not self.confirm_discard():
            return
        self.restore_session(path)

    def restore_session(self, path):
        try:
            curves, domain, results, plot_options = load_session(path, include_plot_options=True)
            self.cancel_measurement(redraw=False)
            self.curves, self.domain, self.results = curves, domain, results
            self.plot_options = plot_options
            self.domain_box.blockSignals(True)
            self.domain_box.setCurrentIndex(("temperature", "time", "signal").index(domain))
            self.domain_box.blockSignals(False)
            self.rebuild_files()
            if self.curves:
                self.files.setCurrentItem(self.files.topLevelItem(0))
            self.refresh_results()
            self.redraw()
            self.session_path = Path(path)
            self.dirty = False
            self.setWindowTitle(f"TMA Studio {__version__}  ·  {Path(path).name}")
        except Exception as exc:
            self.warn(f"会话未打开：{exc}")

    def export_plot(self, preferred=None):
        visible = self.visible_curves()
        curve = self.selected()
        if curve not in visible: curve = visible[0] if visible else None
        extension = "pdf" if preferred == "pdf" else "png"
        default = (curve.dataset.path.stem if curve else "TMA") + "." + extension
        filters = "PDF (*.pdf)" if extension == "pdf" else "PNG (*.png);;SVG (*.svg);;PDF (*.pdf);;TIFF (*.tif)"
        path, _ = QFileDialog.getSaveFileName(self, "导出图像", default, filters)
        if path:
            try:
                self.protect_output(path)
                self.write_plot(path)
                self.statusBar().showMessage(f"图像已导出：{path}")
            except Exception as exc:
                self.warn(str(exc))

    def write_plot(self, path):
        self.protect_output(path)
        suffix = Path(path).suffix.lower()
        metadata = {".png": {"Author": "Power By ZzzHe", "Software": "Power By ZzzHe"},
                    ".svg": {"Creator": "Power By ZzzHe"},
                    ".pdf": {"Author": "Power By ZzzHe", "Creator": "Power By ZzzHe"}}
        options = {"metadata": metadata[suffix]} if suffix in metadata else {}
        # Expand the full page instead of using a tight crop, so headers and
        # annotations keep their positions with an extra white border outside.
        self.figure.savefig(path, dpi=300, facecolor="white",
                            bbox_inches=self.figure.bbox_inches.padded(0.25), **options)

    def write_data(self, path, curve):
        self.protect_output(path, str(path) + ".meta.json")
        x, y = curve.xy(self.domain)
        display_offset=self.display_x_offset(curve);x=x+display_offset
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow([s.label for s in curve.logical_dataset.signals] + [f"display_x:{self.domain}", f"display_y:{curve.result_label}"])
            writer.writerows(np.column_stack((curve.logical_dataset.values[curve.active_rows], x, y)).tolist())
        sidecar = Path(str(path) + ".meta.json")
        from .file_information import snapshot
        sidecar.write_text(json.dumps({"file_information":snapshot(curve),"source": str(curve.dataset.path), "sha256": curve.dataset.sha256, "metadata": curve.dataset.metadata,
                                      "warnings": curve.dataset.warnings, "operations": curve.operations, "domain": self.domain,
                                      "transform": curve.result_transform(self.domain),"derived":curve.derived,"presentation":{"x_offset":display_offset}}, ensure_ascii=False, indent=2), encoding="utf-8")

    def export_data(self):
        c = self.selected()
        if not c:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出原始信号与当前曲线", c.dataset.path.stem + "-data.csv", "CSV (*.csv)")
        if path:
            try:
                self.write_data(path, c)
                self.statusBar().showMessage(f"已导出数据与参数旁文件：{path}")
            except Exception as exc:
                self.warn(str(exc))

    def write_results(self, path):
        self.protect_output(path)
        keys = ["file", "sha256", "curve_id", "analysis_id", "kind", "domain", "lo", "hi", "signal", "axis", "operations", "transform", "reference_length_mm", "transition", "peak_onset", "integration", "sigmoid", "auto_limits", "values", "interactive", "annotation"]
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=keys)
            writer.writeheader()
            for row in self.results:
                writer.writerow({k: json.dumps(row.get(k), ensure_ascii=False) if isinstance(row.get(k), (dict, list)) else row.get(k) for k in keys})

    def export_results(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出分析结果", "TMA-results.csv", "CSV (*.csv)")
        if path:
            try:
                self.write_results(path)
            except Exception as exc:
                self.warn(str(exc))

    def write_report(self, path):
        self.protect_output(path)
        import base64
        from .file_information import snapshot
        from html import escape
        from io import BytesIO
        buffer = BytesIO()
        self.figure.savefig(buffer, format="png", dpi=160, facecolor="white")
        image = base64.b64encode(buffer.getvalue()).decode("ascii")
        payload = escape(json.dumps(self.results, ensure_ascii=False, indent=2))
        sources = "".join(f"<h3>{escape(c.dataset.path.name)} · {escape(c.result_label)}</h3><pre>{escape(json.dumps({'sha256':c.dataset.sha256,'metadata':c.dataset.metadata,'file_information':snapshot(c),'warnings':c.dataset.warnings,'derived':c.derived}, ensure_ascii=False,indent=2))}</pre>" for c in self.curves)
        Path(path).write_text(f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>TMA Studio 报告</title><style>body{{max-width:1100px;margin:40px auto;font:14px sans-serif;color:#25334a}}img{{width:100%}}pre{{white-space:pre-wrap;background:#f4f6fa;padding:18px}}h1{{color:#2469d9}}@media print{{pre{{break-inside:avoid}}}}</style><h1>TMA Studio · 分析报告</h1><p>版本 {__version__} · 分析方法为独立实现。原生峰积分对记录时间积分；旧通用积分使用当前X。基线、始点方法和未验证项见各结果参数。</p><img src="data:image/png;base64,{image}"><h2>分析结果与参数</h2><pre>{payload}</pre><h2>原始数据与实验方法</h2>{sources}</html>', encoding="utf-8")

    def export_report(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出可打印报告", "TMA-report.html", "HTML (*.html)")
        if path:
            try:
                self.write_report(path)
                self.statusBar().showMessage(f"报告已导出，可用浏览器打印 PDF：{path}")
            except Exception as exc:
                self.warn(str(exc))

    def about(self):
        QMessageBox.information(self, "关于 TMA Studio", f"TMA Studio {__version__}\nPython + PySide6 (Qt) + Matplotlib\n\n独立实现的热分析工作台。支持已验证的 TA TMA 二进制与 StartOfData 文本。\n保留原始采集顺序；区间拟合/求导不自动排序升降温分支。\n\n斜率：最小二乘直线拟合。\n积分：支持直线／水平S形基线；原生峰积分使用记录时间，不直接作为焓。\nCTE：斜率(µm/°C) / 长度(mm) × 1000 ppm/K。\nOnset：区间前段基线与最大绝对斜率附近切线交点，需人工核对。\n\n尚未实现原 UA 的专用 DSC/TGA/DMA 分析、旧会话/宏兼容。")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.import_files(paths)

    def closeEvent(self, event):
        if self.worker is not None:
            self.warn("正在导入文件，请等待完成后关闭。")
            event.ignore()
        elif self.confirm_discard():
            event.accept()
        else:
            event.ignore()


def main():
    verify_mode = len(sys.argv) > 2 and sys.argv[1] == "--verify-launch"
    if verify_mode:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication(sys.argv)
    application.setApplicationName("TMA Studio")
    application.setOrganizationName("TMA-New")
    application.setStyle("Fusion")
    if "--modern" in sys.argv:
        application.setStyleSheet(STYLE)
        window = MainWindow()
    else:
        from .classic import ClassicMainWindow, CLASSIC_STYLE
        application.setStyleSheet(CLASSIC_STYLE)
        window = ClassicMainWindow()
    if "--modern" not in sys.argv and not verify_mode:
        window.showMaximized()
    else:
        window.show()
    if verify_mode:
        output = Path(sys.argv[2])
        try:
            if "--modern" not in sys.argv:
                window.resize(1920, 1017)
            window.warn = lambda message: (_ for _ in ()).throw(ValueError(message))
            inputs = [Path(arg) for arg in sys.argv[3:]]
            session_check = len(inputs) == 1 and inputs[0].suffix.casefold() == ".tmas"
            checked_dialogs = []
            def capture_verify_state():
                return dict(curve_objects=list(window.curves),curves={c.uid:dict(vars(c)) for c in window.curves},plots=deepcopy(window.plot_options),results=list(window.results),
                    undo=dict(window._limits_undo),selected=window.selected().uid if window.selected() else None,document=window.active_document(),domain=window.domain)
            def restore_verify_state(state):
                window.cancel_measurement(redraw=False)
                window.curves[:]=state['curve_objects']
                for curve in window.curves:
                    original=state['curves'][curve.uid];vars(curve).clear();vars(curve).update(original)
                window.plot_options.clear();window.plot_options.update(state['plots']);window.results[:]=state['results'];window._limits_undo=state['undo']
                window.domain=state['domain'];window.domain_box.blockSignals(True)
                window.domain_box.setCurrentIndex({'temperature':0,'time':1,'signal':2}[state['domain']]);window.domain_box.blockSignals(False)
                window._show_document(state['document'].key);window.rebuild_files()
                if state['selected'] is not None:window.files.setCurrentItem(window.files.topLevelItem(next(i for i,c in enumerate(window.curves) if c.uid==state['selected'])))
                window.refresh_results();window.redraw();window.canvas.draw()
            if session_check:
                window.restore_session(inputs[0])
                if hasattr(window, "show_overlay_options"):
                    dialog = window.show_overlay_options()
                    application.processEvents()
                    dialog.grab().save(str(output.with_suffix(".options.png")))
                    dialog.tabs.setCurrentIndex(5); application.processEvents()
                    dialog.grab().save(str(output.with_suffix(".auto_styles.png")))
                    dialog.tabs.setCurrentIndex(3); application.processEvents()
                    dialog.grab().save(str(output.with_suffix(".legend_options.png")))
                    dialog.reject(); checked_dialogs.append("overlay_options")
                    auto = window.auto_configure_overlay(); application.processEvents()
                    auto.grab().save(str(output.with_suffix(".auto_configure.png")))
                    auto.reject(); checked_dialogs.append("auto_configure")
                    for kind in ("signal_max", "signal_change"):
                        dialog = window.signal_analysis_dialog(kind)
                        application.processEvents()
                        dialog.grab().save(str(output.with_suffix(f".{kind}.png")))
                        dialog.reject(); checked_dialogs.append(kind)
                    dialog = window.manual_rescale("x")
                    application.processEvents()
                    dialog.grab().save(str(output.with_suffix(".rescale.png")))
                    dialog.reject(); checked_dialogs.append("rescale")
                    window.show_normal()
                    dialog = window.show_native_signals(); application.processEvents()
                    dialog.grab().save(str(output.with_suffix(".signals.png")))
                    if len(dialog.signals) != 4 or dialog.types[0].model().item(1).isEnabled():
                        raise ValueError("打包程序信号窗口控件不完整")
                    dialog.reject(); checked_dialogs.append("signals")
                    dialog = window.show_curve_options(); application.processEvents()
                    dialog.grab().save(str(output.with_suffix(".graph_options.png")))
                    dialog.reject(); checked_dialogs.append("graph_options")
                    curve=window.current_data_curve()
                    before=(None if curve.working is None else curve.working.copy(),list(curve.operations),curve.smooth_width)
                    dialog=window.show_native_smooth();application.processEvents()
                    dialog.width_edit.setText("0.2" if dialog.units.text()=="min" else "5")
                    dialog.grab().save(str(output.with_suffix(".smooth.png")))
                    dialog.accept()
                    if dialog.result()!=QDialog.DialogCode.Accepted:raise ValueError("打包程序物理平滑失败："+dialog.error.text())
                    if curve.working is None:raise ValueError("打包程序物理平滑未生成信号")
                    window.undo()
                    if curve.operations!=before[1] or curve.smooth_width!=before[2]:raise ValueError("打包程序平滑撤销未恢复设置")
                    if before[0] is None:
                        if curve.working is not None:raise ValueError("打包程序平滑撤销未恢复原始信号")
                    elif not np.array_equal(curve.working,before[0]):raise ValueError("打包程序平滑撤销改变原处理数据")
                    checked_dialogs.append("physical_smooth_and_undo")
                    for kind in (None,"time","temperature"):
                        dialog=window.show_data_limits(kind);application.processEvents()
                        label=kind+"_limits" if kind else "data_limits"
                        dialog.grab().save(str(output.with_suffix("."+label+".png")))
                        dialog.reject();checked_dialogs.append(label)
                    # Exercise actual cursor data selection in the frozen app,
                    # then undo it before running the archived-result checks.
                    curve=window.current_data_curve();cursor_uid=curve.uid
                    original_rows=curve.active_rows.copy();original_results=deepcopy(window.results)
                    cursor_count=len(original_rows)
                    pending=window.graphic_range()
                    if pending is None:raise ValueError("打包程序未启动光标数据界限")
                    first,last=cursor_count//4,3*cursor_count//4
                    pending["interactive"]["indices"]=[first,last];window.redraw()
                    application.processEvents();window.canvas.draw()
                    window.grab().save(str(output.with_suffix(".graphic_limits.png")))
                    window.create_measurement_menu().actions()[0].trigger()
                    curve=window.selected()
                    if (window._pending_measurement is not None or curve.uid!=cursor_uid
                            or not np.array_equal(curve.active_rows,original_rows[first:last+1])
                            or window.results!=original_results):raise ValueError("打包程序光标数据界限未正确确定")
                    window.undo()
                    if not np.array_equal(window.selected().active_rows,original_rows):raise ValueError("打包程序光标界限撤销失败")
                    checked_dialogs.append("graphic_data_limits_and_undo")
                    from .overlay_views import snapshot
                    source_key=next(key for key in window.documents if window._is_overlay(key))
                    source_document=window._show_document(source_key)
                    baseline=[snapshot(c) for c in window._document_curves(source_document)]
                    source_uids=list(source_document.curve_uids or [])
                    window.update_overlay_copy_menu()
                    copy_menu=window.classic_actions["Copy4"].menu()
                    copy_action=next(a for a in copy_menu.actions() if a.isVisible() and a.data()==source_key)
                    copy_action.trigger();copied=window.active_document()
                    if copied is None or copied.key==source_key or copied.curve_uids!=source_uids:raise ValueError("打包程序叠图复制失败")
                    visible=window.visible_curves()
                    if visible:
                        visible[0].color="#ff00ff";visible[0].overlay_offset+=3;visible[0].visible=False
                    window.redraw();application.processEvents()
                    window.grab().save(str(output.with_suffix(".overlay_copy.png")))
                    window._show_document(source_key)
                    if [snapshot(c) for c in window._document_curves(source_document)]!=baseline:raise ValueError("打包程序叠图副本串改源窗口")
                    copied.close()
                    if copied.key in window.documents or copied.key in window.plot_options:raise ValueError("打包程序关闭叠图副本失败")
                    checked_dialogs.append("independent_overlay_copy_menu_and_close")
                    saved_offsets=list(window.plot_options[source_key]["axis_x_offsets"])
                    saved_results=deepcopy(window.results)
                    dialog=window.show_overlay_options();dialog.tabs.setCurrentIndex(1)
                    dialog.axis_x_offsets[0].setText(str(saved_offsets[0]+1.25))
                    application.processEvents();dialog.grab().save(str(output.with_suffix(".axis_x_offsets.png")))
                    dialog.accept()
                    if dialog.result()!=QDialog.DialogCode.Accepted:raise ValueError("打包程序X偏移未应用："+dialog.error.text())
                    for item in window.visible_curves():
                        line=next(line for line in window.axes[item.axis].lines if getattr(line,"_tma_curve_uid",None)==item.uid)
                        finite=np.asarray(line.get_xdata())[np.isfinite(line.get_xdata())]
                        if not np.allclose(finite,item.xy(window.domain)[0]+window.display_x_offset(item)):raise ValueError("打包程序X偏移绘图不一致")
                    if window.results!=saved_results:raise ValueError("打包程序显示X偏移改变了分析数值")
                    window.plot_options[source_key]["axis_x_offsets"]=saved_offsets
                    window.selection_changed();window.redraw()
                    checked_dialogs.append("overlay_axis_x_offsets")
                    window._show_document(source_key)
                    target=window.current_data_curve()
                    window.files.setCurrentItem(window.files.topLevelItem(next(i for i,c in enumerate(window.curves) if c.uid==target.uid)))
                    before_count=len(window.results);before_uid=target.uid
                    window.classic_actions["CurveValueAtX1"].trigger()
                    value_entry=window._pending_measurement
                    if value_entry is None or value_entry["kind"]!="curve_value":raise ValueError("打包程序曲线值菜单未启动选点")
                    window.create_measurement_menu().actions()[0].trigger()
                    label=window.dialogs["label_point"];application.processEvents()
                    label.grab().save(str(output.with_suffix(".label_point.png")))
                    if len(window.results)!=before_count or label.boxes["multiplex"].isEnabled():raise ValueError("打包程序曲线值确认阶段或通道状态不正确")
                    label.boxes["arrow"].setChecked(False);label.boxes["cross"].setChecked(True)
                    label.boxes["border"].setChecked(True);label.boxes["transparent"].setChecked(False);label.accept()
                    if (window._pending_measurement is not None or len(window.results)!=before_count+1
                            or window.selected().uid!=before_uid):raise ValueError("打包程序曲线值未正确记录或改变了文件选择")
                    value_artist=next(item for item in window._measurement_artists if item.entry is value_entry)
                    if ("Y =" not in value_artist.annotation.get_text() or value_artist.annotation.arrow_patch.get_visible()
                            or value_artist.annotation.get_bbox_patch() is None):raise ValueError("打包程序标记点外观未应用")
                    window.results[:]=[entry for entry in window.results if entry is not value_entry]
                    window.refresh_results();window.redraw();checked_dialogs.append("curve_value_label_point")
                    window.classic_actions['CurveValueAtY1'].trigger()
                    y_entry=window._pending_measurement
                    if y_entry is None or y_entry['kind']!='curve_value_y':raise ValueError('Y curve-value menu did not start its cursor')
                    horizontal=next(e for e in window._measurement_artists if e.entry is y_entry)
                    if not horizontal.hline.get_visible() or horizontal.vline.get_visible():raise ValueError('Y cursor is not horizontal')
                    manual=window.edit_measurement_limits();application.processEvents()
                    if not manual.fields[0].isReadOnly() or manual.y_fields[0].isReadOnly():raise ValueError('Y cursor manual coordinate editability is reversed')
                    manual.accept()
                    if manual.result()!=QDialog.DialogCode.Accepted:raise ValueError('Y cursor manual coordinates failed')
                    window.confirm_measurement();window.dialogs['label_point'].accept()
                    if window._pending_measurement is not None or window.selected().uid!=before_uid:raise ValueError('Y cursor confirmation changed the file')
                    window.results[:]=[entry for entry in window.results if entry is not y_entry]
                    window.refresh_results();window.redraw();checked_dialogs.append('curve_value_at_y')
                    # Native Alpha routes use a known QA size, never infer it from a curve.
                    from .alpha_dialogs import SampleSizeDialog
                    alpha_before=capture_verify_state()
                    window.domain_box.setCurrentIndex(0)
                    from .alpha import check_curve
                    alpha_target=None
                    for candidate in window.visible_curves():
                        try:check_curve(candidate,window.domain)
                        except ValueError:continue
                        alpha_target=candidate;break
                    if alpha_target is None:raise ValueError('No visible dimension curve is eligible for Alpha verification')
                    window.files.setCurrentItem(window.files.topLevelItem(next(i for i,c in enumerate(window.curves) if c.uid==alpha_target.uid)))
                    size=SampleSizeDialog(window,alpha_target,'alpha_fit');size.show();application.processEvents()
                    size.grab().save(str(output.with_suffix('.sample_size.png')))
                    size.field.setText('2.5');size.accept()
                    if window._pending_measurement is None or window._pending_measurement['kind']!='alpha_fit':raise ValueError('Sample size entry did not start Alpha')
                    window.cancel_measurement();checked_dialogs.append('alpha_sample_size')
                    options=window.show_analysis_options();application.processEvents()
                    options.grab().save(str(output.with_suffix('.analysis_options.png')))
                    if options.controls['CorrectedSizeBox'].isEnabled():raise ValueError('Unsupported corrected-size analysis option is active')
                    options.width_field.setText('4.5');options.accept();checked_dialogs.append('alpha_analysis_options')
                    alpha_entries=[]
                    for name,kind in (('AlphaAtX1','alpha_at_x'),('AlphaX1ToX21','alpha_secant'),('AlphaFitX1ToX21','alpha_fit')):
                        window.classic_actions[name].trigger();pending=window._pending_measurement
                        if pending is None or pending['kind']!=kind:raise ValueError('Alpha menu route did not start the expected analysis')
                        manual=window.edit_measurement_limits();application.processEvents()
                        if not manual.y_fields[0].isReadOnly():raise ValueError('Alpha manual Y must follow the curve')
                        manual.accept()
                        if manual.result()!=QDialog.DialogCode.Accepted:raise ValueError('Alpha manual limits failed')
                        window.create_measurement_menu().actions()[0].trigger()
                        if window._pending_measurement is not None or window.selected().uid!=alpha_target.uid:raise ValueError('Alpha confirmation changed its file or remained pending')
                        if not np.isfinite(pending['values']['alpha']):raise ValueError('Alpha did not produce a finite coefficient')
                        alpha_entries.append(pending)
                    restore_verify_state(alpha_before);checked_dialogs.append('alpha_three_menu_analyses')
                    info_target=window.current_data_curve();info_doc=window.active_document()
                    info_before=capture_verify_state();info_results=list(window.results)
                    info_ids={c.uid for c in window.curves if c.dataset.path==info_target.dataset.path}
                    window.classic_actions['FileInformation1'].trigger();info=window.dialogs['file_information'];application.processEvents()
                    info.grab().save(str(output.with_suffix('.file_information.png')))
                    info.fields['Sample'].setText('Windows file information QA');info.accept()
                    if (info.result()!=QDialog.DialogCode.Accepted or info_target.sample_name!='Windows file information QA'
                            or window.active_document() is not info_doc or len(window.results)!=len(info_results)):raise ValueError('File information text edit lost its file or analyses')
                    from .file_information import effective_size
                    info_new_size=3.25 if effective_size(info_target)==2.75 else 2.75
                    info=window.show_file_information();info.size_field.setText(str(info_new_size));info.accept()
                    if (info.result()!=QDialog.DialogCode.Accepted or info_target.sample_size_mm!=info_new_size or info_target.working is not None
                            or any(r.get('curve_id') in info_ids for r in window.results)):raise ValueError('File information numeric edit did not reread and clear its analyses')
                    restore_verify_state(info_before);checked_dialogs.append('native_file_information_edit_and_reload')
                    units_before=capture_verify_state()
                    buffers={c.uid:None if c.working is None else c.working.copy() for c in window.curves}
                    window.classic_actions['Units1'].trigger();units=window.dialogs['units'];application.processEvents()
                    units.grab().save(str(output.with_suffix('.units.png')))
                    if not units.controls['TemperatureCombo'].isEnabled():raise ValueError('Supported temperature-unit control is disabled')
                    if units.controls['FrequencyCombo'].isEnabled():raise ValueError('Unsupported frequency-unit control is enabled')
                    target_unit='µm' if units.dimension.currentData()=='mm' else 'mm'
                    units.dimension.setCurrentIndex(units.dimension.findData(target_unit));units.offset.setCurrentIndex(0);units.accept()
                    if units.result()!=QDialog.DialogCode.Accepted:raise ValueError('Native TMA units selection did not apply')
                    for curve in window.curves:
                        before=buffers[curve.uid]
                        if (before is None and curve.working is not None) or (before is not None and not np.array_equal(before,curve.working)):raise ValueError('Unit conversion modified canonical working data')
                    window.canvas.draw();window.grab().save(str(output.with_suffix('.units_applied.png')))
                    restore_verify_state(units_before);checked_dialogs.append('native_tma_units_and_buffer_preservation')
                    general_before=capture_verify_state()
                    overlays=[d for key,d in window.documents.items() if window._is_overlay(key)]
                    general_doc=max(overlays,key=lambda d:len(window._document_curves(d))) if overlays else window.active_document()
                    window._show_document(general_doc.key)
                    units=window.show_units();application.processEvents()
                    units.general['time'].setCurrentIndex(units.general['time'].findData('sec'))
                    units.general['temperature'].setCurrentIndex(units.general['temperature'].findData('°F'))
                    units.grab().save(str(output.with_suffix('.general_units.png')));units.accept()
                    if units.result()!=QDialog.DialogCode.Accepted:raise ValueError('Native general-unit conversion failed: '+units.error.text())
                    for curve in window._document_curves(general_doc):
                        if curve.overlay_enabled if window._is_overlay(general_doc.key) else curve.normal_enabled:
                            if curve.x_unit('time')!='sec' or curve.x_unit('temperature')!='°F':raise ValueError('General unit labels were not propagated')
                    for curve in window.curves:
                        before=buffers[curve.uid]
                        if (before is None and curve.working is not None) or (before is not None and not np.array_equal(before,curve.working)):raise ValueError('General conversion modified canonical working data')
                    window.canvas.draw();window.grab().save(str(output.with_suffix('.general_units_applied.png')))
                    restore_verify_state(general_before);checked_dialogs.append('native_time_temperature_units')
                    transition_before=capture_verify_state()
                    from .transitions import defaults as transition_defaults,values as transition_values
                    transition_target=None
                    for candidate in window.curves:
                        if not candidate.normal_enabled or candidate.y_type!='normal':continue
                        window._show_document(str(candidate.dataset.path))
                        window.files.setCurrentItem(window.files.topLevelItem(window.curves.index(candidate)))
                        config=transition_defaults();config['midpoint']='half_width'
                        positions=initial_indices(candidate,window.domain,'glass_transition',config)
                        try:expected=transition_values(candidate,dict(kind='glass_transition',domain=window.domain,transition=config),positions)
                        except ValueError:continue
                        transition_target=candidate;break
                    if transition_target is None:raise ValueError('No valid source curve for native transition gate')
                    options=window.show_analysis_options();options.tabs.setCurrentIndex(0)
                    options.controls['ManualStepBox'].setChecked(False);options.midpoint.setCurrentIndex(options.midpoint.findData('half_width'))
                    options.grab().save(str(output.with_suffix('.step_options.png')));options.accept()
                    if options.result()!=QDialog.DialogCode.Accepted:raise ValueError('Native Step/Change page did not apply')
                    checked_dialogs.append('native_step_change_options')
                    window.classic_actions['GlassTransition1'].trigger();automatic=window._pending_measurement
                    if automatic is None or 'fit_error' in automatic['values']:raise ValueError('Automatic glass transition did not fit')
                    window.create_measurement_menu().actions()[0].trigger()
                    if window._pending_measurement is not None:raise ValueError('Automatic glass transition did not confirm')
                    window.canvas.draw();window.grab().save(str(output.with_suffix('.glass_auto.png')))
                    checked_dialogs.append('native_glass_auto_three_tangents')
                    options=window.show_analysis_options();options.controls['ManualStepBox'].setChecked(True);options.accept()
                    window.classic_actions['StepTransition2'].trigger();manual_entry=window._pending_measurement
                    manual=window.edit_measurement_limits();tx=transition_target.xy(window.domain)[0]
                    if len(manual.fields)!=6 or not all(field.isReadOnly() for field in manual.y_fields):raise ValueError('Six-point manual limits were not available')
                    for field,position in zip(manual.fields,[fit[key] for fit in automatic['values']['fits'] for key in ('position_start','position_stop')]):
                        field.setText(format(float(np.interp(position,np.arange(len(tx)),tx)),'.17g'))
                    manual.grab().save(str(output.with_suffix('.six_limits.png')));manual.accept()
                    if manual.result()!=QDialog.DialogCode.Accepted:raise ValueError('Six-point manual limits failed: '+manual.error.text())
                    window.create_measurement_menu().actions()[-1].trigger()
                    if manual_entry['interactive']['active_point']!=5:raise ValueError('Sixth marker was not selectable')
                    window.create_measurement_menu().actions()[0].trigger()
                    if window._pending_measurement is not None or not np.isclose(manual_entry['values']['onset_x'],automatic['values']['onset_x']):raise ValueError('Manual tangent result did not confirm or match its intervals')
                    window.canvas.draw();window.grab().save(str(output.with_suffix('.step_manual.png')))
                    checked_dialogs.append('native_step_six_marker_manual')
                    restore_verify_state(transition_before)
                    peak_before=capture_verify_state()
                    window._show_document(str(transition_target.dataset.path))
                    window.files.setCurrentItem(window.files.topLevelItem(window.curves.index(transition_target)))
                    options=window.show_analysis_options();options.tabs.setCurrentIndex(1)
                    options.controls['ManualOnsetBox'].setChecked(False);options.controls['InflectionBox'].setChecked(True)
                    options.grab().save(str(output.with_suffix('.peak_options.png')));options.accept()
                    if options.result()!=QDialog.DialogCode.Accepted:raise ValueError('Native Peak/Onset page did not apply')
                    checked_dialogs.append('native_peak_onset_options')
                    window.classic_actions['PeakMax1'].trigger();peak=window._pending_measurement
                    if peak is None or 'fit_error' in peak['values']:raise ValueError('Baseline-relative peak did not fit')
                    auto_limits=window.show_auto_limits();application.processEvents()
                    auto_limits.auto_set();auto_limits.grab().save(str(output.with_suffix('.peak_auto_limits.png')));auto_limits.accept()
                    if auto_limits.result()!=QDialog.DialogCode.Accepted:raise ValueError('Peak automatic limits failed: '+auto_limits.error.text())
                    window.create_measurement_menu().actions()[0].trigger()
                    if window._pending_measurement is not None or window.selected().uid!=transition_target.uid:raise ValueError('Peak confirmation changed its file')
                    checked_dialogs.extend(['native_peak_auto_limits','native_baseline_peak_maximum'])
                    window.classic_actions['OnsetPoint1'].trigger();onset=window._pending_measurement
                    if onset is None or 'fit_error' in onset['values']:raise ValueError('Automatic onset did not fit')
                    window.create_measurement_menu().actions()[0].trigger()
                    if window._pending_measurement is not None:raise ValueError('Automatic onset did not confirm')
                    checked_dialogs.append('native_two_marker_onset')
                    options=window.show_analysis_options();options.controls['ManualOnsetBox'].setChecked(True);options.accept()
                    window.classic_actions['OnsetPoint1'].trigger();manual_onset=window._pending_measurement
                    manual=window.edit_measurement_limits()
                    if len(manual.fields)!=4 or not all(field.isReadOnly() for field in manual.y_fields):raise ValueError('Four-point manual onset limits were not available')
                    for field,position in zip(manual.fields,[fit[key] for fit in automatic['values']['fits'][:2] for key in ('position_start','position_stop')]):
                        field.setText(format(float(np.interp(position,np.arange(len(tx)),tx)),'.17g'))
                    manual.grab().save(str(output.with_suffix('.four_onset_limits.png')));manual.accept()
                    if manual.result()!=QDialog.DialogCode.Accepted:raise ValueError('Four-point onset limits failed: '+manual.error.text())
                    window.create_measurement_menu().actions()[0].trigger()
                    if window._pending_measurement is not None or not np.isclose(manual_onset['values']['onset_x'],automatic['values']['onset_x']):raise ValueError('Manual onset disagreed with its two fitted intervals')
                    checked_dialogs.append('native_four_marker_manual_onset')
                    signal_change=window.start_point_measurement('signal_change')
                    auto_limits=window.show_auto_limits();auto_limits.defaults();application.processEvents()
                    auto_limits.grab().save(str(output.with_suffix('.signal_fraction_limits.png')));auto_limits.accept()
                    if auto_limits.result()!=QDialog.DialogCode.Accepted:raise ValueError('Signal derivative-fraction limits failed: '+auto_limits.error.text())
                    window.cancel_measurement();checked_dialogs.append('native_signal_derivative_fraction_limits')
                    restore_verify_state(peak_before)
                    integration_before=capture_verify_state()
                    window._show_document(str(transition_target.dataset.path))
                    window.files.setCurrentItem(window.files.topLevelItem(window.curves.index(transition_target)))
                    options=window.show_analysis_options();options.tabs.setCurrentIndex(1)
                    options.controls['ManualOnsetBox'].setChecked(False);options.controls['AreaBox'].setChecked(True);options.accept()
                    window.classic_actions['Linear1'].trigger();linear=window._pending_measurement
                    if linear is None or linear['kind']!='peak_linear' or 'fit_error' in linear['values']:raise ValueError('Native linear peak did not start')
                    from scipy.integrate import trapezoid
                    lx,ly=transition_target.xy(window.domain);lt=transition_target.x_values('time');first,last=linear['interactive']['indices']
                    reference=ly[first]+(ly[last]-ly[first])*(lx[first:last+1]-lx[first])/(lx[last]-lx[first])
                    expected_area=float(trapezoid(ly[first:last+1]-reference,lt[first:last+1]))
                    if not np.isclose(linear['values']['integral'],expected_area):raise ValueError('Native peak area did not use recorded time')
                    auto_limits=window.show_auto_limits();auto_limits.auto_set();auto_limits.accept()
                    if auto_limits.result()!=QDialog.DialogCode.Accepted:raise ValueError('Linear peak automatic bounds failed')
                    checked_dialogs.append('native_linear_peak_auto_limits')
                    window.create_measurement_menu().actions()[0].trigger()
                    if window._pending_measurement is not None or window.selected().uid!=transition_target.uid:raise ValueError('Linear peak confirmation changed file')
                    window.canvas.draw();window.grab().save(str(output.with_suffix('.linear_peak.png')))
                    checked_dialogs.append('native_linear_peak_time_integration')
                    options=window.show_analysis_options();options.controls['ManualOnsetBox'].setChecked(True);options.accept()
                    window.classic_actions['Linear1'].trigger();linear_manual=window._pending_measurement;manual=window.edit_measurement_limits()
                    if len(manual.fields)!=4 or not all(field.isReadOnly() for field in manual.y_fields):raise ValueError('Linear peak manual tangent markers were missing')
                    for field,position in zip(manual.fields,[first,last,automatic['values']['fits'][1]['position_start'],automatic['values']['fits'][1]['position_stop']]):
                        field.setText(format(float(np.interp(position,np.arange(len(lx)),lx)),'.17g'))
                    manual.grab().save(str(output.with_suffix('.linear_manual_limits.png')));manual.accept()
                    if manual.result()!=QDialog.DialogCode.Accepted:raise ValueError('Linear peak manual tangent failed: '+manual.error.text())
                    window.create_measurement_menu().actions()[0].trigger()
                    if window._pending_measurement is not None or not np.isclose(linear_manual['values']['integral'],expected_area):raise ValueError('Manual onset changed integration baseline area')
                    checked_dialogs.append('native_four_marker_peak_onset')
                    restore_verify_state(integration_before)
                    sigmoid_before=capture_verify_state()
                    window._show_document(str(transition_target.dataset.path))
                    window.files.setCurrentItem(window.files.topLevelItem(window.curves.index(transition_target)))
                    options=window.show_analysis_options();options.tabs.setCurrentIndex(4)
                    options.controls['SigItterationsBox'].setChecked(True);options.controls['ManualOnsetBox'].setChecked(False)
                    options.grab().save(str(output.with_suffix('.sigmoid_options.png')));options.accept()
                    if not window.sigmoid_iterations():raise ValueError('Sigmoid iteration option did not apply')
                    checked_dialogs.append('native_sigmoid_iteration_options')
                    window.classic_actions['SigHorizontal1'].trigger();sigmoid=window._pending_measurement
                    if sigmoid is None or sigmoid['kind']!='peak_sigmoid' or 'fit_error' in sigmoid['values']:raise ValueError('Horizontal sigmoid did not converge')
                    from .sigmoidal import validate_snapshot
                    validate_snapshot(sigmoid['values']['sigmoid_profile'],len(transition_target.active_rows))
                    auto_limits=window.show_auto_limits();auto_limits.auto_set();auto_limits.accept()
                    if auto_limits.result()!=QDialog.DialogCode.Accepted:raise ValueError('Sigmoid automatic bounds failed: '+auto_limits.error.text())
                    window.create_measurement_menu().actions()[0].trigger()
                    if window._pending_measurement is not None or window.selected().uid!=transition_target.uid:raise ValueError('Sigmoid confirmation changed source')
                    artist=next(a for a in window._measurement_artists if a.entry is sigmoid)
                    if not artist.iteration_lines or not any(len(line.get_xdata()) for line in artist.iteration_lines):raise ValueError('Sigmoid iteration baselines were not drawn')
                    window.canvas.draw();window.grab().save(str(output.with_suffix('.sigmoid_peak.png')))
                    checked_dialogs.append('native_horizontal_sigmoid_peak')
                    options=window.show_analysis_options();options.controls['ManualOnsetBox'].setChecked(True);options.accept()
                    window.classic_actions['SigHorizontal1'].trigger();manual_sigmoid=window._pending_measurement;manual=window.edit_measurement_limits()
                    final_fit=sigmoid['values']['onset_fit']
                    if final_fit is None:raise ValueError('Sigmoid source has no usable onset tangent')
                    for field,position in zip(manual.fields,[0,len(lx)-1,final_fit['position_start'],final_fit['position_stop']]):field.setText(format(float(np.interp(position,np.arange(len(lx)),lx)),'.17g'))
                    manual.grab().save(str(output.with_suffix('.sigmoid_manual_limits.png')));manual.accept()
                    if manual.result()!=QDialog.DialogCode.Accepted:raise ValueError('Sigmoid manual tangent failed: '+manual.error.text())
                    window.create_measurement_menu().actions()[0].trigger()
                    if window._pending_measurement is not None:raise ValueError('Sigmoid manual confirmation failed')
                    mv=manual_sigmoid['values'];mf=mv['onset_fit']
                    if not np.isclose(mv['onset_y'],mf['slope']*mv['onset_x']+mf['intercept']):raise ValueError('Sigmoid onset is off its selected tangent')
                    checked_dialogs.append('native_sigmoid_manual_onset')
                    restore_verify_state(sigmoid_before)
                    # Explicit synthetic diagnostic, separate from restored
                    # experimental files; exercise the failed native preview.
                    import tempfile
                    from . import preferences as qa_preferences
                    from .reader import Dataset,Signal
                    qa_preferences_path=qa_preferences.preferences_path
                    with tempfile.TemporaryDirectory(prefix='tma-sigmoid-native-qa-') as qa_private:
                        qa_preferences.preferences_path=lambda:Path(qa_private)/'preferences.json'
                        qa_window=None
                        try:
                            qa_window=type(window)();qa_window.resize(1000,700);qa_window.show()
                            qa_window.warn=lambda message:(_ for _ in ()).throw(ValueError(message))
                            qt=np.linspace(0,1,101);qy=2+100*qt+np.maximum(0,1-abs((qt-.2)/.1))
                            qa_data=Dataset(Path(qa_private)/'synthetic-nonconvergent.001',[Signal('Time','min'),Signal('Temperature','°C'),Signal('Dimension Change','µm')],
                                np.column_stack((qt,100+100*qt,qy)),{'Sample':['QA synthetic nonconvergent signal']},[],'synthetic-known-nonconvergent')
                            qa_window.finish_import([qa_data],[])
                            qa_options=qa_window.show_analysis_options();qa_options.controls['SigItterationsBox'].setChecked(True);qa_options.accept()
                            failed=qa_window.start_peak_integration('peak_sigmoid');qa_window.confirm_measurement()
                            if qa_window._pending_measurement is not failed or qa_window.results or '10次' not in failed['values'].get('fit_error',''):raise ValueError('Nonconvergent sigmoid was incorrectly confirmed')
                            qa_artist=next(a for a in qa_window._measurement_artists if a.entry is failed)
                            if sum(bool(len(line.get_xdata())) for line in qa_artist.iteration_lines)!=10 or not len(qa_artist.integration_lines[0].get_xdata()):raise ValueError('Failed sigmoid did not display its intermediate baselines')
                            qa_window.canvas.draw();qa_window.grab().save(str(output.with_suffix('.nonconvergent_sigmoid.png')))
                        finally:
                            if qa_window is not None:qa_window.cancel_measurement();qa_window.dirty=False;qa_window.close()
                            qa_preferences.preferences_path=qa_preferences_path
                    checked_dialogs.append('native_nonconvergent_sigmoid_preview')
                    from .running_integral_qa import verify_routes
                    from .dimension_units import dimension_index
                    running_datasets=list({str(c.dataset.path):c.dataset for c in window.curves if c.derived is None and dimension_index(c.dataset)==c.y_index}.values())
                    if running_datasets:checked_dialogs.extend(verify_routes(running_datasets,application,output))
            else:
                window.import_files(inputs, synchronous=True)
            application.processEvents()
            window.canvas.draw()
            if session_check and not window._measurement_artists and hasattr(window,"documents"):
                entry = next((r for r in window.results if "interactive" in r),None)
                curve = next((c for c in window.curves if entry and c.uid == entry.get("curve_id") and c.normal_enabled),None)
                if curve is not None:
                    doc = window.documents[str(curve.dataset.path)]
                    window.mdi.setActiveSubWindow(doc); window.document_activated(doc); window.canvas.draw()
            post_routes_state=capture_verify_state() if session_check and hasattr(window,'documents') else None
            interactive_drag_checked = False
            if session_check and window._measurement_artists:
                from matplotlib.backend_bases import MouseEvent
                from .measurement import nearest_sample
                editor = window._measurement_artists[0]
                window.edit_measurement(editor.entry)
                editor = next(item for item in window._measurement_artists if item.entry is window._pending_measurement)
                original = list(editor.indices)
                sample = original[0]
                px, py = editor.axis.transData.transform(editor.display_coords[0])
                window.canvas.callbacks.process("button_press_event", MouseEvent("button_press_event", window.canvas, px, py, button=1))
                if window._drag_measurement is None: raise ValueError("打包程序无法选中分析控制点")
                target = min(len(editor.x)-1, sample+10)
                tx, ty = editor.axis.transData.transform((editor.x[target]+editor.display_x_offset, editor.y[target]))
                motion = MouseEvent("motion_notify_event", window.canvas, tx, ty, button=1)
                if editor.entry['kind']=='curve_value_y':
                    from .measurement import position_at_y
                    target_y=float(np.clip(editor.axis.transData.inverted().transform((motion.x,motion.y))[1],editor.y.min(),editor.y.max()))
                    snapped=int(round(position_at_y(editor.y,target_y,editor.curve.active_rows)))
                else:snapped = nearest_sample(editor.x,editor.axis.transData.inverted().transform((motion.x,motion.y))[0]-editor.display_x_offset,sample)
                window.canvas.callbacks.process("motion_notify_event", motion)
                window.canvas.callbacks.process("button_release_event", MouseEvent("button_release_event", window.canvas, tx, ty, button=1))
                if editor.indices[0] != snapped: raise ValueError("打包程序控制点未吸附到曲线")
                window.cancel_measurement()
                window.refresh_results(); window.canvas.draw()
                window.statusBar().clearMessage()
                interactive_drag_checked = True
            cursor_menu_checked = False
            if session_check and window._measurement_artists and hasattr(window, "create_measurement_menu"):
                original = window._measurement_artists[0].entry
                window.edit_measurement(original)
                menu = window.create_plot_context_menu()
                labels = [a.text() for a in menu.actions() if not a.isSeparator()]
                if labels[:4] != ["确定", "编辑…", "自动界限", "取消"]:
                    raise ValueError("打包程序选点右键菜单不完整")
                dialog = window.edit_measurement_limits(); application.processEvents()
                dialog.grab().save(str(output.with_suffix(".cursor_limits.png")))
                original_height=float(window._pending_measurement["values"]["start_y"])
                if window._pending_measurement['kind']=='curve_value_y':
                    current=next(e for e in window._measurement_artists if e.entry is window._pending_measurement)
                    manual_height=float(.5*np.min(current.y)+.5*np.max(current.y))
                else:manual_height = original_height+1
                dialog.y_fields[0].setText(format(manual_height, ".15g")); dialog.accept()
                expected_height=original_height if window._pending_measurement["kind"] in ('curve_value','alpha_at_x','alpha_secant','alpha_fit','step_transition','glass_transition','peak_max','onset_point','peak_linear','peak_sigmoid','slope') else manual_height
                if not np.isclose(window._pending_measurement["values"]["start_y"],expected_height):
                    raise ValueError("打包程序手动 Y 界限未应用")
                checked_dialogs.append("cursor_limits")
                menu.actions()[3].trigger()
                if window._pending_measurement is not None: raise ValueError("打包程序选点右键取消失败")
                cursor_menu_checked = True
            keyboard_cursor_checked = False
            if session_check and window._measurement_artists:
                from matplotlib.backend_bases import KeyEvent
                original = window._measurement_artists[0].entry
                index = next(i for i, result in enumerate(window.results) if result is original)
                window.edit_measurement(original)
                editor = next(item for item in window._measurement_artists if item.entry is window._pending_measurement)
                window.activate_measurement_point(0)
                before = editor.coords[0][0]
                window.canvas.callbacks.process("key_press_event", KeyEvent("key_press_event", window.canvas, key="ctrl+right"))
                if editor.coords[0][0] == before: raise ValueError("打包程序方向键未移动控制点")
                window.canvas.callbacks.process("key_press_event", KeyEvent("key_press_event", window.canvas, key="enter"))
                if window._pending_measurement is not None and window._pending_measurement["kind"] in CURVE_VALUE_KINDS:window.dialogs["label_point"].accept()
                if window._pending_measurement is not None: raise ValueError("打包程序 Enter 未确定选点")
                window.results[index] = original
                window.refresh_results(); window.redraw(); window.canvas.draw()
                keyboard_cursor_checked = True
            cross_document_cursor_checked = False
            if session_check and window._measurement_artists and hasattr(window, "current_measurement"):
                original = window._measurement_artists[0].entry
                curve = next(c for c in window.curves if c.uid == original["curve_id"])
                other = next((c for c in window.curves if c.dataset.path != curve.dataset.path), None)
                if other is not None:
                    from matplotlib.backend_bases import KeyEvent
                    active = window.active_document()
                    window.edit_measurement(original)
                    pending = window._pending_measurement
                    doc = window.documents[str(other.dataset.path)]
                    window.mdi.setActiveSubWindow(doc); window.document_activated(doc)
                    window.canvas.callbacks.process("key_press_event", KeyEvent("key_press_event", window.canvas, key="enter"))
                    if window.current_measurement() is not None or window._pending_measurement is not pending:
                        raise ValueError("其它文件错误地确定了当前选点")
                    window.mdi.setActiveSubWindow(active); window.document_activated(active)
                    if window.current_measurement() is not pending: raise ValueError("切换文件丢失了待确定选点")
                    window.cancel_measurement(); window.canvas.draw()
                    cross_document_cursor_checked = True
            temperature_label_drag_checked = False
            # Coincident overlay labels belong to the last drawn curve on top.
            editor = next((item for item in reversed(window._measurement_artists) if item.temps and item.temps[0].get_visible()), None)
            if session_check and editor is not None:
                before = deepcopy(editor.entry.get("annotation", {}))
                window.canvas.draw()
                bounds = Text.get_window_extent(editor.temps[0], window.canvas.get_renderer())
                px, py = (bounds.x0+bounds.x1)/2, (bounds.y0+bounds.y1)/2
                for kind, x, y in (("button_press_event", px, py), ("motion_notify_event", px+25, py+15), ("button_release_event", px+25, py+15)):
                    window.canvas.callbacks.process(kind, MouseEvent(kind, window.canvas, x, y, button=1))
                if editor.entry.get("annotation", {}).get("label_offsets", {}).get("t1") == before.get("label_offsets", {}).get("t1"):
                    window.grab().save(str(output.with_suffix('.label_drag_failure.png')))
                    diagnostics=dict(file=editor.entry.get('file'),kind=editor.entry['kind'],pixel=[px,py],before=before,after=editor.entry.get('annotation'),
                        pending=window._pending_measurement,document=window.active_document().key,
                        labels=[dict(kind=a.entry['kind'],file=a.entry.get('file'),annotation=a.entry.get('annotation'),texts=[t.get_text() for t in a.temps if t.get_visible()]) for a in window._measurement_artists])
                    output.with_suffix('.label_drag_failure.json').write_text(json.dumps(diagnostics,ensure_ascii=False,indent=2),encoding='utf-8')
                    raise ValueError("打包程序无法单独拖动已确定的温度标签")
                editor.entry["annotation"] = before
                window.redraw(); window.canvas.draw()
                temperature_label_drag_checked = True
            curve_value_label_drag_checked=False
            editor=next((item for item in window._measurement_artists if item.entry["kind"] in CURVE_VALUE_KINDS and item.annotation.get_text()),None)
            if session_check and editor is not None:
                before=deepcopy(editor.entry.get("annotation",{}));values=deepcopy(editor.entry["values"])
                window.canvas.draw();bounds=Text.get_window_extent(editor.annotation,window.canvas.get_renderer())
                px,py=(bounds.x0+bounds.x1)/2,(bounds.y0+bounds.y1)/2
                for kind,x,y in (("button_press_event",px,py),("motion_notify_event",px+22,py+17),("button_release_event",px+22,py+17)):
                    window.canvas.callbacks.process(kind,MouseEvent(kind,window.canvas,x,y,button=1))
                if editor.entry.get("annotation",{}).get("offset")==before.get("offset") or editor.entry["values"]!=values:raise ValueError("打包程序曲线值标签拖动失败或改变了数值")
                editor.entry["annotation"]=before;window.redraw();window.canvas.draw();curve_value_label_drag_checked=True
            legend_drag_checked = False
            legend = window.axes[0].get_legend() if 0 in window.axes else None
            if session_check and legend is not None and legend.get_visible():
                from matplotlib.backend_bases import MouseEvent
                active = window.active_document()
                options = window.plot_options[active.key]
                before = deepcopy(options["legend_anchor"])
                window.canvas.draw()
                bounds = legend.get_window_extent(window.canvas.get_renderer())
                x, y = (bounds.x0+bounds.x1)/2, (bounds.y0+bounds.y1)/2
                for kind, px, py in (("button_press_event", x, y), ("motion_notify_event", x-35, y-30), ("button_release_event", x-35, y-30)):
                    window.canvas.callbacks.process(kind, MouseEvent(kind, window.canvas, px, py, button=1))
                if options["legend_anchor"] == before: raise ValueError("打包程序图例拖动未保存位置")
                options["legend_anchor"] = before
                window.redraw(); window.canvas.draw(); legend_drag_checked = True
            if post_routes_state is not None:
                restore_verify_state(post_routes_state)
                from .running_integral import validate_links
                validate_links(window.curves,window.results)
            classic_tick_fonts={}
            if hasattr(window,'documents'):
                from matplotlib.font_manager import findfont
                for index,axis in window.axes.items():
                    files=sorted({findfont(label.get_fontproperties()) for label in axis.get_xticklabels()+axis.get_yticklabels() if label.get_visible()})
                    if not all(Path(font).name.casefold()=='times.ttf' for font in files):raise ValueError(f'Classic Y{index+1} tick font fallback')
                    classic_tick_fonts[str(index)]=files
            window.grab().save(str(output.with_suffix(".png")))
            output.write_text(json.dumps({"status": "passed", "version": __version__, "files": len(window.curves),
                                          "points": [c.sample_count for c in window.curves],
                                          "session_restored": session_check, "results": len(window.results),
                                          "classic_tick_fonts":classic_tick_fonts,
                                          "dialogs_checked": checked_dialogs,
                                          "interactive_measurements": len(window._measurement_artists),
                                          "interactive_drag_checked": interactive_drag_checked,
                                          "temperature_label_drag_checked": temperature_label_drag_checked,
                                          "curve_value_label_drag_checked":curve_value_label_drag_checked,
                                          "cursor_menu_checked": cursor_menu_checked,
                                          "keyboard_cursor_checked": keyboard_cursor_checked,
                                          "cross_document_cursor_checked": cross_document_cursor_checked,
                                          "legend_drag_checked": legend_drag_checked,
                                          "all_measurements_confirmed": all(editor.entry["interactive"]["confirmed"] for editor in window._measurement_artists)}, indent=2), encoding="utf-8")
            window.dirty = False
            window.close()
            return
        except Exception as exc:
            import traceback
            output.write_text(json.dumps({"status": "failed", "error": str(exc),"error_type":type(exc).__name__,"traceback":traceback.format_exc()}), encoding="utf-8")
            raise
    paths = [arg for arg in sys.argv[1:] if Path(arg).is_file()]
    if paths:
        if len(paths) == 1 and Path(paths[0]).suffix.casefold() == ".tmas":
            QTimer.singleShot(0, lambda: window.restore_session(paths[0]))
        else:
            QTimer.singleShot(0, lambda: window.import_files(paths))
    sys.exit(application.exec())
