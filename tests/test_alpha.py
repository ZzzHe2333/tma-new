"""Independent Alpha arithmetic, acquired branches and native interactive workflows."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtWidgets import QDialog,QPushButton
from test_feature_ui import ui,imported,source
from tma_app.alpha import alpha_values,sample_length,validate_config
from tma_app.workspace import Curve,save_session,load_session,default_plot_options,validate_plot_options
from tma_app.preferences import load_defaults


def config(length=2.,width=4.):return dict(reference_length_mm=length,reference_source='explicit test size (mm)',smoothing_width_c=width)


def curve_data(tmp_path,x,y,rows=None):
    ds=source(tmp_path/'ramp.001');ds=replace(ds,values=np.column_stack((np.arange(len(x)),x,y)))
    return Curve(ds,data_indices=rows)


@pytest.mark.parametrize('kind,positions,expected',[
    ('alpha_secant',[1.25,4.5],3500.),('alpha_fit',[1.25,4.5],3500.),('alpha_at_x',[3.25],3500.),
])
def test_exact_linear_expansion_normalization_without_temperature_sorting(tmp_path,kind,positions,expected):
    x=np.array([110,108,106,104,102,100.]);y=7*x+30
    c=curve_data(tmp_path,x,y);entry={'kind':kind,'domain':'temperature','alpha':config()}
    result=alpha_values(c,entry,positions)
    assert result['alpha']==pytest.approx(expected) and result['slope']==pytest.approx(7)
    assert result['reference_length_mm']==2 and result['alpha_unit']=='µm/m/°C'
    assert result['fit_x_start']>result['fit_x_end']


def test_secant_and_fit_are_different_on_curved_data_and_fit_endpoints_can_leave_curve(tmp_path):
    x=np.array([100.,101.,102.,103.]);y=np.array([0.,1.,4.,15.]);c=curve_data(tmp_path,x,y)
    secant=alpha_values(c,{'kind':'alpha_secant','domain':'temperature','alpha':config()},[0,3])
    fit=alpha_values(c,{'kind':'alpha_fit','domain':'temperature','alpha':config()},[0,3])
    assert secant['slope']==5 and fit['slope']==pytest.approx(4.8)
    assert fit['fit_y_start']!=y[0] and fit['fit_y_end']!=y[-1]
    assert fit['r2']==pytest.approx(1-np.sum((y-np.polyval(np.polyfit(x,y,1),x))**2)/np.sum((y-y.mean())**2))


def test_at_x_local_window_truncates_at_gap_and_uses_local_repeat_temperature_branch(tmp_path):
    x=np.array([100.,101.,102.,103.,102.,101.,100.]);y=np.array([0.,2.,4.,20.,30.,40.,50.]);c=curve_data(tmp_path,x,y)
    entry={'kind':'alpha_at_x','domain':'temperature','alpha':config(width=1.)}
    result=alpha_values(c,entry,[4.5]);assert result['slope']==-10 and result['fit_points']==2
    c.data_indices=[0,1,4,5,6];entry['alpha']=config(width=10.)
    result=alpha_values(c,entry,[3]);assert result['slope']==-10 and result['fit_sample_start']==5 and result['fit_sample_stop']==7
    for kind in ('alpha_secant','alpha_fit'):
        with pytest.raises(ValueError,match='采集片段'):alpha_values(c,dict(entry,kind=kind),[0,4])


@pytest.mark.parametrize('kind,positions',[('alpha_secant',[0,2]),('alpha_fit',[0,2]),('alpha_at_x',[1])])
def test_degenerate_temperature_rejected(tmp_path,kind,positions):
    c=curve_data(tmp_path,np.array([100.,100.,100.]),np.array([0.,1.,2.]))
    with pytest.raises(ValueError):alpha_values(c,{'kind':kind,'domain':'temperature','alpha':config()},positions)


@pytest.mark.parametrize('change',[{'reference_length_mm':0},{'reference_length_mm':True},{'smoothing_width_c':float('nan')},{'reference_source':0}])
def test_alpha_configuration_rejects_invalid_inputs(change):
    with pytest.raises(ValueError):validate_config(dict(config(),**change))


def test_sample_size_source_is_explicit_and_ambiguous_or_zero_headers_require_input(tmp_path):
    c=Curve(source(tmp_path/'size.001'))
    for entries in ([],['0.0000 mm'],['2 mm','3 mm'],['2 g']):
        c.dataset.metadata['Size']=entries;assert sample_length(c)==(None,None)
    c.dataset.metadata['Size']=['2.5 mm','2.500 mm'];assert sample_length(c)==(2.5,'source header Size (mm)')
    c.sample_size_mm=3.;assert sample_length(c)==(3.,'session override (mm)')


def test_native_size_prompt_cancel_invalid_and_confirm_retains_third_file(ui,tmp_path):
    imported(ui,tmp_path,3);ui.show_normal();curve=ui.selected();doc=ui.active_document();raw=curve.dataset.values.copy()
    ui.classic_actions['AlphaX1ToX21'].trigger();dialog=ui.dialogs['sample_size']
    assert dialog.objectName()=='SampleSizeForm' and (dialog.width(),dialog.height())==(282,115)
    assert dialog.findChild(QPushButton,'OK').geometry().getRect()==(12,82,81,25)
    dialog.field.setText('0');dialog.accept();assert dialog.error.text() and curve.sample_size_mm is None
    dialog.reject();assert ui._pending_measurement is None and not ui.results
    ui.classic_actions['AlphaX1ToX21'].trigger();dialog=ui.dialogs['sample_size'];dialog.field.setText('2');dialog.accept()
    entry=ui._pending_measurement;assert entry['kind']=='alpha_secant' and entry['alpha']['reference_length_mm']==2
    assert ui.active_document() is doc and ui.selected().uid==curve.uid
    manual=ui.edit_measurement_limits();assert manual.y_fields[0].isReadOnly()
    manual.fields[0].setText('101.25');manual.fields[1].setText('104.5');manual.accept()
    assert manual.result()==QDialog.DialogCode.Accepted
    expected=((3+1)/2-(-2+.25*11))/(104.5-101.25)/2*1000
    assert entry['values']['alpha']==pytest.approx(expected)
    ui.create_measurement_menu().actions()[0].trigger()
    assert ui._pending_measurement is None and ui.results==[entry] and ui.active_document() is doc
    np.testing.assert_array_equal(curve.dataset.values,raw)


@pytest.mark.parametrize('kind',['alpha_at_x','alpha_secant','alpha_fit'])
def test_fixed_alpha_labels_edit_cancel_and_portable_session(ui,tmp_path,kind):
    imported(ui,tmp_path,2);curve=ui.selected();curve.sample_size_mm=2.
    entry=ui.start_alpha(kind);ui.confirm_measurement();assert ui.results==[entry]
    assert 'α =' in ui._measurement_artists[-1].annotation.get_text()
    saved=deepcopy(entry);ui.edit_measurement(entry)
    ui.measurement_key(SimpleNamespace(key='ctrl+right'));ui.cancel_measurement();assert entry==saved
    session=tmp_path/'alpha.tmas';save_session(session,ui.curves,ui.domain,ui.results,ui.plot_options)
    loaded=load_session(session);assert loaded[0][-1].sample_size_mm==2 and loaded[2]==[saved]
    ui.close_all_documents();ui.restore_session(session);assert ui.results==[saved]


def test_alpha_manual_gap_error_is_atomic_and_cross_document_confirm_ignored(ui,tmp_path):
    imported(ui,tmp_path,3);ui.show_normal();curve=ui.selected();curve.sample_size_mm=2.
    curve.data_indices=[0,1,4,5,6];entry=ui.start_alpha('alpha_fit');state=deepcopy(entry['interactive'])
    dialog=ui.edit_measurement_limits();dialog.fields[0].setText('100');dialog.fields[1].setText('105');dialog.accept()
    assert dialog.result()!=QDialog.DialogCode.Accepted and dialog.error.text() and entry['interactive']==state
    dialog.reject();source_doc=ui.active_document();other=next(doc for key,doc in ui.documents.items() if key!=source_doc.key and not ui._is_overlay(key))
    ui.mdi.setActiveSubWindow(other);ui.document_activated(other);ui.confirm_measurement()
    assert ui._pending_measurement is entry and not ui.results
    ui.mdi.setActiveSubWindow(source_doc);ui.document_activated(source_doc);ui.confirm_measurement();assert ui.results==[entry]


def test_native_options_save_default_cancel_page_isolation_and_session_width(ui,tmp_path):
    imported(ui,tmp_path,1);before=deepcopy(ui.plot_options);ui.dirty=False
    ui.classic_actions['AnalysisOptions1'].trigger();dialog=ui.dialogs['analysis_options']
    assert dialog.objectName()=='AnalysisOptionsForm' and (dialog.width(),dialog.height())==(494,357)
    assert dialog.width_field.geometry().getRect()==(336,12,61,21)
    assert dialog.tabs.count()==5 and dialog.tabs.currentIndex()==4
    assert not dialog.controls['CorrectedSizeBox'].isEnabled()
    dialog.width_field.setText('2');dialog.save();dialog.reject()
    assert load_defaults('analysis')['options']['alpha_smoothing_width']==2 and not ui.dirty and ui.plot_options==before
    dialog=ui.show_analysis_options();assert dialog.width_field.text()=='2'
    dialog.defaults();assert dialog.width_field.text()=='10'
    dialog.width_field.setText('0');dialog.accept();assert dialog.error.text() and ui.plot_options==before
    dialog.width_field.setText('3');dialog.accept();assert ui.alpha_width()==3
    curve=ui.selected();curve.sample_size_mm=2.;entry=ui.start_alpha('alpha_at_x');ui.confirm_measurement()
    assert entry['alpha']['smoothing_width_c']==3
    dialog=ui.show_analysis_options();dialog.width_field.setText('4');dialog.accept();assert entry['alpha']['smoothing_width_c']==3
    session=tmp_path/'width.tmas';save_session(session,ui.curves,ui.domain,ui.results,ui.plot_options)
    ui.close_all_documents();ui.restore_session(session);assert ui.alpha_width()==4


def test_alpha_bad_recorded_config_and_bad_session_size_are_rejected(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.selected();curve.sample_size_mm=2.;entry=ui.start_alpha('alpha_fit');ui.confirm_measurement()
    entry['alpha']['reference_length_mm']=0;session=tmp_path/'invalid.tmas';save_session(session,ui.curves,ui.domain,ui.results,ui.plot_options)
    with pytest.raises(ValueError):load_session(session)
    curve.sample_size_mm=-1.
    with pytest.raises(ValueError):save_session(session,ui.curves,ui.domain,[],ui.plot_options)
    with pytest.raises(ValueError):validate_plot_options(dict(default_plot_options(),alpha_smoothing_width=True))


def test_recorded_alpha_survives_new_processing_window_and_other_size_input(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.selected();curve.sample_size_mm=2.
    curve.working=curve.dataset.values[:,2]*2;curve.operations=['explicit QA scale 2']
    entry=ui.start_alpha('alpha_fit');ui.confirm_measurement();saved=deepcopy(entry)
    curve.working=None;curve.operations=[];curve.data_indices=[0,1,2];curve.sample_size_mm=4.
    ui.redraw();assert not ui._measurement_artists and entry==saved
    session=tmp_path/'archived.tmas';save_session(session,ui.curves,ui.domain,ui.results,ui.plot_options)
    curves,domain,results,options=load_session(session,include_plot_options=True)
    assert results==[saved] and curves[0].sample_size_mm==4 and saved['alpha']['reference_length_mm']==2


def test_source_sample_size_is_used_without_prompt_and_duplicates_share_override(ui,tmp_path):
    imported(ui,tmp_path,2);ui.show_normal();curve=ui.selected();curve.dataset.metadata['Size']=['2.5 mm']
    entry=ui.start_alpha('alpha_fit');assert 'sample_size' not in ui.dialogs
    assert entry['alpha']['reference_length_mm']==2.5 and entry['alpha']['reference_source']=='source header Size (mm)'
    ui.cancel_measurement();curve.sample_size_mm=3.;ui.duplicate_curve()
    assert ui.selected().sample_size_mm==3
