"""Real acquisition, independent OLS, general unit dialog and preserved sources."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from copy import deepcopy
import csv,hashlib,json,tempfile
import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication,QDialog
from tma_app import preferences,__version__
from tma_app.classic import ClassicMainWindow,CLASSIC_STYLE
from tma_app.data_limits import smoothed_state
from tma_app.limits_dialog import LimitBoundsDialog
from tma_app.workspace import save_session


def main():
    root=Path(__file__).resolve().parents[1];out=root/'artifacts/general-units-verification';out.mkdir(parents=True,exist_ok=True)
    paths=sorted((root/'测试文件').glob('*.001'));hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(CLASSIC_STYLE)
    with tempfile.TemporaryDirectory(prefix='tma-general-units-qa-') as private:
        preferences.preferences_path=lambda:Path(private)/'preferences.json'
        window=ClassicMainWindow();window.resize(1920,1017);window.show()
        window.warn=lambda message:(_ for _ in ()).throw(AssertionError(message))
        window.import_files(paths[:3],synchronous=True);window.show_overlay();doc=window.active_document();uid=window.selected().uid
        curve=window.curves[0];curve.data_indices=list(range(200,800));curve.y_type='d_time'
        for key,value in smoothed_state(curve,'time',.2).items():setattr(curve,key,value)
        canonical=curve.working.copy();window.curves[1].sample_size_mm=2.5
        window.redraw();window.classic_actions['Units1'].trigger();dialog=window.dialogs['units']
        dialog.general['time'].setCurrentIndex(dialog.general['time'].findData('sec'))
        dialog.general['temperature'].setCurrentIndex(dialog.general['temperature'].findData('°F'))
        app.processEvents();assert dialog.grab().save(str(out/'native-general-units-form.png'));dialog.accept()
        assert dialog.result()==QDialog.DialogCode.Accepted,dialog.error.text()
        assert window.active_document() is doc and window.selected().uid==uid and len(window._plot_artists)==3
        np.testing.assert_array_equal(curve.working,canonical);assert np.isclose(curve.smooth_width,12)
        # Independent physical0.2min window regression over actual acquired rows.
        raw=curve.dataset.values;rows=curve.active_rows;center=100
        t=raw[rows,curve.dataset.time_index].astype(float);y=raw[rows,curve.y_index].astype(float)
        near=np.flatnonzero(np.abs(t-t[center])<=.1)
        assert len(near)>=5
        design=np.column_stack((t[near]-t[center],np.ones(len(near))))
        expected=float(np.linalg.lstsq(design,y[near]-y[center],rcond=None)[0][0])/60
        assert np.isclose(curve.xy()[1][center],expected,rtol=1e-8,atol=1e-8)
        np.testing.assert_allclose(window.curves[2].xy()[0],window.curves[2].dataset.values[:,1]*1.8+32)
        app.processEvents();window.canvas.draw();assert window.grab().save(str(out/'fahrenheit-and-seconds-derivative.png'))
        # Enter displayed seconds, store source-minute bounds and reset origin.
        window.files.setCurrentItem(window.files.topLevelItem(1));curve=window.selected()
        limits=LimitBoundsDialog(window,curve,'time');limits.fields['start'].setText('180');limits.fields['stop'].setText('750');limits.reset.setChecked(True)
        limits.grab().save(str(out/'seconds-time-limits.png'));limits.accept();assert limits.result()==QDialog.DialogCode.Accepted,limits.error.text()
        curve=window.selected();assert curve.data_limit_spec['start']==3 and curve.data_limit_spec['stop']==12.5
        reference=curve.dataset.values[curve.active_rows,curve.dataset.time_index].astype(float)
        np.testing.assert_allclose(curve.x_values('time'),(reference-reference[0])*60)
        # Alpha stays per Celsius, independently of Fahrenheit cursor positions.
        alpha=window.start_alpha('alpha_fit');assert alpha is not None
        menu=window.create_plot_context_menu();assert any('编辑' in a.text() for a in menu.actions())
        next(a for a in menu.actions() if '确定' in a.text()).trigger();assert window._pending_measurement is None
        positions=alpha['interactive'].get('positions',alpha['interactive']['indices']);first,last=sorted(map(int,positions))
        px=curve.dataset.values[curve.active_rows[first:last+1],curve.dataset.temperature_index].astype(float)
        py=curve.dataset.values[curve.active_rows[first:last+1],curve.y_index].astype(float)
        independent_slope=float(np.linalg.lstsq(np.column_stack((px-px[0],np.ones(len(px)))),py,rcond=None)[0][0])
        independent_alpha=independent_slope*1000/2.5
        assert np.isclose(alpha['values']['alpha'],independent_alpha,rtol=1e-8,atol=1e-8)
        assert window.active_document() is doc and window.selected().uid==curve.uid
        window.canvas.draw();assert window.grab().save(str(out/'fahrenheit-alpha-and-context-confirm.png'))
        # Kelvin conversion clears the now-old Fahrenheit analyses, then marks afresh.
        units=window.show_units();units.general['temperature'].setCurrentIndex(units.general['temperature'].findData('K'));units.accept()
        assert units.result()==QDialog.DialogCode.Accepted and not window.results
        alpha=window.start_alpha('alpha_fit');window.confirm_measurement()
        assert np.isclose(alpha['values']['alpha'],independent_alpha,rtol=1e-8,atol=1e-8)
        window.files.setCurrentItem(window.files.topLevelItem(2));point=window.start_point_measurement('curve_value_y');window.confirm_measurement()
        label=window.dialogs['label_point'];label.boxes['time'].setChecked(True);label.accept()
        assert point['values']['temperature_unit']=='K' and point['values']['time_unit']=='sec'
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/'kelvin-point-and-two-axis-view.png'))
        selected=window.selected();export=out/(selected.dataset.path.stem+'.png');window.write_plot(export)
        with Image.open(export) as image:assert image.info['Author']==image.info['Software']=='Power By ZzzHe'
        csv_path=out/'display.csv';window.write_data(csv_path,selected)
        with csv_path.open(encoding='utf-8-sig',newline='') as f:records=list(csv.reader(f))
        np.testing.assert_allclose(np.asarray(records[1:],dtype=float)[:,-2],selected.xy()[0])
        meta=json.loads(Path(str(csv_path)+'.meta.json').read_text(encoding='utf-8'))
        assert meta['transform']['units']['time']=='sec' and meta['transform']['units']['temperature']=='K'
        session=out/'verified.tmas';save_session(session,window.curves,window.domain,window.results,window.plot_options)
        current=[(c.uid,c.xy()[0].copy(),c.xy()[1].copy()) for c in window.curves];results=deepcopy(window.results)
        window.close_all_documents();window.restore_session(session);window._show_document(doc.key)
        assert window.results==results and len(window._plot_artists)==3
        for restored,(uid,x,y) in zip(window.curves,current):
            assert restored.uid==uid;np.testing.assert_allclose(restored.xy()[0],x);np.testing.assert_allclose(restored.xy()[1],y)
        assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        summary=dict(status='passed',version=__version__,source_sha256=hashes,source_files_unchanged=True,physical_files=3,
            independent_derivative_um_per_sec=expected,independent_alpha_um_per_m_per_c=independent_alpha,
            reference_size_mm=2.5,reference_size_evidence='synthetic QA input, not a measured specimen dimension',
            canonical_buffers_unchanged=True,physical_smoothing_window_preserved=True,seconds_bounds_stored_as_source_minutes=True,
            reset_time_before_conversion=True,fahrenheit_and_kelvin_alpha_agree=True,right_click_confirmation=True,
            file_selection_preserved=True,point_label_units_checked=True,csv_and_session_readback=True,user_preferences_untouched=True,
            export_credit='Power By ZzzHe',session=str(session),native_runtime_equivalence='unverified',full_reconstruction_complete=False)
        (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in summary.items() if k!='source_sha256'},ensure_ascii=True,indent=2))
        window.dirty=False;window.close()


if __name__=='__main__':main()
