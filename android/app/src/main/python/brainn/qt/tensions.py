"""M9 认识张力：关键词/规则检测，不引入 NLI 模型。

只在两种情况下登记：
1. 他明确在纠正或否认（不是 / 我没 / 你记错了 …），且本轮召回到了旧记忆；
2. 旧记忆里的倾向词与这句话里的反义词同时出现（喜欢 ↔ 不喜欢 / 讨厌）。
"""
from __future__ import annotations

from typing import Any

CORRECTION_WORDS = (
    "不是", "不对", "没有", "我没", "别瞎说", "你记错了", "搞错", "不是这样", "谁说",
)
OPPOSITE_PAIRS = (
    ("喜欢", "不喜欢"), ("喜欢", "讨厌"), ("爱吃", "不爱吃"), ("爱吃", "讨厌吃"),
    ("是", "不是"), ("有", "没有"), ("会", "不会"), ("想", "不想"),
)


def _item_text(item: dict[str, Any]) -> str:
    return f"{item.get('key') or ''} {item.get('value') or ''} {item.get('hooks') or ''}"


def detect_conflict(text: str, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """返回一条待登记的张力；没有命中返回 None。"""
    raw = str(text or "").strip()
    if not raw or not items:
        return None
    corrected = any(word in raw for word in CORRECTION_WORDS)
    for item in items[:3]:
        old = _item_text(item)
        if not old.strip():
            continue
        for pos, neg in OPPOSITE_PAIRS:
            # 普通反义词只在明确纠正时算；偏好类可以直接触发，避免日常“不是”刷屏
            if not corrected and pos not in ("喜欢", "爱吃"):
                continue
            old_pos, old_neg = pos in old, neg in old
            new_pos, new_neg = pos in raw, neg in raw
            if (old_pos and new_neg) or (old_neg and new_pos):
                return {
                    "a_ref": str(item.get("code") or item.get("key") or ""),
                    "b_ref": "当前说法",
                    "topic": str(item.get("key") or "同一话题")[:120],
                    "note": raw[:160],
                }
        if corrected:
            return {
                "a_ref": str(item.get("code") or item.get("key") or ""),
                "b_ref": "当前说法",
                "topic": str(item.get("key") or "同一话题")[:120],
                "note": raw[:160],
            }
    return None
