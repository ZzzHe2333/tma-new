"""TMA dimension display units over immutable canonical acquisition/working data."""
from __future__ import annotations
import re
import numpy as np

DIMENSIONS=('source','mm','µm','%','µm/m','ppm')
OFFSETS=('none','zero_size','at25')


def defaults():return {'dimension':'source','offset':'none'}


def validate(options):
    if options is None:return defaults()
    if not isinstance(options,dict) or not {'dimension','offset'}<=set(options) or set(options)-{'dimension','offset','time','temperature'} or options['dimension'] not in DIMENSIONS or options['offset'] not in OFFSETS:
        raise ValueError('TMA单位设置无效')
    from .general_units import TIME_UNITS,TEMP_UNITS
    if options.get('time','source') not in ('source',*TIME_UNITS) or options.get('temperature','source') not in ('source',*TEMP_UNITS):raise ValueError('时间或温度单位无效')
    return dict(options)


def dimension_index(dataset):
    return next((i for i,s in enumerate(dataset.signals) if any(w in s.name.casefold() for w in ('dimension','length','尺寸','长度')) and s.unit.strip().replace('μ','µ') in ('µm','um','mm')),None)


def affine(curve,index):
    """Return canonical channel -> display factor/offset/unit and reference evidence."""
    if curve.derived is not None:
        from .running_integral import source_reference
        return affine(source_reference(curve),index)
    signal=curve.dataset.signals[index];unit=signal.unit.strip().replace('μ','µ')
    result=dict(factor=1.,offset=0.,unit=signal.unit,name=signal.name,reference_mm=None,reference_25=None,status='source')
    from .general_units import spec as general_spec
    general=general_spec(curve.dataset,index,validate(curve.unit_options))
    if general is not None:return general
    if index!=dimension_index(curve.dataset):return result
    from .file_information import effective_size
    options=validate(curve.unit_options);length=effective_size(curve);source_factor=1000. if unit=='mm' else 1.
    requested=unit if options['dimension']=='source' else options['dimension']
    if requested=='um':requested='µm'
    correction=0.;status='none';reference=length
    if options['offset']=='zero_size':
        if length is not None and length>0:correction=length*1000;status='zero_size'
        else:status='missing sample size; zero-size offset not applied'
    elif options['offset']=='at25':
        ti=curve.dataset.temperature_index;reference25=None
        target=None
        if ti is not None:
            from .general_units import conversion,TEMP_ALIASES,TEMP_UNITS
            source=curve.dataset.signals[ti].unit
            if TEMP_ALIASES.get(source,source) in TEMP_UNITS:
                scale,origin,_=conversion(source,'°C','temperature');target=(25.-origin)/scale
        if target is not None and length is not None and length>0:
            from .measurement import position_at_x
            rows=curve.active_rows;x=curve.dataset.values[rows,ti];y=curve.dataset.values[rows,index]*source_factor
            try:
                position=position_at_x(x,target,0,rows);left=int(position);right=min(left+1,len(y)-1);fraction=position-left
                reference25=float(y[left]+fraction*(y[right]-y[left]))
            except ValueError:pass
        if reference25 is not None and length+reference25/1000>0:
            correction=-reference25;reference=length+reference25/1000;result['reference_25']=reference25;status='at25 first acquired adjacent crossing'
        else:status='25°C reference unavailable; offset not applied'
    if requested in ('%','µm/m','ppm') and (reference is None or reference<=0):
        requested='µm' if unit=='um' else unit;status+='; zero/missing size, unnormalized fallback'
    factor={'mm':.001,'µm':1.,'%':None,'µm/m':None,'ppm':None}[requested]
    if factor is None:factor=(.1 if requested=='%' else 1000.)/reference
    result.update(factor=source_factor*factor,offset=correction*factor,unit=requested,reference_mm=reference,status=status)
    if options['offset']=='zero_size' and correction:result['name']=signal.name.replace('Dimension Change','Dimension').replace('尺寸变化','尺寸')
    if not np.isfinite(result['factor']) or result['factor']<=0 or not np.isfinite(result['offset']):raise ValueError('尺寸单位换算超出有限范围')
    return result


def channel_label(curve,index,kind='normal'):
    if curve.unit_options is None:
        from .signal_processing import type_label
        return type_label(curve.dataset,index,kind)
    spec=affine(curve,index);label=f"{spec['name']} ({spec['unit']})" if spec['unit'] else spec['name'];unit=spec['unit']
    if kind!='normal':
        variable=curve.dataset.time_index if kind.endswith('time') else curve.dataset.temperature_index
        if variable is None:raise ValueError('文件没有所需的求导自变量')
        denominator=affine(curve,variable);shown=channel_label(curve,variable)[0]
        for _ in range(2 if kind.startswith('d2_') else 1):label=f'd({label}) / d({shown})';unit=f'({unit})/({denominator["unit"]})'
    return label,unit


def typed_affine(curve,index,kind='normal'):
    spec=affine(curve,index)
    if kind!='normal':
        variable=curve.dataset.time_index if kind.endswith('time') else curve.dataset.temperature_index
        if variable is None:raise ValueError('文件没有所需的求导自变量')
        order=2 if kind.startswith('d2_') else 1
        spec=dict(spec,factor=spec['factor']/affine(curve,variable)['factor']**order,offset=0.)
    return spec


def typed_width_factor(curve,kind):
    variable='time' if kind.endswith('time') else 'temperature'
    return curve.x_unit_factor(variable)


def variable_spec(curve,label):
    if curve.derived is not None:
        from .running_integral import source_reference
        curve=source_reference(curve)
    from .signal_processing import KINDS,type_label
    for index,signal in enumerate(curve.dataset.signals):
        for kind in KINDS:
            try:canonical=type_label(curve.dataset,index,kind)[0]
            except ValueError:continue
            if canonical==label:
                spec=typed_affine(curve,index,kind);shown,unit=channel_label(curve,index,kind)
                return dict(spec,unit=unit,label=shown)
    return dict(factor=1.,offset=0.,unit=None,label=label)


def quantity(curve,operations=None):
    """Scale a canonical processed quantity; derivatives remove additive origins."""
    if curve.derived is not None:
        from .running_integral import quantity as derived_quantity
        spec=derived_quantity(curve)
    else:spec=affine(curve,curve.y_index)
    factor,offset,unit=spec['factor'],spec['offset'],spec['unit']
    for operation in curve.operations if operations is None else operations:
        if operation.startswith('derivative:'):
            label=operation.split(':',1)[1];denominator=variable_spec(curve,label)
            factor/=denominator['factor'];offset=0.
            source_unit=next((s.unit for s in curve.dataset.signals if s.label==label),label)
            unit=f"({unit})/({denominator['unit'] or source_unit})"
        elif operation=='normalize':factor,offset,unit=1.,0.,'%'
    if not np.isfinite(factor) or factor<=0 or not np.isfinite(offset):raise ValueError('处理后的单位换算超出有限范围')
    return dict(spec,factor=factor,offset=offset,unit=unit)


def convert(values,spec):
    with np.errstate(over='ignore',invalid='ignore'):
        output=np.asarray(values,dtype=float)*spec['factor']+spec['offset']
    if not np.isfinite(output).all():raise ValueError('单位换算结果超出有限范围')
    return output


def axis_allocation(curves):
    """Keep the first unit on each axis, move incompatible units to free Y axes."""
    units={}
    for curve in curves:units.setdefault(curve.axis,curve.result_unit)
    available=[i for i in range(4) if i not in units];result={}
    for curve in curves:
        unit=curve.result_unit
        if units[curve.axis]==unit:axis=curve.axis
        else:
            compatible=[axis for axis,value in units.items() if value==unit]
            if compatible:axis=compatible[0]
            elif available:axis=available.pop(0);units[axis]=unit
            else:raise ValueError('单位换算后超过4种坐标轴单位；请先调整叠图成员')
        result[curve.uid]=axis
    return result


def processing_state(curve,candidate):
    from dataclasses import replace
    state={'history':[],'_x_cache':None}
    if curve.smooth_domain in ('signal','time','temperature'):
        reference=curve;new_reference=candidate
        if curve.smooth_domain=='signal' and curve.smooth_x_config is not None:
            config=curve.smooth_x_config
            reference=replace(curve,x_signal_index=config['index'],x_signal_type=config['type'],x_smooth_width=config['width'])
            new_reference=replace(candidate,x_signal_index=config['index'],x_signal_type=config['type'],x_smooth_width=config['width'])
            state['smooth_x_config']=dict(config,width=config['width']*typed_width_factor(candidate,config['type'])/typed_width_factor(curve,config['type']))
        domain=curve.smooth_domain
        width=curve.smooth_width*new_reference.x_unit_factor(domain)/reference.x_unit_factor(domain)
        if not np.isfinite(width):raise ValueError('单位转换后的平滑窗口超出范围')
        state['smooth_width']=width
        if curve.operations and curve.operations[-1].startswith('ls_smooth:'):
            state['operations']=curve.operations[:-1]+[f'ls_smooth:{width}:{new_reference.x_label(domain)}']
        elif curve.operations and curve.operations[-1].startswith('ls_window:'):
            state['operations']=curve.operations[:-1]+[f'ls_window:{width}']
    state['x_smooth_width']=curve.x_smooth_width*typed_width_factor(candidate,curve.x_signal_type)/typed_width_factor(curve,curve.x_signal_type)
    if (not np.isfinite(state['x_smooth_width']) or
            ('smooth_x_config' in state and not np.isfinite(state['smooth_x_config']['width']))):
        raise ValueError('单位转换后的X信号平滑窗口超出范围')
    return state


def proposal(owner,document,options):
    """Compute all shared-source/view effects before committing a units transaction."""
    from copy import deepcopy
    from dataclasses import replace
    from .workspace import default_plot_options
    selected=validate(options)
    active_overlay=owner._is_overlay(document.key)
    members=[c for c in owner._document_curves(document) if c.overlay_enabled] if active_overlay else [c for c in owner._document_curves(document) if c.normal_enabled]
    sources={(str(c.dataset.path),c.dataset.sha256) for c in members}
    changed={c.uid for c in owner.curves if (str(c.dataset.path),c.dataset.sha256) in sources and validate(c.unit_options)!=selected}
    if not changed:return {},deepcopy(owner.plot_options)
    copies={c.uid:replace(c,unit_options=dict(selected) if c.uid in changed else deepcopy(c.unit_options),history=list(c.history)) for c in owner.curves}
    states={}
    for curve in owner.curves:
        if curve.uid not in changed:continue
        candidate=copies[curve.uid];candidate.xy(owner.domain)
        state=dict(processing_state(curve,candidate),unit_options=dict(selected))
        for key,value in state.items():setattr(candidate,key,value)
        states[curve.uid]=state
    views,plots=reconcile_views(owner,copies,changed)
    for uid,state in views.items():states.setdefault(uid,{}).update(state)
    return states,plots


def reconcile_views(owner,copies,changed,reset_ids=None,skip_ids=()):
    from copy import deepcopy
    from dataclasses import replace
    from .workspace import default_plot_options
    document=owner.active_document();reset_ids=changed if reset_ids is None else reset_ids;states={}
    plots=deepcopy(owner.plot_options)
    for key,doc in owner.documents.items():
        configured=[c for c in owner._document_curves(doc) if c.uid not in skip_ids]
        if not any(c.uid in changed for c in configured):continue
        overlay=owner._is_overlay(key);view=[]
        for original in configured:
            candidate=replace(copies[original.uid],overlay_views=deepcopy(copies[original.uid].overlay_views),normal_view_details=deepcopy(copies[original.uid].normal_view_details))
            candidate.activate_view(key if overlay else None)
            if (candidate.overlay_enabled if overlay else candidate.normal_enabled):view.append(candidate)
        allocation=axis_allocation(view)
        options=plots.setdefault(key,default_plot_options())
        domain=options.get('x_domain') or owner.domain
        if domain in ('signal','time','temperature'):
            if len({candidate.x_unit(domain) for candidate in view})>1:raise ValueError('叠图X单位不一致；请先补齐样品尺寸或统一X信号')
            for axis in range(4):
                first=next((c for c in configured if c.axis==axis and (c.overlay_enabled if overlay else c.normal_enabled)),None)
                if first is not None:
                    ratio=copies[first.uid].x_unit_factor(domain)/first.x_unit_factor(domain)
                    options['axis_x_offsets'][axis]*=ratio
                    if not np.isfinite(options['axis_x_offsets'][axis]):raise ValueError('单位换算后的X偏移超出范围')
        for candidate in view:
            axis=allocation[candidate.uid];original=copies[candidate.uid]
            state=states.setdefault(candidate.uid,{})
            if overlay:
                candidate.axis=axis;candidate.save_overlay_view()
                views=deepcopy(state.get('overlay_views',original.overlay_views));views[key]=deepcopy(candidate.overlay_views[key]);state['overlay_views']=views
            else:
                details=deepcopy(state.get('normal_view_details',original.normal_view_details))
                if details is None:
                    from .overlay_views import DETAIL_FIELDS
                    details={name:deepcopy(getattr(candidate,name)) for name in DETAIL_FIELDS}
                details['axis']=axis;state['normal_view_details']=details
            if key==document.key:state['axis']=axis
        for curve in configured:
            if curve.uid in reset_ids:
                for axis in {curve.axis,allocation.get(curve.uid,curve.axis)}:
                    options['auto_y'][axis]=True;options['y_limits'][axis]=None;options['y_ticks'][axis]=None
        if any(c.uid in reset_ids and (copies[c.uid].x_unit(domain)!=c.x_unit(domain) or copies[c.uid].x_unit_factor(domain)!=c.x_unit_factor(domain) or (domain=='signal' and c.x_signal_index==dimension_index(c.dataset))) for c in configured):
            options.update(auto_x=True,x_limits=None,x_ticks=None)
    # All configured views must be valid before the live state is touched.
    return states,plots
