"""Independent real-file horizontal sigmoid iteration and native UI workflows."""
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
from tma_app.reader import read_dataset
from tma_app.workspace import Curve,save_session
from tma_app.peak_integration import values,defaults
from tma_app.peak_onset import defaults as peak_defaults
from tma_app.sigmoidal import validate_snapshot


def independent(time,signal,initial):
    def cumulative(response):return np.r_[0.,np.cumsum((response[:-1]+response[1:])*.5*np.diff(time))]
    baseline=initial.copy();running=cumulative(signal-baseline);area=float(running[-1]);history=[]
    if signal[0]==signal[-1] or np.all(signal==baseline):return baseline,running,history
    for i in range(10):
        fraction=running/area;baseline=(1-fraction)*signal[0]+fraction*signal[-1]
        running=cumulative(signal-baseline);new_area=float(running[-1]);delta=abs(new_area-area)/abs(area)
        history.append((baseline.copy(),new_area,delta));area=new_area
        if delta<=.01:return baseline,running,history
    raise AssertionError('Reference real-file calculation failed to converge')


def main():
    root=Path(__file__).resolve().parents[1];out=root/'artifacts/sigmoidal-verification';out.mkdir(parents=True,exist_ok=True)
    files=sorted((root/'测试文件').glob('*.001'));hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files};comparisons=[]
    for path in files:
        curve=Curve(read_dataset(path));x,y=curve.xy();time=curve.x_values('time');initial=y[0]+(y[-1]-y[0])/(x[-1]-x[0])*(x-x[0])
        baseline,cumulative,history=independent(time,y,initial)
        e=dict(kind='peak_sigmoid',domain='temperature',peak_onset=peak_defaults(),integration=defaults(),sigmoid=dict(draw_iterations=True))
        result=values(curve,e,[0,len(x)-1]);profile=result['sigmoid_profile'];validate_snapshot(profile,len(x))
        np.testing.assert_allclose(profile['baseline'],baseline,rtol=1e-12,atol=1e-12);np.testing.assert_allclose(profile['cumulative'],cumulative,rtol=1e-12,atol=1e-12)
        assert result['iteration_count']==len(history) and np.isclose(result['integral'],cumulative[-1],rtol=1e-12)
        assert all(np.isclose(step['area'],reference[1],rtol=1e-12) for step,reference in zip(profile['iterations'],history))
        comparisons.append(dict(file=path.name,independent_area=float(cumulative[-1]),iterations=len(history),onset=result['onset_x'],same_every_iteration=True))
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(CLASSIC_STYLE)
    with tempfile.TemporaryDirectory(prefix='tma-sigmoid-qa-') as private:
        preferences.preferences_path=lambda:Path(private)/'preferences.json'
        w=ClassicMainWindow();w.resize(1920,1017);w.show();w.warn=lambda message:(_ for _ in ()).throw(AssertionError(message))
        w.import_files(files[:3],synchronous=True);w.show_overlay();curve=w.curves[1];doc=w._show_document(str(curve.dataset.path));w.files.setCurrentItem(w.files.topLevelItem(1))
        raw={c.uid:c.dataset.values.copy() for c in w.curves}
        options=w.show_analysis_options();options.tabs.setCurrentIndex(4);options.controls['SigItterationsBox'].setChecked(True)
        assert options.grab().save(str(out/'native-iteration-options.png'));options.save();options.reject();assert w.sigmoid_iterations()
        w.classic_actions['SigHorizontal1'].trigger();automatic=w._pending_measurement
        assert automatic is not None and 'fit_error' not in automatic['values'];old=deepcopy(automatic['interactive'])
        auto=w.show_auto_limits();auto.auto_set();auto.accept();assert auto.result()==QDialog.DialogCode.Accepted,auto.error.text()
        np.testing.assert_allclose(automatic['interactive']['positions'],old['indices'],atol=1e-10)
        w.create_measurement_menu().actions()[0].trigger();assert w.active_document() is doc and w.selected().uid==curve.uid
        w.canvas.draw();app.processEvents();assert w.grab().save(str(out/'real-horizontal-sigmoid.png'))
        artist=next(a for a in w._measurement_artists if a.entry is automatic)
        assert len(artist.integration_lines[0].get_xdata())==len(automatic['values']['sigmoid_profile']['positions'])
        assert sum(bool(len(line.get_xdata())) for line in artist.iteration_lines)==max(1,automatic['values']['iteration_count'])
        # Labels and the result vectors are independent; dragging never refits.
        box=Text.get_window_extent(artist.temps[0],w.canvas.get_renderer());cx,cy=(box.x0+box.x1)/2,(box.y0+box.y1)/2;before=deepcopy(automatic['values'])
        for kind,x,y in (('button_press_event',cx,cy),('motion_notify_event',cx+29,cy+20),('button_release_event',cx+29,cy+20)):
            w.canvas.callbacks.process(kind,MouseEvent(kind,w.canvas,x,y,button=1))
        assert 't1' in automatic['annotation']['label_offsets'] and automatic['values']==before
        fit=automatic['values']['onset_fit'];assert fit is not None
        options=w.show_analysis_options();options.controls['ManualOnsetBox'].setChecked(True);options.accept()
        w.classic_actions['SigHorizontal1'].trigger();manual=w._pending_measurement;limits=w.edit_measurement_limits();xx,yy=curve.xy()
        positions=[0,len(xx)-1,fit['position_start'],fit['position_stop']]
        for field,position in zip(limits.fields,positions):field.setText(format(float(np.interp(position,np.arange(len(xx)),xx)),'.17g'));field.setCursorPosition(0)
        assert all(f.isReadOnly() for f in limits.y_fields);assert limits.grab().save(str(out/'native-four-sigmoid-limits.png'));limits.accept()
        assert limits.result()==QDialog.DialogCode.Accepted,limits.error.text()
        v=manual['values'];profile=v['sigmoid_profile'];mf=v['onset_fit'];ox,oy=v['onset_x'],v['onset_y'];position=v['onset_position']
        # Independent selected-interval OLS and piecewise baseline intersection.
        a,b=int(positions[2]),int(positions[3]);m,intercept=np.polyfit(xx[a:b+1],yy[a:b+1],1)
        assert np.isclose(m,mf['slope'],rtol=1e-10) and np.isclose(oy,m*ox+intercept,rtol=1e-10)
        assert np.isclose(oy,np.interp(position,profile['positions'],profile['baseline']),rtol=1e-10)
        w.create_measurement_menu().actions()[-1].trigger();assert manual['interactive']['active_point']==3
        w.create_plot_context_menu().actions()[0].trigger();assert w.active_document() is doc and w.selected().uid==curve.uid
        automatic['annotation']['hidden']=True;w.redraw();w.canvas.draw();assert w.grab().save(str(out/'real-manual-nonlinear-onset.png'))
        artist=next(a for a in w._measurement_artists if a.entry is manual);before=deepcopy(manual['values'])
        box=Text.get_window_extent(artist.onset_label,w.canvas.get_renderer());cx,cy=(box.x0+box.x1)/2,(box.y0+box.y1)/2
        for kind,x,y in (('button_press_event',cx,cy),('motion_notify_event',cx+25,cy+18),('button_release_event',cx+25,cy+18)):
            w.canvas.callbacks.process(kind,MouseEvent(kind,w.canvas,x,y,button=1))
        assert 'onset' in manual['annotation']['label_offsets'] and manual['values']==before
        saved=deepcopy(manual);w.edit_measurement(manual);w.activate_measurement_point(3);w.measurement_key(type('Key',(),{'key':'ctrl+left'})());w.cancel_measurement();assert saved==manual
        export=out/(curve.dataset.path.stem+'.png');w.write_plot(export)
        with Image.open(export) as im:assert im.info['Author']==im.info['Software']=='Power By ZzzHe'
        csv=out/'results.csv';w.write_results(csv);assert 'sigmoid' in csv.read_text(encoding='utf-8-sig').splitlines()[0]
        report=out/'verified-report.html';w.write_report(report);assert 'sigmoid_horizontal' in report.read_text(encoding='utf-8')
        session=out/'verified.tmas';save_session(session,w.curves,w.domain,w.results,w.plot_options);expected=deepcopy(w.results)
        w.close_all_documents();w.restore_session(session);w._show_document(doc.key);assert w.results==expected
        for c in w.curves:np.testing.assert_array_equal(c.dataset.values,raw[c.uid])
        assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        summary=dict(status='passed',version=__version__,source_sha256=hashes,source_files_unchanged=True,physical_files_plotted=3,
            independent_real_files=len(comparisons),independent_area_and_all_iterations=comparisons,manual_onset_temperature=ox,
            manual_onset_lies_on_baseline_and_selected_ols=True,selected_nonfirst_document_preserved=True,right_click_confirm=True,
            fixed_temperature_and_onset_labels_draggable=True,numerical_profiles_unchanged_by_label_drag=True,edit_cancel_restores_result=True,
            native_other_iteration_checkbox=True,per_page_save_without_applying_current_plot=True,session_roundtrip=True,
            csv_parameters_and_html_profile=True,export_credit='Power By ZzzHe',user_preferences_untouched=True,session=str(session),
            exact_original_convergence_denominator_crossing_and_nonlinear_heating_policies='unverified',peak_running_integral_and_y4='separately verified by tools/verify_running_integral.py',full_reconstruction_complete=False)
        (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in summary.items() if k!='source_sha256'},ensure_ascii=True,indent=2));w.dirty=False;w.close()


if __name__=='__main__':main()
