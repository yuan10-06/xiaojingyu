# -*- mode: python ; coding: utf-8 -*-
"""小鲸鱼 桌面版打包（onedir）。

入口是 desktop_main.py（pywebview 窗口 + 原生桌宠），web/config/assets
在构建脚本里复制到 exe 同级，运行时由 brainn.desktop.paths.resource_root 读取。
"""
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("tzdata")

a = Analysis(
    ["desktop_main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=["webview.platforms.edgechromium"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="小鲸鱼",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=r"desktop_runtime\xiaojingyu.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="BrainN",
)
