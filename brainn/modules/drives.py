"""驱动力模型：内驱力 + 外驱力，作为提案方参与拍卖。"""
from __future__ import annotations

import random
import time
from typing import Any

from ..core.contracts import Percept, Proposal
from ..db import Store

DEFAULTS = {
    "rest": 40.0,
    "belonging": 50.0,
    "relationship": 45.0,
    "mattering": 40.0,
    "autonomy": 50.0,
    "self_esteem": 45.0,
    "task": 35.0,
    "curiosity": 40.0,
    "economy": 30.0,
}

SATIETY_FLOOR = 15.0

PRIORITIES = {
    "body_relation": {
        "rest": 1.00, "belonging": 0.95, "relationship": 0.90, "mattering": 0.80,
        "autonomy": 0.70, "self_esteem": 0.70, "task": 0.60, "curiosity": 0.50, "economy": 0.50,
    },
    "balanced": {
        "rest": 0.80, "belonging": 0.75, "relationship": 0.75, "mattering": 0.70,
        "autonomy": 0.70, "self_esteem": 0.70, "task": 0.65, "curiosity": 0.65, "economy": 0.60,
    },
    "rational": {
        "rest": 0.75, "belonging": 0.70, "relationship": 0.70, "mattering": 0.65,
        "autonomy": 0.85, "self_esteem": 0.75, "task": 0.85, "curiosity": 0.60, "economy": 0.85,
    },
}

INTENTS = {
    "rest": "rest",
    "belonging": "reach_out",
    "relationship": "maintain_relation",
    "mattering": "seek_recognition",
    "autonomy": "self_direct",
    "self_esteem": "protect_face",
    "task": "work",
    "curiosity": "explore",
    "economy": "earn",
}

COSTS = {
    "rest": {"time": 0.6, "energy": 0.0},
    "belonging": {"time": 0.2, "energy": 0.1},
    "relationship": {"time": 0.3, "energy": 0.1},
    "mattering": {"time": 0.2, "energy": 0.1},
    "autonomy": {"time": 0.4, "energy": 0.1},
    "self_esteem": {"time": 0.1, "energy": 0.0},
    "task": {"time": 0.7, "energy": 0.3},
    "curiosity": {"time": 0.2, "energy": 0.0},
    "economy": {"time": 0.6, "energy": 0.3},
}


class DriveModel:
    name = "drives"

    def __init__(self, store: Store, settings: dict[str, Any]):
        self.store = store
        cfg = settings.get("brainn", {}) or {}
        profile = str(cfg.get("drive_priority", "body_relation"))
        self.priorities = PRIORITIES.get(profile, PRIORITIES["body_relation"])
        raw = store.get_state("brainn_drives") or {}
        self.state = {
            "levels": {**DEFAULTS, **(raw.get("levels") or {})},
            # 实践反馈改变的是权重，不是一次性数值：慢变量，按天累积
            "practice_bias": {**{key: 0.0 for key in DEFAULTS}, **(raw.get("practice_bias") or {})},
            "finitude": dict(raw.get("finitude") or {}),
            "last_tick": float(raw.get("last_tick") or time.time()),
        }
        # 关系类驱动保留最低活跃度，避免连续聊天被扣到 0 后永远不再提案
        for key in ("belonging", "relationship"):
            self.state["levels"][key] = max(
                SATIETY_FLOOR, float(self.state["levels"].get(key, SATIETY_FLOOR))
            )

    def tick(self, now: float, ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ctx = ctx or {}
        hours = max(0.0, min(12.0, (now - float(self.state["last_tick"])) / 3600))
        if hours <= 0:
            return []
        asleep = bool(ctx.get("asleep"))
        levels = self.state["levels"]
        rates = {
            "rest": -12.0 if asleep else 4.0,
            "belonging": 2.0,
            "relationship": 1.5 / 24,
            "mattering": 1.5,
            "autonomy": 1.0,
            "self_esteem": 1.0,
            "task": 1.0 / 24,
            "curiosity": 1.0,
            "economy": 1.0 / 24,
        }
        for key, rate in rates.items():
            levels[key] = max(0.0, min(100.0, float(levels.get(key, 0)) + rate * hours))
        self.state["last_tick"] = now
        self.save()
        return []

    def apply_finitude(
        self,
        finitude: dict[str, Any] | None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """G4 → M5：有限性与生理状态把匮乏计往上顶，而不是只写一条 state。"""
        fin = finitude or {}
        body = body or {}
        levels = self.state["levels"]
        if not bool(fin.get("enabled", True)):
            self.state["finitude"] = {"enabled": False}
            self.save()
            return {}
        try:
            lifespan = float(fin.get("lifespan_days") or 0)
            remaining = float(fin.get("remaining_days") or lifespan)
        except (TypeError, ValueError):
            lifespan, remaining = 0.0, 0.0
        pressure = 0.0
        if lifespan > 0:
            pressure = max(0.0, min(0.35, 1.0 - remaining / lifespan))
        fatigue = max(0.0, min(100.0, float(body.get("fatigue") or 0)))
        hunger = max(0.0, min(100.0, float(body.get("hunger") or 0)))
        pain = max(0.0, min(100.0, float(body.get("pain") or 0)))
        raw_energy = fin.get("energy_remaining")
        energy = 100.0 if raw_energy is None else max(0.0, min(100.0, float(raw_energy)))
        damage_state = str(fin.get("damage_state") or "normal")

        # 身体越紧，休息与自我保存越强；寿命压力缓慢推高“被需要/关系”
        if fatigue >= 45:
            levels["rest"] = min(100.0, max(float(levels["rest"]), fatigue * 0.85))
        if hunger >= 65:
            levels["rest"] = min(100.0, max(float(levels["rest"]), hunger * 0.6))
        if pain >= 25:
            levels["rest"] = min(100.0, max(float(levels["rest"]), pain * 0.7))
        if energy <= 25:
            levels["rest"] = min(100.0, max(float(levels["rest"]), 60 + (25 - energy) * 1.2))
        if damage_state == "irreversible":
            levels["rest"] = min(100.0, max(float(levels["rest"]), 70))
        if pressure > 0:
            levels["mattering"] = min(100.0, float(levels["mattering"]) + pressure * 8)
            levels["relationship"] = min(100.0, float(levels["relationship"]) + pressure * 6)

        self.state["finitude"] = {
            "enabled": True,
            "pressure": round(pressure, 4),
            "remaining_days": round(remaining, 1),
            "fatigue": round(fatigue, 1),
            "hunger": round(hunger, 1),
            "pain": round(pain, 1),
            "energy_remaining": round(energy, 1),
            "damage_state": damage_state,
        }
        self.save()
        return dict(self.state["finitude"])

    def on_event(self, percept: Percept, ctx: dict[str, Any]) -> list:
        levels = self.state["levels"]
        text = str(percept.text or "")
        if text:
            # 每条消息只扣 3~5，保留 15 的下限
            drop = random.uniform(3.0, 5.0)
            levels["belonging"] = max(
                SATIETY_FLOOR, float(levels["belonging"]) - drop
            )
            levels["relationship"] = max(
                SATIETY_FLOOR, float(levels["relationship"]) - drop
            )
        if percept.kind == "link":
            levels["curiosity"] = max(0.0, float(levels["curiosity"]) - 5.0)
        if any(word in text for word in ("谢谢", "厉害", "夸", "不错", "牛")):
            levels["mattering"] = max(0.0, float(levels["mattering"]) - 3.0)
            levels["self_esteem"] = max(0.0, float(levels["self_esteem"]) - 2.0)
        self.save()
        return []

    def _priority(self, key: str) -> float:
        bias = float((self.state.get("practice_bias") or {}).get(key, 0) or 0)
        return max(0.05, min(1.0, float(self.priorities.get(key, 0.5)) + bias))

    def propose(self, ctx: dict[str, Any]) -> list[Proposal]:
        ranked = sorted(
            self.state["levels"].items(),
            key=lambda item: float(item[1]) / 100 * self._priority(item[0]),
            reverse=True,
        )[:3]
        proposals = []
        for key, level in ranked:
            priority = self._priority(key)
            strength = max(0.0, min(1.0, float(level) / 100 * priority))
            if strength < 0.05:
                continue
            proposals.append(
                Proposal(
                    source="drives",
                    intent=INTENTS[key],
                    strength=round(strength, 3),
                    expected_reward=round(min(1.0, 0.4 + priority * 0.4), 3),
                    cost=COSTS.get(key, {}),
                    payload={"drive": key, "level": round(float(level), 1)},
                )
            )
        return proposals

    def save(self) -> None:
        self.store.set_state("brainn_drives", self.state)

    def snapshot(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        top = sorted(
            self.state["levels"].items(),
            key=lambda item: float(item[1]) / 100 * self._priority(item[0]),
            reverse=True,
        )[:3]
        return {
            "levels": dict(self.state["levels"]),
            "priorities": dict(self.priorities),
            "practice_bias": dict(self.state.get("practice_bias") or {}),
            "finitude": dict(self.state.get("finitude") or {}),
            "top": [key for key, _ in top],
        }

    def apply_practice(self, deltas: dict[str, float]) -> dict[str, float]:
        """M11 → M9：劳动反馈改变驱力水平，也缓慢改变驱力权重。"""
        levels = self.state["levels"]
        bias = self.state.setdefault("practice_bias", {})
        for key, raw in (deltas or {}).items():
            if key not in DEFAULTS:
                continue
            try:
                delta = float(raw)
            except (TypeError, ValueError):
                continue
            levels[key] = max(0.0, min(100.0, float(levels.get(key, 0)) + delta))
            bias[key] = max(-0.25, min(0.25, float(bias.get(key, 0) or 0) + delta * 0.01))
        self.save()
        return {key: float(levels[key]) for key in deltas if key in levels}

    def learn(self, experience: dict[str, Any]) -> None:
        label = str((experience.get("emotion") or {}).get("label", "neutral"))
        levels = self.state["levels"]
        if label in ("happy", "love", "laugh"):
            levels["belonging"] = max(0.0, float(levels["belonging"]) - 5.0)
            levels["mattering"] = max(0.0, float(levels["mattering"]) - 3.0)
        elif label == "angry":
            levels["relationship"] = min(100.0, float(levels["relationship"]) + 3.0)
            levels["self_esteem"] = min(100.0, float(levels["self_esteem"]) + 2.0)
        elif label in ("sad", "tired", "anxious"):
            levels["belonging"] = max(0.0, float(levels["belonging"]) - 3.0)
        self.save()
