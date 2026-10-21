"""User workflows for overlay drafts, persistent settings, and signal dialogs."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QLineEdit

from tma_app.classic import ClassicMainWindow
from tma_app.classic_dialogs import AddCurvesDialog, OverlayOptionsDialog, SignalAnalysisDialog
from tma_app.reader import Dataset, Signal
from tma_app.workspace import save_session


@pytest.fixture
def ui():
    application = QApplication.instance() or QApplication([])
    window = ClassicMainWindow()
    window.warn = lambda message: (_ for _ in ()).throw(AssertionError(message))
    window.show()
    application.processEvents()
    yield window
    for dialog in window.findChildren(QDialog):
        dialog.hide()
    window.dirty = False
    window.close()
    application.processEvents()


def source(path):
    time = np.arange(7, dtype=float)
    return Dataset(Path(path), [Signal("Time", "min"), Signal("Temperature", "°C"), Signal("Dimension Change", "µm")],
                   np.column_stack([time, time + 100, [0., -2., 9., 4., 3., 1., -4.]]),
                   {"Sample": [Path(path).stem]}, [], hashlib.sha256(str(path).encode()).hexdigest())


def imported(ui, tmp_path, count=2):
    ui.finish_import([source(tmp_path / f"sample-{i}.00{i + 1}") for i in range(count)], [])
    ui.show_overlay()
    QApplication.processEvents()


def set_combo(box, value):
    index = box.findData(value)
    assert index >= 0
    box.setCurrentIndex(index)


def texts(ui):
    return [text.get_text() for axis in ui.axes.values() for text in axis.texts]


def test_cancel_overlay_edits_preserves_live_state(ui, tmp_path):
    imported(ui, tmp_path)
    original = list(ui.curves)
    before = [(c.style, c.marker, c.offset, c.legend_text, c.overlay_enabled) for c in original]
    options = deepcopy(ui.plot_options)
    ui.dirty = False
    dialog = OverlayOptionsDialog(ui)
    set_combo(dialog.table.cellWidget(0, 1), "None")
    set_combo(dialog.table.cellWidget(0, 2), "s")
    dialog.table.cellWidget(0, 4).setValue(12)
    dialog.table.cellWidget(0, 6).findChild(QLineEdit).setText("discarded legend")
    dialog.title.setText("discarded title")
    dialog.table.selectRow(1)
    dialog.delete_curves()
    dialog.reject()
    assert ui.curves == original
    assert [(c.style, c.marker, c.offset, c.legend_text, c.overlay_enabled) for c in ui.curves] == before
    assert ui.plot_options == options
    assert not ui.dirty
    assert len(ui._plot_artists) == 2


def test_accept_overlay_edits_updates_rendered_order_and_style(ui, tmp_path):
    imported(ui, tmp_path, 3)
    first, second, third = [c.dataset.path for c in ui.curves]
    dialog = OverlayOptionsDialog(ui)
    set_combo(dialog.table.cellWidget(0, 1), "None")
    set_combo(dialog.table.cellWidget(0, 2), "D")
    dialog.table.cellWidget(0, 4).setValue(11)
    dialog.table.cellWidget(0, 6).findChild(QLineEdit).setText("第一条实验")
    dialog.table.selectRow(2)
    dialog.delete_curves()
    dialog.move_curve(dialog.axis_curves()[0], "bottom")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert [c.dataset.path for c in ui.curves] == [second, first, third]
    assert [c.dataset.path for c in ui.visible_curves()] == [second, first]
    assert len(ui._plot_artists) == 2
    lines = [line for line in ui.axes[0].lines if len(line.get_xdata()) == 7]
    assert [line.get_label() for line in lines] == [second.stem, "第一条实验"]
    assert lines[1].get_linestyle() == "None"
    assert lines[1].get_marker() == "D"
    np.testing.assert_array_equal(lines[1].get_ydata(), np.array([0, -2, 9, 4, 3, 1, -4]) + 11)
    assert not ui.curves[2].overlay_enabled
    assert ui.dirty


def test_ten_curve_limit_prevents_partial_apply(ui, tmp_path):
    imported(ui, tmp_path, 11)
    original = list(ui.curves)
    options = deepcopy(ui.plot_options)
    dialog = OverlayOptionsDialog(ui)
    dialog.title.setText("must not leak")
    set_combo(dialog.table.cellWidget(0, 1), "--")
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "10" in dialog.error.text()
    assert ui.curves == original
    assert ui.curves[0].style == "-"
    assert ui.plot_options == options
    # Removing one draft curve enables the same complete proposal to commit.
    dialog.draft[-1].overlay_enabled = False
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert len(ui.visible_curves()) == 10
    assert ui.curves[0].style == "--"
    assert ui.plot_options["__overlay__"]["window_name"] == "must not leak"


def test_incompatible_signals_reject_whole_proposal(ui, tmp_path):
    imported(ui, tmp_path)
    original = list(ui.curves)
    original_options = deepcopy(ui.plot_options)
    dialog = OverlayOptionsDialog(ui)
    dialog.draft[1].y_index = 1
    dialog.draft[0].offset = 77
    dialog.title.setText("invalid proposal")
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "单位" in dialog.error.text()
    assert ui.curves == original
    assert [c.y_index for c in ui.curves] == [2, 2]
    assert ui.curves[0].offset == 0
    assert ui.plot_options == original_options


def test_saved_overlay_restores_labels_ranges_and_curve_presentation(ui, tmp_path):
    imported(ui, tmp_path)
    dialog = OverlayOptionsDialog(ui)
    dialog.title.setText("拉伸实验叠图")
    dialog.x_label.setText("设定温度")
    dialog.y_labels[0].setText("尺寸变化 / µm")
    dialog.grid_boxes["grid_x"].setChecked(True)
    set_combo(dialog.legend, False)
    set_combo(dialog.table.cellWidget(0, 2), "^")
    dialog.table.cellWidget(0, 6).findChild(QLineEdit).setText("试样 A")
    dialog.accept()
    scale = ui.manual_rescale("x")
    for field, value in zip(scale.fields["x"], [99, 110, 5, 1, 0]): field.setText(str(value))
    scale.accept()
    expected = deepcopy(ui.plot_options)
    path = tmp_path / "plot.tmas"
    save_session(path, ui.curves, ui.domain, ui.results, plot_options=ui.plot_options)
    ui.close_all_documents()
    ui.restore_session(path)
    assert ui.plot_options == expected
    assert ui.curves[0].marker == "^"
    assert ui.curves[0].legend_text == "试样 A"
    assert ui.axes[0].get_xlim() == pytest.approx((99, 110))
    assert ui.axes[0].get_xlabel() == "设定温度"
    assert ui.axes[0].get_ylabel() == "尺寸变化 / µm"
    assert ui.mdi.activeSubWindow().windowTitle() == "拉伸实验叠图"
    assert "拉伸实验叠图" not in [item.get_text() for item in ui.figure.texts]
    assert not ui.axes[0].get_legend().get_visible()
    assert any(line.get_visible() for line in ui.axes[0].get_xgridlines())


def test_signal_max_dialog_records_sample_and_curve_annotation(ui, tmp_path):
    imported(ui, tmp_path, 1)
    dialog = SignalAnalysisDialog(ui, "signal_max")
    dialog.low.setValue(101)
    dialog.high.setValue(105)
    dialog.calculate()
    result = ui.results[-1]
    assert result["kind"] == "signal_max"
    assert result["values"]["value"] == pytest.approx(9)
    assert result["values"]["max_x"] == pytest.approx(102)
    assert "9" in dialog.output.text() and "102" in dialog.output.text()
    assert "102.00 °C" in texts(ui)
    assert not any("信号最大" in text for text in texts(ui))
    assert any(np.array_equal(line.get_xdata(), [102]) and np.array_equal(line.get_ydata(), [9])
               for line in ui.axes[0].lines)


def test_signal_change_dialog_records_signed_result_and_annotation_choices(ui, tmp_path):
    imported(ui, tmp_path, 1)
    dialog = SignalAnalysisDialog(ui, "signal_change")
    dialog.low.setValue(102)
    dialog.high.setValue(106)
    dialog.annotation_boxes["signed"].setChecked(False)
    dialog.annotation_boxes["y_limits"].setChecked(False)
    dialog.calculate()
    values = ui.results[-1]["values"]
    assert (values["start_x"], values["start_y"], values["stop_x"], values["stop_y"]) == (102, 9, 106, -4)
    assert values["change"] == pytest.approx(-13)
    assert "-13" in dialog.output.text()
    annotation = next(text for text in texts(ui) if "ΔY" in text)
    assert "ΔY = 13" in annotation and "X: 102 → 106" in annotation
    assert "Y:" not in annotation
    assert any(np.array_equal(line.get_xdata(), [102, 106]) and np.array_equal(line.get_ydata(), [9, -4])
               for line in ui.axes[0].lines)


def test_graph_range_returns_to_dialog_and_point_click_snaps_to_sample(ui, tmp_path):
    imported(ui, tmp_path, 1)
    dialog = SignalAnalysisDialog(ui, "signal_change")
    dialog.show()
    dialog.select_range()
    assert not dialog.isVisible() and ui.range_enabled.isChecked()
    ui.range_selected(101.2, 104.8)
    assert dialog.isVisible()
    assert (dialog.low.value(), dialog.high.value()) == pytest.approx((101.2, 104.8))
    assert not ui.range_enabled.isChecked()
    dialog.pick_point(0)
    assert not dialog.isVisible()
    ui.analysis_click(SimpleNamespace(xdata=102.65, button=1))
    assert dialog.isVisible()
    assert dialog.low.value() == 103
    dialog.pick_point(1)
    ui.analysis_click(SimpleNamespace(xdata=105.2, button=1))
    assert dialog.high.value() == 105
    assert ui._point_dialog[0] is None
    dialog.calculate()
    assert ui.results[-1]["values"]["start_x"] == 103
    assert ui.results[-1]["values"]["stop_x"] == 105


def test_disabling_legend_text_keeps_curve_rows_without_empty_workspace_text(ui, tmp_path):
    imported(ui, tmp_path)
    dialog = OverlayOptionsDialog(ui)
    for row in range(2):
        dialog.table.cellWidget(row, 6).findChild(QCheckBox).setChecked(False)
    dialog.accept()
    assert len(ui._plot_artists) == 2
    assert len([line for line in ui.axes[0].lines if len(line.get_xdata()) == 7]) == 2
    assert [t.get_text() for t in ui.axes[0].get_legend().get_texts()] == ["", ""]
    assert not any("从原始数据开始" in text or "导入 .001" in text for text in texts(ui))


def test_removing_overlay_curve_keeps_original_normal_document(ui, tmp_path):
    imported(ui, tmp_path)
    removed_path = ui.curves[0].dataset.path
    dialog = OverlayOptionsDialog(ui)
    dialog.table.selectRow(0)
    dialog.delete_curves()
    dialog.accept()
    assert len(ui.curves) == 2
    assert len(ui.visible_curves()) == 1
    assert str(removed_path) in ui.documents
    ui.files.setCurrentItem(ui.files.topLevelItem(0))
    ui.show_normal()
    assert ui.mdi.activeSubWindow().key == str(removed_path)
    assert [c.dataset.path for c in ui.visible_curves()] == [removed_path]
    assert len(ui._plot_artists) == 1


def test_drag_result_annotation_survives_redraw_and_session(ui, tmp_path):
    from matplotlib.text import Text
    imported(ui, tmp_path, 1)
    dialog = SignalAnalysisDialog(ui, "signal_max")
    dialog.calculate()
    ui.canvas.draw()
    entry, annotation = ui._result_annotations[0]
    before = tuple(annotation.xyann)
    box = Text.get_window_extent(annotation, ui.canvas.get_renderer())
    x, y = (box.x0 + box.x1)/2, (box.y0 + box.y1)/2
    ui.result_press(SimpleNamespace(button=1, x=x, y=y))
    ui.result_motion(SimpleNamespace(x=x+50, y=y+25))
    ui.result_release(SimpleNamespace(button=1))
    stored = entry["annotation"]["offset"]
    assert stored != list(before)
    ui.redraw()
    assert list(ui._result_annotations[0][1].xyann) == pytest.approx(stored)
    path = tmp_path / "annotations.tmas"
    save_session(path, ui.curves, ui.domain, ui.results, plot_options=ui.plot_options)
    ui.close_all_documents(); ui.restore_session(path)
    assert ui.results[0]["annotation"]["offset"] == pytest.approx(stored)
    assert list(ui._result_annotations[0][1].xyann) == pytest.approx(stored)


def test_add_curves_selects_named_signal_and_rejects_incompatible_axis(ui, tmp_path):
    imported(ui, tmp_path)
    dialog = AddCurvesDialog(ui, ui.curves, 0)
    assert dialog.signals.count() == 1
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert len(dialog.selected_curves) == 2
    assert all(c.y_index == 2 and c.axis == 0 for c in dialog.selected_curves)
    other_axis = AddCurvesDialog(ui, ui.curves, 1)
    assert other_axis.signals.count() == 3
    other_axis.signals.setCurrentRow(next(i for i in range(other_axis.signals.count()) if other_axis.signals.item(i).text().startswith("Temperature")))
    other_axis.accept()
    assert all(c.y_index == 1 and c.axis == 1 for c in other_axis.selected_curves)
    dialog = AddCurvesDialog(ui, ui.curves, 0)
    dialog.compatible.setChecked(False)
    dialog.signals.setCurrentRow(next(i for i in range(dialog.signals.count()) if dialog.signals.item(i).text().startswith("Time")))
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "单位" in dialog.error.text()


def test_auto_overlay_assigns_units_and_colors_then_allows_manual_axis_move(ui, tmp_path):
    imported(ui, tmp_path)
    ui.curves[1].y_index = 1
    ui.curves[1].axis = 1
    auto = ui.auto_configure_overlay()
    auto.mode_groups["color"].button(0).setChecked(True)
    auto.accept()
    assert [c.axis for c in ui.curves] == [0, 1]
    assert ui.curves[0].color != ui.curves[1].color
    assert len(ui._plot_artists) == 2 and len(ui.axes) == 2
    dialog = OverlayOptionsDialog(ui)
    dialog.move_axis(dialog.axis_curves()[0], 1)
    assert "单位" in dialog.error.text()
    assert dialog.draft[0].axis == 0
    dialog.move_axis(dialog.axis_curves()[0], 3)
    dialog.accept()
    assert ui.curves[0].axis == 3
    assert len(ui._plot_artists) == 2 and 3 in ui.axes


def test_full_range_and_picked_bounds_preserve_exact_sample_temperatures(ui, tmp_path):
    ds = source(tmp_path / "precision.001")
    xs = np.array([59.758087158203125, 60.00000017, 60.00000014, 100.1148910522461, 180.12345678913, 240.23456789014, 244.74618530273438])
    ds.values[:, 1] = xs
    ui.finish_import([ds], [])
    dialog = SignalAnalysisDialog(ui, "signal_change")
    dialog.calculate()
    vals = ui.results[-1]["values"]
    assert vals["points"] == len(xs)
    assert (vals["start_x"], vals["stop_x"]) == (xs[0], xs[-1])
    assert vals["change"] == -4
    # Picking sample X must retain it even if the displayed decimal is rounded.
    dialog.pick_point(0)
    ui.analysis_click(SimpleNamespace(xdata=xs[3], button=1))
    dialog.pick_point(1)
    ui.analysis_click(SimpleNamespace(xdata=xs[4], button=1))
    dialog.calculate()
    vals = ui.results[-1]["values"]
    assert (vals["start_x"], vals["stop_x"]) == (xs[3], xs[4])
    assert vals["points"] == 2
    assert vals["change"] == -1
