"""Real-file peak/onset/automatic-limit workflows and independent regressions."""
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
    root=Path(__file__).resolve().parents[1];out=root/'artifacts/peak-onset-verification';out.mkdir(parents=True,exist_ok=True)
    files=sorted((root/'测试文件').glob('*.001'));hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(CLASSIC_STYLE)
    with tempfile.TemporaryDirectory(prefix='tma-peak-qa-') as private:
        preferences.preferences_path=lambda:Path(private)/'preferences.json'
        window=ClassicMainWindow();window.resize(1920,1017);window.show()
        window.warn=lambda message:(_ for _ in ()).throw(AssertionError(message))
        window.import_files(files[:3],synchronous=True)
        # Explicitly choose a non-first file, covering the reported selection regression.
        target=window.curves[1];doc=window._show_document(str(target.dataset.path));window.files.setCurrentItem(window.files.topLevelItem(1))
        uid=window.selected().uid;raw={c.uid:c.dataset.values.copy() for c in window.curves}
        options=window.show_analysis_options();options.tabs.setCurrentIndex(1)
        options.controls['ManualOnsetBox'].setChecked(False);options.controls['WidthBox'].setChecked(True)
        assert options.grab().save(str(out/'native-peak-onset-options.png'));options.accept()
        window.classic_actions['PeakMax1'].trigger();peak=window._pending_measurement
        assert peak is not None and 'fit_error' not in peak['values']
        x,y=target.xy();a,b=peak['interactive']['indices'];xx=x[a:b+1];yy=y[a:b+1]
        baseline=yy[0]+(yy[-1]-yy[0])*(xx-xx[0])/(xx[-1]-xx[0]);residual=yy-baseline;k=int(np.argmax(abs(residual)))
        assert np.isclose(peak['values']['height'],residual[k]) and peak['values']['max_x']==xx[k]
        # Independent connected half-height crossings on the actual acquired data.
        response=residual*np.sign(residual[k]);half=abs(residual[k])/2;left=right=None
        for i in range(k-1,-1,-1):
            if response[i]<=half<=response[i+1] and response[i]!=response[i+1]:
                left=float(np.interp(half,response[i:i+2],xx[i:i+2]));break
        for i in range(k,len(xx)-1):
            if response[i]>=half>=response[i+1] and response[i]!=response[i+1]:
                right=float(np.interp(half,response[i:i+2][::-1],xx[i:i+2][::-1]));break
        width=None if left is None or right is None else abs(right-left)
        assert width is None and peak['values']['width_half_height'] is None or np.isclose(width,peak['values']['width_half_height'])
        before=deepcopy(peak['interactive']);auto=window.show_auto_limits();auto.auto_set()
        assert auto.grab().save(str(out/'native-peak-auto-limits.png'))
        auto.save();assert peak['interactive']==before;auto.reject()
        auto=window.show_auto_limits();auto.accept();assert auto.result()==QDialog.DialogCode.Accepted,auto.error.text()
        np.testing.assert_allclose(peak['interactive']['positions'],before['indices'],atol=1e-10)
        window.create_plot_context_menu().actions()[0].trigger()
        assert window.active_document() is doc and window.selected().uid==uid and window._pending_measurement is None
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/'real-baseline-peak.png'))
        # Each fixed endpoint label remains independently movable without changing results.
        artist=next(a for a in window._measurement_artists if a.entry is peak);values=deepcopy(peak['values'])
        box=Text.get_window_extent(artist.temps[0],window.canvas.get_renderer());cx,cy=(box.x0+box.x1)/2,(box.y0+box.y1)/2
        for kind,px,py in (('button_press_event',cx,cy),('motion_notify_event',cx+32,cy+24),('button_release_event',cx+32,cy+24)):
            window.canvas.callbacks.process(kind,MouseEvent(kind,window.canvas,px,py,button=1))
        assert 't1' in peak['annotation']['label_offsets'] and peak['values']==values
        window.classic_actions['OnsetPoint1'].trigger();automatic=window._pending_measurement
        assert automatic is not None and 'fit_error' not in automatic['values']
        fits=automatic['values']['fits'];acquired=automatic['interactive']['indices'];x,y=target.xy()
        # Use selected automatic intervals, then independently fit two manual OLS lines.
        positions=[fit[key] for fit in fits for key in ('position_start','position_stop')]
        coefficients=[np.polyfit(x[int(positions[i]):int(positions[i+1])+1],y[int(positions[i]):int(positions[i+1])+1],1) for i in (0,2)]
        expected=float((coefficients[1][1]-coefficients[0][1])/(coefficients[0][0]-coefficients[1][0]))
        window.create_measurement_menu().actions()[0].trigger();automatic['annotation']['hidden']=True
        options=window.show_analysis_options();options.controls['ManualOnsetBox'].setChecked(True);options.accept()
        window.classic_actions['OnsetPoint1'].trigger();manual=window._pending_measurement;limits=window.edit_measurement_limits()
        assert len(limits.fields)==4 and all(f.isReadOnly() for f in limits.y_fields)
        for field,position in zip(limits.fields,positions):field.setText(format(float(x[int(position)]),'.17g'))
        assert limits.grab().save(str(out/'native-four-tangent-limits.png'));limits.accept()
        assert limits.result()==QDialog.DialogCode.Accepted,limits.error.text()
        assert np.isclose(manual['values']['onset_x'],expected,rtol=1e-10)
        window.create_measurement_menu().actions()[-1].trigger();assert manual['interactive']['active_point']==3
        window.create_measurement_menu().actions()[0].trigger();assert window.active_document() is doc and window.selected().uid==uid
        window.canvas.draw();assert window.grab().save(str(out/'real-manual-onset.png'))
        saved=deepcopy(manual);window.edit_measurement(manual);window.activate_measurement_point(3)
        window.measurement_key(type('Key',(),{'key':'ctrl+left'})());window.cancel_measurement();assert manual==saved
        change=window.start_point_measurement('signal_change');auto=window.show_auto_limits();auto.defaults()
        assert auto.grab().save(str(out/'native-signal-fraction-limits.png'));auto.accept()
        assert auto.result()==QDialog.DialogCode.Accepted,auto.error.text()
        assert all(p['mode']=='fraction' and p['offset']==.05 for p in change['auto_limits']['endpoints'])
        window.create_measurement_menu().actions()[0].trigger()
        export=out/(target.dataset.path.stem+'.png');window.write_plot(export)
        with Image.open(export) as image:assert image.info['Author']==image.info['Software']=='Power By ZzzHe'
        csv=out/'results.csv';window.write_results(csv);header=csv.read_text(encoding='utf-8-sig').splitlines()[0]
        assert 'peak_onset' in header and 'auto_limits' in header
        session=out/'verified.tmas';save_session(session,window.curves,window.domain,window.results,window.plot_options);expected_results=deepcopy(window.results)
        window.close_all_documents();window.restore_session(session);window._show_document(doc.key)
        assert window.results==expected_results and len(window.results)==4
        for curve in window.curves:np.testing.assert_array_equal(curve.dataset.values,raw[curve.uid])
        assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        summary=dict(status='passed',version=__version__,source_sha256=hashes,source_files_unchanged=True,physical_files=3,
            independent_peak_height=float(residual[k]),independent_peak_temperature=float(xx[k]),independent_half_height_width=width,
            independent_manual_onset=expected,independent_two_tangent_fits=[c.tolist() for c in coefficients],
            native_peak_page_geometry=[494,357],native_peak_auto_geometry=[338,197],native_signal_auto_geometry=[314,197],
            read_only_four_tangent_y=True,fourth_marker_selectable=True,right_click_confirm=True,fixed_temperature_label_draggable=True,
            selected_nonfirst_document_preserved=True,numerical_values_unchanged_by_label_drag=True,auto_save_cancel_does_not_move_cursors=True,
            signal_derivative_fraction_default=.05,session_roundtrip=True,csv_config_snapshots=True,user_preferences_untouched=True,
            export_credit='Power By ZzzHe',session=str(session),automatic_onset_and_derivative_filter_exact_native_equivalence='unverified',
            peak_integration_and_area_options='not implemented',full_reconstruction_complete=False)
        (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in summary.items() if k!='source_sha256'},ensure_ascii=True,indent=2))
        window.dirty=False;window.close()


if __name__=='__main__':main()
