"""Native single-graph options, transcribed from TGRAPHOPTIONSFORM.

Geometry and control grouping come from the original DFM. Custom dash lengths
are approximations: native dash bitmaps and Multiline semantics were not recovered.
Numeric/letter symbol assignment is deliberately unavailable; custom marker lists
use the application's existing supported Matplotlib markers.

Manufacturer Win_Graph_Options.htm:49 makes grid type and symbol differentiation
global to an ordinary plot. Axis labels, styles, visibility, symbol lists/types
and spacing remain selected-axis controls.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QRadioButton, QVBoxLayout,
)

from .workspace import default_plot_options, validate_plot_options

# Native item order; identifiers are portable session state, not native dash IDs.
STYLE_ITEMS = [
    ("点", "None"), ("短划线", ":"), ("划线", "--"),
    ("长划线", "long_dash"), ("点划线", "-."),
    ("断续线", "broken_dash"), ("双断续线", "broken_double_dash"),
    ("实线", "-"), ("多线", "multiline"),
]
MARKER_ITEMS = [("○", "o"), ("□", "s"), ("△", "^"), ("▽", "v"),
                ("+", "+"), ("×", "x"), ("·", "."), ("◇", "D")]
COLOR_ITEMS = [("黑色", "#000000"), ("红色", "#ff0000"), ("蓝色", "#0000ff"),
               ("绿色", "#008000"), ("紫色", "#800080"), ("青色", "#008080"),
               ("橙色", "#e17b32")]
GRAPH_DEFAULTS = {
    "graph_axis_visible": [True] * 4,
    "graph_grid_types": [0] * 4,
    "graph_symbol_spacing": ["medium"] * 4,
    "graph_show_symbols": [True] * 4,
    "graph_symbol_differentiate": "axes",
}


def render_style(style):
    """Return a Matplotlib linestyle. Extended dash patterns approximate native ones."""
    patterns = {
        "long_dash": (0, (10., 4.)),
        "broken_dash": (0, (6., 2., 1.5, 2.)),
        "broken_double_dash": (0, (6., 2., 1.5, 2., 1.5, 2.)),
    }
    if style in patterns:
        return patterns[style]
    if style in ("-", "--", "-.", ":", "None"):
        return style
    raise ValueError(f"不支持的线型：{style}")


class GraphOptionsDialog(QDialog):
    """One ordinary document only; edits remain private until explicit acceptance.

    Parent integration consumes graph_axis_visible, graph_grid_types,
    graph_symbol_spacing and graph_show_symbols (four entries each). The legacy
    four-entry grid schema stores one broadcast global value. Symbol
    differentiation is one global axes/curves setting. Curve styles must be
    rendered through render_style rather than passed directly to Matplotlib.
    """
    def __init__(self, owner, key=None):
        super().__init__(owner)
        self.owner = owner
        self.document = owner.active_document()
        self.key = key or getattr(self.document, "key", None)
        if not self.key or self.key == "__overlay__" or self.key.startswith("__overlay__:"):
            raise ValueError("曲线图选项需要活动的普通数据文档")
        if self.document is None or self.document.key != self.key:
            raise ValueError("活动文档与曲线图选项不匹配")
        self.originals = [c for c in owner.curves if c.dataset.document_key == self.key]
        if not self.originals:
            raise ValueError("活动文档没有曲线")
        self.draft = [replace(c, operations=list(c.operations), history=list(c.history)) for c in self.originals]
        self.options = deepcopy(owner.plot_options.get(self.key, default_plot_options()))
        for name, value in GRAPH_DEFAULTS.items():
            self.options.setdefault(name, deepcopy(value))
        current = owner.selected()
        self.selected_uid = current.uid if current in self.originals else self.originals[0].uid
        self.axis = current.axis if current in self.originals else self.draft[0].axis
        self._loading = False
        self._symbol_lists = {i: list(dict.fromkeys(c.marker for c in self.draft if c.axis == i and c.marker)) or ["o"] for i in range(4)}
        self._symbol_types = {i: "custom" if any(c.marker for c in self.draft if c.axis == i) else "none"
                              for i in range(4)}
        # Resolve older per-axis grid values from the first schema entry, rather
        # than changing the displayed global choice when the selected axis changes.
        self.options["graph_grid_types"] = [self.options["graph_grid_types"][0]] * 4
        self.setObjectName("GraphOptionsForm")
        self.setWindowTitle("曲线图选项")
        self.setFixedSize(522, 380)
        self.setModal(True)
        self._build()
        self.load_axis()

    @staticmethod
    def _place(widget, name, rect):
        widget.setObjectName(name)
        widget.setGeometry(*rect)
        return widget

    def _label(self, text, name, rect, parent=None):
        return self._place(QLabel(text, parent or self), name, rect)

    def _combo(self, items, name, rect, parent=None):
        box = self._place(QComboBox(parent or self), name, rect)
        for text, value in items:
            box.addItem(text, value)
        return box

    def _build(self):
        place = self._place
        self.axis_group = place(QGroupBox("坐标轴", self), "AxisGroup", (12, 4, 497, 33))
        self.axis_buttons = QButtonGroup(self)
        for axis in range(4):
            radio = place(QRadioButton(f"Y{axis+1}", self.axis_group), f"AxisButton{axis+1}", (36+52*axis, 12, 35, 17))
            self.axis_buttons.addButton(radio, axis)
            radio.setEnabled(any(c.axis == axis for c in self.draft))
        self.axis_buttons.idClicked.connect(self.switch_axis)
        names = place(QGroupBox("名称", self), "NamesGroup", (12, 48, 497, 79))
        self._label("Y:", "YLabel", (32, 20, 16, 13), names)
        self._label("X:", "XLabel", (32, 52, 16, 13), names)
        self.y_name = place(QLineEdit(names), "YNameEdit", (52, 16, 433, 21))
        self.x_name = place(QLineEdit(self.options.get("x_label", ""), names), "XNameEdit", (52, 48, 433, 21))
        self._label("线条类型:", "LineTypeLabel", (36, 148, 62, 15))
        self.line_type = self._combo(STYLE_ITEMS, "LineTypeCombo", (104, 144, 205, 21))
        unsupported = self.line_type.model().item(self.line_type.findData("multiline"))
        unsupported.setEnabled(False)
        unsupported.setToolTip("原版多线语义尚未确认")
        self._label("颜色:", "ColorLabel", (340, 148, 36, 15))
        self.color = place(QComboBox(self), "ColorCombo", (381, 144, 115, 21))
        for text, value in COLOR_ITEMS:
            self._add_color(text, value)
        self.color.addItem("自定义…", "custom")
        self.color.currentIndexChanged.connect(self.choose_color)
        self._label("网格类型:", "GridTypeLabel", (36, 184, 62, 15))
        self.grid_type = self._combo([("无网格", 0), ("标值刻度处网格", 1), ("全部刻度处网格", 2)], "GridTypeCombo", (104, 180, 245, 21))
        self.grid_type.setToolTip("此网格类型应用于整个普通曲线图")
        self.show_symbols = place(QCheckBox("显示符号", self), "ShowSymbolsBox", (384, 172, 105, 17))
        self.show_axis = place(QCheckBox("显示坐标轴", self), "ShowAxisBox", (384, 190, 110, 17))
        group = place(QGroupBox("符号", self), "SymbolsGroup", (12, 216, 497, 117))
        self._label("类型:", "SymbolTypeLabel", (41, 20, 32, 15), group)
        self.symbol_type = self._combo([("无符号", "none"), ("数字", "digits"), ("字母", "letters"), ("自定义符号列表", "custom")], "SymbolTypeCombo", (76, 16, 181, 21), group)
        for value in ("digits", "letters"):
            item = self.symbol_type.model().item(self.symbol_type.findData(value))
            item.setEnabled(False); item.setToolTip("原版数字/字母分配规则尚未确认")
        self._label("间距:", "SpacingLabel", (304, 20, 46, 15), group)
        self.spacing = self._combo([("粗", "coarse"), ("中", "medium"), ("细", "fine"), ("每个点", "every")], "SpacingCombo", (356, 16, 115, 21), group)
        self._label("区分:", "DifferentiateLabel", (52, 52, 44, 15), group)
        self.differentiate = self._combo([("坐标轴", "axes"), ("曲线", "curves")], "DifferentiateCombo", (108, 48, 149, 21), group)
        self.differentiate.setToolTip("整个图统一按坐标轴或曲线顺序区分符号")
        self.symbol_preview = place(QLabel(group), "SymbolsPaintBox", (19, 81, 293, 23))
        self.symbol_preview.setFrameStyle(QLabel.Shape.Panel | QLabel.Shadow.Sunken)
        self.edit_list = place(QPushButton("编辑列表…", group), "EditList", (352, 82, 117, 21))
        self.edit_list.clicked.connect(self.edit_symbols)
        self.symbol_type.currentIndexChanged.connect(self.symbol_controls)
        self.error = place(QLabel(self), "GraphOptionsError", (12, 333, 497, 12))
        self.error.setStyleSheet("color: #a02020; font-size: 10px;")
        for text, name, x, callback in (("确定", "OK", 76, self.accept), ("保存", "Save", 164, self.save), ("默认值", "Default", 252, self.defaults), ("取消", "Cancel", 340, self.reject), ("帮助", "Help", 428, self.help)):
            button = place(QPushButton(text, self), name, (x, 346, 81, 25))
            button.setMinimumWidth(0); button.clicked.connect(callback)
            if name == "OK": button.setDefault(True)
            if name == "Cancel": button.setShortcut("Esc")

    def _add_color(self, text, value):
        pixmap = QPixmap(12, 12); pixmap.fill(QColor(value))
        self.color.addItem(QIcon(pixmap), text, value)

    def axis_curves(self):
        return [c for c in self.draft if c.axis == self.axis]

    def load_axis(self):
        self._loading = True
        self.axis_buttons.button(self.axis).setChecked(True)
        curves = self.axis_curves()
        curve = curves[0]
        self.y_name.setText(self.options.get("y_labels", [""]*4)[self.axis])
        self.line_type.setCurrentIndex(max(0, self.line_type.findData(curve.style)))
        index = self.color.findData(curve.color)
        if index < 0:
            self._add_color(curve.color, curve.color); index = self.color.count()-1
        self.color.setCurrentIndex(index)
        self.grid_type.setCurrentIndex(self.grid_type.findData(self.options["graph_grid_types"][0]))
        self.show_axis.setChecked(self.options["graph_axis_visible"][self.axis])
        self.show_symbols.setChecked(self.options["graph_show_symbols"][self.axis])
        self.spacing.setCurrentIndex(self.spacing.findData(self.options["graph_symbol_spacing"][self.axis]))
        self.symbol_type.setCurrentIndex(self.symbol_type.findData(self._symbol_types[self.axis]))
        self.differentiate.setCurrentIndex(self.differentiate.findData(self.options["graph_symbol_differentiate"]))
        self._loaded_state = {
            "style": self.line_type.currentData(), "color": self.color.currentData(),
            "symbol_type": self.symbol_type.currentData(),
            "differentiate": self.differentiate.currentData(),
            "symbols": list(self._symbol_lists[self.axis]),
        }
        self._loading = False
        self.symbol_controls()

    def store_axis(self):
        if self._loading:
            return
        style, color = self.line_type.currentData(), self.color.currentData()
        render_style(style)
        if not QColor(color).isValid() or color == "custom":
            raise ValueError("请选择有效颜色")
        self.options.setdefault("y_labels", [""]*4)[self.axis] = self.y_name.text()
        self.options["graph_axis_visible"][self.axis] = self.show_axis.isChecked()
        self.options["graph_grid_types"] = [self.grid_type.currentData()] * 4
        self.options["graph_symbol_spacing"][self.axis] = self.spacing.currentData()
        self.options["graph_show_symbols"][self.axis] = self.show_symbols.isChecked()
        differentiation_changed = self.differentiate.currentData() != self._loaded_state["differentiate"]
        self.options["graph_symbol_differentiate"] = self.differentiate.currentData()
        self._symbol_types[self.axis] = self.symbol_type.currentData()
        symbols = self._symbol_lists[self.axis]
        symbols_changed = (
            self.symbol_type.currentData() != self._loaded_state["symbol_type"]
            or symbols != self._loaded_state["symbols"]
        )
        for curve in self.axis_curves():
            if style != self._loaded_state["style"]:
                curve.style = style
            if color != self._loaded_state["color"]:
                curve.color = color
        # A global differentiation edit must reach every configured symbol axis.
        # Otherwise only an explicit symbol edit on the selected axis changes
        # markers; accepting a grid/label edit preserves distinct existing curves.
        if differentiation_changed or symbols_changed:
            for i, curve in enumerate(self.draft):
                if not differentiation_changed and curve.axis != self.axis:
                    continue
                kind = self._symbol_types[curve.axis]
                if kind == "none":
                    if curve.axis == self.axis and symbols_changed:
                        curve.marker = ""
                    continue
                if kind == "custom":
                    sequence = self._symbol_lists[curve.axis]
                    index = curve.axis if self.options["graph_symbol_differentiate"] == "axes" else i
                    curve.marker = sequence[index % len(sequence)]

    def switch_axis(self, axis):
        if axis == self.axis:
            return
        try:
            self.store_axis()
        except ValueError as exc:
            self.error.setText(str(exc)); self.axis_buttons.button(self.axis).setChecked(True); return
        self.axis = axis
        self.error.clear(); self.load_axis()

    def choose_color(self, _):
        if self._loading or self.color.currentData() != "custom":
            return
        previous = self.axis_curves()[0].color
        chosen = QColorDialog.getColor(QColor(previous), self)
        if chosen.isValid():
            value = chosen.name(); index = self.color.findData(value)
            if index < 0:
                self._add_color(value, value); index = self.color.count()-1
        else:
            index = self.color.findData(previous)
        self.color.setCurrentIndex(index)

    def symbol_controls(self, *_):
        enabled = self.symbol_type.currentData() == "custom"
        for widget in (self.differentiate, self.edit_list, self.spacing):
            widget.setEnabled(enabled)
        labels = dict((marker, label) for label, marker in MARKER_ITEMS)
        self.symbol_preview.setText("  " + "  ".join(labels[m] for m in self._symbol_lists[self.axis]) if enabled else "")

    def set_symbol_list(self, markers):
        if not markers or any(m not in dict((v, k) for k, v in MARKER_ITEMS) for m in markers):
            raise ValueError("符号列表至少包含一个支持的符号")
        self._symbol_lists[self.axis] = list(markers)
        self.symbol_type.setCurrentIndex(self.symbol_type.findData("custom"))
        self.symbol_controls()

    def edit_symbols(self):
        dialog = QDialog(self); dialog.setWindowTitle("符号列表")
        layout = QVBoxLayout(dialog); choices = QListWidget(dialog); layout.addWidget(choices)
        for text, marker in MARKER_ITEMS:
            item = QListWidgetItem(text); item.setData(Qt.ItemDataRole.UserRole, marker)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if marker in self._symbol_lists[self.axis] else Qt.CheckState.Unchecked)
            choices.addItem(item)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            markers = [choices.item(i).data(Qt.ItemDataRole.UserRole) for i in range(choices.count()) if choices.item(i).checkState() == Qt.CheckState.Checked]
            if markers:
                self.set_symbol_list(markers)
            else:
                self.symbol_type.setCurrentIndex(self.symbol_type.findData("none"))

    def _validated_options(self):
        self.store_axis()
        self.options["x_label"] = self.x_name.text()
        return validate_plot_options(self.options)

    def apply(self):
        try:
            if self.owner.documents.get(self.key) is not self.document:
                raise ValueError("数据文档已关闭，请重新打开曲线图选项")
            options = self._validated_options()
            live = {c.uid: c for c in self.owner.curves}
            if any(c.uid not in live for c in self.draft):
                raise ValueError("曲线已改变，请重新打开曲线图选项")
            for draft in self.draft:
                curve = live[draft.uid]
                curve.style, curve.color, curve.marker = draft.style, draft.color, draft.marker
            self.owner.plot_options[self.key] = options
            # Never replace curve objects or reorder the global file tree.
            self.owner.mdi.setActiveSubWindow(self.document)
            self.owner.rebuild_files()
            target = next((i for i, c in enumerate(self.owner.curves) if c.uid == self.selected_uid), None)
            if target is not None:
                self.owner.files.setCurrentItem(self.owner.files.topLevelItem(target))
            self.document.plot_signature = None
            self.owner.touch(); self.owner.redraw()
            return True
        except ValueError as exc:
            self.error.setText(str(exc)); return False

    def accept(self):
        if self.apply():
            super().accept()

    def save(self):
        from .preferences import save_defaults
        try:
            save_defaults("graph", "graph", self._validated_options(), self.draft)
            self.error.clear(); self.owner.statusBar().showMessage("默认设置已保存。", 5000)
        except (ValueError, OSError) as exc:
            self.error.setText(str(exc))

    def defaults(self):
        for curve in self.draft:
            curve.style, curve.color, curve.marker = "-", "#000000", ""
        self.options["x_label"] = ""
        self.options["y_labels"] = [""] * 4
        for key, value in GRAPH_DEFAULTS.items():
            self.options[key] = deepcopy(value)
        self._symbol_lists = {i: ["o"] for i in range(4)}
        self._symbol_types = {i: "none" for i in range(4)}
        self.x_name.clear(); self.load_axis()

    def help(self):
        self.error.setText("确定应用当前图；保存写入默认设置；默认值恢复出厂设置。")
