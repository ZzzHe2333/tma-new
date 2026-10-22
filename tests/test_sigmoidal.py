"""Native horizontal sigmoid areas, nonlinear onsets and frozen profiles."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest
from matplotlib.backend_bases import MouseEvent
from matplotlib.text import Text
from PySide6.QtWidgets import QDialog
from test_feature_ui import ui,source
from tma_app.sigmoidal import horizontal,onset_crossing,ConvergenceError,validate,validate_snapshot
from tma_app.peak_integration import values,defaults as integration_defaults
from tma_app.peak_onset import defaults as peak_defaults
from tma_app.workspace import Curve,save_session,load_session,validate_plot_options,default_plot_options


def data(tmp_path,name='sigmoid.001',descending=False):
    t=np.linspace(0,1,101);f=3*t*t-2*t*t*t;x=100+100*t;y=2+3*f+np.maximum(0,20-100*abs(t-.6))
    return replace(source(tmp_path/name),values=np.column_stack((t,300-x if descending else x,y)))


def entry(manual=False):
    peak=peak_defaults();peak['onset']['manual']=manual
    return dict(kind='peak_sigmoid',domain='temperature',peak_onset=peak,integration=integration_defaults(),sigmoid=dict(draw_iterations=True))


def test_first_iteration_has_independent_closed_form_area_and_baseline():
    t=np.linspace(0,1,1001);f=3*t*t-2*t**3;r=60*t*(1-t);y=2+3*f+r;initial=2+3*t;before=[v.copy() for v in (t,y,initial)]
    result=horizontal(t,y,initial);expected_fraction=f+.3*(t**3-.5*t**4-.5*t*t)
    assert len(result['iterations'])==1 and result['area']==pytest.approx(10.015,abs=2e-5)
    np.testing.assert_allclose(result['baseline'],2+3*expected_fraction,atol=2e-6,rtol=0)
    negative=horizontal(t,-y,-initial);np.testing.assert_allclose(negative['baseline'],-result['baseline']);np.testing.assert_allclose(negative['cumulative'],-result['cumulative'])
    for old,current in zip(before,(t,y,initial)):np.testing.assert_array_equal(old,current)


def test_nonconvergence_is_a_real_ten_iteration_abort():
    t=np.linspace(0,1,101);y=2+100*t+np.maximum(0,1-abs((t-.2)/.1))
    with pytest.raises(ConvergenceError,match='10次') as caught:horizontal(t,y,2+100*t)
    assert len(caught.value.iterations)==10 and caught.value.iterations[-1]['relative_change']>.01


def test_cancelled_area_and_constant_horizontals_have_explicit_distinct_rules():
    t=np.linspace(0,1,101);y=np.sin(2*np.pi*t)
    with pytest.raises(ConvergenceError,match='接近零'):horizontal(t,y,np.linspace(y[0],y[-1],len(t)))
    y[-1]=0;constant=horizontal(t,y,np.zeros_like(t));assert not constant['iterations']
    np.testing.assert_array_equal(constant['baseline'],np.zeros_like(t))
    flat=horizontal(t,np.ones_like(t),np.ones_like(t));assert flat['area']==0


@pytest.mark.parametrize('descending',[False,True])
def test_manual_onset_intersects_actual_sampled_baseline_in_acquisition_order(tmp_path,descending):
    curve=Curve(data(tmp_path,descending=descending));v=values(curve,entry(True),[0,100,45,50]);p=v['sigmoid_profile'];position=v['onset_position'];fit=v['onset_fit']
    assert 0<position<45 and v['onset_x']<v['max_x'] if not descending else v['onset_x']>v['max_x']
    expected=float(np.interp(position,p['positions'],p['baseline']))
    assert v['onset_y']==pytest.approx(expected) and fit['slope']*v['onset_x']+fit['intercept']==pytest.approx(expected)
    assert v['iteration_count']<=10 and p['iterations'][-1]['relative_change']<=.01
    validate_snapshot(p,len(curve.active_rows))


def test_nonlinear_crossing_keeps_branch_and_does_not_sort_x():
    p=np.linspace(0,1,101);baseline=p*p;fit=dict(slope=.5,intercept=0,position_start=.6)
    ox,oy,position=onset_crossing(p,baseline,p,fit,1)
    assert (ox,oy,position)==pytest.approx((.5,.25,.5))
    fit.update(slope=-.5,intercept=.5);result=onset_crossing(1-p,baseline,p,fit,1)
    assert result==pytest.approx((.5,.25,.5))


def test_fractional_endpoints_and_physical_unit_conversion_preserve_shape(tmp_path):
    source_data=data(tmp_path);a=Curve(source_data);b=Curve(source_data,unit_options=dict(dimension='mm',offset='none',time='sec',temperature='°F'),x_shift=2,offset=7)
    av=values(a,entry(),[.25,99.5]);bv=values(b,entry(),[.25,99.5])
    assert bv['integral']==pytest.approx(av['integral']*.06) and bv['area_unit']=='mm·sec'
    np.testing.assert_allclose(bv['sigmoid_profile']['baseline'],(np.asarray(av['sigmoid_profile']['baseline'])+7)*.001,atol=1e-12)
    assert bv['iteration_count']==av['iteration_count'];validate_snapshot(bv['sigmoid_profile'],101)


def test_snapshot_validation_rejects_corrupt_vectors_and_unconverged_profiles(tmp_path):
    v=values(Curve(data(tmp_path)),entry(),[0,100]);original=v['sigmoid_profile']
    changes=[('baseline',10,1.),('cumulative',10,1.),('positions',10,-10.)]
    for key,i,new in changes:
        bad=deepcopy(original);bad[key][i]=new
        with pytest.raises(ValueError):validate_snapshot(bad,101)
    bad=deepcopy(original);bad['iterations'][-1]['relative_change']=.5
    with pytest.raises(ValueError):validate_snapshot(bad,101)
    bad=deepcopy(original);bad['converged']=False
    with pytest.raises(ValueError):validate_snapshot(bad,101)
    with pytest.raises(ValueError):validate(dict(draw_iterations=1))
    with pytest.raises(ValueError):validate_plot_options(dict(default_plot_options(),sigmoid_iterations=1))


def test_native_sigmoid_menu_iterations_labels_context_and_session(ui,tmp_path):
    ui.finish_import([data(tmp_path,name=f's-{i}.001') for i in range(3)],[]);curve=ui.curves[1];doc=ui._show_document(str(curve.dataset.path));ui.files.setCurrentItem(ui.files.topLevelItem(1))
    options=ui.show_analysis_options();options.controls['SigItterationsBox'].setChecked(True);options.accept()
    ui.classic_actions['SigHorizontal1'].trigger();e=ui._pending_measurement;assert e['kind']=='peak_sigmoid' and 'fit_error' not in e['values']
    limits=ui.edit_measurement_limits();assert all(f.isReadOnly() for f in limits.y_fields);limits.reject()
    auto=ui.show_auto_limits();auto.auto_set();auto.accept();assert auto.result()==QDialog.DialogCode.Accepted,auto.error.text()
    ui.create_measurement_menu().actions()[0].trigger();assert ui.active_document() is doc and ui.selected().uid==curve.uid
    artist=ui._measurement_artists[-1];p=e['values']['sigmoid_profile']
    assert np.asarray(artist.integration_lines[0].get_ydata())==pytest.approx(p['baseline'])
    assert sum(bool(len(line.get_xdata())) for line in artist.iteration_lines)==max(1,e['values']['iteration_count'])
    ui.canvas.draw();box=Text.get_window_extent(artist.onset_label,ui.canvas.get_renderer());cx,cy=(box.x0+box.x1)/2,(box.y0+box.y1)/2;old=deepcopy(e['values'])
    for kind,x,y in (('button_press_event',cx,cy),('motion_notify_event',cx+22,cy+17),('button_release_event',cx+22,cy+17)):
        ui.canvas.callbacks.process(kind,MouseEvent(kind,ui.canvas,x,y,button=1))
    assert 'onset' in e['annotation']['label_offsets'] and e['values']==old
    saved=deepcopy(e);ui.edit_measurement(e);ui.activate_measurement_point(0);ui.measurement_key(SimpleNamespace(key='ctrl+right'));ui.cancel_measurement();assert e==saved
    path=tmp_path/'sigmoid.tmas';save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options);assert load_session(path)[2]==[saved]
    ui.close_all_documents();ui.restore_session(path);ui._show_document(doc.key);assert ui.results==[saved]


def test_confirmed_profile_is_frozen_while_editing_recalculates(ui,tmp_path,monkeypatch):
    ui.finish_import([data(tmp_path)],[]);e=ui.start_peak_integration('peak_sigmoid');ui.confirm_measurement();old=deepcopy(e)
    with monkeypatch.context() as local:
        local.setattr('tma_app.sigmoidal.horizontal',lambda *a:(_ for _ in ()).throw(AssertionError('Confirmed profile must not be recomputed')))
        ui.redraw();assert e==old
    ui.edit_measurement(e);ui.activate_measurement_point(0);ui.measurement_key(SimpleNamespace(key='ctrl+right'))
    assert ui._pending_measurement['values']['sigmoid_profile']!=old['values']['sigmoid_profile'];ui.cancel_measurement();assert e==old


def test_failed_iteration_cannot_confirm_or_add_a_result(ui,tmp_path):
    ds=data(tmp_path);t=ds.values[:,0];ds.values[:,2]=2+100*t+np.maximum(0,1-abs((t-.2)/.1))
    ui.finish_import([ds],[]);options=ui.show_analysis_options();options.controls['SigItterationsBox'].setChecked(True);options.accept()
    e=ui.start_peak_integration('peak_sigmoid');assert '10次' in e['values']['fit_error']
    artist=ui._measurement_artists[-1];assert len(artist.integration_lines[0].get_xdata())==101 and e['values']['sigmoid_failure']['converged'] is False
    assert sum(bool(len(line.get_xdata())) for line in artist.iteration_lines)==10
    ui.confirm_measurement();assert ui._pending_measurement is e and not ui.results;ui.cancel_measurement()


def test_other_page_defaults_save_do_not_change_peak_or_current_results(ui,tmp_path):
    from tma_app.preferences import load_defaults
    ui.finish_import([data(tmp_path)],[]);before=deepcopy(ui.plot_options);ui.dirty=False
    options=ui.show_analysis_options();options.controls['SigItterationsBox'].setChecked(True);options.save();options.reject()
    assert load_defaults('analysis')['options']['sigmoid_iterations'] and ui.plot_options==before and not ui.dirty
    assert ui.sigmoid_iterations()
    options=ui.show_analysis_options();options.defaults();assert not options.controls['SigItterationsBox'].isChecked();options.reject();assert ui.sigmoid_iterations()


def test_archived_processed_profile_survives_a_new_processing_window(ui,tmp_path):
    ui.finish_import([data(tmp_path)],[]);curve=ui.selected();curve.working=curve.dataset.values[:,2]*2;curve.operations=['explicit QA scale2']
    e=ui.start_peak_integration('peak_sigmoid');ui.confirm_measurement();old=deepcopy(e)
    curve.working=None;curve.operations=[];curve.data_indices=list(range(20));ui.redraw();assert not ui._measurement_artists and e==old
    path=tmp_path/'archive.tmas';save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    restored=load_session(path);assert restored[2]==[old] and restored[0][0].data_indices==list(range(20))


def test_loaded_snapshot_must_match_baseline_control_positions(ui,tmp_path):
    ui.finish_import([data(tmp_path)],[]);e=ui.start_peak_integration('peak_sigmoid');ui.confirm_measurement()
    e['interactive']['positions']=[1.,100.];e['interactive']['indices']=[1,100]
    path=tmp_path/'mismatch.tmas';save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    with pytest.raises(ValueError,match='控制点'):load_session(path)


def test_existing_linear_integral_also_stays_frozen_during_redraw(ui,tmp_path,monkeypatch):
    ui.finish_import([data(tmp_path)],[]);e=ui.start_peak_integration();ui.confirm_measurement();old=deepcopy(e)
    with monkeypatch.context() as local:
        local.setattr('tma_app.peak_integration.values',lambda *a:(_ for _ in ()).throw(AssertionError('Confirmed linear integral must stay frozen')))
        ui.redraw();assert e==old
    ui.edit_measurement(e);ui.activate_measurement_point(0);ui.measurement_key(SimpleNamespace(key='ctrl+right'));assert ui._pending_measurement['values']!=old['values']


def test_nonconvergent_automatic_bounds_leave_existing_markers_and_values_unchanged(ui,tmp_path):
    ui.finish_import([data(tmp_path)],[]);e=ui.start_peak_integration('peak_sigmoid');before=deepcopy(e);plots=deepcopy(ui.plot_options)
    dialog=ui.show_auto_limits();peak=e['values']['max_x']
    for group,field,target in zip(dialog.groups,dialog.offsets,(100.,130.)):
        next(b for b in group.buttons() if b.property('mode')=='offset').setChecked(True);field.setText(format(target-peak,'.17g'))
    dialog.accept();assert dialog.result()!=QDialog.DialogCode.Accepted and '10次' in dialog.error.text()
    assert e==before and ui.plot_options==plots;dialog.reject()
