"""Native marker workflows, independent fits and linked peak deletion."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import json,zipfile
import numpy as np
import pytest
from PySide6.QtWidgets import QDialog
from matplotlib.backend_bases import MouseEvent
from matplotlib.text import Text
from test_feature_ui import ui,source
from test_running_integral import setup_ui
from tma_app.workspace import Curve,save_session,load_session
from tma_app.slope import values,validate_snapshot


@pytest.mark.parametrize('x',[[0,1,2,3,4],[4,3,2,1,0],[0,1,1,3,4],[0,2,1,4,3]])
def test_ols_retains_acquired_order_and_fractional_endpoints(tmp_path,x):
    x=np.asarray(x,dtype=float);y=x*x+2*x+1
    c=Curve(replace(source(tmp_path/'slope.001'),values=np.column_stack((np.arange(5),x,y))))
    before=c.dataset.values.copy();v=values(c,dict(kind='slope',domain='temperature'),[.25,3.75])
    p=np.array([.25,1,2,3,3.75]);xx=np.interp(p,np.arange(5),x);yy=np.interp(p,np.arange(5),y)
    m,b=np.polyfit(xx,yy,1);assert v['slope']==pytest.approx(m) and v['intercept']==pytest.approx(b)
    assert v['slope_unit']=='µm/°C' and v['points']==5
    np.testing.assert_array_equal(v['fit_profile']['x'],xx);validate_snapshot(v,5,[3.75,.25])
    np.testing.assert_array_equal(before,c.dataset.values)


def test_units_scale_slopes_and_preserve_origins(tmp_path):
    c=Curve(source(tmp_path/'units.001'));e=dict(kind='slope',domain='temperature')
    a=values(c,e,[0,6]);converted=replace(c,unit_options=dict(dimension='mm',offset='zero_size',temperature='°F',time='sec'),sample_size_mm=2.)
    b=values(converted,e,[0,6]);assert b['slope']==pytest.approx(a['slope']*.001/1.8) and b['slope_unit']=='mm/°F'
    t=dict(e,domain='time');assert values(converted,t,[0,6])['slope']==pytest.approx(values(c,t,[0,6])['slope']/60000)


def test_invalid_regions_and_strict_snapshot(tmp_path):
    c=Curve(source(tmp_path/'invalid.001'));e=dict(kind='slope',domain='temperature')
    for p in ([0,0],[-1,3],[0,7],[True,3],[0,float('nan')]):
        with pytest.raises(ValueError):values(c,e,p)
    with pytest.raises(ValueError,match='跨'):values(replace(c,data_indices=[0,1,4,5,6]),e,[0,4])
    ds=replace(c.dataset,values=c.dataset.values.copy());ds.values[:,1]=100
    with pytest.raises(ValueError,match='尺度'):values(replace(c,dataset=ds),e,[0,6])
    v=values(c,e,[0,6]);bad=deepcopy(v);bad['slope']+=.01
    with pytest.raises(ValueError,match='快照'):validate_snapshot(bad,7,[0,6])
    bad=deepcopy(v);bad['fit_profile']['positions'].pop(2);bad['fit_profile']['x'].pop(2);bad['fit_profile']['y'].pop(2)
    with pytest.raises(ValueError,match='遗漏'):validate_snapshot(bad,7,[0,6])


def test_compound_slope_units_and_constant_signal(tmp_path):
    from tma_app.slope import ratio_unit
    assert ratio_unit('µm','(µm)/(min)')=='µm/((µm)/(min))'
    assert ratio_unit('(µm)/(min)','°C')=='((µm)/(min))/°C'
    assert ratio_unit('µm','')=='µm/X'
    c=Curve(source(tmp_path/'constant.001'));c.dataset.values[:,2]=3
    v=values(c,dict(kind='slope',domain='temperature'),[0,6]);assert v['slope']==0 and v['r2']==1
    validate_snapshot(v,7,[0,6])


def test_slope_menu_exact_editor_labels_cancel_and_second_file(ui,tmp_path):
    c,_=setup_ui(ui,tmp_path);raw=c.dataset.values.copy();ui.classic_actions['Slope1'].trigger();e=ui._pending_measurement
    assert e['kind']=='slope' and len(e['interactive']['indices'])==2 and 'fit_error' not in e['values']
    old=deepcopy(e['interactive']);dialog=ui.edit_measurement_limits();assert all(f.isReadOnly() for f in dialog.y_fields)
    x,y=c.xy();targets=[23.25,79.75]
    for field,p in zip(dialog.fields,targets):field.setText(format(np.interp(p,np.arange(len(x)),x),'.17g'))
    dialog.accept();assert dialog.result()==QDialog.Accepted,dialog.error.text()
    np.testing.assert_allclose(e['interactive']['positions'],targets,atol=1e-10)
    assert e['interactive']!=old
    ui.create_measurement_menu().actions()[0].trigger();assert e in ui.results and ui._pending_measurement is None
    assert ui.selected().uid==c.uid and ui.active_document().key==str(c.dataset.path)
    artist=next(a for a in ui._measurement_artists if a.entry is e);frozen=deepcopy(e['values'])
    assert '斜率' in artist.annotation.get_text() and len(artist.slope_line.get_xdata())==2
    for text in [artist.temps[0],artist.annotation]:
        ui.canvas.draw();box=Text.get_window_extent(text,ui.canvas.get_renderer());px,py=(box.x0+box.x1)/2,(box.y0+box.y1)/2
        for kind,a,b in (('button_press_event',px,py),('motion_notify_event',px+24,py+18),('button_release_event',px+24,py+18)):
            ui.canvas.callbacks.process(kind,MouseEvent(kind,ui.canvas,a,b,button=1))
    assert e['values']==frozen and 't1' in e['annotation']['label_offsets'] and 'offset' in e['annotation']
    ui.edit_measurement(e);ui.cancel_measurement();assert e in ui.results and e['values']==frozen
    path=tmp_path/'slope.tmas';save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    loaded,_,results=load_session(path);assert next(r for r in results if r['kind']=='slope')['values']==frozen
    np.testing.assert_array_equal(c.dataset.values,raw)


def test_invalid_slope_cannot_confirm_and_exact_editor_is_atomic(ui,tmp_path):
    c,_=setup_ui(ui,tmp_path);e=ui.start_point_measurement('slope');e['interactive']['indices']=[10,10];ui.redraw()
    ui.confirm_measurement();assert ui._pending_measurement is e and e not in ui.results and 'fit_error' in e['values']
    before=deepcopy(e);dialog=ui.edit_measurement_limits()
    for field in dialog.fields:field.setText(str(c.xy()[0][10]))
    dialog.accept();assert dialog.result()!=QDialog.Accepted and e==before;dialog.reject();ui.cancel_measurement()


def test_slope_on_derived_quantity_and_archived_processing(ui,tmp_path):
    c,_=setup_ui(ui,tmp_path);ui.start_running_integral();dialog=ui.confirm_measurement();dialog.percent.setChecked(True);dialog.accept();d=ui.curves[-1]
    ui.refresh_curve(d.uid);e=ui.start_point_measurement('slope');ui.confirm_measurement();assert e in ui.results and e['values']['slope_unit']=='%/°C'
    fixed=deepcopy(e['values']);ui.process('derivative')
    path=tmp_path/'archived.tmas';save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    loaded,_,results=load_session(path);assert next(r for r in results if r['kind']=='slope')['values']==fixed
    ui.reset_curve();assert next(a for a in ui._measurement_artists if a.entry is e).entry['values']==fixed


def test_legacy_noninteractive_slope_archive_is_still_valid(tmp_path):
    c=Curve(source(tmp_path/'legacy.001'))
    old=dict(file=c.dataset.path.name,sha256=c.dataset.sha256,curve_id=c.uid,kind='slope',domain='temperature',lo=100.,hi=106.,signal=c.result_label,operations=[],transform=c.result_transform('temperature'),values=dict(slope=1.,intercept=-100.,r2=.5))
    path=tmp_path/'legacy.tmas';save_session(path,[c],'temperature',[old]);assert load_session(path)[2]==[old]


def test_delete_peak_native_marker_cancel_and_linked_quantities(ui,tmp_path):
    c,peak=setup_ui(ui,tmp_path);ui.start_running_integral();ui.confirm_measurement().accept();child=ui.curves[-1]
    slope=ui.start_point_measurement('slope');ui.confirm_measurement();before=list(ui.results)
    ui.classic_actions['DeletePeak1'].trigger();e=ui._pending_measurement
    assert e['purpose']=='delete_peak' and len(e['interactive']['indices'])==1
    ui.cancel_measurement();assert ui.results==before and child in ui.curves
    ui.classic_actions['DeletePeak1'].trigger();ui.create_measurement_menu().actions()[0].trigger()
    assert peak not in ui.results and slope in ui.results and child not in ui.curves and ui._pending_measurement is None
    assert ui.selected().uid==c.uid and ui.active_document().key==str(c.dataset.path)
    save_session(tmp_path/'deleted.tmas',ui.curves,ui.domain,ui.results,ui.plot_options)


def test_delete_peak_cross_document_and_changed_curve_do_not_delete(ui,tmp_path):
    c,peak=setup_ui(ui,tmp_path);e=ui.start_delete_peak();other=ui.curves[0]
    ui._show_document(str(other.dataset.path));ui.confirm_measurement();assert peak in ui.results and ui._pending_measurement is e
    ui._show_document(str(c.dataset.path));c.offset=1;ui.redraw();ui.confirm_measurement();assert peak in ui.results
    c.offset=0;ui.redraw();ui.cancel_measurement()


def test_delete_selector_chooses_latest_compatible_peak_at_position(ui,tmp_path):
    c,first=setup_ui(ui,tmp_path);second=ui.start_peak_integration();ui.confirm_measurement();e=ui.start_delete_peak()
    assert ui.running_integral_parent(e) is second
    ui.confirm_measurement();assert any(r is first for r in ui.results) and all(r is not second for r in ui.results)


def test_delete_marker_outside_all_peak_limits_stays_pending(ui,tmp_path):
    c,first=setup_ui(ui,tmp_path);ui.delete_result(first)
    peak=ui.start_peak_integration();peak['interactive']['indices']=[20,80];ui.redraw();ui.confirm_measurement()
    e=ui.start_delete_peak();e['interactive'].update(indices=[0],positions=[0.]);ui.redraw();ui.confirm_measurement()
    assert ui._pending_measurement is e and any(r is peak for r in ui.results)
    assert '范围' in ui.statusBar().currentMessage();ui.cancel_measurement()


def test_slope_snapshot_tampering_fails_session_load(ui,tmp_path):
    c,_=setup_ui(ui,tmp_path);ui.start_point_measurement('slope');ui.confirm_measurement()
    path=tmp_path/'good.tmas';save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    with zipfile.ZipFile(path) as z:members={name:z.read(name) for name in z.namelist()}
    doc=json.loads(members['session.json']);next(r for r in doc['results'] if r['kind']=='slope')['values']['slope']+=1
    members['session.json']=json.dumps(doc,ensure_ascii=False).encode('utf8');bad=tmp_path/'bad.tmas'
    with zipfile.ZipFile(bad,'w') as z:
        for name,content in members.items():z.writestr(name,content)
    with pytest.raises(ValueError,match='快照'):load_session(bad)
