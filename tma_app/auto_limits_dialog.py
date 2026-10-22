"""Resource-derived338x177 automatic limits, with20px inline feedback."""
from copy import deepcopy
import json
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QGroupBox,QRadioButton,QButtonGroup,QLineEdit,QLabel,QPushButton,QMessageBox
from .auto_limits import family,default_rule,key,validate_rule,anchor,positions,replace_rule


class AutoLimitsDialog(QDialog):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.entry=owner.current_measurement();self.document=owner.active_document()
        self.curve=next(c for c in owner.curves if c.uid==self.entry['curve_id']);self.family=family(self.entry)
        name={'peak':'tautopeakform','onset':'tautoonsetform','step':'tautostepform','signal':'tautosignalchangeform'}[self.family]
        tree=json.loads((Path(__file__).parent/'assets/classic'/f'{name}.json').read_text(encoding='utf-8'))['tree']
        self.setObjectName(tree['name']);self.setWindowTitle('自动界限');self.setWindowModality(Qt.WindowModality.WindowModal);self.setFixedSize(tree['props']['ClientWidth'],197)
        rules=owner.auto_limit_rules();current=default_rule(self.curve,self.entry)
        self.rule=next((deepcopy(r) for r in reversed(rules) if key(r)==key(current)),current)
        self.state_signature=deepcopy(self.entry['interactive']);self.transform=self.curve.result_transform(self.entry['domain'])
        self.processing=(list(self.curve.operations),id(self.curve.working))
        self.groups=[];self.offsets=[]
        for i in range(2):
            group_node=next(c for c in tree['children'] if c['name']==f'Point{i+1}Group');p=group_node['props']
            group=QGroupBox('起点' if i==0 else '止点',self);group.setGeometry(p['Left'],p['Top'],p['Width'],p['Height'])
            buttons=QButtonGroup(self);self.groups.append(buttons)
            for mode,part in (('cursor','Cursor'),('fraction','Fraction') if self.family=='signal' else ('offset','Offset')):
                node=next(c for c in group_node['children'] if c['name']==f'{part}{i+1}Button');q=node['props']
                text='使用当前光标' if mode=='cursor' else ('峰最大偏移:' if self.family=='peak' else '导数分数:' if self.family=='signal' else '拐点偏移:')
                button=QRadioButton(text,group);button.setObjectName(node['name']);button.setGeometry(q['Left'],q['Top'],q['Width'],q['Height']);button.setProperty('mode',mode)
                buttons.addButton(button);button.setChecked(self.rule['endpoints'][i]['mode']==mode)
            node=next(c for c in group_node['children'] if c['name']==f"{'Fraction' if self.family=='signal' else 'Offset'}{i+1}Edit");q=node['props']
            edit=QLineEdit(format(self.rule['endpoints'][i]['offset'],'.15g'),group);edit.setObjectName(node['name']);edit.setGeometry(q['Left'],q['Top'],q['Width'],q['Height']);edit.setToolTip('导数峰高度的比例' if self.family=='signal' else self.curve.x_unit(self.entry['domain']));self.offsets.append(edit)
            buttons.buttonClicked.connect(self.update_enabled)
        for name,text,callback in (('OK','确定',self.accept),('Save','保存',self.save),('Default','默认值',self.defaults) if self.family=='signal' else ('AutoSet','自动设定',self.auto_set),('Cancel','取消',self.reject),('Help','帮助',self.help)):
            node=next(c for c in tree['children'] if c['name']==name);q=node['props'];button=QPushButton(text,self);button.setObjectName(name);button.setStyleSheet('min-width:0px;');button.setGeometry(q['Left'],q['Top'],q['Width'],q['Height']);button.clicked.connect(callback)
            if name=='OK':button.setDefault(True)
        self.error=QLabel(self);self.error.setGeometry(12,175,self.width()-24,20);self.error.setStyleSheet('color:#a00000');self.update_enabled()

    def update_enabled(self):
        for group,edit in zip(self.groups,self.offsets):edit.setEnabled(group.checkedButton().property('mode')!='cursor')

    def collect(self):
        points=[]
        for group,edit in zip(self.groups,self.offsets):
            mode=group.checkedButton().property('mode')
            points.append(dict(mode=mode,offset=float(edit.text()) if mode!='cursor' else 0.))
        return validate_rule(dict(default_rule(self.curve,self.entry),endpoints=points))

    def check_context(self):
        if (self.owner.current_measurement() is not self.entry or self.owner.active_document() is not self.document or
                not any(c is self.curve for c in self.owner.curves) or (list(self.curve.operations),id(self.curve.working))!=self.processing or
                self.entry['interactive']!=self.state_signature or self.curve.result_transform(self.entry['domain'])!=self.transform):raise ValueError('当前选点或曲线已改变，请重新打开自动界限')

    def auto_set(self):
        try:
            self.check_context();reference=anchor(self.curve,self.entry);x,_=self.curve.xy(self.entry['domain'])
            current=self.entry['interactive'].get('positions',self.entry['interactive']['indices'])
            import numpy as np
            for group,edit,position in zip(self.groups,self.offsets,current):
                next(b for b in group.buttons() if b.property('mode')=='offset').setChecked(True)
                edit.setText(format(float(np.interp(position,np.arange(len(x)),x))-reference,'.17g'))
            self.update_enabled();self.error.clear()
        except ValueError as exc:self.error.setText(str(exc))

    def defaults(self):
        for group,edit in zip(self.groups,self.offsets):
            next(b for b in group.buttons() if b.property('mode')=='fraction').setChecked(True);edit.setText('0.05')
        self.update_enabled();self.error.clear()

    def accept(self):
        try:
            self.check_context();rule=self.collect();selected=positions(self.curve,self.entry,rule)
            self.owner.apply_auto_limits(self.entry,rule,selected);super().accept()
        except (ValueError,OverflowError) as exc:self.error.setText(str(exc))

    def save(self):
        from .preferences import load_defaults,save_defaults
        try:
            self.check_context();rule=self.collect();old=load_defaults('analysis')['options'].get('auto_limits_rules',[])
            save_defaults('analysis','auto_limits',{'auto_limits_rules':replace_rule(old,rule)});self.error.setText('已保存本信号模板；当前光标未改变')
        except (ValueError,OSError) as exc:self.error.setText(str(exc))

    def help(self):
        QMessageBox.information(self,'自动界限','使用当前光标保留该端点；峰／始点／步阶偏移以当前X单位计算，自动设定从当前两点计算偏移。\n信号变化使用导数分数，默认0.05：取区间内主要导数峰，在同一连续采集片段中寻找相邻峰各自的分数交点，取两交点的X中点；没有邻峰时用数据端点。导数采用当前X及至少5点局部拟合，峰筛选和分支规则仍待原版运行核对。\n保存只写本分析、本X信号和单位的默认模板，确定后才应用；其它单位不套用。取消不移动光标。手动多切线使用准确界限或恢复初始界限。')
