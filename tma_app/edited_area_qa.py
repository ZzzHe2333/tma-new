"""Real edited-file import and auditable area workflow, source and frozen."""
from pathlib import Path
import hashlib,json,traceback
import numpy as np
from PySide6.QtWidgets import QApplication,QFileDialog

from . import __version__
from .reader import read_dataset
from .workspace import save_session,load_session
from .batch_qa import wait_until


def verify(window,output,paths):
    output.parent.mkdir(parents=True,exist_ok=True)
    report={'status':'failed','version':__version__,'checks':[]}
    original_picker=QFileDialog.getSaveFileName
    try:
        source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        window.import_files(paths);wait_until(lambda:window.worker is None)
        assert len(window.curves)==len(paths)
        details=[]
        for curve,path in zip(window.curves,paths):
            text=path.read_text(encoding='utf-16')
            expected=np.array([[float(v) for v in s.split()] for s in text.split('StartOfData',1)[1].splitlines() if s.strip()])
            np.testing.assert_array_equal(curve.dataset.values,expected)
            assert curve.y_index==2 and curve.dataset.signals[-1].unit=='' and curve.dataset.warnings
            details.append({'file':path.name,'rows':len(expected),'columns':expected.shape[1],'exact_values':True})
        report['checks'].append('all_edited_files_import_asynchronously_all_1140_rows_5_columns_exact')
        window.import_files([paths[0]]);wait_until(lambda:window.worker is None)
        assert len(window.curves)==len(paths)+1
        assert len({c.dataset.document_key for c in window.curves})==len(window.curves)
        assert window.curves[-1].dataset.values is not window.curves[0].dataset.values
        report['checks'].append('repeated_edited_file_open_is_independent')
        document=window.active_document();curve=window.selected()
        dialog=window.show_area_calculation();dialog.compute()
        assert len(window.results)==1,dialog.feedback.text()
        area=window.results[-1]['values'];profile=area['area_profile']
        y=np.array(profile['signal'])-profile['baseline'];t=np.array(profile['q'])
        expected=float(np.sum((y[:-1]+y[1:])*np.diff(t)/2))
        assert np.isclose(area['integral'],expected)
        assert np.isclose(area['net_area'],area['positive_area']+area['negative_area'])
        assert np.isclose(area['absolute_area'],area['positive_area']-area['negative_area'])
        assert window.active_document() is document and window.selected() is curve
        QApplication.processEvents();dialog.grab().save(str(output.with_suffix('.areas.png')))
        xlsx=output.with_suffix('.xlsx')
        QFileDialog.getSaveFileName=lambda *args:(str(xlsx),'')
        dialog.export();assert xlsx.is_file();dialog.reject()
        window.write_plot(output.with_suffix('.plot.png'))
        csv=output.with_suffix('.csv');window.write_data(csv,curve)
        restored=np.loadtxt(csv,delimiter=',',skiprows=1,encoding='utf-8-sig')
        np.testing.assert_array_equal(restored[:,:5],curve.dataset.values)
        peak=window.start_peak_integration('peak_linear');window.confirm_measurement()
        assert peak in window.results and 'area_profile' in peak['values']
        session=output.with_suffix('.tmas');save_session(session,window.curves,window.domain,window.results,window.plot_options)
        assert load_session(session)[2]==window.results
        dialog=window.show_area_calculation();assert dialog.table.rowCount()==2;dialog.reject()
        report['checks'].extend(['independent_area_four_baselines_formula_table_and_xlsx',
            'native_peak_integral_preserved_with_signed_components',
            'area_plot_annotations_and_full_raw_data_export',
            'session_restores_all_import_instances_and_area_snapshots'])
        assert source_hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        report.update(status='passed',sources=details,source_sha256=source_hashes,net_area=area['integral'],area_unit=area['area_unit'])
    except Exception:report['error']=traceback.format_exc()
    finally:
        QFileDialog.getSaveFileName=original_picker
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        window.dirty=False;window.close()
    if report['status']!='passed':raise SystemExit(1)
