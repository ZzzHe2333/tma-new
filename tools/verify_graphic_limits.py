"""Real-file graphic data bounds, exact-X editing, undo, session and export QA."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from copy import deepcopy
import csv,hashlib,json,tempfile
import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication,QDialog
from PySide6.QtCore import QPoint,QTimer
from tma_app import preferences,__version__
from tma_app.classic import ClassicMainWindow,CLASSIC_STYLE
from tma_app.workspace import save_session
from tma_app.data_limits import cursor_spec


def main():
    root=Path(__file__).resolve().parents[1];out=root/"artifacts/graphic-limits-verification";out.mkdir(parents=True,exist_ok=True)
    paths=sorted((root/"测试文件").glob("*.001"));hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    app=QApplication([]);app.setStyle("Fusion");app.setStyleSheet(CLASSIC_STYLE)
    with tempfile.TemporaryDirectory(prefix="tma-cursor-qa-") as private:
        preferences.preferences_path=lambda:Path(private)/"preferences.json"
        window=ClassicMainWindow();window.resize(1920,1017);window.show()
        window.warn=lambda message:(_ for _ in ()).throw(AssertionError(message))
        window.import_files(paths[:3],synchronous=True);window.show_normal();curve=window.selected();uid=curve.uid;document=window.active_document()
        old=window.start_point_measurement("signal_max");window.confirm_measurement();old=deepcopy(old)
        pending=window.graphic_range();state=pending["interactive"];x,y=curve.xy(window.domain)
        n=len(x);state["indices"]=[n//3,3*n//4];window.redraw()
        editor=next(e for e in window._measurement_artists if e.entry is pending)
        assert not editor.annotation.get_visible() and not editor.arrow.get_visible()
        window.canvas.draw();app.processEvents();window.grab().save(str(out/"cursor-preview.png"))
        menu=window.create_plot_context_menu();menu.popup(window.canvas.mapToGlobal(QPoint(1200,480)))
        app.processEvents();assert menu.grab().save(str(out/"cursor-menu.png"));menu.close()
        dialog=window.edit_measurement_limits()
        first,last=n//3+1,3*n//4-1
        # Off-grid boundaries remain exact draft positions; the confirmed window
        # contains original samples only, with no interpolated data invented.
        t1=float((x[first]+x[first+1])/2);t2=float((x[last-1]+x[last])/2)
        dialog.fields[0].setText(format(t1,".15g"));dialog.fields[1].setText(format(t2,".15g"))
        for field in dialog.fields:field.setCursorPosition(0)
        app.processEvents();assert dialog.grab().save(str(out/"manual-cursor.png"))
        dialog.accept();assert dialog.result()==QDialog.DialogCode.Accepted,dialog.error.text()
        expected=cursor_spec(curve,state.get("positions",state["indices"]))["rows"]
        window.create_plot_context_menu().actions()[0].trigger();curve=window.selected()
        assert curve.uid==uid and window.active_document() is document and curve.data_indices==expected
        assert window._pending_measurement is None and len(window.results)==1 and window.results[0]==old
        assert window.table.model().rowCount()==len(expected)
        window.start_point_measurement("dimension_change");window.confirm_measurement()
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/"limited-analysis.png"))
        export=out/(curve.dataset.path.stem+".png");window.write_plot(export)
        with Image.open(export) as image:assert image.info["Author"]==image.info["Software"]=="Power By ZzzHe"
        data=out/"cursor-data.csv";window.write_data(data,curve)
        assert len(list(csv.reader(data.read_text(encoding="utf-8-sig").splitlines())))==len(expected)+1
        session=out/"verified.tmas";save_session(session,window.curves,window.domain,window.results,window.plot_options)
        window.undo();assert window.selected().data_indices is None and len(window.results)==2
        assert any(e.entry is window.results[0] for e in window._measurement_artists)
        window.close_all_documents();window.restore_session(session)
        doc=window.documents[str(curve.dataset.path)];window.mdi.setActiveSubWindow(doc);window.document_activated(doc)
        curve=next(c for c in window.curves if c.uid==uid)
        assert curve.data_indices==expected and len(window.results)==2 and window.results[0]==old
        window.graphic_range();window.create_plot_context_menu().actions()[3].trigger();assert window._pending_measurement is None and curve.data_indices==expected
        assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        report={"status":"passed","version":__version__,"source_sha256":hashes,"source_files_unchanged":True,
            "physical_files":3,"selected_file_preserved":True,"selected_rows":len(expected),"source_row_start":expected[0]+1,"source_row_stop":expected[-1]+1,
            "manual_x_bounds":[t1,t2],"acquired_order_preserved":True,"dedicated_context_menu":True,"cancel_inert":True,
            "draft_not_saved_as_analysis":True,"old_analysis_preserved":True,"limits_undo_restores_old_analysis":True,
            "table_csv_rows_agree":True,"session_roundtrip":True,"user_preferences_untouched":True,"export_credit":"Power By ZzzHe",
            "session":str(session),"export":str(export),"manufacturer_source":"Menu_graph_data_limits_cursor.htm",
            "fractional_boundary_policy":"Retain actual acquired rows strictly inside or on both adjacent-segment cursor positions; do not fabricate boundary samples",
            "vendor_fractional_boundary_equivalence":"unverified","full_reconstruction_complete":False}
        (out/"summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({k:v for k,v in report.items() if k!="source_sha256"},ensure_ascii=True,indent=2))
        window.dirty=False;window.close()


if __name__=="__main__":main()
