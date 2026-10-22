"""Reviewable real-data checks for the native cursor popup and export workflow."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hashlib
import json
from copy import deepcopy
import numpy as np
from PIL import Image
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
from tma_app.classic import ClassicMainWindow, CLASSIC_STYLE
from tma_app.classic_dialogs import OverlayOptionsDialog
from tma_app.workspace import save_session


def main():
    root = Path(__file__).resolve().parents[1]
    out = root / "artifacts/native-interaction-verification"; out.mkdir(parents=True, exist_ok=True)
    sources = sorted((root / "测试文件").glob("*.001"))
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    chosen = sources[:2] + [next(p for p in sources if p.stem == "20261015-9#")]
    app = QApplication([]); app.setStyle("Fusion"); app.setStyleSheet(CLASSIC_STYLE)
    window = ClassicMainWindow(); window.resize(1920, 1017); window.show()
    window.warn = lambda message: (_ for _ in ()).throw(AssertionError(message))
    window.import_files(chosen, synchronous=True); app.processEvents()
    active_key = window.mdi.activeSubWindow().key; active_uid = window.selected().uid
    pending = window.start_point_measurement("dimension_change")
    app.processEvents(); window.canvas.draw()
    assert window.statusBar().height() == 19
    window.grab().save(str(out / "select-points.png"))
    menu = window.create_plot_context_menu()
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert labels == ["确定", "编辑…", "自动界限", "取消", "恢复初始界限", "点 1", "点 2"]
    menu.popup(window.canvas.mapToGlobal(QPoint(950, 470))); app.processEvents()
    menu.grab().save(str(out / "cursor-menu.png")); menu.hide()
    dialog = window.edit_measurement_limits(); app.processEvents()
    dialog.fields[0].setText("179.75"); dialog.fields[1].setText("187.85")
    app.processEvents(); dialog.grab().save(str(out / "manual-limits.png")); dialog.accept()
    assert np.allclose([pending["values"]["T1"], pending["values"]["T2"]], [179.75, 187.85])
    menu.actions()[0].trigger(); app.processEvents(); window.canvas.draw()
    assert window.mdi.activeSubWindow().key == active_key and window.selected().uid == active_uid
    assert pending["interactive"]["confirmed"]
    window.grab().save(str(out / "confirmed.png"))
    graph = window.show_curve_options(); app.processEvents()
    graph.grab().save(str(out / "graph-options.png")); graph.reject()
    editor = next(editor for editor in window._measurement_artists if editor.entry is pending)
    objects = window.create_result_context_menu(pending, editor.temps[0])
    objects.popup(window.canvas.mapToGlobal(QPoint(950, 470))); app.processEvents()
    objects.grab().save(str(out / "result-menu.png")); objects.hide()
    window.write_plot(out / (window.selected().dataset.path.stem + ".png"))
    with Image.open(out / (window.selected().dataset.path.stem + ".png")) as picture:
        assert picture.info["Author"] == picture.info["Software"] == "Power By ZzzHe"
    window.show_overlay()
    options = OverlayOptionsDialog(window)
    options.legend_boxes["legend_border"].setChecked(True)
    options.legend_boxes["legend_file"].setChecked(True)
    options.legend.setCurrentIndex(options.legend.findData(True))
    options.tabs.setCurrentIndex(3); options.show(); app.processEvents()
    options.grab().save(str(out / "legend-options.png")); options.accept(); app.processEvents()
    assert window.selected().uid == active_uid
    before = deepcopy(window.results)
    session = out / "verified.tmas"
    save_session(session, window.curves, window.domain, window.results, plot_options=window.plot_options)
    window.close_all_documents(); window.restore_session(session); app.processEvents()
    assert window.results == before and window.plot_options["__overlay__"]["legend_border"]
    window.canvas.draw(); window.grab().save(str(out / "overlay-restored.png"))
    assert hashes == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    summary = {"status": "passed", "files": len(chosen), "menu": labels, "active_file_preserved": True,
               "exact_temperatures": [179.75, 187.85], "values": pending["values"],
               "source_files_unchanged": True, "source_sha256": hashes,
               "export_author": "Power By ZzzHe", "session": str(session)}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in summary.items() if k != "source_sha256"}, ensure_ascii=False, indent=2))
    window.dirty = False; window.close()


if __name__ == "__main__": main()
