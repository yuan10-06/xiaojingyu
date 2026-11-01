"""对外感知框架：维护人物模型，并把网上看到的东西纳入世界感知。"""
from __future__ import annotations

import re
import time
from typing import Any

from ..core.contracts import Percept
from ..db import Store

DEFAULT_PERSON = {
    "name": "",
    "role": "",
    "traits": [],
    "emotion_history": [],
    "emotion": "neutral",
    "intensity": 0.0,
    "relation": {"depth": 0.0, "trust": 0.0, "conflict": 0.0},
    "last_event": "",
    "last_seen": 0.0,
    "confidence": 0.3,
    "updated_at": 0.0,
}

# 只感知情绪、关系与结构位置；不抽取偏好、兴趣或话题画像。


def _short(text: str, limit: int = 28) -> str:
    text = str(text or "").strip()
    return text[:limit] + ("…" if len(text) > limit else "")


class PersonModels:
    name = "perception"

    def __init__(self, store: Store, social, world=None, user_model=None):
        self.store = store
        self.social = social
        self.world = world
        self.user_model = user_model
        raw_state = store.get_state("brainn_persons") or {}
        # 清掉历史遗留的偏好/兴趣/话题画像字段
        legacy = ("preferences", "interests", "recent_topics")
        self.state: dict[str, Any] = {
            key: {k: v for k, v in (value or {}).items() if k not in legacy}
            for key, value in raw_state.items()
            if isinstance(value, dict)
        }

    def on_event(self, percept: Percept, ctx: dict[str, Any]) -> list:
        key = "user"
        node = self.social.node("user")
        edge = self.social.edge("her", "user")
        model = {**DEFAULT_PERSON, **self.state.get(key, {})}
        model.update(
            {
                "name": node.get("name", "他"),
                "role": node.get("role", ""),
                "emotion": str(percept.emotion.get("label", "neutral")),
                "intensity": float(percept.emotion.get("intensity", 0) or 0),
                "relation": {
                    "depth": round(float(edge.get("depth", 0) or 0), 1),
                    "trust": round(float(edge.get("trust", 0) or 0), 1),
                    "conflict": round(float(edge.get("conflict", 0) or 0), 1),
                },
                "last_event": (percept.text or "")[:80],
                "last_seen": time.time(),
                "confidence": round(min(0.95, float(model.get("confidence", 0.3)) + 0.02), 3),
                "updated_at": time.time(),
            }
        )

        text = str(percept.text or "")
        if self.user_model is not None:
            self.user_model.observe(text)

        # 情绪历史
        history = list(model.get("emotion_history") or [])
        label = str(percept.emotion.get("label", "neutral"))
        if label != "neutral":
            history.append(
                {
                    "label": label,
                    "intensity": round(float(percept.emotion.get("intensity", 0) or 0), 2),
                    "ts": time.time(),
                }
            )
        model["emotion_history"] = history[-6:]
        self.state[key] = model

        # 其他社会关系成员：文本里出现名字就更新
        for node in self.social.nodes.values():
            if node.get("id") in ("her", "user") or not node.get("active", 1):
                continue
            name = str(node.get("name") or "")
            if len(name) < 2 or name not in text:
                continue
            other = {**DEFAULT_PERSON, **self.state.get(node["id"], {})}
            other.update(
                {
                    "name": name,
                    "role": node.get("role", ""),
                    "emotion": model["emotion"],
                    "intensity": model["intensity"],
                    "last_event": text[:80],
                    "last_seen": time.time(),
                    "confidence": round(min(0.9, float(other.get("confidence", 0.2)) + 0.01), 3),
                    "updated_at": time.time(),
                }
            )
            self.state[node["id"]] = other
        self.save()
        return []

    def context_for_prompt(self) -> str:
        """给表达系统一段短印象，不重复记忆清单。"""
        user = self.state.get("user") or {}
        parts: list[str] = []
        if user:
            line = "你对他的印象："
            if user.get("emotion") and user.get("emotion") != "neutral":
                line += (
                    f"他刚才的情绪是{user.get('emotion')}"
                    f"（{float(user.get('intensity', 0) or 0):.1f}）。"
                )
            relation = user.get("relation") or {}
            depth = float(relation.get("depth", 0) or 0)
            if depth >= 80:
                line += "你们最近很亲近。"
            elif depth >= 60:
                line += "你们算亲近。"
            elif depth >= 40:
                line += "你们是朋友。"
            parts.append(line)

        if self.user_model is not None:
            structural = self.user_model.perception_line()
            if structural:
                parts.append(structural)

        if self.world is not None:
            views = self.world.views_for_prompt()
            if views:
                parts.append(views)

        world = self.store.get_state("web_surf") or {}
        titles = [
            str(item.get("title") or "")
            for item in (world.get("items") or [])[:3]
            if item.get("title")
        ]
        if titles:
            parts.append("你刚在网上看到：" + "；".join(titles) + "。")
        return "\n".join(parts)

    def world_snapshot(self) -> dict[str, Any]:
        return self.store.get_state("web_surf") or {}

    def save(self) -> None:
        self.store.set_state("brainn_persons", self.state)

    def snapshot(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        return dict(self.state)

    def tick(self, now: float, ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return []

    def learn(self, experience: dict[str, Any]) -> None:
        return None
