"""Real auto-limit dialogs, atomic bounds, per-signal templates and reuse."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtWidgets import QDialog,QPushButton
from test_feature_ui import ui
from test_peak_onset import data
from test_transitions import dataset as step_data
from tma_app.auto_limits import validate_rule,default_rule,positions,anchor
from tma_app.workspace import save_session,load_session
from tma_app.workspace import Curve
from tma_app.peak_onset import defaults as peak_defaults


def offset_mode(dialog,index):
    next(b for b in dialog.groups[index].buttons() if b.property('mode')=='offset').click()


@pytest.mark.parametrize('kind,shape',[('peak_max','peak'),('onset_point','onset'),('step_transition','step'),('signal_change','peak')])
def test_resource_shell_autoset_cancel_and_actual_offset_apply(ui,tmp_path,kind,shape):
    ds=step_data(tmp_path) if shape=='step' else data(tmp_path,shape)
    if kind=='signal_change':ds.values[:,2]=50*(1+np.tanh((ds.values[:,1]-40)/3))
    ui.finish_import([ds],[])
    e=ui.start_transition(kind) if shape=='step' else ui.start_peak_onset(kind) if kind!='signal_change' else ui.start_point_measurement(kind)
    state=deepcopy(e['interactive']);original=deepcopy(ui.plot_options)
    dialog=ui.show_auto_limits();assert (dialog.width(),dialog.height())==((314 if kind=='signal_change' else 338),197)
    if kind=='signal_change':dialog.defaults();assert dialog.findChild(QPushButton,'Default').geometry().getRect()==(234,77,69,25)
    else:dialog.auto_set();assert dialog.findChild(QPushButton,'AutoSet').geometry().getRect()==(246,77,81,25)
    assert not dialog.error.text()
    dialog.reject();assert e['interactive']==state and ui.plot_options==original
    dialog=ui.show_auto_limits()
    if kind=='signal_change':dialog.defaults()
    else:dialog.auto_set()
    dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted,dialog.error.text()
    if kind!='signal_change':assert e['interactive']['positions']==pytest.approx(state.get('positions',state['indices']))
    else:assert e['interactive']['positions']==pytest.approx([0,100])
    assert len(ui.auto_limit_rules())==1 and e['auto_limits']['family'] in ('peak','onset','step','signal')
    ui.cancel_measurement()


def test_saved_peak_offsets_follow_shifted_peak_in_next_file_without_auto_commit(ui,tmp_path):
    ui.finish_import([data(tmp_path)],[]);first=ui.start_peak_onset('peak_max')
    dialog=ui.show_auto_limits();dialog.auto_set();dialog.save();dialog.reject()
    assert not ui.plot_options.get('__settings__',{}).get('auto_limits_rules')
    ui.cancel_measurement();ds=data(tmp_path,name='shifted.002')
    # Same baseline, peak shifts from40 to50 while using a longer range.
    x=np.arange(121,dtype=float);ds=replace(ds,values=np.column_stack((x,x,3*x+np.maximum(0,100-10*np.abs(x-50)))))
    ui.finish_import([ds],[]);e=ui.start_peak_onset('peak_max');before=deepcopy(e['interactive'])
    dialog=ui.show_auto_limits();assert dialog.groups[0].checkedButton().property('mode')=='offset'
    assert e['interactive']==before
    dialog.accept();assert dialog.result()==QDialog.DialogCode.Accepted,dialog.error.text()
    curve=ui.selected();xp,_=curve.xy()
    assert np.interp(e['interactive']['positions'],np.arange(len(xp)),xp)==pytest.approx([10,110])
    assert e['values']['max_x']==50


def test_bad_offset_bounds_are_atomic_and_cursor_mode_ignores_unused_empty_text(ui,tmp_path):
    ui.finish_import([data(tmp_path)],[]);e=ui.start_peak_onset('peak_max');state=deepcopy(e['interactive']);plots=deepcopy(ui.plot_options)
    dialog=ui.show_auto_limits();offset_mode(dialog,0);dialog.offsets[0].setText('-10000');dialog.accept()
    assert dialog.result()!=QDialog.DialogCode.Accepted and dialog.error.text()
    assert e['interactive']==state and ui.plot_options==plots
    next(b for b in dialog.groups[0].buttons() if b.property('mode')=='cursor').click();dialog.offsets[0].setText('')
    dialog.accept();assert dialog.result()==QDialog.DialogCode.Accepted,dialog.error.text()


def test_mixed_cursor_and_offset_rule_is_saved_with_session(ui,tmp_path):
    ui.finish_import([data(tmp_path)],[]);e=ui.start_peak_onset('peak_max');dialog=ui.show_auto_limits()
    offset_mode(dialog,1);dialog.offsets[1].setText('30');dialog.accept();assert dialog.result()==QDialog.DialogCode.Accepted
    assert e['interactive']['positions']==pytest.approx([0,70])
    ui.confirm_measurement();path=tmp_path/'auto.tmas';save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    restored=load_session(path,include_plot_options=True)
    assert restored[3]['__settings__']['auto_limits_rules']==ui.auto_limit_rules()
    assert restored[2][0]['auto_limits']==e['auto_limits']


def test_wrong_units_or_changed_document_cannot_move_markers(ui,tmp_path):
    ui.finish_import([data(tmp_path,name=f'case-{i}.001') for i in range(2)],[]);e=ui.start_peak_onset('peak_max');curve=ui.selected()
    rule=default_rule(curve,e);rule['unit']='K'
    with pytest.raises(ValueError,match='不匹配'):positions(curve,e,rule)
    dialog=ui.show_auto_limits();original=deepcopy(e['interactive']);other=next(d for d in ui.documents.values() if d is not ui.active_document());ui._show_document(other.key)
    dialog.accept();assert dialog.result()!=QDialog.DialogCode.Accepted and e['interactive']==original;dialog.reject()


def test_manual_multi_tangents_have_explicit_reset_and_no_fake_auto_dialog(ui,tmp_path):
    ui.finish_import([step_data(tmp_path)],[]);options=ui.show_analysis_options();options.controls['ManualStepBox'].setChecked(True);options.accept()
    e=ui.start_transition('step_transition');menu=ui.create_measurement_menu()
    auto=next(a for a in menu.actions() if a.objectName()=='AutoLimits1');assert not auto.isEnabled()
    reset=next(a for a in menu.actions() if a.objectName()=='ResetLimits1');assert reset.text()=='恢复初始界限'
    old=e['interactive']['indices'].copy();ui.activate_measurement_point(5);ui.measurement_key(SimpleNamespace(key='ctrl+left'));reset.trigger()
    assert e['interactive']['indices']==old


def test_template_validation_rejects_data_bound_or_nonfinite_values(ui,tmp_path):
    ui.finish_import([data(tmp_path)],[]);e=ui.start_peak_onset('peak_max');rule=default_rule(ui.selected(),e)
    for changed in (dict(rule,source='private.001'),dict(rule,endpoints=[dict(mode='offset',offset=float('nan'))]*2)):
        with pytest.raises(ValueError):validate_rule(changed)


def test_derivative_fractions_share_adjacent_step_boundary_and_keep_missing_neighbor_ends(tmp_path):
    ds=data(tmp_path);x=np.arange(201,dtype=float)
    y=25*(1+np.tanh((x-60)/2))+15*(1+np.tanh((x-140)/2))
    ds=replace(ds,values=np.column_stack((x,x,y)));curve=Curve(ds)
    first=dict(kind='signal_change',domain='temperature',interactive=dict(indices=[0,100]))
    second=dict(kind='signal_change',domain='temperature',interactive=dict(indices=[100,200]))
    a=positions(curve,first,default_rule(curve,first));b=positions(curve,second,default_rule(curve,second))
    assert a[0]==0 and b[1]==200 and a[1]==pytest.approx(b[0],abs=1e-9)
    assert a[1]==pytest.approx(100,abs=.001)
    raw=ds.values.copy();curve.unit_options={'dimension':'mm','offset':'none','temperature':'°F'}
    a_f=positions(curve,first,default_rule(Curve(ds),first))
    np.testing.assert_allclose(a_f,a);np.testing.assert_array_equal(ds.values,raw)


def test_derivative_fraction_does_not_use_neighbor_across_excluded_gap(tmp_path):
    ds=data(tmp_path);x=np.arange(201,dtype=float);y=25*(1+np.tanh((x-60)/2))+15*(1+np.tanh((x-140)/2))
    curve=Curve(replace(ds,values=np.column_stack((x,x,y))),data_indices=list(range(91))+list(range(110,201)))
    e=dict(kind='signal_change',domain='temperature',interactive=dict(indices=[0,90]))
    assert positions(curve,e,default_rule(curve,e))==[0,90]


def test_offset_roundtrip_preserves_acquired_endpoint_at_float_tie(tmp_path):
    ds=data(tmp_path);ds.values[:,1]=np.linspace(59.731178283691406,294.739999,101)
    curve=Curve(ds,unit_options={'dimension':'µm','offset':'none','temperature':'K'})
    e=dict(kind='peak_max',domain='temperature',peak_onset=peak_defaults(),interactive=dict(indices=[0,100]))
    x,_=curve.xy();center=anchor(curve,e);rule=default_rule(curve,e)
    rule['endpoints']=[dict(mode='offset',offset=float(np.nextafter(x[0],-np.inf)-center)),dict(mode='offset',offset=float(np.nextafter(x[-1],np.inf)-center))]
    assert positions(curve,e,rule)==[0.,100.]
