"""叙事自我重构：事后解释、章节与转折点。

M5 对实践的总结必须滞后 N 个 tick，且允许美化或歪曲；细节可改，慢变量锚不可改。
"""
from __future__ import annotations

import time
from typing import Any

from ..core.contracts import Decision
from ..db import Store


class NarrativeModel:
    name = "narrative"

    def __init__(self, store: Store, settings: dict[str, Any] | None = None):
        self.store = store
        cfg = (settings or {}).get("brainn", {}) or {}
        practice_cfg = cfg.get("practice", {}) or {}
        self.delay = max(1, int(practice_cfg.get("narrative_delay", 3)))
        raw = store.get_state("brainn_narrative") or {}
        self.state = {
            "current": raw.get("current") or store.get_state("memory_mainline") or "",
            "chapters": list(raw.get("chapters") or []),
            "turning_points": list(raw.get("turning_points") or []),
            "rationalizations": list(raw.get("rationalizations") or []),
            "practice_reflections": list(raw.get("practice_reflections") or []),
            "pending": list(raw.get("pending") or []),
            "tick_count": int(raw.get("tick_count") or 0),
            "last_tick": float(raw.get("last_tick") or time.time()),
        }

    def bias(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按当前叙事一致性给记忆加一个很小的检索偏置，不改事实。"""
        current = str(self.state.get("current") or "")
        grams = {current[i : i + 2] for i in range(max(0, len(current) - 1))}
        out = []
        for item in items:
            text = " ".join(
                str(item.get(key) or "") for key in ("key", "value", "interpretation")
            )
            item_grams = {text[i : i + 2] for i in range(max(0, len(text) - 1))}
            overlap = len(grams & item_grams)
            copy = dict(item)
            copy["narrative_bias"] = round(min(0.30, overlap * 0.02), 3)
            out.append(copy)
        return out

    def rewrite_proposal(self, memory: dict[str, Any]) -> dict[str, Any] | None:
        """只允许改解读/讲述，事实层不可改。"""
        if not memory.get("interpretation"):
            return None
        return {
            "target": memory.get("code") or memory.get("key"),
            "field": "interpretation",
            "allowed": True,
            "confidence": 0.5,
            "reason": "叙事一致性",
        }

    def _queue(self, entry: dict[str, Any]) -> None:
        item = dict(entry)
        item["due_tick"] = int(self.state["tick_count"]) + self.delay
        pending = list(self.state.get("pending") or [])
        pending.append(item)
        self.state["pending"] = pending[-200:]

    def schedule_practice(self, writeback: dict[str, Any]) -> int:
        """M11 结算后登记一次实践反思；N 个 tick 之后才允许生成。"""
        seeds = writeback.get("narrative") or []
        if not seeds:
            return int(self.state["tick_count"]) + self.delay
        for seed in seeds:
            self._queue({"ts": time.time(), "kind": "practice", **seed})
        self.save()
        return int(self.state["tick_count"]) + self.delay

    def observe(
        self,
        decision: Decision,
        outcome: dict[str, Any],
        ctx: dict[str, Any],
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {"ts": time.time(), "intent": decision.intent}
        bypass = ctx.get("bypass") or {}
        if bypass.get("triggered"):
            entry.update(
                {
                    "kind": "rationalization",
                    "text": f"我那样说是因为{bypass.get('habit', '习惯')}",
                    "confidence": 0.5,
                }
            )
            self._queue(entry)
        intensity = float((outcome.get("emotion") or {}).get("intensity", 0) or 0)
        if intensity >= 0.6:
            entry = {
                "ts": time.time(),
                "kind": "turning",
                "text": str(outcome.get("text", ""))[:80],
                "intensity": round(intensity, 2),
            }
            self._queue(entry)
        self.save()
        return {**entry, "deferred": True, "delay_ticks": self.delay}

    def tick(self, now: float, ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.state["tick_count"] = int(self.state.get("tick_count") or 0) + 1
        self.state["last_tick"] = now
        due = [
            item
            for item in self.state.get("pending") or []
            if int(item.get("due_tick", 0)) <= int(self.state["tick_count"])
        ]
        rest = [
            item
            for item in self.state.get("pending") or []
            if int(item.get("due_tick", 0)) > int(self.state["tick_count"])
        ]
        self.state["pending"] = rest
        for item in due:
            kind = str(item.get("kind") or "")
            if kind == "practice":
                self._practice_reflection(item)
            elif kind == "turning":
                self._turning_point(item)
            elif kind == "rationalization":
                logs = list(self.state.get("rationalizations") or [])
                logs.append(
                    {
                        "ts": item.get("ts") or time.time(),
                        "kind": "rationalization",
                        "text": str(item.get("text") or ""),
                        "confidence": item.get("confidence", 0.5),
                    }
                )
                self.state["rationalizations"] = logs[-100:]
        self.save()
        return []

    def _practice_reflection(self, item: dict[str, Any]) -> None:
        """滞后生成的实践总结：可以美化、可以歪曲，但不能改事实锚。"""
        feedback = str(item.get("feedback") or "unseen")
        if feedback == "recognized":
            text = "那天的事其实没那么糟，至少我做得还行。"
        elif feedback == "denied":
            text = "算了，做得再好也没人看见。"
        else:
            text = "忙完也就那样，说不清值不值。"
        if bool(item.get("compensation")):
            text += "最近是真的有点提不起劲。"
        logs = list(self.state.get("practice_reflections") or [])
        logs.append(
            {
                "ts": time.time(),
                "day": item.get("day"),
                "artifact": item.get("artifact"),
                "feedback": feedback,
                "text": text,
                "delay_ticks": self.delay,
            }
        )
        self.state["practice_reflections"] = logs[-50:]

    def _turning_point(self, item: dict[str, Any]) -> None:
        points = list(self.state.get("turning_points") or [])
        points.append(
            {
                "ts": item.get("ts") or time.time(),
                "text": str(item.get("text") or "")[:80],
                "intensity": round(float(item.get("intensity") or 0), 2),
            }
        )
        self.state["turning_points"] = points[-50:]
        try:
            self.store.add_qt_transition(
                from_state=str(item.get("from") or ""),
                to_state=str(item.get("text") or "")[:120],
                retained=str(item.get("retained") or ""),
                reason="叙事转折点",
                meta={"intensity": round(float(item.get("intensity") or 0), 2)},
            )
        except Exception:  # noqa: BLE001
            pass
        chapters = list(self.state.get("chapters") or [])
        expected = len(self.state["turning_points"]) // 5
        if len(chapters) < expected:
            chapters.append(
                {
                    "ts": time.time(),
                    "title": f"第{len(chapters) + 1}章",
                    "from": points[-5]["ts"] if len(points) >= 5 else points[0]["ts"],
                    "to": time.time(),
                }
            )
            self.state["chapters"] = chapters[-12:]

    def save(self) -> None:
        self.store.set_state("brainn_narrative", self.state)

    def snapshot(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        reflections = self.state.get("practice_reflections") or []
        return {
            "current": self.state.get("current", ""),
            "chapters": len(self.state.get("chapters") or []),
            "turning_points": len(self.state.get("turning_points") or []),
            "rationalizations": len(self.state.get("rationalizations") or []),
            "practice_reflections": len(reflections),
            "last_practice_reflection": reflections[-1]["text"] if reflections else "",
            "pending": len(self.state.get("pending") or []),
            "tick_count": int(self.state.get("tick_count") or 0),
            "delay_ticks": self.delay,
        }

    def on_event(self, percept, ctx: dict[str, Any]) -> list:
        return []

    def learn(self, experience: dict[str, Any]) -> None:
        return None
