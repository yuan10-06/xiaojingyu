"""桌面版主程序：单实例、启动本地服务、开 pywebview 窗口、退出清理。"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import json
import os
import socket
import threading
import time
import urllib.request
from pathlib import Path

from . import autostart, paths
from .bridge import DesktopBridge
from .hotkeys import Hotkeys
from .notify import Notifier
from .persona_seed import ensure_initial_persona
from .pet import PetWindow
from .splash import SplashHost
from .tray import Tray

APP_VERSION = "9.10"


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", int(port)))
        except OSError:
            return False
    return True


def pick_port(preferred: int = 8765) -> int:
    if preferred and _port_free(preferred):
        return int(preferred)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class SingleInstance:
    """Windows 命名互斥体：重复启动时唤醒已有窗口。"""

    ERROR_ALREADY_EXISTS = 183

    def __init__(self, name: str = "BrainN.Desktop") -> None:
        self.name = name
        self.handle = None

    def acquire(self) -> bool:
        if os.name != "nt":
            return True
        kernel32 = ctypes.windll.kernel32
        self.handle = kernel32.CreateMutexW(None, False, f"Local\\{self.name}")
        return kernel32.GetLastError() != self.ERROR_ALREADY_EXISTS

    @staticmethod
    def focus_existing() -> bool:
        if os.name != "nt":
            return False
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, paths.TITLE)
        if not hwnd:
            return False
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True


class DesktopApp:
    version = APP_VERSION

    def __init__(
        self,
        root: Path,
        data_dir: Path,
        web_dir: Path | None = None,
        port: int = 8765,
        debug: bool = False,
        window_smoke: float = 0.0,
        bridge_check: bool = False,
        ui_check: bool = False,
        pet_check: bool = False,
        autostart: bool = False,
    ) -> None:
        self.root = Path(root)
        self.data_dir = Path(data_dir)
        self.web_dir = Path(web_dir) if web_dir else self.root / "web"
        self.port = pick_port(port)
        self.debug = debug
        self.window_smoke = float(window_smoke or 0)
        self.bridge_check = bool(bridge_check)
        self.ui_check = bool(ui_check)
        self.pet_check = bool(pet_check)
        self.autostart = bool(autostart)
        self.window = None
        self.server_info: dict = {}
        self._server = None
        self.notifier = Notifier(self)
        self.pet = PetWindow(self)
        self.tray = Tray(self, self._tray_image())
        self.hotkeys = Hotkeys(self)
        self.window_active = True
        self._quitting = False
        self._fullscreen = True
        self._windowed_rect: tuple[int, int, int, int] | None = None
        self.ui_theme = "sakura"
        self._hicons: list[tuple[int, int]] = []
        self._load_prefs()

    def _tray_image(self) -> Path:
        for name in ("app_icon.png", "whale_girl.png", "whale_smile.png", "whale_silhouette.png"):
            path = self.web_dir / name
            if path.exists():
                return path
        return self.web_dir / "whale_girl.png"

    # ------------------------------------------------------------------
    # 本地服务
    # ------------------------------------------------------------------
    def start_server(self) -> None:
        os.environ["BRAINN_ROOT"] = str(self.root)
        os.environ["BRAINN_DATA_DIR"] = str(self.data_dir)
        os.environ["BRAINN_WEB_DIR"] = str(self.web_dir)
        os.environ.setdefault("BRAINN_DESKTOP", "1")
        # 源码运行时配置根是 .desktop_runtime，真正的 .env 在仓库根；
        # 先加载，后面的 load_config() 才能读到 DEEPSEEK_API_KEY。
        try:
            from brainn.config import load_env

            load_env(self.root / ".env")
            load_env(paths.resource_root() / ".env")
        except Exception:  # noqa: BLE001
            pass

        import mobile_server  # 必须在 BRAINN_ROOT 设置之后导入

        self._server = mobile_server
        mobile_server.PORT = self.port
        self.server_info = mobile_server.start(str(self.root))
        mobile_server.set_notify_hook(self._notify)
        mobile_server.set_desktop_hooks(
            {
                "pet_hide": self.hide_pet,
                "pet_restart": self.restart_pet,
                "show_main": self.activate,
                "settings": self.open_settings,
                "pet_pos": self.pet.report_position,
                "quit": self.request_quit,
                "theme": lambda: self.ui_theme,
            },
            self.pet.token,
        )
        mobile_server.set_splash_host(SplashHost(paths.resource_root(), paths.app_home()))
        self.wait_http()

    def wait_http(self, timeout: float = 25.0) -> None:
        deadline = time.time() + timeout
        last = ""
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/api/status", timeout=2
                ) as resp:
                    if resp.status == 200:
                        return
            except Exception as exc:  # noqa: BLE001
                last = str(exc)
                time.sleep(0.25)
        raise RuntimeError(f"本地服务没起来：{last}")

    def stop_server(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:  # noqa: BLE001
                pass

    def _notify(self, title: str, text: str) -> None:
        self.notifier.show(title, text)
        try:
            self.pet.say(text)
        except Exception:  # noqa: BLE001
            pass

    def test_notification(self) -> None:
        self.notifier.show("小鲸鱼", "通知测试：看到这条说明桌面通知已接通", force=True)

    def _poll_proactive(self) -> None:
        """把主动消息转给原生桌宠气泡（页面轮询只对网页版生效）。"""
        cursor: int | None = None
        while not self._quitting:
            try:
                url = f"http://127.0.0.1:{self.port}/api/proactive"
                if cursor is not None:
                    url += f"?since={cursor}"
                with urllib.request.urlopen(url, timeout=6) as resp:
                    data = json.loads(resp.read().decode() or "{}")
                if data.get("ok") and cursor is not None:
                    for item in data.get("items") or []:
                        text = str((item or {}).get("text") or "").strip()
                        if text:
                            self.pet.say(text)
                if data.get("last") is not None:
                    cursor = int(data["last"])
            except Exception:  # noqa: BLE001
                pass
            time.sleep(18)

    # ------------------------------------------------------------------
    # 窗口
    # ------------------------------------------------------------------
    def run(self) -> int:
        import webview

        if not (self.bridge_check or self.ui_check or self.pet_check or self.window_smoke > 0):
            try:
                ensure_initial_persona(self.root, self.data_dir)
            except Exception:  # noqa: BLE001
                pass
        self.start_server()
        storage = paths.app_home() / "webview"
        storage.mkdir(parents=True, exist_ok=True)

        state = self._load_window_state()
        kwargs = {
            "js_api": DesktopBridge(self),
            "width": state["width"],
            "height": state["height"],
            "min_size": (980, 640),
            "background_color": "#061426",
            "text_select": True,
            "frameless": True,
            "easy_drag": False,
            "fullscreen": False,
            "hidden": True,
        }
        if state.get("x") is not None and state.get("y") is not None:
            kwargs["x"] = state["x"]
            kwargs["y"] = state["y"]
            self._windowed_rect = (
                int(state["x"]),
                int(state["y"]),
                int(state["width"]),
                int(state["height"]),
            )

        self.window = webview.create_window(
            paths.TITLE, f"http://127.0.0.1:{self.port}/", **kwargs
        )
        self.window.events.closing += self._on_closing
        self.window.events.minimized += self._on_minimized
        self.window.events.restored += self._on_active
        self.window.events.shown += self._on_active
        self.window.events.maximized += self._on_active
        self.window.events.loaded += self._on_main_loaded
        self.window.events.closed += self._on_main_closed

        webview.start(
            self._after_start,
            gui="edgechromium",
            private_mode=False,
            storage_path=str(storage),
            debug=self.debug,
        )
        self.tray.stop()
        self.pet.destroy()
        self._save_window_state()
        self.stop_server()
        return 0

    def _after_start(self) -> None:
        self.tray.start()
        self.hotkeys.start()
        self._ensure_main_on_screen()
        self._apply_window_chrome()
        if not self.autostart:
            self.enter_fullscreen()
            try:
                self.window.show()
            except Exception:  # noqa: BLE001
                pass
            self._apply_fullscreen_bounds()
        # 窗口刚显示时 DWM 会重置部分属性，延迟再刷一次深色标题栏
        chrome_timer = threading.Timer(1.2, self._apply_window_chrome)
        chrome_timer.daemon = True
        chrome_timer.start()
        if not self.autostart:
            fs_timer = threading.Timer(1.2, self._apply_fullscreen_bounds)
            fs_timer.daemon = True
            fs_timer.start()
        if self.pet.enabled:
            self.pet.show()
        threading.Thread(target=self._poll_proactive, daemon=True).start()
        if self.bridge_check:
            threading.Thread(target=self._check_bridge, daemon=True).start()
        if self.ui_check:
            threading.Thread(target=self._check_ui, daemon=True).start()
        if self.pet_check:
            threading.Thread(target=self._check_pet, daemon=True).start()
        if self.window_smoke > 0:
            threading.Timer(self.window_smoke, self._close).start()

    def _on_minimized(self) -> None:
        self.window_active = False

    def _on_active(self) -> None:
        self.window_active = True
        if self._fullscreen:
            timer = threading.Timer(0.25, self._apply_fullscreen_bounds)
            timer.daemon = True
            timer.start()
        else:
            self._set_resize_frame(not self.is_main_maximized())

    def _on_closing(self) -> bool:
        """pywebview 的约定：处理器返回 False 才取消关闭。"""
        self._save_window_state()
        if self._quitting or not self.close_to_tray:
            return True
        self.window_active = False
        try:
            self.window.hide()
        except Exception:  # noqa: BLE001
            return True
        return False

    def activate(self) -> None:
        if self.window is None:
            return
        try:
            self.window.show()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.window.restore()
        except Exception:  # noqa: BLE001
            pass
        self._raise_main()
        self.window_active = True
        if self._fullscreen:
            timer = threading.Timer(0.3, self._apply_fullscreen_bounds)
            timer.daemon = True
            timer.start()

    def _raise_main(self) -> None:
        """从后台线程把主窗提到前台（SetForegroundWindow 会被前台锁拦截，先临时置顶再取消）。"""
        if os.name != "nt":
            return
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, paths.TITLE)
            if not hwnd:
                return
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0003)  # HWND_TOPMOST
            user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0003)  # HWND_NOTOPMOST
            user32.SetForegroundWindow(hwnd)
        except Exception:  # noqa: BLE001
            pass

    def _ensure_main_on_screen(self) -> None:
        """换过显示器/改过缩放后，把落在屏幕外的窗口挪回主屏中间。"""
        if os.name != "nt":
            return
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, paths.TITLE)
            if not hwnd:
                return
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            if user32.MonitorFromRect(ctypes.byref(rect), 0):  # MONITOR_DEFAULTTONULL
                return
            work = wintypes.RECT()
            user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0)  # SPI_GETWORKAREA
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            x = work.left + max(0, (work.right - work.left - width) // 2)
            y = work.top + max(0, (work.bottom - work.top - height) // 2)
            user32.SetWindowPos(hwnd, 0, int(x), int(y), 0, 0, 0x0001 | 0x0004)
        except Exception:  # noqa: BLE001
            pass

    def _apply_window_chrome(self) -> None:
        """Win11 圆角 + 深色标题栏，做出接近 Trae 的窗口外观。"""
        if os.name != "nt":
            return
        try:
            user32 = ctypes.windll.user32
            dwm = ctypes.windll.dwmapi
            hwnd = user32.FindWindowW(None, paths.TITLE)
            if not hwnd:
                return

            def attr(code: int, value: int) -> None:
                v = ctypes.c_int(value)
                dwm.DwmSetWindowAttribute(hwnd, code, ctypes.byref(v), ctypes.sizeof(v))

            attr(19, 1)  # DWMWA_USE_IMMERSIVE_DARK_MODE（旧版）
            attr(20, 1)  # 同上，Win10 20H1+
            attr(33, 1 if self._fullscreen else 2)  # 全屏不圆角，窗口态圆角
            attr(34, 0x00442A0E)  # 边框 #0E2A44
            attr(35, 0x00261406)  # 标题栏 #061426
            attr(36, 0x00FFF2E8)  # 标题文字 #E8F2FF
            self._apply_window_icon(user32, hwnd)
            self._set_resize_frame(not self._fullscreen and not self.is_main_maximized())
        except Exception:  # noqa: BLE001
            pass

    def _set_resize_frame(self, enabled: bool) -> None:
        """无边框窗口保留拖边缩放；最大化时去掉边框，避免超出屏幕 10px。"""
        hwnd = self._main_hwnd()
        if not hwnd:
            return
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, -16)  # GWL_STYLE
        style |= 0x00010000 | 0x00020000  # MAXBOX | MINBOX
        if enabled:
            style |= 0x00040000  # THICKFRAME
        else:
            style &= ~0x00040000
        user32.SetWindowLongW(hwnd, -16, style)
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)  # FRAMECHANGED|NOMOVE|NOSIZE|NOZORDER

    def _apply_window_icon(self, user32, hwnd: int) -> None:
        """把标题栏/任务栏的 Python 图标换成小鲸鱼。"""
        if not self._hicons:
            icon_path = paths.resource_root() / "desktop_runtime" / "xiaojingyu.ico"
            if not icon_path.exists():
                return
            user32.SendMessageW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]
            user32.LoadImageW.restype = ctypes.c_void_p
            for flag in (1, 0):  # ICON_SMALL / ICON_BIG
                hicon = user32.LoadImageW(
                    None, str(icon_path), 1, 0, 0, 0x00000010 | 0x00000040
                )
                if hicon:
                    self._hicons.append((flag, hicon))
        for flag, hicon in self._hicons:
            user32.SendMessageW(hwnd, 0x0080, flag, hicon)  # WM_SETICON

    def _main_hwnd(self) -> int:
        if os.name != "nt":
            return 0
        return int(ctypes.windll.user32.FindWindowW(None, paths.TITLE) or 0)

    def is_main_maximized(self) -> bool:
        hwnd = self._main_hwnd()
        return bool(hwnd and ctypes.windll.user32.IsZoomed(hwnd))

    def is_main_fullscreen(self) -> bool:
        return bool(self._fullscreen)

    def set_main_fullscreen(self, on: bool) -> bool:
        self._fullscreen = bool(on)
        return self._fullscreen

    def _monitor_rect(self) -> tuple[int, int, int, int] | None:
        """当前窗口所在显示器的物理边界（含任务栏区域）。"""
        if os.name != "nt":
            return None
        hwnd = self._main_hwnd()
        if not hwnd:
            return None
        user32 = ctypes.windll.user32

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", ctypes.c_uint),
            ]

        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        r = info.rcMonitor
        return int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top)

    def _apply_fullscreen_bounds(self) -> None:
        """用显示器物理边界钉死窗口：托盘恢复/最小化恢复后也不会缩回去。"""
        if os.name != "nt" or not self._fullscreen:
            return
        hwnd = self._main_hwnd()
        rect = self._monitor_rect()
        if not hwnd or not rect:
            return
        self._set_resize_frame(False)
        user32 = ctypes.windll.user32
        user32.SetWindowPos(
            hwnd,
            0,
            int(rect[0]),
            int(rect[1]),
            int(rect[2]),
            int(rect[3]),
            0x0004 | 0x0010 | 0x0020 | 0x0040,  # NOZORDER|NOACTIVATE|FRAMECHANGED|SHOWWINDOW
        )

    def enter_fullscreen(self) -> bool:
        if os.name != "nt":
            return False
        hwnd = self._main_hwnd()
        if not hwnd:
            return False
        if not self._fullscreen:
            # 统一用 pywebview 的逻辑尺寸，避免 150% 缩放时和物理像素混用
            if self.window is not None:
                try:
                    self._windowed_rect = (
                        int(self.window.x),
                        int(self.window.y),
                        int(self.window.width),
                        int(self.window.height),
                    )
                except Exception:  # noqa: BLE001
                    pass
        self._fullscreen = True
        self._apply_fullscreen_bounds()
        self._apply_window_chrome()
        return True

    def exit_fullscreen(self) -> bool:
        if os.name != "nt":
            return False
        hwnd = self._main_hwnd()
        if not hwnd:
            return False
        self._fullscreen = False
        rect = self._windowed_rect
        if rect is None:
            w, h = 1280, 860
            work = wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(
                0x0030, 0, ctypes.byref(work), 0
            )
            rect = (
                int(work.left + max(0, (work.right - work.left - w) // 2)),
                int(work.top + max(0, (work.bottom - work.top - h) // 2)),
                w,
                h,
            )
        self._set_resize_frame(True)
        try:
            self.window.resize(int(rect[2]), int(rect[3]))
            self.window.move(int(rect[0]), int(rect[1]))
        except Exception:  # noqa: BLE001
            ctypes.windll.user32.SetWindowPos(
                hwnd,
                0,
                int(rect[0]),
                int(rect[1]),
                int(rect[2]),
                int(rect[3]),
                0x0004 | 0x0010 | 0x0020,
            )
        self._apply_window_chrome()
        return True

    def toggle_main_fullscreen(self) -> bool:
        if self._fullscreen:
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()
        return bool(self._fullscreen)

    def minimize_main(self) -> bool:
        if self.window is None:
            return False
        try:
            self.window.minimize()
            return True
        except Exception:  # noqa: BLE001
            return False

    def toggle_maximize(self) -> bool:
        if self.window is None:
            return False
        zoomed = self.is_main_maximized()
        try:
            if zoomed:
                self.window.restore()
                self._set_resize_frame(True)
            else:
                self._set_resize_frame(False)
                self.window.maximize()
            return not zoomed
        except Exception:  # noqa: BLE001
            return zoomed

    def close_main_window(self) -> bool:
        if self.window is None:
            return False
        if self._quitting or not self.close_to_tray:
            self.request_quit()
            return True
        self._save_window_state()
        self.window_active = False
        try:
            self.window.hide()
        except Exception:  # noqa: BLE001
            self.request_quit()
        return True

    def _on_main_loaded(self) -> None:
        self._sync_pet_ui(self.pet.enabled)

    def _on_main_closed(self) -> None:
        self.pet.destroy()

    def show_pet(self) -> None:
        self.pet.show()

    def hide_pet(self) -> None:
        self.pet.hide()

    def restart_pet(self) -> None:
        """保存 API Key 后重启一次桌宠，让余额拿到新的 DEEPSEEK_API_KEY。"""
        self.pet.restart()

    def toggle_pet(self) -> None:
        if self.pet.enabled:
            self.pet.hide()
        else:
            self.pet.show()

    def open_settings(self) -> None:
        self.activate()
        self.main_eval("switchTab('settings')")

    def main_eval(self, js: str) -> None:
        if self.window is None:
            return
        try:
            self.window.evaluate_js(js)
        except Exception:  # noqa: BLE001
            pass

    def _sync_pet_ui(self, on: bool) -> None:
        flag = "1" if on else "0"
        self.main_eval(
            "try{localStorage.setItem('gf_pet_on','" + flag + "');}catch(e){};"
            "try{window.updatePetState&&updatePetState();}catch(e){}"
        )

    def request_quit(self) -> None:
        self._quitting = True
        self._close()

    def _close(self) -> None:
        self._quitting = True
        self._save_window_state()
        self.pet.destroy()
        if self.window is not None:
            self.window.destroy()

    # ------------------------------------------------------------------
    # 窗口位置记忆
    # ------------------------------------------------------------------
    def _state_path(self) -> Path:
        return paths.app_home() / "window.json"

    def _load_window_state(self) -> dict:
        default = {"width": 1280, "height": 860, "x": None, "y": None}
        try:
            raw = json.loads(self._state_path().read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return default
        width = int(raw.get("width") or 0)
        height = int(raw.get("height") or 0)
        if not (900 <= width <= 4000 and 600 <= height <= 3000):
            width, height = default["width"], default["height"]
        x, y = raw.get("x"), raw.get("y")
        try:
            x, y = int(x), int(y)
            if not (-10000 < x < 20000 and -10000 < y < 20000):
                x, y = None, None
        except (TypeError, ValueError):
            x, y = None, None
        return {"width": width, "height": height, "x": x, "y": y}

    def _save_window_state(self) -> None:
        if self.window is None:
            return
        try:
            if self._fullscreen and self._windowed_rect:
                x, y, width, height = self._windowed_rect
            else:
                x, y = int(self.window.x), int(self.window.y)
                width, height = int(self.window.width), int(self.window.height)
            data = {
                "width": int(width),
                "height": int(height),
                "x": int(x),
                "y": int(y),
            }
            self._state_path().write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # 桌面偏好
    # ------------------------------------------------------------------
    def _prefs_path(self) -> Path:
        return paths.app_home() / "desktop.json"

    def _load_prefs(self) -> None:
        try:
            raw = json.loads(self._prefs_path().read_text(encoding="utf-8-sig"))
            self.close_to_tray = bool(raw.get("close_to_tray", True))
        except Exception:  # noqa: BLE001
            self.close_to_tray = True

    def _save_prefs(self) -> None:
        try:
            self._prefs_path().write_text(
                json.dumps({"close_to_tray": self.close_to_tray}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            pass

    def set_close_to_tray(self, on: bool) -> None:
        self.close_to_tray = bool(on)
        self._save_prefs()

    # ------------------------------------------------------------------
    # 自动检查
    # ------------------------------------------------------------------
    def _check_bridge(self) -> None:
        time.sleep(3)
        try:
            raw = self.window.evaluate_js(
                "JSON.stringify({"
                "desktop: !!window.__BRAINN_DESKTOP__,"
                "android: !!window.Android,"
                "isDesktop: !!(window.Android && window.Android.isDesktop && window.Android.isDesktop()),"
                "api: !!(window.pywebview && window.pywebview.api),"
                "title: document.title"
                "})"
            )
            print("bridge-check:", raw)
            try:
                self.window.evaluate_js(
                    "window.pywebview.api.ping().then(function(r){window.__p0ping=JSON.stringify(r);})"
                )
                time.sleep(1)
                print("bridge-ping:", self.window.evaluate_js("window.__p0ping || ''"))
            except Exception as exc:  # noqa: BLE001
                print("bridge-ping-error:", exc)
            try:
                print(
                    "notify-check:",
                    self.window.evaluate_js(
                        "JSON.stringify({can: Android.canNotify(),"
                        "status: JSON.parse(Android.notifyStatus())})"
                    ),
                )
                self.window.evaluate_js("window.Android.testNotification()")
                time.sleep(2.5)
            except Exception as exc:  # noqa: BLE001
                print("notify-check-error:", exc)
            try:
                self.window.resize(1100, 700)
                self.window.move(120, 90)
                time.sleep(0.6)
            except Exception as exc:  # noqa: BLE001
                print("geometry-check-error:", exc)
        except Exception as exc:  # noqa: BLE001
            print("bridge-check-error:", exc)
        finally:
            self._close()

    # ------------------------------------------------------------------
    # 页面巡检
    # ------------------------------------------------------------------
    def _check_ui(self) -> None:
        time.sleep(4)
        try:
            self.window.evaluate_js(
                "window.__DSH_STARTUP_API__ && window.__DSH_STARTUP_API__.skip"
                " && window.__DSH_STARTUP_API__.skip()"
            )
        except Exception as exc:  # noqa: BLE001
            print("ui-skip-error:", exc)
        time.sleep(1.5)
        try:
            self.window.evaluate_js(
                "document.getElementById('heroEnter') &&"
                " document.getElementById('heroEnter').click()"
            )
            time.sleep(0.8)
            print(
                "ui-cards:",
                self.window.evaluate_js(
                    "JSON.stringify(Array.from(document.querySelectorAll('.homeCard'))"
                    ".map(function(c){return c.dataset.go;}))"
                ),
            )
            self.window.evaluate_js(
                "var c=document.querySelector('.homeCard[data-go=chat]');"
                " c && c.click()"
            )
            time.sleep(0.6)
            self.window.evaluate_js(
                "var c=document.querySelector('.homeCard[data-go=chat]');"
                " if (c && c.classList.contains('on')) c.click()"
            )
            time.sleep(1.0)
            print(
                "ui-enter:",
                self.window.evaluate_js(
                    "JSON.stringify({page: (typeof state!=='undefined'?state.page:'?'),"
                    " picker: (document.getElementById('homePicker')||{}).className||'',"
                    " nav: document.querySelectorAll('.nav').length,"
                    " navBtn: document.querySelectorAll('.nav button').length,"
                    " onCard: document.querySelectorAll('.homeCard.on').length})"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            print("ui-enter-error:", exc)
        tabs: list[str] = []
        try:
            raw = self.window.evaluate_js(
                "JSON.stringify(Array.from(document.querySelectorAll('.nav button'))"
                ".map(function(b){return b.dataset.tab;}))"
            )
            tabs = json.loads(raw) if raw else []
            print("ui-tabs:", tabs)
        except Exception as exc:  # noqa: BLE001
            print("ui-tabs-error:", exc)

        pages = ["chat", "world", "tool", "api", "pet", "settings", "food", "mall"]
        results = []
        for page in pages:
            try:
                self.window.evaluate_js(f"switchTab({json.dumps(page)})")
                time.sleep(0.45)
                info = json.loads(
                    self.window.evaluate_js(
                        "JSON.stringify({page: state.page,"
                        "active: (document.querySelector('.page.on')||{}).id||''})"
                    )
                )
                if page == "settings":
                    info["perm"] = json.loads(
                        self.window.evaluate_js(
                            "JSON.stringify({notify: (document.getElementById('permNotify')||{}).textContent,"
                            "camera: (document.getElementById('permCamera')||{}).textContent,"
                            "overlay: (document.getElementById('permOverlay')||{}).textContent})"
                        )
                    )
                if page == "pet":
                    info["ar"] = json.loads(
                        self.window.evaluate_js(
                            "JSON.stringify({text: (document.getElementById('startAr')||{}).textContent,"
                            "disabled: !!(document.getElementById('startAr')||{}).disabled})"
                        )
                    )
                results.append({"tab": page, **info})
            except Exception as exc:  # noqa: BLE001
                results.append({"tab": page, "error": str(exc)})
        print("ui-pages:", json.dumps(results, ensure_ascii=False))
        try:
            self.window.evaluate_js("switchTab('home')")
            time.sleep(0.5)
            print(
                "ui-home:",
                self.window.evaluate_js(
                    "JSON.stringify({cards: document.querySelectorAll('.homeCard').length,"
                    "brand: !!document.querySelector('.homeBrand')})"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            print("ui-home-error:", exc)
        try:
            before = json.loads(
                self.window.evaluate_js(
                    "JSON.stringify({theme: document.documentElement.dataset.theme})"
                )
            )
            self.window.evaluate_js("applyTheme('black')")
            time.sleep(0.4)
            whale = self.window.evaluate_js(
                "JSON.stringify({theme: document.documentElement.dataset.theme,"
                " dark: document.body.classList.contains('dark')})"
            )
            self.window.evaluate_js(f"applyTheme({json.dumps(before['theme'])})")
            print("ui-theme:", before, "->", whale)
        except Exception as exc:  # noqa: BLE001
            print("ui-theme-error:", exc)
        for name in ("memory.html", "whale.html"):
            try:
                self.window.load_url(f"http://127.0.0.1:{self.port}/{name}")
                time.sleep(2.2)
                print(
                    f"ui-{name}:",
                    self.window.evaluate_js(
                        "JSON.stringify({title: document.title,"
                        " body: document.body ? document.body.children.length : 0})"
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                print(f"ui-{name}-error:", exc)
        self._close()

    # ------------------------------------------------------------------
    # 桌宠巡检
    # ------------------------------------------------------------------
    def _check_pet(self) -> None:
        time.sleep(5)
        print("[pet-check] showing pet", flush=True)
        try:
            self.show_pet()
        except Exception as exc:  # noqa: BLE001
            print("[pet-check] show error:", exc, flush=True)
        time.sleep(4)
        print(
            "pet-process:",
            self.pet.is_running(),
            self.pet.process.pid if self.pet.process is not None else None,
            flush=True,
        )
        print(
            "pet-native:",
            self.pet.use_native,
            self.pet.native.is_running(),
            self.pet.native.port,
            flush=True,
        )
        try:
            import ctypes
            import ctypes.wintypes as wt

            user32 = ctypes.windll.user32
            found = []

            def cb(hwnd, _):
                n = user32.GetWindowTextLengthW(hwnd)
                if not n:
                    return True
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if "BrainN 桌宠" in buf.value or "dsh-pet" in buf.value:
                    r = wt.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(r))
                    found.append(
                        (
                            bool(user32.IsWindowVisible(hwnd)),
                            (r.left, r.top, r.right, r.bottom),
                        )
                    )
                return True

            user32.EnumWindows(ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)(cb), 0)
            print("pet-window:", found, flush=True)
        except Exception as exc:  # noqa: BLE001
            print("pet-window-error:", exc)
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/api/desktop/theme", timeout=5
            ) as resp:
                print("pet-theme:", resp.read().decode(), flush=True)
        except Exception as exc:  # noqa: BLE001
            print("pet-theme-error:", exc)
        print(
            "pet-state:",
            json.dumps(
                {"enabled": self.pet.enabled, "x": self.pet.x, "y": self.pet.y},
                ensure_ascii=False,
            ),
        )
        self._close()

    # ------------------------------------------------------------------
    # 无窗口冒烟
    # ------------------------------------------------------------------
    def smoke(self) -> int:
        self.start_server()
        result: dict = {
            "port": self.port,
            "root": str(self.root),
            "data_dir": str(self.data_dir),
            "needs_key": self.server_info.get("needs_key"),
            "db_exists": (self.data_dir / "ganfanyu.db").exists(),
            "notify": self.notifier.available,
            "notify_hook": bool(getattr(self._server, "NOTIFY_HOOK", None)),
            "http": {},
        }
        ok = True
        for path in ("/api/status", "/", "/desktop/bridge.js"):
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}{path}", timeout=8
                ) as resp:
                    body = resp.read()
                    result["http"][path] = {
                        "status": resp.status,
                        "bytes": len(body),
                    }
                    ok = ok and resp.status == 200
            except Exception as exc:  # noqa: BLE001
                result["http"][path] = {"error": str(exc)}
                ok = False
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/api/memory/list", timeout=8
            ) as resp:
                data = json.loads(resp.read().decode())
                result["memory_list_ok"] = data.get("ok")
        except Exception as exc:  # noqa: BLE001
            result["memory_list_error"] = str(exc)
            ok = False
        print(json.dumps(result, ensure_ascii=False, indent=2))
        self.stop_server()
        return 0 if ok else 1
