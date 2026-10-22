"""Time/temperature display quantities over source acquisition units.

Absolute temperatures use affine conversion; widths and derivative denominators
use only the scale. Unrecognized source units remain source quantities.
"""
from __future__ import annotations

TIME_UNITS={'sec':1.,'min':60.,'hr':3600.,'day':86400.,'ms':.001,'s':1.,'h':3600.,'d':86400.}
TEMP_UNITS={'°C':(1.,0.),'°F':(5./9.,-32.*5./9.),'K':(1.,-273.15)}
TEMP_ALIASES={'C':'°C','deg C':'°C','degC':'°C','F':'°F','deg F':'°F'}


def category(dataset,index):
    signal=dataset.signals[index];unit=signal.unit.strip()
    if (index==dataset.time_index or 'time' in signal.name.casefold()) and unit in TIME_UNITS:return 'time'
    if (index==dataset.temperature_index or 'temperature' in signal.name.casefold() or '温度' in signal.name) and TEMP_ALIASES.get(unit,unit) in TEMP_UNITS:return 'temperature'
    return None


def conversion(source,target,kind):
    if target=='source':return 1.,0.,source
    if kind=='time':return TIME_UNITS[source]/TIME_UNITS[target],0.,target
    source=TEMP_ALIASES.get(source,source);target=TEMP_ALIASES.get(target,target)
    a,b=TEMP_UNITS[source];c,d=TEMP_UNITS[target]
    return a/c,(b-d)/c,target


def spec(dataset,index,options):
    kind=category(dataset,index)
    if kind is None:return None
    signal=dataset.signals[index];target=(options or {}).get(kind,'source')
    factor,offset,unit=conversion(signal.unit.strip(),target,kind)
    return dict(factor=factor,offset=offset,unit=unit,name=signal.name,reference_mm=None,reference_25=None,status='source' if target=='source' else kind+' display conversion')


def displayed_delta_per_c(unit):
    return 1.8 if TEMP_ALIASES.get(unit,unit)=='°F' else 1.


def source_bound(value,spec,samples):
    """Invert an absolute UI bound; retain exact acquired endpoints at FP ties."""
    import numpy as np
    source=(value-spec['offset'])/spec['factor']
    if not np.isfinite(source):raise ValueError('数据界限换算超出有限范围')
    samples=np.asarray(samples,dtype=float)
    if samples.size:
        nearest=float(samples[np.argmin(np.abs(samples-source))])
        tolerance=8*np.finfo(float).eps*max(1.,abs(source),abs(nearest))
        if abs(source-nearest)<=tolerance:source=nearest
    return source
