# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto', 'docx', 'pydantic', 'multipart']
hiddenimports += collect_submodules('routers')


a = Analysis(
    ['E:\\openhanako-work\\writing-app\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('E:\\openhanako-work\\writing-app\\routers', 'routers'), ('E:\\openhanako-work\\writing-app\\core', 'core'), ('E:\\openhanako-work\\writing-app\\services', 'services'), ('E:\\openhanako-work\\writing-app\\static', 'static'), ('E:\\openhanako-work\\writing-app\\templates', 'templates'), ('E:\\openhanako-work\\writing-app\\data', 'data')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='shiyi-gongfang',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
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
    name='shiyi-gongfang',
)
