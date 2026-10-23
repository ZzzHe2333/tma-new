"""Local nickname and permanent, machine-bound membership display."""
from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
import hashlib
import hmac
import json
import os
from pathlib import Path
import platform
import sys
import time
import uuid

from .atomic_files import write_json
from .path_settings import config_path


@lru_cache(maxsize=1)
def machine_code():
    identity = None
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography', 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                identity = winreg.QueryValueEx(key, 'MachineGuid')[0]
        except OSError: pass
    if not identity: identity = f'{platform.node()}|{uuid.getnode():012x}'
    return hashlib.sha256(('ZzzHeTMA|' + str(identity).strip().lower()).encode('utf-8')).hexdigest().upper()


def authorization_code(day=None):
    day = day or date.today()
    return hashlib.sha256(day.strftime('%Y%m%d').encode('utf-8')).hexdigest()


def account_path(): return config_path().with_name('user.json')


def portable_path(primary):
    from .ui_size import fallback_path
    path = fallback_path(primary)
    return path.with_name('user.json') if path is not None else None


def paths(*, reading=False):
    primary = account_path()
    if reading:
        from .ui_size import fallback_paths
        return list(dict.fromkeys(p for p in [primary, portable_path(primary), *fallback_paths(primary)] if p is not None))
    return [p for p in (primary, portable_path(primary)) if p is not None]


def registry_key():
    identity = os.path.normcase(os.path.abspath(account_path())).encode('utf-8')
    return 'Software\\ZzzHeTMA\\Accounts\\' + hashlib.sha256(identity).hexdigest()[:16]


def registry_enabled():
    return os.name == 'nt' and getattr(sys, 'frozen', False) and os.environ.get('ZZZHE_TMA_ACCOUNT_REGISTRY') != '0'


def read_registry():
    if not registry_enabled(): return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_key(), 0, winreg.KEY_READ) as key:
            return json.loads(winreg.QueryValueEx(key, 'Profile')[0])
    except (OSError, ValueError): return None


def write_registry(data):
    if not registry_enabled(): return False
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, registry_key(), 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, 'Profile', 0, winreg.REG_SZ, json.dumps(data, ensure_ascii=False))
    return True


def load_account():
    candidates = []
    for path in paths(reading=True):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or data.get('version') != 1: continue
            if not isinstance(data.get('nickname'), str) or len(data['nickname']) > 24: continue
            candidates.append((data.get('saved_at_ns', path.stat().st_mtime_ns), data))
        except (OSError, ValueError): continue
    data = read_registry()
    if isinstance(data, dict) and data.get('version') == 1 and isinstance(data.get('nickname'),str) and len(data['nickname']) <= 24:
        candidates.append((data.get('saved_at_ns',0), data))
    candidates = [(stamp, data) for stamp, data in candidates if type(stamp) is int]
    return max(candidates, key=lambda value:value[0])[1] if candidates else {'version':1, 'nickname':''}


def is_member(account=None, *, machine=None):
    account = load_account() if account is None else account
    try:
        if not account.get('nickname') or account.get('machine') != (machine or machine_code()): return False
        day = datetime.strptime(account['grant_day'], '%Y%m%d').date()
        return hmac.compare_digest(str(account['grant_hash']), authorization_code(day))
    except (KeyError, ValueError, TypeError): return False


def save_account(data):
    data = dict(data, version=1, saved_at_ns=time.time_ns())
    last_error = None
    saved = None
    for path in paths():
        try:
            write_json(path, data)
            saved = path; break
        except OSError as exc: last_error = exc
    try:
        if write_registry(data) and saved is None: saved = 'Windows 当前用户配置'
    except OSError as exc: last_error = exc
    if saved is not None: return saved
    raise last_error


def login(nickname):
    nickname = nickname.strip()
    if not nickname or len(nickname) > 24 or any(ord(c) < 32 for c in nickname):
        raise ValueError('请输入 1–24 个字符的昵称。')
    account = dict(load_account(), nickname=nickname)
    save_account(account)
    return account


def activate(code, *, day=None):
    account = load_account()
    if not account.get('nickname'): raise ValueError('请先通过“用户 → 登录”设置昵称。')
    day = day or date.today()
    code = code.strip().lower()
    if len(code) != 64 or any(c not in '0123456789abcdef' for c in code) or not hmac.compare_digest(code, authorization_code(day)):
        raise ValueError('授权码无效，请核对授权码和电脑日期。')
    account = dict(account, machine=machine_code(), grant_day=day.strftime('%Y%m%d'),
                   grant_hash=code, activated_at=datetime.now().astimezone().isoformat(timespec='seconds'))
    save_account(account)
    return account
