"""Unvisited MDI graphs allocate their renderer only when actually drawn."""
import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from shiboken6 import isValid
from test_feature_ui import ui,source


def loaded(ui,tmp_path,count=8):
    ui.finish_import([source(tmp_path/f'sample-{i}.001') for i in range(count)],[])
    QApplication.processEvents();QApplication.processEvents()
    return list(ui.documents.values())


def test_import_never_draws_blank_unvisited_graphs(ui,tmp_path,monkeypatch):
    calls=[];draw=FigureCanvasQTAgg.draw
    def recorded(canvas,*args,**kwargs):
        calls.append((canvas,len(canvas.figure.axes)))
        return draw(canvas,*args,**kwargs)
    monkeypatch.setattr(FigureCanvasQTAgg,'draw',recorded)
    docs=loaded(ui,tmp_path);active=ui.active_document()
    own=[entry for entry in calls if any(entry[0] is doc.canvas for doc in docs)]
    assert own and all(axis_count>0 for canvas,axis_count in own)
    assert sum(hasattr(doc.canvas,'renderer') for doc in docs)==1
    assert active.canvas.plot_ready and hasattr(active.canvas,'renderer')
    assert all(not doc.canvas.plot_ready and not hasattr(doc.canvas,'renderer') for doc in docs if doc is not active)
    for doc in docs:
        ui._show_document(doc.key);QApplication.processEvents()
        assert doc.canvas.plot_ready and hasattr(doc.canvas,'renderer')
        curve=ui.selected();assert curve.dataset.document_key==doc.key
        x,y=curve.xy(ui.domain);shown=next((a,b) for c,a,b in ui._plot_artists if c.uid==curve.uid)
        np.testing.assert_array_equal(x,shown[0]);np.testing.assert_array_equal(y,shown[1])
        assert ui.table.model().curve is curve


def test_resize_unvisited_document_does_not_allocate_renderer(ui,tmp_path):
    docs=loaded(ui,tmp_path,2);active=ui.active_document();hidden=next(doc for doc in docs if doc is not active)
    hidden.canvas.resize(hidden.canvas.width()-40,hidden.canvas.height()-20)
    QApplication.processEvents();QApplication.processEvents()
    assert ui.active_document() is active
    assert not hidden.canvas.plot_ready and not hasattr(hidden.canvas,'renderer') and not hidden.canvas._draw_pending
    ui._show_document(hidden.key);QApplication.processEvents()
    assert hidden.canvas.plot_ready and hidden.layout_size==hidden.canvas.get_width_height(physical=True)
    assert ui._plot_artists and len(ui.axes[0].lines)>0


def test_explicit_draw_remains_available_before_first_curve_display(ui,tmp_path):
    docs=loaded(ui,tmp_path,2);hidden=next(doc for doc in docs if doc is not ui.active_document())
    hidden.canvas.draw()
    assert hasattr(hidden.canvas,'renderer') and not hidden.canvas.plot_ready
    ui._show_document(hidden.key);QApplication.processEvents()
    assert hidden.canvas.plot_ready and ui._plot_artists


def test_close_unvisited_graphs_releases_controls_and_has_no_late_draw(ui,tmp_path):
    docs=loaded(ui,tmp_path)
    controls=[(doc,doc.canvas,doc.navigation) for doc in docs]
    assert any(not hasattr(canvas,'renderer') for doc,canvas,nav in controls)
    ui.close_all_documents();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    QApplication.processEvents()
    assert all(not isValid(obj) for group in controls for obj in group)
