"""Curve-attached measurements: sampled dragging and adjacent-segment manual X."""
from __future__ import annotations
import numpy as np
from matplotlib.text import Annotation
from .numerics import _xy
from .legacy_t1_t2_h import format_height_um, format_plot_temp_c
from .point_labels import CURVE_VALUE_KINDS
from .alpha import ALPHA_KINDS
from .transitions import KINDS as TRANSITION_KINDS
from .peak_onset import KINDS as PEAK_ONSET_KINDS
from .peak_integration import KINDS as INTEGRATION_KINDS

POINT_KINDS = ("signal_max", "signal_change", "dimension_change", "height_change","slope")+INTEGRATION_KINDS+CURVE_VALUE_KINDS+ALPHA_KINDS+TRANSITION_KINDS+PEAK_ONSET_KINDS


def annotation_key(text):
    return getattr(text, "_tma_offset_key", "result")


def apply_text_style(entry, text):
    options = entry.get("annotation", {})
    style = dict(options.get("text_style", {}))
    style.update(options.get("label_styles", {}).get(annotation_key(text), {}))
    text.set_fontweight("bold" if style.get("bold", False) else "normal")
    text.set_fontstyle("italic" if style.get("italic", False) else "normal")
    if "size" in style: text.set_fontsize(style["size"])
    if style.get("hidden", False): text.set_visible(False)


class ResultAnnotation(Annotation):
    """Keep aggregate result text available while rendering each line separately."""
    def _get_layout(self, renderer):
        if getattr(self, "_tma_split", False) and "\n" in self.get_text():
            with self._cm_set(text=self.get_text().splitlines()[0]):
                return super()._get_layout(renderer)
        return super()._get_layout(renderer)


def split_result_lines(annotation, entry, details, color):
    lines = annotation.get_text().splitlines()
    annotation._tma_split = len(lines) > 1
    options = entry.get("annotation", {})
    origin = options.get("offset", (12, 18))
    for index, line in enumerate(lines[1:], 1):
        key = f"info{index}"
        if len(details) < index:
            text = annotation.axes.annotate("", annotation.xy, xytext=(0, 0), textcoords="offset points",
                                            fontsize=10, color=color, zorder=13)
            text._tma_offset_key = key
            details.append(text)
        text = details[index-1]
        text.set_text(line); text.xy = annotation.xy
        text.xyann = options.get("label_offsets", {}).get(key, (origin[0], origin[1]-18*index))
        text.set_visible(annotation.get_visible())
    for text in details[max(0, len(lines)-1):]: text.set_visible(False)
    return details


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


def position_at_y(y,target,rows=None):
    """First acquired intersection, without sorting X or bridging excluded rows."""
    if isinstance(target,bool) or not isinstance(target,(int,float)) or not np.isfinite(target):raise ValueError("请输入有限的Y坐标")
    try:return position_at_x(y,float(target),0,rows)
    except ValueError as exc:raise ValueError(f"Y {target:g} 在当前连续采集片段中没有交点") from exc


def initial_y_point(y,rows=None):
    target=float(.5*np.min(y)+.5*np.max(y))
    try:position=position_at_y(y,target,rows)
    except ValueError:target=float(y[0]);position=0.
    return position,target


def point_values(x, y, kind, indices, positions=None, manual_y=None):
    xa, ya = _xy(x, y)
    count = 1 if kind in ("signal_max","alpha_at_x")+CURVE_VALUE_KINDS else 2
    if kind not in POINT_KINDS or (len(indices) not in (2,6) if kind in TRANSITION_KINDS else len(indices) not in (2,4) if kind in ("onset_point",)+INTEGRATION_KINDS else len(indices) != count) or any(type(i) is not int or not 0 <= i < len(xa) for i in indices):
        raise ValueError("交互分析控制点无效")
    first, last = indices[0], indices[-1]
    coords = point_coordinates(xa, ya, indices, positions, manual_y)
    if kind in ('slope',)+CURVE_VALUE_KINDS+ALPHA_KINDS+TRANSITION_KINDS+PEAK_ONSET_KINDS+INTEGRATION_KINDS and manual_y is not None and any(value is not None for value in manual_y):raise ValueError("曲线值坐标必须由曲线计算")
    (x1, y1), (x2, y2) = coords[0], coords[-1]
    interpolated = positions is not None and any(float(p) != int(p) for p in positions)
    result = {"method": kind, "start_x": x1, "start_y": y1,
              "stop_x": x2, "stop_y": y2,
              "x_start": x1, "x_end": x2,
              "sample_start": first + 1, "sample_stop": last + 1, "points": abs(last-first) + 1,
              "selection": "adjacent acquisition segment interpolation; no sorting" if interpolated else "explicit acquired sample indices; no interpolation or sorting"}
    if manual_y is not None and any(v is not None for v in manual_y):
        result["selection"] += "; explicitly entered Y coordinates"
    if kind in ('slope',)+ALPHA_KINDS+TRANSITION_KINDS+PEAK_ONSET_KINDS+INTEGRATION_KINDS:return result
    if kind in CURVE_VALUE_KINDS:
        at_y=kind=="curve_value_y"
        result.update(x=x1,y=y1,value=x1 if at_y else y1,
                      algorithm="First acquired Y intersection; adjacent sample interpolation, no sorting" if at_y else "Curve value at selected X; acquisition-adjacent interpolation, no sorting")
        if at_y:result["selection_axis"]="y"
    elif kind == "signal_max":
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


def initial_indices(curve, domain, kind,config=None):
    x, y = curve.xy(domain)
    if kind=='slope':
        from .data_limits import segments
        section=max(segments(curve.active_rows),key=lambda s:s.stop-s.start)
        if section.stop-section.start<2:raise ValueError('斜率需要至少两个连续采集点')
        return [section.start,section.stop-1]
    if kind in INTEGRATION_KINDS:
        from .peak_integration import check_curve
        from .data_limits import segments
        check_curve(curve);section=max(segments(curve.active_rows),key=lambda s:s.stop-s.start);size=section.stop-section.start
        manual=config['peak_onset']['onset']['manual']
        if size<(4 if manual else 2):raise ValueError('峰积分连续采集点不足')
        start,stop=section.start,section.stop-1
        return [start,stop,start+size//4,start+size//2] if manual else [start,stop]
    if kind in ALPHA_KINDS:
        from .data_limits import segments
        section=max(segments(curve.active_rows),key=lambda s:s.stop-s.start)
        size=section.stop-section.start
        if size<2:raise ValueError("Alpha需要至少2个连续采集点")
        return [section.start+size//2] if kind=="alpha_at_x" else [section.start+size//3,section.start+2*size//3]
    if kind in PEAK_ONSET_KINDS:
        from .data_limits import segments
        section=max(segments(curve.active_rows),key=lambda s:s.stop-s.start);size=section.stop-section.start
        manual=kind=='onset_point' and config['onset']['manual']
        if size<(4 if manual else 2):raise ValueError('峰／始点采集点不足')
        start=section.start;stop=section.stop-1
        if kind=='onset_point':
            peak=start+int(np.argmax(y[section]))
            if peak-start>=5:stop=peak
        return np.linspace(start,stop,4).round().astype(int).tolist() if manual else [start,stop]
    if kind in TRANSITION_KINDS:
        from .data_limits import segments
        section=max(segments(curve.active_rows),key=lambda s:s.stop-s.start)
        size=section.stop-section.start
        if size<6:raise ValueError('转变分析需要至少6个连续采集点')
        peak=section.start+int(np.argmax(y[section]));start=section.start
        if peak-start<8:peak=section.stop-1
        if config and config['manual']:return np.linspace(start,peak,6).round().astype(int).tolist()
        return [start,peak]
    if kind=="curve_value":return [len(x)//2]
    if kind=="curve_value_y":return [int(round(initial_y_point(y,curve.active_rows)[0]))]
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
            from .general_units import conversion,TEMP_ALIASES,TEMP_UNITS
            unit=curve.x_unit(domain)
            if TEMP_ALIASES.get(unit,unit) not in TEMP_UNITS:raise ValueError('未识别的温度单位')
            factor,origin,_=conversion(unit,'°C','temperature')
            detection_x=x*factor+origin
            t1, _, _ = detect_T2_T1_super_gradient(detection_x.tolist(), y.tolist(), None)
            start = nearest_sample(detection_x[:peak+1], t1, start)
        except (ValueError, ArithmeticError, IndexError):
            pass  # Transparent sampled minimum fallback; both handles remain editable.
    if start == peak:
        start = 0 if peak else min(1, len(x)-1)
    return [start+offset, peak+offset]


class MeasurementArtists:
    """A small set of mutable Matplotlib artists; drag updates avoid clearing axes."""
    def __init__(self,axis,curve,entry,domain,display_x_offset=0.):
        self.axis, self.curve, self.entry, self.domain = axis, curve, entry, domain
        self.display_x_offset=float(display_x_offset)
        self.indices = list(entry["interactive"]["indices"])
        entry["interactive"].setdefault("confirmed", True)
        self.x, self.y = curve.xy(domain)
        self.point_channels,self.point_signal_error=({},None)
        if entry["kind"] in CURVE_VALUE_KINDS+PEAK_ONSET_KINDS+INTEGRATION_KINDS:
            from .point_labels import channels
            self.point_channels,self.point_signal_error=channels(curve,entry)
        self.markers = [axis.plot([], [], "+", color="#c00000", ms=15, mew=.7, zorder=12, label="_handle")[0] for _ in self.indices]
        self.vline = axis.axvline(self.x[self.indices[0]]+self.display_x_offset, color="#d05050", lw=.55, alpha=.7, zorder=2)
        self.hline = axis.axhline(self.y[self.indices[0]], color="#d05050", lw=.55, alpha=.7, zorder=2)
        self.vline.set_visible(False); self.hline.set_visible(False)
        options = entry.get("annotation", {})
        self.annotation = ResultAnnotation("", (0, 0), xytext=options.get("offset", (12, 18)), textcoords="offset points", fontsize=10,
                                       arrowprops={"arrowstyle": "-", "lw": .6, "color": curve.color}, color=curve.color, zorder=13)
        axis.add_artist(self.annotation)
        self.details = []
        self.temps = []
        if len(self.indices) >= 2:
            self.horizontal, = axis.plot([], [], color=curve.color, lw=.65, zorder=3, label="_height_reference")
            self.arrow = axis.annotate("", (0, 0), (0, 0), arrowprops={"arrowstyle": "<->", "color": curve.color, "lw": .7}, zorder=4)
            offsets=((6,-30),(6,18)) if len(self.indices)==2 else tuple((6,(-1 if i%2==0 else 1)*(20+10*(i//2))) for i in range(len(self.indices)))
            for number, offset in enumerate(offsets, 1):
                key = f"t{number}"
                text = axis.annotate("", (0, 0), xytext=options.get("label_offsets", {}).get(key, offset), textcoords="offset points", fontsize=10, color=curve.color, zorder=13)
                text._tma_offset_key = key
                self.temps.append(text)
        if entry["kind"] in PEAK_ONSET_KINDS:
            self.analysis_lines=[axis.plot([],[],color=curve.color,lw=.7,zorder=4,label="_peak_onset_fit")[0] for _ in range(2 if entry["kind"]=="onset_point" else 1)]
            self.result_marker,=axis.plot([],[],"+",color=curve.color,ms=12,mew=.7,zorder=11)
        if entry['kind'] in INTEGRATION_KINDS:
            self.integration_lines=[axis.plot([],[],color=curve.color,lw=.7,zorder=4,label='_integration_fit')[0] for _ in range(2)]
            self.iteration_lines=[axis.plot([],[],color=curve.color,lw=.45,ls=':',alpha=.45,zorder=3,label='_sigmoid_iteration')[0] for _ in range(10)] if entry['kind']=='peak_sigmoid' and entry['sigmoid']['draw_iterations'] else []
            self.result_marker,=axis.plot([],[],'+',color=curve.color,ms=12,mew=.7,zorder=11)
            self.onset_marker,=axis.plot([],[],'+',color=curve.color,ms=12,mew=.7,zorder=11)
            self.onset_label=axis.annotate('',(0,0),xytext=options.get('label_offsets',{}).get('onset',(12,10)),textcoords='offset points',fontsize=10,color=curve.color,
                arrowprops={'arrowstyle':'-','lw':.6,'color':curve.color},zorder=13)
            self.onset_label._tma_offset_key='onset';self.temps.append(self.onset_label)
        if entry["kind"] in TRANSITION_KINDS:self.tangent_lines=[axis.plot([],[],color=curve.color,lw=.7,zorder=4,label="_transition_fit")[0] for _ in range(3)]
        if entry["kind"] in ALPHA_KINDS:self.alpha_line,=axis.plot([],[],color=curve.color,lw=.7,zorder=4,label="_alpha_fit")
        if entry['kind']=='slope':self.slope_line,=axis.plot([],[],color=curve.color,lw=.7,zorder=4,label='_slope_fit')
        self.update(active=None if entry['interactive']['confirmed'] else entry['interactive'].get('active_point',0))

    @property
    def display_coords(self):
        return [(x+self.display_x_offset,y) for x,y in self.coords]

    def calculate(self,indices,positions=None,manual_y=None):
        values=point_values(self.x,self.y,self.entry['kind'],indices,positions,manual_y)
        if self.entry['kind']=='slope':
            if self.entry['interactive']['confirmed'] and 'fit_profile' in self.entry['values']:return dict(self.entry['values'])
            from .slope import values as compute
            try:values.update(compute(self.curve,self.entry,indices if positions is None else positions))
            except ValueError as exc:
                if self.entry['interactive']['confirmed']:raise
                values['fit_error']=str(exc)
        if self.entry['kind'] in INTEGRATION_KINDS:
            from .peak_integration import values as compute,add_channels
            required=('integral','area_unit','height','width_half_height','max_x','max_y','onset_fit','onset_x','onset_y','start_x','start_y','stop_x','stop_y')
            if self.entry['interactive']['confirmed'] and all(k in self.entry['values'] for k in required) and (self.entry['kind']!='peak_sigmoid' or 'sigmoid_profile' in self.entry['values']):
                return dict(self.entry['values'])
            try:
                values.update(compute(self.curve,self.entry,indices if positions is None else positions));add_channels(values,self.point_channels)
            except ValueError as exc:
                if self.entry['interactive']['confirmed']:raise
                values['fit_error']=str(exc)
                if self.entry['kind']=='peak_sigmoid' and hasattr(exc,'preview'):values['sigmoid_failure']=exc.preview
        if self.entry['kind'] in ALPHA_KINDS:
            from .alpha import alpha_values
            values.update(alpha_values(self.curve,self.entry,indices if positions is None else positions))
        if self.entry['kind'] in TRANSITION_KINDS:
            from .transitions import values as transition_values
            try:values.update(transition_values(self.curve,self.entry,indices if positions is None else positions))
            except ValueError as exc:
                if self.entry['interactive']['confirmed']:raise
                values['fit_error']=str(exc)
        if self.entry['kind'] in PEAK_ONSET_KINDS:
            from .peak_onset import values as compute,add_channels
            try:
                values.update(compute(self.curve,self.entry,indices if positions is None else positions))
                add_channels(values,self.point_channels,self.entry['kind'])
            except ValueError as exc:
                if self.entry['interactive']['confirmed']:raise
                values['fit_error']=str(exc)
        return values

    def update(self, active=None):
        self.annotation.set_visible(True)
        values = self.calculate(self.indices,self.entry['interactive'].get('positions'),self.entry['interactive'].get('manual_y'))
        self.entry["values"] = values
        self.entry["interactive"]["indices"] = list(self.indices)
        coords = point_coordinates(self.x, self.y, self.indices, self.entry["interactive"].get("positions"), self.entry["interactive"].get("manual_y"))
        self.coords = coords
        if self.entry["kind"] in CURVE_VALUE_KINDS:
            from .point_labels import channel_values
            positions=self.entry["interactive"].get("positions",self.indices);self.curve.validate_positions(positions)
            if self.entry["kind"]=="curve_value_y":
                target=self.entry["interactive"]["target_y"]
                expected=position_at_y(self.y,target,self.curve.active_rows)
                if not np.isclose(positions[0],expected,rtol=0,atol=1e-10):raise ValueError("Y标记必须使用采集顺序中的第一个交点")
                values["requested_y"]=float(target)
            values.update(channel_values(self.point_channels,positions[0]))
            if self.point_signal_error:values["label_signal_error"]=self.point_signal_error
        self.entry["lo"], self.entry["hi"] = min(x for x, _ in coords), max(x for x, _ in coords)
        unit = self.curve.result_unit
        xunit = self.curve.x_unit(self.domain)
        options = self.entry.get("annotation", {})
        dx=self.display_x_offset
        for marker, (x, y) in zip(self.markers, coords): marker.set_data([x+dx], [y])
        if self.entry['kind']=='slope':
            self.horizontal.set_visible(False);self.arrow.set_visible(False);self.slope_line.set_data([],[])
            self.annotation.xy=(coords[-1][0]+dx,coords[-1][1])
            if 'fit_error' in values:self.annotation.set_text(values['fit_error'])
            else:
                self.slope_line.set_data([values['fit_x_start']+dx,values['fit_x_end']+dx],[values['fit_y_start'],values['fit_y_end']])
                self.annotation.xy=(values['fit_x_end']+dx,values['fit_y_end'])
                self.annotation.set_text(f"斜率 = {values['slope']:.6g} {values['slope_unit']}")
            for i,(text,(x,y)) in enumerate(zip(self.temps,coords),1):
                text.xy=(x+dx,y);text.set_text(f"{dict(temperature='T',time='t',signal='X')[self.domain]}{i} = {x:.6g} {xunit}")
        elif self.entry['kind'] in INTEGRATION_KINDS:
            self.update_integration(values,coords)
        elif self.entry["kind"] in PEAK_ONSET_KINDS:
            self.update_peak_onset(values,coords,unit,xunit)
        elif self.entry["kind"] in TRANSITION_KINDS:
            self.update_transition(values,coords,options,unit,xunit)
        elif len(coords) == 1:
            x, y = coords[0]
            self.annotation.xy = (x+dx, y)
            rendered = format_plot_temp_c(x) if self.domain == "temperature" else f"{x:.6g}"
            self.annotation.set_text(f"{rendered} {xunit}")
            if self.entry["kind"] in CURVE_VALUE_KINDS:
                from .point_labels import label_text,validate_options
                settings=validate_options(self.entry["annotation"]["point_label"])
                self.annotation.set_text(label_text(self.entry,unit))
                self.annotation.arrow_patch.set_visible(settings["arrow"] and bool(self.annotation.get_text()))
                self.annotation.set_bbox(dict(boxstyle="square,pad=.2",facecolor="none" if settings["transparent"] else "white",edgecolor=self.curve.color if settings["border"] else "none",linewidth=.6) if settings["border"] or not settings["transparent"] else None)
                self.markers[0].set_visible(not self.entry["interactive"]["confirmed"] or settings["cross"])
                self.annotation.set_visible(self.entry["interactive"]["confirmed"])
        else:
            (x1, y1), (x2, y2) = coords
            self.horizontal.set_data([x1+dx, x2+dx], [y1, y1])
            self.arrow.xy = (x2+dx, y2); self.arrow.set_position((x2+dx, y1))
            value = values.get("change",0.) if options.get("signed", True) else abs(values.get("change",0.))
            self.annotation.xy = (x2+dx, (y1+y2)/2)
            rendered = format_height_um(value) if unit.replace("μ", "µ") in ("µm", "um") else f"{value:.6g}"
            lines=[f"H = {rendered} {unit}"] if options.get('change',True) else []
            if options.get('y_limits',False):lines += [f'Y1 = {y1:.6g} {unit}',f'Y2 = {y2:.6g} {unit}']
            self.annotation.set_text('\n'.join(lines))
            for number, (text, (x, y)) in enumerate(zip(self.temps, coords), 1):
                text.xy = (x+dx, y)
                rendered = format_plot_temp_c(x) if self.domain == "temperature" else f"{x:.6g}"
                text.set_text(f"{dict(temperature='T', time='t', signal='X')[self.domain]}{number} = {rendered} {xunit}")
                text.set_visible(options.get("x_limits", True))
        if self.entry['kind'] in ALPHA_KINDS:
            confirmed=self.entry['interactive']['confirmed']
            alpha_text=f"α = {values['alpha']:.6g} µm/m/°C"
            if len(coords)==1:
                self.annotation.set_text(f"{format_plot_temp_c(coords[0][0])} {xunit}\n{alpha_text}")
                self.alpha_line.set_data([],[])
            else:
                self.horizontal.set_visible(False);self.arrow.set_visible(False)
                self.annotation.set_text(alpha_text)
                self.annotation.xy=(coords[-1][0]+dx,values['slope']*coords[-1][0]+values['intercept'])
                self.alpha_line.set_data([values['fit_x_start']+dx,values['fit_x_end']+dx],[values['fit_y_start'],values['fit_y_end']])
                for marker,text,(cx,cy) in zip(self.markers,self.temps,coords):
                    fitted=values['slope']*cx+values['intercept']
                    text.xy=(cx+dx,fitted if confirmed else cy)
                    if confirmed and self.entry['kind']=='alpha_fit':marker.set_data([cx+dx],[fitted])
        confirmed = self.entry["interactive"]["confirmed"]
        if self.entry.get("purpose")=="data_limits":
            self.annotation.set_visible(False)
            self.horizontal.set_visible(False);self.arrow.set_visible(False)
        for marker in self.markers: marker.set_color(self.curve.color if confirmed else "#c00000")
        if confirmed:
            self.vline.set_visible(False); self.hline.set_visible(False)
        elif active is not None:
            x, y = coords[active]
            self.vline.set_xdata([x+dx,x+dx]); self.hline.set_ydata([y, y])
            self.vline.set_visible(self.entry["kind"]!="curve_value_y"); self.hline.set_visible(True)
        self.update_detail_labels()
        for text in (self.annotation, *self.details, *self.temps): apply_text_style(self.entry, text)

    def update_detail_labels(self):
        split_result_lines(self.annotation, self.entry, self.details, self.curve.color)

    def update_integration(self,values,coords):
        from .peak_integration import label_text,onset_label_text
        dx=self.display_x_offset;self.horizontal.set_visible(False);self.arrow.set_visible(False);self.result_marker.set_data([],[]);self.onset_marker.set_data([],[]);self.onset_label.set_visible(False)
        for line in self.integration_lines:line.set_data([],[]);line.set_color(self.curve.color)
        for line in self.iteration_lines:line.set_data([],[])
        confirmed=self.entry['interactive']['confirmed'];limits=self.entry['peak_onset']['peak']['limits']
        for i,(text,(x,y)) in enumerate(zip(self.temps,coords)):
            text.xy=(x+dx,y);text.set_text(f"{dict(temperature='T',time='t',signal='X')[self.domain]}{i+1} = {x:.6g} {self.curve.x_unit(self.domain)}")
            text.set_visible(not confirmed or (i<2 and limits))
        self.annotation.xy=(coords[0][0]+dx,coords[0][1])
        if 'fit_error' in values:
            if self.iteration_lines and 'sigmoid_failure' in values:
                profile=values['sigmoid_failure'];xx=np.asarray(profile['x'])+dx;self.integration_lines[0].set_data(xx,profile['baseline']);self.integration_lines[0].set_color('#b00000')
                for line,base in zip(self.iteration_lines,[profile['initial_baseline']]+[step['baseline'] for step in profile['iterations'][:-1]]):line.set_data(xx,base)
            self.annotation.set_text(values['fit_error']);return
        if self.entry['kind']=='peak_sigmoid':
            profile=values['sigmoid_profile'];xx=np.asarray(profile['x'])+dx;self.integration_lines[0].set_data(xx,profile['baseline'])
            for line,base in zip(self.iteration_lines,[profile['initial_baseline']]+[step['baseline'] for step in profile['iterations'][:-1]]):line.set_data(xx,base)
        else:self.integration_lines[0].set_data([values['start_x']+dx,values['stop_x']+dx],[values['start_y'],values['stop_y']])
        self.result_marker.set_data([values['max_x']+dx],[values['max_y']]);self.annotation.xy=(values['max_x']+dx,values['max_y'])
        fit=values['onset_fit']
        if fit is not None and values['onset_x'] is not None:
            start,stop=values['onset_x'],fit['x_stop'];self.integration_lines[1].set_data([start+dx,stop+dx],[values['onset_y'],fit['slope']*stop+fit['intercept']])
            text=onset_label_text(self.entry,self.curve);self.onset_label.set_text(text);self.onset_label.xy=(start+dx,values['onset_y']);self.onset_label.set_visible(bool(text))
            self.onset_marker.set_data([start+dx],[values['onset_y']])
        self.annotation.set_text(label_text(self.entry,self.curve,include_onset=False))

    def update_peak_onset(self,values,coords,unit,xunit):
        from .peak_onset import label_text
        dx=self.display_x_offset;peak=self.entry['kind']=='peak_max'
        self.horizontal.set_visible(False);self.arrow.set_visible(False);self.result_marker.set_data([],[])
        for line in self.analysis_lines:line.set_data([],[])
        limits=self.entry['peak_onset']['peak']['limits'] if peak else not self.entry['interactive']['confirmed']
        for i,(text,(x,y)) in enumerate(zip(self.temps,coords),1):
            text.xy=(x+dx,y);text.set_text(f"{dict(temperature='T',time='t',signal='X')[self.domain]}{i} = {x:.6g} {xunit}");text.set_visible(limits)
        self.annotation.xy=(coords[len(coords)//2][0]+dx,coords[len(coords)//2][1])
        if 'fit_error' in values:self.annotation.set_text(values['fit_error']);return
        self.annotation.set_text(label_text(self.entry,self.curve))
        if peak:
            (x1,y1),(x2,y2)=coords;self.analysis_lines[0].set_data([x1+dx,x2+dx],[y1,y2])
            px,py=values['max_x'],values['max_y'];self.annotation.xy=(px+dx,py)
            self.result_marker.set_data([px+dx],[py]);self.arrow.xy=(px+dx,py);self.arrow.set_position((px+dx,values['baseline_y']));self.arrow.set_visible(True)
        else:
            ox,oy=values['onset_x'],values['onset_y'];self.annotation.xy=(ox+dx,oy);self.result_marker.set_data([ox+dx],[oy])
            for i,(line,fit) in enumerate(zip(self.analysis_lines,values['fits'])):
                begin=fit['x_start'] if i==0 else ox;end=ox if i==0 else fit['x_stop']
                line.set_data([begin+dx,end+dx],[fit['slope']*begin+fit['intercept'],fit['slope']*end+fit['intercept']])

    def update_transition(self,values,coords,options,unit,xunit):
        config=self.entry['transition'];labels=config['labels'];dx=self.display_x_offset
        self.horizontal.set_visible(False);self.arrow.set_visible(False)
        for i,(text,(x,y)) in enumerate(zip(self.temps,coords),1):
            text.xy=(x+dx,y);text.set_text(f"{dict(temperature='T',time='t',signal='X')[self.domain]}{i} = {x:.6g} {xunit}");text.set_visible(labels['limits'] and self.entry['kind']!='glass_transition')
        for line in self.tangent_lines:line.set_data([],[])
        self.annotation.xy=(coords[len(coords)//2][0]+dx,coords[len(coords)//2][1])
        if 'fit_error' in values:
            self.annotation.set_text(values['fit_error']);return
        self.annotation.xy=(values['onset_x']+dx,values['onset_y'])
        lines=[]
        if labels['onset']:lines.append(f"始点 {values['onset_x']:.6g} {xunit}")
        if values['midpoint_x'] is not None:lines.append(f"中点 {values['midpoint_x']:.6g} {xunit}")
        if labels['end']:lines.append(f"终点 {values['end_x']:.6g} {xunit}")
        if labels['change']:
            value=values['change'] if labels['signed'] else abs(values['change'])
            lines.append(f'变化 {value:.6g} {unit}')
        self.annotation.set_text('\n'.join(lines))
        for i,(line,fit) in enumerate(zip(self.tangent_lines,values['fits'])):
            begin=fit['x_start'] if i==0 else values['onset_x'] if i==1 else values['end_x']
            end=values['onset_x'] if i==0 else values['end_x'] if i==1 else fit['x_stop']
            line.set_data([begin+dx,end+dx],[fit['slope']*begin+fit['intercept'],fit['slope']*end+fit['intercept']])

    def hit(self, pixel_x, pixel_y, radius=13):
        if self.entry["interactive"]["confirmed"]: return None
        if self.entry["kind"]=="curve_value_y" and self.hline.get_visible() and self.axis.bbox.contains(pixel_x,pixel_y):
            _,py=self.axis.transData.transform(self.display_coords[0])
            if abs(py-pixel_y)<=6:return 0
        candidates = []
        for i, coordinate in enumerate(self.display_coords):
            px, py = self.axis.transData.transform(coordinate)
            distance = float(np.hypot(px-pixel_x, py-pixel_y))
            if distance <= radius: candidates.append((distance, i))
        return min(candidates)[1] if candidates else None

    def move(self, point, target_x):
        if self.entry["kind"]=="curve_value_y":
            target=float(np.clip(target_x,self.y.min(),self.y.max()))
            position=position_at_y(self.y,target,self.curve.active_rows)
            candidate=[int(round(position))]
            point_values(self.x,self.y,self.entry["kind"],candidate,[position])
            self.indices=candidate
            self.entry["interactive"].update(positions=[position],manual_y=[None],target_y=target)
            self.update(active=point);return
        index = nearest_sample(self.x, target_x, self.indices[point])
        candidate = list(self.indices); candidate[point] = index
        self.calculate(candidate)  # Validate the full analysis before changing saved state.
        self.indices = candidate
        if "positions" in self.entry["interactive"]: self.entry["interactive"]["positions"][point] = index
        if "manual_y" in self.entry["interactive"]: self.entry["interactive"]["manual_y"][point] = None
        self.update(active=point)

    def nudge(self, point, pixels):
        state = self.entry["interactive"]
        px, py = self.axis.transData.transform(self.display_coords[point])
        if self.entry["kind"]=="curve_value_y":
            target=float(self.axis.transData.inverted().transform((px,py+pixels))[1])
            self.move(point,target);return
        target_x = float(self.axis.transData.inverted().transform((px+pixels, py))[0])-self.display_x_offset
        target_x = float(np.clip(target_x, self.x.min(), self.x.max()))
        positions = list(state.get("positions", self.indices))
        positions[point] = position_at_x(self.x, target_x, positions[point],self.curve.active_rows)
        candidate = list(self.indices); candidate[point] = int(round(positions[point]))
        manual_y = list(state.get("manual_y", [None]*len(candidate))); manual_y[point] = None
        self.calculate(candidate,positions,manual_y)
        self.indices = candidate; state.update(positions=positions, manual_y=manual_y)
        self.update(active=point)
