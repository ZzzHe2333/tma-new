"""Exercise released Qt ownership and actual editor lifetimes in the EXE."""
from pathlib import Path
import gc,hashlib,json,traceback,weakref
import numpy as np
from PySide6.QtCore import QCoreApplication,QEvent,QThread
from PySide6.QtWidgets import QApplication,QDialog
from . import __version__
from .batch_qa import wait_until
from .reader import Dataset,Signal


def verify(window,output,paths):
    output.parent.mkdir(parents=True,exist_ok=True)
    report={'status':'failed','version':__version__,'checks':[],'closed_array_bytes':[],'editors':{}}
    originals={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    def settle():
        assert QThread.currentThread()==QApplication.instance().thread()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        QApplication.processEvents();gc.collect()
    def load():
        t=np.linspace(0,30,100000)
        ds=Dataset(output.parent/'synthetic.001',[Signal('Time','min'),Signal('Temperature','°C'),Signal('Dimension Change','µm')],
            np.column_stack((t,30+t*7,5+np.sin(t)*100+t*t)),{},[],'synthetic')
        window.finish_import([ds],[]);window.process('smooth');curve=window.selected();curve.checkpoint()
        window.start_point_measurement('dimension_change');window.confirm_measurement();window.canvas.draw()
        doc=window.active_document()
        refs={key:weakref.ref(value) for key,value in {'raw':ds.values,'working':curve.working,
            'history':curve.history[-1][0],'curve':curve,'figure':doc.figure,'canvas':doc.canvas,'document':doc}.items()}
        return refs,{key:ref().nbytes for key,ref in refs.items() if hasattr(ref(),'nbytes')}
    try:
        for method in ('close_all_documents','close_active_document','remove_selected'):
            refs,sizes=load();window._plot_resize_timer.start(60);getattr(window,method)();settle()
            retained=sum(size for key,size in sizes.items() if refs[key]() is not None)
            report['closed_array_bytes'].append(retained)
            assert retained==0 and all(ref() is None for ref in refs.values())
            assert window.canvas is window._default_canvas and not window._plot_artists
            assert not window._plot_resize_timer.isActive()
        report['checks'].append('last_document_close_all_or_remove_releases_100000_point_buffers_canvas_and_history')

        for method,key in [('show_native_smooth','smooth'),('show_native_signals','signals'),('show_curve_options','graph_options')]:
            retained=[];children=len(window.findChildren(QDialog))
            for index in range(4):
                refs,sizes=load();dialog=getattr(window,method)();form=weakref.ref(dialog)
                dialog.reject() if index%2 else dialog.close()
                assert key not in window.dialogs;del dialog
                window.close_all_documents();settle()
                retained.append(sum(size for name,size in sizes.items() if refs[name]() is not None))
                assert retained[-1]==0 and all(ref() is None for ref in refs.values()) and form() is None
                assert len(window.findChildren(QDialog))==children
            report['editors'][key]={'retained_array_bytes':retained,'extra_qt_children':0}
        report['checks'].append('12_temporary_editor_cancel_and_x_cycles_have_no_orphan_arrays_or_qt_children')

        for method,key in [('show_native_smooth','smooth'),('show_native_signals','signals'),('show_curve_options','graph_options')]:
            window.import_files(paths[:1],synchronous=True,batch_results=False)
            raw=window.selected().dataset.values.copy();dialog=getattr(window,method)();form=weakref.ref(dialog)
            outcomes=[];dialog.finished.connect(outcomes.append);dialog.accept()
            wait_until(lambda:QDialog.DialogCode.Accepted in outcomes)
            expected=tuple(a.copy() for a in window.selected().xy(window.domain))
            assert key not in window.dialogs;del dialog;settle();assert form() is None
            reopened=getattr(window,method)()
            for actual,wanted in zip(window.selected().xy(window.domain),expected):np.testing.assert_array_equal(actual,wanted)
            np.testing.assert_array_equal(window.selected().dataset.values,raw)
            reopened.reject();del reopened;window.close_all_documents();settle()
        report['checks'].append('real_file_editor_accept_reopen_preserves_applied_coordinates_and_raw_data')

        window.import_files(paths,synchronous=True,batch_results=False);current=window.selected();doc=window.active_document()
        expected=tuple(a.copy() for a in current.xy(window.domain))
        inactive=next(d for d in window.documents.values() if d is not doc);inactive.close();del inactive;settle()
        assert window.selected() is current and window.table.model().curve is current
        actual=next((x,y) for curve,x,y in window._plot_artists if curve is current)
        for a,b in zip(actual,expected):np.testing.assert_array_equal(a,b)
        report['checks'].append('closing_inactive_file_preserves_current_selection_table_and_plot_coordinates')
        window.close_all_documents();settle()

        refs,sizes=load();old=window.selected().dataset;old._import_ticket='old-qa-ticket'
        window._import_mass_targets={'old-qa-ticket':old.document_key};window.close_all_documents();assert not window._import_mass_targets
        del old;settle();assert all(ref() is None for ref in refs.values())
        report['checks'].append('closed_document_async_mass_targets_cleared_before_path_can_be_reopened')
        assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest for path,digest in originals.items())
        report.update(status='passed',source_files_unchanged=True,source_sha256=originals)
    except Exception:report['error']=traceback.format_exc()
    finally:
        window.close();QApplication.processEvents()
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    raise SystemExit(0 if report['status']=='passed' else 1)
