"""Inert per-signal cursor/feature-offset templates; current data stay local."""
from copy import deepcopy
import math
import numpy as np

FAMILIES=('peak','onset','step','signal')


def family(entry):
    if entry.get('purpose')=='data_limits' or len(entry['interactive']['indices'])!=2:return None
    return {'peak_max':'peak','peak_linear':'peak','peak_sigmoid':'peak','onset_point':'onset','step_transition':'step','glass_transition':'step',
            'signal_change':'signal'}.get(entry['kind'])


def basis(curve,entry):
    selected=family(entry);domain=entry['domain']
    if selected=='signal':
        label=domain if domain!='signal' else curve.dataset.signals[curve.x_signal_index].name+':'+curve.x_signal_type
        return dict(family=selected,domain=domain,label=label,unit='fraction')
    return dict(family=selected,domain=domain,label=curve.x_label(domain),unit=curve.x_unit(domain))


def default_rule(curve,entry):
    point=dict(mode='fraction',offset=.05) if family(entry)=='signal' else dict(mode='cursor',offset=0.)
    return dict(basis(curve,entry),endpoints=[dict(point),dict(point)])


def validate_rule(rule):
    if not isinstance(rule,dict) or set(rule)!={'family','domain','label','unit','endpoints'} or rule['family'] not in FAMILIES or rule['domain'] not in ('time','temperature','signal'):raise ValueError('自动界限模板无效')
    if any(not isinstance(rule[k],str) or len(rule[k])>4096 for k in ('label','unit')):raise ValueError('自动界限信号无效')
    points=rule['endpoints']
    if not isinstance(points,list) or len(points)!=2:raise ValueError('自动界限需要两个端点')
    for point in points:
        if not isinstance(point,dict) or set(point)!={'mode','offset'} or point['mode'] not in (('cursor','fraction') if rule['family']=='signal' else ('cursor','offset')):raise ValueError('自动界限端点无效')
        offset=point['offset']
        if isinstance(offset,bool) or not isinstance(offset,(int,float)) or not math.isfinite(offset):raise ValueError('自动界限偏移须为有限数')
        if point['mode']=='fraction' and not 0<offset<1:raise ValueError('导数分数须大于0且小于1')
    return deepcopy(rule)


def key(rule):return tuple(rule[k] for k in ('family','domain','label','unit'))


def validate_rules(rules):
    if not isinstance(rules,list) or len(rules)>1000:raise ValueError('自动界限模板列表无效')
    result=[validate_rule(r) for r in rules]
    if len({key(r) for r in result})!=len(result):raise ValueError('自动界限模板重复')
    return result


def replace_rule(rules,rule):
    rule=validate_rule(rule)
    return validate_rules([r for r in validate_rules(rules) if key(r)!=key(rule)]+[rule])


def anchor(curve,entry):
    kind=family(entry)
    if kind is None:raise ValueError('此分析的自动界限尚未定义，请使用恢复初始界限')
    x,y=curve.xy(entry['domain']);state=entry['interactive'];positions=state.get('positions',state['indices'])
    from .transitions import _interval,_steepest
    px,py,sp=_interval(x,y,sorted(positions))
    if kind=='signal':return float(px[int(np.argmax(py))])
    if kind=='peak':
        if entry['kind'] in ('peak_linear','peak_sigmoid'):
            from .peak_integration import values
            return values(curve,entry,positions)['max_x']
        from .peak_onset import values
        return values(curve,entry,positions)['max_x']
    if kind=='onset':
        from .peak_onset import _onset_windows
        _,value,_=_onset_windows(px,py,sp,True);return value
    n=len(px)
    if n<9:raise ValueError('自动步阶界限至少需要9个点')
    outer=max(3,int(np.ceil(n*.2)));center,_,_=_steepest(px,py,outer,n-outer-1,max(1,n//20))
    return float(px[center])


def positions(curve,entry,rule):
    rule=validate_rule(rule)
    if key(rule)!=key(default_rule(curve,entry)):raise ValueError('自动界限的X信号或单位不匹配')
    from .measurement import position_at_x
    old=entry['interactive'].get('positions',entry['interactive']['indices']);x,_=curve.xy(entry['domain'])
    if rule['family']=='signal':return fraction_positions(curve,entry,rule)
    reference=anchor(curve,entry) if any(p['mode']=='offset' for p in rule['endpoints']) else None
    result=[]
    for i,point in enumerate(rule['endpoints']):
        if point['mode']=='cursor':result.append(float(old[i]))
        else:
            from .general_units import source_bound
            target=source_bound(reference+point['offset'],dict(factor=1.,offset=0.),x)
            result.append(position_at_x(x,target,old[i],curve.active_rows))
    return result


def fraction_positions(curve,entry,rule):
    """Derivative-fraction boundaries between neighboring resolved peaks.

    Each peak uses its own fractional height, so adjacent analyses at the same
    fraction share a boundary. Peak filtering/plateau and active-interval
    selection are explicit application policies, not verified native internals.
    """
    from .data_limits import segments
    from .signal_processing import local_fit
    from scipy.signal import find_peaks
    from .transitions import _interval
    from .measurement import position_at_x
    x,y=curve.xy(entry['domain']);old=entry['interactive'].get('positions',entry['interactive']['indices'])
    if all(p['mode']=='cursor' for p in rule['endpoints']):return list(map(float,old))
    profiles=[];choices=[]
    for section in segments(curve.active_rows):
        xx=x[section];yy=y[section]
        if len(xx)<5:continue
        try:derivative=np.abs(local_fit(xx,yy,0.,1))
        except ValueError:
            derivative=np.zeros(len(xx))
            from .numerics import _fit
            for i in range(len(xx)):
                lo=max(0,min(i-2,len(xx)-5));hi=lo+5
                try:derivative[i]=abs(_fit(xx[lo:hi],yy[lo:hi])[0])
                except ValueError:pass
        highest=float(np.max(derivative))
        if highest==0 or float(np.ptp(derivative))<=512*np.finfo(float).eps*highest:continue
        peaks=list(find_peaks(derivative,prominence=highest*1e-6,plateau_size=1)[0])
        if derivative[0]>derivative[1]:peaks.insert(0,0)
        if derivative[-1]>derivative[-2]:peaks.append(len(xx)-1)
        profile=(section,xx,derivative,peaks);profiles.append(profile)
        choices += [(float(derivative[p]),section.start+int(p),profile,int(p)) for p in peaks if min(old)<=section.start+p<=max(old)]
    if not choices:raise ValueError('当前界限内没有可识别的导数峰，请扩大范围或使用当前光标')
    height,_,profile,peak=max(choices,key=lambda p:(p[0],-p[1]));section,xx,magnitude,peaks=profile
    def edge(start,stop,fraction):
        direction=1 if stop>start else -1;level=magnitude[start]*fraction;previous=start
        for i in range(start+direction,stop+direction,direction):
            if magnitude[i]<=level and magnitude[i]!=magnitude[previous]:return previous+(i-previous)*(level-magnitude[previous])/(magnitude[i]-magnitude[previous])
            previous=i
        return None
    result=[];peak_slot=peaks.index(peak)
    for endpoint,point in enumerate(rule['endpoints']):
        if point['mode']=='cursor':result.append(float(old[endpoint]));continue
        direction=-1 if endpoint==0 else 1;boundary=0. if direction<0 else float(len(xx)-1)
        for slot in range(peak_slot+direction,len(peaks) if direction>0 else -1,direction):
            other=int(peaks[slot]);own=edge(peak,other,point['offset']);neighbor=edge(other,peak,point['offset'])
            if own is None or neighbor is None or direction*(neighbor-own)<0:continue
            if own==neighbor:boundary=float(own);break
            vx,_,vp=_interval(xx,magnitude,sorted((own,neighbor)))
            target=(float(np.interp(own,np.arange(len(xx)),xx))+float(np.interp(neighbor,np.arange(len(xx)),xx)))/2
            local=position_at_x(vx,target,(len(vx)-1)/2)
            boundary=float(np.interp(local,np.arange(len(vp)),vp));break
        result.append(section.start+boundary)
    return result
