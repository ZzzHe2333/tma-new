"""Native TFileInfoForm editing existing files; fields remain drafts until OK."""
from __future__ import annotations
from copy import deepcopy
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QLabel,QLineEdit,QPushButton,QComboBox,QMessageBox
from .file_information import TEXT_LIMITS,text_value,effective_size,source_text,nonnegative_size


class FileInfoDialog(QDialog):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.curve=owner.current_data_curve();self.document=owner.active_document()
        self.setObjectName('FileInfoForm');self.setWindowTitle('文件信息');self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setFixedSize(490,326);self.fields={};self.labels={}
        self.original_info=deepcopy(self.curve.file_info);self.original_size=self.curve.sample_size_mm
        self.original_text={key:text_value(self.curve,key) for key in TEXT_LIMITS}
        for key,y,caption in (('Sample',76,'样品:'),('Operator',140,'操作者:'),('Method',172,'方法:'),('Comment',204,'备注:')):
            label=QLabel(caption,self);label.setGeometry(25,y+2,61,16);label.setAlignment(Qt.AlignmentFlag.AlignRight)
            field=QLineEdit(self.original_text[key],self);field.setObjectName(key+'Edit');field.setGeometry(96,y,381,21)
            field.setMaxLength(max(TEXT_LIMITS[key],len(self.original_text[key])));self.fields[key]=field
        label=QLabel('尺寸:',self);label.setGeometry(30,110,56,16);label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.size_field=QLineEdit(self);self.size_field.setObjectName('Size1Edit');self.size_field.setGeometry(96,108,77,21)
        current=effective_size(self.curve);self.size_original_text=format(current,'.15g') if current is not None else source_text(self.curve,'Size')
        self.size_field.setText(self.size_original_text);self.size_field.setToolTip(format(current,'.17g') if current is not None else '输入TMA原始尺寸(mm)')
        self.tma=any(s.name.lower().startswith('dimension') and s.unit.replace('μ','µ') in ('µm','um','mm') for s in self.curve.dataset.signals)
        self.size_field.setReadOnly(not self.tma)
        for name,x in (('Size2Edit',196),('Size3Edit',296)):
            field=QLineEdit(self);field.setObjectName(name);field.setGeometry(x,108,77,21);field.setEnabled(False)
        for x in (181,281):label=QLabel('×',self);label.setGeometry(x,112,12,13);label.setEnabled(False)
        label=QLabel('mm' if self.tma else '—',self);label.setGeometry(384,112,60,16)
        for name,caption,x,y,value,vx,width in (
            ('RunDate','运行日期:',40,8,' '.join(filter(None,(source_text(self.curve,'Date'),source_text(self.curve,'Time')))),128,145),
            ('PointsRead','读取点数:',40,28,str(len(self.curve.dataset.values)),128,100),
            ('PointsUsed','使用点数:',40,48,str(len(self.curve.active_rows)),128,100),
            ('Cycles','循环数:',265,8,self.cycle_count(),344,133),
            ('BufferSize','缓冲区:',265,28,'—',344,133),('Compression','压缩:',265,48,'—',344,133)):
            label=QLabel(caption,self);label.setGeometry(x,y,76,15);label.setAlignment(Qt.AlignmentFlag.AlignRight)
            value_label=QLabel(value,self);value_label.setObjectName(name);value_label.setGeometry(vx,y,width,15);value_label.setToolTip(value)
            self.labels[name]=value_label
            if value=='—':value_label.setEnabled(False);value_label.setToolTip('源文件未提供已识别的该项信息')
        label=QLabel('放热:',self);label.setGeometry(38,238,48,16);label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.exotherm=QComboBox(self);self.exotherm.setObjectName('ExothermCombo');self.exotherm.setGeometry(96,236,77,21);self.exotherm.setEnabled(False)
        label=QLabel('池常数:',self);label.setGeometry(220,238,65,16);label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.kcell=QLineEdit(source_text(self.curve,'Kcell'),self);self.kcell.setObjectName('KCellEdit');self.kcell.setGeometry(296,236,77,21);self.kcell.setReadOnly(True);self.kcell.setToolTip('保留源校准值；校准重算尚未接入')
        self.error=QLabel(self);self.error.setGeometry(12,262,466,27);self.error.setWordWrap(True);self.error.setStyleSheet('color:#a00000')
        for name,text,x,callback in (('OK','确定',220,self.accept),('Cancel','取消',308,self.reject),('Help','帮助',396,self.help)):
            button=QPushButton(text,self);button.setObjectName(name);button.setStyleSheet('min-width:0px;');button.setGeometry(x,292,81,25);button.clicked.connect(callback)
            if name=='OK':button.setDefault(True)

    def cycle_count(self):
        from .data_limits import cycle_index
        index=cycle_index(self.curve.dataset)
        if index is None:return '—'
        values=self.curve.dataset.values[:,index]
        return str(len(np.unique(values)))

    def accept(self):
        try:
            if self.owner.active_document() is not self.document or not any(c is self.curve for c in self.owner.visible_curves()):raise ValueError('当前文件已切换，请返回原文件后确定')
            if self.curve.file_info!=self.original_info or self.curve.sample_size_mm!=self.original_size:raise ValueError('文件信息已变化，请重新打开本窗口')
            changes={key:field.text() for key,field in self.fields.items() if field.text()!=self.original_text[key]}
            size_changed=self.tma and self.size_field.text()!=self.size_original_text
            value=nonnegative_size(float(self.size_field.text())) if size_changed else None
            # Re-entering a different numeric spelling must not trigger a destructive reload.
            if size_changed and value==effective_size(self.curve):size_changed=False
            if changes or size_changed:self.owner.apply_file_information(self.curve,changes,size_changed,value)
            super().accept()
        except ValueError as exc:self.error.setText(str(exc))

    def help(self):
        QMessageBox.information(self,'文件信息','样品名最多32字，操作者25字，备注64字。只修改文字会保留当前处理和分析。\n修改尺寸会重新读取同一源文件，清除该文件的处理及分析；图形显示样式和数据范围保留。输入0表示未指定尺寸，下次Alpha分析会再次要求非零实测尺寸。\n修改只随本应用会话保存，不写入原始文件。池常数重算和放热方向尚未接入。')
