"""Baseline-relative peaks, two-tangent onsets and native point workflows."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtWidgets import QDialog
from test_feature_ui import ui,source
from tma_app.workspace import Curve,save_session,load_session
from tma_app.peak_onset import defaults,values,validate


def data(tmp_path,kind='peak',sign=1,descending=False,name='native.001'):
    x=np.arange(101,dtype=float)
    if kind=='peak':y=3*x+sign*np.maximum(0,100-10*np.abs(x-40))
    else:y=np.where(x<=30,x,5*x-120)
    if descending:x=x[::-1].copy();y=y[::-1].copy()
    return replace(source(tmp_path/name),values=np.column_stack((np.arange(101),x,y)))


def entry(kind='peak_max',manual=False):
    config=defaults();config['onset']['manual']=manual
    return dict(kind=kind,domain='temperature',peak_onset=config)


@pytest.mark.parametrize('sign',[1,-1])
@pytest.mark.parametrize('descending',[True,False])
def test_peak_uses_linear_baseline_rather_than_largest_y(tmp_path,sign,descending):
    c=Curve(data(tmp_path,sign=sign,descending=descending));raw=c.dataset.values.copy()
    result=values(c,entry(),[.25,99.5])
    assert result['max_x']==pytest.approx(40) and result['height']==pytest.approx(sign*100)
    assert result['baseline_y']==pytest.approx(120) and result['width_half_height']==pytest.approx(10)
    assert result['max_y']==pytest.approx(120+sign*100)
    np.testing.assert_array_equal(c.dataset.values,raw)


@pytest.mark.parametrize('descending',[True,False])
def test_four_manual_onset_handles_have_known_intersection(tmp_path,descending):
    c=Curve(data(tmp_path,'onset',descending=descending));positions=[0,20,80,100] if descending else [0,20,40,80]
    result=values(c,entry('onset_point',True),positions)
    assert result['onset_x']==pytest.approx(30) and result['onset_y']==pytest.approx(30)


def test_auto_unchecked_tangent_window_fallback_has_correct_onset(tmp_path):
    c=Curve(data(tmp_path,'onset'));e=entry('onset_point');e['peak_onset']['onset']['inflection']=False
    result=values(c,e,[0,100]);assert result['onset_x']==pytest.approx(30)
    assert not result['inflection_found'] and result['fits'][0]['points']==13


def test_checked_inflection_tangent_passes_through_curve_crossing(tmp_path):
    ds=data(tmp_path);x=np.linspace(-5,5,201);ds=replace(ds,values=np.column_stack((np.arange(201),x,np.tanh(x))))
    result=values(Curve(ds),entry('onset_point'),[0,200])
    assert result['inflection_found'] and result['inflection_x']==pytest.approx(0,abs=.01)
    final=result['fits'][1]
    assert final['slope']*result['inflection_x']+final['intercept']==pytest.approx(np.tanh(result['inflection_x']),abs=.001)


def test_peak_and_onset_respect_display_units_and_physical_offsets(tmp_path):
    config={'dimension':'mm','offset':'none','temperature':'°F'}
    c=Curve(data(tmp_path),unit_options=config,x_shift=2,offset=10,scale=1e-3)
    result=values(c,entry(),[0,100])
    assert result['max_x']==pytest.approx(107.6) and result['height']==pytest.approx(.0001)
    assert result['width_half_height']==pytest.approx(18)
    c=Curve(data(tmp_path,'onset'),unit_options=config,x_shift=2)
    result=values(c,entry('onset_point',True),[0,20,40,80]);assert result['onset_x']==pytest.approx(89.6)


def test_no_gap_bridge_parallel_onset_or_invalid_config(tmp_path):
    c=Curve(data(tmp_path));c.data_indices=list(range(30))+list(range(40,101))
    with pytest.raises(ValueError,match='片段'):values(c,entry(),[0,len(c.active_rows)-1])
    c=Curve(data(tmp_path,'onset'));c.dataset.values[:,2]=2*c.dataset.values[:,1]
    with pytest.raises(ValueError,match='平行'):values(c,entry('onset_point',True),[0,20,40,80])
    cfg=defaults();cfg['peak']['maximum']='bad'
    with pytest.raises(ValueError):validate(cfg)


def test_native_peak_page_scoped_defaults_cancel_and_manual_inflection(ui,tmp_path):
    ui.finish_import([data(tmp_path)],[]);original=deepcopy(ui.plot_options);ui.dirty=False
    dialog=ui.show_analysis_options();dialog.tabs.setCurrentIndex(1)
    assert dialog.tabs.isTabEnabled(1) and dialog.controls['AreaBox'].isEnabled() and not dialog.controls['NormalizedBox'].isEnabled()
    dialog.controls['ManualOnsetBox'].setChecked(True);assert not dialog.controls['InflectionBox'].isEnabled()
    dialog.controls['WidthBox'].setChecked(True);dialog.width_field.setText('0');dialog.save();dialog.reject()
    from tma_app.preferences import load_defaults
    saved=load_defaults('analysis')['options'];assert saved['peak_onset_options']['onset']['manual'] and saved['peak_onset_options']['peak']['width']
    assert ui.plot_options==original and not ui.dirty and 'alpha_smoothing_width' not in saved
    dialog=ui.show_analysis_options();dialog.tabs.setCurrentIndex(1);dialog.defaults()
    assert not dialog.controls['ManualOnsetBox'].isChecked() and dialog.controls['InflectionBox'].isChecked();dialog.accept()


def test_native_peak_two_markers_baseline_labels_and_portable_session(ui,tmp_path):
    ui.finish_import([data(tmp_path,name=f'peak-{i}.001') for i in range(3)],[]);curve=ui.selected();doc=ui.active_document()
    ui.classic_actions['PeakMax1'].trigger();e=ui._pending_measurement
    assert e['kind']=='peak_max' and e['values']['max_x']==40 and len(e['interactive']['indices'])==2
    limits=ui.edit_measurement_limits();assert all(f.isReadOnly() for f in limits.y_fields);limits.reject()
    ui.create_measurement_menu().actions()[0].trigger()
    assert ui.results==[e] and ui.selected().uid==curve.uid and ui.active_document() is doc
    artist=next(a for a in ui._measurement_artists if a.entry is e)
    assert '高度' in artist.annotation.get_text() and 'T = 40' in artist.annotation.get_text()
    assert list(artist.analysis_lines[0].get_ydata())==[0,300]
    path=tmp_path/'peak.tmas';save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options);assert load_session(path)[2]==ui.results


def test_onset_manual_four_points_right_menu_and_cross_document(ui,tmp_path):
    ui.finish_import([data(tmp_path,'onset',name=f'onset-{i}.001') for i in range(3)],[]);doc=ui.active_document()
    options=ui.show_analysis_options();options.controls['ManualOnsetBox'].setChecked(True);options.controls['TimeBox'].setChecked(True);options.accept()
    ui.classic_actions['OnsetPoint1'].trigger();e=ui._pending_measurement;assert len(e['interactive']['indices'])==4
    manual=ui.edit_measurement_limits();assert len(manual.fields)==4 and all(f.isReadOnly() for f in manual.y_fields)
    for field,value in zip(manual.fields,[0,20,40,80]):field.setText(str(value))
    manual.accept();assert manual.result()==QDialog.DialogCode.Accepted,manual.error.text()
    other=next(d for key,d in ui.documents.items() if key!=doc.key);ui._show_document(other.key);ui.confirm_measurement()
    assert ui._pending_measurement is e and not ui.results
    ui._show_document(doc.key);ui.create_measurement_menu().actions()[0].trigger();assert ui.results==[e]
    a=ui._measurement_artists[-1];assert '始点 30' in a.annotation.get_text() and 't = 30' in a.annotation.get_text()
    assert a.annotation.get_text().count('30 °C')==1  # X-axis and specific temperature are deduplicated.
    saved=deepcopy(e);ui.edit_measurement(e);ui.create_measurement_menu().actions()[-1].trigger();ui.measurement_key(SimpleNamespace(key='ctrl+left'));ui.cancel_measurement();assert e==saved
    path=tmp_path/'onset.tmas';save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options);assert load_session(path)[2]==[saved]


def test_invalid_onset_keeps_draft_and_no_false_confirm(ui,tmp_path):
    ds=data(tmp_path,'onset');ds.values[:,2]=2*ds.values[:,1]
    ui.finish_import([ds],[]);e=ui.start_peak_onset('onset_point')
    assert 'fit_error' in e['values'];ui.confirm_measurement();assert ui._pending_measurement is e and not ui.results


def test_specific_time_and_selected_time_signal_are_not_duplicated(ui,tmp_path):
    ui.finish_import([data(tmp_path,'onset')],[]);ui.selected().x_signal_index=0
    options=ui.show_analysis_options();options.controls['ManualOnsetBox'].setChecked(True)
    options.controls['TimeBox'].setChecked(True);options.controls['XSignalBox'].setChecked(True);options.accept()
    e=ui.start_peak_onset('onset_point');manual=ui.edit_measurement_limits()
    for field,value in zip(manual.fields,[0,20,40,80]):field.setText(str(value))
    manual.accept();ui.confirm_measurement()
    text=ui._measurement_artists[-1].annotation.get_text()
    assert text.count('min')==1 and 't = 30 min' in text
