"""Local-only end-to-end sharing verification for source and frozen releases."""
from __future__ import annotations

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
import threading
import tempfile
import time
import traceback
from urllib.parse import unquote
import uuid

import httpx
from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, Qt

from . import __version__, cloud_storage as cloud, sharing
from .batch_qa import wait_until
from .reader import read_dataset


def _verify_preparation(window, expected, report):
    from . import path_settings
    from .classic import ClassicMainWindow
    read, protect, temporary, deliver = (path_settings._read_settings, window.protect_output,
        tempfile.TemporaryDirectory, sharing.share_job)
    entered, release = threading.Event(), threading.Event()
    ticks, reads, deliveries = [], [], []
    timer = QTimer(); timer.timeout.connect(lambda: ticks.append(1)); timer.start(5)
    dialog = fresh = None
    def forbidden(*args, **kwargs): raise AssertionError('Share attempted temporary/source I/O')
    def blocked(*args, **kwargs):
        assert threading.current_thread() is not threading.main_thread()
        reads.append(1); entered.set(); assert release.wait(15)
        return read(*args, **kwargs)
    try:
        wait_until(lambda: not window._startup_services_pending)
        window.protect_output = forbidden; tempfile.TemporaryDirectory = forbidden
        path_settings._read_settings = blocked
        started = time.perf_counter(); dialog = window.show_share()
        report['share_window_with_blocked_config_seconds'] = time.perf_counter() - started
        assert report['share_window_with_blocked_config_seconds'] < .5
        wait_until(entered.is_set); wait_until(lambda: bool(dialog.png))
        from io import BytesIO
        from PIL import Image
        from .image_provenance import verify_image
        with Image.open(BytesIO(dialog.png)) as actual, Image.open(BytesIO(expected)) as reference:
            assert actual.size == reference.size
            assert actual.convert('RGBA').tobytes() == reference.convert('RGBA').tobytes()
        assert verify_image(BytesIO(dialog.png))['status'] == 'verified'
        baseline = len(ticks); wait_until(lambda: len(ticks) >= baseline + 8)
        assert not dialog.send_button.isEnabled()
        worker = dialog._configuration_job.thread
        started = time.perf_counter(); dialog.close()
        assert time.perf_counter() - started < .5 and not dialog.isVisible()
        release.set(); wait_until(lambda: not worker.is_alive())
        QApplication.processEvents()
        assert not dialog.isVisible() and not dialog.send_button.isEnabled()
        report['checks'].append('share_snapshot_matches_export_without_source_resolution_or_temp_files_blocked_config_keeps_gui_alive_close_ignores_late_load')

        path_settings._read_settings = read
        tempfile.TemporaryDirectory = temporary; window.protect_output = protect
        sharing.share_job = lambda *args: deliveries.append(args)
        dialog = window.show_share(); wait_until(dialog.send_button.isEnabled)
        entered.clear(); release.clear(); reads.clear()
        path_settings._read_settings = blocked
        started = time.perf_counter(); dialog.send(); dialog.send()
        report['enqueue_share_while_config_blocked_seconds'] = time.perf_counter() - started
        assert report['enqueue_share_while_config_blocked_seconds'] < .5
        wait_until(entered.is_set)
        baseline = len(ticks); wait_until(lambda: len(ticks) >= baseline + 8)
        assert dialog.preparing and dialog.busy and len(reads) == 1 and not deliveries
        worker = dialog._preparation_job.thread
        dialog.close(); assert not dialog.isVisible()
        release.set(); wait_until(lambda: not worker.is_alive())
        QApplication.processEvents(); assert not deliveries
        report['checks'].append('send_configuration_check_is_background_duplicate_click_coalesces_cancelled_preparation_never_sends')

        path_settings._read_settings = read
        fresh = ClassicMainWindow(); fresh.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        fresh.start_cloud_maintenance = lambda **kwargs: None
        fresh.show(); wait_until(lambda: not fresh._startup_services_pending)
        fresh.finish_import([c.dataset for c in window.visible_curves()], [])
        dialog = fresh.show_share(); wait_until(dialog.send_button.isEnabled)
        entered.clear(); release.clear(); reads.clear()
        path_settings._read_settings = blocked
        dialog.send(); wait_until(entered.is_set)
        worker = dialog._preparation_job.thread
        started = time.perf_counter(); fresh.close()
        report['close_during_share_preparation_seconds'] = time.perf_counter() - started
        assert report['close_during_share_preparation_seconds'] < .5 and not dialog.isVisible()
        release.set(); wait_until(lambda: not worker.is_alive())
        QApplication.processEvents(); assert not deliveries
        report['checks'].append('closing_main_window_cancels_share_preparation_without_late_network_send')
        report['share_preparation_gui_heartbeats'] = len(ticks)
    finally:
        release.set(); timer.stop()
        path_settings._read_settings = read; window.protect_output = protect
        tempfile.TemporaryDirectory, sharing.share_job = temporary, deliver
        if dialog is not None: dialog.close()
        if fresh is not None: fresh.close()


def verify(window, output, paths):
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'version': __version__, 'status': 'failed', 'checks': []}
    original_appdata = os.environ.get('LOCALAPPDATA')
    original_client = httpx.Client
    original_maintenance = window.start_cloud_maintenance
    window.start_cloud_maintenance = lambda **kwargs: None
    server = None
    os.environ['LOCALAPPDATA'] = str(output.parent / ('sharing-fixture-' + uuid.uuid4().hex[:8]))
    try:
        if not paths: raise ValueError('需要一个测试样品')
        before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        uploaded = {}; webhooks = []; auth_headers = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_MKCOL(self):
                self.send_response(201); self.send_header('Content-Length', '0'); self.end_headers()
            def do_PUT(self):
                auth_headers.append(self.headers.get('Authorization'))
                uploaded[unquote(self.path)] = self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(201); self.send_header('Content-Length', '0'); self.end_headers()
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        mount = {'id': 'a'*32, 'name': '分享验证云盘', 'url': f'http://127.0.0.1:{server.server_port}/dav/',
                 'username': 'fixture', 'password': cloud.protect_password('fixture-password'), 'verify_tls': True}
        cloud.save_settings([mount])
        sharing.save_settings(mount['id'], '/图片/本次', False,
                              'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=fixture-key')
        assert 'fixture-key' not in cloud.config_path().read_text(encoding='utf-8')
        def intercept(request):
            assert request.url.host == 'qyapi.weixin.qq.com'
            webhooks.append(json.loads(request.content))
            return httpx.Response(200, json={'errcode': 0, 'errmsg': 'ok'})
        # DAV uses real localhost HTTP; the WeCom client is intercepted here.
        # No traffic or messages go to an external account.
        def client(**kwargs):
            if 'auth' not in kwargs: kwargs['transport'] = httpx.MockTransport(intercept)
            return original_client(**kwargs)
        httpx.Client = client
        window.finish_import([read_dataset(path) for path in paths], [])
        if len(paths) > 1: window.show_overlay()
        QApplication.processEvents(); window.canvas.draw()
        document = window.active_document()
        image_path = output.with_suffix('.export.png')
        window.write_plot(image_path)
        _verify_preparation(window, image_path.read_bytes(), report)
        window.grab().save(str(output.with_suffix('.main.png')))
        dialog = window.show_share(); wait_until(dialog.send_button.isEnabled)
        assert dialog.filename.text() == window.default_plot_filename()
        assert dialog.dav.isChecked() and dialog.wecom.isChecked()
        with Image.open(image_path) as normal, Image.open(BytesIO(dialog.png)) as snapshot:
            assert normal.size == snapshot.size and normal.tobytes() == snapshot.tobytes()
            assert snapshot.info['Author'] == 'Power By ZzzHe'
            assert snapshot.getpixel((0, 0))[:3] == (255, 255, 255)
        report['checks'].append('same_export_pixels_annotations_metadata_filename_and_white_border')
        dialog.grab().save(str(output.with_suffix('.preview.png')))
        dialog.send(); wait_until(lambda: not dialog.busy)
        assert '失败' not in dialog.feedback.toPlainText(), dialog.feedback.toPlainText()
        assert len(uploaded) == 1 and next(iter(uploaded.values())) == dialog.png
        assert next(iter(uploaded)).endswith('/图片/本次/' + dialog.filename.text())
        assert all(value and value.startswith('Basic ') for value in auth_headers)
        assert len(webhooks) == 1 and webhooks[0]['msgtype'] == 'image'
        message = webhooks[0]['image']; raw = base64.b64decode(message['base64'])
        assert message['md5'] == hashlib.md5(raw).hexdigest()
        assert len(raw) <= sharing.WECOM_IMAGE_LIMIT
        assert window.active_document() is document
        report['checks'] += ['real_localhost_webdav_put_unicode_path_authentication',
                             'mock_only_wecom_base64_md5_response_and_encrypted_settings',
                             'background_two_channel_send_keeps_active_document']
        dialog.grab().save(str(output.with_suffix('.sent.png')))
        dialog.close()
        settings_dialog = window.show_sharing_settings(); wait_until(settings_dialog.save_button.isEnabled)
        settings_dialog.grab().save(str(output.with_suffix('.settings.png')))
        settings_dialog.reject()
        assert before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        report['checks'].append('raw_sample_hashes_unchanged')
        report['status'] = 'passed'
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        httpx.Client = original_client
        window.start_cloud_maintenance = original_maintenance
        if server is not None:
            server.shutdown(); server.server_close(); thread.join(timeout=3)
        if original_appdata is None: os.environ.pop('LOCALAPPDATA', None)
        else: os.environ['LOCALAPPDATA'] = original_appdata
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        window.dirty = False; window.close()
    if report['status'] != 'passed': raise SystemExit(1)
