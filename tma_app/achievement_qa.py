"""Exercise real exports, durable achievements, and deliberately stalled I/O."""
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import traceback

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication,QFileDialog,QMessageBox,QInputDialog,QDialog,QPlainTextEdit

from . import __version__
from .batch_qa import wait_until
from .achievement_ui import AchievementToast
from .achievements import TIERS


def verify(window,output,phase,paths):
    output.parent.mkdir(parents=True,exist_ok=True)
    report={'status':'failed','version':__version__,'phase':phase,'checks':[]}
    manager=window.achievement_controller
    save=QFileDialog.getSaveFileName;question=QMessageBox.question;note_exec=QInputDialog.exec
    try:
        wait_until(lambda:manager.loaded)
        from .path_settings import config_path
        config=config_path();before=config.read_bytes() if config.exists() else None
        if phase=='restart':
            assert manager.state['counts']['images']==100 and len(manager.state['earned'])>=3
            assert not manager.waiting and manager.toast is None
            wall=window.show_achievements();QApplication.processEvents()
            assert wall.cards[0].badges[2].unlocked and not wall.cards[0].badges[3].unlocked
            report['checks'].append('saved_counts_and_frames_restored_without_replaying_toasts')
            QMessageBox.question=lambda *a,**k:QMessageBox.StandardButton.Yes
            wall.clear_statistics();wait_until(lambda:sum(manager.state['counts'].values())==0)
            assert not manager.state['earned'];wall.grab().save(str(output.with_suffix('.cleared.png')))
            report['checks'].append('clear_wall_resets_counts_frames_and_pending_toasts')
        elif phase=='cleared':
            assert sum(manager.state['counts'].values())==0 and not manager.state['earned']
            report['checks'].append('reset_survives_process_restart')
        else:
            assert sum(manager.state['counts'].values())==0
            originals={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
            window.import_files(paths,synchronous=True,batch_results=False)
            wait_until(lambda:manager.state['counts']['imports']==len(paths))
            # Let the actual event delivery run, then avoid obscuring the plot.
            if manager.toast is not None:
                manager.toast.timer.stop();manager.toast.close();manager.toast.deleteLater();manager.toast=None
            manager.waiting.clear()
            window.start_point_measurement('dimension_change');window.confirm_measurement()
            wait_until(lambda:manager.state['counts']['analysis']==1)
            window.show_overlay();window.show_overlay()
            wait_until(lambda:manager.state['counts']['overlays']==2)
            export=output.with_suffix('.plot.png')
            QFileDialog.getSaveFileName=lambda *a,**k:(str(export),'PNG (*.png)')
            window.export_plot();wait_until(lambda:manager.state['counts']['images']==1)
            assert export.stat().st_size>10000
            # Render a real animation frame without changing the statistics.
            toast=AchievementToast(window,'images',TIERS[0],lambda:None);toast.start()
            wait_until(lambda:toast.clock.elapsed()>350)
            toast.grab().save(str(output.with_suffix('.toast.png')));toast.timer.stop();toast.close();toast.deleteLater()
            QFileDialog.getSaveFileName=lambda *a,**k:('','');window.export_plot()
            window.write_plot(output.with_suffix('.preview.png'))
            QApplication.processEvents();assert manager.state['counts']['images']==1
            report['checks'].append('real_export_unlocks_wood_cancel_and_preview_do_not_count')
            batch=window.show_batch_analysis(paths,popup=False)
            wait_until(lambda:batch.job is None and len(batch.rows)==len(paths),timeout=90000)
            wait_until(lambda:manager.state['counts']['batch']==len(paths))
            directory=output.parent/'batch-images';directory.mkdir(exist_ok=True)
            batch.start_plot_job(batch.rows,str(directory))
            wait_until(lambda:batch.export_job is None,timeout=90000)
            assert all(row.get('png') and not row.get('export_error') for row in batch.rows),batch.rows
            wait_until(lambda:manager.state['counts']['images']==1+len(paths))
            batch.copy_selection();wait_until(lambda:manager.state['counts']['tables']==1)
            QFileDialog.getSaveFileName=lambda *a,**k:(str(output.with_suffix('.xlsx')),'Excel (*.xlsx)')
            batch.export_xlsx();wait_until(lambda:batch.export_job is None)
            wait_until(lambda:manager.state['counts']['tables']==2)
            report['checks'].append('real_batch_rows_images_copy_and_xlsx_count_once_each')
            manager.record('images',100-manager.state['counts']['images'],window)
            wait_until(lambda:manager.state['counts']['images']==100)
            wall=window.show_achievements();QApplication.processEvents()
            assert len(wall.cards)==9 and len(manager.state['earned'])>=3
            assert all(b.unlocked for b in wall.cards[0].badges[:3])
            assert all(not b.unlocked for b in wall.cards[0].badges[3:])
            wall.grab().save(str(output.with_suffix('.wall.png')));wall.hide()
            report['checks'].append('nine_cards_63_material_frames_and_100_count_copper_boundary')
            # A stuck filesystem call never occupies the UI thread.
            from . import async_data_picker as picker
            entered=threading.Event();release=threading.Event();original=picker.os.scandir
            def blocked(directory):
                if str(directory).endswith('qa-stalled-directory'):entered.set();release.wait(8)
                return original(output.parent)
            picker.os.scandir=blocked
            try:
                t=time.monotonic();dialog=picker.DataFileDialog(window,'导入文件',str(output.parent/'qa-stalled-directory'),'TMA (*.001)')
                report['picker_open_seconds']=time.monotonic()-t;assert report['picker_open_seconds']<1
                dialog.show();wait_until(entered.is_set)
                beats=[];timer=QTimer();timer.setInterval(20);timer.timeout.connect(lambda:beats.append(1));timer.start()
                wait_until(lambda:len(beats)>=8);dialog.grab().save(str(output.with_suffix('.slow-picker.png')))
                t=time.monotonic();dialog.reject();report['picker_cancel_seconds']=time.monotonic()-t;assert report['picker_cancel_seconds']<.5
                timer.stop();dialog.deleteLater()
            finally:release.set();picker.os.scandir=original
            report['checks'].append('stalled_directory_open_and_cancel_responsive_heartbeat_continues')
            # Hold mass I/O open, edit the note, then deliver a late lookup.
            from . import mass_lookup
            from .path_settings import save_paths
            original_lookup=mass_lookup.lookup_record
            note_entered=threading.Event();note_release=threading.Event()
            def blocked_mass(*a,**k):
                note_entered.set();note_release.wait(8)
                return mass_lookup.MassMatch(.47,'qa fixture','mg','matched')
            mass_lookup.lookup_record=blocked_mass
            save_paths({'m':'//unavailable.invalid/weighing.xlsx'})
            os.environ.pop('TMA_MASS_XLSX',None)
            for c in window.curves:
                for key in ('LookupMassSample','LookupMass'):c.dataset.metadata.pop(key,None)
            def note_test(dialog):
                wait_until(note_entered.is_set);assert dialog.textValue().endswith('0.50 mg')
                editor=dialog.findChild(QPlainTextEdit);editor.setPlainText('手工备注\n称取质量：0.46 mg')
                note_release.set();wait_until(lambda:not any(t.name=='TMA-mass-lookup' and t.is_alive() for t in threading.enumerate()))
                QApplication.processEvents();assert dialog.textValue()=='手工备注\n称取质量：0.46 mg'
                return QDialog.DialogCode.Accepted
            QInputDialog.exec=note_test
            try:window.add_note();assert window.results[-1]['values']['text'].startswith('手工备注')
            finally:note_release.set();mass_lookup.lookup_record=original_lookup
            report['checks'].append('note_opens_while_mass_blocked_and_late_mass_does_not_overwrite_edit')
            assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha for p,sha in originals.items())
            report['source_files_unchanged']=True
            # Restore only this isolated QA profile, so the second process can
            # verify reset is independent from settings and data documents.
            if before is None:config.unlink(missing_ok=True)
            else:config.write_bytes(before)
        report['counts']=dict(manager.state['counts']);report['earned']=len(manager.state['earned'])
        report['status']='passed'
    except Exception:
        report['error']=traceback.format_exc()
    finally:
        QFileDialog.getSaveFileName=save;QMessageBox.question=question;QInputDialog.exec=note_exec
        window.close();QApplication.processEvents()
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if report['status']!='passed':raise RuntimeError(report['error'])
