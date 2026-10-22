"""Universal Analysis style MDI shell, using the independent TMA backend.

Menu order and glyphs originate in the local DFM resources. Main-view spacing,
toolbar order and plot typography follow the supplied original screenshot.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from contextlib import contextmanager
from io import BytesIO

import numpy as np
from PySide6.QtCore import Qt, QSize, Signal, QTimer, QSignalBlocker
from PySide6.QtGui import QAction, QColor, QIcon, QPixmap, QFont, QPalette, QImage, QPainter
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDialog, QDialogButtonBox, QMdiArea, QMdiSubWindow, QToolBar,
    QGroupBox, QCheckBox, QMessageBox, QMenu, QInputDialog, QStyle,
    QFileDialog,
)
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.ticker import MaxNLocator, AutoMinorLocator, MultipleLocator, FuncFormatter
from matplotlib.lines import Line2D

from .app import MainWindow
from .workspace import default_plot_options, validate_plot_options
from .overlay_settings import fill_manual_limits
from .legend import render_legend, apply_anchor, moved_anchor
from . import __version__, APP_NAME
from .theme import CUTE_STYLE, cute_palette, app_icon, action_icon, PastelMdiArea

ASSETS = Path(__file__).parent / "assets" / "classic"
REFERENCE_TOOLBAR = (1, 15, 21, 29, 33, 34, 36, 39, 40, 42, 43, 49, 50, 51, 54,
                     67, 68, 69, 70, 71, 72, 79, 80, 152, 81, 82, 85, 87, 95, 96, 97)
PLOT_FONTS = ["Times New Roman", "SimSun", "Microsoft YaHei"]


def nice_limits(values):
    """Enclose the actual samples with readable 1/2/5 ticks; never clip data."""
    lo, hi = float(np.min(values)), float(np.max(values))
    if lo == hi:
        pad = max(1.0, abs(lo) * .05)
        lo, hi = lo - pad, hi + pad
    ticks = MaxNLocator(nbins=5, steps=[1, 2, 5, 10]).tick_values(lo, hi)
    return (float(ticks[0]), float(ticks[-1])), ticks


def localized_signal(label):
    for source, target in (("Dimension Change", "尺寸变化"), ("Temperature", "温度"),
                           ("Sample Purge Flow", "样品吹扫流量"), ("Force", "力"), ("Time", "时间")):
        label = label.replace(source, target)
    return label.replace(" (", "(")


def reference_disabled_icon(path, inverted=False):
    """The original toolbar uses an embossed one-pixel disabled mask."""
    source = QImage(str(path)).convertToFormat(QImage.Format.Format_RGBA8888)
    image = QImage(16, 16, QImage.Format.Format_RGBA8888)
    image.fill(QColor(105, 105, 105) if inverted else QColor(240, 240, 240))
    for y in range(16):
        for x in range(16):
            covered = source.pixelColor(x, y).alpha() > 0
            shifted = x > 0 and y > 0 and source.pixelColor(x - 1, y - 1).alpha() > 0
            if covered:
                value = 240 if inverted else 160
                image.setPixelColor(x, y, QColor(value, value, value))
            elif shifted:
                image.setPixelColor(x, y, QColor("white"))
    return QPixmap.fromImage(image)


CLASSIC_STYLE = CUTE_STYLE


def classic_palette():
    return cute_palette()


class PlotDocument(QMdiSubWindow):
    closed_document = Signal(object)

    def __init__(self, owner, key, title):
        super().__init__()
        self.key = key
        self.curve_uids = None
        self.plot_signature = None
        self.plot_axes = {}
        self.plot_ticks = {}
        self.plot_ranges = {}
        self.figure = Figure(facecolor="white")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.navigation = NavigationToolbar2QT(self.canvas, owner)
        self.navigation.hide()
        content = QWidget()
        content.setStyleSheet("background: white;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.canvas)
        self.setWidget(content)
        self.setWindowTitle(title)
        self.setWindowIcon(app_icon())
        self.resize(790, 590)
        self.canvas.mpl_connect("motion_notify_event", owner.cursor_motion)
        self.canvas.mpl_connect("resize_event", owner.canvas_resized)
        self.canvas.mpl_connect("button_press_event", owner.analysis_click)
        self.canvas.mpl_connect("button_press_event", owner.result_press)
        self.canvas.mpl_connect("motion_notify_event", owner.result_motion)
        self.canvas.mpl_connect("button_release_event", owner.result_release)
        self.canvas.mpl_connect("key_press_event", owner.measurement_key)
        self.canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.canvas.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.canvas.customContextMenuRequested.connect(lambda point: owner.show_plot_context_menu(self, point))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

    def closeEvent(self, event):
        self.closed_document.emit(self)
        event.accept()


class ClassicMainWindow(MainWindow):
    def __init__(self):
        self.documents = {}
        self._syncing_documents = False
        self._activating = False
        self._overlay_seq = 0
        self.dialogs = {}
        self.classic_actions = {}
        self.classic_legend = None  # Single traces have no legend; overlays do.
        self._drag_legend = None
        self._limits_undo={}
        self._session_smooth_rules=[]
        self._last_document=None
        super().__init__()
        self.setStyleSheet(CLASSIC_STYLE)
        self.setPalette(classic_palette())
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowIcon(app_icon())
        self.resize(1400, 900)
        self.statusBar().clearMessage()
        self._plot_resize_timer = QTimer(self)
        self._plot_resize_timer.setSingleShot(True)
        self._plot_resize_timer.timeout.connect(self.redraw)

    def _callbacks(self):
        return {
            "Open1": self.open_files, "Reopen1": self.show_file_list, "Close1": self.close_active_document, "CloseAll1": self.close_all_documents,
            "SaveSession1": self.save, "AnalysisOnly1": self.export_results, "AnalysisAndData1": self.save,
            "ExportPlot1": self.export_plot, "ExportPDFFile1": lambda: self.export_plot("pdf"),
            "FileSignalsOnly1": self.export_data, "PlotSignalsOnly1": self.export_data,
            "FileAndPlotSignals1": self.export_data, "Exit1": self.close,
            "Print1": self.print_plot, "Annotate1": self.add_note,
            "MainOptions1": self.show_options, "EditParamBlock1": lambda: self.show_view("metadata"),
            "Copy3": self.copy_plot, "FileInformation1": self.show_file_information,
            "SelectAll1": lambda: self.set_all_visible(True),
            "ManualRescale1": lambda: self.manual_rescale(), "ZoomOut1": lambda: self.toolbar.back(),
            "PreviousLimits1": lambda: self.toolbar.back(), "FullScaleAxis1": self.full_scale,
            "FullScaleAll1": self.full_scale, "ExactScalingX1": lambda: self.manual_rescale("x"),
            "ExactScalingY1": lambda: self.manual_rescale(self.selected().axis if self.selected() else 0),
            "SpreadsheetView1": lambda: self.show_view("data"), "Signals1": self.show_native_signals,
            "Units1": self.show_units, "InstrParams1": lambda: self.show_view("metadata"),
            "Curve1": self.show_curve_options,
            "Y1": lambda: self.select_plot_axis(0), "Y2": lambda: self.select_plot_axis(1),
            "Y3": lambda: self.select_plot_axis(2), "Y4": lambda: self.select_plot_axis(3),
            "FullRangeLimits1": self.full_data_range,
            "CursorLimits1": self.graphic_range,
            "TimeLimits1": lambda: self.show_data_limits("time"), "TemperatureLimits1": lambda: self.show_data_limits("temperature"),
            "CycleLimits1":lambda:self.show_data_limits("cycle"),
            "Data1": self.redraw, "Plot1": self.redraw,
            "XTime1": lambda: self.domain_box.setCurrentIndex(1),
            "XTemp1": lambda: self.domain_box.setCurrentIndex(0),
            "XSignal1": lambda: self.domain_box.setCurrentIndex(2),
            "AutoConfigure1": self.auto_configure_overlay, "ManualSetup1": self.show_overlay_options,
            "Edit4": self.show_overlay_options, "Copy4": lambda:self.copy_overlay(),
            "ShowOverlayPlot1": self.show_overlay, "ShowNormalPlot1": self.show_normal,
            "GraphOptions1": self.show_curve_options, "Plotlegend1": self.toggle_legend,
            "PlotHeader1": self.set_plot_title, "PlotFullRange1": self.full_scale,
            "HideResults1": lambda: self.show_results.setChecked(not self.show_results.isChecked()),
            "AlphaAtX1":lambda:self.start_alpha("alpha_at_x"),
            "AlphaX1ToX21":lambda:self.start_alpha("alpha_secant"),
            "AlphaFitX1ToX21":lambda:self.start_alpha("alpha_fit"),
            "DimensionChange1": lambda: self.start_point_measurement("dimension_change"),
            "Linear1": lambda:self.start_peak_integration('peak_linear'),
            "SigHorizontal1":lambda:self.start_peak_integration('peak_sigmoid'),
            "PeakRunningIntegral1":self.start_running_integral,
            "DeletePeak1":self.start_delete_peak,
            "PeakMax1": lambda: self.start_peak_onset("peak_max"), "SignalMax1": lambda: self.start_point_measurement("signal_max"),
            "SignalChange1": lambda: self.start_point_measurement("signal_change"),
            "CurveValueAtX1":lambda:self.start_point_measurement("curve_value"),
            "CurveValueAtY1":lambda:self.start_point_measurement("curve_value_y"),
            "OnsetPoint1": lambda: self.start_peak_onset("onset_point"), "Slope1": lambda:self.start_point_measurement('slope'),
            "FullRange1": self.full_range, "EnterLimits1": lambda: self.analysis_dialog(),
            "StepTransition1":lambda:self.start_transition("step_transition"),
            "StepTransition2":lambda:self.start_transition("step_transition"),
            "GlassTransition1":lambda:self.start_transition("glass_transition"),
            "AnalysisOptions1": self.show_analysis_options,
            "Smooth1": self.show_native_smooth, "Shift1": self.show_signal_options,
            "YAxis2": self.show_signal_options, "XAxis2": self.show_signal_options,
            "RemoveShifts1": self.reset_curve,
            "ResultsReport1": lambda: self.show_view("results"), "ResultsSpreadsheet1": lambda: self.show_view("results"),
            "DataTableReport1": lambda: self.show_view("data"), "DataTableSpreadsheet1": lambda: self.show_view("data"),
            "ParameterBlock1": lambda: self.show_view("metadata"), "MethodLog1": lambda: self.show_view("metadata"),
            "AnalysisLog1": lambda: self.show_view("log"), "Spreadsheet1": lambda: self.show_view("data"),
            "Tile1": lambda: self.mdi.tileSubWindows(), "Cascade1": lambda: self.mdi.cascadeSubWindows(),
            "StayOnTop1": self.toggle_topmost, "MoreWindows1": self.show_file_list,
            "AboutUniversalAnalysis1": self.about, "GettingStartedGuide1": self.about,
            "HelpTopics1": self.about,
        }

    def _menu(self):
        model_path = ASSETS / "ui.json"
        self.ui_model = json.loads(model_path.read_text(encoding="utf-8")) if model_path.exists() else {"menus": [], "buttons": []}
        callbacks = self._callbacks()
        settings_menu = self.menuBar().addMenu("设置")
        settings_menu.addAction("数据路径…", self.show_path_settings).setObjectName("PathSettings1")
        settings_menu.addAction("批量窗口设置…", self.show_path_settings).setObjectName("BatchWindowSettings1")

        def append(parent, item):
            caption, name = item["caption"], item["name"]
            if name == "AboutUniversalAnalysis1":
                caption = f"关于 {APP_NAME}"
            if caption == "-":
                parent.addSeparator()
                return
            if item.get("children"):
                submenu = parent.addMenu(caption)
                self.classic_actions[name] = submenu.menuAction()
                for child in item["children"]:
                    append(submenu, child)
                return
            action = QAction(caption, self)
            self.classic_actions[name] = action
            action.setObjectName(name)
            action.setStatusTip(caption)
            if name in callbacks:
                action.triggered.connect(callbacks[name])
            else:
                action.setEnabled(False)
                action.setToolTip(caption + " — 尚未实现")
            shortcut = item.get("shortcut")
            if shortcut:
                action.setShortcut(shortcut)
            parent.addAction(action)

        for menu in self.ui_model["menus"]:
            parent = self.menuBar().addMenu(menu["caption"])
            for item in menu.get("children", []):
                append(parent, item)
            if menu["name"] == "Window1":
                self.window_menu = parent
            if menu["caption"]=="工具":
                parent.addSeparator();parent.addAction("通用信号处理…",self.show_processing)
            if menu["caption"] == "文件":
                action = QAction("批量处理 T1 / T2 / M / H…", self)
                action.setObjectName("BatchAnalysis1")
                action.setShortcut("Ctrl+Shift+B")
                action.triggered.connect(self.show_batch_analysis)
                action.setIcon(action_icon("Signals1"))
                parent.insertAction(parent.actions()[1], action)
                self.classic_actions["BatchAnalysis1"] = action
                report = QAction("单样品报告…", self)
                report.setObjectName("SingleReport1")
                report.setShortcut("Ctrl+Shift+R")
                report.setIcon(action_icon("AnalysisOptions1"))
                report.triggered.connect(self.show_single_report)
                parent.insertAction(parent.actions()[2], report)
                self.classic_actions["SingleReport1"] = report
        height = QAction("高度差", self)
        height.setObjectName("HeightChange")
        height.triggered.connect(lambda: self.start_point_measurement("height_change"))
        self.classic_actions["HeightChange"] = height
        for menu_action in self.menuBar().actions():
            if menu_action.text() == "分析":
                menu = menu_action.menu()
                after = self.classic_actions.get("SignalChange1")
                menu.insertAction(after, height)
        if hasattr(self, "window_menu"):
            self.window_menu.aboutToShow.connect(self.update_window_menu)
        data_menu=self.classic_actions.get("DataLimits1")
        if data_menu is not None and data_menu.menu() is not None:
            menu=data_menu.menu();action=QAction("设置数据界限…",self);action.triggered.connect(lambda:self.show_data_limits())
            menu.insertAction(menu.actions()[0],action)
        copy_action=self.classic_actions.get("Copy4")
        if copy_action is not None and copy_action.menu() is not None:
            menu=copy_action.menu();menu.aboutToShow.connect(self.update_overlay_copy_menu)
            self._empty_copy_action=menu.addAction("无叠图");self._empty_copy_action.setEnabled(False)
            for i in range(1,21):
                action=self.classic_actions.get(f"C{i}")
                if action is not None:action.triggered.connect(lambda checked=False,action=action:self.copy_overlay(action.data()))
            self.update_overlay_copy_menu()

    def _build(self):
        MainWindow._build(self)
        # Preserve the proven controllers, but place their widgets in dialogs.
        # The visible workspace contains only original-style MDI plot windows.
        self._controller_root = self.takeCentralWidget()
        self._controller_root.setParent(self)
        self._controller_root.hide()
        self._default_figure, self._default_canvas, self._default_toolbar = self.figure, self.canvas, self.toolbar
        self.property_group = self.y_box.parentWidget()
        self.analysis_group = self.analysis_box.parentWidget()
        self.processing_group = self.smooth_window.parentWidget()
        self._panels = {
            "metadata": self.metadata, "data": self.table, "results": self.result_table, "log": self.log,
        }
        self.mdi = PastelMdiArea()
        self.mdi.setOption(QMdiArea.AreaOption.DontMaximizeSubWindowOnActivation, False)
        self.mdi.subWindowActivated.connect(self.document_activated)
        self.setCentralWidget(self.mdi)
        self.statusBar().setSizeGripEnabled(True)
        self.statusBar().setFixedHeight(19)
        self._make_toolbar()

    def show_path_settings(self):
        from .settings_dialog import SettingsDialog
        old = self.dialogs.get("path_settings")
        if old and old.isVisible(): old.raise_(); return old
        try: dialog = SettingsDialog(self)
        except (ValueError, OSError) as exc: self.warn(str(exc)); return
        self.dialogs["path_settings"] = dialog; dialog.show(); return dialog

    def _make_toolbar(self):
        toolbar = QToolBar("工具栏", self)
        toolbar.setObjectName("MainToolBar")
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setFixedHeight(26)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        buttons = {b["image_index"]: b for b in self.ui_model.get("buttons", [])}
        for index in REFERENCE_TOOLBAR:
            info = buttons.get(index)
            if not info:
                continue
            target = self.classic_actions.get(info.get("menu"))
            action = QAction(info["caption"], self)
            action.setData(index)
            if target is not None and target.isEnabled():
                action.triggered.connect(target.trigger)
            else:
                action.setToolTip(info["caption"] + "（功能待实现）")
                action.triggered.connect(lambda checked=False, title=info["caption"]: QMessageBox.information(self, title, "此功能的界面入口已保留，分析方法尚未实现。"))
            if index in (34, 39, 49):
                action.setEnabled(False)
            action.setIcon(action_icon(info.get("menu")))
            if target is not None:
                target.setIcon(action.icon())
            toolbar.addAction(action)
            toolbar.widgetForAction(action).setFixedSize(24, 24)
        toolbar.addSeparator()
        self.single_report_button = QPushButton("单样品报告", self)
        self.single_report_button.setObjectName("SingleReportButton")
        self.single_report_button.setIcon(action_icon("AnalysisOptions1"))
        self.single_report_button.setFixedHeight(24)
        self.single_report_button.setAutoDefault(False)
        self.single_report_button.clicked.connect(self.show_single_report)
        toolbar.addWidget(self.single_report_button)
        self.classic_toolbar = toolbar

    @staticmethod
    def _is_overlay(key):
        return key == "__overlay__" or (isinstance(key, str) and key.startswith("__overlay__:"))

    @staticmethod
    def _overlay_title(key):
        return "叠加绘图" if key == "__overlay__" else f"叠加绘图 {key.rsplit(':', 1)[-1]}"

    def _next_overlay_key(self):
        if sum(self._is_overlay(key) for key in self.documents)>=20:raise ValueError("最多可打开20张叠图，请先关闭一张。")
        sequence = getattr(self, "_overlay_seq", 0)
        while True:
            sequence += 1
            key = "__overlay__" if sequence == 1 else f"__overlay__:{sequence}"
            if key not in self.documents:
                self._overlay_seq = sequence
                return key

    def _overlay_key_for_edit(self):
        active = self.active_document() if hasattr(self, "mdi") else None
        if isinstance(active, PlotDocument) and self._is_overlay(active.key):
            return active.key
        return self._next_overlay_key()

    def _overlay_members(self):
        members = [c for c in self.curves if c.visible and c.overlay_enabled]
        return members or [c for c in self.curves if c.visible]

    def _document_curves(self, doc):
        if not isinstance(doc, PlotDocument):
            return []
        if self._is_overlay(doc.key):
            uids = getattr(doc,"curve_uids",None)
            if uids is None:return [c for c in self.curves if c.overlay_enabled]
            lookup={c.uid:c for c in self.curves}
            return [lookup[uid] for uid in uids if uid in lookup]
        return [c for c in self.curves if c.dataset.document_key == doc.key]

    def _show_document(self, key):
        doc = self._document(key)
        with QSignalBlocker(self.mdi):
            doc.showMaximized()
            self.mdi.setActiveSubWindow(doc)
        self.document_activated(doc)
        return doc

    def _open_overlay(self, key, members):
        doc = self._document(key)
        doc.curve_uids = [c.uid for c in members]
        self.plot_options[key]["overlay_members"]=list(doc.curve_uids)
        doc.plot_signature = None
        self._show_document(key)
        return doc

    def _toggle_curve_visible(self, curve, visible):
        curve.visible = visible
        self.touch()
        self.rebuild_files()
        self.redraw()

    def _build_visibility_menu(self, menu):
        doc = self.active_document()
        curves = self._document_curves(doc)
        if not curves:
            return
        submenu = menu.addMenu("显示 / 隐藏曲线")
        for curve in curves:
            label = f"{curve.dataset.path.name} · {curve.signal_label} · Y{curve.axis + 1}"
            action = submenu.addAction(label)
            action.setCheckable(True)
            action.setChecked(curve.visible)
            action.triggered.connect(lambda checked=False, c=curve: self._toggle_curve_visible(c, checked))
        submenu.addSeparator()
        submenu.addAction("全部显示", lambda: self.set_all_visible(True))
        submenu.addAction("全部隐藏", lambda: self.set_all_visible(False))

    def _document(self, key):
        doc = self.documents.get(key)
        if doc is None:
            if key not in self.plot_options and not getattr(self, "_restoring_session", False):
                saved = self.user_defaults("overlay" if self._is_overlay(key) else "graph")
                if saved["options"]:
                    self.plot_options[key] = validate_plot_options(fill_manual_limits(self, validate_plot_options(saved["options"])))
            source = next((c.dataset for c in self.curves if c.dataset.document_key == key), None)
            title = self._overlay_title(key) if self._is_overlay(key) else source.display_name if source else Path(key).name
            options = self.plot_options.setdefault(key, default_plot_options())
            if options["x_domain"] is None:
                candidates = [c for c in self.curves if self._is_overlay(key) or c.dataset.document_key == key]
                options["x_domain"] = self.domain if self.domain != "signal" or all(c.x_signal_index is not None for c in candidates) else "temperature"
            doc = PlotDocument(self, key, title)
            self.documents[key] = doc
            if self._is_overlay(key):doc.curve_uids=deepcopy(options["overlay_members"])
            self.mdi.addSubWindow(doc)
            doc.closed_document.connect(self.document_closed)
            count = len(self.documents) - 1
            doc.move(20 * (count % 8), 20 * (count % 8))
        return doc

    def user_defaults(self, scope):
        from .preferences import load_defaults
        try:
            return load_defaults(scope)
        except (ValueError, OSError) as exc:
            self.log.appendPlainText(f"默认设置未载入：{exc}")
            self.statusBar().showMessage(f"默认设置未载入：{exc}")
            return {"options": {}, "curves": [[], [], [], []]}

    @staticmethod
    def apply_default_appearance(curves, saved):
        slots = [0]*4
        for curve in curves:
            axis, slot = curve.axis, slots[curve.axis]
            if slot < len(saved["curves"][axis]):
                for key, value in saved["curves"][axis][slot].items(): setattr(curve, "overlay_offset" if key == "offset" and curve.appearance_mode == "overlay" else key, value/curve.y_unit_factor() if key=="offset" else value)
            slots[axis] += 1

    def sync_documents(self):
        if self._syncing_documents:
            return
        self._syncing_documents = True
        try:
            valid_uids={c.uid for c in self.curves}
            for key,options in self.plot_options.items():
                if self._is_overlay(key) and options.get("overlay_members") is not None:
                    options["overlay_members"]=[uid for uid in options["overlay_members"] if uid in valid_uids]
                    if key in self.documents:self.documents[key].curve_uids=list(options["overlay_members"])
            valid = {c.dataset.document_key for c in self.curves}
            for key in list(self.documents):
                if not self._is_overlay(key) and key not in valid:
                    doc = self.documents.pop(key)
                    self.mdi.removeSubWindow(doc)
                    doc.deleteLater()
            if not self.curves:
                for key in [k for k in self.documents if self._is_overlay(k)]:
                    doc = self.documents.pop(key)
                    self.mdi.removeSubWindow(doc)
                    doc.deleteLater()
            for c in self.curves:
                key = c.dataset.document_key
                if key not in self.documents:
                    self._document(key).show()
        finally:
            self._syncing_documents = False

    def active_document(self):
        if not hasattr(self,"mdi"):return None
        current=self.mdi.activeSubWindow()
        if isinstance(current,PlotDocument) and any(current is doc for doc in self.documents.values()):return current
        # Windows may temporarily clear QMdiArea's active child while a modal
        # window closes or another application receives focus. Keep the logical
        # document only while it is still attached to this workspace.
        previous=getattr(self,"_last_document",None)
        return previous if any(previous is doc for doc in self.documents.values()) else None

    def document_activated(self, doc):
        if not isinstance(doc, PlotDocument) or self._activating or self._syncing_documents:
            return
        self._activating = True
        self._last_document=doc
        self._drag_legend = None
        try:
            for curve in self.curves:curve.activate_view(doc.key if self._is_overlay(doc.key) else None)
            self.figure, self.canvas, self.toolbar = doc.figure, doc.canvas, doc.navigation
            domain = self.plot_options.get(doc.key, {}).get("x_domain")
            if domain is not None:
                self.domain = domain
                self.domain_box.blockSignals(True); self.domain_box.setCurrentIndex(("temperature", "time", "signal").index(domain)); self.domain_box.blockSignals(False)
            if not self._is_overlay(doc.key):
                current = self.selected()
                index = self.curves.index(current) if current is not None and current.dataset.document_key == doc.key else next((i for i, c in enumerate(self.curves) if c.dataset.document_key == doc.key), None)
                if index is not None:
                    with QSignalBlocker(self.files):
                        self.files.setCurrentItem(self.files.topLevelItem(index))
            MainWindow.selection_changed(self)
        finally:
            self._activating = False

    def selection_changed(self):
        if self._updating:
            return
        c = self.selected()
        if hasattr(self, "mdi") and not self._activating and not self._syncing_documents and c:
            active = self.active_document()
            if not isinstance(active, PlotDocument) or not self._is_overlay(active.key):
                doc = self.documents.get(c.dataset.document_key)
                if doc and doc is not active:
                    self.mdi.setActiveSubWindow(doc)
        MainWindow.selection_changed(self)

        cycle_action=self.classic_actions.get("CycleLimits1")
        if cycle_action is not None:
            from .data_limits import cycle_index
            target=self.selected()
            cycle_action.setEnabled(target is not None and cycle_index(target.dataset) is not None)

    def visible_curves(self):
        if not hasattr(self, "mdi"):
            return []
        active = self.active_document()
        if not isinstance(active, PlotDocument):
            return []
        if self._is_overlay(active.key):
            return [c for c in self._document_curves(active) if c.visible and c.overlay_enabled and len(c.active_rows)>=2]
        return [c for c in self.curves if c.visible and c.dataset.document_key == active.key and c.normal_enabled and len(c.active_rows)>=2]

    def display_x_offset(self,curve):
        if curve is None or not hasattr(self,"mdi"):return 0.
        doc=self.active_document()
        if not isinstance(doc,PlotDocument) or not self._is_overlay(doc.key):return 0.
        members=[c for c in self._document_curves(doc) if c.overlay_enabled and c.axis==curve.axis]
        position=next((i for i,c in enumerate(members) if c.uid==curve.uid),None)
        if position is None:return 0.
        options=self.plot_options.get(doc.key,{})
        return float(position*options.get("axis_x_offsets",[0.]*4)[curve.axis])

    def change_domain(self, index):
        if self._updating or not hasattr(self, "mdi"): return
        domain = ("temperature", "time", "signal")[index]
        doc = self.active_document()
        try:
            for curve in self.visible_curves(): curve.x_values(domain)
            if domain == "signal" and len({(c.x_unit(domain), c.x_signal_type) for c in self.visible_curves()}) > 1:
                raise ValueError("叠图X信号单位及类型必须一致")
        except ValueError as exc:
            self.domain_box.blockSignals(True); self.domain_box.setCurrentIndex(("temperature", "time", "signal").index(self.domain)); self.domain_box.blockSignals(False)
            self.warn(str(exc)); return
        self.domain = domain
        if isinstance(doc, PlotDocument):
            options = self.plot_options.setdefault(doc.key, default_plot_options()); options["x_domain"] = domain
            options.update(x_limits=None, x_ticks=None, auto_x=True)
            doc.plot_signature = None
        self.cancel_measurement(redraw=False); self.touch(); self.selection_changed()

    def current_data_curve(self):
        selected=self.selected();visible=self.visible_curves()
        return selected if selected in visible or not visible else visible[0]

    def refresh_curve(self,uid):
        index=next((i for i,c in enumerate(self.curves) if c.uid==uid),None)
        if index is not None:self.files.setCurrentItem(self.files.topLevelItem(index))
        self.selection_changed()

    def select_plot_axis(self,axis):
        curve=next((c for c in self.visible_curves() if c.axis==axis),None)
        if curve is not None:self.refresh_curve(curve.uid)
        else:self.statusBar().showMessage(f"Y{axis+1}没有绘制曲线。",4000)

    def show_native_smooth(self):
        curve=self.current_data_curve()
        if curve is None:return
        from .smoothing_dialog import SmoothDialog
        old=self.dialogs.get("smooth")
        if old and old.isVisible():old.raise_();return old
        try:dialog=SmoothDialog(self,curve)
        except ValueError as exc:self.warn(str(exc));return
        self.dialogs["smooth"]=dialog;dialog.show();return dialog

    def smoothing_rules(self):
        from copy import deepcopy
        from .data_limits import smoothing_rule
        if "__settings__" in self.plot_options:return deepcopy(self.plot_options["__settings__"]["smoothing_rules"])
        return deepcopy(self._session_smooth_rules) or [smoothing_rule(c) for c in self.curves if c.smooth_reuse and c.smooth_domain is not None]

    def remember_smoothing(self,curve,previous=None):
        from copy import deepcopy
        from .data_limits import smoothing_rule,rule_key
        rule=smoothing_rule(curve)
        if rule is None and previous is not None:rule=dict(previous,enabled=False)
        if rule is None:return
        rules=[r for r in self.smoothing_rules() if rule_key(r)!=rule_key(rule)]+[rule]
        self._session_smooth_rules=deepcopy(rules)
        self.plot_options.setdefault("__settings__",default_plot_options())["smoothing_rules"]=rules

    def show_data_limits(self,kind=None):
        curve=self.current_data_curve()
        if curve is None:return
        from .limits_dialog import DataLimitsDialog,LimitBoundsDialog
        from .data_limits import cycle_index
        if kind=="cycle" and cycle_index(curve.dataset) is None:
            self.statusBar().showMessage("文件没有明确的循环编号信号。",5000);return
        old=self.dialogs.get("data_limits")
        if old and old.isVisible():old.raise_();return old
        dialog=LimitBoundsDialog(self,curve,kind) if kind else DataLimitsDialog(self,curve)
        self.dialogs["data_limits"]=dialog;dialog.show();return dialog

    def full_data_range(self):
        curve=self.current_data_curve()
        if curve is not None:
            try:self.apply_data_limits(curve.dataset,None,curve_uid=curve.uid)
            except ValueError as exc:self.warn(str(exc))

    def apply_data_limits(self,dataset,spec,*,curve_uid=None):
        from copy import deepcopy
        from .data_limits import limits_proposal
        if not any(c.dataset.document_key==dataset.document_key for c in self.curves):raise ValueError("此数据文件已关闭")
        if curve_uid is not None and not any(c.uid==curve_uid and c.dataset.document_key==dataset.document_key for c in self.curves):raise ValueError("此曲线已关闭")
        draft=limits_proposal(self.curves,dataset,spec,self.domain,curve_uid=curve_uid)
        source=[c for c,old in zip(draft,self.curves) if c is not old]
        selected=self.selected();uid=curve_uid or (selected.uid if selected else source[0].uid)
        range_keys=("auto_x","auto_y","x_limits","y_limits","x_ticks","y_ticks")
        keys=[key for key in (dataset.document_key,) if key in self.plot_options]
        keys += [key for key in self.plot_options if self._is_overlay(key)]
        before={key:{name:deepcopy(self.plot_options[key][name]) for name in range_keys} for key in keys}
        transaction={"source":dataset.document_key,"checkpoints":{c.uid:c.history[-1] for c in source},"ranges":before}
        self.cancel_measurement(redraw=False);self.curves=draft
        for key in keys:
            self.plot_options[key].update(auto_x=True,auto_y=[True]*4,x_limits=None,y_limits=[None]*4,x_ticks=None,y_ticks=[None]*4)
            if key in self.documents:self.documents[key].plot_signature=None
        transaction["after"]={key:{name:deepcopy(self.plot_options[key][name]) for name in range_keys} for key in keys}
        for state in transaction["checkpoints"].values():self._limits_undo[id(state)]=transaction
        self.touch();self.refresh_curve(uid)
        self.statusBar().showMessage("数据界限已应用；原始文件未改。",5000)

    def undo(self):
        curve=self.selected()
        transaction=self._limits_undo.get(id(curve.history[-1])) if curve and curve.history else None
        if transaction is None:
            from .data_limits import smoothing_rule
            before=smoothing_rule(curve) if curve is not None else None
            MainWindow.undo(self)
            if curve is not None and before is not None:self.remember_smoothing(curve,before)
            return
        states=transaction["checkpoints"]
        current=[c for c in self.curves if c.uid in states]
        if {c.uid for c in current}!=set(states) or any(not c.history or c.history[-1] is not states[c.uid] for c in current):
            self.statusBar().showMessage("请先撤销此文件较新的处理；也可用‘全范围’重新读取。",6000);return
        for item in current:item.undo()
        for key,values in transaction["ranges"].items():
            if key in self.plot_options:
                for name,value in values.items():
                    if self.plot_options[key][name]==transaction["after"][key][name]:self.plot_options[key][name]=value
        for state in states.values():self._limits_undo.pop(id(state),None)
        self.touch();self.selection_changed()

    def redraw(self, *_):
        if getattr(self, '_import_batch', False): return
        if not hasattr(self, "mdi"):
            return
        active = self.active_document()
        if not isinstance(active, PlotDocument):
            return
        self._drag_legend = None
        self.figure, self.canvas, self.toolbar = active.figure, active.canvas, active.navigation
        curves = self.visible_curves()
        options = self.plot_options.get(active.key, default_plot_options())
        signature = (self.domain, tuple((id(c.dataset), c.y_index, c.axis, c.x_shift, c.scale, c.offset,self.display_x_offset(c), id(c.working),tuple(sorted((c.unit_options or {}).items())),
            (c.sample_size_mm,tuple(c.data_indices) if c.data_indices is not None else None) if c.unit_options is not None else None) for c in curves))
        old_limits = {i: (axis.get_xlim(), axis.get_ylim()) for i, axis in active.plot_axes.items()} if active.plot_signature == signature else {}
        MainWindow.redraw(self)
        # Measured reference paper: 1920x951, frame (217,97)-(1800,856).
        # Normalize the paper geometry so window resizing and exports agree.
        used = {c.axis for c in curves}
        self.figure.subplots_adjust(left=.20 if 3 in used else 217/1920, right=.78 if 2 in used else (.85 if 1 in used else .9375), top=1-97/951, bottom=95/951)
        scale = max(.25, self.figure.bbox.width / 1920)
        base = self.axes[0]
        base.set_title("", loc="left")
        base.set_title("")
        for index, axis in self.axes.items():
            axis.grid(False, which="both")
            if index == 0:
                for grid_axis, enabled in (("x", options["grid_x"]), ("y", options["grid_y"])):
                    if enabled:
                        axis.grid(True, axis=grid_axis, which="both" if options["grid_minor"] else "major", color="#b0b0b0", linewidth=.5)
            axis.tick_params(axis="both", which="both", colors="black", direction="out", top=False, right=False, labelsize=21.5*scale, width=.55, labelfontfamily="Times New Roman")
            axis.tick_params(axis="x", which="major", length=8*scale, pad=7*scale)
            axis.tick_params(axis="y", which="major", length=11.5*scale, pad=8.5*scale)
            axis.tick_params(axis="y", which="both", left=index in (0, 3), right=index in (1, 2))
            axis.tick_params(which="minor", length=4.5*scale)
            axis.xaxis.set_minor_locator(AutoMinorLocator(4))
            axis.yaxis.set_minor_locator(AutoMinorLocator(4))
            if index in old_limits:
                if index in active.plot_ranges and np.allclose(old_limits[index], active.plot_ranges[index]):
                    xticks, yticks = active.plot_ticks[index]
                else:
                    _, xticks = nice_limits(np.array(old_limits[index][0]))
                    _, yticks = nice_limits(np.array(old_limits[index][1]))
                axis.set_xticks(xticks)
                axis.set_yticks(yticks)
                axis.set_xlim(old_limits[index][0])
                axis.set_ylim(old_limits[index][1])
            else:
                matching = [(c, x, y) for c, x, y in self._plot_artists if c.axis == index]
                if matching:
                    ylim, yticks = nice_limits(np.concatenate([y for c, x, y in matching]))
                    axis.set_ylim(*ylim)
                    axis.set_yticks(yticks)
                if self._plot_artists:
                    xlim, xticks = nice_limits(np.concatenate([x+self.display_x_offset(c) for c, x, y in self._plot_artists]))
                    axis.set_xlim(*xlim)
                    axis.set_xticks(xticks)
            if not options["auto_x"] and options["x_limits"] is not None:
                axis.set_xlim(options["x_limits"])
                axis.xaxis.set_major_locator(MaxNLocator(nbins=5, steps=[1, 2, 5, 10]))
            if not options["auto_y"][index] and options["y_limits"][index] is not None:
                axis.set_ylim(options["y_limits"][index])
                axis.yaxis.set_major_locator(MaxNLocator(nbins=5, steps=[1, 2, 5, 10]))
            for coordinate, setting in ((axis.xaxis, options.get("x_ticks")), (axis.yaxis, options.get("y_ticks", [None]*4)[index])):
                if setting is not None:
                    coordinate.set_major_locator(MultipleLocator(setting["label_interval"]))
                    coordinate.set_minor_locator(MultipleLocator(setting["tick_interval"]))
                    offset = setting["label_offset"]
                    coordinate.set_major_formatter(FuncFormatter(lambda value, pos, delta=offset: f"{value+delta:.12g}"))
            axis.set_ylabel(options["y_labels"][index] or localized_signal(axis.get_ylabel()), fontsize=22.5*scale, labelpad=45*scale)
            axis.set_xlabel(options["x_label"] or localized_signal(self._plot_artists[0][0].x_label(self.domain) if self._plot_artists else self.domain), fontsize=21.5*scale, labelpad=4*scale)
            for spine in axis.spines.values():
                spine.set_color("black")
                spine.set_linewidth(.55)
                spine.set_antialiased(False)
            for label in [axis.xaxis.label, axis.yaxis.label] + axis.get_xticklabels() + axis.get_yticklabels():
                label.set_fontfamily(PLOT_FONTS)
            for line in axis.lines:
                line.set_antialiased(False)
                line.set_snap(True)
            for annotation in axis.texts:
                annotation.set_fontfamily(PLOT_FONTS)
                annotation.set_fontsize(max(8, 14*scale))
        for entry, annotation in self._result_annotations:
            from .measurement import apply_text_style
            apply_text_style(entry, annotation)
        ds = curves[0].dataset if curves else None
        if ds is not None:
            def field(name):
                return "; ".join(ds.metadata.get(name, []))
            self.figure.text(8/1920, 1, options["title"] or f"样品: {curves[0].sample_name}", ha="left", va="top", fontsize=22*scale, fontfamily=PLOT_FONTS, color="black", parse_math=False, gid="tma-header")
            module = (field("Module").split() or ["TMA"])[0]
            source = str(ds.path)
            self.figure.text(.996, 1, f"{module} 文件: {source}", ha="right", va="top", fontsize=22*scale, fontfamily=PLOT_FONTS, color="black", parse_math=False, gid="tma-source")
        self.figure.text(.996, .017, "Power By ZzzHe", ha="right", fontsize=20*scale, fontfamily="Times New Roman")
        if self._is_overlay(active.key): active.setWindowTitle(options["window_name"] or self._overlay_title(active.key))
        for curve, x, y in self._plot_artists:
            line = next((line for line in self.axes[curve.axis].lines if getattr(line, "_tma_curve_uid", None) == curve.uid), None)
            if line is not None:
                spacing = options["graph_symbol_spacing"][curve.axis]
                line.set_markevery(max(1, len(x)//{"coarse": 20, "medium": 60, "fine": 120, "every": max(1, len(x))}[spacing]))
                if not options["graph_show_symbols"][curve.axis] and curve.style != "None": line.set_marker("")
        for index, axis in self.axes.items():
            axis.yaxis.set_visible(options["graph_axis_visible"][index] and index in used)
            mode = options["graph_grid_types"][index]
            if mode:
                axis.grid(True, axis="both", which="both" if mode == 2 else "major", color="#b7b7b7", lw=.4)
        render_legend(self, base, options, PLOT_FONTS, scale)
        if options["secondary_x"] and self.domain in ("temperature", "time") and curves:
            from .secondary_axis import add_secondary_axis
            add_secondary_axis(base,curves[0],self.domain,PLOT_FONTS,scale,display_x_offset=self.display_x_offset(curves[0]))
        active.plot_signature = signature
        active.plot_axes = dict(self.axes)
        active.plot_ticks = {i: (axis.get_xticks().copy(), axis.get_yticks().copy()) for i, axis in self.axes.items()}
        active.plot_ranges = {i: (axis.get_xlim(), axis.get_ylim()) for i, axis in self.axes.items()}
        from .axis_layout import fit_y_gaps
        fit_y_gaps(self,scale)
        self.layout_result_annotations()
        if any(flags["line"] or flags["symbol"] for flags in options["axis_flags"]): self.canvas.draw()
        renderer = self.canvas.get_renderer()
        for index, axis in self.axes.items():
            flags = options["axis_flags"][index]
            curve = next((c for c, _, _ in self._plot_artists if c.axis == index), None)
            if curve is None: continue
            color = curve.color if flags["color"] else "black"
            axis.yaxis.label.set_color(color)
            if flags["line"] or flags["symbol"]:
                bounds = axis.yaxis.label.get_window_extent(renderer)
                x = (bounds.x0+bounds.x1)/2/self.figure.bbox.width
                y = (bounds.y1+10*scale)/self.figure.bbox.height
                height = 22*scale/self.figure.bbox.height
                from .graph_options import render_style
                glyph = Line2D([x, x, x], [y, y+height/2, y+height], transform=self.figure.transFigure,
                               color=color, lw=.8, ls=render_style(curve.style) if flags["line"] else "None",
                               marker=curve.marker if flags["symbol"] else "", markevery=[1], ms=4, clip_on=False)
                glyph.set_gid(f"tma-axis-style-{index}"); self.figure.add_artist(glyph)
        self.canvas.draw_idle()

    def canvas_resized(self, event):
        if hasattr(self, "_plot_resize_timer") and event.canvas is self.canvas:
            self._plot_resize_timer.start(60)

    def result_press(self, event):
        if (getattr(event, "canvas", self.canvas) is self.canvas and event.button == 1 and self.current_measurement() is None
                and not self.range_enabled.isChecked() and not self.toolbar.mode and 0 in self.axes):
            legend = self.axes[0].get_legend()
            if legend is not None and legend.get_visible() and event.x is not None and event.y is not None:
                bounds = legend.get_window_extent(self.canvas.get_renderer())
                if bounds.contains(event.x, event.y):
                    if getattr(event, "dblclick", False):
                        self.edit_legend_options(); return
                    doc = self.active_document()
                    options = self.plot_options.get(doc.key, default_plot_options())
                    anchor = options["legend_anchor"] or {"x": 1., "y": 1., "horizontal": "right", "vertical": "top"}
                    self._drag_legend = (doc, legend, event.x, event.y, bounds.frozen(), dict(anchor), False)
                    return
            if getattr(event,"inaxes",None) is None and event.x is not None and event.y is not None and self.result_annotation_at(event.x,event.y) is None:
                axis=self.axis_at_position(event.x,event.y)
                if isinstance(axis,int):self.select_plot_axis(axis);return
        MainWindow.result_press(self, event)

    def result_motion(self, event):
        if self._drag_legend is not None:
            doc, legend, x, y, bounds, anchor, moved = self._drag_legend
            if event.canvas is not doc.canvas or event.x is None or event.y is None: return
            if not moved and abs(event.x-x)+abs(event.y-y) < 3: return
            value = moved_anchor(self.axes[0], bounds, anchor, event.x-x, event.y-y)
            apply_anchor(legend, self.axes[0], value)
            self._drag_legend = (doc, legend, x, y, bounds, anchor, True)
            self.canvas.draw_idle(); return
        MainWindow.result_motion(self, event)

    def result_release(self, event):
        if self._drag_legend is not None:
            doc, legend, x, y, bounds, anchor, moved = self._drag_legend
            self._drag_legend = None
            if moved and event.canvas is doc.canvas:
                # The last drawn position is authoritative if release is
                # outside the canvas or has no usable mouse coordinates.
                shown = legend.get_window_extent(doc.canvas.get_renderer())
                value = moved_anchor(self.axes[0], shown, anchor, 0, 0)
                self.plot_options.setdefault(doc.key, default_plot_options())["legend_anchor"] = value
                self.touch()
            return
        MainWindow.result_release(self, event)

    def edit_legend_options(self):
        doc = self.active_document()
        if isinstance(doc, PlotDocument) and self._is_overlay(doc.key):
            dialog = self.show_overlay_options(); dialog.tabs.setCurrentIndex(3)
            return dialog

    def create_plot_context_menu(self):
        """Use the same actions as the main menu, in the supplied popup order."""
        if self.current_measurement() is not None:
            return self.create_measurement_menu()
        menu = QMenu(self)
        def action(name, label=None):
            existing = self.classic_actions.get(name)
            if existing:
                if label is None: menu.addAction(existing)
                else:
                    clone = menu.addAction(label); clone.setEnabled(existing.isEnabled())
                    clone.setToolTip(existing.toolTip()); clone.triggered.connect(existing.trigger)
        action("Open1", "打开")
        save = menu.addMenu("保存分析")
        for name in ("SaveSession1", "AnalysisOnly1", "AnalysisAndData1"):
            if name in self.classic_actions: save.addAction(self.classic_actions[name])
        action("Print1", "打印"); menu.addSeparator(); action("Annotate1", "批注")
        menu.addSeparator()
        for name, label in (("ManualRescale1", "手动重定刻度"), ("FullScaleAxis1", "坐标轴满刻度"), ("FullScaleAll1", "全部坐标轴满刻度")):
            action(name, label)
        menu.addSeparator()
        for name, label in (("Signals1", "信号"), ("FullRangeLimits1", "全范围数据"), ("CursorLimits1", "光标数据界限"), ("TimeLimits1", "时间数据界限"), ("TemperatureLimits1", "温度数据界限")):
            action(name, label)
        menu.addSeparator()
        xmenu = menu.addMenu("X 轴")
        for name in ("XTime1", "XTemp1"):
            if name in self.classic_actions: xmenu.addAction(self.classic_actions[name])
        overlay = menu.addMenu("叠加")
        for name in ("AutoConfigure1", "ManualSetup1", "Edit4", "Copy4", "ShowOverlayPlot1", "ShowNormalPlot1"):
            if name in self.classic_actions: overlay.addAction(self.classic_actions[name])
        action("GraphOptions1", "曲线图选项"); menu.addSeparator()
        self._build_visibility_menu(menu)
        for name, label in (("AlphaAtX1", "Alpha于X"), ("AlphaX1ToX21", "Alpha X1 至 X2"), ("AlphaFitX1ToX21", "线性拟合Alpha X1 至 X2"), ("DimensionChange1", "尺寸变化")):
            action(name, label)
        menu.addSeparator()
        for name, label in (("Linear1", "线性峰值积分"), ("SigHorizontal1", "水平 S 形曲线峰值积分"), ("PeakMax1", "峰最大"), ("SignalMax1", "信号最大"), ("SignalChange1", "信号变化"), ("HeightChange", "高度差"), ("GlassTransition1", "玻璃化转变"),("StepTransition2","步阶转变"), ("OnsetPoint1", "始点"), ("Slope1", "斜率"), ("PeakRunningIntegral1", "执行积分"), ("CurveValueAtX1", "曲线值于X轴"), ("CurveValueAtY1", "曲线值于Y轴")):
            action(name, label)
        menu.addSeparator(); action("AnalysisOptions1", "分析选项")
        if self._measurement_artists and self.current_measurement() is None:
            menu.addSeparator()
            menu.addAction("调整分析点", lambda: self.edit_measurement())
        if self._result_annotations and self.current_measurement() is None:
            labels_menu = menu.addMenu("分析文字显隐")
            added = set()
            for entry, text in self._result_annotations:
                if id(entry) in added: continue
                added.add(id(entry))
                caption = (text.get_text().splitlines() or ["分析结果"])[0]
                submenu = labels_menu.addMenu(f"{Path(entry['file']).name} · {caption}")
                self.add_label_visibility_actions(submenu, entry)
        if any(r.get("annotation", {}).get("hidden", False) for r in self.results):
            menu.addSeparator(); menu.addAction("显示隐藏结果", self.show_hidden_results)
        return menu

    def show_plot_context_menu(self, doc, point):
        if self.active_document() is not doc:
            self.mdi.setActiveSubWindow(doc); self.document_activated(doc)
        self._context_point = (point.x(), doc.canvas.height() - point.y())
        if self.current_measurement() is not None:
            for editor in self._measurement_artists:
                if editor.entry is self._pending_measurement:
                    hit = editor.hit(*self._context_point)
                    if hit is not None: self.activate_measurement_point(hit)
            menu = self.create_measurement_menu()
            menu.exec(doc.canvas.mapToGlobal(point))
            menu.deleteLater()
            return
        hit = self.result_annotation_at(*self._context_point)
        if hit is not None:
            menu = self.create_result_context_menu(*hit)
            menu.exec(doc.canvas.mapToGlobal(point)); menu.deleteLater()
            return
        legend = self.axes.get(0).get_legend() if 0 in self.axes else None
        if (self._is_overlay(doc.key) and legend is not None and legend.get_visible()
                and legend.get_window_extent(doc.canvas.get_renderer()).contains(*self._context_point)):
            self.edit_legend_options(); return
        selected_axis = self.axis_at_position(*self._context_point)
        if selected_axis is not None:
            self.manual_rescale(selected_axis)
            return
        menu = self.create_plot_context_menu()
        menu.exec(doc.canvas.mapToGlobal(point))
        menu.deleteLater()

    def current_measurement(self):
        pending = self._pending_measurement
        return pending if any(editor.entry is pending for editor in self._measurement_artists) else None

    def result_annotation_at(self, x, y):
        from matplotlib.text import Text
        self.canvas.draw()
        renderer = self.canvas.get_renderer()
        for entry, annotation in reversed(self._result_annotations):
            if annotation.get_visible() and annotation.get_text() and Text.get_window_extent(annotation, renderer).expanded(1.05, 1.2).contains(x, y):
                return entry, annotation
        for editor in reversed(self._measurement_artists):
            if editor.entry["kind"] in ("curve_value","curve_value_y") and editor.markers[0].get_visible():
                px,py=editor.axis.transData.transform(editor.display_coords[0])
                if np.hypot(px-x,py-y)<=10:return editor.entry,editor.annotation
        return None

    def create_result_context_menu(self, entry, annotation):
        from .measurement import annotation_key
        label_key = annotation_key(annotation)
        menu = QMenu(self); menu.setObjectName("ObjectPopupMenu")
        style = dict(entry.get("annotation", {}).get("text_style", {}))
        style.update(entry.get("annotation", {}).get("label_styles", {}).get(label_key, {}))
        for key, caption in (("bold", "粗体"), ("italic", "斜体")):
            action = menu.addAction(caption); action.setCheckable(True); action.setChecked(style.get(key, False))
            action.triggered.connect(lambda checked, key=key: self.style_result(entry, key, checked, label_key))
        sizes = menu.addMenu("字号")
        for size in (8, 10, 12, 14, 16, 18, 20, 24):
            action = sizes.addAction(str(size)); action.triggered.connect(lambda checked=False, size=size: self.style_result(entry, "size", size, label_key))
        menu.addAction("隐藏此文字", lambda: self.style_result(entry, "hidden", True, label_key))
        self.add_label_visibility_actions(menu.addMenu("文字显隐"), entry)
        menu.addSeparator()
        if "interactive" in entry: menu.addAction("调整结果", lambda: self.edit_measurement(entry))
        if entry["kind"] in ("curve_value","curve_value_y"):menu.addAction("标注选项…",lambda:self.edit_point_label(entry))
        menu.addAction("删除结果", lambda: self.delete_result(entry))
        menu.addAction("隐藏结果", lambda: self.hide_result(entry))
        menu.addAction("复制文字", lambda: QApplication.clipboard().setText(annotation.get_text().splitlines()[0] if getattr(annotation, '_tma_split', False) else annotation.get_text()))
        return menu

    def add_label_visibility_actions(self, menu, entry):
        from .measurement import annotation_key
        texts = []
        for result, text in self._result_annotations:
            if result is not entry or not text.get_text(): continue
            key = annotation_key(text)
            if entry['kind'] == 'glass_transition' and key.startswith('t'): continue
            caption = (text.get_text().splitlines() or ["分析结果"])[0]
            texts.append((key, caption, text))
        for key, caption, text in texts:
            action = menu.addAction(caption); action.setCheckable(True); action.setChecked(text.get_visible())
            action.triggered.connect(lambda checked, key=key: self.style_result(entry, "hidden", not checked, key))

    def style_result(self, entry, key, value, label_key=None):
        options = entry.setdefault("annotation", {})
        style = options.setdefault("text_style", {}) if label_key is None else options.setdefault("label_styles", {}).setdefault(label_key, {})
        style[key] = value
        self.touch(); self.redraw()

    def delete_result(self, entry):
        children={c.uid for c in self.curves if c.derived is not None and c.derived['parent_id']==entry.get('analysis_id')}
        if children:self.remove_derived_curves(children)
        self.results[:] = [result for result in self.results if result is not entry]
        self.touch(); self.refresh_results(); self.redraw()

    def remove_derived_curves(self,ids):
        """Remove dependent quantities and their annotations/membership together."""
        if not ids:return
        if self._pending_measurement is not None and self._pending_measurement.get('curve_id') in ids:self.cancel_measurement(redraw=False)
        self.curves[:]=[c for c in self.curves if c.uid not in ids]
        self.results[:]=[r for r in self.results if r.get('curve_id') not in ids]
        self.sync_documents();self.rebuild_files()

    def hide_result(self, entry):
        entry.setdefault("annotation", {})["hidden"] = True
        self.touch(); self.redraw()

    def show_hidden_results(self):
        for entry in self.results: entry.setdefault("annotation", {}).pop("hidden", None)
        self.touch(); self.redraw()

    def create_measurement_menu(self):
        menu = QMenu(self)
        menu.setObjectName("CursorPopupMenu")
        menu.addAction(self.measurement_confirm)
        menu.addAction("编辑…", self.edit_measurement_limits).setObjectName("ManualLimits1")
        auto=menu.addAction('自动界限',self.show_auto_limits);auto.setObjectName('AutoLimits1')
        from .auto_limits import family
        auto.setEnabled(self._pending_measurement is not None and family(self._pending_measurement) is not None)
        if not auto.isEnabled():auto.setToolTip('此模式可用恢复初始界限')
        menu.addAction(self.measurement_cancel)
        if not auto.isEnabled():menu.addAction("恢复初始界限",self.reset_measurement_limits).setObjectName("ResetLimits1")
        menu.addSeparator()
        pending = self._pending_measurement
        if pending:
            for point in range(len(pending["interactive"]["indices"])):
                action = menu.addAction(f"点 {point+1}", lambda checked=False, point=point: self.activate_measurement_point(point))
                action.setCheckable(True)
                action.setChecked(point == pending["interactive"].get("active_point", 0))
        return menu

    def activate_measurement_point(self, point):
        for editor in self._measurement_artists:
            if editor.entry is self._pending_measurement:
                editor.entry["interactive"]["active_point"] = point
                editor.update(active=point); self.canvas.draw_idle()
                self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def reset_measurement_limits(self):
        pending = self._pending_measurement
        if pending is None: return
        pending["interactive"]["indices"] = list(pending["interactive"]["initial_indices"])
        if "initial_positions" in pending["interactive"]:
            pending["interactive"]["positions"]=list(pending["interactive"]["initial_positions"])
        else:pending["interactive"].pop("positions", None)
        if "initial_target_y" in pending["interactive"]:pending["interactive"]["target_y"]=pending["interactive"]["initial_target_y"]
        pending["interactive"].pop("manual_y", None)
        self.redraw(); self.activate_measurement_point(0); self._update_measurement_controls()

    def edit_measurement_limits(self):
        if self._pending_measurement is None: return
        from .classic_dialogs import CursorLimitsDialog
        dialog = CursorLimitsDialog(self)
        self.dialogs["cursor_limits"] = dialog
        dialog.show()
        return dialog

    def add_note(self):
        curves = self.visible_curves()
        c = self.selected()
        if c not in curves: c = curves[0] if curves else None
        if c is None: return
        from .mass_lookup import default_note_text
        dialog = QInputDialog(self)
        dialog.setWindowTitle("批注")
        dialog.setLabelText("文字（支持多行）")
        dialog.setOption(QInputDialog.InputDialogOption.UsePlainTextEditForTextInput)
        dialog.setTextValue(default_note_text(c.sample_name))
        dialog.setOkButtonText("确定"); dialog.setCancelButtonText("取消")
        dialog.setMinimumSize(560, 300); dialog.resize(680, 380)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        text = dialog.textValue()
        dialog.deleteLater()
        if not accepted or not text.strip(): return
        axis = self.axes[c.axis]
        # 默认放在鼠标位置；否则放在该坐标轴视图中心（显示像素坐标）。
        # ``axis.bbox`` 是图形分数坐标，不能直接喂给 ``transData``，否则批注会落到错误位置。
        pixel = getattr(self, "_context_point", None)
        if pixel is None:
            renderer = self.canvas.get_renderer()
            bounds = axis.get_window_extent(renderer)
            pixel = ((bounds.x0 + bounds.x1) / 2, (bounds.y0 + bounds.y1) / 2)
        x, y = axis.transData.inverted().transform(pixel)
        x-=self.display_x_offset(c)
        self.results.append({"file": c.dataset.path.name, "sha256": c.dataset.sha256, "curve_id": c.uid, "kind": "note",
                             "domain": self.domain, "lo": float(x), "hi": float(x), "signal": c.result_label,
                             "operations": list(c.operations), "transform": c.result_transform(self.domain),
                             "values": {"x": float(x), "y": float(y), "text": text}, "annotation": {}})
        self.touch(); self.refresh_results(); self.redraw()

    def print_plot(self):
        if not self.visible_curves(): return
        from PySide6.QtPrintSupport import QPrinter, QPrintDialog
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        pixmap = self.output_pixmap()
        painter = QPainter(printer)
        viewport = painter.viewport()
        size = pixmap.size(); size.scale(viewport.size(), Qt.AspectRatioMode.KeepAspectRatio)
        painter.setViewport(viewport.x(), viewport.y(), size.width(), size.height())
        painter.setWindow(pixmap.rect()); painter.drawPixmap(0, 0, pixmap); painter.end()

    def full_scale(self):
        doc = self.active_document()
        if isinstance(doc, PlotDocument):
            options = self.plot_options.get(doc.key)
            if options:
                options.update(auto_x=True, auto_y=[True]*4, x_ticks=None, y_ticks=[None]*4)
                self.touch()
            doc.plot_signature = None
            self.redraw()

    def finish_import(self, datasets, failures):
        self._import_batch = True
        try:
            self._finish_import_batch(datasets, failures)
        finally:
            self._import_batch = False
        if datasets:
            self._show_document(datasets[-1].document_key)
        else: self.redraw()

    def _finish_import_batch(self, datasets, failures):
        before = {c.dataset.document_key for c in self.curves}
        rules=self.smoothing_rules()
        MainWindow.finish_import(self, datasets, failures)
        for i, c in enumerate(self.curves):
            if c.dataset.document_key not in before:
                c.color = "#000000"
                c.width = .45
        if datasets:
            saved = self.user_defaults("graph")
            for dataset in datasets:
                self.apply_default_appearance([c for c in self.curves if c.dataset is dataset], saved)
                template = saved["options"].get("signal_defaults")
                if template:
                    from .signals_dialog import build_proposal
                    try:
                        self.curves = build_proposal(self.curves, dataset, template)
                        options = self.plot_options.setdefault(dataset.document_key, default_plot_options())
                        options.update(x_domain=template["x"]["domain"], secondary_x=template["secondary"])
                    except ValueError as exc: self.log.appendPlainText(f"信号默认设置未应用于{dataset.path.name}：{exc}")
                if rules:
                    from .data_limits import reusable_smoothing
                    domain=self.plot_options.get(dataset.document_key,{}).get("x_domain") or self.domain
                    for curve in [c for c in self.curves if c.dataset is dataset and c.normal_enabled]:
                        try:
                            values=reusable_smoothing(curve,rules,domain)
                            if values:
                                for key,value in values.items():setattr(curve,key,value)
                        except ValueError as exc:self.log.appendPlainText(f"平滑复用未应用于{dataset.path.name}：{exc}")
        self.sync_documents()
        # Hidden documents draw when activated; import paints only the last one.
        self.rebuild_files()
        self.statusBar().clearMessage()

    def open_files(self):
        from .path_settings import import_folder
        paths, _ = QFileDialog.getOpenFileNames(self, "打开数据文件", import_folder(), "TA 数据 / TMA 会话 (*.0?? *.1?? *.2?? *.3?? *.4?? *.5?? *.6?? *.7?? *.8?? *.9?? *.tai *.txt *.tmas);;所有文件 (*)")
        if not paths:
            return
        sessions = [p for p in paths if Path(p).suffix.casefold() == ".tmas"]
        if sessions:
            if len(paths) != 1:
                self.warn("会话文件请单独打开。")
            elif self.confirm_discard():
                self.restore_session(paths[0])
        else:
            self.import_files(paths)

    def restore_session(self, path):
        old_curves = self.curves
        self._restoring_session = True
        try:
            MainWindow.restore_session(self, path)
            if self.curves is not old_curves:
                self._limits_undo.clear()
                self._session_smooth_rules=[]
                self._session_smooth_rules=self.smoothing_rules()
                for key in [k for k in self.documents if self._is_overlay(k)]:
                    doc = self.documents.pop(key)
                    self.mdi.removeSubWindow(doc)
                    doc.deleteLater()
                self._overlay_seq = 0
                self.sync_documents()
                saved=[key for key in self.plot_options if self._is_overlay(key)]
                if self.curves and saved:
                    active_key=next((c.active_overlay_key for c in self.curves if c.active_overlay_key in saved),saved[0])
                    for key in saved:
                        doc=self._document(key)
                        if doc.curve_uids is None:
                            doc.curve_uids=[c.uid for c in self.curves if c.overlay_enabled]
                            self.plot_options[key]["overlay_members"]=list(doc.curve_uids)
                        doc.show()
                    self._show_document(active_key)
                elif self.curves:self.show_overlay()
        finally:
            self._restoring_session = False

    def touch(self):
        self.dirty = True
        self.setWindowTitle(f"{APP_NAME} {__version__} *")

    def _update_measurement_controls(self):
        MainWindow._update_measurement_controls(self)
        self.statusBar().setFixedHeight(19)

    def show_overlay(self):
        if not self.curves:
            return
        members = self._overlay_members()
        if not members:
            return
        if sum(self._is_overlay(key) for key in self.documents)>=20:
            self.statusBar().showMessage("最多可打开20张叠图，请先关闭一张。",6000);return
        first_overlay = not any(self._is_overlay(k) for k in self.documents)
        if first_overlay and not getattr(self, "_restoring_session", False):
            # Defaults apply to the first overlay only, not ordinary graphs.
            key=self._next_overlay_key()
            for curve in self.curves:curve.activate_view(key)
            self.apply_default_appearance(members, self.user_defaults("overlay"))
        else:key=self._next_overlay_key()
        self._open_overlay(key, members)

    def update_overlay_copy_menu(self):
        keys=[key for key in self.documents if self._is_overlay(key)]
        current=self.active_document()
        for i in range(20):
            action=self.classic_actions.get(f"C{i+1}")
            if action is None:continue
            key=keys[i] if i<len(keys) else None
            action.setVisible(key is not None);action.setEnabled(key is not None and len(keys)<20)
            action.setData(key);action.setCheckable(True);action.setChecked(current is not None and current.key==key)
            action.setText(f"{i+1}. {self.documents[key].windowTitle()}" if key is not None else str(i+1))
            action.setToolTip("选择要复制的叠图" if len(keys)<20 else "最多可打开20张叠图，请先关闭一张。")
        if hasattr(self,"_empty_copy_action"):self._empty_copy_action.setVisible(not keys)

    def copy_overlay(self,source_key=None):
        """Native Overlay / Copy chooses an existing overlay and opens a copy."""
        from copy import deepcopy
        keys=[key for key in self.documents if self._is_overlay(key)]
        if not keys:
            self.statusBar().showMessage("请先创建叠图。",5000);return
        if len(keys)>=20:
            self.statusBar().showMessage("最多可打开20张叠图，请先关闭一张。",6000);return
        if source_key is None:
            labels=[f"{i+1}. {self.documents[key].windowTitle()}" for i,key in enumerate(keys)]
            current=self.active_document();index=keys.index(current.key) if current and current.key in keys else 0
            label,accepted=QInputDialog.getItem(self,"复制叠图","选择叠图",labels,index,False)
            if not accepted:return
            source_key=keys[labels.index(label)]
        if source_key not in keys:raise ValueError("源叠图已关闭")
        for curve in self.curves:curve.save_overlay_view()
        key=self._next_overlay_key();options=deepcopy(self.plot_options[source_key])
        if options["window_name"]:options["window_name"]=options["window_name"][:77]+" 副本"
        self.plot_options[key]=options
        for curve in self.curves:
            state=curve.overlay_views.get(source_key)
            if state is not None:curve.overlay_views=dict(curve.overlay_views,**{key:deepcopy(state)})
        doc=self._document(key)
        doc.curve_uids=list(self.documents[source_key].curve_uids or [])
        self.plot_options[key]["overlay_members"]=list(doc.curve_uids)
        self.cancel_measurement(redraw=False);self._show_document(key);self.touch()
        return doc

    def show_normal(self):
        c = self.selected()
        if c:
            doc = self._document(c.dataset.document_key)
            doc.showMaximized()
            self.mdi.setActiveSubWindow(doc)
            self.document_activated(doc)

    def document_closed(self, doc):
        if self._syncing_documents:
            return
        self.cancel_measurement(redraw=False)
        self.documents.pop(doc.key, None)
        if not self._is_overlay(doc.key):
            removed = {c.uid for c in self.curves if c.dataset.document_key == doc.key}
            self.curves = [c for c in self.curves if c.dataset.document_key != doc.key]
            self.results[:] = [r for r in self.results if r.get('curve_id') not in removed]
            self.refresh_results()
            self.plot_options.pop(doc.key, None)
            self.touch()
            self.rebuild_files()
            self.sync_documents()
        else:
            self.plot_options.pop(doc.key,None)
            for curve in self.curves:
                if curve.active_overlay_key==doc.key:curve.activate_view(None)
                curve.overlay_views={key:value for key,value in curve.overlay_views.items() if key!=doc.key}
            self.touch()
        self.mdi.removeSubWindow(doc)
        doc.deleteLater()

    def close_active_document(self):
        active = self.active_document()
        if active:
            active.close()

    def close_all_documents(self):
        self._opening_counts = {}
        self._limits_undo.clear()
        self._overlay_seq = 0
        self._session_smooth_rules=self.smoothing_rules()
        self._last_document=None
        self.cancel_measurement(redraw=False)
        self._syncing_documents = True
        try:
            for doc in list(self.documents.values()):
                self.mdi.removeSubWindow(doc)
                doc.deleteLater()
            self.documents.clear()
            self.curves.clear()
            self.results.clear()
            self.plot_options.clear()
            self.rebuild_files()
            self.refresh_results()
            self.touch()
        finally:
            self._syncing_documents = False

    def remove_selected(self):
        curve=self.selected()
        if curve is not None:
            children={c.uid for c in self.curves if c.derived is not None and c.derived['source_curve_uid']==curve.uid}
            self.results[:]=[r for r in self.results if r.get('curve_id')!=curve.uid]
            self.remove_derived_curves(children)
            self.refresh_curve(curve.uid)
        MainWindow.remove_selected(self)
        self.sync_documents()

    def _dialog(self, key, title, widgets, size=(600, 460)):
        if key not in self.dialogs:
            dialog = QDialog(self)
            dialog.setWindowTitle(title)
            # In PySide, ~WindowType masks out flags beyond the enum mask,
            # including WindowCloseButtonHint. Toggle flags individually.
            dialog.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
            dialog.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
            layout = QVBoxLayout(dialog)
            for widget in widgets:
                widget.setParent(dialog)
                widget.show()
                layout.addWidget(widget)
            close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            close_buttons.rejected.connect(dialog.reject)
            layout.addWidget(close_buttons)
            dialog.resize(*size)
            self.dialogs[key] = dialog
        dialog = self.dialogs[key]
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def show_view(self, key):
        titles = {"metadata": "参数块 / 文件信息", "data": "数据表", "results": "结果表", "log": "分析日志"}
        self._dialog(key, titles[key], [self._panels[key]], (850, 520))

    def show_curve_options(self):
        active = self.active_document()
        if isinstance(active, PlotDocument) and self._is_overlay(active.key):
            return self.show_overlay_options()
        if not isinstance(active, PlotDocument): return
        from .graph_options import GraphOptionsDialog
        old = self.dialogs.get("graph_options")
        if old and old.isVisible():
            old.raise_(); return old
        dialog = GraphOptionsDialog(self)
        self.dialogs["graph_options"] = dialog
        dialog.show()
        return dialog

    def show_signal_options(self):
        return self._dialog("curve", "信号 / 曲线参数", [self.property_group], (410, 480))

    def alpha_width(self):
        from .alpha import DEFAULT_WIDTH_C,positive
        value=self.plot_options.get('__settings__',{}).get('alpha_smoothing_width')
        if value is None:
            try:value=self.user_defaults('analysis')['options'].get('alpha_smoothing_width')
            except (ValueError,OSError):value=None
        return DEFAULT_WIDTH_C if value is None else positive(value,'单点Alpha窗口')

    def transition_options(self):
        from .transitions import defaults,validate
        value=self.plot_options.get('__settings__',{}).get('transition_options')
        if value is None:
            try:value=self.user_defaults('analysis')['options'].get('transition_options')
            except (ValueError,OSError):value=None
        return defaults() if value is None else validate(value)

    def signal_change_settings(self):
        from .transitions import signal_defaults,validate_signal
        value=self.plot_options.get('__settings__',{}).get('signal_change_options')
        if value is None:
            try:value=self.user_defaults('analysis')['options'].get('signal_change_options')
            except (ValueError,OSError):value=None
        return signal_defaults() if value is None else validate_signal(value)

    def start_transition(self,kind):
        return self.start_point_measurement(kind,analysis_config=self.transition_options())

    def peak_onset_options(self):
        from .peak_onset import defaults,validate
        value=self.plot_options.get('__settings__',{}).get('peak_onset_options')
        if value is None:
            try:value=self.user_defaults('analysis')['options'].get('peak_onset_options')
            except (ValueError,OSError):value=None
        return defaults() if value is None else validate(value)

    def start_peak_onset(self,kind):return self.start_point_measurement(kind,analysis_config=self.peak_onset_options())

    def integration_options(self):
        from .peak_integration import defaults,validate
        value=self.plot_options.get('__settings__',{}).get('integration_options')
        if value is None:
            try:value=self.user_defaults('analysis')['options'].get('integration_options')
            except (ValueError,OSError):value=None
        return defaults() if value is None else validate(value)

    def sigmoid_iterations(self):
        value=self.plot_options.get('__settings__',{}).get('sigmoid_iterations')
        if value is None:
            try:value=self.user_defaults('analysis')['options'].get('sigmoid_iterations')
            except (ValueError,OSError):value=None
        return False if value is None else value

    def start_peak_integration(self,kind='peak_linear'):
        config=dict(peak_onset=self.peak_onset_options(),integration=self.integration_options())
        if kind=='peak_sigmoid':config['sigmoid']=dict(draw_iterations=self.sigmoid_iterations())
        return self.start_point_measurement(kind,analysis_config=config)

    def running_integral_parent(self,entry):
        if self._pending_measurement is not entry or self.current_measurement() is not entry:raise ValueError('请返回正在选点的曲线窗口')
        curve=next((c for c in self.visible_curves() if c.uid==entry['curve_id']),None)
        if curve is None or curve.derived is not None:raise ValueError('请选择已完成峰积分的原始尺寸曲线')
        if curve.result_transform(self.domain)!=entry['transform'] or curve.operations!=entry['operations'] or self.domain!=entry['domain']:raise ValueError('曲线已变更，请重新选择峰')
        p=entry['interactive'].get('positions',entry['interactive']['indices'])[0]
        from .peak_integration import KINDS
        for parent in reversed(self.results):
            if (parent.get('kind') not in KINDS or parent.get('curve_id')!=curve.uid or parent.get('domain')!=self.domain
                    or not parent.get('interactive',{}).get('confirmed') or parent['operations']!=curve.operations
                    or parent['transform']!=curve.result_transform(self.domain) or parent['signal']!=curve.result_label):continue
            positions=parent['interactive'].get('positions',parent['interactive']['indices'])
            if min(positions[:2])<=p<=max(positions[:2]):return parent
        raise ValueError('此标记点不在已确认峰积分的基线范围内')

    def start_running_integral(self):
        return self.start_peak_selector('running_integral')

    def start_delete_peak(self):
        return self.start_peak_selector('delete_peak')

    def start_peak_selector(self,purpose):
        from .peak_integration import KINDS
        curve=self.current_data_curve()
        if curve is None or curve.derived is not None:return self.statusBar().showMessage('请选择已完成峰积分的原始尺寸曲线。',6000)
        parents=[r for r in self.results if r.get('kind') in KINDS and r.get('curve_id')==curve.uid and r['domain']==self.domain
                 and r['operations']==curve.operations and r['transform']==curve.result_transform(self.domain) and r['interactive']['confirmed']]
        if not parents:return self.statusBar().showMessage('请先完成线性或水平S形峰积分，再选择峰。',6000)
        entry=self.start_point_measurement('curve_value')
        if entry is None:return
        p=float(parents[-1]['values']['peak_position']);index=int(round(p))
        entry['purpose']=purpose
        entry['interactive'].update(positions=[p],initial_positions=[p],indices=[index],initial_indices=[index])
        entry['annotation']['point_label'].update(time=False,temperature=False,signal=False,y=False,arrow=False,cross=True)
        self.redraw();self.activate_measurement_point(0);self._update_measurement_controls()
        return entry

    def show_running_integral_type(self,entry):
        from .running_integral_dialog import RunningIntegralDialog
        try:
            self.running_integral_parent(entry)
            old=self.dialogs.get('running_integral')
            if old and old.isVisible():
                if old.entry is entry:old.raise_();return old
                old.reject()
            dialog=RunningIntegralDialog(self,entry);self.dialogs['running_integral']=dialog;dialog.show();return dialog
        except ValueError as exc:self.statusBar().showMessage(str(exc),7000)

    def commit_running_integral(self,entry,*,expected_parent=None,expected_positions=None,**config):
        import uuid
        from .running_integral import descriptor,create_curve,validate_links
        parent=self.running_integral_parent(entry)
        if (expected_parent is not None and parent is not expected_parent or expected_positions is not None
                and tuple(entry['interactive'].get('positions',entry['interactive']['indices']))!=expected_positions):raise ValueError('选点或父积分已变更，请取消并重新执行积分')
        source=next(c for c in self.visible_curves() if c.uid==entry['curve_id'])
        parent_id=parent.get('analysis_id') or uuid.uuid4().hex
        d=descriptor(source,parent,parent_id,**config);computed=create_curve(source,d)
        doc=self.active_document();is_overlay=self._is_overlay(doc.key)
        occupied=[c for c in self._document_curves(doc) if c.axis==3 and (c.overlay_enabled if is_overlay else c.normal_enabled)]
        if any(c.derived is None or c.result_unit!=computed.result_unit for c in occupied):raise ValueError('Y4已有其它信号或不同单位的积分，请先释放Y4')
        computed.xy(self.domain)
        draft_results=[dict(r,analysis_id=parent_id) if r is parent else r for r in self.results]
        validate_links(self.curves+[computed],draft_results)
        # Materialize other overlays before appending: no implicit membership leaks.
        for key,other in self.documents.items():
            if self._is_overlay(key) and other is not doc and getattr(other,'curve_uids',None) is None:
                members=[c.uid for c in self._document_curves(other)]
                other.curve_uids=members;self.plot_options[key]['overlay_members']=list(members)
        if is_overlay:
            members=[c.uid for c in self._document_curves(doc)]+[computed.uid]
            computed.normal_enabled=False;computed.overlay_enabled=True;computed.activate_view(doc.key)
            doc.curve_uids=members;self.plot_options[doc.key]['overlay_members']=list(members)
        parent['analysis_id']=parent_id
        self.curves.append(computed);self.cancel_measurement(redraw=False)
        self.plot_options[doc.key].update(auto_y=[True]*4,y_limits=[None]*4,y_ticks=[None]*4)
        doc.plot_signature=None;self.touch();self.rebuild_files();self.refresh_curve(source.uid);self.refresh_results();self.redraw()
        self.statusBar().showMessage('执行积分已绘到Y4。',6000)
        return computed

    def auto_limit_rules(self):
        from .auto_limits import validate_rules,key
        try:saved=self.user_defaults('analysis')['options'].get('auto_limits_rules',[])
        except (ValueError,OSError):saved=[]
        current=self.plot_options.get('__settings__',{}).get('auto_limits_rules',[])
        return validate_rules([r for r in saved if key(r) not in {key(c) for c in current}]+current)

    def show_auto_limits(self):
        from .auto_limits import family
        entry=self.current_measurement()
        if entry is None or family(entry) is None:return
        from .auto_limits_dialog import AutoLimitsDialog
        old=self.dialogs.get('auto_limits')
        if old and old.isVisible():old.raise_();return old
        dialog=AutoLimitsDialog(self);self.dialogs['auto_limits']=dialog;dialog.show();return dialog

    def apply_auto_limits(self,entry,rule,positions):
        from .auto_limits import replace_rule
        if self.current_measurement() is not entry:raise ValueError('请返回正在选点的窗口')
        editor=next(e for e in self._measurement_artists if e.entry is entry)
        indices=[int(round(p)) for p in positions];values=editor.calculate(indices,positions,[None]*len(indices))
        if 'fit_error' in values:raise ValueError(values['fit_error'])
        rules=replace_rule(self.auto_limit_rules(),rule)
        entry['interactive'].update(indices=indices,positions=list(positions),manual_y=[None]*len(indices))
        entry['values']=values;entry['auto_limits']=deepcopy(rule)
        self.plot_options.setdefault('__settings__',default_plot_options())['auto_limits_rules']=rules
        self.touch();self.redraw();self.activate_measurement_point(0);self._update_measurement_controls()

    def show_analysis_options(self):
        from .alpha_dialogs import AnalysisOptionsDialog
        old=self.dialogs.get('analysis_options')
        if old and old.isVisible():old.raise_();return old
        dialog=AnalysisOptionsDialog(self);self.dialogs['analysis_options']=dialog;dialog.show();return dialog

    def start_alpha(self,kind,curve_uid=None):
        from .alpha import ALPHA_KINDS,check_curve,reference_length
        from .alpha_dialogs import SampleSizeDialog
        visible=self.visible_curves();curve=next((c for c in visible if c.uid==curve_uid),None) if curve_uid else self.current_data_curve()
        if curve is None or curve not in visible:return
        try:
            if kind not in ALPHA_KINDS:raise ValueError('Alpha方法无效')
            check_curve(curve,self.domain);length,source=reference_length(curve)
            if length is None:
                old=self.dialogs.get('sample_size')
                if old and old.isVisible():old.raise_();return old
                dialog=SampleSizeDialog(self,curve,kind);self.dialogs['sample_size']=dialog;dialog.show();return dialog
            self.files.setCurrentItem(self.files.topLevelItem(next(i for i,c in enumerate(self.curves) if c.uid==curve.uid)))
            return self.start_point_measurement(kind,analysis_config=dict(reference_length_mm=length,reference_source=source,smoothing_width_c=self.alpha_width()))
        except ValueError as exc:self.warn(str(exc))

    def show_units(self):
        if self.current_data_curve() is None:return
        from .units_dialog import UnitsDialog
        old=self.dialogs.get('units')
        if old and old.isVisible():old.raise_();return old
        dialog=UnitsDialog(self);self.dialogs['units']=dialog;dialog.show();return dialog

    def apply_unit_options(self,document,options):
        from .dimension_units import proposal
        states,plots=proposal(self,document,options)
        if not states:return
        changed={uid for uid,state in states.items() if 'unit_options' in state}
        sources={(c.dataset.path.name,c.dataset.sha256) for c in self.curves if c.uid in changed}
        paths={c.dataset.document_key for c in self.curves if c.uid in changed}
        if self._pending_measurement is not None and self._pending_measurement.get('curve_id') in changed:self.cancel_measurement(redraw=False)
        linked={c.derived['parent_id'] for c in self.curves if c.derived is not None}
        self.results[:]=[r for r in self.results if r.get('analysis_id') in linked or (r.get('curve_id') not in changed if r.get('curve_id') else (r['file'],r['sha256']) not in sources)]
        self._limits_undo={key:value for key,value in self._limits_undo.items() if value['source'] not in paths}
        for curve in self.curves:
            for key,value in states.get(curve.uid,{}).items():setattr(curve,key,value)
        self.plot_options.clear();self.plot_options.update(plots)
        self.touch();self.refresh_results();self.rebuild_files();self.redraw()
        self.statusBar().showMessage(f'已更新{len(paths)}个文件的单位；相关分析已清除。')

    def apply_sample_size(self,curve,size):
        from dataclasses import replace
        from .dimension_units import reconcile_views,processing_state
        ids={c.uid for c in self.curves if c.dataset.document_key==curve.dataset.document_key and c.dataset.sha256==curve.dataset.sha256}
        copies={c.uid:replace(c,sample_size_mm=size if c.uid in ids else c.sample_size_mm) for c in self.curves}
        removed={c.uid for c in self.curves if c.uid in ids and c.derived is not None}
        dependent={c.uid for c in self.curves if c.uid in ids and c.unit_options is not None and c.uid not in removed}
        processing={uid:processing_state(next(c for c in self.curves if c.uid==uid),copies[uid]) for uid in dependent}
        for uid,state in processing.items():
            for key,value in state.items():setattr(copies[uid],key,value)
        states,plots=reconcile_views(self,copies,dependent,skip_ids=removed) if dependent else ({},None)
        for uid,state in processing.items():states.setdefault(uid,{}).update(state)
        if dependent:
            self.results[:]=[r for r in self.results if r.get('curve_id') not in ids]
            if self._pending_measurement is not None and self._pending_measurement.get('curve_id') in ids:self.cancel_measurement(redraw=False)
        for peer in self.curves:
            if peer.uid in ids:peer.sample_size_mm=size;peer._x_cache=None
            for key,state in states.get(peer.uid,{}).items():setattr(peer,key,state)
        if plots is not None:self.plot_options.clear();self.plot_options.update(plots)
        self.remove_derived_curves(removed)
        self.touch();self.refresh_results();self.selection_changed()

    def show_file_information(self):
        if self.current_data_curve() is None:return
        from .file_info_dialog import FileInfoDialog
        old=self.dialogs.get('file_information')
        if old and old.isVisible():old.raise_();return old
        dialog=FileInfoDialog(self);self.dialogs['file_information']=dialog;dialog.show();return dialog

    def apply_file_information(self,curve,changes,size_changed=False,size=None):
        from .file_information import prepare_edit
        proposals=prepare_edit(self.curves,curve,changes,size_changed,size)
        ids=set(proposals)
        removed={c.uid for c in self.curves if c.uid in ids and c.derived is not None} if size_changed else set()
        plots=None
        if size_changed:
            from dataclasses import replace
            from .dimension_units import reconcile_views
            dependent={c.uid for c in self.curves if c.uid in ids and c.unit_options is not None and c.uid not in removed}
            if dependent:
                copies={c.uid:replace(c) for c in self.curves}
                for uid,state in proposals.items():
                    for key,value in state.items():setattr(copies[uid],key,value)
                views,plots=reconcile_views(self,copies,dependent,skip_ids=removed)
                for uid,state in views.items():proposals.setdefault(uid,{}).update(state)
        if size_changed:
            if self._pending_measurement is not None and self._pending_measurement.get('curve_id') in ids:self.cancel_measurement(redraw=False)
            self.results[:]=[r for r in self.results if (r.get('curve_id') not in ids if r.get('curve_id') else not (r['sha256']==curve.dataset.sha256 and r['file']==curve.dataset.path.name))]
            self._limits_undo={key:value for key,value in self._limits_undo.items() if value['source']!=curve.dataset.document_key}
        for peer in self.curves:
            if peer.uid in proposals:
                for key,value in proposals[peer.uid].items():setattr(peer,key,value)
        if 'Sample' in changes:self.update_curve_mass(curve)
        if plots is not None:self.plot_options.clear();self.plot_options.update(plots)
        self.remove_derived_curves(removed)
        self.touch();self.refresh_results();self.rebuild_files();self.selection_changed()

    def show_native_signals(self):
        if self.selected() is None: return
        from .signals_dialog import SignalsDialog
        old = self.dialogs.get("signals")
        if old and old.isVisible(): old.raise_(); return old
        dialog = SignalsDialog(self); self.dialogs["signals"] = dialog; dialog.show(); return dialog

    def show_overlay_options(self):
        from .classic_dialogs import OverlayOptionsDialog
        if not self.curves:
            self.statusBar().showMessage("请先打开数据文件，再设置叠图。")
            return
        old = self.dialogs.get("overlay_options")
        if old and old.isVisible():
            old.raise_(); return old
        try:key=self._overlay_key_for_edit()
        except ValueError as exc:self.statusBar().showMessage(str(exc),6000);return
        dialog = OverlayOptionsDialog(self, key=key)
        self.dialogs["overlay_options"] = dialog
        dialog.setModal(True); dialog.show()
        return dialog

    def auto_configure_overlay(self):
        if not self.curves: return
        from .auto_configure import AutoConfigureDialog
        old = self.dialogs.get("auto_configure")
        if old and old.isVisible(): old.raise_(); return old
        try:dialog=AutoConfigureDialog(self)
        except ValueError as exc:self.statusBar().showMessage(str(exc),6000);return
        self.dialogs["auto_configure"] = dialog
        dialog.show(); return dialog

    def signal_analysis_dialog(self, kind):
        from .classic_dialogs import SignalAnalysisDialog
        if not self.visible_curves():
            self.statusBar().showMessage("请先显示一条曲线。")
            return
        old = self.dialogs.get("signal_analysis")
        if old: old.reject()
        dialog = SignalAnalysisDialog(self, kind)
        self.dialogs["signal_analysis"] = dialog
        dialog.show(); dialog.raise_()
        return dialog

    def range_selected(self, lo, hi):
        dialog = getattr(self, "_range_dialog", None)
        curve=dialog.curves[dialog.curve_box.currentIndex()] if dialog is not None else self.current_data_curve()
        offset=self.display_x_offset(curve);lo,hi=lo-offset,hi-offset
        MainWindow.range_selected(self, lo, hi)
        if dialog is not None:
            dialog.set_bounds(lo, hi)
            self._range_dialog = None; self.range_enabled.setChecked(False)
            dialog.show(); dialog.raise_()

    def analysis_click(self, event):
        dialog, point = getattr(self, "_point_dialog", (None, 0))
        if dialog is None or event.xdata is None or event.button != 1: return
        curve = dialog.curves[dialog.curve_box.currentIndex()]
        x, _ = curve.xy(self.domain)
        target=event.xdata-self.display_x_offset(curve)
        value=float(x[int(np.argmin(np.abs(x-target)))])
        bounds = list(dialog.bounds()); bounds[point] = value
        dialog.set_bounds(*sorted(bounds))
        self._point_dialog = (None, 0)
        dialog.show(); dialog.raise_()

    def analysis_dialog(self, kind=None):
        if kind:
            self.analysis_box.setCurrentIndex(self.analysis_box.findData(kind))
        self._dialog("analysis", "分析范围 / 分析选项", [self.analysis_group], (420, 390))

    def show_processing(self):
        self._dialog("processing", "平滑 / 信号处理", [self.processing_group], (410, 380))

    def show_file_list(self):
        if "files" not in self.dialogs:
            panel = QWidget()
            layout = QVBoxLayout(panel)
            self.files.setParent(panel)
            self.files.show()
            layout.addWidget(self.files)
            row = QHBoxLayout()
            for title, fn in (("打开", self.open_files), ("全部显示", lambda: self.set_all_visible(True)),
                              ("添加信号", self.duplicate_curve), ("移除", self.remove_selected)):
                widget = QPushButton(title)
                widget.clicked.connect(fn)
                row.addWidget(widget)
            layout.addLayout(row)
            self._dialog("files", "叠加 · 手动设置", [panel], (580, 430))
        else:
            self._dialog("files", "叠加 · 手动设置", [])

    def show_options(self):
        if "options" not in self.dialogs:
            panel = QWidget()
            layout = QVBoxLayout(panel)
            layout.addWidget(QLabel("X 轴"))
            self.domain_box.setParent(panel)
            self.domain_box.show()
            layout.addWidget(self.domain_box)
            for checkbox in (self.show_results, self.range_enabled):
                checkbox.setParent(panel)
                checkbox.show()
                layout.addWidget(checkbox)
            self._dialog("options", "主要选项", [panel], (380, 240))
        else:
            self._dialog("options", "主要选项", [])

    def full_range(self):
        c = self.selected()
        if c:
            x, _ = c.xy(self.domain)
            self.lo_box.setValue(float(np.min(x)))
            self.hi_box.setValue(float(np.max(x)))

    def graphic_range(self):
        """Native Graph / Data Limits / Cursor, separate from analysis bounds."""
        curve=self.current_data_curve()
        if curve is None or curve not in self.visible_curves():return
        from .measurement import point_values
        try:
            x,y=curve.xy(self.domain);indices=[0,len(x)-1]
            values=point_values(x,y,"signal_change",indices)
        except ValueError as exc:self.warn(str(exc));return
        self.cancel_measurement(redraw=False)
        self.range_enabled.setChecked(False)
        if self.toolbar.mode:
            if "pan" in str(self.toolbar.mode).lower():self.toolbar.pan()
            else:self.toolbar.zoom()
        self._pending_measurement={"file":curve.dataset.path.name,"sha256":curve.dataset.sha256,"curve_id":curve.uid,
            "kind":"signal_change","purpose":"data_limits","domain":self.domain,"lo":min(values["start_x"],values["stop_x"]),
            "hi":max(values["start_x"],values["stop_x"]),"signal":curve.result_label,"axis":curve.axis+1,
            "operations":list(curve.operations),"transform":curve.result_transform(self.domain),"values":values,
            "interactive":{"indices":indices,"initial_indices":list(indices),"confirmed":False},"annotation":{"change":False,"x_limits":True}}
        self.show_results.setChecked(True)
        self._update_measurement_controls();self.redraw();self.activate_measurement_point(0)
        self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)
        return self._pending_measurement

    def confirm_measurement(self):
        entry=self._pending_measurement
        if entry is not None and self.current_measurement() is None:return
        if entry is not None and entry.get('purpose')=='delete_peak':
            try:
                peak=self.running_integral_parent(entry);uid=entry['curve_id']
                self.cancel_measurement(redraw=False);self.delete_result(peak);self.refresh_curve(uid)
                self.statusBar().showMessage('已删除选中的峰及其派生积分曲线。',6000)
            except ValueError as exc:self.statusBar().showMessage(str(exc),7000)
            return
        if entry is not None and entry.get('purpose')=='running_integral':return self.show_running_integral_type(entry)
        if entry is not None and entry["kind"] in ("curve_value","curve_value_y"):
            if self.current_measurement() is not None:return self.show_label_point(entry)
            return
        if entry is None or entry.get("purpose")!="data_limits":
            edited=self._editing_measurement
            MainWindow.confirm_measurement(self)
            if edited is not None and self._pending_measurement is None and edited.get('analysis_id'):
                self.remove_derived_curves({c.uid for c in self.curves if c.derived is not None and c.derived['parent_id']==edited['analysis_id']})
                self.redraw()
            return
        # A hidden draft in another document must never alter its source file.
        if self.current_measurement() is None:return
        curve=next((c for c in self.visible_curves() if c.uid==entry["curve_id"]),None)
        if curve is None:return
        from .data_limits import cursor_spec
        try:
            if (self.domain!=entry["domain"] or curve.result_transform(self.domain)!=entry["transform"]
                    or curve.operations!=entry["operations"] or curve.result_label!=entry["signal"]):raise ValueError("曲线已变更，请重新选择数据界限")
            state=entry["interactive"]
            spec=cursor_spec(curve,state.get("positions",state["indices"]))
            self.apply_data_limits(curve.dataset,spec,curve_uid=curve.uid)
        except ValueError as exc:self.statusBar().showMessage(str(exc),6000)

    def show_label_point(self,entry):
        from .label_point_dialog import LabelPointDialog
        old=self.dialogs.get("label_point")
        if old and old.isVisible():old.raise_();return old
        dialog=LabelPointDialog(self,entry);self.dialogs["label_point"]=dialog;dialog.show();return dialog

    def edit_point_label(self,entry):
        if entry.get("kind") not in ("curve_value","curve_value_y"):return
        self.edit_measurement(entry)
        return self.show_label_point(self._pending_measurement)

    def axis_at_position(self, x, y):
        """Hit actual tick numbers/axis titles and frame edges, in canvas pixels."""
        if not self._plot_artists: return None
        self.canvas.draw()
        renderer = self.canvas.get_renderer()
        for index, axis in self.axes.items():
            for text in [axis.yaxis.label] + axis.get_yticklabels():
                if text.get_visible() and text.get_text() and text.get_window_extent(renderer).padded(4).contains(x, y): return index
        base = self.axes[0]
        for text in [base.xaxis.label] + base.get_xticklabels():
            if text.get_visible() and text.get_text() and text.get_window_extent(renderer).padded(4).contains(x, y): return "x"
        frame = base.bbox
        if frame.x0 <= x <= frame.x1 and abs(y-frame.y0) <= 6: return "x"
        for index, axis in self.axes.items():
            edge = axis.spines["left" if index in (0, 3) else "right"].get_window_extent(renderer)
            if frame.y0 <= y <= frame.y1 and abs(x-(edge.x0+edge.x1)/2) <= 6: return index
        return None

    def manual_rescale(self, selected="x"):
        if not self._plot_artists: return
        from .classic_dialogs import RescaleDialog
        old = self.dialogs.get("rescale")
        if old and old.isVisible(): old.raise_(); return old
        dialog = RescaleDialog(self, selected)
        self.dialogs["rescale"] = dialog
        dialog.setModal(True); dialog.show()
        return dialog

    def copy_plot(self):
        if self.active_document():
            QApplication.clipboard().setPixmap(self.output_pixmap())

    @contextmanager
    def output_heading(self):
        doc = self.active_document()
        options = self.plot_options.get(doc.key, {}) if isinstance(doc, PlotDocument) else {}
        title = options.get("export_title", "")
        originals = [(text, text.get_text(), text.get_visible(), text.get_position(), text.get_ha(), text.get_fontsize()) for text in self.figure.texts if text.get_gid() in ("tma-header", "tma-source")]
        added = None
        try:
            if title:
                header = next((item[0] for item in originals if item[0].get_gid() == "tma-header"), None)
                if header is None: added = self.figure.text(.004, 1, title, ha="left", va="top", fontsize=18, fontfamily=PLOT_FONTS, parse_math=False)
                else:
                    header.set_text(title)
                    align = options.get("export_align", "left")
                    header.set_ha(align); header.set_position(({"left": .004, "center": .5, "right": .996}[align], 1))
                    available = (1-max(axis.get_position().y1 for axis in self.axes.values()))*self.figure.bbox.height
                    header.set_fontsize(min(header.get_fontsize(), max(6, available/max(1, len(title.splitlines()))/1.5*72/self.figure.dpi)))
                for text, *_ in originals:
                    if text.get_gid() == "tma-source": text.set_visible(False)
            yield
        finally:
            for text, contents, visible, position, align, size in originals:
                text.set_text(contents); text.set_visible(visible); text.set_position(position); text.set_ha(align); text.set_fontsize(size)
            if added is not None: added.remove()

    def write_plot(self, path):
        with self.output_heading(): MainWindow.write_plot(self, path)

    def output_pixmap(self):
        buffer = BytesIO()
        with self.output_heading(): self.figure.savefig(buffer, format="png", dpi=150, facecolor="white", bbox_inches=self.figure.bbox_inches.padded(0.25))
        return QPixmap.fromImage(QImage.fromData(buffer.getvalue()))

    def toggle_legend(self):
        doc = self.active_document()
        if not isinstance(doc, PlotDocument): return
        options = self.plot_options.setdefault(doc.key, default_plot_options())
        current = len(self.visible_curves()) > 1 if options["legend"] is None else options["legend"]
        options["legend"] = not current
        self.touch()
        self.redraw()

    def set_plot_title(self):
        doc = self.active_document()
        if doc:
            title, ok = QInputDialog.getText(self, "绘图标题", "标题", text=doc.windowTitle())
            if ok:
                doc.setWindowTitle(title)
                self.plot_options.setdefault(doc.key, default_plot_options())["title"] = title
                self.touch(); self.redraw()

    def toggle_topmost(self):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, not bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))
        self.show()

    def update_window_menu(self):
        for action in list(self.window_menu.actions()):
            if action.property("dynamic_document"):
                self.window_menu.removeAction(action)
                action.deleteLater()
        for i, doc in enumerate(self.documents.values()):
            action = self.window_menu.addAction(f"{i + 1} {doc.windowTitle()}")
            action.setProperty("dynamic_document", True)
            action.setCheckable(True)
            action.setChecked(doc is self.active_document())
            action.triggered.connect(lambda checked=False, target=doc: self.mdi.setActiveSubWindow(target))
