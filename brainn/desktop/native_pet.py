"""原生 DSH 桌宠（dsh-pet 绿色包）的进程管理。

不重画桌宠：直接跑原版 Electron helper（独立模式），通过它的本机 HTTP
接口投喂气泡、注册右键菜单、读取点击、优雅退出。运行时缺失时返回 False，
由调用方回退到 pywebview 桌宠。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

PET_ID = "main"
OWNER = "BrainN"
DEFAULT_PORT = 3199
MENU_LABELS = ("打开小鲸鱼", "设置", "隐藏桌宠", "退出")
DEFAULT_CONFIG = """{
  // BrainN 电脑版桌宠：只显示桌面小窗，余额走 DeepSeek 官方接口
  "pets": [
    {
      "id": "main",
      "name": "小鲸鱼",
      "size": 420,
      "display": "desktop",
      "balanceEnabled": true,
      "whisperEnabled": false,
      "workStatusEnabled": false,
      "fixedEnabled": false,
      "position": { "corner": "bottom-right", "marginX": 24, "marginY": 24 }
    }
  ]
}
"""


class NativePet:
    def __init__(self, app) -> None:
        self._app = app
        self.process: subprocess.Popen | None = None
        self.port = 0
        self.token = ""
        self._menu_thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------
    # 路径
    # ------------------------------------------------------------------
    def _runtime_root(self) -> Path:
        from . import paths

        return paths.resource_root() / "desktop_runtime"

    def app_dir(self) -> Path:
        candidates = [
            self._runtime_root() / "dsh-pet-app",
            Path(os.getenv("LOCALAPPDATA", "")) / "BrainN" / "dsh-pet-app",
        ]
        for path in candidates:
            if (path / "lib" / "standalone.js").exists():
                return path
        return candidates[0]

    def electron_exe(self) -> Path | None:
        candidates = []
        env = os.getenv("DSH_PET_ELECTRON_PATH", "").strip()
        if env:
            candidates.append(Path(env))
        user_profile = os.getenv("USERPROFILE", "")
        if user_profile:
            candidates.append(Path(user_profile) / ".dsh" / "electron" / "electron.exe")
        candidates.append(self._runtime_root() / "electron" / "electron.exe")
        for path in candidates:
            if path.exists():
                return path
        return None

    def home_dir(self) -> Path:
        from . import paths

        return paths.app_home() / "dsh_pet_home"

    def runtime_file(self) -> Path:
        return self.home_dir() / "dsh-pet" / "standalone-runtime.json"

    def available(self) -> bool:
        return (
            self.electron_exe() is not None
            and (self.app_dir() / "lib" / "standalone.js").exists()
        )

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    # ------------------------------------------------------------------
    # 请求
    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        if not self.port or not self.token:
            return {}
        url = f"http://127.0.0.1:{self.port}/dsh-pet-7340{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("X-DSH-Pet-Token", self.token)
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                return json.loads(resp.read().decode() or "{}")
        except (urllib.error.URLError, OSError, ValueError):
            return {}

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def _config_path(self) -> Path:
        return self.home_dir() / "dsh-pet" / "main-config.jsonc"

    def _ensure_config(self) -> None:
        """插件首次运行会默认成 web 模式（不显示桌面小窗），这里写死 desktop。

        旧配置没有 position 时补一个右下角：插件默认的 top-right 在 150% 缩放下
        会把窗口算到屏幕外，桌宠看起来像没打开。
        display 被插件设置页改成 web/none 时也要拉回 desktop，否则 helper 根本
        不启动，主程序却会误判“桌宠已经显示”。
        """
        path = self._config_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                text = path.read_text(encoding="utf-8-sig")
                changed = False
                if '"position"' not in text:
                    text = re.sub(
                        r'("id"\s*:\s*"main"[^{}]*?)(\s*\n\s*)\}',
                        r'\1,\2  "position": { "corner": "bottom-right", "marginX": 24, "marginY": 24 }\2}',
                        text,
                        count=1,
                    )
                    changed = True
                fixed = re.sub(r'"display"\s*:\s*"web"', '"display": "desktop"', text)
                fixed = re.sub(r'"display"\s*:\s*"none"', '"display": "desktop"', fixed)
                if fixed != text:
                    text = fixed
                    changed = True
                if changed:
                    path.write_text(text, encoding="utf-8")
                return
            path.write_text(DEFAULT_CONFIG, encoding="utf-8")
        except (OSError, ValueError):
            pass

    def _has_desktop_helper(self) -> bool:
        """检查桌宠小窗进程是否真的起来了。

        standalone 服务起来不代表有窗口：display=web 时它只跑服务、不 spawn
        helper，主程序如果只看 runtime 文件就会误判成功，把 pywebview 桌宠关掉。
        这里按父进程链找 electron helper 子进程。
        """
        proc = self.process
        if os.name != "nt" or proc is None or proc.poll() is not None:
            return False
        root = int(proc.pid)
        try:
            import ctypes
            import ctypes.wintypes as wt

            class PROCESSENTRY32W(ctypes.Structure):
                _fields_ = [
                    ("dwSize", wt.DWORD),
                    ("cntUsage", wt.DWORD),
                    ("th32ProcessID", wt.DWORD),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", wt.DWORD),
                    ("cntThreads", wt.DWORD),
                    ("th32ParentProcessID", wt.DWORD),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wt.DWORD),
                    ("szExeFile", wt.WCHAR * 260),
                ]

            kernel32 = ctypes.windll.kernel32
            snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)
            if not snap or snap == -1:
                return False
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            parents: dict[int, int] = {}
            names: dict[int, str] = {}
            ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                pid = int(entry.th32ProcessID)
                parents[pid] = int(entry.th32ParentProcessID)
                names[pid] = str(entry.szExeFile or "").lower()
                ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
            kernel32.CloseHandle(snap)
            for pid, name in names.items():
                if pid == root or "electron" not in name:
                    continue
                cur = pid
                for _ in range(6):
                    parent = parents.get(cur, 0)
                    if parent == root:
                        return True
                    if not parent:
                        break
                    cur = parent
        except Exception:  # noqa: BLE001
            return False
        return False

    def _wait_helper(self, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._has_desktop_helper():
                return True
            if self.process is None or self.process.poll() is not None:
                return False
            time.sleep(0.25)
        return False

    def _debug(self, msg: str) -> None:
        try:
            path = self.home_dir().parent / "native_debug.log"
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        except OSError:
            pass

    def show(self) -> bool:
        electron = self.electron_exe()
        app_dir = self.app_dir()
        standalone = app_dir / "lib" / "standalone.js"
        self._debug(f"show start electron={electron} app_dir={app_dir} standalone={standalone.exists()}")
        if electron is None or not standalone.exists():
            self._debug("show abort: runtime missing")
            return False
        self._ensure_config()
        if self.is_running():
            if self._has_desktop_helper():
                return True
            # 服务在跑但桌面上没有小窗（配置刚从 web/none 拉回来），重启一次
            self.shutdown()
        home = self.home_dir()
        home.mkdir(parents=True, exist_ok=True)
        log_path = home.parent / "native_pet.log"
        try:
            log = open(log_path, "ab")
        except OSError:
            log = subprocess.DEVNULL
        env = dict(os.environ)
        env["ELECTRON_RUN_AS_NODE"] = "1"
        env["DSH_HOME"] = str(home)
        env["DSH_PET_ELECTRON_PATH"] = str(electron)
        flags = 0x08000000 if os.name == "nt" else 0
        try:
            self.process = subprocess.Popen(
                [str(electron), str(standalone), "--port", str(DEFAULT_PORT)],
                cwd=str(app_dir),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                creationflags=flags,
                close_fds=True,
            )
        except OSError as exc:
            self._debug(f"popen failed: {exc}")
            self.process = None
            return False
        info = self._wait_runtime(15)
        if not info:
            self._debug("wait runtime timeout")
            self.shutdown()
            return False
        self.port = int(info.get("port") or 0)
        self.token = str(info.get("token") or "")
        # 服务起来了 ≠ 桌面上有窗口：display=web 时不会 spawn helper。
        # 等不到桌宠小窗就当成失败，交给 pywebview 桌宠兜底。
        if not self._wait_helper(10):
            self._debug("wait helper timeout")
            self.shutdown()
            return False
        self._debug("show ok")
        self._register_menu()
        self._stop.clear()
        self._menu_thread = threading.Thread(target=self._menu_loop, daemon=True)
        self._menu_thread.start()
        return True

    def _wait_runtime(self, timeout: float) -> dict | None:
        pid = self.process.pid if self.process is not None else None
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                info = json.loads(self.runtime_file().read_text(encoding="utf-8-sig"))
                if int(info.get("pid") or 0) == pid and info.get("token"):
                    return info
            except (OSError, ValueError):
                pass
            if self.process is not None and self.process.poll() is not None:
                return None
            time.sleep(0.25)
        return None

    def shutdown(self) -> None:
        self._stop.set()
        if self.port and self.token:
            try:
                urllib.request.urlopen(
                    urllib.request.Request(
                        f"http://127.0.0.1:{self.port}/shutdown",
                        data=b"{}",
                        method="POST",
                        headers={"X-DSH-Pet-Token": self.token},
                    ),
                    timeout=5,
                ).read()
            except (urllib.error.URLError, OSError):
                pass
        proc = self.process
        self.process = None
        self.port = 0
        self.token = ""
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=4)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass

    # ------------------------------------------------------------------
    # 菜单与气泡
    # ------------------------------------------------------------------
    def _register_menu(self) -> None:
        self._request(
            "POST",
            "/menu/item",
            {"owner": OWNER, "labels": list(MENU_LABELS), "target": "desktop"},
        )

    def _menu_loop(self) -> None:
        while not self._stop.is_set():
            events = self._request("GET", f"/menu/events?owner={OWNER}&wait=1200")
            for label, hit in (events.get("events") or {}).items():
                if not hit:
                    continue
                try:
                    if label == "打开小鲸鱼":
                        self._app.activate()
                    elif label == "设置":
                        self._app.open_settings()
                    elif label == "隐藏桌宠":
                        self._app.hide_pet()
                    elif label == "退出":
                        self._app.request_quit()
                        return
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(0.2)

    def say(self, text: str) -> bool:
        body = str(text or "").strip()
        if not body or not self.is_running():
            return False
        result = self._request(
            "POST", f"/broadcast?pet={PET_ID}&surface=desktop", {"text": body}
        )
        return bool(result.get("ok"))
