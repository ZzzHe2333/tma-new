"""Independent presentation windows referencing shared source/processing state."""
from copy import deepcopy
import json,zipfile
import numpy as np
import pytest
from PySide6.QtWidgets import QDialog,QInputDialog
from test_feature_ui import ui,imported
from tma_app.classic_dialogs import OverlayOptionsDialog
from tma_app.workspace import save_session,load_session,validate_plot_options
from tma_app.overlay_views import snapshot,validate_views


def activate(ui,key):
    ui.mdi.setActiveSubWindow(ui.documents[key]);ui.document_activated(ui.documents[key])


def test_copy_has_independent_axis_styles_members_aliases_offsets_and_options(ui,tmp_path):
    imported(ui,tmp_path,3);first=ui.active_document();curve=ui.curves[0];uid=curve.uid
    curve.color="#ff0000";curve.axis=1;curve.overlay_offset=20;curve.legend_text="原叠图";curve.display_filename="源别名"
    settings=ui.plot_options[first.key];settings.update(window_name="叠图A",export_title="报告A",legend_anchor={"x":.4,"y":.7,"horizontal":"center","vertical":"center"})
    ui.redraw();before=snapshot(curve);original_uids=list(first.curve_uids)
    second=ui.copy_overlay(first.key)
    assert second.key!=first.key and second.curve_uids==original_uids
    assert snapshot(curve)==before and ui.plot_options[second.key]["export_title"]=="报告A"
    assert ui.plot_options[second.key]["window_name"]=="叠图A 副本"
    dialog=ui.show_overlay_options();candidate=next(c for c in dialog.draft if c.uid==uid)
    candidate.color="#0000ff";candidate.axis=2;candidate.overlay_offset=5;candidate.legend_text="副本";candidate.display_filename="副本别名"
    dialog.draft[-1].overlay_enabled=False;dialog.populate();dialog.title.setText("报告B");dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted
    curve=next(c for c in ui.curves if c.uid==uid);assert curve.axis==2 and curve.overlay_offset==5 and len(ui.visible_curves())==2
    second_state=snapshot(curve)
    activate(ui,first.key);curve=next(c for c in ui.curves if c.uid==uid)
    assert snapshot(curve)==before and len(ui.visible_curves())==3 and first.curve_uids==original_uids
    assert ui.plot_options[first.key]["export_title"]=="报告A"
    activate(ui,second.key);assert snapshot(curve)==second_state and len(ui.visible_curves())==2
    ui.show_normal();assert curve.axis==0 and curve.color=="#000000" and curve.overlay_offset==5
    assert curve.legend_text!="副本" and curve.display_filename!="副本别名"


def test_copy_inactive_overlay_uses_that_sources_order_and_state(ui,tmp_path):
    imported(ui,tmp_path,3);first=ui.active_document();uid=ui.curves[0].uid
    dialog=ui.show_overlay_options();dialog.move_curve(dialog.axis_curves()[0],"bottom");dialog.accept()
    first_order=list(first.curve_uids);next(c for c in ui.curves if c.uid==uid).color="#ff0000"
    second=ui.copy_overlay(first.key);next(c for c in ui.curves if c.uid==uid).color="#0000ff"
    third=ui.copy_overlay(first.key)
    assert third.curve_uids==first_order and next(c for c in ui.curves if c.uid==uid).color=="#ff0000"
    activate(ui,second.key);assert next(c for c in ui.curves if c.uid==uid).color=="#0000ff"
    activate(ui,third.key)
    dialog=ui.show_overlay_options();assert [c.uid for c in dialog.axis_curves()]==first_order;dialog.reject()


def test_cancel_copy_and_options_have_no_snapshot_side_effects(ui,tmp_path,monkeypatch):
    imported(ui,tmp_path,2);first=ui.active_document();ui.copy_overlay(first.key);ui.show_normal()
    before=[deepcopy(c.overlay_views) for c in ui.curves];keys=list(ui.documents);options=deepcopy(ui.plot_options)
    dialog=ui.show_overlay_options();dialog.draft[0].color="#ff0000";dialog.reject()
    assert [c.overlay_views for c in ui.curves]==before and ui.plot_options==options and list(ui.documents)==keys
    monkeypatch.setattr(QInputDialog,"getItem",lambda *a,**k:("",False))
    assert ui.copy_overlay() is None and list(ui.documents)==keys


def test_native_copy_menu_chooses_a_window_instead_of_copying_image(ui,tmp_path,monkeypatch):
    imported(ui,tmp_path,2);first=ui.active_document();ui.curves[0].color="#ff0000"
    second=ui.copy_overlay(first.key);ui.curves[0].color="#0000ff"
    monkeypatch.setattr(QInputDialog,"getItem",lambda *args:(_ for _ in ()).throw(AssertionError("native Copy is a submenu")))
    menu=ui.classic_actions["Copy4"].menu();menu.aboutToShow.emit()
    choices=[a for a in menu.actions() if a.isVisible()]
    assert len(choices)==2 and choices[0].text().startswith("1. ") and "__overlay__" not in choices[0].text()
    assert choices[1].isChecked() and not choices[0].isChecked()
    choices[0].trigger()
    assert ui.active_document().key not in (first.key,second.key) and ui.curves[0].color=="#ff0000"


def test_empty_and_hidden_overlays_stay_empty_or_hidden_after_session_restore(ui,tmp_path):
    imported(ui,tmp_path,2);first=ui.active_document();uid=ui.curves[0].uid
    ui.curves[0].visible=False;second=ui.copy_overlay(first.key)
    assert first.curve_uids==second.curve_uids and len(ui.visible_curves())==1
    dialog=ui.show_overlay_options();dialog.delete_all();dialog.accept()
    assert second.curve_uids==[] and ui.visible_curves()==[]
    path=tmp_path/"two.tmas";save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    ui.close_all_documents();ui.restore_session(path)
    assert set(key for key in ui.documents if ui._is_overlay(key))=={first.key,second.key}
    activate(ui,second.key);assert ui.visible_curves()==[] and ui.documents[second.key].curve_uids==[]
    activate(ui,first.key);assert len(ui.visible_curves())==1 and not next(c for c in ui.curves if c.uid==uid).visible
    ui.show_normal();assert all(c.visible for c in ui.curves)


def test_closing_overlay_discards_only_it_and_closing_source_prunes_both(ui,tmp_path):
    imported(ui,tmp_path,3);first=ui.active_document();second=ui.copy_overlay(first.key);third=ui.copy_overlay(first.key)
    ui.close_active_document();assert third.key not in ui.documents and third.key not in ui.plot_options
    assert all(third.key not in c.overlay_views for c in ui.curves)
    source=ui.curves[0];uid=source.uid;activate(ui,str(source.dataset.path));ui.close_active_document()
    for key in (first.key,second.key):
        assert uid not in ui.documents[key].curve_uids and uid not in ui.plot_options[key]["overlay_members"]
        activate(ui,key);assert len(ui.visible_curves())==2
    assert len(ui.curves)==2


def test_auto_configure_of_copy_does_not_change_source_presentation(ui,tmp_path):
    imported(ui,tmp_path,2);first=ui.active_document();ui.curves[0].color="#ff0000";before=snapshot(ui.curves[0])
    second=ui.copy_overlay(first.key);dialog=ui.auto_configure_overlay();dialog.auto_boxes["color"].setChecked(True);dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted and ui.active_document() is second
    activate(ui,first.key);assert snapshot(ui.curves[0])==before


def test_shared_processing_does_not_overwrite_other_overlay_style_during_undo(ui,tmp_path):
    imported(ui,tmp_path,1);first=ui.active_document();curve=ui.curves[0];curve.overlay_offset=10
    second=ui.copy_overlay(first.key);curve.overlay_offset=30;curve.checkpoint();curve.overlay_offset=35
    activate(ui,first.key);assert curve.overlay_offset==10
    curve.undo();assert curve.overlay_offset==10
    activate(ui,second.key);assert curve.overlay_offset==30
    # Data/processing remain explicitly shared; presentation isolation does not
    # silently clone, re-read or alter measured arrays.
    raw=curve.dataset.values.copy();ui.process("derivative");working=curve.working.copy()
    activate(ui,first.key);np.testing.assert_array_equal(curve.working,working)
    np.testing.assert_array_equal(curve.dataset.values,raw)


def test_auto_configuration_reads_normal_axes_while_overlay_axes_remain_local(ui,tmp_path):
    imported(ui,tmp_path,2);ui.show_normal();ui.curves[1].axis=1;ui.show_overlay();source=ui.active_document()
    ui.curves[1].axis=2
    dialog=ui.auto_configure_overlay();dialog.signal_boxes[1].setChecked(False);dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted and len(ui.visible_curves())==1
    # The newly configured current overlay uses the source's ordinary axis1
    # selection, even though its preceding local presentation placed it onY3.
    assert ui.curves[1].normal_view_details["axis"]==1 and not ui.curves[1].overlay_enabled


@pytest.mark.parametrize("mutation",[lambda s:s.update(axis=True),lambda s:s.update(color="red"),lambda s:s.update(offset=float("nan")),lambda s:s.update(width=0),lambda s:s.update(visible=1),lambda s:s.pop("marker")])
def test_view_metadata_is_strict_inert_data(ui,tmp_path,mutation):
    imported(ui,tmp_path,1);curve=ui.curves[0];state=snapshot(curve);mutation(state)
    with pytest.raises(ValueError):validate_views({"__overlay__":state})


def test_membership_schema_rejects_duplicates_and_nonexistent_uids(ui,tmp_path):
    with pytest.raises(ValueError):validate_plot_options({"overlay_members":["a"*32,"a"*32]})
    imported(ui,tmp_path,1);path=tmp_path/"bad.tmas"
    save_session(path,ui.curves,ui.domain,[],ui.plot_options)
    with zipfile.ZipFile(path) as source:
        entries={name:source.read(name) for name in source.namelist()}
    name=next(name for name in entries if name.endswith(".json"));document=json.loads(entries[name])
    document["plot_options"]["__overlay__"]["overlay_members"]=["a"*32]
    entries[name]=json.dumps(document).encode()
    with zipfile.ZipFile(path,"w") as dest:
        for name,data in entries.items():dest.writestr(name,data)
    with pytest.raises(ValueError):load_session(path)


def test_documented_twenty_overlay_limit_blocks_creation_but_allows_editing(ui,tmp_path):
    imported(ui,tmp_path,1);original=ui.active_document()
    for i in range(2,21):ui._document(f"__overlay__:{i}")
    assert sum(ui._is_overlay(key) for key in ui.documents)==20
    keys=list(ui.documents)
    assert ui.copy_overlay(original.key) is None and ui.show_overlay() is None
    assert list(ui.documents)==keys and "20" in ui.statusBar().currentMessage()
    dialog=ui.show_overlay_options();assert dialog.key==original.key;dialog.reject()
    ui.show_normal();assert ui.show_overlay_options() is None and ui.auto_configure_overlay() is None
    assert list(ui.documents)==keys
