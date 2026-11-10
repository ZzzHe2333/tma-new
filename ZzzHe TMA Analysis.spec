# -*- mode: python ; coding: utf-8 -*-


from PyInstaller.utils.hooks import copy_metadata
from pathlib import Path

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[('tma_app\\assets', 'tma_app\\assets')] + copy_metadata('mcp'),
    hiddenimports=['uvicorn.loops.asyncio', 'uvicorn.protocols.http.h11_impl', 'uvicorn.lifespan.on'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'PyQt5', 'PyQt6', 'PySide2', 'torch', 'pandas', 'IPython', 'notebook', 'jupyterlab'],
    noarchive=False,
    optimize=0,
)
# Directory workers must not create matplotlib temporary folders before run.py
# can dispatch them: forced cancellation cannot run that hook's atexit cleanup.
# Retain normal GUI cache isolation with a conditional version of that hook.
if sum(name == 'pyi_rth_mplconfig' for name, _, _ in a.scripts) != 1:
    raise RuntimeError('Expected exactly one matplotlib runtime hook')
a.scripts = [(name, str(Path(SPECPATH) / 'tools/runtime_mpl_config.py'), kind)
             if name == 'pyi_rth_mplconfig' else (name, path, kind)
             for name, path, kind in a.scripts]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ZzzHe TMA Analysis',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    uac_admin=True,
    icon='tma_app/assets/cute/app.ico',
    version='tma_app/assets/cute/version_info.txt',
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ZzzHe TMA Analysis',
)
