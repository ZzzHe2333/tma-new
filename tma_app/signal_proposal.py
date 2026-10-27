"""Pure signal proposal calculation, usable without a GUI in the worker."""
from dataclasses import replace
import uuid
from .workspace import Curve
from .cancellation import check_cancelled

SUPPORTED = {"normal", "d_time", "d_temperature", "d2_time", "d2_temperature"}


def build_proposal(curves, dataset, template, *, cancelled=None):
    """Return an independent full proposal. No live curve is modified on error."""
    check_cancelled(cancelled)
    domain = template["x"]["domain"]
    if domain not in ("temperature", "time", "signal"): raise ValueError("X信号无效")
    draft = [replace(c, operations=list(c.operations), history=list(c.history)) for c in curves]
    computed = [c for c in draft if c.dataset.document_key == dataset.document_key and c.derived is not None and c.normal_enabled]
    source = [c for c in draft if c.dataset.document_key == dataset.document_key and c.derived is None]
    originals = [c for c in source if c.normal_enabled]
    for curve in source: curve.activate_appearance("normal"); curve.normal_enabled = False
    def index(label):
        matches = [i for i,s in enumerate(dataset.signals) if s.label == label]
        if len(matches) != 1: raise ValueError(f"信号不存在或名称不唯一：{label}")
        return matches[0]
    xindex = index(template["x"]["signal"]) if template["x"]["signal"] is not None else None
    xkind, xwidth = template["x"]["type"], template["x"]["width"]
    if xkind not in SUPPORTED: raise ValueError("所选X类型的数学定义尚未确认")
    if domain == "signal" and xindex is None: raise ValueError("请选择X信号")
    for curve in source+[c for c in draft if c.dataset.document_key==dataset.document_key and c.derived is not None]: curve.x_signal_index, curve.x_signal_type, curve.x_smooth_width = xindex, xkind, xwidth
    reference = source[0] if source else Curve(dataset)
    x = reference.x_values(domain,cancelled=cancelled)
    for axis, item in enumerate(template["y"]):
        check_cancelled(cancelled)
        reserved=[c for c in computed if c.axis==axis]
        if reserved:
            if item['signal'] not in (None,reserved[0].signal_label):raise ValueError(f'Y{axis+1}已有派生积分，请先删除积分曲线再选择其它信号')
            continue
        if item["signal"] is None: continue
        yi, kind, width = index(item["signal"]), item["type"], item["width"]
        candidate = next((c for c in source if c.axis == axis and c.y_index == yi and c.y_type == kind and c.smooth_width == width), None)
        if candidate is None:
            if kind not in SUPPORTED: raise ValueError("当前处理只能保留在原曲线上；请选择已实现的信号类型")
            base = next((c for c in originals if c.axis == axis), reference)
            candidate = replace(base, uid=uuid.uuid4().hex, y_index=yi, axis=axis, scale=1., offset=0.,
                                normal_enabled=True, overlay_enabled=False, y_type=kind, smooth_width=width,
                                operations=[], history=[], normal_appearance=None, overlay_appearance=None,
                                smooth_source=None,smooth_base_ops=[],smooth_reuse=False,smooth_domain=None,smooth_x_config=None,
                                working_rows=None,smooth_source_rows=None)
            from .data_limits import smoothed_state
            for key,value in smoothed_state(candidate,domain,width,cancelled=cancelled).items():setattr(candidate,key,value)
            draft.append(candidate); source.append(candidate)
        elif candidate not in originals and candidate.y_type!="custom":
            from .data_limits import smoothed_state
            for key,value in smoothed_state(candidate,domain,width,cancelled=cancelled).items():setattr(candidate,key,value)
        candidate.normal_enabled = True
        candidate.xy(domain,cancelled=cancelled)
    return draft

