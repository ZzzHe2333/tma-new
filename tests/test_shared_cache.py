"""Persistent low-frequency mass snapshots and independent raw-curve reuse."""
import hashlib
import json
import threading

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from test_feature_ui import ui, imported
from tma_app import mass_lookup as mass, mass_cache as cache, path_settings as settings
from tma_app.batch_qa import wait_until
from tma_app.mass_jobs import MassLookupJob
from tma_app.reader import read_dataset


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.delenv('TMA_MASS_XLSX', raising=False); mass.clear_cache()
    yield
    mass.clear_cache()


def sheet(tmp_path, text='sample,M (mg)\nsample-0,0.46\nsample-1,0.55\n'):
    path=tmp_path/'mass.csv';path.write_text(text,encoding='utf-8-sig');return str(path)


def test_known_samples_never_resolve_or_stat_source_until_due(tmp_path,monkeypatch):
    source=sheet(tmp_path); assert mass.lookup_record('sample-0',source).value==.46
    def forbid(*args,**kwargs):raise AssertionError('Fresh cache must not touch source')
    monkeypatch.setattr(mass,'_load_source_records',forbid)
    for _ in range(20):
        assert mass.lookup_record('sample-0',source).value==.46
        assert mass.lookup_record('sample-1',source).value==.55


def test_disk_cache_survives_memory_reset_and_offline_restart(tmp_path,monkeypatch):
    source=sheet(tmp_path); mass.lookup_record('sample-0',source)
    assert len(list(cache.folder().glob('*.json')))==1
    cache.clear(disk=False); mass._table_cache.clear()
    def forbid(*args,**kwargs):raise AssertionError('Restart cache should be local only')
    monkeypatch.setattr(mass,'_load_source_records',forbid)
    assert mass.lookup_record('sample-1',source).value==.55
    assert cache.peek('sample-0',source).value==.46


def test_manual_refresh_updates_typo_once_for_whole_job(ui,tmp_path,monkeypatch):
    source=sheet(tmp_path); assert mass.lookup_record('sample-0',source).value==.46
    with open(source,'w',encoding='utf-8-sig') as handle:handle.write('sample,M (mg)\nsample-0,0.49\nsample-1,0.52\n')
    assert mass.lookup_record('sample-0',source).value==.46
    original=mass._load_source_records;loads=[]
    def load(*args,**kwargs):loads.append(1);return original(*args,**kwargs)
    monkeypatch.setattr(mass,'_load_source_records',load)
    job=MassLookupJob([('0','sample-0'),('1','sample-1')],source,ui,force=True)
    values={};done=[];job.row_ready.connect(lambda key,result:values.update({key:result.value}))
    job.finished.connect(lambda:done.append(1));job.start();wait_until(lambda:bool(done))
    assert values=={'0':.49,'1':.52} and len(loads)==1


def test_expiry_and_misses_are_rate_limited_per_source(tmp_path,monkeypatch):
    source=sheet(tmp_path);clock=[1000000.];monkeypatch.setattr(cache.time,'time',lambda:clock[0])
    original=mass._load_source_records;loads=[]
    def load(*args,**kwargs):loads.append(1);return original(*args,**kwargs)
    monkeypatch.setattr(mass,'_load_source_records',load)
    assert mass.lookup_record('sample-0',source).value==.46
    for i in range(10):assert mass.lookup_record(f'missing-{i}',source).value is None
    assert len(loads)==1
    clock[0]+=301;mass.lookup_record('missing-new',source);assert len(loads)==2
    for i in range(10):mass.lookup_record(f'missing-{i}',source)
    assert len(loads)==2
    clock[0]+=24*3600+1;mass.lookup_record('sample-0',source);assert len(loads)==3


def test_failure_retry_backoff_and_expired_positive_cache_fallback(tmp_path,monkeypatch):
    source=sheet(tmp_path);mass.lookup_record('sample-0',source)
    entry=cache._get(cache.identity(source));entry.loaded-=25*3600
    attempts=[]
    def failed(*args,**kwargs):attempts.append(1);raise OSError('offline')
    monkeypatch.setattr(mass,'_load_source_records',failed)
    for _ in range(10):
        result=mass.lookup_record('sample-0',source)
        assert result.value==.46 and '暂不可用' in result.message
    assert len(attempts)==1


def test_unknown_and_conflicting_masses_not_fabricated_and_sources_isolated(tmp_path):
    a=sheet(tmp_path,'sample,M (mg)\nx,0.46\nx,0.55\n')
    other=tmp_path/'other';other.mkdir();b=sheet(other,'sample,M (mg)\nx,0.49\n')
    assert mass.lookup_record('x',a).value is None
    assert '不同重量' in mass.lookup_record('x',a).message
    assert mass.lookup_record('x',b).value==.49
    assert mass.lookup_record('unknown',b).value is None


def test_corrupt_disk_cache_recovers_and_configuration_persists(tmp_path):
    source=sheet(tmp_path);key=cache.identity(source);path=cache.disk_path(key)
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{broken',encoding='utf-8')
    assert mass.lookup_record('sample-0',source).value==.46
    settings.save_paths({'m':source,'open_folder':str(tmp_path)})
    cache.save_refresh_hours(48)
    assert cache.refresh_hours()==48 and settings.load_paths()['m']==source
    with pytest.raises(ValueError):cache.save_refresh_hours(0)


def test_auto_normalization_populates_from_disk_cache_in_mg_without_confirming(ui,tmp_path,monkeypatch):
    imported(ui,tmp_path,2);source=sheet(tmp_path,'sample,M (g)\nsample-0,0.00046\nsample-1,0.00055\n')
    settings.save_paths({'m':source});mass.lookup_record('sample-0',source);cache.clear(disk=False)
    def forbid(*args,**kwargs):raise AssertionError('Normalization must reuse shared cache')
    monkeypatch.setattr(mass,'_load_source_records',forbid)
    dialog=ui.show_mass_normalization()
    assert [edit.text() for edit in dialog.edits]==['0.46','0.55']
    QApplication.processEvents();wait_until(lambda:dialog.mass_job is None)
    assert not any(check.isChecked() for check in dialog.checks)
    dialog.reject()


def test_auto_normalization_fills_missing_preserves_manual_edits_and_cancel(ui,tmp_path,monkeypatch):
    imported(ui,tmp_path,2);source=sheet(tmp_path);settings.save_paths({'m':source})
    entered,release=threading.Event(),threading.Event();original=mass._load_source_records
    def slow(*args,**kwargs):entered.set();release.wait(10);return original(*args,**kwargs)
    monkeypatch.setattr(mass,'_load_source_records',slow)
    dialog=ui.show_mass_normalization();QApplication.processEvents();wait_until(entered.is_set)
    try:
        assert [edit.text() for edit in dialog.edits]==['','']
        dialog.edits[0].setText('0.48');dialog.checks[0].setChecked(True)
        release.set();wait_until(lambda:dialog.mass_job is None)
        assert [edit.text() for edit in dialog.edits]==['0.48','0.55']
        assert dialog.table.item(0,1).text()=='0.46' and dialog.checks[0].isChecked()
        assert all(c.mass_normalization_mg is None for c in ui.curves)
    finally:release.set();dialog.reject()


def test_reader_reuses_parse_but_clones_all_mutable_data(tmp_path,monkeypatch):
    from tma_app import reader
    from test_reader import binary
    path=tmp_path/'repeat.001';path.write_bytes(binary());raw_hash=hashlib.sha256(path.read_bytes()).hexdigest()
    parser=reader._read_binary;calls=[]
    def parse(*args):calls.append(1);return parser(*args)
    monkeypatch.setattr(reader,'_read_binary',parse)
    a=read_dataset(path);b=read_dataset(path)
    assert calls==[1] and a is not b and a.values is not b.values
    a.values[0,1]=999;a.metadata['Sample']=['changed'];a.warnings.append('changed')
    c=read_dataset(path);assert c.values[0,1]!=999 and c.metadata['Sample']!=['changed'] and not c.warnings
    assert c.sha256==raw_hash and c.path==path.resolve()
    path.write_bytes(binary()+b'changed footer')
    d=read_dataset(path);assert len(calls)==2 and d.sha256!=raw_hash


def test_batch_reuses_calculation_without_reusing_mass_or_mutable_arrays(tmp_path,monkeypatch):
    from tma_app import batch_analysis as batch
    from pathlib import Path
    batch._CALC_CACHE.clear()
    path=tmp_path/'batch.001';path.write_bytes(Path('测试文件/20261013-9#.001').read_bytes())
    detector=batch.original.detect_T2_T1_super_gradient;calls=[]
    def detect(*args):calls.append(1);return detector(*args)
    monkeypatch.setattr(batch.original,'detect_T2_T1_super_gradient',detect)
    a=batch.calculate_file(path);b=batch.calculate_file(path)
    assert not a['error'] and a['T1']==b['T1'] and len(calls)==1
    a['xs'][0]=999;a['M']=999;a['details']['changed']=True
    c=batch.calculate_file(path)
    assert c['xs'][0]!=999 and c['M'] is None and 'changed' not in c['details']


def test_explicit_refresh_can_correct_an_already_normalized_comparison(ui,tmp_path):
    from tma_app import mass_normalization
    imported(ui,tmp_path,2);source=sheet(tmp_path);settings.save_paths({'m':source})
    mass.lookup_record('sample-0',source)
    mass_normalization.apply(ui,ui.active_document(),{c.uid:v for c,v in zip(ui.curves,[.46,.55])})
    with open(source,'w',encoding='utf-8-sig') as handle:handle.write('sample,M (mg)\nsample-0,0.49\nsample-1,0.55\n')
    dialog=ui.show_mass_normalization();QApplication.processEvents();wait_until(lambda:dialog.mass_job is None)
    assert dialog.edits[0].text()=='0.46'
    dialog.refresh_button.click();wait_until(lambda:dialog.mass_job is None)
    assert dialog.edits[0].text()=='0.49'
    for check in dialog.checks:check.setChecked(True)
    dialog.accept();assert ui.curves[0].mass_normalization_mg==.49
