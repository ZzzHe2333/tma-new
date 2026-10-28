"""App notifications: Server酱 / Bark / 企业微信 / 飞书.

Transport only — no Qt objects and no plotting happen here. Every network call
runs on a short-lived daemon thread, so a slow or unreachable endpoint can never
block the UI or startup. Targets (send keys, webhook URLs, app secrets) are
stored with the same Windows DPAPI protection used for cloud passwords and are
never echoed in an error message or a log line.
"""
from __future__ import annotations

import base64
import hashlib
import json
import platform
import socket
import threading
import time
import uuid
from datetime import datetime
from urllib.parse import parse_qs, urlsplit, urlunsplit, urlencode

import httpx

from . import cloud_storage as cloud
from .path_settings import _settings_data, _save_data

# key, label, supports image, hint shown in the settings dialog
PROVIDERS = (
    ('serverchan', 'Server酱', False, 'SENDKEY，或 https://sctapi.ftqq.com/<SENDKEY>.send'),
    ('bark', 'Bark', False, 'KEY，或 https://api.day.app/<KEY>'),
    ('wecom', '企业微信', True, 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…'),
    ('feishu', '飞书', True, 'https://open.feishu.cn/open-apis/bot/v2/hook/…'),
)
PROVIDER_KEYS = tuple(item[0] for item in PROVIDERS)
DEFAULT_PROVIDER = 'serverchan'
EVENT_KEYS = {'登录软件': 'startup', '启动': 'startup', '单样品报告': 'report', '出报告': 'report',
              '导入数据': 'import', '批量导入': 'batch_import', '批量处理': 'batch_process',
              '复制到excal': 'copy_excel', '批量出图': 'batch_plot'}
DEFAULT_EVENTS = {'startup': True, 'report': True, 'import': True, 'batch_import': True,
                  'batch_process': True, 'copy_excel': True, 'batch_plot': True}
TIMEOUT = httpx.Timeout(30, connect=10)
_last_error = ''


def provider_label(key):
    return next((item[1] for item in PROVIDERS if item[0] == key), key)


def supports_image(key):
    return next((item[2] for item in PROVIDERS if item[0] == key), False)


def provider_hint(key):
    return next((item[3] for item in PROVIDERS if item[0] == key), '')


def _post_json(url, payload, headers=None):
    """POST once, never follow redirects, never leak the URL in the error text."""
    try:
        with httpx.Client(timeout=TIMEOUT, trust_env=False, follow_redirects=False) as client:
            response = client.post(url, json=payload, headers=headers or {})
        if response.status_code != 200:
            raise ValueError(f'通知服务返回 HTTP {response.status_code}')
        try:
            return response.json()
        except ValueError:
            raise ValueError('通知服务返回的数据格式异常') from None
    except httpx.HTTPError:
        raise ValueError('通知发送网络请求失败，结果未确认；请检查网络后重试') from None


def _post_form(url, data):
    try:
        with httpx.Client(timeout=TIMEOUT, trust_env=False, follow_redirects=False) as client:
            response = client.post(url, data=data)
        if response.status_code != 200:
            raise ValueError(f'通知服务返回 HTTP {response.status_code}')
        try:
            return response.json()
        except ValueError:
            raise ValueError('通知服务返回的数据格式异常') from None
    except httpx.HTTPError:
        raise ValueError('通知发送网络请求失败，结果未确认；请检查网络后重试') from None


# ---------------------------------------------------------------- target rules

def _serverchan_url(value):
    text = value.strip()
    if not text:
        raise ValueError('请填写 Server酱 的 SENDKEY')
    if '://' not in text:
        if not text.replace('-', '').replace('_', '').isalnum() or len(text) < 8:
            raise ValueError('Server酱 SENDKEY 格式无效')
        return f'https://sctapi.ftqq.com/{text}.send'
    parts = urlsplit(text)
    if parts.scheme != 'https' or parts.hostname != 'sctapi.ftqq.com' or parts.username or parts.password:
        raise ValueError('请填写 https://sctapi.ftqq.com/<SENDKEY>.send 形式的地址')
    key = parts.path.strip('/')
    if key.endswith('.send'):
        key = key[:-5]
    if not key or '/' in key:
        raise ValueError('Server酱 地址中缺少 SENDKEY')
    return f'https://sctapi.ftqq.com/{key}.send'


def _bark_url(value):
    text = value.strip()
    if not text:
        raise ValueError('请填写 Bark 的 KEY')
    if '://' not in text:
        if not text.replace('-', '').replace('_', '').isalnum() or len(text) < 6:
            raise ValueError('Bark KEY 格式无效')
        return f'https://api.day.app/{text}'
    parts = urlsplit(text)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('请填写 https://api.day.app/<KEY> 形式的地址')
    if not parts.path.strip('/'):
        raise ValueError('Bark 地址中缺少 KEY')
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/'), '', ''))


def _wecom_url(value):
    from .sharing import webhook_url
    return webhook_url(value)


def _feishu_url(value):
    text = value.strip()
    parts = urlsplit(text)
    try:
        valid = (parts.scheme == 'https' and parts.hostname == 'open.feishu.cn'
                 and parts.port in (None, 443) and not parts.username and not parts.password
                 and parts.path.startswith('/open-apis/bot/v2/hook/') and not parts.fragment and not parts.query)
    except ValueError:
        valid = False
    token = parts.path.rsplit('/', 1)[-1]
    if not valid or not token or token == 'hook':
        raise ValueError('请填写飞书群机器人的完整 Webhook 地址（https://open.feishu.cn/open-apis/bot/v2/hook/…）')
    return urlunsplit(('https', 'open.feishu.cn', parts.path, '', ''))


NORMALIZERS = {'serverchan': _serverchan_url, 'bark': _bark_url,
               'wecom': _wecom_url, 'feishu': _feishu_url}


def normalize_target(provider, value):
    normalizer = NORMALIZERS.get(provider)
    if normalizer is None:
        raise ValueError('未知的通知渠道')
    return normalizer(value)


# -------------------------------------------------------------------- settings

def _secret(value, label):
    if not isinstance(value, str) or (value and not value.startswith('dpapi:')):
        raise ValueError(f'{label}配置无效，请重新保存')
    return value


def settings():
    data = _settings_data().get('notifications', {})
    if not isinstance(data, dict):
        raise ValueError('通知配置格式无效')
    provider = data.get('provider', DEFAULT_PROVIDER)
    if provider not in PROVIDER_KEYS:
        provider = DEFAULT_PROVIDER
    events = data.get('events', {})
    if not isinstance(events, dict):
        events = {}
    return {
        'enabled': data.get('enabled', False) is True,
        'provider': provider,
        'target': _secret(data.get('target', ''), '通知地址'),
        'attach_image': data.get('attach_image', False) is True,
        'app_id': _secret(data.get('app_id', ''), '飞书 App ID'),
        'app_secret': _secret(data.get('app_secret', ''), '飞书 App Secret'),
        'events': {key: events.get(key, True) is not False for key in DEFAULT_EVENTS},
    }


def save_settings(provider, target, *, enabled, attach_image, app_id='', app_secret='',
                  events=None, clear_target=False):
    if provider not in PROVIDER_KEYS:
        raise ValueError('请选择通知渠道')
    if type(enabled) is not bool or type(attach_image) is not bool:
        raise ValueError('通知开关必须是开或关')
    if attach_image and not supports_image(provider):
        raise ValueError(f'{provider_label(provider)} 仅支持文字通知')
    previous = settings()
    value = {
        'enabled': enabled,
        'provider': provider,
        'attach_image': attach_image,
        'target': '' if clear_target else previous['target'],
        'app_id': previous['app_id'],
        'app_secret': previous['app_secret'],
        'events': {key: bool((events or {}).get(key, previous['events'][key])) for key in DEFAULT_EVENTS},
    }
    if str(target).strip():
        value['target'] = cloud.protect_password(normalize_target(provider, str(target)))
    if str(app_id).strip():
        value['app_id'] = cloud.protect_password(str(app_id).strip())
    if str(app_secret).strip():
        value['app_secret'] = cloud.protect_password(str(app_secret).strip())
    data = _settings_data()
    data['notifications'] = value
    _save_data(data)
    return value


# ----------------------------------------------------------------- machine info

def machine_code():
    """Stable short code derived from the Windows MachineGuid (never reversible)."""
    raw = ''
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography') as key:
            raw = str(winreg.QueryValueEx(key, 'MachineGuid')[0])
    except Exception:
        raw = ''
    if not raw:
        try:
            raw = f'{platform.node()}-{uuid.getnode()}'
        except Exception:
            raw = platform.node() or 'unknown'
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest().upper()
    return '-'.join(digest[i:i + 4] for i in range(0, 16, 4))


def computer_name():
    try:
        return platform.node() or socket.gethostname()
    except Exception:
        return ''


def lan_ip():
    """Outbound-interface address; a UDP connect sends no packets."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.settimeout(0.6)
            probe.connect(('223.5.5.5', 80))
            return probe.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return ''


def public_ip(timeout=6):
    for url in ('https://api.ipify.org', 'https://ifconfig.me/ip'):
        try:
            with httpx.Client(timeout=httpx.Timeout(timeout, connect=4),
                              trust_env=False, follow_redirects=False) as client:
                response = client.get(url)
            if response.status_code == 200:
                text = response.text.strip()
                if 0 < len(text) <= 45 and all(ch.isdigit() or ch in '.:' for ch in text):
                    return text
        except Exception:
            continue
    return ''


MACHINE_CACHE_TTL = 30 * 24 * 3600   # 每 30 天重新采集并校验一次


def machine_cache_path():
    from .path_settings import config_path
    return config_path().parent / 'cache' / 'machine.json'


def _read_machine_cache():
    try:
        value = json.loads(machine_cache_path().read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_machine_cache(value):
    try:
        from .atomic_files import write_json
        path = machine_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, value)
    except (OSError, ValueError):
        pass


def _cache_fresh(cache):
    stamp = cache.get('checked_at')
    return isinstance(stamp, (int, float)) and 0 <= time.time() - stamp < MACHINE_CACHE_TTL


def _collect_machine(full=True):
    value = {'machine_code': machine_code()}
    if full:
        value['computer_name'] = computer_name()
        value['lan_ip'] = lan_ip()
        value['public_ip'] = public_ip()
    return value


def _machine_items(cache, full=False):
    """Login carries addresses, computer name and the code; later events only the code."""
    if not full:
        return [('机器码', cache.get('machine_code') or '')]
    return [('内网', cache.get('lan_ip') or ''),
            ('公网', cache.get('public_ip') or '获取失败'),
            ('名字', cache.get('computer_name') or ''),
            ('机器码', cache.get('machine_code') or '')]


def machine_details(full=False, force=False):
    """Cached machine identity; re-collected only when missing or older than 30 days.

    ``full`` adds computer name and both addresses (startup only). A failed public
    lookup keeps the previous value and leaves the timestamp alone so the next
    launch retries instead of caching a failure for a month.
    """
    cache = _read_machine_cache()
    if not full:
        code = cache.get('machine_code')
        if code:
            return [('机器码', code)]
        fresh = machine_code()
        _write_machine_cache({**cache, 'machine_code': fresh})
        return [('机器码', fresh)]
    if not force and cache.get('machine_code') and _cache_fresh(cache):
        return _machine_items(cache, full=True)
    fresh = _collect_machine(full=True)
    got_public = bool(fresh.get('public_ip'))
    if not got_public:
        fresh['public_ip'] = cache.get('public_ip', '')
    merged = {**cache, **fresh}
    # Only a complete collection advances the 30-day clock; a failed public
    # lookup keeps the old timestamp so the next launch retries.
    merged['checked_at'] = time.time() if got_public else cache.get('checked_at', 0)
    _write_machine_cache(merged)
    return _machine_items(merged, full=True)


# --------------------------------------------------------------------- message

def format_message(event, batch='', when=None, details=None, path='', separated=None):
    """Operator template: 日期 / 时间 / 行为 / 批次 / 路径, then machine lines.

    ``path`` may contain newlines (batch import lists one file per line).
    ``separated`` forces the blank line before the machine block; ``None`` keeps
    it only when 批次 or 路径 is present.
    """
    stamp = when or datetime.now()
    matter = str(event or '').strip() or '通知'
    lines = [f'日期：{stamp:%Y-%m-%d}', f'时间：{stamp:%H:%M:%S}', f'行为：{matter}']
    involved = str(batch or '').strip()
    if involved:
        lines.append(f'批次：{involved}')
    # A leading newline is meaningful: 批量导入 lists one file per line after 路径：
    where = str(path or '').rstrip()
    if where.strip():
        lines.append(f'路径：{where}')
    extra = '\n'.join(f'{label}：{text}' for label, value in (details or ())
                      if (text := str(value or '').strip()))
    if separated is None:
        separated = bool(involved or where.strip())
    return '\n'.join(lines) + (('\n\n' if separated else '\n') + extra if extra else '')


def _image_for_wecom(png):
    from .sharing import image_for_wecom
    return image_for_wecom(png)


# ---------------------------------------------------------------- text senders

def _send_text_serverchan(url, event, text):
    reply = _post_form(url, {'title': str(event)[:32] or 'TMA', 'desp': text})
    if not isinstance(reply, dict) or reply.get('code') not in (0, '0'):
        raise ValueError(f"Server酱发送失败（code={reply.get('code') if isinstance(reply, dict) else '?'}），请检查 SENDKEY")


def _send_text_bark(url, event, text):
    reply = _post_json(url, {'title': str(event), 'body': text, 'group': 'ZzzHe TMA'})
    if not isinstance(reply, dict) or reply.get('code') not in (200, '200'):
        raise ValueError(f"Bark 发送失败（code={reply.get('code') if isinstance(reply, dict) else '?'}），请检查 KEY")


def _send_text_wecom(url, event, text):
    reply = _post_json(url, {'msgtype': 'text', 'text': {'content': text}})
    if not isinstance(reply, dict) or type(reply.get('errcode')) is not int:
        raise ValueError('企业微信返回的数据格式异常')
    if reply['errcode'] != 0:
        raise ValueError(f"企业微信发送失败（errcode={reply['errcode']}），请检查机器人设置或发送频率")


def _send_text_feishu(url, event, text):
    reply = _post_json(url, {'msg_type': 'text', 'content': {'text': text}})
    code = reply.get('code', reply.get('StatusCode')) if isinstance(reply, dict) else None
    if code not in (0, '0'):
        raise ValueError(f'飞书发送失败（code={code}），请检查机器人设置')


TEXT_SENDERS = {'serverchan': _send_text_serverchan, 'bark': _send_text_bark,
                'wecom': _send_text_wecom, 'feishu': _send_text_feishu}


# --------------------------------------------------------------- image senders

def _send_image_wecom(url, png):
    raw = _image_for_wecom(png)
    payload = {'msgtype': 'image',
               'image': {'base64': base64.b64encode(raw).decode('ascii'),
                         'md5': hashlib.md5(raw).hexdigest()}}
    reply = _post_json(url, payload)
    if not isinstance(reply, dict) or type(reply.get('errcode')) is not int:
        raise ValueError('企业微信返回的数据格式异常')
    if reply['errcode'] != 0:
        raise ValueError(f"企业微信图片发送失败（errcode={reply['errcode']}）")


def _feishu_token(app_id, app_secret):
    reply = _post_json('https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
                       {'app_id': app_id, 'app_secret': app_secret})
    token = reply.get('tenant_access_token') if isinstance(reply, dict) else None
    if not token:
        raise ValueError('飞书 App ID / App Secret 未通过校验，无法发送图片')
    return token


def _send_image_feishu(url, png, app_id, app_secret):
    if not app_id or not app_secret:
        raise ValueError('飞书发送图片需在通知设置中填写 App ID 与 App Secret；否则请取消勾选图片')
    token = _feishu_token(app_id, app_secret)
    try:
        with httpx.Client(timeout=TIMEOUT, trust_env=False, follow_redirects=False) as client:
            upload = client.post('https://open.feishu.cn/open-apis/im/v1/images',
                                 headers={'Authorization': f'Bearer {token}'},
                                 data={'image_type': 'message'},
                                 files={'image': ('plot.png', png, 'image/png')})
        if upload.status_code != 200:
            raise ValueError(f'飞书图片上传返回 HTTP {upload.status_code}')
        reply = upload.json()
    except httpx.HTTPError:
        raise ValueError('飞书图片上传网络请求失败，结果未确认') from None
    image_key = (reply.get('data') or {}).get('image_key') if isinstance(reply, dict) else None
    if not image_key:
        raise ValueError('飞书图片上传失败，请检查 App 权限（im:resource）')
    answer = _post_json(url, {'msg_type': 'image', 'content': {'image_key': image_key}})
    code = answer.get('code', answer.get('StatusCode')) if isinstance(answer, dict) else None
    if code not in (0, '0'):
        raise ValueError(f'飞书图片发送失败（code={code}）')


# ---------------------------------------------------------------------- public

def send_now(provider, target, event, batch='', png=None, *, app_id='', app_secret='',
             plain_target=False, path='', separated=None):
    """Blocking send used by the settings dialog's test button."""
    url = str(target) if plain_target else normalize_target(provider, str(target))
    text = format_message(event, batch, details=[('机器码', machine_code())], path=path,
                          separated=separated)
    TEXT_SENDERS[provider](url, event, text)
    if png:
        if provider == 'wecom':
            _send_image_wecom(url, png)
        elif provider == 'feishu':
            _send_image_feishu(url, png, app_id, app_secret)
        else:
            raise ValueError(f'{provider_label(provider)} 仅支持文字通知')
    return text


def _deliver(config, event, batch, png, details, path, separated):
    global _last_error
    try:
        url = normalize_target(config['provider'], cloud.protect_password(config['target'], decrypt=True))
        items = details() if callable(details) else details
        text = format_message(event, batch, details=items, path=path, separated=separated)
        TEXT_SENDERS[config['provider']](url, event, text)
        if png:
            if config['provider'] == 'wecom':
                _send_image_wecom(url, png)
            elif config['provider'] == 'feishu':
                _send_image_feishu(url, png,
                                   cloud.protect_password(config['app_id'], decrypt=True) if config['app_id'] else '',
                                   cloud.protect_password(config['app_secret'], decrypt=True) if config['app_secret'] else '')
        _last_error = ''
    except (ValueError, OSError) as exc:
        _last_error = str(exc)
    except Exception:
        _last_error = '通知发送失败，请检查配置和网络'


def notify(event, batch='', png=None, details=None, path='', separated=None):
    """Fire-and-forget: never blocks the caller, never raises to the UI.

    ``details`` may be a callable; it is evaluated on the worker thread, which is
    where a public-IP lookup belongs.
    """
    try:
        config = settings()
    except (ValueError, OSError):
        return False
    if not config['enabled'] or not config['target']:
        return False
    key = EVENT_KEYS.get(str(event).strip())
    if key is not None and not config['events'].get(key, True):
        return False
    if png is not None and (not config['attach_image'] or not supports_image(config['provider'])):
        png = None
    threading.Thread(target=_deliver, args=(config, event, batch, png, details, path, separated),
                     name='TMA-notify', daemon=True).start()
    return True


def last_error():
    return _last_error
