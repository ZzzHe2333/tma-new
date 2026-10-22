"""Plot spacing stays separate from physical coordinates and acquired rows."""
from copy import deepcopy
from types import SimpleNamespace
import csv,json
import numpy as np
import pytest
from matplotlib.backend_bases import MouseEvent
from PySide6.QtWidgets import QDialog,QInputDialog
from test_feature_ui import ui,imported
from tma_app.app import DataModel
from tma_app.workspace import save_session,validate_plot_options
from tma_app.preferences import load_defaults


def spacing(ui,values):
    dialog=ui.show_overlay_options()
    for field,value in zip(dialog.axis_x_offsets,values):field.setText(str(value))
    dialog.accept();assert dialog.result()==QDialog.DialogCode.Accepted,dialog.error.text()
    return dialog


def line_for(ui,curve):return next(line for line in ui.axes[curve.axis].lines if getattr(line,"_tma_curve_uid",None)==curve.uid)


def test_axis_spacing_first_curve_order_hidden_members_and_negative_steps(ui,tmp_path):
    imported(ui,tmp_path,4);original={c.uid:c.dataset.values.copy() for c in ui.curves}
    ui.curves[2].axis=1;ui.curves[3].axis=1
    spacing(ui,[7.5,-4,0,0]);assert [ui.display_x_offset(c) for c in ui.curves]==[0,7.5,0,-4]
    for curve in ui.curves:
        np.testing.assert_array_equal(line_for(ui,curve).get_xdata(),curve.xy(ui.domain)[0]+ui.display_x_offset(curve))
        lo,hi=ui.axes[0].get_xlim();display_x=line_for(ui,curve).get_xdata()
        assert lo<=min(display_x) and hi>=max(display_x)
        assert curve.x_shift==0;np.testing.assert_array_equal(curve.dataset.values,original[curve.uid])
    ui.curves[0].visible=False;ui.redraw();assert ui.display_x_offset(ui.curves[1])==7.5
    dialog=ui.show_overlay_options();first=dialog.axis_curves()[0];dialog.move_curve(first,"bottom");dialog.accept()
    members=ui._document_curves(ui.active_document());axis0=[c for c in members if c.axis==0]
    assert [ui.display_x_offset(c) for c in axis0]==[0,7.5]
    assert axis0[0].uid!=first.uid


def test_shifted_signal_max_drag_confirm_and_labels_keep_physical_temperature(ui,tmp_path):
    imported(ui,tmp_path,3);curve=ui.selected();uid=curve.uid;spacing(ui,[12,0,0,0]);curve=ui.selected()
    pending=ui.start_point_measurement("signal_max");editor=next(e for e in ui._measurement_artists if e.entry is pending)
    assert editor.display_x_offset==24 and pending["values"]["max_x"]==102
    assert editor.annotation.get_text()=="102.00 °C" and editor.annotation.xy[0]==126
    ui.canvas.draw();start=editor.axis.transData.transform(editor.display_coords[0])
    ui.result_press(MouseEvent("button_press_event",ui.canvas,*start,button=1))
    target=editor.axis.transData.transform((104+24,3))
    ui.result_motion(MouseEvent("motion_notify_event",ui.canvas,*target,button=1));ui.result_release(SimpleNamespace())
    assert pending["values"]["max_x"]==104 and pending["interactive"]["indices"]==[4]
    ui.confirm_measurement();saved=deepcopy(ui.results[0]);assert ui.selected().uid==uid
    spacing(ui,[3,0,0,0]);assert ui.results[0]==saved
    editor=next(e for e in ui._measurement_artists if e.entry is ui.results[0])
    assert editor.display_x_offset==6 and editor.annotation.xy[0]==110 and editor.annotation.get_text()=="104.00 °C"


def test_exact_two_point_limits_nudge_and_data_window_use_unshifted_positions(ui,tmp_path):
    imported(ui,tmp_path,3);spacing(ui,[10,0,0,0]);curve=ui.selected();uid=curve.uid
    pending=ui.start_point_measurement("dimension_change");dialog=ui.edit_measurement_limits()
    dialog.fields[0].setText("101.25");dialog.fields[1].setText("104.75");dialog.accept()
    assert pending["values"]["T1"]==101.25 and pending["values"]["T2"]==104.75
    editor=next(e for e in ui._measurement_artists if e.entry is pending)
    before=editor.coords[0][0];editor.nudge(0,1);assert before<editor.coords[0][0]<102
    assert editor.temps[0].xy[0]==pytest.approx(editor.coords[0][0]+20)
    ui.cancel_measurement();pending=ui.graphic_range();dialog=ui.edit_measurement_limits()
    dialog.fields[0].setText("101.25");dialog.fields[1].setText("104.75");dialog.accept();ui.confirm_measurement()
    assert ui.selected().uid==uid and ui.selected().data_indices==[2,3,4] and not ui.results


def test_range_and_pick_point_convert_from_display_to_physical_bounds(ui,tmp_path):
    imported(ui,tmp_path,3);spacing(ui,[10,0,0,0]);curve=ui.selected()
    dialog=ui.signal_analysis_dialog("signal_change");dialog.pick_point(0)
    ui.analysis_click(SimpleNamespace(xdata=122.,button=1));assert dialog.bounds()[0]==102
    dialog.select_range();ui.range_selected(121.25,124.75)
    assert dialog.bounds()==(101.25,104.75) and ui.lo_box.value()==101.25
    dialog.reject();ui.analysis_box.setCurrentIndex(ui.analysis_box.findData("slope"));ui.run_analysis(bounds=(101,105))
    values=ui.results[-1]["values"];x,y=curve.xy(ui.domain);mask=(x>=101)&(x<=105)
    assert values["slope"]==pytest.approx(np.polyfit(x[mask],y[mask],1)[0])
    fit=next(line for line in ui.axes[0].lines if line.get_linestyle()=="--")
    np.testing.assert_allclose(fit.get_xdata(),[121,125])
    np.testing.assert_allclose(fit.get_ydata(),values["slope"]*np.array([101,105])+values["intercept"])


def test_csv_table_and_status_distinguish_display_spacing_from_source(ui,tmp_path):
    imported(ui,tmp_path,2);spacing(ui,[15,0,0,0]);curve=ui.selected();x,y=curve.xy(ui.domain)
    model=ui.table.model();n=len(curve.dataset.signals)
    assert model.data(model.index(0,1))=="100" and model.data(model.index(0,n))=="115"
    assert DataModel(curve,ui.domain).data(model.index(0,n))=="100"
    ui.cursor_motion(SimpleNamespace(xdata=117.));assert "X 102" in ui.statusBar().currentMessage()
    path=tmp_path/"spaced.csv";ui.write_data(path,curve)
    rows=list(csv.reader(path.read_text(encoding="utf-8-sig").splitlines()))
    assert float(rows[1][1])==100 and float(rows[1][-2])==115
    meta=json.loads((tmp_path/"spaced.csv.meta.json").read_text(encoding="utf-8"))
    assert meta["presentation"]=={"x_offset":15} and meta["transform"]["x_shift"]==0
    np.testing.assert_array_equal(curve.xy(ui.domain)[0],x)


def test_notes_anchor_once_and_copy_session_normal_views_preserve_spacing(ui,tmp_path,monkeypatch):
    imported(ui,tmp_path,2);spacing(ui,[8,0,0,0]);curve=ui.selected();source=ui.active_document()
    def accept_note(dialog):
        dialog.setTextValue("标记")
        return QInputDialog.DialogCode.Accepted
    monkeypatch.setattr(QInputDialog,"exec",accept_note)
    ui._context_point=ui.axes[0].transData.transform((111,2));ui.add_note();result=deepcopy(ui.results[-1])
    assert result["values"]["x"]==pytest.approx(103)
    note=next(annotation for entry,annotation in ui._result_annotations if entry is ui.results[-1]);assert note.xy[0]==pytest.approx(111)
    copy=ui.copy_overlay(source.key);spacing(ui,[-6,0,0,0]);assert ui.display_x_offset(ui.selected())==-6
    path=tmp_path/"spacing.tmas";save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    ui.close_all_documents();ui.restore_session(path)
    ui._show_document(source.key);selected=next(c for c in ui.curves if c.uid==curve.uid)
    assert ui.display_x_offset(selected)==8
    ui._show_document(copy.key);assert ui.display_x_offset(selected)==-6 and ui.results[-1]==result
    ui.show_normal();assert ui.display_x_offset(selected)==0


def test_axes_defaults_save_only_offsets_and_cancel_is_inert(ui,tmp_path):
    imported(ui,tmp_path,2);before=deepcopy(ui.plot_options)
    dialog=ui.show_overlay_options();dialog.tabs.setCurrentIndex(1)
    dialog.axis_x_offsets[0].setText("9.25");dialog.y_labels[0].setText("不要保存名称");dialog.save();dialog.reject()
    assert ui.plot_options==before
    stored=load_defaults("overlay")["options"]
    assert stored["axis_x_offsets"]==[9.25,0,0,0] and "y_labels" not in stored
    dialog=ui.show_overlay_options();dialog.tabs.setCurrentIndex(1);dialog.axis_x_offsets[0].setText("3");dialog.defaults()
    assert [field.text() for field in dialog.axis_x_offsets]==["0"]*4;dialog.reject()
    ui.close_all_documents();imported(ui,tmp_path,2)
    assert ui.plot_options[ui.active_document().key]["axis_x_offsets"]==[9.25,0,0,0]


@pytest.mark.parametrize("value",[[0,1,2],[0,True,0,0],[0,float("inf"),0,0],"1,2,3,4"])
def test_offset_metadata_strict_finite_four_axis_schema(value):
    with pytest.raises(ValueError):validate_plot_options({"axis_x_offsets":value})


def test_invalid_axes_input_does_not_partially_commit_style_or_spacing(ui,tmp_path):
    imported(ui,tmp_path,2);before=deepcopy(ui.plot_options);colors=[c.color for c in ui.curves]
    dialog=ui.show_overlay_options();dialog.draft[0].color="#ff0000";dialog.axis_x_offsets[0].setText("nan");dialog.accept()
    assert dialog.result()!=QDialog.DialogCode.Accepted and dialog.error.text()
    assert ui.plot_options==before and [c.color for c in ui.curves]==colors


def test_secondary_time_axis_maps_the_shifted_first_visible_curve(ui,tmp_path):
    imported(ui,tmp_path,2);spacing(ui,[10,0,0,0]);ui.curves[0].visible=False
    ui.plot_options[ui.active_document().key]["secondary_x"]=True;ui.redraw();ui.canvas.draw()
    axis=next(axis for axis in ui.figure.axes if axis.get_gid()=="tma-secondary-x")
    values=[]
    for tick,label in zip(axis.get_xticks(),axis.get_xticklabels()):
        if label.get_text():
            value=float(label.get_text());assert value==pytest.approx(tick-110);values.append(value)
    assert values and 0 in values


def test_fixed_temperature_label_drag_survives_changed_display_spacing(ui,tmp_path):
    from matplotlib.text import Text
    imported(ui,tmp_path,2);spacing(ui,[10,0,0,0]);ui.start_point_measurement("dimension_change");ui.confirm_measurement()
    result=ui.results[-1];values=deepcopy(result["values"]);editor=next(e for e in ui._measurement_artists if e.entry is result)
    ui.canvas.draw();box=Text.get_window_extent(editor.temps[0],ui.canvas.get_renderer());x,y=(box.x0+box.x1)/2,(box.y0+box.y1)/2
    for kind,px,py in (("button_press_event",x,y),("motion_notify_event",x+25,y+17),("button_release_event",x+25,y+17)):
        ui.canvas.callbacks.process(kind,MouseEvent(kind,ui.canvas,px,py,button=1))
    offset=deepcopy(result["annotation"]["label_offsets"]["t1"])
    spacing(ui,[20,0,0,0]);editor=next(e for e in ui._measurement_artists if e.entry is result)
    assert result["values"]==values and list(editor.temps[0].xyann)==offset
    assert editor.temps[0].xy[0]==pytest.approx(values["T1"]+20)


def test_physical_smoothing_ignores_display_spacing(ui,tmp_path):
    from tma_app.signal_processing import local_fit
    imported(ui,tmp_path,3);spacing(ui,[25,0,0,0]);curve=ui.selected();x=curve.x_values(ui.domain)
    dialog=ui.show_native_smooth();dialog.width_edit.setText("2");dialog.accept();assert dialog.result()==QDialog.DialogCode.Accepted
    np.testing.assert_allclose(curve.working,local_fit(x,curve.dataset.values[:,curve.y_index],2))
    np.testing.assert_allclose(line_for(ui,curve).get_xdata(),x+50)


def test_native_overlay_shell_axes_geometry_and_ten_visible_slots(ui,tmp_path):
    from PySide6.QtWidgets import QApplication,QGroupBox,QPushButton
    imported(ui,tmp_path,2);dialog=ui.show_overlay_options();QApplication.processEvents()
    assert (dialog.width(),dialog.height())==(640,440)
    assert dialog.tabs.geometry().getRect()==(1,0,638,381)
    for i,field in enumerate(dialog.axis_x_offsets):
        group=field.parentWidget();assert isinstance(group,QGroupBox)
        assert group.geometry().getRect()==(16,12+72*i,601,65)
        assert field.geometry().getRect()==(456,38,49,21)
        assert group.rect().contains(field.geometry())
    for name,left in (("OK",188),("Save",276),("Default",364),("Cancel",452),("Help",544)):
        button=dialog.findChild(QPushButton,name)
        assert button.geometry().getRect()==(left,410,81,25) and dialog.rect().contains(button.geometry())
    dialog.tabs.setCurrentIndex(0);QApplication.processEvents()
    assert dialog.table.rowViewportPosition(9)+dialog.table.rowHeight(9)<=dialog.table.viewport().height()
    dialog.reject()
