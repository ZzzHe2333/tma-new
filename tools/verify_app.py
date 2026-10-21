"""Run the real Qt workspace offscreen and retain inspectable evidence."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PySide6.QtWidgets import QApplication
from tma_app.app import MainWindow, STYLE
from tma_app.reader import read_dataset
from tma_app.workspace import save_session, load_session


def main():
    root = Path(__file__).resolve().parents[1]
    out = root / "artifacts" / "verification"
    out.mkdir(parents=True, exist_ok=True)
    samples = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Desktop" / "cga"
    paths = [samples / "1.001", samples / "H906-2512097.001", samples / "H907-1125122302.005", samples / "H907-1125122302.txt"]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.warn = lambda message: (_ for _ in ()).throw(AssertionError(message))
    window.show()
    window.import_files(paths, synchronous=True)
    assert len(window.curves) == 4
    assert all(len(c.dataset.values) == 1140 for c in window.curves)
    # Text files may contain edited dimension signals: never replace them with
    # the same-stem raw file. Only acquisition time/temperature match here.
    np.testing.assert_allclose(window.curves[2].dataset.values[:, :2], window.curves[3].dataset.values[:, :2])
    window.files.setCurrentItem(window.files.topLevelItem(0))
    window.lo_box.setValue(100)
    window.hi_box.setValue(180)
    for kind in ("slope", "peak", "integral", "change", "cte", "onset"):
        window.analysis_box.setCurrentIndex(window.analysis_box.findData(kind))
        window.length_box.setValue(5)
        window.run_analysis()
    assert len(window.results) == 6
    original = window.curves[0].dataset.values.copy()
    window.process("smooth")
    assert window.curves[0].working is not None
    window.undo()
    assert window.curves[0].working is None
    window.process("normalize")
    assert np.isclose(window.curves[0].working[0], 100)
    window.reset_curve()
    np.testing.assert_array_equal(window.curves[0].dataset.values, original)
    window.duplicate_curve()
    assert len(window.curves) == 5
    assert window.curves[-1].dataset is window.curves[0].dataset
    assert window.curves[-1].y_index != window.curves[0].y_index
    window.remove_selected()
    assert len(window.curves) == 4
    # Four independent Y axes and per-curve visibility/offset.
    for i, c in enumerate(window.curves):
        c.axis = i
    window.redraw()
    assert len(window.axes) == 4
    for c in window.curves:
        c.axis = 0
    window.curves[1].offset = 300
    window.redraw()
    window.write_data(out / "sample-data.csv", window.curves[0])
    window.write_results(out / "results.csv")
    window.write_report(out / "report.html")
    with (out / "sample-data.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert len(rows) == 1141 and len(rows[0]) == 7
    save_session(out / "verification.tmas", window.curves, window.domain, window.results)
    restored, domain, results = load_session(out / "verification.tmas")
    assert len(restored) == 4 and len(results) == 6 and domain == "temperature"
    np.testing.assert_array_equal(restored[0].dataset.values, original)
    app.processEvents()
    window.canvas.draw()
    assert window.grab().save(str(out / "workspace.png"))
    window.figure.savefig(out / "overlay.svg")
    # Source guard is exercised without writing any source bytes.
    for function in (lambda: window.write_data(paths[0], window.curves[0]), lambda: window.write_report(paths[0]), lambda: window.write_results(paths[0])):
        try:
            function()
        except ValueError:
            pass
        else:
            raise AssertionError("source output guard failed")
    after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    assert before == after
    summary = {"status": "passed", "imported_files": len(paths), "points_per_file": 1140,
               "analysis_methods": len(results), "session_roundtrip": True, "four_y_axes": True,
               "source_hashes_unchanged": True, "exports_read_back": True, "source_hashes": after}
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    window.dirty = False
    window.close()


if __name__ == "__main__":
    main()
