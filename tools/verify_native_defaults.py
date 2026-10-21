"""Real-data native cursor/default-page evidence, isolated from user preferences."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hashlib
import json
import tempfile
from copy import deepcopy
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tma_app import preferences, __version__
from tma_app.classic import ClassicMainWindow, CLASSIC_STYLE
from tma_app.classic_dialogs import OverlayOptionsDialog
from tma_app.workspace import save_session


def main():
    root = Path(__file__).resolve().parents[1]
    out = root / "artifacts/native-defaults-verification"; out.mkdir(parents=True, exist_ok=True)
    sources = sorted((root / "测试文件").glob("*.001"))
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    selected = next(path for path in sources if path.stem == "20261015-9#")
    application = QApplication([]); application.setStyle("Fusion"); application.setStyleSheet(CLASSIC_STYLE)
    with tempfile.TemporaryDirectory(prefix="tma-defaults-qa-") as private:
        preferences.preferences_path = lambda: Path(private) / "preferences.json"
        window = ClassicMainWindow(); window.resize(1920, 1017); window.show()
        window.warn = lambda message: (_ for _ in ()).throw(AssertionError(message))
        window.import_files([selected], synchronous=True)
        entry = window.start_point_measurement("dimension_change")
        dialog = window.edit_measurement_limits(); application.processEvents()
        for field, value in zip(dialog.fields, [170, 187.85]): field.setText(str(value))
        for field, value in zip(dialog.y_fields, [-3.5, 1300]): field.setText(str(value))
        dialog.grab().save(str(out / "manual-xy.png")); dialog.accept()
        assert entry["values"]["H"] == 1303.5 and not window.results
        QTest.keyClick(window.canvas, Qt.Key.Key_Return)
        assert window.results == [entry] and window._pending_measurement is None
        application.processEvents(); window.canvas.draw(); window.grab().save(str(out / "confirmed-xy.png"))
        values = deepcopy(entry["values"])
        window.edit_measurement(entry); editor = window._measurement_artists[-1]
        before = editor.coords[0]
        QTest.keyClick(window.canvas, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
        assert editor.coords[0] != before
        window.cancel_measurement(); assert window.results[0]["values"] == values
        session = out / "manual-xy.tmas"
        save_session(session, window.curves, window.domain, window.results, window.plot_options)
        window.show_overlay()
        options = OverlayOptionsDialog(window)
        options.tabs.setCurrentIndex(3); options.legend_boxes["legend_border"].setChecked(True)
        options.title.setText("not saved from legend page")
        options.save()
        saved = preferences.load_defaults("overlay")
        assert saved["options"]["legend_border"] and "title" not in saved["options"]
        options.defaults()
        assert options.title.text() == "not saved from legend page" and not options.legend_boxes["legend_border"].isChecked()
        options.show(); application.processEvents(); options.grab().save(str(out / "page-defaults.png")); options.reject()
        (out / "preferences-snapshot.json").write_bytes(preferences.preferences_path().read_bytes())
        window.close_all_documents(); window.restore_session(session); application.processEvents()
        assert window.results[0]["interactive"]["manual_y"] == [-3.5, 1300]
        assert window.results[0]["values"] == values
        assert hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
        summary = {"status": "passed", "version": __version__, "manual_xy": [[170, -3.5], [187.85, 1300]],
                   "manual_values_are_explicit_inputs": True, "height": 1303.5,
                   "enter_confirms": True, "keyboard_nudge_cancel_preserves_result": True,
                   "save_and_factory_default_are_page_scoped": True,
                   "user_preferences_untouched": True, "source_files_unchanged": True,
                   "source_sha256": hashes, "session": str(session)}
        (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k:v for k,v in summary.items() if k != "source_sha256"}, ensure_ascii=True, indent=2))
        window.dirty = False; window.close()


if __name__ == "__main__": main()
