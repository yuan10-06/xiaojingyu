"""主动消息：每天 4~8 条，按时间窗、配额、冷落时长和心情决定。"""
from __future__ import annotations

import datetime as dt
import random
import time
from typing import Any

from .clock import Clock
from .db import Store
from .mood import Mood
from .persona import Persona
from .prompt import topic_for_now


class Proactive:
    def __init__(self, store: Store, persona: Persona, clock: Clock, mood: Mood, cfg: dict[str, Any]):
        self.store = store
        self.persona = persona
        self.clock = clock
        self.mood = mood
        self.cfg = cfg

    # ---------- 配额 ----------
    def _day_key(self) -> str:
        return self.clock.now().strftime("%Y-%m-%d")

    def quota(self) -> int:
        lo, hi = self.cfg.get("daily_quota", [4, 8])
        seed = int(self.clock.now().strftime("%Y%m%d"))
        return random.Random(seed).randint(int(lo), int(hi))

    def sent_today(self) -> int:
        start = self.clock.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        return self.store.proactive_since(start)

    def remaining(self) -> int:
        return max(0, self.quota() - self.sent_today())

    def in_window(self) -> bool:
        cur = self.clock.minutes_of_day()
        for start, end in self.cfg.get("windows", []):
            s = Clock._minutes(start)
            e = Clock._minutes(end)
            if s <= e and s <= cur <= e:
                return True
            if s > e and (cur >= s or cur <= e):  # 跨零点
                return True
        return False

    # ---------- 是否该发 ----------
    def check(self) -> tuple[bool, str]:
        if self.remaining() <= 0:
            return False, "今日配额已用完"
        if not self.in_window():
            return False, "不在活跃时间窗"
        gap_minutes = (self.clock.now_ts() - self.store.last_proactive_ts()) / 60
        min_gap = float(self.cfg.get("min_gap_minutes", 75))
        if gap_minutes < min_gap:
            return False, f"距上次主动才 {gap_minutes:.0f} 分钟"
        last_user = self.store.last_message_ts("user")
        after_chat = float(self.cfg.get("after_chat_minutes", 12))
        if last_user and (self.clock.now_ts() - last_user) / 60 < after_chat:
            return False, "刚聊过，不打扰"
        if self.clock.is_asleep():
            return False, "已睡着"
        # 心情很差时仍会发，但概率降低（她需要被哄）
        if self.mood.state.grievance > 50 and random.random() < 0.5:
            return False, "还在赌气"
        return True, "ok"

    def pick_topic(self) -> str:
        topics = self.cfg.get("topics", ["尬聊（问在干嘛）"])
        last = self.store.last_topic(6)
        hour = self.clock.now().hour
        base = float(self.persona.get("proactive_bias", 0.6))
        if self.mood.state.mood < 40:
            topics = ["今天有点累", "深夜情绪", "想问你个事"] + list(topics)
        return topic_for_now(topics, last, hour, base)

    def next_window_seconds(self) -> float:
        return self.clock.seconds_until_next_window(self.cfg.get("windows", []))

    def params(self) -> dict[str, Any]:
        return {"quota": self.quota(), "sent": self.sent_today(), "remaining": self.remaining()}
