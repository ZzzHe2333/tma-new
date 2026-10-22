"""Opt-in persistence, lifecycle, cancellation and real SDK HTTP round trips."""
import asyncio
import json
from pathlib import Path
import socket
import threading
import time

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from test_point_interaction import ui
from tma_app import mcp_service as mcp
from tma_app import path_settings
from tma_app.mcp_qa import free_port, transport_checks, wait_running


def settings():
    return {"enabled": True, "port": free_port(), "token": mcp.new_token()}


def eventually(test, timeout=5):
    deadline = time.monotonic() + timeout
    while not test() and time.monotonic() < deadline:
        app = QApplication.instance()
        if app: app.processEvents()
        time.sleep(.01)
    assert test()


def test_default_disabled_and_settings_preserve_other_sections():
    assert mcp.load_settings() == {"enabled": False, "port": 18765, "token": ""}
    path_settings.save_paths({"m": "C:/weights.csv", "particle_folder": "D:/particles"})
    path_settings.save_batch_popup(False)
    value = settings()
    mcp.save_settings(value)
    path_settings.save_paths({"m": "C:/new.csv"})
    assert mcp.load_settings() == value
    assert path_settings.batch_popup_enabled() is False
    assert path_settings.load_paths()["m"] == "C:/new.csv"


@pytest.mark.parametrize("value", [
    {"enabled": "true", "port": 18765, "token": ""},
    {"enabled": False, "port": True, "token": ""},
    {"enabled": False, "port": 1023, "token": ""},
    {"enabled": False, "port": 65536, "token": ""},
    {"enabled": False, "port": 18765, "token": "short"},
    {"enabled": False, "port": 18765, "token": "a" * 24 + "\n"},
])
def test_config_validation(value):
    with pytest.raises(ValueError):
        mcp.save_settings(value)
    assert not path_settings.config_path().exists()


def test_real_http_official_client_batch_exports_and_port_reuse(tmp_path, monkeypatch):
    files = [Path("测试文件/20261013-9#.001").resolve(), Path("测试文件/20261014-7#.001").resolve()]
    sheet = tmp_path / "weights.csv"
    sheet.write_text(f"样品名,M (mg)\n{files[0].stem},0.47\n{files[1].stem},0.48\n", encoding="utf-8-sig")
    monkeypatch.setenv("TMA_MASS_XLSX", str(sheet))
    value = settings(); service = mcp.McpService()
    try:
        service.start(value); wait_running(service)
        checks, result = asyncio.run(transport_checks(value, files, tmp_path / "exports"))
        assert len(checks) == 8 and len(result["artifacts"]) == 5
    finally:
        service.stop()
    assert service.state == "stopped"
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", value["port"])) != 0
    service.start(value); wait_running(service); service.stop()


def test_port_conflict_does_not_leave_background_thread():
    value = settings()
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", value["port"])); occupied.listen()
        service = mcp.McpService()
        with pytest.raises(ValueError, match="端口"):
            service.start(value)
        assert service.state == "error" and service.thread is None
        service.stop()


@pytest.mark.parametrize("files,formats,directory", [
    ([], [], None), (["relative.001"], [], None), (["C:/input.txt"], [], None),
    (["C:/input.001"], ["pdf"], "C:/exports"),
    (["C:/input.001"], ["png"], "relative"),
    (["C:/input.001"] * 1001, [], None),
])
def test_invalid_job_inputs(files, formats, directory):
    jobs = mcp.BatchJobs()
    with pytest.raises(ValueError):
        jobs.submit(files, directory, formats)
    assert not jobs.jobs and jobs.worker is None


def test_cancel_queued_and_running_jobs_and_stop_prevents_exports(tmp_path, monkeypatch):
    from tma_app import batch_analysis as batch
    entered, release = threading.Event(), threading.Event()
    def calculate(file):
        entered.set(); release.wait(timeout=5)
        return {"file": file, "name": "source.001", "T1": 1, "T2": 2, "M": None, "H": 3, "error": "", "state": "完成"}
    monkeypatch.setattr(batch, "calculate_file", calculate)
    monkeypatch.setattr(batch, "match_mass", lambda row, source: row)
    writes = []
    monkeypatch.setattr(batch, "write_plot", lambda *args: writes.append(args))
    jobs = mcp.BatchJobs()
    first = jobs.submit([str(tmp_path / "source.001")], str(tmp_path / "out"), ["png"], "")
    assert entered.wait(timeout=3)
    second = jobs.submit([str(tmp_path / "source.001")], mass_source="")
    jobs.cancel(second["job_id"])
    assert jobs.status(second["job_id"])["state"] == "cancelled"
    jobs.shutdown(); release.set(); jobs.worker.join(timeout=3)
    assert jobs.status(first["job_id"])["state"] == "cancelled" and not writes
    with pytest.raises(ValueError, match="关闭"):
        jobs.submit([str(tmp_path / "source.001")])
    with pytest.raises(ValueError, match="不存在"):
        jobs.status("unknown")


def test_ui_default_copy_apply_close_and_restart_saved_config(ui, monkeypatch):
    notices = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: notices.append(args[-1]))
    ui.show_mcp_settings()
    dialog = ui.mcp_dialog
    assert not dialog.enabled.isChecked() and ui.mcp_service.state == "stopped"
    assert dialog.windowFlags() & Qt.WindowType.WindowCloseButtonHint
    dialog.copy_config()
    assert notices
    value = settings()
    dialog.port.setValue(value["port"]); dialog.enabled.setChecked(True)
    dialog.apply()
    wait_running(ui.mcp_service)
    saved = mcp.load_settings()
    assert saved["enabled"] and saved["token"] and saved["port"] == value["port"]
    dialog.copy_config()
    copied = json.loads(QApplication.clipboard().text())["mcpServers"]["zzzhe-tma"]
    assert copied["headers"]["Authorization"] == "Bearer " + saved["token"]
    assert saved["token"] not in dialog.preview.toPlainText()
    dialog.close()
    assert ui.mcp_service.state == "running"
    ui.mcp_service.stop()
    ui.start_saved_mcp(); wait_running(ui.mcp_service)
    ui.show_mcp_settings(); dialog.enabled.setChecked(False); dialog.apply()
    assert not mcp.load_settings()["enabled"] and ui.mcp_service.state == "stopped"


def test_app_close_stops_service_and_does_not_change_document(ui):
    value = settings(); mcp.save_settings(value)
    ui.start_saved_mcp(); wait_running(ui.mcp_service)
    curve = ui.selected()
    ui.dirty = False
    ui.close()
    assert ui.mcp_service.state == "stopped" and ui.selected() is curve
    ui.start_saved_mcp()
    assert ui.mcp_service.state == "stopped"  # A queued startup after close cannot reopen a port.


def test_saved_enabled_setting_autostarts_a_new_window(ui):
    from tma_app.classic import ClassicMainWindow
    value = settings(); mcp.save_settings(value)
    fresh = ClassicMainWindow()
    try:
        eventually(lambda: fresh.mcp_service.state == "running", timeout=25)
        assert fresh.mcp_service.port == value["port"]
    finally:
        fresh.dirty = False; fresh.close()
    assert fresh.mcp_service.state == "stopped"


def test_gui_timer_keeps_running_during_batch_job(ui, tmp_path, monkeypatch):
    from tma_app import batch_analysis as batch
    entered, release = threading.Event(), threading.Event()
    original = batch.calculate_file
    def slow(file):
        entered.set(); release.wait(timeout=3)
        return original(file)
    monkeypatch.setattr(batch, "calculate_file", slow)
    jobs = mcp.BatchJobs()
    value = jobs.submit([str(tmp_path / "absent.001")], mass_source="")
    assert entered.wait(timeout=2)
    ticks = []
    timer = QTimer(); timer.timeout.connect(lambda: ticks.append(True)); timer.start(10)
    try:
        eventually(lambda: len(ticks) >= 3)
        assert jobs.status(value["job_id"])["state"] == "running"
    finally:
        timer.stop(); jobs.shutdown(); release.set(); jobs.worker.join(timeout=3)
