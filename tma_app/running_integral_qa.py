"""Real-dataset native-window gates, also exercised inside the frozen program."""
from pathlib import Path
import json
import tempfile
from copy import deepcopy
import numpy as np
from PySide6.QtWidgets import QDialog
from matplotlib.font_manager import findfont
from matplotlib.backend_bases import MouseEvent
from matplotlib.text import Text
from .workspace import save_session,load_session


def verify_routes(datasets,application,output):
    from . import preferences,__version__
    from .classic import ClassicMainWindow
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    original_preferences=preferences.preferences_path;w=None
    with tempfile.TemporaryDirectory(prefix='tma-running-native-qa-') as private:
        preferences.preferences_path=lambda:Path(private)/'preferences.json'
        try:
            w=ClassicMainWindow();w.resize(1500,900);w.show()
            w.warn=lambda message:(_ for _ in ()).throw(ValueError(message))
            datasets=list(datasets)[:3]
            w.finish_import(datasets,[]);source=w.curves[min(1,len(w.curves)-1)]
            raw={c.uid:c.dataset.values.copy() for c in w.curves}
            document=w._show_document(source.dataset.document_key);w.refresh_curve(source.uid)
            peak=w.start_peak_integration('peak_linear');w.confirm_measurement()
            if peak not in w.results:raise ValueError('Real running-integral parent was not confirmed')
            e=w.start_running_integral();menu=w.create_measurement_menu()
            if [a.text() for a in menu.actions()][:4]!=['确定','编辑…','自动界限','取消']:raise ValueError('Dedicated running-integral cursor menu is missing')
            menu.actions()[0].trigger();menu.deleteLater();dialog=w.dialogs['running_integral']
            if dialog.size().width()!=282 or dialog.size().height()!=217 or dialog.normalized.isEnabled():raise ValueError('Native integral type form geometry or TMA choices differ')
            application.processEvents()
            if not dialog.grab().save(str(output.with_suffix('.integral_type.png'))):raise ValueError('Integral type screenshot failed')
            dialog.percent.setChecked(True);dialog.inverted.setChecked(True);dialog.accept()
            if dialog.result()!=QDialog.Accepted:raise ValueError(dialog.error.text())
            computed=w.curves[-1];p=computed.derived['profile']
            time,signal,baseline=(np.asarray(p[k]) for k in ('time','signal','baseline'))
            response=signal-baseline;running=np.r_[0.,np.cumsum((response[:-1]+response[1:])*.5*np.diff(time))]
            expected=100-100*running/running[-1]
            np.testing.assert_allclose(computed.xy()[1],expected,rtol=1e-12,atol=1e-10)
            if computed.axis!=3 or computed.result_unit!='%' or w.selected().uid!=source.uid or w.active_document() is not document or len(w.results)!=1:raise ValueError('Computed Y4 or second-file identity changed')
            w.canvas.draw();application.processEvents()
            if not w.grab().save(str(output.with_suffix('.running_y4.png'))):raise ValueError('Y4 screenshot failed')
            session=output.with_suffix('.running.tmas');save_session(session,w.curves,w.domain,w.results,w.plot_options)
            restored,domain,results,plots=load_session(session,include_plot_options=True)
            np.testing.assert_allclose(restored[-1].xy()[1],expected,rtol=1e-12,atol=1e-10)
            if restored[-1].derived!=computed.derived or results!=w.results:raise ValueError('Derived running-integral session changed')
            w.write_data(output.with_suffix('.running.csv'),computed);w.write_report(output.with_suffix('.running.html'))
            for stage in (1,2):
                w.start_running_integral()
                if stage==1:w.cancel_measurement()
                else:w.confirm_measurement().reject()
                if len(w.curves)!=len(datasets)+1 or len(w.results)!=1 or w.selected().uid!=source.uid:raise ValueError('Cancel changed running-integral state')
            w.start_running_integral();dialog=w.confirm_measurement();dialog.percent.setChecked(True);dialog.zero_baseline.setChecked(True);dialog.accept()
            if dialog.result()!=QDialog.Accepted:raise ValueError(dialog.error.text())
            absolute=w.curves[-1];ids={computed.uid,absolute.uid}
            configure=w.auto_configure_overlay();configure.accept()
            if configure.result()!=QDialog.Accepted or not ids<=set(c.uid for c in w.visible_curves()):raise ValueError('Auto Configure dropped a distinct same-unit derived curve')
            w.canvas.draw();font_files={}
            for index,axis in w.axes.items():
                font_files[str(index)]=[findfont(label.get_fontproperties()) for label in axis.get_xticklabels()+axis.get_yticklabels() if label.get_visible()]
                if not all(Path(font).name.casefold()=='times.ttf' for font in font_files[str(index)]):raise ValueError('A classic axis reverted to the system tick font')
            if not w.grab().save(str(output.with_suffix('.distinct_quantities.png'))):raise ValueError('Distinct quantities screenshot failed')
            multi_session=output.with_suffix('.multi-running.tmas');save_session(multi_session,w.curves,w.domain,w.results,w.plot_options)
            multi,_,_,multi_plots=load_session(multi_session,include_plot_options=True)
            if not ids<=set(multi_plots[w.active_document().key]['overlay_members']):raise ValueError('Distinct derived quantities were lost in the overlay session')
            # Native Slope uses two graph handles and the exact manual editor.
            w._show_document(source.dataset.document_key);w.refresh_curve(source.uid)
            current=next(c for c in w.curves if c.uid==source.uid)
            w.classic_actions['Slope1'].trigger();slope=w._pending_measurement
            if slope is None or slope['kind']!='slope' or len(slope['interactive']['indices'])!=2:raise ValueError('Slope did not start two graph markers')
            manual=w.edit_measurement_limits();xx,yy=current.xy(w.domain);n=len(xx)
            desired=[.25*(n-1)+.25,.8*(n-1)+.25]
            for field,p in zip(manual.fields,desired):field.setText(format(float(np.interp(p,np.arange(n),xx)),'.17g'))
            if not all(f.isReadOnly() for f in manual.y_fields):raise ValueError('Slope Y coordinates must be curve-derived')
            manual.accept()
            if manual.result()!=QDialog.Accepted:raise ValueError(manual.error.text())
            selected=slope['interactive']['positions'];lo,hi=sorted(selected)
            points=np.r_[lo,np.arange(np.floor(lo)+1,np.ceil(hi)),hi]
            fx=np.interp(points,np.arange(n),xx);fy=np.interp(points,np.arange(n),yy)
            m,b=np.polyfit(fx,fy,1)
            w.create_measurement_menu().actions()[0].trigger()
            if w._pending_measurement is not None or not any(r is slope for r in w.results) or w.selected().uid!=source.uid:raise ValueError('Native slope confirmation changed its source or did not commit')
            if not np.isclose(slope['values']['slope'],m,rtol=1e-11,atol=1e-12) or not np.isclose(slope['values']['intercept'],b,rtol=1e-11,atol=1e-10):raise ValueError('Slope differs from independent OLS')
            frozen=deepcopy(slope['values']);w.canvas.draw()
            artist=next(a for a in w._measurement_artists if a.entry is slope)
            for text in (artist.temps[0],artist.annotation):
                bounds=Text.get_window_extent(text,w.canvas.get_renderer());px,py=(bounds.x0+bounds.x1)/2,(bounds.y0+bounds.y1)/2
                for event,x,y in (('button_press_event',px,py),('motion_notify_event',px+24,py+18),('button_release_event',px+24,py+18)):
                    w.canvas.callbacks.process(event,MouseEvent(event,w.canvas,x,y,button=1))
            if slope['values']!=frozen or 't1' not in slope['annotation'].get('label_offsets',{}) or 'offset' not in slope['annotation']:raise ValueError('Slope labels were not independently draggable')
            w.canvas.draw();w.grab().save(str(output.with_suffix('.native_slope.png')))
            slope_session=output.with_suffix('.slope.tmas');save_session(slope_session,w.curves,w.domain,w.results,w.plot_options)
            restored_slope=load_session(slope_session)[2]
            if next(r for r in restored_slope if r['kind']=='slope')['values']!=frozen:raise ValueError('Slope session changed the confirmed fit')
            w.write_results(output.with_suffix('.analysis.csv'));w.write_report(output.with_suffix('.analysis.html'))
            w.classic_actions['DeletePeak1'].trigger();delete=w._pending_measurement
            if delete is None or delete.get('purpose')!='delete_peak' or len(delete['interactive']['indices'])!=1:raise ValueError('Delete Peak did not start its native single marker')
            if len(datasets)>1:
                other=next(c for c in w.curves if c.derived is None and c.dataset.document_key!=source.dataset.document_key)
                w._show_document(other.dataset.document_key);w.confirm_measurement()
                if w._pending_measurement is not delete or not any(r is peak for r in w.results):raise ValueError('Another document deleted the selected peak')
                w._show_document(source.dataset.document_key);w.refresh_curve(source.uid)
            w.cancel_measurement()
            if not ids<=set(c.uid for c in w.curves) or not any(r is peak for r in w.results):raise ValueError('Cancel deleted a peak or derived quantity')
            w.start_delete_peak();w.canvas.draw();w.grab().save(str(output.with_suffix('.delete_peak_marker.png')))
            w.create_measurement_menu().actions()[0].trigger()
            if w._pending_measurement is not None or any(r is peak for r in w.results) or ids&set(c.uid for c in w.curves) or not any(r is slope for r in w.results) or w.selected().uid!=source.uid:raise ValueError('Delete Peak did not preserve unrelated results and source identity')
            deleted_session=output.with_suffix('.deleted.tmas');save_session(deleted_session,w.curves,w.domain,w.results,w.plot_options)
            if len(load_session(deleted_session)[0])!=len(datasets):raise ValueError('Deleted peak left orphan derived curves')
            for c in w.curves:
                if c.uid in raw:np.testing.assert_array_equal(c.dataset.values,raw[c.uid])
            summary=dict(status='passed',version=__version__,files=[ds.path.name for ds in datasets],
                independent_cumulative_percent=True,second_file_stays_selected=True,native_type_geometry=[282,217],
                two_stage_cancel_atomic=True,derived_y4=True,source_arrays_unchanged=True,session=str(session),
                derived_session_roundtrip=True,source_curve_id=source.uid,parent_id=peak['analysis_id'],derived_id=computed.uid,
                distinct_quantities_preserved=True,distinct_derived_ids=sorted(ids),multiple_quantity_session=str(multi_session),classic_tick_fonts=font_files,
                native_two_marker_slope=True,independent_slope=float(m),slope_unit=slope['values']['slope_unit'],fixed_slope_labels_draggable=True,
                slope_session=str(slope_session),native_single_marker_delete_peak=True,delete_cancel_and_other_document_safe=True,
                dependent_quantities_deleted=True,unrelated_slope_preserved=True,deleted_session=str(deleted_session),
                total_signed_area=float(running[-1]),original_numeric_equivalence='unverified')
            output.with_suffix('.running.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
            return ['native_running_integral_type','native_running_percent_y4','native_running_session_roundtrip','native_running_distinct_quantities_overlay','native_two_marker_slope','native_delete_selected_peak']
        finally:
            if w is not None:
                for dialog in w.findChildren(QDialog):dialog.hide()
                w.cancel_measurement(redraw=False);w.dirty=False;w.close()
            preferences.preferences_path=original_preferences
