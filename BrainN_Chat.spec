# -*- mode: python ; coding: utf-8 -*-
"""单机聊天版打包配置：窗口程序，配置、数据与图库外置。"""
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("tzdata")

a = Analysis(
    ["chat_main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BrainN_Chat",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="BrainN_Chat",
)
