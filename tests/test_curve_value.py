"""Native two-stage curve-value labeling with immutable source coordinates."""
from copy import deepcopy
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtWidgets import QDialog,QPushButton
from matplotlib.backend_bases import MouseEvent
from matplotlib.text import Text
from test_feature_ui import ui,imported
from tma_app.preferences import load_defaults
from tma_app.workspace import save_session,load_session
from tma_app.point_labels import default_options,validate_options,validate_signal


def limits(ui,x):
    dialog=ui.edit_measurement_limits();dialog.fields[0].setText(str(x));dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted,dialog.error.text()
    return dialog


def mark(ui):
    ui.create_measurement_menu().actions()[0].trigger()
    return ui.dialogs["label_point"]


def test_native_menu_has_two_stage_confirmation_and_preserves_third_document(ui,tmp_path):
    imported(ui,tmp_path,3);ui.show_normal();curve=ui.selected();uid=curve.uid;document=ui.active_document();ui.dirty=False
    assert ui.classic_actions["CurveValueAtX1"].isEnabled()
    ui.classic_actions["CurveValueAtX1"].trigger();entry=ui._pending_measurement
    assert entry["kind"]=="curve_value" and entry["values"]["x"]==103 and entry["values"]["y"]==4
    assert "max_x" not in entry["values"] and not ui.results and not ui.dirty
    dialog=mark(ui)
    assert ui._pending_measurement is entry and not ui.results
    assert dialog.objectName()=="LabelPointForm" and (dialog.width(),dialog.height())==(370,229)
    assert dialog.findChild(QPushButton,"OK").geometry().getRect()==(12,194,81,25)
    assert dialog.boxes["temperature"].isChecked() and dialog.boxes["y"].isChecked()
    assert not dialog.boxes["signal"].isEnabled() and not dialog.boxes["multiplex"].isEnabled()
    dialog.boxes["time"].setChecked(True);dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted and ui._pending_measurement is None
    assert ui.results==[entry] and ui.selected().uid==uid and ui.active_document() is document
    text=ui._measurement_artists[-1].annotation.get_text()
    assert "t = 3 min" in text and "T = 103.00 °C" in text and "Y = 4 µm" in text


def test_exact_x_interpolates_y_time_temperature_and_recorded_x_signal(ui,tmp_path):
    imported(ui,tmp_path,1);ui.show_normal();curve=ui.selected();curve.x_signal_index=0
    raw=curve.dataset.values.copy();entry=ui.start_point_measurement("curve_value")
    dialog=ui.edit_measurement_limits();assert dialog.y_fields[0].isReadOnly()
    dialog.fields[0].setText("101.25");dialog.y_fields[0].setText("999");dialog.accept()
    assert entry["values"]["y"]==pytest.approx(-2+.25*(9-(-2)))
    assert entry["values"]["time_at_point"]==1.25 and entry["values"]["temperature_at_point"]==101.25
    assert entry["values"]["signal_at_point"]==1.25 and entry["point_signal"]["index"]==0
    label=mark(ui);label.boxes["signal"].setChecked(True);label.accept();saved=deepcopy(ui.results[-1])
    curve.x_signal_index=2;ui.redraw()
    assert ui.results[-1]==saved and "Time (min) = 1.25" in ui._measurement_artists[-1].annotation.get_text()
    path=tmp_path/"value.tmas";save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    ui.close_all_documents();ui.restore_session(path)
    assert ui.results[-1]==saved and ui.results[-1]["point_signal"]["index"]==0
    np.testing.assert_array_equal(ui.curves[0].dataset.values,raw)


def test_point_styles_are_independent_and_label_can_drag_without_changing_values(ui,tmp_path):
    imported(ui,tmp_path,1);entry=ui.start_point_measurement("curve_value");dialog=mark(ui)
    dialog.boxes["arrow"].setChecked(False);dialog.boxes["cross"].setChecked(False)
    dialog.boxes["border"].setChecked(True);dialog.boxes["transparent"].setChecked(False);dialog.accept()
    editor=next(e for e in ui._measurement_artists if e.entry is entry)
    assert not editor.markers[0].get_visible() and not editor.annotation.arrow_patch.get_visible()
    box=editor.annotation.get_bbox_patch();assert box is not None and box.get_facecolor()[:3]==(1,1,1)
    values=deepcopy(entry["values"]);ui.canvas.draw();bounds=Text.get_window_extent(editor.annotation,ui.canvas.get_renderer())
    x,y=(bounds.x0+bounds.x1)/2,(bounds.y0+bounds.y1)/2
    for kind,px,py in (("button_press_event",x,y),("motion_notify_event",x+23,y+19),("button_release_event",x+23,y+19)):
        ui.canvas.callbacks.process(kind,MouseEvent(kind,ui.canvas,px,py,button=1))
    assert entry["values"]==values and "offset" in entry["annotation"]


def test_label_dialog_cancel_discards_new_draft_and_preserves_existing_edit(ui,tmp_path):
    imported(ui,tmp_path,2);ui.show_normal();uid=ui.selected().uid
    ui.start_point_measurement("curve_value");mark(ui).reject()
    assert not ui.results and ui._pending_measurement is None and ui.selected().uid==uid
    entry=ui.start_point_measurement("curve_value");mark(ui).accept();saved=deepcopy(entry)
    dialog=ui.edit_point_label(entry);dialog.boxes["temperature"].setChecked(False);dialog.boxes["y"].setChecked(False);dialog.reject()
    assert ui.results==[entry] and entry==saved and ui._pending_measurement is None
    menu=ui.create_result_context_menu(entry,ui._measurement_artists[-1].annotation)
    assert "标注选项…" in [action.text() for action in menu.actions()]


def test_saving_label_defaults_does_not_commit_point_or_change_other_preferences(ui,tmp_path):
    imported(ui,tmp_path,1);ui.dirty=False;before=deepcopy(ui.plot_options)
    ui.start_point_measurement("curve_value");dialog=mark(ui)
    dialog.boxes["time"].setChecked(True);dialog.boxes["temperature"].setChecked(False);dialog.boxes["cross"].setChecked(False)
    dialog.save();dialog.reject()
    saved=load_defaults("analysis")["options"]["point_label_options"]
    assert saved["time"] and not saved["temperature"] and not saved["cross"]
    assert not ui.results and not ui.dirty and ui.plot_options==before
    ui.start_point_measurement("curve_value");dialog=mark(ui)
    assert dialog.boxes["time"].isChecked() and not dialog.boxes["temperature"].isChecked();dialog.reject()


def test_label_options_do_not_change_signal_max_temperature_only_behavior(ui,tmp_path):
    imported(ui,tmp_path,1);ui.start_point_measurement("curve_value");dialog=mark(ui)
    dialog.boxes["time"].setChecked(True);dialog.save();dialog.reject()
    entry=ui.start_point_measurement("signal_max");ui.confirm_measurement()
    assert ui.results==[entry] and ui._pending_measurement is None
    assert ui._measurement_artists[-1].annotation.get_text()=="102.00 °C"


def test_hidden_other_document_enter_cannot_open_label_dialog(ui,tmp_path):
    imported(ui,tmp_path,3);ui.show_normal();entry=ui.start_point_measurement("curve_value");source=ui.active_document()
    other=next(doc for key,doc in ui.documents.items() if key!=source.key and not ui._is_overlay(key))
    ui.mdi.setActiveSubWindow(other);ui.document_activated(other)
    ui.measurement_key(SimpleNamespace(key="enter"));ui.confirm_measurement()
    assert ui._pending_measurement is entry and "label_point" not in ui.dialogs
    ui.mdi.setActiveSubWindow(source);ui.document_activated(source);mark(ui).accept()
    assert ui.results==[entry]


def test_shifted_point_uses_physical_input_and_preview_cross_remains_draggable(ui,tmp_path):
    imported(ui,tmp_path,2);options=ui.plot_options[ui.active_document().key];options["axis_x_offsets"][0]=15;ui.redraw()
    entry=ui.start_point_measurement("curve_value");limits(ui,101.25)
    editor=next(e for e in ui._measurement_artists if e.entry is entry)
    assert editor.coords[0][0]==101.25 and editor.display_coords[0][0]==116.25
    label=mark(ui);label.boxes["cross"].setChecked(False);label.accept()
    assert "101.25" in ui._measurement_artists[-1].annotation.get_text()
    ui.edit_measurement(entry);editor=next(e for e in ui._measurement_artists if e.entry is ui._pending_measurement)
    assert editor.markers[0].get_visible()
    editor.move(0,104);assert editor.entry["values"]["temperature_at_point"]==104
    ui.cancel_measurement();assert entry["values"]["temperature_at_point"]==101.25


def test_curve_value_manual_input_cannot_interpolate_across_excluded_rows(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.selected();curve.data_indices=[0,1,4,5]
    ui.start_point_measurement("curve_value");entry=ui._pending_measurement;before=deepcopy(entry["interactive"])
    dialog=ui.edit_measurement_limits();dialog.fields[0].setText("102.5");dialog.accept()
    assert dialog.result()!=QDialog.DialogCode.Accepted and dialog.error.text() and entry["interactive"]==before
    dialog.reject();ui.cancel_measurement()


def test_unavailable_label_channel_is_disabled_without_placeholder_numeric_values(ui,tmp_path):
    from pathlib import Path
    from tma_app.reader import Dataset,Signal
    dataset=Dataset(Path(tmp_path/"no-time.001"),[Signal("Temperature","°C"),Signal("Dimension Change","µm")],np.column_stack(([100.,101.,102.],[0.,3.,7.])),{},[],"no-time")
    ui.finish_import([dataset],[]);entry=ui.start_point_measurement("curve_value");dialog=mark(ui)
    assert not dialog.boxes["time"].isEnabled() and "time_at_point" not in entry["values"]
    dialog.reject()


def test_marker_only_point_remains_accessible_to_label_options(ui,tmp_path):
    imported(ui,tmp_path,1);entry=ui.start_point_measurement("curve_value");dialog=mark(ui)
    for key in ("time","temperature","signal","y","arrow"):dialog.boxes[key].setChecked(False)
    dialog.boxes["cross"].setChecked(True);dialog.accept()
    editor=ui._measurement_artists[-1];assert editor.annotation.get_text()=="" and editor.markers[0].get_visible()
    pixel=editor.axis.transData.transform(editor.display_coords[0])
    hit=ui.result_annotation_at(*pixel);assert hit is not None and hit[0] is entry
    menu=ui.create_result_context_menu(*hit)
    next(action for action in menu.actions() if action.text()=="标注选项…").trigger()
    assert ui.dialogs["label_point"].isVisible();ui.dialogs["label_point"].reject()


def test_unavailable_derived_label_signal_does_not_block_other_channel_values(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.selected();curve.data_indices=[0,1,2];curve.x_signal_index=2;curve.x_signal_type="d_time"
    entry=ui.start_point_measurement("curve_value");dialog=mark(ui)
    assert not dialog.boxes["signal"].isEnabled() and "signal_at_point" not in entry["values"]
    assert entry["values"]["label_signal_error"] and entry["values"]["temperature_at_point"]==101
    dialog.accept();assert ui.results==[entry]


@pytest.mark.parametrize("change",[{"y":1},{"time":"true"},{"multiplex":True}])
def test_label_options_reject_ambiguous_or_unsupported_flags(change):
    options=default_options();options.update(change)
    with pytest.raises(ValueError):validate_options(options)


def test_recorded_signal_definition_is_validated_when_loading_session(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.selected();curve.x_signal_index=0
    entry=ui.start_point_measurement("curve_value");mark(ui).accept()
    invalid=dict(entry["point_signal"],index=99)
    with pytest.raises(ValueError):validate_signal(invalid,curve.dataset)
    entry["point_signal"]=invalid;path=tmp_path/"invalid.tmas";save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    with pytest.raises(ValueError):load_session(path)
