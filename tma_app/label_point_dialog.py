"""Native Label Point form; source selection and label changes are a draft."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QGroupBox,QCheckBox,QPushButton,QLabel
from .point_labels import validate_options


class LabelPointDialog(QDialog):
    def __init__(self,owner,entry):
        super().__init__(owner);self.owner,self.entry=owner,entry
        self.setObjectName("LabelPointForm");self.setWindowTitle("标记点 — "+entry["file"])
        self.setFixedSize(370,229);self.setWindowModality(Qt.WindowModality.WindowModal)
        options=validate_options(entry["annotation"]["point_label"]);values=entry["values"]
        group=QGroupBox("标记点显示内容",self);group.setObjectName("LabelGroup");group.setGeometry(12,12,345,97)
        self.boxes={}
        items=(("time","时间","TimeBox",16,20,80),("temperature","温度","TemperatureBox",16,44,100),
               ("signal","信号","XSignalBox",16,68,110),("y","Y轴值","YSignalBox",188,20,110),("multiplex","多频参数","MpxBox",188,44,120))
        for key,caption,name,left,top,width in items:
            box=QCheckBox(caption,group);box.setObjectName(name);box.setGeometry(left,top,width,17);box.setChecked(options[key]);self.boxes[key]=box
            available=key=="y" or key+"_at_point" in values
            if key=="multiplex":available=False
            box.setEnabled(available)
            if not available:
                box.setChecked(False)
                message=(values.get("label_signal_error","请先在信号窗口选择可用的X信号") if key=="signal" else
                         ("当前未识别为多频数据文件" if key=="multiplex" else "当前文件没有相应的时间或温度通道"))
                box.setToolTip(message)
            elif key=="signal":box.setToolTip(values["label_signal"])
        for key,caption,name,left,top,width in (("arrow","箭头指向数据点","ArrowBox",28,120,155),("cross","在数据点画十字","CrossBox",28,144,155),
                                              ("border","绘制边框","BorderBox",200,120,120),("transparent","透明背景","TransparentBox",200,144,120)):
            box=QCheckBox(caption,self);box.setObjectName(name);box.setGeometry(left,top,width,17);box.setChecked(options[key]);self.boxes[key]=box
        self.error=QLabel(self);self.error.setGeometry(12,167,345,22);self.error.setStyleSheet("color:#a00000")
        for caption,name,left,callback in (("确定","OK",12,self.accept),("保存","Save",100,self.save),("取消","Cancel",188,self.reject),("帮助","Help",276,self.help)):
            button=QPushButton(caption,self);button.setObjectName(name);button.setStyleSheet("min-width:0px;");button.setGeometry(left,194,81,25);button.clicked.connect(callback)
            if name=="OK":button.setDefault(True)

    def collect(self):return validate_options({key:box.isChecked() for key,box in self.boxes.items()})

    def accept(self):
        if self.owner._pending_measurement is not self.entry:QDialog.reject(self);return
        try:
            if self.owner.current_measurement() is None:raise ValueError("请回到正在标记的曲线窗口")
            options=self.collect();self.entry["annotation"]["point_label"]=options
            from .app import MainWindow
            MainWindow.confirm_measurement(self.owner)
            self.owner.statusBar().showMessage("曲线值已标记；标注文字可拖动。")
            QDialog.accept(self)
        except ValueError as exc:self.error.setText(str(exc));self.error.setToolTip(str(exc))

    def save(self):
        from .preferences import save_defaults
        try:
            save_defaults("analysis","point_label",{"point_label_options":self.collect()})
            self.error.setText("标记点默认选项已保存。")
        except (ValueError,OSError) as exc:self.error.setText(str(exc));self.error.setToolTip(str(exc))

    def reject(self):
        if self.owner._pending_measurement is self.entry:self.owner.cancel_measurement()
        QDialog.reject(self)

    def help(self):
        self.error.setText("按采集位置标记通道值；保存只设置默认选项。")
        self.error.setToolTip("可同时标注时间、温度、已选X信号和Y值。箭头、十字、边框及背景互相独立。取消不记录本次分析。")
