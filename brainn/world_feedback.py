"""M15/M16：从用户对视频通话内容的回应里回收命中率。

用户说“对/没错/就是”算证实；说“不对/看错/没有”算证伪。
只处理明确反馈，不把普通闲聊硬算成命中。
"""
from __future__ import annotations

import re
import time
from typing import Any

from .db import Store

_NEGATIVE = (
    "不对", "不是", "看错", "没有", "哪有", "错了", "不是这样",
    "猜错", "说错", "别看错", "哪有啊", "才不是",
)
_POSITIVE = (
    "没错", "对的", "是的", "就是", "确实", "好准", "猜对", "看对",
    "对呀", "对哦", "对啊", "嗯对",
)
_QUESTION_MARKS = ("?", "？", "吗", "么", "呢")


def detect_feedback(text: str) -> str | None:
    raw = str(text or "").strip()
    if not raw or len(raw) > 30:
        return None
    if any(mark in raw for mark in _QUESTION_MARKS):
        return None
    compact = re.sub(r"[\s，。！!~～、,]+", "", raw)
    if not compact:
        return None
    if any(word in compact for word in _NEGATIVE):
        return "refuted"
    if any(word in compact for word in _POSITIVE):
        return "confirmed"
    if compact in ("对", "是", "嗯", "好", "准"):
        return "confirmed"
    if compact in ("不", "错"):
        return "refuted"
    return None


class WorldFeedback:
    def __init__(self, store: Store):
        self.store = store

    def record(self, claim: dict[str, Any], text: str) -> dict[str, Any] | None:
        if not isinstance(claim, dict):
            return None
        claim_id = str(claim.get("id") or "").strip()
        verdict = detect_feedback(text)
        if not claim_id or not verdict:
            return None
        try:
            age = time.time() - float(claim.get("at") or 0)
        except (TypeError, ValueError):
            age = 999
        if age > 150:
            return None
        hit = verdict == "confirmed"
        match = 0.9 if hit else 0.8
        evidence = str(text or "")[:160]
        try:
            self.store.add_qt_outcome(
                claim_id,
                verdict=verdict,
                evidence=evidence,
                confidence=0.85,
                source="world.feedback",
            )
            self.store.add_qt_metric(
                claim_id,
                hit=hit,
                match_score=match,
                note=("她看准了：" if hit else "她看错了：") + evidence,
            )
            self.store.set_qt_artifact_feedback(
                claim_id, "confirmed" if hit else "refuted"
            )
        except Exception:  # noqa: BLE001
            return None
        return {
            "claim_id": claim_id,
            "verdict": verdict,
            "hit": hit,
            "match_score": match,
            "evidence": evidence,
        }
