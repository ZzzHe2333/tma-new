import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from tma_app.classic import ClassicMainWindow, nice_limits
from tma_app.reader import Dataset, Signal
from tma_app.workspace import save_session


@pytest.fixture
def ui():
    application = QApplication.instance() or QApplication([])
    window = ClassicMainWindow()
    window.warn = lambda message: (_ for _ in ()).throw(AssertionError(message))
    window.show()
    application.processEvents()
    yield window
    window.dirty = False
    for dialog in window.dialogs.values():
        dialog.hide()
    window.close()
    application.processEvents()


def dataset(path):
    time = np.arange(31, dtype=float)
    return Dataset(Path(path), [Signal("Time", "min"), Signal("Temperature", "°C"), Signal("Dimension Change", "µm")],
                   np.column_stack([time, time + 100, time * 2 + 3]),
                   {"Sample": [Path(path).stem]}, [], "test-source-digest")


def test_source_menu_order_and_glyphs(ui):
    assert [a.text() for a in ui.menuBar().actions()] == ["设置", "文件", "编辑", "重定刻度", "曲线图", "分析", "工具", "视图", "宏", "窗口", "帮助", "用户", "成就"]
    assert not ui.documents
    assert not ui.classic_actions["Open1"].icon().isNull()
    assert ui.classic_actions["Open1"].isEnabled()
    assert ui.classic_actions["GlassTransition1"].isEnabled()
    assert ui.classic_actions["SigHorizontal1"].isEnabled()


def test_independent_documents_overlay_and_close(ui, tmp_path):
    ui.finish_import([dataset(tmp_path / "a.001"), dataset(tmp_path / "b.002")], [])
    assert len(ui.documents) == 2
    assert len(ui.visible_curves()) == 1
    ui.show_overlay()
    assert len(ui.visible_curves()) == 2
    assert len(ui.mdi.subWindowList()) == 3
    assert ui.mdi.activeSubWindow().key == "__overlay__"
    ui.show_normal()
    ui.close_active_document()
    assert len(ui.curves) == 1
    ui.show_overlay()
    # 再次点击“叠图”应新开一张独立的叠图，而不是覆盖原叠图。
    assert ui.mdi.activeSubWindow().key == "__overlay__:2"
    assert "__overlay__" in ui.documents and "__overlay__:2" in ui.documents
    assert len(ui.mdi.subWindowList()) == 3
    assert len(ui.visible_curves()) == 1


def test_session_restore_rebuilds_documents(ui, tmp_path):
    curve_datasets = [dataset(tmp_path / "a.001"), dataset(tmp_path / "b.002")]
    ui.finish_import(curve_datasets, [])
    save_session(tmp_path / "state.tmas", ui.curves, "temperature", [])
    ui.close_all_documents()
    ui.restore_session(tmp_path / "state.tmas")
    assert len(ui.curves) == 2
    assert len(ui.documents) == 3
    assert len(ui.visible_curves()) == 2
    ui.analysis_box.setCurrentIndex(ui.analysis_box.findData("slope"))
    ui.lo_box.setValue(105)
    ui.hi_box.setValue(120)
    ui.run_analysis()
    assert ui.results[-1]["values"]["slope"] == pytest.approx(2)


def test_background_import_completes_in_classic_ui(ui, tmp_path):
    file = tmp_path / "async.003"
    file.write_text("Nsig 3\nSig1 Time (min)\nSig2 Temperature (°C)\nSig3 Dimension Change (µm)\nStartOfData\n0 100 1\n1 110 2\n2 120 3\n", encoding="utf-8")
    loop = QEventLoop()
    ui.import_files([file])
    ui.worker.finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    assert ui.worker is None
    assert len(ui.curves) == 1 and len(ui.documents) == 1


def test_redraw_preserves_user_view_and_full_scale_restores_data(ui, tmp_path):
    ui.finish_import([dataset(tmp_path / "sample.001")], [])
    original_ticks = ui.axes[0].get_yticks().copy()
    ui.redraw()
    np.testing.assert_array_equal(ui.axes[0].get_yticks(), original_ticks)
    ui.axes[0].set_xlim(108, 118)
    ui.axes[0].set_ylim(15, 40)
    ui.redraw()
    assert ui.axes[0].get_xlim() == pytest.approx((108, 118))
    assert ui.axes[0].get_ylim() == pytest.approx((15, 40))
    ui.full_scale()
    x, y = ui.curves[0].xy(ui.domain)
    assert ui.axes[0].get_xlim()[0] <= x.min() and ui.axes[0].get_xlim()[1] >= x.max()
    assert ui.axes[0].get_ylim()[0] <= y.min() and ui.axes[0].get_ylim()[1] >= y.max()


@pytest.mark.parametrize("values", [[-1200, -3], [3, 3], [1e-8, 2e-8], [-1e6, 4e6]])
def test_readable_limits_enclose_samples(values):
    limits, ticks = nice_limits(np.array(values))
    assert limits[0] <= min(values) <= max(values) <= limits[1]
    assert limits[0] < limits[1]
    assert np.all(np.diff(ticks) > 0)
