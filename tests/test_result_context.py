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
    assert labels(menu) == ["粗体", "斜体", "字号", "隐藏此文字", "文字显隐", "调整结果", "删除结果", "隐藏结果", "复制文字"]
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


def test_endpoint_and_height_text_controls_are_independent_and_persistent(ui, tmp_path):
    from tma_app.workspace import load_session
    ui.start_point_measurement("dimension_change"); ui.confirm_measurement()
    entry = ui.results[0]; original_values = deepcopy(entry["values"])
    original_sizes = [text.get_fontsize() for text in (ui._measurement_artists[0].annotation, *ui._measurement_artists[0].temps)]
    menu = ui.create_result_context_menu(entry, ui._measurement_artists[0].temps[0])
    size_action = next(a for a in menu.actions() if a.text() == "字号")
    size_menu = size_action.menu()
    next(a for a in size_menu.actions() if a.text() == "24").trigger()
    editor = ui._measurement_artists[0]
    assert editor.temps[0].get_fontsize() == 24
    assert editor.annotation.get_fontsize() == original_sizes[0]
    assert editor.temps[1].get_fontsize() == original_sizes[2]
    menu = ui.create_result_context_menu(entry, editor.temps[0])
    next(a for a in menu.actions() if a.text() == "隐藏此文字").trigger()
    editor = ui._measurement_artists[0]
    assert not editor.temps[0].get_visible() and editor.temps[1].get_visible() and editor.annotation.get_visible()
    ui.style_result(entry, "size", 18, "result")
    ui.style_result(entry, "hidden", True, "t2")
    ui.style_result(entry, "hidden", True, "result")
    assert all(not text.get_visible() for text in (ui._measurement_artists[0].annotation, *ui._measurement_artists[0].temps))
    graph = ui.create_plot_context_menu()
    visibility_action = next(a for a in graph.actions() if a.text() == "分析文字显隐")
    visibility_menu = visibility_action.menu()
    result_action = visibility_menu.actions()[0]
    result_menu = result_action.menu()
    assert [a.text() for a in result_menu.actions()][0].startswith("H = ")
    assert result_menu.actions()[1].text().startswith("T1 = ") and result_menu.actions()[2].text().startswith("T2 = ")
    result_menu.actions()[1].trigger()
    assert ui._measurement_artists[0].temps[0].get_visible()
    path = tmp_path / "individual-labels.tmas"
    save_session(path, ui.curves, ui.domain, ui.results, ui.plot_options)
    assert load_session(path)[2][0]["annotation"]["label_styles"] == entry["annotation"]["label_styles"]
    ui.close_all_documents(); ui.restore_session(path)
    editor = ui._measurement_artists[0]
    assert editor.temps[0].get_visible() and editor.temps[0].get_fontsize() == 24
    assert not editor.temps[1].get_visible() and not editor.annotation.get_visible()
    assert editor.annotation.get_fontsize() == 18
    assert ui.results[0]["values"] == original_values


def test_each_line_of_multiline_result_can_be_styled_hidden_dragged_and_restored(ui, tmp_path):
    from test_confirm_rescale import drag_label
    from tma_app.workspace import load_session
    ui.start_point_measurement("signal_change"); ui.confirm_measurement()
    entry = ui.results[0]
    entry["annotation"]["y_limits"] = True
    ui.redraw(); editor = ui._measurement_artists[0]
    assert len(editor.details) == 2
    assert editor.details[0].get_text().startswith("Y1 =") and editor.details[1].get_text().startswith("Y2 =")
    values = deepcopy(entry["values"])
    menu = ui.create_result_context_menu(entry, editor.details[0])
    size_action = next(a for a in menu.actions() if a.text() == "字号")
    size_menu = size_action.menu()
    next(a for a in size_menu.actions() if a.text() == "20").trigger()
    editor = ui._measurement_artists[0]
    assert editor.details[0].get_fontsize() == 20 and editor.details[1].get_fontsize() != 20
    drag_label(ui, editor.details[0], 35, 25)
    position = deepcopy(entry["annotation"]["label_offsets"]["info1"])
    ui.style_result(entry, "hidden", True, "info2")
    editor = ui._measurement_artists[0]
    assert editor.details[0].get_visible() and not editor.details[1].get_visible()
    assert editor.annotation.get_visible() and all(t.get_visible() for t in editor.temps)
    path = tmp_path / "multiline.tmas"
    save_session(path, ui.curves, ui.domain, ui.results, ui.plot_options)
    assert load_session(path)[2][0]["annotation"]["label_offsets"]["info1"] == position
    ui.close_all_documents(); ui.restore_session(path)
    editor = ui._measurement_artists[0]
    assert editor.details[0].get_fontsize() == 20 and not editor.details[1].get_visible()
    assert list(editor.details[0].xyann) == position and ui.results[0]["values"] == values
