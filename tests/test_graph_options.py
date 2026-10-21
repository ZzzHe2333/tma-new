"""Ordinary-graph drafts stay isolated from other documents and imported data."""
from copy import deepcopy

import numpy as np
import pytest
from matplotlib.figure import Figure
from PySide6.QtWidgets import QApplication, QDialog

from test_point_interaction import ui
from tma_app.graph_options import GraphOptionsDialog, STYLE_ITEMS, render_style
from tma_app.reader import Dataset


def set_value(box, value):
    index = box.findData(value)
    assert index >= 0
    box.setCurrentIndex(index)


def second_document(ui):
    source = ui.curves[0].dataset
    dataset = Dataset(source.path.with_name('second.002'), source.signals, source.values.copy(),
                      source.metadata, [], 'second-hash')
    ui.finish_import([dataset], [])
    QApplication.processEvents()
    return ui.curves[-1]


def test_cancel_draft_keeps_objects_data_selection_and_other_document(ui):
    current = second_document(ui)
    uid, document = current.uid, ui.mdi.activeSubWindow()
    objects = list(ui.curves)
    state = [(c.style, c.color, c.marker) for c in ui.curves]
    options = deepcopy(ui.plot_options)
    source = current.dataset.values.copy()
    ui.dirty = False
    dialog = GraphOptionsDialog(ui)
    assert (dialog.width(), dialog.height()) == (522, 380)
    dialog.y_name.setText('discarded')
    set_value(dialog.line_type, '--')
    set_value(dialog.color, '#ff0000')
    dialog.set_symbol_list(['s', 'D'])
    set_value(dialog.grid_type, 2)
    set_value(dialog.differentiate, 'curves')
    dialog.show_axis.setChecked(False)
    dialog.store_axis()
    dialog.defaults()
    dialog.reject()
    assert ui.curves == objects
    assert [(c.style, c.color, c.marker) for c in ui.curves] == state
    assert ui.plot_options == options
    assert ui.selected().uid == uid
    assert ui.mdi.activeSubWindow() is document
    assert not ui.dirty
    np.testing.assert_array_equal(source, current.dataset.values)


def test_apply_updates_only_active_document_preserves_uid_and_mdi_after_events(ui):
    current = second_document(ui)
    first = ui.curves[0]
    first_state = (first.style, first.color, first.marker)
    document, uid = ui.mdi.activeSubWindow(), current.uid
    first_options = deepcopy(ui.plot_options.get(str(first.dataset.path)))
    source = current.dataset.values.copy()
    dialog = GraphOptionsDialog(ui)
    dialog.x_name.setText('Test X')
    dialog.y_name.setText('Test Y')
    set_value(dialog.line_type, '--')
    set_value(dialog.color, '#ff0000')
    set_value(dialog.grid_type, 2)
    set_value(dialog.spacing, 'fine')
    dialog.set_symbol_list(['D'])
    dialog.show_axis.setChecked(False)
    dialog.show_symbols.setChecked(True)
    dialog.accept()
    QApplication.processEvents()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert ui.curves[1] is current
    assert ui.selected().uid == uid
    assert ui.mdi.activeSubWindow() is document
    assert (first.style, first.color, first.marker) == first_state
    assert ui.plot_options.get(str(first.dataset.path)) == first_options
    assert (current.style, current.color, current.marker) == ('--', '#ff0000', 'D')
    options = ui.plot_options[str(current.dataset.path)]
    assert options['x_label'] == 'Test X' and options['y_labels'][0] == 'Test Y'
    assert options['graph_grid_types'] == [2] * 4
    assert options['graph_symbol_spacing'][0] == 'fine'
    assert options['graph_axis_visible'][0] is False
    np.testing.assert_array_equal(source, current.dataset.values)


def test_clear_symbols_and_unsupported_native_choices(ui):
    current = ui.curves[0]
    current.marker = 's'
    dialog = GraphOptionsDialog(ui)
    set_value(dialog.symbol_type, 'none')
    dialog.accept()
    assert current.marker == ''
    assert not dialog.symbol_type.model().item(dialog.symbol_type.findData('digits')).isEnabled()
    assert not dialog.symbol_type.model().item(dialog.symbol_type.findData('letters')).isEnabled()
    item = dialog.line_type.model().item(dialog.line_type.findData('multiline'))
    assert not item.isEnabled() and item.toolTip()


def test_extended_native_style_renderers_are_real_matplotlib_dash_patterns():
    axis = Figure().subplots()
    for code in ('long_dash', 'broken_dash', 'broken_double_dash'):
        line, = axis.plot([0, 1], [1, 2], linestyle=render_style(code))
        assert line.is_dashed()
    assert len(STYLE_ITEMS) == 9
    with pytest.raises(ValueError):
        render_style('multiline')


def test_closed_document_does_not_partially_apply(ui):
    current = ui.curves[0]
    old = (current.style, current.color, current.marker)
    dialog = GraphOptionsDialog(ui)
    set_value(dialog.line_type, '--')
    ui.documents.pop(dialog.key)
    assert not dialog.apply()
    assert (current.style, current.color, current.marker) == old
    assert '关闭' in dialog.error.text()


def test_accept_without_style_edits_preserves_distinct_existing_curves(ui):
    from dataclasses import replace
    import uuid
    current = ui.curves[0]
    current.marker, current.color = 's', '#000000'
    duplicate = replace(current, uid=uuid.uuid4().hex, marker='D', color='#ff0000', style='--')
    ui.curves.append(duplicate)
    ui.rebuild_files()
    dialog = GraphOptionsDialog(ui)
    dialog.y_name.setText('Axis only')
    dialog.accept()
    assert (current.marker, current.color, current.style) == ('s', '#000000', '-')
    assert (duplicate.marker, duplicate.color, duplicate.style) == ('D', '#ff0000', '--')


def multi_axis_curves(ui):
    from dataclasses import replace
    import uuid
    first = ui.curves[0]
    first.marker, first.color = 'o', '#000000'
    second = replace(first, uid=uuid.uuid4().hex, axis=1, marker='s', color='#ff0000', style='--')
    third = replace(first, uid=uuid.uuid4().hex, axis=0, marker='D', color='#0000ff', style=':')
    fourth = replace(first, uid=uuid.uuid4().hex, axis=2, marker='^', color='#008000', style='-.')
    ui.curves.extend([second, third, fourth])
    ui.rebuild_files()
    ui.files.setCurrentItem(ui.files.topLevelItem(0))
    return [first, second, third, fourth]


def test_global_grid_survives_axis_switch_without_reassigning_symbols_or_styles(ui):
    curves = multi_axis_curves(ui)
    before = [(c.marker, c.color, c.style) for c in curves]
    dialog = GraphOptionsDialog(ui)
    set_value(dialog.grid_type, 2)
    dialog.switch_axis(1)
    assert dialog.grid_type.currentData() == 2
    assert dialog.options['graph_grid_types'] == [2] * 4
    set_value(dialog.grid_type, 1)
    dialog.switch_axis(2)
    assert dialog.grid_type.currentData() == 1
    dialog.switch_axis(0)
    assert dialog.grid_type.currentData() == 1
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert ui.plot_options[dialog.key]['graph_grid_types'] == [1] * 4
    assert [(c.marker, c.color, c.style) for c in curves] == before


def test_differentiation_is_global_and_curves_use_whole_document_order(ui, tmp_path):
    from tma_app.workspace import save_session, load_session
    curves = multi_axis_curves(ui)
    dialog = GraphOptionsDialog(ui)
    symbols = ['o', 's', 'D', '^']
    for axis in (0, 1, 2):
        dialog.switch_axis(axis)
        dialog.set_symbol_list(symbols)
    set_value(dialog.differentiate, 'curves')
    dialog.switch_axis(0)
    assert dialog.differentiate.currentData() == 'curves'
    assert [c.marker for c in dialog.draft] == ['o', 's', 'D', '^']
    dialog.switch_axis(1)
    assert dialog.differentiate.currentData() == 'curves'
    dialog.accept()
    assert [c.marker for c in curves] == ['o', 's', 'D', '^']
    assert ui.plot_options[dialog.key]['graph_symbol_differentiate'] == 'curves'
    path = tmp_path / 'global-symbols.tmas'
    save_session(path, ui.curves, ui.domain, ui.results, ui.plot_options)
    restored, _, _, options = load_session(path, include_plot_options=True)
    assert [c.marker for c in restored] == ['o', 's', 'D', '^']
    assert options[dialog.key]['graph_symbol_differentiate'] == 'curves'
    reopened = GraphOptionsDialog(ui)
    assert reopened.differentiate.currentData() == 'curves'
    reopened.switch_axis(2)
    assert reopened.differentiate.currentData() == 'curves'
    reopened.reject()


def test_global_axes_differentiation_updates_all_symbol_axes(ui):
    from tma_app.workspace import default_plot_options
    multi_axis_curves(ui)
    ui.plot_options.setdefault(str(ui.curves[0].dataset.path), default_plot_options())['graph_symbol_differentiate'] = 'curves'
    dialog = GraphOptionsDialog(ui)
    symbols = ['o', 's', 'D', '^']
    for axis in (0, 1, 2):
        dialog.switch_axis(axis)
        dialog.set_symbol_list(symbols)
    set_value(dialog.differentiate, 'axes')
    dialog.accept()
    assert [c.marker for c in ui.curves] == ['o', 's', 'o', 'D']
    assert ui.plot_options[dialog.key]['graph_symbol_differentiate'] == 'axes'


def test_axis_visibility_and_symbol_spacing_remain_per_axis(ui):
    multi_axis_curves(ui)
    dialog = GraphOptionsDialog(ui)
    dialog.show_axis.setChecked(False)
    set_value(dialog.spacing, 'fine')
    dialog.switch_axis(1)
    assert dialog.show_axis.isChecked()
    assert dialog.spacing.currentData() == 'medium'
    dialog.accept()
    options = ui.plot_options[dialog.key]
    assert options['graph_axis_visible'] == [False, True, True, True]
    assert options['graph_symbol_spacing'] == ['fine', 'medium', 'medium', 'medium']


@pytest.mark.parametrize('style', ['long_dash', 'broken_dash', 'broken_double_dash'])
def test_extended_styles_apply_render_and_roundtrip_on_selected_document(ui, tmp_path, style):
    from tma_app.workspace import save_session, load_session
    current = second_document(ui)
    document, uid = ui.mdi.activeSubWindow(), current.uid
    dialog = GraphOptionsDialog(ui)
    set_value(dialog.line_type, style)
    dialog.accept()
    QApplication.processEvents()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert current.style == style
    assert ui.selected().uid == uid and ui.mdi.activeSubWindow() is document
    assert any(line.is_dashed() for line in ui.axes[0].lines)
    path = tmp_path / 'graph-session.tmas'
    save_session(path, ui.curves, ui.domain, ui.results, ui.plot_options)
    restored, _, _, options = load_session(path, include_plot_options=True)
    assert next(c for c in restored if c.uid == uid).style == style
    assert options[document.key]['graph_axis_visible'] == [True] * 4
