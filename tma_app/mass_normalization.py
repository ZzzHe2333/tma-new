"""Per-overlay comparison at 0.50 mg; acquired data are never rewritten."""
from copy import deepcopy
import math
import re

import numpy as np

TARGET_MASS_MG = .50


def validate_mass(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int,float,np.integer,np.floating)):
        raise ValueError('每条曲线的 m 必须是大于零的有限数值（mg）')
    try:mass=float(value)
    except (OverflowError,ValueError):raise ValueError('m 必须是大于零的有限数值（mg）') from None
    if not math.isfinite(mass) or mass <= 0 or not math.isfinite(TARGET_MASS_MG/mass):
        raise ValueError('每条曲线的 m 必须是大于零的有限数值（mg）')
    return mass


def known_mass_mg(curve):
    """Only real read values; never use the annotation's 0.50 mg fallback."""
    metadata=curve.dataset.metadata
    keys=['LookupMass','Mass']
    sample=metadata.get('LookupMassSample')
    if sample and sample != [curve.sample_name]:keys.remove('LookupMass')
    for key in keys:
        values=metadata.get(key,[])
        if not values:continue
        text=str(values[0]).strip()
        match=re.fullmatch(r'([+\-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+\-]?\d+)?)\s*(mg|g)?',text,re.I)
        if match is None:continue
        units=metadata.get('LookupMassUnit' if key=='LookupMass' else 'MassUnit', metadata.get('MassUnits',['mg']))
        unit=(match.group(2) or (units[0] if units else 'mg')).strip().lower()
        if unit not in ('mg','g'):continue
        try:return validate_mass(float(match.group(1))*(1000. if unit=='g' else 1.))
        except ValueError:continue
    return None


def members(owner,document):
    if document is None or not owner._is_overlay(document.key) or owner.documents.get(document.key) is not document:
        raise ValueError('请先打开叠图，再使用统一化')
    curves=[c for c in owner._document_curves(document) if c.overlay_enabled]
    if not curves:raise ValueError('当前叠图没有可统一化的曲线')
    from .dimension_units import dimension_index
    if any(c.derived is not None or c.y_index != dimension_index(c.dataset) for c in curves):
        raise ValueError('统一化用于尺寸变化曲线；请先在叠图中选择尺寸变化信号')
    return curves


def apply(owner,document,masses):
    curves=members(owner,document)
    if owner.active_document() is not document:raise ValueError('请先切换到要统一化的叠图')
    if not isinstance(masses,dict) or set(masses)!={c.uid for c in curves}:
        raise ValueError('必须为当前叠图的每条曲线输入并确认 m')
    masses={uid:validate_mass(value) for uid,value in masses.items()}
    # Validate every displayed vector before committing any state. Repeated
    # application replaces the original mass; it does not multiply again.
    from dataclasses import replace
    for curve in curves:
        preview=replace(curve,mass_normalization_mg=masses[curve.uid])
        with np.errstate(over='ignore',invalid='ignore'):
            _,y=preview.xy(owner.domain)
        if not np.isfinite(y).all():raise ValueError(f'{curve.dataset.path.name} 换算后超出有效数值范围，请检查 m')
    owner.cancel_measurement(redraw=False)
    owner._show_document(document.key)
    options=owner.plot_options[document.key]
    if options['mass_normalization_titles'] is None:
        options['mass_normalization_titles']={key:options[key] for key in ('title','window_name','export_title')}
    for curve in curves:
        curve.mass_normalization_mg=masses[curve.uid]
        curve.save_overlay_view()
    options.update(title='Tong1-Tma',window_name='Tong1-Tma',export_title='Tong1-Tma',
                   auto_y=[True]*4,y_limits=[None]*4,y_ticks=[None]*4)
    document.plot_signature=None
    owner.touch();owner.redraw()


def invalidate_incomplete(owner,document):
    """Adding a curve requires a new confirmation for the whole comparison."""
    options=owner.plot_options.get(document.key,{})
    titles=options.get('mass_normalization_titles')
    if titles is None:return False
    curves=owner._document_curves(document)
    selected=[c for c in curves if c.overlay_enabled]
    from .dimension_units import dimension_index
    if selected and all(c.mass_normalization_mg is not None and c.derived is None and c.y_index==dimension_index(c.dataset) for c in selected):return False
    for curve in curves:
        curve.mass_normalization_mg=None
        curve.save_overlay_view()
    options.update(deepcopy(titles))
    options.update(mass_normalization_titles=None,auto_y=[True]*4,y_limits=[None]*4,y_ticks=[None]*4)
    document.plot_signature=None
    owner.statusBar().showMessage('叠图曲线已改变，请重新确认每条 m 后应用统一化',7000)
    return True


def restore(owner,document):
    members(owner,document)
    owner.cancel_measurement(redraw=False)
    owner._show_document(document.key)
    for curve in owner._document_curves(document):
        curve.mass_normalization_mg=None
        curve.save_overlay_view()
    options=owner.plot_options[document.key]
    titles=options.get('mass_normalization_titles')
    if titles is not None:options.update(deepcopy(titles))
    options.update(mass_normalization_titles=None,auto_y=[True]*4,y_limits=[None]*4,y_ticks=[None]*4)
    document.plot_signature=None
    owner.touch();owner.redraw()
