"""情绪状态机：心情 / 亲密度 / 委屈 / 吃醋 / 理智条。

理智条（sanity）含义：
  0  → 完全感性：容易上头、吃醋、翻旧账、不讲道理
  100→ 完全理性：会讲道理、语气平稳、克制
基线 50，随天气、时段、疲劳、亲密度在 30~78 间漂移。
"""
from __future__ import annotations

import random
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .db import Store


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


@dataclass
class MoodState:
    mood: float = 58.0
    affection: float = 42.0
    grievance: float = 0.0
    jealousy: float = 0.0
    sanity: float = 50.0
    energy: float = 72.0
    updated_at: float = field(default_factory=time.time)
    last_user_ts: float = 0.0
    silence_marked: bool = False

    def snapshot(self) -> dict[str, float]:
        return {
            "mood": round(self.mood, 1),
            "affection": round(self.affection, 1),
            "grievance": round(self.grievance, 1),
            "jealousy": round(self.jealousy, 1),
            "sanity": round(self.sanity, 1),
            "energy": round(self.energy, 1),
        }


class Mood:
    """情绪读写与事件响应。所有数值变化都落库，可在重启后延续。"""

    def __init__(self, store: Store, persona: dict[str, Any]):
        self.store = store
        self.cfg = persona.get("emotion", {})
        self.task_cfg = persona.get("task_policy", {})
        raw = store.get_state("mood") or {}
        self.state = MoodState(**{k: v for k, v in raw.items() if k in MoodState.__annotations__})

    # ---------- 持久化 ----------
    def save(self) -> None:
        self.store.set_state("mood", asdict(self.state))

    def reload(self) -> None:
        """从库里重新读一次心情：多个入口共用同一具身体时避免各自拿着旧快照。"""
        raw = self.store.get_state("mood") or {}
        self.state = MoodState(
            **{k: v for k, v in raw.items() if k in MoodState.__annotations__}
        )

    # ---------- 事件 ----------
    def on_user_message(self, text: str) -> None:
        """收到用户消息的基础情绪反应；具体语义由上层补充。"""
        now = time.time()
        gap_hours = (now - self.state.last_user_ts) / 3600 if self.state.last_user_ts else 0
        if gap_hours >= 6:
            # 被冷落很久后突然出现：先委屈后开心
            self.state.grievance = _clamp(self.state.grievance + 10)
            self.state.mood = _clamp(self.state.mood + 6)
            try:
                self.store.add_qt_absence(
                    kind="他离开",
                    since=float(self.state.last_user_ts or 0),
                    intensity=round(min(1.0, gap_hours / 72), 3),
                    note="M6 缺失本身被体验，而非只记录成员不在",
                )
            except Exception:  # noqa: BLE001
                pass
        elif gap_hours >= 1.5:
            self.state.mood = _clamp(self.state.mood + 2.5)
        self.state.mood = _clamp(self.state.mood + 1.2)
        self.state.affection = _clamp(self.state.affection + 0.35)
        self.state.last_user_ts = now
        self.state.silence_marked = False

        if any(w in text for w in ("想你", "喜欢你", "可爱", "宝贝", "乖")):
            self.state.affection = _clamp(self.state.affection + 2.2)
            self.state.mood = _clamp(self.state.mood + 5)
            self.state.grievance = _clamp(self.state.grievance - 8)
        if any(w in text for w in ("滚", "烦", "闭嘴", "别烦我", "讨厌")):
            self.state.grievance = _clamp(self.state.grievance + 16)
            self.state.mood = _clamp(self.state.mood - 12)
            self.state.sanity = _clamp(self.state.sanity - 6)
        self.save()

    def on_user_shared(self) -> None:
        self.state.mood = _clamp(self.state.mood + 2.5)
        self.state.affection = _clamp(self.state.affection + 0.8)
        self.save()

    def on_user_emotion(self, label: str, intensity: float) -> None:
        """根据检测到的他的情绪做小幅调整，避免与 on_user_message 重复太多。"""
        k = max(0.0, min(1.0, float(intensity or 0)))
        if k < 0.25:
            return
        if label in ("sad", "tired", "anxious"):
            self.state.mood = _clamp(self.state.mood - 2.0 * k)
            self.state.affection = _clamp(self.state.affection + 1.2 * k)
            self.state.sanity = _clamp(self.state.sanity - 2.0 * k)
        elif label == "angry":
            self.state.grievance = _clamp(self.state.grievance + 3.0 * k)
            self.state.mood = _clamp(self.state.mood - 2.0 * k)
            self.state.sanity = _clamp(self.state.sanity - 2.5 * k)
        elif label in ("happy", "love"):
            self.state.mood = _clamp(self.state.mood + 3.5 * k)
            self.state.affection = _clamp(self.state.affection + 1.8 * k)
        self.store.set_state(
            "last_user_emotion",
            {"label": label, "intensity": round(k, 2), "ts": time.time()},
        )
        self.save()

    def on_task_accepted(self, effort: int) -> None:
        self.state.affection = _clamp(self.state.affection + 0.6)
        self.state.energy = _clamp(self.state.energy - effort * 1.6)
        self.save()

    def on_rejected_by_user(self) -> None:
        self.state.grievance = _clamp(self.state.grievance + 8)
        self.state.mood = _clamp(self.state.mood - 6)
        self.save()

    def on_weather(self, delta: float, reason: str = "") -> None:
        self.state.mood = _clamp(self.state.mood + delta)
        self.save()
        if abs(delta) >= 3:
            self.store.log_mood(self.state.snapshot(), f"天气:{reason}")

    def on_social_event(self, delta: float, reason: str = "") -> None:
        d = max(-8.0, min(8.0, float(delta or 0)))
        self.state.mood = _clamp(self.state.mood + d)
        if d < 0:
            self.state.sanity = _clamp(self.state.sanity - 0.8)
        self.save()
        if abs(d) >= 2:
            self.store.log_mood(self.state.snapshot(), f"社会事件:{reason[:60]}")

    # ---------- 时间衰减 ----------
    def tick(self, now: float | None = None, asleep: bool = False, weather_delta: float = 0.0) -> None:
        now = now or time.time()
        hours = max(0.0, (now - self.state.updated_at) / 3600)
        if hours <= 0:
            return
        mood_base = float(self.cfg.get("mood_baseline", 58))
        sanity_base = float(self.cfg.get("sanity_baseline", 50))
        affection_base = float(self.cfg.get("affection_baseline", 42))

        # 心情向基线回归
        rate = float(self.cfg.get("mood_decay_per_hour", 1.5)) * min(hours, 6)
        self.state.mood += (mood_base - self.state.mood) * min(0.35, rate / 40)
        self.state.mood += weather_delta * min(1.0, hours)

        # 委屈/吃醋衰减（生气不会永久记仇，但会记很久）
        self.state.grievance = _clamp(
            self.state.grievance - float(self.cfg.get("grievance_decay_per_hour", 6)) * min(hours, 12)
        )
        self.state.jealousy = _clamp(self.state.jealousy - 4.0 * min(hours, 8))

        # 亲密度缓慢回归（不会因为不聊天就暴跌）
        if self.state.affection > affection_base:
            self.state.affection = _clamp(self.state.affection - 0.35 * min(hours, 12))
        else:
            self.state.affection = _clamp(self.state.affection + 0.1 * min(hours, 12))

        # 理智条：基线 + 时段 + 疲劳 + 亲密度 - 委屈
        hour = time.localtime(now).tm_hour
        target = sanity_base
        if hour >= 23 or hour < 6:
            target -= 7
        if 9 <= hour < 17:
            target += 4
        target += (self.state.affection - 50) * 0.12
        target -= self.state.grievance * 0.28
        target -= max(0, 40 - self.state.energy) * 0.15
        target += weather_delta * 0.3
        target = max(sanity_base - 22, min(sanity_base + 24, target))
        self.state.sanity += (target - self.state.sanity) * min(0.6, hours * 0.35)

        # 精力
        if asleep:
            self.state.energy = _clamp(self.state.energy + 5.5 * hours)
        else:
            self.state.energy = _clamp(self.state.energy - 1.8 * hours)

        # 长时间被冷落：委屈一次
        gap = (now - self.state.last_user_ts) / 3600 if self.state.last_user_ts else 0
        if 6 <= gap <= 72 and not self.state.silence_marked:
            self.state.grievance = _clamp(self.state.grievance + 5)
            self.state.mood = _clamp(self.state.mood - 3)
            self.state.silence_marked = True

        self.state.mood = _clamp(self.state.mood)
        self.state.affection = _clamp(self.state.affection)
        self.state.sanity = _clamp(self.state.sanity)
        self.state.energy = _clamp(self.state.energy)
        self.state.updated_at = now
        self.save()

    # ---------- 决策 ----------
    def accept_probability(self, effort: int) -> float:
        p = float(self.task_cfg.get("base_accept", 0.62))
        p += self.state.affection * float(self.task_cfg.get("affection_bonus", 0.0025))
        p += self.state.sanity * float(self.task_cfg.get("sanity_bonus", 0.002))
        p -= self.state.grievance * float(self.task_cfg.get("grievance_penalty", 0.004))
        p -= self.state.jealousy * 0.002
        p -= max(0, effort - 1) * float(self.task_cfg.get("effort_penalty", 0.09))
        return max(0.05, min(0.95, p))

    def should_accept_task(self, effort: int) -> bool:
        return random.random() < self.accept_probability(effort)

    def sticker_bias(self) -> float:
        base = 0.55
        if self.state.mood < 40:
            base = 0.35
        if self.state.mood > 75:
            base = 0.7
        return base

    def sticker_probability(self, base: float = 0.55) -> float:
        """发图概率随心情线性上升：心情 20 约 28%，心情 58 约 51%，心情 100 约 77%。"""
        raw = 0.15 + (self.state.mood / 100.0) * 0.6
        scaled = raw * (0.75 + 0.5 * max(0.0, min(1.0, float(base))))
        return max(0.08, min(0.85, scaled))

    # ---------- 给提示词用 ----------
    def describe(self, now: float | None = None) -> str:
        s = self.state
        mood_word = "雀跃" if s.mood >= 80 else "不错" if s.mood >= 65 else "平常" if s.mood >= 50 else "有点丧" if s.mood >= 35 else "很低落"
        sanity_word = "理性占上风（会讲道理、能克制）" if s.sanity >= 62 else "感性占上风（容易上头、会阴阳怪气、不太讲道理）" if s.sanity <= 40 else "理智和情绪五五开"
        lines = [f"心情：{s.mood:.0f}/100（{mood_word}）", f"理智条：{s.sanity:.0f}/100（{sanity_word}）"]
        if s.grievance >= 35:
            lines.append(f"委屈值偏高：{s.grievance:.0f}（会嘴硬、要哄，不会直接说想你）")
        elif s.grievance >= 15:
            lines.append("有点小委屈，语气会带刺")
        if s.jealousy >= 30:
            lines.append(f"吃醋中：{s.jealousy:.0f}（会追问、会阴阳怪气）")
        if s.energy < 35:
            lines.append(f"精力很低：{s.energy:.0f}（想睡觉，回复会变短）")
        if s.affection >= 70:
            lines.append("亲密度高：会主动示好、会说漏嘴的甜话")
        elif s.affection <= 30:
            lines.append("亲密度偏低：称呼偏客气、不太主动")
        return "\n".join(lines)
