import hashlib
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from xml.etree import ElementTree as ET

import httpx
import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication
from test_point_interaction import ui
from tma_app import cloud_storage as cloud
from tma_app.cloud_qa import fixture_server
from tma_app.cloud_schedule import task_xml
from tma_app.reader import read_dataset


@pytest.fixture
def dav():
    source = Path("测试文件/20261013-9#.001")
    with fixture_server({"中文 空格/" + source.name: source.read_bytes(), "mass.csv": f"样品名,M (mg)\n{source.stem},.47\n".encode("utf-8-sig"),
                         "broken.001": b"incomplete"}) as server:
        profile = {"id": "a"*32, "name": "测试云盘", "url": server.url, "username": "fixture", "password": cloud.protect_password("fixture-password"), "verify_tls": True}
        cloud.save_settings([profile])
        yield server, profile, "/中文 空格/" + source.name


def age(path, hours):
    with cloud.database() as db: db.execute("UPDATE files SET last_used=?,lease_until=0 WHERE path=?", (time.time() - hours*3600, str(path)))


def wait(test, timeout=20):
    deadline = time.monotonic() + timeout
    while not test() and time.monotonic() < deadline:
        QApplication.processEvents(); time.sleep(.01)
    assert test()


def test_defaults_password_encrypted_and_other_settings_preserved(dav):
    from tma_app import path_settings
    _, profile, _ = dav
    path_settings.save_paths({"m": "C:/weights.csv"})
    path_settings.save_batch_popup(False)
    cloud.save_settings([profile], 96)
    text = cloud.config_path().read_text(encoding="utf-8")
    assert "fixture-password" not in text and "dpapi:" in text
    assert cloud.protect_password(cloud.settings()["mounts"][0]["password"], True) == "fixture-password"
    assert path_settings.load_paths()["m"] == "C:/weights.csv" and not path_settings.batch_popup_enabled()
    assert cloud.settings()["retention_hours"] == 96


@pytest.mark.parametrize("hours", [0, -1, 87601, True, "72", float("nan")])
def test_retention_validation(hours):
    with pytest.raises(ValueError): cloud.save_settings([], hours)


@pytest.mark.parametrize("url", ["file:///C:/data", "https://user:password@example.com/dav/", "https://example.com/../", "https://example.com/dav/?key=secret", "https://example.com:wrong/dav/"])
def test_bad_mount_urls(url):
    with pytest.raises(ValueError): cloud.normalize_url(url)


def test_href_default_port_equivalence_and_https_downgrade_rejected():
    profile = {"id": "b"*32, "name": "fixture", "url": "https://example.com/dav/"}
    dav = cloud.WebDAV(profile)
    assert dav.relative("https://example.com:443/dav/sample.001", dav.base) == "/sample.001"
    def handler(request):
        return httpx.Response(302, headers={"Location": "http://cdn.example/file"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="重定向"):
            with dav.request(client, "GET", dav.url("/sample.001")): pass


def test_webdav_depth_one_unicode_paths_auth_and_scope(dav):
    server, profile, remote = dav
    client = cloud.WebDAV(profile)
    listing = client.list("/")
    assert {e["name"] for e in listing} == {"中文 空格", "mass.csv", "broken.001"}
    inside = client.list("/中文 空格")
    assert inside[0]["path"] == remote and not inside[0]["directory"]
    assert all(headers.get("Depth") == "1" for method, _, headers in server.requests if method == "PROPFIND")
    wrong = {**profile, "password": cloud.protect_password("wrong")}
    with pytest.raises(ValueError, match="登录失败"): cloud.WebDAV(wrong).list()


def test_download_etag_revalidation_and_refresh_after_remote_change(dav):
    server, profile, remote = dav
    path = cloud.fetch(profile["id"], remote)
    assert path.name == Path(remote).name and cloud.cache_root() in path.parents
    old = path.read_bytes(); timestamp = cloud.cached_record(path)["last_used"]
    cloud.fetch(profile["id"], remote, refresh=True)
    assert any("If-None-Match" in headers for method, _, headers in server.requests if method == "GET")
    assert cloud.cached_record(path)["last_used"] >= timestamp
    server.files["/dav" + remote] = b"new version"
    cloud.fetch(profile["id"], remote, refresh=True)
    assert path.read_bytes() == b"new version" and old != path.read_bytes()


def test_repeated_use_renews_expiry_and_custom_hours_take_effect(dav):
    _, profile, remote = dav
    path = cloud.fetch(profile["id"], remote); age(path, 80)
    before = cloud.cached_record(path)["last_used"]
    read_dataset(path)
    assert cloud.cached_record(path)["last_used"] > before
    assert cloud.cleanup(force=True)["deleted"] == 0
    age(path, 80); cloud.save_settings([profile], 96)
    assert cloud.cleanup(force=True)["deleted"] == 0
    cloud.save_settings([profile], 72)
    assert cloud.cleanup(force=True)["deleted"] == 1 and not path.exists()
    assert cloud.resolve_source(path).is_file()


def test_cleanup_strict_boundary_daily_due_active_lease_and_safe_index(dav, tmp_path):
    _, profile, remote = dav
    path = cloud.fetch(profile["id"], remote)
    now = time.time()
    with cloud.database() as db: db.execute("UPDATE files SET last_used=?,lease_until=0", (now - 72*3600,))
    assert cloud.cleanup(force=True, now=now)["deleted"] == 0
    assert cloud.cleanup(now=now+1).get("not_due")
    with cloud.database() as db: db.execute("UPDATE files SET lease_until=?", (now+3600,))
    assert cloud.cleanup(force=True, now=now+1)["deleted"] == 0
    outside = tmp_path / "ordinary.001"; outside.write_bytes(b"keep")
    with cloud.database() as db: db.execute("UPDATE files SET path=?,lease_until=0", (str(outside),))
    result = cloud.cleanup(force=True, now=now+2)
    assert result["skipped"] == 1 and outside.read_bytes() == b"keep" and path.exists()


def test_incomplete_and_cancelled_download_never_publish_partial(dav):
    _, profile, _ = dav
    with pytest.raises(ValueError, match="下载失败"): cloud.fetch(profile["id"], "/broken.001")
    assert not list(cloud.cache_root().rglob("*.part"))
    cancelled = threading.Event(); cancelled.set()
    with pytest.raises(ValueError, match="取消"): cloud.fetch(profile["id"], "/mass.csv", cancelled=cancelled)
    assert not list(cloud.cache_root().rglob("*.part"))
    assert cloud.cache_stats()["files"] == 0


def test_old_crash_partial_removed_without_removing_recent_file(dav):
    _, profile, remote = dav
    path = cloud.fetch(profile["id"], remote)
    partial = path.parent / "download-crash.part"; partial.write_bytes(b"orphan")
    old = time.time() - 80*3600; os.utime(partial, (old, old))
    result = cloud.cleanup(force=True)
    assert result["deleted"] == 0 and path.is_file() and not partial.exists()


def test_new_file_is_not_deleted_if_only_plain_local_file_is_used(tmp_path):
    path = tmp_path / "local.001"; path.write_bytes(b"keep")
    assert not cloud.touch_path(path)
    assert not (cloud.root() / "cache.sqlite3").exists()
    assert cloud.cleanup(force=True)["deleted"] == 0 and path.read_bytes() == b"keep"


def test_cloud_uri_batch_mass_and_history_reexport_redownload(dav, tmp_path):
    from tma_app.batch_analysis import calculate_file, match_mass, history_snapshot, write_plot, write_xlsx
    from tma_app.mcp_service import BatchJobs
    _, profile, remote = dav
    uri = cloud.cloud_uri(profile["id"], remote)
    row = match_mass(calculate_file(uri), cloud.cloud_uri(profile["id"], "/mass.csv"))
    assert row["T1"] < row["T2"] and row["M"] == .47 and not row["error"]
    cached = Path(row["file"]); age(cached, 80); assert cloud.cleanup(force=True)["deleted"] == 1
    write_plot(history_snapshot([row])[0], tmp_path / "again.png")
    assert cached.exists() and (tmp_path / "again.png").exists()
    age(cached, 80); write_xlsx([row], tmp_path / "again.xlsx")
    assert cloud.cleanup(force=True)["deleted"] == 0
    jobs = BatchJobs()
    submitted = jobs.submit([uri, uri], mass_source=cloud.cloud_uri(profile["id"], "/mass.csv"))
    try:
        deadline = time.monotonic() + 15
        while jobs.status(submitted["job_id"])["state"] not in ("completed", "failed") and time.monotonic() < deadline: time.sleep(.02)
        result = jobs.status(submitted["job_id"])
        assert result["state"] == "completed" and len(result["rows"]) == 2
        assert all(row["M"] == .47 for row in result["rows"])
    finally: jobs.shutdown()


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_cdn_redirect_does_not_forward_mount_auth_or_cookies(dav, scheme):
    _, profile, remote = dav
    seen = []
    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(302, headers={"Location": scheme + "://cdn.example/signed?key=fixture"})
        return httpx.Response(200, content=b"sample")
    dav = cloud.WebDAV(profile)
    with httpx.Client(transport=httpx.MockTransport(handler), auth=("fixture", "secret"), cookies={"secret": "cookie"}) as client:
        with dav.request(client, "GET", dav.url(remote)) as response: assert response.read() == b"sample"
    assert "Authorization" in seen[0].headers
    assert "Authorization" not in seen[1].headers and "Cookie" not in seen[1].headers


def test_unavailable_cloud_template_keeps_fallback_error_class(dav, monkeypatch):
    from tma_app import single_report as report
    _, profile, _ = dav
    request = {"tma_path": "", "particle_path": "", "template_path": cloud.cloud_uri(profile["id"], "/missing.pdf")}
    with pytest.raises(report.TemplateError, match="不存在"):
        report.generate_report(request, {})


def test_headless_cleanup_cli_and_daily_task_scope(dav):
    _, profile, remote = dav
    path = cloud.fetch(profile["id"], remote); age(path, 80)
    folder = cloud.config_path().parent
    subprocess.run([sys.executable, "run.py", "--cloud-cleanup", "--cloud-config-folder", str(folder)], check=True, timeout=15)
    assert not path.exists()
    document = ET.fromstring(task_xml()); ns = {"s": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert document.findtext("s:Triggers/s:CalendarTrigger/s:ScheduleByDay/s:DaysInterval", namespaces=ns) == "1"
    args = document.findtext("s:Actions/s:Exec/s:Arguments", namespaces=ns)
    assert "--cloud-cleanup" in args and str(folder.resolve()) in args
    assert document.findtext("s:Settings/s:StartWhenAvailable", namespaces=ns) == "true"
    assert Path(document.findtext("s:Actions/s:Exec/s:WorkingDirectory", namespaces=ns)) == Path(__file__).resolve().parents[1]


def test_frozen_daily_task_sets_executable_folder_even_with_spaces(tmp_path, monkeypatch):
    from tma_app import cloud_schedule
    executable = tmp_path / "folder with spaces" / "ZzzHe TMA Analysis.exe"
    monkeypatch.setattr(cloud_schedule.sys, "frozen", True, raising=False)
    monkeypatch.setattr(cloud_schedule.sys, "executable", str(executable))
    document = ET.fromstring(task_xml())
    ns = {"s": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert document.findtext("s:Actions/s:Exec/s:Command", namespaces=ns) == str(executable)
    assert document.findtext("s:Actions/s:Exec/s:WorkingDirectory", namespaces=ns) == str(executable.parent.resolve())


def test_cloud_ui_browse_download_import_retention_and_close(ui, dav, monkeypatch):
    _, _, _ = dav
    monkeypatch.setattr(ui, "ensure_cloud_schedule", lambda: None)
    dialog = ui.show_cloud(); dialog.browse(); wait(lambda: dialog.job is None)
    assert dialog.windowFlags() & Qt.WindowType.WindowCloseButtonHint
    assert dialog.width() == 880 and dialog.height() == 620
    entry = next(e for e in dialog.entries if e["directory"])
    dialog.path.setText(entry["path"]); dialog.browse(); wait(lambda: dialog.job is None)
    count = len(ui.curves)
    dialog.table.selectRow(0); dialog.copy_uri()
    assert QApplication.clipboard().text().startswith("cloud://")
    dialog.download(); wait(lambda: dialog.job is None and ui.worker is None and len(ui.curves) > count)
    dialog.hours.setValue(120); dialog.save_retention()
    assert cloud.settings()["retention_hours"] == 120
    assert ui.curves[-1].dataset.path.is_file()
    dialog.close(); assert not dialog.isVisible()
