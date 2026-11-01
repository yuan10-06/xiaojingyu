"""系统托盘：显示主窗 / 退出。"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


class Tray:
    def __init__(self, app, image_path: Path) -> None:
        self._app = app
        self._image_path = Path(image_path)
        self._icon = None

    def start(self) -> None:
        try:
            import pystray
            from PIL import Image
        except Exception:  # noqa: BLE001
            log.warning("托盘依赖不可用", exc_info=True)
            return
        if not self._image_path.exists():
            return
        try:
            image = Image.open(self._image_path).convert("RGBA")
            image.thumbnail((64, 64))
            menu = pystray.Menu(
                pystray.MenuItem("显示小鲸鱼", self._show, default=True),
                pystray.MenuItem("显示桌宠", self._show_pet),
                pystray.MenuItem("隐藏桌宠", self._hide_pet),
                pystray.MenuItem("退出", self._quit),
            )
            self._icon = pystray.Icon("BrainN", image, "小鲸鱼", menu)
            self._icon.run_detached()
        except Exception:  # noqa: BLE001
            log.warning("托盘启动失败", exc_info=True)

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:  # noqa: BLE001
                pass
            self._icon = None

    def _show(self, icon, item) -> None:  # noqa: ANN001
        self._app.activate()

    def _show_pet(self, icon, item) -> None:  # noqa: ANN001
        self._app.show_pet()

    def _hide_pet(self, icon, item) -> None:  # noqa: ANN001
        self._app.hide_pet()

    def _quit(self, icon, item) -> None:  # noqa: ANN001
        self._app.request_quit()
