"""Independent cursor editing, document isolation, persistence, and export flows."""
from copy import deepcopy

import numpy as np
import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog

from test_point_interaction import ui  # Reuse the actual single-document Qt fixture.
from tma_app.classic_dialogs import CursorLimitsDialog, OverlayOptionsDialog
from tma_app.reader import Dataset
from tma_app.workspace import save_session


def menu_action(menu, title):
    return next(action for action in menu.actions() if action.text() == title)


@pytest.mark.parametrize("file_index", [1, 2])
@pytest.mark.parametrize("confirm", [False, True])
def test_cursor_confirm_and_cancel_keep_second_or_third_document_active(ui, file_index, confirm):
    original = ui.curves[0].dataset
    extras = [Dataset(original.path.with_name(f"sample-{i}.00{i}"), original.signals,
                      original.values.copy(), original.metadata, [], f"source-{i}") for i in (2, 3)]
    ui.finish_import(extras, [])
    ui.files.setCurrentItem(ui.files.topLevelItem(file_index))
    ui.show_normal()
    selected = ui.curves[file_index]
    active_key = str(selected.dataset.path)
    assert ui.mdi.activeSubWindow().key == active_key
    ui.start_point_measurement("dimension_change")
    assert ui._pending_measurement["curve_id"] == selected.uid
    dialog = ui.edit_measurement_limits()
    dialog.fields[0].setText("103.25")
    dialog.fields[1].setText("106.4")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert ui.mdi.activeSubWindow().key == active_key
    assert ui.selected() is selected
    menu = ui.create_plot_context_menu()
    menu_action(menu, "确定" if confirm else "取消").trigger()
    assert ui._pending_measurement is None
    assert ui.mdi.activeSubWindow().key == active_key
    assert ui.selected() is selected
    assert [c.uid for c in ui.visible_curves()] == [selected.uid]
    assert len(ui.results) == int(confirm)
    if confirm:
        assert ui.results[0]["curve_id"] == selected.uid
        assert ui.results[0]["values"]["T1"] == pytest.approx(103.25)


def test_selecting_points_uses_dedicated_menu_without_normal_plot_commands(ui):
    normal = [a.text() for a in ui.create_plot_context_menu().actions()]
    assert "打开" in normal and "信号最大" in normal
    ui.start_point_measurement("dimension_change")
    menu = ui.create_plot_context_menu()
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert labels == ["确定", "编辑…", "自动界限", "取消", "恢复初始界限", "点 1", "点 2"]
    assert menu.objectName() == "CursorPopupMenu"
    assert not set(labels).intersection({"打开", "保存分析", "打印", "尺寸变化", "信号最大", "分析选项"})
    menu_action(menu, "点 2").trigger()
    assert ui._pending_measurement["interactive"]["active_point"] == 1
    rebuilt = ui.create_plot_context_menu()
    assert menu_action(rebuilt, "点 2").isChecked()
    assert not menu_action(rebuilt, "点 1").isChecked()
    ui.cancel_measurement()
    assert "打开" in [a.text() for a in ui.create_plot_context_menu().actions()]


@pytest.mark.parametrize("file_index", [1, 2])
def test_accepting_overlay_options_preserves_second_or_third_selected_curve(ui, file_index):
    original = ui.curves[0].dataset
    ui.finish_import([Dataset(original.path.with_name(f"overlay-{i}.00{i}"), original.signals,
                             original.values.copy(), original.metadata, [], f"overlay-source-{i}")
                      for i in (2, 3)], [])
    ui.show_overlay()
    ui.files.setCurrentItem(ui.files.topLevelItem(file_index))
    selected_uid = ui.selected().uid
    source_key = str(ui.selected().dataset.path)
    dialog = OverlayOptionsDialog(ui)
    dialog.title.setText("保持活动样品")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert ui.selected().uid == selected_uid
    assert ui.files.indexOfTopLevelItem(ui.files.currentItem()) == file_index
    assert source_key in ui.documents
    ui.show_normal()
    assert ui.mdi.activeSubWindow().key == source_key
    assert ui.selected().uid == selected_uid


def test_manual_off_grid_temperatures_interpolate_adjacent_acquired_samples(ui):
    measured = ui.curves[0].dataset.values.copy()
    entry = ui.start_point_measurement("dimension_change")
    dialog = CursorLimitsDialog(ui)
    dialog.fields[0].setText("103.25")
    dialog.fields[1].setText("106.4")
    assert float(dialog.y_fields[0].text()) == pytest.approx(2.75)
    assert float(dialog.y_fields[1].text()) == pytest.approx(11.2)
    assert "positions" not in entry["interactive"]  # Preview remains a dialog draft.
    dialog.accept()
    assert entry["interactive"]["positions"] == pytest.approx([3.25, 6.4])
    assert entry["values"]["T1"] == pytest.approx(103.25)
    assert entry["values"]["T2"] == pytest.approx(106.4)
    assert entry["values"]["H1"] == pytest.approx(2.75)
    assert entry["values"]["H2"] == pytest.approx(11.2)
    assert entry["values"]["H"] == pytest.approx(8.45)
    editor = next(editor for editor in ui._measurement_artists if editor.entry is entry)
    assert editor.markers[0].get_xdata()[0] == pytest.approx(103.25)
    assert editor.markers[0].get_ydata()[0] == pytest.approx(2.75)
    np.testing.assert_array_equal(ui.curves[0].dataset.values, measured)


def test_repeated_temperature_uses_each_handles_current_acquisition_branch(ui):
    original = ui.curves[0].dataset
    original.values = np.column_stack((np.arange(7.), [100, 101, 102, 103, 102, 101, 100], np.arange(7.) * 10))
    entry = ui.start_point_measurement("dimension_change")
    entry["interactive"]["indices"] = [1, 4]
    ui.redraw()
    dialog = CursorLimitsDialog(ui)
    dialog.fields[0].setText("101.5")
    dialog.fields[1].setText("101.5")
    assert [float(field.text()) for field in dialog.y_fields] == pytest.approx([15, 45])
    dialog.accept()
    assert entry["interactive"]["positions"] == pytest.approx([1.5, 4.5])
    assert entry["values"]["H"] == pytest.approx(30)
    # The same exact repeated X also retains the second handle's cooling branch.
    exact = CursorLimitsDialog(ui)
    exact.fields[1].setText("102")
    exact.accept()
    assert entry["interactive"]["positions"][1] == 4
    assert entry["values"]["H2"] == 40


@pytest.mark.parametrize("invalid", ["", "not a temperature", "nan", "inf", "99", "111"])
def test_invalid_manual_input_does_not_change_pending_result_or_control_points(ui, invalid):
    entry = ui.start_point_measurement("dimension_change")
    before = deepcopy(entry)
    dialog = CursorLimitsDialog(ui)
    dialog.fields[0].setText("103.25")
    dialog.fields[1].setText(invalid)
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.error.text()
    assert entry == before
    assert not ui.results
    dialog.reject()
    assert entry == before


def test_cancel_manual_limits_and_automatic_limits_preserve_expected_draft(ui):
    entry = ui.start_point_measurement("dimension_change")
    initial = deepcopy(entry)
    dialog = CursorLimitsDialog(ui)
    dialog.fields[0].setText("103.25")
    dialog.reject()
    assert entry == initial
    dialog = CursorLimitsDialog(ui)
    dialog.fields[0].setText("103.25")
    dialog.fields[1].setText("106.4")
    dialog.accept()
    assert "positions" in entry["interactive"]
    menu_action(ui.create_plot_context_menu(), "恢复初始界限").trigger()
    assert "positions" not in entry["interactive"]
    assert entry["interactive"]["indices"] == initial["interactive"]["indices"]
    assert entry["values"] == initial["values"]


def test_fractional_cursor_positions_and_annotations_survive_session_round_trip(ui, tmp_path):
    entry = ui.start_point_measurement("dimension_change")
    curve_uid = ui.curves[0].uid
    dialog = CursorLimitsDialog(ui)
    dialog.fields[0].setText("103.25")
    dialog.fields[1].setText("106.4")
    dialog.accept()
    ui.confirm_measurement()
    expected = deepcopy(ui.results[0])
    path = tmp_path / "fractional.tmas"
    save_session(path, ui.curves, ui.domain, ui.results, plot_options=ui.plot_options)
    ui.close_all_documents()
    ui.restore_session(path)
    assert ui.results == [expected]
    assert ui.results[0]["curve_id"] == curve_uid
    assert ui.results[0]["interactive"]["positions"] == pytest.approx([3.25, 6.4])
    editor = ui._measurement_artists[0]
    np.testing.assert_allclose(editor.coords, [(103.25, 2.75), (106.4, 11.2)])
    assert "103.25" in editor.temps[0].get_text()
    assert "106.40" in editor.temps[1].get_text()
    ui.edit_measurement(ui.results[0])
    dialog = CursorLimitsDialog(ui)
    assert [float(field.text()) for field in dialog.fields] == pytest.approx([103.25, 106.4])
    dialog.fields[0].setText("104.5")
    dialog.accept()
    ui.cancel_measurement()
    assert ui.results == [expected]


def test_export_defaults_to_active_source_stem_and_records_png_author(ui, tmp_path, monkeypatch):
    original = ui.curves[0].dataset
    other = Dataset(original.path.with_name("second-sample.002"), original.signals, original.values.copy(),
                    original.metadata, [], "second-source")
    ui.finish_import([other], [])
    assert ui.mdi.activeSubWindow().key == str(other.path)
    exported = tmp_path / "export.png"
    calls = []
    def select_file(parent, title, default, filters):
        calls.append((title, default, filters))
        return str(exported), "PNG (*.png)"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", select_file)
    ui.export_plot()
    assert calls[0][1] == "second-sample.png"
    with Image.open(exported) as image:
        assert image.format == "PNG"
        assert image.info["Author"] == "Power By ZzzHe"
        assert image.info["Software"] == "Power By ZzzHe"
    assert "Power By ZzzHe" in [text.get_text() for text in ui.figure.texts]
    exported = tmp_path / "export.pdf"
    ui.export_plot("pdf")
    assert calls[-1][1] == "second-sample.pdf"
    assert calls[-1][2] == "PDF (*.pdf)"
    assert exported.read_bytes().startswith(b"%PDF-")
    assert b"Power By ZzzHe" in exported.read_bytes()
