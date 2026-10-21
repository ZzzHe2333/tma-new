"""Native legend fields, source identity, normalized handles and mouse editing."""
from copy import deepcopy
import json
import zipfile
import numpy as np
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QCheckBox, QLineEdit, QApplication
from matplotlib.backend_bases import MouseEvent
from test_feature_ui import ui, imported, set_combo
from tma_app.classic_dialogs import OverlayOptionsDialog
from tma_app.workspace import default_plot_options, validate_plot_options, save_session, load_session
from tma_app.preferences import load_defaults


def captions(ui): return [t.get_text() for t in ui.axes[0].get_legend().get_texts()]


def choose(group, value):
    button = next(b for b in group.buttons() if b.property("handle") == value)
    button.click()


def test_curve_text_checkbox_only_controls_text_and_alias_never_changes_source(ui, tmp_path):
    imported(ui, tmp_path)
    source = ui.curves[0].dataset.path
    originals = ui.curves[0].dataset.values.copy()
    dialog = OverlayOptionsDialog(ui)
    alias = dialog.table.cellWidget(0, 5); assert not alias.isReadOnly()
    alias.setText("比较样品.001")
    text = dialog.table.cellWidget(0, 6).findChild(QLineEdit)
    assert text.text() == ui.curves[0].dataset.name[:32] and text.maxLength() == 32
    text.setText("sample " + "a"*100); assert len(text.text()) == 32
    dialog.table.cellWidget(0, 6).findChild(QCheckBox).setChecked(False)
    dialog.legend_boxes["legend_file"].setChecked(True); dialog.accept()
    assert captions(ui)[0] == "比较样品.001" and len(captions(ui)) == 2
    assert ui.curves[0].show_legend and not ui.curves[0].show_legend_text
    assert ui.curves[0].dataset.path == source
    np.testing.assert_array_equal(ui.curves[0].dataset.values, originals)
    path = tmp_path / "aliases.tmas"; save_session(path, ui.curves, ui.domain, ui.results, ui.plot_options)
    ui.close_all_documents(); ui.restore_session(path)
    assert ui.curves[0].display_filename == "比较样品.001" and captions(ui)[0] == "比较样品.001"


@pytest.mark.parametrize("horizontal,vertical", [(h,v) for h in ("left","center","right") for v in ("top","center","bottom")])
def test_all_nine_normalized_handles_position_actual_legend(ui, tmp_path, horizontal, vertical):
    imported(ui, tmp_path)
    dialog = OverlayOptionsDialog(ui); dialog.tabs.setCurrentIndex(3)
    dialog.legend_coordinates[0].setValue(.45); dialog.legend_coordinates[1].setValue(.55)
    choose(dialog.legend_handles["horizontal"], horizontal); choose(dialog.legend_handles["vertical"], vertical)
    dialog.accept(); ui.canvas.draw()
    bounds = ui.axes[0].get_legend().get_window_extent(ui.canvas.get_renderer())
    x = {"left": bounds.x0,"center":(bounds.x0+bounds.x1)/2,"right":bounds.x1}[horizontal]
    y = {"bottom":bounds.y0,"center":(bounds.y0+bounds.y1)/2,"top":bounds.y1}[vertical]
    np.testing.assert_allclose(ui.axes[0].transAxes.inverted().transform((x,y)), [.45,.55], atol=1e-8)
    assert ui.plot_options["__overlay__"]["legend_anchor"]["horizontal"] == horizontal


def test_legend_mouse_drag_stores_position_survives_resize_session_and_keeps_results(ui, tmp_path):
    imported(ui, tmp_path)
    ui.start_point_measurement("signal_max"); ui.confirm_measurement()
    result = deepcopy(ui.results)
    ui.canvas.draw(); legend = ui.axes[0].get_legend()
    bounds = legend.get_window_extent(ui.canvas.get_renderer())
    x,y = (bounds.x0+bounds.x1)/2, (bounds.y0+bounds.y1)/2
    for kind,px,py in (("button_press_event",x,y),("motion_notify_event",x-65,y-45),("button_release_event",x-65,y-45)):
        ui.canvas.callbacks.process(kind, MouseEvent(kind,ui.canvas,px,py,button=1))
    anchor = deepcopy(ui.plot_options["__overlay__"]["legend_anchor"])
    assert anchor is not None and anchor["x"] < 1 and anchor["y"] < 1
    assert ui.results == result
    ui.resize(1280,800); QApplication.processEvents(); ui.redraw(); ui.canvas.draw()
    assert ui.plot_options["__overlay__"]["legend_anchor"] == anchor
    save_session(tmp_path/"drag.tmas",ui.curves,ui.domain,ui.results,ui.plot_options)
    ui.close_all_documents(); ui.restore_session(tmp_path/"drag.tmas")
    assert ui.plot_options["__overlay__"]["legend_anchor"] == anchor and ui.results == result


def test_legend_cancel_default_save_scope_and_invalid_input(ui, tmp_path):
    imported(ui,tmp_path)
    before = deepcopy(ui.plot_options)
    dialog = OverlayOptionsDialog(ui); dialog.table.cellWidget(0,5).setText("discard")
    dialog.legend_coordinates[0].setValue(.3); dialog.reject()
    assert ui.curves[0].display_filename != "discard" and ui.plot_options == before
    dialog = OverlayOptionsDialog(ui); dialog.tabs.setCurrentIndex(3)
    dialog.title.setText("do not save another page")
    dialog.legend_coordinates[0].setValue(.35); dialog.save()
    assert load_defaults("overlay")["options"]["legend_anchor"]["x"] == .35
    assert "window_name" not in load_defaults("overlay")["options"]
    dialog.defaults(); assert dialog.legend_location.currentData() == "best"
    assert dialog.title.text() == "do not save another page"
    dialog.accept(); assert ui.plot_options["__overlay__"]["legend_anchor"] is None


def test_legend_right_click_opens_options_but_pending_selection_suppresses_it(ui,tmp_path,monkeypatch):
    imported(ui,tmp_path); ui.canvas.draw(); doc=ui.mdi.activeSubWindow()
    box=ui.axes[0].get_legend().get_window_extent(ui.canvas.get_renderer())
    point=QPoint(round((box.x0+box.x1)/2),round(ui.canvas.height()-(box.y0+box.y1)/2))
    calls=[]; monkeypatch.setattr(ui,"edit_legend_options",lambda:calls.append(True))
    ui.show_plot_context_menu(doc,point); assert calls == [True]
    ui.start_point_measurement("dimension_change")
    from types import SimpleNamespace
    menu_calls=[]
    monkeypatch.setattr(ui,"create_measurement_menu",lambda:SimpleNamespace(exec=lambda *args:menu_calls.append(True),deleteLater=lambda:None))
    ui.show_plot_context_menu(doc,point); assert calls == [True]
    assert menu_calls == [True] and ui.current_measurement() is not None


def test_legacy_hidden_entry_and_empty_filename_fallback_survive_migration(ui,tmp_path):
    imported(ui,tmp_path); ui.curves[0].show_legend=False; ui.curves[1].legend_text=""
    path=tmp_path/"old.tmas"; save_session(path,ui.curves,ui.domain,[],ui.plot_options)
    with zipfile.ZipFile(path) as archive: contents={n:archive.read(n) for n in archive.namelist()}
    document=json.loads(contents["session.json"])
    for curve in document["curves"]:
        curve.pop("display_filename");curve.pop("show_legend_text")
    contents["session.json"]=json.dumps(document).encode()
    with zipfile.ZipFile(path,"w") as archive:
        for name,data in contents.items():archive.writestr(name,data)
    ui.close_all_documents();ui.restore_session(path)
    assert len(captions(ui))==1 and captions(ui)[0]==ui.curves[1].dataset.path.name
    assert not ui.curves[0].show_legend


def test_duplicate_custom_text_keeps_each_curve_style_and_order(ui,tmp_path):
    imported(ui,tmp_path)
    for curve,color,style in zip(ui.curves,["#ff0000","#0000ff"],["long_dash",":"]):
        curve.legend_text="same label";curve.color=color;curve.style=style
    ui.curves[0].axis=1
    ui.redraw();ui.canvas.draw()
    legend=ui.axes[0].get_legend()
    assert captions(ui)==["same label","same label"]
    assert [line.get_color() for line in legend.get_lines()]==["#ff0000","#0000ff"]
    assert [line.get_linestyle() for line in legend.get_lines()]==["--",":"]


@pytest.mark.parametrize("anchor", [False,{}, {"x":True,"y":.5,"horizontal":"left","vertical":"top"},
    {"x":float("nan"),"y":.5,"horizontal":"left","vertical":"top"},
    {"x":1.1,"y":.5,"horizontal":"left","vertical":"top"},
    {"x":.5,"y":.5,"horizontal":"other","vertical":"top"}])
def test_invalid_legend_anchor_rejected(anchor):
    with pytest.raises(ValueError):validate_plot_options({"legend_anchor":anchor})
