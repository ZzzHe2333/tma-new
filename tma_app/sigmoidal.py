"""Horizontal sigmoidal baselines using acquired-time reacted fractions.

Manufacturer help specifies1% area convergence and at most10iterations.
Relative denominator, cancellation and crossing selection are explicit local
policies; exact original numerical behavior remains unverified.
"""
import numpy as np
from scipy.integrate import cumulative_trapezoid


class ConvergenceError(ValueError):
    def __init__(self,message,iterations):
        super().__init__(message);self.iterations=iterations


def defaults():return dict(draw_iterations=False)


def validate(config):
    if not isinstance(config,dict) or set(config)!={'draw_iterations'} or type(config['draw_iterations']) is not bool:raise ValueError('S形基线选项无效')
    return dict(config)


def horizontal(time,signal,initial):
    t,y,b=[np.asarray(a,dtype=float) for a in (time,signal,initial)]
    if t.ndim!=1 or y.shape!=t.shape or b.shape!=t.shape or len(t)<2 or not all(np.isfinite(a).all() for a in (t,y,b)):raise ValueError('S形基线需要对应的有限时间与信号向量')
    if np.any(np.diff(t)<0) or t[-1]<=t[0]:raise ValueError('S形基线时间不能倒退，且总时长须为正')
    initial=b.copy();b=b.copy();cumulative=cumulative_trapezoid(y-b,t,initial=0);area=float(cumulative[-1]);history=[]
    # The two projected horizontals coincide, so their blend is constant even
    # when the signed net area is zero. No undefined fraction is needed.
    if y[0]==y[-1] or np.all(y==b):return dict(baseline=b,cumulative=cumulative,area=area,iterations=history,initial=initial)
    for number in range(1,11):
        magnitude=float(np.sum(abs(np.diff(cumulative))))
        if area==0 or abs(area)<=128*np.finfo(float).eps*magnitude:raise ConvergenceError('S形基线有符号面积接近零，无法计算反应分数',history)
        fraction=cumulative/area;next_baseline=(1-fraction)*y[0]+fraction*y[-1]
        next_cumulative=cumulative_trapezoid(y-next_baseline,t,initial=0);next_area=float(next_cumulative[-1]);change=abs(next_area-area)/abs(area)
        if not np.isfinite(next_baseline).all() or not np.isfinite(next_cumulative).all() or not np.isfinite(change):raise ConvergenceError('S形基线迭代超出有限范围',history)
        history.append(dict(number=number,baseline=next_baseline.copy(),area=next_area,relative_change=float(change)))
        b,cumulative,area=next_baseline,next_cumulative,next_area
        if change<=.01:return dict(baseline=b,cumulative=cumulative,area=area,iterations=history,initial=initial)
    raise ConvergenceError('S形基线在10次迭代内未收敛，请调整界限',history)


def onset_crossing(x,baseline,positions,fit,peak_position):
    """Nearest pre-peak baseline/tangent crossing to the chosen tangent start."""
    x,b,p=[np.asarray(v,dtype=float) for v in (x,baseline,positions)];difference=b-(fit['slope']*x+fit['intercept'])
    scale=max(float(np.max(abs(b))),float(np.max(abs(fit['slope']*x+fit['intercept']))),np.finfo(float).tiny)
    if np.max(abs(difference))<=128*np.finfo(float).eps*scale:raise ValueError('始点切线与S形基线重合，无法确定唯一交点')
    candidates=[]
    for i,d in enumerate(difference):
        if p[i]>peak_position:break
        if d==0:candidates.append((float(p[i]),float(x[i]),float(b[i])))
        if i+1<len(x) and difference[i]*difference[i+1]<0:
            f=float(-d/(difference[i+1]-d));position=float(p[i]+f*(p[i+1]-p[i]))
            if position<=peak_position:candidates.append((position,float(x[i]+f*(x[i+1]-x[i])),float(b[i]+f*(b[i+1]-b[i]))))
    if not candidates:raise ValueError('主峰之前未找到始点切线与S形基线的交点，请调整界限')
    position,ox,oy=min(candidates,key=lambda c:(abs(c[0]-fit['position_start']),c[0]))
    return ox,oy,position


def snapshot(result,x,y,time,positions,*,converged=True):
    return dict(positions=np.asarray(positions).tolist(),x=np.asarray(x).tolist(),signal=np.asarray(y).tolist(),time=np.asarray(time).tolist(),
        initial_baseline=result['initial'].tolist(),baseline=result['baseline'].tolist(),cumulative=result['cumulative'].tolist(),
        iterations=[dict(step,baseline=step['baseline'].tolist()) for step in result['iterations']],converged=converged,tolerance=.01,limit=10,
        policy='previous signed-area relative denominator;128eps cancellation guard; no fraction clipping; acquisition order')


def validate_snapshot(value,point_count):
    keys={'positions','x','signal','time','initial_baseline','baseline','cumulative','iterations','converged','tolerance','limit','policy'}
    if not isinstance(value,dict) or set(value)!=keys or value['converged'] is not True or value['tolerance']!=.01 or type(value['limit']) is not int or value['limit']!=10 or not isinstance(value['policy'],str):raise ValueError('S形积分曲线快照无效')
    vectors={}
    for key in ('positions','x','signal','time','initial_baseline','baseline','cumulative'):
        values=value[key]
        if not isinstance(values,list) or any(isinstance(v,bool) or not isinstance(v,(int,float)) for v in values):raise ValueError('S形积分曲线向量无效')
        vector=np.asarray(values,dtype=float)
        if vector.ndim!=1 or not 2<=len(vector)<=point_count+2 or not np.isfinite(vector).all():raise ValueError('S形积分曲线向量超出范围')
        vectors[key]=vector
    n=len(vectors['positions'])
    if any(len(v)!=n for v in vectors.values()) or np.any(np.diff(vectors['positions'])<=0) or vectors['positions'][0]<0 or vectors['positions'][-1]>point_count-1:raise ValueError('S形积分采集坐标无效')
    if np.any(np.diff(vectors['time'])<0) or vectors['time'][-1]<=vectors['time'][0]:raise ValueError('S形积分时间无效')
    if vectors['x'][-1]==vectors['x'][0]:raise ValueError('S形积分初始基线X端点重合')
    slope=(vectors['signal'][-1]-vectors['signal'][0])/(vectors['x'][-1]-vectors['x'][0]);initial=vectors['signal'][0]+slope*(vectors['x']-vectors['x'][0])
    initial_scale=max(float(np.max(abs(vectors['signal']))),np.finfo(float).tiny)
    if not np.allclose(initial,vectors['initial_baseline'],rtol=1e-12,atol=128*np.finfo(float).eps*initial_scale):raise ValueError('S形积分初始基线与端点不符')
    history=value['iterations']
    if not isinstance(history,list) or len(history)>10:raise ValueError('S形积分迭代记录无效')
    previous_cumulative=cumulative_trapezoid(vectors['signal']-vectors['initial_baseline'],vectors['time'],initial=0);previous=float(previous_cumulative[-1])
    scale=max(float(np.max(abs(vectors['signal']))),float(np.max(abs(vectors['baseline']))),np.finfo(float).tiny)
    atol=128*np.finfo(float).eps*scale*float(np.ptp(vectors['time']))
    for i,step in enumerate(history):
        if not isinstance(step,dict) or set(step)!={'number','baseline','area','relative_change'} or type(step['number']) is not int or step['number']!=i+1:raise ValueError('S形积分迭代顺序无效')
        if not isinstance(step['baseline'],list) or len(step['baseline'])!=n or any(isinstance(v,bool) or not isinstance(v,(int,float)) for v in step['baseline']):raise ValueError('S形积分迭代基线无效')
        base=np.asarray(step['baseline'],dtype=float)
        if not np.isfinite(base).all() or any(isinstance(step[k],bool) or not isinstance(step[k],(int,float)) or not np.isfinite(step[k]) for k in ('area','relative_change')):raise ValueError('S形积分迭代数值无效')
        if previous==0:raise ValueError('S形积分反应分数的分母为零')
        fraction=previous_cumulative/previous;blend=(1-fraction)*vectors['signal'][0]+fraction*vectors['signal'][-1]
        if not np.allclose(blend,base,rtol=1e-12,atol=128*np.finfo(float).eps*scale):raise ValueError('S形基线与前次反应分数不符')
        cumulative=cumulative_trapezoid(vectors['signal']-base,vectors['time'],initial=0);area=float(cumulative[-1])
        change=abs(area-previous)/abs(previous) if previous else float('inf')
        if not np.isclose(area,step['area'],rtol=1e-12,atol=atol) or not np.isclose(change,step['relative_change'],rtol=1e-12,atol=1e-14):raise ValueError('S形积分迭代面积与基线不符')
        if i<len(history)-1 and change<=.01:raise ValueError('S形积分在已收敛后仍继续迭代')
        previous=area;previous_cumulative=cumulative
    expected=cumulative_trapezoid(vectors['signal']-vectors['baseline'],vectors['time'],initial=0)
    if not np.allclose(expected,vectors['cumulative'],rtol=1e-12,atol=atol) or not np.allclose(vectors['baseline'][[0,-1]],vectors['signal'][[0,-1]],rtol=1e-12,atol=128*np.finfo(float).eps*scale):raise ValueError('S形积分累计面积或端点不符')
    if history and (history[-1]['relative_change']>.01 or not np.array_equal(history[-1]['baseline'],value['baseline'])):raise ValueError('S形积分未达到收敛条件')
    if not history and not np.array_equal(vectors['baseline'],vectors['initial_baseline']):raise ValueError('S形积分缺少迭代记录')
    return value
