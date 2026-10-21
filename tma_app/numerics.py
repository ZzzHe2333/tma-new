"""Transparent numerical methods, independent of TA Universal Analysis algorithms.

All interval methods preserve acquisition order. Most methods require a single
strictly monotonic ramp. Signal Change and Signal Maximum may inspect a
contiguous acquisition containing any X order, including holds. Neither method
joins disjoint acquisition fragments selected by the same X bounds. These
independent algorithms have not been validated for vendor equivalence.
No method infers signal units; the CTE caller must supply temperature in deg C,
length change in micrometres, and a positive original length in millimetres.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.integrate import trapezoid
from scipy.signal import savgol_filter


def _xy(x, y, minimum=2):
    try:
        if np.iscomplexobj(x) or np.iscomplexobj(y):
            raise ValueError("X、Y 必须为实数数组")
        xa, ya = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("X、Y 必须为数值数组") from exc
    if xa.ndim != 1 or ya.ndim != 1 or xa.shape != ya.shape:
        raise ValueError("X、Y 必须为等长的一维数组")
    if len(xa) < minimum:
        raise ValueError(f"至少需要 {minimum} 个数据点")
    if not np.isfinite(xa).all() or not np.isfinite(ya).all():
        raise ValueError("数据包含 NaN 或无穷值")
    return xa, ya


def _number(value, name):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} 必须是有限数值") from exc
    if not math.isfinite(value):
        raise ValueError(f"{name} 必须是有限数值")
    return value


def _monotonic(x):
    with np.errstate(over="ignore", invalid="ignore"):
        delta = np.diff(x)
    if not np.isfinite(delta).all():
        raise ValueError("X 数值范围过大")
    if np.any(delta == 0):
        raise ValueError("区间内 X 有重复值；请选择单一且严格单调的区间")
    if not (np.all(delta > 0) or np.all(delta < 0)):
        raise ValueError("区间内 X 非单调，可能包含多个升降温过程；请缩小区间")
    return "increasing" if delta[0] > 0 else "decreasing"


def _signal_direction(x, allow_turns=False):
    """Classify sample order, allowing holds without subtracting large X values."""
    increases = bool(np.any(x[1:] > x[:-1]))
    decreases = bool(np.any(x[1:] < x[:-1]))
    if increases and decreases:
        if allow_turns:
            return "nonmonotonic"
        raise ValueError("区间内 X 非单调，可能包含多个升降温过程；请缩小区间")
    if not increases and not decreases:
        return "constant"
    return "increasing" if increases else "decreasing"


def _fit(x, y):
    """Centered ordinary least squares, with R squared = 1 for exact constants."""
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        xm, ym = np.mean(x), np.mean(y)
        dx, dy = x - xm, y - ym
        denominator = float(np.dot(dx, dx))
        if denominator == 0 or not math.isfinite(denominator):
            raise ValueError("X 的数值尺度不适合线性拟合")
        slope = float(np.dot(dx, dy) / denominator)
        intercept = float(ym - slope * xm)
        residual = y - (slope * dx + ym)
        ss_res, ss_total = float(np.dot(residual, residual)), float(np.dot(dy, dy))
        r2 = 1.0 if ss_total == 0 and ss_res == 0 else (0.0 if ss_total == 0 else 1 - ss_res / ss_total)
    values = slope, intercept, float(r2)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("线性拟合溢出，请检查数值尺度")
    return values


def _result(result):
    converted = {key: value if isinstance(value, str) else float(value) for key, value in result.items()}
    if any(not math.isfinite(v) for v in converted.values() if isinstance(v, float)):
        raise ValueError("计算结果超出有限数值范围")
    return converted


def analyze(x, y, kind: str, lo: float, hi: float,
            reference_length_mm: float | None = None) -> dict[str, float | str]:
    """Analyse inclusive sampled bounds without sorting or endpoint interpolation.

    ``integral`` subtracts the straight line joining the selected endpoint
    samples, then uses signed trapezoidal integration in acquisition order. Its
    units are Y-unit times X-unit, with no enthalpy/calibration assumption.
    ``onset`` intersects a regression on the first 20% of selected samples with
    a regression on a 20% window around the largest absolute numerical slope.
    Both windows have at least three samples; a minimum of ten is required.

    ``signal_max`` returns the largest sampled Y (including negative signals),
    with the first acquired point winning ties. Repeated and nonmonotonic X are
    allowed within one contiguous selected acquisition. ``signal_change`` is
    the signed last Y minus first Y in acquisition order, allowing repeated X
    for holds but rejecting a reversal of X direction. Bounds select actual
    samples inclusively; neither operation interpolates or scales derivatives.
    These methods are independently specified, not vendor-equivalence claims.
    """
    xa, ya = _xy(x, y)
    lo, hi = _number(lo, "区间下限"), _number(hi, "区间上限")
    if lo > hi or (lo == hi and kind not in ("signal_max", "signal_change")):
        raise ValueError("区间下限必须小于上限")
    indices = np.flatnonzero((xa >= lo) & (xa <= hi))
    if len(indices) < 2:
        raise ValueError("所选区间至少需要两个数据点")
    if np.any(np.diff(indices) != 1):
        raise ValueError("所选区间横跨多个采集片段；请选择单一升降温过程")
    xa, ya = xa[indices], ya[indices]
    if kind in ("signal_max", "signal_change"):
        direction = _signal_direction(xa, allow_turns=True)
    else:
        direction = _monotonic(xa)
    result = {"method": kind, "x_start": xa[0], "x_end": xa[-1],
              "points": len(xa), "direction": direction}
    if kind in ("signal_max", "signal_change"):
        result.update(start_x=xa[0], start_y=ya[0], stop_x=xa[-1], stop_y=ya[-1],
                      sample_start=indices[0] + 1, sample_stop=indices[-1] + 1,
                      selection="sampled inclusive bounds", vendor_equivalence="unverified")
        if kind == "signal_max":
            maximum = int(np.argmax(ya))
            result.update(max_x=xa[maximum], max_y=ya[maximum], value=ya[maximum],
                          algorithm="Maximum sampled Y in contiguous inclusive selection; first acquired point wins ties; no interpolation")
        else:
            with np.errstate(over="ignore", invalid="ignore"):
                change = ya[-1] - ya[0]
            result.update(value=change, change=change,
                          algorithm="Signed stop_y - start_y from first and last acquired selected samples; contiguous holds/turns allowed; no interpolation")
    elif kind == "slope":
        slope, intercept, r2 = _fit(xa, ya)
        result.update(slope=slope, intercept=intercept, r2=r2,
                      algorithm="Ordinary least squares: y = slope*x + intercept")
    elif kind == "peak":
        maximum, minimum = int(np.argmax(ya)), int(np.argmin(ya))
        result.update(peak_x=xa[maximum], peak_y=ya[maximum],
                      max_x=xa[maximum], max_y=ya[maximum],
                      min_x=xa[minimum], min_y=ya[minimum],
                      algorithm="Sampled maximum and minimum; first acquired point wins ties")
    elif kind == "integral":
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            baseline = ya[0] + (ya[-1] - ya[0]) * ((xa - xa[0]) / (xa[-1] - xa[0]))
            area = trapezoid(ya - baseline, xa)
        result.update(integral=area, algorithm="Endpoint straight-line baseline; signed trapezoidal area in Y-unit*X-unit")
    elif kind == "change":
        with np.errstate(over="ignore", invalid="ignore"):
            change = ya[-1] - ya[0]
        result.update(start_y=ya[0], end_y=ya[-1], change=change,
                      algorithm="Last selected sample minus first selected sample in acquisition order")
    elif kind == "cte":
        if reference_length_mm is None:
            raise ValueError("CTE 需要明确的试样原始长度（mm）")
        length = _number(reference_length_mm, "试样原始长度（mm）")
        if length <= 0:
            raise ValueError("试样原始长度（mm）必须大于 0")
        slope, intercept, r2 = _fit(xa, ya)
        result.update(slope=slope, intercept=intercept, r2=r2,
                      reference_length_mm=length, cte_ppm_per_k=slope / length * 1000,
                      algorithm="OLS slope [um/deg C] / original length [mm] * 1000 = CTE [ppm/K]")
    elif kind == "onset":
        if len(xa) < 10:
            raise ValueError("外推起始点至少需要 10 个数据点")
        window = max(3, math.ceil(len(xa) * 0.2))
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            gradient = np.gradient(ya, xa, edge_order=2)
        if not np.isfinite(gradient).all():
            raise ValueError("斜率计算溢出，请检查数据尺度")
        center = int(np.argmax(np.abs(gradient)))
        start = max(0, min(center - window // 2, len(xa) - window))
        baseline_slope, baseline_intercept, baseline_r2 = _fit(xa[:window], ya[:window])
        tangent_slope, tangent_intercept, tangent_r2 = _fit(xa[start:start + window], ya[start:start + window])
        delta_slope = baseline_slope - tangent_slope
        scale = max(abs(baseline_slope), abs(tangent_slope))
        if scale == 0 or abs(delta_slope) <= scale * 1e-9:
            raise ValueError("基线与切线平行或信号为常量，无法确定外推起始点")
        onset = (tangent_intercept - baseline_intercept) / delta_slope
        if not math.isfinite(onset) or not min(xa[0], xa[-1]) <= onset <= max(xa[0], xa[-1]):
            raise ValueError("基线与切线交点不在所选区间内；请调整区间")
        result.update(onset_x=onset, onset_y=baseline_slope * onset + baseline_intercept,
                      baseline_slope=baseline_slope, baseline_intercept=baseline_intercept,
                      baseline_r2=baseline_r2, tangent_slope=tangent_slope,
                      tangent_intercept=tangent_intercept, tangent_r2=tangent_r2,
                      baseline_x_start=xa[0], baseline_x_end=xa[window - 1],
                      tangent_x_start=xa[start], tangent_x_end=xa[start + window - 1],
                      algorithm="First 20% of acquired samples baseline OLS; 20% window OLS around max absolute gradient; line intersection (minimum 3 samples/window)")
    else:
        raise ValueError(f"不支持的分析方法：{kind}")
    return _result(result)


def process_signal(x, y, kind, parameter=11) -> np.ndarray:
    """Return a new signal; never modify input arrays.

    Smooth uses a Savitzky-Golay window in sample indices, not physical X
    spacing. Normalize is 100*y/y[0]. Derivative uses numpy's nonuniform-grid
    gradient with second-order edges where three or more samples are present.
    """
    xa, ya = _xy(x, y)
    if kind == "smooth":
        value = _number(parameter, "平滑窗口")
        if not value.is_integer() or value < 3 or int(value) % 2 == 0:
            raise ValueError("平滑窗口必须为不小于 3 的奇数")
        window = int(value)
        if window > len(ya):
            raise ValueError("平滑窗口不能超过数据点数")
        output = savgol_filter(ya, window, polyorder=min(3, window - 1))
    elif kind == "derivative":
        _monotonic(xa)
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            output = np.gradient(ya, xa, edge_order=2 if len(xa) >= 3 else 1)
    elif kind == "normalize":
        if ya[0] == 0:
            raise ValueError("首点为 0，无法按首点归一化为百分比")
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            output = ya / ya[0] * 100
    else:
        raise ValueError(f"不支持的信号处理方法：{kind}")
    if not np.isfinite(output).all():
        raise ValueError("处理结果超出有限数值范围")
    return np.asarray(output, dtype=float).copy()


def apply_transform(x, y, x_shift=0, y_scale=1, y_offset=0):
    """Return transformed copies using x+shift and y*scale+offset."""
    xa, ya = _xy(x, y)
    shift = _number(x_shift, "X 平移")
    scale = _number(y_scale, "Y 倍率")
    offset = _number(y_offset, "Y 偏移")
    with np.errstate(over="ignore", invalid="ignore"):
        result_x, result_y = xa + shift, ya * scale + offset
    if not np.isfinite(result_x).all() or not np.isfinite(result_y).all():
        raise ValueError("变换结果超出有限数值范围")
    return result_x, result_y
