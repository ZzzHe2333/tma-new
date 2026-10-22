"""Date-aware recommendations, ambiguity handling and revision-aware speedup."""
import os
from pathlib import Path
import threading
import time

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton
from test_single_report import ui, wait_until
from tma_app import single_report as backend
from tma_app import particle_recommendation as recommend
from tma_app.path_settings import save_paths, particle_folder


def p9m(path, *, sample="20261017-5#", average=True, ambiguous=False, value=34.841):
    rows = []
    for i, name in enumerate((sample, "20261017-5", "2026101705", "other")):
        is_average = average and (i == 2 or ambiguous and i == 1)
        rows.append(f'<Record ID="{i+1}" IsAverageResult="{str(is_average).lower()}" MeasurementTime="2026-10-20T10:09:21" D50="{value+i}" Span="1.064"><SopConfig SampleName="{name}" SampleSerialNumber="0001"/></Record>')
    raw = ('<Records>' + ''.join(rows) + '</Records>').encode()
    pad = PKCS7(128).padder(); raw = pad.update(raw) + pad.finalize()
    enc = Cipher(algorithms.AES(backend.core._P9M_AES_KEY), modes.CBC(backend.core._P9M_AES_IV)).encryptor()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(enc.update(raw) + enc.finalize())
    return path


@pytest.mark.parametrize("sample", ["20261017-5#", "20261017-5", "2026101705", "20261017-5#.001"])
def test_date_aliases_recommend_exact_month_and_unique_average(tmp_path, sample):
    expected = p9m(tmp_path / "2026年10月份实验.p9m")
    p9m(tmp_path / "2026年09月份实验.p9m", value=999)
    data = recommend.recommend(sample, str(tmp_path / "2020-2028"))
    assert Path(data["file"]) == expected.resolve()
    assert data["selected_index"] == 2 and data["matched_indices"] == [0, 1, 2]
    assert data["fields"]["D50"] == "36.841" and "平均" in data["warning"]


@pytest.mark.parametrize("sample", ["20260231-5#", "20261317-5", "20261017", "20261017-", "20261017-5 extra", "nonsense"])
def test_invalid_date_or_unrecognized_id_never_guesses_today(sample):
    with pytest.raises(ValueError): recommend.sample_date(sample)


def test_missing_month_single_nonmatching_record_and_ambiguity(tmp_path):
    with pytest.raises(ValueError, match="未找到"): recommend.recommend("20261017-5#", str(tmp_path))
    p9m(tmp_path / "2026年10月份实验.p9m", sample="20261017-9", average=False)
    # The fixture's other two aliases still match: multiple single-run rows may
    # be offered, but choosing the first record is never implicit.
    data = recommend.recommend("20261017-5#", str(tmp_path))
    assert data["selected_index"] is None and len(data["matched_indices"]) == 2
    with pytest.raises(ValueError, match="未匹配"): recommend.recommend("20261017-99#", str(tmp_path))
    p9m(tmp_path / "2026年10月实验.p9m")
    with pytest.raises(ValueError, match="多个数据集"): recommend.recommend("20261017-5#", str(tmp_path))


def test_two_average_records_require_manual_choice(tmp_path):
    p9m(tmp_path / "2026年10月份实验.p9m", ambiguous=True)
    data = recommend.recommend("2026101705", str(tmp_path))
    assert data["selected_index"] is None and not data["fields"]


def test_p9m_revision_cache_skips_duplicate_decrypt_and_invalidates_changes(tmp_path, monkeypatch):
    path = p9m(tmp_path / "2026年10月份实验.p9m")
    backend.clear_particle_cache()
    original = backend.core._p9m_parse_records
    calls = []
    def counted(file): calls.append(file); return original(file)
    monkeypatch.setattr(backend.core, "_p9m_parse_records", counted)
    first = backend.read_particle(path, "20261017-5#")
    second = backend.read_particle(path, "2026101705", record_index=0)
    assert len(calls) == 1 and second["fields"]["D50"] == "34.841"
    p9m(path, value=44.841)
    stamp = path.stat().st_mtime_ns + 10000000; os.utime(path, ns=(stamp, stamp))
    updated = backend.read_particle(path, "20261017-5")
    assert len(calls) == 2 and updated["sha256"] != first["sha256"]
    assert updated["fields"]["D50"] == "46.841"


def test_toolbar_equal_size_and_recommend_ui_filter_and_manual_override(ui, tmp_path, monkeypatch):
    dataset = p9m(tmp_path / "2026年10月份实验.p9m")
    save_paths({"m": "", "particle_folder": str(tmp_path / "2020-2028")})
    assert ui.batch_processing_button.size() == ui.single_report_button.size()
    assert ui.single_report_button.width() == 112 and ui.single_report_button.height() == 24
    ui.batch_processing_button.click()
    assert ui.batch_dialog.isVisible()
    ui.batch_dialog.close()
    dialog = ui.show_single_report()
    assert dialog.findChild(QPushButton, "ReportParticleFolder") is None
    dialog.tma_path.setText(str(tmp_path / "20261017-5#.001"))
    dialog.recommend_button.click(); wait_until(lambda: dialog.job is None)
    assert Path(dialog.particle_path.text()) == dataset
    assert dialog.record_box.count() == 4 and dialog.record_box.currentData() == 2
    assert dialog.fields["D50"].text() == "36.841"
    dialog.record_box.setCurrentIndex(1); wait_until(lambda: dialog.job is None)
    assert dialog.fields["D50"].text() == "34.841"
    assert particle_folder() == str(tmp_path / "2020-2028")
    old = dialog.particle_path.text(), dialog.fields["D50"].text()
    dialog.fields["sample_name"].setText("20261017-99#")
    dialog.recommend_button.click(); wait_until(lambda: dialog.job is None)
    assert (dialog.particle_path.text(), dialog.fields["D50"].text()) == old


def test_slow_recommendation_keeps_gui_responsive_and_close_cancels_result(ui, tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def slow(*args, **kwargs):
        entered.set(); release.wait(timeout=3); return None
    monkeypatch.setattr(recommend, "recommend", slow)
    dialog = ui.show_single_report(); dialog.fields["sample_name"].setText("20261017-5#")
    started = time.perf_counter(); dialog.recommend_button.click()
    assert time.perf_counter() - started < .1 and entered.wait(timeout=2)
    assert dialog.close() and not dialog.isVisible()
    release.set(); wait_until(lambda: dialog.job is None)
    assert not dialog.particle_path.text()
