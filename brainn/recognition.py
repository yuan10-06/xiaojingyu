"""M9 子驱力：定位唯一真实他者（用户），并偶尔形成结构性判断。

频率不固定：urgency × 情境 × 随机，不是定时器。
"""
from __future__ import annotations

import random
import time
from typing import Any

from .core.contracts import Proposal
from .db import Store
from .user_model import UserModel


class RecognitionDrive:
    name = "recognition"

    def __init__(
        self,
        store: Store,
        settings: dict[str, Any],
        user_model: UserModel,
        practice=None,
    ):
        self.store = store
        self.user_model = user_model
        self.practice = practice
        cfg = (settings.get("brainn") or {}).get("recognition") or {}
        self.threshold = float(cfg.get("urgency_threshold", 0.55))
        self.probe_gap_hours = float(cfg.get("probe_gap_hours", 6))
        raw = store.get_state("brainn_recognition") or {}
        self.state = {
            "urgency": float(raw.get("urgency", 0.25)),
            "last_probe_ts": float(raw.get("last_probe_ts") or 0),
            "probe_count": int(raw.get("probe_count") or 0),
            "last_question": str(raw.get("last_question") or ""),
            "last_tick": float(raw.get("last_tick") or time.time()),
        }

    def tick(self, now: float, ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        hours = max(0.0, min(12.0, (now - float(self.state["last_tick"])) / 3600))
        if hours <= 0:
            return []
        practice = self.store.get_state("brainn_practice") or {}
        alienation = float(practice.get("alienation") or 0)
        world = self.store.get_state("brainn_world") or {}
        negative = sum(
            1
            for item in (world.get("deltas") or [])[-20:]
            if float(item.get("delta_true") or 0) < 0
        )
        confidence = float(self.user_model.confidence)
        target = 0.20 + alienation * 0.45 + (1.0 - confidence) * 0.20 + min(0.20, negative * 0.03)
        if confidence >= 0.75:
            target *= 0.55
        target = max(0.0, min(1.0, target))
        urgency = float(self.state["urgency"])
        urgency += (target - urgency) * min(1.0, 0.12 * hours)
        self.state["urgency"] = round(max(0.0, min(1.0, urgency)), 3)
        self.state["last_tick"] = now
        self.save()
        return []

    def should_probe(self, now: float, ctx: dict[str, Any] | None = None) -> bool:
        urgency = float(self.state["urgency"])
        if urgency < self.threshold:
            return False
        last = float(self.state.get("last_probe_ts") or 0)
        if last and (now - last) / 3600 < self.probe_gap_hours:
            return False
        activity = (ctx or {}).get("activity") or {}
        kind = str(activity.get("kind") or "")
        chance = 0.15 if kind in ("work", "class", "deadline") else 0.55
        return random.random() < urgency * chance

    def take_question(self, now: float, ctx: dict[str, Any] | None = None) -> str:
        if not self.should_probe(now, ctx):
            return ""
        question = self.user_model.structural_question()
        self.state["last_probe_ts"] = now
        self.state["probe_count"] = int(self.state.get("probe_count") or 0) + 1
        self.state["last_question"] = question
        self.save()
        return question

    def propose(self, now: float) -> list[Proposal]:
        urgency = float(self.state["urgency"])
        if urgency < self.threshold:
            return []
        return [
            Proposal(
                source="drives",
                intent="probe_user",
                strength=round(min(1.0, urgency * 0.85), 3),
                expected_reward=0.62,
                cost={"time": 0.2, "energy": 0.1},
                payload={"urgency": urgency, "question": self.user_model.structural_question()},
            )
        ]

    def save(self) -> None:
        self.store.set_state("brainn_recognition", self.state)

    def snapshot(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "urgency": round(float(self.state.get("urgency") or 0), 3),
            "probe_count": int(self.state.get("probe_count") or 0),
            "last_probe_ts": self.state.get("last_probe_ts"),
            "last_question": self.state.get("last_question", ""),
            "user_confidence": round(float(self.user_model.confidence), 3),
            "judgment": self.user_model.judgment(),
        }
