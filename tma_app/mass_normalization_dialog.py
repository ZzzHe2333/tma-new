"""Explicit per-curve weighing confirmation for mass-normalized overlays."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QLabel,QTableWidget,QTableWidgetItem,
    QHeaderView,QLineEdit,QCheckBox,QDialogButtonBox,QPushButton,QHBoxLayout)

from . import mass_normalization as core


class MassNormalizationDialog(QDialog):
    def __init__(self,owner,document):
        super().__init__(owner)
        self.owner=owner;self.document=document
        self.curves=core.members(owner,document)
        self.uids=[c.uid for c in self.curves]
        self.setWindowTitle('统一化 · m = 0.50 mg')
        self.setObjectName('MassNormalizationDialog')
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(760,420)
        layout=QVBoxLayout(self)
        title=QLabel('统一到 0.50 mg，让高度更方便比较')
        title.setStyleSheet('font-size: 16px; font-weight: 600; color: #806491;')
        layout.addWidget(title)
        hint=QLabel('每条曲线都需填写或核对 m，并勾选确认。高度 × (0.50 ÷ m)，温度不变。\n只作用于当前叠图；原始数据不改动，重复应用不会叠乘。')
        hint.setWordWrap(True);layout.addWidget(hint)
        self.table=QTableWidget(len(self.curves),5)
        self.table.setHorizontalHeaderLabels(['曲线 / 文件','读取到的 m (mg)','使用的 m (mg)','高度倍率','确认'])
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1,125);self.table.setColumnWidth(2,125);self.table.setColumnWidth(3,90);self.table.setColumnWidth(4,60)
        self.edits=[];self.checks=[]
        for row,curve in enumerate(self.curves):
            known=core.known_mass_mg(curve)
            used=curve.mass_normalization_mg if curve.mass_normalization_mg is not None else known
            for col,text in ((0,f'{curve.sample_name} · {curve.dataset.display_name} · Y{curve.axis+1}'),(1,'' if known is None else f'{known:.12g}'),(3,'')):
                item=QTableWidgetItem(text);item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setToolTip(text);self.table.setItem(row,col,item)
            edit=QLineEdit('' if used is None else f'{used:.12g}')
            edit.setPlaceholderText('必填，单位 mg');edit.setObjectName(f'MassInput{row}')
            check=QCheckBox();check.setObjectName(f'MassConfirm{row}')
            self.edits.append(edit);self.checks.append(check)
            self.table.setCellWidget(row,2,edit);self.table.setCellWidget(row,4,check)
            edit.textChanged.connect(lambda text,r=row:self.changed(r))
            check.toggled.connect(self.update_validity)
        layout.addWidget(self.table)
        self.error=QLabel();self.error.setWordWrap(True);self.error.setStyleSheet('color:#b14c69;')
        layout.addWidget(self.error)
        bottom=QHBoxLayout()
        self.restore_button=QPushButton('恢复原始比例')
        self.restore_button.setEnabled(any(c.mass_normalization_mg is not None for c in self.curves))
        self.restore_button.clicked.connect(self.restore_original)
        bottom.addWidget(self.restore_button);bottom.addStretch()
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('应用统一化')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject)
        bottom.addWidget(self.buttons);layout.addLayout(bottom)
        self.update_validity()

    def changed(self,row):
        self.checks[row].setChecked(False)
        self.update_validity()

    def masses(self):
        values={}
        for uid,edit,check in zip(self.uids,self.edits,self.checks):
            try:value=core.validate_mass(float(edit.text().strip()))
            except (ValueError,OverflowError):raise ValueError('每条曲线都必须输入大于零的有效 m（mg）') from None
            if not check.isChecked():raise ValueError('请逐条核对 m，并勾选确认')
            values[uid]=value
        return values

    def update_validity(self,*args):
        for row,edit in enumerate(self.edits):
            try:factor=core.TARGET_MASS_MG/core.validate_mass(float(edit.text().strip()));text=f'{factor:.6g} ×'
            except (ValueError,OverflowError):text='—'
            self.table.item(row,3).setText(text)
        try:self.masses();valid=True
        except ValueError:valid=False
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)

    def accept(self):
        try:
            current=core.members(self.owner,self.document)
            if [c.uid for c in current]!=self.uids:raise ValueError('叠图曲线已改变，请重新打开统一化窗口')
            core.apply(self.owner,self.document,self.masses())
        except ValueError as exc:self.error.setText(str(exc));return
        super().accept()

    def restore_original(self):
        try:core.restore(self.owner,self.document)
        except ValueError as exc:self.error.setText(str(exc));return
        super().accept()
