"""Config I/O and large lists must not run inside menu/UI callbacks."""
import json
import queue
import threading
import time

from PySide6.QtCore import QTimer,Qt,QItemSelectionModel
from PySide6.QtWidgets import QApplication

from test_feature_ui import ui
from tma_app import path_settings as settings
from tma_app.batch_qa import wait_until


def beats_while_blocked():
    beats=[];timer=QTimer();timer.setInterval(5);timer.timeout.connect(lambda:beats.append(1));timer.start()
    wait_until(lambda:len(beats)>=8);timer.stop();return beats


def test_settings_load_and_save_do_not_wait_for_disk(ui,tmp_path,monkeypatch):
    from tma_app import settings_jobs
    entered=threading.Event();release=threading.Event()
    source=tmp_path/'keep.json';source.write_text('unchanged')
    def load(primary,events):
        entered.set();release.wait(8)
        events.put(('loaded',primary,{'paths':{'m':'','open_folder':'late-A'}},'standard'))
    monkeypatch.setattr(settings_jobs,'load',load)
    start=time.monotonic();dialog=ui.show_path_settings();assert time.monotonic()-start<.5
    try:
        wait_until(entered.is_set);dialog.paths.item(1,1).setText('user-B');beats_while_blocked()
        release.set();wait_until(lambda:not dialog._loading)
        assert dialog.paths.item(1,1).text()=='user-B'
        entered.clear();release.clear()
        def save(paths,popup,hours,events):
            entered.set();release.wait(8);events.put(('save_error','fixture disk denied'))
        monkeypatch.setattr(settings_jobs,'save',save)
        start=time.monotonic();dialog.accept();assert time.monotonic()-start<.5
        wait_until(entered.is_set);beats_while_blocked()
        assert dialog.saving and dialog.isVisible()
        release.set();wait_until(lambda:not dialog.saving)
        assert 'disk denied' in dialog.feedback.text() and dialog.paths.item(1,1).text()=='user-B'
        assert source.read_text()=='unchanged'
    finally:release.set();dialog.reject()


def test_start_folder_is_memory_only_and_cache_copies_are_independent(ui,monkeypatch):
    from tma_app.data_file_dialog import start_folder
    settings.save_paths({'m':'//slow/weights.xlsx','open_folder':'A'})
    monkeypatch.setattr(settings,'_read_settings',lambda *a,**k:(_ for _ in ()).throw(AssertionError('disk on UI')))
    assert start_folder(ui)=='A'
    copy=settings.cached_settings();copy[1]['paths']['open_folder']='bad'
    assert start_folder(ui)=='A'
    ui._last_data_directory='B';assert start_folder(ui)=='B'


def test_large_directory_sort_filter_and_selection_use_plain_background_rows(ui,tmp_path,monkeypatch):
    from tma_app import async_data_picker as picker
    entries=[(f's-{i:05}.001',str(tmp_path/f's-{i:05}.001'),False,100,1700000000+i) for i in range(10000)]
    def scan(directory,cancelled,events):events.put(('rows',entries))
    monkeypatch.setattr(picker,'scan_directory',scan)
    dialog=picker.DataFileDialog(ui,'导入',str(tmp_path),'TMA (*.001);;CSV (*.csv)');dialog.show()
    try:
        wait_until(lambda:dialog.model.rowCount()==10000)
        assert dialog.headers.index(0,0).data()=='s-09999.001'
        index=dialog.headers.index(0,0);dialog.tree.selectionModel().select(index,QItemSelectionModel.SelectionFlag.Select|QItemSelectionModel.SelectionFlag.Rows)
        selected=dialog.selectedFiles();dialog.tree.sortByColumn(0,Qt.SortOrder.AscendingOrder)
        wait_until(lambda:dialog.headers.index(0,0).data()=='s-00000.001')
        assert dialog.selectedFiles()==selected
        dialog.filters.setCurrentIndex(1);wait_until(lambda:dialog.model.rowCount()==0)
        assert not dialog.selectedFiles()
    finally:dialog.reject();dialog.deleteLater()


def test_achievement_primary_only_and_legacy_migration(tmp_path,monkeypatch):
    from tma_app import ui_size,atomic_files
    from tma_app.achievements import empty
    from tma_app.achievement_ui import _storage
    from tma_app import achievement_ui
    primary=tmp_path/'C-profile/ZzzHeTMA/achievements.json';legacy=tmp_path/'project/achievements.json'
    state=empty();state['counts']['images']=10
    secondary=tmp_path/'C-shared/ZzzHeTMA/profile/achievements.json'
    monkeypatch.setattr(achievement_ui,'common_achievement_path',lambda path:secondary)
    atomic_files.write_json(legacy,state);before=legacy.read_bytes()
    monkeypatch.setattr(ui_size,'fallback_paths',lambda path:[legacy])
    commands=queue.Queue();events=queue.Queue();commands.put(('stop',));_storage(primary,commands,events)
    assert json.loads(primary.read_text())['counts']['images']==10 and legacy.read_bytes()==before
    original=atomic_files.write_json;calls=[]
    def deny(path,data):calls.append(path);raise PermissionError('fixture C profile denied')
    monkeypatch.setattr(atomic_files,'write_json',deny)
    commands=queue.Queue();events=queue.Queue();commands.put(('record','images',1));commands.put(('stop',));_storage(primary,commands,events)
    assert calls==[primary,secondary] and legacy.read_bytes()==before
    assert any(e[0]=='error' for e in events.queue)


def test_C_fallback_persists_and_reset_does_not_restore_old_primary(tmp_path,monkeypatch):
    from tma_app import atomic_files,achievements
    primary=tmp_path/'user/achievements.json';common=tmp_path/'ProgramData/ZzzHeTMA/profile/achievements.json'
    state=achievements.empty();achievements.advance(state,'images',10)
    atomic_files.write_json(primary,state)
    original=atomic_files.write_json
    def denied(path,data):
        if path==primary:raise PermissionError('fixture user profile read only')
        original(path,data)
    monkeypatch.setattr(atomic_files,'write_json',denied)
    def run(items):
        commands=queue.Queue();events=queue.Queue()
        for item in [*items,('stop',)]:commands.put(item)
        achievements.disk_worker([primary,common],common,commands,events)
        return list(events.queue)
    run([('record','images',1)])
    assert run([])[0][1]['counts']['images']==11
    run([('reset',1)])
    assert run([])[0][1]['counts']['images']==0
    assert json.loads(primary.read_text())['counts']['images']==10
