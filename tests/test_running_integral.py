"""Computed peak-area quantities, portable provenance and the native two stages."""
from copy import deepcopy
from dataclasses import replace
from io import BytesIO
import json
import zipfile
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication,QDialog,QPushButton
from test_feature_ui import ui,source
from test_peak_integration import data,entry
from tma_app.workspace import Curve,save_session,load_session
from tma_app.measurement import point_values
from tma_app.peak_integration import values
from tma_app.running_integral import calculate,descriptor,create_curve,validate,validate_links


def parent(curve,positions=(0,100)):
    e=entry();e.update(file=curve.dataset.path.name,sha256=curve.dataset.sha256,curve_id=curve.uid,
        signal=curve.result_label,operations=list(curve.operations),transform=curve.result_transform('temperature'),
        lo=100,hi=200,axis=curve.axis+1,point_signal=None,annotation={},analysis_id='a'*32,
        interactive=dict(indices=[int(round(p)) for p in positions],positions=list(positions),initial_indices=[0,100],confirmed=True))
    e['values']=point_values(*curve.xy('temperature'),'peak_linear',e['interactive']['indices'],list(positions))
    e['values'].update(values(curve,e,positions))
    return e


@pytest.mark.parametrize('mode,inverted,expected',[
    ('integral',False,[0,.5,1]),('integral',True,[0,-.5,-1]),
    ('percent',False,[0,50,100]),('percent',True,[100,50,0])])
def test_exact_triangle(mode,inverted,expected):
    t=np.array([0.,1.,2.]);y=np.array([0.,1.,0.]);b=np.zeros(3);before=[a.copy() for a in (t,y,b)]
    np.testing.assert_array_equal(calculate(t,y,b,mode=mode,inverted=inverted)['values'],expected)
    for a,old in zip((t,y,b),before):np.testing.assert_array_equal(a,old)


def test_signed_percentage_duplicate_time_and_cancellation():
    np.testing.assert_allclose(calculate([0,0,1,3],[0,-2,-2,0],[0]*4,mode='percent')['values'],[0,0,50,100])
    for y in ([0,0,0],[1,-1,1]):
        with pytest.raises(ValueError,match='抵消'):calculate([0,1,2],y,[0]*3,mode='percent')
    with pytest.raises(ValueError,match='不能下降'):calculate([0,2,1],[0,1,0],[0]*3)


def derived_pair(tmp_path,**config):
    c=Curve(data(tmp_path,variable=True));e=parent(c,(10.25,90.75))
    d=descriptor(c,e,e['analysis_id'],**config)
    return c,e,create_curve(c,d)


def test_derived_rows_fractional_x_and_quantity_units(tmp_path):
    c,e,d=derived_pair(tmp_path);raw=c.dataset.values.copy();x,y=d.xy('temperature')
    assert d.sample_count==82 and len(c.dataset.values)==101 and d.dataset is c.dataset
    assert x[0]==pytest.approx(e['values']['start_x']) and x[-1]==pytest.approx(e['values']['stop_x'])
    assert y[0]==0 and y[-1]==pytest.approx(e['values']['integral']) and d.result_unit=='µm·min'
    changed=replace(d,unit_options={'dimension':'mm','offset':'none','time':'sec','temperature':'°F'})
    np.testing.assert_allclose(changed.xy()[0],x*1.8+32)
    np.testing.assert_allclose(changed.xy()[1],y*.06)
    assert changed.result_unit=='mm·sec'
    np.testing.assert_array_equal(c.dataset.values,raw)
    assert d.logical_dataset.signals[2].unit=='µm·min'


def test_percent_ignores_dimension_conversion_but_x_still_converts(tmp_path):
    c,e,d=derived_pair(tmp_path,mode='percent',inverted=True)
    changed=replace(d,unit_options={'dimension':'ppm','offset':'at25','time':'sec','temperature':'K'},sample_size_mm=2.)
    np.testing.assert_allclose(changed.xy()[1],d.xy()[1]);assert changed.result_unit=='%'
    assert d.xy()[1][0]==100 and d.xy()[1][-1]==pytest.approx(0)


def test_processed_x_uses_complete_source_context(tmp_path):
    c=Curve(data(tmp_path,variable=True),x_signal_index=2,x_signal_type='d_time',x_smooth_width=1.)
    e=parent(c,(10.25,90.75));d=create_curve(c,descriptor(c,e,e['analysis_id']))
    expected=np.interp(d.derived['positions'],np.arange(len(c.active_rows)),c.x_values('signal'))
    np.testing.assert_allclose(d.x_values('signal'),expected)
    changed=replace(d,unit_options={'dimension':'mm','offset':'none','time':'sec','temperature':'°C'},x_smooth_width=60.)
    np.testing.assert_allclose(changed.x_values('signal'),expected/60000)


def test_session_embeds_original_matrix_and_logical_working(tmp_path):
    c,e,d=derived_pair(tmp_path);d.working=d.base_y*2;d.operations=['normalize'];d.y_type='custom'
    path=tmp_path/'computed.tmas';save_session(path,[c,d],'temperature',[e])
    with zipfile.ZipFile(path) as z:
        np.testing.assert_array_equal(np.load(BytesIO(z.read('1-data.npy'))),c.dataset.values)
        assert np.load(BytesIO(z.read('1-working.npy'))).shape==(d.sample_count,)
    loaded,domain,results=load_session(path)
    assert loaded[1].derived==d.derived and results==[e]
    np.testing.assert_allclose(loaded[1].xy()[1],d.xy()[1])
    corrupt=deepcopy(d.derived);corrupt['base_values'][1]+=1
    with pytest.raises(ValueError,match='快照'):validate(corrupt,c.dataset)
    with pytest.raises(ValueError,match='缺少'):save_session(tmp_path/'orphan.tmas',[d],'temperature',[e])


def test_source_limits_project_without_reintegrating_and_undo(tmp_path):
    from tma_app.data_limits import limits_proposal
    c,e,d=derived_pair(tmp_path);before=d.base_y.copy()
    spec=dict(kind='cursor',rows=list(range(40,61)),reset_time=True)
    out=limits_proposal([c,d],c.dataset,spec,'temperature')
    assert len(out[0].active_rows)==21 and len(out[1].active_rows)==21
    np.testing.assert_allclose(out[1].xy()[1],before[out[1].active_rows]);out[1].undo()
    assert out[1].data_indices is None
    absent=limits_proposal([c,d],c.dataset,dict(kind='cursor',rows=[0,1],reset_time=False),'temperature')[1]
    assert absent.active_rows.tolist()==[] and len(absent.xy()[0])==0
    path=tmp_path/'empty.tmas';save_session(path,[c,absent],'temperature',[e]);assert load_session(path)[0][1].active_rows.tolist()==[]


def setup_ui(ui,tmp_path):
    ui.finish_import([data(tmp_path,name='first.001'),data(tmp_path,name='second.002')],[])
    c=ui.curves[1];ui._show_document(str(c.dataset.path));ui.refresh_curve(c.uid)
    e=ui.start_peak_integration();ui.confirm_measurement();assert e in ui.results
    return c,e


def test_native_selection_dialog_commit_and_export(ui,tmp_path):
    c,e=setup_ui(ui,tmp_path);raw=c.dataset.values.copy();selection=ui.start_running_integral()
    assert selection['purpose']=='running_integral'
    menu=ui.create_measurement_menu();assert [a.text() for a in menu.actions()][:4]==['确定','编辑…','自动界限','取消'];menu.deleteLater()
    dialog=ui.confirm_measurement();assert dialog.objectName()=='IntegralTypeForm' and dialog.size().width()==282 and not dialog.normalized.isEnabled()
    dialog.percent.setChecked(True);dialog.inverted.setChecked(True);dialog.accept()
    assert dialog.result()==QDialog.Accepted and ui._pending_measurement is None and ui.selected().uid==c.uid
    d=ui.curves[-1];assert d.axis==3 and d.result_unit=='%' and e['analysis_id']==d.derived['parent_id']
    assert len(ui.results)==1 and ui.active_document().key==str(c.dataset.path)
    assert 3 in ui.axes and any(c is d for c,_,_ in ui._plot_artists)
    path=tmp_path/'area.csv';ui.write_data(path,d)
    assert '面积百分比 (%)' in path.read_text(encoding='utf-8-sig').splitlines()[0]
    assert json.loads((tmp_path/'area.csv.meta.json').read_text(encoding='utf8'))['derived']==d.derived
    np.testing.assert_array_equal(c.dataset.values,raw)
    save_session(tmp_path/'ui.tmas',ui.curves,ui.domain,ui.results,ui.plot_options)
    assert load_session(tmp_path/'ui.tmas')[0][-1].derived==d.derived


@pytest.mark.parametrize('stage',[1,2])
def test_cancel_is_atomic_and_preserves_second_file(ui,tmp_path,stage):
    c,e=setup_ui(ui,tmp_path);original=list(ui.curves);snapshot=deepcopy(e)
    ui.start_running_integral()
    if stage==2:ui.confirm_measurement().reject()
    else:ui.cancel_measurement()
    assert ui.curves==original and e==snapshot and ui.selected().uid==c.uid and ui._pending_measurement is None


def test_occupied_y4_and_cross_document_commit_leave_draft(ui,tmp_path):
    c,e=setup_ui(ui,tmp_path);selection=ui.start_running_integral();dialog=ui.confirm_measurement()
    occupied=replace(c,uid='b'*32,axis=3);ui.curves.append(occupied)
    dialog.accept();assert 'Y4' in dialog.error.text() and len(ui.curves)==3 and 'analysis_id' not in e
    ui.curves.pop();ui._show_document(str(ui.curves[0].dataset.path));dialog.accept()
    assert '返回' in dialog.error.text() and ui._pending_measurement is selection and len(ui.curves)==2
    dialog.reject()


def test_parent_delete_and_edit_invalidate_children(ui,tmp_path):
    c,e=setup_ui(ui,tmp_path);ui.start_running_integral();ui.confirm_measurement().accept();d=ui.curves[-1]
    ui.edit_measurement(e);ui.confirm_measurement()
    assert d not in ui.curves and len(ui.results)==1
    e=ui.results[0];ui.start_running_integral();ui.confirm_measurement().accept();assert len(ui.curves)==3
    ui.delete_result(e);assert len(ui.curves)==2 and ui.results==[]


def test_signals_preserves_derived_and_units_keep_parent_provenance(ui,tmp_path):
    from tma_app.signals_dialog import SignalsDialog
    c,e=setup_ui(ui,tmp_path);ui.start_running_integral();ui.confirm_measurement().accept();d=ui.curves[-1]
    dialog=SignalsDialog(ui);assert not dialog.signals[3].isEnabled();dialog.accept()
    assert dialog.result()==QDialog.Accepted and ui.curves[-1].derived==d.derived
    d=ui.curves[-1];old=d.xy()[1].copy();doc=ui.active_document()
    ui.apply_unit_options(doc,dict(dimension='mm',offset='none',time='sec',temperature='°F'))
    d=ui.curves[-1];assert e in ui.results
    np.testing.assert_allclose(d.xy()[1],old*.06)
    save_session(tmp_path/'converted.tmas',ui.curves,ui.domain,ui.results,ui.plot_options)
    assert len(load_session(tmp_path/'converted.tmas')[0])==3


def test_overlay_creation_does_not_leak_to_other_views(ui,tmp_path):
    ui.finish_import([data(tmp_path,name='one.001'),data(tmp_path,name='two.002')],[])
    ui.show_overlay();first=ui.active_document();second=ui.copy_overlay(first.key)
    c=ui.curves[1];ui.refresh_curve(c.uid)
    e=ui.start_peak_integration();ui.confirm_measurement()
    ui.start_running_integral();ui.confirm_measurement().accept();d=ui.curves[-1]
    assert d.uid in second.curve_uids and d.uid not in first.curve_uids and not d.normal_enabled
    assert any(c.uid==d.uid for c in ui.visible_curves())
    ui._show_document(first.key);assert all(c.uid!=d.uid for c in ui.visible_curves())
    ui._show_document(str(c.dataset.path));assert all(c.uid!=d.uid for c in ui.visible_curves())
    ui._show_document(second.key);assert d.axis==3 and any(c.uid==d.uid for c in ui.visible_curves())
    save_session(tmp_path/'views.tmas',ui.curves,ui.domain,ui.results,ui.plot_options)
    assert len(load_session(tmp_path/'views.tmas')[0])==3


def test_sigmoid_snapshot_and_absolute_baseline_are_distinct(ui,tmp_path):
    c,e=setup_ui(ui,tmp_path);ui.delete_result(e)
    e=ui.start_peak_integration('peak_sigmoid');ui.confirm_measurement();snapshot=deepcopy(e['values']['sigmoid_profile'])
    ui.start_running_integral();dialog=ui.confirm_measurement();assert dialog.parent_baseline.text()=='S形基线'
    dialog.accept();d=ui.curves[-1]
    np.testing.assert_allclose(d.base_y,snapshot['cumulative'])
    ui.start_running_integral();dialog=ui.confirm_measurement();dialog.zero_baseline.setChecked(True);dialog.accept()
    absolute=ui.curves[-1];assert absolute is not d
    t=np.asarray(snapshot['time']);y=np.asarray(snapshot['signal']);reference=np.r_[0.,np.cumsum((y[:-1]+y[1:])*.5*np.diff(t))]
    np.testing.assert_allclose(absolute.base_y,reference)
    assert e['values']['sigmoid_profile']==snapshot and absolute.base_y[-1]!=pytest.approx(d.base_y[-1])
    save_session(tmp_path/'two-baselines.tmas',ui.curves,ui.domain,ui.results,ui.plot_options)
    assert len(load_session(tmp_path/'two-baselines.tmas')[0])==4


def test_numeric_file_information_failure_is_atomic_success_removes_children(ui,tmp_path,monkeypatch):
    c,e=setup_ui(ui,tmp_path);ui.start_running_integral();ui.confirm_measurement().accept();d=ui.curves[-1]
    from tma_app import reader
    monkeypatch.setattr(reader,'read_dataset',lambda path:(_ for _ in ()).throw(ValueError('missing')))
    before=deepcopy(ui.plot_options)
    with pytest.raises(ValueError,match='重新读取'):ui.apply_file_information(c,{'Sample':'new'},True,2.)
    assert d in ui.curves and e in ui.results and ui.plot_options==before and c.file_info=={}
    ui.apply_file_information(c,{'Sample':'new'})
    assert d in ui.curves and e in ui.results and d.sample_name=='new'
    monkeypatch.setattr(reader,'read_dataset',lambda path:c.dataset)
    ui.apply_file_information(c,{},True,2.)
    assert d not in ui.curves and e not in ui.results and c.sample_size_mm==2.
    assert ui.active_document().key==str(c.dataset.path)


def test_derived_specific_limits_and_curve_value(ui,tmp_path):
    c,e=setup_ui(ui,tmp_path);ui.start_running_integral();dialog=ui.confirm_measurement();dialog.percent.setChecked(True);dialog.accept();d=ui.curves[-1]
    ui.refresh_curve(d.uid)
    ui.apply_data_limits(d.dataset,dict(kind='cursor',rows=list(range(30,71)),reset_time=True),curve_uid=d.uid)
    d=ui.curves[-1];assert c.data_indices is None and len(d.active_rows)==41
    marker=ui.start_point_measurement('curve_value');dialog=ui.confirm_measurement();dialog.accept()
    assert marker in ui.results and marker['values']['start_y']==pytest.approx(d.xy()[1][marker['interactive']['indices'][0]])
    assert ui.selected().uid==d.uid and d.result_unit=='%'
    save_session(tmp_path/'derived-marker.tmas',ui.curves,ui.domain,ui.results,ui.plot_options)
    assert len(load_session(tmp_path/'derived-marker.tmas')[0][-1].active_rows)==41
    ui.undo();assert ui.curves[-1].data_indices is None
    bounds=ui.show_data_limits('time');bounds.fields['start'].setText('3');bounds.fields['stop'].setText('7');bounds.accept()
    assert bounds.result()==QDialog.Accepted and len(ui.curves[-1].active_rows)==41 and c.data_indices is None
    chooser=ui.show_data_limits()
    next(b for b in chooser.choices.buttons() if b.property('kind')=='full').setChecked(True);chooser.accept()
    assert chooser.result()==QDialog.Accepted and ui.curves[-1].data_indices is None and c.data_indices is None


def test_reset_and_processing_use_computed_base_not_raw_dimension(ui,tmp_path):
    c,e=setup_ui(ui,tmp_path);ui.start_running_integral();ui.confirm_measurement().accept();d=ui.curves[-1];before=d.base_y.copy()
    ui.refresh_curve(d.uid);ui.process('derivative')
    assert d.working.shape==(d.sample_count,) and 'µm·min' in d.result_unit and '/(°C)' in d.result_unit
    assert d.result_label.count('d(')==2 # quantity and its independent variable
    ui.reset_curve();np.testing.assert_array_equal(d.xy()[1],before);assert d.derived is not None and d.result_unit=='µm·min'
    from tma_app.data_limits import smoothed_state
    with pytest.raises(ValueError,match='不能平滑'):smoothed_state(d,'temperature',1.)


def test_auto_configure_retains_distinct_same_unit_integrals_and_deduplicates_raw(ui,tmp_path):
    import uuid
    c,e=setup_ui(ui,tmp_path)
    ui.start_running_integral();ui.confirm_measurement().accept();first=ui.curves[-1]
    ui.start_running_integral();dialog=ui.confirm_measurement();dialog.zero_baseline.setChecked(True);dialog.accept();second=ui.curves[-1]
    frozen={d.uid:deepcopy(d.derived) for d in (first,second)}
    ui.curves.append(replace(c,uid=uuid.uuid4().hex,history=[]))
    dialog=ui.auto_configure_overlay();dialog.accept();assert dialog.result()==QDialog.Accepted,dialog.error.text()
    visible=ui.visible_curves()
    assert {first.uid,second.uid}<=set(d.uid for d in visible)
    assert len([d for d in visible if d.dataset.path==c.dataset.path and d.derived is None])==1
    assert all(next(d for d in ui.curves if d.uid==uid).derived==snapshot for uid,snapshot in frozen.items())
    path=tmp_path/'distinct-integrals.tmas';save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    loaded,_,_,plots=load_session(path,include_plot_options=True)
    assert {first.uid,second.uid}<=set(plots[ui.active_document().key]['overlay_members'])
