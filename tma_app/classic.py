"""Universal Analysis style MDI shell, using the independent TMA backend.

Menu order and glyphs originate in the local DFM resources. Main-view spacing,
toolbar order and plot typography follow the supplied original screenshot.
"""
from __future__ import annotations

import json
from pathlib import Path
from contextlib import contextmanager
from io import BytesIO

import numpy as np
from PySide6.QtCore import Qt, QSize, Signal, QTimer
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
from . import __version__

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


CLASSIC_STYLE = """
QWidget { color: black; font-family: 'Tahoma', 'SimSun'; font-size: 12px; }
QMainWindow, QDialog, QMenuBar, QToolBar, QStatusBar { background: #f0f0f0; }
QMenuBar { spacing: 0px; border-bottom: 1px solid #a0a0a0; min-height: 20px; max-height: 20px; }
QMenuBar::item { padding: 0px 8px; height: 18px; background: transparent; }
QMenuBar::item:selected { background: #0a246a; color: white; }
QMenu { background: #d4d0c8; border: 1px solid #808080; }
QMenu::item { padding: 3px 26px 3px 22px; }
QMenu::item:selected { background: #0a246a; color: white; }
QMenu::item:disabled { color: #808080; }
QToolBar { border-top: 1px solid white; border-bottom: 1px solid #a0a0a0; spacing: 0px; padding: 0px 2px; }
QToolButton { background: #f0f0f0; border: 1px solid transparent; padding: 2px; }
QToolButton:hover { border-top: 1px solid white; border-left: 1px solid white; border-bottom: 1px solid #808080; border-right: 1px solid #808080; }
QToolButton:pressed, QToolButton:checked { border-top: 1px solid #808080; border-left: 1px solid #808080; border-bottom: 1px solid white; border-right: 1px solid white; background: #c4c0b8; }
QPushButton { background: #d4d0c8; border-top: 1px solid white; border-left: 1px solid white; border-bottom: 1px solid #404040; border-right: 1px solid #404040; min-width: 65px; padding: 4px 8px; border-radius: 0; }
QPushButton#primary { background: #d4d0c8; color: black; border: 1px solid #404040; }
QPushButton:pressed { border-top: 1px solid #404040; border-left: 1px solid #404040; }
QGroupBox { background: #d4d0c8; border: 1px solid #808080; margin-top: 9px; padding: 8px; border-radius: 0; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; }
QLabel { background: transparent; }
QTreeWidget, QTableView, QPlainTextEdit { background: white; border: 1px solid #808080; border-radius: 0; color: black; selection-background-color: #0a246a; selection-color: white; }
QComboBox, QSpinBox, QDoubleSpinBox { background: white; color: black; border: 1px solid #808080; padding: 2px; border-radius: 0; min-height: 15px; }
QHeaderView::section { background: #d4d0c8; color: black; padding: 3px; border: 1px solid #aaa69e; }
QTabWidget::pane { border: 1px solid #a0a0a0; background: #f0f0f0; }
QTabBar::tab { background: #f0f0f0; color: black; border: 1px solid #a0a0a0; padding: 2px 7px; margin: 0; }
QTabBar::tab:selected { border-bottom-color: #f0f0f0; }
QStatusBar { border-top: 1px solid white; min-height: 18px; }
QStatusBar::item { border: 1px solid #a09c94; }
QMdiArea { background: #808080; }
"""


def classic_palette():
    palette = QApplication.palette()
    for role, color in ((QPalette.ColorRole.Window, "#f0f0f0"), (QPalette.ColorRole.Button, "#f0f0f0"),
                        (QPalette.ColorRole.Base, "white"), (QPalette.ColorRole.Text, "black"),
                        (QPalette.ColorRole.ButtonText, "black"), (QPalette.ColorRole.WindowText, "black"),
                        (QPalette.ColorRole.Highlight, "#0a246a"), (QPalette.ColorRole.HighlightedText, "white"),
                        (QPalette.ColorRole.Light, "white"), (QPalette.ColorRole.Dark, "#808080")):
        palette.setColor(role, QColor(color))
    return palette


class PlotDocument(QMdiSubWindow):
    closed_document = Signal(object)

    def __init__(self, owner, key, title):
        super().__init__()
        self.key = key
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
        self.setWindowIcon(QIcon(str(ASSETS / "app.ico")))
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
        self.dialogs = {}
        self.classic_actions = {}
        self.classic_legend = None  # Single traces have no legend; overlays do.
        self._drag_legend = None
        self._limits_undo={}
        self._session_smooth_rules=[]
        super().__init__()
        self.setStyleSheet(CLASSIC_STYLE)
        self.setPalette(classic_palette())
        self.setWindowTitle(f"Universal Analysis — TMA Studio {__version__}")
        self.setWindowIcon(QIcon(str(ASSETS / "app.ico")))
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
            "Copy3": self.copy_plot, "FileInformation1": lambda: self.show_view("metadata"),
            "SelectAll1": lambda: self.set_all_visible(True),
            "ManualRescale1": lambda: self.manual_rescale(), "ZoomOut1": lambda: self.toolbar.back(),
            "PreviousLimits1": lambda: self.toolbar.back(), "FullScaleAxis1": self.full_scale,
            "FullScaleAll1": self.full_scale, "ExactScalingX1": lambda: self.manual_rescale("x"),
            "ExactScalingY1": lambda: self.manual_rescale(self.selected().axis if self.selected() else 0),
            "SpreadsheetView1": lambda: self.show_view("data"), "Signals1": self.show_native_signals,
            "Units1": self.show_signal_options, "InstrParams1": lambda: self.show_view("metadata"),
            "Curve1": self.show_curve_options,
            "Y1": lambda: self.select_plot_axis(0), "Y2": lambda: self.select_plot_axis(1),
            "Y3": lambda: self.select_plot_axis(2), "Y4": lambda: self.select_plot_axis(3),
            "FullRangeLimits1": self.full_data_range,
            "TimeLimits1": lambda: self.show_data_limits("time"), "TemperatureLimits1": lambda: self.show_data_limits("temperature"),
            "CycleLimits1":lambda:self.show_data_limits("cycle"),
            "Data1": self.redraw, "Plot1": self.redraw,
            "XTime1": lambda: self.domain_box.setCurrentIndex(1),
            "XTemp1": lambda: self.domain_box.setCurrentIndex(0),
            "XSignal1": lambda: self.domain_box.setCurrentIndex(2),
            "AutoConfigure1": self.auto_configure_overlay, "ManualSetup1": self.show_overlay_options,
            "Edit4": self.show_overlay_options, "Copy4": self.copy_plot,
            "ShowOverlayPlot1": self.show_overlay, "ShowNormalPlot1": self.show_normal,
            "GraphOptions1": self.show_curve_options, "Plotlegend1": self.toggle_legend,
            "PlotHeader1": self.set_plot_title, "PlotFullRange1": self.full_scale,
            "HideResults1": lambda: self.show_results.setChecked(not self.show_results.isChecked()),
            "AlphaFitX1ToX21": lambda: self.analysis_dialog("cte"),
            "DimensionChange1": lambda: self.start_point_measurement("dimension_change"),
            "Linear1": lambda: self.analysis_dialog("integral"),
            "PeakMax1": lambda: self.analysis_dialog("peak"), "SignalMax1": lambda: self.start_point_measurement("signal_max"),
            "SignalChange1": lambda: self.start_point_measurement("signal_change"),
            "OnsetPoint1": lambda: self.analysis_dialog("onset"), "Slope1": lambda: self.analysis_dialog("slope"),
            "FullRange1": self.full_range, "EnterLimits1": lambda: self.analysis_dialog(),
            "AnalysisOptions1": lambda: self.analysis_dialog(),
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

        def append(parent, item):
            caption, name = item["caption"], item["name"]
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
        self.mdi = QMdiArea()
        self.mdi.setBackground(QColor("#808080"))
        self.mdi.setOption(QMdiArea.AreaOption.DontMaximizeSubWindowOnActivation, False)
        self.mdi.subWindowActivated.connect(self.document_activated)
        self.setCentralWidget(self.mdi)
        self.statusBar().setSizeGripEnabled(True)
        self.statusBar().setFixedHeight(19)
        self._make_toolbar()

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
            image_path = ASSETS / "icons" / f"{info['image_index']:03}.png"
            if image_path.exists():
                action.setIcon(QIcon(str(image_path)))
                if index in (34, 39, 49):
                    icon = action.icon()
                    icon.addPixmap(reference_disabled_icon(image_path, index == 39), QIcon.Mode.Disabled)
                    action.setIcon(icon)
                if target is not None:
                    target.setIcon(action.icon())
            else:
                action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
            toolbar.addAction(action)
            toolbar.widgetForAction(action).setFixedSize(24, 24)
        self.classic_toolbar = toolbar

    def _document(self, key):
        doc = self.documents.get(key)
        if doc is None:
            if key not in self.plot_options and not getattr(self, "_restoring_session", False):
                saved = self.user_defaults("overlay" if key == "__overlay__" else "graph")
                if saved["options"]:
                    self.plot_options[key] = validate_plot_options(fill_manual_limits(self, validate_plot_options(saved["options"])))
            title = "叠加绘图" if key == "__overlay__" else Path(key).name
            options = self.plot_options.setdefault(key, default_plot_options())
            if options["x_domain"] is None:
                candidates = [c for c in self.curves if key == "__overlay__" or str(c.dataset.path) == key]
                options["x_domain"] = self.domain if self.domain != "signal" or all(c.x_signal_index is not None for c in candidates) else "temperature"
            doc = PlotDocument(self, key, title)
            self.documents[key] = doc
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
                for key, value in saved["curves"][axis][slot].items(): setattr(curve, "overlay_offset" if key == "offset" and curve.appearance_mode == "overlay" else key, value)
            slots[axis] += 1

    def sync_documents(self):
        if self._syncing_documents:
            return
        self._syncing_documents = True
        try:
            valid = {str(c.dataset.path) for c in self.curves}
            for key in list(self.documents):
                if key != "__overlay__" and key not in valid:
                    doc = self.documents.pop(key)
                    self.mdi.removeSubWindow(doc)
                    doc.deleteLater()
            if not self.curves and "__overlay__" in self.documents:
                doc = self.documents.pop("__overlay__")
                self.mdi.removeSubWindow(doc)
                doc.deleteLater()
            for c in self.curves:
                key = str(c.dataset.path)
                if key not in self.documents:
                    self._document(key).show()
        finally:
            self._syncing_documents = False

    def document_activated(self, doc):
        if not isinstance(doc, PlotDocument) or self._activating or self._syncing_documents:
            return
        self._activating = True
        self._drag_legend = None
        try:
            for curve in self.curves: curve.activate_appearance("overlay" if doc.key == "__overlay__" else "normal")
            self.figure, self.canvas, self.toolbar = doc.figure, doc.canvas, doc.navigation
            domain = self.plot_options.get(doc.key, {}).get("x_domain")
            if domain is not None:
                self.domain = domain
                self.domain_box.blockSignals(True); self.domain_box.setCurrentIndex(("temperature", "time", "signal").index(domain)); self.domain_box.blockSignals(False)
            if doc.key != "__overlay__":
                current = self.selected()
                index = self.curves.index(current) if current is not None and str(current.dataset.path) == doc.key else next((i for i, c in enumerate(self.curves) if str(c.dataset.path) == doc.key), None)
                if index is not None:
                    self.files.setCurrentItem(self.files.topLevelItem(index))
            MainWindow.selection_changed(self)
        finally:
            self._activating = False

    def selection_changed(self):
        if self._updating:
            return
        c = self.selected()
        if hasattr(self, "mdi") and not self._activating and not self._syncing_documents and c:
            active = self.mdi.activeSubWindow()
            if not isinstance(active, PlotDocument) or active.key != "__overlay__":
                doc = self.documents.get(str(c.dataset.path))
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
        active = self.mdi.activeSubWindow()
        if not isinstance(active, PlotDocument):
            return []
        return [c for c in self.curves if c.visible and ((active.key == "__overlay__" and c.overlay_enabled) or (str(c.dataset.path) == active.key and c.normal_enabled))]

    def change_domain(self, index):
        if self._updating or not hasattr(self, "mdi"): return
        domain = ("temperature", "time", "signal")[index]
        doc = self.mdi.activeSubWindow()
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
            try:self.apply_data_limits(curve.dataset,None)
            except ValueError as exc:self.warn(str(exc))

    def apply_data_limits(self,dataset,spec):
        from copy import deepcopy
        from .data_limits import limits_proposal
        if not any(c.dataset.path==dataset.path for c in self.curves):raise ValueError("此数据文件已关闭")
        draft=limits_proposal(self.curves,dataset,spec,self.domain)
        source=[c for c in draft if c.dataset.path==dataset.path]
        selected=self.selected();uid=selected.uid if selected else source[0].uid
        range_keys=("auto_x","auto_y","x_limits","y_limits","x_ticks","y_ticks")
        keys=[key for key in (str(dataset.path),"__overlay__") if key in self.plot_options]
        before={key:{name:deepcopy(self.plot_options[key][name]) for name in range_keys} for key in keys}
        transaction={"source":str(dataset.path),"checkpoints":{c.uid:c.history[-1] for c in source},"ranges":before}
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
        current=[c for c in self.curves if str(c.dataset.path)==transaction["source"]]
        states=transaction["checkpoints"]
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
        if not hasattr(self, "mdi"):
            return
        active = self.mdi.activeSubWindow()
        if not isinstance(active, PlotDocument):
            return
        self._drag_legend = None
        self.figure, self.canvas, self.toolbar = active.figure, active.canvas, active.navigation
        curves = self.visible_curves()
        options = self.plot_options.get(active.key, default_plot_options())
        signature = (self.domain, tuple((id(c.dataset), c.y_index, c.axis, c.x_shift, c.scale, c.offset, id(c.working)) for c in curves))
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
            axis.tick_params(axis="both", which="both", colors="black", direction="out", top=False, right=False, labelsize=21.5*scale, width=.55)
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
                    xlim, xticks = nice_limits(np.concatenate([x for c, x, y in self._plot_artists]))
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
            style = entry.get("annotation", {}).get("text_style", {})
            annotation.set_fontweight("bold" if style.get("bold", False) else "normal")
            annotation.set_fontstyle("italic" if style.get("italic", False) else "normal")
            if "size" in style: annotation.set_fontsize(style["size"])
        ds = curves[0].dataset if curves else None
        if ds is not None:
            def field(name):
                return "; ".join(ds.metadata.get(name, []))
            self.figure.text(8/1920, 1, options["title"] or f"样品: {ds.name}", ha="left", va="top", fontsize=22*scale, fontfamily=PLOT_FONTS, color="black", parse_math=False, gid="tma-header")
            module = (field("Module").split() or ["TMA"])[0]
            source = field("File").strip() or str(ds.path)
            self.figure.text(.996, 1, f"{module} 文件: {source}", ha="right", va="top", fontsize=22*scale, fontfamily=PLOT_FONTS, color="black", parse_math=False, gid="tma-source")
        self.figure.text(.996, .017, "Power By ZzzHe", ha="right", fontsize=20*scale, fontfamily="Times New Roman")
        if active.key == "__overlay__": active.setWindowTitle(options["window_name"] or "叠加绘图")
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
            add_secondary_axis(base, curves[0], self.domain, PLOT_FONTS, scale)
        active.plot_signature = signature
        active.plot_axes = dict(self.axes)
        active.plot_ticks = {i: (axis.get_xticks().copy(), axis.get_yticks().copy()) for i, axis in self.axes.items()}
        active.plot_ranges = {i: (axis.get_xlim(), axis.get_ylim()) for i, axis in self.axes.items()}
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
                    doc = self.mdi.activeSubWindow()
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
        doc = self.mdi.activeSubWindow()
        if isinstance(doc, PlotDocument) and doc.key == "__overlay__":
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
        for name, label in (("Signals1", "信号"), ("FullRangeLimits1", "全范围数据"), ("TimeLimits1", "时间数据界限"), ("TemperatureLimits1", "温度数据界限")):
            action(name, label)
        menu.addSeparator()
        xmenu = menu.addMenu("X 轴")
        for name in ("XTime1", "XTemp1"):
            if name in self.classic_actions: xmenu.addAction(self.classic_actions[name])
        overlay = menu.addMenu("叠加")
        for name in ("AutoConfigure1", "ManualSetup1", "Edit4", "ShowOverlayPlot1", "ShowNormalPlot1"):
            if name in self.classic_actions: overlay.addAction(self.classic_actions[name])
        action("GraphOptions1", "曲线图选项"); menu.addSeparator()
        for name, label in (("AlphaAtX1", "Alpha于X"), ("AlphaX1ToX21", "Alpha X1 至 X2"), ("AlphaFitX1ToX21", "线性拟合Alpha X1 至 X2"), ("DimensionChange1", "尺寸变化")):
            action(name, label)
        menu.addSeparator()
        for name, label in (("Linear1", "线性峰值积分"), ("SigHorizontal1", "水平 S 形曲线峰值积分"), ("PeakMax1", "峰最大"), ("SignalMax1", "信号最大"), ("SignalChange1", "信号变化"), ("HeightChange", "高度差"), ("GlassTransition1", "玻璃化/步阶转变"), ("OnsetPoint1", "始点"), ("Slope1", "斜率"), ("PeakRunningIntegral1", "执行积分"), ("CurveValueAtX1", "曲线值于X轴")):
            action(name, label)
        menu.addSeparator(); action("AnalysisOptions1", "分析选项")
        if self._measurement_artists and self.current_measurement() is None:
            menu.addSeparator()
            menu.addAction("调整分析点", lambda: self.edit_measurement())
        if any(r.get("annotation", {}).get("hidden", False) for r in self.results):
            menu.addSeparator(); menu.addAction("显示隐藏结果", self.show_hidden_results)
        return menu

    def show_plot_context_menu(self, doc, point):
        if self.mdi.activeSubWindow() is not doc:
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
        if (doc.key == "__overlay__" and legend is not None and legend.get_visible()
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
        return None

    def create_result_context_menu(self, entry, annotation):
        menu = QMenu(self); menu.setObjectName("ObjectPopupMenu")
        style = entry.get("annotation", {}).get("text_style", {})
        for key, caption in (("bold", "粗体"), ("italic", "斜体")):
            action = menu.addAction(caption); action.setCheckable(True); action.setChecked(style.get(key, False))
            action.triggered.connect(lambda checked, key=key: self.style_result(entry, key, checked))
        sizes = menu.addMenu("字号")
        for size in (8, 10, 12, 14, 16, 18, 20, 24):
            action = sizes.addAction(str(size)); action.triggered.connect(lambda checked=False, size=size: self.style_result(entry, "size", size))
        menu.addSeparator()
        if "interactive" in entry: menu.addAction("调整结果", lambda: self.edit_measurement(entry))
        menu.addAction("删除结果", lambda: self.delete_result(entry))
        menu.addAction("隐藏结果", lambda: self.hide_result(entry))
        menu.addAction("复制文字", lambda: QApplication.clipboard().setText(annotation.get_text()))
        return menu

    def style_result(self, entry, key, value):
        entry.setdefault("annotation", {}).setdefault("text_style", {})[key] = value
        self.touch(); self.redraw()

    def delete_result(self, entry):
        self.results[:] = [result for result in self.results if result is not entry]
        self.touch(); self.refresh_results(); self.redraw()

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
        menu.addAction("自动界限", self.reset_measurement_limits).setObjectName("AutoLimits1")
        menu.addAction(self.measurement_cancel)
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
        pending["interactive"].pop("positions", None)
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
        text, accepted = QInputDialog.getText(self, "批注", "文字")
        if not accepted or not text.strip(): return
        axis = self.axes[c.axis]
        pixel = getattr(self, "_context_point", axis.bbox.p0 + axis.bbox.size / 2)
        x, y = axis.transData.inverted().transform(pixel)
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
        doc = self.mdi.activeSubWindow()
        if isinstance(doc, PlotDocument):
            options = self.plot_options.get(doc.key)
            if options:
                options.update(auto_x=True, auto_y=[True]*4, x_ticks=None, y_ticks=[None]*4)
                self.touch()
            doc.plot_signature = None
            self.redraw()

    def finish_import(self, datasets, failures):
        before = {str(c.dataset.path) for c in self.curves}
        rules=self.smoothing_rules()
        MainWindow.finish_import(self, datasets, failures)
        for i, c in enumerate(self.curves):
            if str(c.dataset.path) not in before:
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
                        options = self.plot_options.setdefault(str(dataset.path), default_plot_options())
                        options.update(x_domain=template["x"]["domain"], secondary_x=template["secondary"])
                    except ValueError as exc: self.log.appendPlainText(f"信号默认设置未应用于{dataset.path.name}：{exc}")
                if rules:
                    from .data_limits import reusable_smoothing
                    domain=self.plot_options.get(str(dataset.path),{}).get("x_domain") or self.domain
                    for curve in [c for c in self.curves if c.dataset is dataset and c.normal_enabled]:
                        try:
                            values=reusable_smoothing(curve,rules,domain)
                            if values:
                                for key,value in values.items():setattr(curve,key,value)
                        except ValueError as exc:self.log.appendPlainText(f"平滑复用未应用于{dataset.path.name}：{exc}")
        self.sync_documents()
        # Populate each independent plot, then leave the last imported file active.
        for ds in datasets:
            doc = self.documents[str(ds.path)]
            self.mdi.setActiveSubWindow(doc)
            self.document_activated(doc)
        self.rebuild_files()
        if datasets:
            self.documents[str(datasets[-1].path)].showMaximized()
        self.statusBar().clearMessage()

    def open_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "打开数据文件", "", "TA 数据 / TMA 会话 (*.0?? *.1?? *.2?? *.3?? *.4?? *.5?? *.6?? *.7?? *.8?? *.9?? *.tai *.txt *.tmas);;所有文件 (*)")
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
                self.sync_documents()
                if self.curves: self.show_overlay()
        finally:
            self._restoring_session = False

    def touch(self):
        self.dirty = True
        self.setWindowTitle(f"Universal Analysis — TMA Studio {__version__} *")

    def _update_measurement_controls(self):
        MainWindow._update_measurement_controls(self)
        self.statusBar().setFixedHeight(19)

    def show_overlay(self):
        if not self.curves:
            return
        if "__overlay__" not in self.documents and not getattr(self, "_restoring_session", False):
            for curve in self.curves: curve.activate_appearance("overlay")
            self.apply_default_appearance([c for c in self.curves if c.visible and c.overlay_enabled], self.user_defaults("overlay"))
        doc = self._document("__overlay__")
        doc.showMaximized()
        self.mdi.setActiveSubWindow(doc)
        self.document_activated(doc)

    def show_normal(self):
        c = self.selected()
        if c:
            doc = self._document(str(c.dataset.path))
            doc.showMaximized()
            self.mdi.setActiveSubWindow(doc)
            self.document_activated(doc)

    def document_closed(self, doc):
        if self._syncing_documents:
            return
        self.cancel_measurement(redraw=False)
        self.documents.pop(doc.key, None)
        if doc.key != "__overlay__":
            self.curves = [c for c in self.curves if str(c.dataset.path) != doc.key]
            self.touch()
            self.rebuild_files()
        self.mdi.removeSubWindow(doc)
        doc.deleteLater()

    def close_active_document(self):
        active = self.mdi.activeSubWindow()
        if active:
            active.close()

    def close_all_documents(self):
        self._limits_undo.clear()
        self._session_smooth_rules=self.smoothing_rules()
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
        MainWindow.remove_selected(self)
        self.sync_documents()

    def _dialog(self, key, title, widgets, size=(600, 460)):
        if key not in self.dialogs:
            dialog = QDialog(self)
            dialog.setWindowTitle(title)
            dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
            layout = QVBoxLayout(dialog)
            for widget in widgets:
                widget.setParent(dialog)
                widget.show()
                layout.addWidget(widget)
            close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            close_buttons.rejected.connect(dialog.hide)
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
        active = self.mdi.activeSubWindow()
        if isinstance(active, PlotDocument) and active.key == "__overlay__":
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
        dialog = OverlayOptionsDialog(self)
        self.dialogs["overlay_options"] = dialog
        dialog.setModal(True); dialog.show()
        return dialog

    def auto_configure_overlay(self):
        if not self.curves: return
        from .auto_configure import AutoConfigureDialog
        old = self.dialogs.get("auto_configure")
        if old and old.isVisible(): old.raise_(); return old
        dialog = AutoConfigureDialog(self); self.dialogs["auto_configure"] = dialog
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
        MainWindow.range_selected(self, lo, hi)
        dialog = getattr(self, "_range_dialog", None)
        if dialog is not None:
            dialog.set_bounds(lo, hi)
            self._range_dialog = None; self.range_enabled.setChecked(False)
            dialog.show(); dialog.raise_()

    def analysis_click(self, event):
        dialog, point = getattr(self, "_point_dialog", (None, 0))
        if dialog is None or event.xdata is None or event.button != 1: return
        curve = dialog.curves[dialog.curve_box.currentIndex()]
        x, _ = curve.xy(self.domain)
        value = float(x[int(np.argmin(np.abs(x - event.xdata)))])
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
        self.range_enabled.setChecked(True)
        self.statusBar().showMessage("在图中拖拽选择分析范围")

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
        if self.mdi.activeSubWindow():
            QApplication.clipboard().setPixmap(self.output_pixmap())

    @contextmanager
    def output_heading(self):
        doc = self.mdi.activeSubWindow()
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
        with self.output_heading(): self.figure.savefig(buffer, format="png", dpi=150, facecolor="white")
        return QPixmap.fromImage(QImage.fromData(buffer.getvalue()))

    def toggle_legend(self):
        doc = self.mdi.activeSubWindow()
        if not isinstance(doc, PlotDocument): return
        options = self.plot_options.setdefault(doc.key, default_plot_options())
        current = len(self.visible_curves()) > 1 if options["legend"] is None else options["legend"]
        options["legend"] = not current
        self.touch()
        self.redraw()

    def set_plot_title(self):
        doc = self.mdi.activeSubWindow()
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
            action.setChecked(doc is self.mdi.activeSubWindow())
            action.triggered.connect(lambda checked=False, target=doc: self.mdi.setActiveSubWindow(target))
