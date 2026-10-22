"""Manufacturer-sized sample entry and analysis Other page, with inert defaults."""
from __future__ import annotations
import json
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QLabel,QLineEdit,QPushButton,QTabWidget,QWidget,QGroupBox,QCheckBox,QComboBox,QMessageBox
from .alpha import positive,DEFAULT_WIDTH_C


class SampleSizeDialog(QDialog):
    def __init__(self,owner,curve,kind):
        super().__init__(owner);self.owner,self.curve,self.kind=owner,curve,kind;self.document=owner.active_document()
        self.setObjectName('SampleSizeForm');self.setWindowTitle('样品尺寸');self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setFixedSize(282,115)
        label=QLabel('尺寸:',self);label.setGeometry(54,24,38,13)
        label=QLabel('mm',self);label.setGeometry(188,24,40,13)
        self.field=QLineEdit(self);self.field.setObjectName('SizeEdit');self.field.setGeometry(100,20,77,21)
        self.error=QLabel(self);self.error.setGeometry(12,47,258,31);self.error.setWordWrap(True);self.error.setStyleSheet('color:#a00000')
        for name,text,left,callback in (('OK','确定',12,self.accept),('Cancel','取消',100,self.reject),('Help','帮助',188,self.help)):
            button=QPushButton(text,self);button.setObjectName(name);button.setStyleSheet('min-width:0px;');button.setGeometry(left,82,81,25);button.clicked.connect(callback)
            if name=='OK':button.setDefault(True)
        self.field.setFocus()

    def accept(self):
        try:
            value=positive(float(self.field.text()),'样品原始尺寸(mm)')
            if self.owner.active_document() is not self.document or not any(c is self.curve for c in self.owner.visible_curves()):raise ValueError('当前文件已切换，请返回原文件后确认')
            self.owner.apply_sample_size(self.curve,value);super().accept()
            self.owner.start_alpha(self.kind,curve_uid=self.curve.uid)
        except ValueError as exc:self.error.setText(str(exc))

    def help(self):
        QMessageBox.information(self,'样品尺寸','输入实测的非零原始尺寸(mm)。本值随会话保存，所有同源信号共用；原始数据文件保持不变。')


class AnalysisOptionsDialog(QDialog):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner
        self.setObjectName('AnalysisOptionsForm');self.setWindowTitle('分析选项');self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setFixedSize(494,357);self.tabs=QTabWidget(self);self.tabs.setGeometry(1,0,492,297)
        self.controls={}
        tree=json.loads((Path(__file__).parent/'assets/classic/analysis-options-form.json').read_text(encoding='utf-8'))['tree']
        pagecontrol=next(c for c in tree['children'] if c['name']=='PageControl')
        captions={'StepSheet':'步阶/变化','PeakSheet':'峰','AreaSheet':'面积','ResolutionSheet':'分辨率','OtherSheet':'其他'}
        for index,node in enumerate(pagecontrol['children']):
            if node['class']!='TElTabSheet':continue
            page=QWidget();self.render(node['children'],page);i=self.tabs.addTab(page,captions[node['name']])
            self.tabs.setTabEnabled(i,node['name'] in ('OtherSheet','StepSheet','PeakSheet'))
        self.tabs.setCurrentIndex(4)
        translations={'HeatFlowWeightLabel':'修正热流最小重量:','CorrectedSizeBox':'TMA百分比按修正后的样品尺寸计算',
            'SigItterationsBox':'绘制S形基线迭代','AdjustWeightDerivBox':'修改尺寸时调整TGA重量导数',
            'TGAGroup':'TGA步阶变化／重量变化／残余量标签','TGAWeightBox':'重量','TGAPercentBox':'百分比',
            'TGALabelBox':'转变标签','TGALimitsBox':'界限','TGASignedChangeBox':'有符号变化',
            'CurveColorBox':'结果标签使用曲线颜色','NoArrowheadsBox':'结果线不显示箭头'}
        for name,text in translations.items():
            widget=self.controls[name]
            if isinstance(widget,QGroupBox):widget.setTitle(text)
            else:widget.setText(text)
        self.width_field=self.controls['AlphaWindowEdit'];self.width_field.setEnabled(True);self.width_field.setText(format(owner.alpha_width(),'.15g'))
        self.controls['SmoothingWidthLabel'].setEnabled(True);self.controls['SmoothingWidthLabel'].setText('单点Alpha平滑宽度:')
        self.controls['Label13'].setEnabled(True)
        self.controls['SigItterationsBox'].setEnabled(True);self.controls['SigItterationsBox'].setToolTip('新建S形峰积分时绘制中间迭代基线')
        self.controls['SigItterationsBox'].setChecked(owner.sigmoid_iterations())
        self.configure_step_page()
        self.configure_peak_page()
        self.error=QLabel(self);self.error.setGeometry(12,299,470,23);self.error.setStyleSheet('color:#a00000')
        for name,text,left,callback in (('OK','确定',48,self.accept),('Save','保存',136,self.save),('Default','默认值',224,self.defaults),('Cancel','取消',312,self.reject),('Help','帮助',400,self.help)):
            button=QPushButton(text,self);button.setObjectName(name);button.setStyleSheet('min-width:0px;');button.setGeometry(left,325,81,25);button.clicked.connect(callback)
            if name=='OK':button.setDefault(True)

    def render(self,nodes,parent):
        for node in nodes:
            kind=node['class'];p=node['props'];name=node['name'];caption=p.get('Caption','')
            if kind=='TElGroupBox':widget=QGroupBox(caption,parent)
            elif kind=='TElPanel':widget=QWidget(parent)
            elif kind=='TElLabel':widget=QLabel(caption,parent)
            elif kind=='TElEdit':widget=QLineEdit(p.get('Text',''),parent)
            elif kind=='TElCheckBox':widget=QCheckBox(caption,parent)
            elif kind=='TElComboBox':
                widget=QComboBox(parent);widget.addItems(p.get('Items.Strings',[]))
            else:continue
            widget.setObjectName(name);widget.setGeometry(p.get('Left',0),p.get('Top',0),p.get('Width',100),p.get('Height',21))
            self.controls[name]=widget
            self.render(node['children'],widget)
            # Unimplemented parameters are visible evidence, never active no-op controls.
            if kind not in ('TElGroupBox','TElPanel'):
                widget.setEnabled(False);widget.setToolTip('此参数尚未接入')

    def configure_step_page(self):
        names={'StepMidpointLabel':'中点位置:','StepChangeLabel':'变化范围:','AndLabel':'至','StepGroup':'转变标注','ManualStepBox':'手动选择切线',
            'StepOnsetBox':'始点','StepEndBox':'终点','StepChangeBox':'变化','StepLimitsBox':'界限','StepSignedChangeBox':'有符号变化',
            'SignalChangeGroup':'信号变化标注','SignalChangeBox':'变化','SignalChangeYLimitsBox':'Y界限','SignalChangeXLimitsBox':'X界限','SignalChangeSignedBox':'有符号变化'}
        for name,text in names.items():
            widget=self.controls[name]
            if isinstance(widget,QGroupBox):widget.setTitle(text)
            else:widget.setText(text)
            widget.setEnabled(True);widget.setToolTip('')
        self.midpoint=self.controls['MidpointCombo'];self.midpoint.clear()
        for text,value in (('无','none'),('拐点','inflection'),('半高度','half_height'),('半宽度','half_width'),('两条外推切线之间','half_tangents'),('虚拟温度（待接入）','fictive')):
            self.midpoint.addItem(text,value)
        self.midpoint.model().item(self.midpoint.count()-1).setEnabled(False)
        self.start,self.stop=self.controls['StartCombo'],self.controls['StopCombo']
        for combo in (self.start,self.stop):
            combo.clear()
            for text,value in (('起点','start'),('始点','onset'),('中点','midpoint'),('终点','end'),('止点','stop')):combo.addItem(text,value)
            combo.setEnabled(True);combo.setToolTip('')
        self.midpoint.setEnabled(True);self.midpoint.setToolTip('')
        self.step_boxes={'limits':'StepLimitsBox','onset':'StepOnsetBox','end':'StepEndBox','change':'StepChangeBox','signed':'StepSignedChangeBox'}
        self.signal_boxes={'x_limits':'SignalChangeXLimitsBox','y_limits':'SignalChangeYLimitsBox','change':'SignalChangeBox','signed':'SignalChangeSignedBox'}
        self.load_step(self.owner.transition_options(),self.owner.signal_change_settings())
        self.controls['StepDeltaCpBox'].setText('ΔCp')
        self.controls['StepSignedDeltaCpBox'].setText('有符号ΔCp')

    def load_step(self,config,signal):
        self.controls['ManualStepBox'].setChecked(config['manual'])
        for box,key in ((self.midpoint,'midpoint'),(self.start,'start'),(self.stop,'stop')):box.setCurrentIndex(box.findData(config[key]))
        for key,name in self.step_boxes.items():self.controls[name].setChecked(config['labels'][key])
        for key,name in self.signal_boxes.items():self.controls[name].setChecked(signal[key])

    def step_value(self):
        from .transitions import validate,validate_signal
        config=validate(dict(manual=self.controls['ManualStepBox'].isChecked(),midpoint=self.midpoint.currentData(),start=self.start.currentData(),stop=self.stop.currentData(),labels={key:self.controls[name].isChecked() for key,name in self.step_boxes.items()}))
        signal=validate_signal({key:self.controls[name].isChecked() for key,name in self.signal_boxes.items()})
        return dict(transition_options=config,signal_change_options=signal)

    def configure_peak_page(self):
        names={'ManualOnsetBox':'手动选择始点切线','InflectionBox':'始点取拐点','OnsetGroup':'始点标注','PeakGroup':'峰标注',
            'XAxisBox':'X轴','YAxisBox':'Y轴','TimeBox':'时间','TempBox':'温度','XSignalBox':'X信号','PeakLimitsBox':'界限',
            'HeightBox':'高度','WidthBox':'半高宽','MaximumLabel':'最大值:'}
        for name,text in names.items():
            widget=self.controls[name]
            if isinstance(widget,QGroupBox):widget.setTitle(text)
            else:widget.setText(text)
            widget.setEnabled(True);widget.setToolTip('')
        for name,text in (('AreaBox','面积'),('NormalizedBox','归一化面积'),('SignedAreaBox','有符号面积'),('WeightLabel','重量:'),('PeakOnsetLabel','峰始点自变量:')):self.controls[name].setText(text)
        self.controls['AreaBox'].setEnabled(True);self.controls['AreaBox'].setToolTip('线性峰积分：尺寸信号对实际采集时间的面积')
        self.controls['AreaBox'].setChecked(self.owner.integration_options()['area'])
        for name in ('OnsetVersusCombo','IntWeightCombo'):
            self.controls[name].clear();self.controls[name].addItem('无')
        self.maximum=self.controls['MaximumCombo'];self.maximum.clear()
        for text,value in (('无','none'),('时间','time'),('温度','temperature'),('X信号','signal')):self.maximum.addItem(text,value)
        self.maximum.setEnabled(True);self.maximum.setToolTip('')
        curve=self.owner.current_data_curve()
        if curve is not None:
            for kind,index in (('time',curve.dataset.time_index),('temperature',curve.dataset.temperature_index),('signal',curve.x_signal_index)):
                available=index is not None
                self.maximum.model().item(self.maximum.findData(kind)).setEnabled(available)
                box=self.controls[dict(time='TimeBox',temperature='TempBox',signal='XSignalBox')[kind]]
                box.setEnabled(available)
                if not available:box.setToolTip('当前文件没有此标注信号；选项仍为其它文件保留')
        self.onset_boxes={'x':'XAxisBox','y':'YAxisBox','time':'TimeBox','temperature':'TempBox','signal':'XSignalBox'}
        self.peak_boxes={'limits':'PeakLimitsBox','height':'HeightBox','width':'WidthBox'}
        self.load_peak(self.owner.peak_onset_options())
        self.controls['ManualOnsetBox'].toggled.connect(self.update_onset_mode)
        self.update_onset_mode()

    def update_onset_mode(self):self.controls['InflectionBox'].setEnabled(not self.controls['ManualOnsetBox'].isChecked())

    def load_peak(self,config):
        onset,peak=config['onset'],config['peak']
        self.controls['ManualOnsetBox'].setChecked(onset['manual']);self.controls['InflectionBox'].setChecked(onset['inflection'])
        for key,name in self.onset_boxes.items():self.controls[name].setChecked(onset['labels'][key])
        for key,name in self.peak_boxes.items():self.controls[name].setChecked(peak[key])
        self.maximum.setCurrentIndex(self.maximum.findData(peak['maximum']))

    def peak_value(self):
        from .peak_onset import validate
        return validate(dict(onset=dict(manual=self.controls['ManualOnsetBox'].isChecked(),inflection=self.controls['InflectionBox'].isChecked(),labels={key:self.controls[name].isChecked() for key,name in self.onset_boxes.items()}),peak=dict({key:self.controls[name].isChecked() for key,name in self.peak_boxes.items()},maximum=self.maximum.currentData())))

    def value(self):return positive(float(self.width_field.text()),'单点Alpha窗口(°C)')

    def accept(self):
        from .workspace import default_plot_options
        try:value=self.value();step=self.step_value();peak=self.peak_value()
        except ValueError as exc:self.error.setText(str(exc));return
        self.owner.plot_options.setdefault('__settings__',default_plot_options()).update(alpha_smoothing_width=value,sigmoid_iterations=self.controls['SigItterationsBox'].isChecked(),peak_onset_options=peak,integration_options=dict(area=self.controls['AreaBox'].isChecked()),**step)
        self.owner.touch();super().accept()

    def save(self):
        from .preferences import save_defaults
        try:
            if self.tabs.currentIndex()==0:save_defaults('analysis','step',self.step_value());self.error.setText('已保存本页步阶／信号变化默认设置')
            elif self.tabs.currentIndex()==1:save_defaults('analysis','peak',{'peak_onset_options':self.peak_value(),'integration_options':dict(area=self.controls['AreaBox'].isChecked())});self.error.setText('已保存本页峰／始点／积分默认设置')
            else:save_defaults('analysis','other',{'alpha_smoothing_width':self.value(),'sigmoid_iterations':self.controls['SigItterationsBox'].isChecked()});self.error.setText('已保存本页Alpha宽度及S形基线迭代显示')
        except (ValueError,OSError) as exc:self.error.setText(str(exc))

    def defaults(self):
        if self.tabs.currentIndex()==0:
            from .transitions import defaults,signal_defaults
            self.load_step(defaults(),signal_defaults())
        elif self.tabs.currentIndex()==1:
            from .peak_onset import defaults
            self.load_peak(defaults());self.update_onset_mode()
            from .peak_integration import defaults as integration_defaults
            self.controls['AreaBox'].setChecked(integration_defaults()['area'])
        else:self.width_field.setText(format(DEFAULT_WIDTH_C,'g'));self.controls['SigItterationsBox'].setChecked(False)
        self.error.clear()

    def help(self):
        QMessageBox.information(self,'分析选项','峰最大相对于两端直线基线求最大绝对偏离；始点支持两点自动或四点手动切线。自动拐点／基线取窗的精确原版规则仍待核对，手动模式忽略拐点选项。直线及水平S形峰积分均以实际时间计算；S形基线最多迭代10次，面积相对前次变化不超过1%后接受。绘制迭代仅影响新分析的参数快照；热量归一化、有符号热量及SDT重量尚未接入。\n步阶／玻璃化转变支持自动两点或手动六点三切线。自动采用外侧20%基线及中部最陡局部拟合；该取窗规则尚未证明与原版一致。虚拟温度及Delta Cp尚未接入。保存／默认值只作用于当前页，确定应用已实现的所有页面；新分析复制参数，既有结果不变。\n单点Alpha在标记温度附近的指定温度宽度内作最小二乘直线拟合；窗口在采集界限和数据间隙处截断。至少需要2个不同温度的采集点。\n保存只写本页的默认宽度和S形迭代显示；确定设置本工作区以后新建的分析。已有结果保留各自参数。应用默认10°C，厂家默认值及窗口边界细节尚待运行核对。')
