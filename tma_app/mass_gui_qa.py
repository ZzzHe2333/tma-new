"""Offline packaged checks for nonblocking normalization and note prefill."""
import hashlib,json,threading,traceback
from PySide6.QtCore import QEventLoop,QTimer
from PySide6.QtWidgets import QApplication,QInputDialog,QPlainTextEdit
from . import __version__,mass_lookup as mass,mass_jobs
from .batch_qa import wait_until
from .reader import read_dataset
from .note_prefill import prepare


def verify(window,output,paths):
    output.parent.mkdir(parents=True,exist_ok=True)
    report={'status':'failed','version':__version__,'checks':[]}
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    old_lookup,old_source=mass.lookup_record,mass.configured_source
    entered=threading.Event();release=threading.Event();threads=[]
    def configured():
        threads.append(threading.get_ident());entered.set();release.wait(20);return 'qa-only.csv'
    def lookup(sample,source):return mass.MassMatch(.47,source,'mg','matched')
    def heartbeat():
        ticks=[];timer=QTimer();timer.timeout.connect(lambda:ticks.append(1));timer.start(10)
        loop=QEventLoop();QTimer.singleShot(120,loop.quit);loop.exec();timer.stop()
        assert len(ticks)>=3 and not release.is_set()
    try:
        datasets=[read_dataset(path) for path in paths]
        for dataset in datasets:dataset._mass_match=mass.MassMatch(message='pending')
        window.finish_import(datasets,[]);window.show_overlay()
        mass.configured_source=configured;mass.lookup_record=lookup
        dialog=window.show_mass_normalization();QApplication.processEvents();wait_until(entered.is_set)
        heartbeat();assert threads and threads[0]!=threading.get_ident()
        dialog.reject();release.set();wait_until(lambda:not mass_jobs.DISPATCHER.active)
        report['checks'].append('normalization_remains_responsive_while_config_read_is_blocked')
        entered.clear();release.clear();threads.clear()
        curve=window.selected();note=QInputDialog(window)
        note.setOption(QInputDialog.InputDialogOption.UsePlainTextEditForTextInput)
        job=prepare(note,curve);done=[];job.finished.connect(lambda:done.append(True))
        wait_until(entered.is_set);heartbeat()
        note.findChild(QPlainTextEdit).setPlainText('用户手写\n保留内容')
        release.set();wait_until(lambda:bool(done))
        assert note.textValue()=='用户手写\n保留内容'
        job.cancel();note.close()
        report['checks'].append('note_remains_responsive_and_does_not_overwrite_manual_text')
        assert all(hashlib.sha256(p.read_bytes()).hexdigest()==hashes[str(p)] for p in paths)
        report.update(status='passed',source_files_unchanged=True)
    except Exception:report['error']=traceback.format_exc()
    finally:
        release.set();window.close();QApplication.processEvents()
        mass.lookup_record=old_lookup;mass.configured_source=old_source
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    raise SystemExit(0 if report['status']=='passed' else 1)
