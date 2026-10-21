"""Render genuine project data at the supplied reference screenshot size."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import numpy as np
from PySide6.QtCore import QPoint, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from tma_app.classic import ClassicMainWindow, CLASSIC_STYLE, REFERENCE_TOOLBAR


def main():
    root = Path(__file__).resolve().parents[1]
    out = root / "artifacts/screenshot-verification"
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(CLASSIC_STYLE)
    window = ClassicMainWindow()
    window.warn = lambda message: (_ for _ in ()).throw(AssertionError(message))
    window.resize(1920, 1017)  # Supplied 1920x1080 screenshot, excluding OS chrome.
    window.show()
    paths = sorted((root / "测试文件").glob("*.001"))
    assert paths
    window.import_files([paths[0]], synchronous=True)
    loop = QEventLoop()
    QTimer.singleShot(150, loop.quit)
    loop.exec()
    window.redraw()
    window.canvas.draw()
    app.processEvents()
    window.grab().save(str(out / "single-trace.png"))
    window.figure.savefig(out / "single-trace.svg")
    origin = window.canvas.mapTo(window, QPoint(0, 0))
    bounds = window.axes[0].bbox.bounds
    toolbar = window.classic_toolbar
    items = []
    for action in toolbar.actions():
        rect = toolbar.widgetForAction(action).geometry()
        pos = toolbar.widgetForAction(action).mapTo(window, QPoint(0, 0))
        items.append({"image_index": action.data(), "rect": [pos.x(), pos.y(), rect.width(), rect.height()]})
    assert [item["image_index"] for item in items] == list(REFERENCE_TOOLBAR)
    summary = {"status": "passed", "canvas": [origin.x(), origin.y(), window.canvas.width(), window.canvas.height()],
               "frame_in_window": [origin.x() + bounds[0], origin.y() + window.canvas.height() - bounds[1] - bounds[3],
                                   origin.x() + bounds[0] + bounds[2], origin.y() + window.canvas.height() - bounds[1]],
               "x_limits": window.axes[0].get_xlim(), "y_limits": window.axes[0].get_ylim(), "toolbar": items,
               "source": str(paths[0]), "source_sha256": window.curves[0].dataset.sha256}
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "toolbar"}, indent=2))
    print("First button:", items[0])
    print("Menus:", [(a.text(), window.menuBar().actionGeometry(a).getRect()) for a in window.menuBar().actions()])
    if "--probe-lines" in sys.argv:
        line = window.axes[0].lines[0]
        for snap in (False, True):
            for width in (.2, .45, .72, 1.):
                line.set_snap(snap)
                line.set_linewidth(width)
                window.canvas.draw()
                rgb = np.asarray(window.canvas.buffer_rgba())
                rows = np.flatnonzero(rgb[720:740,400,:3].max(axis=1)<100)+720
                print("Line probe", snap, width, rows.tolist())
    window.dirty = False
    window.close()


if __name__ == "__main__":
    main()
