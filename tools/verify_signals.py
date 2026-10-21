"""Real-file native signal window, two X axes and custom-X analysis QA."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import hashlib
import tempfile
from copy import deepcopy
import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication
from tma_app import preferences,__version__
from tma_app.classic import ClassicMainWindow,CLASSIC_STYLE
from tma_app.workspace import save_session


def set_combo(box,value):
    index=box.findData(value);assert index>=0;box.setCurrentIndex(index)


def domain(dialog,value):next(b for b in dialog.x_modes.buttons() if b.property("mode")==value).click()


def main():
    root=Path(__file__).resolve().parents[1];out=root/"artifacts/signals-verification";out.mkdir(parents=True,exist_ok=True)
    paths=sorted((root/"测试文件").glob("*.001"));hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    app=QApplication([]);app.setStyle("Fusion");app.setStyleSheet(CLASSIC_STYLE)
    with tempfile.TemporaryDirectory(prefix="tma-signals-qa-") as private:
        preferences.preferences_path=lambda:Path(private)/"preferences.json"
        window=ClassicMainWindow();window.resize(1920,1017);window.show()
        window.warn=lambda message:(_ for _ in ()).throw(AssertionError(message))
        window.import_files(paths[:3],synchronous=True)
        target=window.selected().dataset;uid=window.selected().uid
        dialog=window.show_native_signals()
        set_combo(dialog.signals[1],target.signals[2].label);set_combo(dialog.types[1],"d_time")
        domain(dialog,"time");dialog.show_temperature.setChecked(True)
        app.processEvents();assert dialog.grab().save(str(out/"signals-dialog.png"))
        dialog.accept();assert not dialog.error.text(),dialog.error.text()
        assert window.selected().uid==uid and len(window.visible_curves())==2
        derived=next(c for c in window.visible_curves() if c.y_type=="d_time")
        i=len(target.values)//2;x=target.values[i-2:i+3,target.time_index].astype(float);y=target.values[i-2:i+3,2].astype(float)
        slope=np.linalg.lstsq(np.column_stack((np.ones(5),x-x[2])),y-y[2],rcond=None)[0][1]
        assert np.isclose(derived.working[i],slope,rtol=1e-10,atol=1e-10)
        assert any(axis.get_gid()=="tma-secondary-x" for axis in window.figure.axes)
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/"two-x-axes.png"))
        window.write_plot(out/"time-with-temperature.png")
        dialog=window.show_native_signals();set_combo(dialog.signals[1],None)
        domain(dialog,"signal");set_combo(dialog.x_signal,target.signals[target.time_index].label)
        app.processEvents();assert dialog.grab().save(str(out/"custom-x-dialog.png"))
        dialog.accept();assert not dialog.error.text() and window.domain=="signal"
        assert window.selected().uid==uid
        entry=window.start_point_measurement("dimension_change")
        assert entry["transform"]["x_signal"]["index"]==target.time_index
        window.create_measurement_menu().actions()[0].trigger()
        assert entry in window.results and window.mdi.activeSubWindow().key==str(target.path)
        result=deepcopy(entry);window.canvas.draw();app.processEvents()
        assert window.grab().save(str(out/"custom-x-analysis.png"))
        export=out/(target.path.stem+".png");window.write_plot(export)
        with Image.open(export) as image:assert image.info["Author"]==image.info["Software"]=="Power By ZzzHe"
        window.write_data(out/"signal-data.csv",window.selected())
        session=out/"verified.tmas";save_session(session,window.curves,window.domain,window.results,window.plot_options)
        window.close_all_documents();window.restore_session(session)
        document=window.documents[str(target.path)];window.mdi.setActiveSubWindow(document);window.document_activated(document)
        assert window.domain=="signal" and window.results==[result] and len(window._measurement_artists)==1
        assert all("X" in text.get_text() for text in window._measurement_artists[0].temps)
        assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        summary={"status":"passed","version":__version__,"physical_files":3,"workspace_curves":len(window.curves),
                 "real_sources_hashed":len(hashes),"source_sha256":hashes,"source_files_unchanged":True,
                 "native_signals_dialog":True,"derivative_checked_against_independent_window_ols":True,
                 "derivative_check_index":i,"derivative_value":float(derived.working[i]),"two_x_axes":True,
                 "custom_x_analysis":True,"selected_file_preserved":True,"right_click_confirm":True,
                 "session_roundtrip":True,"user_preferences_untouched":True,"export_credit":"Power By ZzzHe",
                 "export":str(export),"session":str(session),"vendor_numerical_equivalence":"unverified",
                 "remaining_types_disabled":["Log","Inverse","Inverse x 1000","Derivative log"],"full_reconstruction_complete":False}
        (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({k:v for k,v in summary.items() if k!="source_sha256"},ensure_ascii=True,indent=2))
        window.dirty=False;window.close()


if __name__=="__main__":main()
