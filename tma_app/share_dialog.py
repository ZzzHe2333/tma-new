"""Pastel sharing dialogs; snapshots are rendered once on the GUI thread."""
from __future__ import annotations

from pathlib import Path
import queue
import tempfile
import threading

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QPlainTextEdit, QVBoxLayout)

from . import cloud_storage as cloud
from . import sharing


class SharingSettingsDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.setWindowTitle('分享设置 · ZzzHe TMA Analysis')
        self.setObjectName('SharingSettingsDialog')
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self.resize(620, 390)
        layout = QVBoxLayout(self)
        title = QLabel('配置图片的分享渠道')
        title.setStyleSheet('font-size:18px; color:#765d86; font-weight:bold')
        layout.addWidget(title)
        config = sharing.settings()
        group = QGroupBox('WebDAV · 保存到云盘')
        form = QFormLayout(group)
        row = QHBoxLayout()
        self.mounts = QComboBox(); row.addWidget(self.mounts, 1)
        add = QPushButton('＋ 挂载云盘'); add.clicked.connect(self.add_mount); row.addWidget(add)
        form.addRow('云盘', row)
        self.folder = QLineEdit(config['folder']); self.folder.setObjectName('ShareFolder')
        form.addRow('云盘内文件夹', self.folder)
        self.overwrite = QCheckBox('允许覆盖云盘中的同名图片')
        self.overwrite.setChecked(config['overwrite']); form.addRow('', self.overwrite)
        layout.addWidget(group)
        group = QGroupBox('企业微信 · 群机器人图片')
        form = QFormLayout(group)
        self.webhook = QLineEdit(); self.webhook.setObjectName('ShareWebhook')
        self.webhook.setEchoMode(QLineEdit.EchoMode.Password)
        self.webhook.setPlaceholderText('已配置，留空保留' if config['webhook'] else 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…')
        form.addRow('Webhook', self.webhook)
        self.clear_webhook = QCheckBox('清除已保存的 Webhook'); form.addRow('', self.clear_webhook)
        hint = QLabel('Webhook 按当前 Windows 用户加密保存。保存设置不会发送消息。')
        hint.setWordWrap(True); form.addRow(hint); layout.addWidget(group)
        self.feedback = QLabel(); self.feedback.setWordWrap(True); layout.addWidget(self.feedback)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.reload_mounts(config['mount_id'])

    def reload_mounts(self, selected):
        self.mounts.clear(); self.mounts.addItem('请选择已挂载云盘', '')
        for mount in cloud.settings()['mounts']:
            self.mounts.addItem(mount['name'], mount['id'])
        self.mounts.setCurrentIndex(max(0, self.mounts.findData(selected)))

    def add_mount(self):
        from .cloud_dialog import MountDialog
        dialog = MountDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                config = cloud.settings()
                cloud.save_settings([*config['mounts'], dialog.value], config['retention_hours'])
                self.reload_mounts(dialog.value['id'])
            except (ValueError, OSError) as exc:
                self.feedback.setText(str(exc))

    def accept(self):
        try:
            sharing.save_settings(self.mounts.currentData(), self.folder.text(), self.overwrite.isChecked(),
                                  self.webhook.text(), clear_webhook=self.clear_webhook.isChecked())
        except (ValueError, OSError) as exc:
            self.feedback.setText(str(exc)); return
        super().accept()


class ShareDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.busy = False; self.events = queue.Queue(); self.png = b''
        self.setWindowTitle('分享图片 · ZzzHe TMA Analysis')
        self.setObjectName('ShareDialog')
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self.resize(760, 620)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        title = QLabel('分享当前图像'); title.setStyleSheet('font-size:18px; color:#765d86; font-weight:bold')
        top.addWidget(title); top.addStretch()
        self.settings_button = QPushButton('分享设置…'); self.settings_button.clicked.connect(self.configure)
        top.addWidget(self.settings_button); layout.addLayout(top)
        self.preview = QLabel('正在准备图片…'); self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(320, 260)
        self.preview.setStyleSheet('background:white; border:1px solid #e2d3e9; border-radius:8px')
        layout.addWidget(self.preview, 1)
        self.info = QLabel('图片包含当前曲线、批注、白边和 Power By ZzzHe 信息。')
        self.info.setWordWrap(True); layout.addWidget(self.info)
        row = QHBoxLayout(); row.addWidget(QLabel('图片文件名'))
        self.filename = QLineEdit(owner.default_plot_filename()); self.filename.setObjectName('ShareFilename')
        row.addWidget(self.filename, 1); layout.addLayout(row)
        row = QHBoxLayout(); row.addWidget(QLabel('发送到'))
        self.dav = QCheckBox('WebDAV 云盘'); self.wecom = QCheckBox('企业微信')
        row.addWidget(self.dav); row.addWidget(self.wecom); row.addStretch(); layout.addLayout(row)
        config = sharing.settings()
        self.dav.setChecked(bool(config['mount_id'])); self.wecom.setChecked(bool(config['webhook']))
        self.feedback = QPlainTextEdit(); self.feedback.setReadOnly(True); self.feedback.setMaximumHeight(90)
        self.feedback.setPlaceholderText('选择渠道后点击分享；每次点击仅发送一次。'); layout.addWidget(self.feedback)
        row = QHBoxLayout(); row.addStretch()
        self.send_button = QPushButton('分享图片'); self.send_button.setObjectName('primary')
        self.send_button.setEnabled(False); self.send_button.clicked.connect(self.send); row.addWidget(self.send_button)
        self.close_button = QPushButton('关闭'); self.close_button.clicked.connect(self.close); row.addWidget(self.close_button)
        layout.addLayout(row)
        self.timer = QTimer(self); self.timer.setInterval(40); self.timer.timeout.connect(self.drain)
        # Finish painting the dialog before the existing export renderer runs.
        QTimer.singleShot(0, self.capture)

    @Slot()
    def capture(self):
        if not self.isVisible(): return
        try:
            self.owner.touch_cloud_usage()
            with tempfile.TemporaryDirectory(prefix='ZzzHeTMA-share-') as directory:
                path = Path(directory) / 'image.png'
                self.owner.write_plot(path)
                self.png = path.read_bytes()
            self.pixmap = QPixmap(); self.pixmap.loadFromData(self.png)
            self.update_preview()
            self.send_button.setEnabled(True)
            self.info.setText(f'当前图像快照 · {self.pixmap.width()} × {self.pixmap.height()} · {len(self.png)/1024:.0f} KB · PNG\n'
                              '保留批注与白边。企业微信大图自动缩小；WebDAV 上传原图。')
        except Exception:
            self.preview.setText('图片生成失败')
            self.feedback.appendPlainText('请先关闭此窗口，检查当前图像后重新分享。')

    def update_preview(self):
        if hasattr(self, 'pixmap'):
            ratio = self.preview.devicePixelRatioF()
            preview = self.pixmap.scaled(self.preview.size()*ratio, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation)
            preview.setDevicePixelRatio(ratio); self.preview.setPixmap(preview)

    def resizeEvent(self, event):
        super().resizeEvent(event); self.update_preview()

    def configure(self):
        try:
            dialog = SharingSettingsDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                config = sharing.settings()
                self.dav.setChecked(bool(config['mount_id'])); self.wecom.setChecked(bool(config['webhook']))
        except (ValueError, OSError) as exc:
            self.feedback.appendPlainText(str(exc))

    @Slot()
    def send(self):
        if self.busy or not self.png: return
        try:
            name = self.filename.text().strip()
            if not name or name in ('.', '..') or any(c in name for c in '<>:"/\\|?*') or any(ord(c) < 32 for c in name) or name.endswith(('.', ' ')):
                raise ValueError('请填写有效的图片文件名，不包含路径')
            if not name.lower().endswith('.png'): name += '.png'
            self.filename.setText(name)
            config = sharing.settings(); targets = []
            if self.dav.isChecked():
                targets.append({'channel': 'webdav', 'mount': cloud.get_mount(config['mount_id']),
                                'folder': config['folder'], 'overwrite': config['overwrite']})
            if self.wecom.isChecked():
                if not config['webhook']: raise ValueError('请先在分享设置中填写企业微信 Webhook')
                targets.append({'channel': 'wecom', 'webhook': config['webhook']})
            if not targets: raise ValueError('请选择至少一个分享渠道')
        except (ValueError, OSError) as exc:
            self.feedback.appendPlainText(str(exc)); return
        self.busy = True; self.feedback.clear(); self.feedback.appendPlainText('正在分享，请稍候…')
        for widget in (self.send_button, self.settings_button, self.filename, self.dav, self.wecom):
            widget.setEnabled(False)
        self.worker_thread = threading.Thread(target=sharing.share_job, args=(self.png, name, targets, self.events),
                                              name='TMA-share', daemon=True)
        self.timer.start(); self.worker_thread.start()

    @Slot()
    def drain(self):
        while True:
            try: value = self.events.get_nowait()
            except queue.Empty: return
            if value is None:
                self.busy = False; self.timer.stop()
                for widget in (self.send_button, self.settings_button, self.filename, self.dav, self.wecom):
                    widget.setEnabled(True)
                return
            channel = 'WebDAV' if value['channel'] == 'webdav' else '企业微信'
            self.feedback.appendPlainText(f"{'成功' if value['ok'] else '失败'} · {channel}：{value['message']}")

    def reject(self):
        if self.busy:
            self.feedback.appendPlainText('正在发送图片，请等待本次请求完成后关闭。'); return
        super().reject()

    def closeEvent(self, event):
        if self.busy:
            self.feedback.appendPlainText('正在发送图片，请等待本次请求完成后关闭。'); event.ignore()
        else:
            event.accept()
