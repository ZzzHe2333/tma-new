"""TIntegralTypeForm geometry from the complete installed native DFM."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QGroupBox,QRadioButton,QCheckBox,QPushButton,QLabel


class RunningIntegralDialog(QDialog):
    def __init__(self,owner,entry):
        super().__init__(owner);self.owner,self.entry=owner,entry
        self.document=owner.active_document()
        self.setObjectName('IntegralTypeForm');self.setWindowTitle('积分类型')
        self.setFixedSize(282,217);self.setWindowModality(Qt.WindowModality.WindowModal)
        group=QGroupBox('积分类型',self);group.setObjectName('AreaTypeGroup');group.setGeometry(12,12,257,69)
        self.integral=QRadioButton('积分',group);self.integral.setObjectName('IntegralButton');self.integral.setGeometry(8,20,104,17);self.integral.setChecked(True)
        self.percent=QRadioButton('面积百分比',group);self.percent.setObjectName('AreaPercentButton');self.percent.setGeometry(8,44,116,17)
        self.normalized=QCheckBox('归一化',group);self.normalized.setObjectName('NormalizedBox');self.normalized.setGeometry(136,20,106,17);self.normalized.setEnabled(False);self.normalized.setToolTip('TMA尺寸积分不使用DSC热量归一化')
        self.inverted=QCheckBox('反向',group);self.inverted.setObjectName('InvertedBox');self.inverted.setGeometry(136,44,106,17)
        group=QGroupBox('积分基线',self);group.setObjectName('AreaBaselineGroup');group.setGeometry(12,96,257,69)
        parent=owner.running_integral_parent(entry)
        self.parent_peak=parent;self.positions=tuple(entry['interactive'].get('positions',entry['interactive']['indices']))
        self.parent_baseline=QRadioButton('S形基线' if parent['kind']=='peak_sigmoid' else '线性基线',group);self.parent_baseline.setGeometry(8,20,235,17);self.parent_baseline.setChecked(True)
        self.zero_baseline=QRadioButton('零基线（绝对积分）',group);self.zero_baseline.setGeometry(8,44,235,17)
        self.error=QLabel(self);self.error.setGeometry(12,165,257,16);self.error.setStyleSheet('color:#a00000')
        for caption,name,x,callback in (('确定','OK',12,self.accept),('取消','Cancel',100,self.reject),('帮助','Help',188,self.help)):
            button=QPushButton(caption,self);button.setObjectName(name);button.setGeometry(x,182,81,25);button.clicked.connect(callback)
            if name=='OK':button.setDefault(True)

    def accept(self):
        try:
            if self.owner.active_document() is not self.document:raise ValueError('请返回正在执行积分的曲线窗口')
            self.owner.commit_running_integral(self.entry,mode='percent' if self.percent.isChecked() else 'integral',
                inverted=self.inverted.isChecked(),baseline='zero' if self.zero_baseline.isChecked() else 'parent',
                expected_parent=self.parent_peak,expected_positions=self.positions)
            QDialog.accept(self)
        except ValueError as exc:self.error.setText(str(exc));self.error.setToolTip(str(exc))

    def reject(self):
        if self.owner._pending_measurement is self.entry:self.owner.cancel_measurement()
        QDialog.reject(self)

    def help(self):
        self.error.setText('按文件实际时间累计积分并绘到Y4。')
        self.error.setToolTip('面积百分比使用带符号的总面积归一化；反向百分比为100减去百分比。反向积分取负值。零基线为绝对积分。')
