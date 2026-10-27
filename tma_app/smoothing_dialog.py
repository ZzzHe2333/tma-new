"""Physical smoothing window matching the local TSmoothForm layout."""
from PySide6.QtWidgets import QDialog,QLabel,QLineEdit,QCheckBox,QPushButton
from .data_limits import smoothed_state
from .calculation import BACKGROUND_POINTS
from .calculation_jobs import CalculationDialogMixin


def smoothing_variable(curve,display):
    if curve.y_type not in ("normal","custom"):return "time" if curve.y_type.endswith("time") else "temperature"
    derivative=next((op.split(":",1)[1] for op in reversed(curve.operations) if op.startswith("derivative:")),None)
    if derivative:
        for domain,index in (("time",curve.dataset.time_index),("temperature",curve.dataset.temperature_index)):
            if index is not None and curve.dataset.signals[index].label==derivative:return domain
        if curve.x_signal_index is not None and curve.x_label("signal")==derivative:return "signal"
        raise ValueError("此处理曲线的求导自变量未确定，请使用通用处理入口")
    return display


class SmoothDialog(CalculationDialogMixin,QDialog):
    def __init__(self,owner,curve):
        super().__init__(owner);self.owner,self.curve=owner,curve
        self.domain=smoothing_variable(curve,owner.domain)
        self.setObjectName("SmoothForm");self.setWindowTitle(f"平滑曲线 — Y{curve.axis+1} · {curve.dataset.path.name}")
        self.setFixedSize(370,131);self.setModal(True)
        label=QLabel("平滑区域宽度:",self);label.setGeometry(60,12,123,20)
        compatible=curve.smooth_domain in (None,self.domain)
        if self.domain=="signal" and curve.smooth_x_config is not None:
            compatible=compatible and curve.smooth_x_config=={"index":curve.x_signal_index,"type":curve.x_signal_type,"width":curve.x_smooth_width}
        value=curve.smooth_width if compatible else 0.
        self.width_edit=QLineEdit(format(value,".15g"),self);self.width_edit.setGeometry(184,8,73,23)
        self.units=QLabel(curve.x_unit(self.domain),self);self.units.setGeometry(267,12,95,20)
        self.reuse=QCheckBox("对新文件／新数据界限复用",self);self.reuse.setGeometry(60,44,265,20)
        self.reuse.setChecked(curve.smooth_reuse and compatible)
        self.error=QLabel(self);self.error.setGeometry(12,71,346,22);self.error.setStyleSheet("color:#a00000")
        for text,x,callback in (("确定",12,self.accept),("默认值",100,self.defaults),("取消",188,self.reject),("帮助",276,self.help)):
            button=QPushButton(text,self);button.setGeometry(x,100,81,25);button.clicked.connect(callback)
            if text=="确定":button.setDefault(True)

    def accept(self):
        if self.job is not None:return
        try:
            if not any(c is self.curve for c in self.owner.curves):raise ValueError("此曲线已移除")
            width=float(self.width_edit.text())
            if self.curve.sample_count>=BACKGROUND_POINTS:
                peers=[c for c in self.owner.curves if c.dataset.document_key==self.curve.dataset.document_key]
                self._calculation_reuse=self.reuse.isChecked()
                self.start_calculation(peers,dict(kind='smooth',uid=self.curve.uid,domain=self.domain,width=width),self.apply_values)
                return
            values=smoothed_state(self.curve,self.domain,width,use_saved_x=False)
            self._calculation_reuse=self.reuse.isChecked()
            self.apply_values(values)
        except (ValueError,OverflowError) as exc:self.error.setText(str(exc));self.error.setToolTip(str(exc))

    def apply_values(self,values):
        self.owner.cancel_measurement(redraw=False);self.curve.checkpoint()
        for key,value in values.items():setattr(self.curve,key,value)
        self.curve.smooth_reuse=self._calculation_reuse
        self.owner.remember_smoothing(self.curve)
        self.owner.touch();self.owner.refresh_curve(self.curve.uid)
        super().accept()

    def defaults(self):self.width_edit.setText("0");self.reuse.setChecked(False);self.error.clear()

    def help(self):self.error.setText("正常曲线宽度0不平滑；导数至少使用5点。")
