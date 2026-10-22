"""Acquired-data cursor boundaries, separate from stored analysis results."""
from copy import deepcopy
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtWidgets import QDialog
from matplotlib.backend_bases import MouseEvent
from test_feature_ui import ui,imported
from test_smoothing_limits import cycled_dataset,limits,smooth
from tma_app.data_limits import cursor_spec,select_rows
from tma_app.workspace import save_session,load_session
from tma_app.app import DataModel


def action(menu,label):return next(a for a in menu.actions() if a.text()==label)


def test_cursor_menu_manual_confirm_limits_data_not_analysis_and_keeps_third_file(ui,tmp_path):
    imported(ui,tmp_path,3);ui.show_normal();curve=ui.selected();uid=curve.uid;doc=ui.active_document()
    ui.start_point_measurement("signal_max");ui.confirm_measurement();old=deepcopy(ui.results)
    raw=curve.dataset.values.copy();ui.dirty=False
    assert ui.classic_actions["CursorLimits1"].isEnabled()
    ui.classic_actions["CursorLimits1"].trigger();pending=ui._pending_measurement
    assert pending["purpose"]=="data_limits" and not ui.dirty
    editor=next(e for e in ui._measurement_artists if e.entry is pending)
    assert not editor.annotation.get_visible() and not editor.arrow.get_visible()
    assert not editor.horizontal.get_visible() and len(editor.temps)==2
    menu=ui.create_plot_context_menu()
    assert [a.text() for a in menu.actions() if not a.isSeparator()]==["确定","编辑…","自动界限","取消","恢复初始界限","点 1","点 2"]
    dialog=ui.edit_measurement_limits();assert all(field.isReadOnly() for field in dialog.y_fields)
    dialog.fields[0].setText("100.25");dialog.fields[1].setText("104.75");dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted and not ui.dirty
    assert "H " not in ui.statusBar().currentMessage()
    action(ui.create_plot_context_menu(),"确定").trigger();curve=ui.selected()
    assert curve.uid==uid and ui.active_document() is doc
    assert curve.data_indices==[1,2,3,4] and curve.data_limit_spec["kind"]=="cursor"
    assert ui._pending_measurement is None and ui.results==old
    assert DataModel(curve,ui.domain).rowCount()==4 and not ui._measurement_artists
    assert all(c.data_indices is None for c in ui.curves if c.dataset.path!=curve.dataset.path)
    np.testing.assert_array_equal(curve.dataset.values,raw)
    path=tmp_path/"cursor.tmas";save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    restored,domain,results=load_session(path)
    assert results==old and next(c for c in restored if c.uid==uid).data_indices==[1,2,3,4]
    ui.undo();assert ui.selected().data_indices is None and ui.results==old
    assert len(ui._measurement_artists)==1


def test_cursor_cancel_and_other_document_enter_do_not_commit_hidden_draft(ui,tmp_path):
    imported(ui,tmp_path,3);ui.show_normal();curve=ui.selected();uid=curve.uid;raw=deepcopy(curve.data_limit_spec);ui.dirty=False
    pending=ui.graphic_range();original=ui.active_document()
    other=next(doc for key,doc in ui.documents.items() if key!=original.key and not ui._is_overlay(key))
    ui.mdi.setActiveSubWindow(other);ui.document_activated(other)
    assert ui.current_measurement() is None
    ui.measurement_key(SimpleNamespace(key="enter"));ui.confirm_measurement()
    assert ui._pending_measurement is pending and curve.data_limit_spec==raw and not ui.results
    assert "打开" in [a.text() for a in ui.create_plot_context_menu().actions()]
    ui.mdi.setActiveSubWindow(original);ui.document_activated(original)
    action(ui.create_plot_context_menu(),"取消").trigger()
    assert ui._pending_measurement is None and ui.selected().uid==uid and not ui.dirty


def test_cursor_drag_tab_reverse_bounds_and_reset_time_use_original_rows(ui,tmp_path):
    imported(ui,tmp_path,1);ui.show_normal();ui.domain_box.setCurrentIndex(1)
    spec=limits(start=1,stop=6);spec["reset_time"]=True;ui.apply_data_limits(ui.selected().dataset,spec)
    pending=ui.graphic_range();editor=next(e for e in ui._measurement_artists if e.entry is pending)
    ui.canvas.draw();point=editor.axis.transData.transform(editor.coords[0])
    ui.result_press(MouseEvent("button_press_event",ui.canvas,*point,button=1))
    target=editor.axis.transData.transform((1.,editor.coords[0][1]))
    ui.result_motion(MouseEvent("motion_notify_event",ui.canvas,*target,button=1));ui.result_release(SimpleNamespace())
    assert pending["interactive"]["indices"][0]==1
    ui.measurement_key(SimpleNamespace(key="tab"));assert pending["interactive"]["active_point"]==1
    ui.measurement_key(SimpleNamespace(key="shift+tab"));assert pending["interactive"]["active_point"]==0
    dialog=ui.edit_measurement_limits();dialog.fields[0].setText("3.5");dialog.fields[1].setText("0.5");dialog.accept()
    ui.measurement_key(SimpleNamespace(key="enter"));curve=ui.selected()
    assert curve.data_indices==[2,3,4] and curve.reset_time and curve.time_origin==2
    np.testing.assert_array_equal(curve.xy("time")[0],[0,1,2])
    ui.full_data_range();assert ui.selected().data_indices is None and not ui.selected().reset_time


def test_cursor_on_repeated_temperature_uses_current_branch_and_keeps_excluded_gaps(ui,tmp_path):
    ds=cycled_dataset(tmp_path/"cycled.001");ui.finish_import([ds],[]);ui.show_normal()
    pending=ui.graphic_range();pending["interactive"]["indices"]=[7,8];ui.redraw()
    dialog=ui.edit_measurement_limits();dialog.fields[0].setText("10");dialog.fields[1].setText("20");dialog.accept();ui.confirm_measurement()
    assert ui.selected().data_indices==[7,8]
    spec=limits("temperature",10,20);spec["all_cycles"]=True;ui.apply_data_limits(ds,spec)
    curve=ui.selected();rows=curve.active_rows.copy();pending=ui.graphic_range()
    pending["interactive"]["indices"]=[1,5];ui.redraw();ui.confirm_measurement()
    assert ui.selected().data_indices==rows[1:6].tolist() and np.any(np.diff(ui.selected().active_rows)>1)
    ui.canvas.draw();line=next(l for l in ui.axes[0].lines if getattr(l,"_tma_curve_uid",None)==curve.uid)
    assert np.isnan(line.get_xdata()).any()


def test_cursor_rejects_too_few_points_without_mutating_data_or_losing_draft(ui,tmp_path):
    imported(ui,tmp_path,1);ui.show_normal();curve=ui.selected();pending=ui.graphic_range()
    pending["interactive"]["positions"]=[1.1,1.9];pending["interactive"]["indices"]=[1,2];ui.redraw()
    ui.confirm_measurement()
    assert ui._pending_measurement is pending and curve.data_indices is None and not ui.results
    assert "至少需要2" in ui.statusBar().currentMessage()
    action(ui.create_plot_context_menu(),"恢复初始界限").trigger()
    assert pending["interactive"]["indices"]==[0,6] and "positions" not in pending["interactive"]
    ui.confirm_measurement();assert ui._pending_measurement is None and ui.selected().data_indices is None
    chooser=ui.show_data_limits();assert chooser.choices.checkedButton() is not None;chooser.reject()


def test_cursor_limits_recompute_reused_physical_smooth_and_undo(ui,tmp_path):
    imported(ui,tmp_path,1);ui.show_normal();smooth(ui,2,True);curve=ui.selected();before=curve.working.copy()
    pending=ui.graphic_range();pending["interactive"]["indices"]=[1,5];ui.redraw();ui.confirm_measurement();curve=ui.selected()
    assert curve.data_indices==[1,2,3,4,5] and curve.smooth_width==2 and curve.working_rows==curve.data_indices
    ui.undo();assert ui.selected().data_indices is None
    np.testing.assert_array_equal(ui.selected().working,before)


@pytest.mark.parametrize("rows",[[1], [2,1], [1,1], [True,2], [-1,2], [1,7], [1.,2], "1,2"])
def test_portable_cursor_rows_reject_invalid_acquisition_windows(tmp_path,rows):
    ds=cycled_dataset(tmp_path/"bad.001");ds.values=ds.values[:7]
    with pytest.raises(ValueError):select_rows(ds,{"kind":"cursor","rows":rows,"reset_time":False})


def test_cursor_session_rejects_contradictory_metadata(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.selected()
    curve.data_limit_spec={"kind":"cursor","rows":[1,2,3],"reset_time":False};curve.data_indices=[2,3]
    with pytest.raises(ValueError):save_session(tmp_path/"bad.tmas",ui.curves,ui.domain,[])


def test_cursor_custom_x_uses_acquisition_positions_instead_of_temperature(ui,tmp_path):
    imported(ui,tmp_path,1);ui.show_normal();curve=ui.selected();curve.x_signal_index=0;ui.domain_box.setCurrentIndex(2)
    pending=ui.graphic_range();dialog=ui.edit_measurement_limits()
    dialog.fields[0].setText("1.25");dialog.fields[1].setText("5.75");dialog.accept();ui.confirm_measurement()
    assert ui.selected().data_indices==[2,3,4,5] and ui.domain=="signal"
    assert not ui.results and pending["domain"]=="signal"


def test_compact_manual_fields_preserve_untouched_exact_sample_position(ui,tmp_path):
    imported(ui,tmp_path,1);ui.show_normal();curve=ui.selected()
    curve.dataset.values[:,1]+=0.123456789
    pending=ui.graphic_range();dialog=ui.edit_measurement_limits()
    assert dialog.fields[0].text()=="100.12346"
    assert float(dialog.fields[0].toolTip())==pytest.approx(curve.dataset.values[0,1])
    dialog.accept()
    assert pending["interactive"]["positions"]==[0,6]
    ui.confirm_measurement();assert ui.selected().data_indices is None
    # Explicitly typing that displayed rounded number is a real edit, even
    # when its text is identical to the compact initial display.
    from PySide6.QtTest import QTest
    pending=ui.graphic_range();dialog=ui.edit_measurement_limits()
    dialog.fields[0].selectAll();QTest.keyClicks(dialog.fields[0],"100.12346");dialog.accept()
    assert pending["interactive"]["positions"][0]>0
    ui.confirm_measurement();assert ui.selected().data_indices==[1,2,3,4,5,6]
