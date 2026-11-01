"""社会关系神经网络的提案适配器：把关系状态转成竞标单。"""
from __future__ import annotations

from typing import Any

from ..core.contracts import Proposal


class SocialBidder:
    name = "social"

    def __init__(self, social):
        self.social = social

    def propose(self, ctx: dict[str, Any]) -> list[Proposal]:
        edge = self.social.edge("her", "user")
        conflict = float(edge.get("conflict", 0) or 0)
        depth = float(edge.get("depth", 0) or 0)
        gap = float(ctx.get("gap_hours", 0) or 0)
        if conflict >= 20:
            return [
                Proposal(
                    source="social",
                    intent="repair",
                    strength=round(min(1.0, 0.3 + conflict / 50), 3),
                    expected_reward=0.75,
                    cost={"relation": 0.3},
                    payload={"conflict": round(conflict, 1)},
                )
            ]
        if gap >= 6:
            return [
                Proposal(
                    source="social",
                    intent="reach_out",
                    strength=round(min(0.9, 0.4 + gap / 24), 3),
                    expected_reward=0.70,
                    cost={"time": 0.2},
                    payload={"gap_hours": round(gap, 1), "depth": round(depth, 1)},
                )
            ]
        return [
            Proposal(
                source="social",
                intent="maintain_relation",
                strength=0.25,
                expected_reward=0.30,
                cost={"time": 0.05},
                payload={"depth": round(depth, 1)},
            )
        ]

    def snapshot(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        edge = self.social.edge("her", "user")
        return {
            "depth": round(float(edge.get("depth", 0) or 0), 1),
            "trust": round(float(edge.get("trust", 0) or 0), 1),
            "conflict": round(float(edge.get("conflict", 0) or 0), 1),
        }

    def tick(self, now: float, ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return []

    def on_event(self, percept, ctx: dict[str, Any]) -> list:
        return []

    def learn(self, experience: dict[str, Any]) -> None:
        return None
