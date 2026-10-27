"""Exercise history ownership and grouped undo in source and frozen builds."""
from copy import deepcopy
from pathlib import Path
import hashlib,json,time,traceback,weakref
import numpy as np
from PySide6.QtWidgets import QApplication,QDialog
from . import __version__
from .batch_qa import wait_until
from .reader import Dataset,Signal
from .signals_dialog import SignalsDialog


def verify(window,output,paths):
    output.parent.mkdir(parents=True,exist_ok=True)
    report={'status':'failed','version':__version__,'checks':[]}
    originals={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    def warn(message):raise ValueError(message)
    window.warn=warn
    try:
        t=np.linspace(0,30,100000)
        raw=np.column_stack((t,20+t*7,5+np.sin(t)*100+t*t))
        ds=Dataset(output.parent/'synthetic.001',[Signal('Time','min'),Signal('Temperature','°C'),Signal('Dimension Change','µm')],raw.copy(),{},[],'synthetic')
        window.finish_import([ds],[]);window.show_normal();QApplication.processEvents()
        refs=[];sizes=[]
        for _ in range(6):
            window.process('normalize');window.apply_data_limits(ds,None)
            refs.append(weakref.ref(window.selected().history[-1][0]))
            window.y_changed(1 if window.selected().y_index==2 else 2)
            sizes.append(sum(ref().nbytes for ref in refs if ref() is not None))
            assert sizes[-1]==0
        window._prune_limits_undo();assert not window._limits_undo
        np.testing.assert_array_equal(ds.values,raw)
        report['orphan_buffer_bytes_after_each_clear']=sizes
        report['checks'].append('six_100000_point_history_clears_release_orphan_buffers_immediately')

        window.import_files(paths[:1],synchronous=True,batch_results=False);window.show_normal()
        real=window.selected().dataset
        dialog=SignalsDialog(window)
        dialog.signals[1].setCurrentIndex(dialog.signals[1].findData(real.signals[2].label))
        dialog.types[1].setCurrentIndex(dialog.types[1].findData('d_time'))
        dialog.accept();assert dialog.result()==QDialog.Accepted,dialog.error.text()
        peers=[c for c in window.curves if c.dataset.document_key==real.document_key]
        assert len(peers)==2
        before={c.uid:{'working':None if c.working is None else c.working.copy(),'operations':list(c.operations)} for c in peers}
        uids=list(before);times=real.values[:,real.time_index]
        spec=dict(kind='time',start=float(times[100]),stop=float(times[-100]),delay=0.,all_cycles=False,reset_time=False)
        window.apply_data_limits(real,spec);registered=set(window._limits_undo)
        window.refresh_curve(uids[0]);window.process('smooth');window._prune_limits_undo()
        assert set(window._limits_undo)==registered
        window.refresh_curve(uids[1]);window.undo()
        assert '请先撤销' in window.statusBar().currentMessage()
        window.refresh_curve(uids[0]);window.undo()
        window.refresh_curve(uids[1]);window.undo()
        assert not window._limits_undo
        for curve in peers:
            # limits_proposal replaces curves, so examine the current object.
            current=next(c for c in window.curves if c.uid==curve.uid)
            assert current.data_indices is None and current.operations==before[current.uid]['operations']
            if before[current.uid]['working'] is None:assert current.working is None
            else:np.testing.assert_array_equal(current.working,before[current.uid]['working'])
        report['checks'].append('real_two_axis_older_transaction_retained_and_atomic_undo_exact')

        window.apply_data_limits(real,spec);registered=set(window._limits_undo)
        window.touch();timer=window._limits_cleanup_timer;identity=timer.timerId()
        for _ in range(500):window.touch()
        assert timer.isActive() and timer.timerId()==identity
        wait_until(lambda:not timer.isActive())
        assert set(window._limits_undo)==registered
        for curve in window.curves:
            if curve.dataset.document_key==real.document_key:curve.history=deepcopy(curve.history)
        window._prune_limits_undo();window.undo();assert not window._limits_undo
        report['checks'].append('500_touches_coalesced_and_logical_history_copies_keep_grouped_undo')

        window.apply_data_limits(real,spec)
        first=next(c for c in window.curves if c.uid==uids[0]);second=next(c for c in window.curves if c.uid==uids[1])
        # Y2 has a computed derivative, hence its checkpoint owns a real array.
        second_ref=weakref.ref(second.history[-1][0]);first.history=[]
        second.history=[];window._prune_limits_undo()
        assert second_ref() is None and not window._limits_undo
        report['checks'].append('replacing_all_group_histories_releases_arrays_and_metadata')

        # A settings class imported under a previous provider must not retain
        # that provider. Exercise this in the EXE as well as the unit process.
        from . import path_settings
        original_provider=path_settings.config_path;form=None
        older=output.parent/'provider-a/settings.json';current=output.parent/'provider-b/settings.json'
        for path in (older,current):path.parent.mkdir(parents=True,exist_ok=True)
        older.write_text(json.dumps({'paths':{'m':'older.xlsx'},'ui':{}}),encoding='utf-8')
        current.write_text(json.dumps({'paths':{'m':''},'ui':[]}),encoding='utf-8');current_bytes=current.read_bytes()
        try:
            path_settings.config_path=lambda:older
            from .settings_dialog import SettingsDialog
            path_settings.config_path=lambda:current
            form=SettingsDialog(window);wait_until(lambda:not form._loading)
            assert '设置未能刷新' in form.feedback.text()
            assert str(current) in form.location.text() and current.read_bytes()==current_bytes
        finally:
            if form is not None:form.reject()
            path_settings.config_path=original_provider
        report['checks'].append('settings_current_provider_and_corrupt_config_feedback_exact')

        window.apply_data_limits(real,None);assert window._limits_cleanup_timer.isActive()
        started=time.perf_counter();window.close();report['pending_cleanup_close_seconds']=time.perf_counter()-started
        assert not window._limits_cleanup_timer.isActive() and report['pending_cleanup_close_seconds']<.5
        report['checks'].append('close_cancels_pending_cleanup_without_waiting')
        assert originals=={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        report['source_files_unchanged']=True;report['status']='passed'
    except Exception:report['error']=traceback.format_exc()
    finally:
        window.close();QApplication.processEvents()
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if report['status']!='passed':raise SystemExit(1)
