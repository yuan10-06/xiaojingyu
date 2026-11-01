"""Windows 通知：窗口不在前台时才弹，点击回到主窗口。"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, app) -> None:
        self._app = app
        try:
            import win11toast  # noqa: F401
            self._ok = True
        except Exception:  # noqa: BLE001
            self._ok = False

    @property
    def available(self) -> bool:
        return self._ok

    def show(self, title: str, text: str, force: bool = False) -> None:
        if not self._ok or not text:
            return
        if not force and getattr(self._app, "window_active", False):
            return
        threading.Thread(
            target=self._show,
            args=(str(title or "小鲸鱼"), str(text)[:120]),
            daemon=True,
        ).start()

    def _show(self, title: str, text: str) -> None:
        try:
            from win11toast import toast

            toast(title, text, duration="short", on_click=self._on_click)
        except Exception:  # noqa: BLE001
            log.warning("Windows 通知失败", exc_info=True)

    def _on_click(self, *args) -> None:  # noqa: ANN002
        self._app.activate()
