"""Validated defaults reuse, batch coherence and bounded durable saves."""
from copy import deepcopy
import json
import os
from pathlib import Path
import threading

import pytest

from tma_app import preferences as prefs,atomic_files
from test_feature_ui import ui,source


@pytest.fixture(autouse=True)
def clear_snapshots():
    with prefs._LOCK:prefs._CACHE.clear()
    yield
    with prefs._LOCK:prefs._CACHE.clear()


def document(title):
    return {'format':prefs.FORMAT,'version':1,'scopes':{'overlay':{'title':{'options':{'title':title}}}}}


def write(path,title):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(document(title)),encoding='utf-8')


def reads_for(monkeypatch,path):
    calls=[];original=Path.read_text
    def read(self,*args,**kwargs):
        if self==path:calls.append(1)
        return original(self,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',read)
    return calls


def test_validated_file_and_all_scopes_reused_but_callers_are_independent(tmp_path,monkeypatch):
    path=tmp_path/'preferences.json';write(path,'original');calls=reads_for(monkeypatch,path)
    first=prefs.load_defaults('overlay',path=path);first['options']['title']='edited';first['curves'][0].append({'bad':True})
    for _ in range(20):
        assert prefs.load_defaults('overlay',path=path)['options']['title']=='original'
        assert prefs.load_defaults('graph',path=path)=={'options':{},'curves':[[],[],[],[]]}
    assert calls==[1] and prefs.load_defaults('overlay',path=path)['curves']==[[],[],[],[]]


def test_external_replacement_with_same_size_and_mtime_is_detected(tmp_path):
    path=tmp_path/'preferences.json';write(path,'first');prefs.load_defaults('overlay',path=path)
    old=path.stat();replacement=tmp_path/'replacement.json';write(replacement,'other')
    assert path.stat().st_size==replacement.stat().st_size
    os.utime(replacement,ns=(old.st_atime_ns,old.st_mtime_ns));os.replace(replacement,path)
    assert prefs.load_defaults('overlay',path=path)['options']['title']=='other'
    path.write_text('{corrupt',encoding='utf-8')
    with pytest.raises(ValueError):prefs.load_defaults('overlay',path=path)
    write(path,'fixed');assert prefs.load_defaults('overlay',path=path)['options']['title']=='fixed'


def test_missing_and_deleted_files_do_not_hide_later_external_creation(tmp_path):
    path=tmp_path/'preferences.json'
    assert not prefs.load_defaults('overlay',path=path)['options']
    write(path,'created');assert prefs.load_defaults('overlay',path=path)['options']['title']=='created'
    path.unlink();assert not prefs.load_defaults('overlay',path=path)['options']
    write(path,'new');assert prefs.load_defaults('overlay',path=path)['options']['title']=='new'


def test_batch_is_coherent_nested_and_thread_local(tmp_path,monkeypatch):
    path=tmp_path/'preferences.json';write(path,'before');calls=reads_for(monkeypatch,path);other=[]
    with prefs.batch_defaults():
        assert prefs.load_defaults('overlay',path=path)['options']['title']=='before'
        write(path,'after')
        with prefs.batch_defaults():assert prefs.load_defaults('overlay',path=path)['options']['title']=='before'
        worker=threading.Thread(target=lambda:other.append(prefs.load_defaults('overlay',path=path)))
        worker.start();worker.join(3);assert not worker.is_alive()
        assert other[0]['options']['title']=='after'
        assert prefs.load_defaults('overlay',path=path)['options']['title']=='before'
    assert prefs.load_defaults('overlay',path=path)['options']['title']=='after' and len(calls)==2


def test_save_inside_batch_invalidates_old_snapshot_and_preserves_other_pages(tmp_path):
    path=tmp_path/'preferences.json';write(path,'before')
    with prefs.batch_defaults():
        old=prefs.load_defaults('overlay',path=path)
        prefs.save_defaults('overlay','grid',{'grid_x':True},path=path)
        assert prefs.load_defaults('overlay',path=path)['options']=={'title':'before','grid_x':True}
        prefs.save_defaults('overlay','title',{'title':'after'},path=path)
        assert prefs.load_defaults('overlay',path=path)['options']=={'title':'after','grid_x':True}
        assert old['options']=={'title':'before'}


def test_invalid_batch_checked_once_and_exception_does_not_leak_snapshot(tmp_path,monkeypatch):
    path=tmp_path/'preferences.json';path.write_text('{invalid',encoding='utf-8');calls=reads_for(monkeypatch,path)
    with prefs.batch_defaults():
        for scope in ('units','graph','overlay'):
            with pytest.raises(ValueError,match='默认设置文件无效'):prefs.load_defaults(scope,path=path)
        write(path,'fixed')
        with pytest.raises(ValueError):prefs.load_defaults('overlay',path=path)
    assert calls==[1]
    assert prefs.load_defaults('overlay',path=path)['options']['title']=='fixed'
    with pytest.raises(RuntimeError):
        with prefs.batch_defaults():
            prefs.load_defaults('overlay',path=path);raise RuntimeError('fixture')
    assert getattr(prefs._BATCH,'entries',None) is None


def test_changed_during_read_is_rejected_then_recovered(tmp_path,monkeypatch):
    path=tmp_path/'preferences.json';write(path,'before');original=Path.read_text;changed=[]
    def read(self,*args,**kwargs):
        text=original(self,*args,**kwargs)
        if self==path and not changed:changed.append(1);write(path,'changed after read')
        return text
    monkeypatch.setattr(Path,'read_text',read)
    with pytest.raises(ValueError,match='读取期间发生变化'):prefs.load_defaults('overlay',path=path)
    assert prefs.load_defaults('overlay',path=path)['options']['title']=='changed after read'


@pytest.mark.parametrize('error,attempts',[(PermissionError,1),(FileExistsError,4)])
def test_temp_open_failure_is_bounded_preserves_file_and_cached_defaults(tmp_path,monkeypatch,error,attempts):
    path=tmp_path/'preferences.json';write(path,'keep');before=path.read_bytes();prefs.load_defaults('overlay',path=path)
    calls=[];original=atomic_files.os.open
    def fail(name,*args,**kwargs):
        if Path(name).parent==tmp_path and Path(name).name.startswith('.'):
            calls.append(str(name));raise error('fixture blocked temporary creation')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(atomic_files.os,'open',fail)
    with pytest.raises(error):prefs.save_defaults('overlay','title',{'title':'changed'},path=path)
    assert len(calls)==attempts and len(set(calls))==attempts
    assert path.read_bytes()==before and list(tmp_path.iterdir())==[path]
    assert prefs.load_defaults('overlay',path=path)['options']['title']=='keep'


def test_fsync_failure_keeps_old_file_and_no_temporary(tmp_path,monkeypatch):
    path=tmp_path/'preferences.json';write(path,'keep');before=path.read_bytes()
    def fail(*args):raise OSError('fixture sync failed')
    monkeypatch.setattr(atomic_files.os,'fsync',fail)
    with pytest.raises(OSError,match='sync failed'):prefs.save_defaults('overlay','title',{'title':'new'},path=path)
    assert path.read_bytes()==before and list(tmp_path.iterdir())==[path]


def test_cache_profiles_and_bytes_are_bounded_and_large_files_not_cached(tmp_path,monkeypatch):
    monkeypatch.setattr(prefs,'_CACHE_BYTES',600)
    for i in range(25):
        path=tmp_path/f'{i}.json';write(path,f'profile {i}')
        assert prefs.load_defaults('overlay',path=path)['options']['title']==f'profile {i}'
    assert len(prefs._CACHE)<=16 and sum(entry[0][2] for entry in prefs._CACHE.values())<=600
    path=tmp_path/'large.json';write(path,'large');path.write_text(' '*300000+path.read_text(),encoding='utf-8')
    calls=reads_for(monkeypatch,path)
    for _ in range(2):assert prefs.load_defaults('overlay',path=path)['options']['title']=='large'
    assert calls==[1,1] and prefs._identity(path) not in prefs._CACHE


def test_import_reads_one_coherent_snapshot_and_keeps_curve_options_independent(ui,tmp_path,monkeypatch):
    path=prefs.preferences_path()
    prefs.save_defaults('units','tma',{'unit_defaults':{'dimension':'mm','offset':'none'}})
    prefs.save_defaults('overlay','title',{'title':'stored'})
    calls=reads_for(monkeypatch,path);fingerprints=[];original=prefs._fingerprint
    def fingerprint(target):fingerprints.append(1);return original(target)
    monkeypatch.setattr(prefs,'_fingerprint',fingerprint)
    with prefs._LOCK:prefs._CACHE.clear()
    ui.finish_import([source(tmp_path/f'{i}.001') for i in range(8)],[])
    assert len(calls)==1 and len(fingerprints)==2
    assert all(c.unit_options['dimension']=='mm' for c in ui.curves)
    ui.curves[0].unit_options['dimension']='µm'
    assert all(c.unit_options['dimension']=='mm' for c in ui.curves[1:])
