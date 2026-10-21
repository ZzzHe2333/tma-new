"""Native appearance controls affect actual rendering and portable sessions."""
from copy import deepcopy
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from test_point_interaction import ui
from tma_app.classic_dialogs import OverlayOptionsDialog
from tma_app.graph_options import GraphOptionsDialog
from tma_app.workspace import save_session, load_session, validate_plot_options


def test_graph_menu_renderer_spacing_visibility_and_session(ui, tmp_path):
    raw = ui.curves[0].dataset.values.copy()
    dialog = ui.show_curve_options()
    assert isinstance(dialog, GraphOptionsDialog)
    dialog.set_symbol_list(["D"])
    dialog.spacing.setCurrentIndex(dialog.spacing.findData("every"))
    dialog.grid_type.setCurrentIndex(dialog.grid_type.findData(2))
    dialog.show_axis.setChecked(False)
    dialog.accept(); QApplication.processEvents(); ui.canvas.draw()
    line = next(line for line in ui.axes[0].lines if getattr(line, "_tma_curve_uid", None) == ui.curves[0].uid)
    assert line.get_markevery() == 1 and line.get_marker() == "D"
    assert not ui.axes[0].yaxis.get_visible()
    assert any(line.get_visible() for line in ui.axes[0].get_xgridlines())
    np.testing.assert_array_equal(raw, ui.curves[0].dataset.values)
    session = tmp_path / "appearance.tmas"
    save_session(session, ui.curves, ui.domain, ui.results, ui.plot_options)
    ui.close_all_documents(); ui.restore_session(session); ui.show_normal(); ui.canvas.draw()
    assert not ui.axes[0].yaxis.get_visible()
    dialog = ui.show_curve_options()
    dialog.show_symbols.setChecked(False); dialog.accept(); ui.canvas.draw()
    line = next(line for line in ui.axes[0].lines if getattr(line, "_tma_curve_uid", None) == ui.curves[0].uid)
    assert line.get_marker() == ""


def test_legend_content_controls_render_and_restore_without_altering_trace(ui, tmp_path):
    curve = ui.curves[0]
    curve.color = "#ff0000"; curve.marker = "D"; curve.legend_text = "custom"
    raw = curve.dataset.values.copy()
    ui.show_overlay()
    dialog = OverlayOptionsDialog(ui)
    dialog.legend.setCurrentIndex(dialog.legend.findData(True))
    for key, box in dialog.legend_boxes.items():
        box.setChecked(key in ("legend_border", "legend_file"))
    dialog.accept(); ui.canvas.draw()
    legend = ui.axes[0].get_legend()
    assert legend.get_visible() and legend.get_frame_on()
    assert [text.get_text() for text in legend.get_texts()] == [curve.dataset.path.name]
    handle = legend.legend_handles[0]
    assert handle.get_color() == "black" and handle.get_linestyle() == "None" and handle.get_marker() == ""
    actual = next(line for line in ui.axes[0].lines if getattr(line, "_tma_curve_uid", None) == curve.uid)
    assert actual.get_color() == "#ff0000" and actual.get_marker() == "D"
    np.testing.assert_array_equal(raw, curve.dataset.values)
    session = tmp_path / "legend.tmas"
    save_session(session, ui.curves, ui.domain, ui.results, ui.plot_options)
    _, _, _, settings = load_session(session, include_plot_options=True)
    assert settings["__overlay__"]["legend_file"] and not settings["__overlay__"]["legend_text"]
    before = deepcopy(ui.plot_options)
    dialog = OverlayOptionsDialog(ui)
    dialog.defaults(); dialog.reject()
    assert ui.plot_options == before


@pytest.mark.parametrize("options", [{"graph_axis_visible": [True]}, {"graph_grid_types": [0, 1, 2, 3]}, {"graph_symbol_spacing": ["every", "fine", "medium", None]}, {"legend_text": 1}])
def test_invalid_native_appearance_settings_are_rejected(options):
    with pytest.raises(ValueError): validate_plot_options(options)
