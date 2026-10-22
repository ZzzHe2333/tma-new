"""Curve state and portable, non-executable session files."""
from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile
import uuid

import numpy as np

from .reader import Dataset, Signal
from .overlay_settings import default_auto_styles, default_auto_configure, validate_auto_styles, validate_auto_configure

PALETTE = ["#2974e5", "#e17b32", "#159d87", "#995bd5", "#d6537a", "#8b9b36", "#328eaa", "#ad6d50"]
CURVE_FIELDS = ("y_index", "axis", "color", "visible", "width", "style", "x_shift", "scale", "offset", "operations",
                "marker", "legend_text", "show_legend", "overlay_enabled", "uid", "appearance_mode", "normal_appearance", "overlay_appearance",
                "display_filename", "show_legend_text", "normal_enabled", "y_type", "smooth_width", "x_signal_index", "x_signal_type", "x_smooth_width",
                "data_indices", "data_limit_spec", "reset_time", "smooth_domain", "smooth_reuse", "smooth_base_ops","smooth_x_config","working_rows","smooth_source_rows",
                "overlay_views","active_overlay_key","normal_view_details","sample_size_mm","file_info","unit_options","derived","mass_normalization_mg")
CURVE_OPTION_DEFAULTS = {"marker": "", "legend_text": "", "show_legend": True, "overlay_enabled": True,
                         "appearance_mode": "normal", "normal_appearance": None, "overlay_appearance": None,
                         "display_filename": None, "show_legend_text": True, "normal_enabled": True,
                         "y_type": "normal", "smooth_width": 0., "x_signal_index": None, "x_signal_type": "normal", "x_smooth_width": 0.,
                         "data_indices":None,"data_limit_spec":None,"reset_time":False,"smooth_domain":None,"smooth_reuse":False,"smooth_base_ops":[],"smooth_x_config":None,"working_rows":None,"smooth_source_rows":None,
                         "overlay_views":{},"active_overlay_key":None,"normal_view_details":None,"sample_size_mm":None,"file_info":{},"unit_options":None,"derived":None,"mass_normalization_mg":None}
APPEARANCE_FIELDS = ("style", "color", "marker", "width", "offset")


def _text(value, label, maximum=4096):
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"{label} 必须是长度不超过 {maximum} 的字符串")
    return value


def _number(value, label):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(f"{label} 必须是有限实数")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label} 必须是有限实数") from exc
    if not np.isfinite(result):
        raise ValueError(f"{label} 必须是有限实数")
    return result


def _boolean(value, label):
    if type(value) is not bool:
        raise ValueError(f"{label} 必须是布尔值")
    return value


def _limits(value, label):
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{label} 必须是两个递增的有限实数或空值")
    low, high = [_number(v, label) for v in value]
    if low >= high:
        raise ValueError(f"{label} 必须递增")
    return [low, high]


def default_plot_options():
    """Return independent defaults for one document, suitable for JSON storage."""
    from .point_labels import default_options
    return {"title": "", "x_label": "", "y_labels": ["", "", "", ""],
            "legend": None, "legend_location": "best", "grid_x": False, "grid_y": False,
            "grid_minor": False, "auto_x": True, "auto_y": [True, True, True, True],
            "x_limits": None, "y_limits": [None, None, None, None],
            "x_ticks": None, "y_ticks": [None, None, None, None],
            "graph_axis_visible": [True]*4, "graph_grid_types": [0]*4,
            "graph_symbol_spacing": ["medium"]*4, "graph_show_symbols": [True]*4,
            "graph_symbol_differentiate": "axes",
            "legend_border": False, "legend_color": True, "legend_text": True,
            "legend_line": True, "legend_file": False, "legend_symbol": True,
            "overlay_auto": default_auto_styles(), "overlay_configure": default_auto_configure(),
            "axis_flags": [{"line": False, "color": False, "symbol": False} for _ in range(4)],
            "export_title": "", "export_align": "left", "window_name": "", "mass_normalization_titles": None,
            "legend_anchor": None, "x_domain": None, "secondary_x": False, "signal_defaults": None,"smoothing_rules":[],"overlay_members":None,"axis_x_offsets":[0.]*4,"point_label_options":default_options(),"alpha_smoothing_width":None,"unit_defaults":None,"transition_options":None,"signal_change_options":None,"peak_onset_options":None,"integration_options":None,"sigmoid_iterations":None,"auto_limits_rules":[]}


def _ticks(value, label):
    if value is None: return None
    if not isinstance(value, dict): raise ValueError(f"{label} 刻度设置无效")
    result = {key: _number(value.get(key), label) for key in ("label_interval", "tick_interval", "label_offset")}
    if result["label_interval"] <= 0 or result["tick_interval"] <= 0:
        raise ValueError("标值间隔、刻度间隔必须大于零")
    if result["tick_interval"] > result["label_interval"]:
        raise ValueError("刻度间隔不能大于标值间隔")
    return result


def validate_plot_options(options):
    """Validate one document's settings and return a complete independent dict.

    Unknown settings are ignored for forward compatibility. Known settings are
    strict: in particular numbers and strings do not stand in for booleans.
    """
    if not isinstance(options, dict):
        raise ValueError("绘图设置必须是字典")
    result = default_plot_options()
    for key in result:
        if key not in options:
            continue
        value = options[key]
        if key == "x_domain":
            if value not in (None, "temperature", "time", "signal"): raise ValueError("X信号类型无效")
            result[key] = value
        elif key == "secondary_x": result[key] = _boolean(value, key)
        elif key == "signal_defaults":
            from .signal_processing import validate_template
            result[key] = None if value is None else validate_template(value)
        elif key=="smoothing_rules":
            from .data_limits import validate_rules
            result[key]=validate_rules(value)
        elif key=="overlay_members":
            if value is not None and (not isinstance(value,list) or len(value)>10000 or any(not isinstance(uid,str) or not re.fullmatch(r"[0-9a-f]{32}",uid) for uid in value) or len(set(value))!=len(value)):raise ValueError("叠图成员列表无效")
            result[key]=deepcopy(value)
        elif key in ("title", "x_label", "export_title"):
            result[key] = _text(value, key)
        elif key == "window_name": result[key] = _text(value, key, maximum=80)
        elif key == "mass_normalization_titles":
            if value is not None and (not isinstance(value,dict) or set(value)!={'title','window_name','export_title'}):raise ValueError('统一化原始标题无效')
            result[key]=None if value is None else {name:_text(text,name,80 if name=='window_name' else 4096) for name,text in value.items()}
        elif key == "export_align":
            if value not in ("left", "center", "right"): raise ValueError("绘图标题对齐方式无效")
            result[key] = value
        elif key == "y_labels":
            if not isinstance(value, (list, tuple)) or len(value) != 4:
                raise ValueError("y_labels 必须包含四个字符串")
            result[key] = [_text(v, key) for v in value]
        elif key == "legend":
            result[key] = None if value is None else _boolean(value, key)
        elif key == "legend_location":
            if value not in ("best", "upper right", "upper left", "lower right", "lower left"):
                raise ValueError("无效的图例位置")
            result[key] = value
        elif key == "legend_anchor":
            if value is None: result[key] = None
            else:
                if not isinstance(value, dict) or set(value) != {"x", "y", "horizontal", "vertical"}:
                    raise ValueError("图例位置字段无效")
                x, y = _number(value["x"], "图例X位置"), _number(value["y"], "图例Y位置")
                if not 0 <= x <= 1 or not 0 <= y <= 1: raise ValueError("图例位置必须在0到1之间")
                if value["horizontal"] not in ("left", "center", "right") or value["vertical"] not in ("top", "center", "bottom"):
                    raise ValueError("图例定位点无效")
                result[key] = dict(value, x=x, y=y)
        elif key == "overlay_auto": result[key] = validate_auto_styles(value)
        elif key == "overlay_configure": result[key] = validate_auto_configure(value)
        elif key == "axis_flags":
            if not isinstance(value, (list, tuple)) or len(value) != 4 or any(not isinstance(v, dict) or set(v) != {"line", "color", "symbol"} for v in value):
                raise ValueError("坐标轴样式标识无效")
            result[key] = [{name: _boolean(item, name) for name, item in flags.items()} for flags in value]
        elif key=="axis_x_offsets":
            if not isinstance(value,(list,tuple)) or len(value)!=4:raise ValueError("X偏移必须包含四个坐标轴数值")
            result[key]=[_number(item,"X偏移") for item in value]
        elif key=="unit_defaults":
            from .dimension_units import validate as validate_units
            result[key]=None if value is None else validate_units(value)
        elif key=='peak_onset_options':
            from .peak_onset import validate
            result[key]=None if value is None else validate(value)
        elif key=='sigmoid_iterations':
            result[key]=None if value is None else _boolean(value,'S形基线迭代显示')
        elif key=='integration_options':
            from .peak_integration import validate
            result[key]=None if value is None else validate(value)
        elif key=='auto_limits_rules':
            from .auto_limits import validate_rules
            result[key]=validate_rules(value)
        elif key in ('transition_options','signal_change_options'):
            from .transitions import validate,validate_signal
            result[key]=None if value is None else (validate(value) if key=='transition_options' else validate_signal(value))
        elif key=="alpha_smoothing_width":
            from .alpha import positive
            result[key]=None if value is None else positive(value,"单点Alpha窗口")
        elif key=="point_label_options":
            from .point_labels import validate_options
            result[key]=validate_options(value)
        elif key in ("grid_x", "grid_y", "grid_minor", "auto_x", "legend_border", "legend_color", "legend_text", "legend_line", "legend_file", "legend_symbol"):
            result[key] = _boolean(value, key)
        elif key in ("graph_axis_visible", "graph_show_symbols"):
            if not isinstance(value, (list, tuple)) or len(value) != 4:
                raise ValueError(f"{key} 必须包含四个布尔值")
            result[key] = [_boolean(v, key) for v in value]
        elif key in ("graph_grid_types", "graph_symbol_spacing"):
            allowed = (0, 1, 2) if key == "graph_grid_types" else ("coarse", "medium", "fine", "every")
            if not isinstance(value, (list, tuple)) or len(value) != 4 or any(isinstance(v, bool) or v not in allowed for v in value):
                raise ValueError(f"{key} 设置无效")
            if key == "graph_grid_types" and any(type(v) is not int for v in value):
                raise ValueError("网格类型必须是整数")
            result[key] = list(value)
        elif key == "graph_symbol_differentiate":
            if value not in ("axes", "curves"): raise ValueError("符号区分方式无效")
            result[key] = value
        elif key == "auto_y":
            if not isinstance(value, (list, tuple)) or len(value) != 4:
                raise ValueError("auto_y 必须包含四个布尔值")
            result[key] = [_boolean(v, key) for v in value]
        elif key == "x_limits":
            result[key] = _limits(value, key)
        elif key == "y_limits":
            if not isinstance(value, (list, tuple)) or len(value) != 4:
                raise ValueError("y_limits 必须包含四组范围或空值")
            result[key] = [_limits(v, key) for v in value]
        elif key == "x_ticks":
            result[key] = _ticks(value, key)
        elif key == "y_ticks":
            if not isinstance(value, (list, tuple)) or len(value) != 4:
                raise ValueError("y_ticks 必须包含四组刻度设置")
            result[key] = [_ticks(v, key) for v in value]
    for limits, ticks in [(result["x_limits"], result["x_ticks"])] + list(zip(result["y_limits"], result["y_ticks"])):
        if limits is not None and ticks is not None:
            span = limits[1] - limits[0]
            if not np.isfinite(span) or span / ticks["tick_interval"] > 1000:
                raise ValueError("刻度过密，请增大刻度间隔（每轴最多 1000 个刻度）")
    return result


def _plot_options_mapping(options):
    if options is None:
        return {}
    if not isinstance(options, dict):
        raise ValueError("文档绘图设置必须是字典")
    result = {}
    for key, value in options.items():
        _text(key, "文档键", maximum=32768)
        if not key:
            raise ValueError("文档键不能为空")
        result[key] = validate_plot_options(value)
    return result


def _validate_curve_state(state, signal_count, sample_count=None):
    derived=state.get('derived')
    if derived is not None:
        if not isinstance(derived,dict) or not isinstance(derived.get('positions'),list) or len(derived['positions'])<2:raise ValueError('派生积分描述无效')
        sample_count=len(derived['positions'])
    from .overlay_views import validate_views,validate_details,overlay_key
    state["overlay_views"]=validate_views(state["overlay_views"])
    if state['mass_normalization_mg'] is not None:
        from .mass_normalization import validate_mass
        validate_mass(state['mass_normalization_mg'])
    if state["active_overlay_key"] is not None and not overlay_key(state["active_overlay_key"]):raise ValueError("当前叠图窗口键无效")
    if state["normal_view_details"] is not None:validate_details(state["normal_view_details"])
    if not isinstance(state["uid"], str) or not re.fullmatch(r"[0-9a-f]{32}", state["uid"]):
        raise ValueError("会话曲线标识无效")
    if (type(state["y_index"]) is not int or type(state["axis"]) is not int
            or not 0 <= state["y_index"] < signal_count or not 0 <= state["axis"] < 4):
        raise ValueError("会话信号/坐标轴索引无效")
    if state["style"] not in ("-", "--", "-.", ":", "None", "long_dash", "broken_dash", "broken_double_dash"):
        raise ValueError("会话线型无效")
    if not isinstance(state["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", state["color"]):
        raise ValueError("会话曲线颜色必须是 #RRGGBB")
    if state["marker"] not in ("", "o", "s", "^", "v", "+", "x", ".", "D"):
        raise ValueError("会话点样式无效")
    _text(state["legend_text"], "图例文字")
    _text(state["display_filename"], "显示文件名")
    for key in ("visible", "show_legend", "overlay_enabled", "show_legend_text", "normal_enabled", "reset_time", "smooth_reuse"):
        _boolean(state[key], key)
    for row_key in ("data_indices","working_rows","smooth_source_rows"):
        rows=state[row_key]
        if rows is not None and (not isinstance(rows,list) or (len(rows)<2 and not (derived is not None and row_key=='data_indices' and rows==[])) or any(type(v) is not int or v<0 or (sample_count is not None and v>=sample_count) for v in rows) or any(b<=a for a,b in zip(rows,rows[1:]))):raise ValueError("采集数据行范围无效")
    if state["smooth_domain"] not in (None,"temperature","time","signal"):raise ValueError("平滑自变量无效")
    config=state["smooth_x_config"]
    if config is not None:
        if not isinstance(config,dict) or set(config)!={"index","type","width"} or type(config["index"]) is not int or not 0<=config["index"]<signal_count:raise ValueError("平滑X信号设置无效")
        from .signal_processing import KINDS
        if config["type"] not in KINDS or _number(config["width"],"平滑X窗口")<0:raise ValueError("平滑X信号设置无效")
    if not isinstance(state["smooth_base_ops"],list) or len(state["smooth_base_ops"])>10000:raise ValueError("平滑来源记录无效")
    for value in state["smooth_base_ops"]:_text(value,"平滑来源记录")
    spec=state["data_limit_spec"]
    if isinstance(spec,dict) and spec.get("kind")=="cursor":
        from .data_limits import cursor_spec_rows
        rows=cursor_spec_rows(spec,sample_count)
        expected=None if len(rows)==sample_count else rows
        if state["data_indices"]!=expected or state["reset_time"]!=spec["reset_time"]:raise ValueError("光标界限与数据采集范围不一致")
    elif spec is not None:
        if not isinstance(spec,dict) or set(spec)!={"kind","start","stop","delay","all_cycles","reset_time"} or spec["kind"] not in ("time","temperature","cycle"):raise ValueError("数据界限设置无效")
        for key in ("start","stop","delay"):_number(spec[key],key)
        if spec["delay"]<0:raise ValueError("延迟时间不能为负数")
        for key in ("all_cycles","reset_time"):_boolean(spec[key],key)
    from .signal_processing import KINDS
    if state["y_type"] not in KINDS+("custom",) or state["x_signal_type"] not in KINDS: raise ValueError("信号类型无效")
    if derived is not None and state['y_type'] not in ('normal','custom'):raise ValueError('派生积分信号类型无效')
    from .file_information import validate_text_overrides
    validate_text_overrides(state["file_info"])
    from .dimension_units import validate as validate_units
    validate_units(state["unit_options"])
    if state["sample_size_mm"] is not None:
        from .file_information import nonnegative_size
        nonnegative_size(state["sample_size_mm"])
    for key in ("smooth_width", "x_smooth_width"):
        if _number(state[key], key) < 0: raise ValueError("平滑宽度不能为负数")
    if state["x_signal_index"] is not None and (type(state["x_signal_index"]) is not int or not 0 <= state["x_signal_index"] < signal_count): raise ValueError("X信号索引无效")
    for key in ("width", "x_shift", "scale", "offset"):
        _number(state[key], key)
    if state["width"] <= 0:
        raise ValueError("会话曲线宽度必须大于零")
    operations = state["operations"]
    if not isinstance(operations, list) or len(operations) > 10000:
        raise ValueError("会话处理记录无效")
    for operation in operations:
        _text(operation, "处理记录")
    if state["appearance_mode"] not in ("normal", "overlay"): raise ValueError("曲线显示模式无效")
    for name in ("normal_appearance", "overlay_appearance"):
        value = state[name]
        if value is None: continue
        if not isinstance(value, dict) or set(value) != set(APPEARANCE_FIELDS): raise ValueError("曲线视图样式无效")
        if value["style"] not in ("-", "--", "-.", ":", "None", "long_dash", "broken_dash", "broken_double_dash"): raise ValueError("曲线视图线型无效")
        if not isinstance(value["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value["color"]): raise ValueError("曲线视图颜色无效")
        if value["marker"] not in ("", "o", "s", "^", "v", "+", "x", ".", "D"): raise ValueError("曲线视图符号无效")
        if _number(value["width"], "线宽") <= 0: raise ValueError("曲线视图线宽必须大于零")
        _number(value["offset"], "偏移")


@dataclass(eq=False)
class Curve:
    dataset: Dataset
    y_index: int = 2
    axis: int = 0
    color: str = PALETTE[0]
    visible: bool = True
    width: float = 1.8
    style: str = "-"
    x_shift: float = 0.0
    scale: float = 1.0
    offset: float = 0.0
    working: np.ndarray | None = None
    operations: list[str] = field(default_factory=list)
    marker: str = ""
    legend_text: str | None = None
    show_legend: bool = True
    overlay_enabled: bool = True
    uid: str = field(default_factory=lambda: uuid.uuid4().hex)
    appearance_mode: str = "normal"
    normal_appearance: dict | None = None
    overlay_appearance: dict | None = None
    display_filename: str | None = None
    show_legend_text: bool = True
    normal_enabled: bool = True
    y_type: str = "normal"
    smooth_width: float = 0.
    x_signal_index: int | None = None
    x_signal_type: str = "normal"
    x_smooth_width: float = 0.
    data_indices: list | None = None
    data_limit_spec: dict | None = None
    reset_time: bool = False
    smooth_domain: str | None = None
    smooth_reuse: bool = False
    smooth_base_ops: list = field(default_factory=list)
    smooth_source: np.ndarray | None = field(default=None,repr=False)
    smooth_x_config: dict | None = None
    working_rows: list | None = None
    smooth_source_rows: list | None = None
    overlay_views: dict = field(default_factory=dict)
    active_overlay_key: str | None = None
    normal_view_details: dict | None = None
    sample_size_mm: float | None = None
    file_info: dict = field(default_factory=dict)
    unit_options: dict | None = None
    derived: dict | None = None
    mass_normalization_mg: float | None = None
    _x_cache: tuple | None = field(default=None, init=False, repr=False)
    history: list[tuple] = field(default_factory=list, repr=False)

    def __post_init__(self):
        if self.legend_text is None: self.legend_text = self.dataset.name[:32]
        if self.display_filename is None: self.display_filename = self.dataset.path.name

    @property
    def sample_name(self):
        from .file_information import text_value
        return text_value(self,"Sample") if "Sample" in self.file_info else self.dataset.name

    @property
    def signal_label(self):
        if self.derived is not None:return f"{self.derived['label']} ({self.derived['creation_unit']})"
        return self.dataset.signals[self.y_index].label

    @property
    def result_label(self):
        from .dimension_units import channel_label
        if self.derived is not None:
            from .running_integral import quantity as derived_quantity
            label=f"{self.derived['label']} ({derived_quantity(self)['unit']})"
        else:label=self.signal_label if "normalize" in self.operations else channel_label(self,self.y_index)[0]
        for operation in self.operations:
            if operation.startswith("derivative:"):
                from .dimension_units import variable_spec
                variable=operation.split(':',1)[1]
                shown=variable if "normalize" in self.operations else variable_spec(self,variable)['label']
                label = f"d({label}) / d({shown})"
            elif operation == "normalize":
                label = f"Relative [{label}] (%)"
        return label

    @property
    def plot_label(self):
        if self.y_type in ("normal","custom"):return self.result_label
        from .dimension_units import affine
        variable=self.dataset.time_index if self.y_type.endswith('time') else self.dataset.temperature_index
        unit=affine(self,self.y_index)['unit'];denominator=affine(self,variable)['unit'] if variable is not None else '?'
        order=2 if self.y_type.startswith('d2_') else 1
        if self.y_type=='d_temperature' and unit in ('µm/m','ppm'):return f'Alpha ({unit}/{denominator})'
        return f"{'二阶' if order==2 else '一阶'}导数 {self.dataset.signals[self.y_index].name} ({unit}/{denominator}{'²' if order==2 else ''})"

    @property
    def result_unit(self):
        from .dimension_units import quantity
        return quantity(self)['unit'] or self.result_label

    def y_unit_factor(self):
        from .dimension_units import quantity
        return quantity(self)['factor']

    def x_unit_factor(self,domain):
        if self.derived is not None:
            from .running_integral import source_reference
            return source_reference(self).x_unit_factor(domain)
        from .dimension_units import affine,typed_affine
        if domain=='signal' and self.x_signal_index is not None:return typed_affine(self,self.x_signal_index,self.x_signal_type)['factor']
        index=self.dataset.time_index if domain=='time' else self.dataset.temperature_index
        return affine(self,index)['factor'] if index is not None else 1.

    def display_y_offset(self,value=None):return (self.offset if value is None else value)*self.y_unit_factor()
    def display_x_shift(self,domain):return self.x_shift*self.x_unit_factor(domain)

    def xy(self, domain="temperature"):
        if self.working is not None and self.working_rows is not None and not np.isin(self.active_rows,self.working_rows).all():raise ValueError("此自定义处理未覆盖所选数据；请先恢复原始曲线再扩大范围")
        x = self.x_values(domain) + self.display_x_shift(domain)
        y = self.base_y if self.working is None else self.working
        y=y[self.active_rows].astype(float)
        time_index=self.dataset.time_index
        if self.derived is None and self.reset_time and self.y_index==time_index and not any(op=="normalize" or op.startswith("derivative:") for op in self.operations):y-=self.time_origin
        from .dimension_units import quantity,convert
        spec=quantity(self)
        return x,convert(y,spec)*self.scale*self.mass_normalization_factor+self.offset*spec["factor"]

    @property
    def mass_normalization_factor(self):
        if self.appearance_mode!='overlay' or self.active_overlay_key is None or self.mass_normalization_mg is None:return 1.
        from .mass_normalization import TARGET_MASS_MG, validate_mass
        return TARGET_MASS_MG/validate_mass(self.mass_normalization_mg)

    @property
    def active_rows(self):return np.arange(self.sample_count) if self.data_indices is None else np.asarray(self.data_indices,dtype=int)

    @property
    def sample_count(self):return len(self.dataset.values) if self.derived is None else len(self.derived['positions'])

    @property
    def base_y(self):return self.dataset.values[:,self.y_index] if self.derived is None else np.asarray(self.derived['base_values'],dtype=float)

    @property
    def logical_dataset(self):
        if self.derived is None:return self.dataset
        from .running_integral import logical_dataset
        return logical_dataset(self)

    @property
    def time_origin(self):
        index=self.dataset.time_index
        if index is None:raise ValueError("文件没有时间信号")
        if self.derived is not None:
            if self.data_indices is None or not len(self.active_rows):return self.derived['time_origin']
            return float(self.logical_dataset.values[self.active_rows[0],index])
        return float(self.dataset.values[self.active_rows[0],index])

    def x_values(self, domain="temperature", *, full=False, canonical=False):
        if self.derived is not None:
            from .running_integral import x_values
            return x_values(self,domain,full=full,canonical=canonical)
        rows=np.arange(len(self.dataset.values)) if full else self.active_rows
        if domain == "signal":
            from .signal_processing import typed_signal
            from .dimension_units import typed_width_factor
            from .data_limits import segments
            from dataclasses import replace
            width=self.x_smooth_width/typed_width_factor(self,self.x_signal_type)
            key = (id(self.dataset.values), self.x_signal_index, self.x_signal_type, width,tuple(rows))
            if self._x_cache is None or self._x_cache[0] != key:
                output=np.empty(len(rows))
                for section in segments(rows):
                    output[section]=typed_signal(replace(self.dataset,values=self.dataset.values[rows[section]]),self.x_signal_index,self.x_signal_type,width)
                self._x_cache = (key,output)
            output=self._x_cache[1].copy()
            if not full and self.reset_time and self.x_signal_index==self.dataset.time_index and self.x_signal_type=="normal":output-=self.time_origin
            if not canonical:
                from .dimension_units import typed_affine,convert
                spec=typed_affine(self,self.x_signal_index,self.x_signal_type)
                output=convert(output,spec)
            return output
        idx = self.dataset.temperature_index if domain == "temperature" else self.dataset.time_index
        if idx is None or idx < 0:
            raise ValueError(f"{self.dataset.path.name} 没有{domain}信号")
        output=self.dataset.values[rows, idx].astype(float)
        if not full and domain=="time" and self.reset_time:output-=self.time_origin
        if not canonical:
            from .dimension_units import affine,convert
            output=convert(output,affine(self,idx))
        return output

    def x_label(self, domain):
        if self.derived is not None:
            from .running_integral import source_reference
            return source_reference(self).x_label(domain)
        from .dimension_units import channel_label
        if domain == "signal":
            from .dimension_units import channel_label
            return channel_label(self,self.x_signal_index,self.x_signal_type)[0]
        idx = self.dataset.temperature_index if domain == "temperature" else self.dataset.time_index
        return channel_label(self,idx)[0] if idx is not None else domain

    def x_unit(self, domain):
        if self.derived is not None:
            from .running_integral import source_reference
            return source_reference(self).x_unit(domain)
        from .dimension_units import channel_label
        if domain == "signal":
            from .dimension_units import channel_label
            return channel_label(self,self.x_signal_index,self.x_signal_type)[1]
        idx = self.dataset.temperature_index if domain == "temperature" else self.dataset.time_index
        return channel_label(self,idx)[1] if idx is not None else ""

    def result_transform(self, domain):
        result = {"x_shift": self.x_shift, "scale": self.scale*self.mass_normalization_factor, "offset": self.offset}
        if self.derived is not None:result['derived_parent']=self.derived['parent_id']
        if domain == "signal": result["x_signal"] = {"index": self.x_signal_index, "type": self.x_signal_type, "width": self.x_smooth_width}
        if self.unit_options is not None:
            from .dimension_units import dimension_index,affine
            from .file_information import effective_size
            result['units']=dict(self.unit_options)
            index=dimension_index(self.dataset)
            if index is not None:
                from .running_integral import source_reference
                spec=affine(source_reference(self) if self.derived is not None else self,index)
                result['units_reference']={'original_size_mm':effective_size(self),'reference_mm':spec['reference_mm'],'at25_um':spec['reference_25'],'effective_unit':spec['unit']}
        if self.data_indices is not None:result["data_indices"]=list(self.data_indices)
        if self.reset_time:result.update(reset_time=True,time_origin=self.time_origin)
        return result

    def assert_contiguous_analysis(self,domain,low,high):
        x,_=self.xy(domain);rows=self.active_rows[(x>=low)&(x<=high)]
        if np.any(np.diff(rows)!=1):raise ValueError("所选分析横跨被排除的采集片段，请选择单一连续范围")

    def validate_positions(self,positions):
        rows=self.active_rows
        for position in positions:
            left=int(position)
            if position!=left and left+1<len(rows) and rows[left+1]!=rows[left]+1:raise ValueError("不能在被排除的数据间隙内插值")

    def checkpoint(self):
        self.save_overlay_view()
        self.history.append((None if self.working is None else self.working.copy(), list(self.operations), self.x_shift, self.scale,
                             self.overlay_offset if self.appearance_mode == "overlay" else self.offset, self.appearance_mode, self.y_type, self.smooth_width,
                             dict({key:deepcopy(getattr(self,key)) for key in ("data_indices","data_limit_spec","reset_time","smooth_domain","smooth_reuse","smooth_base_ops","smooth_source","smooth_x_config","working_rows","smooth_source_rows")},
                                  _offset_view_key=self.active_overlay_key if self.appearance_mode=="overlay" else None)))

    def undo(self):
        if self.history:
            state = self.history.pop()
            if len(state)>8:
                for key,value in state[8].items():
                    if key!="_offset_view_key":setattr(self,key,value)
            if len(state) >= 8: self.y_type, self.smooth_width = state[6:8]
            self.working, self.operations, self.x_shift, self.scale, offset = state[:5]
            mode = state[5] if len(state) > 5 else self.appearance_mode
            offset_key=state[8].get("_offset_view_key") if len(state)>8 else None
            if mode=="overlay" and offset_key is not None and (self.appearance_mode!="overlay" or self.active_overlay_key!=offset_key):
                if offset_key in self.overlay_views:
                    appearance=dict(self.overlay_views[offset_key],offset=offset)
                    self.overlay_views=dict(self.overlay_views,**{offset_key:appearance})
                return
            if mode == self.appearance_mode:
                if mode == "overlay": self.overlay_offset = offset if len(state) > 5 else offset-(self.normal_appearance or {}).get("offset", 0.)
                else: self.offset = offset
            else:
                appearance = dict(getattr(self, mode+"_appearance") or {key: getattr(self, key) for key in APPEARANCE_FIELDS})
                if mode == "normal" and self.appearance_mode == "overlay": self.offset += offset-appearance["offset"]
                appearance["offset"] = offset; setattr(self, mode+"_appearance", appearance)

    def activate_appearance(self, mode):
        if mode not in ("normal", "overlay"): raise ValueError("曲线显示模式无效")
        if self.appearance_mode == mode: return
        current = {key: getattr(self, key) for key in APPEARANCE_FIELDS}
        if self.appearance_mode == "overlay": current["offset"] = self.overlay_offset
        setattr(self, self.appearance_mode+"_appearance", current)
        target = dict(getattr(self, mode+"_appearance") or current)
        if mode == "overlay":
            if self.overlay_appearance is None: target["offset"] = 0.
            target["offset"] += self.normal_appearance["offset"]
        for key, value in target.items(): setattr(self, key, value)
        self.appearance_mode = mode

    def save_overlay_view(self):
        if self.appearance_mode=="overlay" and self.active_overlay_key is not None:
            from .overlay_views import snapshot
            self.overlay_views=dict(self.overlay_views,**{self.active_overlay_key:snapshot(self)})

    def activate_view(self,key=None):
        """Switch presentation state while retaining shared signal processing."""
        from .overlay_views import DETAIL_FIELDS,restore,overlay_key
        if key is not None and not overlay_key(key):raise ValueError("叠图窗口键无效")
        if key==self.active_overlay_key and self.appearance_mode==("overlay" if key else "normal"):return
        if self.appearance_mode=="normal":
            self.normal_view_details={name:deepcopy(getattr(self,name)) for name in DETAIL_FIELDS}
        else:
            self.save_overlay_view();self.activate_appearance("normal")
            if self.normal_view_details is not None:
                for name,value in self.normal_view_details.items():setattr(self,name,deepcopy(value))
        self.active_overlay_key=None
        self.mass_normalization_mg=None
        if key is None:return
        if self.normal_view_details is None:self.normal_view_details={name:deepcopy(getattr(self,name)) for name in DETAIL_FIELDS}
        self.activate_appearance("overlay")
        if key in self.overlay_views:restore(self,self.overlay_views[key])
        self.active_overlay_key=key

    @property
    def overlay_offset(self):
        if self.appearance_mode == "overlay": return self.offset - (self.normal_appearance or {}).get("offset", 0.)
        return (self.overlay_appearance or {}).get("offset", 0.)

    @overlay_offset.setter
    def overlay_offset(self, value):
        if self.appearance_mode == "overlay": self.offset = (self.normal_appearance or {}).get("offset", 0.) + value
        else:
            target = dict(self.overlay_appearance or {key: getattr(self, key) for key in APPEARANCE_FIELDS})
            target["offset"] = value; self.overlay_appearance = target


def save_session(path, curves, domain, results, plot_options=None):
    """Embed original data and working signals, atomically replacing only the session."""
    path = Path(path)
    if domain not in ("temperature", "time", "signal"):
        raise ValueError("会话 X 轴无效")
    from .running_integral import validate_links
    validate_links(curves,results)
    document = {"format": "tma-studio", "version": 1, "domain": domain, "results": results, "curves": [],
                "plot_options": _plot_options_mapping(plot_options)}
    handle, temporary = tempfile.mkstemp(prefix=".tma-", suffix=".tmp", dir=path.parent)
    os.close(handle)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for i, curve in enumerate(curves):
                curve.save_overlay_view()
                ds = curve.dataset
                from .cloud_storage import touch_path
                touch_path(ds.path)
                entry = {"path": str(ds.path), "instance_id": ds.instance_id, "opening_index": ds.opening_index, "metadata": ds.metadata, "warnings": ds.warnings,
                         "sha256": ds.sha256, "signals": [{"name": s.name, "unit": s.unit} for s in ds.signals]}
                state = {key: getattr(curve, key) for key in CURVE_FIELDS}
                if curve.derived is not None:
                    from .running_integral import validate as validate_derived
                    validate_derived(curve.derived,ds)
                    if curve.y_index!=curve.derived['source_y_index']:raise ValueError('派生积分信号索引不符')
                _validate_curve_state(state, len(ds.signals),len(ds.values))
                for key in CURVE_FIELDS:
                    entry[key] = getattr(curve, key)
                for key, array in (("data", ds.values), ("working", curve.working),("smooth_source",curve.smooth_source)):
                    if array is not None:
                        if key!="data" and (not isinstance(array,np.ndarray) or array.dtype.kind not in "fiu" or array.shape!=(curve.sample_count,) or not np.isfinite(array).all()):raise ValueError("处理信号或平滑来源无效")
                        buffer = BytesIO()
                        np.save(buffer, array, allow_pickle=False)
                        archive.writestr(f"{i}-{key}.npy", buffer.getvalue())
                entry["has_working"] = curve.working is not None
                entry["has_smooth_source"] = curve.smooth_source is not None
                document["curves"].append(entry)
            archive.writestr("session.json", json.dumps(document, ensure_ascii=False, allow_nan=False))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_session(path, include_plot_options=False):
    with zipfile.ZipFile(path) as archive:
        if sum(m.file_size for m in archive.infolist()) > 512 * 1024 * 1024:
            raise ValueError("会话解压大小超过 512 MB 限制")
        def reject_nonfinite(value):
            raise ValueError(f"会话包含非有限数值：{value}")
        doc = json.loads(archive.read("session.json"), parse_constant=reject_nonfinite)
        if not isinstance(doc, dict):
            raise ValueError("会话描述必须是字典")
        if doc.get("format") != "tma-studio" or doc.get("version") != 1:
            raise ValueError("不支持的会话格式或版本")
        if doc.get("domain") not in ("temperature", "time", "signal"):
            raise ValueError("会话 X 轴无效")
        curves = []
        for i, entry in enumerate(doc["curves"]):
            values = np.load(BytesIO(archive.read(f"{i}-data.npy")), allow_pickle=False)
            signals = [Signal(**s) for s in entry["signals"]]
            if values.dtype.kind not in "fiu" or values.ndim != 2 or values.shape[1] != len(signals) or len(values) < 2 or not np.isfinite(values).all():
                raise ValueError("会话包含无效数据矩阵")
            instance_id = entry.get("instance_id", "")
            opening_index = entry.get("opening_index", 1)
            if not isinstance(instance_id, str) or (instance_id and not re.fullmatch(r"[0-9a-f]{32}", instance_id)) or type(opening_index) is not int or opening_index < 1:
                raise ValueError("文件打开实例标识无效")
            ds = Dataset(path=Path(entry["path"]), signals=signals, values=values, instance_id=instance_id, opening_index=opening_index,
                         metadata=entry["metadata"], warnings=entry["warnings"], sha256=entry["sha256"])
            state = {k: deepcopy(entry[k]) if k in entry else (uuid.uuid4().hex if k == "uid" else deepcopy(CURVE_OPTION_DEFAULTS[k])) for k in CURVE_FIELDS}
            if "display_filename" not in entry: state["display_filename"] = ds.path.name
            if "y_type" not in entry and state["operations"]: state["y_type"] = "custom"
            # Older versions used empty text as a filename fallback and used
            # show_legend to hide the entire row. Preserve that visible intent.
            if "show_legend_text" not in entry and state["legend_text"] == "": state["legend_text"] = ds.path.name
            _validate_curve_state(state, len(signals),len(values))
            curve = Curve(ds, **state)
            if curve.derived is not None:
                from .running_integral import validate as validate_derived
                validate_derived(curve.derived,ds)
                if curve.y_index!=curve.derived['source_y_index']:raise ValueError('派生积分信号索引不符')
            _boolean(entry["has_working"], "has_working")
            if entry["has_working"]:
                curve.working = np.load(BytesIO(archive.read(f"{i}-working.npy")), allow_pickle=False)
                if curve.working.dtype.kind not in "fiu" or curve.working.shape != (curve.sample_count,) or not np.isfinite(curve.working).all():
                    raise ValueError("会话处理后信号无效")
            _boolean(entry.get("has_smooth_source",False),"has_smooth_source")
            if entry.get("has_smooth_source",False):
                curve.smooth_source=np.load(BytesIO(archive.read(f"{i}-smooth_source.npy")),allow_pickle=False)
                if curve.smooth_source.dtype.kind not in "fiu" or curve.smooth_source.shape!=(curve.sample_count,) or not np.isfinite(curve.smooth_source).all():raise ValueError("会话平滑来源无效")
            if curve.reset_time:curve.time_origin
            curves.append(curve)
        results = doc.get("results", [])
        required = {"file", "sha256", "kind", "domain", "lo", "hi", "signal", "operations", "transform", "values"}
        if not isinstance(results, list) or any(not isinstance(r, dict) or not required.issubset(r) or not isinstance(r["values"], dict) for r in results):
            raise ValueError("会话分析结果格式无效")
        from .measurement import POINT_KINDS, point_values
        for result in results:
            if "interactive" not in result: continue
            state = result["interactive"]
            curve = next((c for c in curves if c.uid == result.get("curve_id")), None)
            if not isinstance(state, dict) or curve is None or result["kind"] not in POINT_KINDS:
                raise ValueError("会话交互分析无效")
            _boolean(state.get("confirmed", True), "confirmed")
            state.setdefault("confirmed", True)
            if result['kind'] in ('peak_linear','peak_sigmoid'):
                from .peak_integration import validate as validate_integration
                from .peak_onset import validate as validate_peak
                validate_integration(result.get('integration'));config=validate_peak(result.get('peak_onset'))
                if result['kind']=='peak_sigmoid':
                    from .sigmoidal import validate as validate_sigmoid,validate_snapshot
                    validate_sigmoid(result.get('sigmoid'));validate_snapshot(result['values'].get('sigmoid_profile'),len(curve.dataset.values))
                    area=_number(result['values'].get('integral'),'S形积分面积')
                    if not np.isclose(area,result['values']['sigmoid_profile']['cumulative'][-1],rtol=1e-12,atol=0):raise ValueError('S形积分面积与快照不符')
                if len(state.get('indices',[]))!=(4 if config['onset']['manual'] else 2):raise ValueError('峰积分控制点数量无效')
                from .point_labels import validate_signal
                validate_signal(result.get('point_signal'),curve.dataset)
            if result['kind'] in ('peak_max','onset_point'):
                from .peak_onset import validate
                config=validate(result.get('peak_onset'))
                if len(state.get('indices',[]))!=(4 if result['kind']=='onset_point' and config['onset']['manual'] else 2):raise ValueError('峰／始点控制点数量无效')
                from .point_labels import validate_signal
                validate_signal(result.get('point_signal'),curve.dataset)
            if 'auto_limits' in result:
                from .auto_limits import validate_rule
                validate_rule(result['auto_limits'])
            if result['kind'] in ('step_transition','glass_transition'):
                from .transitions import validate
                validate(result.get('transition'))
                if len(state.get('indices',[]))!=(6 if result['transition']['manual'] else 2):raise ValueError('转变控制点数量无效')
            if result["kind"] in ("alpha_at_x","alpha_secant","alpha_fit"):
                from .alpha import validate_config
                validate_config(result.get("alpha"))
                if result["domain"]!="temperature":raise ValueError("Alpha结果必须使用温度X轴")
            annotation = result.get("annotation", {})
            if result["kind"] in ("curve_value","curve_value_y"):
                from .point_labels import validate_options,validate_signal
                validate_options(annotation.get("point_label"));validate_signal(result.get("point_signal"),curve.dataset)
            if "hidden" in annotation: _boolean(annotation["hidden"], "hidden")
            style = annotation.get("text_style", {})
            if not isinstance(style, dict): raise ValueError("标注文字格式无效")
            for key in ("bold", "italic"):
                if key in style: _boolean(style[key], key)
            if "size" in style and not 6 <= _number(style["size"], "字号") <= 72:
                raise ValueError("字号必须为6至72")
            label_styles = annotation.get("label_styles", {})
            if not isinstance(label_styles, dict): raise ValueError("独立文字格式无效")
            for label_key, label_style in label_styles.items():
                if label_key not in ("result", "t1", "t2", "t3", "t4", "t5", "t6", "onset") + tuple(f"info{i}" for i in range(1, 100)) or not isinstance(label_style, dict) or set(label_style) - {"bold", "italic", "size", "hidden"}:
                    raise ValueError("独立文字格式无效")
                for flag in ("bold", "italic", "hidden"):
                    if flag in label_style: _boolean(label_style[flag], flag)
                if "size" in label_style and not 6 <= _number(label_style["size"], "字号") <= 72:
                    raise ValueError("字号必须为6至72")
            offsets = annotation.get("label_offsets", {})
            if not isinstance(offsets, dict): raise ValueError("温度标签位置无效")
            for key, value in offsets.items():
                if key not in (("t1","t2","t3","t4","onset") if result["kind"] in ("peak_linear","peak_sigmoid") else ("t1","t2","t3","t4","t5","t6") if result["kind"] in ("step_transition","glass_transition","onset_point") else ("t1","t2")) + tuple(f"info{i}" for i in range(1, 100)) or not isinstance(value, (list, tuple)) or len(value) != 2:
                    raise ValueError("温度标签位置无效")
                for coordinate in value: _number(coordinate, "标签位置")
            from dataclasses import replace
            transform=result["transform"]
            # Archived values belong to their recorded processing state. The
            # current working buffer may cover another window; validate cursor
            # structure against immutable raw rows without replacing results.
            archived=replace(curve,unit_options=transform.get("units"),data_indices=transform.get("data_indices"),data_limit_spec=None,reset_time=transform.get("reset_time",False),working=None,working_rows=None,scale=transform['scale'],offset=transform['offset'],mass_normalization_mg=None)
            reference=transform.get('units_reference')
            if reference is not None:
                if not isinstance(reference,dict) or set(reference)!={'original_size_mm','reference_mm','at25_um','effective_unit'}:raise ValueError('分析单位参考无效')
                from .file_information import nonnegative_size
                for key in ('original_size_mm','reference_mm'):
                    if reference[key] is not None:nonnegative_size(reference[key])
                if reference['at25_um'] is not None:_number(reference['at25_um'],'25°C参考')
                if reference['effective_unit'] not in ('µm','mm','%','µm/m','ppm'):raise ValueError('分析尺寸单位无效')
                archived.sample_size_mm=reference['original_size_mm']
            xconfig=transform.get("x_signal")
            if xconfig is not None:
                if not isinstance(xconfig,dict) or set(xconfig)!={"index","type","width"}:raise ValueError("分析X信号设置无效")
                archived.x_signal_index,archived.x_signal_type,archived.x_smooth_width=xconfig["index"],xconfig["type"],xconfig["width"]
            _validate_curve_state({key:getattr(archived,key) for key in CURVE_FIELDS},len(archived.dataset.signals),len(archived.dataset.values))
            archived.validate_positions(state.get("positions",state["indices"]))
            if result['kind']=='slope':
                from .slope import validate_snapshot
                positions=state.get('positions',state['indices'])
                validate_snapshot(result['values'],len(archived.active_rows),positions)
                lo,hi=sorted(positions)
                if np.any(np.diff(archived.active_rows[int(np.floor(lo)):int(np.ceil(hi))+1])!=1):raise ValueError('斜率快照不能跨被排除的采集片段')
            if result["kind"]=="peak_sigmoid":
                from .sigmoidal import validate_snapshot
                validate_snapshot(result["values"]["sigmoid_profile"],len(archived.active_rows))
                selected=state.get('positions',state['indices']);profile=result['values']['sigmoid_profile']
                if not np.allclose([profile['positions'][0],profile['positions'][-1]],sorted(selected[:2]),rtol=0,atol=1e-12):raise ValueError('S形积分快照与控制点界限不符')
            x, y = archived.xy(result["domain"])
            point_values(x, y, result["kind"], state.get("indices", []), state.get("positions"), state.get("manual_y"))
            initial_positions=state.get("initial_positions")
            if initial_positions is not None:archived.validate_positions(initial_positions)
            point_values(x, y, result["kind"], state.get("initial_indices", []),initial_positions)
            if result["kind"]=="curve_value_y":
                if initial_positions is None:raise ValueError("Y标记缺少初始交点")
                target=_number(state.get("target_y"),"Y标记")
                initial_target=_number(state.get("initial_target_y"),"初始Y标记")
                # Validate intersections only against the matching processing state.
                # Archived measurements must retain their recorded values after later processing.
                if (curve.result_transform(result["domain"])==transform and curve.operations==result["operations"]
                        and curve.result_label==result["signal"]):
                    from .measurement import position_at_y
                    current_y=curve.xy(result["domain"])[1]
                    for selected,level in ((state.get("positions",state["indices"])[0],target),(initial_positions[0],initial_target)):
                        if not np.isclose(selected,position_at_y(current_y,level,curve.active_rows),rtol=0,atol=1e-10):raise ValueError("Y标记必须使用采集顺序中的第一个交点")
            if "active_point" in state and (type(state["active_point"]) is not int or not 0 <= state["active_point"] < len(state["indices"])):
                raise ValueError("活动控制点无效")
        plot_options = _plot_options_mapping(doc.get("plot_options", {}))
        from .running_integral import validate_links
        validate_links(curves,results)
        from .overlay_views import overlay_key
        known_uids={c.uid for c in curves}
        for key,options in plot_options.items():
            if overlay_key(key) and options["overlay_members"] is not None and any(uid not in known_uids for uid in options["overlay_members"]):raise ValueError("叠图包含不存在的曲线")
        if include_plot_options:
            return curves, doc["domain"], results, plot_options
        return curves, doc["domain"], results
