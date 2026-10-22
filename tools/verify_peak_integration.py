"""Independent real-file trapezoids and native linear integration workflows."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from copy import deepcopy
import hashlib,json,tempfile
import numpy as np
from PIL import Image
from matplotlib.backend_bases import MouseEvent
from matplotlib.text import Text
from PySide6.QtWidgets import QApplication,QDialog
from tma_app import __version__,preferences
from tma_app.classic import ClassicMainWindow,CLASSIC_STYLE
from tma_app.workspace import save_session


def main():
    root=Path(__file__).resolve().parents[1];out=root/'artifacts/integration-verification';out.mkdir(parents=True,exist_ok=True)
    files=sorted((root/'测试文件').glob('*.001'));hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(CLASSIC_STYLE)
    with tempfile.TemporaryDirectory(prefix='tma-integral-qa-') as private:
        preferences.preferences_path=lambda:Path(private)/'preferences.json'
        window=ClassicMainWindow();window.resize(1920,1017);window.show();window.warn=lambda message:(_ for _ in ()).throw(AssertionError(message))
        window.import_files(files[:3],synchronous=True);window.show_overlay();raw={c.uid:c.dataset.values.copy() for c in window.curves}
        options=window.show_analysis_options();options.tabs.setCurrentIndex(1);options.controls['ManualOnsetBox'].setChecked(False)
        options.controls['AreaBox'].setChecked(True);assert options.grab().save(str(out/'native-integration-options.png'));options.accept()
        independent=[];entries=[]
        for n,curve in enumerate(window.curves):
            doc=window._show_document(str(curve.dataset.path));window.files.setCurrentItem(window.files.topLevelItem(n));uid=curve.uid
            window.classic_actions['Linear1'].trigger();e=window._pending_measurement;assert e is not None and 'fit_error' not in e['values']
            x,y=curve.xy();time=curve.x_values('time');a,b=e['interactive']['indices']
            xx,yy,tt=x[a:b+1],y[a:b+1],time[a:b+1];baseline=yy[0]+(yy[-1]-yy[0])*(xx-xx[0])/(xx[-1]-xx[0]);residual=yy-baseline
            area=float(np.sum((residual[:-1]+residual[1:])*.5*np.diff(tt)));temperature_area=float(np.sum((residual[:-1]+residual[1:])*.5*np.diff(xx)))
            assert np.isclose(e['values']['integral'],area,rtol=1e-12) and not np.isclose(area,temperature_area)
            assert e['values']['area_unit']=='µm·min'
            if n==1:
                old=deepcopy(e['interactive']);auto=window.show_auto_limits();auto.auto_set();auto.save()
                assert e['interactive']==old;auto.reject();auto=window.show_auto_limits();auto.accept()
                assert auto.result()==QDialog.DialogCode.Accepted,auto.error.text()
                np.testing.assert_allclose(e['interactive']['positions'],old['indices'],atol=1e-10)
                assert window.create_measurement_menu().actions()[0].text()=='确定'
            window.create_plot_context_menu().actions()[0].trigger();assert window.active_document() is doc and window.selected().uid==uid
            entries.append(e);independent.append(dict(file=curve.dataset.path.name,time_area=area,temperature_area=temperature_area,unit=e['values']['area_unit']))
        curve=window.curves[1];doc=window._show_document(str(curve.dataset.path));window.files.setCurrentItem(window.files.topLevelItem(1));original=entries[1]
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/'real-linear-peak.png'))
        artist=next(a for a in window._measurement_artists if a.entry is original);old_values=deepcopy(original['values'])
        box=Text.get_window_extent(artist.temps[0],window.canvas.get_renderer());cx,cy=(box.x0+box.x1)/2,(box.y0+box.y1)/2
        for kind,px,py in (('button_press_event',cx,cy),('motion_notify_event',cx+30,cy+23),('button_release_event',cx+30,cy+23)):
            window.canvas.callbacks.process(kind,MouseEvent(kind,window.canvas,px,py,button=1))
        assert 't1' in original['annotation']['label_offsets'] and original['values']==old_values
        fit=original['values']['onset_fit'];assert fit is not None
        options=window.show_analysis_options();options.controls['ManualOnsetBox'].setChecked(True);options.accept()
        window.classic_actions['Linear1'].trigger();manual=window._pending_measurement;limits=window.edit_measurement_limits();x,y=curve.xy()
        positions=[0,len(x)-1,fit['position_start'],fit['position_stop']]
        for field,position in zip(limits.fields,positions):field.setText(format(float(x[int(position)]),'.17g'));field.setCursorPosition(0)
        assert all(f.isReadOnly() for f in limits.y_fields);assert limits.grab().save(str(out/'native-four-peak-limits.png'));limits.accept()
        assert limits.result()==QDialog.DialogCode.Accepted,limits.error.text()
        m,b=np.polyfit(x[int(positions[2]):int(positions[3])+1],y[int(positions[2]):int(positions[3])+1],1)
        base_m=float((y[-1]-y[0])/(x[-1]-x[0]));base_b=float(y[0]-base_m*x[0]);expected_onset=float((b-base_b)/(base_m-m))
        assert np.isclose(manual['values']['onset_x'],expected_onset,rtol=1e-10)
        assert np.isclose(manual['values']['integral'],original['values']['integral'])
        window.create_measurement_menu().actions()[-1].trigger();assert manual['interactive']['active_point']==3
        window.create_measurement_menu().actions()[0].trigger();assert window.active_document() is doc and window.selected().uid==curve.uid
        original['annotation']['hidden']=True;window.redraw();window.canvas.draw();assert window.grab().save(str(out/'real-manual-onset-area.png'))
        artist=next(a for a in window._measurement_artists if a.entry is manual);old_values=deepcopy(manual['values'])
        box=Text.get_window_extent(artist.onset_label,window.canvas.get_renderer());cx,cy=(box.x0+box.x1)/2,(box.y0+box.y1)/2
        for kind,px,py in (('button_press_event',cx,cy),('motion_notify_event',cx+26,cy+18),('button_release_event',cx+26,cy+18)):
            window.canvas.callbacks.process(kind,MouseEvent(kind,window.canvas,px,py,button=1))
        assert 'onset' in manual['annotation']['label_offsets'] and manual['values']==old_values
        saved=deepcopy(manual);window.edit_measurement(manual);window.activate_measurement_point(3)
        window.measurement_key(type('Key',(),{'key':'ctrl+left'})());window.cancel_measurement();assert saved==manual
        export=out/(curve.dataset.path.stem+'.png');window.write_plot(export)
        with Image.open(export) as image:assert image.info['Author']==image.info['Software']=='Power By ZzzHe'
        csv=out/'results.csv';window.write_results(csv);assert 'integration' in csv.read_text(encoding='utf-8-sig').splitlines()[0]
        session=out/'verified.tmas';save_session(session,window.curves,window.domain,window.results,window.plot_options);expected_results=deepcopy(window.results)
        window.close_all_documents();window.restore_session(session);window._show_document(doc.key);assert window.results==expected_results
        for c in window.curves:np.testing.assert_array_equal(c.dataset.values,raw[c.uid])
        assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        summary=dict(status='passed',version=__version__,source_sha256=hashes,source_files_unchanged=True,physical_files=3,
            independent_areas=independent,independent_manual_onset=expected_onset,selected_nonfirst_document_preserved=True,
            four_manual_markers=True,read_only_manual_y=True,right_click_confirm=True,fixed_temperature_label_draggable=True,separate_onset_label_draggable=True,
            numerical_values_unchanged_by_label_drag=True,auto_save_cancel_does_not_move_cursors=True,session_roundtrip=True,csv_config_snapshot=True,
            export_credit='Power By ZzzHe',user_preferences_untouched=True,session=str(session),
            baseline_policy='straight line in current displayed X; integrate residual over recorded time',
            exact_native_nonlinear_heating_baseline_and_onset_rules='unverified',native_superheating_exception='not implemented',
            calorimetric_normalization_and_other_instruments='not implemented',full_reconstruction_complete=False)
        (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in summary.items() if k!='source_sha256'},ensure_ascii=True,indent=2))
        window.dirty=False;window.close()


if __name__=='__main__':main()
