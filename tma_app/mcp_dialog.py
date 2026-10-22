"""Shared-theme controls for the optional local MCP endpoint."""
import json
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QVBoxLayout)
from . import mcp_service as mcp


class McpDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.service = owner.mcp_service
        self.setWindowTitle("MCP · AI 连接")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self.resize(680, 520)
        layout = QVBoxLayout(self)
        title = QLabel("让 AI 帮你批量处理 TMA")
        title.setStyleSheet("font-size:18px;color:#765d86;font-weight:bold")
        layout.addWidget(title)
        hint = QLabel("默认关闭 · 仅本机可连接 · 使用现有 T1 / T2 / M / H 算法\n开启后可批量读数、出图和导出 XLSX / CSV，不改变桌面曲线。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.enabled = QCheckBox("开启 MCP 服务（下次启动沿用此设置）")
        self.enabled.setObjectName("McpEnabled")
        layout.addWidget(self.enabled)
        form = QFormLayout()
        self.port = QSpinBox(); self.port.setRange(1024, 65535)
        self.port.setObjectName("McpPort")
        form.addRow("本机端口", self.port)
        self.url = QLineEdit(); self.url.setReadOnly(True)
        form.addRow("MCP 地址", self.url)
        token_row = QHBoxLayout()
        self.token = QLineEdit(); self.token.setReadOnly(True)
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        token_row.addWidget(self.token)
        reveal = QCheckBox("显示")
        reveal.toggled.connect(lambda checked: self.token.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
        token_row.addWidget(reveal)
        form.addRow("访问密钥", token_row)
        layout.addLayout(form)
        self.status = QLabel(); self.status.setWordWrap(True)
        self.status.setObjectName("McpStatus")
        layout.addWidget(self.status)
        layout.addWidget(QLabel("连接方式：Streamable HTTP。将地址和 Bearer 密钥填入支持 HTTP 的 MCP 客户端。"))
        self.preview = QPlainTextEdit(); self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(120)
        layout.addWidget(self.preview)
        buttons = QHBoxLayout()
        copy = QPushButton("复制连接配置"); copy.clicked.connect(self.copy_config)
        buttons.addWidget(copy)
        buttons.addStretch()
        apply = QPushButton("应用"); apply.setObjectName("primary"); apply.clicked.connect(self.apply)
        buttons.addWidget(apply)
        close = QPushButton("关闭窗口"); close.clicked.connect(self.close)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.port.valueChanged.connect(self.refresh_preview)
        self.timer = QTimer(self); self.timer.timeout.connect(self.refresh_status)
        self.reload()

    def reload(self):
        try:
            settings = mcp.load_settings()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "MCP 配置", str(exc))
            settings = {"enabled": False, "port": mcp.DEFAULT_PORT, "token": ""}
        self.enabled.setChecked(settings["enabled"])
        self.port.setValue(settings["port"])
        self.token.setText(settings["token"])
        self.refresh_preview()
        self.refresh_status()

    def value(self):
        return {"enabled": self.enabled.isChecked(), "port": self.port.value(), "token": self.token.text()}

    def refresh_preview(self, *_):
        settings = self.value()
        self.url.setText(mcp.endpoint(settings["port"]))
        redacted = {**settings, "token": "<访问密钥；复制配置会包含真实密钥>"}
        self.preview.setPlainText(json.dumps(mcp.client_config(redacted), ensure_ascii=False, indent=2))

    def refresh_status(self):
        labels = {"stopped": "已关闭", "starting": "正在启动…", "running": "运行中", "stopping": "正在停止…", "error": "启动失败"}
        state = labels.get(self.service.state, self.service.state)
        suffix = " · " + mcp.endpoint(self.service.port) if self.service.state == "running" else ""
        self.status.setText("服务状态：" + state + suffix + ("\n" + self.service.error if self.service.error else ""))

    def apply(self):
        value = self.value()
        if not value["token"]:
            value["token"] = mcp.new_token()
        try:
            if self.service.state in ("running", "starting") and value["enabled"] and self.service.port != value["port"]:
                self.service.stop()
            if value["enabled"]:
                self.service.start(value)
            else:
                self.service.stop()
            mcp.save_settings(value)
        except (OSError, ValueError) as exc:
            # If persisting an enabled setting fails, don't leave a surprise server.
            if value["enabled"]:
                self.service.stop()
            QMessageBox.warning(self, "MCP 服务", str(exc))
        else:
            self.token.setText(value["token"])
            self.refresh_preview()
        self.refresh_status()

    def copy_config(self):
        try:
            saved = mcp.load_settings()
            if not saved["token"] or self.value() != saved:
                QMessageBox.information(self, "MCP 连接", "请先点击「应用」保存，再复制连接配置。")
                return
            QApplication.clipboard().setText(json.dumps(mcp.client_config(saved), ensure_ascii=False, indent=2))
            self.status.setText("已复制连接配置（包含访问密钥）")
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "MCP 连接", str(exc))

    def showEvent(self, event):
        self.reload()
        self.timer.start(400)
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)
