"""开机自启：只写当前用户的 Run 注册表项，不碰系统级设置。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

VALUE_NAME = "BrainN"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _target_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --autostart'
    script = Path(__file__).resolve().parents[2] / "desktop_main.py"
    return f'"{sys.executable}" "{script}" --autostart'


def is_enabled() -> bool:
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
        return bool(value)
    except OSError:
        return False


def set_enabled(on: bool) -> bool:
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if on:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _target_command())
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
