"""System 1：实践直觉 / 情境—行动倾向表。

这里只存数字：特征哈希、权重、曝光次数。
M1（表达）和 M5（叙事）都读不到它；只有 M12 拍卖能接收它的一点点调制。
"""
from __future__ import annotations

import hashlib
import math
import random
from typing import Any

from .db import Store


class System1PermissionDenied(Exception):
    """System 2 试图读取 System 1 时抛出。"""


ACTIONS = ("work", "check", "ask_help", "slow", "avoid", "rush")
_ACTION_INDEX = {name: idx for idx, name in enumerate(ACTIONS)}
_INTENTS = {
    "work": "work",
    "check": "work",
    "rush": "work",
    "ask_help": "reach_out",
    "slow": "rest",
    "avoid": "do_nothing",
}


def _hash(text: str) -> int:
    return int(hashlib.md5(str(text).encode("utf-8")).hexdigest()[:8], 16)


def _features(context: dict[str, Any]) -> list[int]:
    kind = str(context.get("kind") or "")
    title = str(context.get("title") or "")
    place = str(context.get("place") or "")
    hour = int(context.get("hour") or 12)
    load = float(context.get("load") or 0.5)
    bucket = "早" if hour < 10 else "中" if hour < 17 else "晚"
    load_bucket = int(max(0.0, min(4.0, load * 4)))
    tokens = [f"k:{kind}", f"p:{place}", f"t:{bucket}", f"l:{load_bucket}"]
    # 标题用 2 字片段，让“奶茶店晚班”和“奶茶店临时班”也能相似
    for i in range(max(1, len(title) - 1)):
        tokens.append(f"g:{title[i:i+2]}")
    return sorted({_hash(token) for token in tokens})


class PracticalIntuition:
    def __init__(self, store: Store, settings: dict[str, Any]):
        self.store = store
        cfg = (settings.get("brainn") or {}).get("intuition") or {}
        self.tau = float(cfg.get("tau", 0.7))
        self.eta = float(cfg.get("eta", 0.02))
        self.lambda_minus = float(cfg.get("lambda_minus", 1.0))
        self.lambda_plus = float(cfg.get("lambda_plus", 0.25))
        self.sim_threshold = float(cfg.get("sim_threshold", 0.25))
        raw = store.get_state("brainn_intuition") or {}
        self.contexts: list[list[int]] = [
            [int(x) for x in row] for row in (raw.get("contexts") or [])
        ]
        self.weights: list[list[float]] = [
            [float(x) for x in row] for row in (raw.get("weights") or [])
        ]
        self.exposures: list[int] = [int(x) for x in (raw.get("exposures") or [])]
        while len(self.exposures) < len(self.contexts):
            self.exposures.append(0)
        while len(self.weights) < len(self.contexts):
            self.weights.append([0.0] * len(ACTIONS))
        self.save()

    # ---------- 隔离 ----------
    def read_for_prompt(self):
        raise System1PermissionDenied("System 1 不可被 System 2 读取")

    def __str__(self) -> str:  # 不泄露权重内容
        return f"<PracticalIntuition contexts={len(self.contexts)} exposures={sum(self.exposures)}>"

    def snapshot(self) -> dict[str, Any]:
        return {
            "contexts": len(self.contexts),
            "exposures": sum(self.exposures),
            "trained": self.trained(),
            "max_weight": round(self.max_weight(), 3),
        }

    def trained(self) -> bool:
        return self.max_weight() > 0.001

    def max_weight(self) -> float:
        best = 0.0
        for row in self.weights:
            for value in row:
                best = max(best, abs(float(value)))
        return best

    # ---------- 相似度与选择 ----------
    @staticmethod
    def _sim(a: list[int], b: list[int]) -> float:
        sa, sb = set(a), set(b)
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    def _nearest(self, features: list[int]) -> tuple[int, float]:
        best_index = -1
        best_sim = 0.0
        for idx, known in enumerate(self.contexts):
            sim = self._sim(features, known)
            if sim > best_sim:
                best_index, best_sim = idx, sim
        return best_index, best_sim

    def distribution(self, context: dict[str, Any]) -> dict[str, float]:
        features = _features(context)
        idx, sim = self._nearest(features)
        if idx < 0 or sim < self.sim_threshold or not self.trained():
            return {name: 1.0 / len(ACTIONS) for name in ACTIONS}
        scores = []
        for a_idx, name in enumerate(ACTIONS):
            value = 0.0
            for known_idx, known in enumerate(self.contexts):
                s = self._sim(features, known)
                if s <= 0:
                    continue
                value += s * float(self.weights[known_idx][a_idx])
            scores.append(value / self.tau)
        peak = max(scores)
        exps = [math.exp(min(20.0, score - peak)) for score in scores]
        total = sum(exps) or 1.0
        return {name: round(exps[i] / total, 4) for i, name in enumerate(ACTIONS)}

    def choose(self, context: dict[str, Any], rng: random.Random | None = None) -> str:
        rng = rng or random
        dist = self.distribution(context)
        pick = rng.random()
        upto = 0.0
        for name, prob in dist.items():
            upto += prob
            if pick <= upto:
                return name
        return ACTIONS[-1]

    # ---------- 学习 ----------
    def observe(
        self,
        context: dict[str, Any],
        action: str,
        outcome: float,
        *,
        exposure: int = 1,
    ) -> None:
        if action not in _ACTION_INDEX:
            return
        features = _features(context)
        idx, sim = self._nearest(features)
        if idx < 0 or sim < self.sim_threshold:
            self.contexts.append(features)
            self.weights.append([0.0] * len(ACTIONS))
            self.exposures.append(0)
            idx, sim = len(self.contexts) - 1, 1.0
        self.exposures[idx] += max(0, int(exposure))
        a_idx = _ACTION_INDEX[action]
        predicted = float(self.weights[idx][a_idx])
        delta = float(outcome) - predicted
        lam = self.lambda_minus if delta < 0 else self.lambda_plus
        self.weights[idx][a_idx] = max(
            -1.0, min(1.0, predicted + self.eta * lam * delta * sim)
        )
        self.save()

    def modulate(self, proposals: list, context: dict[str, Any]) -> list:
        """把 System 1 的倾向压成很小的强度修正，不产生文本。"""
        if not self.trained():
            return proposals
        dist = self.distribution(context)
        top_action = max(dist, key=dist.get)
        top_prob = float(dist.get(top_action, 0.0))
        intent = _INTENTS.get(top_action, "")
        if not intent:
            return proposals
        for proposal in proposals:
            if str(getattr(proposal, "intent", "")) == intent:
                proposal.strength = min(
                    1.0, float(proposal.strength) + 0.06 * top_prob
                )
        return proposals

    def save(self) -> None:
        self.store.set_state(
            "brainn_intuition",
            {
                "version": 1,
                "contexts": self.contexts,
                "weights": [
                    [round(float(v), 5) for v in row] for row in self.weights
                ],
                "exposures": self.exposures,
                "tau": self.tau,
                "eta": self.eta,
                "lambda_minus": self.lambda_minus,
                "lambda_plus": self.lambda_plus,
                "sim_threshold": self.sim_threshold,
            },
        )
