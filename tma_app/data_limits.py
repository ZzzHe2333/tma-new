"""Acquisition rows and physical-window smoothing; raw datasets stay immutable."""
from copy import deepcopy
from dataclasses import replace
import math
import numpy as np
from .signal_processing import local_fit
from .cancellation import check_cancelled


def segments(rows):
    rows=np.asarray(rows,dtype=int)
    breaks=np.flatnonzero(np.diff(rows)!=1)+1
    return [slice(int(a),int(b)) for a,b in zip(np.r_[0,breaks],np.r_[breaks,len(rows)]) if b>a]


def finite(value,label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError(label+"必须为有限数值")
    return float(value)


def cycle_index(dataset):
    return next((i for i,s in enumerate(dataset.signals) if s.name.casefold() in ("cycle","cycle number","cycle index")),None)


def cursor_spec_rows(spec,sample_count):
    """Portable acquired-row bounds; never reinterpret repeated X as a range."""
    if not isinstance(spec,dict) or set(spec)!={"kind","rows","reset_time"} or spec["kind"]!="cursor":raise ValueError("光标数据界限字段无效")
    rows=spec["rows"]
    if (not isinstance(rows,list) or len(rows)<2 or len(rows)>sample_count
            or any(type(row) is not int or not 0<=row<sample_count for row in rows)
            or any(a>=b for a,b in zip(rows,rows[1:]))):raise ValueError("光标界限内至少需要2个按采集顺序排列的数据点")
    if type(spec["reset_time"]) is not bool:raise ValueError("时间归零设置无效")
    return list(rows)


def cursor_spec(curve,positions):
    """Retain only acquired samples inside the two handles, including endpoints.

    Fractional handles describe boundaries, not new samples. Prior exclusions
    survive, and reversed handles refer to the same acquired interval.
    """
    if not isinstance(positions,(list,tuple)) or len(positions)!=2:raise ValueError("光标数据界限需要2个点")
    positions=[finite(value,"光标位置") for value in positions]
    rows=curve.active_rows
    if min(positions)<0 or max(positions)>len(rows)-1:raise ValueError("光标位置超出当前数据范围")
    first=math.ceil(min(positions)-1e-10);last=math.floor(max(positions)+1e-10)
    spec={"kind":"cursor","rows":rows[first:last+1].tolist(),"reset_time":bool(curve.reset_time)}
    cursor_spec_rows(spec,curve.sample_count)
    return spec


def select_rows(dataset,spec):
    if spec is None:return None
    if isinstance(spec,dict) and spec.get("kind")=="cursor":
        rows=cursor_spec_rows(spec,len(dataset.values))
        if spec["reset_time"] and dataset.time_index is None:raise ValueError("时间归零需要时间信号")
        return None if len(rows)==len(dataset.values) else rows
    if not isinstance(spec,dict) or set(spec)!={"kind","start","stop","delay","all_cycles","reset_time"}:raise ValueError("数据界限字段无效")
    kind=spec["kind"]
    if kind not in ("time","temperature","cycle"):raise ValueError("数据界限类型无效")
    start,stop,delay=[finite(spec[k],k) for k in ("start","stop","delay")]
    if delay<0 or type(spec["all_cycles"]) is not bool or type(spec["reset_time"]) is not bool:raise ValueError("数据界限设置无效")
    n=len(dataset.values);rows=np.arange(n)
    if kind=="time":
        index=dataset.time_index
        if index is None:raise ValueError("文件没有时间信号")
        if stop!=0 and start>stop:raise ValueError("开始时间不能大于结束时间")
        x=dataset.values[:,index];mask=((x>=start) if start!=0 else np.ones(n,dtype=bool))&((x<=stop) if stop!=0 else True)
    elif kind=="temperature":
        index=dataset.temperature_index
        if index is None:raise ValueError("文件没有温度信号")
        if start==stop==0:mask=np.ones(n,dtype=bool)
        else:
            if start==stop:raise ValueError("起止温度不能相同，0/0表示全范围")
            x=dataset.values[:,index];mask=(x>=min(start,stop))&(x<=max(start,stop))
            if delay:
                if dataset.time_index is None:raise ValueError("延迟搜索需要时间信号")
                mask&=dataset.values[:,dataset.time_index]>=delay
            if not spec["all_cycles"]:
                # First acquired traversal in the requested direction; stop
                # at the target or reversal without joining a later cycle.
                selected=rows[mask];chosen=[]
                for section in segments(selected):
                    candidate=selected[section]
                    direction=1 if stop>start else -1
                    for i in range(len(candidate)-1):
                        if direction*(x[candidate[i+1]]-x[candidate[i]])<=0:continue
                        end=i+1
                        while end+1<len(candidate) and x[candidate[end]]!=stop and direction*(x[candidate[end+1]]-x[candidate[end]])>=0:end+=1
                        first=i
                        while first>0 and x[candidate[first-1]]==x[candidate[i]]:first-=1
                        chosen=candidate[first:end+1];break
                    if not len(chosen) and len(candidate)>=2 and np.all(x[candidate]==x[candidate[0]]):chosen=candidate
                    if len(chosen):break
                mask=np.zeros(n,dtype=bool);mask[chosen]=True
    else:
        index=cycle_index(dataset)
        if index is None:raise ValueError("文件没有明确的循环编号信号")
        if not start.is_integer() or not stop.is_integer() or start>stop:raise ValueError("循环编号必须为递增整数")
        x=dataset.values[:,index]
        if not np.allclose(x,np.round(x),rtol=0,atol=1e-8):raise ValueError("循环信号不是整数编号")
        mask=(x>=start)&(x<=stop)
    selected=rows[mask]
    if len(selected)<2:raise ValueError("数据界限内至少需要2个采样点")
    if spec["reset_time"] and dataset.time_index is None:raise ValueError("时间归零需要时间信号")
    return None if len(selected)==n else selected.tolist()


def smoothed_state(curve,domain,width,*,capture_custom=False,use_saved_x=True,cancelled=None):
    """Compute a complete proposal before changing any live curve."""
    check_cancelled(cancelled)
    width=finite(width,"平滑宽度")
    if width<0:raise ValueError("平滑宽度不能为负数")
    if curve.derived is not None or any("integral" in op.casefold() for op in curve.operations):raise ValueError("积分曲线不能平滑")
    rows=curve.active_rows
    kind=curve.y_type
    variable=("time" if kind.endswith("time") else "temperature") if kind not in ("normal","custom") else domain
    if variable not in ("temperature","time","signal"):raise ValueError("平滑自变量无效")
    independent=curve
    config=None
    if variable=="signal":
        config=curve.smooth_x_config if use_saved_x and curve.smooth_x_config is not None else {"index":curve.x_signal_index,"type":curve.x_signal_type,"width":curve.x_smooth_width}
        independent=replace(curve,x_signal_index=config["index"],x_signal_type=config["type"],x_smooth_width=config["width"])
    x=independent.x_values(variable,canonical=True,cancelled=cancelled)
    fit_width=width/independent.x_unit_factor(variable)
    source=curve.base_y.astype(float)
    base_ops=[]
    custom_source=None
    source_rows=None
    if kind=="custom":
        source_rows=curve.working_rows if capture_custom or curve.smooth_source is None else curve.smooth_source_rows
        if source_rows is not None and not np.isin(rows,source_rows).all():raise ValueError("此自定义处理仅覆盖原区间；请先恢复原始曲线再扩大范围")
        custom_source=(curve.working if capture_custom or curve.smooth_source is None else curve.smooth_source)
        custom_source=source.copy() if custom_source is None else custom_source.copy()
        source=custom_source
        base_ops=list(curve.operations if capture_custom or curve.smooth_source is None else curve.smooth_base_ops)
    output=source.copy()
    order=2 if kind.startswith("d2_") else (1 if kind not in ("normal","custom") else 0)
    for section in segments(rows):
        ids=rows[section];output[ids]=local_fit(x[section],source[ids],fit_width,order,cancelled=cancelled)
    if kind not in ("normal","custom"):
        index=curve.dataset.time_index if variable=="time" else curve.dataset.temperature_index
        operations=[f"derivative:{curve.dataset.signals[index].label}"]*order+[f"ls_window:{width}"]
    else:operations=base_ops+([f"ls_smooth:{width}:{independent.x_label(variable)}"] if width else [])
    if not operations and kind=="normal":output=None
    return dict(working=output,operations=operations,smooth_width=width,smooth_domain=variable,
                smooth_source=custom_source,smooth_base_ops=base_ops,smooth_x_config=deepcopy(config),
                working_rows=deepcopy(curve.data_indices) if output is not None else None,smooth_source_rows=deepcopy(source_rows))


def limits_proposal(curves,dataset,spec,domain,*,curve_uid=None):
    target=next((c for c in curves if c.uid==curve_uid),None)
    derived_only=target is not None and target.derived is not None
    rows=select_rows(target.logical_dataset if derived_only else dataset,spec);draft=[]
    for curve in curves:
        if curve.dataset.document_key!=dataset.document_key or derived_only and curve.uid!=curve_uid:draft.append(curve);continue
        candidate=replace(curve,operations=list(curve.operations),history=list(curve.history))
        candidate.checkpoint()
        candidate.data_indices=deepcopy(rows);candidate.data_limit_spec=deepcopy(spec)
        candidate.reset_time=bool(spec and spec["reset_time"])
        if candidate.derived is not None:
            if not derived_only:
                context=np.asarray(candidate.derived['source_rows']);p=np.asarray(candidate.derived['positions'])
                allowed=np.arange(len(dataset.values)) if rows is None else np.asarray(rows)
                mask=np.isin(context[np.floor(p).astype(int)],allowed)&np.isin(context[np.ceil(p).astype(int)],allowed)
                selected=np.flatnonzero(mask).tolist()
                candidate.data_indices=None if len(selected)==candidate.sample_count else (selected if len(selected)>=2 else [])
                candidate.data_limit_spec=None
            candidate.xy(domain);draft.append(candidate);continue
        active=candidate.normal_enabled or candidate.overlay_enabled
        if active:candidate.x_values(domain)
        if active and (candidate.y_type!="custom" or candidate.smooth_source is not None):
            width=candidate.smooth_width if candidate.smooth_reuse else 0.
            variable=candidate.smooth_domain or domain
            for key,value in smoothed_state(candidate,variable,width).items():setattr(candidate,key,value)
        elif not active and not candidate.smooth_reuse:candidate.smooth_width=0.
        if active:candidate.xy(domain)
        draft.append(candidate)
    return draft


def smoothing_rule(curve):
    variable=curve.smooth_domain
    if variable is None:return None
    reference=curve
    if variable=="signal" and curve.smooth_x_config is not None:
        config=curve.smooth_x_config
        reference=replace(curve,x_signal_index=config["index"],x_signal_type=config["type"],x_smooth_width=config["width"])
    return {"axis":curve.axis,"signal":curve.signal_label,"kind":curve.y_type,"variable":variable,
            "x_label":reference.x_label(variable),"x_type":reference.x_signal_type if variable=="signal" else "normal",
            "x_unit":reference.x_unit(variable),"x_width":reference.x_smooth_width if variable=="signal" else 0.,"width":curve.smooth_width,"enabled":curve.smooth_reuse}


def rule_key(rule):return tuple(rule[k] for k in ("axis","signal","kind","variable","x_label","x_type","x_unit","x_width"))


def validate_rules(rules):
    from .signal_processing import KINDS
    if not isinstance(rules,list) or len(rules)>1000:raise ValueError("smoothing rules invalid")
    required={"axis","signal","kind","variable","x_label","x_type","x_unit","x_width","width","enabled"}
    for rule in rules:
        if not isinstance(rule,dict) or set(rule)!=required:raise ValueError("smoothing rule fields invalid")
        if type(rule["axis"]) is not int or not 0<=rule["axis"]<4 or type(rule["enabled"]) is not bool:raise ValueError("smoothing rule axis invalid")
        if rule["kind"] not in KINDS+("custom",) or rule["x_type"] not in KINDS or rule["variable"] not in ("time","temperature","signal"):raise ValueError("smoothing rule type invalid")
        for key in ("signal","x_label","x_unit"):
            if not isinstance(rule[key],str) or len(rule[key])>4096:raise ValueError("smoothing rule text invalid")
        if finite(rule["width"],"width")<0:raise ValueError("smoothing width must be nonnegative")
        if finite(rule["x_width"],"X width")<0:raise ValueError("smoothing X width must be nonnegative")
    return deepcopy(rules)


def reusable_smoothing(curve,rules,domain):
    if curve.y_type=="custom":return None
    for rule in reversed(validate_rules(rules)):
        if rule["axis"]!=curve.axis or rule["kind"]!=curve.y_type or rule["signal"].replace("μ","µ")!=curve.signal_label.replace("μ","µ"):continue
        variable=rule["variable"]
        if curve.y_type=="normal" and variable!=domain:continue
        try:label,unit=curve.x_label(variable),curve.x_unit(variable)
        except (ValueError,TypeError):continue
        if label!=rule["x_label"] or unit.replace("μ","µ")!=rule["x_unit"].replace("μ","µ"):continue
        if variable=="signal" and (curve.x_signal_type!=rule["x_type"] or curve.x_smooth_width!=rule["x_width"]):continue
        if not rule["enabled"]:return None
        values=smoothed_state(curve,variable,rule["width"],use_saved_x=False)
        return dict(values,smooth_reuse=True)
    return None
