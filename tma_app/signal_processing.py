"""Acquisition-order local least-squares signal types.

Manufacturer help describes linear/quadratic sliding fits and at least five
points. Exact window ties, reversals and end handling are unverified. Here a
contiguous physical half-width is expanded to the nearest adjacent points until
five samples are present, without sorting or joining acquisition branches.
"""
import math
import numpy as np

KINDS = ("normal", "d_time", "d_temperature", "d2_time", "d2_temperature")


def validate_template(value):
    if not isinstance(value, dict) or set(value) != {"y", "x", "secondary"}: raise ValueError("信号默认设置格式无效")
    if type(value["secondary"]) is not bool or not isinstance(value["y"], list) or len(value["y"]) != 4: raise ValueError("信号默认设置格式无效")
    def item(item, x=False):
        if not isinstance(item, dict) or set(item) != ({"signal", "type", "width", "domain"} if x else {"signal", "type", "width"}): raise ValueError("信号默认设置字段无效")
        if item["signal"] is not None and (not isinstance(item["signal"], str) or len(item["signal"]) > 4096): raise ValueError("信号名称无效")
        if item["type"] not in KINDS: raise ValueError("当前自定义处理不能作为信号默认类型")
        width = item["width"]
        if isinstance(width, bool) or not isinstance(width, (int,float)) or not math.isfinite(width) or width < 0: raise ValueError("平滑窗口宽度无效")
        if x and item["domain"] not in ("temperature", "time", "signal"): raise ValueError("X信号无效")
        return dict(item, width=float(width))
    return {"y": [item(v) for v in value["y"]], "x": item(value["x"], True), "secondary": value["secondary"]}


def factory_template(dataset):
    dimension = next((i for i,s in enumerate(dataset.signals) if "dimension" in s.name.casefold()), 0)
    domain = "temperature" if dataset.temperature_index is not None else ("time" if dataset.time_index is not None else "signal")
    return {"y": [{"signal": dataset.signals[dimension].label if axis == 0 else None, "type": "normal", "width": 0.} for axis in range(4)],
            "x": {"domain": domain, "signal": dataset.signals[dimension].label, "type": "normal", "width": 0.}, "secondary": False}


def local_fit(x, y, width=0., derivative=0):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if x.ndim != 1 or x.shape != y.shape or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("局部拟合需要等长、有限的一维信号")
    if isinstance(width, bool) or not isinstance(width, (int, float)) or not math.isfinite(width) or width < 0:
        raise ValueError("平滑窗口宽度必须为非负有限数")
    if type(derivative) is not int or derivative not in (0, 1, 2): raise ValueError("导数阶数无效")
    if derivative == 0 and width == 0: return y.copy()
    if len(x) < 5: raise ValueError("局部最小二乘至少需要5个采样点")
    output = np.empty(len(x)); degree = max(1, derivative)
    for i in range(len(x)):
        left, right = i, i+1
        while left > 0 and abs(x[left-1]-x[i]) <= width/2: left -= 1
        while right < len(x) and abs(x[right]-x[i]) <= width/2: right += 1
        while right-left < 5:
            if left and (right == len(x) or abs(x[left-1]-x[i]) <= abs(x[right]-x[i])): left -= 1
            else: right += 1
        with np.errstate(over="ignore", invalid="ignore"):
            z = x[left:right]-x[i]; span = float(np.max(np.abs(z)))
        if not math.isfinite(span) or span == 0: raise ValueError(f"第{i+1}点附近自变量恒定，无法拟合；可改用时间导数")
        design = np.polynomial.polynomial.polyvander(z/span, degree)
        with np.errstate(over="ignore", invalid="ignore"):
            baseline = y[i]; response = y[left:right]-baseline
        if not np.isfinite(response).all(): raise ValueError("信号数值尺度不适合局部拟合")
        coefficients, _, rank, _ = np.linalg.lstsq(design, response, rcond=None)
        if rank != degree+1: raise ValueError(f"第{i+1}点附近拟合退化")
        with np.errstate(over="ignore", invalid="ignore", divide="ignore", under="ignore"):
            output[i] = coefficients[derivative]*math.factorial(derivative)/np.float64(span)**derivative + (baseline if derivative == 0 else 0.)
    if not np.isfinite(output).all(): raise ValueError("局部拟合结果超出有限范围")
    return output


def typed_signal(dataset, index, kind="normal", width=0., normal_domain="temperature"):
    if type(index) is not int or not 0 <= index < len(dataset.signals): raise ValueError("信号索引无效")
    if kind not in KINDS: raise ValueError("此信号类型的数学定义尚未确认")
    y = dataset.values[:, index]
    variable = kind.split("_", 1)[1] if kind != "normal" else normal_domain
    axis_index = dataset.time_index if variable == "time" else dataset.temperature_index
    if kind == "normal" and width == 0: return np.asarray(y, dtype=float).copy()
    if axis_index is None: raise ValueError("文件没有所需的求导/平滑自变量")
    return local_fit(dataset.values[:, axis_index], y, width, 2 if kind.startswith("d2_") else (1 if kind != "normal" else 0))


def type_label(dataset, index, kind):
    label, unit = dataset.signals[index].label, dataset.signals[index].unit
    if kind == "normal": return label, unit
    variable = "time" if kind.endswith("time") else "temperature"
    axis_index = dataset.time_index if variable == "time" else dataset.temperature_index
    if axis_index is None: raise ValueError("文件没有所需的求导自变量")
    signal = dataset.signals[axis_index]
    for _ in range(2 if kind.startswith("d2_") else 1):
        label = f"d({label}) / d({signal.label})"; unit = f"({unit})/({signal.unit})"
    return label, unit
