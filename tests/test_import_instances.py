"""Repeated opens are independent; slow file and weighing I/O leave Qt responsive."""
from copy import deepcopy
import time
import threading
import numpy as np
from PySide6.QtCore import QEventLoop,QTimer
from test_point_interaction import ui
from tma_app.workspace import save_session,load_session


def datafile(tmp_path):
    path=tmp_path/'same.001'
    path.write_text('Sample repeated\nNsig 3\nSig1 Time (min)\nSig2 Temperature (°C)\nSig3 Dimension Change (µm)\nStartOfData\n'+''.join(f'{i} {100+i} {i*i}\n' for i in range(21)),encoding='utf-8')
    return path


def opened(ui,tmp_path):
    ui.close_all_documents();path=datafile(tmp_path)
    ui.import_files([path],synchronous=True);first=ui.selected()
    ui.import_files([path],synchronous=True);second=ui.selected()
    assert first is not second and first.dataset.document_key!=second.dataset.document_key
    assert first.dataset.path==second.dataset.path and len(ui.documents)==2
    return first,second


def test_repeated_open_signals_graph_and_file_information_are_independent(ui,tmp_path):
    from tma_app.signals_dialog import current_template,build_proposal
    first,second=opened(ui,tmp_path);original=first.dataset.values.copy()
    template=current_template(ui,second.dataset);template['y'][1]=dict(template['y'][0])
    ui.curves=build_proposal(ui.curves,second.dataset,template);ui.rebuild_files();ui.refresh_curve(second.uid)
    assert len([c for c in ui.curves if c.dataset.document_key==first.dataset.document_key])==1
    assert len([c for c in ui.curves if c.dataset.document_key==second.dataset.document_key])==2
    ui.apply_file_information(second,{'Sample':'second only'})
    assert first.sample_name=='repeated' and next(c for c in ui.curves if c.uid==second.uid).sample_name=='second only'
    assert not np.shares_memory(first.dataset.values,second.dataset.values)
    np.testing.assert_array_equal(first.dataset.values,original)
    dialog=ui.show_curve_options();assert all(c.dataset.document_key==second.dataset.document_key for c in dialog.originals);dialog.reject()


def test_limits_units_results_and_close_only_affect_one_opening(ui,tmp_path):
    from tma_app.dimension_units import defaults
    first,second=opened(ui,tmp_path)
    ui.start_point_measurement('signal_max');ui.confirm_measurement();result=deepcopy(ui.results[0])
    second_doc=ui.active_document();ui._show_document(first.dataset.document_key)
    ui.apply_data_limits(first.dataset,dict(kind='time',start=2.,stop=15.,delay=0.,all_cycles=True,reset_time=False),curve_uid=first.uid)
    assert next(c for c in ui.curves if c.uid==second.uid).data_indices is None
    options=defaults();options['dimension']='mm';ui.apply_unit_options(ui.active_document(),options)
    assert next(c for c in ui.curves if c.uid==second.uid).unit_options is None
    assert result in ui.results
    ui.close_active_document()
    assert len(ui.documents)==1 and second_doc in ui.documents.values()
    assert all(c.dataset.document_key==second.dataset.document_key for c in ui.curves)
    assert result in ui.results


def test_duplicate_openings_survive_session_and_overlay_selection(ui,tmp_path):
    from tma_app.classic_dialogs import AddCurvesDialog
    first,second=opened(ui,tmp_path);keys=[first.dataset.document_key,second.dataset.document_key]
    ui.show_overlay();assert len(ui.visible_curves())==2
    dialog=AddCurvesDialog(ui,ui.curves,0);assert len(dialog.datasets)==2;dialog.reject()
    path=tmp_path/'instances.tmas';save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    assert [c.dataset.document_key for c in load_session(path)[0]]==keys
    ui.close_all_documents();ui.restore_session(path)
    assert set(keys)<=set(ui.documents)
    ui._show_document(keys[1]);assert len(ui.visible_curves())==1
    ui.close_active_document();assert keys[0] in ui.documents and keys[1] not in ui.documents


def test_slow_io_runs_in_worker_while_timer_ticks_and_repeated_requests_queue(ui,tmp_path,monkeypatch):
    import tma_app.app as module
    import tma_app.mass_lookup as mass
    ui.close_all_documents();path=datafile(tmp_path);read=module.read_dataset;lookup=mass.lookup_record
    threads=[];main=threading.get_ident()
    def slow_read(path):
        threads.append(threading.get_ident());time.sleep(.18);return read(path)
    def slow_lookup(sample,source=None):
        threads.append(threading.get_ident());time.sleep(.18);return lookup(sample,source)
    monkeypatch.setattr(module,'read_dataset',slow_read);monkeypatch.setattr(mass,'lookup_record',slow_lookup)
    loop=QEventLoop();ticks=[];timer=QTimer();timer.setInterval(20)
    def tick():
        ticks.append(time.perf_counter())
        if len(ui.curves)==2 and ui.worker is None:loop.quit()
    timer.timeout.connect(tick);timer.start();QTimer.singleShot(12000,loop.quit)
    started=time.perf_counter();ui.import_files([path]);elapsed=time.perf_counter()-started
    ui.import_files([path]);loop.exec();timer.stop()
    assert elapsed<.15 and len(ui.curves)==2 and ui.worker is None
    assert len(ticks)>=12 and all(identity!=main for identity in threads)
    assert ui.curves[0].dataset.document_key!=ui.curves[1].dataset.document_key


def test_reopen_after_close_gets_fresh_options_and_distinct_number(ui,tmp_path):
    first,second=opened(ui,tmp_path);path=first.dataset.path
    ui._show_document(first.dataset.document_key)
    ui.plot_options[first.dataset.document_key]['title']='first only'
    ui.close_active_document();ui.import_files([path],synchronous=True)
    current=ui.selected()
    assert current.dataset.opening_index==3 and current.dataset.document_key!=first.dataset.document_key
    assert ui.plot_options[current.dataset.document_key]['title']!='first only'
    assert second.dataset.document_key in ui.documents


def test_real_signal_dialog_and_auto_overlay_keep_both_openings(ui,tmp_path):
    first,second=opened(ui,tmp_path)
    dialog=ui.show_native_signals()
    dialog.signals[1].setCurrentIndex(dialog.signals[1].findData(second.dataset.signals[2].label))
    dialog.accept();assert not dialog.error.text()
    assert len([c for c in ui.curves if c.dataset.document_key==first.dataset.document_key and c.normal_enabled])==1
    assert len([c for c in ui.curves if c.dataset.document_key==second.dataset.document_key and c.normal_enabled])==2
    auto=ui.auto_configure_overlay();assert len(auto.sources)==2
    auto.accept();assert not auto.error.text()
    assert {c.dataset.document_key for c in ui.visible_curves()}=={first.dataset.document_key,second.dataset.document_key}


def test_curve_is_shown_before_slow_weighing_table_returns(ui,tmp_path,monkeypatch):
    import tma_app.mass_lookup as mass
    ui.close_all_documents();path=datafile(tmp_path)
    original=mass.lookup_record;waiting=threading.Event();release=threading.Event()
    def slow_lookup(sample,source=None):
        waiting.set();release.wait(5);return original(sample,source)
    monkeypatch.setattr(mass,'lookup_record',slow_lookup)
    loop=QEventLoop();timer=QTimer();timer.setInterval(10);shown=[]
    def check():
        if waiting.is_set() and ui.curves:
            shown.append(ui.visible_curves()[0].dataset.path)
            release.set()
        if ui.curves and ui.worker is None:loop.quit()
    timer.timeout.connect(check);timer.start();QTimer.singleShot(7000,loop.quit)
    ui.import_files([path]);loop.exec();release.set();timer.stop()
    assert shown and shown[0]==path and ui.worker is None
