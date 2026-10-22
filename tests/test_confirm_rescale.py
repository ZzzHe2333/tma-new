"""Explicit confirmation, independently movable labels and axis rescaling."""
from copy import deepcopy
from types import SimpleNamespace
import numpy as np
import pytest
from matplotlib.backend_bases import MouseEvent
from matplotlib.text import Text
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox
from test_point_interaction import ui, drag
from tma_app.workspace import save_session, validate_plot_options


def drag_label(window, text, dx=50, dy=22):
    window.canvas.draw()
    box = Text.get_window_extent(text, window.canvas.get_renderer())
    x, y = (box.x0+box.x1)/2, (box.y0+box.y1)/2
    window.canvas.callbacks.process("button_press_event", MouseEvent("button_press_event", window.canvas, x, y, button=1))
    assert window._drag_annotation is not None and window._drag_measurement is None
    window.canvas.callbacks.process("motion_notify_event", MouseEvent("motion_notify_event", window.canvas, x+dx, y+dy, button=1))
    window.canvas.callbacks.process("button_release_event", MouseEvent("button_release_event", window.canvas, x+dx, y+dy, button=1))


def test_confirm_button_freezes_points_and_removes_crosshairs(ui):
    ui.dirty = False
    pending = ui.start_point_measurement("dimension_change")
    assert not ui.results and not ui.dirty
    editor = ui._measurement_artists[0]
    drag(ui, editor, 0, 3)
    drag(ui, editor, 1, 8)
    assert editor.vline.get_visible() and editor.hline.get_visible()
    assert not ui.dirty
    ui.measurement_confirm.trigger()
    assert ui.results == [pending] and pending["interactive"]["confirmed"]
    assert ui._pending_measurement is None and ui.dirty
    assert not ui.measurement_confirm.isEnabled()
    editor = ui._measurement_artists[0]
    assert not editor.vline.get_visible() and not editor.hline.get_visible()
    indices = list(editor.indices)
    px, py = editor.axis.transData.transform((editor.x[indices[0]], editor.y[indices[0]]))
    ui.result_press(SimpleNamespace(button=1, x=px, y=py))
    assert ui._drag_measurement is None
    assert editor.indices == indices


def test_confirmation_is_in_exclusive_context_menu_without_status_buttons(ui):
    ui.resize(1080, 720)
    ui.start_point_measurement("dimension_change")
    QApplication.processEvents()
    menu = ui.create_plot_context_menu()
    assert [a.text() for a in menu.actions() if not a.isSeparator()] == ["确定", "编辑…", "自动界限", "取消", "恢复初始界限", "点 1", "点 2"]
    assert ui.statusBar().height() == 19
    menu.actions()[0].trigger()
    QApplication.processEvents()
    assert ui.results[0]["interactive"]["confirmed"]
    assert ui.statusBar().height() == 19


def test_cancel_preview_and_cancel_reedit_do_not_change_saved_results(ui):
    ui.dirty = False
    ui.start_point_measurement("signal_max")
    drag(ui, ui._measurement_artists[0], 0, 3)
    ui.measurement_cancel.trigger()
    assert not ui.results and not ui.dirty and not ui._measurement_artists
    ui.start_point_measurement("dimension_change"); ui.confirm_measurement()
    original = deepcopy(ui.results)
    ui.dirty = False
    ui.edit_measurement(ui.results[0])
    drag(ui, ui._measurement_artists[0], 1, 9)
    ui.cancel_measurement()
    assert ui.results == original and not ui.dirty
    assert len(ui._measurement_artists) == 1
    ui.edit_measurement(ui.results[0])
    drag(ui, ui._measurement_artists[0], 1, 9)
    ui.confirm_measurement()
    assert len(ui.results) == 1 and ui.results[0]["interactive"]["indices"][1] == 9


def test_both_temperature_labels_drag_after_confirm_and_restore(ui, tmp_path):
    ui.start_point_measurement("dimension_change"); ui.confirm_measurement()
    values = deepcopy(ui.results[0]["values"])
    editor = ui._measurement_artists[0]
    drag_label(ui, editor.temps[0], 55, 27)
    editor = ui._measurement_artists[0]
    drag_label(ui, editor.temps[1], -65, 18)
    offsets = deepcopy(ui.results[0]["annotation"]["label_offsets"])
    assert set(offsets) == {"t1", "t2"}
    assert offsets["t1"] != [6, -30] and offsets["t2"] != [6, 18]
    assert ui.results[0]["values"] == values
    ui.redraw()
    assert list(ui._measurement_artists[0].temps[0].xyann) == pytest.approx(offsets["t1"])
    assert list(ui._measurement_artists[0].temps[1].xyann) == pytest.approx(offsets["t2"])
    path = tmp_path / "fixed.tmas"
    save_session(path, ui.curves, ui.domain, ui.results, plot_options=ui.plot_options)
    ui.close_all_documents(); ui.restore_session(path)
    assert ui.results[0]["interactive"]["confirmed"]
    assert ui.results[0]["annotation"]["label_offsets"] == offsets
    assert ui.results[0]["values"] == values
    assert not ui._measurement_artists[0].vline.get_visible()
    drag_label(ui, ui._measurement_artists[0].temps[0], -20, 25)
    assert ui.results[0]["annotation"]["label_offsets"]["t1"] != offsets["t1"]


def test_single_point_shows_only_temperature_before_after_confirmation(ui):
    entry = ui.start_point_measurement("signal_max")
    assert ui._measurement_artists[0].annotation.get_text() == "106.00 °C"
    drag(ui, ui._measurement_artists[0], 0, 3)
    ui.confirm_measurement()
    editor = ui._measurement_artists[0]
    assert editor.annotation.get_text() == "103.00 °C"
    assert entry["values"]["value"] == 2
    drag_label(ui, editor.annotation)
    ui.redraw()
    assert ui._measurement_artists[0].annotation.get_text() == "103.00 °C"
    assert ui.results[0]["annotation"]["offset"]


def configure(dialog, axis, values):
    for widget, value in zip(dialog.fields[axis], values): widget.setText(str(value))


def test_rescale_sets_ranges_major_minor_and_label_offsets_without_changing_data(ui, tmp_path):
    before = ui.curves[0].dataset.values.copy()
    dialog = ui.manual_rescale("x")
    assert len(dialog.fields) == 5
    assert all(not box.isEnabled() for axis in (1, 2, 3) for box in dialog.fields[axis])
    configure(dialog, "x", [90, 130, 10, 2.5, 2])
    configure(dialog, 0, [-10, 20, 5, 1.25, -1])
    dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    ui.canvas.draw()
    axis = ui.axes[0]
    assert axis.get_xlim() == pytest.approx((90, 130))
    assert axis.get_ylim() == pytest.approx((-10, 20))
    assert axis.xaxis.get_major_locator().tick_values(90, 130)[1:6].tolist() == [90, 100, 110, 120, 130]
    assert any(np.isclose(axis.xaxis.get_minorticklocs(), 92.5))
    assert axis.xaxis.get_major_formatter()(100) == "102"
    assert axis.yaxis.get_major_formatter()(0) == "-1"
    np.testing.assert_array_equal(ui.curves[0].dataset.values, before)
    ui.redraw(); assert ui.axes[0].get_xlim() == pytest.approx((90, 130))
    path = tmp_path / "axes.tmas"
    save_session(path, ui.curves, ui.domain, ui.results, plot_options=ui.plot_options)
    ui.close_all_documents(); ui.restore_session(path)
    ui.show_normal()
    assert ui.axes[0].get_xlim() == pytest.approx((90, 130))
    assert ui.axes[0].xaxis.get_major_formatter()(100) == "102"
    ui.full_scale()
    assert ui.plot_options[ui.mdi.activeSubWindow().key]["x_ticks"] is None
    assert ui.axes[0].get_xlim()[0] <= 100 and ui.axes[0].get_xlim()[1] >= 110


@pytest.mark.parametrize("values", [[100, 90, 10, 2.5, 0], [90, 130, 0, 1, 0], [90, 130, 10, 20, 0], [90, 130, 10, .0001, 0], [90, 130, 10, 2.5, "nan"]])
def test_invalid_rescale_is_transactional_and_cancel_preserves_view(ui, values):
    before = deepcopy(ui.plot_options)
    limits = ui.axes[0].get_xlim()
    dialog = ui.manual_rescale()
    configure(dialog, "x", values)
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted and dialog.error.text()
    assert ui.plot_options == before and ui.axes[0].get_xlim() == limits
    dialog.reject()
    assert ui.plot_options == before


def test_axis_right_click_and_rescale_menu_open_the_same_editor(ui):
    ui.canvas.draw(); renderer = ui.canvas.get_renderer()
    for expected, label in [(0, ui.axes[0].get_yticklabels()[1]), ("x", ui.axes[0].get_xticklabels()[2])]:
        bounds = label.get_window_extent(renderer)
        x, y = (bounds.x0+bounds.x1)/2, (bounds.y0+bounds.y1)/2
        assert ui.axis_at_position(x, y) == expected
        doc = ui.mdi.activeSubWindow()
        ui.show_plot_context_menu(doc, QPoint(round(x), round(ui.canvas.height()-y)))
        assert ui.dialogs["rescale"].isVisible()
        ui.dialogs["rescale"].reject()
    ui.classic_actions["ManualRescale1"].trigger()
    assert ui.dialogs["rescale"].isVisible()
    ui.dialogs["rescale"].reject()
    assert not ui.toolbar.mode


def test_old_interactive_session_opens_fixed_and_tick_fields_are_validated(ui, tmp_path):
    ui.start_point_measurement("signal_max"); ui.confirm_measurement()
    ui.results[0]["interactive"].pop("confirmed")
    path = tmp_path / "v040.tmas"
    save_session(path, ui.curves, ui.domain, ui.results)
    ui.close_all_documents(); ui.restore_session(path)
    assert ui.results[0]["interactive"]["confirmed"]
    assert ui._measurement_artists[0].hit(*ui.axes[0].transData.transform((106, 12))) is None
    with pytest.raises(ValueError):
        validate_plot_options({"x_ticks": {"label_interval": True, "tick_interval": 1, "label_offset": 0}})
