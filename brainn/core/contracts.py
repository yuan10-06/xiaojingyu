"""BrainN Core 的模块契约（P2 骨架，尚未接入热路径）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Percept:
    """对外感知框架的标准化输出。"""

    text: str = ""
    kind: str = "text"
    user_id: int | None = None
    ts: float = 0.0
    emotion: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Proposal:
    """提案方交给仲裁中枢的竞标单。"""

    source: str
    intent: str
    strength: float = 0.0
    expected_reward: float = 0.0
    cost: dict[str, float] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)


@dataclass
class Decision:
    """仲裁中枢的输出。"""

    intent: str = "do_nothing"
    winner: Proposal | None = None
    score: float = 0.0
    distorted_by: str = ""
    bypass: bool = False
    rationale: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


class Module(Protocol):
    """所有模块统一接口；模块之间不直接调用。"""

    name: str

    def snapshot(self, ctx: dict[str, Any]) -> dict[str, Any]:
        ...

    def on_event(self, percept: Percept, ctx: dict[str, Any]) -> list[Proposal]:
        ...

    def tick(self, now: float, ctx: dict[str, Any]) -> list[dict[str, Any]]:
        ...

    def learn(self, experience: dict[str, Any]) -> None:
        ...
