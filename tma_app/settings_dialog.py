"""Local named paths and read-only weighing-sheet lookup settings."""
import math
import os
import queue
import threading
from PySide6.QtCore import Qt, QTimer, Slot,QSignalBlocker
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QFileDialog, QDialogButtonBox, QCheckBox, QDoubleSpinBox, QComboBox)
from . import path_settings as settings


class SettingsDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner); self.owner = owner
        self.mass_job = None; self.tested_mass = None; self.test_request = None
        self.io_events=queue.Queue();self.saving=False;self._edited=False;self._loading=True
        cached=settings.cached_settings();initial=cached[1] if cached is not None else {}
        try:settings.validate_dialog_settings(initial)
        except ValueError:cached=None;initial={}
        self.setWindowTitle("设置 · 数据路径"); self.setObjectName("PathSettingsDialog"); self.resize(760, 390)
        layout = QVBoxLayout(self)
        self.location = QLabel(f"配置文件：{cached[0] if cached and cached[0] else settings.config_path()}"); self.location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.location.setWordWrap(True); layout.addWidget(self.location)
        hint = QLabel("默认打开文件夹：每次启动后首次从这里选文件；之后沿用本次最近选定文件所在目录，重启再回到默认目录。\nm：选择称量表或其所在文件夹，支持 CSV、XLSX、XLS。优先识别样品名与重量表头；无表头时读取 B 列名称、C 列重量。")
        hint.setWordWrap(True); layout.addWidget(hint)
        from .ui_size import PRESETS
        size_row = QHBoxLayout(); size_row.addWidget(QLabel('字体与界面大小'))
        self.ui_size = QComboBox(); self.ui_size.setObjectName('UiSizePreset')
        for key, label, _ in PRESETS: self.ui_size.addItem(label, key)
        controller=getattr(owner,'_ui_size_controller',None)
        self.ui_size.setCurrentIndex(self.ui_size.findData(controller.selected if controller is not None else 'standard')); size_row.addWidget(self.ui_size)
        self.original_ui_size = self.ui_size.currentData()
        size_row.addWidget(QLabel('字体、图标、预览整体放大，重启后生效'), 1); layout.addLayout(size_row)
        self.batch_popup = QCheckBox("批量导入后自动弹出结果窗口（关闭后仍会后台计算，可从文件菜单查看）")
        self.batch_popup.setObjectName("BatchPopupSetting")
        self.batch_popup.setChecked(initial.get('ui',{}).get('batch_popup',True) is not False); layout.addWidget(self.batch_popup)
        cache_row = QHBoxLayout(); cache_row.addWidget(QLabel('m 缓存有效期'))
        self.cache_hours = QDoubleSpinBox(); self.cache_hours.setRange(1, 720); self.cache_hours.setSuffix(' 小时')
        hours=initial.get('mass_cache',{}).get('refresh_hours',24)
        self.cache_hours.setValue(hours if type(hours) in (int,float) and math.isfinite(hours) and 1<=hours<=720 else 24); cache_row.addWidget(self.cache_hours)
        cache_row.addWidget(QLabel('优先复用，重启后保留'), 1)
        self.refresh_button = QPushButton('强制刷新 m'); self.refresh_button.clicked.connect(lambda: self.test_mass(force=True))
        cache_row.addWidget(self.refresh_button); layout.addLayout(cache_row)
        self.paths = QTableWidget(0, 2); self.paths.setHorizontalHeaderLabels(["路径名称", "文件或文件夹路径"])
        self.paths.setColumnWidth(0, 140); self.paths.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.paths)
        self.original_paths = dict(initial.get('paths',{'m':''}))
        if "默认打开文件夹" in self.original_paths:
            legacy = self.original_paths.pop("默认打开文件夹")
            self.original_paths.setdefault("open_folder", legacy)
        for name, path in {"m": "", "open_folder": "", "particle_folder": "", **self.original_paths}.items(): self.add_row(name, path)
        row = QHBoxLayout()
        self.form_buttons=[]
        for caption, callback in (("选择文件…", self.choose_file), ("云盘文件…", self.choose_cloud_file), ("选择文件夹…", self.choose_folder), ("新增路径", self.add_path), ("删除路径", self.remove_path), ("测试 m 匹配", self.test_mass)):
            button = QPushButton(caption); button.clicked.connect(callback); row.addWidget(button)
            self.form_buttons.append(button)
            if caption == "测试 m 匹配": self.test_button = button
        layout.addLayout(row)
        self.feedback = QLabel(); self.feedback.setWordWrap(True); self.feedback.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); layout.addWidget(self.feedback)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.save_button=buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setEnabled(cached is not None)
        self.paths.setCurrentCell(0, 1)
        self.paths.itemChanged.connect(self.path_changed)
        self.paths.itemChanged.connect(self.mark_edited)
        self.batch_popup.toggled.connect(self.mark_edited);self.ui_size.currentIndexChanged.connect(self.mark_edited);self.cache_hours.valueChanged.connect(self.mark_edited)
        self.slow_timer = QTimer(self); self.slow_timer.setSingleShot(True)
        self.slow_timer.timeout.connect(lambda: self.feedback.setText("m 数据源响应较慢，仍在后台读取；可以继续保存设置或关闭窗口。"))
        self.io_timer=QTimer(self);self.io_timer.setInterval(30);self.io_timer.timeout.connect(self.drain_io)
        self.io_timer.start()
        self.set_form_enabled(cached is not None)
        if cached is None:self.feedback.setText('正在后台读取设置，可以随时关闭窗口。')
        from .settings_jobs import load
        threading.Thread(target=load,args=(settings.config_path(),self.io_events),name='TMA-settings-load',daemon=True).start()

    def mark_edited(self,*_):self._edited=True

    def set_form_enabled(self,enabled):
        for widget in [self.paths,self.batch_popup,self.cache_hours,self.ui_size,self.refresh_button,*self.form_buttons]:widget.setEnabled(enabled)
        if enabled and self.mass_job is not None:
            self.test_button.setEnabled(False);self.refresh_button.setEnabled(False)

    def drain_io(self):
        for _ in range(8):
            try:message=self.io_events.get_nowait()
            except queue.Empty:return
            kind=message[0]
            if kind=='loaded':
                self._loading=False
                if not self._edited and not self.saving and self.test_request is None:
                    location,data,size=message[1:]
                    paths=data.get('paths',{'m':''})
                    if not isinstance(paths,dict):self.feedback.setText('路径配置格式无效');continue
                    with QSignalBlocker(self.paths),QSignalBlocker(self.batch_popup),QSignalBlocker(self.ui_size),QSignalBlocker(self.cache_hours):
                        self.original_paths={'m':'',**paths}
                        legacy=self.original_paths.pop('默认打开文件夹',None)
                        if legacy is not None:self.original_paths.setdefault('open_folder',legacy)
                        self.paths.setRowCount(0)
                        for name,path in {'m':'','open_folder':'','particle_folder':'',**self.original_paths}.items():self.add_row(name,path)
                        self.paths.setCurrentCell(0,1)
                        self.batch_popup.setChecked(data.get('ui',{}).get('batch_popup',True) is not False)
                        hours=data.get('mass_cache',{}).get('refresh_hours',24)
                        self.cache_hours.setValue(hours if type(hours) in (int,float) and math.isfinite(hours) and 1<=hours<=720 else 24)
                        self.ui_size.setCurrentIndex(self.ui_size.findData(size));self.original_ui_size=self.ui_size.currentData()
                    self.location.setText(f'配置文件：{location or settings.config_path()}');self.feedback.clear()
                self.save_button.setEnabled(not self.saving)
                if not self.saving:self.set_form_enabled(True)
            elif kind=='load_error':
                self._loading=False;self.feedback.setText('设置未能刷新：'+message[1])
            elif kind=='save_error':
                self.saving=False;self.save_button.setEnabled(True);self.set_form_enabled(True);self.feedback.setText(message[1])
            elif kind=='saved':
                self.saving=False;self.finish_saved(message[1],message[2])

    def add_row(self, name, path):
        index = self.paths.rowCount(); self.paths.insertRow(index)
        item = QTableWidgetItem({"open_folder": "默认打开文件夹", "particle_folder": "粒径默认文件夹"}.get(name, name))
        if name in ("m", "open_folder", "particle_folder"):
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setData(Qt.ItemDataRole.UserRole, name)
        self.paths.setItem(index, 0, item); self.paths.setItem(index, 1, QTableWidgetItem(path))

    def choose_cloud_file(self):
        index = max(0, self.paths.currentRow())
        if self.paths.item(index, 0).data(Qt.ItemDataRole.UserRole) in ("open_folder", "particle_folder"):
            self.feedback.setText("默认打开目录用于本地文件选择；云文件请在云盘窗口浏览。")
            return
        self.owner.show_cloud(selected_callback=lambda path: self.paths.item(index, 1).setText(path))

    def add_path(self):
        self.add_row("", ""); self.paths.setCurrentCell(self.paths.rowCount()-1, 0)

    def remove_path(self):
        index = self.paths.currentRow()
        if index < 0 or self.paths.item(index, 0).data(Qt.ItemDataRole.UserRole) in ("m", "open_folder", "particle_folder"):
            self.feedback.setText("此项保留，清空路径即可停用。")
        else: self.paths.removeRow(index)

    def choose_file(self):
        index = max(0, self.paths.currentRow())
        if self.paths.item(index, 0).data(Qt.ItemDataRole.UserRole) in ("open_folder", "particle_folder"):
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

    def stop_mass_test(self):
        self.slow_timer.stop()
        if self.mass_job is not None:
            self.mass_job.cancel(); self.mass_job.deleteLater(); self.mass_job = None
        self.test_button.setEnabled(True)
        self.refresh_button.setEnabled(True)

    def path_changed(self, item):
        if self.test_request is None: return
        try: changed = self.values().get('m', '') != self.test_request[1]
        except ValueError: changed = True
        if changed:
            self.stop_mass_test(); self.tested_mass = None; self.test_request = None
            self.feedback.setText("m 路径已修改，请重新测试；可以直接保存，样品重量将在后台刷新。")

    def test_mass(self, *, force=False):
        from .mass_jobs import MassLookupJob
        curve = self.owner.selected()
        if curve is None: self.feedback.setText("请先导入一个样品，再测试 m 匹配。"); return
        try: source = self.values()["m"]
        except ValueError as exc: self.feedback.setText(str(exc)); return
        if self.mass_job is not None: return
        self.test_request = (curve.sample_name, source); self.tested_mass = None
        self.mass_job = MassLookupJob([('test', curve.sample_name)], source, self, force=force)
        self.mass_job.row_ready.connect(self.mass_test_ready)
        self.mass_job.finished.connect(self.mass_test_finished)
        self.test_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.feedback.setText(f"样品：{curve.sample_name}\n正在后台测试 m 匹配，可以继续编辑或保存设置…")
        self.slow_timer.start(10000); self.mass_job.start()

    @Slot(str, object)
    def mass_test_ready(self, key, result):
        if self.sender() is not self.mass_job or self.test_request is None: return
        sample, source = self.test_request
        try:
            if self.values()['m'] != source: return
        except ValueError: return
        self.tested_mass = (sample, source, result)
        self.feedback.setText(f"样品：{sample}\n" + (f"m = {result.value:g} {result.unit}\n来源：{result.source}" if result.value is not None else result.message))
        if result.value is not None and '暂不可用' in result.message:
            self.feedback.setText(self.feedback.text()+'\n'+result.message)

    @Slot()
    def mass_test_finished(self):
        if self.sender() is not self.mass_job: return
        error=self.mass_job.error_message
        self.stop_mass_test()
        if error:self.feedback.setText(error)

    def accept(self):
        if self.saving or not self.save_button.isEnabled():return
        try:
            paths = self.values()
        except (ValueError, OSError) as exc: self.feedback.setText(str(exc)); return
        self.stop_mass_test();self.saving=True;self.save_button.setEnabled(False);self.set_form_enabled(False)
        self.feedback.setText('正在后台保存设置…')
        from .settings_jobs import save
        threading.Thread(target=save,args=(paths,self.batch_popup.isChecked(),self.cache_hours.value(),self.io_events),name='TMA-settings-save',daemon=True).start()

    def finish_saved(self,saved,paths):
        self.io_timer.stop()
        tested = self.tested_mass
        self.stop_mass_test()
        if paths.get('m', '') != self.original_paths.get('m', '') or tested is not None:
            source = os.environ.get('TMA_MASS_XLSX', paths.get('m', '')).strip()
            seed = {tested[0]: tested[2]} if tested is not None and tested[1] == source else None
            self.owner.refresh_mass_lookup(initial_matches=seed, source_hint=source)
        else: self.owner.statusBar().showMessage(f"路径设置已保存：{saved}")
        if self.ui_size.currentData() != self.original_ui_size:
            from .ui_size import change_from_menu
            change_from_menu(self.owner, self.ui_size.currentData())
        super().accept()

    def reject(self):
        self.stop_mass_test();self.io_timer.stop(); super().reject()

    def closeEvent(self, event):
        self.stop_mass_test();self.io_timer.stop(); super().closeEvent(event)
