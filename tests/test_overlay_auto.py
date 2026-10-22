"""Native overlay sequences, independent view styles, defaults and output heading."""
from copy import deepcopy
from dataclasses import replace
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import Qt
from test_feature_ui import ui, imported, set_combo
from tma_app.classic_dialogs import OverlayOptionsDialog, AddCurvesDialog
from tma_app.auto_configure import AutoConfigureDialog
from tma_app.overlay_settings import default_auto_styles, validate_auto_styles, offset_step
from tma_app.preferences import load_defaults
from tma_app.workspace import save_session, load_session, validate_plot_options


def rescale(ui, values):
    dialog = ui.manual_rescale(0)
    for field, value in zip(dialog.fields[0], values): field.setText(str(value))
    dialog.accept(); assert dialog.result() == QDialog.DialogCode.Accepted


def test_ten_sequence_editors_drive_actual_curves_and_survive_view_switch_and_session(ui, tmp_path):
    imported(ui, tmp_path, 3)
    originals = [c.dataset.values.copy() for c in ui.curves]
    dialog = OverlayOptionsDialog(ui)
    assert len(dialog.auto_page.lines) == len(dialog.auto_page.colors) == len(dialog.auto_page.symbols) == 10
    set_combo(dialog.auto_page.lines[0], "long_dash")
    set_combo(dialog.auto_page.colors[0], "#0000ff")
    set_combo(dialog.auto_page.symbols[0], "D")
    dialog.auto_lines(); dialog.auto_colors(); dialog.auto_symbols()
    assert ui.curves[0].style == "-" and ui.curves[0].color == "#000000"
    dialog.accept(); assert dialog.result() == QDialog.DialogCode.Accepted
    assert (ui.curves[0].style, ui.curves[0].color, ui.curves[0].marker) == ("long_dash", "#0000ff", "D")
    ui.show_normal()
    assert (ui.curves[0].style, ui.curves[0].color, ui.curves[0].marker) == ("-", "#000000", "")
    ui.show_overlay()
    assert ui.curves[0].color == "#0000ff"
    session = tmp_path / "sequences.tmas"
    save_session(session, ui.curves, ui.domain, ui.results, ui.plot_options)
    ui.close_all_documents(); ui.restore_session(session)
    assert ui.plot_options["__overlay__"]["overlay_auto"]["lines"][0] == "long_dash"
    assert ui.curves[0].marker == "D"
    ui.show_normal(); assert ui.curves[0].color == "#000000"
    for curve, original in zip(ui.curves, originals): np.testing.assert_array_equal(curve.dataset.values, original)


def test_offsets_use_real_minor_spacing_half_percent_sign_and_start_at_zero(ui, tmp_path):
    imported(ui, tmp_path, 3); rescale(ui, [0, 20, 5, 4, 0])
    dialog = OverlayOptionsDialog(ui)
    dialog.auto_page.offset_modes.button(1).setChecked(True); dialog.auto_offsets()
    assert [c.overlay_offset for c in dialog.draft] == [0, 4, 8]
    dialog.auto_page.offset_modes.button(2).setChecked(True); dialog.auto_page.negative.setChecked(True); dialog.auto_offsets()
    assert [c.overlay_offset for c in dialog.draft] == [0, -2, -4]
    dialog.auto_page.offset_modes.button(3).setChecked(True); dialog.auto_page.percent.setValue(25); dialog.auto_offsets()
    assert [c.overlay_offset for c in dialog.draft] == [0, -5, -10]
    assert all(c.overlay_offset == 0 for c in ui.curves)
    dialog.reject()


def test_overlay_offsets_add_to_normal_shifts_without_changing_them(ui, tmp_path):
    imported(ui, tmp_path)
    ui.show_normal(); ui.curves[0].offset = 7; ui.curves[1].offset = 3
    ui.show_overlay(); rescale(ui, [0, 100, 20, 5, 0])
    dialog = OverlayOptionsDialog(ui)
    dialog.auto_page.offset_modes.button(3).setChecked(True); dialog.auto_page.percent.setValue(10)
    dialog.auto_offsets(); dialog.accept()
    assert [c.offset for c in ui.curves] == [7, 13]
    assert [c.overlay_offset for c in ui.curves] == [0, 10]
    ui.show_normal(); assert [c.offset for c in ui.curves] == [7, 3]
    ui.curves[0].offset = 11
    ui.show_overlay(); assert [c.offset for c in ui.curves] == [11, 13]


def test_auto_configure_respects_original_axes_and_per_axis_or_curve_sequences(ui, tmp_path):
    imported(ui, tmp_path, 4)
    ui.show_normal()
    for curve, axis, marker in zip(ui.curves, [0, 0, 1, 1], ["o", "s", "^", "D"]): curve.axis = axis; curve.marker = marker
    ui.show_overlay()
    uid = ui.selected().uid
    dialog = ui.auto_configure_overlay()
    assert isinstance(dialog, AutoConfigureDialog)
    dialog.mode_groups["line"].button(0).setChecked(True)
    dialog.mode_groups["color"].button(1).setChecked(True)
    dialog.auto_boxes["symbol"].setChecked(False)
    dialog.accept(); assert not dialog.error.text()
    assert [c.axis for c in ui.curves] == [0, 0, 1, 1]
    assert [c.style for c in ui.curves] == ["-", "-", "--", "--"]
    assert [c.color for c in ui.curves] == ["#000000", "#ff0000", "#000000", "#ff0000"]
    assert [c.marker for c in ui.curves] == ["o", "s", "^", "D"]
    assert ui.selected().uid == uid
    assert any(artist.get_gid() == "tma-axis-style-1" for artist in ui.figure.artists)
    ui.show_normal()
    assert all(c.color == "#000000" and c.style == "-" for c in ui.curves)


def test_unchecked_automatic_styles_use_normal_graph_styles_not_previous_overlay(ui, tmp_path):
    imported(ui, tmp_path)
    ui.curves[0].color = "#ff0000"; ui.curves[0].overlay_offset = 20
    dialog = AutoConfigureDialog(ui)
    for key in ("line", "color", "symbol", "offset"): dialog.auto_boxes[key].setChecked(False)
    dialog.accept()
    assert ui.curves[0].color == "#000000" and ui.curves[0].overlay_offset == 0


def test_file_and_signal_selection_are_effective_and_duplicate_signal_is_used_once(ui, tmp_path):
    imported(ui, tmp_path, 3)
    ui.show_normal()
    ui.curves[1].axis = 1
    duplicate = replace(ui.curves[0], uid="a"*32)
    ui.curves.append(duplicate); ui.rebuild_files()
    dialog = AutoConfigureDialog(ui)
    dialog.file_items[2].setCheckState(Qt.CheckState.Unchecked)
    dialog.signal_boxes[1].setChecked(False); dialog.accept()
    visible = ui.visible_curves()
    assert len(visible) == 1 and visible[0].dataset.path == ui.curves[0].dataset.path
    assert len(ui.curves) == 4 and all(str(c.dataset.path) in ui.documents for c in ui.curves)


def test_configure_cancel_and_invalid_units_never_partially_commit(ui, tmp_path):
    imported(ui, tmp_path)
    before = [(c.color, c.style, c.overlay_enabled, c.appearance_mode) for c in ui.curves]
    options = deepcopy(ui.plot_options)
    dialog = AutoConfigureDialog(ui); dialog.auto_boxes["symbol"].setChecked(True); dialog.reject()
    assert [(c.color, c.style, c.overlay_enabled, c.appearance_mode) for c in ui.curves] == before
    assert ui.plot_options == options
    ui.curves[1].y_index = 1
    dialog = AutoConfigureDialog(ui); dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted and "单位" in dialog.error.text()
    assert [(c.color, c.style, c.overlay_enabled, c.appearance_mode) for c in ui.curves] == before


def test_same_units_different_names_are_compatible_and_first_name_labels_axis(ui, tmp_path):
    from tma_app.reader import Signal
    imported(ui, tmp_path)
    ui.curves[1].dataset.signals[2] = Signal("Other dimension", "μm")
    options = OverlayOptionsDialog(ui); options.accept()
    assert options.result() == QDialog.DialogCode.Accepted and len(ui._plot_artists) == 2
    assert "尺寸变化" in ui.axes[0].get_ylabel()
    additions = AddCurvesDialog(ui, ui.curves, 0)
    additions.files.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert any(additions.signals.item(i).text().startswith("Other dimension") for i in range(additions.signals.count()))
    additions.reject()


def test_auto_defaults_persist_page_only_and_export_heading_never_changes_screen(ui, tmp_path):
    imported(ui, tmp_path)
    original_title = [text.get_text() for text in ui.figure.texts]
    dialog = AutoConfigureDialog(ui)
    dialog.heading.setPlainText("仅用于打印和导出的标题")
    dialog.save()
    assert load_defaults("overlay")["options"]["overlay_configure"]["heading"].startswith("仅用于")
    assert [text.get_text() for text in ui.figure.texts] == original_title
    dialog.accept()
    screen = [text.get_text() for text in ui.figure.texts]
    assert "仅用于打印和导出的标题" not in screen
    path = tmp_path / "plot.svg"; ui.write_plot(path)
    assert "仅用于打印和导出的标题" in path.read_text(encoding="utf-8")
    assert "Power By ZzzHe" in path.read_text(encoding="utf-8")
    assert [text.get_text() for text in ui.figure.texts] == screen
    with pytest.raises(ValueError): ui.write_plot(tmp_path / "plot.unknown")
    assert [text.get_text() for text in ui.figure.texts] == screen
    ui.show_normal(); path = tmp_path / "normal.svg"; ui.write_plot(path)
    assert "仅用于打印和导出的标题" not in path.read_text(encoding="utf-8")


def test_undo_on_another_view_preserves_overlay_additional_offset(ui, tmp_path):
    imported(ui, tmp_path, 1); ui.show_normal(); curve = ui.curves[0]
    curve.offset = 4; curve.checkpoint(); curve.offset = 9
    curve.activate_appearance("overlay"); curve.overlay_offset = 10
    curve.working = np.ones(len(curve.dataset.values)); curve.operations.append("smooth:3")
    curve.undo()
    assert curve.working is None and curve.overlay_offset == 10 and curve.offset == 14
    curve.activate_appearance("normal"); assert curve.offset == 4


@pytest.mark.parametrize("change", [{"lines": ["-"]}, {"colors": ["red"]*10}, {"symbols": ["bad"]*10}, {"offset_percent": float('nan')}, {"offset_percent": True}, {"offset_negative": 1}, {"offset_method": "bad"}])
def test_invalid_sequences_rejected_by_workspace_and_preferences(change, tmp_path):
    from tma_app.preferences import save_defaults
    with pytest.raises(ValueError): validate_plot_options({"overlay_auto": change})
    with pytest.raises(ValueError): save_defaults("overlay", "auto", {"overlay_auto": change}, path=tmp_path / "prefs.json")


def test_offset_methods_and_default_lists_are_independent():
    first, second = default_auto_styles(), default_auto_styles()
    first["colors"][0] = "#123456"; assert second["colors"][0] == "#000000"
    for method, expected in (("major", 20), ("minor", 4), ("half", 2), ("percent", 10)):
        value = validate_auto_styles({"offset_method": method})
        assert offset_step(value, 0, 100, 20, 4) == expected


def test_auto_configure_keeps_derivative_and_raw_signal_on_separate_axes(ui, tmp_path):
    imported(ui, tmp_path, 1)
    ui.show_normal()
    derivative = replace(ui.curves[0], uid="b"*32, axis=1,
                         working=np.gradient(ui.curves[0].dataset.values[:, 2]), operations=["derivative:temperature"])
    ui.curves.append(derivative); ui.rebuild_files()
    dialog = AutoConfigureDialog(ui); dialog.accept()
    assert not dialog.error.text()
    assert len(ui.visible_curves()) == 2
    assert ui.curves[0].result_unit != ui.curves[1].result_unit


def test_auto_sequence_save_default_and_invalid_proposal_are_page_scoped(ui, tmp_path):
    imported(ui, tmp_path, 11)
    before = [(c.color, c.style, c.overlay_enabled) for c in ui.curves]
    dialog = AutoConfigureDialog(ui); dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert [(c.color, c.style, c.overlay_enabled) for c in ui.curves] == before
    options = OverlayOptionsDialog(ui); options.tabs.setCurrentIndex(5)
    options.title.setText("unsaved window name")
    set_combo(options.auto_page.colors[0], "#0000ff"); options.save()
    assert load_defaults("overlay")["options"]["overlay_auto"]["colors"][0] == "#0000ff"
    assert "window_name" not in load_defaults("overlay")["options"]
    options.defaults()
    assert options.title.text() == "unsaved window name"
    assert options.auto_page.colors[0].currentData() == "#000000"
    options.reject()
