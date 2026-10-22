"""Real-file plot spacing with physical cursor/analysis and display export QA."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from copy import deepcopy
import csv,hashlib,json,tempfile
import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication,QDialog,QPushButton
from matplotlib.backend_bases import MouseEvent
from matplotlib.text import Text
from tma_app import preferences,__version__
from tma_app.classic import ClassicMainWindow,CLASSIC_STYLE
from tma_app.workspace import save_session


def main():
    root=Path(__file__).resolve().parents[1];out=root/"artifacts/x-offset-verification";out.mkdir(parents=True,exist_ok=True)
    paths=sorted((root/"测试文件").glob("*.001"));hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    app=QApplication([]);app.setStyle("Fusion");app.setStyleSheet(CLASSIC_STYLE)
    with tempfile.TemporaryDirectory(prefix="tma-x-offset-qa-") as private:
        preferences.preferences_path=lambda:Path(private)/"preferences.json"
        window=ClassicMainWindow();window.resize(1920,1017);window.show()
        window.warn=lambda message:(_ for _ in ()).throw(AssertionError(message))
        window.import_files(paths[:3],synchronous=True);curve=window.selected();uid=curve.uid
        window.start_point_measurement("signal_max");window.confirm_measurement();maximum=deepcopy(window.results[0])
        window.show_overlay();source=window.active_document();dialog=window.show_overlay_options();dialog.tabs.setCurrentIndex(1)
        assert (dialog.width(),dialog.height())==(640,440)
        assert dialog.axis_x_offsets[0].geometry().getRect()==(456,38,49,21)
        assert dialog.findChild(QPushButton,"OK").geometry().getRect()==(188,410,81,25)
        dialog.axis_x_offsets[0].setText("8");app.processEvents();assert dialog.grab().save(str(out/"native-axes-page.png"))
        for page in range(6):
            dialog.tabs.setCurrentIndex(page);app.processEvents();assert dialog.grab().save(str(out/f"overlay-page-{page}.png"))
        dialog.accept();assert dialog.result()==QDialog.DialogCode.Accepted,dialog.error.text()
        curve=window.selected();assert curve.uid==uid and curve.x_shift==0
        assert [window.display_x_offset(c) for c in window._document_curves(source)]==[0,8,16]
        assert window.results[0]==maximum
        editor=next(e for e in window._measurement_artists if e.entry is window.results[0])
        assert editor.annotation.xy[0]==maximum["values"]["max_x"]+16
        pending=window.start_point_measurement("dimension_change");manual=window.edit_measurement_limits()
        manual.fields[0].setText("179.75");manual.fields[1].setText("187.85");manual.accept();assert manual.result()==QDialog.DialogCode.Accepted
        editor=next(e for e in window._measurement_artists if e.entry is pending);x,y=curve.xy(window.domain)
        assert pending["values"]["T1"]==179.75 and pending["values"]["T2"]==187.85
        window.canvas.draw();start=editor.axis.transData.transform(editor.display_coords[1])
        window.canvas.callbacks.process("button_press_event",MouseEvent("button_press_event",window.canvas,*start,button=1))
        assert window._drag_measurement is not None
        target=min(len(x)-1,900);pixel=editor.axis.transData.transform((x[target]+16,y[target]))
        motion=MouseEvent("motion_notify_event",window.canvas,*pixel,button=1)
        physical=editor.axis.transData.inverted().transform((motion.x,motion.y))[0]-16
        expected=int(np.argmin(np.abs(x-physical)))
        window.canvas.callbacks.process("motion_notify_event",motion)
        window.canvas.callbacks.process("button_release_event",MouseEvent("button_release_event",window.canvas,*pixel,button=1))
        assert editor.indices[1]==expected and pending["values"]["T2"]==x[expected]
        position=pending["interactive"]["positions"][0];left=int(position);fraction=position-left
        baseline=y[left]+fraction*(y[left+1]-y[left])
        expected_h=float(y[expected]-baseline);assert np.isclose(pending["values"]["H"],expected_h)
        window.create_measurement_menu().actions()[0].trigger();assert window.selected().uid==uid
        values=deepcopy(window.results[-1]["values"]);window.canvas.draw();editor=next(e for e in window._measurement_artists if e.entry is window.results[-1])
        box=Text.get_window_extent(editor.temps[0],window.canvas.get_renderer());px,py=(box.x0+box.x1)/2,(box.y0+box.y1)/2
        for kind,tx,ty in (("button_press_event",px,py),("motion_notify_event",px+30,py+15),("button_release_event",px+30,py+15)):
            window.canvas.callbacks.process(kind,MouseEvent(kind,window.canvas,tx,ty,button=1))
        assert "t1" in window.results[-1]["annotation"]["label_offsets"] and window.results[-1]["values"]==values
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/"spaced-analysis.png"))
        export=out/(curve.dataset.path.stem+".png");window.write_plot(export)
        with Image.open(export) as image:assert image.info["Author"]==image.info["Software"]=="Power By ZzzHe"
        csv_path=out/"spaced-data.csv";window.write_data(csv_path,curve)
        rows=list(csv.reader(csv_path.read_text(encoding="utf-8-sig").splitlines()))
        np.testing.assert_allclose([float(row[-2]) for row in rows[1:]],x+16)
        assert len(rows)==len(curve.active_rows)+1
        meta=json.loads((out/"spaced-data.csv.meta.json").read_text(encoding="utf-8"));assert meta["presentation"]["x_offset"]==16 and meta["transform"]["x_shift"]==0
        model=window.table.model();n=len(curve.dataset.signals);assert float(model.data(model.index(0,n)))==float(f"{x[0]+16:.8g}")
        copy=window.copy_overlay(source.key);dialog=window.show_overlay_options();dialog.axis_x_offsets[0].setText("-5");dialog.accept()
        assert window.display_x_offset(window.selected())==-10 and window.results[-1]["values"]==values
        session=out/"verified.tmas";save_session(session,window.curves,window.domain,window.results,window.plot_options)
        window.close_all_documents();window.restore_session(session)
        curve=next(c for c in window.curves if c.uid==uid)
        for key,expected_offset in ((source.key,16),(copy.key,-10)):
            window._show_document(key);assert window.display_x_offset(curve)==expected_offset
            assert window.results[-1]["values"]==values
        assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        report={"status":"passed","version":__version__,"source_sha256":hashes,"source_files_unchanged":True,
            "physical_files":3,"overlay_windows":2,"native_overlay_geometry_checked":True,"native_client_plus_feedback":[640,440],
            "axis_x_step":8,"display_x_offsets":[0,8,16],"copy_display_x_offset":-10,
            "selected_file_preserved":True,"raw_x_shift_unchanged":True,"maximum_physical_value_preserved":True,
            "shifted_actual_cursor_drag_checked":True,"manual_physical_T1":179.75,"dragged_physical_T2":float(x[expected]),
            "independent_height_difference":expected_h,"fixed_temperature_label_drag_checked":True,
            "csv_table_match_display_x":True,"csv_records_separate_presentation_offset":True,"session_roundtrip":True,
            "user_preferences_untouched":True,"export_credit":"Power By ZzzHe","session":str(session),"export":str(export),
            "physical_label_policy":"Display-only spacing does not alter physical cursor coordinates, fits or processing; raw CSV columns remain original",
            "native_analysis_label_and_hidden_slot_policy_equivalence":"unverified","full_reconstruction_complete":False}
        (out/"summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({k:v for k,v in report.items() if k!="source_sha256"},ensure_ascii=True,indent=2))
        window.dirty=False;window.close()


if __name__=="__main__":main()
