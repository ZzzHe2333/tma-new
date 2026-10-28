"""Exercise the numerical worker in the actual Windows executable."""
from concurrent.futures import CancelledError
from pathlib import Path
import json
import threading
import time
import traceback

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog

from . import __version__, calculation, signal_processing
from .batch_qa import wait_until
from .data_limits import smoothed_state
from .reader import Dataset, Signal
from .signals_dialog import SignalsDialog


def verify(window, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    report={'status':'failed','version':__version__,'checks':[]}
    original=calculation.calculate;fit=signal_processing.local_fit
    release=threading.Event();entered=threading.Event();exited=threading.Event()
    timer=QTimer();timer.setInterval(5);beats=[]
    timer.timeout.connect(lambda:beats.append(time.perf_counter()));timer.start()
    def blocked(request,cancelled):
        entered.set()
        try:
            while not release.wait(.005):
                if cancelled.is_set():raise CancelledError()
            return original(request,cancelled)
        finally:exited.set()
    try:
        t=np.linspace(0,30,12000);values=np.column_stack((t,30+t*7,np.sin(t)*100+t*t))
        ds=Dataset(output.parent/'synthetic.001',[Signal('Time','min'),Signal('Temperature','°C'),Signal('Dimension Change','µm')],values.copy(),{'Sample':['numerical QA']},[],'synthetic')
        window.finish_import([ds],[]);window.show_normal();QApplication.processEvents()
        curve=window.selected();expected=smoothed_state(curve,window.domain,6)
        calculation.calculate=blocked
        dialog=window.show_native_smooth();outcomes=[];dialog.finished.connect(outcomes.append)
        dialog.width_edit.setText('6');dialog.reuse.setChecked(True)
        started=time.perf_counter();dialog.accept();report['smooth_accept_seconds']=time.perf_counter()-started
        assert dialog.job is not None and report['smooth_accept_seconds']<.5
        wait_until(entered.is_set);before=len(beats);wait_until(lambda:len(beats)>=before+10)
        assert curve.working is None and not curve.history
        release.set();wait_until(lambda:QDialog.Accepted in outcomes)
        np.testing.assert_array_equal(curve.working,expected['working'])
        assert curve.operations==expected['operations'] and curve.smooth_reuse
        window.undo();assert curve.working is None and not curve.history
        report['checks'].append('background_smoothing_heartbeat_exact_result_and_undo')

        # The first redraw must reuse the worker's processed X, rather than
        # deriving it again on the GUI after rebinding the original dataset.
        calls=[];main=threading.get_ident()
        def checked(*a,**kw):
            calls.append(threading.get_ident());return fit(*a,**kw)
        signal_processing.local_fit=checked
        dialog=SignalsDialog(window)
        next(b for b in dialog.x_modes.buttons() if b.property('mode')=='signal').click()
        dialog.x_signal.setCurrentIndex(dialog.x_signal.findData(ds.signals[2].label))
        dialog.x_type.setCurrentIndex(dialog.x_type.findData('d_time'))
        dialog.types[0].setCurrentIndex(dialog.types[0].findData('d2_time'))
        before=len(beats)
        started=time.perf_counter();dialog.accept();report['signals_accept_seconds']=time.perf_counter()-started
        assert dialog.job is not None and report['signals_accept_seconds']<.5
        wait_until(lambda:dialog.result()==QDialog.Accepted)
        assert len(beats)-before>=10
        assert calls and all(thread!=main for thread in calls)
        signal_processing.local_fit=fit
        curve=window.selected()
        np.testing.assert_array_equal(curve.working,signal_processing.typed_signal(curve.dataset,2,'d2_time'))
        np.testing.assert_array_equal(curve.x_values('signal'),signal_processing.typed_signal(curve.dataset,2,'d_time'))
        assert curve.dataset is ds
        report['checks'].append('background_signal_and_custom_x_derivatives_exact_no_gui_recompute')

        # Stale units/curve state invalidate the complete proposal, with no
        # checkpoint or partial write. The same dialog remains usable.
        release.clear();entered.clear();exited.clear()
        dialog=window.show_native_smooth();dialog.width_edit.setText('2');old=curve.working.copy();history=len(curve.history)
        dialog.accept();wait_until(entered.is_set);curve.scale=2;release.set()
        wait_until(lambda:dialog.job is None)
        assert '未应用' in dialog.error.text() and len(curve.history)==history
        np.testing.assert_array_equal(curve.working,old)
        dialog.reject()
        report['checks'].append('stale_state_discarded_without_partial_write_or_undo')

        # A blocked calculation never delays X/Cancel, and late output cannot
        # touch the curve. The single daemon cooperatively leaves its work.
        release.clear();entered.clear();exited.clear()
        dialog=window.show_native_smooth();dialog.width_edit.setText('2');dialog.accept();wait_until(entered.is_set)
        job=dialog.job;started=time.perf_counter();dialog.close();report['blocked_close_seconds']=time.perf_counter()-started
        assert job.cancelled.is_set() and dialog.job is None and report['blocked_close_seconds']<.5
        wait_until(exited.is_set);release.set();QApplication.processEvents()
        np.testing.assert_array_equal(curve.working,old)
        assert len(curve.history)==history
        assert calculation.DISPATCHER.thread.daemon and not calculation.DISPATCHER.pending
        report['checks'].append('cancel_close_cooperative_stop_and_single_bounded_daemon')
        np.testing.assert_array_equal(ds.values,values)
        report['checks'].append('raw_synthetic_acquisition_values_unchanged')
        report['heartbeat_count']=len(beats);report['status']='passed'
    except Exception:report['error']=traceback.format_exc()
    finally:
        release.set();timer.stop()
        calculation.calculate=original;signal_processing.local_fit=fit
        window.close();QApplication.processEvents()
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if report['status']!='passed':raise SystemExit(1)
