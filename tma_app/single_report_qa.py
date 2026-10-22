"""Packaged report UI verification; all output/config stays in the report folder."""
import csv
import hashlib
import json
import os
from pathlib import Path
import traceback
import uuid

import fitz
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from . import __version__
from .batch_qa import wait_until
from .path_settings import save_paths
from . import single_report as backend


def _test_p9m(path, name):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7
    records = []
    for index in range(2):
        records.append(f'''<Record ID="{index+1}" D50="{12.3+index}" Span="{1.1+index}" D10="3" D90="25"
 MeasurementTime="2026-10-20T09:10:11" Tester="Test fixture" InstrumentId="Test" SoftwareVersion="Test">
 <SopConfig SampleName="{name}" SampleSerialNumber="{name}" ResultType="Volume"/>
 <FrequencyDistributionList><Db ParticleSize="1" Distribution="0.1"/><Db ParticleSize="10" Distribution="0.8"/><Db ParticleSize="100" Distribution="0.1"/></FrequencyDistributionList>
 <UnderSizeCumulativeDistributionList><Db ParticleSize="1" Distribution="0.1"/><Db ParticleSize="10" Distribution="0.9"/><Db ParticleSize="100" Distribution="1"/></UnderSizeCumulativeDistributionList>
 </Record>''')
    plain = ("<Root>" + "".join(records) + "</Root>").encode("utf-8")
    padder = PKCS7(128).padder()
    padded = padder.update(plain) + padder.finalize()
    enc = Cipher(algorithms.AES(backend.core._P9M_AES_KEY), modes.CBC(backend.core._P9M_AES_IV)).encryptor()
    path.write_bytes(enc.update(padded) + enc.finalize())


def verify_single_report(window, output, paths):
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"status": "failed", "version": __version__, "checks": []}
    previous = {key: os.environ.get(key) for key in ("LOCALAPPDATA", "TMA_MASS_XLSX")}
    os.environ["LOCALAPPDATA"] = str(output.parent / (output.stem + "-config-" + uuid.uuid4().hex[:8]))
    picker = QFileDialog.getOpenFileName
    question = QMessageBox.question
    try:
        if len(paths) != 3:
            raise ValueError("报告验证需要 TMA 文件、粒径 PDF、模板 PDF 三个输入")
        tma, particle, template = [p.resolve() for p in paths]
        original = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (tma, particle, template)}
        mass = output.with_suffix(".mass.csv")
        with mass.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["样品名", "M (mg)"])
            writer.writerow([tma.stem, .47])
        os.environ["TMA_MASS_XLSX"] = str(mass)
        save_paths({"m": str(mass), "open_folder": str(tma.parent), "particle_folder": str(particle.parent)})
        window.single_report_button.click()
        dialog = window.single_report_dialog
        assert dialog.isVisible() and dialog.template_path.text() == ""
        choices = iter((str(tma), str(particle)))
        directories = []
        def pick(*args, **kwargs):
            directories.append(args[2])
            return next(choices), ""
        QFileDialog.getOpenFileName = staticmethod(pick)
        dialog.choose_tma()
        wait_until(lambda: dialog.job is None)
        dialog.choose_particle()
        wait_until(lambda: dialog.job is None)
        assert directories == [str(tma.parent), str(particle.parent)]
        assert dialog.fields["sample_name"].text() == tma.stem
        assert dialog.fields["M"].text() == "0.4700"
        assert dialog.fields["D50"].text() and dialog.fields["SPAN"].text()
        report["checks"].append("toolbar_window_independent_saved_folders_and_automatic_reading")
        outputs = []
        def generate(label):
            path = output.with_suffix("." + label + ".pdf")
            dialog.output_path.setText(str(path))
            dialog.generate_button.click()
            wait_until(lambda: dialog.job is None)
            assert path.is_file(), dialog.log.toPlainText()
            with fitz.open(path) as doc:
                assert doc.page_count == 3
                assert doc[1].get_images() and doc[2].get_images()
                text = "".join(doc[0].get_text().split())
                assert tma.stem in text
                assert dialog.fields["T1"].text() in text
                for index, page in enumerate(doc):
                    page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2), alpha=False).save(output.with_suffix(f".{label}.page{index+1}.png"))
            outputs.append(str(path))
            return text
        assert "内部检测报告" in generate("internal")
        dialog.grab().save(str(output.with_suffix(".window.png")))
        report["checks"].append("blank_template_uses_internal_three_page_layout")
        dialog.template_path.setText(str(template))
        text = generate("template")
        assert not any(key in text for key in backend.TEMPLATE_KEYS)
        report["checks"].append("selected_v6_template_filled_and_three_pages_preserved")
        questions = []
        def decline(*args, **kwargs):
            questions.append(args[2])
            return QMessageBox.StandardButton.No
        QMessageBox.question = staticmethod(decline)
        dialog.template_path.setText(str(output.with_suffix(".missing-template.pdf")))
        cancelled_output = output.with_suffix(".declined.pdf")
        dialog.output_path.setText(str(cancelled_output))
        dialog.generate_button.click()
        wait_until(lambda: dialog.job is None)
        assert len(questions) == 1 and not cancelled_output.exists()
        QMessageBox.question = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
        assert "内部检测报告" in generate("fallback")
        report["checks"].append("invalid_template_asks_decline_writes_nothing_accept_uses_internal")
        p9m = output.with_suffix(".particle-test.p9m")
        _test_p9m(p9m, tma.stem)
        dialog.template_path.clear()
        dialog.particle_path.setText(str(p9m))
        dialog.read_information(parts=("particle",))
        wait_until(lambda: dialog.job is None)
        assert dialog.record_box.count() == 3 and dialog.record_box.currentData() is None
        dialog.record_box.setCurrentIndex(2)
        wait_until(lambda: dialog.job is None)
        assert dialog.fields["D50"].text() == "13.300" and dialog.fields["SPAN"].text() == "2.100"
        assert "13.300" in generate("p9m")
        dialog.grab().save(str(output.with_suffix(".p9m-window.png")))
        report["checks"].append("p9m_record_selection_and_direct_three_page_generation")
        old_pdf = Path(dialog.last_output)
        old_pdf_hash = hashlib.sha256(old_pdf.read_bytes()).hexdigest()
        dialog.record_box.setCurrentIndex(0)
        assert dialog.data["particle"]["selected_index"] is None
        assert all(not dialog.fields[key].text() for key in ("D50", "SPAN", "particle_time"))
        assert not dialog.last_output and not dialog.open_button.isEnabled()
        dialog.generate_button.click()
        wait_until(lambda: dialog.job is None)
        assert hashlib.sha256(old_pdf.read_bytes()).hexdigest() == old_pdf_hash
        assert "请选择" in dialog.log.toPlainText()
        report["checks"].append("unselected_p9m_record_clears_numbers_and_blocks_stale_pdf")
        dialog.record_box.setCurrentIndex(1)
        wait_until(lambda: dialog.job is None)
        _test_p9m(p9m, tma.stem + "-changed")
        stamp = p9m.stat().st_mtime_ns + 10000000
        os.utime(p9m, ns=(stamp, stamp))
        dialog.record_box.setCurrentIndex(2)
        wait_until(lambda: dialog.job is None)
        assert dialog.data["particle"]["selected_index"] is None
        assert dialog.record_box.currentData() is None
        assert not dialog.fields["D50"].text() and "已更新" in dialog.log.toPlainText()
        report["checks"].append("changed_p9m_revision_requires_fresh_record_selection")
        assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == value for p, value in original.items())
        report["checks"].append("tma_particle_and_template_inputs_unchanged")
        report.update(status="passed", outputs=outputs, internal_source_sha256=backend.core.SOURCE_SHA256)
    except Exception as exc:
        report.update(error=str(exc), traceback=traceback.format_exc())
        raise
    finally:
        QFileDialog.getOpenFileName = picker
        QMessageBox.question = question
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        window.dirty = False
        window.close()
        window.single_report_dialog = None
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
