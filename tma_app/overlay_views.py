"""Independent overlay presentation snapshots, referencing immutable curve UIDs.

Signal processing and acquired data windows remain shared Curve state. These
snapshots isolate plot membership, ordering, axes, visibility, styles and legend
details; they do not duplicate raw files or invent independent processed data.
"""
from copy import deepcopy
import re

DETAIL_FIELDS=("axis","visible","legend_text","show_legend","display_filename","show_legend_text")
STYLE_FIELDS=("style","color","marker","width","offset")
VIEW_FIELDS=DETAIL_FIELDS+STYLE_FIELDS+("overlay_enabled", "mass_normalization_mg")


def overlay_key(value):
    return isinstance(value,str) and re.fullmatch(r"__overlay__(?::[1-9][0-9]*)?",value) is not None


def validate_details(state,full=False):
    from .workspace import _number,_boolean,_text
    if full and isinstance(state,dict) and "mass_normalization_mg" not in state:
        state = dict(state, mass_normalization_mg=None)
    if not isinstance(state,dict) or set(state)!=set(VIEW_FIELDS if full else DETAIL_FIELDS):raise ValueError("绘图窗口曲线设置字段无效")
    if type(state["axis"]) is not int or not 0<=state["axis"]<4:raise ValueError("窗口曲线坐标轴无效")
    for key in ("visible","show_legend","show_legend_text"):_boolean(state[key],key)
    for key in ("legend_text","display_filename"):_text(state[key],key)
    if full:
        from .mass_normalization import validate_mass
        if state['mass_normalization_mg'] is not None:validate_mass(state['mass_normalization_mg'])
        _boolean(state["overlay_enabled"],"overlay_enabled")
        if state["style"] not in ("-","--","-.",":","None","long_dash","broken_dash","broken_double_dash"):raise ValueError("窗口曲线线型无效")
        if not isinstance(state["color"],str) or not re.fullmatch(r"#[0-9a-fA-F]{6}",state["color"]):raise ValueError("窗口曲线颜色无效")
        if state["marker"] not in ("","o","s","^","v","+","x",".","D"):raise ValueError("窗口曲线符号无效")
        if _number(state["width"],"窗口曲线宽度")<=0:raise ValueError("窗口曲线宽度必须大于零")
        _number(state["offset"],"窗口曲线偏移")
    return deepcopy(state)


def validate_views(views):
    if not isinstance(views,dict) or len(views)>1000:raise ValueError("叠图窗口设置无效")
    result={}
    for key,state in views.items():
        if not overlay_key(key):raise ValueError("叠图窗口键无效")
        result[key]=validate_details(state,True)
    return result


def snapshot(curve):
    state={key:deepcopy(getattr(curve,key)) for key in VIEW_FIELDS}
    state["offset"]=curve.overlay_offset
    return state


def restore(curve,state):
    for key,value in state.items():
        if key!="offset":setattr(curve,key,deepcopy(value))
    curve.overlay_offset=state["offset"]
