"""Exercise the classic Qt MDI shell using actual project data."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
from PySide6.QtWidgets import QApplication
from tma_app.classic import ClassicMainWindow, CLASSIC_STYLE


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(CLASSIC_STYLE)
    window = ClassicMainWindow()
    window.warn = lambda message: (_ for _ in ()).throw(AssertionError(message))
    window.show()
    root = Path(__file__).resolve().parents[1]
    out = root / "artifacts/classic-verification"
    out.mkdir(parents=True, exist_ok=True)
    assert len(window.menuBar().actions()) == 10
    assert not window.documents
    app.processEvents()
    window.grab().save(str(out / "empty.png"))
    paths = sorted((root / "测试文件").glob("*.001"))[:3]
    assert len(paths) == 3
    window.import_files(paths, synchronous=True)
    assert len(window.documents) == 3
    assert len(window.visible_curves()) == 1
    window.show_overlay()
    assert len(window.documents) == 4
    assert len(window.visible_curves()) == 3
    doc = window.mdi.activeSubWindow()
    doc.showMaximized()
    window.lo_box.setValue(130)
    window.hi_box.setValue(160)
    window.analysis_box.setCurrentIndex(window.analysis_box.findData("peak"))
    window.run_analysis()
    assert len(window.results) == 1
    window.show_curve_options()
    assert window.dialogs["overlay_options"].isVisible()
    window.dialogs["overlay_options"].reject()
    window.show_processing()
    window.dialogs["processing"].hide()
    window.show_file_list()
    window.dialogs["files"].hide()
    window.show_view("data")
    assert window.table.model().rowCount() >= 1000
    window.dialogs["data"].hide()
    window.show_overlay()
    app.processEvents()
    window.canvas.draw()
    window.grab().save(str(out / "overlay.png"))
    window.show_normal()
    assert len(window.visible_curves()) == 1
    window.show_curve_options()
    assert window.dialogs["graph_options"].isVisible()
    window.dialogs["graph_options"].reject()
    window.close_active_document()
    assert len(window.curves) == 2
    assert len(window.documents) == 3
    window.mdi.tileSubWindows()
    window.close_all_documents()
    assert not window.documents and not window.curves
    summary = {"status": "passed", "menus": 10, "independent_normal_plots": 3,
               "overlay": True, "analysis": True, "dialogs": True,
               "close_and_tile": True}
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))
    window.dirty = False
    window.close()


if __name__ == "__main__":
    main()
