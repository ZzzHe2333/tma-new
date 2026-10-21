"""Reader regression tests, including optional read-only instrument fixtures."""
from pathlib import Path
import hashlib
import struct

import numpy as np
import pytest

from tma_app.reader import ParseError, Signal, read_dataset


HEADER = ("CLOSED\r\nVERSION 2.0\r\nInstrument TMA Q400 V22.5 Build 31\r\n"
          "Module TMA Standard\r\nSample 测试样品\r\nComment first\r\nComment second\r\n"
          "Nsig 5\r\nSig1 Time (min)\r\nSig2 Temperature (°C)\r\n"
          "Sig3 Dimension Change (µm)\r\nSig4 Force (N)\r\n"
          "Sig5 Sample Purge Flow (mL/min)\r\n")
ROWS = np.array([[.004, 60, -2, .06, 50], [.004166667, 60, -1, .06, 50],
                 [.0125, 70, 2, .06, 50], [.020833333, 65, 1, .06, 50]])
END = struct.pack("<5f", -100, 20, 0, 0, 0)


@pytest.mark.parametrize("path", sorted((Path(__file__).resolve().parents[1] / "测试文件").glob("*.001")), ids=lambda p: p.name)
def test_project_real_samples(path):
    original = path.read_bytes()
    ds = read_dataset(path)
    assert ds.values.shape[1] == 5
    assert len(ds.values) >= 1000
    assert not ds.warnings
    assert np.isfinite(ds.values).all()
    assert path.read_bytes() == original


def binary(rows=ROWS, *, footer=True):
    data = HEADER.encode("utf-16") + b"\x0c\x00\x05" + np.asarray(rows, dtype="<f4").tobytes()
    return data + (END + bytes(60) if footer else b"")


def test_binary_known_boundary_preserves_order_and_unicode(tmp_path):
    path = tmp_path / "test.003"
    path.write_bytes(binary())
    ds = read_dataset(path)
    np.testing.assert_allclose(ds.values, ROWS, rtol=1e-6)
    assert ds.name == "测试样品"
    assert ds.metadata["Comment"] == ["first", "second"]
    assert ds.signals[2] == Signal("Dimension Change", "µm")
    assert ds.index_for("dimension") == 2
    assert ds.index_for("Dimension Change (μm)") == 2
    assert ds.time_index == 0 and ds.temperature_index == 1
    assert ds.values[:, 1].tolist() == [60, 60, 70, 65]
    assert ds.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert ds.warnings == []


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-16le", "utf-16be"])
def test_text_encodings(tmp_path, encoding):
    path = tmp_path / "text.002"
    text = HEADER + "StartOfData\r\n" + "\r\n".join("\t".join(map(str, r)) for r in ROWS)
    data = text.encode(encoding)
    if encoding == "utf-16be":
        data = b"\xfe\xff" + data
    path.write_bytes(data)
    ds = read_dataset(path)
    np.testing.assert_allclose(ds.values, ROWS)
    assert ds.warnings == []


def test_unknown_binary_rejected(tmp_path):
    path = tmp_path / "unknown.001"
    path.write_bytes(bytes(1000))
    with pytest.raises(ParseError):
        read_dataset(path)
    path.write_bytes(binary().replace(b"\x0c\x00\x05", b"\x0b\x00\x05", 1))
    with pytest.raises(ParseError, match="前导"):
        read_dataset(path)


def test_other_binary_module_rejected(tmp_path):
    path = tmp_path / "DSC.001"
    path.write_bytes(binary().replace("TMA Standard".encode("utf-16le"),
                                      "DSC Standard".encode("utf-16le")))
    with pytest.raises(ParseError, match="TMA Standard"):
        read_dataset(path)


def test_valid_first_float_is_not_enough_to_accept_binary(tmp_path):
    path = tmp_path / "false_match.001"
    fake = ROWS.copy()
    fake[1:, 0] = 0
    path.write_bytes(binary(fake))
    with pytest.raises(ParseError, match="时间"):
        read_dataset(path)


def test_binary_partial_final_record_returns_intact_prefix_with_warning(tmp_path):
    path = tmp_path / "truncated.001"
    path.write_bytes(binary(footer=False)[:-3])
    ds = read_dataset(path)
    assert ds.values.shape == (3, 5)
    assert any("截断" in w for w in ds.warnings)
    assert any("17 字节" in w for w in ds.warnings)


def test_binary_invalid_record_is_not_silently_accepted(tmp_path):
    path = tmp_path / "corrupt.001"
    rows = np.vstack([ROWS, [np.nan, 60, 0, .06, 50]])
    path.write_bytes(binary(rows))
    ds = read_dataset(path)
    assert ds.values.shape == (4, 5)
    assert any("数值无效" in w for w in ds.warnings)


def test_binary_late_time_reversal_warns(tmp_path):
    path = tmp_path / "time_reversal.001"
    rows = np.tile(ROWS[-1], (12, 1))
    rows[:, 0] = np.arange(12) / 100
    rows[-1, 0] = 0
    path.write_bytes(binary(rows))
    ds = read_dataset(path)
    assert len(ds.values) == 11
    assert any("时间倒退" in w for w in ds.warnings)


def test_text_malformed_tail_reports_partial_data(tmp_path):
    path = tmp_path / "truncated.txt"
    path.write_text(HEADER + "StartOfData\n0 60 -2 .06 50\n.01 60", encoding="utf-8")
    ds = read_dataset(path)
    assert len(ds.values) == 1
    assert any("不完整" in w for w in ds.warnings)


def test_text_time_reversal_retains_original_rows(tmp_path):
    path = tmp_path / "restart.txt"
    path.write_text(HEADER + "StartOfData\n1 60 -2 .06 50\n0 50 -3 .06 50", encoding="utf-8")
    ds = read_dataset(path)
    assert ds.values[:, 0].tolist() == [1, 0]
    assert any("倒退" in w for w in ds.warnings)


def test_text_column_definition_and_empty_data_rejected(tmp_path):
    path = tmp_path / "bad.txt"
    for text in [HEADER + "StartOfData\n", HEADER + "StartOfData\n0 1 2", "StartOfData\n0 1 2"]:
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ParseError):
            read_dataset(path)


SAMPLES = Path.home() / "Desktop" / "cga"
REAL_FILES = sorted(p for p in SAMPLES.glob("*") if p.suffix.lower() in (".001", ".005", ".txt"))


@pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name)
def test_real_q400_file(path):
    ds = read_dataset(path)
    assert ds.values.shape == (1140, 5)
    assert ds.warnings == []
    assert ds.values[0, 0] == pytest.approx(.004)
    assert ds.values[-1, 0] == pytest.approx(9.4875)
    assert np.isfinite(ds.values).all()


@pytest.mark.skipif(not REAL_FILES, reason="Original cga fixtures are local, not distributed")
def test_binary_matches_instrument_text_exports():
    compared = 0
    for path in SAMPLES.glob("*.txt"):
        ds = read_dataset(path)
        original = SAMPLES / (ds.name + ".001")
        if not original.exists():
            continue
        raw = read_dataset(original)
        # Exported decimal text is rounded, with largest observed difference
        # below 0.0007 µm; use independent per-channel rounding tolerances.
        for channel, tolerance in enumerate([2e-6, 1e-4, 1e-3, 1e-7, 2e-5]):
            np.testing.assert_allclose(ds.values[:, channel], raw.values[:, channel],
                                       atol=tolerance, rtol=0)
        compared += 1
    assert compared >= 1
