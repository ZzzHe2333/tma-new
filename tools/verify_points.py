"""Real-data QA for sample-attached handles, popup menu and session persistence."""
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
from PySide6.QtWidgets import QApplication
from tma_app.classic import ClassicMainWindow, CLASSIC_STYLE
from tma_app.workspace import save_session
from tma_app.measurement import nearest_sample


def drag(window, editor, point, target):
    canvas = window.canvas; canvas.draw()
    editor = next(current for current in window._measurement_artists if current.entry is editor.entry)
    x, y = editor.x[editor.indices[point]], editor.y[editor.indices[point]]
    px, py = editor.axis.transData.transform((x, y))
    canvas.callbacks.process("button_press_event", MouseEvent("button_press_event", canvas, px, py, button=1))
    assert window._drag_measurement == (editor, point)
    tx, ty = editor.axis.transData.transform((float(editor.x[target]), float(np.min(editor.y))))
    motion = MouseEvent("motion_notify_event", canvas, tx, ty, button=1)
    actual_x = editor.axis.transData.inverted().transform((motion.x, motion.y))[0]
    expected = nearest_sample(editor.x, actual_x, editor.indices[point])
    canvas.callbacks.process("motion_notify_event", motion)
    canvas.callbacks.process("button_release_event", MouseEvent("button_release_event", canvas, tx, ty, button=1))
    assert editor.indices[point] == expected
    return editor


def main():
    root = Path(__file__).resolve().parents[1]
    out = root / "artifacts/point-verification"; out.mkdir(parents=True, exist_ok=True)
    files = sorted((root / "测试文件").glob("*.001"))
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    app = QApplication([]); app.setStyle("Fusion"); app.setStyleSheet(CLASSIC_STYLE)
    window = ClassicMainWindow(); window.resize(1920, 1017); window.show()
    window.warn = lambda text: (_ for _ in ()).throw(AssertionError(text))
    window.import_files([files[0]], synchronous=True)
    entry = window.start_point_measurement("dimension_change")
    editor = window._measurement_artists[0]
    initial = deepcopy(entry)
    window.canvas.draw(); app.processEvents()
    window.grab().save(str(out / "dimension-initial.png"))
    editor = drag(window, editor, 0, int(np.argmin(abs(editor.x - 180))))
    editor = drag(window, editor, 1, int(np.argmin(abs(editor.x - 220))))
    values = entry["values"]
    assert values["H"] == editor.y[editor.indices[1]] - editor.y[editor.indices[0]]
    assert values["T1"] == editor.x[editor.indices[0]] and values["T2"] == editor.x[editor.indices[1]]
    window.canvas.draw(); app.processEvents()
    window.grab().save(str(out / "dimension-dragged.png"))
    window.figure.savefig(out / "dimension-dragged.svg")
    window.measurement_confirm.trigger()
    menu = window.create_plot_context_menu(); menu.ensurePolished(); menu.adjustSize()
    menu.setFixedHeight(menu.actionGeometry(menu.actions()[-1]).bottom() + 5)
    menu.grab().save(str(out / "context-menu.png"))
    context_labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    maximum = window.start_point_measurement("signal_max")
    editor = next(e for e in window._measurement_artists if e.entry is maximum)
    assert editor.indices == [int(np.argmax(editor.y))]
    editor = drag(window, editor, 0, int(np.argmin(abs(editor.x - 225))))
    assert maximum["values"]["value"] == editor.y[editor.indices[0]]
    window.measurement_confirm.trigger()
    window.canvas.draw(); app.processEvents(); window.grab().save(str(out / "signal-max-dragged.png"))
    session = out / "interactive.tmas"
    save_session(session, window.curves, window.domain, window.results, plot_options=window.plot_options)
    expected = [list(e["interactive"]["indices"]) for e in window.results]
    window.close_all_documents(); window.restore_session(session)
    assert [list(e.indices) for e in window._measurement_artists] == expected
    window.canvas.draw(); app.processEvents(); window.grab().save(str(out / "restored.png"))
    window.write_results(out / "results.csv")
    assert hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    report = {"status": "passed", "initial": initial, "results": window.results,
              "context_menu": context_labels, "source_files_unchanged": True,
              "source_sha256": hashes, "mouse_drag_events": True, "session_restored": True}
    (out / "interactive-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "mouse_drag_events", "session_restored", "source_files_unchanged")}, indent=2))
    window.dirty = False; window.close()


if __name__ == "__main__": main()
