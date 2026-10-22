"""Native TSigUnitsForm shell with functional TMA dimensional units and origins."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QWidget,QGroupBox,QLabel,QComboBox,QPushButton,QMessageBox
from .dimension_units import validate,dimension_index,affine


class UnitsDialog(QDialog):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.document=owner.active_document();self.curve=owner.current_data_curve()
        self.setObjectName('SigUnitsForm');self.setWindowTitle('单位选择');self.setWindowModality(Qt.WindowModality.WindowModal);self.setFixedSize(638,450)
        self.controls={}
        tree=json.loads((Path(__file__).parent/'assets/classic/units-form.json').read_text(encoding='utf-8'))['tree']
        self.render(tree['children'],self)
        names={'GeneralGroup':'通用','DimensionLabel':'尺寸:','OffsetLabel':'偏移:','TimeLabel':'时间:','TemperatureLabel':'温度:','FrequencyLabel':'频率:','PressureLabel':'压力:'}
        for name,text in names.items():
            if name not in self.controls:continue
            widget=self.controls[name]
            if isinstance(widget,QGroupBox):widget.setTitle(text)
            else:widget.setText(text)
        self.dimension=self.controls['DimensionCombo'];self.offset=self.controls['OffsetCombo']
        self.dimension.clear()
        for value in ('mm','µm','%','µm/m','ppm'):self.dimension.addItem(value,value)
        self.offset.clear()
        for text,value in (('无偏移','none'),('零尺寸','zero_size'),('25°C处尺寸','at25')):self.offset.addItem(text,value)
        self.original=validate(self.curve.unit_options);self.index=dimension_index(self.curve.dataset)
        self.dimension_eligible=self.index is not None
        self.eligible=self.dimension_eligible
        self.dimension.setEnabled(self.dimension_eligible);self.offset.setEnabled(self.dimension_eligible)
        initial=self.original['dimension']
        if initial=='source' and self.index is not None:initial=self.curve.dataset.signals[self.index].unit.replace('μ','µ').replace('um','µm')
        self.initial_dimension=initial;self.initial_offset=self.original['offset']
        self.dimension.setCurrentIndex(max(0,self.dimension.findData(initial)));self.offset.setCurrentIndex(self.offset.findData(self.initial_offset))
        from .general_units import category,TEMP_ALIASES
        self.general={};self.initial_general={}
        self.controls['GeneralGroup'].setEnabled(True)
        for name,kind,index in (('TimeCombo','time',self.curve.dataset.time_index),('TemperatureCombo','temperature',self.curve.dataset.temperature_index)):
            combo=self.controls[name];self.general[kind]=combo
            for i in range(combo.count()):combo.setItemData(i,combo.itemText(i))
            available=index is not None and category(self.curve.dataset,index)==kind
            combo.setEnabled(available)
            if available:
                combo.setToolTip('按当前显示单位换算；原始数据不变')
                value=affine(self.curve,index)['unit']
                if kind=='temperature':value=TEMP_ALIASES.get(value,value)
                found=combo.findData(value)
                if found<0:combo.addItem(value,value);found=combo.count()-1
                combo.setCurrentIndex(found);self.eligible=True
            else:combo.setCurrentIndex(-1)
            self.initial_general[kind]=combo.currentData()
        self.signatures=self.capture()
        self.mixed=len({(tuple(sorted(validate(c.unit_options).items())),tuple((index,c.dataset.signals[index].unit) for index in (c.dataset.time_index,c.dataset.temperature_index,dimension_index(c.dataset)) if index is not None)) for c in self.members()})>1
        self.error=QLabel(self);self.error.setGeometry(12,392,613,23);self.error.setStyleSheet('color:#a00000')
        for name,text,x,callback in (('OK','确定',192,self.accept),('Save','保存',280,self.save),('Default','默认值',368,self.defaults),('Cancel','取消',456,self.reject),('Help','帮助',544,self.help)):
            button=QPushButton(text,self);button.setObjectName(name);button.setStyleSheet('min-width:0px;');button.setGeometry(x,418,81,25);button.clicked.connect(callback)
            if name=='OK':button.setDefault(True)
            if name in ('Save','Default'):button.setEnabled(self.eligible)
        self.dimension.currentIndexChanged.connect(self.preview);self.offset.currentIndexChanged.connect(self.preview)
        for combo in self.general.values():combo.currentIndexChanged.connect(self.preview)
        self.preview()

    def render(self,nodes,parent):
        for node in nodes:
            kind=node['class'];p=node['props'];caption=p.get('Caption','')
            if kind=='TElGroupBox':
                widget=QGroupBox(caption,parent)
                if node['name'] not in ('TMAGroup','GeneralGroup'):widget.setEnabled(False)
            elif kind=='TElLabel':
                caption={'Heat Flow:':'热流:','Heat Capacity:':'热容:','Difference:':'温差:','Microvolts:':'微伏:',
                    'Weight:':'重量:','Modulus:':'模量:','Compliance:':'柔量:','Viscosity:':'黏度:',
                    'Strain:':'应变:','Coordinate:':'坐标:','Current:':'电流:'}.get(caption,caption)
                widget=QLabel(caption,parent)
            elif kind=='TElComboBox':
                widget=QComboBox(parent);widget.addItems([s.strip() for s in p.get('Items.Strings',[])])
            else:continue
            widget.setObjectName(node['name']);widget.setGeometry(p.get('Left',0),p.get('Top',0),p.get('Width',100),p.get('Height',21))
            self.controls[node['name']]=widget
            if kind=='TElComboBox':
                widget.setEnabled(False);widget.setToolTip('此类单位换算尚未接入');widget.setStyleSheet('QComboBox:disabled {color:#aa9daf;background:#f4eff6;}')
            self.render(node['children'],widget)

    def members(self):
        overlay=self.owner._is_overlay(self.document.key)
        return [c for c in self.owner._document_curves(self.document) if (c.overlay_enabled if overlay else c.normal_enabled)]

    def capture(self):
        return {c.uid:deepcopy(c.unit_options) for c in self.members()}

    def collect(self,for_default=False):
        dimension=self.dimension.currentData() if self.dimension_eligible else self.original['dimension']
        offset=self.offset.currentData() if self.dimension_eligible else self.original['offset']
        if not for_default and not self.mixed and self.original['dimension']=='source' and dimension==self.initial_dimension:dimension='source'
        result={'dimension':dimension,'offset':offset}
        for kind,combo in self.general.items():
            value=combo.currentData()
            if value is None:continue
            if not for_default and not self.mixed and value==self.initial_general[kind]:
                if kind in self.original:result[kind]=self.original[kind]
            else:result[kind]=value
        return validate(result)

    def preview(self):
        if not self.eligible:self.error.setText('当前文件没有已识别的尺寸、时间或温度信号');return
        try:
            proposed=replace(self.curve,unit_options=self.collect());parts=[]
            if self.dimension_eligible:
                spec=affine(proposed,self.index);parts.append(f"尺寸：{spec['unit']}")
                if 'unnormalized fallback' in spec['status']:parts.append('缺非零尺寸，暂用原单位')
                elif 'unavailable' in spec['status']:parts.append('25°C参考不可用')
            for kind,index in (('time',self.curve.dataset.time_index),('temperature',self.curve.dataset.temperature_index)):
                if self.general[kind].isEnabled():parts.append(('时间：' if kind=='time' else '温度：')+affine(proposed,index)['unit'])
            if self.mixed:parts.append('确定后统一当前图单位')
            self.error.setText('；'.join(parts))
        except ValueError as exc:self.error.setText(str(exc))

    def accept(self):
        try:
            if self.owner.active_document() is not self.document or self.capture()!=self.signatures:raise ValueError('当前图或单位设置已变化，请重新打开单位窗口')
            if self.eligible:self.owner.apply_unit_options(self.document,self.collect())
            super().accept()
        except ValueError as exc:self.error.setText(str(exc))

    def save(self):
        from .preferences import save_defaults
        try:save_defaults('units','tma',{'unit_defaults':self.collect(True)});self.error.setText('已保存单位默认设置；当前曲线未改变')
        except (ValueError,OSError) as exc:self.error.setText(str(exc))

    def defaults(self):
        self.dimension.setCurrentIndex(self.dimension.findData('µm'));self.offset.setCurrentIndex(0)
        for kind,value in (('time','min'),('temperature','°C')):
            if self.general[kind].isEnabled():self.general[kind].setCurrentIndex(self.general[kind].findData(value))
        self.preview()

    def help(self):
        QMessageBox.information(self,'单位选择','TMA支持mm、µm、%、µm/m和ppm；%及ppm单位需要非零样品尺寸，缺失时退回未归一化单位。\n零尺寸将原始尺寸加到尺寸变化，25°C参考按当前数据范围内首个相邻采集交点计算；未采集25°C时不校正。\n普通图作用于本文件；叠图作用于配置成员引用的文件，并同步它们的其它图。换算保留原始采集／处理数据和物理偏移，清除相关分析；不同Y单位使用不同轴。保存只写本应用的单位默认设置。\n通用时间支持秒、分、时、天、毫秒；温度支持°C、°F、K。宽度与导数只按比例换算，绝对温度包含零点。其它仪器单位尚未接入；原版作用范围、25°C分支细节仍待运行核对。')
