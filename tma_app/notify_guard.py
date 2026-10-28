"""Password guard for the notification settings.

Only a salted scrypt digest is stored — never the password. Verification has to
run the KDF (about 110 ms and 32 MB per attempt), so guessing cannot be
shortcut with a fast hash, and repeated failures back off exponentially.

Note: a local guard can always be bypassed by someone who can edit the code or
delete the files. It exists to stop casual changes to where notifications go,
not to defeat a determined attacker.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from . import cloud_storage as cloud
from .path_settings import config_path

SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64
SCRYPT_MAXMEM = 96 * 1024 * 1024

# sha512 of the shipped password; used only until the first unlock writes the
# salted scrypt guard.
BOOTSTRAP_SHA512 = ('cace2724d412dd6a681ce6c7ea797c261559d254d1c74816cd76cd9745133137'
                    'b4948fb2fc1887bec096ee22633f3551fab6dd8a7196ba6c8f2f6ae656eb5a0a')

# consecutive failures -> lock seconds
LOCK_STEPS = ((3, 5), (5, 60), (6, 300), (7, 900), (8, 3600))
MAX_LOCK = 3600


def guard_path():
    return config_path().parent / 'notify_guard.json'


def state_path():
    return config_path().parent / 'notify_guard_state.json'


def _read_json(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, value):
    try:
        from .atomic_files import write_json
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, value)
    except (OSError, ValueError):
        pass


def _derive(password, salt):
    return hashlib.scrypt(str(password or '').encode('utf-8'), salt=salt, n=SCRYPT_N,
                          r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN,
                          maxmem=SCRYPT_MAXMEM)


def _create_guard(password):
    salt = secrets.token_bytes(16)
    _write_json(guard_path(), {
        'version': 1,
        'algorithm': 'scrypt',
        'n': SCRYPT_N, 'r': SCRYPT_R, 'p': SCRYPT_P,
        'salt': base64.b64encode(salt).decode('ascii'),
        'digest': _derive(password, salt).hex(),
    })


def _check(password, guard):
    digest = guard.get('digest')
    salt = guard.get('salt')
    if isinstance(digest, str) and isinstance(salt, str):
        try:
            raw_salt = base64.b64decode(salt, validate=True)
            expected = bytes.fromhex(digest)
        except (ValueError, TypeError):
            return False
        try:
            actual = _derive(password, raw_salt)
        except (ValueError, OSError):
            return False
        return hmac.compare_digest(actual, expected)
    fast = hashlib.sha512(str(password or '').encode('utf-8')).hexdigest()
    return hmac.compare_digest(fast, BOOTSTRAP_SHA512)


def _lock_seconds(failures):
    seconds = 0
    for step, value in LOCK_STEPS:
        if failures >= step:
            seconds = value
    return min(seconds, MAX_LOCK)


def _load_state():
    raw = _read_json(state_path())
    sealed = raw.get('sealed', '')
    if not isinstance(sealed, str) or not sealed:
        return {'failures': 0, 'lock_until': 0.0}
    try:
        data = json.loads(cloud.protect_password(sealed, decrypt=True))
    except (ValueError, OSError, TypeError):
        return {'failures': 0, 'lock_until': 0.0}
    if not isinstance(data, dict):
        return {'failures': 0, 'lock_until': 0.0}
    try:
        return {'failures': max(0, int(data.get('failures', 0) or 0)),
                'lock_until': float(data.get('lock_until', 0) or 0)}
    except (TypeError, ValueError):
        return {'failures': 0, 'lock_until': 0.0}


def _save_state(failures, lock_until):
    try:
        sealed = cloud.protect_password(json.dumps({'failures': int(failures),
                                                    'lock_until': float(lock_until)}))
    except (ValueError, OSError):
        return
    _write_json(state_path(), {'version': 1, 'sealed': sealed})


def verify(password, *, now=None):
    """Return (allowed, message). Failures back off; success resets the counter."""
    stamp = time.time() if now is None else float(now)
    state = _load_state()
    remaining = state['lock_until'] - stamp
    if remaining > 0:
        return False, f'密码错误次数过多，请 {int(remaining) + 1} 秒后再试。'
    guard = _read_json(guard_path())
    if _check(password, guard):
        _save_state(0, 0.0)
        if not guard.get('digest'):
            _create_guard(password)
        return True, ''
    failures = state['failures'] + 1
    lock = _lock_seconds(failures)
    _save_state(failures, stamp + lock if lock else 0.0)
    if lock:
        return False, f'密码不正确（第 {failures} 次），请 {lock} 秒后再试。'
    return False, f'密码不正确（第 {failures} 次）。'


def reset():
    """Forget the guard and the attempt counter; the shipped password applies again."""
    for path in (guard_path(), state_path()):
        try:
            path.unlink()
        except OSError:
            pass
