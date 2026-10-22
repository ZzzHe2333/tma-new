"""Real-file horizontal cursor, independently calculated crossing and native stages."""
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
from matplotlib.backend_bases import MouseEvent,KeyEvent
from matplotlib.text import Text
from tma_app import preferences,__version__
from tma_app.classic import ClassicMainWindow,CLASSIC_STYLE
from tma_app.workspace import save_session


def independent_crossing(y,level,rows):
    # Deliberately scan acquisition order, including exact samples and excluding gaps.
    for i,value in enumerate(y):
        if value==level:return float(i)
        if i+1<len(y) and rows[i+1]==rows[i]+1 and min(value,y[i+1])<level<max(value,y[i+1]):
            return i+(level-value)/(y[i+1]-value)
    raise AssertionError('No acquired intersection')


def main():
    root=Path(__file__).resolve().parents[1];out=root/'artifacts/curve-value-y-verification';out.mkdir(parents=True,exist_ok=True)
    paths=sorted((root/'测试文件').glob('*.001'));hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(CLASSIC_STYLE)
    with tempfile.TemporaryDirectory(prefix='tma-horizontal-qa-') as private:
        preferences.preferences_path=lambda:Path(private)/'preferences.json'
        window=ClassicMainWindow();window.resize(1920,1017);window.show()
        window.warn=lambda message:(_ for _ in ()).throw(AssertionError(message))
        window.import_files(paths[:3],synchronous=True);curve=window.selected();uid=curve.uid;curve.x_signal_index=3
        window.show_overlay();doc=window.active_document();window.plot_options[doc.key]['axis_x_offsets'][0]=7;window.redraw()
        window.classic_actions['CurveValueAtY1'].trigger();entry=window._pending_measurement
        manual=window.edit_measurement_limits();manual.y_fields[0].setText('500.123456789');manual.accept()
        assert manual.result()==QDialog.DialogCode.Accepted and manual.fields[0].isReadOnly() and not manual.y_fields[0].isReadOnly()
        x,y=curve.xy(window.domain);target=500.123456789
        position=independent_crossing(y,target,curve.active_rows);left=int(position);fraction=position-left
        expected_x=float(x[left]+fraction*(x[left+1]-x[left]))
        assert np.isclose(entry['values']['y'],target) and np.isclose(entry['values']['x'],expected_x)
        assert entry['interactive']['positions'][0]==position
        # Untouched compact fields retain the exact requested Y and acquired position.
        state=deepcopy(entry['interactive']);manual=window.edit_measurement_limits();manual.accept()
        assert entry['interactive']==state
        editor=next(e for e in window._measurement_artists if e.entry is entry)
        assert editor.hline.get_visible() and not editor.vline.get_visible() and not editor.annotation.get_visible()
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/'horizontal-cursor.png'))
        window.create_plot_context_menu().actions()[0].trigger();label=window.dialogs['label_point']
        assert not window.results and window._pending_measurement is entry
        for key in ('time','temperature','signal','y','arrow','cross','border'):label.boxes[key].setChecked(True)
        label.boxes['transparent'].setChecked(False);app.processEvents();assert label.grab().save(str(out/'label-point-form.png'))
        label.accept();assert window.results==[entry] and window.selected().uid==uid and window.active_document() is doc
        values=deepcopy(entry['values']);window.edit_measurement(entry)
        editor=next(e for e in window._measurement_artists if e.entry is window._pending_measurement)
        window.canvas.draw();px=editor.axis.bbox.x0+25;py=editor.axis.transData.transform(editor.display_coords[0])[1]
        window.canvas.callbacks.process('button_press_event',MouseEvent('button_press_event',window.canvas,px,py,button=1))
        assert window._drag_measurement is not None
        end=editor.axis.transData.transform((editor.display_coords[0][0],650.))
        motion=MouseEvent('motion_notify_event',window.canvas,px,end[1],button=1)
        expected_y=editor.axis.transData.inverted().transform((motion.x,motion.y))[1]
        window.canvas.callbacks.process('motion_notify_event',motion)
        window.canvas.callbacks.process('button_release_event',MouseEvent('button_release_event',window.canvas,px,end[1],button=1))
        assert np.isclose(editor.entry['values']['y'],expected_y)
        assert np.isclose(editor.entry['interactive']['positions'][0],independent_crossing(y,expected_y,curve.active_rows))
        before=editor.entry['values']['y'];window.canvas.callbacks.process('key_press_event',KeyEvent('key_press_event',window.canvas,key='ctrl+up'))
        assert editor.entry['values']['y']>before
        window.cancel_measurement();assert entry['values']==values
        editor=next(e for e in window._measurement_artists if e.entry is entry);window.canvas.draw()
        box=Text.get_window_extent(editor.annotation,window.canvas.get_renderer());px,py=(box.x0+box.x1)/2,(box.y0+box.y1)/2
        for kind,a,b in (('button_press_event',px,py),('motion_notify_event',px+25,py+18),('button_release_event',px+25,py+18)):
            window.canvas.callbacks.process(kind,MouseEvent(kind,window.canvas,a,b,button=1))
        assert 'offset' in entry['annotation'] and entry['values']==values
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/'labelled-curve.png'))
        export=out/(curve.dataset.path.stem+'.png');window.write_plot(export)
        with Image.open(export) as image:assert image.info['Author']==image.info['Software']=='Power By ZzzHe'
        session=out/'verified.tmas';save_session(session,window.curves,window.domain,window.results,window.plot_options)
        saved=deepcopy(entry);window.close_all_documents();window.restore_session(session);window._show_document(doc.key)
        assert window.results==[saved]
        assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        summary={'status':'passed','version':__version__,'source_sha256':hashes,'source_files_unchanged':True,'physical_files':3,
            'selected_file_preserved':True,'manual_y':target,'independent_acquisition_position':position,'independent_adjacent_x':expected_x,
            'two_stage_confirmation_checked':True,'horizontal_line_grab_away_from_curve_checked':True,'vertical_keyboard_checked':True,
            'untouched_compact_input_keeps_precision':True,'cancel_edit_preserves_record':True,'actual_label_drag_checked':True,
            'session_roundtrip':True,'user_preferences_untouched':True,'export_credit':'Power By ZzzHe','session':str(session),
            'native_first_acquisition_interpretation_and_interpolation_equivalence':'unverified','full_reconstruction_complete':False}
        (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in summary.items() if k!='source_sha256'},ensure_ascii=True,indent=2))
        window.dirty=False;window.close()


if __name__=='__main__':main()
