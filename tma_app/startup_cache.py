"""Reuse font discovery for directory-based EXE installs, before importing MPL."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import uuid


def cache_key():
    # PyInstaller's default temp cache is necessary for one-file unpack paths.
    # Our directory release has stable resources. Isolate every install/move;
    # Matplotlib additionally versions its own fontlist JSON schema.
    resources = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    parts = [os.path.normcase(os.path.abspath(resources))]
    for fonts in (Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Fonts',
                  Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Microsoft/Windows/Fonts',
                  resources / 'matplotlib/mpl-data/fonts'):
        try: stamp = fonts.stat().st_mtime_ns
        except OSError: stamp = None
        parts.append(f'{fonts}:{stamp}')
    return hashlib.sha256('\n'.join(parts).encode('utf-8')).hexdigest()[:20]


def configure():
    """Return the cache directory, or leave PyInstaller's temporary fallback."""
    if not getattr(sys, 'frozen', False):
        return None
    from .path_settings import config_path
    from .ui_size import fallback_path
    primary = config_path()
    portable = fallback_path(primary)
    roots = [primary.parent]
    if portable is not None: roots.append(portable.parent)
    key = cache_key()
    for root in dict.fromkeys(roots):
        cache = root / 'cache/matplotlib' / key
        probe = cache / ('.write-' + uuid.uuid4().hex)
        created = False
        try:
            cache.mkdir(parents=True, exist_ok=True)
            # One bounded write: no mkstemp loop on read-only Windows folders.
            with probe.open('xb') as handle:
                created = True
                handle.write(b'')
            probe.unlink()
        except OSError:
            if created:
                try: probe.unlink(missing_ok=True)
                except OSError: pass
            continue
        os.environ['MPLCONFIGDIR'] = str(cache)
        return cache
    return None
