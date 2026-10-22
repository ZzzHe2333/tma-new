"""Acquisition-time areas, baseline semantics and native linear-peak workflows."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import json
import numpy as np
import pytest
from scipy.integrate import trapezoid
from matplotlib.backend_bases import MouseEvent
from matplotlib.text import Text
from PySide6.QtWidgets import QDialog
from test_feature_ui import ui,source
from tma_app.workspace import Curve,save_session,load_session
from tma_app.peak_onset import defaults as peak_defaults
from tma_app.peak_integration import defaults,values,profile,validate


def data(tmp_path,name='linear.001',sign=1,variable=False,descending=False):
    time=np.linspace(0,10,101);x=100+(time**2 if variable else 10*time)
    if descending:x=300-x
    y=2*x+3+sign*np.maximum(0,20-4*np.abs(time-5))
    return replace(source(tmp_path/name),values=np.column_stack((time,x,y)))


def entry(manual=False,domain='temperature'):
    peak=peak_defaults();peak['onset']['manual']=manual
    return dict(kind='peak_linear',domain=domain,peak_onset=peak,integration=defaults())


@pytest.mark.parametrize('sign',[1,-1])
@pytest.mark.parametrize('variable',[False,True])
@pytest.mark.parametrize('descending',[False,True])
def test_time_integral_does_not_become_temperature_area(tmp_path,sign,variable,descending):
    curve=Curve(data(tmp_path,sign=sign,variable=variable,descending=descending));raw=curve.dataset.values.copy()
    v=values(curve,entry(),[0,100]);assert v['integral']==pytest.approx(sign*100)
    assert v['height']==pytest.approx(sign*20) and v['area_unit']=='µm·min'
    assert v['baseline_domain']=='temperature' and v['integration_domain']=='recorded_time'
    np.testing.assert_array_equal(curve.dataset.values,raw)


def test_fractional_time_endpoints_and_units_are_paired(tmp_path):
    curve=Curve(data(tmp_path,variable=True),unit_options={'dimension':'mm','offset':'none','time':'sec','temperature':'°F'},x_shift=2,offset=7)
    e=entry();v=values(curve,e,[10.25,90.75]);parts=profile(curve,e,[10.25,90.75])
    assert v['integral']==pytest.approx(trapezoid(parts[9],parts[7])) and v['area_unit']=='mm·sec'
    other=Curve(curve.dataset,unit_options={'dimension':'µm','offset':'none','time':'min','temperature':'K'})
    assert v['integral']==pytest.approx(values(other,e,[10.25,90.75])['integral']*.06)
    assert v['time_start']==pytest.approx(61.5) and v['time_stop']==pytest.approx(544.5)


def test_manual_onset_uses_its_own_two_points_and_baseline_limits(tmp_path):
    curve=Curve(data(tmp_path));v=values(curve,entry(True),[0,100,30,40])
    assert v['onset_x']==pytest.approx(100) and v['onset_y']==pytest.approx(203)
    assert v['start_x']==100 and v['stop_x']==200 and v['points']==101
    assert v['integral']==pytest.approx(100)
    # Baseline and tangent handle identities need not be globally sorted.
    assert values(curve,entry(True),[100,0,40,30])['integral']==pytest.approx(100)
    with pytest.raises(ValueError,match='基线界限'):values(curve,entry(True),[20,80,0,40])


@pytest.mark.parametrize('case',['reverse_time','gap','no_time','unknown_unit','other_signal','zero_duration'])
def test_rejects_invalid_time_gaps_and_unsupported_instrument_signals(tmp_path,case):
    curve=Curve(data(tmp_path))
    if case=='zero_duration':curve.dataset.values[:,0]=0
    elif case=='reverse_time':curve.dataset.values[50,0]=-1
    elif case=='gap':curve.data_indices=list(range(30))+list(range(40,101))
    elif case=='no_time':curve.dataset.signals[0]=replace(curve.dataset.signals[0],name='Unknown')
    elif case=='unknown_unit':curve.dataset.signals[0]=replace(curve.dataset.signals[0],unit='ticks')
    else:curve.y_index=1
    with pytest.raises(ValueError):values(curve,entry(),[0,len(curve.active_rows)-1])


def test_repeated_time_is_a_zero_width_trapezoid_without_merging_samples(tmp_path):
    curve=Curve(data(tmp_path));curve.dataset.values[50,0]=curve.dataset.values[49,0]
    before=curve.dataset.values.copy();v=values(curve,entry(),[0,100]);x,y=curve.xy();t=curve.x_values('time');r=y-(2*x+3)
    assert v['integral']==pytest.approx(np.sum((r[1:]+r[:-1])*np.diff(t)/2)) and v['points']==101
    np.testing.assert_array_equal(curve.dataset.values,before)


def test_native_menu_manual_four_points_confirm_focus_labels_and_session(ui,tmp_path):
    ui.finish_import([data(tmp_path,name=f'curve-{i}.001') for i in range(3)],[])
    curve=ui.curves[1];doc=ui._show_document(str(curve.dataset.path));ui.files.setCurrentItem(ui.files.topLevelItem(1))
    options=ui.show_analysis_options();options.controls['ManualOnsetBox'].setChecked(True);options.accept()
    ui.classic_actions['Linear1'].trigger();e=ui._pending_measurement;assert len(e['interactive']['indices'])==4
    manual=ui.edit_measurement_limits();assert len(manual.fields)==4 and all(f.isReadOnly() for f in manual.y_fields)
    for field,value in zip(manual.fields,[100,200,130,140]):field.setText(str(value))
    manual.accept();assert manual.result()==QDialog.DialogCode.Accepted,manual.error.text()
    assert e['values']['integral']==pytest.approx(100)
    ui.create_measurement_menu().actions()[-1].trigger();assert e['interactive']['active_point']==3
    ui.create_plot_context_menu().actions()[0].trigger()
    assert ui.results==[e] and ui.active_document() is doc and ui.selected().uid==curve.uid
    artist=ui._measurement_artists[-1];assert '面积 100 µm·min' in artist.annotation.get_text() and '始点 100' in artist.onset_label.get_text()
    assert [t.get_visible() for t in artist.temps]==[True,True,False,False,True]
    ui.canvas.draw();box=Text.get_window_extent(artist.onset_label,ui.canvas.get_renderer());cx,cy=(box.x0+box.x1)/2,(box.y0+box.y1)/2
    old_values=deepcopy(e['values'])
    for kind,x,y in (('button_press_event',cx,cy),('motion_notify_event',cx+28,cy+19),('button_release_event',cx+28,cy+19)):
        ui.canvas.callbacks.process(kind,MouseEvent(kind,ui.canvas,x,y,button=1))
    assert 'onset' in e['annotation']['label_offsets'] and e['values']==old_values
    saved=deepcopy(e);ui.edit_measurement(e);ui.activate_measurement_point(3);ui.measurement_key(SimpleNamespace(key='ctrl+right'));ui.cancel_measurement();assert e==saved
    path=tmp_path/'integration.tmas';save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options);assert load_session(path)[2]==[saved]
    csv=tmp_path/'integration.csv';ui.write_results(csv);assert 'integration' in csv.read_text(encoding='utf-8-sig').splitlines()[0]


def test_auto_peak_limits_and_area_preference_are_page_scoped(ui,tmp_path):
    ui.finish_import([data(tmp_path)],[]);options=ui.show_analysis_options();options.tabs.setCurrentIndex(1)
    assert options.controls['AreaBox'].isEnabled() and not options.controls['NormalizedBox'].isEnabled()
    options.controls['AreaBox'].setChecked(False);options.save();options.reject()
    assert not ui.integration_options()['area']
    ui.classic_actions['Linear1'].trigger();e=ui._pending_measurement;auto=ui.show_auto_limits();auto.auto_set();auto.accept()
    assert auto.result()==QDialog.DialogCode.Accepted,auto.error.text()
    ui.confirm_measurement();assert '面积' not in ui._measurement_artists[-1].annotation.get_text() and e['values']['integral']==pytest.approx(100)
    options=ui.show_analysis_options();options.tabs.setCurrentIndex(1);options.defaults();assert options.controls['AreaBox'].isChecked();options.accept()
    assert ui.integration_options()['area']


def test_invalid_manual_tangent_cannot_confirm_and_options_are_strict(ui,tmp_path):
    ds=data(tmp_path);ds.values[:,2]=2*ds.values[:,1]+3
    ui.finish_import([ds],[]);options=ui.show_analysis_options();options.controls['ManualOnsetBox'].setChecked(True);options.accept()
    e=ui.start_peak_integration();e['interactive']['indices']=[0,100,0,20];ui.redraw();ui.confirm_measurement()
    assert e is ui._pending_measurement and 'fit_error' in e['values'] and not ui.results
    with pytest.raises(ValueError):validate(dict(area=1))
    with pytest.raises(ValueError):validate(dict(area=True,normalized=True))


def test_time_axis_uses_actual_time_without_x_shift_or_reset_origin_area_change(tmp_path):
    curve=Curve(data(tmp_path),x_shift=7);e=entry(domain='time')
    assert values(curve,e,[0,100])['integral']==pytest.approx(100)
    curve.dataset.values[:,0]+=2;curve.reset_time=True
    assert values(curve,e,[0,100])['integral']==pytest.approx(100)


def test_unavailable_onset_channels_do_not_reuse_peak_temperature(tmp_path):
    from tma_app.peak_integration import label_text
    curve=Curve(data(tmp_path));e=entry();e['peak_onset']['onset']['labels'].update(x=False,temperature=True,time=True)
    e['values']=values(curve,e,[0,100]);e['values']['peak_channels']=dict(time_at_point=5,time_unit='min',temperature_at_point=150,temperature_unit='°C')
    # An extrapolated onset can have no acquired matching channels.
    e['values'].update(onset_x=80.,onset_position=None,onset_channels={})
    text=label_text(e,curve);assert 'T = 80 °C' in text and text.count('150')==1 and 't = 5' not in text


def test_coincident_overlay_temperature_drag_selects_topmost_visible_label(ui,tmp_path):
    ui.finish_import([data(tmp_path,name=f'same-{i}.001') for i in range(3)],[])
    for i,curve in enumerate(ui.curves):
        ui._show_document(str(curve.dataset.path));ui.files.setCurrentItem(ui.files.topLevelItem(i));ui.start_peak_integration();ui.confirm_measurement()
    ui.show_overlay();ui.canvas.draw();artist=ui._measurement_artists[-1];before=deepcopy(ui.results)
    box=Text.get_window_extent(artist.temps[0],ui.canvas.get_renderer());cx,cy=(box.x0+box.x1)/2,(box.y0+box.y1)/2
    for kind,x,y in (('button_press_event',cx,cy),('motion_notify_event',cx+29,cy+17),('button_release_event',cx+29,cy+17)):
        ui.canvas.callbacks.process(kind,MouseEvent(kind,ui.canvas,x,y,button=1))
    assert ui.results[:2]==before[:2] and 't1' in ui.results[-1]['annotation']['label_offsets']
    assert ui.results[-1]['values']==before[-1]['values']
