"""Invisible PNG/TIFF origin record bound to decoded pixels and export time.

This is an application origin marker, not a third-party authenticity certificate.
"""
from datetime import datetime
from io import BytesIO
import hashlib
import hmac
import json
from functools import lru_cache

from PIL import Image, PngImagePlugin

TAG = 'ZzzHeTMA-Origin'
_KEY = b'ZzzHeTMA-image-origin-v1-20261109'


@lru_cache(maxsize=1)
def local_machine_code():
    from .notifications import machine_code
    return machine_code()


def _pixels(image):
    rgba = image.convert('RGBA')
    return hashlib.sha256(str(rgba.size).encode() + rgba.tobytes()).hexdigest()


def _signature(record):
    body = json.dumps(record, sort_keys=True, separators=(',', ':')).encode()
    return hmac.new(_KEY, body, hashlib.sha256).hexdigest()


def stamp_image(data, format='PNG'):
    from . import __version__
    with Image.open(BytesIO(data)) as source:
        source.load()
        image = source.copy()
        info = dict(source.info)
    now = datetime.now().astimezone()
    from .frequency_watermark import embed
    machine = local_machine_code()
    from .machine_environment import snapshot
    environment = snapshot()
    image = embed(image, machine_code=machine)
    record = dict(schema=1, app='ZzzHe TMA Analysis', version=__version__,
                  exported_at=now.isoformat(timespec='seconds'), pixels=_pixels(image), machine_code=machine,
                  environment=environment)
    record['signature'] = _signature(record)
    payload = json.dumps(record, ensure_ascii=True, separators=(',', ':'))
    exif = image.getexif()
    exif[306] = now.strftime('%Y:%m:%d %H:%M:%S')
    exif[36867] = exif[306]  # DateTimeOriginal: export date for generated images.
    exif[36868] = exif[306]
    exif[271] = 'ZzzHe'
    exif[305] = 'ZzzHe TMA Analysis'
    exif[270] = TAG + ':' + payload
    output = BytesIO()
    options = dict(exif=exif.tobytes())
    if info.get('dpi'): options['dpi'] = info['dpi']
    if format.upper() == 'PNG':
        text = PngImagePlugin.PngInfo()
        for key in ('Author', 'Software'):
            if isinstance(info.get(key), str): text.add_text(key, info[key])
        text.add_text(TAG, payload)
        options['pnginfo'] = text
    image.save(output, format=format, **options)
    return output.getvalue()


def verify_image(path):
    """Return explicit missing/modified/verified outcomes; malformed input raises."""
    with Image.open(path) as image:
        image.load()
        payload = image.info.get(TAG)
        if not payload:
            description = image.getexif().get(270, '')
            if isinstance(description, str) and description.startswith(TAG + ':'):
                payload = description[len(TAG)+1:]
        if not payload:
            from .frequency_watermark import detect
            frequency = detect(image, extract_machine=True)
            return dict(status='frequency_only' if frequency['detected'] else 'missing',
                        frequency=frequency, machine_code=frequency.get('machine_code'))
        try:
            record = json.loads(payload)
            signature = record.pop('signature')
            valid = (record.get('schema') == 1 and record.get('app') == 'ZzzHe TMA Analysis'
                     and hmac.compare_digest(signature, _signature(record))
                     and record.get('pixels') == _pixels(image))
        except (ValueError, TypeError, KeyError, AttributeError):
            return dict(status='modified')
        return dict(status='verified' if valid else 'modified',
                    exported_at=record.get('exported_at', ''), version=record.get('version', ''),
                    machine_code=record.get('machine_code') if valid else None,
                    environment=record.get('environment', {}) if valid else {})


def verify_job(cancelled, path):
    if cancelled.is_set(): return None
    import os
    from tempfile import SpooledTemporaryFile
    # Hash and identify the same snapshot, even if the original path is replaced.
    result = {'path': os.path.abspath(os.fspath(path))}
    try:
        digest = hashlib.sha256()
        with SpooledTemporaryFile(max_size=16*1024*1024) as snapshot:
            with open(path, 'rb') as source:
                before = os.fstat(source.fileno())
                while True:
                    if cancelled.is_set(): return None
                    chunk = source.read(1024*1024)
                    if not chunk: break
                    digest.update(chunk)
                    snapshot.write(chunk)
                after = os.fstat(source.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('图片在读取过程中发生变化，请重新鉴定。')
            result['file_sha256'] = digest.hexdigest()
            snapshot.seek(0)
            try: result.update(verify_image(snapshot))
            except Exception as exc:
                result.update(status='unreadable', error=str(exc))
    except Exception as exc:
        result.update(status='unreadable', error=str(exc))
    return result
