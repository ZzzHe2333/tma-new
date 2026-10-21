"""The native result popup addresses one result, preserving data and other entries."""
from copy import deepcopy
from matplotlib.text import Text
from PySide6.QtWidgets import QApplication
from test_point_interaction import ui
from tma_app.workspace import save_session


def labels(menu):
    return [action.text() for action in menu.actions() if not action.isSeparator()]


def test_result_hit_and_specific_adjustment_cancel(ui):
    ui.start_point_measurement("dimension_change"); ui.confirm_measurement()
    first = ui.results[0]
    ui.start_point_measurement("signal_max"); ui.confirm_measurement()
    original = deepcopy(ui.results)
    editor = next(editor for editor in ui._measurement_artists if editor.entry is first)
    ui.canvas.draw()
    box = Text.get_window_extent(editor.temps[0], ui.canvas.get_renderer())
    entry, annotation = ui.result_annotation_at(*box.get_points().mean(axis=0))
    assert entry is first and annotation is editor.temps[0]
    menu = ui.create_result_context_menu(entry, annotation)
    assert labels(menu) == ["粗体", "斜体", "字号", "调整结果", "删除结果", "隐藏结果", "复制文字"]
    next(a for a in menu.actions() if a.text() == "调整结果").trigger()
    assert ui._editing_measurement is first
    ui.cancel_measurement()
    assert ui.results == original


def test_object_popup_copy_styles_hide_show_and_roundtrip(ui, tmp_path):
    raw = ui.curves[0].dataset.values.copy()
    ui.start_point_measurement("dimension_change"); ui.confirm_measurement()
    entry = ui.results[0]; values = deepcopy(entry["values"])
    menu = ui.create_result_context_menu(entry, ui._measurement_artists[0].temps[0])
    next(a for a in menu.actions() if a.text() == "复制文字").trigger()
    assert QApplication.clipboard().text().startswith("T1 = ")
    ui.style_result(entry, "bold", True); ui.style_result(entry, "italic", True); ui.style_result(entry, "size", 16)
    ui.canvas.draw()
    for text in (ui._measurement_artists[0].annotation, *ui._measurement_artists[0].temps):
        assert text.get_fontweight() == "bold" and text.get_fontstyle() == "italic" and text.get_fontsize() == 16
    ui.hide_result(entry)
    assert not ui._measurement_artists and ui.results == [entry]
    assert "显示隐藏结果" in labels(ui.create_plot_context_menu())
    session = tmp_path / "hidden.tmas"
    save_session(session, ui.curves, ui.domain, ui.results, ui.plot_options)
    ui.close_all_documents(); ui.restore_session(session)
    assert not ui._measurement_artists
    ui.show_hidden_results(); ui.canvas.draw()
    assert len(ui._measurement_artists) == 1
    assert ui._measurement_artists[0].temps[0].get_fontsize() == 16
    assert ui.results[0]["values"] == values
    import numpy as np
    np.testing.assert_array_equal(raw, ui.curves[0].dataset.values)


def test_delete_only_the_selected_result(ui):
    ui.start_point_measurement("dimension_change"); ui.confirm_measurement()
    first = ui.results[0]
    ui.start_point_measurement("signal_max"); ui.confirm_measurement()
    second = ui.results[1]; values = deepcopy(second)
    menu = ui.create_result_context_menu(first, ui._measurement_artists[0].annotation)
    next(a for a in menu.actions() if a.text() == "删除结果").trigger()
    assert ui.results == [second] and ui.results[0] == values
    assert len(ui._measurement_artists) == 1
