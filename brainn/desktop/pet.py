"""桌面桌宠：优先原生 dsh-pet，运行时缺失时回退到 pywebview 小窗。

pywebview 6 在 Windows/WinForms 下多窗口支持不稳（子窗口创建在后台线程，
窗口可见但 WebView 不绘制），所以回退方案单独起一个进程。
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
from pathlib import Path

from .native_pet import NativePet

PET_W = 320
PET_H = 320


class PetWindow:
    def __init__(self, app) -> None:
        self._app = app
        self.enabled = False
        self.x: int | None = None
        self.y: int | None = None
        self.token = secrets.token_hex(16)
        self.process: subprocess.Popen | None = None
        self._save_timer: threading.Timer | None = None
        self.native = NativePet(app)
        self.use_native = False
        self._load()

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    def _state_path(self) -> Path:
        from . import paths

        return paths.app_home() / "pet.json"

    def _load(self) -> None:
        try:
            data = json.loads(self._state_path().read_text(encoding="utf-8-sig"))
            self.enabled = bool(data.get("enabled"))
            self.x = int(data["x"]) if data.get("x") is not None else None
            self.y = int(data["y"]) if data.get("y") is not None else None
        except Exception:  # noqa: BLE001
            # 首次安装（还没有 pet.json）：默认把桌宠打开，否则新用户看不到她
            self.enabled = True
            self.x = self.y = None

    def _save(self) -> None:
        try:
            self._state_path().write_text(
                json.dumps(
                    {"enabled": self.enabled, "x": self.x, "y": self.y},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            pass

    def _schedule_save(self) -> None:
        if self._save_timer is not None:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(0.6, self._save)
        self._save_timer.daemon = True
        self._save_timer.start()

    def report_position(self, x: int, y: int) -> None:
        self.x, self.y = int(x), int(y)
        self._schedule_save()

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    # ------------------------------------------------------------------
    # 进程
    # ------------------------------------------------------------------
    def _command(self) -> list[str]:
        from . import paths

        url = (
            f"http://127.0.0.1:{self._app.port}/whale/pet_overlay.html"
            f"?desktop=1&theme={self._app.ui_theme}&v=p2-3"
        )
        args = [
            "--url",
            url,
            "--control",
            f"http://127.0.0.1:{self._app.port}",
            "--token",
            self.token,
            "--storage",
            str(paths.app_home() / "webview_pet"),
        ]
        if self.x is not None and self.y is not None:
            args += ["--x", str(self.x), "--y", str(self.y)]
        if getattr(sys, "frozen", False):
            return [sys.executable, "--pet-process"] + args
        script = Path(__file__).resolve().parents[2] / "desktop_pet.py"
        return [sys.executable, str(script)] + args

    def _spawn(self) -> None:
        if self.is_running():
            return
        from . import paths

        log_path = paths.app_home() / "pet.log"
        try:
            log = open(log_path, "ab")
        except Exception:  # noqa: BLE001
            log = subprocess.DEVNULL
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        try:
            self.process = subprocess.Popen(
                self._command(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                creationflags=flags,
                close_fds=True,
            )
        except Exception:  # noqa: BLE001
            self.process = None

    def _stop_process(self) -> None:
        proc = self.process
        self.process = None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------
    def show(self) -> None:
        self.enabled = True
        self._save()
        ok = self.native.show()
        if ok:
            self.use_native = True
            self._stop_process()
        else:
            self.use_native = False
            self._spawn()
        self._app._sync_pet_ui(True)

    def hide(self) -> None:
        self.enabled = False
        self._save()
        if self.use_native:
            self.native.shutdown()
        self.use_native = False
        self._stop_process()
        self._app._sync_pet_ui(False)

    def destroy(self) -> None:
        self._save()
        self.native.shutdown()
        self.use_native = False
        self._stop_process()

    def restart(self) -> None:
        """保留开关与位置，只换一个新进程，用于让桌宠读到新的 API Key。"""
        if not self.enabled:
            return
        if self.use_native:
            self.native.shutdown()
        self.use_native = False
        self._stop_process()
        self.show()

    def say(self, text: str) -> bool:
        if not (self.enabled and self.use_native):
            return False
        return self.native.say(text)
