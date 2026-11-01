"""自我人格冲突：四个子系统辩论，扭曲胜出意图。"""
from __future__ import annotations

import time
from typing import Any

from ..core.contracts import Decision
from ..db import Store

SUB_WEIGHTS = {"desire": 0.35, "moral": 0.25, "rational": 0.25, "long_term": 0.15}

STANCES = {
    "desire": {"approach": 0.80, "honesty": -0.20, "directness": 0.60, "now": 0.70},
    "moral": {"approach": 0.20, "honesty": 0.80, "directness": 0.30, "now": 0.20},
    "rational": {"approach": 0.40, "honesty": 0.60, "directness": 0.50, "now": -0.30},
    "long_term": {"approach": 0.50, "honesty": 0.50, "directness": 0.40, "now": -0.60},
}


class ConflictModel:
    name = "conflict"

    def __init__(self, store: Store, weights: dict[str, Any], thrownness=None):
        self.store = store
        self.thrownness = thrownness
        self.cap = float(weights.get("distortion", 0.30) or 0.30)
        self.state = store.get_state("brainn_conflict") or {
            "regret": 20.0,
            "suppression": 10.0,
            "compromise": 10.0,
            "last_tick": time.time(),
        }
        self.state.setdefault(
            "stances", {sub: dict(values) for sub, values in STANCES.items()}
        )

    def tick(self, now: float, ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        hours = max(0.0, min(48.0, (now - float(self.state["last_tick"])) / 3600))
        self.state["regret"] = max(0.0, float(self.state["regret"]) - hours / 24)
        self.state["last_tick"] = now
        self.save()
        return []

    def distort(self, decision: Decision, ctx: dict[str, Any]) -> dict[str, Any]:
        stances = self.state.get("stances") or STANCES
        net = {dim: 0.0 for dim in ("approach", "honesty", "directness", "now")}
        for sub, weight in SUB_WEIGHTS.items():
            for dim, value in stances.get(sub, {}).items():
                net[dim] += value * weight
        pressure = 0.0
        if self.thrownness is not None:
            try:
                pressure = float(self.thrownness.pressure())
            except Exception:  # noqa: BLE001
                pressure = 0.0
            # 既定之我 vs 想成为谁：被抛压力越大，越不甘、越收着
            net["approach"] -= pressure * 0.12
            net["now"] -= pressure * 0.05
        distorted = {dim: round(value * self.cap, 3) for dim, value in net.items()}
        pairs = self._pairs()
        dominant = max(pairs, key=pairs.get)
        spread = sum(abs(value) for value in net.values())
        self.state["suppression"] = min(
            100.0, float(self.state["suppression"]) + spread * 0.1
        )
        self.state["compromise"] = min(
            100.0, float(self.state["compromise"]) + spread * self.cap * 0.2
        )
        self.state["regret"] = min(
            100.0, float(self.state["regret"]) + spread * 0.05
        )
        self.save()
        try:
            self.store.bump_qt_tension(
                "QT.M9",
                dominant,
                dominant,
                delta=1.0,
                threshold=1.0,
                note="自我人格冲突：只登记张力，不判定对错",
            )
        except Exception:  # noqa: BLE001
            pass
        return {
            **distorted,
            "dominant_conflict": dominant,
            "tension": round(float(pairs[dominant]), 3),
            "thrownness_pressure": round(pressure, 3),
            "given_self": "被给予的出身、家庭与童年" if pressure >= 0.3 else "",
        }

    def _pairs(self) -> dict[str, float]:
        stances = self.state.get("stances") or STANCES
        desire = stances.get("desire", {})
        rational = stances.get("rational", {})
        moral = stances.get("moral", {})
        return {
            "嘴硬心软": round(abs(float(desire.get("approach", 0)) - float(rational.get("directness", 0))), 3),
            "说一套做一套": round(abs(float(moral.get("honesty", 0)) - float(desire.get("honesty", 0))), 3),
            "事后后悔": round(float(self.state.get("regret", 0)) / 100, 3),
        }

    def save(self) -> None:
        self.store.set_state("brainn_conflict", self.state)

    def snapshot(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "regret": round(float(self.state.get("regret", 0)), 1),
            "suppression": round(float(self.state.get("suppression", 0)), 1),
            "compromise": round(float(self.state.get("compromise", 0)), 1),
            "pairs": self._pairs(),
            "thrownness_pressure": round(
                float(self.thrownness.pressure()) if self.thrownness is not None else 0.0,
                3,
            ),
        }

    def on_event(self, percept, ctx: dict[str, Any]) -> list:
        label = str(getattr(percept, "emotion", {}).get("label", "neutral"))
        stances = self.state.get("stances") or STANCES
        if label == "angry":
            changes = {"desire": {"approach": -0.05, "now": -0.03}, "rational": {"directness": 0.02}}
        elif label in ("sad", "tired"):
            changes = {"desire": {"approach": 0.05}, "moral": {"approach": 0.02}}
        elif label in ("happy", "love"):
            changes = {"desire": {"approach": 0.04}, "rational": {"now": 0.02}}
        else:
            changes = {}
        for sub, dims in changes.items():
            for dim, delta in dims.items():
                target = stances.get(sub, {})
                target[dim] = max(-1.0, min(1.0, float(target.get(dim, 0)) + delta))
                stances[sub] = target
        self.state["stances"] = stances
        self.save()
        return []

    def learn(self, experience: dict[str, Any]) -> None:
        label = str((experience.get("emotion") or {}).get("label", "neutral"))
        if label == "angry":
            self.state["regret"] = min(100.0, float(self.state.get("regret", 0)) + 2.0)
            self.state["suppression"] = min(
                100.0, float(self.state.get("suppression", 0)) + 1.0
            )
        elif label in ("happy", "love"):
            self.state["regret"] = max(0.0, float(self.state.get("regret", 0)) - 1.0)
        self.save()
