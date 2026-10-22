"""Real-file canonical buffers, TMA units/origins, mixed-axis views and export QA."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from copy import deepcopy
import hashlib,json,tempfile
import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication,QDialog
from tma_app import preferences,__version__
from tma_app.classic import ClassicMainWindow,CLASSIC_STYLE
from tma_app.data_limits import smoothed_state
from tma_app.workspace import save_session


def main():
    root=Path(__file__).resolve().parents[1];out=root/'artifacts/units-verification';out.mkdir(parents=True,exist_ok=True)
    paths=sorted((root/'测试文件').glob('*.001'));hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(CLASSIC_STYLE)
    with tempfile.TemporaryDirectory(prefix='tma-units-qa-') as private:
        preferences.preferences_path=lambda:Path(private)/'preferences.json'
        window=ClassicMainWindow();window.resize(1920,1017);window.show()
        window.warn=lambda message:(_ for _ in ()).throw(AssertionError(message))
        window.import_files(paths[:3],synchronous=True);selected=window.selected();uid=selected.uid
        window.show_overlay();doc=window.active_document();curves=window.curves
        curves[0].sample_size_mm=1.25;curves[1].sample_size_mm=2.5;curves[2].sample_size_mm=0.
        curves[0].data_indices=list(range(300,800));curves[0].y_type='d_temperature'
        for key,value in smoothed_state(curves[0],'temperature',0.).items():setattr(curves[0],key,value)
        canonical=curves[0].working.copy();curves[0].offset=1.;curves[1].offset=10.
        window.redraw();window.classic_actions['Units1'].trigger();dialog=window.dialogs['units']
        dialog.dimension.setCurrentIndex(dialog.dimension.findData('µm/m'));app.processEvents()
        assert dialog.grab().save(str(out/'native-units-form.png'));dialog.accept()
        assert dialog.result()==QDialog.DialogCode.Accepted and window.active_document() is doc and window.selected().uid==uid
        assert len(window._plot_artists)==3 and len({c.axis for c,x,y in window._plot_artists})==3
        assert curves[0].plot_label=='Alpha (µm/m/°C)' and curves[1].result_unit=='µm/m' and curves[2].result_unit=='µm'
        np.testing.assert_array_equal(curves[0].working,canonical)
        # Independent nearest-five OLS at one interior acquired sample.
        c=curves[0];rows=c.active_rows;raw=c.dataset.values;temperature=raw[rows,c.dataset.temperature_index].astype(float);dimension=raw[rows,c.y_index].astype(float)
        center=100;near=np.lexsort((np.arange(len(rows)),np.abs(temperature-temperature[center])))[:5]
        design=np.column_stack((temperature[near]-temperature[center],np.ones(5)))
        slope=float(np.linalg.lstsq(design,dimension[near],rcond=None)[0][0]);expected=(slope+1)*1000/1.25
        assert np.isclose(c.xy()[1][center],expected,rtol=1e-8,atol=1e-8)
        np.testing.assert_allclose(curves[1].xy()[1],(curves[1].dataset.values[:,2]+10)*1000/2.5)
        np.testing.assert_allclose(curves[2].xy()[1],curves[2].dataset.values[:,2])
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/'normalized-alpha-and-size-fallback.png'))
        # A single-file origin change propagates into the already open overlay.
        window.files.setCurrentItem(window.files.topLevelItem(1));window.show_normal();normal=window.active_document()
        normal_offset=curves[1].offset
        origin=window.show_units();origin.dimension.setCurrentIndex(origin.dimension.findData('µm'));origin.offset.setCurrentIndex(origin.offset.findData('zero_size'));origin.accept()
        np.testing.assert_allclose(curves[1].xy()[1],curves[1].dataset.values[:,2]+2500+normal_offset)
        mark=window.start_point_measurement('signal_max');window.confirm_measurement();assert window.results==[mark]
        missing=window.show_units();missing.offset.setCurrentIndex(missing.offset.findData('at25'));missing.accept()
        assert not window.results and curves[1].unit_options['offset']=='at25'
        np.testing.assert_allclose(curves[1].xy()[1],curves[1].dataset.values[:,2]+normal_offset)
        window._show_document(doc.key);assert len(window._plot_artists)==3
        window.files.setCurrentItem(window.files.topLevelItem(2))
        point=window.start_point_measurement('curve_value_y');window.confirm_measurement();window.dialogs['label_point'].accept()
        assert window.results==[point]
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/'independent-origin-fallback-view.png'))
        export=out/(selected.dataset.path.stem+'.png');window.write_plot(export)
        with Image.open(export) as image:assert image.info['Author']==image.info['Software']=='Power By ZzzHe'
        csv=out/'current-data.csv';window.write_data(csv,curves[0]);meta=json.loads(Path(str(csv)+'.meta.json').read_text(encoding='utf-8'))
        assert meta['transform']['units']=={'dimension':'µm/m','offset':'none'} and meta['transform']['units_reference']['original_size_mm']==1.25
        session=out/'verified.tmas';save_session(session,window.curves,window.domain,window.results,window.plot_options)
        states=[(deepcopy(c.unit_options),c.sample_size_mm,c.xy()[1].copy()) for c in curves]
        window.close_all_documents();window.restore_session(session);window._show_document(doc.key)
        for restored,(options,size,y) in zip(window.curves,states):
            assert restored.unit_options==options and restored.sample_size_mm==size;np.testing.assert_allclose(restored.xy()[1],y)
        assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        summary={'status':'passed','version':__version__,'source_sha256':hashes,'source_files_unchanged':True,'physical_files':3,
            'reference_sizes_mm':[1.25,2.5,0.],'reference_size_evidence':'explicit synthetic QA inputs, not measured specimen dimensions',
            'native_geometry':[638,450],'independent_local_slope_um_per_c':slope,'independent_displayed_alpha':expected,
            'canonical_working_buffer_unchanged':True,'mixed_units_three_y_axes_visible':True,'zero_size_unnormalized_fallback':True,
            'absolute_size_origin_checked':True,'missing_25_reference_no_extrapolation':True,'other_open_overlay_keeps_all_curves':True,
            'unit_change_clears_affected_analysis':True,'physical_y_offsets_checked':True,'csv_units_reference_readback':True,
            'session_roundtrip':True,'selected_document_preserved':True,'user_preferences_untouched':True,'export_credit':'Power By ZzzHe','session':str(session),
            'general_and_other_instrument_unit_conversions':'remaining','native_scope_reference_branch_and_axis_allocation_equivalence':'unverified','full_reconstruction_complete':False}
        (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in summary.items() if k!='source_sha256'},ensure_ascii=True,indent=2))
        window.dirty=False;window.close()


if __name__=='__main__':main()
