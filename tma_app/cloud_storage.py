"""Read-only WebDAV mounts, private local cache and sliding expiry.

Only indexed, application-owned cache files are eligible for deletion. HTTP
operations never issue PUT, DELETE, MOVE or other remote mutation requests.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import tempfile
import threading
import time
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from defusedxml import ElementTree as ET

from .path_settings import config_path, _settings_data, _save_data

DAV = "{DAV:}"
_DOWNLOAD_LOCK = threading.RLock()


def root():
    return config_path().parent / "cloud"


def cache_root():
    return root() / "cache"


def settings():
    value = _settings_data().get("cloud", {})
    hours = value.get("retention_hours", 72)
    if type(hours) not in (int, float) or not 1 <= hours <= 87600:
        raise ValueError("云文件保留时间须为 1–87600 小时")
    mounts = value.get("mounts", [])
    if not isinstance(mounts, list):
        raise ValueError("云盘配置格式无效")
    for mount in mounts:
        validate_mount(mount)
    if len({mount["id"] for mount in mounts}) != len(mounts):
        raise ValueError("云盘标识重复")
    return {"retention_hours": hours, "mounts": mounts}


def save_settings(mounts, retention_hours=72):
    if type(retention_hours) not in (int, float) or not 1 <= retention_hours <= 87600:
        raise ValueError("云文件保留时间须为 1–87600 小时")
    for mount in mounts:
        validate_mount(mount)
    if len({mount["id"] for mount in mounts}) != len(mounts):
        raise ValueError("云盘标识重复")
    data = _settings_data()
    data["cloud"] = {"retention_hours": retention_hours, "mounts": mounts}
    _save_data(data)


def normalize_url(value):
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("请输入完整 http(s) WebDAV 地址，账号密码请填在独立输入框")
    try:
        parts.port
    except ValueError as exc:
        raise ValueError("WebDAV 端口无效") from exc
    path = remote_path(unquote(parts.path))
    return urlunsplit((parts.scheme, parts.netloc, quote(path, safe="/").rstrip("/") + "/", "", ""))


def remote_path(value):
    value = str(value)
    if "\\" in value or any(part in (".", "..") for part in value.split("/")) or any(ord(c) < 32 for c in value):
        raise ValueError("云文件路径无效")
    return "/" + "/".join(part for part in value.split("/") if part)


def validate_mount(mount):
    if not isinstance(mount, dict) or not re.fullmatch(r"[0-9a-f]{32}", str(mount.get("id", ""))):
        raise ValueError("云盘标识无效")
    if not isinstance(mount.get("name"), str) or not mount["name"].strip():
        raise ValueError("请填写云盘名称")
    if not isinstance(mount.get("url"), str):
        raise ValueError("WebDAV 地址无效")
    normalize_url(mount["url"])
    if not isinstance(mount.get("username", ""), str) or type(mount.get("verify_tls", True)) is not bool:
        raise ValueError("云盘登录配置无效")
    password = mount.get("password", "")
    if not isinstance(password, str) or (password and not password.startswith("dpapi:")):
        raise ValueError("密码必须加密后保存")


def protect_password(value, decrypt=False):
    if not value:
        return ""
    if os.name != "nt":
        raise ValueError("云盘密码保存需要 Windows 用户加密接口")
    class Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    raw = base64.b64decode(value.removeprefix("dpapi:"), validate=True) if decrypt else value.encode("utf-8")
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(Blob)]
    function.restype = ctypes.c_int
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError("云盘密码解密失败，请在当前 Windows 账户下重新输入密码" if decrypt else "云盘密码加密失败")
    try:
        result = ctypes.string_at(target.data, target.size)
        return result.decode("utf-8") if decrypt else "dpapi:" + base64.b64encode(result).decode("ascii")
    finally:
        free = ctypes.WinDLL("kernel32", use_last_error=True).LocalFree
        free.argtypes = [ctypes.c_void_p]; free.restype = ctypes.c_void_p
        free(target.data)


def get_mount(identifier):
    for mount in settings()["mounts"]:
        if mount["id"] == identifier:
            return mount
    raise ValueError("此云盘未挂载，请先在云盘窗口中配置")


def cloud_uri(mount_id, path):
    return f"cloud://{mount_id}" + quote(remote_path(path), safe="/")


def parse_uri(value):
    parts = urlsplit(str(value))
    if parts.scheme != "cloud" or not re.fullmatch(r"[0-9a-f]{32}", parts.netloc) or parts.query or parts.fragment:
        raise ValueError("云文件地址无效")
    return parts.netloc, remote_path(unquote(parts.path))


class WebDAV:
    def __init__(self, mount):
        validate_mount(mount)
        self.mount = mount
        self.base = normalize_url(mount["url"])

    def url(self, path):
        return self.base + quote(remote_path(path).lstrip("/"), safe="/")

    @contextmanager
    def client(self):
        import httpx
        password = protect_password(self.mount.get("password", ""), decrypt=True)
        auth = httpx.BasicAuth(self.mount.get("username", ""), password) if self.mount.get("username") or password else None
        with httpx.Client(auth=auth, verify=self.mount.get("verify_tls", True), follow_redirects=False,
                          trust_env=False, timeout=httpx.Timeout(60, connect=15)) as client:
            yield client

    @contextmanager
    def request(self, client, method, url, **kwargs):
        anonymous = False
        for _ in range(5):
            request = client.build_request(method, url, **kwargs)
            if anonymous:
                request.headers.pop("authorization", None)
                request.headers.pop("cookie", None)
            response = client.send(request, stream=True, **({"auth": None} if anonymous else {}))
            if response.status_code not in (301, 302, 303, 307, 308):
                try: yield response
                finally: response.close()
                return
            redirected = urljoin(url, response.headers.get("location", ""))
            response.close()
            if not self._inside(redirected):
                target = urlsplit(redirected)
                transport_ok = target.scheme == "https" or (target.scheme == "http" and urlsplit(self.base).scheme == "http")
                if method != "GET" or not transport_ok or not target.hostname or target.username or target.password:
                    raise ValueError("云盘重定向到挂载范围之外，请使用最终 WebDAV 地址")
                # Netdisk gateways commonly redirect GET to a signed CDN URL.
                # The mount's Basic credentials/cookies must never follow it.
                anonymous = True
            url = redirected
        raise ValueError("WebDAV 重定向次数过多")

    def _inside(self, url):
        base, target = urlsplit(self.base), urlsplit(url)
        def origin(parts):
            return parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)
        if origin(target) != origin(base) or target.query or target.fragment:
            return False
        prefix, path = unquote(base.path).rstrip("/"), unquote(target.path)
        try: remote_path(path)
        except ValueError: return False
        return path == prefix or path.startswith(prefix + "/")

    def relative(self, href, requested_url):
        url = urljoin(requested_url, href)
        if not self._inside(url):
            return None
        prefix = unquote(urlsplit(self.base).path).rstrip("/")
        return remote_path(unquote(urlsplit(url).path)[len(prefix):])

    def list(self, directory="/"):
        import httpx
        directory = remote_path(directory)
        url = self.url(directory).rstrip("/") + "/"
        body = b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:displayname/><d:resourcetype/><d:getcontentlength/><d:getlastmodified/><d:getetag/></d:prop></d:propfind>'
        try:
            with self.client() as client, self.request(client, "PROPFIND", url,
                    headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"}, content=body) as response:
                self.check(response, 207)
                chunks = []; size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 8 * 1024 * 1024:
                        raise ValueError("目录列表过大，请缩小挂载目录范围")
                    chunks.append(chunk)
                document = ET.fromstring(b"".join(chunks))
            entries = []
            for item in document.findall(DAV + "response"):
                path = self.relative(item.findtext(DAV + "href", ""), url)
                if not path or path == directory or str(PurePosixPath(path).parent) != directory:
                    continue
                prop = None
                for status in item.findall(DAV + "propstat"):
                    if " 200 " in status.findtext(DAV + "status", ""):
                        prop = status.find(DAV + "prop"); break
                if prop is None: continue
                collection = prop.find(f"{DAV}resourcetype/{DAV}collection") is not None
                length = prop.findtext(DAV + "getcontentlength", "")
                entries.append({"name": PurePosixPath(path).name, "path": path, "directory": collection,
                                "size": int(length) if length.isdigit() else None,
                                "modified": prop.findtext(DAV + "getlastmodified", ""),
                                "uri": cloud_uri(self.mount["id"], path)})
            return sorted(entries, key=lambda e: (not e["directory"], e["name"].casefold()))
        except httpx.HTTPError as exc:
            raise ValueError("WebDAV 连接失败，请检查地址、网络和证书：" + type(exc).__name__) from None

    @staticmethod
    def check(response, expected=200):
        if response.status_code in (401, 403):
            raise ValueError("WebDAV 登录失败或无读取权限，请检查账号密码")
        if response.status_code == 404:
            raise ValueError("云文件或目录不存在")
        if response.status_code != expected:
            raise ValueError(f"WebDAV 返回 HTTP {response.status_code}")


@contextmanager
def database():
    root().mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root() / "cache.sqlite3", timeout=20)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS files (key TEXT PRIMARY KEY, mount_id TEXT, remote TEXT, origin TEXT, path TEXT UNIQUE, last_used REAL, etag TEXT, modified TEXT, size INTEGER, sha256 TEXT, lease_until REAL DEFAULT 0)")
        db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)")
        db.commit()
        yield db
        db.commit()
    finally:
        db.close()


def file_key(mount_id, origin, path):
    return hashlib.sha256((mount_id + "\n" + origin + "\n" + path).encode("utf-8")).hexdigest()


def target_path(mount_id, origin, path):
    if not re.fullmatch(r"[0-9a-f]{32}", mount_id):
        raise ValueError("缓存云盘标识无效")
    name = PurePosixPath(remote_path(path)).name
    if not name:
        raise ValueError("请选择文件，不能下载根目录")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).rstrip(". ")
    if not name or name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    return cache_root() / mount_id / file_key(mount_id, origin, path) / name


def checked_target(row):
    expected = target_path(row["mount_id"], row["origin"], row["remote"])
    target = Path(row["path"])
    # Reject forged index paths, symlinks and junction escapes before deleting.
    if os.path.normcase(str(expected.absolute())) != os.path.normcase(str(target.absolute())):
        raise ValueError("缓存索引路径无效")
    resolved = target.resolve()
    if not resolved.is_relative_to(cache_root().resolve()) or resolved != expected.absolute():
        raise ValueError("缓存路径包含链接或超出缓存范围")
    return target


def fetch(mount_id, path, *, refresh=False, cancelled=None, progress=None):
    import httpx
    mount = get_mount(mount_id)
    dav = WebDAV(mount); path = remote_path(path)
    origin = dav.base; target = target_path(mount_id, origin, path)
    key = file_key(mount_id, origin, path)
    with _DOWNLOAD_LOCK:
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM files WHERE key=?", (key,)).fetchone()
            if row and checked_target(row).is_file() and not refresh:
                db.execute("UPDATE files SET last_used=? WHERE key=?", (time.time(), key))
                return target
            now = time.time()
            db.execute("INSERT INTO files(key,mount_id,remote,origin,path,last_used,size,lease_until) VALUES(?,?,?,?,?,?,0,?) ON CONFLICT(key) DO UPDATE SET lease_until=excluded.lease_until",
                       (key, mount_id, path, origin, str(target.absolute()), now, now + 3600))
        target.parent.mkdir(parents=True, exist_ok=True)
        checked_target({"mount_id": mount_id, "origin": origin, "remote": path, "path": str(target.absolute())})
        headers = {}
        if row and target.is_file():
            if row["etag"]: headers["If-None-Match"] = row["etag"]
            elif row["modified"]: headers["If-Modified-Since"] = row["modified"]
        temporary = None
        try:
            with dav.client() as client, dav.request(client, "GET", dav.url(path), headers=headers) as response:
                if response.status_code == 304 and target.is_file():
                    with database() as db:
                        db.execute("UPDATE files SET last_used=?,lease_until=0 WHERE key=?", (time.time(), key))
                    return target
                dav.check(response)
                descriptor, temporary = tempfile.mkstemp(prefix="download-", suffix=".part", dir=target.parent)
                digest = hashlib.sha256(); size = 0; heartbeat = time.time()
                with os.fdopen(descriptor, "wb") as handle:
                    for chunk in response.iter_bytes(chunk_size=256 * 1024):
                        if cancelled and cancelled.is_set(): raise ValueError("已取消下载")
                        handle.write(chunk); digest.update(chunk); size += len(chunk)
                        if time.time() - heartbeat > 60:
                            heartbeat = time.time()
                            with database() as db:
                                db.execute("UPDATE files SET lease_until=? WHERE key=?", (heartbeat + 3600, key))
                        if progress: progress(f"正在下载 {target.name} · {size / 1024 / 1024:.1f} MB")
                if cancelled and cancelled.is_set(): raise ValueError("已取消下载")
                length = response.headers.get("content-length", "")
                if length.isdigit() and not response.headers.get("content-encoding") and size != int(length):
                    raise ValueError("云文件下载不完整，请重试")
                with database() as db:
                    db.execute("BEGIN IMMEDIATE")
                    checked_target({"mount_id": mount_id, "origin": origin, "remote": path, "path": str(target.absolute())})
                    os.replace(temporary, target)
                    db.execute("UPDATE files SET last_used=?,etag=?,modified=?,size=?,sha256=?,lease_until=0 WHERE key=?",
                               (time.time(), response.headers.get("etag", ""), response.headers.get("last-modified", ""), size, digest.hexdigest(), key))
            return target
        except httpx.HTTPError as exc:
            raise ValueError("云文件下载失败：" + type(exc).__name__) from None
        finally:
            if temporary: Path(temporary).unlink(missing_ok=True)
            with database() as db:
                db.execute("UPDATE files SET lease_until=0 WHERE key=?", (key,))


def cached_record(path):
    candidate = Path(path).expanduser().absolute()
    if not candidate.is_relative_to(cache_root().absolute()) or not (root() / "cache.sqlite3").exists():
        return None
    with database() as db:
        return db.execute("SELECT * FROM files WHERE path=? COLLATE NOCASE", (str(candidate),)).fetchone()


def touch_path(path):
    """No network IO. Ordinary local files do not create or enter the cache."""
    row = cached_record(path)
    if row:
        checked_target(row)
        with database() as db:
            db.execute("UPDATE files SET last_used=? WHERE key=?", (time.time(), row["key"]))
        return True
    return False


def resolve_source(source, *, refresh=True):
    if str(source).startswith("cloud://"):
        identifier, path = parse_uri(source)
        return fetch(identifier, path, refresh=refresh)
    path = Path(source).expanduser().resolve()
    row = cached_record(path)
    if row:
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            if checked_target(row).is_file():
                db.execute("UPDATE files SET last_used=? WHERE key=?", (time.time(), row["key"]))
                return path
        mount = get_mount(row["mount_id"])
        if normalize_url(mount["url"]) != row["origin"]:
            raise ValueError("原挂载地址已变化，请从云盘窗口重新打开文件")
        return fetch(row["mount_id"], row["remote"], refresh=True)
    return path


def cleanup(*, now=None, force=False):
    now = time.time() if now is None else now
    report = {"deleted": 0, "bytes": 0, "skipped": 0, "errors": [], "checked_at": now}
    if not (root() / "cache.sqlite3").exists(): return report
    cutoff = now - settings()["retention_hours"] * 3600
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("SELECT value FROM metadata WHERE key='last_cleanup' ").fetchone()
        if not force and previous and now - float(previous[0]) < 24 * 3600:
            report["not_due"] = True; return report
        for row in db.execute("SELECT * FROM files WHERE last_used < ? AND lease_until < ?", (cutoff, now)).fetchall():
            try:
                target = checked_target(row)
                if target.is_file():
                    size = target.stat().st_size
                    target.unlink()
                    report["deleted"] += 1; report["bytes"] += size
                    db.execute("UPDATE files SET size=0 WHERE key=?", (row["key"],))
            except (OSError, ValueError) as exc:
                report["skipped"] += 1; report["errors"].append(str(exc))
        # A crash can leave partials even when the final file is used again.
        # Visit only indexed private directories, and respect active downloads.
        for row in db.execute("SELECT * FROM files WHERE lease_until < ?", (now,)).fetchall():
            try:
                target = checked_target(row)
                if target.parent.is_dir():
                    for part in target.parent.glob("download-*.part"):
                        if not part.is_symlink() and part.stat().st_mtime < cutoff:
                            size = part.stat().st_size; part.unlink(); report["bytes"] += size
            except (OSError, ValueError): pass
        db.execute("INSERT OR REPLACE INTO metadata VALUES('last_cleanup',?)", (str(now),))
    return report


def cache_stats():
    result = {"files": 0, "bytes": 0}
    if not (root() / "cache.sqlite3").exists(): return result
    with database() as db:
        for row in db.execute("SELECT * FROM files"):
            try:
                path = checked_target(row)
                if path.is_file():
                    result["files"] += 1; result["bytes"] += path.stat().st_size
            except (OSError, ValueError): pass
    return result


def cleanup_main():
    try:
        report = {"status": "passed", **cleanup(force=True)}
    except Exception as exc:
        report = {"status": "failed", "error": str(exc)}
    root().mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="cleanup-", suffix=".tmp", dir=root())
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, root() / "cleanup-last.json")
    return 0 if report["status"] == "passed" else 1
