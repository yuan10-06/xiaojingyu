"""BrainN 桌宠独立进程（由主程序按需拉起）。"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
import urllib.request

PET_W = 320
PET_H = 320


class PetBridge:
    def __init__(self, control: str, token: str) -> None:
        self._control = control
        self._token = token
        self._win = None
        self._pos_timer: threading.Timer | None = None

    def _call(self, path: str, payload: dict | None = None) -> bytes:
        try:
            req = urllib.request.Request(
                self._control + path,
                data=json.dumps(payload or {}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-BrainN-Token": self._token,
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.read()
        except Exception:  # noqa: BLE001
            return b""

    @staticmethod
    def _allow_foreground() -> None:
        """桌宠此刻是前台进程，放行主进程的 SetForegroundWindow。"""
        if os.name != "nt":
            return
        try:
            import ctypes

            ctypes.windll.user32.AllowSetForegroundWindow(-1)
        except Exception:  # noqa: BLE001
            pass

    def ping(self) -> dict:
        return {"ok": True, "pet_process": True}

    def move_pet(self, dx: int, dy: int) -> bool:
        if self._win is None:
            return False
        try:
            self._win.move(
                int(self._win.x) + int(dx), int(self._win.y) + int(dy)
            )
            self._pos_soon()
            return True
        except Exception:  # noqa: BLE001
            return False

    def show_main(self) -> bool:
        self._allow_foreground()
        self._call("/api/desktop/pet/show-main")
        return True

    def hide_pet(self) -> bool:
        self._call("/api/desktop/pet/hide")
        threading.Timer(0.4, self._exit).start()
        return True

    def open_settings(self) -> bool:
        self._allow_foreground()
        self._call("/api/desktop/pet/settings")
        return True

    def quit_app(self) -> bool:
        self._call("/api/desktop/quit")
        threading.Timer(0.4, self._exit).start()
        return True

    def on_moved(self, x: int, y: int) -> None:
        self._pos_soon()

    def _pos_soon(self) -> None:
        if self._pos_timer is not None:
            self._pos_timer.cancel()
        self._pos_timer = threading.Timer(0.6, self._send_pos)
        self._pos_timer.daemon = True
        self._pos_timer.start()

    def _send_pos(self) -> None:
        if self._win is None:
            return
        try:
            self._call(
                "/api/desktop/pet/pos",
                {"x": int(self._win.x), "y": int(self._win.y)},
            )
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _exit() -> None:
        os._exit(0)


def apply_region(window) -> None:
    if os.name != "nt":
        return
    try:
        from System.Drawing import Region
        from System.Drawing.Drawing2D import GraphicsPath

        native = window.native
        w = int(native.ClientSize.Width) or PET_W
        h = int(native.ClientSize.Height) or PET_H
        d = max(8, min(44, w // 8, h // 8))
        path = GraphicsPath()
        path.AddArc(0, 0, d, d, 180, 90)
        path.AddArc(w - d, 0, d, d, 270, 90)
        path.AddArc(w - d, h - d, d, d, 0, 90)
        path.AddArc(0, h - d, d, d, 90, 90)
        path.CloseFigure()
        native.Region = Region(path)
    except Exception:  # noqa: BLE001
        pass


def watchdog(control: str, window) -> None:
    time.sleep(5)
    while True:
        try:
            with urllib.request.urlopen(control + "/api/status", timeout=4) as resp:
                if resp.status == 200:
                    time.sleep(15)
                    continue
        except Exception:  # noqa: BLE001
            pass
        try:
            window.destroy()
        except Exception:  # noqa: BLE001
            pass
        os._exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(description="BrainN 桌宠进程")
    parser.add_argument("--url", required=True)
    parser.add_argument("--control", required=True)
    parser.add_argument("--token", default="")
    parser.add_argument("--storage", default="")
    parser.add_argument("--x", type=int, default=None)
    parser.add_argument("--y", type=int, default=None)
    args = parser.parse_args()

    import webview

    x, y = args.x, args.y
    screens = getattr(webview, "screens", None) or []
    if screens:
        placed = False
        if x is not None and y is not None:
            for screen in screens:
                sx, sy = int(screen.x), int(screen.y)
                sw, sh = int(screen.width), int(screen.height)
                if (
                    sx - PET_W + 80 <= x <= sx + sw - 80
                    and sy - PET_H + 80 <= y <= sy + sh - 80
                ):
                    placed = True
                    break
        if not placed:
            base = screens[0]
            x = int(base.x) + int(base.width) - PET_W - 28
            y = int(base.y) + int(base.height) - PET_H - 72
    elif x is None or y is None:
        x, y = 1200, 700

    bridge = PetBridge(args.control, args.token)
    window = webview.create_window(
        "小鲸鱼 桌宠",
        args.url,
        js_api=bridge,
        width=PET_W,
        height=PET_H,
        x=int(x),
        y=int(y),
        frameless=True,
        transparent=True,
        on_top=True,
        resizable=False,
        focus=True,
        background_color="#000000",
        easy_drag=False,
        text_select=False,
    )
    bridge._win = window
    window.events.moved += bridge.on_moved
    window.events.loaded += lambda: (apply_region(window), bridge._pos_soon())
    window.events.closed += lambda: os._exit(0)
    threading.Thread(target=watchdog, args=(args.control, window), daemon=True).start()

    storage = args.storage or ""
    webview.start(
        gui="edgechromium",
        private_mode=False,
        storage_path=storage or None,
    )


if __name__ == "__main__":
    main()
