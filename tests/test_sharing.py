"""Protocol, persistence, snapshot fidelity and GUI-thread sharing regression."""
import base64
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import queue
import threading
import time
from urllib.parse import unquote

import httpx
import numpy as np
from PIL import Image
import pytest
from PySide6.QtWidgets import QApplication, QDialog

from test_feature_ui import ui, imported
from tma_app import sharing, cloud_storage as cloud
from tma_app.path_settings import _settings_data, config_path, save_paths
from tma_app.share_dialog import SharingSettingsDialog


def png_bytes():
    output = BytesIO(); Image.new('RGB', (160, 100), 'white').save(output, format='PNG')
    return output.getvalue()


@contextmanager
def dav_server():
    files = {}; calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_MKCOL(self):
            calls.append(('MKCOL', unquote(self.path), self.headers.get('Authorization')))
            self.send_response(201); self.send_header('Content-Length', '0'); self.end_headers()
        def do_PUT(self):
            path = unquote(self.path)
            data = self.rfile.read(int(self.headers['Content-Length']))
            calls.append(('PUT', path, self.headers.get('Authorization')))
            status = 412 if path in files and self.headers.get('If-None-Match') == '*' else 201
            if status == 201: files[path] = data
            self.send_response(status); self.send_header('Content-Length', '0'); self.end_headers()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    mount = {'id': 'a'*32, 'name': '测试云盘', 'url': f'http://127.0.0.1:{server.server_port}/dav/',
             'username': 'user', 'password': cloud.protect_password('private-password'), 'verify_tls': True}
    try: yield mount, files, calls
    finally: server.shutdown(); server.server_close(); thread.join(timeout=3)


def wait(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents(); time.sleep(.01)
    assert predicate()


def test_encrypted_settings_preserve_paths_cloud_and_blank_secret():
    save_paths({'m': 'C:/mass.xlsx', 'open_folder': 'C:/samples'})
    cloud.save_settings([], 96)
    url = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=private-fixture-key'
    sharing.save_settings('a'*32, '/图片/本次', False, url)
    value = sharing.settings()
    assert 'private-fixture-key' not in config_path().read_text(encoding='utf-8')
    assert cloud.protect_password(value['webhook'], True) == url
    sharing.save_settings('b'*32, '/其它', True)
    assert sharing.settings()['webhook'] == value['webhook']
    assert _settings_data()['paths']['m'] == 'C:/mass.xlsx'
    assert cloud.settings()['retention_hours'] == 96
    sharing.save_settings('', '/', False, clear_webhook=True)
    assert sharing.settings()['webhook'] == ''


@pytest.mark.parametrize('url', [
    'http://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x',
    'https://example.com/cgi-bin/webhook/send?key=x',
    'https://qyapi.weixin.qq.com.evil.test/cgi-bin/webhook/send?key=x',
    'https://user@qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x',
    'https://qyapi.weixin.qq.com:123/cgi-bin/webhook/send?key=x',
    'https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key=x',
    'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=',
    'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x&key=y',
    'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x#frag',
])
def test_invalid_webhook_rejected_without_saving(url):
    before = _settings_data()
    with pytest.raises(ValueError): sharing.save_settings('', '/', False, url)
    assert _settings_data() == before


def test_webdav_actual_put_nested_unicode_and_conflict():
    raw = png_bytes()
    with dav_server() as (mount, files, calls):
        dav = sharing.ShareDAV(mount)
        result = dav.upload('/图片/本次', '20261017-5#.png', raw)
        assert '20261017-5#.png' in result
        assert files == {'/dav/图片/本次/20261017-5#.png': raw}
        assert [call[:2] for call in calls[:2]] == [('MKCOL', '/dav/图片/'), ('MKCOL', '/dav/图片/本次/')]
        assert all(call[2].startswith('Basic ') for call in calls)
        with pytest.raises(ValueError, match='同名'): dav.upload('/图片/本次', '20261017-5#.png', b'new')
        assert files['/dav/图片/本次/20261017-5#.png'] == raw
        dav.upload('/图片/本次', '20261017-5#.png', b'new', overwrite=True)
        assert files['/dav/图片/本次/20261017-5#.png'] == b'new'


def test_webdav_rejects_unsafe_destination_and_cross_origin_redirect(monkeypatch):
    mount = {'id': 'b'*32, 'name': 'fixture', 'url': 'https://example.com/dav/'}
    dav = sharing.ShareDAV(mount)
    for folder, filename in [('/../other', 'a.png'), ('/', '../a.png'), ('/', 'a/b.png')]:
        with pytest.raises(ValueError): dav.upload(folder, filename, b'png')
    seen = []
    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(307, headers={'Location': 'https://elsewhere.test/stolen'})
    @contextmanager
    def client():
        with httpx.Client(transport=httpx.MockTransport(handler)) as value: yield value
    monkeypatch.setattr(dav, 'client', client)
    with pytest.raises(ValueError, match='重定向'): dav.upload('/', 'a.png', b'png')
    assert len(seen) == 1


def test_wecom_payload_errcode_and_secrets_not_exposed(monkeypatch):
    secret = cloud.protect_password('https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=private-key')
    raw = png_bytes(); seen = []; answer = {'errcode': 0}
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=answer)
    original_client = httpx.Client
    monkeypatch.setattr(sharing.httpx, 'Client', lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    assert '已发送' in sharing.send_wecom(secret, raw)
    body = json.loads(seen[0].content)
    assert body['msgtype'] == 'image'
    assert base64.b64decode(body['image']['base64']) == raw
    assert body['image']['md5'] == hashlib.md5(raw).hexdigest()
    answer.update(errcode=93000, errmsg='private-key returned by remote')
    with pytest.raises(ValueError, match='93000') as error: sharing.send_wecom(secret, raw)
    assert 'private-key' not in str(error.value)


@pytest.mark.parametrize('status', [302, 403, 500])
def test_wecom_http_failure_not_followed_or_reported_as_success(monkeypatch, status):
    secret = cloud.protect_password('https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=private-key')
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(status, headers={'Location': 'https://example.com/secret'})
    original_client = httpx.Client
    monkeypatch.setattr(sharing.httpx, 'Client', lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(ValueError, match=f'HTTP {status}'): sharing.send_wecom(secret, png_bytes())
    assert len(seen) == 1


def test_wecom_compresses_big_image_keeps_small_image_and_metadata():
    raw = png_bytes(); assert sharing.image_for_wecom(raw) is raw
    noise = np.random.default_rng(2).integers(0, 256, (1100, 1100, 3), dtype=np.uint8)
    output = BytesIO(); Image.fromarray(noise).save(output, format='PNG')
    assert len(output.getvalue()) > sharing.WECOM_IMAGE_LIMIT
    result = sharing.image_for_wecom(output.getvalue())
    assert len(result) <= sharing.WECOM_IMAGE_LIMIT
    with Image.open(BytesIO(result)) as image:
        assert image.info['Author'] == 'Power By ZzzHe'
        assert image.width < 1100


def test_worker_partial_failure_and_gui_free_result_records(monkeypatch):
    monkeypatch.setattr(sharing.ShareDAV, 'upload', lambda *args, **kwargs: 'uploaded')
    def fail(*args): raise ValueError('fixture failure')
    monkeypatch.setattr(sharing, 'send_wecom', fail)
    events = queue.Queue()
    sharing.share_job(b'png', 'a.png', [
        {'channel': 'webdav', 'mount': {'id': 'a'*32, 'name': 'x', 'url': 'https://example.com/'},
         'folder': '/', 'overwrite': False}, {'channel': 'wecom', 'webhook': 'fixture'}], events)
    assert events.get()['ok'] is True
    assert events.get()['ok'] is False
    assert events.get() is None


def test_share_ui_snapshot_actual_export_and_settings_do_not_send(ui, tmp_path, monkeypatch):
    imported(ui, tmp_path, 2)
    doc = ui.active_document(); original = [curve.xy()[1].copy() for curve in ui.curves]
    ui.plot_options[doc.key]['export_title'] = '分享测试标题'
    ui.canvas.draw(); expected = (ui.figure.get_figwidth() + .5) * 300
    dialog = ui.show_share(); wait(lambda: bool(dialog.png))
    assert dialog.filename.text() == ui.default_plot_filename()
    with Image.open(BytesIO(dialog.png)) as image:
        assert abs(image.width - expected) <= 1
        assert image.info['Author'] == 'Power By ZzzHe'
        assert image.getpixel((0, 0))[:3] == (255, 255, 255)
    assert ui.active_document() is doc
    for curve, y in zip(ui.curves, original): np.testing.assert_array_equal(curve.xy()[1], y)
    assert ui.show_share() is dialog
    settings = SharingSettingsDialog(ui)
    settings.webhook.setText('https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=fixture-key')
    settings.accept(); assert settings.result() == QDialog.DialogCode.Accepted
    assert sharing.settings()['webhook']
    dialog.reject()
    assert ui.share_button.isVisible()
    assert ui.share_button.mapTo(ui, ui.share_button.rect().center()).x() > ui.width() * .75


def test_dialog_background_send_does_not_block_and_cannot_close_mid_request(ui, tmp_path, monkeypatch):
    imported(ui, tmp_path, 1)
    with dav_server() as (mount, files, calls):
        cloud.save_settings([mount]); sharing.save_settings(mount['id'], '/图片', False)
        dialog = ui.show_share(); wait(lambda: bool(dialog.png))
        entered = threading.Event(); release = threading.Event(); worker_ids = []
        original_upload = sharing.ShareDAV.upload
        def delayed(self, *args, **kwargs):
            worker_ids.append(threading.get_ident()); entered.set(); release.wait(10)
            return original_upload(self, *args, **kwargs)
        monkeypatch.setattr(sharing.ShareDAV, 'upload', delayed)
        dialog.send(); wait(entered.is_set)
        assert dialog.busy and not dialog.send_button.isEnabled()
        dialog.reject(); assert dialog.isVisible()
        dialog.close(); assert dialog.isVisible()
        release.set(); wait(lambda: not dialog.busy)
        assert worker_ids == [dialog.worker_thread.ident] and worker_ids[0] != threading.get_ident()
        assert dialog.send_button.isEnabled() and '成功' in dialog.feedback.toPlainText()
        assert len(files) == 1 and next(iter(files.values())) == dialog.png
        dialog.close(); assert not dialog.isVisible()


def test_no_data_has_no_share_and_filename_validation(ui, tmp_path):
    assert ui.show_share() is None
    imported(ui, tmp_path, 1)
    dialog = ui.show_share(); wait(lambda: bool(dialog.png))
    dialog.filename.setText('../bad.png'); dialog.send()
    assert not dialog.busy and '文件名' in dialog.feedback.toPlainText()
    dialog.filename.setText('sample'); dialog.dav.setChecked(False); dialog.wecom.setChecked(False)
    dialog.send(); assert '至少一个' in dialog.feedback.toPlainText()
    dialog.close()
