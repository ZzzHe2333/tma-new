"""Native Save and Default act on settings pages, separately from sessions."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from PySide6.QtWidgets import QApplication
from test_point_interaction import ui
from tma_app.classic_dialogs import OverlayOptionsDialog
from tma_app.preferences import load_defaults, preferences_path
from tma_app.workspace import save_session


def test_graph_save_defaults_does_not_open_session_dialog_or_mutate_current_graph(ui):
    ui.save = lambda: (_ for _ in ()).throw(AssertionError("Save must not save a session"))
    old = ui.curves[0].color
    ui.dirty = False
    graph = ui.show_curve_options()
    graph.color.setCurrentIndex(graph.color.findData("#ff0000"))
    graph.x_name.setText("current name")
    graph.save()
    assert ui.curves[0].color == old
    assert not ui.dirty
    saved = load_defaults("graph")
    assert saved["curves"][0][0]["color"] == "#ff0000"
    assert "x_label" not in saved["options"]
    graph.reject()
    source = ui.curves[0].dataset
    second = replace(source, path=source.path.with_name("next.002"))
    ui.finish_import([second], []); QApplication.processEvents()
    assert ui.selected().dataset is second and ui.selected().color == "#ff0000"


def test_overlay_save_only_the_active_page_and_default_only_resets_that_page(ui):
    ui.show_overlay()
    ui.save = lambda: (_ for _ in ()).throw(AssertionError("Save must not save a session"))
    dialog = OverlayOptionsDialog(ui)
    unsaved_title = "unsaved title"
    dialog.title.setText(unsaved_title)
    dialog.export_heading.setPlainText("too many lines\n"*5)
    dialog.legend_boxes["legend_border"].setChecked(True)
    dialog.grid_boxes["grid_x"].setChecked(True)
    # Invalid edits on another page do not prevent saving this valid page.
    dialog.tabs.setCurrentIndex(3); dialog.save()
    saved = load_defaults("overlay")["options"]
    assert saved["legend_border"] is True
    assert "title" not in saved and "grid_x" not in saved and "auto_x" not in saved
    dialog.defaults()
    assert not dialog.legend_boxes["legend_border"].isChecked()
    assert dialog.title.text() == unsaved_title and dialog.grid_boxes["grid_x"].isChecked()
    assert load_defaults("overlay")["options"]["legend_border"] is True
    dialog.reject()


def test_curve_defaults_load_for_a_new_overlay_without_saving_file_identity(ui):
    ui.show_overlay()
    dialog = OverlayOptionsDialog(ui)
    dialog.draft[0].color = "#0000ff"; dialog.draft[0].offset = 8
    dialog.tabs.setCurrentIndex(0); dialog.save(); dialog.reject()
    assert "point.001" not in preferences_path().read_text(encoding="utf-8")
    source = ui.curves[0].dataset
    ui.close_all_documents(); ui.finish_import([replace(source, path=source.path.with_name("different.005"))], [])
    ui.show_overlay()
    assert ui.curves[0].color == "#0000ff" and ui.curves[0].offset == 8


def test_user_defaults_never_replace_restored_session_appearance(ui, tmp_path):
    ui.curves[0].color = "#008000"
    session = tmp_path / "appearance.tmas"
    save_session(session, ui.curves, ui.domain, ui.results)
    graph = ui.show_curve_options()
    graph.color.setCurrentIndex(graph.color.findData("#ff0000")); graph.save(); graph.reject()
    ui.close_all_documents(); ui.restore_session(session)
    assert ui.curves[0].color == "#008000"


def test_invalid_preference_file_is_preserved_and_reported(ui):
    target = preferences_path(); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("not valid json", encoding="utf-8")
    before = deepcopy(ui.plot_options)
    graph = ui.show_curve_options(); graph.save()
    assert graph.error.text() and target.read_text(encoding="utf-8") == "not valid json"
    graph.reject()
    assert ui.plot_options == before
