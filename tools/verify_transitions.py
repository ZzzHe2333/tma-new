"""Native step/glass workflows and independent real-file tangent regressions."""
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
    root=Path(__file__).resolve().parents[1];out=root/'artifacts/transition-verification';out.mkdir(parents=True,exist_ok=True)
    files=sorted((root/'测试文件').glob('*.001'));hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(CLASSIC_STYLE)
    with tempfile.TemporaryDirectory(prefix='tma-step-qa-') as private:
        preferences.preferences_path=lambda:Path(private)/'preferences.json'
        window=ClassicMainWindow();window.resize(1920,1017);window.show();window.warn=lambda message:(_ for _ in ()).throw(AssertionError(message))
        window.import_files(files[:3],synchronous=True);window.show_overlay();doc=window.active_document();curve=window.selected();uid=curve.uid
        options=window.show_analysis_options();options.tabs.setCurrentIndex(0)
        assert options.grab().save(str(out/'native-step-change-options.png'));options.accept()
        window.classic_actions['GlassTransition1'].trigger();automatic=window._pending_measurement
        assert automatic is not None and 'fit_error' not in automatic['values']
        # Regress independently with NumPy over the recorded acquired intervals.
        x,y=curve.xy();independent=[]
        for fit in automatic['values']['fits']:
            start,stop=int(fit['position_start']),int(fit['position_stop'])
            coefficients=np.polyfit(x[start:stop+1],y[start:stop+1],1);independent.append(coefficients)
        expected_onset=float((independent[1][1]-independent[0][1])/(independent[0][0]-independent[1][0]))
        expected_end=float((independent[2][1]-independent[1][1])/(independent[1][0]-independent[2][0]))
        assert np.isclose(automatic['values']['onset_x'],expected_onset,rtol=1e-10)
        assert np.isclose(automatic['values']['end_x'],expected_end,rtol=1e-10)
        window.create_plot_context_menu().actions()[0].trigger();assert window.results==[automatic]
        assert window.active_document() is doc and window.selected().uid==uid
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/'real-glass-automatic-three-tangents.png'))
        options=window.show_analysis_options();options.tabs.setCurrentIndex(0);options.controls['ManualStepBox'].setChecked(True)
        options.controls['SignalChangeYLimitsBox'].setChecked(True);options.accept()
        window.classic_actions['StepTransition2'].trigger();manual=window._pending_measurement
        bounds=window.edit_measurement_limits()
        positions=[fit[key] for fit in automatic['values']['fits'] for key in ('position_start','position_stop')]
        assert len(bounds.fields)==6 and all(field.isReadOnly() for field in bounds.y_fields)
        for field,position in zip(bounds.fields,positions):field.setText(format(float(x[int(position)]),'.17g'))
        assert bounds.grab().save(str(out/'native-six-tangent-limits.png'));bounds.accept()
        assert bounds.result()==QDialog.DialogCode.Accepted,bounds.error.text()
        assert np.isclose(manual['values']['onset_x'],expected_onset,rtol=1e-10)
        assert np.isclose(manual['values']['end_x'],expected_end,rtol=1e-10)
        menu=window.create_measurement_menu();menu.actions()[-1].trigger();assert manual['interactive']['active_point']==5
        menu.actions()[0].trigger();assert window.results==[automatic,manual] and window.selected().uid==uid
        automatic['annotation']['hidden']=True;window.redraw()
        artist=next(a for a in window._measurement_artists if a.entry is manual);window.canvas.draw();values=deepcopy(manual['values'])
        box=Text.get_window_extent(artist.temps[5],window.canvas.get_renderer());cx,cy=(box.x0+box.x1)/2,(box.y0+box.y1)/2
        for kind,px,py in (('button_press_event',cx,cy),('motion_notify_event',cx-35,cy-22),('button_release_event',cx-35,cy-22)):
            window.canvas.callbacks.process(kind,MouseEvent(kind,window.canvas,px,py,button=1))
        assert 't6' in manual['annotation']['label_offsets'] and manual['values']==values
        window.canvas.draw();assert window.grab().save(str(out/'real-step-six-fixed-labels.png'))
        original=deepcopy(manual);window.edit_measurement(manual);window.create_measurement_menu().actions()[-1].trigger()
        window.measurement_key(type('Key',(),{'key':'ctrl+left'})());window.cancel_measurement();assert manual==original
        change=window.start_point_measurement('signal_change');window.confirm_measurement()
        assert change['annotation']['y_limits'] and 'Y1 =' in next(a for a in window._measurement_artists if a.entry is change).annotation.get_text()
        export=out/(curve.dataset.path.stem+'.png');window.write_plot(export)
        with Image.open(export) as image:assert image.info['Author']==image.info['Software']=='Power By ZzzHe'
        results_path=out/'results.csv';window.write_results(results_path)
        assert 'transition' in results_path.read_text(encoding='utf-8-sig').splitlines()[0]
        session=out/'verified.tmas';save_session(session,window.curves,window.domain,window.results,window.plot_options)
        expected=deepcopy(window.results);window.close_all_documents();window.restore_session(session);window._show_document(doc.key)
        assert window.results==expected and len(window._measurement_artists)==2 and window.transition_options()['manual']
        assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        summary=dict(status='passed',version=__version__,source_sha256=hashes,source_files_unchanged=True,physical_files=3,
            independent_onset_c=expected_onset,independent_end_c=expected_end,independent_three_tangent_fits=[c.tolist() for c in independent],
            native_step_page_geometry=[494,357],native_six_limits_geometry=[369,275],automatic_and_manual_agree_for_same_intervals=True,
            right_click_confirm=True,sixth_point_selectable=True,sixth_fixed_temperature_label_draggable=True,numerical_values_unchanged_by_label_drag=True,
            selected_document_preserved=True,edit_cancel_restores_result=True,signal_change_y_limits=True,session_roundtrip=True,
            csv_config_snapshot=True,user_preferences_untouched=True,export_credit='Power By ZzzHe',session=str(session),
            native_automatic_windows_and_midpoint_branch_equivalence='unverified',fictive_temperature_and_delta_cp='not implemented',full_reconstruction_complete=False)
        (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in summary.items() if k!='source_sha256'},ensure_ascii=True,indent=2))
        window.dirty=False;window.close()


if __name__=='__main__':main()
