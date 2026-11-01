"""时间/作息判定（统一用 Asia/Shanghai，Windows 缺 tzdata 时退回本地时间）。"""
from __future__ import annotations

import datetime as dt
import time
from typing import Any

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


class Clock:
    def __init__(self, tz: str, schedule: dict[str, Any]):
        self.tz = tz
        self.schedule = schedule
        try:
            self.zone = ZoneInfo(tz) if ZoneInfo else None
        except Exception:
            self.zone = None

    def now(self) -> dt.datetime:
        return dt.datetime.now(self.zone) if self.zone else dt.datetime.now()

    def now_ts(self) -> float:
        """纳秒级时间戳换算成秒；用于内部间隔计算，减少浮点漂移。"""
        return time.time_ns() / 1_000_000_000

    def now_ns(self) -> int:
        return time.time_ns()

    @staticmethod
    def _minutes(hhmm: str) -> int:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)

    def minutes_of_day(self) -> int:
        n = self.now()
        return n.hour * 60 + n.minute

    def is_asleep(self, when: dt.datetime | None = None) -> bool:
        n = when or self.now()
        cur = n.hour * 60 + n.minute
        wake = self._minutes(self.schedule.get("wake", "08:00"))
        sleep = self._minutes(self.schedule.get("sleep", "00:30"))
        if sleep < wake:
            return sleep <= cur < wake
        return cur >= sleep or cur < wake

    def is_busy(self, when: dt.datetime | None = None) -> bool:
        n = when or self.now()
        if n.weekday() >= 5:
            return False
        cur = n.hour * 60 + n.minute
        for start, end in self.schedule.get("class_blocks", []):
            if self._minutes(start) <= cur < self._minutes(end):
                return True
        return False

    def seconds_until_wake(self) -> float:
        n = self.now()
        wake = self._minutes(self.schedule.get("wake", "08:00"))
        cur = n.hour * 60 + n.minute
        delta = (wake - cur) % 1440 or 1440
        return float(delta * 60)

    def part_of_day(self) -> str:
        h = self.now().hour
        if h < 6:
            return "凌晨"
        if h < 9:
            return "早上"
        if h < 12:
            return "上午"
        if h < 14:
            return "中午"
        if h < 18:
            return "下午"
        if h < 23:
            return "晚上"
        return "深夜"

    def hhmm(self) -> str:
        return self.now().strftime("%H:%M")

    def date_line(self) -> str:
        n = self.now()
        week = "一二三四五六日"[n.weekday()]
        return f"{n.year}年{n.month}月{n.day}日 星期{week} {n.strftime('%H:%M')}"

    def seconds_until_next_window(self, windows: list[list[str]]) -> float:
        """返回距离下一个主动消息时间窗的小时数（用于调度）。"""
        now = self.now()
        cur = now.hour * 3600 + now.minute * 60 + now.second
        best = None
        for start, end in windows:
            s = self._minutes(start) * 60
            e = self._minutes(end) * 60
            if s <= cur <= e:
                return 0.0
            wait = s - cur if s > cur else (s + 86400 - cur)
            best = wait if best is None else min(best, wait)
        return float(best if best is not None else 3600)
