"""Notification settings: who to tell, and whether a plot image rides along."""
from __future__ import annotations

import queue
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton,
    QVBoxLayout)

from . import cloud_storage as cloud
from . import notifications


class NotificationSettingsDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.busy = False
        self.events_queue = queue.Queue()
        self.setWindowTitle('通知设置 · ZzzHe TMA Analysis')
        self.setObjectName('NotificationSettingsDialog')
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.resize(660, 620)
        layout = QVBoxLayout(self)
        title = QLabel('有人使用软件时，向指定地址发送通知')
        title.setStyleSheet('font-size:18px; color:#765d86; font-weight:bold')
        layout.addWidget(title)

        config = notifications.settings()
        self.enabled = QCheckBox('启用通知')
        self.enabled.setObjectName('NotificationEnabled')
        self.enabled.setChecked(config['enabled'])
        layout.addWidget(self.enabled)

        group = QGroupBox('推送渠道')
        form = QFormLayout(group)
        self.provider = QComboBox()
        self.provider.setObjectName('NotificationProvider')
        for key, label, _image, _hint in notifications.PROVIDERS:
            self.provider.addItem(label, key)
        self.provider.setCurrentIndex(max(0, self.provider.findData(config['provider'])))
        form.addRow('渠道', self.provider)
        self.target = QLineEdit()
        self.target.setObjectName('NotificationTarget')
        self.target.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow('地址 / 密钥', self.target)
        self.clear_target = QCheckBox('清除已保存的地址')
        form.addRow('', self.clear_target)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        form.addRow(self.hint)
        self.image = QCheckBox('同时发送 TMA 图片（文字与图片分开发送，默认关闭）')
        self.image.setObjectName('NotificationImage')
        self.image.setChecked(config['attach_image'])
        form.addRow('', self.image)
        self.app_id = QLineEdit()
        self.app_id.setObjectName('NotificationAppId')
        self.app_id.setEchoMode(QLineEdit.EchoMode.Password)
        self.app_secret = QLineEdit()
        self.app_secret.setObjectName('NotificationAppSecret')
        self.app_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.app_id_row = QLabel('App ID')
        self.app_secret_row = QLabel('App Secret')
        form.addRow(self.app_id_row, self.app_id)
        form.addRow(self.app_secret_row, self.app_secret)
        self.app_hint = QLabel('飞书发送图片需要自建应用的 App ID 与 App Secret（权限 im:resource）；不填则只发文字。')
        self.app_hint.setWordWrap(True)
        form.addRow(self.app_hint)
        layout.addWidget(group)

        events = QGroupBox('触发时机')
        event_form = QFormLayout(events)
        self.event_startup = QCheckBox('登录软件时')
        self.event_startup.setObjectName('NotificationStartup')
        self.event_startup.setChecked(config['events'].get('startup', True))
        self.event_report = QCheckBox('生成报告时')
        self.event_report.setObjectName('NotificationReport')
        self.event_report.setChecked(config['events'].get('report', True))
        self.event_import = QCheckBox('导入数据时')
        self.event_import.setObjectName('NotificationImport')
        self.event_import.setChecked(config['events'].get('import', True))
        self.event_batch = QCheckBox('批量导入时')
        self.event_batch.setObjectName('NotificationBatchImport')
        self.event_batch.setChecked(config['events'].get('batch_import', True))
        self.event_process = QCheckBox('批量处理时')
        self.event_process.setObjectName('NotificationBatchProcess')
        self.event_process.setChecked(config['events'].get('batch_process', True))
        self.event_copy = QCheckBox('复制到 Excel 时')
        self.event_copy.setObjectName('NotificationCopyExcel')
        self.event_copy.setChecked(config['events'].get('copy_excel', True))
        self.event_plot = QCheckBox('批量出图时')
        self.event_plot.setObjectName('NotificationBatchPlot')
        self.event_plot.setChecked(config['events'].get('batch_plot', True))
        event_form.addRow('', self.event_startup)
        event_form.addRow('', self.event_report)
        event_form.addRow('', self.event_import)
        event_form.addRow('', self.event_batch)
        event_form.addRow('', self.event_process)
        event_form.addRow('', self.event_copy)
        event_form.addRow('', self.event_plot)
        layout.addWidget(events)

        preview = QLabel(
            '登录软件：\n日期：2026-10-27\n时间：11:22:55\n行为：登录软件\n内网：192.168.0.191\n公网：27.152.26.88\n'
            '名字：电脑名\n机器码：123E-45F6-7894-4567\n\n'
            '导入 / 批量导入 / 批量处理 / 复制到excal / 批量出图：行为 + 路径（批量时一行一个）+ 机器码\n'
            '单样品报告：行为 + TMA源 / 粒径源 / 粒径名 / 数据 / 样品报告名字 / 保存路径 + 机器码')
        preview.setStyleSheet('color:#6b5a74; background:#faf6fc; border:1px solid #e6d9ec; border-radius:6px; padding:8px')
        preview.setWordWrap(True)
        layout.addWidget(preview)

        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        self.feedback.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.feedback)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.test_button = QPushButton('测试发送')
        self.test_button.setObjectName('NotificationTest')
        self.test_button.clicked.connect(self.test)
        buttons.addButton(self.test_button, QDialogButtonBox.ButtonRole.ActionRole)

        self._saved_target = bool(config['target'])
        self._saved_app = bool(config['app_id'] and config['app_secret'])
        self.provider.currentIndexChanged.connect(self.refresh_provider)
        self.image.toggled.connect(self.refresh_provider)
        self.refresh_provider()
        self.timer = QTimer(self)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.drain)

    # ------------------------------------------------------------------ helpers

    def current_provider(self):
        return self.provider.currentData()

    def refresh_provider(self, *_):
        provider = self.current_provider()
        self.hint.setText(notifications.provider_hint(provider))
        image_ok = notifications.supports_image(provider)
        self.image.setEnabled(image_ok)
        if not image_ok:
            self.image.setChecked(False)
        self.target.setPlaceholderText('已配置，留空保留' if self._saved_target else notifications.provider_hint(provider))
        feishu_image = provider == 'feishu' and self.image.isChecked()
        for widget in (self.app_id_row, self.app_id, self.app_secret_row, self.app_secret, self.app_hint):
            widget.setVisible(provider == 'feishu')
        self.app_id.setEnabled(feishu_image)
        self.app_secret.setEnabled(feishu_image)
        self.app_id.setPlaceholderText('已配置，留空保留' if self._saved_app else 'cli_…')
        self.app_secret.setPlaceholderText('已配置，留空保留' if self._saved_app else '飞书应用密钥')

    def typed_target(self):
        text = self.target.text().strip()
        if text:
            return text
        if self._saved_target:
            return cloud.protect_password(notifications.settings()['target'], decrypt=True)
        raise ValueError('请填写通知地址或密钥')

    # --------------------------------------------------------------------- test

    @Slot()
    def test(self):
        if self.busy:
            return
        provider = self.current_provider()
        try:
            target = self.typed_target()
        except (ValueError, OSError) as exc:
            self.feedback.setText(str(exc))
            return
        config = notifications.settings()
        png = None
        if self.image.isChecked() and notifications.supports_image(provider):
            png = self.capture_plot()
        app_id = self.app_id.text().strip() or (cloud.protect_password(config['app_id'], decrypt=True) if config['app_id'] else '')
        app_secret = self.app_secret.text().strip() or (cloud.protect_password(config['app_secret'], decrypt=True) if config['app_secret'] else '')
        self.busy = True
        self.test_button.setEnabled(False)
        self.feedback.setText('正在发送测试通知…')
        threading.Thread(target=self._test_worker,
                         args=(provider, target, png, app_id, app_secret),
                         name='TMA-notify-test', daemon=True).start()
        self.timer.start()

    def capture_plot(self):
        try:
            with tempfile.TemporaryDirectory(prefix='ZzzHeTMA-notify-') as directory:
                path = Path(directory) / 'plot.png'
                self.owner.write_plot(path)
                return path.read_bytes()
        except Exception:
            return None

    def _test_worker(self, provider, target, png, app_id, app_secret):
        try:
            text = notifications.send_now(provider, target, '测试通知', '测试批次',
                                          png=png, app_id=app_id, app_secret=app_secret,
                                          plain_target=True)
            self.events_queue.put(('ok', text))
        except (ValueError, OSError) as exc:
            self.events_queue.put(('error', str(exc)))
        except Exception:
            self.events_queue.put(('error', '测试发送失败，请检查配置和网络'))

    @Slot()
    def drain(self):
        while True:
            try:
                kind, message = self.events_queue.get_nowait()
            except queue.Empty:
                return
            self.busy = False
            self.timer.stop()
            self.test_button.setEnabled(True)
            if kind == 'ok':
                self.feedback.setText('测试通知已发送，请到接收端确认。')
            else:
                self.feedback.setText(message)

    # --------------------------------------------------------------------- save

    def accept(self):
        if self.busy:
            self.feedback.setText('正在发送测试通知，请等待完成后保存。')
            return
        if not self.confirm_password():
            return
        provider = self.current_provider()
        try:
            notifications.save_settings(
                provider, self.target.text(),
                enabled=self.enabled.isChecked(),
                attach_image=self.image.isChecked(),
                app_id=self.app_id.text(), app_secret=self.app_secret.text(),
                events={'startup': self.event_startup.isChecked(),
                        'report': self.event_report.isChecked(),
                        'import': self.event_import.isChecked(),
                        'batch_import': self.event_batch.isChecked(),
                        'batch_process': self.event_process.isChecked(),
                        'copy_excel': self.event_copy.isChecked(),
                        'batch_plot': self.event_plot.isChecked()},
                clear_target=self.clear_target.isChecked())
        except (ValueError, OSError) as exc:
            self.feedback.setText(str(exc))
            return
        super().accept()

    def confirm_password(self):
        """修改通知需要密码：本地只存加盐 scrypt 摘要，错误次数过多会退避。"""
        from . import notify_guard
        text, ok = QInputDialog.getText(self, '修改通知设置', '请输入密码：',
                                        QLineEdit.EchoMode.Password)
        if not ok:
            self.feedback.setText('已取消：未输入密码，通知设置未保存。')
            return False
        allowed, message = notify_guard.verify(text)
        if not allowed:
            self.feedback.setText(message or '密码不正确，通知设置未保存。')
            return False
        return True

    def reject(self):
        if self.busy:
            self.feedback.setText('正在发送测试通知，请等待完成后关闭。')
            return
        super().reject()

    def closeEvent(self, event):
        if self.busy:
            self.feedback.setText('正在发送测试通知，请等待完成后关闭。')
            event.ignore()
        else:
            event.accept()
