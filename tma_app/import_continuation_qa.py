"""Exercise the real Open menu/picker while an old weighing request is blocked."""
from pathlib import Path
import hashlib,json,threading,time,traceback
import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication,QDialog
from . import __version__,data_file_dialog as picker,mass_lookup as mass
from .batch_qa import wait_until


def verify(window,output,paths):
    output.parent.mkdir(parents=True,exist_ok=True)
    report={'status':'failed','version':__version__,'checks':[],'opens':[]}
    hashes={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    entered,release=threading.Event(),threading.Event();threads=[]
    old_lookup,old_source,old_exec=mass.lookup_record,mass.configured_source,picker.DataFileDialog.exec
    window.warn=lambda message:(_ for _ in ()).throw(ValueError(message))
    plan=[]
    def lookup(sample,source=None):
        threads.append(threading.get_ident());entered.set();release.wait(30)
        return mass.MassMatch(.47,'qa-only.csv','mg','matched')
    def execute(dialog):
        selected=plan.pop(0)
        def choose():
            if selected is None:dialog.reject()
            else:dialog.selectFile(str(selected));dialog.accept()
        QTimer.singleShot(40,choose)
        return old_exec(dialog)
    def open_file(path):
        previous=len(window.curves);plan.append(path);start=time.perf_counter()
        window.classic_actions['Open1'].trigger()
        if path is None:assert len(window.curves)==previous;return
        wait_until(lambda:len(window.curves)==previous+1,timeout=3000)
        assert window.selected().dataset.path==path
        report['opens'].append({'path':str(path),'seconds':time.perf_counter()-start})
    try:
        mass.lookup_record=lookup;mass.configured_source=lambda:'qa-only.csv'
        picker.DataFileDialog.exec=execute
        open_file(paths[0]);wait_until(entered.is_set)
        window.start_point_measurement('dimension_change');window.confirm_measurement()
        window.process('smooth');first=window.selected();expected=first.working.copy()
        result=json.dumps(window.results,sort_keys=True,default=str)
        job=window._import_mass_job;thread=job.worker_thread
        for path in (paths[1],paths[0],paths[1]):
            open_file(path)
            assert not release.is_set() and job.worker_thread is thread
        assert len(threads)==1 and len(window.documents)==4
        assert len({c.dataset.document_key for c in window.curves})==4
        np.testing.assert_array_equal(first.working,expected)
        assert json.dumps(window.results,sort_keys=True,default=str)==result
        report['checks'].append('four_actual_open_menu_picker_imports_while_first_mass_lookup_blocked')
        report['checks'].append('processed_first_curve_and_results_preserved_with_independent_duplicate_openings')
        open_file(None);open_file(paths[0]);assert len(window.documents)==5
        report['checks'].append('cancel_picker_then_open_again_succeeds')
        release.set();wait_until(lambda:job.pending==0 and window.worker is None)
        assert len(threads)==5 and len(set(threads))==1
        assert all(c.dataset.metadata['LookupMass']==['0.47'] for c in window.curves)
        assert not window._import_mass_targets
        report['checks'].append('one_mass_daemon_delivers_all_late_weights_to_their_own_documents')
        assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest for path,digest in hashes.items())
        report.update(status='passed',source_files_unchanged=True,source_sha256=hashes)
    except Exception:report['error']=traceback.format_exc()
    finally:
        release.set();window.close();QApplication.processEvents()
        mass.lookup_record=old_lookup;mass.configured_source=old_source;picker.DataFileDialog.exec=old_exec
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    raise SystemExit(0 if report['status']=='passed' else 1)
