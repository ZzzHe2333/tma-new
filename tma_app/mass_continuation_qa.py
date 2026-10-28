"""Offline end-to-end checks for import and source-change mass lifetimes."""
from pathlib import Path
import hashlib
import json
import threading
import traceback

from PySide6.QtWidgets import QApplication
from . import __version__, mass_lookup as mass
from .batch_qa import wait_until


def verify(window, output, paths):
    output.parent.mkdir(parents=True, exist_ok=True)
    report={'status':'failed','version':__version__,'checks':[]}
    hashes={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    old_lookup,old_source=mass.lookup_record,mass.configured_source
    entered=threading.Event();release=threading.Event();configured=['old.csv'];offline=[False]

    def lookup(sample, source):
        if source=='old.csv':
            entered.set();release.wait(20)
            return mass.MassMatch(.91,source,'mg','old')
        if offline[0]:
            return mass.MassMatch(source=source,message='数据源暂不可用',unavailable=True)
        return mass.MassMatch(.52,source,'mg','matched')

    window.warn=lambda message:(_ for _ in ()).throw(ValueError(message))
    try:
        mass.lookup_record=lookup;mass.configured_source=lambda:configured[0]
        window.import_files([paths[0]],batch_results=False)
        wait_until(lambda:len(window.curves)==1 and entered.is_set(),timeout=10000)
        old_job=window._import_mass_job;old_thread=old_job.worker_thread
        configured[0]='new.csv';window.refresh_mass_lookup()
        assert old_job.cancelled.is_set()
        window.import_files([paths[1]],batch_results=False)
        wait_until(lambda:len(window.curves)==2 and window.curves[-1].dataset.metadata.get('LookupMass')==['0.52'],timeout=10000)
        assert not release.is_set()
        report['checks'].append('new_source_import_matches_while_old_source_is_blocked')
        wait_until(lambda:window._mass_refresh_job is None)
        assert window.curves[0].dataset.metadata['LookupMass']==['0.52']
        release.set();wait_until(lambda:not old_thread.is_alive())
        assert all(curve.dataset.metadata['LookupMass']==['0.52'] for curve in window.curves)
        report['checks'].append('late_old_result_cannot_replace_new_source_values')
        offline[0]=True;window.refresh_mass_lookup()
        wait_until(lambda:window._mass_refresh_job is None)
        assert all(curve.dataset.metadata['LookupMass']==['0.52'] and
                   curve.dataset.metadata.get('LookupMassStatus') for curve in window.curves)
        assert '暂不可用' in window.statusBar().currentMessage()
        report['checks'].append('offline_refresh_retains_same_source_weights_with_warning')
        assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest for path,digest in hashes.items())
        report.update(status='passed',source_files_unchanged=True)
    except Exception:
        report['error']=traceback.format_exc()
    finally:
        release.set();window.close();QApplication.processEvents()
        mass.lookup_record=old_lookup;mass.configured_source=old_source
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    raise SystemExit(0 if report['status']=='passed' else 1)
