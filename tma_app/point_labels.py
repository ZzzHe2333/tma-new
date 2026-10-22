"""Curve-value labels use recorded channel definitions and acquisition positions."""
from copy import deepcopy
from dataclasses import replace
import math
import numpy as np

CURVE_VALUE_KINDS=("curve_value","curve_value_y")


def default_options():
    return dict(time=False,temperature=True,signal=False,y=True,multiplex=False,arrow=True,cross=True,border=False,transparent=True)


def validate_options(options):
    if not isinstance(options,dict) or set(options)!=set(default_options()) or any(type(v) is not bool for v in options.values()):raise ValueError("标记点选项必须为明确的勾选状态")
    if options["multiplex"]:raise ValueError("尚未识别此文件的多频标注参数")
    return dict(options)


def signal_snapshot(curve):
    if curve.x_signal_index is None:return None
    return dict(index=curve.x_signal_index,type=curve.x_signal_type,width=curve.x_smooth_width,label=curve.x_label("signal"),unit=curve.x_unit("signal"))


def validate_signal(snapshot,dataset):
    if snapshot is None:return None
    from .signal_processing import KINDS
    if not isinstance(snapshot,dict) or set(snapshot)!={"index","type","width","label","unit"}:raise ValueError("标记点信号来源字段无效")
    if type(snapshot["index"]) is not int or not 0<=snapshot["index"]<len(dataset.signals) or snapshot["type"] not in KINDS:raise ValueError("标记点信号来源无效")
    width=snapshot["width"]
    if isinstance(width,bool) or not isinstance(width,(int,float)) or not math.isfinite(width) or width<0:raise ValueError("标记点信号窗口无效")
    if any(not isinstance(snapshot[k],str) or len(snapshot[k])>4096 for k in ("label","unit")):raise ValueError("标记点信号名称或单位无效")
    return deepcopy(snapshot)


def channels(curve,entry):
    """Compute vectors once per editor, not on every mouse movement."""
    output={};error=None
    for key,index in (("time",curve.dataset.time_index),("temperature",curve.dataset.temperature_index)):
        if index is not None:output[key]=dict(values=curve.x_values(key),unit=curve.x_unit(key))
    config=validate_signal(entry.get("point_signal"),curve.dataset)
    if config is not None:
        reference=replace(curve,x_signal_index=config["index"],x_signal_type=config["type"],x_smooth_width=config["width"])
        try:output["signal"]=dict(values=reference.x_values("signal"),unit=config["unit"],label=config["label"])
        except ValueError as exc:error=str(exc)
    return output,error


def channel_values(channels,position):
    values={}
    for key,channel in channels.items():
        data=channel["values"];left=int(position);right=min(left+1,len(data)-1);fraction=position-left
        value=float(data[left]+fraction*(data[right]-data[left]))
        if not np.isfinite(value):raise ValueError("标记点通道值超出有限数值范围")
        values[key+"_at_point"]=value;values[key+"_unit"]=channel["unit"]
        if key=="signal":values["label_signal"]=channel["label"]
    return values


def label_text(entry,unit):
    from .legacy_t1_t2_h import format_plot_temp_c
    options=validate_options(entry["annotation"]["point_label"]);values=entry["values"];lines=[]
    if options["time"] and "time_at_point" in values:lines.append(f"t = {values['time_at_point']:.6g} {values['time_unit']}")
    if options["temperature"] and "temperature_at_point" in values:lines.append(f"T = {format_plot_temp_c(values['temperature_at_point'])} {values['temperature_unit']}")
    if options["signal"] and "signal_at_point" in values:lines.append(f"{values['label_signal']} = {values['signal_at_point']:.6g}")
    if options["y"]:lines.append(f"Y = {values['start_y']:.6g} {unit}")
    return "\n".join(lines)
