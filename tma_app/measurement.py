"""Curve-attached measurements: sampled dragging and adjacent-segment manual X."""
from __future__ import annotations
import numpy as np
from .numerics import _xy
from .legacy_t1_t2_h import format_height_um, format_plot_temp_c

POINT_KINDS = ("signal_max", "signal_change", "dimension_change", "height_change")


def nearest_sample(x, target, anchor=0):
    distances = np.abs(np.asarray(x, dtype=float) - float(target))
    tied = np.flatnonzero(distances == distances.min())
    return int(tied[np.argmin(np.abs(tied - anchor))])


def point_coordinates(x, y, indices, positions=None, manual_y=None):
    """Interpolate only between adjacent acquisition samples, never sort a cycle."""
    positions = indices if positions is None else positions
    if not isinstance(positions, (list, tuple)) or len(positions) != len(indices):
        raise ValueError("手动界限坐标无效")
    manual_y = [None]*len(indices) if manual_y is None else manual_y
    if not isinstance(manual_y, (list, tuple)) or len(manual_y) != len(indices):
        raise ValueError("手动 Y 坐标无效")
    coords = []
    for position, height in zip(positions, manual_y):
        if isinstance(position, bool) or not isinstance(position, (int, float)) or not np.isfinite(position) or not 0 <= position <= len(x)-1:
            raise ValueError("手动界限坐标超出数据范围")
        left = int(position); right = min(left+1, len(x)-1); fraction = position-left
        if height is not None and (isinstance(height, bool) or not isinstance(height, (int, float)) or not np.isfinite(height)):
            raise ValueError("手动 Y 坐标必须为有限数值")
        coords.append((float(x[left] + fraction*(x[right]-x[left])), float(y[left] + fraction*(y[right]-y[left])) if height is None else float(height)))
    return coords


def position_at_x(x, target, anchor,rows=None):
    """Select the acquired segment closest to the current handle on repeated X."""
    x = np.asarray(x, dtype=float)
    if not np.isfinite(target): raise ValueError("请输入有限的温度或时间")
    exact = np.flatnonzero(x == target)
    candidates = [float(i) for i in exact]
    for i in np.flatnonzero(((x[:-1] < target) & (target < x[1:])) | ((x[1:] < target) & (target < x[:-1]))):
        if rows is not None and rows[i+1]!=rows[i]+1:continue
        candidates.append(float(i + (target-x[i])/(x[i+1]-x[i])))
    if not candidates: raise ValueError(f"界限 {target:g} 超出曲线范围 {x.min():g} 至 {x.max():g}")
    return min(candidates, key=lambda p: (abs(p-anchor), p))


def point_values(x, y, kind, indices, positions=None, manual_y=None):
    xa, ya = _xy(x, y)
    count = 1 if kind == "signal_max" else 2
    if kind not in POINT_KINDS or len(indices) != count or any(type(i) is not int or not 0 <= i < len(xa) for i in indices):
        raise ValueError("交互分析控制点无效")
    first, last = indices[0], indices[-1]
    coords = point_coordinates(xa, ya, indices, positions, manual_y)
    (x1, y1), (x2, y2) = coords[0], coords[-1]
    interpolated = positions is not None and any(float(p) != int(p) for p in positions)
    result = {"method": kind, "start_x": x1, "start_y": y1,
              "stop_x": x2, "stop_y": y2,
              "x_start": x1, "x_end": x2,
              "sample_start": first + 1, "sample_stop": last + 1, "points": abs(last-first) + 1,
              "selection": "adjacent acquisition segment interpolation; no sorting" if interpolated else "explicit acquired sample indices; no interpolation or sorting"}
    if manual_y is not None and any(v is not None for v in manual_y):
        result["selection"] += "; explicitly entered Y coordinates"
    if kind == "signal_max":
        result.update(max_x=x1, max_y=y1, value=y1,
                      algorithm="Sample-attached signal cursor; initialized at sampled maximum, manually movable")
    else:
        with np.errstate(over="ignore", invalid="ignore"):
            difference = y2-y1
        if not np.isfinite(difference): raise ValueError("高度差超出有限数值范围")
        result.update(change=difference, value=difference, H=difference,
                      T1=x1, T2=x2, H1=y1, H2=y2,
                      algorithm="Y(point 2) - Y(point 1), preserving handle identity" + ("; adjacent sample interpolation" if interpolated else "; no interpolation"))
    return result


def initial_indices(curve, domain, kind):
    x, y = curve.xy(domain)
    peak = int(np.argmax(y))
    if kind == "signal_max": return [peak]
    from .data_limits import segments
    section=next(s for s in segments(curve.active_rows) if s.start<=peak<s.stop)
    offset=section.start;x,y=x[section],y[section];peak-=offset
    if len(x)<2:raise ValueError("主峰所在连续采集片段不足2点")
    # Prefer the user's iterated onset detector for the initial handle only.
    # Handles themselves remain attached to original acquired samples.
    start = int(np.argmin(y[:peak+1])) if peak else 0
    if domain == "temperature" and peak >= 5:
        from .legacy_t1_t2_h import detect_T2_T1_super_gradient
        try:
            t1, _, _ = detect_T2_T1_super_gradient(x.tolist(), y.tolist(), None)
            start = nearest_sample(x[:peak+1], t1, start)
        except (ValueError, ArithmeticError, IndexError):
            pass  # Transparent sampled minimum fallback; both handles remain editable.
    if start == peak:
        start = 0 if peak else min(1, len(x)-1)
    return [start+offset, peak+offset]


class MeasurementArtists:
    """A small set of mutable Matplotlib artists; drag updates avoid clearing axes."""
    def __init__(self, axis, curve, entry, domain):
        self.axis, self.curve, self.entry, self.domain = axis, curve, entry, domain
        self.indices = list(entry["interactive"]["indices"])
        entry["interactive"].setdefault("confirmed", True)
        self.x, self.y = curve.xy(domain)
        self.markers = [axis.plot([], [], "+", color="#c00000", ms=15, mew=.7, zorder=12, label="_handle")[0] for _ in self.indices]
        self.vline = axis.axvline(self.x[self.indices[0]], color="#d05050", lw=.55, alpha=.7, zorder=2)
        self.hline = axis.axhline(self.y[self.indices[0]], color="#d05050", lw=.55, alpha=.7, zorder=2)
        self.vline.set_visible(False); self.hline.set_visible(False)
        options = entry.get("annotation", {})
        self.annotation = axis.annotate("", (0, 0), xytext=options.get("offset", (12, 18)), textcoords="offset points", fontsize=10,
                                       arrowprops={"arrowstyle": "-", "lw": .6, "color": curve.color}, color=curve.color, zorder=13)
        self.temps = []
        if len(self.indices) == 2:
            self.horizontal, = axis.plot([], [], color=curve.color, lw=.65, zorder=3, label="_height_reference")
            self.arrow = axis.annotate("", (0, 0), (0, 0), arrowprops={"arrowstyle": "<->", "color": curve.color, "lw": .7}, zorder=4)
            for number, offset in enumerate(((6, -30), (6, 18)), 1):
                key = f"t{number}"
                text = axis.annotate("", (0, 0), xytext=options.get("label_offsets", {}).get(key, offset), textcoords="offset points", fontsize=10, color=curve.color, zorder=13)
                text._tma_offset_key = key
                self.temps.append(text)
        self.update()

    def update(self, active=None):
        values = point_values(self.x, self.y, self.entry["kind"], self.indices, self.entry["interactive"].get("positions"), self.entry["interactive"].get("manual_y"))
        self.entry["values"] = values
        self.entry["interactive"]["indices"] = list(self.indices)
        coords = point_coordinates(self.x, self.y, self.indices, self.entry["interactive"].get("positions"), self.entry["interactive"].get("manual_y"))
        self.coords = coords
        self.entry["lo"], self.entry["hi"] = min(x for x, _ in coords), max(x for x, _ in coords)
        unit = self.curve.result_unit
        xunit = self.curve.x_unit(self.domain)
        options = self.entry.get("annotation", {})
        for marker, (x, y) in zip(self.markers, coords): marker.set_data([x], [y])
        if len(coords) == 1:
            x, y = coords[0]
            self.annotation.xy = (x, y)
            rendered = format_plot_temp_c(x) if self.domain == "temperature" else f"{x:.6g}"
            self.annotation.set_text(f"{rendered} {xunit}")
        else:
            (x1, y1), (x2, y2) = coords
            self.horizontal.set_data([x1, x2], [y1, y1])
            self.arrow.xy = (x2, y2); self.arrow.set_position((x2, y1))
            value = values["change"] if options.get("signed", True) else abs(values["change"])
            self.annotation.xy = (x2, (y1+y2)/2)
            rendered = format_height_um(value) if unit.replace("μ", "µ") in ("µm", "um") else f"{value:.6g}"
            self.annotation.set_text(f"H = {rendered} {unit}" if options.get("change", True) else "")
            for number, (text, (x, y)) in enumerate(zip(self.temps, coords), 1):
                text.xy = (x, y)
                rendered = format_plot_temp_c(x) if self.domain == "temperature" else f"{x:.6g}"
                text.set_text(f"{dict(temperature='T', time='t', signal='X')[self.domain]}{number} = {rendered} {xunit}")
                text.set_visible(options.get("x_limits", True))
        confirmed = self.entry["interactive"]["confirmed"]
        for marker in self.markers: marker.set_color(self.curve.color if confirmed else "#c00000")
        if confirmed:
            self.vline.set_visible(False); self.hline.set_visible(False)
        elif active is not None:
            x, y = coords[active]
            self.vline.set_xdata([x, x]); self.hline.set_ydata([y, y])
            self.vline.set_visible(True); self.hline.set_visible(True)

    def hit(self, pixel_x, pixel_y, radius=13):
        if self.entry["interactive"]["confirmed"]: return None
        candidates = []
        for i, coordinate in enumerate(self.coords):
            px, py = self.axis.transData.transform(coordinate)
            distance = float(np.hypot(px-pixel_x, py-pixel_y))
            if distance <= radius: candidates.append((distance, i))
        return min(candidates)[1] if candidates else None

    def move(self, point, target_x):
        index = nearest_sample(self.x, target_x, self.indices[point])
        candidate = list(self.indices); candidate[point] = index
        point_values(self.x, self.y, self.entry["kind"], candidate)  # Validate before changing saved state.
        self.indices = candidate
        if "positions" in self.entry["interactive"]: self.entry["interactive"]["positions"][point] = index
        if "manual_y" in self.entry["interactive"]: self.entry["interactive"]["manual_y"][point] = None
        self.update(active=point)

    def nudge(self, point, pixels):
        state = self.entry["interactive"]
        px, py = self.axis.transData.transform(self.coords[point])
        target_x = float(self.axis.transData.inverted().transform((px+pixels, py))[0])
        target_x = float(np.clip(target_x, self.x.min(), self.x.max()))
        positions = list(state.get("positions", self.indices))
        positions[point] = position_at_x(self.x, target_x, positions[point])
        candidate = list(self.indices); candidate[point] = int(round(positions[point]))
        manual_y = list(state.get("manual_y", [None]*len(candidate))); manual_y[point] = None
        point_values(self.x, self.y, self.entry["kind"], candidate, positions, manual_y)
        self.indices = candidate; state.update(positions=positions, manual_y=manual_y)
        self.update(active=point)
