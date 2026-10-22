"""Nonmodal WebDAV browser; networking and cleanup always run off the GUI."""
from pathlib import Path, PurePosixPath
import threading
import uuid

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QApplication, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem,
    QVBoxLayout)

from . import cloud_storage as cloud


class CloudJob(QObject):
    done = Signal(object)
    progress = Signal(str)

    def __init__(self, function):
        super().__init__(); self.function = function; self.cancelled = threading.Event()

    def notify(self, text):
        try: self.progress.emit(text)
        except RuntimeError: self.cancelled.set()

    def start(self):
        self.thread = threading.Thread(target=self.run, name="TMA-WebDAV", daemon=True)
        self.thread.start()

    def run(self):
        try: value = {"value": self.function(self)}
        except Exception as exc: value = {"error": str(exc)}
        try: self.done.emit(value)
        except RuntimeError: pass


class MountDialog(QDialog):
    def __init__(self, owner, mount=None):
        super().__init__(owner)
        self.mount = mount or {"id": uuid.uuid4().hex, "name": "", "url": "", "username": "", "password": "", "verify_tls": True}
        self.setWindowTitle("WebDAV 云盘")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self.resize(520, 300)
        layout = QVBoxLayout(self); form = QFormLayout()
        self.name = QLineEdit(self.mount["name"])
        self.url = QLineEdit(self.mount["url"]); self.url.setPlaceholderText("https://网盘地址/dav/")
        self.username = QLineEdit(self.mount.get("username", ""))
        self.password = QLineEdit(); self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("已有密码留空表示保留；无密码连接可留空")
        self.clear_password = QCheckBox("清除已保存的密码")
        self.verify = QCheckBox("验证 HTTPS 证书"); self.verify.setChecked(self.mount.get("verify_tls", True))
        for label, widget in (("名称", self.name), ("WebDAV 地址", self.url), ("账号", self.username), ("密码 / 应用密码", self.password)):
            form.addRow(label, widget)
        form.addRow("", self.clear_password); form.addRow("", self.verify)
        layout.addLayout(form)
        hint = QLabel("使用网盘提供的 WebDAV 地址及应用密码。密码按当前 Windows 用户加密保存。")
        hint.setWordWrap(True); layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        try:
            password = self.mount.get("password", "")
            if self.clear_password.isChecked(): password = ""
            if self.password.text(): password = cloud.protect_password(self.password.text())
            value = {"id": self.mount["id"], "name": self.name.text().strip(), "url": cloud.normalize_url(self.url.text()),
                     "username": self.username.text().strip(), "password": password, "verify_tls": self.verify.isChecked()}
            cloud.validate_mount(value)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "云盘配置", str(exc)); return
        self.value = value
        super().accept()


class CloudDialog(QDialog):
    def __init__(self, owner, *, target="import", selected_callback=None):
        super().__init__(owner)
        self.owner = owner; self.target = target; self.selected_callback = selected_callback
        self.job = None; self.directory = "/"; self.entries = []
        self.setWindowTitle("云盘 · WebDAV")
        self.setObjectName("CloudDialog")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self.resize(880, 620)
        layout = QVBoxLayout(self)
        title = QLabel("云端文件，随用随取")
        title.setStyleSheet("font-size:18px;color:#765d86;font-weight:bold")
        layout.addWidget(title)
        hint = QLabel("打开前下载至本地缓存 · 再次使用自动续期 · 每日只清理过期缓存，保留云端原文件")
        hint.setWordWrap(True); layout.addWidget(hint)
        mounts = QHBoxLayout()
        self.mounts = QComboBox(); self.mounts.setMinimumWidth(250)
        self.mounts.currentIndexChanged.connect(self.mount_changed); mounts.addWidget(self.mounts, 1)
        self.controls = []
        for label, callback in (("＋ 挂载", self.add_mount), ("编辑", self.edit_mount), ("移除挂载", self.remove_mount)):
            button = QPushButton(label); button.clicked.connect(callback); mounts.addWidget(button); self.controls.append(button)
        layout.addLayout(mounts)
        navigation = QHBoxLayout()
        up = QPushButton("上一级"); up.clicked.connect(self.go_up); navigation.addWidget(up); self.controls.append(up)
        self.path = QLineEdit("/"); self.path.returnPressed.connect(self.browse); navigation.addWidget(self.path, 1)
        refresh = QPushButton("连接 / 刷新"); refresh.clicked.connect(self.browse); navigation.addWidget(refresh); self.controls.append(refresh)
        layout.addLayout(navigation)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["名称", "大小", "修改时间"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 95); self.table.setColumnWidth(2, 250)
        self.table.cellDoubleClicked.connect(self.open_entry)
        layout.addWidget(self.table, 1)
        cache = QHBoxLayout()
        cache.addWidget(QLabel("本地保留"))
        self.hours = QDoubleSpinBox(); self.hours.setRange(1, 87600); self.hours.setDecimals(1); self.hours.setSuffix(" 小时")
        self.hours.setObjectName("CloudRetentionHours")
        cache.addWidget(self.hours)
        save = QPushButton("保存时长"); save.clicked.connect(self.save_retention); cache.addWidget(save); self.controls.append(save)
        clean = QPushButton("清理已过期缓存"); clean.clicked.connect(self.clean); cache.addWidget(clean); self.controls.append(clean)
        cache.addStretch(); layout.addLayout(cache)
        self.stats = QLabel(); self.stats.setWordWrap(True)
        self.stats.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.stats)
        self.feedback = QLabel("先挂载云盘，再连接查看文件。默认保留 72 小时（3 天）。")
        self.feedback.setWordWrap(True); self.feedback.setObjectName("CloudFeedback"); layout.addWidget(self.feedback)
        bottom = QHBoxLayout()
        self.schedule_status = QLabel(); self.schedule_status.setWordWrap(True); bottom.addWidget(self.schedule_status, 1)
        copy = QPushButton("复制云文件地址"); copy.clicked.connect(self.copy_uri); bottom.addWidget(copy); self.controls.append(copy)
        self.open_button = QPushButton("下载并打开" if selected_callback is None else "下载并选用")
        self.open_button.setObjectName("primary"); self.open_button.clicked.connect(self.download)
        bottom.addWidget(self.open_button); self.controls.append(self.open_button)
        close = QPushButton("关闭"); close.clicked.connect(self.close); bottom.addWidget(close)
        layout.addLayout(bottom)
        self.reload()

    def reload(self, selected=None):
        try: value = cloud.settings()
        except (ValueError, OSError) as exc:
            self.feedback.setText(str(exc)); return
        self.profiles = value["mounts"]; self.hours.setValue(value["retention_hours"])
        self.mounts.blockSignals(True); self.mounts.clear()
        for profile in self.profiles: self.mounts.addItem(profile["name"], profile["id"])
        if selected: self.mounts.setCurrentIndex(max(0, self.mounts.findData(selected)))
        self.mounts.blockSignals(False)
        self.mount_changed()
        self.update_stats()

    def update_stats(self):
        try:
            info = cloud.cache_stats()
            self.stats.setText(f"缓存 {info['files']} 个文件 · {info['bytes']/1024/1024:.1f} MB · {cloud.cache_root()}")
        except (ValueError, OSError) as exc: self.stats.setText(str(exc))

    def mount_changed(self, *_):
        self.directory = "/"; self.path.setText("/"); self.entries = []; self.table.setRowCount(0)

    def profile(self):
        identifier = self.mounts.currentData()
        return next((p for p in self.profiles if p["id"] == identifier), None)

    def persist(self, profiles):
        cloud.save_settings(profiles, self.hours.value())
        self.reload(self.mounts.currentData())
        self.owner.ensure_cloud_schedule()

    def add_mount(self):
        dialog = MountDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.persist([*self.profiles, dialog.value]); self.mounts.setCurrentIndex(self.mounts.findData(dialog.value["id"]))
                self.feedback.setText("挂载已保存，点击「连接 / 刷新」查看文件。")
            except (ValueError, OSError) as exc: self.feedback.setText(str(exc))

    def edit_mount(self):
        profile = self.profile()
        if profile is None: return
        dialog = MountDialog(self, profile)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try: self.persist([dialog.value if p["id"] == profile["id"] else p for p in self.profiles])
            except (ValueError, OSError) as exc: self.feedback.setText(str(exc))

    def remove_mount(self):
        profile = self.profile()
        if profile:
            try:
                self.persist([p for p in self.profiles if p["id"] != profile["id"]])
                self.feedback.setText("挂载已移除。现有本地缓存继续按保留时长自动清理。")
            except (ValueError, OSError) as exc: self.feedback.setText(str(exc))

    def save_retention(self):
        try:
            cloud.save_settings(cloud.settings()["mounts"], self.hours.value()); self.owner.ensure_cloud_schedule()
            self.feedback.setText(f"已保存：距离上次打开或使用超过 {self.hours.value():g} 小时后，在每日清理时删除本地缓存。")
        except (ValueError, OSError) as exc: self.feedback.setText(str(exc))

    def run(self, function, callback):
        if self.job: return
        self.job = job = CloudJob(function)
        self.set_busy(True)
        job.progress.connect(self.feedback.setText)
        job.done.connect(lambda value: self.finished(value, callback))
        job.start()

    def finished(self, value, callback):
        cancelled = self.job.cancelled.is_set() if self.job else True
        self.job = None; self.set_busy(False)
        if cancelled: return
        if "error" in value: self.feedback.setText(value["error"])
        else: callback(value["value"])
        self.update_stats()

    def set_busy(self, busy):
        for control in [self.mounts, self.path, self.hours, self.table, *self.controls]: control.setEnabled(not busy)

    def browse(self):
        profile = self.profile()
        if profile is None:
            self.feedback.setText("请先挂载一个 WebDAV 云盘。"); return
        try: directory = cloud.remote_path(self.path.text())
        except ValueError as exc: self.feedback.setText(str(exc)); return
        self.feedback.setText("正在连接 WebDAV…")
        self.run(lambda job: (directory, cloud.WebDAV(profile).list(directory)), self.listed)

    def listed(self, value):
        self.directory, self.entries = value; self.path.setText(self.directory)
        self.table.setRowCount(len(self.entries))
        for i, entry in enumerate(self.entries):
            for j, text in enumerate(("▸ " + entry["name"] if entry["directory"] else entry["name"],
                    "文件夹" if entry["directory"] else f"{entry['size']/1024:.1f} KB" if entry["size"] is not None else "", entry["modified"])):
                self.table.setItem(i, j, QTableWidgetItem(text))
        self.feedback.setText(f"已连接 · {len(self.entries)} 项，双击文件夹进入；可多选文件下载。")

    def go_up(self):
        self.path.setText(str(PurePosixPath(self.directory).parent)); self.browse()

    def open_entry(self, row, _):
        entry = self.entries[row]
        if entry["directory"]:
            self.path.setText(entry["path"]); self.browse()
        else: self.download()

    def download(self):
        selected = [self.entries[i] for i in sorted({index.row() for index in self.table.selectedIndexes()}) if not self.entries[i]["directory"]]
        if not selected:
            self.feedback.setText("请选择要打开的文件，可按 Ctrl 多选。"); return
        if self.selected_callback and len(selected) != 1:
            self.feedback.setText("此处请选择一个文件。"); return
        if not self.selected_callback and any(not Path(entry["name"]).suffix[1:].isdigit() and Path(entry["name"]).suffix.lower() not in (".txt", ".tai", ".csv") for entry in selected):
            self.feedback.setText("绘图导入请选择 .001 等 TMA 数据文件；其他文件可从报告窗口选用。"); return
        identifier = self.mounts.currentData()
        def work(job):
            paths, errors = [], []
            for entry in selected:
                if job.cancelled.is_set(): break
                try: paths.append(str(cloud.fetch(identifier, entry["path"], refresh=True, cancelled=job.cancelled, progress=job.notify)))
                except Exception as exc: errors.append(entry["name"] + "：" + str(exc))
            return paths, errors
        self.run(work, self.downloaded)

    def copy_uri(self):
        selected = [self.entries[i]["uri"] for i in sorted({index.row() for index in self.table.selectedIndexes()}) if not self.entries[i]["directory"]]
        if selected:
            QApplication.clipboard().setText("\n".join(selected))
            self.feedback.setText("已复制 cloud:// 地址，可用于 MCP 文件参数或 m 称量表路径。")

    def downloaded(self, value):
        paths, errors = value
        if paths:
            if self.selected_callback: self.selected_callback(paths[0]); self.close()
            elif self.target == "batch": self.owner.show_batch_analysis(paths)
            else: self.owner.import_files(paths)
        self.feedback.setText(f"已下载并选用 {len(paths)} 个文件。" + ("\n" + "\n".join(errors) if errors else ""))

    def clean(self):
        self.feedback.setText("正在清理超过保存时长的本地缓存…")
        self.run(lambda job: cloud.cleanup(force=True), lambda result: self.feedback.setText(
            f"清理完成：删除 {result['deleted']} 个文件，释放 {result['bytes']/1024/1024:.1f} MB。" + (" 部分文件未删除：" + "；".join(result["errors"]) if result["errors"] else "")))

    def closeEvent(self, event):
        if self.job: self.job.cancelled.set()
        event.accept()
