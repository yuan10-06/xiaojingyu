"""G1 身体图式：当前载体的能力表。

不是遥测，而是“这具身体能做什么、不能做什么”：
传感器种类、执行器范围、能量来源、损伤阈值。
结果写入 state.qt_carrier，并注入 prompt 的能力边界。
"""
from __future__ import annotations

import os
import platform
import time
from typing import Any

from ..db import Store

STATE_KEY = "qt_carrier"

DEFAULT_PROFILES: dict[str, dict[str, Any]] = {
    "android": {
        "id": "android-phone",
        "label": "手机（Android）",
        "platform": "android",
        "sensors": ["摄像头", "麦克风", "定位", "日历", "通知", "电池"],
        "actuators": ["文字", "表情包", "图片", "链接", "通知", "下载", "换头像"],
        "unavailable": ["打电话", "发语音", "拍现实照片", "转账", "真实支付"],
        "energy": {"source": "battery", "damage_threshold": 0.05},
    },
    "pc": {
        "id": "pc-desktop",
        "label": "电脑（桌面）",
        "platform": "pc",
        "sensors": ["剪贴板", "屏幕", "网络", "系统通知", "电池/电源"],
        "actuators": ["文字", "表情包", "图片", "链接", "通知", "文件", "换头像"],
        "unavailable": ["打电话", "发语音", "拍现实照片", "转账", "真实支付"],
        "energy": {"source": "mains_or_battery", "damage_threshold": 0.05},
    },
}


def detect_key() -> str:
    """Android Chaquopy 会设置 ANDROID_DATA/ANDROID_ROOT；其余按桌面处理。"""
    if os.environ.get("ANDROID_DATA") or os.environ.get("ANDROID_ROOT"):
        return "android"
    return "pc"


def _profiles(settings: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    cfg = ((settings or {}).get("qt") or {}).get("carrier") or {}
    custom = cfg.get("profiles") or {}
    profiles = {**DEFAULT_PROFILES}
    for key, value in custom.items():
        if isinstance(value, dict):
            profiles[key] = {**profiles.get(key, {}), **value}
    return profiles


def ensure_carrier(store: Store, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """写入当前载体的能力表；已有则保留人工修改，只补缺失字段。"""
    cfg = ((settings or {}).get("qt") or {}).get("carrier") or {}
    profiles = _profiles(settings)
    active = str(cfg.get("active") or "auto").strip()
    key = detect_key() if active in ("", "auto") else active
    profile = profiles.get(key) or profiles["pc"]
    raw = store.get_state(STATE_KEY) or {}
    if isinstance(raw, dict) and str(raw.get("key") or "") == key:
        state = {**profile, **raw}
    else:
        # 换载体时以新载体能力表为准，避免上一台设备的字段残留
        state = dict(profile)
    state["key"] = key
    state["detected_at"] = state.get("detected_at") or time.time()
    state["updated_at"] = time.time()
    state["system"] = platform.system()
    store.set_state(STATE_KEY, state)
    return state


def carrier_state(store: Store) -> dict[str, Any]:
    return store.get_state(STATE_KEY) or {}


def carrier_text(state: dict[str, Any] | None = None) -> str:
    """给 prompt 用的一段能力边界；只写能力和限制，不写遥测数值。"""
    data = state or {}
    if not data:
        return ""
    label = str(data.get("label") or "当前载体")
    sensors = "、".join(str(x) for x in (data.get("sensors") or []) if str(x).strip())
    actuators = "、".join(str(x) for x in (data.get("actuators") or []) if str(x).strip())
    unavailable = "、".join(str(x) for x in (data.get("unavailable") or []) if str(x).strip())
    parts = [f"你现在在：{label}。"]
    if sensors:
        parts.append(f"能感知：{sensors}。")
    if actuators:
        parts.append(f"能做出：{actuators}。")
    if unavailable:
        parts.append(f"做不到：{unavailable}。")
    parts.append("只能声称载体真的做过的动作。")
    return "".join(parts)
