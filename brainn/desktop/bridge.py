"""桌面桥接：暴露给网页的 pywebview JS API。

网页里原本调用 window.Android；桌面版由 desktop/bridge.js 把同一个名字
映射到这里的方法，手机端原生桥接完全不受影响。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import webbrowser
from pathlib import Path

from . import autostart

log = logging.getLogger(__name__)


class DesktopBridge:
    def __init__(self, app) -> None:
        # 私有属性：pywebview 会把 js_api 的公开属性递归序列化，
        # 暴露 app 会一路走到 WinForms 的 AccessibilityObject 导致递归溢出
        self._app = app

    def ping(self) -> dict:
        return {"ok": True, "desktop": True, "version": self._app.version}

    # ------------------------------------------------------------------
    # 文件对话框
    # ------------------------------------------------------------------
    def _run_on_ui(self, func):
        """把调用切到 WinForms 主线程。

        pywebview 的 JS API 回调跑在 worker 线程里，WinForms 的文件对话框
        在非 UI 线程上会直接抛异常并返回空值 —— 用户看到的就是“点了没反应”。
        这里用 form.Invoke 回到 UI 线程，再由 UI 线程自己拥有这个模态对话框。
        """
        window = getattr(self._app, "window", None)
        gui = getattr(window, "gui", None) if window is not None else None
        form = getattr(gui, "form", None)
        if form is None:
            return func()
        try:
            if not bool(form.InvokeRequired):
                return func()
            from webview.platforms.winforms import WinForms  # pythonnet 已由 pywebview 初始化

            box: dict = {}
            form.Invoke(WinForms.MethodInvoker(lambda: box.__setitem__("value", func())))
            return box.get("value")
        except Exception:  # noqa: BLE001
            log.warning("切到 UI 线程失败，退回当前线程", exc_info=True)
            return func()

    def _pick_folder(self, initial: str = "") -> dict:
        """弹系统文件夹选择；返回 {path} / {canceled} / {error}。"""
        import webview

        window = getattr(self._app, "window", None)
        if window is None:
            return {"error": "no_window"}
        start = str(initial or "").strip()
        if not start or not Path(start).is_dir():
            downloads = Path.home() / "Downloads"
            start = str(downloads if downloads.is_dir() else Path.home())

        holder: dict = {}

        def run():
            form = getattr(getattr(window, "gui", None), "form", None)
            if form is not None:
                try:
                    form.Activate()
                except Exception:  # noqa: BLE001
                    pass
            try:
                picked = window.create_file_dialog(
                    webview.FileDialog.FOLDER,
                    directory=start,
                    allow_multiple=False,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("文件夹选择框弹不出", exc_info=True)
                holder["error"] = "dialog_failed: " + str(exc)[:120]
                return
            if not picked:
                holder["canceled"] = True
                return
            holder["path"] = str(
                picked[0] if isinstance(picked, (list, tuple)) else picked
            ).strip()

        self._run_on_ui(run)
        return holder

    def choose_directory(self, directory: str = "") -> str:
        """弹系统文件夹选择框，返回选中目录；取消返回空字符串。"""
        return str(self._pick_folder(directory).get("path") or "")

    def save_memory_export(self, path: str, name: str = "") -> dict:
        """把已打包好的全量记忆 zip 复制到用户选的文件夹（U 盘/高速磁盘）。"""
        src = Path(str(path or ""))
        if not src.is_file():
            return {"ok": False, "error": "missing_file"}
        picked = self._pick_folder("")
        if picked.get("error"):
            return {"ok": False, "error": str(picked["error"])}
        folder = str(picked.get("path") or "")
        if not folder:
            return {"ok": False, "canceled": True}
        target = Path(folder) / (str(name or "").strip() or src.name)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                n = 2
                while True:
                    candidate = target.with_name(f"{target.stem}-{n}{target.suffix}")
                    if not candidate.exists():
                        target = candidate
                        break
                    n += 1
            shutil.copy2(src, target)
            return {
                "ok": True,
                "path": str(target),
                "bytes": target.stat().st_size,
                "dir": folder,
            }
        except OSError as exc:
            return {"ok": False, "error": str(exc)[:160]}

    def open_url(self, url: str) -> bool:
        target = str(url or "").strip()
        if not target.startswith(("http://", "https://")):
            return False
        webbrowser.open(target)
        return True

    def quit(self) -> bool:
        self._app.request_quit()
        return True

    def set_window_active(self, active: bool) -> None:
        self._app.window_active = bool(active)

    def set_theme(self, theme: str) -> bool:
        self._app.ui_theme = str(theme or "sakura")
        return True

    def toggle_fullscreen(self) -> bool:
        try:
            return self._app.toggle_main_fullscreen()
        except Exception:  # noqa: BLE001
            return False

    def window_is_fullscreen(self) -> bool:
        return self._app.is_main_fullscreen()

    def minimize_window(self) -> bool:
        return self._app.minimize_main()

    def toggle_maximize(self) -> bool:
        return self._app.toggle_maximize()

    def close_window(self) -> bool:
        return self._app.close_main_window()

    def window_is_maximized(self) -> bool:
        return self._app.is_main_maximized()

    def show_pet(self) -> bool:
        self._app.show_pet()
        return True

    def hide_pet(self) -> bool:
        self._app.hide_pet()
        return True

    def notify_status(self) -> str:
        return json.dumps({"enabled": self._app.notifier.available})

    def test_notification(self) -> bool:
        self._app.test_notification()
        return True

    def open_notification_settings(self) -> bool:
        try:
            os.startfile("ms-settings:notifications")
            return True
        except Exception:  # noqa: BLE001
            return False

    def desktop_settings(self) -> str:
        return json.dumps(
            {
                "autostart": autostart.is_enabled(),
                "close_to_tray": bool(self._app.close_to_tray),
                "hotkeys_ok": bool(self._app.hotkeys.ok),
            },
            ensure_ascii=False,
        )

    def set_autostart(self, on: bool) -> bool:
        return autostart.set_enabled(bool(on))

    def set_close_to_tray(self, on: bool) -> bool:
        self._app.set_close_to_tray(bool(on))
        return True
