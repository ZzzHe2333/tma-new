import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
import pytest
from tma_app import legacy_t1_t2_h as legacy
from tma_app.reader import read_dataset, Dataset, Signal
from tma_app.t1_t2_h import extract_metrics

ROOT = Path(__file__).resolve().parents[1]


def test_extracted_algorithm_definitions_are_unchanged():
    source = ROOT / "power/tma_super_max_v219.py"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == legacy.SOURCE_SHA256
    before = {node.name: node for node in ast.parse(source.read_text(encoding="utf-8-sig")).body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    after = [node for node in ast.parse(Path(legacy.__file__).read_text(encoding="utf-8")).body if isinstance(node, (ast.FunctionDef, ast.ClassDef))]
    assert len(after) == 20
    for node in after:
        assert ast.dump(node, include_attributes=False) == ast.dump(before[node.name], include_attributes=False)


@pytest.mark.parametrize("algorithm", ["super", "robust"])
def test_real_data_matches_original_function_api(algorithm):
    paths = sorted((ROOT / "测试文件").glob("*.001"))
    if not paths: pytest.skip("Real project samples unavailable")
    for path in paths:
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        ds = read_dataset(path)
        result = extract_metrics(ds, algorithm=algorithm)
        expected = legacy._compute_t1_t2_h_integral_details(ds.values[:, ds.temperature_index].tolist(), ds.values[:, 2].tolist(), use_super=algorithm == "super")
        assert [result[key] for key in ("T1", "T2", "H", "area", "H1", "H2")] == pytest.approx(expected[:6], abs=1e-10)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_cycles_require_explicit_slice():
    x = np.r_[np.linspace(60, 260, 100), np.linspace(260, 60, 100)]
    ds = Dataset(Path("cycle.001"), [Signal("Time", "min"), Signal("Temperature", "°C"), Signal("Dimension Change", "µm")], np.column_stack((np.arange(200), x, np.exp(-((x-200)/30)**2)*1000)), {}, [], "test")
    with pytest.raises(ValueError, match="升温段"): extract_metrics(ds)
    result = extract_metrics(ds, sample_start=0, sample_stop=100)
    assert result["sample_stop"] == 100 and result["H"] > 0


def test_cli_json_csv_and_portable_script(tmp_path):
    sample = next(iter((ROOT / "测试文件").glob("*.001")), None)
    if sample is None: pytest.skip("Real project samples unavailable")
    before = sample.read_bytes()
    result = subprocess.run([sys.executable, str(ROOT / "extract_t1_t2_h.py"), str(sample), "--json", str(tmp_path / "result.json"), "--csv", str(tmp_path / "result.csv")], capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    report = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert len(report["results"]) == 1 and not report["errors"]
    assert (tmp_path / "result.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    from tools.build_t1_t2_h_standalone import build
    portable = build(tmp_path / "extract_t1_t2_h.py")
    portable_report = tmp_path / "portable.json"
    result = subprocess.run([sys.executable, str(portable), str(sample), "--json", str(portable_report)], cwd=tmp_path, capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert json.loads(portable_report.read_text(encoding="utf-8"))["results"] == report["results"]
    result = subprocess.run([sys.executable, str(portable), str(sample), "--json", str(sample)], capture_output=True)
    assert result.returncode != 0 and sample.read_bytes() == before


def test_cli_handles_windows_gbk_console_and_missing_input(tmp_path):
    import os
    sample = next(iter((ROOT / "测试文件").glob("*.001")), None)
    if sample is None: pytest.skip("Real project samples unavailable")
    environment = dict(os.environ, PYTHONIOENCODING="gbk")
    result = subprocess.run([sys.executable, str(ROOT / "extract_t1_t2_h.py"), str(sample)], capture_output=True, env=environment)
    assert result.returncode == 0
    assert json.loads(result.stdout.decode("gbk"))["results"][0]["height_unit"] == "µm"
    path = tmp_path / "nested/report.json"
    result = subprocess.run([sys.executable, str(ROOT / "extract_t1_t2_h.py"), str(tmp_path / "missing.001"), "--json", str(path), "--quiet"], capture_output=True)
    assert result.returncode == 1
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["results"] == [] and len(report["errors"]) == 1
