"""全局快捷键：RegisterHotKey + 独立线程消息循环。

Ctrl+Alt+Space 显示/隐藏桌宠，Ctrl+Alt+B 回到主窗。
被其他程序占用时只跳过该组合，不影响程序其余功能。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import threading

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
WM_HOTKEY = 0x0312

HOTKEYS = (
    (1, MOD_CONTROL | MOD_ALT, 0x20, "pet"),
    (2, MOD_CONTROL | MOD_ALT, 0x42, "main"),
)


class Hotkeys:
    def __init__(self, app) -> None:
        self._app = app
        self.ok = False

    def start(self) -> None:
        if os.name != "nt":
            return
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        registered = []
        for hotkey_id, mods, vk, _ in HOTKEYS:
            if user32.RegisterHotKey(None, hotkey_id, mods, vk):
                registered.append(hotkey_id)
        self.ok = bool(registered)
        if not registered:
            return
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self._dispatch(int(msg.wParam))

    def _dispatch(self, hotkey_id: int) -> None:
        try:
            if hotkey_id == 1:
                self._app.toggle_pet()
            elif hotkey_id == 2:
                self._app.activate()
        except Exception:  # noqa: BLE001
            pass
