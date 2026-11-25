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
    from .mass_cache import peek_memory
    try:
        cached = peek_memory(curve.sample_name)
        value = match_mass_mg(cached)
        if value is not None: return value
    except (ValueError, OSError): pass
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


def match_mass_mg(match):
    if match is None or match.value is None or match.unit not in ('', 'mg', 'g'): return None
    try: return validate_mass(match.value * (1000. if match.unit == 'g' else 1.))
    except ValueError: return None


def members(owner,document):
    if document is None or not owner._is_overlay(document.key) or owner.documents.get(document.key) is not document:
        raise ValueError('请先打开叠图，再使用统一化')
    curves=[c for c in owner._document_curves(document) if c.overlay_enabled]
    if not curves:raise ValueError('当前叠图没有可统一化的曲线')
    from .dimension_units import dimension_index
    if any(c.derived is not None or c.y_index != dimension_index(c.dataset) for c in curves):
        raise ValueError('统一化用于尺寸变化曲线；请先在叠图中选择尺寸变化信号')
    return curves


MARKER_KINDS = ('dimension_change', 'signal_change', 'height_change', 'signal_max')


def locked_marker(entry):
    return bool(entry.get('normalized_document'))


def replace_document_markers(owner, key, markers=()):
    retained = [result for result in owner.results if result.get('normalized_document') != key]
    if markers or len(retained) != len(owner.results):
        owner.results[:] = retained
        owner.results.extend(markers)
        owner.refresh_results()


def normalized_markers(owner, document, curve, source_transform):
    """Retain confirmed source cursors as independent, locked overlay labels."""
    from .measurement import point_values
    x, y = curve.xy(owner.domain)
    copies = []
    expected = dict(source_transform)
    expected.pop("offset", None)
    for source in list(owner.results):
        if (locked_marker(source) or source.get('kind') not in MARKER_KINDS
                or source.get('curve_id') != curve.uid or source.get('domain') != owner.domain
                or source.get('signal') != curve.result_label
                or {k: v for k, v in source.get('transform', {}).items() if k != 'offset'} != expected
                or source.get('operations') != curve.operations
                or not source.get('interactive', {}).get('confirmed')):
            continue
        entry = deepcopy(source)
        entry.pop('analysis_id', None)
        entry['normalized_document'] = document.key
        entry['transform'] = curve.result_transform(owner.domain)
        options = entry.setdefault('annotation', {})
        options.pop('hidden', None)
        options.get('text_style', {}).pop('hidden', None)
        for style in options.get('label_styles', {}).values():
            style.pop('hidden', None)
        state = entry['interactive']
        if state.get('manual_y'):
            factor = curve.mass_normalization_factor
            source_offset = source['transform']['offset']
            target_offset = curve.offset
            if curve.unit_options is not None:
                from .dimension_units import affine
                unit_factor = affine(curve, curve.y_index)['factor']
                source_offset *= unit_factor
                target_offset *= unit_factor
            state['manual_y'] = [None if value is None else (value-source_offset)*factor+target_offset
                                 for value in state['manual_y']]
        entry['values'] = point_values(x, y, entry['kind'], state['indices'],
                                      state.get('positions'), state.get('manual_y'))
        copies.append(entry)
    return copies


def apply(owner,document,masses):
    curves=members(owner,document)
    if owner.active_document() is not document:raise ValueError('请先切换到要统一化的叠图')
    if not isinstance(masses,dict) or set(masses)!={c.uid for c in curves}:
        raise ValueError('必须为当前叠图的每条曲线输入并确认 m')
    masses={uid:validate_mass(value) for uid,value in masses.items()}
    # Validate every displayed vector before committing any state. Repeated
    # application replaces the original mass; it does not multiply again.
    from dataclasses import replace
    markers = []
    for curve in curves:
        source = replace(curve, mass_normalization_mg=None)
        source_transform = source.result_transform(owner.domain)
        preview=replace(curve,mass_normalization_mg=masses[curve.uid])
        with np.errstate(over='ignore',invalid='ignore'):
            _,y=preview.xy(owner.domain)
        if not np.isfinite(y).all():raise ValueError(f'{curve.dataset.path.name} 换算后超出有效数值范围，请检查 m')
        markers.extend(normalized_markers(owner, document, preview, source_transform))
    owner.cancel_measurement(redraw=False)
    owner._show_document(document.key)
    options=owner.plot_options[document.key]
    if options['mass_normalization_titles'] is None:
        options['mass_normalization_titles']={key:options[key] for key in ('title','window_name','export_title')}
    for curve in curves:
        curve.mass_normalization_mg=masses[curve.uid]
        curve.save_overlay_view()
    replace_document_markers(owner, document.key, markers)
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
    replace_document_markers(owner, document.key)
    document.plot_signature=None
    owner.statusBar().showMessage('叠图曲线已改变，请重新确认每条 m 后应用统一化',7000)
    return True


def restore(owner,document):
    members(owner,document)
    replace_document_markers(owner, document.key)
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
