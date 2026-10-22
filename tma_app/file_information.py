"""Editable in-memory file information, preserving source files and text-only analyses."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import replace
import re
import numpy as np

TEXT_LIMITS={'Sample':32,'Operator':25,'Method':4096,'Comment':64}


def validate_text_overrides(value):
    if not isinstance(value,dict) or set(value)-set(TEXT_LIMITS):raise ValueError('文件信息字段无效')
    result={}
    for key,text in value.items():
        if not isinstance(text,str) or len(text)>TEXT_LIMITS[key] or any(char in text for char in '\r\n\0'):
            raise ValueError(f'{key}最多{TEXT_LIMITS[key]}个字符，且不能含换行或空字符')
        result[key]=text
    return result


def nonnegative_size(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not np.isfinite(value) or value<0:
        raise ValueError('样品尺寸(mm)必须是不小于0的有限数值')
    return float(value)


def source_text(curve,key):
    values=[v for name,entries in curve.dataset.metadata.items() if name.casefold()==key.casefold() for v in entries]
    return '; '.join(str(v) for v in values)


def text_value(curve,key):return curve.file_info.get(key,source_text(curve,key))


def source_size(curve):
    entries=[v for name,items in curve.dataset.metadata.items() if name.casefold()=='size' for v in items];values=[]
    for entry in entries:
        match=re.fullmatch(r'\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*mm\s*',str(entry))
        if not match:return None
        value=float(match[1])
        if not np.isfinite(value) or value<0:return None
        values.append(value)
    return values[0] if values and len(set(values))==1 else None


def effective_size(curve):return source_size(curve) if curve.sample_size_mm is None else nonnegative_size(curve.sample_size_mm)


def snapshot(curve):
    return {'text':{key:text_value(curve,key) for key in TEXT_LIMITS},'sample_size_mm':effective_size(curve),
        'text_overrides':deepcopy(curve.file_info),'size_override_mm':curve.sample_size_mm}


def prepare_edit(curves,curve,text_changes,size_changed=False,size=None):
    """Validate and read before proposing any live change; only known TMA size is editable."""
    changes=validate_text_overrides(text_changes)
    peers=[c for c in curves if c.dataset.document_key==curve.dataset.document_key and c.dataset.sha256==curve.dataset.sha256]
    if not peers:raise ValueError('文件已关闭')
    if size_changed:size=nonnegative_size(size)
    new_info=dict(curve.file_info)
    for key,text in changes.items():
        if text==source_text(curve,key):new_info.pop(key,None)
        else:new_info[key]=text
    dataset=curve.dataset
    if size_changed:
        from .reader import read_dataset
        # The manufacturer explicitly rereads on numeric changes. Missing or changed
        # source files cannot silently substitute another set of acquisition values.
        try:fresh=read_dataset(dataset.path)
        except (OSError,ValueError) as exc:raise ValueError(f'无法重新读取源文件：{exc}') from exc
        if fresh.sha256!=dataset.sha256:raise ValueError('源文件内容已变化，请重新打开该文件后再编辑尺寸')
        dataset=replace(dataset,values=fresh.values.copy(),signals=list(fresh.signals))
    proposals={}
    for peer in peers:
        state={'file_info':dict(new_info)}
        if size_changed:
            state.update(dataset=dataset,sample_size_mm=size,working=None,operations=[],y_type='normal',smooth_width=0.,
                smooth_domain=None,smooth_reuse=False,smooth_base_ops=[],smooth_source=None,smooth_x_config=None,
                working_rows=None,smooth_source_rows=None,history=[],_x_cache=None)
        proposals[peer.uid]=state
    return proposals
