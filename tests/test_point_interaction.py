import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import numpy as np
import pytest
from matplotlib.backend_bases import MouseEvent
from PySide6.QtWidgets import QApplication
from tma_app.classic import ClassicMainWindow
from tma_app.reader import Dataset, Signal
from tma_app.workspace import save_session
from tma_app.measurement import nearest_sample, point_values


@pytest.fixture
def ui(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = ClassicMainWindow(); window.show()
    window.warn = lambda text: (_ for _ in ()).throw(AssertionError(text))
    x = np.arange(11.) + 100
    y = np.array([0, -2, -1, 2, 5, 9, 12, 10, 7, 5, 3.])
    ds = Dataset(tmp_path / "point.001", [Signal("Time", "min"), Signal("Temperature", "°C"), Signal("Dimension Change", "µm")],
                 np.column_stack((x-100, x, y)), {"Sample": ["point"]}, [], "same-content-hash")
    window.finish_import([ds], []); app.processEvents(); window.canvas.draw()
    yield window
    window.dirty = False; window.close(); app.processEvents()


def drag(ui, editor, point, target_index):
    ui.canvas.draw()
    x, y = editor.x[editor.indices[point]], editor.y[editor.indices[point]]
    px, py = editor.axis.transData.transform((x, y))
    press = MouseEvent("button_press_event", ui.canvas, px, py, button=1)
    ui.canvas.callbacks.process("button_press_event", press)
    assert ui._drag_measurement == (editor, point)
    # Intentionally move Y far away: the handle must stay attached to the trace.
    tx, ty = editor.axis.transData.transform((editor.x[target_index], float(np.min(editor.y))))
    ui.canvas.callbacks.process("motion_notify_event", MouseEvent("motion_notify_event", ui.canvas, tx, ty, button=1))
    ui.canvas.callbacks.process("button_release_event", MouseEvent("button_release_event", ui.canvas, tx, ty, button=1))
    assert ui._drag_measurement is None


def test_context_order_and_direct_menu_measurement(ui):
    menu = ui.create_plot_context_menu()
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert labels[:4] == ["打开", "保存分析", "打印", "批注"]
    assert labels.index("尺寸变化") < labels.index("信号最大") < labels.index("信号变化")
    assert "高度差" in labels and labels[-1] == "分析选项"
    maximum = next(a for a in menu.actions() if a.text() == "信号最大")
    maximum.trigger()
    assert ui._pending_measurement["kind"] == "signal_max"
    assert ui._pending_measurement["interactive"]["indices"] == [6]
    assert not ui.results and ui.measurement_confirm.isEnabled()
    assert "signal_analysis" not in ui.dialogs
    assert ui._measurement_artists[0].markers[0].get_xdata()[0] == 106


@pytest.mark.parametrize("kind", ["dimension_change", "signal_change", "height_change"])
def test_two_handles_recompute_live_from_real_samples(ui, kind):
    raw = ui.curves[0].dataset.values.copy()
    entry = ui.start_point_measurement(kind)
    editor = ui._measurement_artists[0]
    assert len(editor.markers) == 2
    drag(ui, editor, 0, 3)
    assert entry["values"]["T1"] == 103
    assert entry["values"]["H1"] == 2
    drag(ui, editor, 1, 8)
    assert entry["values"]["T2"] == 108
    assert entry["values"]["H2"] == 7
    assert entry["values"]["H"] == 5
    assert "5.0" in editor.annotation.get_text()
    assert [text.get_visible() for text in editor.temps] == [kind != "height_change"]*2
    assert "103.00" in editor.temps[0].get_text() and "108.00" in editor.temps[1].get_text()
    assert not ui.results
    ui.measurement_confirm.trigger()
    assert len(ui.results) == 1 and ui.results[0]["interactive"]["confirmed"]
    np.testing.assert_array_equal(ui.curves[0].dataset.values, raw)


def test_signal_max_starts_at_peak_then_moves_without_returning_to_peak(ui, tmp_path):
    ui.classic_actions["SignalMax1"].trigger()
    editor = ui._measurement_artists[0]
    assert editor.indices == [6] and editor.entry["values"]["value"] == 12
    drag(ui, editor, 0, 3)
    assert editor.entry["values"]["max_x"] == 103
    assert editor.entry["values"]["value"] == 2
    assert editor.annotation.get_text() == "103.00 °C"
    ui.redraw()
    assert ui._measurement_artists[0].indices == [3]
    ui.confirm_measurement()
    uid = ui.curves[0].uid
    path = tmp_path / "drag.tmas"
    save_session(path, ui.curves, ui.domain, ui.results, plot_options=ui.plot_options)
    ui.close_all_documents(); ui.restore_session(path)
    assert ui.curves[0].uid == uid
    assert ui._measurement_artists[0].indices == [3]
    assert ui.results[0]["values"]["value"] == 2
    ui.edit_measurement(ui.results[0])
    drag(ui, ui._measurement_artists[0], 0, 9)
    ui.confirm_measurement()
    assert ui.results[0]["values"]["value"] == 5


def test_handles_can_cross_and_height_display_preserves_signed_result(ui):
    ui.start_point_measurement("height_change")
    editor = ui._measurement_artists[0]
    drag(ui, editor, 0, 10)
    drag(ui, editor, 1, 1)
    assert editor.entry["interactive"]["indices"] == [10, 1]
    assert editor.entry["values"]["H"] == -5
    assert "5.0" in editor.annotation.get_text() and "-5" not in editor.annotation.get_text()


def test_identical_datasets_do_not_share_measurement_handles(ui):
    original = ui.curves[0].dataset
    other = Dataset(original.path.with_name("other.002"), original.signals, original.values.copy(), original.metadata, [], original.sha256)
    ui.finish_import([other], []); ui.show_overlay()
    ui.files.setCurrentItem(ui.files.topLevelItem(0)); first = ui.start_point_measurement("dimension_change")
    ui.confirm_measurement()
    ui.files.setCurrentItem(ui.files.topLevelItem(1)); second = ui.start_point_measurement("signal_max")
    assert first["curve_id"] != second["curve_id"]
    assert len(ui._measurement_artists) == 2
    assert len({editor.curve.uid for editor in ui._measurement_artists}) == 2


def test_interactive_result_csv_includes_positions_and_values(ui, tmp_path):
    import csv, json
    ui.start_point_measurement("dimension_change")
    editor = ui._measurement_artists[0]
    drag(ui, editor, 0, 3)
    ui.confirm_measurement()
    path = tmp_path / "measurement.csv"
    ui.write_results(path)
    with path.open(encoding="utf-8-sig", newline="") as stream: rows = list(csv.DictReader(stream))
    assert len(rows) == 1 and rows[0]["kind"] == "dimension_change"
    assert json.loads(rows[0]["interactive"])["indices"][0] == 3
    assert json.loads(rows[0]["values"])["T1"] == 103


def test_maximum_annotation_avoids_temperature_labels(ui):
    from matplotlib.text import Text
    ui.start_point_measurement("dimension_change")
    ui.confirm_measurement()
    ui.start_point_measurement("signal_max")
    ui.canvas.draw()
    renderer = ui.canvas.get_renderer()
    maximum = next(editor for editor in ui._measurement_artists if editor.entry["kind"] == "signal_max")
    box = Text.get_window_extent(maximum.annotation, renderer)
    for editor in ui._measurement_artists:
        for text in editor.temps:
            assert not box.overlaps(Text.get_window_extent(text, renderer))


def test_explicit_sample_values_preserve_order_precision_and_ties():
    x = [100.123456789123, 102, 102, 101]
    y = [0, 10, 20, 5]
    values = point_values(x, y, "dimension_change", [2, 0])
    assert values["T2"] == x[0] and values["H"] == -20
    assert nearest_sample(x, 102, anchor=2) == 2
    with pytest.raises(ValueError): point_values(x, y, "signal_max", [-1])
    with pytest.raises(ValueError): point_values(x, y, "height_change", [True, 2])
