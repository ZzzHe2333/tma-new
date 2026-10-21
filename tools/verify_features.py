"""Exercise new analysis/overlay dialogs against real data without touching sources."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import hashlib
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PySide6.QtWidgets import QApplication
from tma_app.classic import ClassicMainWindow, CLASSIC_STYLE
from tma_app.classic_dialogs import OverlayOptionsDialog, SignalAnalysisDialog
from tma_app.workspace import save_session, load_session
from tma_app.numerics import analyze
from tma_app.reader import read_dataset


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = Path(__file__).resolve().parents[1]
    out = root / "artifacts/feature-verification"
    out.mkdir(parents=True, exist_ok=True)
    paths = sorted((root / "测试文件").glob("*.001"))
    assert len(paths) >= 3
    hashes = {str(path): digest(path) for path in paths}
    full_range_checks = []
    for path in paths:
        ds = read_dataset(path)
        x, y = ds.values[:, ds.temperature_index].astype(float), ds.values[:, 2].astype(float)
        for kind, expected in (("signal_max", float(np.max(y))), ("signal_change", float(y[-1] - y[0]))):
            result = analyze(x, y, kind, float(x.min()), float(x.max()))
            assert result["value"] == expected and result["points"] == len(x)
            full_range_checks.append({"file": path.name, "kind": kind, "value": expected, "points": len(x), "direction": result["direction"]})
    app = QApplication([]); app.setStyle("Fusion"); app.setStyleSheet(CLASSIC_STYLE)
    window = ClassicMainWindow(); window.resize(1600, 900); window.show()
    window.warn = lambda message: (_ for _ in ()).throw(AssertionError(message))
    window.import_files(paths[:3], synchronous=True)
    auto = window.auto_configure_overlay(); auto.accept()
    assert not auto.error.text(), auto.error.text()
    # Cancel must leave both numerical transforms and appearance untouched.
    original = [(c.offset, c.color, c.overlay_enabled) for c in window.curves]
    cancel = OverlayOptionsDialog(window)
    cancel.draft[0].offset = 999; cancel.draft[0].overlay_enabled = False
    cancel.reject()
    assert original == [(c.offset, c.color, c.overlay_enabled) for c in window.curves]
    dialog = OverlayOptionsDialog(window)
    dialog.title.setText("TMA 多文件叠图验证")
    dialog.grid_boxes["grid_y"].setChecked(True)
    dialog.legend.setCurrentIndex(dialog.legend.findData(True))
    for i, c in enumerate(dialog.draft):
        c.legend_text = f"样品 {i+1} · {c.dataset.path.stem}"; c.offset = i * 100
    dialog.populate(); dialog.show(); app.processEvents()
    assert dialog.grab().save(str(out / "overlay-options.png"))
    dialog.accept(); window.redraw(); window.canvas.draw(); app.processEvents()
    assert len(window._plot_artists) == 3
    results = []
    for kind in ("signal_max", "signal_change"):
        analysis = SignalAnalysisDialog(window, kind)
        analysis.low.setValue(100); analysis.high.setValue(200)
        analysis.batch.setChecked(True); analysis.calculate()
        added = window.results[-3:]
        assert len(added) == 3 and all(r["kind"] == kind for r in added)
        for c, result in zip(window.visible_curves(), added):
            x, y = c.xy(window.domain); selected = (x >= 100) & (x <= 200)
            expected = np.max(y[selected]) if kind == "signal_max" else y[selected][-1] - y[selected][0]
            assert result["values"]["value"] == float(expected)
        results.extend(added)
        analysis.show(); app.processEvents()
        assert analysis.grab().save(str(out / f"{kind}-dialog.png"))
        analysis.reject()
    window.redraw(); window.canvas.draw(); app.processEvents()
    assert window.grab().save(str(out / "overlay-analysis.png"))
    window.figure.savefig(out / "overlay-analysis.svg")
    session = out / "verified.tmas"
    save_session(session, window.curves, window.domain, window.results, plot_options=window.plot_options)
    curves, domain, restored, options = load_session(session, include_plot_options=True)
    assert len(curves) == 3 and len(restored) == 6 and options == window.plot_options
    assert [c.legend_text for c in curves] == [c.legend_text for c in window.curves]
    window.close_all_documents(); window.restore_session(session)
    assert len(window._plot_artists) == 3
    window.canvas.draw(); app.processEvents()
    assert window.grab().save(str(out / "session-restored.png"))
    assert hashes == {str(path): digest(path) for path in paths}
    summary = {"status": "passed", "real_sources_hashed": len(paths), "plotted_files": len(curves),
               "results": results, "source_sha256": hashes, "session": str(session),
               "desktop_reference": "WinUA process running but no targetable window; static resources and user screenshots only",
               "vendor_numerical_equivalence": "unverified", "cancel_preserves_state": True,
               "source_files_unchanged": True, "session_settings_restored": True,
               "full_range_real_checks": full_range_checks}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    window.dirty = False; window.close()
    print(json.dumps({k: v for k, v in summary.items() if k not in ("results", "source_sha256", "full_range_real_checks")}, ensure_ascii=False, indent=2))
    print(f"Full-range analysis checks: {len(full_range_checks)} across {len(paths)} real sources")


if __name__ == "__main__": main()
