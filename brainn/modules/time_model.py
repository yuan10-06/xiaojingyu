"""时间有限性：只消费 M11 输出的日程占用，不再自己生成生活。

M8 的时间由“我在忙什么”决定：M11 先把日程与当前活动供料进来，M8 再算
注意力预算、机会成本与昼夜节律。摘掉 M11，时间就变空洞。
"""
from __future__ import annotations

import time
from typing import Any

from ..db import Store


class TimeBudgetModel:
    name = "time"

    def __init__(self, store: Store, clock, weights: dict[str, Any]):
        self.store = store
        self.clock = clock
        self.weights = weights
        self.state = store.get_state("brainn_time") or {}
        self.state.setdefault("occupancy", 0.25)
        self.state.setdefault("circadian", 0.6)
        self.state.setdefault("opportunity_cost", 0.40)
        self.state.setdefault(
            "remaining_life_years",
            float((weights or {}).get("remaining_life_years", 59.0)),
        )
        self.state.setdefault("last_tick", time.time())
        self.state.setdefault("schedule", [])
        self.state.setdefault("current", None)
        self.state.setdefault("next", None)
        self.state.setdefault("exam", {})

    # ---------- 节拍 ----------
    def tick(self, now: float, ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ctx = ctx or {}
        now_dt = self.clock.now()
        schedule = list(ctx.get("schedule") or [])
        current = ctx.get("activity")
        idle = ctx.get("idle")
        nxt = ctx.get("next")
        exam = ctx.get("exam") or {}
        asleep = bool(ctx.get("asleep"))
        if asleep:
            occupancy = 1.0
        elif current:
            occupancy = max(0.15, min(0.95, float(current.get("load") or 0.5)))
        elif idle:
            # 空闲时的生活只占一小部分注意力，她仍然聊得动
            occupancy = max(0.12, min(0.30, 0.10 + float(idle.get("load") or 0.2) * 0.35))
        else:
            occupancy = 0.35 if exam and 0 <= int(exam.get("days_left", 99)) <= 7 else 0.25
        hour = now_dt.hour
        if 10 <= hour < 17:
            circadian = 0.90
        elif 7 <= hour < 10 or 17 <= hour < 22:
            circadian = 0.70
        elif 0 <= hour < 6:
            circadian = 0.30
        else:
            circadian = 0.50
        fin = self.store.get_state("qt_finitude") or {}
        remaining_days = float(fin.get("remaining_days") or 0)
        lifespan_days = float(fin.get("lifespan_days") or 0)
        pressure = max(0.0, min(0.35, 1.0 - remaining_days / lifespan_days)) if lifespan_days else 0.0
        energy_remaining = float(fin.get("energy_remaining") or 0)
        energy_penalty = max(0.0, min(0.25, (40.0 - energy_remaining) / 40.0 * 0.25))
        damage_penalty = max(0.0, float(fin.get("capacity_penalty") or 0))
        self.state.update(
            {
                "occupancy": round(occupancy, 3),
                "circadian": circadian,
                "opportunity_cost": round(
                    max(0.0, min(1.0, 0.30 + occupancy * 0.40 + (1.0 - circadian) * 0.20
                        + pressure * 0.5 + energy_penalty + damage_penalty)), 3
                ),
                "remaining_life_years": round(remaining_days / 365, 2) if remaining_days else self.state.get("remaining_life_years"),
                "finitude_pressure": round(pressure, 4),
                "energy_remaining": round(energy_remaining, 2),
                "energy_penalty": round(energy_penalty, 3),
                "damage_penalty": round(damage_penalty, 3),
                "schedule": schedule,
                "current": current,
                "idle": idle,
                "next": nxt,
                "exam": exam,
                "last_tick": now,
            }
        )
        self.save()
        return []

    def save(self) -> None:
        self.store.set_state("brainn_time", self.state)

    def snapshot(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        return dict(self.state)

    def on_event(self, percept, ctx: dict[str, Any]) -> list:
        return []

    def learn(self, experience: dict[str, Any]) -> None:
        return None
