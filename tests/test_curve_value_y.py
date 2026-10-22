"""Horizontal cursor: first acquired intersection, precise editing and native stages."""
from copy import deepcopy
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtWidgets import QDialog
from matplotlib.backend_bases import MouseEvent
from test_feature_ui import ui,imported
from test_curve_value import mark
from tma_app.measurement import position_at_y
from tma_app.workspace import save_session,load_session


def manual(ui,y):
    dialog=ui.edit_measurement_limits()
    assert dialog.fields[0].isReadOnly() and not dialog.y_fields[0].isReadOnly()
    dialog.y_fields[0].setText(str(y));dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted,dialog.error.text()
    return dialog


def test_native_horizontal_menu_two_stages_exact_y_and_document_identity(ui,tmp_path):
    imported(ui,tmp_path,3);ui.show_normal();uid=ui.selected().uid;doc=ui.active_document()
    assert ui.classic_actions['CurveValueAtY1'].isEnabled()
    ui.classic_actions['CurveValueAtY1'].trigger();entry=ui._pending_measurement
    editor=next(e for e in ui._measurement_artists if e.entry is entry)
    assert entry['kind']=='curve_value_y' and editor.hline.get_visible() and not editor.vline.get_visible()
    assert not editor.annotation.get_visible() and not ui.results
    ui.redraw()
    editor=next(e for e in ui._measurement_artists if e.entry is entry)
    assert editor.hline.get_visible() and not editor.vline.get_visible()
    manual(ui,1.25)
    assert entry['values']['y']==pytest.approx(1.25)
    assert entry['values']['x']==pytest.approx(100+3.25/11+1)
    assert entry['values']['requested_y']==1.25
    dialog=mark(ui);assert ui._pending_measurement is entry and not ui.results
    dialog.accept()
    assert ui.selected().uid==uid and ui.active_document() is doc and ui.results==[entry]
    assert not ui._measurement_artists[-1].hline.get_visible()
    path=tmp_path/'y.tmas';save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    saved=deepcopy(entry);ui.close_all_documents();ui.restore_session(path)
    assert ui.results==[saved]


@pytest.mark.parametrize('y,target,rows,expected',[
    ([0,10,0,10],5,None,.5),([10,0,10,0],5,None,.5),
    ([0,10,0,10],0,None,0),([0,5,5,10],5,None,1),
    ([0,10,0,10],5,[0,2,3,4],1.5),
])
def test_first_acquired_intersection_handles_repeated_and_flat_segments(y,target,rows,expected):
    assert position_at_y(np.array(y,dtype=float),target,rows)==expected


@pytest.mark.parametrize('target',[True,float('nan'),float('inf'),11])
def test_invalid_or_absent_y_rejected(target):
    with pytest.raises(ValueError):position_at_y(np.array([0.,10.]),target)


def test_gap_rejection_is_atomic_and_reset_restores_exact_initial_intersection(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.selected();curve.data_indices=[0,1,4,5]
    entry=ui.start_point_measurement('curve_value_y');initial=deepcopy(entry['interactive'])
    dialog=ui.edit_measurement_limits();dialog.y_fields[0].setText('.5');dialog.accept()
    assert dialog.result()!=QDialog.DialogCode.Accepted and dialog.error.text()
    assert entry['interactive']==initial
    dialog.reject();manual(ui,-1)
    ui.reset_measurement_limits()
    assert entry['interactive']['positions']==initial['positions']
    assert entry['interactive']['target_y']==initial['target_y']


def test_horizontal_line_grab_anywhere_moves_only_y_and_cancels_cleanly(ui,tmp_path):
    imported(ui,tmp_path,2);options=ui.plot_options[ui.active_document().key]
    options['axis_x_offsets'][0]=15;ui.redraw()
    entry=ui.start_point_measurement('curve_value_y');manual(ui,1.25)
    editor=next(e for e in ui._measurement_artists if e.entry is entry);ui.canvas.draw()
    assert editor.display_coords[0][0]==editor.coords[0][0]+15
    px,py=editor.axis.transData.transform(editor.display_coords[0]);px=editor.axis.bbox.x0+20
    assert editor.hit(px,py)==0
    ui.canvas.callbacks.process('button_press_event',MouseEvent('button_press_event',ui.canvas,px,py,button=1))
    assert ui._drag_measurement is not None
    target=editor.axis.transData.transform((editor.display_coords[0][0],3.))
    motion=MouseEvent('motion_notify_event',ui.canvas,px,target[1],button=1)
    expected=editor.axis.transData.inverted().transform((motion.x,motion.y))[1]
    ui.canvas.callbacks.process('motion_notify_event',motion)
    ui.canvas.callbacks.process('button_release_event',MouseEvent('button_release_event',ui.canvas,px,target[1],button=1))
    assert entry['values']['y']==pytest.approx(expected)
    assert entry['interactive']['positions'][0]==pytest.approx(position_at_y(editor.y,expected))
    mark(ui).accept();saved=deepcopy(entry)
    ui.edit_measurement(entry);ui.measurement_key(SimpleNamespace(key='ctrl+up'))
    assert ui._pending_measurement['values']['y']>saved['values']['y']
    ui.cancel_measurement();assert ui.results==[saved]


def test_untouched_compact_y_keeps_full_precision_and_manual_y_is_not_override(ui,tmp_path):
    imported(ui,tmp_path,1);entry=ui.start_point_measurement('curve_value_y')
    target=1.2345678912345;manual(ui,target);state=deepcopy(entry['interactive'])
    dialog=ui.edit_measurement_limits();dialog.accept()
    assert entry['interactive']==state and entry['values']['requested_y']==target
    assert entry['interactive']['manual_y']==[None]
    mark(ui).accept();entry['interactive']['target_y']=7.
    path=tmp_path/'invalid.tmas';save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    with pytest.raises(ValueError):load_session(path)


def test_y_cursor_cannot_confirm_from_another_document(ui,tmp_path):
    imported(ui,tmp_path,3);ui.show_normal();entry=ui.start_point_measurement('curve_value_y');source=ui.active_document()
    other=next(doc for key,doc in ui.documents.items() if key!=source.key and not ui._is_overlay(key))
    ui.mdi.setActiveSubWindow(other);ui.document_activated(other);ui.confirm_measurement()
    assert ui._pending_measurement is entry and 'label_point' not in ui.dialogs
    ui.mdi.setActiveSubWindow(source);ui.document_activated(source);mark(ui).accept()
    assert ui.results==[entry]
