"""G4 有限性设定：寿命、能耗上限、不可逆损伤阈值。

默认开启。它不只是记录：每日能耗会约束可用动作，损伤会永久降低载体能力，
寿命压力会进入时间预算与匮乏计。
"""
from __future__ import annotations

import time
from typing import Any

from ..db import Store

STATE_KEY = "qt_finitude"

DEFAULTS = {
    "enabled": True,
    "lifespan_days": 21585,      # 59 年 × 365
    "energy_limit": 100.0,
    "damage_threshold": 30.0,
}


def _cfg(settings: dict[str, Any] | None) -> dict[str, Any]:
    cfg = ((settings or {}).get("qt") or {}).get("finitude") or {}
    return {**DEFAULTS, **cfg}


def ensure_finitude(store: Store, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """启动时调用：缺则按配置写入；已有则只补缺失键，不覆盖人工修改。"""
    cfg = _cfg(settings)
    raw = store.get_state(STATE_KEY) or {}
    state = {**cfg, **raw} if isinstance(raw, dict) else dict(cfg)
    if not state.get("g4_version"):
        # v1 只写了阈值，没有能耗/损伤字段；升级到完整体时按新配置初始化
        state["damage_threshold"] = float(cfg.get("damage_threshold", 30))
        state["energy_limit"] = float(cfg.get("energy_limit", 100))
        state["energy_used_today"] = float(state.get("energy_used_today") or 0)
        state["energy_remaining"] = max(
            0.0, float(state.get("energy_limit") or 100) - state["energy_used_today"]
        )
        state["energy_state"] = "normal"
        state["damage"] = float(state.get("damage") or 0)
        state["damage_state"] = str(state.get("damage_state") or "normal")
        state["g4_version"] = 2
    now = time.time()
    if not state.get("born_at"):
        state["born_at"] = now
    lifespan = float(state.get("lifespan_days") or 0)
    if lifespan > 0:
        state["remaining_days"] = max(
            0.0, round(lifespan - (now - float(state["born_at"])) / 86400, 2)
        )
    else:
        state["remaining_days"] = float(state.get("remaining_days") or 0)
    state["updated_at"] = now
    store.set_state(STATE_KEY, state)
    return state


def finitude_state(store: Store) -> dict[str, Any]:
    return store.get_state(STATE_KEY) or {}


def remaining_days(store: Store) -> float:
    state = finitude_state(store)
    try:
        born = float(state.get("born_at") or 0)
        total = float(state.get("lifespan_days") or 0)
        if born and total:
            used = (time.time() - born) / 86400
            return max(0.0, round(total - used, 2))
    except (TypeError, ValueError):
        pass
    return float(state.get("remaining_days") or 0)


def hint_from_state(state: dict[str, Any] | None) -> str:
    """把 G4 状态压成一句 prompt 提示；没有明显压力时返回空串。"""
    data = state or {}
    if not bool(data.get("enabled", True)):
        return ""
    if str(data.get("damage_state") or "") == "irreversible":
        return "你身上有一处不可逆的损伤，累到一定程度会先疼；今天不会硬撑。"
    remaining = float(data.get("energy_remaining") or 100)
    if remaining <= 8:
        return "你今天几乎没力气了，句子会更短，能推掉的事就推掉。"
    if remaining <= 25:
        return "你今天有点透支，回消息会慢一点，不想长篇解释。"
    pressure = float(data.get("remaining_days") or 0) / max(
        1.0, float(data.get("lifespan_days") or 1)
    )
    if pressure < 0.85:
        return "你知道自己的时间不是无限的，做选择时会先算机会成本。"
    return ""


def finitude_hint(store: Store) -> str:
    return hint_from_state(finitude_state(store))


class FinitudeModel:
    """G4 完整体：寿命倒计时、每日能耗、不可逆损伤。"""

    def __init__(self, store: Store, settings: dict[str, Any] | None = None):
        self.store = store
        self.settings = settings or {}
        self.state = ensure_finitude(store, self.settings)

    def tick(
        self,
        now: float,
        body: dict[str, Any] | None = None,
        labor_delta: float = 0.0,
        asleep: bool = False,
    ) -> dict[str, Any]:
        state = ensure_finitude(self.store, self.settings)
        body = body or {}
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        if str(state.get("energy_day") or "") != today:
            state["energy_day"] = today
            state["energy_used_today"] = 0.0
        last = float(state.get("last_tick") or now)
        hours = max(0.0, min(12.0, (now - last) / 3600))
        used = float(state.get("energy_used_today") or 0)
        if asleep:
            used = max(0.0, used - 6.0 * hours)
        else:
            used += 1.0 * hours + max(0.0, float(labor_delta or 0)) * 0.35
        limit = max(1.0, float(state.get("energy_limit") or 100))
        used = min(limit, used)
        remaining = max(0.0, limit - used)

        fatigue = max(0.0, min(100.0, float(body.get("fatigue") or 0)))
        pain = max(0.0, min(100.0, float(body.get("pain") or 0)))
        damage = float(state.get("damage") or 0)
        if fatigue >= 85:
            damage += 0.15 * max(0.5, hours)
        if pain >= 60:
            damage += 0.25 * max(0.5, hours)
        threshold = max(1.0, float(state.get("damage_threshold") or 30))
        damage_state = str(state.get("damage_state") or "normal")
        if damage >= threshold:
            damage = threshold
            damage_state = "irreversible"
        state.update(
            {
                "energy_used_today": round(used, 2),
                "energy_remaining": round(remaining, 2),
                "energy_state": (
                    "depleted" if remaining <= 5 else "low" if remaining <= 20 else "normal"
                ),
                "damage": round(damage, 2),
                "damage_ratio": round(damage / threshold, 3) if threshold else 0,
                "damage_state": damage_state,
                "capacity_penalty": round(0.15 if damage_state == "irreversible" else 0, 3),
                "last_tick": now,
                "updated_at": now,
            }
        )
        self.store.set_state(STATE_KEY, state)
        self.state = state
        return state

    def can_act(self, cost: float = 5.0) -> bool:
        state = self.state
        if not bool(state.get("enabled", True)):
            return True
        return float(state.get("energy_remaining") or 0) >= float(cost)

    def hint_line(self) -> str:
        return hint_from_state(self.state)

    def snapshot(self) -> dict[str, Any]:
        state = self.state
        return {
            "energy_remaining": state.get("energy_remaining", 0),
            "energy_used_today": state.get("energy_used_today", 0),
            "energy_state": state.get("energy_state", "normal"),
            "damage": state.get("damage", 0),
            "damage_state": state.get("damage_state", "normal"),
            "damage_ratio": state.get("damage_ratio", 0),
            "remaining_days": state.get("remaining_days", 0),
            "capacity_penalty": state.get("capacity_penalty", 0),
        }

