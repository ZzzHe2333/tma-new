"""Read-only display for local feature counters and opt-in hidden tools."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QMessageBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from .feature_usage import database_path, read_usage, track
from .service_jobs import ServiceJob


def show_usage(owner):
    dialog = QDialog(owner)
    dialog.setWindowTitle('功能使用统计')
    dialog.resize(560, 420)
    layout = QVBoxLayout(dialog)
    summary = QLabel('正在读取本地统计…', dialog)
    summary.setWordWrap(True)
    summary.setTextFormat(Qt.TextFormat.PlainText)
    layout.addWidget(summary)
    table = QTableWidget(0, 2, dialog)
    table.setHorizontalHeaderLabels(['功能', '使用次数'])
    table.horizontalHeader().setStretchLastSection(True)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    layout.addWidget(table)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=dialog)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    job = ServiceJob(read_usage, (database_path(),), dialog)

    def loaded(event):
        if 'error' in event:
            summary.setText('读取统计失败：' + event['error'])
            return
        rows = event['value']
        summary.setText(f'已使用 {len(rows)} 项功能，共 {sum(count for _, count in rows)} 次。按入口触发计数，仅保存在本机。')
        table.setRowCount(len(rows))
        for index, (label, count) in enumerate(rows):
            table.setItem(index, 0, QTableWidgetItem(label))
            item = QTableWidgetItem()
            item.setData(Qt.ItemDataRole.DisplayRole, count)
            table.setItem(index, 1, item)
        table.resizeColumnToContents(0)

    job.done.connect(loaded)
    dialog.finished.connect(job.cancel)
    job.start()
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()


def show_sample_identity(owner):
    curve = owner.selected()
    if curve is None:
        QMessageBox.information(owner, '样品编号识别', '请先打开并选中一条曲线。')
        return
    identity = curve.dataset.sample_identity
    if identity is None:
        text = '未识别到实验号、生产号或外来样品编号。'
    else:
        kind = {'experiment': '实验号', 'production_a': '生产号 A',
                'production_b': '生产号 B', 'external': '外来样品'}[identity.kind]
        text = f'类型：{kind}\n匹配编号：{identity.matched}\n标准编号：{identity.canonical}'
        if identity.repeat is not None:
            text += f'\n复测序号：{identity.repeat}'
    box = QMessageBox(QMessageBox.Icon.Information, '样品编号识别', text,
                      QMessageBox.StandardButton.Ok, owner)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.exec()


def install(owner):
    # Attach to shared actions once. Right-click and toolbar aliases trigger the same action.
    seen = set()
    owner._usage_menu_references = []

    def attach(menu, prefix):
        for action in menu.actions():
            submenu = action.menu()
            if submenu is not None:
                owner._usage_menu_references.append((action, submenu))
                attach(submenu, prefix + (action.text(),))
            elif not action.isSeparator() and action.isEnabled() and action not in seen:
                seen.add(action)
                label = ' → '.join((*prefix, action.text())).replace('&', '')
                track(action, action.objectName() or label, label)

    for action in owner.menuBar().actions():
        menu = action.menu()
        if menu is not None:
            owner._usage_menu_references.append((action, menu))
            attach(menu, (action.text(),))
    owner.settings_menu.addAction('功能使用统计…', lambda: show_usage(owner))
    tools = owner.menuBar().addMenu('隐藏功能')
    owner.hidden_tools_menu = tools
    tools.menuAction().setVisible(False)
    action = tools.addAction('样品编号识别…', lambda: show_sample_identity(owner))
    track(action, 'SampleIdentity', '隐藏功能 → 样品编号识别')
    toggle = owner.settings_menu.addAction('显示隐藏功能')
    toggle.setCheckable(True)
    toggle.toggled.connect(tools.menuAction().setVisible)
