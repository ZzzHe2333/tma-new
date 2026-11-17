"""Fetch Windows portable updates from the official GitHub release feed."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from . import __version__

_REPO = 'ZzzHe2333/tma-new'
_API = f'https://api.github.com/repos/{_REPO}/releases/latest'
_MAX_PACKAGE = 1024**3
_VERSION = re.compile(r'v?(\d{1,6}\.\d{1,6}\.\d{1,6})')


@dataclass(frozen=True)
class Release:
    version: str
    filename: str
    url: str
    size: int
    sha256: str


class _HttpsRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != 'https':
            raise ValueError('更新下载禁止重定向至非 HTTPS 地址。')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener(proxy):
    if proxy:
        parts = urlsplit(proxy)
        if (parts.scheme != 'http' or not parts.hostname or not parts.port
                or parts.username or parts.password or parts.path not in ('', '/')
                or parts.query or parts.fragment):
            raise ValueError('HTTP 代理格式示例：http://127.0.0.1:7897')
    return build_opener(ProxyHandler({'https': proxy} if proxy else {}), _HttpsRedirect())


def _request(opener, url, accept):
    request = Request(url, headers={'User-Agent': 'ZzzHe-TMA-Analysis', 'Accept': accept})
    return opener.open(request, timeout=20)


def _release(data, current):
    tag = data.get('tag_name', '')
    match = _VERSION.fullmatch(tag)
    if not match or data.get('draft') or data.get('prerelease'):
        raise ValueError('GitHub 未返回可识别的正式版本。')
    version = match[1]
    if tuple(map(int, version.split('.'))) <= tuple(map(int, current.split('.'))):
        return None
    filename = f'ZzzHe-TMA-Analysis-{version}.zip'
    url = f'https://github.com/{_REPO}/releases/download/{tag}/{filename}'
    for asset in data.get('assets', []):
        if asset.get('name') != filename or asset.get('browser_download_url') != url:
            continue
        digest = re.fullmatch(r'sha256:([0-9a-fA-F]{64})', asset.get('digest') or '')
        size = asset.get('size')
        if digest and type(size) is int and 0 < size <= _MAX_PACKAGE:
            return Release(version, filename, url, size, digest[1].lower())
    raise ValueError('正式版本缺少 Windows ZIP 或 GitHub SHA-256 校验值。')


def check(cancelled, proxy):
    if cancelled.is_set():
        return None
    try:
        with _request(_opener(proxy), _API, 'application/vnd.github+json') as response:
            raw = response.read(2 * 1024**2 + 1)
    except HTTPError as exc:
        if exc.code == 404:
            raise ValueError('无法访问正式 Release。请检查仓库权限或是否已发布更新。') from exc
        raise
    if len(raw) > 2 * 1024**2:
        raise ValueError('版本信息超过大小限制。')
    return _release(json.loads(raw), __version__)


def _download_url(release, mirror):
    if not mirror:
        return release.url
    if mirror.count('{url}') != 1 or not mirror.startswith('https://'):
        raise ValueError('加速地址须为 HTTPS，且包含一个 {url} 占位符。')
    # Path-style mirrors accept the original URL; query-style mirrors need escaping.
    before = mirror.split('{url}', 1)[0]
    original = quote(release.url, safe='') if '?' in before else release.url
    return mirror.replace('{url}', original)


def download(cancelled, release, target, proxy, mirror):
    target = Path(target)
    url = _download_url(release, mirror)
    opener = _opener(proxy)
    digest = hashlib.sha256()
    total = 0
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.tma-update-', suffix='.part', delete=False) as output:
            temporary = Path(output.name)
            with _request(opener, url, 'application/octet-stream') as response:
                while not cancelled.is_set():
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > release.size:
                        raise ValueError('下载大小与 GitHub 发布记录不符。')
                    digest.update(chunk)
                    output.write(chunk)
        if cancelled.is_set():
            return None
        if total != release.size or digest.hexdigest() != release.sha256:
            raise ValueError('更新包校验失败。请切换下载渠道后重试。')
        os.replace(temporary, target)
        return target
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
