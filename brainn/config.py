"""配置加载：config/*.yaml + .env + 运行时路径。"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_env_root = os.getenv("BRAINN_ROOT", "").strip()
if _env_root:
    # 手机端由 Android 服务把可写目录传进来
    ROOT = Path(_env_root).resolve()
elif getattr(sys, "frozen", False):
    # 打包成 exe 后，配置与数据放在 exe 同级目录
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path) -> None:
    """极简 .env 解析，避免额外依赖。"""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"缺少配置文件：{path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """把手机端的 overrides 合并进默认配置；列表整体替换。"""
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


LEGACY_NAMES = ("陈雨棠", "干饭鱼", "鱼鱼")
HER_NAME = "小鲸鱼"


def _unify_persona_name(persona: dict[str, Any]) -> dict[str, Any]:
    """把旧版本留下的名字收口成小鲸鱼；只替换旧名/空名，保留之后的自定义。"""
    if not isinstance(persona, dict):
        return persona

    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            for old in LEGACY_NAMES:
                value = value.replace(old, HER_NAME)
            return value
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()}
        return value

    name = str(persona.get("name") or "").strip()
    nickname = str(persona.get("nickname") or "").strip()
    if not name or name in LEGACY_NAMES:
        persona["name"] = HER_NAME
    if not nickname or nickname in LEGACY_NAMES:
        persona["nickname"] = persona.get("name") or HER_NAME
    return scrub(persona)


def _load_merged(name: str) -> dict[str, Any]:
    base = _read_yaml(ROOT / "config" / f"{name}.yaml")
    override = ROOT / "config" / f"{name}_overrides.yaml"
    if override.exists():
        try:
            patch = yaml.safe_load(override.read_text(encoding="utf-8")) or {}
            if isinstance(patch, dict):
                _deep_merge(base, patch)
        except Exception:  # noqa: BLE001
            pass
    return base


def _align_weather(settings: dict[str, Any], persona: dict[str, Any]) -> None:
    """城市只有一个来源：人格页里的 city。

    架构页、世界和聊天天气读的都是 settings.weather，这里在加载配置时把
    人设城市同步进去，避免种子/旧安装留下的天气城市和人格页各说各的。
    """
    city = str(persona.get("city") or "").strip()
    if not city:
        return
    weather = settings.get("weather")
    if not isinstance(weather, dict):
        weather = {}
        settings["weather"] = weather
    if str(weather.get("city") or "").strip() != city:
        weather["city"] = city
        weather["lat"] = None
        weather["lon"] = None
    province = str(persona.get("province") or "").strip()
    if province:
        weather["province"] = province


@dataclass
class Config:
    settings: dict[str, Any]
    persona: dict[str, Any]
    root: Path = ROOT

    @property
    def data_dir(self) -> Path:
        # 桌面版用 BRAINN_DATA_DIR 把数据放到 %LOCALAPPDATA%，配置/网页留在运行根
        raw = os.getenv("BRAINN_DATA_DIR", "").strip()
        if raw:
            p = Path(raw).expanduser()
        else:
            p = self.root / self.settings.get("storage", {}).get("data_dir", "data")
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def log_dir(self) -> Path:
        p = self.root / self.settings.get("storage", {}).get("log_dir", "logs")
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def sticker_dir(self) -> Path:
        p = self.root / self.settings.get("storage", {}).get("sticker_dir", "assets/stickers")
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ganfanyu.db"

    @property
    def memory_db_path(self) -> Path | None:
        """共享记忆库：留空则与 db_path 同一个库。

        小鲸鱼接入后指向主聊天库，做到“记忆共用一份，运行状态各自独立”。
        """
        raw = str(self.settings.get("storage", {}).get("memory_db") or "").strip()
        if not raw:
            return None
        p = Path(raw)
        if not p.is_absolute():
            p = self.root / p
        return p

    @property
    def owner_qq(self) -> int:
        env = os.getenv("OWNER_QQ", "").strip()
        if env.isdigit():
            return int(env)
        return int(self.settings.get("owner_qq") or 0)

    @property
    def onebot_ws(self) -> str:
        return os.getenv("ONEBOT_WS") or self.settings["onebot"]["ws_url"]

    @property
    def onebot_token(self) -> str:
        return os.getenv("ONEBOT_TOKEN") or self.settings["onebot"].get("access_token", "")

    @property
    def deepseek_key(self) -> str:
        return os.getenv("DEEPSEEK_API_KEY", "").strip()

    def persona_name(self) -> str:
        return self.persona.get("name", HER_NAME)


def load_config() -> Config:
    load_env(ROOT / ".env")
    settings = _load_merged("settings")
    persona = _unify_persona_name(_load_merged("persona"))
    _align_weather(settings, persona)
    return Config(settings=settings, persona=persona)
