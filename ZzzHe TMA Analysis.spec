# -*- mode: python ; coding: utf-8 -*-


from PyInstaller.utils.hooks import copy_metadata

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
