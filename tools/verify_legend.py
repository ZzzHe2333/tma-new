"""Real-data legend UI, mouse events, source identity, metadata and session QA."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copy import deepcopy
import hashlib
import json
import tempfile
from PySide6.QtWidgets import QApplication, QLineEdit, QCheckBox
from matplotlib.backend_bases import MouseEvent
from PIL import Image
from tma_app import preferences, __version__
from tma_app.classic import ClassicMainWindow, CLASSIC_STYLE
from tma_app.classic_dialogs import OverlayOptionsDialog
from tma_app.workspace import save_session


def main():
    root=Path(__file__).resolve().parents[1]
    out=root/"artifacts/legend-verification";out.mkdir(parents=True,exist_ok=True)
    paths=sorted((root/"测试文件").glob("*.001"))
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    app=QApplication([]);app.setStyle("Fusion");app.setStyleSheet(CLASSIC_STYLE)
    with tempfile.TemporaryDirectory(prefix="tma-legend-qa-") as private:
        preferences.preferences_path=lambda:Path(private)/"preferences.json"
        window=ClassicMainWindow();window.resize(1920,1017);window.show()
        window.warn=lambda message:(_ for _ in ()).throw(AssertionError(message))
        window.import_files(paths[:3],synchronous=True)
        auto=window.auto_configure_overlay();auto.accept();assert not auto.error.text()
        selected=window.selected().uid
        dialog=OverlayOptionsDialog(window)
        dialog.table.cellWidget(0,5).setText("比较样品 A")
        dialog.table.cellWidget(0,6).findChild(QLineEdit).setText("第一份样品")
        dialog.table.cellWidget(1,6).findChild(QCheckBox).setChecked(False)
        dialog.show();app.processEvents();assert dialog.grab().save(str(out/"curve-aliases.png"))
        dialog.tabs.setCurrentIndex(3)
        dialog.legend_boxes["legend_file"].setChecked(True);dialog.legend_boxes["legend_text"].setChecked(True)
        dialog.legend_boxes["legend_border"].setChecked(True)
        dialog.legend_coordinates[0].setValue(.73);dialog.legend_coordinates[1].setValue(.80)
        for group in dialog.legend_handles.values():
            next(b for b in group.buttons() if b.property("handle")=="center").click()
        dialog.save()
        app.processEvents();assert dialog.grab().save(str(out/"legend-options.png"))
        dialog.accept();assert not dialog.error.text()
        assert window.selected().uid==selected
        window.start_point_measurement("signal_max");window.confirm_measurement()
        results=deepcopy(window.results)
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/"before-drag.png"))
        legend=window.axes[0].get_legend()
        labels=[t.get_text() for t in legend.get_texts()]
        assert len(labels)==3 and labels[0]=="比较样品 A\n第一份样品"
        assert labels[1]==paths[1].name
        original_anchor=deepcopy(window.plot_options["__overlay__"]["legend_anchor"])
        bounds=legend.get_window_extent(window.canvas.get_renderer())
        x,y=(bounds.x0+bounds.x1)/2,(bounds.y0+bounds.y1)/2
        for kind,px,py in (("button_press_event",x,y),("motion_notify_event",x-120,y-60),("button_release_event",x-120,y-60)):
            window.canvas.callbacks.process(kind,MouseEvent(kind,window.canvas,px,py,button=1))
        anchor=deepcopy(window.plot_options["__overlay__"]["legend_anchor"])
        assert anchor!=original_anchor and window.results==results
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/"after-drag.png"))
        export=out/(window.selected().dataset.path.stem+".png")
        window.write_plot(export)
        with Image.open(export) as image:
            assert image.info["Author"]==image.info["Software"]=="Power By ZzzHe"
        session=out/"verified.tmas"
        save_session(session,window.curves,window.domain,window.results,window.plot_options)
        window.close_all_documents();window.restore_session(session)
        assert window.plot_options["__overlay__"]["legend_anchor"]==anchor
        assert window.results==results and window.curves[0].dataset.path==paths[0]
        assert window.curves[0].display_filename=="比较样品 A"
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/"restored.png"))
        assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        summary={"status":"passed","version":__version__,"real_sources_hashed":len(hashes),"source_sha256":hashes,
                 "source_files_unchanged":True,"physical_paths_unchanged":True,"text_toggle_keeps_row":True,
                 "selected_uid_preserved":True,"legend_drag_preserves_measurement":True,"session_roundtrip":True,
                 "user_preferences_untouched":True,"export_credit":"Power By ZzzHe","export":str(export),
                 "session":str(session),"legend_anchor":anchor,"normalized_origin":"inner axes lower-left; vendor rectangle unverified",
                 "full_reconstruction_complete":False}
        (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({k:v for k,v in summary.items() if k!="source_sha256"},ensure_ascii=True,indent=2))
        window.dirty=False;window.close()


if __name__=="__main__":main()
