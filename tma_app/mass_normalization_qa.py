"""Exercise the shipped overlay control using read-only real TMA samples."""
import csv
import hashlib
import json
from pathlib import Path
import traceback

import numpy as np
from PySide6.QtWidgets import QApplication,QDialogButtonBox

from . import __version__


def verify(window,output,inputs):
    from .reader import read_dataset
    from .mass_lookup import lookup_record, MassMatch
    from .workspace import save_session,load_session
    from . import mass_normalization as core
    output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    report={'version':__version__,'status':'failed','checks':[]}
    try:
        assert len(inputs)==2
        hashes=[hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs]
        datasets=[read_dataset(path) for path in inputs]
        # This check supplies controlled CSV matches below; avoid racing an
        # unrelated automatic lookup for the isolated QA profile.
        for dataset in datasets:dataset._mass_match=MassMatch(message='m 正在后台匹配')
        window.finish_import(datasets,[])
        window.show_overlay();doc=window.active_document()
        original={c.uid:tuple(v.copy() for v in c.xy()) for c in window.curves}
        weights=output.with_suffix('.weights.csv')
        with weights.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(['样品名','M (mg)'])
            writer.writerows((c.sample_name,m) for c,m in zip(window.curves,[.46,.55]))
        for curve in window.curves:window.update_curve_mass(curve,lookup_record(curve.sample_name,str(weights)))
        QApplication.processEvents();doc.mass_normalize_button.click()
        dialog=window.dialogs['mass_normalization']
        assert dialog.isVisible() and [e.text() for e in dialog.edits]==['0.46','0.55']
        assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
        dialog.grab().save(str(output.with_suffix('.dialog.png')))
        dialog.reject();assert all(c.mass_normalization_factor==1 for c in window.curves)
        report['checks'].append('real_mass_csv_prefill_required_individual_confirmation_and_cancel')
        doc.mass_normalize_button.click();dialog=window.dialogs['mass_normalization']
        for check in dialog.checks:check.setChecked(True)
        assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
        dialog.accept()
        for curve,m in zip(window.curves,[.46,.55]):
            x,y=curve.xy();np.testing.assert_array_equal(x,original[curve.uid][0])
            np.testing.assert_allclose(y,original[curve.uid][1]*.50/m,rtol=1e-12,atol=1e-12)
        assert doc.windowTitle()=='Tong1-Tma'
        assert window.plot_options[doc.key]['export_title']=='Tong1-Tma'
        report['checks'].append('pointwise_0_50_over_mass_taller_smaller_temperature_unchanged_and_title')
        window.canvas.draw();QApplication.processEvents()
        window.grab().save(str(output.with_suffix('.window.png')))
        window.write_plot(output.with_suffix('.plot.png'))
        saved={c.uid:c.xy()[1].copy() for c in window.curves}
        copied=window.copy_overlay(doc.key)
        core.apply(window,copied,{c.uid:.50 for c in window.curves})
        window._show_document(doc.key)
        for curve in window.curves:np.testing.assert_array_equal(curve.xy()[1],saved[curve.uid])
        window.show_normal()
        assert not window.active_document().mass_normalize_button.isVisible()
        for curve in window.curves:np.testing.assert_array_equal(curve.xy()[1],original[curve.uid][1])
        report['checks'].append('copied_overlay_and_normal_documents_independent')
        window._show_document(doc.key)
        core.apply(window,doc,{c.uid:m for c,m in zip(window.curves,[.46,.55])})
        for curve in window.curves:np.testing.assert_array_equal(curve.xy()[1],saved[curve.uid])
        window.files.setCurrentItem(window.files.topLevelItem(0))
        entry=window.start_point_measurement('signal_max');window.confirm_measurement()
        assert np.isclose(entry['values']['max_y'],window.curves[0].xy()[1].max())
        session=output.with_suffix('.tmas')
        save_session(session,window.curves,window.domain,window.results,window.plot_options)
        loaded,_,results,options=load_session(session,include_plot_options=True)
        for curve in loaded:
            curve.activate_view(doc.key)
            np.testing.assert_array_equal(curve.xy()[1],saved[curve.uid])
        assert results[0]['values']==entry['values'] and options[doc.key]['window_name']=='Tong1-Tma'
        report['checks'].append('repeat_not_cumulative_scaled_analysis_and_session_roundtrip')
        dialog=window.show_mass_normalization(doc);dialog.restore_original()
        for curve in window.curves:np.testing.assert_array_equal(curve.xy()[1],original[curve.uid][1])
        assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs]==hashes
        report['checks'].append('restore_original_ratio_and_input_files_unchanged')
        report.update(status='passed',masses_mg=[.46,.55],height_factors=[.50/.46,.50/.55])
    except BaseException:report['error']=traceback.format_exc()
    finally:
        window.dirty=False;window.close()
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
