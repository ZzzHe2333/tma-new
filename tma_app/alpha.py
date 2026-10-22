"""TMA expansion coefficients; explicit independent acquisition-window rules."""
from __future__ import annotations
import numpy as np
from .numerics import _fit

ALPHA_KINDS=('alpha_at_x','alpha_secant','alpha_fit')
DEFAULT_WIDTH_C=10.


def positive(value,label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not np.isfinite(value) or value<=0:
        raise ValueError(f'{label}必须是大于0的有限数值')
    return float(value)


def validate_config(config):
    if not isinstance(config,dict) or set(config)!={'reference_length_mm','reference_source','smoothing_width_c'}:
        raise ValueError('Alpha参数无效')
    length=positive(config['reference_length_mm'],'样品原始尺寸(mm)')
    width=positive(config['smoothing_width_c'],'单点Alpha窗口(°C)')
    source=config['reference_source']
    if not isinstance(source,str) or not source or len(source)>512:raise ValueError('样品尺寸来源无效')
    return dict(reference_length_mm=length,reference_source=source,smoothing_width_c=width)


def sample_length(curve):
    from .file_information import effective_size
    value=effective_size(curve)
    if value is None or value==0:return None,None
    return value,'session override (mm)' if curve.sample_size_mm is not None else 'source header Size (mm)'



def check_curve(curve,domain):
    if curve.derived is not None:raise ValueError('Alpha分析需要尺寸信号，累计积分不适用')
    from .general_units import TEMP_ALIASES,TEMP_UNITS
    if domain!='temperature' or TEMP_ALIASES.get(curve.x_unit(domain),curve.x_unit(domain)) not in TEMP_UNITS:
        raise ValueError('Alpha分析需要温度(°C、°F或K)作为X轴')
    if curve.result_unit.replace('μ','µ') not in ('µm','um','mm','%','µm/m','ppm') or 'normalize' in curve.operations:
        raise ValueError('Alpha分析需要尺寸信号；通用归一化或已求导的信号不适用')
    if not any(word in curve.dataset.signals[curve.y_index].name.lower() for word in ('dimension','length','尺寸','长度')):
        raise ValueError('Alpha分析需要选择尺寸信号')


def _interval(x,y,positions,rows):
    low,high=sorted(float(p) for p in positions)
    if low==high:raise ValueError('Alpha区间需要两个不同的点')
    first,last=int(np.floor(low)),int(np.ceil(high))
    if np.any(np.diff(rows[first:last+1])!=1):raise ValueError('Alpha分析不能横跨被排除的采集片段')
    acquired=[low]+[float(i) for i in range(int(np.floor(low))+1,int(np.ceil(high)))]+[high]
    # Interpolated endpoints participate exactly once; no X sorting or cycle merging.
    px=np.interp(acquired,np.arange(len(x)),x);py=np.interp(acquired,np.arange(len(y)),y)
    return px,py,first,last


def alpha_values(curve,entry,positions):
    check_curve(curve,entry['domain']);config=validate_config(entry['alpha'])
    kind=entry['kind'];x,y=curve.xy(entry['domain']);rows=curve.active_rows
    if kind not in ALPHA_KINDS:raise ValueError('Alpha方法无效')
    curve.validate_positions(positions)
    if kind=='alpha_at_x':
        if len(positions)!=1:raise ValueError('单点Alpha需要一个点')
        position=float(positions[0]);center=float(np.interp(position,np.arange(len(x)),x))
        from .general_units import displayed_delta_per_c
        half=config['smoothing_width_c']*displayed_delta_per_c(curve.x_unit(entry['domain']))/2
        low,high=center-half,center+half
        left=int(np.floor(position));right=int(np.ceil(position))
        # Grow only the local acquired neighborhood containing this handle.
        if not low<=x[left]<=high:left+=1
        if not low<=x[right]<=high:right-=1
        if left>right:raise ValueError('单点Alpha窗口内不足2个采集点，请增加窗口宽度')
        while left>0 and rows[left]==rows[left-1]+1 and low<=x[left-1]<=high:left-=1
        while right+1<len(x) and rows[right+1]==rows[right]+1 and low<=x[right+1]<=high:right+=1
        if right-left<1:raise ValueError('单点Alpha窗口内不足2个采集点，请增加窗口宽度')
        if np.any(np.diff(rows[left:right+1])!=1):raise ValueError('单点Alpha窗口不能跨数据间隙')
        px,py=x[left:right+1],y[left:right+1]
        slope,intercept,r2=_fit(px,py);method='local acquired-neighborhood OLS, truncated at collection/gap/window boundaries'
    else:
        if len(positions)!=2:raise ValueError('区间Alpha需要两个点')
        px,py,left,right=_interval(x,y,positions,rows)
        if kind=='alpha_secant':
            delta=float(px[-1]-px[0])
            if delta==0:raise ValueError('两点温度相同，无法计算Alpha')
            slope=float((py[-1]-py[0])/delta);intercept=float(py[0]-slope*px[0]);r2=None
            method='endpoint dimension change / endpoint temperature change'
        else:
            slope,intercept,r2=_fit(px,py);method='OLS through acquired interval with adjacent-interpolated endpoints'
    with np.errstate(over='ignore',invalid='ignore',divide='ignore'):
        unit=curve.result_unit.replace('μ','µ')
        multiplier={'µm':1000/config['reference_length_mm'],'um':1000/config['reference_length_mm'],
                    'mm':1e6/config['reference_length_mm'],'%':10000.,'µm/m':1.,'ppm':1.}[unit]
        from .general_units import displayed_delta_per_c
        temperature_factor=displayed_delta_per_c(curve.x_unit(entry['domain']))
        alpha=float(slope*multiplier*temperature_factor)
        yfirst=float(slope*px[0]+intercept);ylast=float(slope*px[-1]+intercept)
    if not all(np.isfinite(v) for v in (slope,intercept,alpha,yfirst,ylast)):raise ValueError('Alpha计算超出有限数值范围')
    result=dict(alpha=alpha,cte_ppm_per_k=alpha,value=alpha,alpha_unit='µm/m/°C',slope=slope,intercept=intercept,
        reference_length_mm=config['reference_length_mm'],reference_source=config['reference_source'],
        fit_sample_start=int(rows[left])+1,fit_sample_stop=int(rows[right])+1,fit_points=len(px),
        fit_x_start=float(px[0]),fit_x_end=float(px[-1]),fit_y_start=yfirst,fit_y_end=ylast,
        algorithm=method+f'; displayed slope [{unit}/{curve.x_unit(entry["domain"])}] * {multiplier*temperature_factor:.17g} = µm/m/°C; acquisition order, no sorting')
    if r2 is not None:result['r2']=r2
    if kind=='alpha_at_x':result['smoothing_width_c']=config['smoothing_width_c']
    return result


def reference_length(curve):
    length,source=sample_length(curve)
    if curve.unit_options is not None:
        from .dimension_units import affine
        spec=affine(curve,curve.y_index)
        if spec['reference_25'] is not None:return spec['reference_mm'],f'{source}; corrected to first acquired 25°C reference'
    return length,source
