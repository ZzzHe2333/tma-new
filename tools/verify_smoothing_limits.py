"""Real-data physical smoothing, limits, reset time, CSV and archived-result QA."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from copy import deepcopy
import hashlib,json,tempfile,csv
import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication
from tma_app import preferences,__version__
from tma_app.classic import ClassicMainWindow,CLASSIC_STYLE
from tma_app.workspace import save_session


def main():
    root=Path(__file__).resolve().parents[1];out=root/"artifacts/smoothing-limits-verification";out.mkdir(parents=True,exist_ok=True)
    paths=sorted((root/"测试文件").glob("*.001"));hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    app=QApplication([]);app.setStyle("Fusion");app.setStyleSheet(CLASSIC_STYLE)
    with tempfile.TemporaryDirectory(prefix="tma-smooth-qa-") as private:
        preferences.preferences_path=lambda:Path(private)/"preferences.json"
        window=ClassicMainWindow();window.resize(1920,1017);window.show()
        window.warn=lambda message:(_ for _ in ()).throw(AssertionError(message))
        window.import_files(paths[:3],synchronous=True);window.domain_box.setCurrentIndex(1)
        curve=window.selected();uid=curve.uid;dataset=curve.dataset
        dialog=window.show_native_smooth();dialog.width_edit.setText("0.2");dialog.reuse.setChecked(True)
        app.processEvents();assert dialog.grab().save(str(out/"smooth.png"))
        dialog.accept();assert not dialog.error.text()
        i=len(dataset.values)//2;x=dataset.values[:,dataset.time_index].astype(float);y=dataset.values[:,curve.y_index].astype(float)
        mask=np.abs(x-x[i])<=.1
        expected=np.linalg.lstsq(np.column_stack((np.ones(mask.sum()),x[mask]-x[i])),y[mask]-y[i],rcond=None)[0][0]+y[i]
        assert np.isclose(curve.working[i],expected,rtol=1e-10,atol=1e-10)
        old=window.start_point_measurement("signal_max");window.confirm_measurement();old_values=deepcopy(old)
        chooser=window.show_data_limits();app.processEvents();assert chooser.grab().save(str(out/"data-limits.png"))
        next(b for b in chooser.choices.buttons() if b.property("kind")=="time").click();chooser.accept()
        bounds=chooser.child;bounds.fields["start"].setText("2");bounds.fields["stop"].setText("10");bounds.reset.setChecked(True)
        app.processEvents();assert bounds.grab().save(str(out/"time-limits.png"))
        bounds.accept();assert not bounds.error.text();curve=window.selected()
        assert curve.uid==uid and curve.data_indices is not None and curve.smooth_width==.2
        assert curve.xy("time")[0][0]==0 and not window._measurement_artists
        selected_rows=len(curve.active_rows);assert selected_rows==window.table.model().rowCount()
        entry=window.start_point_measurement("dimension_change");window.create_measurement_menu().actions()[0].trigger()
        assert window.mdi.activeSubWindow().key==str(dataset.path)
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/"limited-analysis.png"))
        export=out/(dataset.path.stem+".png");window.write_plot(export)
        with Image.open(export) as image:assert image.info["Author"]==image.info["Software"]=="Power By ZzzHe"
        data=out/"limited-data.csv";window.write_data(data,curve)
        assert len(list(csv.reader(data.read_text(encoding="utf-8-sig").splitlines())))==selected_rows+1
        session=out/"verified.tmas";save_session(session,window.curves,window.domain,window.results,window.plot_options)
        window.undo();assert window.selected().data_indices is None and old in window.results and old==old_values
        assert any(editor.entry is old for editor in window._measurement_artists)
        window.close_all_documents();window.restore_session(session)
        doc=window.documents[str(dataset.path)];window.mdi.setActiveSubWindow(doc);window.document_activated(doc)
        assert len(window.results)==2 and window.results[0]==old_values
        curve=next(c for c in window.curves if c.uid==uid)
        assert len(curve.active_rows)==selected_rows and curve.reset_time and curve.smooth_reuse
        assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        summary={"status":"passed","version":__version__,"source_sha256":hashes,"source_files_unchanged":True,
                 "physical_files":3,"smoothed_sample_index":i,"smoothed_sample_value":float(expected),"independent_window_ols_checked":True,
                 "physical_width":.2,"width_unit":"min","selected_rows":selected_rows,"time_zero_origin":curve.time_origin,
                 "selected_file_preserved":True,"table_csv_rows_agree":True,"old_analysis_preserved_and_hidden_for_other_limits":True,
                 "limits_undo_restores_old_analysis":True,"session_roundtrip":True,"user_preferences_untouched":True,
                 "export_credit":"Power By ZzzHe","export":str(export),"session":str(session),
                 "vendor_window_boundary_equivalence":"unverified","full_reconstruction_complete":False}
        (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({k:v for k,v in summary.items() if k!="source_sha256"},ensure_ascii=True,indent=2))
        window.dirty=False;window.close()


if __name__=="__main__":main()
