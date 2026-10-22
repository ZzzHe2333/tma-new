"""Selection and revision changes must invalidate stale particle numbers."""
from pathlib import Path
import os
import threading

import pytest
from test_single_report import ui, wait_until
from test_particle_recommendation import p9m
from tma_app.path_settings import save_paths


def recommended(ui, tmp_path):
    path = p9m(tmp_path / "2026年10月份实验.p9m")
    save_paths({"m": "", "particle_folder": str(tmp_path)})
    dialog = ui.show_single_report()
    dialog.tma_path.setText(str(tmp_path / "20261017-5#.001"))
    dialog.recommend_button.click(); wait_until(lambda: dialog.job is None)
    assert dialog.record_box.currentData() == 2
    assert dialog.fields["D50"].text() == "36.841"
    return dialog, path


def test_placeholder_clears_particle_numbers_and_backend_selection(ui, tmp_path):
    dialog, _ = recommended(ui, tmp_path)
    dialog.record_box.setCurrentIndex(0)
    assert dialog.record_box.currentData() is None
    assert dialog.data["particle"]["selected_index"] is None
    assert all(not dialog.fields[key].text() for key in ("D50", "SPAN", "particle_time"))
    dialog.record_box.setCurrentIndex(1); wait_until(lambda: dialog.job is None)
    assert dialog.fields["D50"].text() == "34.841"


def test_recommend_ambiguous_revision_of_same_file_drops_old_numbers(ui, tmp_path):
    dialog, path = recommended(ui, tmp_path)
    p9m(path, average=False)
    stamp = path.stat().st_mtime_ns + 10000000; os.utime(path, ns=(stamp, stamp))
    dialog.recommend_button.click(); wait_until(lambda: dialog.job is None)
    assert dialog.data["particle"]["selected_index"] is None
    assert dialog.record_box.currentData() is None
    assert all(not dialog.fields[key].text() for key in ("D50", "SPAN", "particle_time"))


def test_changed_p9m_never_reuses_an_old_index_for_another_sample(ui, tmp_path):
    dialog, path = recommended(ui, tmp_path)
    original_sha = dialog.data["particle"]["sha256"]
    p9m(path, sample="20261018-99#", value=100)
    stamp = path.stat().st_mtime_ns + 10000000; os.utime(path, ns=(stamp, stamp))
    # This index belonged to the requested sample in the old file. The new
    # record at the same index belongs to a different experiment.
    dialog.record_box.setCurrentIndex(1); wait_until(lambda: dialog.job is None)
    assert dialog.data["particle"]["sha256"] != original_sha
    assert dialog.data["particle"]["selected_index"] is None
    assert dialog.record_box.currentData() is None
    assert not dialog.fields["D50"].text()
    assert "更新" in dialog.log.toPlainText()
    dialog.record_box.setCurrentIndex(1); wait_until(lambda: dialog.job is None)
    assert dialog.data["particle"]["selected_index"] == 1
    assert dialog.fields["D50"].text() == "101.000"


def test_new_record_selection_invalidates_previous_report_link(ui, tmp_path):
    dialog, _ = recommended(ui, tmp_path)
    dialog.last_output = str(tmp_path / "previous.pdf")
    dialog.open_button.setEnabled(True)
    dialog.record_box.setCurrentIndex(1); wait_until(lambda: dialog.job is None)
    assert not dialog.last_output and not dialog.open_button.isEnabled()


@pytest.mark.parametrize("cancelled", [False, True])
def test_failed_or_cancelled_record_read_restores_displayed_selection(ui, tmp_path, monkeypatch, cancelled):
    from tma_app import single_report as backend
    dialog, _ = recommended(ui, tmp_path)
    entered, release = threading.Event(), threading.Event()
    def interrupted(*args, **kwargs):
        entered.set(); release.wait(timeout=3)
        raise ValueError("synthetic read interruption")
    monkeypatch.setattr(backend, "read_sources", interrupted)
    dialog.record_box.setCurrentIndex(1)
    assert entered.wait(timeout=2)
    if cancelled: dialog.close()
    release.set(); wait_until(lambda: dialog.job is None)
    assert dialog.data["particle"]["selected_index"] == 2
    assert dialog.record_box.currentData() == 2
    assert dialog.fields["D50"].text() == "36.841"
