"""5.0 生理状态：月经周期、饥饿、疼痛、疲劳。

所有数值只存本地 state.body，每 10 分钟推进一步：
- 月经：按周期天数计算经期 / 排卵期 / 经前，经期自带痛经
- 饥饿：随时间上升，三餐时间自动吃饭
- 疼痛：经期痛经 + 低频随机疼痛（头痛/胃痛/腰酸/嗓子疼）
- 疲劳：醒着累积、睡着恢复，疼痛会加重疲劳

权重按“偏轻档”配置在 persona.yaml 的 body 段，影响心情、理智、精力，
并在提示词里转成“感受”，不直接报数值。
"""
from __future__ import annotations

import random
import time
from typing import Any

from .db import Store


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(v)))


MEALS = ((8.5, "早饭"), (12.5, "午饭"), (18.5, "晚饭"))
PAIN_KINDS = (("头痛", 0.4), ("胃痛", 0.3), ("腰酸", 0.2), ("嗓子疼", 0.1))


class Body:
    def __init__(self, store: Store, persona_cfg: dict[str, Any]):
        self.store = store
        self.cfg = persona_cfg.get("body", {}) or {}
        raw = store.get_state("body") or {}
        if raw:
            self.state = {**self._defaults(), **raw}
        else:
            self.state = self._initial()
            self.save()
        self._last_hours = 0.0

    # ---------- 初始化 ----------
    def _defaults(self) -> dict[str, Any]:
        return {
            "hunger": 40.0,
            "pain": 0.0,
            "pain_type": "",
            "pain_until": 0.0,
            "cramp": 0.0,
            "fatigue": 20.0,
            "cycle_start": time.time(),
            "cycle_len": int(self.cfg.get("cycle_days", 28)),
            "period_len": int(self.cfg.get("period_days", 5)),
            "cycle_day": 1,
            "phase": "卵泡期",
            "last_meal_ts": time.time() - 2 * 3600,
            "last_tick": time.time(),
            "updated_at": time.time(),
        }

    def _initial(self) -> dict[str, Any]:
        """首次运行：随机落在周期某一天，不刻意安排成经期。"""
        now = time.time()
        state = self._defaults()
        cycle_len = int(self.cfg.get("cycle_days", 28))
        day = random.randint(1, cycle_len)
        state.update(
            {
                "cycle_start": now - (day - 1) * 86400,
                "cycle_day": day,
                "last_meal_ts": now - random.uniform(1.5, 4.0) * 3600,
                "hunger": random.uniform(30, 55),
                "fatigue": random.uniform(15, 30),
            }
        )
        self.state = state
        state["phase"] = self._phase(day)
        state["cramp"] = self._cramp(day)
        return state

    def save(self) -> None:
        self.state["updated_at"] = time.time()
        self.store.set_state("body", self.state)

    def reload(self) -> None:
        """从库里重新读身体状态，多个入口共用同一具身体时用。"""
        raw = self.store.get_state("body") or {}
        if raw:
            self.state = {**self._defaults(), **raw}
        self._last_hours = 0.0

    # ---------- 周期 ----------
    def _phase(self, day: int) -> str:
        period_len = int(self.state.get("period_len") or self.cfg.get("period_days", 5))
        cycle_len = int(self.state.get("cycle_len") or self.cfg.get("cycle_days", 28))
        pms_days = int(self.cfg.get("pms_days", 7))
        if day <= period_len:
            return "经期"
        if day > cycle_len - pms_days:
            return "经前"
        if abs(day - (cycle_len - 14)) <= 1:
            return "排卵期"
        if day > cycle_len // 2:
            return "黄体期"
        return "卵泡期"

    def _cramp(self, day: int) -> float:
        period_len = int(self.state.get("period_len") or self.cfg.get("period_days", 5))
        if day > period_len:
            return 0.0
        if day <= 2:
            lo, hi = self.cfg.get("period_extra_pain", [20, 28])
        else:
            lo, hi = self.cfg.get("period_late_pain", [6, 14])
        # 越往后越轻，不逐次抖动
        progress = (day - 1) / max(1, period_len)
        return round(float(hi) - (float(hi) - float(lo)) * progress, 1)

    # ---------- 时间推进 ----------
    def tick(self, now: float | None = None, asleep: bool = False) -> dict[str, Any]:
        now = now or time.time()
        s = self.state
        hours = max(0.0, min(8.0, (now - float(s.get("last_tick") or now)) / 3600))
        if hours <= 0.01:
            self._last_hours = 0.0
            return {"hours": 0.0}
        self._last_hours = hours
        period_started = False

        # 月经周期推进
        day = int((now - float(s["cycle_start"])) // 86400) + 1
        while day > int(s["cycle_len"]):
            base = int(self.cfg.get("cycle_days", 28))
            s["cycle_start"] = float(s["cycle_start"]) + int(s["cycle_len"]) * 86400
            s["cycle_len"] = base + random.randint(-1, 2)
            day = int((now - float(s["cycle_start"])) // 86400) + 1
            period_started = True
        s["cycle_day"] = day
        s["phase"] = self._phase(day)
        s["cramp"] = self._cramp(day)

        # 饥饿
        rate = float(
            self.cfg.get("hunger_sleep_per_hour", 1.5)
            if asleep
            else self.cfg.get("hunger_per_hour", 4.0)
        )
        s["hunger"] = _clamp(float(s["hunger"]) + rate * hours)
        meal = ""
        if not asleep:
            for ts, name in self._meal_times(now):
                if float(s["last_meal_ts"]) < ts <= now:
                    meal = name
            if meal:
                s["hunger"] = random.uniform(10, 22)
                s["last_meal_ts"] = now

        # 疼痛：随机疼 + 经期痛
        pain_started = ""
        if now > float(s.get("pain_until") or 0):
            s["pain"] = _clamp(float(s["pain"]) - 10.0 * hours)
            if float(s["pain"]) <= 0.1:
                s["pain"] = 0.0
                s["pain_type"] = ""
            if (
                not asleep
                and float(s["pain"]) <= 0
                and float(s["cramp"]) <= 0
                and random.random() < self._pain_chance_per_hour() * hours
            ):
                s["pain"] = round(random.uniform(18, 40), 1)
                s["pain_type"] = random.choices(
                    [k for k, _ in PAIN_KINDS], weights=[w for _, w in PAIN_KINDS]
                )[0]
                s["pain_until"] = now + random.uniform(1, 4) * 3600
                pain_started = str(s["pain_type"])

        # 疲劳
        pain_now = max(float(s["pain"]), float(s["cramp"]))
        if asleep:
            s["fatigue"] = _clamp(float(s["fatigue"]) - 12.0 * hours)
        else:
            s["fatigue"] = _clamp(
                float(s["fatigue"]) + 2.2 * hours + pain_now * 0.02 * hours
            )

        s["last_tick"] = now
        self.save()
        return {
            "hours": hours,
            "period_started": period_started,
            "pain_started": pain_started,
            "meal": meal,
        }

    def _meal_times(self, now: float) -> list[tuple[float, str]]:
        lt = time.localtime(now)
        base = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
        return [(base + h * 3600, name) for h, name in MEALS]

    def _pain_chance_per_hour(self) -> float:
        # 低频：每周 1~2 次
        lo, hi = self.cfg.get("pain_events_per_week", [1, 2])
        return (float(lo) + float(hi)) / 2 / 7 / 24

    # ---------- 对外状态 ----------
    @property
    def total_pain(self) -> float:
        return max(float(self.state.get("pain") or 0), float(self.state.get("cramp") or 0))

    def unwell(self) -> bool:
        return (
            self.total_pain >= 40
            or float(self.state.get("fatigue") or 0) >= 75
            or float(self.state.get("hunger") or 0) >= 85
        )

    def reply_factor(self) -> float:
        return 0.8 if self.unwell() else 1.0

    def apply_to_mood(self, mood) -> None:
        """把生理状态折算成心情 / 理智 / 精力的缓慢漂移。"""
        hours = self._last_hours
        if hours <= 0:
            return
        s = self.state
        pain = self.total_pain
        hunger_over = max(0.0, float(s["hunger"]) - 50.0)
        fatigue_over = max(0.0, float(s["fatigue"]) - 60.0)
        mood_d = -(
            pain * float(self.cfg.get("pain_mood_per_hour", 0.04))
            + hunger_over * float(self.cfg.get("hunger_mood_per_hour", 0.02))
            + fatigue_over * float(self.cfg.get("fatigue_mood_per_hour", 0.012))
        ) * hours
        sanity_d = -(
            pain * float(self.cfg.get("pain_sanity_per_hour", 0.03))
            + hunger_over * float(self.cfg.get("hunger_sanity_per_hour", 0.015))
            + fatigue_over * float(self.cfg.get("fatigue_sanity_per_hour", 0.008))
        ) * hours
        energy_d = -(
            pain * float(self.cfg.get("pain_energy_per_hour", 0.012))
            + fatigue_over * float(self.cfg.get("fatigue_energy_per_hour", 0.01))
        ) * hours
        if s.get("phase") == "经期" and int(s.get("cycle_day") or 0) <= 2:
            mood_d -= float(self.cfg.get("period_mood_per_hour", 0.5)) * hours
            energy_d -= float(self.cfg.get("period_energy_per_hour", 0.5)) * hours
        elif s.get("phase") == "经前":
            mood_d -= float(self.cfg.get("pms_mood_per_hour", 0.3)) * hours
            sanity_d -= float(self.cfg.get("pms_sanity_per_hour", 0.2)) * hours

        mood.state.mood = _clamp(mood.state.mood + mood_d)
        mood.state.sanity = _clamp(mood.state.sanity + sanity_d)
        mood.state.energy = _clamp(mood.state.energy + energy_d)
        mood.save()
        if abs(mood_d) + abs(sanity_d) + abs(energy_d) >= 4:
            mood.store.log_mood(mood.state.snapshot(), "生理状态")

    def describe(self) -> str:
        s = self.state
        parts: list[str] = []
        day = int(s.get("cycle_day") or 1)
        phase = str(s.get("phase") or "")
        if phase == "经期":
            parts.append(f"经期第{day}天")
        elif phase == "经前":
            parts.append("经前一周，情绪有点压不住")
        pain = self.total_pain
        if pain >= 40:
            if s.get("pain_type"):
                parts.append(f"{s['pain_type']}得明显")
            else:
                parts.append("小腹坠着疼，坐着都不舒服")
        elif pain >= 18:
            if s.get("pain_type"):
                parts.append(f"{s['pain_type']}隐隐作痛")
            else:
                parts.append("小腹隐隐坠着")
        hunger = float(s.get("hunger") or 0)
        if hunger >= 85:
            parts.append("饿得胃里发空")
        elif hunger >= 65:
            parts.append("有点饿了")
        fatigue = float(s.get("fatigue") or 0)
        if fatigue >= 80:
            parts.append("困得眼睛睁不开")
        elif fatigue >= 60:
            parts.append("有点乏，想躺着")
        return "；".join(parts) or "身体没什么特别的"

    def dialogue_hint(self) -> str:
        """给表达系统的生理期/身体行为提示，不是数值播报。"""
        s = self.state
        phase = str(s.get("phase") or "")
        day = int(s.get("cycle_day") or 0)
        pain = self.total_pain
        hunger = float(s.get("hunger") or 0)
        fatigue = float(s.get("fatigue") or 0)
        lines: list[str] = []
        if phase == "经期" and day <= 2:
            lines.append(
                "经期前两天，小腹坠疼、脾气冲，句子比平时短，不想被讲道理；"
                "他关心你就嘴硬两句，但别硬撑着说没事。"
            )
        elif phase == "经期":
            lines.append(
                "经期后段，还是累、容易烦，别主动开长话题；他问就照实说，别装没事。"
            )
        elif phase == "经前":
            lines.append(
                "经前一周，情绪有点压不住，看谁都不顺眼，容易因为小事刺他；"
                "别主动找茬，也别长篇解释。"
            )
        if pain >= 40:
            lines.append("现在疼得明显，不想多解释，回短句，少发表情包。")
        elif fatigue >= 60:
            lines.append("现在很困/很累，句子短，不主动找话题。")
        elif hunger >= 80:
            lines.append("现在很饿，注意力在吃的上，别长篇聊正事。")
        return " ".join(lines)

    def status(self) -> str:
        s = self.state
        pain = self.total_pain
        pain_word = f"{s.get('pain_type') or '痛经'} {pain:.0f}" if pain > 0 else "无"
        return (
            f"{s.get('phase')}第{s.get('cycle_day')}天｜饥饿 {float(s.get('hunger')):.0f}"
            f"｜疼痛 {pain_word}｜疲劳 {float(s.get('fatigue')):.0f}"
            f"｜上次吃饭 {time.strftime('%H:%M', time.localtime(float(s.get('last_meal_ts') or 0)))}"
        )
