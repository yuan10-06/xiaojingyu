"""情绪调制场：在评价处生成，贯穿下游，而不是某一个模块的激素。

valence 效价 ∈ [-1,1]，arousal 唤醒 ∈ [0,1]；duration 让情绪有惯性。
"""
from __future__ import annotations

import time
from typing import Any

from .db import Store


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


VALENCE_BY_LABEL = {
    "happy": 0.8,
    "love": 0.9,
    "laugh": 0.7,
    "neutral": 0.0,
    "tired": -0.35,
    "sad": -0.75,
    "anxious": -0.65,
    "angry": -0.8,
}


class AffectField:
    name = "affect"

    def __init__(self, store: Store, settings: dict[str, Any], clock, social=None, thrownness=None):
        self.store = store
        self.clock = clock
        self.social = social
        self.thrownness = thrownness
        cfg = (settings.get("brainn") or {}).get("affect") or {}
        self.cfg = {
            "decay_per_hour": float(cfg.get("decay_per_hour", 0.12)),
            "memory_bias": float(cfg.get("memory_bias", 0.8)),
            "time_slow_arousal": float(cfg.get("time_slow_arousal", 0.65)),
            "time_fast_arousal": float(cfg.get("time_fast_arousal", 0.25)),
        }
        raw = store.get_state("brainn_affect") or {}
        mood = store.get_state("mood") or {}
        initial_valence = (float(mood.get("mood", 55) or 55) - 50.0) / 50.0 * 0.5
        self.state = {
            "valence": float(raw.get("valence", _clamp(initial_valence))),
            "arousal": float(raw.get("arousal", 0.35)),
            "duration": float(raw.get("duration", 0.0)),
            "appraisal": dict(raw.get("appraisal") or {}),
            "attribution": str(raw.get("attribution") or ""),
            "last_event": str(raw.get("last_event") or ""),
            "last_tick": float(raw.get("last_tick") or time.time()),
        }

    # ---------- 评价处生成 ----------
    def appraise(
        self,
        decision,
        distortion: dict[str, Any],
        outcome: dict[str, Any],
        ctx: dict[str, Any],
    ) -> dict[str, Any]:
        emotion = (outcome or {}).get("emotion") or {}
        label = str(emotion.get("label") or "neutral")
        intensity = float(emotion.get("intensity") or 0)
        emotion_valence = VALENCE_BY_LABEL.get(label, 0.0)
        tension = float((distortion or {}).get("tension") or 0)
        intent = str(getattr(decision, "intent", "") or "")
        intent_score = 0.15 if intent not in ("", "do_nothing") else -0.15
        pressure = float(getattr(self.thrownness, "pressure", lambda: 0.0)()) if self.thrownness else 0.0
        valence = _clamp(
            0.55 * emotion_valence
            + 0.25 * intent_score
            - 0.20 * tension
            - 0.10 * pressure
        )
        arousal = _clamp(
            0.35 * intensity
            + 0.25 * abs(valence)
            + 0.20 * tension
            + 0.15 * (1.0 if intent not in ("", "do_nothing") else 0.0),
            0.0,
            1.0,
        )
        duration = round(2.0 + 4.0 * abs(valence) + 2.0 * arousal, 2)
        text = str((outcome or {}).get("text") or "")
        attribution = "self"
        if valence < -0.15:
            if any(word in text for word in ("你", "他", "宝", "哥")):
                attribution = "user"
            elif any(word in text for word in ("店", "班", "组长", "老师", "作业")):
                attribution = "world"
        self.state.update(
            {
                "valence": round(valence, 3),
                "arousal": round(arousal, 3),
                "duration": duration,
                "appraisal": {
                    "goal_relevance": round(abs(valence), 3),
                    "coping": round(_clamp(1.0 - tension, 0.0, 1.0), 3),
                    "attribution": attribution,
                    "source": label,
                },
                "attribution": attribution,
                "last_event": text[:120],
                "last_tick": float((ctx or {}).get("now") or self.clock.now().timestamp()),
            }
        )
        if valence < -0.25 and attribution == "user" and self.social is not None:
            self.social.adjust_edge(
                "her", "user", {"conflict": 0.2}, interactions=0,
                last_event="情绪归因到他",
            )
        self.save()
        return self.snapshot()

    # ---------- 惯性 ----------
    def tick(self, now: float, ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        hours = max(0.0, min(12.0, (now - float(self.state["last_tick"])) / 3600))
        if hours <= 0:
            return []
        duration = float(self.state.get("duration") or 0)
        if duration > 0:
            remaining = max(0.0, duration - hours)
            ratio = remaining / duration
            self.state["valence"] = _clamp(float(self.state["valence"]) * ratio)
            self.state["arousal"] = max(
                0.0, float(self.state["arousal"]) * (0.4 + 0.6 * ratio)
            )
            self.state["duration"] = round(remaining, 2)
        else:
            self.state["valence"] = _clamp(
                float(self.state["valence"]) * max(0.0, 1.0 - self.cfg["decay_per_hour"] * hours)
            )
            self.state["arousal"] = max(
                0.0, float(self.state["arousal"]) - self.cfg["decay_per_hour"] * 0.5 * hours
            )
        self.state["last_tick"] = now
        self.save()
        return []

    # ---------- 下游调制 ----------
    def modulate(self) -> dict[str, float]:
        valence = float(self.state["valence"])
        arousal = float(self.state["arousal"])
        return {
            "attention": round(_clamp(0.5 + 0.4 * arousal + 0.1 * valence, 0.0, 1.0), 3),
            "memory_bias": round(_clamp(valence, -1.0, 1.0), 3),
            "time_perception": round(1.0 + 0.6 * arousal - 0.3 * valence, 3),
            "risk_tolerance": round(_clamp(0.5 + 0.3 * valence, 0.0, 1.0), 3),
            "expressivity": round(_clamp(0.3 + 0.7 * arousal, 0.0, 1.0), 3),
        }

    def emotion_label(self) -> str:
        valence = float(self.state["valence"])
        arousal = float(self.state["arousal"])
        if valence >= 0.35:
            return "兴奋" if arousal >= 0.6 else "松快"
        if valence <= -0.35:
            return "发紧" if arousal >= 0.6 else "低落"
        if arousal >= 0.65:
            return "不安"
        return "平"

    def time_line(self) -> str:
        arousal = float(self.state["arousal"])
        if arousal >= self.cfg["time_slow_arousal"]:
            return "你现在觉得时间过得有点慢，几分钟像拖了很久。"
        if arousal <= self.cfg["time_fast_arousal"]:
            return "时间过得有点快，回过神来已经过去一阵了。"
        return ""

    def hint_line(self) -> str:
        label = self.emotion_label()
        if label == "平":
            return ""
        return f"你现在的情绪底色是{label}；不用直接说出来，但它会影响你的语气和耐心。"

    # ---------- 持久化 ----------
    def save(self) -> None:
        self.store.set_state("brainn_affect", self.state)

    def snapshot(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "valence": round(float(self.state["valence"]), 3),
            "arousal": round(float(self.state["arousal"]), 3),
            "duration": round(float(self.state["duration"]), 2),
            "label": self.emotion_label(),
            "appraisal": dict(self.state.get("appraisal") or {}),
            "attribution": self.state.get("attribution", ""),
            "modulation": self.modulate(),
        }
