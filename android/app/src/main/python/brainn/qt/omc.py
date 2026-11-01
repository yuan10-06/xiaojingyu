"""OMC 全能记忆卡的专属字段：continuity 与 finitude。

卡片只负责保存与迁移，不参与推理。
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from ..db import Store
from .carrier import carrier_state
from .finitude import finitude_state, remaining_days

INSTANCE_KEY = "qt_instance_id"


def instance_id(store: Store) -> str:
    """本实例的稳定编号；首次调用生成并写入 state。"""
    current = store.get_state(INSTANCE_KEY)
    if isinstance(current, str) and current:
        return current
    value = "inst-" + uuid.uuid4().hex[:8]
    store.set_state(INSTANCE_KEY, value)
    return value


def card_fields(store: Store, source_instance: str = "", score: float = 1.0) -> dict[str, Any]:
    """导出卡片时写入的两个专属字段。"""
    current = instance_id(store)
    finitude = finitude_state(store)
    return {
        "continuity": {
            "source_instance": source_instance or current,
            "current_instance": current,
            "score": round(float(score), 3),
            "fork": None,
            "exported_at": time.time(),
        },
        "m0": store.get_state("qt_m0") or {},
        "m3": store.get_state("persona_knobs") or {},
        "m4": store.get_state("brainn_unconscious") or {},
        "carrier": carrier_state(store),
        "finitude": {
            "lifespan_days": finitude.get("lifespan_days"),
            "remaining_days": remaining_days(store),
            "energy_limit": finitude.get("energy_limit"),
            "damage_threshold": finitude.get("damage_threshold"),
            "damage": finitude.get("damage", 0),
            "damage_state": finitude.get("damage_state", "normal"),
            "enabled": bool(finitude.get("enabled", True)),
        },
    }
