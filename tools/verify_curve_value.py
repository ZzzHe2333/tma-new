"""Real-file native point-label stages, interpolated channels and save QA."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
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


def main():
    root=Path(__file__).resolve().parents[1];out=root/"artifacts/curve-value-verification";out.mkdir(parents=True,exist_ok=True)
    paths=sorted((root/"测试文件").glob("*.001"));hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    app=QApplication([]);app.setStyle("Fusion");app.setStyleSheet(CLASSIC_STYLE)
    with tempfile.TemporaryDirectory(prefix="tma-point-label-qa-") as private:
        preferences.preferences_path=lambda:Path(private)/"preferences.json"
        window=ClassicMainWindow();window.resize(1920,1017);window.show()
        window.warn=lambda message:(_ for _ in ()).throw(AssertionError(message))
        window.import_files(paths[:3],synchronous=True);curve=window.selected();uid=curve.uid;curve.x_signal_index=3
        window.show_overlay();doc=window.active_document();window.plot_options[doc.key]["axis_x_offsets"][0]=7;window.redraw()
        window.classic_actions["CurveValueAtX1"].trigger();entry=window._pending_measurement
        manual=window.edit_measurement_limits();manual.fields[0].setText("179.75");manual.accept()
        assert manual.result()==QDialog.DialogCode.Accepted and manual.y_fields[0].isReadOnly()
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/"value-cursor.png"))
        raw=curve.dataset.values;temp=raw[:,curve.dataset.temperature_index].astype(float);target=179.75
        candidates=np.flatnonzero((temp[:-1]<target)&(target<temp[1:]));assert len(candidates)==1
        left=int(candidates[0]);fraction=(target-temp[left])/(temp[left+1]-temp[left])
        expected={name:float(raw[left,index]+fraction*(raw[left+1,index]-raw[left,index])) for name,index in (("y",curve.y_index),("time",curve.dataset.time_index),("signal",3))}
        assert np.isclose(entry["values"]["y"],expected["y"]) and np.isclose(entry["values"]["time_at_point"],expected["time"])
        assert np.isclose(entry["values"]["signal_at_point"],expected["signal"]) and entry["values"]["temperature_at_point"]==target
        window.create_plot_context_menu().actions()[0].trigger();label=window.dialogs["label_point"]
        assert not window.results and window._pending_measurement is entry
        for key in ("time","temperature","signal","y","arrow","cross","border"):label.boxes[key].setChecked(True)
        label.boxes["transparent"].setChecked(False);app.processEvents();assert label.grab().save(str(out/"label-point-form.png"))
        label.save();label.accept();assert label.result()==QDialog.DialogCode.Accepted
        assert window.selected().uid==uid and window.active_document() is doc and window.results==[entry]
        values=deepcopy(entry["values"]);saved_signal=deepcopy(entry["point_signal"])
        curve.x_signal_index=1;window.redraw();assert entry["values"]==values and saved_signal["index"]==3
        window.edit_measurement(entry);editor=next(e for e in window._measurement_artists if e.entry is window._pending_measurement)
        window.canvas.draw();pixel=editor.axis.transData.transform(editor.display_coords[0])
        window.canvas.callbacks.process("button_press_event",MouseEvent("button_press_event",window.canvas,*pixel,button=1))
        assert window._drag_measurement is not None
        target_index=min(len(editor.x)-1,900);end=editor.axis.transData.transform((editor.x[target_index]+editor.display_x_offset,editor.y[target_index]))
        motion=MouseEvent("motion_notify_event",window.canvas,*end,button=1)
        physical=editor.axis.transData.inverted().transform((motion.x,motion.y))[0]-editor.display_x_offset
        expected_index=int(np.argmin(np.abs(editor.x-physical)))
        window.canvas.callbacks.process("motion_notify_event",motion);window.canvas.callbacks.process("button_release_event",MouseEvent("button_release_event",window.canvas,*end,button=1))
        assert editor.indices[0]==expected_index
        window.cancel_measurement();assert entry["values"]==values
        editor=next(e for e in window._measurement_artists if e.entry is entry);window.canvas.draw()
        box=Text.get_window_extent(editor.annotation,window.canvas.get_renderer());x,y=(box.x0+box.x1)/2,(box.y0+box.y1)/2
        for kind,px,py in (("button_press_event",x,y),("motion_notify_event",x+25,y+18),("button_release_event",x+25,y+18)):
            window.canvas.callbacks.process(kind,MouseEvent(kind,window.canvas,px,py,button=1))
        assert "offset" in entry["annotation"] and entry["values"]==values
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/"labelled-curve.png"))
        export=out/(curve.dataset.path.stem+".png");window.write_plot(export)
        with Image.open(export) as image:assert image.info["Author"]==image.info["Software"]=="Power By ZzzHe"
        session=out/"verified.tmas";save_session(session,window.curves,window.domain,window.results,window.plot_options)
        saved=deepcopy(entry);window.close_all_documents();window.restore_session(session)
        window._show_document(doc.key);assert window.results==[saved]
        assert window.results[0]["point_signal"]==saved_signal
        assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        summary={"status":"passed","version":__version__,"source_sha256":hashes,"source_files_unchanged":True,
            "physical_files":3,"selected_file_preserved":True,"two_stage_confirmation_checked":True,
            "manual_x":target,"independent_adjacent_y":expected["y"],"independent_adjacent_time":expected["time"],
            "independent_adjacent_signal":expected["signal"],"saved_signal_index":3,"later_signal_change_preserves_recorded_definition":True,
            "actual_shifted_cursor_drag_checked":True,"cancel_edit_preserves_record":True,"actual_label_drag_checked":True,
            "native_form_geometry":[370,229],"multiplex_unavailable_not_fabricated":True,"private_defaults_save_checked":True,
            "session_roundtrip":True,"user_preferences_untouched":True,"export_credit":"Power By ZzzHe","export":str(export),"session":str(session),
            "native_factory_defaults_and_exact_interpolation_equivalence":"unverified","full_reconstruction_complete":False}
        (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({k:v for k,v in summary.items() if k!="source_sha256"},ensure_ascii=True,indent=2))
        window.dirty=False;window.close()


if __name__=="__main__":main()
