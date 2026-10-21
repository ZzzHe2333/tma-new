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
                "data_indices", "data_limit_spec", "reset_time", "smooth_domain", "smooth_reuse", "smooth_base_ops","smooth_x_config","working_rows","smooth_source_rows")
CURVE_OPTION_DEFAULTS = {"marker": "", "legend_text": "", "show_legend": True, "overlay_enabled": True,
                         "appearance_mode": "normal", "normal_appearance": None, "overlay_appearance": None,
                         "display_filename": None, "show_legend_text": True, "normal_enabled": True,
                         "y_type": "normal", "smooth_width": 0., "x_signal_index": None, "x_signal_type": "normal", "x_smooth_width": 0.,
                         "data_indices":None,"data_limit_spec":None,"reset_time":False,"smooth_domain":None,"smooth_reuse":False,"smooth_base_ops":[],"smooth_x_config":None,"working_rows":None,"smooth_source_rows":None}
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
            "export_title": "", "export_align": "left", "window_name": "",
            "legend_anchor": None, "x_domain": None, "secondary_x": False, "signal_defaults": None,"smoothing_rules":[]}


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
        elif key in ("title", "x_label", "export_title"):
            result[key] = _text(value, key)
        elif key == "window_name": result[key] = _text(value, key, maximum=80)
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
        if rows is not None and (not isinstance(rows,list) or len(rows)<2 or any(type(v) is not int or v<0 or (sample_count is not None and v>=sample_count) for v in rows) or any(b<=a for a,b in zip(rows,rows[1:]))):raise ValueError("采集数据行范围无效")
    if state["smooth_domain"] not in (None,"temperature","time","signal"):raise ValueError("平滑自变量无效")
    config=state["smooth_x_config"]
    if config is not None:
        if not isinstance(config,dict) or set(config)!={"index","type","width"} or type(config["index"]) is not int or not 0<=config["index"]<signal_count:raise ValueError("平滑X信号设置无效")
        from .signal_processing import KINDS
        if config["type"] not in KINDS or _number(config["width"],"平滑X窗口")<0:raise ValueError("平滑X信号设置无效")
    if not isinstance(state["smooth_base_ops"],list) or len(state["smooth_base_ops"])>10000:raise ValueError("平滑来源记录无效")
    for value in state["smooth_base_ops"]:_text(value,"平滑来源记录")
    spec=state["data_limit_spec"]
    if spec is not None:
        if not isinstance(spec,dict) or set(spec)!={"kind","start","stop","delay","all_cycles","reset_time"} or spec["kind"] not in ("time","temperature","cycle"):raise ValueError("数据界限设置无效")
        for key in ("start","stop","delay"):_number(spec[key],key)
        if spec["delay"]<0:raise ValueError("延迟时间不能为负数")
        for key in ("all_cycles","reset_time"):_boolean(spec[key],key)
    from .signal_processing import KINDS
    if state["y_type"] not in KINDS+("custom",) or state["x_signal_type"] not in KINDS: raise ValueError("信号类型无效")
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
    _x_cache: tuple | None = field(default=None, init=False, repr=False)
    history: list[tuple] = field(default_factory=list, repr=False)

    def __post_init__(self):
        if self.legend_text is None: self.legend_text = self.dataset.name[:32]
        if self.display_filename is None: self.display_filename = self.dataset.path.name

    @property
    def signal_label(self):
        return self.dataset.signals[self.y_index].label

    @property
    def result_label(self):
        label = self.signal_label
        for operation in self.operations:
            if operation.startswith("derivative:"):
                label = f"d({label}) / d({operation.split(':', 1)[1]})"
            elif operation == "normalize":
                label = f"Relative [{label}] (%)"
        return label

    @property
    def plot_label(self):
        if self.y_type in ("normal", "custom"): return self.result_label
        variable = self.dataset.time_index if self.y_type.endswith("time") else self.dataset.temperature_index
        unit = self.dataset.signals[self.y_index].unit
        denominator = self.dataset.signals[variable].unit if variable is not None else "?"
        order = 2 if self.y_type.startswith("d2_") else 1
        return f"{'二阶' if order == 2 else '一阶'}导数 {self.dataset.signals[self.y_index].name} ({unit}/{denominator}{'²' if order == 2 else ''})"

    @property
    def result_unit(self):
        unit = self.dataset.signals[self.y_index].unit.strip().replace("μ", "µ")
        if unit == "um": unit = "µm"
        for operation in self.operations:
            if operation.startswith("derivative:"):
                variable = operation.split(":", 1)[1]
                denominator = next((s.unit for s in self.dataset.signals if s.label == variable),
                                   "°C" if variable.startswith("Temperature") else ("min" if variable.startswith("Time") else variable))
                if self.x_signal_index is not None and variable == self.x_label("signal"): denominator = self.x_unit("signal")
                unit = f"({unit})/({denominator})"
            elif operation == "normalize": unit = "%"
        # Empty units do not establish compatibility for unrelated signals.
        return unit or self.result_label

    def xy(self, domain="temperature"):
        if self.working is not None and self.working_rows is not None and not np.isin(self.active_rows,self.working_rows).all():raise ValueError("此自定义处理未覆盖所选数据；请先恢复原始曲线再扩大范围")
        x = self.x_values(domain) + self.x_shift
        y = self.dataset.values[:, self.y_index] if self.working is None else self.working
        y=y[self.active_rows].astype(float)
        time_index=self.dataset.time_index
        if self.reset_time and self.y_index==time_index and self.result_unit==self.dataset.signals[time_index].unit:y-=self.time_origin
        return x, y * self.scale + self.offset

    @property
    def active_rows(self):return np.arange(len(self.dataset.values)) if self.data_indices is None else np.asarray(self.data_indices,dtype=int)

    @property
    def time_origin(self):
        index=self.dataset.time_index
        if index is None:raise ValueError("文件没有时间信号")
        return float(self.dataset.values[self.active_rows[0],index])

    def x_values(self, domain="temperature", *, full=False):
        rows=np.arange(len(self.dataset.values)) if full else self.active_rows
        if domain == "signal":
            from .signal_processing import typed_signal
            from .data_limits import segments
            from dataclasses import replace
            key = (id(self.dataset.values), self.x_signal_index, self.x_signal_type, self.x_smooth_width,tuple(rows))
            if self._x_cache is None or self._x_cache[0] != key:
                output=np.empty(len(rows))
                for section in segments(rows):
                    output[section]=typed_signal(replace(self.dataset,values=self.dataset.values[rows[section]]),self.x_signal_index,self.x_signal_type,self.x_smooth_width)
                self._x_cache = (key,output)
            output=self._x_cache[1].copy()
            if not full and self.reset_time and self.x_signal_index==self.dataset.time_index and self.x_signal_type=="normal":output-=self.time_origin
            return output
        idx = self.dataset.temperature_index if domain == "temperature" else self.dataset.time_index
        if idx is None or idx < 0:
            raise ValueError(f"{self.dataset.path.name} 没有{domain}信号")
        output=self.dataset.values[rows, idx].astype(float)
        if not full and domain=="time" and self.reset_time:output-=self.time_origin
        return output

    def x_label(self, domain):
        from .signal_processing import type_label
        if domain == "signal": return type_label(self.dataset, self.x_signal_index, self.x_signal_type)[0]
        idx = self.dataset.temperature_index if domain == "temperature" else self.dataset.time_index
        return self.dataset.signals[idx].label if idx is not None else domain

    def x_unit(self, domain):
        from .signal_processing import type_label
        if domain == "signal": return type_label(self.dataset, self.x_signal_index, self.x_signal_type)[1]
        idx = self.dataset.temperature_index if domain == "temperature" else self.dataset.time_index
        return self.dataset.signals[idx].unit if idx is not None else ""

    def result_transform(self, domain):
        result = {"x_shift": self.x_shift, "scale": self.scale, "offset": self.offset}
        if domain == "signal": result["x_signal"] = {"index": self.x_signal_index, "type": self.x_signal_type, "width": self.x_smooth_width}
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
        self.history.append((None if self.working is None else self.working.copy(), list(self.operations), self.x_shift, self.scale,
                             self.overlay_offset if self.appearance_mode == "overlay" else self.offset, self.appearance_mode, self.y_type, self.smooth_width,
                             {key:deepcopy(getattr(self,key)) for key in ("data_indices","data_limit_spec","reset_time","smooth_domain","smooth_reuse","smooth_base_ops","smooth_source","smooth_x_config","working_rows","smooth_source_rows")}))

    def undo(self):
        if self.history:
            state = self.history.pop()
            if len(state)>8:
                for key,value in state[8].items():setattr(self,key,value)
            if len(state) >= 8: self.y_type, self.smooth_width = state[6:8]
            self.working, self.operations, self.x_shift, self.scale, offset = state[:5]
            mode = state[5] if len(state) > 5 else self.appearance_mode
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
    document = {"format": "tma-studio", "version": 1, "domain": domain, "results": results, "curves": [],
                "plot_options": _plot_options_mapping(plot_options)}
    handle, temporary = tempfile.mkstemp(prefix=".tma-", suffix=".tmp", dir=path.parent)
    os.close(handle)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for i, curve in enumerate(curves):
                ds = curve.dataset
                entry = {"path": str(ds.path), "metadata": ds.metadata, "warnings": ds.warnings,
                         "sha256": ds.sha256, "signals": [{"name": s.name, "unit": s.unit} for s in ds.signals]}
                state = {key: getattr(curve, key) for key in CURVE_FIELDS}
                _validate_curve_state(state, len(ds.signals),len(ds.values))
                for key in CURVE_FIELDS:
                    entry[key] = getattr(curve, key)
                for key, array in (("data", ds.values), ("working", curve.working),("smooth_source",curve.smooth_source)):
                    if array is not None:
                        if key!="data" and (not isinstance(array,np.ndarray) or array.dtype.kind not in "fiu" or array.shape!=(len(ds.values),) or not np.isfinite(array).all()):raise ValueError("处理信号或平滑来源无效")
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
            ds = Dataset(path=Path(entry["path"]), signals=signals, values=values,
                         metadata=entry["metadata"], warnings=entry["warnings"], sha256=entry["sha256"])
            state = {k: deepcopy(entry[k]) if k in entry else (uuid.uuid4().hex if k == "uid" else deepcopy(CURVE_OPTION_DEFAULTS[k])) for k in CURVE_FIELDS}
            if "display_filename" not in entry: state["display_filename"] = ds.path.name
            if "y_type" not in entry and state["operations"]: state["y_type"] = "custom"
            # Older versions used empty text as a filename fallback and used
            # show_legend to hide the entire row. Preserve that visible intent.
            if "show_legend_text" not in entry and state["legend_text"] == "": state["legend_text"] = ds.path.name
            _validate_curve_state(state, len(signals),len(values))
            curve = Curve(ds, **state)
            _boolean(entry["has_working"], "has_working")
            if entry["has_working"]:
                curve.working = np.load(BytesIO(archive.read(f"{i}-working.npy")), allow_pickle=False)
                if curve.working.dtype.kind not in "fiu" or curve.working.shape != (len(values),) or not np.isfinite(curve.working).all():
                    raise ValueError("会话处理后信号无效")
            _boolean(entry.get("has_smooth_source",False),"has_smooth_source")
            if entry.get("has_smooth_source",False):
                curve.smooth_source=np.load(BytesIO(archive.read(f"{i}-smooth_source.npy")),allow_pickle=False)
                if curve.smooth_source.dtype.kind not in "fiu" or curve.smooth_source.shape!=(len(values),) or not np.isfinite(curve.smooth_source).all():raise ValueError("会话平滑来源无效")
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
            annotation = result.get("annotation", {})
            if "hidden" in annotation: _boolean(annotation["hidden"], "hidden")
            style = annotation.get("text_style", {})
            if not isinstance(style, dict): raise ValueError("标注文字格式无效")
            for key in ("bold", "italic"):
                if key in style: _boolean(style[key], key)
            if "size" in style and not 6 <= _number(style["size"], "字号") <= 72:
                raise ValueError("字号必须为6至72")
            offsets = annotation.get("label_offsets", {})
            if not isinstance(offsets, dict): raise ValueError("温度标签位置无效")
            for key, value in offsets.items():
                if key not in ("t1", "t2") or not isinstance(value, (list, tuple)) or len(value) != 2:
                    raise ValueError("温度标签位置无效")
                for coordinate in value: _number(coordinate, "标签位置")
            from dataclasses import replace
            transform=result["transform"]
            # Archived values belong to their recorded processing state. The
            # current working buffer may cover another window; validate cursor
            # structure against immutable raw rows without replacing results.
            archived=replace(curve,data_indices=transform.get("data_indices"),reset_time=transform.get("reset_time",False),working=None,working_rows=None)
            xconfig=transform.get("x_signal")
            if xconfig is not None:
                if not isinstance(xconfig,dict) or set(xconfig)!={"index","type","width"}:raise ValueError("分析X信号设置无效")
                archived.x_signal_index,archived.x_signal_type,archived.x_smooth_width=xconfig["index"],xconfig["type"],xconfig["width"]
            _validate_curve_state({key:getattr(archived,key) for key in CURVE_FIELDS},len(archived.dataset.signals),len(archived.dataset.values))
            archived.validate_positions(state.get("positions",state["indices"]))
            x, y = archived.xy(result["domain"])
            point_values(x, y, result["kind"], state.get("indices", []), state.get("positions"), state.get("manual_y"))
            point_values(x, y, result["kind"], state.get("initial_indices", []))
            if "active_point" in state and (type(state["active_point"]) is not int or not 0 <= state["active_point"] < len(state["indices"])):
                raise ValueError("活动控制点无效")
        plot_options = _plot_options_mapping(doc.get("plot_options", {}))
        if include_plot_options:
            return curves, doc["domain"], results, plot_options
        return curves, doc["domain"], results
