"""Real-data review artifacts for explicit confirm, label drag and exact axes."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copy import deepcopy
import hashlib
import json
import numpy as np
from matplotlib.backend_bases import MouseEvent
from matplotlib.text import Text
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QDialog
from tma_app.classic import ClassicMainWindow, CLASSIC_STYLE
from tma_app.workspace import save_session
from verify_points import drag


def move_label(window, text, dx, dy):
    window.canvas.draw()
    box = Text.get_window_extent(text, window.canvas.get_renderer())
    x, y = (box.x0+box.x1)/2, (box.y0+box.y1)/2
    for kind, px, py in (("button_press_event", x, y), ("motion_notify_event", x+dx, y+dy), ("button_release_event", x+dx, y+dy)):
        window.canvas.callbacks.process(kind, MouseEvent(kind, window.canvas, px, py, button=1))


def main():
    root = Path(__file__).resolve().parents[1]
    out = root / "artifacts/confirm-rescale-verification"; out.mkdir(parents=True, exist_ok=True)
    files = sorted((root / "测试文件").glob("*.001"))
    source = next((path for path in files if path.stem == "20261015-9#"), files[0])
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    app = QApplication([]); app.setStyle("Fusion"); app.setStyleSheet(CLASSIC_STYLE)
    window = ClassicMainWindow(); window.resize(1920, 1017); window.show()
    window.warn = lambda text: (_ for _ in ()).throw(AssertionError(text))
    window.import_files([source], synchronous=True)
    entry = window.start_point_measurement("dimension_change")
    window.canvas.draw(); app.processEvents()
    assert not window.results and window.measurement_confirm.isEnabled()
    window.grab().save(str(out / "select-points.png"))
    editor = next(item for item in window._measurement_artists if item.entry is entry)
    editor = drag(window, editor, 0, int(np.argmin(abs(editor.x-180))))
    window.measurement_confirm.trigger()
    window.canvas.draw(); app.processEvents()
    editor = window._measurement_artists[0]
    assert editor.entry["interactive"]["confirmed"] and not editor.vline.get_visible() and not editor.hline.get_visible()
    fixed = deepcopy(entry["values"])
    window.grab().save(str(out / "confirmed.png"))
    move_label(window, editor.temps[0], -55, -10)
    move_label(window, editor.temps[1], 35, 15)
    offsets = deepcopy(entry["annotation"]["label_offsets"])
    assert entry["values"] == fixed and set(offsets) == {"t1", "t2"}
    window.canvas.draw(); app.processEvents(); window.grab().save(str(out / "labels-dragged.png"))
    maximum = window.start_point_measurement("signal_max")
    editor = next(item for item in window._measurement_artists if item.entry is maximum)
    drag(window, editor, 0, int(np.argmin(abs(editor.x-203.677))))
    window.measurement_confirm.trigger()
    editor = next(item for item in window._measurement_artists if item.entry is maximum)
    assert "信号最大" not in editor.annotation.get_text() and "已移动" not in editor.annotation.get_text()
    assert editor.annotation.get_text().endswith("°C")
    window.canvas.draw(); app.processEvents(); window.grab().save(str(out / "temperature-only.png"))
    window.show_overlay()
    dialog = window.manual_rescale("x")
    for key, values in (("x", [50, 300, 50, 12.5, 0]), (0, [-500, 2500, 500, 125, 0])):
        for widget, value in zip(dialog.fields[key], values): widget.setText(str(value))
    app.processEvents(); dialog.grab().save(str(out / "rescale-dialog.png"))
    QTest.mouseClick(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert np.allclose(window.axes[0].get_xlim(), [50, 300]) and np.allclose(window.axes[0].get_ylim(), [-500, 2500])
    window.canvas.draw(); app.processEvents(); window.grab().save(str(out / "rescaled.png"))
    session = out / "confirmed.tmas"
    save_session(session, window.curves, window.domain, window.results, plot_options=window.plot_options)
    window.close_all_documents(); window.restore_session(session)
    assert window.results[0]["annotation"]["label_offsets"] == offsets
    assert all(result["interactive"]["confirmed"] for result in window.results)
    assert not any(editor.vline.get_visible() or editor.hline.get_visible() for editor in window._measurement_artists)
    assert np.allclose(window.axes[0].get_xlim(), [50, 300])
    assert window.axes[0].xaxis.get_major_formatter()(100) == "100"
    assert hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    summary = {"status": "passed", "source": str(source), "explicit_confirm_button": True, "reference_lines_hidden_after_confirm": True,
               "temperature_labels_draggable_after_confirm": True, "dragging_labels_preserves_values": True,
               "maximum_label_temperature_only": True, "rescale_dialog_fields": 5,
               "x_limits": list(window.axes[0].get_xlim()), "y_limits": list(window.axes[0].get_ylim()),
               "plot_options": window.plot_options, "session_restored": True, "source_files_unchanged": True,
               "source_sha256": hashes, "session": str(session)}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key not in ("source_sha256", "plot_options")}, ensure_ascii=False, indent=2))
    window.dirty = False; window.close()


if __name__ == "__main__": main()
