"""Source/frozen stress checks using real curves and isolated plain workers."""
from pathlib import Path
import hashlib
import json
import threading
import time
import traceback

import numpy as np
from PySide6.QtCore import QCoreApplication,QEvent,QEventLoop,QTimer,Qt
from PySide6.QtWidgets import QApplication
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

from . import __version__,async_data_picker as picker
from .app import MainWindow
from .batch_qa import wait_until


def verify(window,output,paths):
    output.parent.mkdir(parents=True,exist_ok=True)
    report={'status':'failed','version':__version__,'checks':[]}
    originals={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    builds=[];draws=[];beats=[];release=threading.Event();dialog=None
    base_draw=MainWindow.redraw;canvas_draw=FigureCanvasQTAgg.draw
    original_scan,original_prepare=picker.scan_directory,picker.prepare_rows
    def rebuilt(owner,*args,**kwargs):builds.append(1);return base_draw(owner,*args,**kwargs)
    def drawn(canvas,*args,**kwargs):draws.append(1);return canvas_draw(canvas,*args,**kwargs)
    def settle(milliseconds=100):
        loop=QEventLoop();QTimer.singleShot(milliseconds,loop.quit);loop.exec()
    timer=QTimer();timer.setInterval(10);timer.timeout.connect(lambda:beats.append(time.perf_counter()));timer.start()
    try:
        window.import_files(paths*4,synchronous=True,batch_results=False);settle()
        assert len(window.documents)==8
        renderers=[doc.canvas.renderer for doc in window.documents.values() if hasattr(doc.canvas,'renderer')]
        assert len(renderers)==1
        assert sum(bool(doc.canvas.plot_ready) for doc in window.documents.values())==1
        report['initial_import']={'documents':8,'renderers':len(renderers),'renderer_bytes':sum(np.asarray(renderer.buffer_rgba()).nbytes for renderer in renderers)}
        report['checks'].append('unvisited_documents_have_no_blank_renderer')
        MainWindow.redraw,FigureCanvasQTAgg.draw=rebuilt,drawn
        started=time.perf_counter()
        for _ in range(3):
            for key in list(window.documents):
                curve=next(c for c in window.curves if c.dataset.document_key==key)
                expected=tuple(a.copy() for a in curve.xy(window.domain))
                before=len(builds);window._show_document(key);settle()
                assert len(builds)-before==1, {'key':key,'builds':len(builds)-before}
                assert window.selected() is curve and window.table.model().curve is curve
                shown=next((x,y) for c,x,y in window._plot_artists if c is curve)
                for a,b in zip(expected,shown):np.testing.assert_array_equal(a,b)
        report['switch_24']={'seconds_including_100ms_wait_per_switch':time.perf_counter()-started,'plot_builds':len(builds),'canvas_draws':len(draws)}
        assert len(builds)==24 and len(draws)<=72
        report['checks'].append('24_switches_one_rebuild_each_current_curve_and_table_exact')
        # Compare optimized and stock legend drawing on the exact same real
        # eight-file overlay and renderer, without changing its geometry.
        from matplotlib.legend import Legend
        native=window.active_document().key;window.show_overlay();settle()
        legend=window.axes[0].get_legend();find=Legend._find_best_position;searches=[]
        def counted(*args,**kwargs):searches.append(1);return find(*args,**kwargs)
        Legend._find_best_position=counted
        try:
            window.canvas.draw();cached=len(searches);pixels=np.asarray(window.canvas.buffer_rgba()).copy()
            draw_method,find_method=legend.draw,legend._find_best_position
            del legend.draw;del legend._find_best_position;searches.clear()
            window.canvas.draw();uncached=len(searches)
            np.testing.assert_array_equal(np.asarray(window.canvas.buffer_rgba()),pixels)
            legend.draw,legend._find_best_position=draw_method,find_method
            assert cached==1 and uncached>=cached and legend._tma_draw_positions is None
            report['legend_searches']={'cached':cached,'uncached':uncached,'pixels_equal':True}
        finally:Legend._find_best_position=find
        window._show_document(native);settle()
        report['checks'].append('legend_search_reused_only_within_draw_pixels_exact_to_stock')
        window.start_point_measurement('dimension_change');window.confirm_measurement();settle()
        values=json.loads(json.dumps(window.results[-1]['values']))
        draws.clear()
        for _ in range(5):window.redraw();QApplication.processEvents()
        assert len(draws)==10 and values==window.results[-1]['values']
        report['annotated_redraw_5']={'canvas_draws':len(draws)}
        window.grab().save(str(output.with_suffix('.plot.png')))
        report['checks'].append('annotation_layout_reuses_renderer_values_unchanged')
        entered=threading.Event();requests=[]
        def blocked(*args):requests.append(args);entered.set();release.wait(10);return original_prepare(*args)
        picker.prepare_rows=blocked
        rows=[(f's-{i:05}.001',str(output.parent/f's-{i:05}.001'),False,100,i) for i in range(10000)]
        picker.scan_directory=lambda directory,cancelled,events:events.put(('rows',rows))
        dialog=picker.DataFileDialog(window,'连续排序测试',str(output.parent),'TMA (*.001);;CSV (*.csv)');dialog.show()
        wait_until(entered.is_set);worker=dialog._view_worker;thread=worker.thread
        for _ in range(100):
            dialog.tree.sortByColumn(0,Qt.SortOrder.AscendingOrder)
            dialog.tree.sortByColumn(3,Qt.SortOrder.DescendingOrder)
        before=len(beats);wait_until(lambda:len(beats)>=before+10)
        assert worker.thread is thread and len(requests)==1 and worker.pending[-3]==dialog._view_token
        release.set();wait_until(lambda:dialog.model.rowCount()==10000)
        assert len(requests)==2 and dialog.model.rows[0][0]=='s-09999.001'
        report['sort_requests']={'submitted':201,'executed':len(requests),'worker_threads':1}
        release.clear();entered.clear();dialog.filters.setCurrentIndex(1);wait_until(entered.is_set)
        started=time.perf_counter();dialog.reject();report['blocked_sort_close_seconds']=time.perf_counter()-started
        assert worker.closed and report['blocked_sort_close_seconds']<.5
        dialog.deleteLater();QApplication.processEvents();dialog=None
        release.set();worker.thread.join(2);assert not worker.thread.is_alive()
        report['checks'].append('201_sort_requests_use_one_worker_latest_result_and_close_while_blocked')
        from shiboken6 import isValid
        for _ in range(3):
            controls=[(doc,doc.navigation,doc.canvas) for doc in window.documents.values()]
            assert controls and all(nav.parent() is doc for doc,nav,canvas in controls)
            window.close_all_documents()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            assert all(not isValid(obj) for group in controls for obj in group)
            window.import_files(paths,synchronous=True,batch_results=False)
            settle()
        report['checks'].append('repeated_close_releases_navigation_canvas_and_cancels_pending_draw')
        assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha for p,sha in originals.items())
        report['source_files_unchanged']=True;report['status']='passed'
    except Exception:report['error']=traceback.format_exc()
    finally:
        release.set();timer.stop()
        if dialog is not None:dialog.reject()
        picker.scan_directory,picker.prepare_rows=original_scan,original_prepare
        MainWindow.redraw,FigureCanvasQTAgg.draw=base_draw,canvas_draw
        window.close();QApplication.processEvents()
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if report['status']!='passed':raise SystemExit(1)
