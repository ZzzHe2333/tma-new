"""Signal selection based on the installed TSignalsForm DFM and local help."""
from copy import deepcopy
from dataclasses import replace
import uuid
from PySide6.QtWidgets import QDialog, QGroupBox, QLabel, QComboBox, QRadioButton, QButtonGroup, QCheckBox, QPushButton
from .workspace import Curve, default_plot_options
from .signal_processing import typed_signal, local_fit, factory_template, validate_template

TYPES = [("正常", "normal"), ("对数", "log"), ("倒数", "inverse"), ("倒数×1000", "inverse1000"),
         ("一阶导数(时间)", "d_time"), ("一阶导数(温度)", "d_temperature"), ("对数导数(时间)", "log_time"),
         ("对数导数(温度)", "log_temperature"), ("二阶导数(时间)", "d2_time"), ("二阶导数(温度)", "d2_temperature")]
SUPPORTED = {"normal", "d_time", "d_temperature", "d2_time", "d2_temperature"}


def current_template(owner, dataset):
    curves = [c for c in owner.curves if c.dataset.path == dataset.path and c.normal_enabled]
    template = factory_template(dataset)
    for axis in range(4):
        curve = next((c for c in curves if c.axis == axis), None)
        template["y"][axis] = {"signal": curve.signal_label if curve else None, "type": curve.y_type if curve else "normal", "width": curve.smooth_width if curve else 0.}
    curve = curves[0] if curves else next(c for c in owner.curves if c.dataset.path == dataset.path)
    options = owner.plot_options.get(str(dataset.path), {})
    template["x"] = {"domain": options.get("x_domain") or owner.domain,
                       "signal": dataset.signals[curve.x_signal_index].label if curve.x_signal_index is not None else template["x"]["signal"],
                       "type": curve.x_signal_type, "width": curve.x_smooth_width}
    template["secondary"] = options.get("secondary_x", False)
    return template


def build_proposal(curves, dataset, template):
    """Return an independent full proposal. No live curve is modified on error."""
    domain = template["x"]["domain"]
    if domain not in ("temperature", "time", "signal"): raise ValueError("X信号无效")
    draft = [replace(c, operations=list(c.operations), history=list(c.history)) for c in curves]
    source = [c for c in draft if c.dataset.path == dataset.path]
    originals = [c for c in source if c.normal_enabled]
    for curve in source: curve.activate_appearance("normal"); curve.normal_enabled = False
    def index(label):
        matches = [i for i,s in enumerate(dataset.signals) if s.label == label]
        if len(matches) != 1: raise ValueError(f"信号不存在或名称不唯一：{label}")
        return matches[0]
    xindex = index(template["x"]["signal"]) if template["x"]["signal"] is not None else None
    xkind, xwidth = template["x"]["type"], template["x"]["width"]
    if xkind not in SUPPORTED: raise ValueError("所选X类型的数学定义尚未确认")
    if domain == "signal" and xindex is None: raise ValueError("请选择X信号")
    for curve in source: curve.x_signal_index, curve.x_signal_type, curve.x_smooth_width = xindex, xkind, xwidth
    reference = source[0] if source else Curve(dataset)
    x = reference.x_values(domain)
    for axis, item in enumerate(template["y"]):
        if item["signal"] is None: continue
        yi, kind, width = index(item["signal"]), item["type"], item["width"]
        candidate = next((c for c in source if c.axis == axis and c.y_index == yi and c.y_type == kind and c.smooth_width == width), None)
        if candidate is None:
            if kind not in SUPPORTED: raise ValueError("当前处理只能保留在原曲线上；请选择已实现的信号类型")
            base = next((c for c in originals if c.axis == axis), reference)
            candidate = replace(base, uid=uuid.uuid4().hex, y_index=yi, axis=axis, scale=1., offset=0.,
                                normal_enabled=True, overlay_enabled=False, y_type=kind, smooth_width=width,
                                operations=[], history=[], normal_appearance=None, overlay_appearance=None,
                                smooth_source=None,smooth_base_ops=[],smooth_reuse=False,smooth_domain=None,smooth_x_config=None,
                                working_rows=None,smooth_source_rows=None)
            from .data_limits import smoothed_state
            for key,value in smoothed_state(candidate,domain,width).items():setattr(candidate,key,value)
            draft.append(candidate); source.append(candidate)
        elif candidate not in originals and candidate.y_type!="custom":
            from .data_limits import smoothed_state
            for key,value in smoothed_state(candidate,domain,width).items():setattr(candidate,key,value)
        candidate.normal_enabled = True
        candidate.xy(domain)
    return draft


class SignalsDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner); self.owner=owner; self.dataset=owner.selected().dataset
        self.template = current_template(owner,self.dataset)
        self.setObjectName("SignalsForm"); self.setWindowTitle("信号 — "+self.dataset.path.name)
        self.setFixedSize(630,403); self.setModal(True)
        self.signals=[]; self.types=[]
        for axis in range(4):
            group=QGroupBox(f"Y{axis+1}",self);group.setGeometry(12,12+56*axis,605,49)
            label=QLabel("信号:",group);label.setGeometry(40,20,40,17)
            label=QLabel("类型:",group);label.setGeometry(416,20,40,17)
            signal=QComboBox(group);signal.setGeometry(84,16,301,23);signal.addItem("无",None)
            for sig in self.dataset.signals:signal.addItem(sig.label,sig.label)
            kind=self.type_combo(group,custom=self.template["y"][axis]["type"]=="custom");kind.setGeometry(456,16,141,23)
            self.signals.append(signal);self.types.append(kind)
        group=QGroupBox("X",self);group.setGeometry(12,234,605,100)
        self.x_modes=QButtonGroup(self)
        for i,(text,mode) in enumerate((("时间 (min)","time"),("温度 (°C)","temperature"),("信号:","signal"))):
            box=QRadioButton(text,group);box.setGeometry(12,20+25*i,120,20);box.setProperty("mode",mode);self.x_modes.addButton(box)
            box.setEnabled(mode=="signal" or (self.dataset.time_index if mode=="time" else self.dataset.temperature_index) is not None)
        self.x_signal=QComboBox(group);self.x_signal.setGeometry(84,68,301,23)
        for signal in self.dataset.signals:self.x_signal.addItem(signal.label,signal.label)
        self.x_type=self.type_combo(group);self.x_type.setGeometry(460,68,137,23)
        label=QLabel("类型:",group);label.setGeometry(420,72,40,17)
        self.show_temperature=QCheckBox("显示温度 (°C)",group);self.show_temperature.setGeometry(228,20,180,20)
        self.show_time=QCheckBox("显示时间 (min)",group);self.show_time.setGeometry(228,44,180,20)
        self.x_modes.buttonClicked.connect(self.update_x)
        self.error=QLabel(self);self.error.setGeometry(12,336,605,20);self.error.setStyleSheet("color: #a00000")
        for text,x,callback in (("确定",184,self.accept),("保存",272,self.save),("默认值",360,self.defaults),("取消",448,self.reject),("帮助",536,self.help)):
            button=QPushButton(text,self);button.setGeometry(x,368,81,25);button.clicked.connect(callback)
            if text=="确定":button.setDefault(True)
        self.load(self.template)

    @staticmethod
    def type_combo(parent,custom=False):
        box=QComboBox(parent)
        for text,value in TYPES:
            box.addItem(text,value)
            if value not in SUPPORTED:
                box.model().item(box.count()-1).setEnabled(False)
                box.setItemData(box.count()-1,"厂家数学定义尚未确认",0x0003)
        if custom:box.addItem("当前处理（保留）","custom")
        return box

    def load(self,value):
        self.template=deepcopy(value)
        for signal,kind,item in zip(self.signals,self.types,value["y"]):
            signal.setCurrentIndex(max(0,signal.findData(item["signal"])));kind.setCurrentIndex(max(0,kind.findData(item["type"])))
        for button in self.x_modes.buttons():button.setChecked(button.property("mode")==value["x"]["domain"])
        self.x_signal.setCurrentIndex(max(0,self.x_signal.findData(value["x"]["signal"])));self.x_type.setCurrentIndex(max(0,self.x_type.findData(value["x"]["type"])))
        self.show_temperature.setChecked(value["secondary"] and value["x"]["domain"]=="time")
        self.show_time.setChecked(value["secondary"] and value["x"]["domain"]=="temperature");self.update_x()

    def update_x(self,*_):
        mode=self.x_modes.checkedButton().property("mode")
        self.x_signal.setEnabled(mode=="signal");self.x_type.setEnabled(mode=="signal")
        self.show_temperature.setEnabled(mode=="time" and self.dataset.temperature_index is not None)
        self.show_time.setEnabled(mode=="temperature" and self.dataset.time_index is not None)

    def collect(self):
        mode=self.x_modes.checkedButton().property("mode")
        return {"y":[{"signal":s.currentData(),"type":t.currentData() if s.currentData() is not None else "normal", "width":old["width"] if s.currentData()==old["signal"] and t.currentData()==old["type"] and s.currentData() is not None else 0.} for s,t,old in zip(self.signals,self.types,self.template["y"])],
                "x":{"domain":mode,"signal":self.x_signal.currentData(),"type":self.x_type.currentData(),"width":self.template["x"]["width"]},
                "secondary":self.show_temperature.isChecked() if mode=="time" else (self.show_time.isChecked() if mode=="temperature" else False)}

    def accept(self):
        try:
            value=self.collect();draft=build_proposal(self.owner.curves,self.dataset,value)
            selected=self.owner.selected();uid=selected.uid if selected else None
            enabled=[c for c in draft if c.dataset.path==self.dataset.path and c.normal_enabled]
            if not any(c.uid==uid for c in enabled) and enabled:uid=enabled[0].uid
            self.owner.cancel_measurement(redraw=False);self.owner.curves=draft
            options=self.owner.plot_options.setdefault(str(self.dataset.path),default_plot_options())
            options.update(x_domain=value["x"]["domain"],secondary_x=value["secondary"],x_limits=None,x_ticks=None,auto_x=True,
                           y_limits=[None]*4,y_ticks=[None]*4,auto_y=[True]*4)
            self.owner.sync_documents();self.owner.rebuild_files()
            doc=self.owner._document(str(self.dataset.path));doc.plot_signature=None
            self.owner.mdi.setActiveSubWindow(doc);self.owner.document_activated(doc)
            index=next((i for i,c in enumerate(draft) if c.uid==uid),None)
            if index is not None:self.owner.files.setCurrentItem(self.owner.files.topLevelItem(index))
            self.owner.touch();self.owner.redraw();super().accept()
        except ValueError as exc:self.error.setText(str(exc))

    def save(self):
        from .preferences import save_defaults
        try:
            value=validate_template(self.collect());save_defaults("graph","signals",{"signal_defaults":value})
            self.error.clear();self.owner.statusBar().showMessage("信号默认设置已保存。",5000)
        except (ValueError,OSError) as exc:self.error.setText(str(exc))

    def defaults(self):self.load(factory_template(self.dataset));self.error.clear()

    def help(self):self.error.setText("导数采用局部最小二乘，至少5点；窗口默认0时使用最邻近5点。未确认的类型灰显。")
