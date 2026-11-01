"""桌面版运行根目录。

手机端的 ROOT 是 seed 解压目录，结构是：
    config/  web/  assets/  data/  logs/

源码运行时网页在 mobile/web，桌面版用一个 .desktop_runtime 目录把
config/assets 按手机端结构摆好（用目录联接，不复制）；网页目录通过
BRAINN_WEB_DIR 单独指向 mobile/web。数据目录默认放
%LOCALAPPDATA%\\BrainN\\data，和手机端互不影响。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

APP_NAME = "BrainN"
TITLE = "小鲸鱼"


def app_home() -> Path:
    base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_NAME


def default_data_dir() -> Path:
    return app_home() / "data"


def _make_junction(link: Path, target: Path) -> None:
    """目录联接：Windows 下不需要管理员权限，也不复制大文件。"""
    if link.exists() or os.path.isjunction(link):
        return
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        link.symlink_to(target, target_is_directory=True)


def resource_root() -> Path:
    """源码里是仓库根；PyInstaller 打包后是 exe 所在目录（web/config/assets 同级）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def prepare_runtime_root(res: Path | None = None) -> Path:
    """返回一个带 config/assets/logs 的 ROOT，供 mobile_server 使用。"""
    res = res or resource_root()
    if getattr(sys, "frozen", False):
        # 打包版把 datas 放在 exe 同级（后续 spec 里设置），这里直接用资源根
        root = res
    else:
        root = res / ".desktop_runtime"
        root.mkdir(parents=True, exist_ok=True)
        _make_junction(root / "assets", res / "assets")
        _make_junction(root / "config", res / "config")
        (root / "logs").mkdir(parents=True, exist_ok=True)
    return root


def web_dir(res: Path | None = None) -> Path:
    """网页目录：源码在 mobile/web，打包后在资源根的 web/。"""
    res = res or resource_root()
    if getattr(sys, "frozen", False):
        return res / "web"
    return res / "mobile" / "web"


def resolve_data_dir(explicit: str | None, portable: bool, root: Path) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
    elif portable:
        path = root / "data"
    elif os.getenv("BRAINN_DATA_DIR", "").strip():
        path = Path(os.environ["BRAINN_DATA_DIR"]).expanduser()
    else:
        path = default_data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path
