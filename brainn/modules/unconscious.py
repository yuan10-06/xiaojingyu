"""无意识黑箱：习惯、条件反射、压抑区；只旁路表达，不改动作。"""
from __future__ import annotations

import random
import time
from typing import Any

from ..core.contracts import Decision
from ..db import Store


class UnconsciousModel:
    name = "unconscious"

    def __init__(self, store: Store, weights: dict[str, Any]):
        self.store = store
        self.chance = float(weights.get("bypass_chance", 0.01) or 0.01)
        self.state = store.get_state("brainn_unconscious") or {
            "habits": {"啊喂": 0.60, "哼哼": 0.50, "我服了": 0.40},
            "chains": [],
            "repression": [],
            "arousal_threshold": 0.75,
            "last_tick": time.time(),
        }
        self.state.setdefault(
            "chains",
            [
                {"trigger": "被冷落", "response": "阴阳一句", "strength": 0.40},
                {"trigger": "被夸", "response": "嘴硬否认", "strength": 0.30},
            ],
        )

    def maybe_bypass(self, decision: Decision, ctx: dict[str, Any]) -> dict[str, Any]:
        if random.random() >= self.chance:
            return {"triggered": False}
        threshold = float(self.state.get("arousal_threshold", 0.75))
        candidates: list[tuple[str, float, str]] = [
            (habit, float(strength), "habit")
            for habit, strength in (self.state.get("habits") or {}).items()
            if float(strength) >= threshold
        ]
        candidates.extend(
            (
                str(chain.get("response") or ""),
                float(chain.get("strength", 0) or 0),
                "chain",
            )
            for chain in (self.state.get("chains") or [])
            if float(chain.get("strength", 0) or 0) >= threshold
        )
        if not candidates:
            return {"triggered": False}
        habit, strength, kind = max(candidates, key=lambda item: item[1])
        return {
            "triggered": True,
            "habit": habit,
            "kind": kind,
            "strength": round(strength, 3),
            "scope": "expression",
            "influence": {"tone": 0.1, "particle": habit},
        }

    def on_event(self, percept, ctx: dict[str, Any]) -> list:
        text = str(getattr(percept, "text", "") or "")
        habits = self.state.setdefault("habits", {})
        for habit in list(habits):
            if habit and habit in text:
                habits[habit] = min(1.0, float(habits[habit]) + 0.03)
        for chain in self.state.get("chains") or []:
            trigger = str(chain.get("trigger") or "")
            if trigger and trigger in text:
                chain["strength"] = min(1.0, float(chain.get("strength", 0)) + 0.03)
        if len(text) > 20 and str(getattr(percept, "emotion", {}).get("label")) == "angry":
            repression = list(self.state.get("repression") or [])
            repression.append({"ts": time.time(), "text": text[:80]})
            self.state["repression"] = repression[-20:]
        self.save()
        return []

    def tick(self, now: float, ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        hours = max(0.0, min(48.0, (now - float(self.state.get("last_tick", now))) / 3600))
        if hours <= 0:
            return []
        for habit, strength in list((self.state.get("habits") or {}).items()):
            self.state["habits"][habit] = max(0.0, float(strength) - 0.01 * hours / 24)
        for chain in self.state.get("chains") or []:
            chain["strength"] = max(0.0, float(chain.get("strength", 0)) - 0.005 * hours / 24)
        cutoff = now - 7 * 86400
        self.state["repression"] = [
            item
            for item in (self.state.get("repression") or [])
            if float(item.get("ts", 0)) >= cutoff
        ]
        self.state["last_tick"] = now
        self.save()
        return []

    def learn_from_expression(self, text: str) -> None:
        """从她实际说出口的话里加固习惯。"""
        habits = self.state.setdefault("habits", {})
        for habit in ("啊喂", "哼哼", "我服了"):
            if habit and habit in text:
                habits[habit] = min(1.0, float(habits.get(habit, 0)) + 0.02)
        self.save()

    def save(self) -> None:
        self.store.set_state("brainn_unconscious", self.state)

    def snapshot(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "habits": dict(self.state.get("habits") or {}),
            "chains": len(self.state.get("chains") or []),
            "repression": len(self.state.get("repression") or []),
            "arousal_threshold": self.state.get("arousal_threshold"),
        }

    def learn(self, experience: dict[str, Any]) -> None:
        text = str(experience.get("text") or "")
        if text:
            self.learn_from_expression(text)
