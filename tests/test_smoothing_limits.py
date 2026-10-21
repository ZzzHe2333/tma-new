"""Physical widths, acquired limits/gaps, reuse and original-data invariants."""
from copy import deepcopy
from pathlib import Path
import csv,json
import numpy as np
import pytest
from PySide6.QtWidgets import QDialog
from PySide6.QtCore import Qt
from test_feature_ui import ui,imported,source,set_combo
from tma_app.app import DataModel
from tma_app.workspace import Curve,save_session
from tma_app.reader import Dataset,Signal
from tma_app.signal_processing import local_fit
from tma_app.data_limits import select_rows,segments
from tma_app.measurement import position_at_x
from tma_app.secondary_axis import corresponding_values
from tma_app.signals_dialog import SignalsDialog


def limits(kind="time",start=0.,stop=0.,**extra):
    return dict(kind=kind,start=float(start),stop=float(stop),delay=0.,all_cycles=False,reset_time=False,**extra)


def smooth(ui,width,reuse=False):
    dialog=ui.show_native_smooth();dialog.width_edit.setText(str(width));dialog.reuse.setChecked(reuse);dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted,dialog.error.text()
    return dialog


def test_native_width_recomputes_from_raw_and_undo_restores_width_and_rule(ui,tmp_path):
    imported(ui,tmp_path);ui.show_normal();curve=ui.selected();raw=curve.dataset.values.copy();uid=curve.uid
    x=raw[:,curve.dataset.temperature_index];y=raw[:,curve.y_index]
    dialog=smooth(ui,2,True)
    assert dialog.size().width()==370 and dialog.units.text()=="°C"
    np.testing.assert_allclose(curve.xy(ui.domain)[1],local_fit(x,y,2))
    first=curve.working.copy();smooth(ui,4,True)
    np.testing.assert_allclose(curve.xy(ui.domain)[1],local_fit(x,y,4))
    ui.undo();np.testing.assert_allclose(curve.working,first);assert curve.smooth_width==2
    assert ui.smoothing_rules()[-1]["width"]==2
    assert ui.selected().uid==uid and ui.mdi.activeSubWindow().key==str(curve.dataset.path)
    np.testing.assert_array_equal(curve.dataset.values,raw)


def test_custom_derivative_smoothing_keeps_base_and_zero_removes_only_new_smoothing(ui,tmp_path):
    imported(ui,tmp_path,1);ui.show_normal();ui.domain_box.setCurrentIndex(1);ui.process("derivative")
    curve=ui.selected();base=curve.working.copy();ops=list(curve.operations);x=curve.x_values("time")
    smooth(ui,2);smooth(ui,4)
    np.testing.assert_allclose(curve.working,local_fit(x,base,4))
    assert curve.operations[:-1]==ops and curve.y_type=="custom"
    smooth(ui,0);np.testing.assert_array_equal(curve.working,base);assert curve.operations==ops
    path=tmp_path/"base.tmas";save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    ui.close_all_documents();ui.restore_session(path);ui.show_normal()
    np.testing.assert_array_equal(ui.selected().smooth_source,base)
    smooth(ui,2);np.testing.assert_allclose(ui.selected().working,local_fit(x,base,2))


def test_native_time_derivative_uses_time_width_on_temperature_plot_and_reuses_limits(ui,tmp_path):
    imported(ui,tmp_path,1);ui.show_normal()
    dialog=SignalsDialog(ui);set_combo(dialog.types[0],"d_time");dialog.accept()
    curve=ui.selected();raw=curve.dataset.values.copy()
    dialog=smooth(ui,2,True);assert dialog.units.text()=="min" and ui.domain=="temperature"
    ui.apply_data_limits(curve.dataset,limits(start=1,stop=5));curve=ui.selected()
    assert curve.smooth_width==2 and len(curve.xy("time")[0])==5
    np.testing.assert_allclose(curve.working[1:6],local_fit(raw[1:6,0],raw[1:6,2],2,1))


def test_time_limits_zero_origin_raw_table_csv_and_full_range(ui,tmp_path):
    imported(ui,tmp_path);ui.show_normal();ui.domain_box.setCurrentIndex(1)
    curve=ui.selected();raw=curve.dataset.values.copy();other=next(c for c in ui.curves if c.dataset.path!=curve.dataset.path)
    dialog=ui.show_data_limits("time");dialog.fields["start"].setText("1");dialog.fields["stop"].setText("4");dialog.reset.setChecked(True);dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted
    curve=ui.selected();assert curve.data_indices==[1,2,3,4]
    np.testing.assert_array_equal(curve.xy("time")[0],[0,1,2,3])
    assert other.data_indices is None
    model=DataModel(curve,"time");assert model.rowCount()==4
    assert model.headerData(0,Qt.Orientation.Vertical)=="2"
    assert model.data(model.index(0,0))=="1" and model.data(model.index(0,3))=="0"
    ui.write_data(tmp_path/"window.csv",curve)
    rows=list(csv.reader((tmp_path/"window.csv").read_text(encoding="utf-8-sig").splitlines()))
    assert len(rows)==5 and float(rows[1][0])==1 and float(rows[1][-2])==0
    meta=json.loads((tmp_path/"window.csv.meta.json").read_text(encoding="utf-8"));assert meta["transform"]["time_origin"]==1
    ui.full_data_range();curve=ui.selected();assert curve.data_indices is None and not curve.reset_time
    np.testing.assert_array_equal(curve.dataset.values,raw)
    assert select_rows(curve.dataset,limits()) is None


def cycled_dataset(path):
    temp=np.array([0,10,20,30,20,10,0,10,20,30,20,10,0,10,20,30,20,10,0,10,20.])
    time=np.arange(len(temp),dtype=float)
    return Dataset(Path(path),[Signal("Time","min"),Signal("Temperature","°C"),Signal("Dimension Change","µm")],
                   np.column_stack((time,temp,time*time)),{},[],"cycled")


def test_temperature_direction_delay_and_all_cycles_keep_acquisition_gaps(ui,tmp_path):
    ds=cycled_dataset(tmp_path/"cycle.001");ui.finish_import([ds],[]);ui.show_normal()
    assert select_rows(ds,limits("temperature",10,20))==[1,2]
    assert select_rows(ds,limits("temperature",20,10))==[4,5]
    spec=limits("temperature",10,20);spec["delay"]=6
    assert select_rows(ds,spec)==[7,8]
    spec["all_cycles"]=True;ui.apply_data_limits(ds,spec);curve=ui.selected();rows=curve.active_rows
    assert len(segments(rows))>1
    ui.canvas.draw();line=next(line for line in ui.axes[0].lines if getattr(line,"_tma_curve_uid",None)==curve.uid)
    assert np.isnan(line.get_xdata()).sum()==len(segments(rows))-1
    x=curve.x_values("time")
    with pytest.raises(ValueError):position_at_x(x,9.,0,rows)
    assert corresponding_values(x,ds.values[rows,1],[9.],rows)==[None]
    errors=[];ui.warn=errors.append;ui.analysis_box.setCurrentIndex(ui.analysis_box.findData("slope"));ui.run_analysis(bounds=(10,20))
    assert errors and not ui.results


def test_physical_fit_does_not_use_excluded_samples(ui,tmp_path):
    time=np.arange(20,dtype=float);temp=np.r_[np.ones(7)*10,np.ones(6)*50,np.ones(7)*10]
    y=2*time+3;y[7:13]=1e9
    ds=Dataset(tmp_path/"gaps.001",[Signal("Time","min"),Signal("Temperature","°C"),Signal("Dimension Change","µm")],np.column_stack((time,temp,y)),{},[],"gaps")
    ui.finish_import([ds],[]);ui.show_normal();ui.domain_box.setCurrentIndex(1)
    spec=limits("temperature",9,11);spec["all_cycles"]=True;ui.apply_data_limits(ds,spec)
    smooth(ui,20,True);curve=ui.selected();rows=curve.active_rows
    np.testing.assert_allclose(curve.xy("time")[1],2*time[rows]+3,atol=1e-10)
    with pytest.raises(ValueError):curve.validate_positions([6.5])


def test_multi_axis_limits_undo_preserves_old_results_and_session_can_restore_old_view(ui,tmp_path):
    imported(ui,tmp_path,1);ui.show_normal();entry=ui.start_point_measurement("signal_max");ui.confirm_measurement();result=deepcopy(entry)
    dialog=SignalsDialog(ui);set_combo(dialog.signals[1],ui.selected().dataset.signals[2].label);set_combo(dialog.types[1],"d_time");dialog.accept()
    ui.select_plot_axis(1);smooth(ui,2,True);ds=ui.selected().dataset
    ui.apply_data_limits(ds,limits(start=1,stop=5))
    assert all(c.data_indices==[1,2,3,4,5] for c in ui.curves)
    assert not ui._measurement_artists and ui.results==[result]
    path=tmp_path/"limited.tmas";save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    ui.select_plot_axis(0);ui.undo()
    assert all(c.data_indices is None for c in ui.curves) and len(ui._measurement_artists)==1
    assert next(c for c in ui.curves if c.axis==1).smooth_width==2
    ui.close_all_documents();ui.restore_session(path)
    assert ui.results==[result] and all(c.data_indices==[1,2,3,4,5] for c in ui.curves)


def test_invalid_limits_and_smooth_cancel_default_never_modify_live_state(ui,tmp_path):
    imported(ui,tmp_path,1);ui.show_normal();curve=ui.selected();before=curve.xy(ui.domain)[1].copy()
    dialog=ui.show_native_smooth();dialog.width_edit.setText("3");dialog.reuse.setChecked(True);dialog.defaults()
    assert dialog.width_edit.text()=="0" and not dialog.reuse.isChecked();dialog.reject()
    assert curve.working is None and not curve.history
    dialog=ui.show_native_smooth();dialog.width_edit.setText("nan");dialog.accept()
    assert dialog.result()!=QDialog.DialogCode.Accepted and dialog.error.text();dialog.reject()
    original=list(ui.curves);options=deepcopy(ui.plot_options)
    with pytest.raises(ValueError):ui.apply_data_limits(curve.dataset,limits(start=500,stop=1000))
    assert ui.curves==original and ui.plot_options==options
    np.testing.assert_array_equal(curve.xy(ui.domain)[1],before)


def test_reuse_survives_close_and_session_and_disabling_reuse_wins(ui,tmp_path):
    imported(ui,tmp_path,1);ui.show_normal();smooth(ui,2,True)
    ui.close_all_documents();ui.finish_import([source(tmp_path/"next.002")],[])
    assert ui.selected().smooth_reuse and ui.selected().smooth_width==2
    smooth(ui,2,False)
    path=tmp_path/"disabled.tmas";save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    ui.close_all_documents();ui.restore_session(path);ui.finish_import([source(tmp_path/"third.003")],[])
    assert not ui.selected().smooth_reuse and ui.selected().smooth_width==0 and ui.selected().working is None


def test_axis_selector_selects_existing_curve_without_reassigning_it(ui,tmp_path):
    imported(ui,tmp_path,1);ui.show_normal()
    dialog=SignalsDialog(ui);set_combo(dialog.signals[1],ui.selected().dataset.signals[0].label);dialog.accept()
    before=[c.axis for c in ui.curves];second=next(c for c in ui.curves if c.axis==1)
    ui.classic_actions["Y2"].trigger()
    assert ui.selected().uid==second.uid and [c.axis for c in ui.curves]==before


def test_explicit_cycle_signal_enables_native_cycle_bounds(ui,tmp_path):
    ds=source(tmp_path/"numbered.001");ds.signals.append(Signal("Cycle",""));ds.values=np.column_stack((ds.values,[1,1,2,2,3,3,3]))
    ui.finish_import([ds],[]);dialog=ui.show_data_limits("cycle")
    dialog.fields["start"].setText("2");dialog.fields["stop"].setText("3");dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted and ui.selected().data_indices==[2,3,4,5,6]


def test_legacy_processing_of_a_limited_window_never_labels_unprocessed_outer_rows_as_derivatives(ui,tmp_path):
    imported(ui,tmp_path,1);ui.show_normal();ui.domain_box.setCurrentIndex(1)
    ui.apply_data_limits(ui.selected().dataset,limits(start=1,stop=5));ui.process("derivative")
    curve=ui.selected();assert curve.working_rows==[1,2,3,4,5]
    before=curve.working.copy()
    with pytest.raises(ValueError):ui.apply_data_limits(curve.dataset,None)
    np.testing.assert_array_equal(ui.selected().working,before)
    ui.reset_curve();ui.full_data_range()
    assert ui.selected().data_indices is None and ui.selected().working is None


def test_smoothing_custom_x_remembers_its_variable_when_display_x_changes(ui,tmp_path):
    imported(ui,tmp_path,1);ui.show_normal()
    dialog=SignalsDialog(ui)
    next(b for b in dialog.x_modes.buttons() if b.property("mode")=="signal").click()
    set_combo(dialog.x_signal,ui.selected().dataset.signals[0].label);dialog.accept()
    smooth(ui,2,True);curve=ui.selected();assert curve.smooth_x_config["index"]==0
    dialog=SignalsDialog(ui);set_combo(dialog.x_signal,curve.dataset.signals[1].label);dialog.accept()
    dialog=ui.show_native_smooth()
    assert dialog.units.text()=="°C" and dialog.width_edit.text()=="0" and not dialog.reuse.isChecked();dialog.reject()
    ui.apply_data_limits(curve.dataset,limits(start=1,stop=5));curve=ui.selected()
    np.testing.assert_allclose(curve.working[1:6],local_fit(curve.dataset.values[1:6,0],curve.dataset.values[1:6,2],2))


def test_leading_temperature_holds_are_kept_and_stop_is_not_joined_to_next_cooling_leg(tmp_path):
    ds=cycled_dataset(tmp_path/"hold.001");ds.values=ds.values[:6].copy();ds.values[:,1]=[10,10,10,15,20,10]
    assert select_rows(ds,limits("temperature",10,20))==[0,1,2,3,4]


@pytest.mark.parametrize("rows",[[],[0],[False,1],[2,1],[0,7],[1,2.5]])
def test_malformed_saved_acquisition_rows_are_rejected_without_writing_a_session(tmp_path,rows):
    curve=Curve(source(tmp_path/"raw.001"),data_indices=rows)
    path=tmp_path/"invalid.tmas"
    with pytest.raises(ValueError):save_session(path,[curve],"temperature",[])
    assert not path.exists()


def test_archived_native_derivative_result_survives_a_new_data_window(ui,tmp_path):
    imported(ui,tmp_path,1);ui.show_normal()
    dialog=SignalsDialog(ui);set_combo(dialog.types[0],"d_time");dialog.accept()
    ui.start_point_measurement("signal_max");ui.confirm_measurement();result=deepcopy(ui.results[0])
    ui.apply_data_limits(ui.selected().dataset,limits(start=1,stop=5))
    path=tmp_path/"derivative-window.tmas";save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    ui.close_all_documents();ui.restore_session(path)
    assert ui.results[0]==result
