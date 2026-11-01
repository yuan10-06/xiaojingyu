"""拟真节奏：读消息延迟、打字耗时、分条发送。"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OutSegment:
    kind: str                 # text | sticker | face
    payload: Any = None
    delay: float = 0.0        # 发送前等待秒数

    def __repr__(self) -> str:  # 便于模拟模式打印
        return f"<{self.kind} {str(self.payload)[:24]!r} +{self.delay:.1f}s>"


@dataclass
class ReplyPlan:
    segments: list[OutSegment] = field(default_factory=list)
    recall: dict[str, Any] | None = None

    @property
    def total_delay(self) -> float:
        return sum(s.delay for s in self.segments)


def split_text(text: str, max_len: int = 26) -> list[str]:
    """把过长的段落按标点拆成更像真人的短句，同时清掉换行和多余空格。"""
    text = re.sub(r"[\r\n]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if len(text) <= max_len:
        return [text] if text else []
    parts = re.split(r"(?<=[。！？!?~…])", text)
    if len(parts) == 1:
        # 没有标点时按空格切片，避免把一长串话塞进同一条
        parts = [p for p in text.split(" ") if p]
    merged: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if merged and len(merged[-1]) + len(p) <= max_len:
            merged[-1] += p
        else:
            merged.append(p)
    return merged or [text[:max_len]]


class Timing:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.min_read = float(cfg.get("min_read_delay", 1.5))
        self.max_read = float(cfg.get("max_read_delay", 22))
        self.busy_extra = cfg.get("busy_extra_delay", [45, 240])
        self.typing_speed = float(cfg.get("typing_speed", 5.5))
        self.overhead = float(cfg.get("typing_overhead", 0.7))
        self.gap = cfg.get("segment_gap", [5, 12])
        self.late_chance = float(cfg.get("late_reply_chance", 0.08))
        self.slow_chance = float(cfg.get("slow_reply_chance", 0.18))
        self.slow_extra = cfg.get("slow_extra", [60, 180])

    def read_delay(self, *, busy: bool, asleep: bool, sanity: float, energy: float) -> float:
        # 5% 概率正好在看手机：稍快一点，但不是秒回
        if random.random() < 0.05 and not busy and not asleep:
            return random.uniform(2.0, 5.0)
        delay = random.uniform(self.min_read, self.max_read)
        if busy:
            delay += random.uniform(*self.busy_extra)
        if asleep:
            # 被手机震醒：迷糊一会儿再回
            delay += random.uniform(15, 75)
        if energy < 35:
            delay += random.uniform(10, 60)
        if random.random() < self.slow_chance:
            delay += random.uniform(*self.slow_extra)
        if sanity < 40:
            delay *= random.uniform(0.7, 1.15)  # 上头的时候反而回得快
        if random.random() < self.late_chance:
            delay += random.uniform(60, 360)
        return delay

    def typing_time(self, text: str, sanity: float) -> float:
        base = len(text) / max(1.0, self.typing_speed) + self.overhead
        base *= random.uniform(0.75, 1.45)
        if sanity < 40:
            base *= 0.7
        return max(0.6, base)

    def build(
        self,
        segments: list[str],
        *,
        sticker: str | None = None,
        faces: list[str] | None = None,
        busy: bool = False,
        asleep: bool = False,
        sanity: float = 50,
        energy: float = 70,
        first_delay: float | None = None,
    ) -> ReplyPlan:
        plan = ReplyPlan()
        merged: list[str] = []
        for seg in segments:
            merged.extend(split_text(str(seg)))
        if not merged and not sticker and not faces:
            merged = ["嗯？"]

        # 90% 概率把表情包放在某种情绪之后；10% 单独先发一个表情
        sticker_first = sticker and random.random() < 0.12
        if sticker_first:
            plan.segments.append(OutSegment("sticker", sticker, 0.0))

        delay = first_delay if first_delay is not None else self.read_delay(
            busy=busy, asleep=asleep, sanity=sanity, energy=energy
        )
        for i, text in enumerate(merged[:3]):
            if i > 0:
                delay = random.uniform(*self.gap)
            plan.segments.append(OutSegment("text", text, max(0.2, delay)))
            delay = self.typing_time(text, sanity)
            # 后一条的等待 = 打字时间 + 段间隔
        if sticker and not sticker_first:
            plan.segments.append(OutSegment("sticker", sticker, random.uniform(0.6, 2.0)))
        for face in (faces or [])[:1]:
            plan.segments.append(OutSegment("face", face, random.uniform(0.4, 1.2)))
        return plan

    def build_for_sleep(self, segments: list[str], sticker: str | None, until_wake: float) -> ReplyPlan:
        """睡着时的消息：压到醒来再回，但保留一点"翻身看手机"的可能。"""
        plan = self.build(segments, sticker=sticker, asleep=True, sanity=40, energy=20, first_delay=until_wake)
        return plan
