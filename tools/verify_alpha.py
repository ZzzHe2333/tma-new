"""Real TMA data with explicit QA-only sample size; no measured size is invented."""
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
from matplotlib.backend_bases import MouseEvent
from matplotlib.text import Text
from tma_app import preferences,__version__
from tma_app.classic import ClassicMainWindow,CLASSIC_STYLE
from tma_app.workspace import save_session


def independent_position(x,target):
    for i,value in enumerate(x):
        if value==target:return float(i)
        if i+1<len(x) and min(value,x[i+1])<target<max(value,x[i+1]):return i+(target-value)/(x[i+1]-value)
    raise AssertionError('No acquired crossing')


def main():
    root=Path(__file__).resolve().parents[1];out=root/'artifacts/alpha-verification';out.mkdir(parents=True,exist_ok=True)
    paths=sorted((root/'测试文件').glob('*.001'));hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(CLASSIC_STYLE)
    with tempfile.TemporaryDirectory(prefix='tma-alpha-qa-') as private:
        preferences.preferences_path=lambda:Path(private)/'preferences.json'
        window=ClassicMainWindow();window.resize(1920,1017);window.show()
        window.warn=lambda message:(_ for _ in ()).throw(AssertionError(message))
        window.import_files(paths[:3],synchronous=True);curve=window.selected();uid=curve.uid
        window.show_overlay();doc=window.active_document();window.plot_options[doc.key]['axis_x_offsets'][0]=7;window.redraw()
        window.classic_actions['AlphaAtX1'].trigger();size=window.dialogs['sample_size'];app.processEvents()
        assert size.grab().save(str(out/'sample-size-form.png'))
        size.field.setText('2.5');size.accept()
        assert window._pending_measurement['kind']=='alpha_at_x' and curve.sample_size_mm==2.5
        window.cancel_measurement()
        options=window.show_analysis_options();options.width_field.setText('4.5');app.processEvents()
        assert options.grab().save(str(out/'analysis-other-page.png'));options.accept()
        raw=curve.dataset.values;temp=raw[:,curve.dataset.temperature_index].astype(float);signal=raw[:,curve.y_index].astype(float)
        expected={};saved_entries=[]
        for action,kind,targets in (('AlphaAtX1','alpha_at_x',[175.5]),('AlphaX1ToX21','alpha_secant',[165.25,180.75]),('AlphaFitX1ToX21','alpha_fit',[165.25,180.75])):
            window.classic_actions[action].trigger();entry=window._pending_measurement;manual=window.edit_measurement_limits()
            for field,target in zip(manual.fields,targets):field.setText(str(target))
            manual.accept();assert manual.result()==QDialog.DialogCode.Accepted and manual.y_fields[0].isReadOnly()
            positions=[independent_position(temp,target) for target in targets]
            np.testing.assert_allclose(entry['interactive']['positions'],positions,rtol=0,atol=1e-10)
            if kind=='alpha_at_x':
                indices=np.flatnonzero((temp>=targets[0]-2.25)&(temp<=targets[0]+2.25));px,py=temp[indices],signal[indices]
            else:
                a,b=positions;indices=np.array([a]+[float(i) for i in range(int(np.floor(a))+1,int(np.ceil(b)))]+[b])
                px=np.interp(indices,np.arange(len(temp)),temp);py=np.interp(indices,np.arange(len(signal)),signal)
            if kind=='alpha_secant':slope=(py[-1]-py[0])/(px[-1]-px[0])
            else:
                design=np.column_stack((px-px.mean(),np.ones(len(px))))
                slope=float(np.linalg.lstsq(design,py,rcond=None)[0][0])
            coefficient=float(slope/2.5*1000);expected[kind]={'independent_slope_um_per_c':float(slope),'independent_alpha_um_per_m_per_c':coefficient,'fit_points':len(px)}
            assert np.isclose(entry['values']['alpha'],coefficient,rtol=1e-10,atol=1e-10)
            window.create_plot_context_menu().actions()[0].trigger()
            assert window._pending_measurement is None and window.selected().uid==uid and window.active_document() is doc
            saved_entries.append(deepcopy(entry))
        assert window.results==saved_entries
        # Each confirmed label moves independently of its saved numerical values.
        label_drags=[]
        for entry in window.results:
            editor=next(e for e in window._measurement_artists if e.entry is entry);window.canvas.draw()
            box=Text.get_window_extent(editor.annotation,window.canvas.get_renderer());px,py=(box.x0+box.x1)/2,(box.y0+box.y1)/2
            values=deepcopy(entry['values'])
            for name,x,y in (('button_press_event',px,py),('motion_notify_event',px+24,py+17),('button_release_event',px+24,py+17)):
                window.canvas.callbacks.process(name,MouseEvent(name,window.canvas,x,y,button=1))
            assert 'offset' in entry['annotation'] and entry['values']==values;label_drags.append(entry['kind'])
        temperature_drags=[]
        for entry in reversed(window.results):
            if entry['kind']=='alpha_at_x':continue
            editor=next(e for e in window._measurement_artists if e.entry is entry)
            for index,text in enumerate(editor.temps):
                window.canvas.draw();box=Text.get_window_extent(text,window.canvas.get_renderer());px,py=(box.x0+box.x1)/2,(box.y0+box.y1)/2
                # Separate the two analyses' initially shared endpoint labels.
                dx,dy=(-75,-42) if entry['kind']=='alpha_fit' else (30,20)
                values=deepcopy(entry['values'])
                for name,a,b in (('button_press_event',px,py),('motion_notify_event',px+dx,py+dy),('button_release_event',px+dx,py+dy)):
                    window.canvas.callbacks.process(name,MouseEvent(name,window.canvas,a,b,button=1))
                key=f't{index+1}'
                assert key in entry['annotation']['label_offsets'] and entry['values']==values
                temperature_drags.append(f"{entry['kind']}:{key}")
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/'three-alpha-results.png'))
        export=out/(curve.dataset.path.stem+'.png');window.write_plot(export)
        with Image.open(export) as image:assert image.info['Author']==image.info['Software']=='Power By ZzzHe'
        session=out/'verified.tmas';save_session(session,window.curves,window.domain,window.results,window.plot_options)
        saved=deepcopy(window.results);window.close_all_documents();window.restore_session(session);window._show_document(doc.key)
        assert window.results==saved and window.alpha_width()==4.5
        assert next(c for c in window.curves if c.uid==uid).sample_size_mm==2.5
        assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        summary={'status':'passed','version':__version__,'source_sha256':hashes,'source_files_unchanged':True,'physical_files':3,
            'reference_length_mm':2.5,'reference_length_evidence':'explicit synthetic QA parameter, not a measured specimen size',
            'alpha_width_c':4.5,'independent_coefficients':expected,'three_native_menu_routes':True,'native_sample_size_prompt':True,
            'native_analysis_other_page':True,'physical_coordinates_with_x_spacing':True,'selected_third_file_preserved':True,
            'confirmed_main_label_drag_kinds':label_drags,'session_roundtrip':True,'user_preferences_untouched':True,
            'confirmed_temperature_label_drags':temperature_drags,
            'export_credit':'Power By ZzzHe','session':str(session),'native_window_boundary_factory_defaults_and_exact_numerical_equivalence':'unverified','full_reconstruction_complete':False}
        (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in summary.items() if k!='source_sha256'},ensure_ascii=True,indent=2))
        window.dirty=False;window.close()


if __name__=='__main__':main()
