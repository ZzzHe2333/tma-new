"""Real-file native information editing, reread/reset, peer state and export QA."""
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
from tma_app.workspace import save_session


def main():
    root=Path(__file__).resolve().parents[1];out=root/'artifacts/file-info-verification';out.mkdir(parents=True,exist_ok=True)
    paths=sorted((root/'测试文件').glob('*.001'));hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(CLASSIC_STYLE)
    with tempfile.TemporaryDirectory(prefix='tma-file-info-qa-') as private:
        preferences.preferences_path=lambda:Path(private)/'preferences.json'
        window=ClassicMainWindow();window.resize(1920,1017);window.show()
        window.warn=lambda message:(_ for _ in ()).throw(AssertionError(message))
        window.import_files(paths[:3],synchronous=True);curve=window.selected();uid=curve.uid
        window.show_normal();doc=window.active_document();original_metadata=deepcopy(curve.dataset.metadata);raw=curve.dataset.values.copy()
        window.files.setCurrentItem(window.files.topLevelItem(0));other=window.start_point_measurement('signal_max');window.confirm_measurement()
        window.files.setCurrentItem(window.files.topLevelItem(2));window.duplicate_curve();peer=window.selected();window.files.setCurrentItem(window.files.topLevelItem(2))
        first=window.show_file_information();first.size_field.setText('2.5');first.accept()
        assert first.result()==QDialog.DialogCode.Accepted
        curve.working=curve.dataset.values[:,curve.y_index]*2;curve.operations=['explicit QA scaling by 2']
        own=window.start_alpha('alpha_fit');window.confirm_measurement();saved=deepcopy(own);working=curve.working
        window.classic_actions['FileInformation1'].trigger();info=window.dialogs['file_information'];app.processEvents()
        info.fields['Sample'].setText('文件信息验证样品');info.fields['Operator'].setText('QA operator');info.fields['Comment'].setText('QA text edit; source preserved')
        assert info.grab().save(str(out/'native-file-information.png'));info.accept()
        assert info.result()==QDialog.DialogCode.Accepted and own==saved and curve.working is working
        assert curve.file_info==peer.file_info and curve.dataset.metadata==original_metadata
        assert window.active_document() is doc and window.selected().uid==uid
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/'text-edit-preserves-analysis.png'))
        reset=window.show_file_information();reset.size_field.setText('2.75');reset.accept()
        assert reset.result()==QDialog.DialogCode.Accepted and window.results==[other]
        assert curve.sample_size_mm==peer.sample_size_mm==2.75 and curve.working is peer.working is None
        assert curve.operations==[] and curve.dataset.metadata==original_metadata
        np.testing.assert_array_equal(curve.dataset.values,raw)
        assert window.active_document() is doc and window.selected().uid==uid
        fresh=window.start_alpha('alpha_fit');window.confirm_measurement();assert fresh['alpha']['reference_length_mm']==2.75
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/'size-reload-and-new-alpha.png'))
        export=out/(curve.dataset.path.stem+'.png');window.write_plot(export)
        with Image.open(export) as image:assert image.info['Author']==image.info['Software']=='Power By ZzzHe'
        csv=out/'current-data.csv';window.write_data(csv,curve);meta=json.loads(Path(str(csv)+'.meta.json').read_text(encoding='utf-8'))
        assert meta['metadata']==original_metadata and meta['file_information']['sample_size_mm']==2.75
        assert meta['file_information']['text']['Sample']=='文件信息验证样品'
        session=out/'verified.tmas';save_session(session,window.curves,window.domain,window.results,window.plot_options)
        results=deepcopy(window.results);window.close_all_documents();window.restore_session(session);window._show_document(doc.key)
        restored=next(c for c in window.curves if c.uid==uid)
        assert restored.sample_size_mm==2.75 and restored.sample_name=='文件信息验证样品' and window.results==results
        assert restored.dataset.metadata==original_metadata
        assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        summary={'status':'passed','version':__version__,'source_sha256':hashes,'source_files_unchanged':True,'physical_files':3,'curves':4,
            'reference_sizes_mm':[2.5,2.75],'reference_size_evidence':'explicit synthetic QA inputs, not measured specimen dimensions',
            'native_geometry':[490,326],'text_edit_preserves_processing_and_analysis':True,'numeric_edit_rereads_raw_and_clears_only_source_analyses':True,
            'all_same_source_peers_synchronized':True,'selected_third_file_preserved':True,'source_metadata_unchanged':True,
            'csv_effective_information_and_source_metadata_readback':True,'session_roundtrip':True,'user_preferences_untouched':True,
            'export_credit':'Power By ZzzHe','session':str(session),'cell_calibration_exotherm_units_and_native_reload_detail_equivalence':'remaining','full_reconstruction_complete':False}
        (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in summary.items() if k!='source_sha256'},ensure_ascii=True,indent=2))
        window.dirty=False;window.close()


if __name__=='__main__':main()
