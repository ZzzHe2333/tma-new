"""Real-file independent overlay presentation, copy, export and session QA."""
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
from PySide6.QtCore import QPoint
from tma_app import preferences,__version__
from tma_app.classic import ClassicMainWindow,CLASSIC_STYLE
from tma_app.workspace import save_session
from tma_app.overlay_views import snapshot


def main():
    root=Path(__file__).resolve().parents[1];out=root/"artifacts/multiple-overlays-verification";out.mkdir(parents=True,exist_ok=True)
    paths=sorted((root/"测试文件").glob("*.001"));hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    app=QApplication([]);app.setStyle("Fusion");app.setStyleSheet(CLASSIC_STYLE)
    with tempfile.TemporaryDirectory(prefix="tma-overlays-qa-") as private:
        preferences.preferences_path=lambda:Path(private)/"preferences.json"
        window=ClassicMainWindow();window.resize(1920,1017);window.show()
        window.warn=lambda message:(_ for _ in ()).throw(AssertionError(message))
        window.import_files(paths[:3],synchronous=True);uid=window.selected().uid
        raw={c.uid:c.dataset.values.copy() for c in window.curves}
        window.start_point_measurement("signal_max");window.confirm_measurement();analyses=deepcopy(window.results)
        window.show_overlay();source=window.active_document();source_order=list(source.curve_uids)
        window.plot_options[source.key].update(window_name="原始叠图",export_title="原始比较",legend=True)
        window.redraw();app.processEvents();window.grab().save(str(out/"source-before-copy.png"))
        baseline={c.uid:snapshot(c) for c in window.curves}
        window.update_overlay_copy_menu();menu=window.classic_actions["Copy4"].menu()
        next(action for action in menu.actions() if action.isVisible() and action.data()==source.key).trigger()
        copy=window.active_document();assert copy.key!=source.key and copy.curve_uids==source_order
        window.update_overlay_copy_menu();menu.popup(window.mapToGlobal(QPoint(380,110)))
        app.processEvents();assert menu.grab().save(str(out/"copy-menu.png"));menu.close()
        dialog=window.show_overlay_options();draft=next(c for c in dialog.draft if c.uid==uid)
        draft.axis=1;draft.color="#0000ff";draft.style="--";draft.overlay_offset=200;draft.legend_text="第三文件 / 对比";draft.display_filename="独立叠图别名"
        dialog.draft[0].overlay_enabled=False;dialog.populate();dialog.title.setText("独立对比叠图");dialog.export_heading.setPlainText("独立对比标题")
        dialog.accept();assert dialog.result()==QDialog.DialogCode.Accepted,dialog.error.text()
        assert window.selected().uid==uid and len(window.visible_curves())==2
        copy_state={c.uid:snapshot(c) for c in window.curves};copy_order=list(copy.curve_uids)
        window.canvas.draw();app.processEvents();assert window.grab().save(str(out/"independent-copy.png"))
        for key,label,expected in ((source.key,"source",baseline),(copy.key,"copy",copy_state)):
            window._show_document(key);assert {c.uid:snapshot(c) for c in window.curves}==expected
            window.canvas.draw();app.processEvents();assert window.grab().save(str(out/(label+"-restored.png")))
            folder=out/label;folder.mkdir(exist_ok=True);export=folder/window.selected().dataset.path.with_suffix(".png").name
            window.write_plot(export)
            with Image.open(export) as image:assert image.info["Author"]==image.info["Software"]=="Power By ZzzHe"
        assert window.results==analyses
        session=out/"verified.tmas";save_session(session,window.curves,window.domain,window.results,window.plot_options)
        window.close_all_documents();window.restore_session(session)
        assert set(k for k in window.documents if window._is_overlay(k))=={source.key,copy.key}
        for key,expected,order in ((source.key,baseline,source_order),(copy.key,copy_state,copy_order)):
            window._show_document(key)
            assert {c.uid:snapshot(c) for c in window.curves}==expected
            assert window.active_document().curve_uids==order
            assert all(np.array_equal(raw[c.uid],c.dataset.values) for c in window.curves)
        assert window.results==analyses
        assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        report={"status":"passed","version":__version__,"source_sha256":hashes,"source_files_unchanged":True,
            "physical_files":3,"overlay_windows":2,"normal_windows":3,"source_member_order":source_order,"copy_member_order":copy_order,
            "selected_file_preserved":True,"independent_axes_styles_visibility_legend_aliases":True,
            "independent_plot_options_export_headings":True,"native_copy_submenu_checked":True,"source_unchanged_by_copy_edit":True,"existing_analysis_unchanged":True,
            "portable_window_membership_and_states":True,"session_roundtrip":True,"user_preferences_untouched":True,
            "export_credit":"Power By ZzzHe","session":str(session),"shared_data_processing":"Overlay references the source signal, data limits and analyses, consistent with installed manufacturer Auto Configure help",
            "manufacturer_sources":["Menu_graph_overlay_copy.htm","Menu_graph_overlay_auto_configure.htm"],"max_new_overlay_windows":20,"full_reconstruction_complete":False}
        (out/"summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({k:v for k,v in report.items() if k!="source_sha256"},ensure_ascii=True,indent=2))
        window.dirty=False;window.close()


if __name__=="__main__":main()
