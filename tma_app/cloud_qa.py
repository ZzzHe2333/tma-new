"""Isolated WebDAV fixture and frozen-application verification."""
from contextlib import contextmanager
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import sys
from pathlib import Path
import threading
import time
import traceback
from urllib.parse import quote, unquote, urlsplit
import uuid
from xml.etree import ElementTree as ET

from . import __version__


@contextmanager
def fixture_server(files=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def authorized(self):
            expected = "Basic " + base64.b64encode(b"fixture:fixture-password").decode()
            self.server.requests.append((self.command, self.path, dict(self.headers)))
            if self.headers.get("Authorization") != expected:
                self.send_response(401); self.end_headers(); return False
            return True

        def do_PROPFIND(self):
            if not self.authorized(): return
            directory = unquote(urlsplit(self.path).path).rstrip("/") + "/"
            if directory not in self.server.directories:
                self.send_response(404); self.end_headers(); return
            doc = ET.Element("{DAV:}multistatus")
            paths = [directory] + [p for p in [*self.server.directories, *self.server.files] if p != directory and p.startswith(directory) and "/" not in p[len(directory):].rstrip("/")]
            for path in [*paths, "/outside/unsafe.001", directory + "%2E%2E/unsafe.001"]:
                response = ET.SubElement(doc, "{DAV:}response")
                ET.SubElement(response, "{DAV:}href").text = quote(path, safe="/%")
                status = ET.SubElement(response, "{DAV:}propstat")
                ET.SubElement(status, "{DAV:}status").text = "HTTP/1.1 200 OK"
                prop = ET.SubElement(status, "{DAV:}prop")
                kind = ET.SubElement(prop, "{DAV:}resourcetype")
                if path.endswith("/"): ET.SubElement(kind, "{DAV:}collection")
                else: ET.SubElement(prop, "{DAV:}getcontentlength").text = str(len(self.server.files.get(path, b"")))
                ET.SubElement(prop, "{DAV:}getlastmodified").text = "Thu, 22 Oct 2026 01:00:00 GMT"
            data = ET.tostring(doc)
            self.send_response(207); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def do_GET(self):
            if not self.authorized(): return
            path = unquote(urlsplit(self.path).path)
            if path not in self.server.files:
                self.send_response(404); self.end_headers(); return
            data = self.server.files[path]; etag = '"' + hashlib.sha256(data).hexdigest() + '"'
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304); self.end_headers(); return
            self.send_response(200)
            self.send_header("ETag", etag)
            self.send_header("Content-Length", str(len(data) + (20 if path.endswith("broken.001") else 0)))
            self.end_headers(); self.wfile.write(data)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.files = {"/dav/" + path.lstrip("/"): data for path, data in (files or {}).items()}
    server.directories = {"/dav/"}
    for path in server.files:
        directory = path.rsplit("/", 1)[0] + "/"
        while directory.startswith("/dav/"):
            server.directories.add(directory)
            directory = directory.rstrip("/").rsplit("/", 1)[0] + "/"
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    server.url = f"http://127.0.0.1:{server.server_port}/dav/"
    try: yield server
    finally: server.shutdown(); server.server_close(); thread.join(timeout=2)


def verify_cloud(window, output, inputs):
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    from . import cloud_storage as cloud
    from .batch_analysis import calculate_file, match_mass, write_plot, write_xlsx
    from .reader import read_dataset
    from .cloud_schedule import task_xml
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"version": __version__, "status": "failed", "checks": []}
    previous = os.environ.get("LOCALAPPDATA")
    os.environ["LOCALAPPDATA"] = str(output.parent / ("isolated-" + uuid.uuid4().hex[:8]))
    window.start_cloud_maintenance = lambda **kwargs: None
    def wait(test):
        deadline = time.monotonic() + 25
        while not test() and time.monotonic() < deadline:
            QApplication.processEvents(); time.sleep(.01)
        assert test(), "云盘操作超时"
    try:
        source = inputs[0]; data = source.read_bytes()
        before = hashlib.sha256(data).hexdigest()
        weights = f"样品名,M (mg)\n{source.stem},0.47\n".encode("utf-8-sig")
        with fixture_server({"中文 空格/" + source.name: data, "mass.csv": weights}) as server:
            mount = {"id": uuid.uuid4().hex, "name": "WebDAV 测试", "url": server.url, "username": "fixture",
                     "password": cloud.protect_password("fixture-password"), "verify_tls": True}
            cloud.save_settings([mount], 72)
            assert "fixture-password" not in cloud.config_path().read_text(encoding="utf-8")
            assert cloud.settings()["retention_hours"] == 72
            report["checks"].append("mount_persistence_dpapi_password_default_72_hours")
            dialog = window.show_cloud(); dialog.browse(); wait(lambda: dialog.job is None)
            folder = next(e for e in dialog.entries if e["directory"])
            dialog.path.setText(folder["path"]); dialog.browse(); wait(lambda: dialog.job is None)
            assert len(dialog.entries) == 1 and dialog.entries[0]["name"] == source.name
            dialog.table.selectRow(0); dialog.download()
            wait(lambda: dialog.job is None and window.worker is None and len(window.curves) > 0)
            cached = window.curves[-1].dataset.path
            assert cached.read_bytes() == data and cached.name == source.name
            report["checks"].append("webdav_browser_unicode_multi_step_download_and_plot_import")
            uri = cloud.cloud_uri(mount["id"], "/中文 空格/" + source.name)
            row = match_mass(calculate_file(uri), cloud.cloud_uri(mount["id"], "/mass.csv"))
            assert row["M"] == .47 and not row["error"]
            export_dir = output.parent / "exports"; export_dir.mkdir(exist_ok=True)
            write_plot(row, export_dir / "cloud.png"); write_xlsx([row], export_dir / "cloud.xlsx")
            report["checks"].append("cloud_uri_batch_mass_lookup_png_and_numeric_xlsx")
            with cloud.database() as db: db.execute("UPDATE files SET last_used=? WHERE path=?", (time.time() - 80*3600, str(cached)))
            read_dataset(cached)
            assert cloud.cleanup(force=True)["deleted"] == 0 and cached.is_file()
            report["checks"].append("reopen_renews_sliding_expiry")
            with cloud.database() as db: db.execute("UPDATE files SET last_used=? WHERE path=?", (time.time() - 80*3600, str(cached)))
            assert cloud.cleanup(force=True)["deleted"] == 1 and not cached.exists()
            assert read_dataset(cached).sha256 == before and cached.is_file()
            report["checks"].append("expired_cache_deleted_and_original_cloud_source_redownloaded")
            dialog.hours.setValue(120); dialog.save_retention()
            assert cloud.settings()["retention_hours"] == 120
            assert b"--cloud-cleanup" in task_xml().decode("utf-16").encode()
            assert b"--cloud-config-folder" in task_xml().decode("utf-16").encode()
            report["checks"].append("editable_retention_and_headless_daily_cleanup_action")
            assert all(method in ("PROPFIND", "GET") for method, _, _ in server.requests)
            assert source.read_bytes() == data and server.files["/dav/中文 空格/" + source.name] == data
            report["checks"].append("local_source_and_remote_files_unchanged_read_only_requests")
            dialog.grab().save(str(output.with_suffix(".window.png")))
            dialog.close()
        report["status"] = "passed"
    except BaseException:
        report["error"] = traceback.format_exc()
    finally:
        window.dirty = False; window.close()
        if previous is None: os.environ.pop("LOCALAPPDATA", None)
        else: os.environ["LOCALAPPDATA"] = previous
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def verify_scheduled_cleanup(output):
    """Install/run/remove an isolated real task from inside the shipped EXE."""
    import subprocess
    from . import cloud_storage as cloud
    from .cloud_schedule import install_daily_task, task_name, task_xml
    output = Path(output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    previous = os.environ.get("LOCALAPPDATA")
    os.environ["LOCALAPPDATA"] = str(output.parent / ("schedule-" + uuid.uuid4().hex[:8]))
    report = {"version": __version__, "status": "failed"}
    created = False
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        with fixture_server({"owned.001": b"owned frozen scheduled cleanup fixture"}) as server:
            mount = {"id": uuid.uuid4().hex, "name": "QA only", "url": server.url, "username": "fixture",
                     "password": cloud.protect_password("fixture-password")}
            cloud.save_settings([mount])
            source = cloud.fetch(mount["id"], "/owned.001")
            with cloud.database() as db:
                db.execute("UPDATE files SET last_used=?", (time.time()-80*3600,))
            registration = install_daily_task()
            report["registration"] = registration
            if not registration["installed"]:
                output.with_suffix('.task.xml').write_bytes(task_xml())
                identity = subprocess.run(['whoami.exe', '/groups'], capture_output=True, timeout=15, creationflags=flags)
                report['identity'] = identity.stdout.decode('mbcs', errors='replace')
            if not registration["installed"]: raise ValueError(registration["message"])
            created = True
            subprocess.run(["schtasks.exe", "/Run", "/TN", task_name()], check=True, capture_output=True,
                           timeout=15, creationflags=flags)
            deadline = time.monotonic() + 40
            result_path = cloud.root() / "cleanup-last.json"
            while not result_path.exists() and time.monotonic() < deadline: time.sleep(.1)
            if not result_path.exists(): raise ValueError("计划任务在验证时限内未产出清理结果")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            assert result["status"] == "passed" and result["deleted"] == 1 and not source.exists(), result
            report.update(status="passed", cleanup=result, configuration_isolated=True,
                          executable_action=bool(getattr(sys, 'frozen', False)))
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if created:
            subprocess.run(["schtasks.exe", "/End", "/TN", task_name()], capture_output=True, timeout=15, creationflags=flags)
            removed = subprocess.run(["schtasks.exe", "/Delete", "/TN", task_name(), "/F"], capture_output=True,
                                     timeout=15, creationflags=flags)
            report["temporary_task_removed"] = removed.returncode == 0
        if previous is None: os.environ.pop("LOCALAPPDATA", None)
        else: os.environ["LOCALAPPDATA"] = previous
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
