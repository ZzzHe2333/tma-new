"""Real-file overlay UI/output/state QA with private preference storage."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hashlib
import json
import tempfile
from copy import deepcopy
from PySide6.QtWidgets import QApplication
from tma_app import preferences, __version__
from tma_app.classic import ClassicMainWindow, CLASSIC_STYLE
from tma_app.classic_dialogs import OverlayOptionsDialog
from tma_app.workspace import save_session


def main():
    root = Path(__file__).resolve().parents[1]
    out = root / "artifacts/overlay-auto-verification"; out.mkdir(parents=True, exist_ok=True)
    sources = sorted((root / "测试文件").glob("*.001"))
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    app = QApplication([]); app.setStyle("Fusion"); app.setStyleSheet(CLASSIC_STYLE)
    with tempfile.TemporaryDirectory(prefix="tma-overlay-qa-") as private:
        preferences.preferences_path = lambda: Path(private) / "preferences.json"
        window = ClassicMainWindow(); window.resize(1920, 1017); window.show()
        window.warn = lambda message: (_ for _ in ()).throw(AssertionError(message))
        window.import_files(sources[:3], synchronous=True); window.show_normal()
        normal = [(c.style, c.color, c.marker, c.offset) for c in window.curves]
        selected = window.selected().uid
        auto = window.auto_configure_overlay(); auto.show(); app.processEvents()
        assert auto.grab().save(str(out / "auto-configure.png"))
        auto.auto_boxes["symbol"].setChecked(True)
        auto.heading.setPlainText("TMA overlay verification\nExport heading only")
        auto.accept(); assert not auto.error.text(), auto.error.text()
        assert window.selected().uid == selected
        dialog = OverlayOptionsDialog(window)
        dialog.tabs.setCurrentIndex(5); dialog.show(); app.processEvents()
        dialog.auto_page.offset_modes.button(3).setChecked(True); dialog.auto_page.percent.setValue(10)
        assert dialog.grab().save(str(out / "auto-tab.png"))
        dialog.auto_offsets(); offsets = [c.overlay_offset for c in dialog.draft]
        assert offsets[0] == 0 and offsets[1] > 0 and offsets[2] == 2*offsets[1]
        dialog.tabs.setCurrentIndex(1)
        for key in ("line", "color", "symbol"): dialog.axis_flag_boxes[0][key].setChecked(True)
        app.processEvents(); assert dialog.grab().save(str(out / "axis-tab.png"))
        dialog.tabs.setCurrentIndex(2); dialog.title.setText("Overlay QA")
        dialog.export_align.setCurrentIndex(dialog.export_align.findData("center"))
        app.processEvents(); assert dialog.grab().save(str(out / "heading-tab.png"))
        dialog.accept(); assert not dialog.error.text(), dialog.error.text()
        assert window.selected().uid == selected
        app.processEvents(); window.canvas.draw()
        assert window.grab().save(str(out / "overlay.png"))
        screen = [(t.get_text(), t.get_position(), t.get_visible()) for t in window.figure.texts]
        export = out / (window.selected().dataset.path.stem + ".svg")
        window.write_plot(export)
        assert "Export heading only" in export.read_text(encoding="utf-8")
        assert "Power By ZzzHe" in export.read_text(encoding="utf-8")
        assert screen == [(t.get_text(), t.get_position(), t.get_visible()) for t in window.figure.texts]
        overlay = [(c.style, c.color, c.marker, c.overlay_offset) for c in window.curves]
        window.show_normal(); assert normal == [(c.style, c.color, c.marker, c.offset) for c in window.curves]
        window.canvas.draw(); app.processEvents(); assert window.grab().save(str(out / "normal-restored.png"))
        window.show_overlay(); assert overlay == [(c.style, c.color, c.marker, c.overlay_offset) for c in window.curves]
        session = out / "verified.tmas"
        save_session(session, window.curves, window.domain, window.results, window.plot_options)
        options = deepcopy(window.plot_options)
        window.close_all_documents(); window.restore_session(session); app.processEvents()
        assert window.plot_options == options
        assert overlay == [(c.style, c.color, c.marker, c.overlay_offset) for c in window.curves]
        window.show_normal(); assert normal == [(c.style, c.color, c.marker, c.offset) for c in window.curves]
        window.show_overlay()
        assert hashes == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        summary = {"status": "passed", "version": __version__, "source_files_unchanged": True,
                   "source_sha256": hashes, "real_sources_hashed": len(hashes), "overlay_files": 3,
                   "selected_uid_preserved": True, "normal_overlay_appearances_independent": True,
                   "session_roundtrip": True, "heading_export_only": True, "credit": "Power By ZzzHe",
                   "user_preferences_untouched": True, "session": str(session), "export": str(export),
                   "vendor_optimization_equivalence": "unverified", "full_reconstruction_complete": False}
        (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k:v for k,v in summary.items() if k != "source_sha256"}, ensure_ascii=True, indent=2))
        window.dirty = False; window.close()


if __name__ == "__main__": main()
