"""Headless adapter for the user's proven T1/T2/H algorithm."""
from pathlib import Path
import numpy as np
from . import legacy_t1_t2_h as original
from .reader import Dataset, read_dataset


def _dimension_index(ds):
    try: return ds.index_for("Dimension Change")
    except ValueError:
        return next((i for i, signal in enumerate(ds.signals) if signal.unit.replace("μ", "µ") in ("µm", "um")), None)


def extract_metrics(source, *, algorithm="super", sample_start=None, sample_stop=None):
    """Return raw T1/T2/H1/H2/H/area, with an explicit acquisition slice.

    Algorithms retain the user's sorting, duplicate averaging and interpolation.
    A real heating/cooling cycle must be sliced explicitly before sorting it.
    Slice indices are zero-based, start inclusive, stop exclusive (like Python).
    """
    ds = source if isinstance(source, Dataset) else read_dataset(source)
    if algorithm not in ("super", "robust"):
        raise ValueError("algorithm 必须是 super 或 robust")
    yi = _dimension_index(ds)
    xi = ds.temperature_index
    if xi is None or yi is None:
        raise ValueError("文件缺少温度或尺寸变化信号")
    if ds.signals[xi].unit.strip() not in ("°C", "C", "degC", "℃"):
        raise ValueError("T1/T2/H 需要摄氏温度 °C，不自动换算温标")
    if ds.signals[yi].unit.replace("μ", "µ") not in ("µm", "um"):
        raise ValueError("T1/T2/H 需要尺寸变化单位 µm")
    start = 0 if sample_start is None else sample_start
    stop = len(ds.values) if sample_stop is None else sample_stop
    if type(start) is not int or type(stop) is not int or not 0 <= start < stop <= len(ds.values):
        raise ValueError("采样切片范围无效")
    x = ds.values[start:stop, xi].astype(float)
    y = ds.values[start:stop, yi].astype(float)
    if len(x) < 5 or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("T1/T2/H 至少需要 5 个有限数值点")
    # Distinguish small sensor jitter from a second physical ramp. Preserve the
    # legacy algorithm within a ramp, but never silently merge a full cycle.
    span = float(np.ptp(x))
    reverse = np.maximum.accumulate(x) - x
    if span > 0 and float(reverse.max()) > max(1., span * .02):
        raise ValueError("温度包含明显降温/回程；请用 --sample-start/--sample-stop 选择单一升温段")
    t1, t2, height, area, h1, h2, meta = original._compute_t1_t2_h_integral_details(x.tolist(), y.tolist(), use_super=algorithm == "super")
    values = [t1, t2, height, area, h1, h2]
    if not np.isfinite(values).all(): raise ValueError("T1/T2/H 结果不是有限数值")
    return {"file": str(ds.path), "sha256": ds.sha256, "sample": ds.name,
            "T1": t1, "T2": t2, "H1": h1, "H2": h2, "H": height,
            "area": area, "temperature_unit": "°C", "height_unit": "µm", "area_unit": "µm·°C",
            "algorithm": algorithm, "algorithm_source": original.SOURCE_FILE,
            "algorithm_source_sha256": original.SOURCE_SHA256,
            "preprocessing": "Original algorithm: sort temperature, round to 8 decimals, average duplicate temperatures; interpolate endpoints",
            "sample_start": start, "sample_stop": stop, "warnings": list(ds.warnings), "details": meta}


def write_metric_plot(source, metrics, path):
    """Use the user's cross/temperature/horizontal-reference/height-arrow layout."""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    ds = source if isinstance(source, Dataset) else read_dataset(source)
    if Path(path).resolve() == ds.path.resolve(): raise ValueError("绘图输出不能覆盖输入文件")
    yi = _dimension_index(ds)
    values = ds.values[metrics["sample_start"]:metrics["sample_stop"]]
    figure = Figure(figsize=(11, 7), dpi=160)
    FigureCanvasAgg(figure)
    axis = figure.add_subplot(111)
    axis.plot(values[:, ds.temperature_index], values[:, yi], color="black", lw=.8)
    x1, x2, y1, y2 = (metrics[key] for key in ("T1", "T2", "H1", "H2"))
    axis.plot([x1, x2], [y1, y2], "+", color="black", ms=15, mew=.8)
    for x, y, offset in ((x1, y1, (0, -18)), (x2, y2, (0, 15))):
        axis.annotate(f"{original.format_plot_temp_c(x)}°C", (x, y), xytext=offset, textcoords="offset points", ha="center")
    axis.plot([x1, x2], [y1, y1], color="black", lw=.65)
    axis.annotate("", (x2, y2), (x2, y1), arrowprops={"arrowstyle": "<->", "color": "black", "lw": .7})
    axis.annotate(f"{original.format_height_um(abs(metrics['H']))} µm", (x2, (y1+y2)/2), xytext=(12, 0), textcoords="offset points")
    axis.set_xlabel("Temperature (°C)"); axis.set_ylabel("Dimension Change (µm)")
    axis.set_title(ds.path.name, loc="left", parse_math=False)
    figure.tight_layout(); figure.savefig(path)
