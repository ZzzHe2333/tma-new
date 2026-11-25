"""Versioned JSON settings backups using local files or existing WebDAV mounts."""
import json
from .atomic_files import write_json
from .path_settings import config_path, _settings_data, _write_settings, validate_dialog_settings
from .config_transaction import settings_transaction

FILES=('appearance.json','icon-appearance.json','theme.json')
LIMIT=4*1024*1024


def snapshot():
    primary=config_path()
    with settings_transaction(primary):
        from .ui_size import saved_size, saved_icon_size
        from .color_theme import _load as saved_theme
        settings = _settings_data()
        files = {
            'appearance.json': {'version': 1, 'size': saved_size(primary=primary, data=settings)},
            'icon-appearance.json': {'version': 1, 'size': saved_icon_size(primary=primary)},
            'theme.json': {'version': 1, 'color': saved_theme(None, primary.with_name('theme.json'))},
        }
        return dict(format='ZzzHeTMA-settings', version=1, settings=settings, appearance=files)


def restore(raw):
    if len(raw)>LIMIT:raise ValueError('设置备份超过 4 MB 限制')
    data=json.loads(raw.decode('utf-8-sig'))
    if not isinstance(data,dict) or data.get('format')!='ZzzHeTMA-settings' or data.get('version')!=1:raise ValueError('请选择本软件导出的设置备份 JSON')
    settings=data.get('settings');files=data.get('appearance',{})
    if not isinstance(settings,dict) or not isinstance(files,dict) or set(files)-set(FILES):raise ValueError('设置备份格式无效')
    validate_dialog_settings(settings)
    from .sharing import _parse_settings as validate_sharing
    from .cloud_storage import _parse_settings as validate_cloud
    from .notifications import _parse_settings as validate_notifications
    validate_sharing(settings.get('sharing', {}))
    validate_cloud(settings.get('cloud', {}))
    validate_notifications(settings.get('notifications', {}))
    from .ui_size import PRESETS
    from .color_theme import CHOICES
    size_keys = {key for key, _, _ in PRESETS}
    color_keys = {key for key, _, _ in CHOICES}
    ui_size = settings.get('ui', {}).get('size', 'standard')
    if not isinstance(ui_size, str) or ui_size not in size_keys:
        raise ValueError('界面设置中的字号无效')
    for name, value in files.items():
        if not isinstance(value, dict):
            raise ValueError('界面设置格式无效')
        field = 'color' if name == 'theme.json' else 'size'
        allowed = color_keys if name == 'theme.json' else size_keys
        if not isinstance(value.get(field), str) or value[field] not in allowed:
            raise ValueError('界面设置中的字号或颜色无效')
    files = {
        'appearance.json': {'version': 1, 'size': ui_size},
        'icon-appearance.json': {'version': 1, 'size': 'standard'},
        'theme.json': {'version': 1, 'color': 'pink'},
        **files,
    }
    visibility=settings.get('feature_visibility',{})
    if not isinstance(visibility,dict) or any(not isinstance(v,list) or any(not isinstance(k,str) for k in v) for v in visibility.values()):raise ValueError('显隐设置格式无效')
    primary=config_path()
    with settings_transaction(primary):
        originals={name:json.loads(primary.with_name(name).read_text(encoding='utf-8-sig')) if primary.with_name(name).exists() else None for name in files}
        try:
            for name,value in files.items():write_json(primary.with_name(name),value)
            _write_settings(settings,primary)
        except Exception:
            for name,value in originals.items():
                if value is None:primary.with_name(name).unlink(missing_ok=True)
                else:write_json(primary.with_name(name),value)
            raise
    return '设置已导入，重启软件后全部生效。'


def run(cancelled, mode, target, mount=None):
    from pathlib import Path
    if cancelled.is_set():return ''
    exporting=mode=='export'
    if exporting:
        raw=json.dumps(snapshot(),ensure_ascii=False,indent=2).encode('utf-8')
        if len(raw)>LIMIT:raise ValueError('设置备份超过 4 MB 限制')
    if mount is None:
        path=Path(target)
        if path.resolve().parent==config_path().resolve().parent:raise ValueError('请在配置目录之外保存备份文件')
        if exporting:write_json(path,json.loads(raw))
        else:
            with path.open('rb') as stream:raw=stream.read(LIMIT+1)
    else:
        from .cloud_storage import WebDAV, remote_path
        dav=WebDAV(mount);remote=remote_path(target)
        with dav.client() as client:
            if exporting:
                with dav.request(client,'PUT',dav.url(remote),content=raw,headers={'Content-Type':'application/json; charset=utf-8'}) as response:
                    if response.status_code not in (200,201,204):dav.check(response,201)
            else:
                with dav.request(client,'GET',dav.url(remote)) as response:
                    dav.check(response);chunks=[];size=0
                    for chunk in response.iter_bytes():
                        size+=len(chunk)
                        if size>LIMIT:raise ValueError('设置备份超过 4 MB 限制')
                        if cancelled.is_set():return ''
                        chunks.append(chunk)
                    raw=b''.join(chunks)
    if cancelled.is_set():return ''
    return '设置备份已导出。' if exporting else restore(raw)
