"""Drive the real Qt picker and verify directory memory across EXE restarts."""
import json
import hashlib
import os
from pathlib import Path
import traceback

from PySide6.QtCore import QTimer,Qt,QSettings
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from . import __version__,data_file_dialog as picker,path_settings
from .batch_qa import wait_until


def verify(window,output,phase):
    output.parent.mkdir(parents=True,exist_ok=True)
    # QFileDialog also remembers its own Qt view state. Keep QA's paths out of
    # the real application's settings while still sharing state across runs.
    identity=hashlib.sha256(os.environ['LOCALAPPDATA'].encode('utf-8')).hexdigest()[:12]
    QApplication.instance().setApplicationName('ZzzHeTMA-PickerQA-'+identity)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(output.parent/'qt-settings'))
    report={'status':'failed','version':__version__,'phase':phase,'dialogs':[]}
    original=picker.DataFileDialog.exec
    settings=path_settings.config_path();before=settings.read_bytes()
    a=Path(path_settings.import_folder());b=a.with_name('B');c=a.with_name('C')
    expected_names=['a-new.001','z-middle.001','m-old.001']
    plans=[(a,False)] if phase=='restart' else [(a,True),(b,False),(b,False),(b,False),(b,False)]
    def execute(dialog):
        expected,choose=plans.pop(0);timer=QTimer(dialog);timer.setInterval(20)
        watchdog=QTimer(dialog);watchdog.setSingleShot(True)
        errors=[];initial=Path(dialog.directory().absolutePath());moved=False
        def drive():
            nonlocal moved
            try:
                assert initial==expected,(initial,expected)
                model=dialog.tree.model();root=dialog.tree.rootIndex()
                names=[model.data(model.index(row,0,root)) for row in range(model.rowCount(root))]
                expected_order=[] if dialog.windowTitle()=='打开分析文件' else expected_names
                if names!=expected_order:return
                assert dialog.tree.header().sortIndicatorSection()==3
                assert dialog.tree.header().sortIndicatorOrder()==Qt.SortOrder.DescendingOrder
                if choose and not moved:
                    dialog.setDirectory(str(b));moved=True;return
                timer.stop()
                report['dialogs'].append({'caption':dialog.windowTitle(),'start':str(initial),'order':names,'modified_descending':True})
                dialog.grab().save(str(output.with_suffix('.picker-'+str(len(report['dialogs']))+'.png')))
                if choose:
                    index=model.index(0,0,root)
                    QTest.mouseClick(dialog.tree.viewport(),Qt.MouseButton.LeftButton,
                                     pos=dialog.tree.visualRect(index).center())
                    assert [Path(p) for p in dialog.selectedFiles()]==[b/'a-new.001']
                    dialog.accept()
                else:
                    dialog.setDirectory(str(c));dialog.reject()
            except Exception:
                errors.append(traceback.format_exc());timer.stop();dialog.reject()
        def timed_out():errors.append('Picker loading/sorting timed out');dialog.reject()
        timer.timeout.connect(drive);watchdog.timeout.connect(timed_out)
        timer.start();watchdog.start(15000)
        try:
            result=original(dialog)
            assert not errors,errors
            return result
        finally:timer.stop();watchdog.stop()
    try:
        picker.DataFileDialog.exec=execute
        window.open_files()
        if phase!='restart':
            wait_until(lambda:window.worker is None)
            assert Path(window.selected().dataset.path).parent==b
            assert Path(window._last_data_directory)==b
            batch=window.show_batch_analysis(popup=False);batch.choose_files()
            single=window.show_single_report();single.choose_tma();single.close()
            from .app import MainWindow
            MainWindow.open_files(window)
            window.open_session()
            assert Path(window._last_data_directory)==b
        else:assert window._last_data_directory==''
        assert not plans
        assert settings.read_bytes()==before and path_settings.import_folder()==str(a)
        report.update(status='passed',configured_directory_unchanged=True,shared_run_directory=window._last_data_directory)
    except Exception:report['error']=traceback.format_exc()
    finally:
        picker.DataFileDialog.exec=original
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        window.close()
    if report['status']!='passed':raise SystemExit(1)
