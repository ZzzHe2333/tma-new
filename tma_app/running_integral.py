"""Recorded-time running peak area as a derived quantity, never acquired data."""
from copy import deepcopy
from dataclasses import replace
import re
import numpy as np
from scipy.integrate import cumulative_trapezoid

KIND = 'peak_running_integral'


def options(mode='integral', inverted=False, baseline='parent'):
    if mode not in ('integral', 'percent') or type(inverted) is not bool or baseline not in ('parent', 'zero'):
        raise ValueError('执行积分类型无效')
    return dict(mode=mode, inverted=inverted, baseline=baseline)


def calculate(time, signal, baseline, *, mode='integral', inverted=False):
    options(mode, inverted)
    t, y, b = (np.asarray(a, dtype=float) for a in (time, signal, baseline))
    if t.ndim != 1 or len(t) < 2 or y.shape != t.shape or b.shape != t.shape or not all(np.isfinite(a).all() for a in (t, y, b)):
        raise ValueError('执行积分需要至少两个有限的配对采集点')
    if np.any(np.diff(t) < 0) or t[-1] <= t[0]:
        raise ValueError('实际采集时间不能下降，且总时长须大于零')
    with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
        raw = cumulative_trapezoid(y-b, t, initial=0)
        if not np.isfinite(raw).all(): raise ValueError('累计积分超出有限范围')
        area = float(raw[-1])
        if mode == 'percent':
            variation = float(np.sum(abs(np.diff(raw))))
            if area == 0 or abs(area) <= 128*np.finfo(float).eps*variation:
                raise ValueError('有符号面积为零或数值抵消，不能计算面积百分比')
            result = 100*raw/area
            if inverted: result = 100-result
        else: result = -raw if inverted else raw.copy()
    if not np.isfinite(result).all(): raise ValueError('累计积分超出有限范围')
    return dict(values=result, cumulative=raw, terminal_area=area)


def source_reference(curve):
    """Use the complete frozen parent context for typed X and unit references."""
    d = curve.derived
    ref = replace(curve, derived=None, y_index=d['source_y_index'],
                  data_indices=list(d['source_rows']), data_limit_spec=None,
                  working=None, working_rows=None, operations=list(d['source_operations']), reset_time=False)
    ref._x_cache = None
    return ref


def x_values(curve, domain, *, full=False, canonical=False):
    ref = source_reference(curve)
    vector = ref.x_values(domain, canonical=True)
    positions = np.asarray(curve.derived['positions'])
    if not full: positions = positions[curve.active_rows]
    output = np.interp(positions, np.arange(len(vector)), vector)
    index = ref.x_signal_index if domain == 'signal' else (ref.dataset.time_index if domain == 'time' else ref.dataset.temperature_index)
    if not full and curve.reset_time and (domain == 'time' or domain == 'signal' and index == ref.dataset.time_index and ref.x_signal_type == 'normal'):
        output -= curve.time_origin
    if not canonical:
        from .dimension_units import affine, typed_affine, convert
        output = convert(output, typed_affine(ref, index, ref.x_signal_type) if domain == 'signal' else affine(ref, index))
    return output


def quantity(curve):
    from .dimension_units import quantity as source_quantity, affine
    d = curve.derived
    if d['mode'] == 'percent': return dict(factor=1., offset=0., unit='%', name='面积百分比')
    ref = source_reference(curve)
    ordinate = source_quantity(ref)
    time = affine(ref, ref.dataset.time_index)
    return dict(factor=ordinate['factor']*time['factor']/d['creation_factor'], offset=0.,
                unit=f"{ordinate['unit']}·{time['unit']}", name='累计积分')


def logical_dataset(curve):
    """Interpolated table view; curve.dataset remains the original acquisition."""
    from .reader import Signal
    d = curve.derived
    rows = np.asarray(d['source_rows']); p = np.asarray(d['positions'])
    frame = np.column_stack([np.interp(p, np.arange(len(rows)), curve.dataset.values[rows, i]) for i in range(len(curve.dataset.signals))])
    frame[:, curve.y_index] = d['base_values']
    signals = list(curve.dataset.signals)
    signals[curve.y_index] = Signal(d['label'], d['creation_unit'])
    return replace(curve.dataset, values=frame, signals=signals)


def descriptor(curve, parent, parent_id, *, mode='integral', inverted=False, baseline='parent'):
    """Freeze a compatible confirmed peak; no source or parent is mutated."""
    from .peak_integration import KINDS, profile
    from .dimension_units import quantity as source_quantity, affine
    config = options(mode, inverted, baseline)
    if curve.derived is not None or parent.get('kind') not in KINDS or not parent.get('interactive', {}).get('confirmed'):
        raise ValueError('请先在原始尺寸曲线上完成峰积分')
    if (parent.get('curve_id') != curve.uid or parent.get('sha256') != curve.dataset.sha256
            or parent.get('operations') != curve.operations or parent.get('transform') != curve.result_transform(parent['domain'])
            or parent.get('signal') != curve.result_label): raise ValueError('峰积分与当前曲线状态不一致，请重新积分')
    state = parent['interactive']; positions = state.get('positions', state['indices'])
    if parent['kind'] == 'peak_sigmoid':
        from .sigmoidal import validate_snapshot
        snapshot = parent['values']['sigmoid_profile']; validate_snapshot(snapshot, len(curve.active_rows))
        p, x, y, t, b = (np.asarray(snapshot[key], dtype=float) for key in ('positions', 'x', 'signal', 'time', 'baseline'))
    else:
        _, _, _, _, x, y, p, t, b, _, _ = profile(curve, parent, positions)
    if baseline == 'zero': b = np.zeros_like(y)
    output = calculate(t, y, b, mode=mode, inverted=inverted)
    factor = source_quantity(curve)['factor']*affine(curve, curve.dataset.time_index)['factor']
    result = dict(kind=KIND, parent_id=parent_id, source_curve_uid=curve.uid, source_sha=curve.dataset.sha256,
                  source_y_index=curve.y_index, source_rows=curve.active_rows.tolist(), positions=p.tolist(),
                  source_operations=list(curve.operations), source_transform=deepcopy(parent['transform']),
                  profile={key: value.tolist() for key, value in dict(x=x, signal=y, time=t, baseline=b).items()},
                  base_values=output['values'].tolist(), creation_factor=factor,
                  time_origin=curve.time_origin,
                  creation_unit='%' if mode == 'percent' else f'{curve.result_unit}·{curve.x_unit("time")}',
                  label='面积百分比' if mode == 'percent' else '累计积分', **config)
    validate(result, curve.dataset)
    return result


def create_curve(source, d):
    """An independently styled Y4 quantity sharing the immutable acquisition."""
    import uuid
    validate(d,source.dataset)
    return replace(source,uid=uuid.uuid4().hex,derived=deepcopy(d),axis=3,color='#0000ff',
                   scale=1.,offset=0.,working=None,operations=[],y_type='normal',
                   data_indices=None,data_limit_spec=None,history=[],smooth_source=None,
                   smooth_domain=None,smooth_width=0.,smooth_reuse=False,smooth_base_ops=[],
                   smooth_x_config=None,working_rows=None,smooth_source_rows=None,
                   legend_text=d['label'],normal_appearance=None,overlay_appearance=None,
                   overlay_views={},active_overlay_key=None,normal_view_details=None,
                   appearance_mode='normal',normal_enabled=True,overlay_enabled=False)


def validate_links(curves,results):
    """A computed series must retain a real source and its confirmed parent."""
    for curve in curves:
        d=curve.derived
        if d is None:continue
        source=next((c for c in curves if c.uid==d['source_curve_uid'] and c.derived is None),None)
        parents=[r for r in results if r.get('analysis_id')==d['parent_id']]
        if source is None or source.dataset.path!=curve.dataset.path or source.dataset.sha256!=d['source_sha'] or len(parents)!=1:
            raise ValueError('派生积分缺少对应的源曲线或峰积分')
        parent=parents[0]
        if (parent.get('curve_id')!=source.uid or parent.get('kind') not in ('peak_linear','peak_sigmoid')
                or not parent.get('interactive',{}).get('confirmed') or parent.get('transform')!=d['source_transform']
                or parent.get('operations')!=d['source_operations']):raise ValueError('派生积分与峰积分来源不符')
        if d['creation_unit']!=('%' if d['mode']=='percent' else parent['values']['area_unit']):raise ValueError('派生积分单位与峰积分来源不符')
        bounds=parent['interactive'].get('positions',parent['interactive']['indices'])
        if not np.allclose([d['positions'][0],d['positions'][-1]],sorted(bounds[:2]),rtol=0,atol=1e-12):raise ValueError('派生积分与峰积分界限不符')
        from .dimension_units import quantity as source_quantity,affine
        transform=d['source_transform'];ref=source_reference(curve)
        ref.unit_options=deepcopy(transform.get('units'));ref.sample_size_mm=transform.get('units_reference',{}).get('original_size_mm',source.sample_size_mm)
        factor=source_quantity(ref)['factor']*affine(ref,ref.dataset.time_index)['factor']
        if not np.isclose(factor,d['creation_factor'],rtol=1e-12,atol=0):raise ValueError('派生积分单位比例与来源不符')
        ref.reset_time=transform.get('reset_time',False)
        recorded_time=np.interp(d['positions'],np.arange(len(ref.active_rows)),ref.x_values('time'))
        if not np.allclose(recorded_time,d['profile']['time'],rtol=1e-12,atol=1e-12):raise ValueError('派生积分与实际采集时间不符')
        if d['baseline']=='parent':
            p=d['profile']
            if parent['kind']=='peak_sigmoid':
                baseline=parent['values']['sigmoid_profile']['baseline']
            else:
                x,y=np.asarray(p['x']),np.asarray(p['signal'])
                baseline=y[0]+(y[-1]-y[0])/(x[-1]-x[0])*(x-x[0])
            if not np.allclose(baseline,p['baseline'],rtol=1e-12,atol=1e-12):raise ValueError('派生积分与父积分基线不符')


def validate(d, dataset):
    """Strict portable descriptor, with independent cumulative recomputation."""
    required = {'kind','parent_id','source_curve_uid','source_sha','source_y_index','source_rows','positions',
                'source_operations','source_transform','profile','base_values','creation_factor','creation_unit','label',
                'mode','inverted','baseline','time_origin'}
    if not isinstance(d, dict) or set(d) != required or d['kind'] != KIND: raise ValueError('派生积分描述无效')
    options(d['mode'], d['inverted'], d['baseline'])
    for key in ('parent_id', 'source_curve_uid'):
        if not isinstance(d[key], str) or not re.fullmatch('[0-9a-f]{32}', d[key]): raise ValueError('派生积分来源标识无效')
    if d['source_sha'] != dataset.sha256: raise ValueError('派生积分来源指纹不符')
    if type(d['source_y_index']) is not int or not 0 <= d['source_y_index'] < len(dataset.signals): raise ValueError('派生积分来源信号无效')
    rows = d['source_rows']
    if not isinstance(rows, list) or len(rows) < 2 or any(type(r) is not int or not 0 <= r < len(dataset.values) for r in rows) or any(a >= b for a,b in zip(rows, rows[1:])): raise ValueError('派生积分来源行无效')
    if not isinstance(d['source_operations'], list) or len(d['source_operations']) > 10000 or any(not isinstance(v,str) or len(v)>4096 for v in d['source_operations']) or not isinstance(d['source_transform'],dict): raise ValueError('派生积分处理来源无效')
    for key in ('creation_unit','label'):
        if not isinstance(d[key],str) or len(d[key])>4096: raise ValueError('派生积分名称或单位无效')
    factor=d['creation_factor']
    if isinstance(factor,bool) or not isinstance(factor,(float,int)) or not np.isfinite(factor) or factor<=0: raise ValueError('派生积分单位比例无效')
    if isinstance(d['time_origin'],bool) or not isinstance(d['time_origin'],(int,float)) or not np.isfinite(d['time_origin']):raise ValueError('派生积分时间原点无效')
    profile=d['profile']
    if not isinstance(profile,dict) or set(profile)!={'x','signal','time','baseline'}: raise ValueError('派生积分曲线快照无效')
    def vector(value):
        if not isinstance(value,list) or len(value)<2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) for v in value): raise ValueError('派生积分数值向量无效')
        a=np.asarray(value,dtype=float)
        if a.ndim!=1 or not np.isfinite(a).all(): raise ValueError('派生积分数值向量无效')
        return a
    p=vector(d['positions']); values=vector(d['base_values']); vectors={k:vector(v) for k,v in profile.items()}
    if any(v.shape!=p.shape for v in (values,*vectors.values())) or np.any(np.diff(p)<=0) or p[0]<0 or p[-1]>len(rows)-1: raise ValueError('派生积分采集位置无效')
    expected=np.unique(np.r_[p[0],np.arange(np.ceil(p[0]),np.floor(p[-1])+1),p[-1]])
    if not np.array_equal(expected,p) or np.any(np.diff(np.asarray(rows)[int(np.floor(p[0])):int(np.ceil(p[-1]))+1])!=1): raise ValueError('派生积分不能遗漏采集点或跨越排除片段')
    if d['baseline']=='zero' and np.any(vectors['baseline']!=0): raise ValueError('绝对积分的基线须为零')
    expected=calculate(vectors['time'],vectors['signal'],vectors['baseline'],mode=d['mode'],inverted=d['inverted'])['values']
    if not np.allclose(expected,values,rtol=1e-12,atol=0): raise ValueError('派生积分数值与来源快照不符')
    return len(p)
