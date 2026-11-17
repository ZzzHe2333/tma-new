"""Manual release checks and background downloads for the portable app."""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QVBoxLayout)

from . import __version__, update_release
from .service_jobs import ServiceJob


class UpdateDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('检查更新')
        self.resize(540, 200)
        self.release = None
        self.job = None
        self.saved = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f'当前版本 {__version__}'))
        fields = QFormLayout()
        self.proxy = QLineEdit()
        self.proxy.setPlaceholderText('留空直连，例如 http://127.0.0.1:7897')
        self.mirror = QLineEdit()
        self.mirror.setPlaceholderText('可选，例如 https://你的加速域名/{url}')
        fields.addRow('HTTP 代理', self.proxy)
        fields.addRow('下载加速地址', self.mirror)
        layout.addLayout(fields)
        self.status = QLabel('从 GitHub Releases 检查正式版本。')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.check_button = QPushButton('检查更新')
        self.download_button = QPushButton('下载新版…')
        self.open_button = QPushButton('打开下载目录')
        self.close_button = QPushButton('关闭')
        for button in (self.check_button, self.download_button, self.open_button, self.close_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.check_button.clicked.connect(self.check)
        self.download_button.clicked.connect(self.download)
        self.open_button.clicked.connect(self.open_folder)
        self.close_button.clicked.connect(self.reject)
        self.finished.connect(self.cancel)
        self.sync()

    def sync(self):
        busy = self.job is not None
        self.check_button.setEnabled(not busy)
        self.download_button.setEnabled(not busy and self.release is not None)
        self.open_button.setEnabled(self.saved is not None)
        self.proxy.setEnabled(not busy)
        self.mirror.setEnabled(not busy)
        self.close_button.setText('取消并关闭' if busy else '关闭')

    def start_job(self, function, arguments, callback):
        job = ServiceJob(function, arguments, self)
        self.job = job
        self.sync()

        def complete(event):
            self.job = None
            job.deleteLater()
            if 'error' in event:
                self.status.setText('操作失败：' + event['error'])
            else:
                callback(event['value'])
            self.sync()

        job.done.connect(complete)
        job.start()

    def check(self):
        self.release = None
        self.status.setText('正在检查 GitHub 正式版本…')
        self.start_job(update_release.check, (self.proxy.text().strip(),), self.checked)

    def checked(self, release):
        self.release = release
        if release is None:
            self.status.setText('当前已是最新版本。')
        else:
            self.status.setText(f'发现新版 {release.version}，大小 {release.size / 1024**2:.1f} MB。')

    def download(self):
        target, _ = QFileDialog.getSaveFileName(self, '保存更新包', self.release.filename, 'ZIP (*.zip)')
        if target:
            self.status.setText('正在下载并校验更新包…')
            args = (self.release, target, self.proxy.text().strip(), self.mirror.text().strip())
            self.start_job(update_release.download, args, self.downloaded)

    def downloaded(self, target):
        self.saved = target
        self.status.setText('下载完成，SHA-256 校验通过。请解压到新文件夹，退出当前版本后启动新版。')

    def open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.saved.parent.resolve())))

    def cancel(self):
        if self.job is not None:
            self.job.cancel()
            self.job.deleteLater()
            self.job = None


def show(owner):
    dialog = UpdateDialog(owner)
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()
