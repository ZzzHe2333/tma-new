"""Local named paths and read-only weighing-sheet lookup settings."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QFileDialog, QDialogButtonBox, QCheckBox)
from .path_settings import ensure_config, load_paths, save_paths, batch_popup_enabled, save_batch_popup


class SettingsDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner); self.owner = owner
        self.setWindowTitle("设置 · 数据路径"); self.setObjectName("PathSettingsDialog"); self.resize(760, 390)
        layout = QVBoxLayout(self)
        self.location = QLabel(f"配置文件：{ensure_config()}"); self.location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.location.setWordWrap(True); layout.addWidget(self.location)
        hint = QLabel("默认打开文件夹：导入数据时首先打开此文件夹，重启后仍生效。\nm：选择称量表或其所在文件夹，支持 CSV、XLSX、XLS。优先识别样品名与重量表头；无表头时读取 B 列名称、C 列重量。")
        hint.setWordWrap(True); layout.addWidget(hint)
        self.batch_popup = QCheckBox("批量导入后自动弹出结果窗口（关闭后仍会后台计算，可从文件菜单查看）")
        self.batch_popup.setObjectName("BatchPopupSetting")
        self.batch_popup.setChecked(batch_popup_enabled()); layout.addWidget(self.batch_popup)
        self.paths = QTableWidget(0, 2); self.paths.setHorizontalHeaderLabels(["路径名称", "文件或文件夹路径"])
        self.paths.setColumnWidth(0, 140); self.paths.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.paths)
        self.original_paths = load_paths()
        if "默认打开文件夹" in self.original_paths:
            legacy = self.original_paths.pop("默认打开文件夹")
            self.original_paths.setdefault("open_folder", legacy)
        for name, path in {"m": "", "open_folder": "", **self.original_paths}.items(): self.add_row(name, path)
        row = QHBoxLayout()
        for caption, callback in (("选择文件…", self.choose_file), ("选择文件夹…", self.choose_folder), ("新增路径", self.add_path), ("删除路径", self.remove_path), ("测试 m 匹配", self.test_mass)):
            button = QPushButton(caption); button.clicked.connect(callback); row.addWidget(button)
        layout.addLayout(row)
        self.feedback = QLabel(); self.feedback.setWordWrap(True); self.feedback.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); layout.addWidget(self.feedback)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.paths.setCurrentCell(0, 1)

    def add_row(self, name, path):
        index = self.paths.rowCount(); self.paths.insertRow(index)
        item = QTableWidgetItem("默认打开文件夹" if name == "open_folder" else name)
        if name in ("m", "open_folder"):
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setData(Qt.ItemDataRole.UserRole, name)
        self.paths.setItem(index, 0, item); self.paths.setItem(index, 1, QTableWidgetItem(path))

    def add_path(self):
        self.add_row("", ""); self.paths.setCurrentCell(self.paths.rowCount()-1, 0)

    def remove_path(self):
        index = self.paths.currentRow()
        if index < 0 or self.paths.item(index, 0).data(Qt.ItemDataRole.UserRole) in ("m", "open_folder"):
            self.feedback.setText("此项保留，清空路径即可停用。")
        else: self.paths.removeRow(index)

    def choose_file(self):
        index = max(0, self.paths.currentRow())
        if self.paths.item(index, 0).data(Qt.ItemDataRole.UserRole) == "open_folder":
            self.choose_folder(); return
        path, _ = QFileDialog.getOpenFileName(self, "选择数据文件", self.paths.item(index, 1).text(), "称量表 (*.csv *.cvs *.xlsx *.xls);;所有文件 (*)")
        if path: self.paths.item(index, 1).setText(path)

    def choose_folder(self):
        index = max(0, self.paths.currentRow())
        path = QFileDialog.getExistingDirectory(self, "选择数据文件夹", self.paths.item(index, 1).text())
        if path: self.paths.item(index, 1).setText(path)

    def values(self):
        result = {}
        for row in range(self.paths.rowCount()):
            item = self.paths.item(row, 0)
            name = item.data(Qt.ItemDataRole.UserRole) or item.text().strip()
            if name == "默认打开文件夹": name = "open_folder"
            path = self.paths.item(row, 1).text().strip()
            if not name: raise ValueError("请填写路径名称，或删除空白行。")
            if name.casefold() in {key.casefold() for key in result}: raise ValueError(f"路径名称重复：{name}")
            result[name] = path
        return result

    def test_mass(self):
        from .mass_lookup import lookup_record
        curve = self.owner.selected()
        if curve is None: self.feedback.setText("请先导入一个样品，再测试 m 匹配。"); return
        try: result = lookup_record(curve.sample_name, self.values()["m"])
        except ValueError as exc: self.feedback.setText(str(exc)); return
        self.feedback.setText(f"样品：{curve.sample_name}\n" + (f"m = {result.value:g} {result.unit}\n来源：{result.source}" if result.value is not None else result.message))

    def accept(self):
        from .mass_lookup import clear_cache
        try:
            paths = self.values()
            save_paths(paths)
            save_batch_popup(self.batch_popup.isChecked())
        except (ValueError, OSError) as exc: self.feedback.setText(str(exc)); return
        if paths.get('m', '') != self.original_paths.get('m', ''):
            clear_cache(); self.owner.refresh_mass_lookup()
        else: self.owner.statusBar().showMessage("路径设置已保存")
        super().accept()
