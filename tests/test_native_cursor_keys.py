"""Manufacturer-documented cursor placement, manual XY, keyboard acceptance."""
from copy import deepcopy
import numpy as np
import pytest
from matplotlib.backend_bases import MouseEvent
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from test_point_interaction import ui
from tma_app.classic_dialogs import CursorLimitsDialog
from tma_app.workspace import save_session


def test_manual_xy_is_explicit_preserves_source_and_survives_session(ui, tmp_path):
    original = ui.curves[0].dataset.values.copy()
    entry = ui.start_point_measurement("dimension_change")
    dialog = CursorLimitsDialog(ui)
    dialog.fields[0].setText("103.25"); dialog.y_fields[0].setText("1.25")
    dialog.fields[1].setText("106.5"); dialog.y_fields[1].setText("18.75")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert entry["values"]["H"] == 17.5
    assert entry["values"]["H1"] == 1.25 and entry["values"]["H2"] == 18.75
    assert "explicitly entered Y" in entry["values"]["selection"]
    assert not ui.results
    QTest.keyClick(ui.canvas, Qt.Key.Key_Return)
    assert ui._pending_measurement is None and ui.results == [entry]
    session = tmp_path / "manual-xy.tmas"
    save_session(session, ui.curves, ui.domain, ui.results, ui.plot_options)
    ui.close_all_documents(); ui.restore_session(session)
    assert ui.results[0]["interactive"]["manual_y"] == [1.25, 18.75]
    np.testing.assert_allclose(ui._measurement_artists[0].coords, [[103.25, 1.25], [106.5, 18.75]])
    np.testing.assert_array_equal(original, ui.curves[0].dataset.values)


@pytest.mark.parametrize("invalid", ["nan", "inf", "-inf", "bad", ""])
def test_invalid_manual_y_never_changes_pending_or_results(ui, invalid):
    entry = ui.start_point_measurement("signal_change")
    before = deepcopy(entry)
    dialog = CursorLimitsDialog(ui)
    dialog.y_fields[0].setText(invalid); dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted and dialog.error.text()
    assert entry == before and not ui.results
    dialog.reject()


def test_double_click_places_active_point_then_activates_the_next(ui):
    entry = ui.start_point_measurement("dimension_change")
    editor = ui._measurement_artists[0]
    px, py = editor.axis.transData.transform((103, 2))
    event = MouseEvent("button_press_event", ui.canvas, px, py, button=1, dblclick=True)
    ui.canvas.callbacks.process("button_press_event", event)
    assert entry["interactive"]["indices"][0] == 3
    assert entry["interactive"]["active_point"] == 1
    assert editor.vline.get_visible() and not ui.results


def test_arrows_move_one_or_ten_screen_pixels_and_enter_only_then_commits(ui):
    entry = ui.start_point_measurement("dimension_change")
    editor = ui._measurement_artists[0]
    ui.canvas.draw()
    before = editor.axis.transData.transform(editor.coords[0])[0]
    QTest.keyClick(ui.canvas, Qt.Key.Key_Right)
    after = editor.axis.transData.transform(editor.coords[0])[0]
    assert after-before == pytest.approx(1)
    QTest.keyClick(ui.canvas, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    accelerated = editor.axis.transData.transform(editor.coords[0])[0]
    assert accelerated-after == pytest.approx(10)
    assert not ui.results and not entry["interactive"]["confirmed"]
    QTest.keyClick(ui.canvas, Qt.Key.Key_Enter)
    assert entry["interactive"]["confirmed"] and ui.results == [entry]
    assert not ui._measurement_artists[0].vline.get_visible()


def test_dragging_explicit_manual_y_returns_that_handle_to_the_curve(ui):
    entry = ui.start_point_measurement("dimension_change")
    dialog = CursorLimitsDialog(ui)
    dialog.fields[0].setText("103.25"); dialog.y_fields[0].setText("-0.5"); dialog.accept()
    editor = ui._measurement_artists[0]; ui.canvas.draw()
    px, py = editor.axis.transData.transform(editor.coords[0])
    tx, ty = editor.axis.transData.transform((105, 9))
    for kind, x, y in (("button_press_event", px, py), ("motion_notify_event", tx, ty), ("button_release_event", tx, ty)):
        ui.canvas.callbacks.process(kind, MouseEvent(kind, ui.canvas, x, y, button=1))
    assert entry["interactive"]["manual_y"][0] is None
    assert entry["values"]["T1"] == 105 and entry["values"]["H1"] == 9


def test_another_document_cannot_confirm_the_first_documents_pending_points(ui):
    from dataclasses import replace
    first = ui.mdi.activeSubWindow()
    pending = ui.start_point_measurement("dimension_change")
    source = ui.curves[0].dataset
    ui.finish_import([replace(source, path=source.path.with_name("other.002"))], [])
    QApplication.processEvents()
    assert ui.mdi.activeSubWindow() is not first and ui.current_measurement() is None
    labels = [action.text() for action in ui.create_plot_context_menu().actions() if not action.isSeparator()]
    assert labels[0] == "打开" and "确定" not in labels
    QTest.keyClick(ui.canvas, Qt.Key.Key_Return)
    assert ui._pending_measurement is pending and not ui.results
    ui.mdi.setActiveSubWindow(first); QApplication.processEvents()
    assert ui.current_measurement() is pending
    QTest.keyClick(ui.canvas, Qt.Key.Key_Return)
    assert ui._pending_measurement is None and ui.results == [pending]
