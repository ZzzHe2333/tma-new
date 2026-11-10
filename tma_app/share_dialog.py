"""Pastel sharing dialogs; snapshots are rendered once on the GUI thread."""
from __future__ import annotations

import queue
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
        from .path_settings import config_path
        self._primary = config_path()
        self._closed = self._ready = self.busy = False
        self._job = None; self._operation = ''
        self.setWindowTitle('分享设置 · ZzzHe TMA Analysis')
        self.setObjectName('SharingSettingsDialog')
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self.resize(620, 390)
        layout = QVBoxLayout(self)
        title = QLabel('配置图片的分享渠道')
        title.setStyleSheet('font-size:18px; color:#765d86; font-weight:bold')
        layout.addWidget(title)
        group = QGroupBox('WebDAV · 保存到云盘')
        form = QFormLayout(group)
        row = QHBoxLayout()
        self.mounts = QComboBox(); row.addWidget(self.mounts, 1)
        self.add_button = QPushButton('＋ 挂载云盘'); self.add_button.clicked.connect(self.add_mount); row.addWidget(self.add_button)
        form.addRow('云盘', row)
        self.folder = QLineEdit(); self.folder.setObjectName('ShareFolder')
        form.addRow('云盘内文件夹', self.folder)
        self.overwrite = QCheckBox('允许覆盖云盘中的同名图片')
        form.addRow('', self.overwrite)
        layout.addWidget(group)
        group = QGroupBox('企业微信 · 群机器人图片')
        form = QFormLayout(group)
        self.webhook = QLineEdit(); self.webhook.setObjectName('ShareWebhook')
        self.webhook.setEchoMode(QLineEdit.EchoMode.Password)
        self.webhook.setPlaceholderText('https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…')
        form.addRow('Webhook', self.webhook)
        self.clear_webhook = QCheckBox('清除已保存的 Webhook'); form.addRow('', self.clear_webhook)
        hint = QLabel('Webhook 按当前 Windows 用户加密保存。保存设置不会发送消息。')
        hint.setWordWrap(True); form.addRow(hint); layout.addWidget(group)
        self.feedback = QLabel(); self.feedback.setWordWrap(True); layout.addWidget(self.feedback)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self._controls = (self.mounts, self.add_button, self.folder, self.overwrite,
                          self.webhook, self.clear_webhook, self.save_button)
        from .sharing_jobs import load_form
        self.start_job('load', load_form, (self._primary,))

    def reload_mounts(self, selected, mounts):
        self.mounts.clear(); self.mounts.addItem('请选择已挂载云盘', '')
        for mount in mounts:
            self.mounts.addItem(mount['name'], mount['id'])
        self.mounts.setCurrentIndex(max(0, self.mounts.findData(selected)))

    def add_mount(self):
        if self.busy or not self._ready or self._closed: return
        from .cloud_dialog import MountDialog
        dialog = MountDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and not self._closed:
            from .sharing_jobs import add_mount
            self._selected_mount = dialog.value['id']
            self.start_job('mount', add_mount, (self._primary, dict(dialog.value)))

    def accept(self):
        if self.busy or not self._ready or self._closed: return
        from .sharing_jobs import save_form
        options = dict(mount_id=self.mounts.currentData(), folder=self.folder.text(),
            overwrite=self.overwrite.isChecked(), webhook=self.webhook.text(),
            clear_webhook=self.clear_webhook.isChecked())
        self.start_job('save', save_form, (self._primary, options))

    def update_controls(self):
        for widget in self._controls:
            widget.setEnabled(self._ready and not self.busy and not self._closed)

    def start_job(self, operation, function, args):
        if self._closed or self.busy: return
        from .service_jobs import ServiceJob
        self.busy = True; self._operation = operation; self.update_controls()
        self.feedback.setText('正在读取配置，可随时关闭。' if operation == 'load' else '正在保存，可随时关闭窗口。')
        self._job = job = ServiceJob(function, args, self)
        job.done.connect(self.job_finished); job.start()

    def job_finished(self, result):
        job = self._job; self._job = None
        if job is not None: job.deleteLater()
        self.busy = False
        if self._closed: return
        if 'error' in result:
            self.feedback.setText(result['error']); self.update_controls(); return
        if self._operation == 'load':
            config, mounts = result['value']['sharing'], result['value']['cloud']['mounts']
            self.reload_mounts(config['mount_id'], mounts)
            self.folder.setText(config['folder']); self.overwrite.setChecked(config['overwrite'])
            self.webhook.setPlaceholderText('已配置，留空保留' if config['webhook'] else 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…')
            self._ready = True; self.feedback.clear()
        elif self._operation == 'mount':
            self.reload_mounts(self._selected_mount, result['value']['mounts'])
            self.feedback.setText('云盘已保存。')
        else:
            self.shutdown_sharing(); super().accept(); return
        self.update_controls()

    def shutdown_sharing(self):
        self._closed = True
        if self._job is not None:
            self._job.cancel(); self._job.deleteLater(); self._job = None
        self.busy = False; self.update_controls()

    def reject(self):
        self.shutdown_sharing(); super().reject()

    def closeEvent(self, event):
        self.shutdown_sharing(); super().closeEvent(event)


class ShareDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.busy = False; self.events = queue.Queue(); self.png = b''
        self.preparing = False; self._closed = False
        self._configuration_ready = False
        self._configuration_job = self._preparation_job = None
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
        self.dav.setEnabled(False); self.wecom.setEnabled(False)
        self.feedback = QPlainTextEdit(); self.feedback.setReadOnly(True); self.feedback.setMaximumHeight(90)
        self.feedback.setPlaceholderText('选择渠道后点击分享；每次点击仅发送一次。'); layout.addWidget(self.feedback)
        row = QHBoxLayout(); row.addStretch()
        self.send_button = QPushButton('分享图片'); self.send_button.setObjectName('primary')
        self.send_button.setEnabled(False); self.send_button.clicked.connect(self.send); row.addWidget(self.send_button)
        self.close_button = QPushButton('关闭'); self.close_button.clicked.connect(self.close); row.addWidget(self.close_button)
        layout.addLayout(row)
        self.timer = QTimer(self); self.timer.setInterval(40); self.timer.timeout.connect(self.drain)
        self.refresh_configuration()
        # Finish painting the dialog before the existing export renderer runs.
        QTimer.singleShot(0, self.capture)

    @Slot()
    def capture(self):
        if not self.isVisible(): return
        try:
            self.owner.touch_cloud_usage()
            self.png = self.owner.plot_png() or b''
            if not self.png: raise ValueError('图片生成失败')
            self.pixmap = QPixmap(); self.pixmap.loadFromData(self.png)
            self.update_preview()
            self.update_controls()
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

    def update_controls(self):
        active = not self._closed and not self.busy and not self.preparing
        self.send_button.setEnabled(active and self._configuration_ready and bool(self.png))
        self.settings_button.setEnabled(active)
        self.filename.setEnabled(active)
        self.dav.setEnabled(active and self._configuration_ready)
        self.wecom.setEnabled(active and self._configuration_ready)

    def refresh_configuration(self):
        from .path_settings import config_path
        from .service_jobs import ServiceJob
        from .sharing_jobs import load_configuration
        if self._closed: return
        previous = self._configuration_job
        if previous is not None: previous.cancel(); previous.deleteLater()
        self._configuration_ready = False; self.update_controls()
        self.feedback.setPlaceholderText('正在读取分享配置，可随时关闭。')
        job = self._configuration_job = ServiceJob(load_configuration, (config_path(),), self)
        job.done.connect(self.configuration_loaded); job.start()

    def configuration_loaded(self, result):
        job = self._configuration_job; self._configuration_job = None
        if job is not None: job.deleteLater()
        if self._closed or self.owner._closing: return
        if 'error' in result:
            self.feedback.appendPlainText('分享配置未能读取：' + result['error'])
        else:
            config = result['value']
            self.dav.setChecked(bool(config['mount_id'])); self.wecom.setChecked(bool(config['webhook']))
            self._configuration_ready = True
            self.feedback.setPlaceholderText('选择渠道后点击分享；每次点击仅发送一次。')
        self.update_controls()

    def resizeEvent(self, event):
        super().resizeEvent(event); self.update_preview()

    def configure(self):
        try:
            dialog = SharingSettingsDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.refresh_configuration()
        except (ValueError, OSError) as exc:
            self.feedback.appendPlainText(str(exc))

    @Slot()
    def send(self):
        if self.busy or self.preparing or self._closed or not self.png or not self._configuration_ready: return
        try:
            name = self.filename.text().strip()
            if not name or name in ('.', '..') or any(c in name for c in '<>:"/\\|?*') or any(ord(c) < 32 for c in name) or name.endswith(('.', ' ')):
                raise ValueError('请填写有效的图片文件名，不包含路径')
            if not name.lower().endswith('.png'): name += '.png'
            self.filename.setText(name)
            if not self.dav.isChecked() and not self.wecom.isChecked(): raise ValueError('请选择至少一个分享渠道')
        except (ValueError, OSError) as exc:
            self.feedback.appendPlainText(str(exc)); return
        from .path_settings import config_path
        from .service_jobs import ServiceJob
        from .sharing_jobs import prepare_targets
        self.busy = True; self.preparing = True; self.update_controls()
        self.feedback.clear(); self.feedback.appendPlainText('正在准备分享配置…')
        self._pending_name = name
        job = self._preparation_job = ServiceJob(prepare_targets,
            (config_path(), self.dav.isChecked(), self.wecom.isChecked()), self)
        job.done.connect(self.prepared); job.start()

    def prepared(self, result):
        job = self._preparation_job; self._preparation_job = None
        if job is not None: job.deleteLater()
        self.preparing = False
        if self._closed or self.owner._closing: return
        if 'error' in result:
            self.busy = False
            self.feedback.appendPlainText(result['error']); self.update_controls(); return
        self.busy = True; self._achievement_shared = False; self.update_controls()
        self.feedback.clear(); self.feedback.appendPlainText('正在分享，请稍候…')
        self.worker_thread = threading.Thread(target=sharing.share_job, args=(self.png, self._pending_name, result['value'], self.events),
                                              name='TMA-share', daemon=True)
        self.timer.start()
        try: self.worker_thread.start()
        except RuntimeError:
            self.busy = False; self.timer.stop(); self.update_controls()
            self.feedback.appendPlainText('分享后台任务未能启动，请稍后重试。')

    @Slot()
    def drain(self):
        while True:
            try: value = self.events.get_nowait()
            except queue.Empty: return
            if value is None:
                self.busy = False; self.timer.stop()
                self.update_controls()
                return
            channel = 'WebDAV' if value['channel'] == 'webdav' else '企业微信'
            if value['ok'] and not getattr(self, '_achievement_shared', False):
                from .achievement_ui import record
                record(self.owner, 'shares'); self._achievement_shared = True
            self.feedback.appendPlainText(f"{'成功' if value['ok'] else '失败'} · {channel}：{value['message']}")

    def reject(self):
        if self.busy and not self.preparing:
            self.feedback.appendPlainText('正在发送图片，请等待本次请求完成后关闭。'); return
        self.shutdown_sharing(); super().reject()

    def shutdown_sharing(self):
        self._closed = True; self.preparing = self.busy = False
        for name in ('_configuration_job', '_preparation_job'):
            job = getattr(self, name)
            if job is not None: job.cancel(); job.deleteLater(); setattr(self, name, None)
        self.timer.stop(); self.update_controls()

    def closeEvent(self, event):
        if self.busy and not self.preparing:
            self.feedback.appendPlainText('正在发送图片，请等待本次请求完成后关闭。'); event.ignore()
        else:
            self.shutdown_sharing(); event.accept()
