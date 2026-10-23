"""Native-style linear peak integration over recorded acquisition time.

The displayed endpoint straight baseline is defined in current X coordinates.
Its exact equivalence to the original under nonlinear heating is unverified.
No heat-flow, sample-mass or instrument-specific normalization is inferred.
"""
from copy import deepcopy
import numpy as np
from .transitions import _interval,_fit
from .peak_onset import validate as validate_peak,_onset_windows

KIND='peak_linear'
KINDS=(KIND,'peak_sigmoid')


def defaults():return dict(area=True)


def validate(value):
    if not isinstance(value,dict) or set(value)!={'area'} or type(value['area']) is not bool:raise ValueError('峰积分标注选项无效')
    return deepcopy(value)


def check_curve(curve):
    from .dimension_units import dimension_index
    from .general_units import TIME_UNITS
    if curve.derived is not None or dimension_index(curve.dataset)!=curve.y_index or curve.y_type!='normal':raise ValueError('原生峰积分当前支持TMA尺寸信号；其它仪器的热量归一化尚未接入')
    if curve.dataset.time_index is None:raise ValueError('峰积分需要文件的实际时间信号')
    if curve.x_unit('time') not in TIME_UNITS:raise ValueError('峰积分的时间单位未识别')


def selection(curve,entry,positions):
    peak=validate_peak(entry['peak_onset']);validate(entry['integration']);check_curve(curve)
    x,y=curve.xy(entry['domain']);count=4 if peak['onset']['manual'] else 2
    if len(positions)!=count or any(isinstance(p,bool) or not isinstance(p,(int,float,np.integer,np.floating)) or not np.isfinite(p) or not 0<=p<len(x) for p in positions):raise ValueError('峰积分控制点无效')
    positions=list(map(float,positions));curve.validate_positions(positions);lo,hi=sorted(positions[:2])
    if count==4 and not lo<=min(positions[2:])<max(positions[2:])<=hi:raise ValueError('手动始点切线的两个点须在基线界限内且互不重合')
    rows=curve.active_rows[int(np.floor(lo)):int(np.ceil(hi))+1]
    if np.any(np.diff(rows)!=1):raise ValueError('峰积分不能跨被排除的采集片段')
    px,py,sp=_interval(x,y,(lo,hi));time=curve.x_values('time');pt=np.interp(sp,np.arange(len(time)),time)
    if np.any(np.diff(pt)<0) or pt[-1]<=pt[0]:raise ValueError('峰积分时间须按采集顺序不下降，且总时长大于零；不能排序或合并时间点')
    if px[-1]==px[0]:raise ValueError('线性基线的两端需要不同X值')
    return peak,x,y,positions,px,py,sp,pt


def _profile(curve,entry,positions):
    if entry['kind'] not in KINDS:raise ValueError('峰积分方法无效')
    config,x,y,positions,px,py,sp,pt=selection(curve,entry,positions)
    slope=float((py[-1]-py[0])/(px[-1]-px[0]));base=py[0]+slope*(px-px[0]);sigmoid=None
    if entry['kind']=='peak_sigmoid':
        from .sigmoidal import horizontal,validate as validate_sigmoid,ConvergenceError,snapshot
        config_sigmoid=validate_sigmoid(entry.get('sigmoid'))
        try:sigmoid=horizontal(pt,py,base)
        except ConvergenceError as exc:
            if config_sigmoid['draw_iterations']:
                from scipy.integrate import cumulative_trapezoid
                last=exc.iterations[-1]['baseline'] if exc.iterations else base
                partial=dict(initial=base,baseline=last,cumulative=cumulative_trapezoid(py-last,pt,initial=0),iterations=exc.iterations)
                exc.preview=snapshot(partial,px,py,pt,sp,converged=False)
            raise
        base=sigmoid['baseline']
    return (config,x,y,positions,px,py,sp,pt,base,py-base,slope),sigmoid


def profile(curve,entry,positions):return _profile(curve,entry,positions)[0]


def values(curve,entry,positions):
    from scipy.integrate import trapezoid
    parts,sigmoid=_profile(curve,entry,positions)
    config,x,y,positions,px,py,sp,pt,base,residual,slope=parts
    area=float(trapezoid(residual,pt));maximum=float(np.max(abs(residual)))
    peak=int(np.flatnonzero(np.isclose(abs(residual),maximum,rtol=1e-12,atol=0))[0]);height=float(residual[peak]);left=right=None
    if height:
        response=residual*np.sign(height);half=abs(height)/2
        for i in range(peak-1,-1,-1):
            if response[i]<=half<=response[i+1] and response[i]!=response[i+1]:
                left=float(px[i]+(px[i+1]-px[i])*(half-response[i])/(response[i+1]-response[i]));break
        for i in range(peak,len(px)-1):
            if response[i]>=half>=response[i+1] and response[i]!=response[i+1]:
                right=float(px[i]+(px[i+1]-px[i])*(half-response[i])/(response[i+1]-response[i]));break
    onset=None;onset_y=None;onset_position=None;fit=None;onset_error=None;found=False
    try:
        if config['onset']['manual']:
            fx,fy,fs=_interval(x,y,sorted(positions[2:]));m,b,r2=_fit(fx,fy)
            fit=dict(slope=m,intercept=b,r2=r2,x_start=float(fx[0]),x_stop=float(fx[-1]),position_start=float(fs[0]),position_stop=float(fs[-1]),points=len(fx))
        else:
            if peak<5:raise ValueError('主峰前采集点不足，始点不可用')
            fits,_,found=_onset_windows(px[:peak+1],py[:peak+1],sp[:peak+1],config['onset']['inflection'],fraction=.1 if config['onset']['inflection'] else .125)
            fit=fits[1];m,b=fit['slope'],fit['intercept']
        if sigmoid is not None:
            from .sigmoidal import onset_crossing
            onset,onset_y,onset_position=onset_crossing(px,base,sp,fit,float(sp[peak]))
        else:
            scale=max(abs(slope),abs(m))
            if not scale or abs(slope-m)<=128*np.finfo(float).eps*scale:raise ValueError('始点切线与积分基线平行，始点不可用')
            onset=float((b-(py[0]-slope*px[0]))/(slope-m));onset_y=float(py[0]+slope*(onset-px[0]))
            from .measurement import position_at_x
            try:onset_position=position_at_x(x,onset,sp[peak]/2,curve.active_rows)
            except ValueError:pass
    except ValueError as exc:
        if config['onset']['manual']:raise
        onset_error=str(exc)
    result=dict(integral=area,value=area,area_unit=f'{curve.result_unit}·{curve.x_unit("time")}',time_unit=curve.x_unit('time'),
        sample_start=int(np.floor(sp[0]))+1,sample_stop=int(np.ceil(sp[-1]))+1,points=len(sp),baseline_positions=[float(sp[0]),float(sp[-1])],
        time_start=float(pt[0]),time_stop=float(pt[-1]),start_x=float(px[0]),stop_x=float(px[-1]),start_y=float(py[0]),stop_y=float(py[-1]),
        baseline_slope=slope,baseline_intercept=float(py[0]-slope*px[0]),baseline_domain=entry['domain'],integration_domain='recorded_time',
        max_x=float(px[peak]),max_y=float(py[peak]),height=height,baseline_y=float(base[peak]),peak_position=float(sp[peak]),
        width_half_height=None if left is None or right is None else abs(right-left),half_left=left,half_right=right,
        onset_x=onset,onset_y=onset_y,onset_position=onset_position,onset_fit=fit,onset_error=onset_error,inflection_found=found,
        native_superheating_exception='not implemented; automatic-onset equivalence unverified',
        algorithm='signed trapezoids over recorded time; endpoint straight baseline in displayed X; adjacent endpoint interpolation, acquisition order; no calorimetry normalization; exact native nonlinear-heating baseline and automatic-onset rules unverified')
    if sigmoid is not None:
        from .sigmoidal import snapshot
        result['initial_baseline_slope']=result.pop('baseline_slope');result['initial_baseline_intercept']=result.pop('baseline_intercept')
        result.update(integral=sigmoid['area'],value=sigmoid['area'],baseline_kind='sigmoid_horizontal',sigmoid_profile=snapshot(sigmoid,px,py,pt,sp),
            iteration_count=len(sigmoid['iterations']),signal_unit=curve.result_unit,
            onset_crossing_policy='nearest pre-peak acquired baseline/tangent crossing to final tangent start; first acquired tie; no extrapolation',
            algorithm='signed recorded-time trapezoids; initial endpoint linear baseline in displayed X; horizontal endpoint blend by preceding signed cumulative fraction;1% previous-area convergence,10iteration cap;128eps cancellation guard, no fraction clipping; original exact numeric policies unverified')
    from .area_calculation import statistics,snapshot as area_snapshot
    result.update(statistics(pt,py-base))
    result['area_profile']=area_snapshot(px,py,pt,base,sp,coordinate='recorded_time',unit=result['area_unit'],
        baseline_kind='sigmoid_horizontal' if sigmoid is not None else 'linear')
    if not np.isfinite([v for v in result.values() if isinstance(v,(int,float))]).all():raise ValueError('峰积分超出有限范围')
    return result


def add_channels(values,channels):
    from .point_labels import channel_values
    for name,position in (('peak',values['peak_position']),('onset',values['onset_position'])):
        if position is not None:values[name+'_channels']=channel_values(channels,position)


def onset_label_text(entry,curve):
    from .peak_onset import label_text as peak_text
    v=entry['values']
    if v['onset_x'] is None:return ''
    proxy=dict(entry,kind='onset_point',values=dict(v));proxy['values'].update(v.get('onset_channels',{}))
    return peak_text(proxy,curve)


def label_text(entry,curve,*,include_onset=True):
    from .peak_onset import label_text as peak_text
    v=entry['values'];proxy=dict(entry,kind='peak_max',values=dict(v));proxy['values'].update(v.get('peak_channels',{}));lines=[peak_text(proxy,curve)]
    if entry['integration']['area']:lines.append(f"面积 {v['integral']:.6g} {v['area_unit']}")
    if include_onset:lines.append(onset_label_text(entry,curve))
    return '\n'.join(line for line in lines if line)
