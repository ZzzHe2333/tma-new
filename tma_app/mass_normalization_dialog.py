"""Explicit per-curve weighing confirmation for mass-normalized overlays."""
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QLabel,QTableWidget,QTableWidgetItem,
    QHeaderView,QLineEdit,QCheckBox,QDialogButtonBox,QPushButton,QHBoxLayout)

from . import mass_normalization as core


class MassNormalizationDialog(QDialog):
    def __init__(self,owner,document):
        super().__init__(owner)
        self.owner=owner;self.document=document
        self.mass_job=None;self._manual_rows=set();self._auto_filling=False
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
        self.lookup_status=QLabel('优先使用已读取的 m；缺失项将自动从称量缓存或数据源获取。')
        self.lookup_status.setWordWrap(True);layout.addWidget(self.lookup_status)
        bottom=QHBoxLayout()
        self.restore_button=QPushButton('恢复原始比例')
        self.restore_button.setEnabled(any(c.mass_normalization_mg is not None for c in self.curves))
        self.restore_button.clicked.connect(self.restore_original)
        bottom.addWidget(self.restore_button);bottom.addStretch()
        self.refresh_button=QPushButton('刷新 m')
        self.refresh_button.clicked.connect(lambda:self.auto_read(force=True));bottom.addWidget(self.refresh_button)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('应用统一化')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject)
        bottom.addWidget(self.buttons);layout.addLayout(bottom)
        self.update_validity()
        QTimer.singleShot(0,self.auto_read)

    def changed(self,row):
        if not self._auto_filling:self._manual_rows.add(row)
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

    def stop_lookup(self):
        if self.mass_job is not None:
            self.mass_job.cancel();self.mass_job.deleteLater();self.mass_job=None
        self.refresh_button.setEnabled(True)

    def auto_read(self,*,force=False):
        if not self.isVisible():return
        from .mass_lookup import configured_source
        from .mass_jobs import MassLookupJob
        try:source=configured_source()
        except (ValueError,OSError):source=''
        if not source:
            self.lookup_status.setText('未配置 m 数据源；已读取的重量仍可使用，缺失项请手动填写。');return
        self.stop_lookup();self.lookup_source=source
        self._force_fill=force
        self._using_stale=False
        self.mass_job=MassLookupJob([(str(i),c.sample_name) for i,c in enumerate(self.curves)],source,self,force=force)
        self.mass_job.row_ready.connect(self.mass_ready);self.mass_job.finished.connect(self.mass_finished)
        self.refresh_button.setEnabled(False);self.lookup_status.setText('正在自动读取 m，优先复用缓存；可以手动填写或取消。')
        self.mass_job.start()

    @Slot(str,object)
    def mass_ready(self,key,result):
        if self.sender() is not self.mass_job:return
        from .mass_lookup import configured_source
        try:
            if configured_source()!=self.lookup_source:return
        except (ValueError,OSError):return
        row=int(key);value=core.match_mass_mg(result)
        if '暂不可用' in result.message:self._using_stale=True
        if value is None:return
        item=self.table.item(row,1);item.setText(f'{value:.12g}');item.setToolTip(result.source+'\n'+result.message)
        if row not in self._manual_rows and (self.curves[row].mass_normalization_mg is None or self._force_fill):
            self._auto_filling=True
            try:self.edits[row].setText(f'{value:.12g}')
            finally:self._auto_filling=False
        self.update_validity()

    @Slot()
    def mass_finished(self):
        if self.sender() is not self.mass_job:return
        self.stop_lookup()
        count=sum(bool(self.table.item(i,1).text()) for i in range(len(self.curves)))
        self.lookup_status.setText(f'已自动读取 {count}/{len(self.curves)} 条 m；请逐条核对并确认。缺失项可手动填写。')
        if self._using_stale:self.lookup_status.setText(self.lookup_status.text()+' 数据源暂不可用，当前采用已有缓存。')

    def accept(self):
        try:
            current=core.members(self.owner,self.document)
            if [c.uid for c in current]!=self.uids:raise ValueError('叠图曲线已改变，请重新打开统一化窗口')
            core.apply(self.owner,self.document,self.masses())
        except ValueError as exc:self.error.setText(str(exc));return
        self.stop_lookup();super().accept()

    def restore_original(self):
        try:core.restore(self.owner,self.document)
        except ValueError as exc:self.error.setText(str(exc));return
        self.stop_lookup();super().accept()

    def reject(self):
        self.stop_lookup();super().reject()

    def closeEvent(self,event):
        self.stop_lookup();super().closeEvent(event)
