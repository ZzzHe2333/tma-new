"""Image sharing: plain data in, no GUI objects or plotting on network workers."""
from __future__ import annotations

import base64
import hashlib
from io import BytesIO
import queue
from urllib.parse import parse_qs, urlsplit, urlunsplit, urlencode

import httpx
from PIL import Image, PngImagePlugin

from . import cloud_storage as cloud
from .path_settings import _settings_data, _save_data

WECOM_IMAGE_LIMIT = 2 * 1024 * 1024


def webhook_url(value):
    parts = urlsplit(value.strip())
    try:
        valid = (parts.scheme == 'https' and parts.hostname == 'qyapi.weixin.qq.com'
                 and parts.port in (None, 443) and not parts.username and not parts.password
                 and parts.path == '/cgi-bin/webhook/send' and not parts.fragment)
    except ValueError:
        valid = False
    query = parse_qs(parts.query, keep_blank_values=True)
    if not valid or set(query) != {'key'} or len(query['key']) != 1 or not query['key'][0].strip():
        raise ValueError('请填写企业微信群机器人的完整 HTTPS Webhook 地址（含 key）')
    return urlunsplit(('https', 'qyapi.weixin.qq.com', parts.path, urlencode({'key': query['key'][0]}), ''))


def settings():
    value = _settings_data().get('sharing', {})
    if not isinstance(value, dict):
        raise ValueError('分享配置格式无效')
    folder = cloud.remote_path(value.get('folder', '/TMA分享'))
    secret = value.get('webhook', '')
    if not isinstance(secret, str) or (secret and not secret.startswith('dpapi:')):
        raise ValueError('分享 Webhook 配置无效，请重新保存')
    return {'mount_id': str(value.get('mount_id', '')), 'folder': folder,
            'overwrite': value.get('overwrite', False) is True, 'webhook': secret}


def save_settings(mount_id, folder, overwrite, webhook='', *, clear_webhook=False):
    previous = settings()
    value = {'mount_id': str(mount_id), 'folder': cloud.remote_path(folder),
             'overwrite': bool(overwrite),
             'webhook': '' if clear_webhook else previous['webhook']}
    if webhook.strip():
        value['webhook'] = cloud.protect_password(webhook_url(webhook))
    data = _settings_data()
    data['sharing'] = value
    _save_data(data)


def image_for_wecom(png):
    """Keep the export untouched when it fits; shrink large PNGs for the API."""
    if len(png) <= WECOM_IMAGE_LIMIT:
        return png
    with Image.open(BytesIO(png)) as source:
        image = source.convert('RGB')
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('Author', 'Power By ZzzHe')
    metadata.add_text('Software', 'Power By ZzzHe')
    for _ in range(18):
        output = BytesIO()
        image.save(output, format='PNG', optimize=True, pnginfo=metadata)
        raw = output.getvalue()
        if len(raw) <= WECOM_IMAGE_LIMIT:
            return raw
        image = image.resize((max(1, int(image.width * .8)), max(1, int(image.height * .8))),
                             Image.Resampling.LANCZOS)
    raise ValueError('图片压缩后仍超过企业微信限制，请缩小图像后重试')


def send_wecom(secret, png):
    url = webhook_url(cloud.protect_password(secret, decrypt=True))
    raw = image_for_wecom(png)
    payload = {'msgtype': 'image', 'image': {'base64': base64.b64encode(raw).decode('ascii'),
                                           'md5': hashlib.md5(raw).hexdigest()}}
    # Never follow redirects or expose HTTP exception strings containing the key.
    try:
        with httpx.Client(timeout=httpx.Timeout(60, connect=15), trust_env=False,
                          follow_redirects=False) as client:
            response = client.post(url, json=payload)
        if response.status_code != 200:
            raise ValueError(f'企业微信返回 HTTP {response.status_code}')
        try:
            reply = response.json()
        except ValueError:
            raise ValueError('企业微信返回的数据格式异常') from None
        if not isinstance(reply, dict) or type(reply.get('errcode')) is not int:
            raise ValueError('企业微信返回的数据格式异常')
        if reply['errcode'] != 0:
            raise ValueError(f"企业微信发送失败（errcode={reply['errcode']}），请检查机器人设置或发送频率")
    except httpx.HTTPError:
        raise ValueError('企业微信网络请求失败，结果未确认；请检查群消息后再决定是否重试') from None
    return '图片已发送到企业微信群'


class ShareDAV(cloud.WebDAV):
    """Explicit upload capability; cloud browsing stays read-only."""
    def upload(self, folder, filename, png, *, overwrite=False):
        folder = cloud.remote_path(folder)
        if not filename or filename in ('.', '..') or any(c in filename for c in '/\\') or any(ord(c) < 32 for c in filename):
            raise ValueError('图片文件名无效')
        destination = cloud.remote_path(folder.rstrip('/') + '/' + filename)
        try:
            with self.client() as client:
                current = ''
                for part in folder.strip('/').split('/') if folder != '/' else []:
                    current += '/' + part
                    with self.request(client, 'MKCOL', self.url(current).rstrip('/') + '/') as response:
                        if response.status_code not in (201, 405):
                            self.check(response, 201)
                headers = {'Content-Type': 'image/png'}
                if not overwrite:
                    headers['If-None-Match'] = '*'
                with self.request(client, 'PUT', self.url(destination), headers=headers, content=png) as response:
                    if response.status_code == 412:
                        raise ValueError('云盘已有同名图片；请更换文件名，或在分享设置中允许覆盖')
                    if response.status_code not in (200, 201, 204):
                        self.check(response, 201)
        except httpx.HTTPError:
            raise ValueError('WebDAV 上传请求失败，结果未确认；请检查云盘后再决定是否重试') from None
        return f"已上传到 {self.mount['name']}：{destination}"


def share_job(png: bytes, filename: str, targets: list, events: queue.Queue):
    """No Qt callbacks in this thread; the dialog polls plain result records."""
    for target in targets:
        channel = target['channel']
        try:
            if channel == 'webdav':
                text = ShareDAV(target['mount']).upload(target['folder'], filename, png,
                                                       overwrite=target['overwrite'])
            else:
                text = send_wecom(target['webhook'], png)
            events.put({'channel': channel, 'ok': True, 'message': text})
        except Exception as exc:
            # Unknown transport errors must not echo a webhook or password.
            text = str(exc) if isinstance(exc, ValueError) else '分享失败，请检查配置和网络后重试'
            events.put({'channel': channel, 'ok': False, 'message': text})
    events.put(None)
