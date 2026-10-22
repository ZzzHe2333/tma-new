"""Exercise the report window against the user's real monthly dataset read-only."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
import uuid

from PySide6.QtWidgets import QApplication, QPushButton
from . import __version__
from .batch_qa import wait_until
from .path_settings import save_paths


def verify_recommendation(window, output, inputs):
    output = output.resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    previous = {key: os.environ.get(key) for key in ("LOCALAPPDATA", "TMA_MASS_XLSX")}
    os.environ["LOCALAPPDATA"] = str(output.parent / ("config-" + uuid.uuid4().hex[:8]))
    os.environ["TMA_MASS_XLSX"] = ""
    report = {"status": "failed", "version": __version__, "checks": []}
    parser = None; backend = None
    try:
        tma, dataset = inputs
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
        save_paths({"m": "", "particle_folder": str(dataset.parent / "2020-2028")})
        window.import_files([tma], synchronous=True, batch_results=False)
        QApplication.processEvents()
        assert window.batch_processing_button.size() == window.single_report_button.size()
        assert window.single_report_button.width() == 112
        window.batch_processing_button.click(); assert window.batch_dialog.isVisible(); window.batch_dialog.close()
        report["checks"].append("equal_size_112x24_batch_and_report_toolbar_buttons")
        assert "tma_app.single_report" not in sys.modules
        started = time.perf_counter(); dialog = window.show_single_report()
        report["window_open_ms"] = round((time.perf_counter() - started) * 1000, 2)
        assert "tma_app.single_report" not in sys.modules
        assert dialog.findChild(QPushButton, "ReportParticleFolder") is None
        assert dialog.recommend_button.text() == "推荐数据"
        report["checks"].append("report_shell_shown_without_loading_report_backend")
        dialog.use_selected(); wait_until(lambda: dialog.job is None)
        from . import single_report as backend
        backend.clear_particle_cache(); parser = backend.core._p9m_parse_records
        calls = []
        def counted(path): calls.append(path); return parser(path)
        backend.core._p9m_parse_records = counted
        timings = []
        for sample in ("20261017-5#", "20261017-5", "2026101705"):
            dialog.fields["sample_name"].setText(sample)
            started = time.perf_counter(); dialog.recommend_button.click()
            wait_until(lambda: dialog.job is None)
            timings.append(round((time.perf_counter() - started)*1000, 2))
            particle = dialog.data["particle"]
            assert particle and Path(particle["file"]).resolve() == dataset.resolve(), dialog.log.toPlainText()
            assert len(particle["matched_indices"]) == 4 and particle["records"][particle["selected_index"]].is_average
            assert dialog.fields["D50"].text() == "34.841" and dialog.fields["SPAN"].text() == "1.064"
        assert len(calls) == 1
        report.update(recommendation_ms=timings, dataset_parse_count=len(calls), matched_records=4,
                      average_D50="34.841", average_SPAN="1.064")
        report["checks"].append("three_date_id_aliases_match_real_month_file_and_unique_average")
        report["checks"].append("p9m_parsed_once_across_recommendation_and_record_changes")
        particle = dialog.data["particle"]
        nonaverage = next(i for i in particle["matched_indices"] if not particle["records"][i].is_average)
        dialog.record_box.setCurrentIndex(dialog.record_box.findData(nonaverage))
        wait_until(lambda: dialog.job is None)
        assert dialog.fields["D50"].text() == backend.core._p9m_n3(particle["records"][nonaverage].d50) and len(calls) == 1
        report["checks"].append("matched_record_list_allows_manual_override_without_reparse")
        dialog.grab().save(str(output.with_suffix(".window.png")))
        window.grab().save(str(output.with_suffix(".toolbar.png")))
        assert all(hashlib.sha256(p.read_bytes()).hexdigest() == before[str(p)] for p in inputs)
        report["checks"].append("tma_and_original_p9m_hashes_unchanged")
        report["status"] = "passed"
    except BaseException:
        report["error"] = traceback.format_exc()
    finally:
        if parser: backend.core._p9m_parse_records = parser
        window.dirty = False; window.close()
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
