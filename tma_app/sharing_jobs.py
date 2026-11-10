"""Plain sharing configuration jobs; no Qt or filesystem calls from callbacks."""
import threading

_read_slots = threading.BoundedSemaphore(2)
_write_slots = threading.BoundedSemaphore(2)


def _read_document(cancelled, primary):
    from .path_settings import _read_settings
    if cancelled.is_set(): return None
    if not _read_slots.acquire(blocking=False):
        raise ValueError('仍有分享配置在后台读取，请稍后重新打开分享窗口。')
    try:
        if cancelled.is_set(): return None
        data = _read_settings(primary=primary)[1]
        return None if cancelled.is_set() else data
    finally:
        _read_slots.release()


def load_configuration(cancelled, primary):
    from .sharing import _parse_settings
    data = _read_document(cancelled, primary)
    if data is None: return None
    return _parse_settings(data.get('sharing', {}))


def load_form(cancelled, primary):
    from . import sharing, cloud_storage as cloud
    data = _read_document(cancelled, primary)
    if data is None: return None
    return {'sharing': sharing._parse_settings(data.get('sharing', {})),
            'cloud': cloud._parse_settings(data.get('cloud', {}))}


def _update_configuration(cancelled, primary, change):
    from .config_transaction import settings_transaction
    from .path_settings import _write_settings
    if cancelled.is_set(): return None
    if not _write_slots.acquire(blocking=False):
        raise ValueError('仍有分享设置在后台保存，请稍后重试。')
    try:
        with settings_transaction(primary):
            if cancelled.is_set(): return None
            data = _read_document(cancelled, primary)
            if data is None: return None
            result = change(data)
            if cancelled.is_set(): return None
            _write_settings(data, primary)
            return result
    finally:
        _write_slots.release()


def save_form(cancelled, primary, options):
    from . import sharing
    if cancelled.is_set(): return None
    value = sharing.settings_change(options['mount_id'], options['folder'],
        options['overwrite'], options['webhook'])
    def change(data):
        sharing.apply_settings(data, value, options['clear_webhook'])
        return {'saved': True}
    return _update_configuration(cancelled, primary, change)


def add_mount(cancelled, primary, mount):
    from . import cloud_storage as cloud
    if cancelled.is_set(): return None
    cloud.validate_mount(mount)
    def change(data):
        current = cloud._parse_settings(data.get('cloud', {}))
        if any(item['id'] == mount['id'] for item in current['mounts']):
            raise ValueError('云盘标识重复，请重新添加。')
        data['cloud'] = {**current, 'mounts': [*current['mounts'], mount]}
        return data['cloud']
    return _update_configuration(cancelled, primary, change)


def prepare_targets(cancelled, primary, dav, wecom):
    from . import sharing, cloud_storage as cloud
    data = _read_document(cancelled, primary)
    if data is None: return None
    config = sharing._parse_settings(data.get('sharing', {}))
    targets = []
    if dav:
        mounts = cloud._parse_settings(data.get('cloud', {}))['mounts']
        mount = next((m for m in mounts if m['id'] == config['mount_id']), None)
        if mount is None: raise ValueError('此云盘未挂载，请先在云盘窗口中配置')
        targets.append({'channel': 'webdav', 'mount': mount,
                        'folder': config['folder'], 'overwrite': config['overwrite']})
    if wecom:
        if not config['webhook']: raise ValueError('请先在分享设置中填写企业微信 Webhook')
        targets.append({'channel': 'wecom', 'webhook': config['webhook']})
    if not targets: raise ValueError('请选择至少一个分享渠道')
    return targets
