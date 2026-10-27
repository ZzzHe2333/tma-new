"""Frozen-capable latency checks with explicitly blocked configuration I/O."""
import json
import os
from pathlib import Path
import threading
import time
import traceback

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication,QDialog
from . import __version__,settings_jobs,path_settings,async_data_picker as picker
from .batch_qa import wait_until


def verify(window,output):
    output.parent.mkdir(parents=True,exist_ok=True)
    report={'status':'failed','version':__version__,'checks':[]}
    old_load,old_save,old_scan=settings_jobs.load,settings_jobs.save,picker.scan_directory
    loaded,release=threading.Event(),threading.Event()
    heartbeat=[];timer=QTimer();timer.setInterval(10);timer.timeout.connect(lambda:heartbeat.append(time.perf_counter()));timer.start()
    try:
        wait_until(lambda:window.achievement_controller.loaded)
        original=path_settings.cached_settings()
        assert original is not None
        def blocked_load(primary,events):
            loaded.set();release.wait(10);events.put(('loaded',primary,original[1],'standard'))
        settings_jobs.load=blocked_load
        t=time.perf_counter();dialog=window.show_path_settings();QApplication.processEvents()
        report['settings_open_seconds']=time.perf_counter()-t;assert report['settings_open_seconds']<1
        wait_until(loaded.is_set);before=len(heartbeat);wait_until(lambda:len(heartbeat)>=before+10)
        dialog.paths.item(1,1).setText(str(output.parent/'user-selected-B'))
        release.set();wait_until(lambda:not dialog._loading)
        assert dialog.paths.item(1,1).text().endswith('user-selected-B')
        report['checks'].append('settings_paints_while_disk_load_blocked_and_late_load_preserves_edits')
        loaded.clear();release.clear()
        def blocked_save(paths,popup,hours,events):
            loaded.set();release.wait(10);old_save(paths,popup,hours,events)
        settings_jobs.save=blocked_save
        t=time.perf_counter();dialog.accept();report['settings_save_return_seconds']=time.perf_counter()-t
        assert report['settings_save_return_seconds']<.5;wait_until(loaded.is_set)
        before=len(heartbeat);wait_until(lambda:len(heartbeat)>=before+10);release.set();wait_until(lambda:not dialog.saving)
        assert dialog.result()==QDialog.DialogCode.Accepted
        assert path_settings.cached_settings()[1]['paths']['open_folder'].endswith('user-selected-B')
        report['checks'].append('settings_save_never_waits_on_ui_and_cache_updates_after_success')
        settings_jobs.load,settings_jobs.save=old_load,old_save
        def scan(directory,cancelled,events):events.put(('rows',[(f'sample-{i:05}.001',str(output.parent/f'sample-{i:05}.001'),False,1000,1700000000+i) for i in range(10000)]))
        picker.scan_directory=scan
        before=len(heartbeat);t=time.perf_counter();dialog=picker.DataFileDialog(window,'导入文件',str(output.parent),'TMA (*.001)');dialog.show()
        wait_until(lambda:dialog.model.rowCount()==10000)
        report['list_10000_seconds']=time.perf_counter()-t
        assert dialog.headers.index(0,0).data()=='sample-09999.001'
        assert dialog.headers.index(9999,0).data()=='sample-00000.001'
        values=heartbeat[before:];report['list_10000_max_event_gap']=max([b-a for a,b in zip(values,values[1:])]+[0])
        assert report['list_10000_max_event_gap']<.5
        dialog.grab().save(str(output.with_suffix('.picker.png')));dialog.reject()
        report['checks'].append('10000_rows_visible_sorted_by_real_mtime_without_per_cell_qt_items')
        # Force a genuinely cold config-cache miss in the actual import action.
        from . import data_file_dialog
        cached,read=path_settings.cached_settings,path_settings._read_settings
        entered=threading.Event();done=threading.Event();release.clear()
        def stalled(*args,**kwargs):
            entered.set();release.wait(10)
            try:return read(*args,**kwargs)
            finally:done.set()
        path_settings.cached_settings=lambda:None;path_settings._read_settings=stalled
        driver=QTimer();driver.setInterval(20)
        def cancel():
            active=QApplication.activeModalWidget()
            if isinstance(active,picker.DataFileDialog) and entered.is_set():active.reject();driver.stop()
        driver.timeout.connect(cancel);driver.start()
        try:
            t=time.perf_counter();data_file_dialog.get_data_files(window,'冷配置导入','TMA (*.001)')
            report['cold_config_picker_cancel_seconds']=time.perf_counter()-t
            assert report['cold_config_picker_cancel_seconds']<1
        finally:
            driver.stop();path_settings.cached_settings=cached;path_settings._read_settings=read;release.set()
        wait_until(done.is_set)
        report['checks'].append('cold_config_lookup_is_background_and_import_dialog_can_cancel')
        manager=window.achievement_controller
        manager.record('images',1,window);wait_until(lambda:manager.state['counts']['images']==1)
        location=Path(manager.location)
        from .achievement_ui import common_achievement_path
        primary=path_settings.config_path().with_name('achievements.json')
        assert location in (primary,common_achievement_path(primary))
        assert location.drive.casefold()==os.environ.get('SystemDrive','C:').casefold()
        assert location.exists(),manager.error
        report['achievement_path']=str(location)
        report['checks'].append('achievement_file_is_in_C_user_profile_not_project_or_release')
        report['status']='passed'
    except Exception:report['error']=traceback.format_exc()
    finally:
        release.set();timer.stop();settings_jobs.load,settings_jobs.save=old_load,old_save;picker.scan_directory=old_scan
        window.close();QApplication.processEvents()
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    # The detailed failure is already in the report. A console-less frozen
    # verifier must exit instead of opening PyInstaller's modal error dialog.
    if report['status']!='passed':raise SystemExit(1)
