"""Overlay style sequences and offsets from the installed WinUA help semantics.

Factory palettes/dash pixel patterns are independent defaults, not a recovered
vendor initialization file. These functions never modify acquired arrays.
"""
from __future__ import annotations
from copy import deepcopy
import math
import re

STYLES = ("-", "--", "-.", ":", "None", "long_dash", "broken_dash", "broken_double_dash")
MARKERS = ("", "o", "s", "^", "v", "+", "x", ".", "D")
COLORS = ("#000000", "#ff0000", "#0000ff", "#008000", "#800080", "#008080", "#e17b32")


def default_auto_styles():
    return {"lines": [STYLES[i % 4] for i in range(10)],
            "colors": [COLORS[i % len(COLORS)] for i in range(10)],
            "symbols": [MARKERS[1+i % (len(MARKERS)-1)] for i in range(10)],
            "offset_method": "major", "offset_percent": 10., "offset_negative": False}


def validate_auto_styles(value):
    if not isinstance(value, dict): raise ValueError("自动样式设置无效")
    result = default_auto_styles()
    for key, allowed in (("lines", STYLES), ("symbols", MARKERS), ("colors", None)):
        seq = value.get(key, result[key])
        if not isinstance(seq, (list, tuple)) or len(seq) != 10: raise ValueError("自动样式必须有十个设置")
        if any(not isinstance(item, str) or (item not in allowed if allowed is not None else re.fullmatch(r"#[0-9a-fA-F]{6}", item) is None) for item in seq):
            raise ValueError(f"自动样式 {key} 包含无效值")
        result[key] = list(seq)
    mode = value.get("offset_method", result["offset_method"])
    if mode not in ("major", "minor", "half", "percent"): raise ValueError("自动偏移方法无效")
    result["offset_method"] = mode
    percent = value.get("offset_percent", result["offset_percent"])
    if isinstance(percent, bool) or not isinstance(percent, (int, float)) or not math.isfinite(percent) or not 0 <= percent <= 10000:
        raise ValueError("偏移百分比必须为0至10000的有限数值")
    result["offset_percent"] = float(percent)
    negative = value.get("offset_negative", result["offset_negative"])
    if type(negative) is not bool: raise ValueError("负向偏移开关无效")
    result["offset_negative"] = negative
    return result


def default_auto_configure():
    return {"signals": [True]*4, "line": True, "line_mode": "curves",
            "symbol": False, "symbol_mode": "curves", "color": True, "color_mode": "curves",
            "offset": False, "axis": True, "file_selection": True, "legend": True,
            "heading": ""}


def validate_auto_configure(value):
    if not isinstance(value, dict): raise ValueError("自动配置设置无效")
    result = default_auto_configure()
    for key in result:
        item = value.get(key, result[key])
        if key == "signals":
            if not isinstance(item, (list, tuple)) or len(item) != 4 or any(type(v) is not bool for v in item): raise ValueError("自动配置信号轴无效")
            result[key] = list(item)
        elif key.endswith("_mode"):
            if item not in ("axes", "curves"): raise ValueError("自动样式区分方式无效")
            result[key] = item
        elif key == "heading":
            if not isinstance(item, str) or len(item) > 4096: raise ValueError("绘图标题过长")
            if len(item.splitlines()) > 4 or any(len(line) > 76 for line in item.splitlines()): raise ValueError("绘图标题最多四行，每行76个字符")
            result[key] = item
        else:
            if type(item) is not bool: raise ValueError("自动配置开关无效")
            result[key] = item
    return result


def apply_auto_styles(curves, styles, choices):
    """Modify private Curve drafts, resetting each selected axis's sequence."""
    styles, choices = validate_auto_styles(styles), validate_auto_configure(choices)
    counts = [0]*4
    for curve in curves:
        slot = counts[curve.axis]
        if slot >= 10: raise ValueError(f"Y{curve.axis+1} 每轴最多十条曲线")
        for key, attr, sequence in (("line", "style", "lines"), ("symbol", "marker", "symbols"), ("color", "color", "colors")):
            if choices[key]:
                index = curve.axis if choices[key+"_mode"] == "axes" else slot
                setattr(curve, attr, styles[sequence][index])
        counts[curve.axis] += 1


def offset_step(settings, low, high, major, minor):
    settings = validate_auto_styles(settings)
    try: numbers = [float(n) for n in (low, high, major, minor)]
    except (TypeError, ValueError, OverflowError) as exc: raise ValueError("坐标轴范围或刻度必须为有限数值") from exc
    low, high, major, minor = numbers
    if not all(math.isfinite(n) for n in numbers) or high <= low or major <= 0 or minor <= 0:
        raise ValueError("坐标轴范围或刻度不适用于自动偏移")
    value = {"major": major, "minor": minor, "half": minor/2,
             "percent": (high-low)*settings["offset_percent"]/100}[settings["offset_method"]]
    value = -value if settings["offset_negative"] else value
    if not math.isfinite(value): raise ValueError("自动偏移超出有限范围")
    return value


def axis_offset_step(owner, curves, axis, settings):
    """Use displayed ticks (including manual minor spacing), else a fresh scale."""
    import numpy as np
    from matplotlib.ticker import MaxNLocator
    target = owner.axes.get(axis)
    if target is not None and any(c.axis == axis and c.result_unit == curves[0].result_unit for c in owner.visible_curves()):
        low, high = sorted(map(float, target.get_ylim()))
        major_ticks, minor_ticks = target.get_yticks(), target.get_yticks(minor=True)
        major_gaps = np.diff(np.sort(major_ticks)); major_gaps = major_gaps[major_gaps > 0]
        minor_gaps = np.diff(np.sort(np.unique(np.concatenate((major_ticks, minor_ticks)))))
        minor_gaps = minor_gaps[minor_gaps > 0]
        major = float(np.median(major_gaps)) if len(major_gaps) else (high-low)/5
        minor = float(np.median(minor_gaps)) if len(minor_ticks) and len(minor_gaps) else major/4
        doc = owner.mdi.activeSubWindow() if hasattr(owner, "mdi") else None
        setting = owner.plot_options.get(doc.key, {}).get("y_ticks", [None]*4)[axis] if doc is not None else None
        if setting is not None:
            major, minor = setting["label_interval"], setting["tick_interval"]
    else:
        data = np.concatenate([c.xy(owner.domain)[1]-c.overlay_offset for c in curves])
        low, high = float(data.min()), float(data.max())
        if low == high: low -= .5; high += .5
        ticks = MaxNLocator(nbins=5, steps=[1, 2, 5, 10]).tick_values(low, high)
        major = float(np.median(np.diff(ticks))); minor = major/4
        low, high = float(ticks[0]), float(ticks[-1])
    return offset_step(settings, low, high, major, minor)


def fill_manual_limits(owner, options):
    """Turning off autoscale retains the current view until manual rescaling."""
    result = deepcopy(options)
    if not result["auto_x"] and result["x_limits"] is None and 0 in owner.axes:
        result["x_limits"] = list(owner.axes[0].get_xlim())
    for axis in range(4):
        if not result["auto_y"][axis] and result["y_limits"][axis] is None and axis in owner.axes:
            result["y_limits"][axis] = list(owner.axes[axis].get_ylim())
    return result
