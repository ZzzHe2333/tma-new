"""Two-handle average slope with explicit, independently specified OLS semantics.

The installed native help specifies the marker workflow but not the averaging
formula. OLS preserves the existing generic slope method; native numeric
equivalence is unverified. Snapshots retain the actual fitted displayed data.
"""
import numpy as np
from .numerics import _fit
from .transitions import _interval


def ratio_unit(y_unit,x_unit):
    y_unit=y_unit or 'Y';x_unit=x_unit or 'X'
    numerator=f'({y_unit})' if '/' in y_unit else y_unit
    denominator=f'({x_unit})' if '/' in x_unit or '·' in x_unit else x_unit
    return f'{numerator}/{denominator}'


def values(curve,entry,positions):
    if entry['kind']!='slope' or len(positions)!=2:raise ValueError('斜率分析需要两个控制点')
    x,y=curve.xy(entry['domain'])
    if any(isinstance(p,bool) or not isinstance(p,(int,float,np.integer,np.floating)) or not np.isfinite(p) or not 0<=p<len(x) for p in positions):raise ValueError('斜率控制点超出当前采集范围')
    curve.validate_positions(positions);lo,hi=sorted(map(float,positions))
    if lo==hi:raise ValueError('斜率区间需要两个不同的采集位置')
    rows=curve.active_rows[int(np.floor(lo)):int(np.ceil(hi))+1]
    if np.any(np.diff(rows)!=1):raise ValueError('斜率分析不能跨被排除的采集片段')
    px,py,p=_interval(x,y,(lo,hi));m,b,r2=_fit(px,py)
    xm,ym=float(np.mean(px)),float(np.mean(py));fy=m*(px[[0,-1]]-xm)+ym
    if not np.isfinite(fy).all():raise ValueError('斜率拟合线超出有限范围')
    return dict(slope=m,intercept=b,r2=r2,value=m,fit_x_start=float(px[0]),fit_x_end=float(px[-1]),
        fit_y_start=float(fy[0]),fit_y_end=float(fy[-1]),fit_x_mean=xm,fit_y_mean=ym,
        sample_start=int(np.floor(lo))+1,sample_stop=int(np.ceil(hi))+1,points=len(p),
        slope_unit=ratio_unit(curve.result_unit,curve.x_unit(entry['domain'])),
        fit_profile=dict(positions=p.tolist(),x=px.tolist(),y=py.tolist(),method='ordinary_least_squares',
            x_unit=curve.x_unit(entry['domain']),y_unit=curve.result_unit),
        algorithm='Centered ordinary least squares over acquired order and exact adjacent fractional endpoints; no sorting or gap bridging; native averaging formula unverified')


def validate_snapshot(v,point_count,selected):
    profile=v.get('fit_profile');keys={'positions','x','y','method','x_unit','y_unit'}
    if not isinstance(profile,dict) or set(profile)!=keys or profile['method']!='ordinary_least_squares':raise ValueError('斜率拟合快照无效')
    for key in ('x_unit','y_unit'):
        if not isinstance(profile[key],str) or len(profile[key])>4096:raise ValueError('斜率单位无效')
    arrays={}
    for key in ('positions','x','y'):
        a=profile[key]
        if not isinstance(a,list) or len(a)<2 or len(a)>point_count+2 or any(isinstance(n,bool) or not isinstance(n,(int,float)) for n in a):raise ValueError('斜率拟合向量无效')
        arrays[key]=np.asarray(a,dtype=float)
        if not np.isfinite(arrays[key]).all():raise ValueError('斜率拟合向量无效')
    p=arrays['positions'];x,y=arrays['x'],arrays['y']
    if x.shape!=p.shape or y.shape!=p.shape or np.any(np.diff(p)<=0) or p[0]<0 or p[-1]>point_count-1:raise ValueError('斜率拟合采集位置无效')
    if not isinstance(selected,(list,tuple)) or len(selected)!=2 or any(isinstance(n,bool) or not isinstance(n,(int,float)) or not np.isfinite(n) for n in selected):raise ValueError('斜率快照控制点无效')
    if not np.allclose([p[0],p[-1]],sorted(selected),rtol=0,atol=1e-12):raise ValueError('斜率快照与控制点不符')
    expected=np.unique(np.r_[p[0],np.arange(np.ceil(p[0]),np.floor(p[-1])+1),p[-1]])
    if not np.array_equal(p,expected):raise ValueError('斜率快照不能遗漏区间内的采集点')
    m,b,r2=_fit(x,y);xm,ym=float(np.mean(x)),float(np.mean(y));fy=m*(x[[0,-1]]-xm)+ym
    expected_values=dict(slope=m,intercept=b,r2=r2,value=m,fit_x_start=x[0],fit_x_end=x[-1],fit_y_start=fy[0],fit_y_end=fy[-1],fit_x_mean=xm,fit_y_mean=ym,
        sample_start=int(np.floor(p[0]))+1,sample_stop=int(np.ceil(p[-1]))+1,points=len(p))
    for key,wanted in expected_values.items():
        a=v.get(key)
        if isinstance(a,bool) or not isinstance(a,(int,float)) or not np.isfinite(a) or not np.isclose(a,wanted,rtol=1e-12,atol=1e-14 if key=='r2' else 0):raise ValueError('斜率结果与拟合快照不符')
    if v.get('slope_unit')!=ratio_unit(profile['y_unit'],profile['x_unit']):raise ValueError('斜率结果单位与快照不符')
