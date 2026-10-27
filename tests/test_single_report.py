"""Report algorithm provenance, PDF paths, template fallback and independent folders."""
import ast
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import threading
import time

import fitz
import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from tma_app import single_report as report
from tma_app import report_internal_core as core, report_template_core as template_core
from tma_app.classic import ClassicMainWindow
from tma_app.path_settings import load_paths, save_paths, particle_folder

ROOT = Path(__file__).resolve().parents[1]


def test_extracted_report_definitions_match_both_supplied_scripts():
    for module in (core, template_core):
        source = ROOT / "power" / module.SOURCE_FILE
        assert hashlib.sha256(source.read_bytes()).hexdigest() == module.SOURCE_SHA256
        before = {n.name: n for n in ast.parse(source.read_text(encoding="utf-8-sig")).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        after = [n for n in ast.parse(Path(module.__file__).read_text(encoding="utf-8")).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        for node in after:
            assert ast.dump(node, include_attributes=False) == ast.dump(before[node.name], include_attributes=False)
        assert "import tkinter" not in Path(module.__file__).read_text(encoding="utf-8")


@pytest.fixture
def sources(tmp_path):
    sample = next((ROOT / "测试文件").glob("*.001"), None)
    if sample is None:
        pytest.skip("Project TMA sample unavailable")
    local = tmp_path / "样品-20261013-9#.001"
    local.write_bytes(sample.read_bytes())
    particle = tmp_path / "particle.pdf"
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((60, 70), "Particle distribution: TEST FIXTURE", fontsize=15)
        page.insert_text((60, 120), "D50: 12.345")
        page.insert_text((60, 150), "SPAN: 1.234")
        doc.save(particle)
    mass = tmp_path / "mass.csv"
    mass.write_text(f"样品名,M (mg)\n{local.stem},0.47\n", encoding="utf-8-sig")
    return local, particle, mass


def request_data(sources, tmp_path):
    sample, particle, mass = sources
    data = report.read_sources(str(sample), str(particle), str(mass))
    assert not data["errors"]
    request = dict(tma_path=str(sample), particle_path=str(particle), mass_source=str(mass), fields=dict(data["fields"]),
                   template_path="", output_path=str(tmp_path / "result.pdf"), algorithm="auto", record_index=None)
    return request, data


def test_internal_algorithm_mass_and_instrument_time_match_source(sources, tmp_path):
    request, data = request_data(sources, tmp_path)
    tma = data["tma"]
    t1, t2, _ = core.detect_T2_T1_precise(tma["xs"], tma["ys"])
    cache = core.build_curve_cache(tma["xs"], tma["ys"])
    height = core.interpolate_curve_height(t2, cache) - core.interpolate_curve_height(t1, cache)
    assert request["fields"]["T1"] == f"{t1:.2f}"
    assert request["fields"]["T2"] == f"{t2:.2f}"
    assert request["fields"]["H"] == core.format_height_um(height)
    assert request["fields"]["M"] == "0.4700"
    assert request["fields"]["D50"] == "12.345" and request["fields"]["SPAN"] == "1.234"
    assert request["fields"]["tma_time"] == core._extract_tma_internal_datetime(str(sources[0]))
    assert request["fields"]["TMA"] == f"{core.calc_tma_from_m_h(.47,float(request['fields']['H'])):.3f}"


def test_default_internal_three_page_report_no_template_autodetection(sources, tmp_path, monkeypatch):
    request, data = request_data(sources, tmp_path)
    before = {p: p.read_bytes() for p in sources}
    monkeypatch.chdir(ROOT / "power")  # A real valid W456.pdf is nearby: still do not use it.
    result = report.generate_report(request, data)
    assert result["mode"] == "internal" and not result["fallback"]
    with fitz.open(result["path"]) as doc:
        assert doc.page_count == 3
        text = "".join(doc[0].get_text().split())
        assert "内部检测报告" in text and request["fields"]["sample_name"] in text
        assert all(value in text for value in ("12.345", "1.234", request["fields"]["TMA"]))
        assert len(doc[1].get_images()) and len(doc[2].get_images())
    assert all(path.read_bytes() == content for path, content in before.items())


def test_selected_template_keeps_layout_fills_unicode_and_numeric_values(sources, tmp_path):
    request, data = request_data(sources, tmp_path)
    template = ROOT / "power/W456.pdf"
    request["template_path"] = str(template)
    before = template.read_bytes()
    result = report.generate_report(request, data)
    assert result["mode"] == "template"
    with fitz.open(result["path"]) as doc:
        assert len(doc) == 3
        text = "".join(doc[0].get_text().split())
        assert request["fields"]["sample_name"] in text
        for key in report.TEMPLATE_KEYS:
            assert key not in text
        assert request["fields"]["T1"] in text and request["fields"]["TMA"] in text
        assert doc[1].get_images() and doc[2].get_images()
    assert template.read_bytes() == before


@pytest.mark.parametrize("kind", ["missing", "broken", "no_fields", "encrypted"])
def test_invalid_template_never_silently_falls_back(sources, tmp_path, kind):
    request, data = request_data(sources, tmp_path)
    template = tmp_path / "template.pdf"
    if kind == "broken":
        template.write_bytes(b"broken pdf")
    elif kind in ("no_fields", "encrypted"):
        with fitz.open() as doc:
            doc.new_page().insert_text((60, 60), "Not a compatible template")
            if kind == "encrypted":
                doc.save(template, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
            else:
                doc.save(template)
    request["template_path"] = str(template)
    with pytest.raises(report.TemplateError):
        report.generate_report(request, data)
    assert not Path(request["output_path"]).exists()


def test_template_runtime_failure_then_explicit_internal_fallback(sources, tmp_path, monkeypatch):
    request, data = request_data(sources, tmp_path)
    request["template_path"] = str(ROOT / "power/W456.pdf")
    def fail(*args, **kwargs):
        raise RuntimeError("test template save failure")
    monkeypatch.setattr(report.ReportTemplateEditor, "save", fail)
    with pytest.raises(report.TemplateError, match="模板填充失败"):
        report.generate_report(request, data)
    assert not Path(request["output_path"]).exists()
    result = report.generate_report(request, data, force_internal=True)
    assert result["fallback"] and result["mode"] == "internal"


def test_sources_are_protected_changed_input_rejected_and_cancel_does_not_commit(sources, tmp_path):
    request, data = request_data(sources, tmp_path)
    request["output_path"] = str(sources[1])
    before = sources[1].read_bytes()
    with pytest.raises(ValueError, match="覆盖"):
        report.generate_report(request, data)
    assert sources[1].read_bytes() == before
    request["output_path"] = str(tmp_path / "cancelled.pdf")
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ValueError, match="取消"):
        report.generate_report(request, data, cancelled=cancel)
    assert not Path(request["output_path"]).exists()
    sources[0].write_bytes(sources[0].read_bytes() + b"changed")
    with pytest.raises(ValueError, match="变化"):
        report.generate_report(request, data)


def make_p9m(path, sample, ambiguous=False):
    records = []
    for index in range(2):
        name = sample if ambiguous or index == 0 else "another sample"
        records.append(f'''<Record ID="{index+1}" D50="{12.3+index}" Span="{1.1+index}" D10="3" D90="25"
 MeasurementTime="2026-10-20T09:10:11" Tester="Test" InstrumentId="Test" SoftwareVersion="Test">
 <SopConfig SampleName="{name}" SampleSerialNumber="{name}" ResultType="Volume"/>
 <FrequencyDistributionList><Db ParticleSize="1" Distribution="0.1"/><Db ParticleSize="10" Distribution="0.8"/><Db ParticleSize="100" Distribution="0.1"/></FrequencyDistributionList>
 <UnderSizeCumulativeDistributionList><Db ParticleSize="1" Distribution="0.1"/><Db ParticleSize="10" Distribution="0.9"/><Db ParticleSize="100" Distribution="1"/></UnderSizeCumulativeDistributionList>
 </Record>''')
    plain = ("<Root>" + "".join(records) + "</Root>").encode("utf-8")
    pad = PKCS7(128).padder()
    padded = pad.update(plain) + pad.finalize()
    enc = Cipher(algorithms.AES(core._P9M_AES_KEY), modes.CBC(core._P9M_AES_IV)).encryptor()
    path.write_bytes(enc.update(padded) + enc.finalize())
    return path


def test_p9m_matching_ambiguous_selection_and_internal_particle_page(sources, tmp_path):
    p9m = make_p9m(tmp_path / "particle.p9m", sources[0].stem)
    particle = report.read_particle(p9m, sources[0].stem)
    assert particle["selected_index"] == 0 and particle["fields"]["D50"] == "12.300"
    assert particle["fields"]["particle_time"] == "2026-10-20 09:10:11"
    make_p9m(p9m, sources[0].stem, ambiguous=True)
    particle = report.read_particle(p9m, sources[0].stem)
    assert particle["selected_index"] is None and "请选择" in particle["warning"]
    request, data = request_data((sources[0], p9m, sources[2]), tmp_path)
    assert data["particle"]["selected_index"] is None
    with pytest.raises(ValueError, match="记录"):
        report.generate_report(request, data)
    selected = report.read_particle(p9m, sources[0].stem, 1)
    data["particle"] = selected
    data["fields"].update(selected["fields"])
    request["fields"] = dict(data["fields"])
    result = report.generate_report(request, data)
    assert result["values"]["lijing"] == "13.300"
    assert result["values"]["span"] == "2.100"
    with fitz.open(result["path"]) as doc:
        assert len(doc[2].get_images()) > 0


def test_pdf_horizontal_metric_columns_do_not_take_next_heading(tmp_path):
    path = tmp_path / "metrics.pdf"
    with fitz.open() as doc:
        page = doc.new_page()
        for x, label, value in ((70, "D10", "2.1"), (150, "D50", "12.345"), (230, "D90", "33.1"), (320, "SPAN", "1.234")):
            page.insert_text((x, 100), label)
            page.insert_text((x, 125), value)
        doc.save(path)
    result = report.read_particle(path)
    assert result["fields"] == {"D50": "12.345", "SPAN": "1.234"}


def test_v6_template_does_not_require_unused_span(sources, tmp_path):
    request, data = request_data(sources, tmp_path)
    request["fields"]["SPAN"] = ""
    with pytest.raises(ValueError, match="SPAN"):
        report.generate_report(request, data)
    request["template_path"] = str(ROOT / "power/W456.pdf")
    result = report.generate_report(request, data)
    assert result["mode"] == "template" and result["values"]["span"] == ""


def test_instrument_iso_and_invalid_calendar_dates():
    assert report.measurement_datetime("2026-10-20T09:10:11") == "2026-10-20 09:10:11"
    assert report.measurement_datetime("2026-10-20T01:10:11Z") == "2026-10-20 09:10:11"
    assert report.measurement_datetime("2026-02-31 09:10:11") == ""


def wait_until(callback, timeout=25000):
    deadline = time.monotonic() + timeout/1000
    while not callback() and time.monotonic() < deadline:
        QTest.qWait(10)
        time.sleep(.003)
    assert callback(), "Single report operation timed out"


@pytest.fixture
def ui(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = ClassicMainWindow()
    window.show()
    yield window
    dialog = getattr(window, "single_report_dialog", None)
    if dialog:
        dialog.shutdown()
        wait_until(lambda: dialog.job is None)
    window.dirty = False
    window.close()
    app.processEvents()


def fill_dialog(ui, sources, tmp_path, monkeypatch):
    monkeypatch.setenv("TMA_MASS_XLSX", str(sources[2]))
    dialog = ui.show_single_report()
    dialog.tma_path.setText(str(sources[0]))
    dialog.particle_path.setText(str(sources[1]))
    dialog.output_path.setText(str(tmp_path / "ui-report.pdf"))
    dialog.read_button.click()
    wait_until(lambda: dialog.job is None)
    return dialog


@pytest.mark.parametrize("accept", [False, True])
def test_ui_bad_template_asks_and_only_generates_if_fallback_accepted(ui, sources, tmp_path, monkeypatch, accept):
    dialog = fill_dialog(ui, sources, tmp_path, monkeypatch)
    assert dialog.fields["sample_name"].text() == sources[0].stem
    dialog.template_path.setText(str(tmp_path / "missing.pdf"))
    questions = []
    def answer(*args, **kwargs):
        questions.append(args[2])
        return QMessageBox.StandardButton.Yes if accept else QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "question", answer)
    dialog.generate_button.click()
    wait_until(lambda: dialog.job is None)
    assert len(questions) == 1 and "内部版" in questions[0]
    assert Path(dialog.output_path.text()).exists() == accept
    assert bool(dialog.last_output) == accept


def test_file_choosers_use_independent_saved_folders_and_settings_preserve_them(ui, sources, tmp_path, monkeypatch):
    tma_folder = tmp_path / "tma-folder"
    particle_dir = tmp_path / "particle-folder"
    save_paths({"m": "", "open_folder": str(tma_folder), "particle_folder": str(particle_dir)})
    dialog = ui.show_single_report()
    calls = []
    def choose(*args, **kwargs):
        calls.append(args[2])
        return "", ""
    monkeypatch.setattr(QFileDialog, "getOpenFileName", choose)
    from tma_app import data_file_dialog as picker
    def choose_data(parent,*args,owner=None,**kwargs):
        calls.append(picker.start_folder(owner or parent));return [],''
    monkeypatch.setattr(picker,'get_data_files',choose_data)
    dialog.choose_tma()
    dialog.choose_particle()
    assert calls == [str(tma_folder), str(particle_dir)]
    assert dialog.recommend_button.text() == "推荐数据"
    assert not hasattr(dialog, "choose_particle_folder")
    assert load_paths()["open_folder"] == str(tma_folder)
    settings = ui.show_path_settings()
    names = [settings.paths.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(settings.paths.rowCount())]
    assert names[:3] == ["m", "open_folder", "particle_folder"]
    settings.accept()
    assert particle_folder() == str(particle_dir)


def test_toolbar_button_and_close_while_reading_keep_window_responsive(ui, sources, monkeypatch):
    called = []
    original = report.read_sources
    def slow(*args, **kwargs):
        called.append(threading.get_ident())
        time.sleep(.15)
        return original(*args, **kwargs)
    monkeypatch.setattr(report, "read_sources", slow)
    ui.single_report_button.click()
    dialog = ui.single_report_dialog
    assert dialog.isVisible() and dialog.template_path.text() == ""
    dialog.tma_path.setText(str(sources[0]))
    started = time.monotonic()
    dialog.read_information()
    assert time.monotonic() - started < .1
    assert dialog.close() and not dialog.isVisible()
    wait_until(lambda: dialog.job is None)
    assert called and all(identity != threading.get_ident() for identity in called)
    assert ui.show_single_report() is dialog and dialog.isVisible()
