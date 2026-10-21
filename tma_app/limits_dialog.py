"""Native data-limit chooser and time/temperature/cycle entry layouts."""
from PySide6.QtWidgets import QDialog,QGroupBox,QRadioButton,QButtonGroup,QLabel,QLineEdit,QCheckBox,QPushButton
from .data_limits import cycle_index


class LimitBoundsDialog(QDialog):
    def __init__(self,owner,curve,kind):
        super().__init__(owner);self.owner,self.curve,self.kind=owner,curve,kind
        self.setObjectName({"time":"TimeLimitsForm","temperature":"TempLimitsForm","cycle":"CycleLimitsForm"}[kind])
        self.setWindowTitle({"time":"时间数据界限","temperature":"温度数据界限","cycle":"循环数据界限"}[kind]+" — "+curve.dataset.path.name)
        original_height={"time":149,"temperature":205,"cycle":114}[kind]
        self.setFixedSize(282,original_height+20);self.setModal(True)
        value=curve.data_limit_spec if curve.data_limit_spec and curve.data_limit_spec["kind"]==kind else dict(start=0.,stop=0.,delay=0.,all_cycles=False,reset_time=False)
        if kind=="cycle" and not (curve.data_limit_spec and curve.data_limit_spec["kind"]==kind):
            index=cycle_index(curve.dataset)
            if index is not None:value=dict(value,start=float(curve.dataset.values[:,index].min()),stop=float(curve.dataset.values[:,index].max()))
        self.fields={}
        if kind=="cycle":
            label=QLabel("循环",self);label.setGeometry(36,20,40,20)
            label=QLabel("至",self);label.setGeometry(140,20,30,20)
            for key,x in (("start",76),("stop",176)):
                edit=QLineEdit(format(value[key],".15g"),self);edit.setGeometry(x,16,49,23);self.fields[key]=edit
        else:
            x=104 if kind=="temperature" else 96
            variable=curve.dataset.time_index if kind=="time" else curve.dataset.temperature_index
            units=curve.dataset.signals[variable].unit if variable is not None else ""
            for key,text,y in (("start","起点:",16),("stop","止点:",48)):
                label=QLabel(text,self);label.setGeometry(x-45,y+4,45,20)
                edit=QLineEdit(format(value[key],".15g"),self);edit.setGeometry(x,y,85,23);self.fields[key]=edit
                label=QLabel(units,self);label.setGeometry(x+96,y+4,70,20)
        self.all_cycles=None
        if kind=="temperature":
            label=QLabel("延迟时间:",self);label.setGeometry(40,84,64,20)
            edit=QLineEdit(format(value["delay"],".15g"),self);edit.setGeometry(104,80,85,23);self.fields["delay"]=edit
            unit=curve.dataset.signals[curve.dataset.time_index].unit if curve.dataset.time_index is not None else ""
            label=QLabel(unit,self);label.setGeometry(200,84,65,20)
            self.all_cycles=QCheckBox("包含延迟后的全部循环",self);self.all_cycles.setGeometry(24,114,242,20);self.all_cycles.setChecked(value["all_cycles"])
        self.reset=QCheckBox("时间归零",self);self.reset.setGeometry(36 if kind=="cycle" else 24,{"cycle":50,"time":82,"temperature":142}[kind],220,20)
        self.reset.setChecked(value["reset_time"])
        self.error=QLabel(self);self.error.setGeometry(12,original_height-35,258,22);self.error.setStyleSheet("color:#a00000")
        for text,x,callback in (("确定",12,self.accept),("取消",100,self.reject),("帮助",188,self.help)):
            button=QPushButton(text,self);button.setGeometry(x,original_height-13,81,25);button.clicked.connect(callback)
            if text=="确定":button.setDefault(True)

    def accept(self):
        try:
            values={key:float(field.text()) for key,field in self.fields.items()}
            spec={"kind":self.kind,"start":values["start"],"stop":values["stop"],"delay":values.get("delay",0.),
                  "all_cycles":bool(self.all_cycles and self.all_cycles.isChecked()),"reset_time":self.reset.isChecked()}
            self.owner.apply_data_limits(self.curve.dataset,spec)
            super().accept()
        except (ValueError,OverflowError) as exc:self.error.setText(str(exc));self.error.setToolTip(str(exc))

    def help(self):
        self.error.setText("时间0表示文件边界；温度0/0为全范围。")


class DataLimitsDialog(QDialog):
    def __init__(self,owner,curve):
        super().__init__(owner);self.owner,self.curve=owner,curve;self.child=None
        self.setObjectName("DataLimitsForm");self.setWindowTitle("数据界限 — "+curve.dataset.path.name);self.setFixedSize(282,186);self.setModal(True)
        group=QGroupBox(self);group.setGeometry(12,8,257,109);self.choices=QButtonGroup(self)
        selected=curve.data_limit_spec["kind"] if curve.data_limit_spec else "full"
        for i,(text,kind,enabled) in enumerate((("全范围","full",True),("时间界限","time",curve.dataset.time_index is not None),("温度界限","temperature",curve.dataset.temperature_index is not None),("循环界限","cycle",cycle_index(curve.dataset) is not None))):
            button=QRadioButton(text,group);button.setGeometry(14,7+24*i,230,21);button.setProperty("kind",kind);button.setEnabled(enabled)
            button.setChecked(kind==selected);self.choices.addButton(button)
            if not enabled:button.setToolTip("文件中没有相应的明确采集信号");button.setStyleSheet("color:#808080")
        self.error=QLabel(self);self.error.setGeometry(12,120,258,24);self.error.setStyleSheet("color:#a00000")
        for text,x,callback in (("确定",12,self.accept),("取消",100,self.reject),("帮助",188,self.help)):
            button=QPushButton(text,self);button.setGeometry(x,152,81,25);button.clicked.connect(callback)
            if text=="确定":button.setDefault(True)

    def accept(self):
        kind=self.choices.checkedButton().property("kind")
        if kind=="full":
            try:self.owner.apply_data_limits(self.curve.dataset,None);super().accept()
            except ValueError as exc:self.error.setText(str(exc));self.error.setToolTip(str(exc))
        else:
            self.child=LimitBoundsDialog(self.owner,self.curve,kind)
            self.child.accepted.connect(lambda:QDialog.accept(self));self.child.rejected.connect(self.reject)
            self.hide();self.child.show()

    def help(self):self.error.setText("选择全文件，或指定下一窗口的数据界限。")
