"""Native overlay Auto tab: ten sequences, offset radio group, autoscale flags."""
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QWidget, QGroupBox, QComboBox, QLabel, QRadioButton, QButtonGroup, QCheckBox, QDoubleSpinBox, QColorDialog
from .overlay_settings import default_auto_styles, validate_auto_styles, STYLES, MARKERS, COLORS

LINE_NAMES = [("实线", "-"), ("短划线", ":"), ("划线", "--"), ("长划线", "long_dash"), ("点划线", "-."), ("断续线", "broken_dash"), ("双断续线", "broken_double_dash"), ("点", "None")]
SYMBOL_NAMES = [("无", ""), ("○", "o"), ("□", "s"), ("△", "^"), ("▽", "v"), ("+", "+"), ("×", "x"), ("·", "."), ("◇", "D")]
COLOR_NAMES = ("黑色", "红色", "蓝色", "绿色", "紫色", "青色", "橙色")


def color_combo(parent, value):
    box = QComboBox(parent)
    for label, color in zip(COLOR_NAMES, COLORS): add_color(box, label, color)
    if box.findData(value) < 0: add_color(box, value, value)
    box.addItem("自定义…", "custom")
    box.setCurrentIndex(box.findData(value))
    box._previous_color = value
    def changed(_):
        chosen = box.currentData()
        if chosen == "custom":
            color = QColorDialog.getColor(QColor(box._previous_color), box)
            chosen = color.name() if color.isValid() else box._previous_color
            if box.findData(chosen) < 0:
                pixmap = QPixmap(12, 12); pixmap.fill(QColor(chosen))
                box.insertItem(box.count()-1, QIcon(pixmap), chosen, chosen)
            box.setCurrentIndex(box.findData(chosen))
        box._previous_color = chosen
    box.currentIndexChanged.connect(changed)
    return box


def add_color(box, label, color):
    pixmap = QPixmap(12, 12); pixmap.fill(QColor(color)); box.addItem(QIcon(pixmap), label, color)


class AutoStylesPage(QWidget):
    def __init__(self, options, parent=None):
        super().__init__(parent)
        self.setObjectName("AutoSheet"); self.setMinimumSize(620, 330)
        self.lines, self.symbols, self.colors = [], [], []
        groups = []
        for caption, rect in (("线条", (14, 15, 160, 241)), ("符号", (182, 15, 69, 241)), ("颜色", (259, 15, 133, 241)), ("偏移", (400, 15, 197, 241))):
            group = QGroupBox(caption, self); group.setGeometry(*rect); groups.append(group)
        for i in range(10):
            for group in groups[:3]:
                label = QLabel(str(i+1), group); label.setGeometry(6, 22+21*i, 22, 18)
            line = QComboBox(groups[0]); line.setGeometry(27, 20+21*i, 125, 21)
            for caption, value in LINE_NAMES: line.addItem(caption, value)
            symbol = QComboBox(groups[1]); symbol.setGeometry(25, 20+21*i, 39, 21)
            for caption, value in SYMBOL_NAMES: symbol.addItem(caption, value)
            color = color_combo(groups[2], COLORS[i % len(COLORS)]); color.setGeometry(27, 20+21*i, 99, 21)
            self.lines.append(line); self.symbols.append(symbol); self.colors.append(color)
        self.offset_modes = QButtonGroup(self)
        for i, (caption, mode) in enumerate((("主刻度间距", "major"), ("次刻度间距", "minor"), ("半次刻度间距", "half"), ("坐标轴范围百分比", "percent"))):
            radio = QRadioButton(caption, groups[3]); radio.setGeometry(12, 30+34*i, 178, 21)
            radio.setProperty("mode", mode); self.offset_modes.addButton(radio, i)
        self.percent = QDoubleSpinBox(groups[3]); self.percent.setRange(0, 10000); self.percent.setDecimals(3)
        self.percent.setGeometry(36, 164, 96, 23); self.percent.setSuffix(" %")
        self.negative = QCheckBox("负向偏移", groups[3]); self.negative.setGeometry(12, 200, 150, 21)
        self.offset_modes.idClicked.connect(lambda _: self.update_percent())
        scale = QGroupBox("自动缩放", self); scale.setGeometry(14, 273, 583, 43)
        self.scale_boxes = {}
        for i, key in enumerate((0, 1, 2, 3, "x")):
            box = QCheckBox("X" if key == "x" else f"Y{key+1}", scale); box.setGeometry(40+105*i, 17, 50, 20)
            self.scale_boxes[key] = box
        self.load(options)

    def update_percent(self):
        self.percent.setEnabled(self.offset_modes.checkedButton().property("mode") == "percent")

    def load(self, options):
        config = validate_auto_styles(options.get("overlay_auto", default_auto_styles()))
        for key, boxes in (("lines", self.lines), ("symbols", self.symbols), ("colors", self.colors)):
            for box, value in zip(boxes, config[key]):
                if box.findData(value) < 0:
                    if key == "colors":
                        pixmap = QPixmap(12, 12); pixmap.fill(QColor(value))
                        box.insertItem(box.count()-1, QIcon(pixmap), value, value)
                    else: box.insertItem(box.count()-1, value, value)
                box.setCurrentIndex(box.findData(value))
                if key == "colors": box._previous_color = value
        for button in self.offset_modes.buttons(): button.setChecked(button.property("mode") == config["offset_method"])
        self.percent.setValue(config["offset_percent"]); self.negative.setChecked(config["offset_negative"])
        for key, box in self.scale_boxes.items(): box.setChecked(options["auto_x"] if key == "x" else options["auto_y"][key])
        self.update_percent()

    def collect(self):
        return validate_auto_styles({"lines": [box.currentData() for box in self.lines], "colors": [box.currentData() for box in self.colors],
                                     "symbols": [box.currentData() for box in self.symbols], "offset_method": self.offset_modes.checkedButton().property("mode"),
                                     "offset_percent": self.percent.value(), "offset_negative": self.negative.isChecked()})
