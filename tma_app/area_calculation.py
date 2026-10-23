"""Auditable piecewise-linear areas without sorting acquisition branches."""
import numpy as np

BASELINES = {'linear':'端点直线', 'zero':'零基线', 'left':'起点水平', 'right':'终点水平'}
FORMULAS = '''rᵢ = yᵢ − bᵢ
净面积 A = Σ (rᵢ + rᵢ₊₁) × (qᵢ₊₁ − qᵢ) / 2
正面积 A+ = ∫ max(r, 0) |dq| ≥ 0
负面积 A− = ∫ min(r, 0) |dq| ≤ 0
绝对面积 = A+ − A−，并非 |净面积|。
跨过基线时，在相邻样点的线性零交点处分成两个三角形，分别计入正、负面积。
q 为实际记录时间或当前 X；不排序、不连接排除片段。重复 q 的区间宽度为零。
q 递增时净面积 = A+ + A−；q 递减时净面积 = −(A+ + A−)。回摆请改用时间积分或缩小范围。
端点直线：b(x) = y₀ + (y₁−y₀)(x−x₀)/(x₁−x₀)，定义在当前绘图 X 中。
零基线：b = 0；起点水平：b = y₀；终点水平：b = y₁。
原生线性／水平 S 形峰积分始终按文件实际时间积分；旧通用积分按当前 X，口径不同。
S 形基线以初始直线开始，用前次有符号累计面积分数加权两端水平线；面积变化 ≤1% 时接受，最多10次。
零基线积分并不等于绝对面积。TMA 尺寸面积不自动转换为焓、热量或结晶度。'''


def statistics(q, residual):
    q, r = np.asarray(q, dtype=float), np.asarray(residual, dtype=float)
    if q.ndim!=1 or r.shape!=q.shape or len(q)<2 or not np.isfinite(q).all() or not np.isfinite(r).all():
        raise ValueError('面积计算需要至少两个有限配对样点')
    with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
        dq=np.diff(q)
        if not np.isfinite(dq).all(): raise ValueError('积分坐标跨度超出有限范围')
        if not np.any(dq) or (np.any(dq>0) and np.any(dq<0)):
            raise ValueError('积分坐标须单向且跨度大于零；遇到回摆请按实际时间积分或缩小范围')
        a,b=r[:-1],r[1:];width=abs(dq)
        positive=(np.maximum(a,0)/2+np.maximum(b,0)/2)*width
        negative=(np.minimum(a,0)/2+np.minimum(b,0)/2)*width
        cross=((a<0)&(b>0))|((a>0)&(b<0))
        if np.any(cross):
            aa,bb=a[cross],b[cross];scale=np.maximum(abs(aa),abs(bb))
            fraction=(abs(aa)/scale)/(abs(aa)/scale+abs(bb)/scale)
            positive[cross]=np.where(aa>0,aa/2*fraction,bb/2*(1-fraction))*width[cross]
            negative[cross]=np.where(aa<0,aa/2*fraction,bb/2*(1-fraction))*width[cross]
        net=float(np.sum((a/2+b/2)*dq));pos=float(np.sum(positive));neg=float(np.sum(negative))
        absolute=pos-neg
    if not np.isfinite([net,pos,neg,absolute]).all():raise ValueError('面积计算超出有限数值范围')
    return dict(net_area=net,positive_area=pos,negative_area=neg,absolute_area=absolute)


def snapshot(x,y,q,baseline,positions,*,coordinate,unit,baseline_kind):
    profile={key:np.asarray(value,dtype=float).tolist() for key,value in
             dict(x=x,signal=y,q=q,baseline=baseline,positions=positions).items()}
    profile.update(coordinate=coordinate,unit=unit,baseline_kind=baseline_kind)
    return profile


def validate_snapshot(profile, values, point_count=None):
    if not isinstance(profile,dict) or set(profile)!={'x','signal','q','baseline','positions','coordinate','unit','baseline_kind'}:
        raise ValueError('面积来源快照无效')
    vectors={}
    for key in ('x','signal','q','baseline','positions'):
        value=profile[key]
        if not isinstance(value,list) or not 2<=len(value)<=1_000_002 or any(type(v) not in (int,float) for v in value):raise ValueError('面积快照向量无效')
        vectors[key]=np.asarray(value,dtype=float)
        if not np.isfinite(vectors[key]).all():raise ValueError('面积快照包含非有限数值')
    p=vectors['positions'];n=len(p)
    if any(len(v)!=n for v in vectors.values()) or np.any(np.diff(p)<=0) or p[0]<0 or (point_count is not None and p[-1]>point_count-1):raise ValueError('面积快照采集位置无效')
    if profile['coordinate'] not in ('recorded_time','display_x') or profile['baseline_kind'] not in (*BASELINES,'sigmoid_horizontal') or not isinstance(profile['unit'],str):raise ValueError('面积快照方法或单位无效')
    if profile['unit']!=values.get('area_unit'):raise ValueError('面积快照单位与结果不符')
    x,y,b=vectors['x'],vectors['signal'],vectors['baseline'];kind=profile['baseline_kind']
    if kind=='linear':
        if x[-1]==x[0]:raise ValueError('直线基线的端点X不能重合')
        expected_b=y[0]+(y[-1]-y[0])/(x[-1]-x[0])*(x-x[0])
    elif kind in BASELINES:expected_b=np.full_like(y,0 if kind=='zero' else y[0] if kind=='left' else y[-1])
    else:expected_b=b
    if not np.allclose(b,expected_b,rtol=1e-11,atol=1e-11):raise ValueError('面积快照基线与方法不符')
    expected=statistics(vectors['q'],vectors['signal']-vectors['baseline'])
    for key,number in expected.items():
        actual=values.get(key)
        if type(actual) not in (int,float) or not np.isfinite(actual) or not np.isclose(actual,number,rtol=1e-11,atol=1e-11):raise ValueError('面积结果与来源快照不符')
    if not np.isclose(values.get('integral',float('nan')),expected['net_area'],rtol=1e-11,atol=1e-11):raise ValueError('净面积与积分结果不符')
    return expected


def calculate(curve,domain,positions,*,coordinate='recorded_time',baseline='linear'):
    from .transitions import _interval
    if coordinate not in ('recorded_time','display_x') or baseline not in BASELINES:raise ValueError('面积方法无效')
    x,y=curve.xy(domain)
    if len(positions)!=2 or any(type(v) not in (int,float) or not np.isfinite(v) or not 0<=v<len(x) for v in positions):raise ValueError('面积计算的两点位置无效')
    curve.validate_positions(positions);lo,hi=sorted(positions)
    if np.any(np.diff(curve.active_rows[int(np.floor(lo)):int(np.ceil(hi))+1])!=1):raise ValueError('面积不能跨被排除的采集片段')
    px,py,p=_interval(x,y,(lo,hi))
    if coordinate=='recorded_time':
        from .general_units import TIME_UNITS
        if curve.dataset.time_index is None or curve.x_unit('time') not in TIME_UNITS:raise ValueError('按时间积分需要可识别的实际时间信号')
        q=np.interp(p,np.arange(len(x)),curve.x_values('time'));q_unit=curve.x_unit('time')
        if np.any(np.diff(q)<0):raise ValueError('实际时间不能倒退')
    else:q,q_unit=px,curve.x_unit(domain)
    if baseline=='linear':
        if px[-1]==px[0]:raise ValueError('端点直线需要不同的 X 值；也可选择零或水平基线')
        base=py[0]+(py[-1]-py[0])/(px[-1]-px[0])*(px-px[0])
    else:base=np.full_like(py,0 if baseline=='zero' else py[0] if baseline=='left' else py[-1])
    unit=f'{curve.result_unit}·{q_unit}'
    result=statistics(q,py-base)
    result.update(integral=result['net_area'],value=result['net_area'],area_unit=unit,
        start_x=float(px[0]),stop_x=float(px[-1]),points=len(p),integration_domain=coordinate,
        baseline_kind=baseline,area_profile=snapshot(px,py,q,base,p,coordinate=coordinate,unit=unit,baseline_kind=baseline),
        algorithm='acquisition-adjacent endpoint interpolation; piecewise-linear trapezoids; exact zero-crossing split; no sorting or calorimetry normalization')
    return result
