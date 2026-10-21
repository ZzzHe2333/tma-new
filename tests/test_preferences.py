"""Page-scoped defaults are inert, isolated, strict, and atomically replaced."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from tma_app import preferences as prefs
from tma_app.workspace import default_plot_options


def appearance(axis=0, **overrides):
    values = dict(axis=axis, style='-', color='#000000', marker='', offset=0.,
                  uid='do-not-save-uid', dataset='C:/do-not-save/source.001',
                  legend_text='do-not-save-sample', filename='do-not-save-filename')
    values.update(overrides)
    return SimpleNamespace(**values)


def test_missing_file_and_default_location_do_not_create_file(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    expected = tmp_path / 'TMA-Studio/preferences.json'
    assert prefs.preferences_path() == expected
    assert prefs.load_defaults('overlay') == {'options': {}, 'curves': [[], [], [], []]}
    assert not expected.exists()


def test_page_save_preserves_other_pages_and_other_scope(tmp_path):
    path = tmp_path / 'defaults.json'
    opts = default_plot_options()
    opts.update(title='Saved heading', x_label='Excluded X', y_labels=['Excluded Y']*4,
                legend_border=True, grid_x=True, auto_x=False)
    prefs.save_defaults('graph', 'graph', opts, [appearance(marker='D')], path=path)
    graph_before = prefs.load_defaults('graph', path=path)
    prefs.save_defaults('overlay', 'title', opts, path=path)
    prefs.save_defaults('overlay', 'legend', opts, path=path)
    prefs.save_defaults('overlay', 'grid', opts, path=path)
    loaded = prefs.load_defaults('overlay', path=path)
    assert loaded['options']['title'] == 'Saved heading'
    assert loaded['options']['legend_border'] is True
    assert loaded['options']['grid_x'] is True
    assert 'auto_x' not in loaded['options']
    assert 'x_label' not in loaded['options'] and 'y_labels' not in loaded['options']
    assert prefs.load_defaults('graph', path=path) == graph_before
    changed = deepcopy(opts); changed['title'] = 'Only title changes'; changed['legend_border'] = False
    prefs.save_defaults('overlay', 'title', changed, path=path)
    assert prefs.load_defaults('overlay', path=path)['options']['legend_border'] is True
    assert prefs.load_defaults('overlay', path=path)['options']['title'] == 'Only title changes'


def test_curves_are_ordered_four_axis_appearance_only_without_source_metadata(tmp_path):
    path = tmp_path / 'preferences.json'
    curves = [appearance(1, color='#ff0000', offset=5), appearance(0),
              appearance(1, style='long_dash', marker='D', offset=-3)]
    prefs.save_defaults('overlay', 'curves', {'title': 'not this page'}, curves, path=path)
    loaded = prefs.load_defaults('overlay', path=path)
    assert loaded['options'] == {}
    assert loaded['curves'][1] == [
        {'style': '-', 'color': '#ff0000', 'marker': '', 'offset': 5.},
        {'style': 'long_dash', 'color': '#000000', 'marker': 'D', 'offset': -3.}]
    assert loaded['curves'][2:] == [[], []]
    raw = path.read_text(encoding='utf8')
    assert 'do-not-save' not in raw
    assert 'uid' not in raw and 'dataset' not in raw and 'legend_text' not in raw


def test_graph_appearance_does_not_store_axis_names_or_curve_offsets(tmp_path):
    path = tmp_path / 'preferences.json'
    options = default_plot_options(); options.update(x_label='sample X', y_labels=['sample Y']*4)
    prefs.save_defaults('graph', 'graph', options, [appearance(2, marker='s', offset=123)], path=path)
    loaded = prefs.load_defaults('graph', path=path)
    assert set(loaded['options']) == set(prefs.PAGE_FIELDS['graph']['graph'])
    assert loaded['curves'][2] == [{'style': '-', 'color': '#000000', 'marker': 's'}]
    assert 'offset' not in path.read_text(encoding='utf8')


def test_axes_page_excludes_names_and_preserves_other_preferences(tmp_path):
    path = tmp_path / 'preferences.json'
    prefs.save_defaults('overlay', 'title', {'title': 'keep'}, path=path)
    prefs.save_defaults('overlay', 'axes', {'x_label': 'not a default', 'y_labels': ['no']*4,
                                          'title': 'not axes', 'auto_y': [False]*4}, path=path)
    assert prefs.load_defaults('overlay', path=path)['options'] == {'title': 'keep'}
    stored = json.loads(path.read_text())
    assert stored['scopes']['overlay']['axes']['options'] == {}


def test_grouped_appearance_roundtrip_is_independent_copy(tmp_path):
    path = tmp_path / 'preferences.json'
    grouped = [[{'style': '--', 'color': '#123456', 'marker': 'x', 'offset': 2}], [], [], []]
    prefs.save_defaults('overlay', 'curves', {}, grouped, path=path)
    first = prefs.load_defaults('overlay', path=path)
    first['curves'][0][0]['color'] = '#ffffff'
    assert prefs.load_defaults('overlay', path=path)['curves'] == grouped


@pytest.mark.parametrize('existing', [b'not json', b'[]', b'{"format":"unknown"}',
                                      b'{"format":"tma-studio-preferences","version":1,"scopes":NaN}',
                                      b'{"format":"tma-studio-preferences","version":1,"version":1,"scopes":{}}',
                                      b'\xff\xfeinvalid utf8'])
def test_invalid_existing_file_is_reported_and_never_overwritten(tmp_path, existing):
    path = tmp_path / 'preferences.json'; path.write_bytes(existing)
    with pytest.raises(ValueError): prefs.load_defaults('overlay', path=path)
    with pytest.raises(ValueError): prefs.save_defaults('overlay', 'title', {'title': 'replacement'}, path=path)
    assert path.read_bytes() == existing


def test_valid_json_with_invalid_saved_page_data_is_not_silently_accepted(tmp_path):
    path = tmp_path / 'preferences.json'
    prefs.save_defaults('graph', 'graph', default_plot_options(), path=path)
    data = json.loads(path.read_text()); data['scopes']['graph']['graph']['options']['graph_axis_visible'] = [1]*4
    path.write_text(json.dumps(data)); original = path.read_bytes()
    with pytest.raises(ValueError): prefs.load_defaults('graph', path=path)
    with pytest.raises(ValueError): prefs.save_defaults('overlay', 'title', {'title': 'x'}, path=path)
    assert path.read_bytes() == original


@pytest.mark.parametrize('curve', [appearance(axis=True), appearance(axis=4), appearance(style='multiline'),
                                    appearance(color='red'), appearance(marker='not-marker'),
                                    appearance(offset=float('nan')), appearance(offset=True)])
def test_invalid_appearance_does_not_replace_old_preferences(tmp_path, curve):
    path = tmp_path / 'preferences.json'
    prefs.save_defaults('overlay', 'title', {'title': 'original'}, path=path)
    original = path.read_bytes()
    with pytest.raises(ValueError): prefs.save_defaults('overlay', 'curves', {}, [curve], path=path)
    assert path.read_bytes() == original


def test_overfull_slots_fail_instead_of_silently_truncating(tmp_path):
    path = tmp_path / 'preferences.json'
    with pytest.raises(ValueError):
        prefs.save_defaults('overlay', 'curves', {}, [appearance() for _ in range(11)], path=path)
    assert not path.exists()


def test_replace_failure_keeps_old_file_and_removes_temporary(tmp_path, monkeypatch):
    path = tmp_path / 'preferences.json'
    prefs.save_defaults('overlay', 'title', {'title': 'original'}, path=path)
    original = path.read_bytes()
    def fail_replace(*_): raise OSError('simulated disk/replace failure')
    monkeypatch.setattr(prefs.os, 'replace', fail_replace)
    with pytest.raises(OSError): prefs.save_defaults('overlay', 'title', {'title': 'new'}, path=path)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize('scope,page', [('other', 'title'), ('graph', 'legend'), ('overlay', 'unknown')])
def test_invalid_scope_page_is_explicit(tmp_path, scope, page):
    with pytest.raises(ValueError): prefs.save_defaults(scope, page, {}, path=tmp_path/'preferences.json')
