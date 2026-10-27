"""Undo bookkeeping owns identities, never numerical history buffers."""
from copy import deepcopy
from dataclasses import replace
import gc
import weakref
import numpy as np
import pytest
from PySide6.QtCore import QEventLoop,QTimer
from PySide6.QtWidgets import QApplication
from test_feature_ui import ui,source,set_combo
from tma_app.signals_dialog import SignalsDialog
from tma_app.workspace import Curve,checkpoint_token


def loaded(ui,tmp_path,multiple=False):
    ui.finish_import([source(tmp_path/'source.001')],[]);ui.show_normal()
    if multiple:
        dialog=SignalsDialog(ui);set_combo(dialog.signals[1],ui.selected().dataset.signals[2].label);dialog.accept()
    for curve in ui.curves:
        curve.working=curve.base_y.copy()+2;curve.y_type='custom';curve.operations=['normalize']
    return ui.selected().dataset


def limits():
    return dict(kind='time',start=1.,stop=5.,delay=0.,all_cycles=False,reset_time=False)


def select(ui,uid):ui.refresh_curve(uid)


def test_checkpoint_tokens_are_unique_preserved_by_copy_and_not_restored_attributes(tmp_path):
    curve=Curve(source(tmp_path/'checkpoint.001'));curve.checkpoint();first=checkpoint_token(curve.history[-1])
    curve.checkpoint();second=checkpoint_token(curve.history[-1])
    assert first and first!=second and checkpoint_token(deepcopy(curve.history[-1]))==second
    curve.undo();assert not hasattr(curve,'_undo_token')
    curve.undo();assert not hasattr(curve,'_undo_token')
    # Old in-memory states without the private marker remain ordinary undo.
    curve.history=[(None,['legacy'],2.,3.,4.,'normal','normal',0.)]
    assert checkpoint_token(curve.history[-1]) is None
    curve.undo();assert curve.operations==['legacy'] and curve.x_shift==2 and curve.scale==3


def test_cleared_history_releases_buffer_before_metadata_cleanup(ui,tmp_path):
    ds=loaded(ui,tmp_path);ui.apply_data_limits(ds,None)
    curve=ui.selected();ref=weakref.ref(curve.history[-1][0]);token=checkpoint_token(curve.history[-1])
    transaction=ui._limits_undo[token]
    assert transaction['checkpoints']=={curve.uid:token}
    assert isinstance(token,str)
    ui.y_changed(1);gc.collect()
    assert not ui.selected().history and ref() is None
    # Retaining even the old metadata dictionary cannot pin the array.
    assert transaction['checkpoints']=={curve.uid:token}
    ui._prune_limits_undo();assert not ui._limits_undo and ui._limits_cleanup_signature is None


@pytest.mark.parametrize('replace_history',[False,True])
def test_working_and_saved_smoothing_buffers_are_not_pinned(ui,tmp_path,replace_history):
    ds=loaded(ui,tmp_path);curve=ui.selected()
    curve.smooth_source=curve.working.copy();curve.smooth_domain='temperature';curve.smooth_base_ops=['normalize']
    ui.apply_data_limits(ds,None);curve=ui.selected()
    refs=[weakref.ref(curve.history[-1][0]),weakref.ref(curve.history[-1][8]['smooth_source'])]
    if replace_history:curve.history=[]
    else:curve.history.clear()
    gc.collect()
    assert all(ref() is None for ref in refs) and ui._limits_undo
    ui._prune_limits_undo();assert not ui._limits_undo


def test_partial_group_keeps_atomic_undo_rule_without_pinning_cleared_member(ui,tmp_path):
    ds=loaded(ui,tmp_path,True);ui.apply_data_limits(ds,limits())
    first,second=ui.curves;first_id,second_id=first.uid,second.uid
    first_ref=weakref.ref(first.history[-1][0]);second_ref=weakref.ref(second.history[-1][0])
    second_token=checkpoint_token(second.history[-1]);before=second.working.copy()
    select(ui,first_id);ui.y_changed(1);gc.collect()
    assert first_ref() is None and second_ref() is not None
    ui._prune_limits_undo();assert set(ui._limits_undo)=={second_token}
    select(ui,second_id);history=len(ui.selected().history);ui.undo()
    assert len(ui.selected().history)==history and '请先撤销' in ui.statusBar().currentMessage()
    np.testing.assert_array_equal(ui.selected().working,before)
    ui.y_changed(1);ui._prune_limits_undo();gc.collect()
    assert second_ref() is None and not ui._limits_undo


def test_buried_group_remains_available_after_newer_processing_is_undone(ui,tmp_path):
    ds=loaded(ui,tmp_path,True)
    before={c.uid:c.working.copy() for c in ui.curves};uids=list(before)
    ui.apply_data_limits(ds,limits());tokens=set(ui._limits_undo)
    select(ui,uids[0]);ui.process('derivative');ui._prune_limits_undo()
    assert set(ui._limits_undo)==tokens
    select(ui,uids[1]);ui.undo();assert '请先撤销' in ui.statusBar().currentMessage()
    select(ui,uids[0]);ui.undo();ui._prune_limits_undo();assert set(ui._limits_undo)==tokens
    select(ui,uids[1]);ui.undo()
    assert all(c.data_indices is None for c in ui.curves) and not ui._limits_undo
    for curve in ui.curves:np.testing.assert_array_equal(curve.working,before[curve.uid])


def test_deliberate_history_copies_keep_the_same_logical_group(ui,tmp_path):
    ds=loaded(ui,tmp_path,True);before={c.uid:c.working.copy() for c in ui.curves}
    ui.apply_data_limits(ds,limits());tokens=set(ui._limits_undo)
    for curve in ui.curves:curve.history=deepcopy(curve.history)
    ui._prune_limits_undo();assert set(ui._limits_undo)==tokens
    ui.undo();assert not ui._limits_undo and all(c.data_indices is None for c in ui.curves)
    for curve in ui.curves:np.testing.assert_array_equal(curve.working,before[curve.uid])


def test_copied_token_on_another_uid_cannot_undo_the_original_group(ui,tmp_path):
    ds=loaded(ui,tmp_path);ui.apply_data_limits(ds,limits());original=ui.selected()
    token=checkpoint_token(original.history[-1])
    duplicate=replace(original,uid='independent-copy',history=list(original.history))
    ui.curves.append(duplicate);ui.rebuild_files();select(ui,duplicate.uid);ui.undo()
    assert original.data_indices==[1,2,3,4,5] and original.history
    assert duplicate.data_indices is None and not duplicate.history and token in ui._limits_undo
    ui.curves=[c for c in ui.curves if c.uid!=duplicate.uid];ui.rebuild_files();select(ui,original.uid);ui.undo()
    assert original.data_indices is None and not ui._limits_undo


def test_cleanup_is_coalesced_and_skips_unchanged_histories(ui,tmp_path,monkeypatch):
    import tma_app.classic as module
    ds=loaded(ui,tmp_path);prunes=[];original=ui._prune_limits_undo
    def counted():prunes.append(1);return original()
    monkeypatch.setattr(ui,'_prune_limits_undo',counted)
    ui.apply_data_limits(ds,None);timer=ui._limits_cleanup_timer;timer_id=timer.timerId()
    for _ in range(500):ui.touch()
    assert timer.isActive() and timer.timerId()==timer_id and not prunes
    loop=QEventLoop();QTimer.singleShot(260,loop.quit);loop.exec()
    assert len(prunes)==1 and not timer.isActive()
    calls=[];get=module.checkpoint_token
    def marker(state):calls.append(1);return get(state)
    monkeypatch.setattr(module,'checkpoint_token',marker)
    original();assert len(calls)==len(ui.curves)
    assert ui._limits_undo


def test_same_length_history_rebuild_is_detected(ui,tmp_path):
    ds=loaded(ui,tmp_path);ui.apply_data_limits(ds,None);curve=ui.selected();ui._prune_limits_undo()
    count=len(curve.history);identity=id(curve.history);curve.history.clear()
    for _ in range(count):curve.checkpoint()
    assert len(curve.history)==count and id(curve.history)==identity
    ui._prune_limits_undo();assert not ui._limits_undo


def test_close_stops_pending_cleanup_without_waiting(ui,tmp_path):
    ds=loaded(ui,tmp_path);ui.apply_data_limits(ds,None);timer=ui._limits_cleanup_timer
    assert timer.isActive();ui.close();assert not timer.isActive()
    ui._prune_limits_undo();QApplication.processEvents()
