"""Three-tangent step/glass transitions in acquired order.

Manual intervals follow the installed help. Automatic fitting uses explicit
application rules: outer20% baselines and a local steepest-slope middle window;
the original automatic-window implementation has not been verified.
"""
from __future__ import annotations
from copy import deepcopy
import numpy as np
from .numerics import _fit

KINDS=('step_transition','glass_transition')
MIDPOINTS=('none','inflection','half_height','half_width','half_tangents')
ENDPOINTS=('start','onset','midpoint','end','stop')


def defaults():
    return dict(manual=False,midpoint='inflection',start='onset',stop='end',
                labels=dict(limits=True,onset=True,end=True,change=True,signed=True))


def signal_defaults():return dict(x_limits=True,y_limits=False,change=True,signed=True)


def validate_signal(value):
    if not isinstance(value,dict) or set(value)!=set(signal_defaults()) or any(type(v) is not bool for v in value.values()):raise ValueError('信号变化标注选项无效')
    return dict(value)


def validate(value):
    base=defaults()
    if not isinstance(value,dict) or set(value)!=set(base):raise ValueError('步阶/玻璃化转变参数无效')
    if type(value['manual']) is not bool or value['midpoint'] not in MIDPOINTS or value['start'] not in ENDPOINTS or value['stop'] not in ENDPOINTS:raise ValueError('步阶/玻璃化转变方法无效')
    if value['midpoint']=='none' and 'midpoint' in (value['start'],value['stop']):raise ValueError('变化范围使用中点时必须选择中点方法')
    labels=value['labels']
    if not isinstance(labels,dict) or set(labels)!=set(base['labels']) or any(type(v) is not bool for v in labels.values()):raise ValueError('转变标注选项无效')
    return deepcopy(value)


def _interval(x,y,positions):
    low,high=positions
    if low>=high:raise ValueError('每条切线的起点须在止点之前（采集顺序）')
    positions=[low]+[float(i) for i in range(int(np.floor(low))+1,int(np.ceil(high)))]+[high]
    return (np.interp(positions,np.arange(len(x)),x),np.interp(positions,np.arange(len(y)),y),np.asarray(positions))


def _steepest(x,y,begin,end,half):
    candidates=[]
    for center in range(begin,end+1):
        left=max(begin,center-half);right=min(end,center+half)
        if right-left<2:continue
        try:slope,_,_=_fit(x[left:right+1],y[left:right+1])
        except ValueError:continue
        candidates.append((abs(slope),center,left,right))
    if not candidates:raise ValueError('转变区没有可拟合的非恒定X窗口')
    maximum=max(item[0] for item in candidates)
    if maximum==0:raise ValueError('转变区斜率为零，无法确定转变切线')
    ties=[item for item in candidates if np.isclose(item[0],maximum,rtol=1e-10,atol=0)]
    return min(ties,key=lambda item:(abs(item[1]-(begin+end)/2),item[1]))[1:]


def _crossing(x,y,target,start,end):
    """First acquired adjacent crossing, clipped to the requested X interval."""
    lo,hi=sorted((start,end))
    for i in range(len(x)-1):
        if lo<=x[i]<=hi and y[i]==target:return float(x[i])
        if (y[i]-target)*(y[i+1]-target)<=0 and y[i]!=y[i+1]:
            result=float(x[i]+(x[i+1]-x[i])*(target-y[i])/(y[i+1]-y[i]))
            if lo<=result<=hi:return result
    if lo<=x[-1]<=hi and y[-1]==target:return float(x[-1])
    raise ValueError('所选中点在转变范围内没有相邻采集交点')


def values(curve,entry,positions):
    config=validate(entry['transition']);x,y=curve.xy(entry['domain']);rows=curve.active_rows
    if entry['kind'] not in KINDS or len(positions)!=(6 if config['manual'] else 2):raise ValueError('转变分析控制点数量无效')
    if any(isinstance(p,bool) or not isinstance(p,(int,float,np.integer,np.floating)) or not np.isfinite(p) or not 0<=p<len(x) for p in positions):raise ValueError('转变控制点超出采集范围')
    positions=list(map(float,positions));curve.validate_positions(positions)
    if not config['manual']:positions=sorted(positions)
    if any(a>b for a,b in zip(positions,positions[1:])):raise ValueError('六个切线点须按采集顺序排列')
    first,last=int(np.floor(positions[0])),int(np.ceil(positions[-1]))
    if np.any(np.diff(rows[first:last+1])!=1):raise ValueError('转变分析不能跨越被排除的采集片段')
    px,py,acquired=_interval(x,y,(positions[0],positions[-1]))
    direction=np.sign(px[-1]-px[0])
    if not direction:raise ValueError('转变分析的两侧界限需要不同X值')
    if config['manual']:
        intervals=[_interval(x,y,positions[i:i+2]) for i in (0,2,4)]
        central_start=int(np.searchsorted(acquired,positions[1]));central_stop=int(np.searchsorted(acquired,positions[4],side='right'))-1
        method='three user-selected acquisition intervals, adjacent-interpolated endpoints, OLS'
    else:
        if len(px)<9:raise ValueError('自动三切线至少需要9个采集点，请扩大范围或使用手动切线')
        n=len(px);outer=max(3,int(np.ceil(n*.2)));central_start=outer;central_stop=n-outer-1
        if central_stop-central_start<2:raise ValueError('自动转变的中部拟合区不足3点')
        _,left,right=_steepest(px,py,central_start,central_stop,max(1,n//20))
        intervals=[(px[:outer],py[:outer],acquired[:outer]),(px[left:right+1],py[left:right+1],acquired[left:right+1]),(px[-outer:],py[-outer:],acquired[-outer:])]
        method='application auto rule: outer20% OLS baselines; middle steepest local OLS with about10% width; not verified native windows'
    fits=[]
    for sx,sy,sp in intervals:
        slope,intercept,r2=_fit(sx,sy)
        fits.append(dict(slope=slope,intercept=intercept,r2=r2,x_start=float(sx[0]),x_stop=float(sx[-1]),points=len(sx),
                         position_start=float(sp[0]),position_stop=float(sp[-1])))
    def intersect(a,b):
        denominator=a['slope']-b['slope']
        scale=max(abs(a['slope']),abs(b['slope']))
        if scale==0 or abs(denominator)<=128*np.finfo(float).eps*scale:raise ValueError('相邻切线平行，不能确定转变交点')
        return (b['intercept']-a['intercept'])/denominator
    onset=intersect(fits[0],fits[1]);end=intersect(fits[1],fits[2])
    tolerance=1e-9*max(1.,abs(px[-1]-px[0]))
    if (not np.isfinite(onset+end) or direction*(end-onset)<=tolerance or
            direction*(onset-px[0])<-tolerance or direction*(px[-1]-end)<-tolerance):raise ValueError('切线交点不构成范围内按采集顺序排列的始点和终点，请调整界限')
    def fitted(fit,value):return fit['slope']*value+fit['intercept']
    onset_y=fitted(fits[0],onset);end_y=fitted(fits[2],end)
    inflection,_,_=_steepest(px,py,central_start,central_stop,max(1,len(px)//20))
    inflection_x=float(px[inflection]);midpoint=None
    if config['midpoint']=='inflection':midpoint=inflection_x
    elif config['midpoint']=='half_width':midpoint=(onset+end)/2
    elif config['midpoint']=='half_height':midpoint=_crossing(px,py,(onset_y+end_y)/2,onset,end)
    elif config['midpoint']=='half_tangents':
        average=(fits[0]['slope']+fits[2]['slope'])/2*px+(fits[0]['intercept']+fits[2]['intercept'])/2
        midpoint=_crossing(px,py-average,0.,onset,end)
    if midpoint is not None and not min(onset,end)-tolerance<=midpoint<=max(onset,end)+tolerance:raise ValueError('中点不在转变始点和终点之间')
    def endpoint(kind,side):
        if kind=='start':return float(py[0])
        if kind=='stop':return float(py[-1])
        if kind=='onset':return float(onset_y)
        if kind=='end':return float(end_y)
        return float(fitted(fits[0 if side==0 else 2],midpoint))
    change_start=endpoint(config['start'],0);change_stop=endpoint(config['stop'],1)
    result=dict(onset_x=float(onset),onset_y=float(onset_y),end_x=float(end),end_y=float(end_y),
                inflection_x=inflection_x,midpoint_x=None if midpoint is None else float(midpoint),
                change_start_y=change_start,change_stop_y=change_stop,change=change_stop-change_start,value=change_stop-change_start,
                fits=fits,algorithm=method+'; first acquired midpoint intersection; no sorting or joining gaps')
    numbers=[v for v in result.values() if isinstance(v,(int,float))]+[v for fit in fits for v in fit.values()]
    if not np.isfinite(numbers).all():raise ValueError('转变计算超出有限数值范围')
    return result
