"""Closing data must release its Python buffers as well as its Qt controls."""
import gc
import weakref
import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication
from test_feature_ui import ui
from tma_app.reader import Dataset,Signal
from test_feature_ui import source


def settle():
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    QApplication.processEvents()
    gc.collect()  # This helper is only called on the Qt GUI thread.


def loaded_refs(ui,tmp_path):
    t=np.linspace(0,30,100000)
    ds=Dataset(tmp_path/'large.001',[Signal('Time','min'),Signal('Temperature','°C'),Signal('Dimension Change','µm')],
        np.column_stack((t,30+t*7,5+np.sin(t)*100+t*t)),{},[],'synthetic')
    ui.finish_import([ds],[]);ui.process('smooth')
    curve=ui.selected();curve.checkpoint()
    ui.start_point_measurement('dimension_change');ui.confirm_measurement()
    ui.canvas.draw()
    doc=ui.active_document()
    return {'curve':weakref.ref(curve),'raw':weakref.ref(ds.values),'working':weakref.ref(curve.working),
            'history':weakref.ref(curve.history[-1][0]),'document':weakref.ref(doc),
            'figure':weakref.ref(doc.figure),'canvas':weakref.ref(doc.canvas)}


@pytest.mark.parametrize('method',['close_all_documents','close_active_document','remove_selected'])
def test_close_last_document_releases_data_plot_and_history(ui,tmp_path,method):
    refs=loaded_refs(ui,tmp_path)
    getattr(ui,method)();settle()
    assert not ui.curves and not ui.documents and not ui.results
    assert not ui._plot_artists and not ui._measurement_artists and not ui._result_annotations
    assert ui._last_document is None
    assert ui.figure is ui._default_figure and ui.canvas is ui._default_canvas
    assert all(ref() is None for ref in refs.values()), {name for name,ref in refs.items() if ref() is not None}


def test_close_then_open_again_rebuilds_valid_controls_and_measurements(ui,tmp_path):
    refs=loaded_refs(ui,tmp_path);ui.close_active_document();settle()
    ui.range_enabled.setChecked(True);ui.range_enabled.setChecked(False)
    ui.finish_import([source(tmp_path/'again.001')],[]);ui.canvas.draw()
    assert ui.active_document() is not None and ui.canvas is ui.active_document().canvas
    assert ui.figure is not ui._default_figure and ui._plot_artists
    ui.start_point_measurement('signal_max');ui.confirm_measurement()
    assert ui.results[0]['values']['value']==9
    assert all(ref() is None for ref in refs.values())


@pytest.mark.parametrize('method',['close_active_document','remove_selected'])
def test_close_active_with_another_document_keeps_survivor_exact(ui,tmp_path,method):
    ui.finish_import([source(tmp_path/'survivor.001')],[])
    survivor=ui.selected();expected=tuple(a.copy() for a in survivor.xy(ui.domain))
    refs=loaded_refs(ui,tmp_path)
    getattr(ui,method)();settle()
    assert len(ui.curves)==len(ui.documents)==1 and ui.selected() is survivor
    assert ui.figure is ui.active_document().figure
    shown=next((x,y) for c,x,y in ui._plot_artists if c is survivor)
    for actual,wanted in zip(shown,expected):np.testing.assert_array_equal(actual,wanted)
    assert all(ref() is None for ref in refs.values())


def test_close_overlay_keeps_sources_and_releases_overlay_canvas(ui,tmp_path):
    ui.finish_import([source(tmp_path/'a.001'),source(tmp_path/'b.001')],[])
    originals=list(ui.curves)
    ui.show_overlay();doc=ui.active_document();ref=weakref.ref(doc.figure)
    doc.close();del doc;settle()
    assert len(ui.curves)==len(ui.documents)==2 and ui.curves==originals
    assert not ui._is_overlay(ui.active_document().key)
    assert ui.figure is ui.active_document().figure and ref() is None


def test_close_inactive_document_keeps_current_canvas_and_coordinates(ui,tmp_path):
    ui.finish_import([source(tmp_path/'a.001'),source(tmp_path/'b.001')],[])
    current=ui.active_document();canvas=ui.canvas
    expected=tuple(a.copy() for a in ui.selected().xy(ui.domain))
    inactive=next(doc for doc in ui.documents.values() if doc is not current)
    ref=weakref.ref(inactive);inactive.close();del inactive;settle()
    assert ui.active_document() is current and ui.canvas is canvas and ref() is None
    shown=next((x,y) for c,x,y in ui._plot_artists if c is ui.selected())
    for actual,wanted in zip(shown,expected):np.testing.assert_array_equal(actual,wanted)
    assert ui.span.canvas is canvas


def test_pending_resize_after_last_close_never_touches_deleted_canvas(ui,tmp_path):
    refs=loaded_refs(ui,tmp_path)
    ui._plot_resize_timer.start(60)
    ui.close_active_document()
    assert not ui._plot_resize_timer.isActive()
    settle();ui._redraw_after_resize();ui.redraw()
    assert all(ref() is None for ref in refs.values())


@pytest.mark.parametrize('method',['close_all_documents','close_active_document','remove_selected'])
def test_closed_import_ticket_cannot_update_reopened_same_file(ui,tmp_path,monkeypatch,method):
    from tma_app.mass_lookup import MassMatch
    import tma_app.mass_lookup as mass
    monkeypatch.setattr(mass,'configured_source',lambda:'qa-only.csv')
    path=tmp_path/'reopen.001';ds=source(path);ds._import_ticket='closed-import'
    ui.finish_import([ds],[]);assert ds._import_ticket in ui._import_mass_targets
    getattr(ui,method)();assert not ui._import_mass_targets
    new=source(path);new._import_ticket='new-import'
    ui.finish_import([new],[])
    current=ui.selected().dataset
    if method=='close_all_documents':assert current.document_key==ds.document_key
    ui.import_mass_ready('closed-import',current.name,'qa-only.csv',MassMatch(.23,'old.csv','mg','old result'))
    assert 'LookupMass' not in current.metadata
    ui.import_mass_ready('new-import',current.name,'qa-only.csv',MassMatch(.51,'new.csv','mg','new result'))
    assert current.metadata['LookupMass']==['0.51']
