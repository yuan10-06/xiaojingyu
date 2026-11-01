"""预算器：生理基础库 + 时间有限性，只衰减、不竞标。"""
from __future__ import annotations

from typing import Any

from .contracts import Proposal


class CombinedBudget:
    def __init__(self, body, time_model, weights: dict[str, Any]):
        self.body = body
        self.time = time_model
        self.weights = weights or {}

    def multiplier(self, proposal: Proposal) -> float:
        w = self.weights
        state = self.body.state
        time_state = self.time.state
        occupancy = float(time_state.get("occupancy", 0.25) or 0.25)
        circadian = float(time_state.get("circadian", 0.6) or 0.6)
        fatigue = float(state.get("fatigue", 0) or 0) / 100
        pain = self.body.total_pain / 100
        hunger_over = max(0.0, float(state.get("hunger", 0) or 0) - 70) / 30
        period = 1.0 if (
            state.get("phase") == "经期" and int(state.get("cycle_day", 0) or 0) <= 2
        ) else 0.0
        value = (
            1.0
            - occupancy * float(w.get("schedule", 0.60))
            - fatigue * float(w.get("fatigue", 0.30))
            - pain * float(w.get("pain", 0.40))
            - hunger_over * float(w.get("hunger", 0.20))
            - period * float(w.get("period", 0.20))
            - (1.0 - circadian) * 0.10
        )
        floor = float(w.get("floor", 0.10))
        return max(floor, min(1.0, value))

    def veto(self, proposal: Proposal) -> bool:
        occupancy = float(self.time.state.get("occupancy", 0) or 0)
        return occupancy >= 0.98 and float(proposal.cost.get("time", 0) or 0) >= 0.7
