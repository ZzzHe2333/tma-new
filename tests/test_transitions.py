"""Known three-line intersections, acquired branches and native workflows."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest
from matplotlib.backend_bases import MouseEvent
from matplotlib.text import Text
from PySide6.QtWidgets import QDialog,QPushButton
from test_feature_ui import ui,source
from tma_app.workspace import Curve,save_session,load_session
from tma_app.transitions import defaults,values,validate


def dataset(tmp_path,name='step.001',descending=False):
    x=np.arange(101,dtype=float)
    y=np.where(x<=30,x,np.where(x<=50,5*x-120,x+80))
    if descending:x=x[::-1].copy();y=y[::-1].copy()
    return replace(source(tmp_path/name),values=np.column_stack((np.arange(101),x,y)))


def entry(manual=False,midpoint='inflection'):
    config=defaults();config.update(manual=manual,midpoint=midpoint)
    return dict(kind='step_transition',domain='temperature',transition=config)


@pytest.mark.parametrize('manual,positions',[(True,[0,20,34,46,70,100]),(False,[0,100])])
@pytest.mark.parametrize('midpoint',['inflection','half_height','half_width','half_tangents','none'])
def test_three_known_lines_and_all_supported_midpoints(tmp_path,manual,positions,midpoint):
    c=Curve(dataset(tmp_path));result=values(c,entry(manual,midpoint),positions)
    assert result['onset_x']==pytest.approx(30) and result['end_x']==pytest.approx(50)
    assert result['change']==pytest.approx(100)
    assert [f['slope'] for f in result['fits']]==pytest.approx([1,5,1])
    if midpoint=='inflection':assert 30<result['midpoint_x']<50  # A linear ramp has no unique steepest point.
    else:assert result['midpoint_x']==(None if midpoint=='none' else pytest.approx(40))


def test_manual_interpolated_endpoints_and_descending_acquisition(tmp_path):
    c=Curve(dataset(tmp_path,descending=True))
    result=values(c,entry(True,'half_tangents'),[.25,20.5,54.25,64.5,80.5,99.5])
    assert result['onset_x']==pytest.approx(50) and result['end_x']==pytest.approx(30)
    assert result['change']==pytest.approx(-100) and result['midpoint_x']==pytest.approx(40)


def test_change_between_tangents_at_midpoint_is_not_end_to_end_change(tmp_path):
    c=Curve(dataset(tmp_path));e=entry(True,'half_width');e['transition'].update(start='midpoint',stop='midpoint')
    result=values(c,e,[0,20,34,46,70,100]);assert result['change']==pytest.approx(80)
    e['transition'].update(start='start',stop='stop')
    assert values(c,e,[0,20,34,46,70,100])['change']==pytest.approx(180)


def test_units_and_physical_offsets_preserve_intersections(tmp_path):
    c=Curve(dataset(tmp_path),unit_options={'dimension':'mm','offset':'none','temperature':'°F'},x_shift=2,offset=20)
    result=values(c,entry(True,'half_width'),[0,20,34,46,70,100])
    assert result['onset_x']==pytest.approx(32+1.8*32) and result['end_x']==pytest.approx(32+1.8*52)
    assert result['change']==pytest.approx(.1) and result['midpoint_x']==pytest.approx(32+1.8*42)


def test_small_y_scale_does_not_turn_distinct_tangents_into_parallel_lines(tmp_path):
    c=Curve(dataset(tmp_path),scale=1e-16)
    result=values(c,entry(True,'half_width'),[0,20,34,46,70,100])
    assert result['onset_x']==pytest.approx(30) and result['end_x']==pytest.approx(50)
    assert result['change']==pytest.approx(1e-14,rel=1e-10,abs=0)


def test_parallel_reversed_gap_and_wrong_midpoint_are_rejected(tmp_path):
    c=Curve(dataset(tmp_path));c.dataset.values[:,2]=2*c.dataset.values[:,1]
    with pytest.raises(ValueError,match='平行'):values(c,entry(True),[0,20,34,46,70,100])
    c=Curve(dataset(tmp_path));c.data_indices=list(range(35))+list(range(40,101))
    with pytest.raises(ValueError,match='片段'):values(c,entry(False),[0,len(c.active_rows)-1])
    c=Curve(dataset(tmp_path));c.dataset.values[:,1]=100
    with pytest.raises(ValueError,match='不同X'):values(c,entry(False),[0,100])
    invalid=defaults();invalid['midpoint']='fictive'
    with pytest.raises(ValueError):validate(invalid)


def import_step(ui,tmp_path,count=1):
    ui.finish_import([dataset(tmp_path,f'step-{i}.00{i+1}') for i in range(count)],[])


def test_native_step_page_save_default_cancel_and_page_isolation(ui,tmp_path):
    import_step(ui,tmp_path);before=deepcopy(ui.plot_options);ui.dirty=False
    dialog=ui.show_analysis_options();assert dialog.tabs.isTabEnabled(0) and dialog.tabs.isTabEnabled(1) and not dialog.tabs.isTabEnabled(2)
    dialog.tabs.setCurrentIndex(0);dialog.controls['ManualStepBox'].setChecked(True)
    dialog.midpoint.setCurrentIndex(dialog.midpoint.findData('half_height'))
    dialog.controls['SignalChangeYLimitsBox'].setChecked(True);dialog.width_field.setText('0')
    dialog.save();dialog.reject()
    assert ui.plot_options==before and not ui.dirty
    from tma_app.preferences import load_defaults
    saved=load_defaults('analysis')['options'];assert saved['transition_options']['manual']
    assert saved['signal_change_options']['y_limits'] and 'alpha_smoothing_width' not in saved
    dialog=ui.show_analysis_options();dialog.tabs.setCurrentIndex(0);dialog.defaults()
    assert not dialog.controls['ManualStepBox'].isChecked() and dialog.width_field.text()=='10'
    dialog.controls['ManualStepBox'].setChecked(True);dialog.accept()
    assert ui.transition_options()['manual'] and ui.alpha_width()==10
    assert not dialog.controls['StepDeltaCpBox'].isEnabled()


@pytest.mark.parametrize('kind',['step_transition','glass_transition'])
def test_six_marker_precise_input_context_confirm_cancel_and_session(ui,tmp_path,kind):
    import_step(ui,tmp_path,3);curve=ui.selected();doc=ui.active_document()
    dialog=ui.show_analysis_options();dialog.controls['ManualStepBox'].setChecked(True);dialog.accept()
    config=deepcopy(ui.transition_options());e=ui.start_transition(kind)
    assert len(e['interactive']['indices'])==6 and ui.selected().uid==curve.uid
    manual=ui.edit_measurement_limits();assert len(manual.fields)==6 and all(f.isReadOnly() for f in manual.y_fields)
    for field,value in zip(manual.fields,[0,20,34,46,70,100]):field.setText(str(value))
    manual.accept();assert manual.result()==QDialog.DialogCode.Accepted,manual.error.text()
    assert e['values']['onset_x']==pytest.approx(30)
    assert len([a for a in ui.create_plot_context_menu().actions() if a.text().startswith('点 ')])==6
    ui.create_plot_context_menu().actions()[0].trigger()
    assert ui.results==[e] and ui._pending_measurement is None and ui.selected().uid==curve.uid and ui.active_document() is doc
    artist=next(a for a in ui._measurement_artists if a.entry is e)
    assert len(artist.tangent_lines)==3 and len(artist.temps)==6 and '始点' in artist.annotation.get_text()
    # Glass transition reports its result without selection-limit labels.
    old_values=deepcopy(e['values']);ui.canvas.draw()
    assert all(text.get_visible() == (kind != 'glass_transition') for text in artist.temps)
    target = artist.annotation if kind == 'glass_transition' else artist.temps[5]
    bounds=Text.get_window_extent(target,ui.canvas.get_renderer());cx,cy=(bounds.x0+bounds.x1)/2,(bounds.y0+bounds.y1)/2
    for event,x,y in (('button_press_event',cx,cy),('motion_notify_event',cx-24,cy-18),('button_release_event',cx-24,cy-18)):
        ui.canvas.callbacks.process(event,MouseEvent(event,ui.canvas,x,y,button=1))
    assert ('offset' in e['annotation'] if kind == 'glass_transition' else 't6' in e['annotation']['label_offsets']) and e['values']==old_values
    old=deepcopy(e);ui.edit_measurement(e);ui.create_measurement_menu().actions()[-1].trigger();assert ui._pending_measurement['interactive']['active_point']==5
    ui.measurement_key(SimpleNamespace(key='ctrl+left'));ui.cancel_measurement();assert e==old
    options=ui.show_analysis_options();options.controls['StepOnsetBox'].setChecked(False);options.accept();assert e['transition']==config
    path=tmp_path/'step.tmas';save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    restored=load_session(path);assert restored[2]==[old]
    ui.close_all_documents();ui.restore_session(path);assert ui.results==[old] and len(ui._measurement_artists[-1].markers)==6


def test_invalid_draft_keeps_cursors_and_cannot_be_confirmed(ui,tmp_path):
    ds=dataset(tmp_path);ds.values[:,2]=ds.values[:,1]
    ui.finish_import([ds],[]);e=ui.start_transition('step_transition')
    assert 'fit_error' in e['values'] and len(ui._measurement_artists[-1].markers)==2
    ui.confirm_measurement();assert not ui.results and ui._pending_measurement is e
    ui.cancel_measurement();assert ui._pending_measurement is None


def test_signal_change_label_options_do_not_change_height_or_maximum(ui,tmp_path):
    import_step(ui,tmp_path);dialog=ui.show_analysis_options();dialog.controls['SignalChangeYLimitsBox'].setChecked(True)
    dialog.controls['SignalChangeBox'].setChecked(False);dialog.controls['SignalChangeXLimitsBox'].setChecked(False);dialog.accept()
    e=ui.start_point_measurement('signal_change');ui.confirm_measurement();a=next(a for a in ui._measurement_artists if a.entry is e)
    assert 'Y1 =' in a.annotation.get_text() and 'H =' not in a.annotation.get_text() and all(not t.get_visible() for t in a.temps)
    e=ui.start_point_measurement('height_change');assert e['annotation']['change'] and not e['annotation'].get('y_limits',False);ui.cancel_measurement()
    e=ui.start_point_measurement('signal_max');ui.confirm_measurement();a=next(a for a in ui._measurement_artists if a.entry is e)
    assert '信号最大' not in a.annotation.get_text() and '°C' in a.annotation.get_text()


def test_warmup_temperature_jitter_is_not_sorted_or_removed(tmp_path):
    ds=dataset(tmp_path);ds.values[:5,1]=[0,.02,.01,.03,.025];ds.values[:5,2]=ds.values[:5,1]
    raw=ds.values.copy();result=values(Curve(ds),entry(False),[0,100])
    assert result['onset_x']==pytest.approx(30,abs=.001) and result['end_x']==pytest.approx(50,abs=.001)
    np.testing.assert_array_equal(ds.values,raw)


def test_six_marker_confirm_cannot_jump_to_other_document(ui,tmp_path):
    import_step(ui,tmp_path,3);doc=ui.active_document()
    options=ui.show_analysis_options();options.controls['ManualStepBox'].setChecked(True);options.accept()
    e=ui.start_transition('step_transition');manual=ui.edit_measurement_limits()
    for field,value in zip(manual.fields,[0,20,34,46,70,100]):field.setText(str(value))
    manual.accept();assert manual.result()==QDialog.DialogCode.Accepted
    other=next(d for key,d in ui.documents.items() if key!=doc.key)
    ui._show_document(other.key);ui.measurement_key(SimpleNamespace(key='enter'))
    assert ui._pending_measurement is e and not ui.results
    ui._show_document(doc.key);ui.measurement_key(SimpleNamespace(key='enter'))
    assert ui.results==[e] and ui.active_document() is doc
