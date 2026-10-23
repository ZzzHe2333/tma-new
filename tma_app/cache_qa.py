"""Frozen-capable, isolated cache and automatic mass-normalization checks."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import traceback
import uuid

from PySide6.QtWidgets import QApplication

from . import __version__, mass_lookup as mass, mass_cache as cache, path_settings as settings
from .batch_qa import wait_until
from .reader import read_dataset


def verify(window, output, paths):
    output.parent.mkdir(parents=True, exist_ok=True)
    report={'version':__version__,'status':'failed','checks':[]}
    previous_appdata=os.environ.get('LOCALAPPDATA');previous_mass=os.environ.get('TMA_MASS_XLSX')
    os.environ['LOCALAPPDATA']=str(output.parent/('cache-fixture-'+uuid.uuid4().hex[:8]))
    os.environ.pop('TMA_MASS_XLSX',None)
    loader=mass._load_source_records;loads=[]
    try:
        mass.clear_cache()
        before={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        datasets=[read_dataset(path) for path in paths]
        window.finish_import(datasets,[]);window.show_overlay();QApplication.processEvents()
        document=window.active_document();selected=window.selected()
        source=output.with_suffix('.weights.csv')
        def weights(first):
            with source.open('w',encoding='utf-8-sig',newline='') as handle:
                writer=csv.writer(handle);writer.writerow(['sample','M (mg)'])
                for i,dataset in enumerate(datasets):writer.writerow([dataset.name,first if i==0 else .55])
        weights(.46);settings.save_paths({'m':str(source)})
        def tracked(*args,**kwargs):loads.append(1);return loader(*args,**kwargs)
        mass._load_source_records=tracked
        for _ in range(5):
            assert mass.lookup_record(datasets[0].name,str(source)).value==.46
            assert mass.lookup_record(datasets[1].name,str(source)).value==.55
        assert len(loads)==1
        report['checks'].append('one_source_read_for_repeated_samples_and_shared_index')
        cache.clear(disk=False);mass._table_cache.clear()
        assert mass.lookup_record(datasets[1].name,str(source)).value==.55 and len(loads)==1
        report['checks'].append('persistent_mass_snapshot_reused_after_memory_reset_without_source_io')
        dialog=window.show_mass_normalization();QApplication.processEvents()
        wait_until(lambda:dialog.mass_job is None)
        assert [edit.text() for edit in dialog.edits]==['0.46','0.55']
        assert not any(check.isChecked() for check in dialog.checks) and len(loads)==1
        report['checks'].append('normalization_automatically_fills_m_from_shared_cache_requires_confirmation')
        weights(.49);dialog.refresh_button.click();wait_until(lambda:dialog.mass_job is None)
        assert [edit.text() for edit in dialog.edits]==['0.49','0.55'] and len(loads)==2
        dialog.grab().save(str(output.with_suffix('.normalization.png')))
        for check in dialog.checks:check.setChecked(True)
        dialog.accept()
        assert [c.mass_normalization_mg for c in window.curves]==[.49,.55]
        assert window.active_document() is document and window.selected() is selected
        report['checks'].append('explicit_refresh_reloads_once_and_normalization_uses_corrected_m')
        settings_dialog=window.show_path_settings();QApplication.processEvents()
        assert settings_dialog.cache_hours.value()==24
        settings_dialog.grab().save(str(output.with_suffix('.settings.png')))
        settings_dialog.reject()
        original=read_dataset(paths[0]);other=read_dataset(paths[0]);other.values[0,1]+=123
        assert read_dataset(paths[0]).values[0,1]==original.values[0,1]
        report['checks'].append('reused_raw_curves_return_independent_mutable_arrays')
        assert before=={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        report.update(status='passed',source_reads=len(loads),source_sha256=before)
    except Exception:report['error']=traceback.format_exc()
    finally:
        mass._load_source_records=loader
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        window.dirty=False;window.close();mass.clear_cache()
        if previous_appdata is None:os.environ.pop('LOCALAPPDATA',None)
        else:os.environ['LOCALAPPDATA']=previous_appdata
        if previous_mass is None:os.environ.pop('TMA_MASS_XLSX',None)
        else:os.environ['TMA_MASS_XLSX']=previous_mass
    if report['status']!='passed':raise SystemExit(1)
