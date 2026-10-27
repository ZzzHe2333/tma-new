"""Exact numerical results, GUI responsiveness and bounded/canceled tasks."""
from concurrent.futures import CancelledError
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import queue
import threading
import time

import numpy as np
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog

from test_feature_ui import ui, set_combo, source
from tma_app.calculation import CurveSnapshot, CalculationDispatcher, calculate
from tma_app.data_limits import smoothed_state
from tma_app.reader import Dataset, Signal
from tma_app.signal_processing import local_fit, typed_signal, factory_template
from tma_app.signal_proposal import build_proposal
from tma_app.signals_dialog import SignalsDialog
from tma_app.workspace import Curve


def dataset(path, n=2400):
    t=np.linspace(0,30,n)
    return Dataset(Path(path),[Signal('Time','min'),Signal('Temperature','°C'),Signal('Dimension Change','µm')],
                   np.column_stack((t,30+t*7,np.sin(t)*100+t*t)),{'Sample':['large'],'Size':['1 mm']},[],'large')


def pump(predicate, timeout=10):
    until=time.monotonic()+timeout
    while not predicate():
        QApplication.processEvents()
        if time.monotonic()>until:pytest.fail('background calculation did not complete')
        time.sleep(.002)
    QApplication.processEvents()


def prepare(ui,tmp_path):
    ui.finish_import([dataset(tmp_path/'large.001')],[]);ui.show_normal()
    QApplication.processEvents()
    return ui.selected()


def blocked(monkeypatch):
    import tma_app.calculation as module
    original=module.calculate;entered=threading.Event();release=threading.Event();exited=threading.Event()
    def wait(request,cancelled):
        entered.set()
        try:
            while not release.wait(.005):
                if cancelled.is_set():raise CancelledError()
            return original(request,cancelled)
        finally:exited.set()
    monkeypatch.setattr(module,'calculate',wait)
    return entered,release,exited


@pytest.mark.parametrize('operation',['fit','typed','x','smooth','signals'])
def test_cancel_propagates_before_computation(operation,tmp_path):
    curve=Curve(dataset(tmp_path/'test.001'))
    curve.x_signal_index=2;curve.x_signal_type='d_time'
    stop=threading.Event();stop.set()
    operations={
        'fit':lambda:local_fit(np.arange(7.),np.arange(7.),1,cancelled=stop),
        'typed':lambda:typed_signal(curve.dataset,2,'d_time',cancelled=stop),
        'x':lambda:curve.x_values('signal',cancelled=stop),
        'smooth':lambda:smoothed_state(curve,'temperature',3,cancelled=stop),
        'signals':lambda:build_proposal([curve],curve.dataset,factory_template(curve.dataset),cancelled=stop)}
    with pytest.raises(CancelledError):operations[operation]()
    assert curve.working is None and curve.history==[] and curve._x_cache is None


def test_cancel_running_fit_stops_before_second_lstsq(monkeypatch):
    stop=threading.Event();entered=threading.Event();release=threading.Event();out=[];calls=[]
    original=np.linalg.lstsq
    def wait(*a,**kw):
        calls.append(1);entered.set();assert release.wait(5)
        return original(*a,**kw)
    monkeypatch.setattr(np.linalg,'lstsq',wait)
    def run():
        try:local_fit(np.arange(100.),np.arange(100.),2,1,cancelled=stop)
        except CancelledError:out.append('canceled')
    thread=threading.Thread(target=run);thread.start()
    assert entered.wait(5);stop.set();release.set();thread.join(5)
    assert not thread.is_alive() and out==['canceled'] and len(calls)==1


def test_snapshot_owns_buffers_but_does_not_copy_undo_or_cache(tmp_path):
    class Undo:
        def __deepcopy__(self,memo):raise AssertionError('undo copied')
    curve=Curve(dataset(tmp_path/'test.001'));curve.history=[Undo()]
    curve.working=curve.base_y.copy();curve.smooth_source=curve.base_y.copy()
    curve._x_cache=('ignored',curve.base_y.copy())
    peer=replace(curve,uid='peer')
    snapshot=CurveSnapshot([curve,peer]);worker=snapshot.worker_curves()
    assert snapshot.matches([curve,peer])
    assert worker[0].dataset is worker[1].dataset
    assert worker[0].dataset is not curve.dataset
    assert not np.shares_memory(worker[0].working,curve.working)
    assert not np.shares_memory(worker[0].dataset.values,curve.dataset.values)
    assert worker[0].history==[] and worker[0]._x_cache is None
    worker[0].operations.append('private');worker[0].file_info['Sample']='private'
    assert snapshot.matches([curve,peer])
    with pytest.raises(ValueError):worker[0].dataset.values[0,2]=0
    curve.dataset.metadata['LookupMass']=['0.47']
    assert snapshot.matches([curve,peer])


@pytest.mark.parametrize('change',['removed','replaced','dataset','raw_in_place','working_in_place','units','limits','width','file_info','history','metadata','x_config','appearance'])
def test_snapshot_rejects_changed_state(change,tmp_path):
    curve=Curve(dataset(tmp_path/'test.001'));curve.working=curve.base_y.copy()
    curves=[curve];snap=CurveSnapshot(curves)
    if change=='removed':curves=[]
    elif change=='replaced':curves=[replace(curve)]
    elif change=='dataset':curve.dataset=deepcopy(curve.dataset)
    elif change=='raw_in_place':curve.dataset.values[4,2]+=1
    elif change=='working_in_place':curve.working[4]+=1
    elif change=='units':curve.unit_options={'dimension':'µm/m'}
    elif change=='limits':curve.data_indices=[1,2,3,4,5]
    elif change=='width':curve.smooth_width=4
    elif change=='file_info':curve.file_info['Sample']='edited'
    elif change=='history':curve.history.append(('new',))
    elif change=='metadata':curve.dataset.metadata['Size']=['2 mm']
    elif change=='x_config':curve.x_signal_type='d_time'
    elif change=='appearance':curve.overlay_views['overlay::1']={'color':'red'}
    assert not snap.matches(curves)


def test_dispatcher_coalesces_bounds_queue_and_recovers_errors(monkeypatch):
    import tma_app.calculation as module
    entered=threading.Event();release=threading.Event();finished=threading.Event();seen=[]
    def work(request,cancelled):
        seen.append(request)
        if request=='block':entered.set();assert release.wait(5)
        if request=='fail':raise ValueError('expected')
        if request=='last':finished.set()
        return request
    monkeypatch.setattr(module,'calculate',work)
    dispatcher=CalculationDispatcher();stop=threading.Event();events=queue.Queue()
    dispatcher.submit('busy','block',stop,events);assert entered.wait(5)
    first=threading.Event();dispatcher.submit('same','old',first,events)
    second=threading.Event();dispatcher.submit('same','latest',second,events)
    assert first.is_set() and len(dispatcher.pending)==1
    dispatcher.cancel('same',second);assert not dispatcher.pending
    for i in range(8):dispatcher.submit(i,'fail' if i==0 else str(i),threading.Event(),events)
    with pytest.raises(ValueError):dispatcher.submit('overflow','no',threading.Event(),events)
    dispatcher.submit(7,'last',threading.Event(),events)
    release.set();assert finished.wait(5)
    assert 'old' not in seen and 'latest' not in seen and 'no' not in seen
    values=[]
    until=time.monotonic()+5
    while len(values)<9 and time.monotonic()<until:
        try:values.append(events.get(timeout=.1))
        except queue.Empty:pass
    assert ('error','expected') in values and ('result','last') in values
    assert dispatcher.thread.daemon


def test_background_smoothing_exact_responsive_and_undoable(ui,tmp_path,monkeypatch):
    curve=prepare(ui,tmp_path);raw=curve.dataset.values.copy()
    expected=smoothed_state(curve,ui.domain,4)
    entered,release,exited=blocked(monkeypatch)
    dialog=ui.show_native_smooth();dialog.width_edit.setText('4');dialog.reuse.setChecked(True)
    beats=[];timer=QTimer();timer.setInterval(5);timer.timeout.connect(lambda:beats.append(1));timer.start()
    started=time.perf_counter();dialog.accept();elapsed=time.perf_counter()-started
    assert dialog.job is not None and dialog.result()!=QDialog.Accepted and elapsed<1
    pump(lambda:entered.is_set() and len(beats)>=5)
    assert curve.working is None and not curve.history
    curve.dataset.metadata['LookupMass']=['0.49']
    release.set();pump(lambda:dialog.result()==QDialog.Accepted);timer.stop()
    assert dialog.job is None and exited.is_set() and curve.smooth_reuse
    np.testing.assert_array_equal(curve.working,expected['working'])
    assert curve.operations==expected['operations'] and curve.dataset.metadata['LookupMass']==['0.49']
    np.testing.assert_array_equal(curve.dataset.values,raw)
    assert len(curve.history)==1;ui.undo();assert curve.working is None


def test_background_signals_preserve_other_documents_mass_and_undo_entries(ui,tmp_path,monkeypatch):
    curve=prepare(ui,tmp_path);curve.checkpoint();entry=curve.history[-1]
    other=Curve(source(tmp_path/'other.001'));ui.curves.append(other)
    entered,release,exited=blocked(monkeypatch)
    dialog=SignalsDialog(ui);set_combo(dialog.types[0],'d2_time')
    expected=typed_signal(curve.dataset,2,'d2_time')
    dialog.accept();assert dialog.job is not None;pump(entered.is_set)
    other.scale=7;curve.dataset.metadata['LookupMass']=['0.46']
    release.set();pump(lambda:dialog.result()==QDialog.Accepted)
    assert exited.is_set() and any(c is other for c in ui.curves) and other.scale==7
    old=next(c for c in ui.curves if c.uid==curve.uid)
    assert old.history[-1] is entry
    result=ui.selected();assert result.dataset is curve.dataset
    assert result.dataset.metadata['LookupMass']==['0.46']
    np.testing.assert_array_equal(result.working,expected)


@pytest.mark.parametrize('action',['reject','close','app_close'])
def test_cancel_or_close_does_not_apply_late_results(ui,tmp_path,monkeypatch,action):
    curve=prepare(ui,tmp_path);entered,release,exited=blocked(monkeypatch)
    dialog=ui.show_native_smooth();dialog.width_edit.setText('4');dialog.accept()
    pump(entered.is_set);job=dialog.job
    started=time.perf_counter()
    if action=='app_close':ui.close()
    else:getattr(dialog,action)()
    assert time.perf_counter()-started<1
    assert job.cancelled.is_set() and dialog.job is None and not job.timer.isActive()
    release.set();pump(exited.is_set)
    assert curve.working is None and not curve.history and dialog.result()!=QDialog.Accepted


@pytest.mark.parametrize('action',['curve','options','removed'])
def test_stale_results_do_not_commit_and_dialog_can_retry(ui,tmp_path,monkeypatch,action):
    curve=prepare(ui,tmp_path);entered,release,exited=blocked(monkeypatch)
    dialog=ui.show_native_smooth();dialog.width_edit.setText('4');dialog.accept();pump(entered.is_set)
    if action=='curve':curve.scale=2
    elif action=='options':ui.plot_options[curve.dataset.document_key]['title']='changed'
    else:ui.curves=[]
    release.set();pump(lambda:dialog.job is None)
    assert '未应用' in dialog.error.text() and dialog.width_edit.isEnabled()
    assert curve.working is None and not curve.history and dialog.result()!=QDialog.Accepted
    if action!='removed':
        dialog.accept();pump(lambda:dialog.result()==QDialog.Accepted)
        assert curve.working is not None and len(curve.history)==1


def test_background_error_leaves_state_unchanged_and_restores_inputs(ui,tmp_path):
    curve=prepare(ui,tmp_path);dialog=ui.show_native_smooth();dialog.width_edit.setText('-2')
    dialog.accept();pump(lambda:dialog.job is None)
    assert '负' in dialog.error.text() and dialog.width_edit.isEnabled()
    assert curve.working is None and not curve.history


def test_latest_document_request_releases_superseded_dialog(ui,tmp_path,monkeypatch):
    from tma_app.smoothing_dialog import SmoothDialog
    curve=prepare(ui,tmp_path);entered,release,exited=blocked(monkeypatch)
    first=SmoothDialog(ui,curve);first.width_edit.setText('2');first.accept();pump(entered.is_set)
    old=first.job
    second=SmoothDialog(ui,curve);second.width_edit.setText('4');second.accept()
    pump(lambda:first.job is None)
    assert old.cancelled.is_set() and first.width_edit.isEnabled() and '替代' in first.error.text()
    release.set();pump(lambda:second.result()==QDialog.Accepted)
    assert curve.smooth_width==4 and len(curve.history)==1 and first.result()!=QDialog.Accepted


def test_unchanged_custom_signal_reuses_owned_writable_buffers(ui,tmp_path):
    curve=prepare(ui,tmp_path);raw=curve.dataset.values.copy()
    curve.y_type='custom';curve.working=curve.base_y.copy();curve.operations=['normalize']
    curve.smooth_source=curve.working.copy();working=curve.working;smooth_source=curve.smooth_source
    dialog=SignalsDialog(ui);dialog.accept();pump(lambda:dialog.result()==QDialog.Accepted)
    current=ui.selected()
    assert current.working is working and current.smooth_source is smooth_source
    assert current.working.flags.writeable and current.smooth_source.flags.writeable
    current.working[0]+=1
    np.testing.assert_array_equal(current.dataset.values,raw)


def test_processed_x_is_not_recalculated_on_gui_after_background_signals(ui,tmp_path,monkeypatch):
    import tma_app.signal_processing as processing
    curve=prepare(ui,tmp_path);calls=[];fit=processing.local_fit;main=threading.get_ident()
    def checked(*args,**kwargs):
        calls.append(threading.get_ident())
        return fit(*args,**kwargs)
    monkeypatch.setattr(processing,'local_fit',checked)
    dialog=SignalsDialog(ui)
    next(button for button in dialog.x_modes.buttons() if button.property('mode')=='signal').click()
    set_combo(dialog.x_signal,curve.dataset.signals[2].label);set_combo(dialog.x_type,'d_time')
    set_combo(dialog.types[0],'d2_time')
    dialog.accept();pump(lambda:dialog.result()==QDialog.Accepted)
    assert calls and all(thread!=main for thread in calls)
    curve=ui.selected();assert curve._x_cache[0][0]==id(curve.dataset.values)
    curve.x_values('signal');assert all(thread!=main for thread in calls)


@pytest.mark.parametrize('domain',['temperature','signal'])
def test_processed_x_background_math_matches_synchronous(tmp_path,domain):
    curve=Curve(dataset(tmp_path/'x.001',3000));curve.x_signal_index=2;curve.x_signal_type='d_time'
    template=factory_template(curve.dataset);template['x'].update(domain=domain,signal=curve.dataset.signals[2].label,type='d_time')
    template['y'][0].update(type='d2_temperature',width=1.)
    expected=build_proposal([curve],curve.dataset,template)
    snap=CurveSnapshot([curve]);actual=calculate(dict(kind='signals',curves=snap.worker_curves(),template=template),threading.Event())
    for a,b in zip(actual,expected):
        if a.working is not None:np.testing.assert_array_equal(a.working,b.working)
        np.testing.assert_array_equal(a.x_values(domain),b.x_values(domain))
    assert snap.matches([curve])
