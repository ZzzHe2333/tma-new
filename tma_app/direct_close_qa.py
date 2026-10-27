"""Wait for a native WM_CLOSE sent by the isolated EXE test controller."""
import json
import os
import threading
import time
import traceback

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__


def verify(window, output, scenario, paths):
    app=QApplication.instance();output.parent.mkdir(parents=True,exist_ok=True)
    report={'status':'failed','version':__version__,'scenario':scenario,'prompts':[]}
    job=None;entered=threading.Event();blocked=threading.Event()
    watchdog=QTimer(app);watchdog.setSingleShot(True)
    ready=QTimer(app);ready.setInterval(20)

    def timeout():
        report['error']='Native close timed out'
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        app.exit(1)
    watchdog.timeout.connect(timeout);watchdog.start(30000)
    def prompt(*args,**kwargs):
        report['prompts'].append(str(args[1:3]));return QMessageBox.StandardButton.Cancel
    QMessageBox.question=prompt
    try:
        if scenario in ('import','mass'):
            import tma_app.app as module
            import tma_app.mass_lookup as mass
            original=module.read_dataset
            if scenario=='import':
                def reader(path):
                    entered.set();blocked.wait(60);return original(path)
                module.read_dataset=reader
            else:
                original_mass=mass.lookup_record
                def lookup(*args,**kwargs):
                    entered.set();blocked.wait(60);return original_mass(*args,**kwargs)
                mass.lookup_record=lookup
            window.import_files(paths[:1],batch_results=False);job=window.worker
            window.import_files(paths[:1],batch_results=False)
        elif scenario in ('dirty','share'):
            window.import_files(paths[:1],synchronous=True)
            window.start_point_measurement('dimension_change')
            if scenario=='share':
                from .share_dialog import ShareDialog
                window.share_dialog=ShareDialog(window);window.share_dialog.busy=True
                window.share_dialog.timer.start()
                if os.environ.get('ZZZHE_TMA_QA_HIDE_WINDOW')!='1':window.share_dialog.show()
        elif scenario=='calculation':
            import numpy as np
            from . import calculation
            from .reader import Dataset,Signal
            t=np.linspace(0,30,12000)
            ds=Dataset(output.parent/'synthetic.001',[Signal('Time','min'),Signal('Temperature','°C'),Signal('Dimension Change','µm')],np.column_stack((t,30+t*7,np.sin(t)*100+t*t)),{},[],'synthetic')
            window.finish_import([ds],[]);window.show_normal()
            original_calculate=calculation.calculate
            def calculate(request,cancelled):
                entered.set();blocked.wait(60);return original_calculate(request,cancelled)
            calculation.calculate=calculate
            from .smoothing_dialog import SmoothDialog
            dialog=SmoothDialog(window,window.current_data_curve())
            dialog.width_edit.setText('6');dialog.accept();job=dialog.job
        elif scenario!='empty':raise ValueError(scenario)
        window.touch()
        assert '*' not in window.windowTitle() and '未保存' not in window.windowTitle()
    except Exception:
        report['error']=traceback.format_exc();output.write_text(json.dumps(report),encoding='utf-8');raise SystemExit(1)

    def advertise():
        nonlocal job
        if scenario in ('import','mass','calculation') and (not entered.is_set() or (scenario=='mass' and not window.curves)):return
        if scenario=='mass':job=window._import_mass_job
        ready.stop()
        output.with_suffix('.ready.json').write_text(json.dumps({'pid':os.getpid(),'hwnd':int(window.winId()),'scenario':scenario}),encoding='utf-8')
    ready.timeout.connect(advertise);ready.start()
    def final():
        try:
            assert window._closing and not window.isVisible() and not report['prompts']
            assert window.worker is None and window._pending_import_paths==[]
            if job is not None:
                assert job.cancelled.is_set()
                if scenario=='calculation':assert calculation.DISPATCHER.thread.daemon
                else:assert job.worker_thread.daemon
            report.update(status='passed',worker_cancelled=job.cancelled.is_set() if job else None)
        except Exception:report['error']=traceback.format_exc()
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    # Default empty/dirty windows have no queue attribute until an import.
    if not hasattr(window,'_pending_import_paths'):window._pending_import_paths=[]
    app.aboutToQuit.connect(final)
    code=app.exec()
    raise SystemExit(0 if code==0 and report['status']=='passed' else 1)
