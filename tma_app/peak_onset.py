"""Baseline-relative peaks and two-tangent onset, in acquired order."""
from copy import deepcopy
import numpy as np
from .numerics import _fit
from .transitions import _interval,_steepest

KINDS=('peak_max','onset_point')


def defaults():
    return dict(onset=dict(manual=False,inflection=True,labels=dict(x=True,y=False,time=False,temperature=True,signal=False)),
                peak=dict(limits=True,height=True,width=False,maximum='temperature'))


def validate(value):
    base=defaults()
    if not isinstance(value,dict) or set(value)!=set(base):raise ValueError('峰／始点参数无效')
    o,p=value['onset'],value['peak']
    if not isinstance(o,dict) or set(o)!=set(base['onset']) or type(o['manual']) is not bool or type(o['inflection']) is not bool:raise ValueError('始点切线选项无效')
    if not isinstance(o['labels'],dict) or set(o['labels'])!=set(base['onset']['labels']) or any(type(v) is not bool for v in o['labels'].values()):raise ValueError('始点标注选项无效')
    if not isinstance(p,dict) or set(p)!=set(base['peak']) or any(type(p[k]) is not bool for k in ('limits','height','width')) or p['maximum'] not in ('none','time','temperature','signal'):raise ValueError('峰标注选项无效')
    return deepcopy(value)


def interval(curve,entry,positions):
    config=validate(entry['peak_onset']);x,y=curve.xy(entry['domain'])
    count=4 if entry['kind']=='onset_point' and config['onset']['manual'] else 2
    if len(positions)!=count or any(isinstance(p,bool) or not isinstance(p,(int,float,np.integer,np.floating)) or not np.isfinite(p) or not 0<=p<len(x) for p in positions):raise ValueError('峰／始点控制点无效')
    positions=list(map(float,positions));curve.validate_positions(positions)
    if count==2:positions.sort()
    if any(a>b for a,b in zip(positions,positions[1:])):raise ValueError('手动切线点须按采集顺序排列')
    rows=curve.active_rows[int(np.floor(positions[0])):int(np.ceil(positions[-1]))+1]
    if np.any(np.diff(rows)!=1):raise ValueError('峰／始点分析不能跨被排除的采集片段')
    px,py,sp=_interval(x,y,(positions[0],positions[-1]))
    return config,x,y,positions,px,py,sp


def _fit_record(x,y,positions):
    m,b,r2=_fit(x,y)
    return dict(slope=m,intercept=b,r2=r2,x_start=float(x[0]),x_stop=float(x[-1]),
                position_start=float(positions[0]),position_stop=float(positions[-1]),points=len(x))


def _onset_windows(px,py,sp,inflection,*,fraction=.125):
    n=len(px);width=max(3,int(np.ceil(n*fraction)))
    if n<6:raise ValueError('自动始点至少需要6个采集点')
    feature,left,right=_steepest(px,py,width,n-1,max(1,width//2))
    found=False
    if inflection:
        candidates=[]
        for i in range(width,n):
            lo=max(width,i-width//2);hi=min(n,i+width//2+1)
            xx=px[lo:hi]-px[i];span=float(np.max(np.abs(xx)))
            if hi-lo<3 or span==0:continue
            design=np.column_stack((np.ones(len(xx)),xx/span,(xx/span)**2))
            coefficients,_,rank,_=np.linalg.lstsq(design,py[lo:hi]-py[i],rcond=None)
            if rank==3:candidates.append((i,float(coefficients[1]/span),float(2*coefficients[2]/span**2)))
        local_span=float(np.ptp(px))*width/n
        tolerance=512*np.finfo(float).eps*float(np.ptp(py))/local_span**2 if local_span else 0.
        strong=[c for c in candidates if abs(c[2])>tolerance];available={c[0] for c in candidates};crossings=[]
        for a,b in zip(strong,strong[1:]):
            if any(i not in available for i in range(a[0],b[0]+1)):continue
            if a[2]*b[2]<0:
                fraction=-a[2]/(b[2]-a[2])
                crossings.append((abs(a[1]+fraction*(b[1]-a[1])),a[0]+fraction*(b[0]-a[0])))
        if crossings:
            maximum=max(p[0] for p in crossings)
            selected=min((p for p in crossings if np.isclose(p[0],maximum,rtol=1e-10,atol=0)),key=lambda p:(abs(p[1]-(width+n-1)/2),p[1]))
            if maximum>0:
                feature=selected[1];found=True
                center=int(round(feature));left=max(width,center-width//2);right=min(n-1,left+width-1);left=max(width,right-width+1)
    first=_fit_record(px[:width],py[:width],sp[:width]);last=_fit_record(px[left:right+1],py[left:right+1],sp[left:right+1])
    feature_x=float(np.interp(feature,np.arange(n),px))
    if found:
        # The checked option constructs a tangent through the acquired curve
        # at the selected curvature crossing. Its finite window is explicit.
        center_y=float(np.interp(feature,np.arange(n),py));xx=px[left:right+1]-feature_x;span=float(np.max(np.abs(xx)))
        coefficients,_,rank,_=np.linalg.lstsq(np.column_stack((np.ones(len(xx)),xx/span,(xx/span)**2)),py[left:right+1]-center_y,rcond=None)
        if rank==3:
            last['slope']=float(coefficients[1]/span);last['intercept']=center_y-last['slope']*feature_x
            fitted=last['slope']*px[left:right+1]+last['intercept'];total=float(np.sum((py[left:right+1]-np.mean(py[left:right+1]))**2))
            last['r2']=float(1-np.sum((py[left:right+1]-fitted)**2)/total) if total else 1.
    return [first,last],feature_x,found


def values(curve,entry,positions):
    if entry['kind'] not in KINDS:raise ValueError('峰／始点方法无效')
    config,x,y,positions,px,py,sp=interval(curve,entry,positions)
    if entry['kind']=='peak_max':
        if px[-1]==px[0]:raise ValueError('峰基线的两端需要不同X值')
        m=float((py[-1]-py[0])/(px[-1]-px[0]));b=float(py[0]-m*px[0]);baseline=py[0]+m*(px-px[0]);residual=py-baseline
        maximum=float(np.max(np.abs(residual)));peak=int(np.flatnonzero(np.isclose(np.abs(residual),maximum,rtol=1e-12,atol=0))[0]);height=float(residual[peak])
        left=right=None
        if height!=0:
            level=abs(height)/2;response=residual*np.sign(height)
            for i in range(peak-1,-1,-1):
                if response[i]<=level<=response[i+1] and response[i]!=response[i+1]:
                    left=float(px[i]+(px[i+1]-px[i])*(level-response[i])/(response[i+1]-response[i]));break
            for i in range(peak,len(px)-1):
                if response[i]>=level>=response[i+1] and response[i]!=response[i+1]:
                    right=float(px[i]+(px[i+1]-px[i])*(level-response[i])/(response[i+1]-response[i]));break
        result=dict(max_x=float(px[peak]),max_y=float(py[peak]),peak_position=float(sp[peak]),baseline_y=float(baseline[peak]),height=height,value=height,
                    baseline_slope=m,baseline_intercept=b,half_left=left,half_right=right,width_half_height=None if left is None or right is None else abs(right-left),
                    algorithm='largest absolute acquired deviation from endpoint linear baseline; first acquired tie; connected adjacent half-height crossings; no sorting')
    else:
        o=config['onset'];found=False;feature=None
        if o['manual']:
            fits=[_fit_record(*_interval(x,y,positions[i:i+2])) for i in (0,2)]
            method='two manual acquired-interval OLS tangents with adjacent-interpolated endpoints'
        else:
            fits,feature,found=_onset_windows(px,py,sp,o['inflection'])
            method='application initial12.5% OLS baseline; local12.5% final window; '+('curve tangent at selected quadratic curvature crossing' if found else 'steepest local OLS fallback')+'; native baseline/tie rules unverified'
        a,b=fits;denominator=a['slope']-b['slope'];scale=max(abs(a['slope']),abs(b['slope']))
        if scale==0 or abs(denominator)<=128*np.finfo(float).eps*scale:raise ValueError('始点两条切线平行，无法确定交点')
        ox=float((b['intercept']-a['intercept'])/denominator);oy=float(a['slope']*ox+a['intercept'])
        from .measurement import position_at_x
        try:position=position_at_x(x,ox,positions[len(positions)//2],curve.active_rows)
        except ValueError:position=None
        result=dict(onset_x=ox,onset_y=oy,onset_position=position,value=ox,inflection_x=feature,inflection_found=found,fits=fits,algorithm=method+'; acquisition order, no sorting or gap bridging')
    numbers=[v for v in result.values() if isinstance(v,(int,float))]
    if not np.isfinite(numbers).all():raise ValueError('峰／始点计算超出有限范围')
    return result


def add_channels(values,channels,kind):
    position=values['peak_position'] if kind=='peak_max' else values['onset_position']
    if position is not None:
        from .point_labels import channel_values
        values.update(channel_values(channels,position))


def label_text(entry,curve):
    v=entry['values'];config=entry['peak_onset'];lines=[];unit=curve.result_unit
    if entry['kind']=='peak_max':
        p=config['peak'];choice=p['maximum']
        if choice!='none' and choice+'_at_point' in v:lines.append(f"{dict(time='t',temperature='T',signal='X')[choice]} = {v[choice+'_at_point']:.6g} {v[choice+'_unit']}")
        if p['height']:lines.append(f"高度 {v['height']:.6g} {unit}")
        if p['width']:lines.append('半高宽 '+('不可用' if v['width_half_height'] is None else f"{v['width_half_height']:.6g} {curve.x_unit(entry['domain'])}"))
    else:
        labels=config['onset']['labels'];domain=entry['domain'];seen=[]
        def identity(name):
            if name!='signal':return name
            signal=entry.get('point_signal')
            if signal and signal['type']=='normal':
                if signal['index']==curve.dataset.time_index:return 'time'
                if signal['index']==curve.dataset.temperature_index:return 'temperature'
            return 'signal'
        primary=identity(domain)
        if labels['x']:
            lines.append(f"始点 {v['onset_x']:.6g} {curve.x_unit(domain)}");seen.append((primary,v['onset_x'],curve.x_unit(domain)))
        if labels['y']:lines.append(f"Y = {v['onset_y']:.6g} {unit}")
        for key in ('time','temperature','signal'):
            if not labels[key]:continue
            value=v.get(key+'_at_point');channel_unit=v.get(key+'_unit')
            channel=identity(key)
            if value is None and primary==channel:value=v['onset_x'];channel_unit=curve.x_unit(domain)
            if value is None:continue
            if any(k==channel and u==channel_unit and np.isclose(n,value,rtol=1e-12,atol=0) for k,n,u in seen):continue
            lines.append(f"{dict(time='t',temperature='T',signal='X')[key]} = {value:.6g} {channel_unit}")
            seen.append((channel,value,channel_unit))
    return '\n'.join(lines)
