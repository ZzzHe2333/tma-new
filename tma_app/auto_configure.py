"""Native Auto Configure window; private proposals commit only after validation."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QGroupBox, QListWidget, QListWidgetItem, QCheckBox, QRadioButton, QButtonGroup, QPushButton, QPlainTextEdit, QLabel
from .workspace import default_plot_options, validate_plot_options, APPEARANCE_FIELDS
from .overlay_settings import default_auto_configure, validate_auto_configure, apply_auto_styles, axis_offset_step, fill_manual_limits


def optimize_legend(curves, options):
    """Independent minimum-field policy; exact vendor tie-breaking is unknown."""
    datasets = {c.dataset.document_key: c.dataset for c in curves}
    names = [next(c.display_filename for c in curves if c.dataset.document_key == key) for key in datasets]
    samples = [ds.name for ds in datasets.values()]
    for curve in curves: curve.show_legend = curve.show_legend_text = True
    options["legend"] = True
    if len(set(names)) == len(names):
        options.update(legend_file=True, legend_text=False)
    elif len(set(samples)) == len(samples):
        options.update(legend_file=False, legend_text=True)
        for curve in curves: curve.legend_text = curve.dataset.name
    else:
        options.update(legend_file=False, legend_text=True)
        paths = list(datasets)
        labels = {path: datasets[path].display_name for path in paths}
        depth = 1
        while len(set(labels.values())) < len(paths):
            depth += 1
            labels = {key: str(Path(*datasets[key].path.parts[-depth:])) + (f" [{datasets[key].opening_index}]" if datasets[key].opening_index>1 else "") for key in paths}
            if depth > max(len(datasets[key].path.parts) for key in paths): break
        for curve in curves: curve.legend_text = labels[curve.dataset.document_key]


def optimize_axis_labels(curves):
    """Show common non-default styles; a transparent independent optimization."""
    flags = []
    for axis in range(4):
        group = [c for c in curves if c.axis == axis]
        flags.append({"line": bool(group) and len({c.style for c in group}) == 1 and group[0].style not in ("-", "None"),
                      "color": bool(group) and len({c.color for c in group}) == 1 and group[0].color.lower() != "#000000",
                      "symbol": bool(group) and len({c.marker for c in group}) == 1 and bool(group[0].marker)})
    return flags


class AutoConfigureDialog(QDialog):
    def __init__(self, owner, *, blank=False):
        super().__init__(owner)
        self.owner = owner
        self.blank_start = blank
        base = default_plot_options(); base.update(owner.user_defaults("overlay")["options"])
        self.key = owner._next_overlay_key() if blank else owner._overlay_key_for_edit() if hasattr(owner, "_overlay_key_for_edit") else "__overlay__"
        self.options = validate_plot_options(owner.plot_options.get(self.key, base))
        self.sources = list({c.dataset.document_key: c.dataset for c in owner.curves}.values())
        self.setObjectName("AutoConfigureForm"); self.setWindowTitle("新建叠图 · 自动配置" if blank else "叠图自动配置")
        self.setFixedSize(631, 355); self.setModal(True)
        files_group = QGroupBox("选择要叠加的曲线（默认不选）" if blank else "文件", self); files_group.setGeometry(10, 8, 299, 189)
        self.files = QListWidget(files_group); self.files.setGeometry(8, 17, 283, 164)
        self.file_items = []
        self.curve_items = {}
        normal = [replace(c, operations=list(c.operations), history=list(c.history)) for c in owner.curves]
        for curve in normal: curve.activate_view(None)
        selected = {c.dataset.document_key for c in owner.visible_curves()}
        choices = [c for c in normal if c.visible and c.normal_enabled] if blank else self.sources
        for source in choices:
            label = f'{source.dataset.display_name} · {source.result_label} · Y{source.axis+1}' if blank else source.display_name
            item = QListWidgetItem(label); item.setToolTip(str(source.dataset.path if blank else source.path)+'\n'+label); item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked if blank else Qt.CheckState.Checked if source.document_key in selected else Qt.CheckState.Unchecked)
            if blank: self.curve_items[source.uid] = item
            self.files.addItem(item); self.file_items.append(item)
        signals = QGroupBox("信号", self); signals.setGeometry(317, 8, 60, 189)
        self.signal_boxes = []
        for axis in range(4):
            box = QCheckBox(f"Y{axis+1}", signals); box.setGeometry(10, 28+40*axis, 43, 20)
            box.setEnabled(any(c.visible and c.axis == axis for c in (normal if blank else owner.curves))); self.signal_boxes.append(box)
        group = QGroupBox("自动", self); group.setGeometry(385, 8, 236, 189)
        self.auto_boxes, self.mode_groups = {}, {}
        for row, (key, caption) in enumerate((("line", "线条"), ("symbol", "符号"), ("color", "颜色"))):
            box = QCheckBox(caption, group); box.setGeometry(18, 28+32*row, 65, 20); self.auto_boxes[key] = box
            buttons = QButtonGroup(self); self.mode_groups[key] = buttons
            for index, (text, mode) in enumerate((("坐标轴", "axes"), ("曲线", "curves"))):
                button = QRadioButton(text, group); button.setGeometry(86+68*index, 28+32*row, 65, 20)
                button.setProperty("mode", mode); buttons.addButton(button, index)
            box.toggled.connect(lambda checked, buttons=buttons: [b.setEnabled(checked) for b in buttons.buttons()])
        for key, caption, x, y in (("offset", "曲线偏移", 18, 124), ("axis", "坐标轴", 128, 124), ("file_selection", "全选曲线" if blank else "文件选择", 18, 156), ("legend", "图例", 128, 156)):
            box = QCheckBox(caption, group); box.setGeometry(x, y, 105, 20); self.auto_boxes[key] = box
        self.auto_boxes["file_selection"].toggled.connect(lambda checked: self.select_all_files(checked) if blank or checked else None)
        heading = QGroupBox("绘图标题", self); heading.setGeometry(10, 208, 611, 85)
        self.heading = QPlainTextEdit(heading); self.heading.setGeometry(8, 17, 595, 60)
        self.heading.setToolTip("只用于打印和导出")
        self.error = QLabel(self); self.error.setGeometry(10, 295, 611, 20); self.error.setStyleSheet("color: #a00000")
        for caption, x, callback in (("确定", 188, self.accept), ("保存", 276, self.save), ("默认值", 364, self.defaults), ("取消", 452, self.reject), ("帮助", 540, self.help)):
            button = QPushButton(caption, self); button.setGeometry(x, 322, 81, 25); button.clicked.connect(callback)
            if caption == "确定": button.setDefault(True)
        self.load(self.options["overlay_configure"])

    def select_all_files(self, checked=True):
        for item in self.file_items: item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def load(self, value):
        value = validate_auto_configure(value)
        if self.blank_start: value['file_selection'] = False
        for axis, box in enumerate(self.signal_boxes): box.setChecked(box.isEnabled() and value["signals"][axis])
        for key, box in self.auto_boxes.items(): box.setChecked(value[key])
        for key, group in self.mode_groups.items():
            for button in group.buttons():
                button.setChecked(button.property("mode") == value[key+"_mode"])
                button.setEnabled(self.auto_boxes[key].isChecked())
        if value["file_selection"]: self.select_all_files()
        self.heading.setPlainText(value["heading"])

    def collect(self):
        values = {key: box.isChecked() for key, box in self.auto_boxes.items()}
        values.update(signals=[box.isChecked() for box in self.signal_boxes], heading=self.heading.toPlainText())
        values.update({key+"_mode": group.checkedButton().property("mode") for key, group in self.mode_groups.items()})
        return validate_auto_configure(values)

    def accept(self):
        try:
            config = self.collect()
            selected = {source.document_key for source, item in zip(self.sources, self.file_items) if item.checkState() == Qt.CheckState.Checked}
            selected_uids = {uid for uid,item in self.curve_items.items() if item.checkState()==Qt.CheckState.Checked}
            if self.blank_start:
                selected = {c.dataset.document_key for c in self.owner.curves if c.uid in selected_uids}
            if not selected: raise ValueError("请选择要叠加的文件")
            draft = [replace(c, operations=list(c.operations), history=list(c.history)) for c in self.owner.curves]
            for curve in draft:
                curve.activate_view(None)
                normal = {key: getattr(curve, key) for key in APPEARANCE_FIELDS}
                from .overlay_views import DETAIL_FIELDS
                details={key:getattr(curve,key) for key in DETAIL_FIELDS}
                curve.activate_view(self.key)
                for key, value in normal.items(): setattr(curve, key, value)
                for key,value in details.items():setattr(curve,key,value)
            curves, used = [], set()
            for curve in draft:
                identity = (curve.dataset.document_key, curve.y_index, curve.result_unit, curve.uid if curve.derived is not None else None)
                chosen = curve.uid in selected_uids if self.blank_start else curve.dataset.document_key in selected
                included = chosen and config["signals"][curve.axis] and curve.visible and curve.normal_enabled and identity not in used
                curve.overlay_enabled = included
                if included: curves.append(curve); used.add(identity)
            if not curves: raise ValueError("所选文件没有勾选的已绘制信号")
            for axis in range(4):
                group = [c for c in curves if c.axis == axis]
                if len(group) > 10: raise ValueError(f"Y{axis+1} 每轴最多十条曲线")
                if len({c.result_unit for c in group}) > 1: raise ValueError(f"Y{axis+1} 信号单位不一致，请先调整普通图坐标轴")
            options = deepcopy(self.options)
            apply_auto_styles(curves, options["overlay_auto"], config)
            if config["offset"]:
                for axis in range(4):
                    group = [c for c in curves if c.axis == axis]
                    if group:
                        step = axis_offset_step(self.owner, group, axis, options["overlay_auto"])
                        for i, curve in enumerate(group): curve.overlay_offset = i*step/curve.y_unit_factor()
                        if not np.isfinite([c.offset for c in group]).all(): raise ValueError("自动偏移超出有限范围")
            if config["axis"]: options["axis_flags"] = optimize_axis_labels(curves)
            if config["legend"]: optimize_legend(curves, options)
            options.update(overlay_configure=config, export_title=config["heading"])
            options = validate_plot_options(fill_manual_limits(self.owner, options))
            options["overlay_members"]=[c.uid for c in curves]
            selected_curve = self.owner.selected()
            uid = selected_curve.uid if selected_curve and any(c.uid == selected_curve.uid for c in curves) else curves[0].uid
            self.owner.cancel_measurement(redraw=False)
            self.owner.curves = draft; self.owner.plot_options[self.key] = options
            self.owner.sync_documents(); self.owner.rebuild_files()
            doc = self.owner._document(self.key); doc.curve_uids = [c.uid for c in curves]; doc.plot_signature = None
            self.owner._show_document(self.key)
            index = next(i for i, c in enumerate(draft) if c.uid == uid)
            self.owner.files.setCurrentItem(self.owner.files.topLevelItem(index))
            self.owner.touch(); self.owner.redraw()
            super().accept()
        except ValueError as exc:
            self.error.setText(str(exc))

    def save(self):
        from .preferences import save_defaults
        try:
            save_defaults("overlay", "configure", {"overlay_configure": self.collect()})
            self.error.clear(); self.owner.statusBar().showMessage("自动配置默认设置已保存。", 5000)
        except (ValueError, OSError) as exc: self.error.setText(str(exc))

    def defaults(self):
        self.error.clear(); self.load(default_auto_configure())

    def help(self):
        self.error.setText("自动样式读取叠图‘自动’页；标题只用于打印和导出。取消放弃本次配置。")
