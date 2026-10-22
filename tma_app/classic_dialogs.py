"""Functional classic dialogs. Edits are drafts until the user presses OK."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget,
    QGroupBox, QRadioButton, QButtonGroup, QTableWidget, QAbstractItemView,
    QHeaderView, QComboBox, QLineEdit, QCheckBox, QPushButton, QLabel,
    QDialogButtonBox, QListWidget, QListWidgetItem, QFileDialog, QColorDialog,
    QInputDialog, QMenu, QMessageBox, QPlainTextEdit,
    QGridLayout,
)

from .app import number
from .reader import read_dataset
from .workspace import Curve, PALETTE, default_plot_options, validate_plot_options
from .overlay_settings import axis_offset_step, fill_manual_limits
from .overlay_controls import AutoStylesPage

LINE_TYPES = [("实线", "-"), ("短划线", "--"), ("点划线", "-."), ("点线", ":"), ("仅符号", "None"), ("长虚线", "long_dash"), ("断续线", "broken_dash"), ("双断续线", "broken_double_dash")]
SYMBOLS = [("", ""), ("○", "o"), ("□", "s"), ("△", "^"), ("▽", "v"), ("+", "+"), ("×", "x"), ("·", "."), ("◇", "D")]
COLORS = [("黑色", "#000000"), ("红色", "#ff0000"), ("蓝色", "#0000ff"), ("绿色", "#008000"), ("紫色", "#800080"), ("青色", "#008080"), ("橙色", "#e17b32")]


def combo(items, value):
    box = QComboBox()
    for label, data in items:
        box.addItem(label, data)
    box.setCurrentIndex(max(0, box.findData(value)))
    return box


class CursorLimitsDialog(QDialog):
    """Native manual X/Y limits; untouched Y follows the acquired curve."""
    def __init__(self, owner):
        super().__init__(owner)
        from .measurement import point_coordinates
        self.owner, self.entry = owner, owner._pending_measurement
        self.data_limits=self.entry.get("purpose")=="data_limits"
        self.read_only_y=self.data_limits or self.entry["kind"] in ("curve_value","alpha_at_x","alpha_secant","alpha_fit","step_transition","glass_transition","peak_max","onset_point","peak_linear","peak_sigmoid","slope")
        self.at_y=self.entry["kind"]=="curve_value_y"
        self.setObjectName("CursorLimitsForm")
        self.setWindowTitle("手动界限")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setFixedSize(369, 275)
        curve = next(c for c in owner.curves if c.uid == self.entry["curve_id"])
        self.curve=curve
        self.x, self.y = curve.xy(self.entry["domain"])
        state = self.entry["interactive"]
        coords = point_coordinates(self.x, self.y, state["indices"], state.get("positions"), state.get("manual_y"))
        self.manual_y = list(state.get("manual_y", [None]*len(coords)))
        self.original_positions=list(state.get("positions",state["indices"]))
        self.original_x_text=[format(coord[0],".8g") for coord in coords]
        self.x_edited=set();self.y_edited=set()
        self.original_target_y=state.get("target_y")
        self.original_y_text=[format(self.original_target_y if self.at_y else coord[1],".8g") for coord in coords]
        self.fields, self.y_fields = [], []
        xlabel = curve.x_label(self.entry["domain"])
        for caption, left in ((xlabel, 96), (curve.result_label, 212)):
            label = QLabel(caption, self); label.setGeometry(left, 7, 140, 21); label.setToolTip(caption)
        for i in range(6):
            label = QLabel(f"点 {i+1}", self); label.setGeometry(20, 32+28*i, 66, 21)
            xfield, yfield = QLineEdit(self), QLineEdit(self)
            xfield.setGeometry(96, 32+28*i, 89, 21); yfield.setGeometry(212, 32+28*i, 120, 21)
            enabled = i < len(coords)
            label.setEnabled(enabled); xfield.setEnabled(enabled); yfield.setEnabled(enabled)
            if self.read_only_y:yfield.setReadOnly(True)
            if self.at_y:xfield.setReadOnly(True)
            if enabled:
                xfield.setText(self.original_x_text[i]);xfield.setToolTip(format(coords[i][0],".15g"))
                yfield.setText(self.original_y_text[i])
                self.fields.append(xfield); self.y_fields.append(yfield)
                xfield.textEdited.connect(lambda text,i=i:self.x_edited.add(i))
                xfield.textChanged.connect(self.preview)
                yfield.textEdited.connect(lambda text,i=i:self.y_edited.add(i))
                yfield.textChanged.connect(lambda text, i=i: self.edit_y(i, text))
        self.error = QLabel(self); self.error.setGeometry(12, 202, 345, 34); self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #a00000")
        for caption, left, callback in (("确定", 12, self.accept), ("光标", 100, self.reject), ("取消", 188, self.reject), ("帮助", 276, self.help)):
            button = QPushButton(caption, self); button.setGeometry(left, 242, 81, 25); button.clicked.connect(callback)
            if caption == "确定": button.setDefault(True)
        focus=(self.y_fields if self.at_y else self.fields)[state.get("active_point",0)]
        focus.setFocus();focus.selectAll()

    def positions(self):
        from .measurement import position_at_x,position_at_y
        if self.at_y:return [position_at_y(self.y,self.y_target(),self.curve.active_rows)]
        state = self.entry["interactive"]
        anchors = state.get("positions", state["indices"])
        # Compact native fields display readable numbers; accepting an untouched
        # field retains its exact original position rather than rounding it.
        return [self.original_positions[i] if i not in self.x_edited and field.text()==self.original_x_text[i]
                else position_at_x(self.x,float(field.text()),anchor,self.curve.active_rows)
                for i,(field,anchor) in enumerate(zip(self.fields,anchors))]

    def y_target(self):
        field=self.y_fields[0]
        return self.original_target_y if 0 not in self.y_edited and field.text()==self.original_y_text[0] else float(field.text())

    def preview(self):
        from .measurement import point_coordinates
        try:
            coords = point_coordinates(self.x, self.y, self.entry["interactive"]["indices"], self.positions())
            if self.at_y:
                self.fields[0].blockSignals(True);self.fields[0].setText(format(coords[0][0],".8g"));self.fields[0].blockSignals(False)
                self.error.clear();return
            for i, (field, (_, value)) in enumerate(zip(self.y_fields, coords)):
                if self.manual_y[i] is None:
                    field.blockSignals(True); field.setText(f"{value:.8g}"); field.blockSignals(False)
            self.error.clear()
        except ValueError as exc:
            self.error.setText(str(exc))

    def edit_y(self, point, text):
        # Keep invalid input local to this dialog until all fields validate.
        if self.at_y:self.preview()
        else:self.manual_y[point] = text

    def accept(self):
        from .measurement import point_values
        if self.owner._pending_measurement is not self.entry:
            self.reject(); return
        try:
            positions = self.positions()
            indices = [int(round(p)) for p in positions]
            manual_y = [None if self.read_only_y or self.at_y or value is None else float(value) for value in self.manual_y]
            values = point_values(self.x, self.y, self.entry["kind"], indices, positions, manual_y)
            if self.entry['kind']=='slope':
                from .slope import values as compute
                values.update(compute(self.curve,self.entry,positions))
            if self.entry["kind"] in ("alpha_at_x","alpha_secant","alpha_fit"):
                from .alpha import alpha_values
                values.update(alpha_values(self.curve,self.entry,positions))
            if self.entry['kind'] in ('peak_max','onset_point'):
                from .peak_onset import values as compute
                values.update(compute(self.curve,self.entry,positions))
            if self.entry['kind'] in ('peak_linear','peak_sigmoid'):
                from .peak_integration import values as compute
                values.update(compute(self.curve,self.entry,positions))
            if self.entry['kind'] in ('step_transition','glass_transition'):
                from .transitions import values as transition_values
                values.update(transition_values(self.curve,self.entry,positions))
            self.entry["interactive"].update(indices=indices, positions=positions, manual_y=manual_y)
            if self.at_y:self.entry["interactive"]["target_y"]=self.y_target()
            self.entry["values"] = values
            self.owner.redraw(); self.owner.activate_measurement_point(0); self.owner._update_measurement_controls()
            super().accept()
            self.owner.canvas.setFocus(Qt.FocusReason.OtherFocusReason)
        except ValueError as exc:
            self.error.setText(str(exc))

    def help(self):
        if self.entry.get('purpose') in ('running_integral','delete_peak'):
            purpose='进入积分类型设置' if self.entry['purpose']=='running_integral' else '删除选中的峰及其累计曲线'
            QMessageBox.information(self,'选择峰','输入已有峰积分范围内的准确X坐标，Y由曲线计算。\n返回曲线后，右键确定或Enter'+purpose+'；取消不修改结果。')
            return
        if self.entry['kind']=='slope':
            QMessageBox.information(self,'斜率','输入两个准确的X坐标，Y由相邻采集点计算。\n返回图中后，右键确定固定斜率；两个坐标标签与斜率文字可分别拖动。')
            return
        if self.at_y:
            QMessageBox.information(self,"曲线值于Y轴","输入准确Y坐标，X取当前连续采集片段内按采集顺序遇到的第一个交点。\n确定后返回水平标记；右键确定或Enter进入标注选项。")
            return
        if self.entry["kind"]=="curve_value":
            QMessageBox.information(self,"曲线值于X轴","输入准确X坐标，Y值沿相邻采集样点计算，不能手动覆盖。\n返回曲线后，右键确定或Enter选择时间、温度、信号、Y值及标记外观。")
            return
        if self.data_limits:
            QMessageBox.information(self,"光标数据界限","输入准确温度或时间。重复横坐标时保留最靠近当前控制点的采集分支。Y 值仅供定位。\n确定后返回选点；右键‘确定’或按 Enter 读取两点之间的实际采集数据。")
            return
        QMessageBox.information(self, "手动界限", "输入准确温度或时间；未编辑的 Y 值沿相邻采样点插值，也可直接输入 Y 坐标。重复温度时使用最靠近当前控制点的采集分支。\n确定后返回选点；右键‘确定’或按 Enter 固定结果。")


class RescaleDialog(QDialog):
    """Manual axis ranges, major labels, minor ticks and displayed label offsets."""
    COLUMNS = ("起点", "止点", "标值间隔", "刻度间隔", "标值偏移")

    def __init__(self, owner, selected="x"):
        super().__init__(owner)
        self.owner = owner
        self.document = owner.active_document()
        self.options = deepcopy(owner.plot_options.get(self.document.key, default_plot_options()))
        self.setWindowTitle("重定刻度")
        self.resize(530, 280)
        layout = QVBoxLayout(self)
        grid = QGridLayout(); grid.setHorizontalSpacing(9); grid.setVerticalSpacing(7)
        for col, label in enumerate(self.COLUMNS, 1): grid.addWidget(QLabel(label), 0, col)
        self.fields = {}
        for row, key in enumerate((0, 1, 2, 3, "x"), 1):
            grid.addWidget(QLabel("X" if key == "x" else f"Y{key+1}"), row, 0)
            axis = owner.axes.get(0 if key == "x" else key)
            enabled = axis is not None and (key == "x" or key in {c.axis for c in owner.visible_curves()})
            if enabled:
                limits = axis.get_xlim() if key == "x" else axis.get_ylim()
                ticks = axis.get_xticks() if key == "x" else axis.get_yticks()
                differences = np.diff(ticks)
                interval = float(np.median(differences[differences > 0])) if np.any(differences > 0) else (limits[1]-limits[0])/5
                setting = self.options["x_ticks"] if key == "x" else self.options["y_ticks"][key]
                values = [*limits, interval, interval/4, 0.]
                if setting is not None:
                    values[2:] = [setting[name] for name in ("label_interval", "tick_interval", "label_offset")]
            else: values = [None]*5
            widgets = []
            for col, value in enumerate(values, 1):
                box = QLineEdit("" if value is None else f"{value:.12g}")
                box.setEnabled(enabled); box.setMinimumWidth(65)
                box.setToolTip(f"{'X' if key == 'x' else 'Y'+str(key+1)} {self.COLUMNS[col-1]}")
                grid.addWidget(box, row, col); widgets.append(box)
            self.fields[key] = widgets
        layout.addLayout(grid)
        self.error = QLabel(); self.error.setWordWrap(True); self.error.setStyleSheet("color: #a02020")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Help)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.StandardButton.Help).setText("帮助")
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        buttons.helpRequested.connect(lambda: self.error.setText("起点须小于止点，间隔须为正数。标值间隔控制数字标签，刻度间隔控制小刻度；标值偏移只改变显示数字（刻度值＋偏移），不修改数据。"))
        layout.addWidget(buttons)
        if selected in self.fields and self.fields[selected][0].isEnabled():
            self.fields[selected][0].setFocus(); self.fields[selected][0].selectAll()

    def accept(self):
        try:
            options = deepcopy(self.options)
            for key, widgets in self.fields.items():
                if not widgets[0].isEnabled(): continue
                try: lo, hi, major, minor, offset = [float(box.text()) for box in widgets]
                except ValueError: raise ValueError("坐标轴的五项设置必须全部是有效数字")
                ticks = {"label_interval": major, "tick_interval": minor, "label_offset": offset}
                if key == "x": options.update(auto_x=False, x_limits=[lo, hi], x_ticks=ticks)
                else:
                    options["auto_y"][key] = False; options["y_limits"][key] = [lo, hi]; options["y_ticks"][key] = ticks
            options = validate_plot_options(options)
            self.owner.plot_options[self.document.key] = options
            self.document.plot_signature = None
            self.owner.touch(); self.owner.redraw()
            super().accept()
        except ValueError as exc:
            self.error.setText(str(exc))


class AddCurvesDialog(QDialog):
    """Select files and a compatible named signal, without changing the workspace."""
    def __init__(self, parent, curves, axis):
        super().__init__(parent)
        self.setWindowTitle("添加曲线")
        self.source_curves=list(curves)
        self.resize(630, 349)
        self.datasets = list({c.dataset.document_key: c.dataset for c in curves}.values())
        self.axis = axis
        self.reference = next((c.result_unit for c in curves if c.overlay_enabled and c.axis == axis), None)
        self.selected_curves = []
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        left, right = QVBoxLayout(), QVBoxLayout()
        left.addWidget(QLabel("文件"))
        self.files = QListWidget()
        left.addWidget(self.files)
        controls = QHBoxLayout()
        for title, fn in (("全部选择", lambda: self.check_files(True)), ("取消选择", lambda: self.check_files(False)), ("打开文件…", self.open_files)):
            btn = QPushButton(title); btn.clicked.connect(fn); controls.addWidget(btn)
        left.addLayout(controls)
        right.addWidget(QLabel("信号"))
        self.signals = QListWidget()
        right.addWidget(self.signals)
        self.compatible = QCheckBox("仅显示兼容信号")
        self.compatible.setChecked(True)
        right.addWidget(self.compatible)
        row.addLayout(left, 3); row.addLayout(right, 2); layout.addLayout(row)
        self.error = QLabel(); self.error.setWordWrap(True); layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.files.itemChanged.connect(self.refresh_signals)
        self.compatible.toggled.connect(self.refresh_signals)
        self.refresh_files()

    def refresh_files(self):
        self.files.blockSignals(True); self.files.clear()
        for ds in self.datasets:
            item = QListWidgetItem(ds.display_name)
            item.setToolTip(str(ds.path)); item.setCheckState(Qt.CheckState.Checked)
            self.files.addItem(item)
        self.files.blockSignals(False); self.refresh_signals()

    def check_files(self, enabled):
        self.files.blockSignals(True)
        for i in range(self.files.count()):
            self.files.item(i).setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
        self.files.blockSignals(False); self.refresh_signals()

    def checked_datasets(self):
        return [ds for i, ds in enumerate(self.datasets) if self.files.item(i).checkState() == Qt.CheckState.Checked]

    def refresh_signals(self, *_):
        old = self.signals.currentItem().text() if self.signals.currentItem() else None
        labels = sorted({s.label for ds in self.checked_datasets() for s in ds.signals})
        if self.compatible.isChecked() and self.reference:
            labels = [label for label in labels if all(any(s.label == label and Curve(ds, y_index=i).result_unit == self.reference for i, s in enumerate(ds.signals)) for ds in self.checked_datasets())]
        self.signals.clear(); self.signals.addItems(labels)
        if labels:
            self.signals.setCurrentRow(labels.index(old) if old in labels else 0)

    def open_files(self):
        from .path_settings import import_folder
        paths, _ = QFileDialog.getOpenFileNames(self, "添加数据文件", import_folder(), "TA 数据 (*.0?? *.1?? *.2?? *.3?? *.4?? *.5?? *.6?? *.7?? *.8?? *.9?? *.txt *.tai);;所有文件 (*)")
        failures = []
        known = {str(ds.path.resolve()) for ds in self.datasets}
        for path in paths:
            if str(Path(path).resolve()) in known:
                continue
            try:
                self.datasets.append(read_dataset(path)); known.add(str(Path(path).resolve()))
            except Exception as exc:
                failures.append(f"{Path(path).name}: {exc}")
        self.refresh_files(); self.error.setText("\n".join(failures))

    def accept(self):
        item = self.signals.currentItem()
        if not item or not self.checked_datasets():
            self.error.setText("请选择文件和一个信号。"); return
        label = item.text()
        missing = [ds.path.name for ds in self.checked_datasets() if label not in [s.label for s in ds.signals]]
        if missing:
            self.error.setText("以下文件没有所选信号：" + "、".join(missing)); return
        candidates = [Curve(ds, y_index=next(i for i, s in enumerate(ds.signals) if s.label == label), axis=self.axis, color="#000000", width=.45) for ds in self.checked_datasets()]
        for candidate in candidates:
            existing=next((c for c in self.source_curves if c.dataset.document_key==candidate.dataset.document_key and c.normal_enabled and c.derived is None),None)
            if existing:
                candidate.data_indices=deepcopy(existing.data_indices);candidate.data_limit_spec=deepcopy(existing.data_limit_spec);candidate.reset_time=existing.reset_time
                candidate.x_signal_index,candidate.x_signal_type,candidate.x_smooth_width=existing.x_signal_index,existing.x_signal_type,existing.x_smooth_width
        if self.reference and any(c.result_unit != self.reference for c in candidates):
            self.error.setText("所选信号与本轴单位不同，请先选择另一个空 Y 轴。"); return
        self.selected_curves = candidates
        super().accept()


class OverlayOptionsDialog(QDialog):
    """Ten slots per axis; six working tabs; OK/Cancel apply atomically."""
    def __init__(self, owner, key=None):
        super().__init__(owner)
        key=key or owner._overlay_key_for_edit()
        self.owner, self.key, self.axis = owner, key, 0
        source=list(owner.curves)
        if key in owner.documents and owner.documents[key].curve_uids is not None:
            order=owner.documents[key].curve_uids;lookup={c.uid:c for c in source}
            source=[lookup[uid] for uid in order if uid in lookup]+[c for c in source if c.uid not in order]
        self.draft = [replace(c, operations=list(c.operations), history=list(c.history)) for c in source]
        for curve in self.draft: curve.activate_view(key)
        base = default_plot_options(); base.update(owner.user_defaults("overlay")["options"])
        self.options = deepcopy(owner.plot_options.get(key, validate_plot_options(base)))
        if key not in owner.documents: owner.apply_default_appearance([c for c in self.draft if c.overlay_enabled], owner.user_defaults("overlay"))
        self.setObjectName("OverlayOptionsForm")
        self.setWindowTitle("叠加绘图选项")
        # Native client640x420, with20px reserved for inline validation.
        self.setFixedSize(640,440)
        self.tabs=QTabWidget(self);self.tabs.setObjectName("PageControl");self.tabs.setGeometry(1,0,638,381)
        self.build_curves(); self.build_axes(); self.build_title(); self.build_legend(); self.build_grid(); self.build_auto()
        self.error=QLabel(self);self.error.setGeometry(8,383,624,20);self.error.setStyleSheet("color:#a02020")
        for title,name,left,fn in (("确定","OK",188,self.accept),("保存","Save",276,self.save),("默认值","Default",364,self.defaults),("取消","Cancel",452,self.reject),("帮助","Help",544,self.help)):
            btn=QPushButton(title,self);btn.setObjectName(name);btn.setStyleSheet("min-width:0px;");btn.setGeometry(left,410,81,25);btn.clicked.connect(fn)
            if title=="确定":btn.setDefault(True)
            if title == "保存": btn.setToolTip("只保存当前页的默认设置；分析会话由文件菜单保存")
        self.populate()

    def build_curves(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(5, 8, 5, 5)
        group = QGroupBox("坐标轴"); radio_row = QHBoxLayout(group); radio_row.setContentsMargins(15, 3, 15, 3)
        self.axis_group = QButtonGroup(self)
        for i in range(4):
            radio = QRadioButton(f"Y{i + 1}"); self.axis_group.addButton(radio, i); radio_row.addWidget(radio)
        self.axis_group.button(0).setChecked(True); radio_row.addStretch(); layout.addWidget(group)
        self.axis_group.idClicked.connect(self.switch_axis)
        self.table = QTableWidget(10, 7)
        self.table.setHorizontalHeaderLabels(["曲线", "线条类型", "符号", "颜色", "Y 偏移", "文件名", "显示图例文本"])
        self.table.verticalHeader().hide(); self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(21)
        self.table.horizontalHeader().setMinimumSectionSize(25)
        for col, width in enumerate((28, 83, 42, 83, 60, 115, 186)):
            self.table.setColumnWidth(col, width)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.context_menu)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout(); row.setSpacing(4)
        for title, fn in (("自动线条", self.auto_lines), ("自动符号", self.auto_symbols), ("自动颜色", self.auto_colors), ("自动偏移", self.auto_offsets), ("添加曲线", self.add_curves), ("删除曲线", self.delete_curves), ("全部删除", self.delete_all)):
            btn = QPushButton(title); btn.setMinimumWidth(0); btn.setStyleSheet("padding: 4px 2px;"); btn.clicked.connect(fn); row.addWidget(btn)
        layout.addLayout(row); self.tabs.addTab(page, "曲线")

    def axis_curves(self):
        return [c for c in self.draft if c.overlay_enabled and c.axis == self.axis]

    def switch_axis(self, index):
        self.axis = index; self.populate()

    def populate(self):
        self.table.clearContents()
        curves = self.axis_curves()
        for row in range(10):
            curve = curves[row] if row < len(curves) else None
            self.table.setCellWidget(row, 0, QLabel(f" {row + 1}"))
            line = combo(LINE_TYPES, curve.style if curve else "-")
            symbol = combo(SYMBOLS, curve.marker if curve else "")
            color = QComboBox()
            colors = COLORS + ([] if not curve or curve.color in dict(COLORS).values() else [(curve.color, curve.color)])
            for name, value in colors:
                pix = QPixmap(14, 14); pix.fill(QColor(value)); color.addItem(QIcon(pix), name, value)
            color.addItem("自定义…", "custom")
            color.setCurrentIndex(max(0, color.findData(curve.color if curve else "#000000")))
            offset = number(value=curve.display_y_offset(curve.overlay_offset) if curve else 0, decimals=4); offset.setButtonSymbols(offset.ButtonSymbols.NoButtons)
            filename = QLineEdit(curve.display_filename if curve else ""); filename.setMaxLength(4096)
            filename.setToolTip(curve.dataset.document_key + "\n" + curve.result_label if curve else "")
            legend = QWidget(); lr = QHBoxLayout(legend); lr.setContentsMargins(0, 0, 0, 0); lr.setSpacing(1)
            check = QCheckBox(); check.setChecked(curve.show_legend_text if curve else False)
            text = QLineEdit(curve.legend_text if curve else ""); text.setMaxLength(32)
            text.setToolTip("图例自定义文字，最多32字符" + ("\n旧会话原文："+curve.legend_text if curve and len(curve.legend_text)>32 else ""))
            lr.addWidget(check); lr.addWidget(text)
            for col, widget in enumerate((line, symbol, color, offset, filename, legend), 1):
                self.table.setCellWidget(row, col, widget)
                widget.setEnabled(curve is not None)
            if curve:
                line.currentIndexChanged.connect(lambda _, c=curve, b=line: setattr(c, "style", b.currentData()))
                symbol.currentIndexChanged.connect(lambda _, c=curve, b=symbol: setattr(c, "marker", b.currentData()))
                color.currentIndexChanged.connect(lambda _, c=curve, b=color: self.set_color(c, b))
                offset.valueChanged.connect(lambda val, c=curve: setattr(c, "overlay_offset", val/c.y_unit_factor()))
                filename.textChanged.connect(lambda val, c=curve: setattr(c, "display_filename", val))
                check.toggled.connect(lambda val, c=curve: setattr(c, "show_legend_text", val))
                text.textChanged.connect(lambda val, c=curve: setattr(c, "legend_text", val))
        if len(curves) > 10:
            self.error.setText(f"Y{self.axis + 1} 有 {len(curves)} 条曲线；每轴最多 10 条，请调整坐标轴或移除曲线。")

    def set_color(self, curve, box):
        value = box.currentData()
        if value == "custom":
            chosen = QColorDialog.getColor(QColor(curve.color), self)
            if chosen.isValid():
                value = chosen.name(); box.insertItem(box.count() - 1, value, value)
            else:
                value = curve.color
            box.setCurrentIndex(box.findData(value))
        curve.color = value

    def auto_lines(self):
        self.apply_auto_sequence("lines", "style")

    def auto_symbols(self):
        self.apply_auto_sequence("symbols", "marker")

    def auto_colors(self):
        self.apply_auto_sequence("colors", "color")

    def apply_auto_sequence(self, name, attribute):
        curves = self.axis_curves()
        if len(curves) > 10:
            self.error.setText("每轴最多十条曲线，请先调整坐标轴或移除曲线。"); return
        values = self.auto_page.collect()[name]
        for curve, value in zip(curves, values): setattr(curve, attribute, value)
        self.error.clear(); self.populate()

    def auto_offsets(self):
        curves = self.axis_curves()
        if not curves: return
        if len(curves) > 10:
            self.error.setText("每轴最多十条曲线，请先调整坐标轴或移除曲线。"); return
        try:
            step = axis_offset_step(self.owner, curves, self.axis, self.auto_page.collect())
            offsets = [i * step for i in range(len(curves))]
            if not np.isfinite(offsets).all(): raise ValueError("自动偏移超出有限范围")
            for curve, offset in zip(curves, offsets): curve.overlay_offset = offset/curve.y_unit_factor()
            self.error.clear(); self.populate()
        except ValueError as exc:
            self.error.setText(str(exc))

    def add_curves(self):
        dialog = AddCurvesDialog(self, self.draft, self.axis)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        selected = dialog.selected_curves
        additions = []
        for c in selected:
            match = next((e for e in self.draft if e.dataset.document_key == c.dataset.document_key and e.y_index == c.y_index and not e.operations and e.axis == self.axis), None)
            if match:
                if not match.overlay_enabled or not match.visible: additions.append(match)
            else: additions.append(c)
        if len(self.axis_curves()) + len(additions) > 10:
            self.error.setText("每个 Y 轴最多 10 条曲线，请选择另一个坐标轴。"); return
        for c in additions:
            c.overlay_enabled = True; c.visible = True
            if c not in self.draft: self.draft.append(c)
        self.error.clear(); self.populate()

    def delete_curves(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        curves = self.axis_curves()
        for row in rows:
            if row < len(curves): curves[row].overlay_enabled = False
        self.populate()

    def delete_all(self):
        for c in self.axis_curves(): c.overlay_enabled = False
        self.populate()

    def move_curve(self, curve, destination):
        curves = self.axis_curves(); position = curves.index(curve)
        target = {"top": 0, "up": max(0, position - 1), "down": min(len(curves)-1, position+1), "bottom": len(curves)-1}[destination]
        if target != position:
            other = curves[target]; self.draft.remove(curve)
            self.draft.insert(self.draft.index(other) + (1 if target > position else 0), curve)
        self.populate()

    def move_axis(self, curve, axis):
        targets = [c for c in self.draft if c.overlay_enabled and c.axis == axis]
        if len(targets) >= 10 or any(c.result_unit != curve.result_unit for c in targets):
            self.error.setText("目标坐标轴已满或信号单位不兼容。"); return
        curve.axis = axis; self.populate()

    def context_menu(self, point):
        row = self.table.rowAt(point.y()); curves = self.axis_curves()
        if not 0 <= row < len(curves): return
        curve = curves[row]; menu = QMenu(self)
        for title, dest in (("移至顶部", "top"), ("上移", "up"), ("下移", "down"), ("移至底部", "bottom")):
            menu.addAction(title, lambda d=dest: self.move_curve(curve, d))
        sub = menu.addMenu("移至坐标轴")
        for axis in range(4): sub.addAction(f"Y{axis+1}", lambda a=axis: self.move_axis(curve, a))
        menu.exec(self.table.viewport().mapToGlobal(point))

    def build_axes(self):
        page=QWidget();page.setObjectName("AxesSheet")
        self.y_labels, self.axis_flag_boxes, self.axis_x_offsets = [], [], []
        domain=self.options["x_domain"] or self.owner.domain
        for i in range(4):
            group=QGroupBox(f"Y{i+1}",page);group.setObjectName(f"Y{i+1}Group");group.setGeometry(16,12+72*i,601,65)
            label=QLabel("名称:",group);label.setGeometry(32,20,40,17)
            name=QLineEdit(self.options["y_labels"][i],group);name.setMaxLength(40);name.setGeometry(72,16,289,21)
            name.setObjectName(f"Y{i+1}NameEdit");self.y_labels.append(name)
            curve = next((c for c in self.draft if c.overlay_enabled and c.axis == i), None)
            label=QLabel("Y单位:",group);label.setGeometry(412,20,40,17)
            label=QLabel(curve.result_unit if curve else "",group);label.setGeometry(456,20,128,17);label.setToolTip(label.text())
            label=QLabel("显示:",group);label.setGeometry(32,42,40,17);flags={}
            for key,caption,left,width in (("line","线条类型",72,85),("color","颜色",172,60),("symbol","符号",272,60)):
                box=QCheckBox(caption,group);box.setGeometry(left,42,width,17);box.setChecked(self.options["axis_flags"][i][key]);flags[key]=box
            label=QLabel("X偏移:",group);label.setGeometry(408,42,44,17)
            field=QLineEdit(format(self.options["axis_x_offsets"][i],".15g"),group);field.setGeometry(456,38,49,21)
            field.setObjectName(f"Y{i+1}XOffsetEdit")
            unit=curve.x_unit(domain) if curve is not None else ""
            field.setToolTip(f"相邻曲线横向间距（{unit}）；本轴首条曲线不偏移")
            self.axis_x_offsets.append(field)
            label=QLabel(unit,group);label.setGeometry(516,42,70,17);label.setToolTip(unit)
            self.axis_flag_boxes.append(flags)
        group=QGroupBox("X",page);group.setObjectName("XGroup");group.setGeometry(16,300,601,45)
        label=QLabel("名称:",group);label.setGeometry(32,20,40,17)
        self.x_label=QLineEdit(self.options["x_label"],group);self.x_label.setMaxLength(40);self.x_label.setGeometry(72,16,289,21)
        label=QLabel("X单位:",group);label.setGeometry(412,20,40,17)
        curve=next((c for c in self.draft if c.overlay_enabled),None);unit=curve.x_unit(domain) if curve else ""
        label=QLabel(unit,group);label.setGeometry(456,20,128,17);label.setToolTip(unit)
        self.tabs.addTab(page, "坐标轴")

    def build_title(self):
        page = QWidget(); layout = QFormLayout(page)
        self.title = QLineEdit(self.options["window_name"]); self.title.setMaxLength(80); layout.addRow("窗口名称", self.title)
        self.export_align = combo([("左", "left"), ("中", "center"), ("右", "right")], self.options["export_align"])
        layout.addRow("对齐", self.export_align)
        self.export_heading = QPlainTextEdit(self.options["export_title"]); self.export_heading.setMinimumHeight(130)
        layout.addRow("绘图标题", self.export_heading)
        layout.addRow(QLabel("标题最多四行，每行76个字符，只用于打印和导出。")); self.tabs.addTab(page, "绘图标题")

    def build_legend(self):
        page = QWidget(); page.setMinimumSize(620, 330)
        group = QGroupBox("显示", page); group.setGeometry(16, 20, 601, 41); self.legend_boxes = {}
        for index, (key, caption) in enumerate((("legend_border", "边框"), ("legend_line", "线条类型"), ("legend_color", "颜色"), ("legend_symbol", "符号"), ("legend_file", "文件名"), ("legend_text", "文本"))):
            box = QCheckBox(caption, group); box.setChecked(self.options[key]); self.legend_boxes[key] = box
            box.setGeometry(24+92*index, 16, 90, 20)
        position = QGroupBox("图例定位点位置", page); position.setGeometry(16, 92, 601, 117)
        self.legend_coordinates = []
        anchor = self.options["legend_anchor"] or {"x": .98, "y": .98, "horizontal": "right", "vertical": "top"}
        for i, key in enumerate(("x", "y")):
            label = QLabel(key.upper()+":", position); label.setGeometry(28, 36+36*i, 18, 20)
            field = number(0, 1, anchor[key], decimals=6); field.setParent(position); field.setGeometry(48, 32+36*i, 101, 23)
            self.legend_coordinates.append(field)
        self.legend_handles = {}
        for key, caption, x, values in (("vertical", "垂直定位点", 172, (("上", "top"), ("中", "center"), ("下", "bottom"))),
                                       ("horizontal", "水平定位点", 312, (("左", "left"), ("中", "center"), ("右", "right")))):
            group = QGroupBox(caption, position); group.setGeometry(x, 16, 121, 85)
            buttons = QButtonGroup(self); self.legend_handles[key] = buttons
            for i, (text, value) in enumerate(values):
                box = QRadioButton(text, group); box.setProperty("handle", value); box.setGeometry(15, 18+20*i, 80, 20)
                buttons.addButton(box); box.setChecked(anchor[key] == value)
        self.legend = combo([("自动（多条曲线时显示）", None), ("显示", True), ("隐藏", False)], self.options["legend"])
        self.legend.setParent(page); self.legend.setGeometry(72, 231, 250, 24)
        label = QLabel("图例", page); label.setGeometry(16, 233, 50, 20)
        locations = [("自动", "best"), ("右上", "upper right"), ("左上", "upper left"), ("右下", "lower right"), ("左下", "lower left"), ("手动坐标", "manual")]
        self.legend_location = combo(locations, "manual" if self.options["legend_anchor"] else self.options["legend_location"])
        self.legend_location.setParent(page); self.legend_location.setGeometry(400, 231, 160, 24)
        label = QLabel("位置", page); label.setGeometry(345, 233, 50, 20)
        for field in self.legend_coordinates: field.valueChanged.connect(self.manual_legend_position)
        for group in self.legend_handles.values(): group.buttonClicked.connect(self.manual_legend_position)
        hint = QLabel("X/Y为绘图区内0到1的相对位置，原点在左下；图例也可直接拖动。", page)
        hint.setGeometry(16, 278, 601, 30)
        self.tabs.addTab(page, "图例")

    def manual_legend_position(self, *_):
        self.legend_location.setCurrentIndex(self.legend_location.findData("manual"))

    def build_grid(self):
        page = QWidget(); layout = QVBoxLayout(page); self.grid_boxes = {}
        for key, label in (("grid_x", "X 主网格"), ("grid_y", "Y 主网格"), ("grid_minor", "同时显示次网格")):
            box = QCheckBox(label); box.setChecked(self.options[key]); self.grid_boxes[key] = box; layout.addWidget(box)
        layout.addStretch(); self.tabs.addTab(page, "网格")

    def build_auto(self):
        self.auto_page = AutoStylesPage(self.options)
        self.tabs.addTab(self.auto_page, "自动")

    def update_page_options(self, settings, page):
        if page == 1:
            settings.update(x_label=self.x_label.text(), y_labels=[box.text() for box in self.y_labels], axis_flags=[{key: box.isChecked() for key, box in flags.items()} for flags in self.axis_flag_boxes])
            settings["axis_x_offsets"]=[float(field.text()) for field in self.axis_x_offsets]
        elif page == 2:
            heading = self.export_heading.toPlainText()
            if len(heading.splitlines()) > 4 or any(len(line) > 76 for line in heading.splitlines()): raise ValueError("绘图标题最多四行，每行76个字符")
            settings.update(window_name=self.title.text(), export_title=heading, export_align=self.export_align.currentData())
        elif page == 3:
            settings["legend"] = self.legend.currentData()
            if self.legend_location.currentData() == "manual":
                settings["legend_anchor"] = {"x": self.legend_coordinates[0].value(), "y": self.legend_coordinates[1].value(),
                                              **{key: group.checkedButton().property("handle") for key, group in self.legend_handles.items()}}
            else: settings.update(legend_location=self.legend_location.currentData(), legend_anchor=None)
            settings.update({key: box.isChecked() for key, box in self.legend_boxes.items()})
        elif page == 4: settings.update({key: box.isChecked() for key, box in self.grid_boxes.items()})
        elif page == 5:
            settings["overlay_auto"] = self.auto_page.collect()
            settings["auto_x"] = self.auto_page.scale_boxes["x"].isChecked()
            settings["auto_y"] = [self.auto_page.scale_boxes[i].isChecked() for i in range(4)]
            if settings["auto_x"]: settings.update(x_limits=None, x_ticks=None)
            for i in range(4):
                if settings["auto_y"][i]: settings["y_limits"][i] = settings["y_ticks"][i] = None
            settings.update(fill_manual_limits(self.owner, settings))

    def collect_options(self):
        settings = deepcopy(self.options)
        for page in range(6): self.update_page_options(settings, page)
        return validate_plot_options(settings)

    def apply(self):
        try:
            options = self.collect_options()
            for axis in range(4):
                curves = [c for c in self.draft if c.overlay_enabled and c.axis == axis]
                if len(curves) > 10: raise ValueError(f"Y{axis+1} 超过 10 条曲线，请调整坐标轴。")
                if len({c.result_unit for c in curves}) > 1: raise ValueError(f"Y{axis+1} 信号单位不一致，请分配不同坐标轴。")
                if not np.isfinite((len(curves)-1)*options["axis_x_offsets"][axis]):raise ValueError("X偏移超出有限数值范围")
            selected = self.owner.selected()
            selected_uid = selected.uid if selected else None
            options["overlay_members"]=[c.uid for c in self.draft if c.overlay_enabled]
            self.owner.curves = self.draft
            self.owner.plot_options[self.key] = options
            self.owner.sync_documents(); self.owner.rebuild_files()
            index = next((i for i, c in enumerate(self.owner.curves) if c.uid == selected_uid), 0)
            if self.owner.curves: self.owner.files.setCurrentItem(self.owner.files.topLevelItem(index))
            members = [c for c in self.draft if c.overlay_enabled]
            doc = self.owner._document(self.key); doc.curve_uids = [c.uid for c in members]; doc.plot_signature = None
            self.owner.touch(); self.owner._show_document(self.key); self.owner.redraw()
            return True
        except ValueError as exc:
            self.error.setText(str(exc)); return False

    def accept(self):
        if self.apply(): super().accept()

    def save(self):
        from .preferences import save_defaults
        try:
            page = self.tabs.currentIndex()
            settings = deepcopy(self.options); self.update_page_options(settings, page)
            curves = [c for c in self.draft if c.overlay_enabled] if page == 0 else ()
            save_defaults("overlay", ("curves", "axes", "title", "legend", "grid", "auto")[page], validate_plot_options(settings), curves)
            self.error.clear(); self.owner.statusBar().showMessage("当前页默认设置已保存。", 5000)
        except (ValueError, OSError) as exc:
            self.error.setText(str(exc))

    def defaults(self):
        self.error.clear()
        factory = default_plot_options(); page = self.tabs.currentIndex()
        if page == 0:
            for c in self.draft:
                c.color, c.style, c.marker, c.overlay_offset = "#000000", "-", "", 0.
                c.legend_text, c.display_filename, c.show_legend_text, c.show_legend = c.dataset.name[:32], c.dataset.path.name, True, True
            self.populate()
        elif page == 1:
            self.x_label.clear()
            for field in self.axis_x_offsets:field.setText("0")
            for box in self.y_labels: box.clear()
            for flags in self.axis_flag_boxes:
                for box in flags.values(): box.setChecked(False)
        elif page == 2:
            self.title.clear(); self.export_heading.clear(); self.export_align.setCurrentIndex(0); self.options["title"] = ""
        elif page == 3:
            self.legend.setCurrentIndex(0)
            for field in self.legend_coordinates: field.setValue(.98)
            for key, group in self.legend_handles.items():
                for button in group.buttons(): button.setChecked(button.property("handle") == ("right" if key == "horizontal" else "top"))
            self.legend_location.setCurrentIndex(0)
            for key, box in self.legend_boxes.items(): box.setChecked(factory[key])
        elif page == 4:
            for key, box in self.grid_boxes.items(): box.setChecked(factory[key])
        elif page == 5:
            self.auto_page.load(factory)

    def help(self):
        self.error.setText("每个 Y 轴最多 10 条兼容信号。确定应用全部页；取消放弃草稿。保存只存当前页默认设置；默认值只恢复当前页。")
        self.error.setToolTip(self.error.text())


class SignalAnalysisDialog(QDialog):
    def __init__(self, owner, kind):
        super().__init__(owner)
        self.owner, self.kind = owner, kind
        self.setWindowTitle("信号最大" if kind == "signal_max" else "信号变化")
        self.resize(440, 330)
        layout = QFormLayout(self)
        self.curves = owner.visible_curves()
        self.curve_box = QComboBox()
        for c in self.curves: self.curve_box.addItem(f"{c.dataset.path.name} · {c.result_label} · Y{c.axis+1}")
        selected = owner.selected()
        self.curve_box.setCurrentIndex(self.curves.index(selected) if selected in self.curves else 0)
        layout.addRow("曲线", self.curve_box)
        self.low, self.high = number(value=owner.lo_box.value(), decimals=9), number(value=owner.hi_box.value(), decimals=9)
        self._exact_bounds = [None, None]
        self.low.valueChanged.connect(lambda _: self.clear_exact(0))
        self.high.valueChanged.connect(lambda _: self.clear_exact(1))
        layout.addRow("X 下限", self.low); layout.addRow("X 上限", self.high)
        row = QHBoxLayout()
        for title, fn in (("全范围", self.full_range), ("图上选范围", self.select_range), ("取点 1", lambda: self.pick_point(0)), ("取点 2", lambda: self.pick_point(1))):
            btn = QPushButton(title); btn.setMinimumWidth(0); btn.clicked.connect(fn); row.addWidget(btn)
        layout.addRow(row)
        self.batch = QCheckBox("对当前图中全部可见曲线计算"); layout.addRow(self.batch)
        self.annotation_boxes = {}
        if kind == "signal_change":
            row = QHBoxLayout()
            for key, label in (("change", "变化值"), ("y_limits", "Y 两点值"), ("signed", "有符号"), ("x_limits", "X 两点值")):
                box = QCheckBox(label); box.setChecked(True); row.addWidget(box); self.annotation_boxes[key] = box
            layout.addRow(row)
        self.output = QLabel("按实际采样点计算；结果会标注在曲线上。")
        self.output.setWordWrap(True); self.output.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); layout.addRow(self.output)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText("计算并记录")
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.calculate)
        buttons.rejected.connect(self.reject); layout.addRow(buttons)
        self.curve_box.currentIndexChanged.connect(self.select_curve)
        self.select_curve(self.curve_box.currentIndex())

    def select_curve(self, index):
        if not 0 <= index < len(self.curves): return
        curve = self.curves[index]
        if curve in self.owner.curves:
            self.owner.files.setCurrentItem(self.owner.files.topLevelItem(self.owner.curves.index(curve)))
        self.full_range()

    def full_range(self):
        if not self.curves: return
        curve = self.curves[self.curve_box.currentIndex()]
        x, _ = curve.xy(self.owner.domain)
        self.set_bounds(float(np.min(x)), float(np.max(x)))

    def clear_exact(self, index):
        self._exact_bounds[index] = None

    def set_bounds(self, lo, hi):
        self.low.setValue(lo); self.high.setValue(hi)
        self._exact_bounds = [float(lo), float(hi)]

    def bounds(self):
        return tuple(exact if exact is not None else box.value() for exact, box in zip(self._exact_bounds, (self.low, self.high)))

    def select_range(self):
        self.owner._range_dialog = self; self.owner.range_enabled.setChecked(True)
        self.owner.enable_range(True); self.hide()
        self.owner.statusBar().showMessage("在曲线上拖拽选择范围，松开后返回分析窗口")

    def pick_point(self, index):
        self.owner.range_enabled.setChecked(False)
        if self.owner.toolbar.mode:
            if "pan" in str(self.owner.toolbar.mode).lower(): self.owner.toolbar.pan()
            else: self.owner.toolbar.zoom()
        self.owner._point_dialog = (self, index)
        self.hide(); self.owner.statusBar().showMessage(f"在图中单击选择点 {index+1}（吸附到最近采样点）")

    def calculate(self):
        if not self.curves: return
        self.owner.analysis_box.setCurrentIndex(self.owner.analysis_box.findData(self.kind))
        lo, hi = self.bounds()
        self.owner.lo_box.setValue(lo); self.owner.hi_box.setValue(hi)
        self.owner.batch_check.setChecked(self.batch.isChecked())
        before = len(self.owner.results)
        self.owner.run_analysis({key: box.isChecked() for key, box in self.annotation_boxes.items()}, bounds=(lo, hi))
        added = self.owner.results[before:]
        if added:
            vals = added[0]["values"]
            if self.kind == "signal_max": self.output.setText(f"信号最大 = {vals['value']:.8g}，X = {vals['max_x']:.8g}\n已记录 {len(added)} 条结果。")
            else: self.output.setText(f"起点 ({vals['start_x']:.8g}, {vals['start_y']:.8g})\n终点 ({vals['stop_x']:.8g}, {vals['stop_y']:.8g})\n变化 = {vals['change']:.8g}；已记录 {len(added)} 条结果。")

    def reject(self):
        if getattr(self.owner, "_range_dialog", None) is self: self.owner._range_dialog = None
        if getattr(self.owner, "_point_dialog", (None,))[0] is self: self.owner._point_dialog = (None, 0)
        super().reject()
