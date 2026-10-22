"""Read-only mass lookup by filename (B=批次号, C=重量) against a weighing xlsx."""
import os
from pathlib import Path

import pytest

import tma_app.mass_lookup as ml
from openpyxl import Workbook


@pytest.fixture
def weighing_sheet(tmp_path, monkeypatch):
    path = tmp_path / "TMA称量数据.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.append([None, "批次号", "重量"])       # A 占位、B 批次号、C 重量
    for batch, weight in (("s0", 12.34), ("s1", 45.6), ("20251225-7#", 78.9),
                          ("2025122508", 91.2), (12345, 1.5),
                          ("H906-2510001", 33.3), ("L301N-26081209", 44.4),
                          ("H906-1126081207", 55.5)):
        sheet.append([None, batch, weight])
    book.save(str(path))
    book.close()
    monkeypatch.setenv("TMA_MASS_XLSX", str(path))
    ml._unavailable = False
    return path


def test_exact_stem_and_full_name_match(weighing_sheet):
    assert ml.lookup_mass("s0.001") == 12.34
    assert ml.lookup_mass("s1.001") == 45.6


def test_batch_run_forms_are_equivalent(weighing_sheet):
    # 20251225-7# / 20251225-7 / 2025122507 是同一个批次。
    assert ml.lookup_mass("20251225-7#.001") == 78.9
    assert ml.lookup_mass("20251225-7.001") == 78.9
    assert ml.lookup_mass("2025122507.001") == 78.9
    # 称量表里用补零形式，文件名用带横杠形式。
    assert ml.lookup_mass("20251225-8.001") == 91.2
    assert ml.lookup_mass("2025122508.001") == 91.2


def test_numeric_batch_and_missing_return_none(weighing_sheet):
    assert ml.lookup_mass("12345.001") == 1.5
    assert ml.lookup_mass("no-such-file.001") is None


def test_model_prefixed_production_batches(weighing_sheet):
    # A 类 7 位 / B 类 8 位 / 其它 10 位：型号-批次号 整串匹配。
    assert ml.lookup_mass("H906-2510001.001") == 33.3
    assert ml.lookup_mass("L301N-26081209.001") == 44.4
    assert ml.lookup_mass("H906-1126081207.001") == 55.5
    # 一侧缺型号时，按纯批次号也能对上。
    assert ml.lookup_mass("2510001.001") == 33.3
    assert ml.lookup_mass("26081209.001") == 44.4
    assert ml.lookup_mass("1126081207.001") == 55.5


def test_missing_sheet_returns_none_and_is_cached(monkeypatch, tmp_path):
    monkeypatch.setenv("TMA_MASS_XLSX", str(tmp_path / "absent.xlsx"))
    ml._unavailable = False
    assert ml.lookup_mass("s0.001") is None
    assert ml._unavailable is True


def test_empty_env_disables_lookup(weighing_sheet, monkeypatch):
    monkeypatch.setenv("TMA_MASS_XLSX", "")
    ml._unavailable = False
    assert ml.lookup_mass("s0.001") is None
