"""仲裁中枢骨架：预算器接口 + 拍卖打分。

P2 只提供纯函数和数据结构，不接入对话热路径。
拍卖权重（threshold / cost_weight）尚未确认，必须由调用方显式传入。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .contracts import Decision, Proposal


@dataclass
class AuctionConfig:
    threshold: float
    cost_weight: float


class Budget:
    """预算器接口：生理 + 时间。只衰减、不竞标。"""

    def multiplier(self, proposal: Proposal) -> float:
        """返回 0~1 的衰减系数。"""
        return 1.0

    def veto(self, proposal: Proposal) -> bool:
        """硬预算不足时直接否决。"""
        return False


class Arbitrator:
    """拍卖 + 拍板。人格扭曲和无意识旁路在后续阶段接入。"""

    def __init__(self, config: AuctionConfig):
        self.config = config

    def score(self, proposal: Proposal, budget: Budget) -> float:
        if budget.veto(proposal):
            return float("-inf")
        strength = max(0.0, min(1.0, float(proposal.strength)))
        reward = max(0.0, min(1.0, float(proposal.expected_reward)))
        cost = sum(max(0.0, float(v)) for v in proposal.cost.values())
        return strength * reward * budget.multiplier(proposal) - self.config.cost_weight * cost

    def decide(self, proposals: Iterable[Proposal], budget: Budget) -> Decision:
        best: Proposal | None = None
        best_score = float("-inf")
        for proposal in proposals:
            score = self.score(proposal, budget)
            if score > best_score:
                best, best_score = proposal, score
        if best is None or best_score < self.config.threshold:
            return Decision(intent="do_nothing", score=best_score, rationale="below_threshold")
        return Decision(intent=best.intent, winner=best, score=best_score)
