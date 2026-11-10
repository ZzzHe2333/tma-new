"""Pastel image provenance result card, with background verification."""
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                              QPushButton, QFrame, QFormLayout, QLineEdit)

from .service_jobs import ServiceJob
from .image_provenance import verify_job


def date_fields(value):
    try:
        parsed = datetime.fromisoformat(value)
        offset = parsed.utcoffset()
        if offset is None:
            zone = '未记录'
        else:
            minutes = int(offset.total_seconds() / 60)
            zone = f"UTC{'+' if minutes >= 0 else '-'}{abs(minutes)//60:02d}:{abs(minutes)%60:02d}"
        return parsed.strftime('%Y-%m-%d'), parsed.strftime('%H:%M:%S'), zone
    except (ValueError, TypeError):
        return '未记录', '未记录', '未记录'


class ImageVerificationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('图片鉴定')
        self.setStyleSheet('QWidget {font-family: "Microsoft YaHei";}')
        self.resize(760, 490)
        self.setMinimumWidth(580)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(18)
        top = QHBoxLayout()
        self.badge = QLabel('◌')
        self.badge.setFixedSize(104, 104)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setStyleSheet('font-size:40px;color:#a78db6;')
        top.addWidget(self.badge)
        heading = QVBoxLayout()
        self.title = QLabel('正在鉴定图片')
        self.title.setStyleSheet('font-size:22px;font-weight:600;color:#655075;')
        self.subtitle = QLabel('正在检查来源标记与图片内容，请稍候。')
        self.subtitle.setWordWrap(True)
        self.subtitle.setTextFormat(Qt.TextFormat.PlainText)
        heading.addWidget(self.title)
        heading.addWidget(self.subtitle)
        top.addLayout(heading, 1)
        layout.addLayout(top)
        card = QFrame()
        card.setObjectName('verificationDetails')
        card.setStyleSheet('QFrame#verificationDetails {background:#fffcff;border:1px solid #e9dff0;border-radius:12px;}')
        form = QFormLayout(card)
        form.setContentsMargins(20, 16, 20, 16)
        form.setVerticalSpacing(12)
        self.path_field = QLineEdit()
        self.hash_field = QLineEdit()
        for title, widget in (('图片路径', self.path_field), ('SHA-256', self.hash_field)):
            widget.setReadOnly(True)
            widget.setMinimumWidth(0)
            widget.setText('—')
            form.addRow(title, widget)
        self.hash_field.setToolTip('对所选图片整个文件计算的 SHA-256，包括图片内容与元数据。')
        self.machine_field = QLineEdit('未读取')
        self.machine_field.setReadOnly(True)
        form.addRow('来源机器码', self.machine_field)
        self.cpu_field = QLineEdit('未读取')
        self.ip_field = QLineEdit('未读取')
        for title, widget in (('来源 CPU', self.cpu_field), ('来源内网 IP', self.ip_field)):
            widget.setReadOnly(True)
            form.addRow(title, widget)
        self.fields = {}
        for name in ('日期', '时间', '时区', '版本'):
            label = QLabel('—')
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.fields[name] = label
            form.addRow(name, label)
        layout.addWidget(card)
        disclaimer = QLabel('免责声明：仅供来源辅助核对，不构成第三方真实性认证。')
        disclaimer.setStyleSheet('color:#95839e;font-size:12px;')
        layout.addWidget(disclaimer)
        footer = QHBoxLayout()
        footer.addStretch()
        close = QPushButton('关闭')
        close.setMinimumSize(96, 32)
        close.clicked.connect(self.close)
        footer.addWidget(close)
        layout.addLayout(footer)
        self.job = None
        self.finished.connect(self._cancel)

    def _cancel(self, *_):
        if self.job: self.job.cancel()

    def start(self, path):
        self.path_field.setText(str(path))
        self.path_field.setToolTip(str(path))
        self.path_field.setCursorPosition(0)
        self.hash_field.setText('计算中…')
        self.job = ServiceJob(verify_job, (path,), self)
        self.job.done.connect(self.show_result)
        self.job.start()

    def show_result(self, event):
        result = event.get('value') or {}
        if result.get('path'):
            self.path_field.setText(result['path'])
            self.path_field.setToolTip(result['path'])
            self.path_field.setCursorPosition(0)
        self.hash_field.setText(result.get('file_sha256', '无法计算'))
        self.hash_field.setCursorPosition(0)
        status = result.get('status')
        self.machine_field.setText(result.get('machine_code') or '未读取（旧图或载荷未能通过校验）')
        environment = result.get('environment') or {}
        self.cpu_field.setText(environment.get('cpu_model') or '未记录')
        self.cpu_field.setToolTip(environment.get('cpu_model') or '未记录')
        self.ip_field.setText(environment.get('lan_ip') or '未记录')
        self.ip_field.setToolTip('导出时使用的内网地址快照，最多缓存5分钟；不是当前查看电脑的地址。')
        passed = status == 'verified' and not event.get('error')
        captions = {'verified': ('鉴定通过', '检测到本软件来源标记，图片内容校验通过。'),
                    'frequency_only': ('检测到频域标记', '缺少完整性记录，仅可辅助判断来源，不能确认图片未被修改。'),
                    'modified': ('校验未通过', '来源标记或图片内容不一致，图片可能经过修改。'),
                    'missing': ('暂时无法确认', '未发现可识别标记；旧图、截图或另存图片可能没有标记。')}
        title, summary = captions.get(status, ('无法读取图片', event.get('error') or result.get('error') or '图片格式不受支持。'))
        self.title.setText(title)
        self.subtitle.setText(summary)
        if passed:
            pixmap = QPixmap(str(Path(__file__).parent/'assets/cute/verification-pass.png'))
            self.badge.setPixmap(pixmap.scaled(104, 104, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self.title.setStyleSheet('font-size:22px;font-weight:600;color:#568c77;')
        else:
            self.badge.clear()
            self.badge.setText('!' if status == 'modified' else '?')
        values = (*date_fields(result.get('exported_at')),
                  str(result.get('version') or '未记录')) if passed else ('未记录',)*4
        for name, value in zip(self.fields, values):
            self.fields[name].setText(value)
