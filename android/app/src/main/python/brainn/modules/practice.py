"""实践黑箱：人格的上游生产者。

M11 不再是被 M12 调度的生产环节，而是位于 M2 之上、M8 / M4 / M9 之下的
上游供料者：先有劳动，才有被占用的时间、人情债与掌控感。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import time
import uuid
from typing import Any

from ..core.contracts import Proposal
from ..db import Store

log = logging.getLogger(__name__)

WORK_WORDS = ("兼职", "上班", "奶茶店", "排班", "作业", "上课", "实验", "小组")
RECOGNIZED = ("谢谢", "厉害", "夸", "不错", "牛", "辛苦了")
DENIED = ("不行", "差", "失望", "怎么这样", "没用", "搞什么")

LABOR_KINDS = {"work", "class", "study", "deadline"}

SKILL_BY_KIND = {"work": "奶茶", "class": "学习", "study": "学习", "deadline": "学习"}

# α 产出归属率：谁拿走了产出（奶茶店的产出归店里，她只拿到工资）
BASE_OWNERSHIP = {"work": 0.15, "class": 0.55, "study": 0.72, "deadline": 0.62}
# κ 过程自主度：被安排 vs 自己决定
BASE_AUTONOMY = {"work": 0.28, "class": 0.24, "study": 0.82, "deadline": 0.42}
# λ 劳动重复率
BASE_REPETITION = {"work": 0.86, "class": 0.56, "study": 0.58, "deadline": 0.66}
# 每小时劳动疲劳
FATIGUE_PER_HOUR = {"work": 6.0, "class": 3.0, "study": 2.0, "deadline": 2.5}
# 每小时技能成长
SKILL_GAIN_PER_HOUR = {"work": 0.12, "class": 0.04, "study": 0.045, "deadline": 0.02}

ARTIFACT_MIN_MINUTES = 10.0

# 空闲不是空白：没有日程时也要有具体的生活
IDLE_POOLS = {
    "早上": [
        {"title": "赖床刷手机", "kind": "leisure", "load": 0.12, "place": "宿舍"},
        {"title": "慢慢洗漱", "kind": "chore", "load": 0.25, "place": "宿舍"},
        {"title": "去食堂吃早饭", "kind": "chore", "load": 0.30, "place": "食堂"},
        {"title": "边听歌边收拾书包", "kind": "chore", "load": 0.20, "place": "宿舍"},
    ],
    "上午": [
        {"title": "在图书馆看闲书", "kind": "leisure", "load": 0.20, "place": "图书馆"},
        {"title": "刷手机", "kind": "leisure", "load": 0.12, "place": "宿舍"},
        {"title": "洗衣服", "kind": "chore", "load": 0.35, "place": "宿舍"},
        {"title": "和室友闲聊", "kind": "social", "load": 0.20, "place": "宿舍"},
        {"title": "看纪录片", "kind": "leisure", "load": 0.18, "place": "宿舍"},
    ],
    "中午": [
        {"title": "在食堂纠结吃什么", "kind": "chore", "load": 0.25, "place": "食堂"},
        {"title": "趴着午睡", "kind": "rest", "load": 0.05, "place": "宿舍"},
        {"title": "刷手机", "kind": "leisure", "load": 0.12, "place": "宿舍"},
        {"title": "慢慢走回宿舍", "kind": "leisure", "load": 0.15, "place": ""},
    ],
    "下午": [
        {"title": "追剧", "kind": "leisure", "load": 0.20, "place": "宿舍"},
        {"title": "在图书馆看闲书", "kind": "leisure", "load": 0.20, "place": "图书馆"},
        {"title": "去超市补点东西", "kind": "chore", "load": 0.35, "place": "校外"},
        {"title": "躺着发呆", "kind": "rest", "load": 0.05, "place": "宿舍"},
        {"title": "出去走走", "kind": "leisure", "load": 0.25, "place": "校外"},
        {"title": "学做一道新菜", "kind": "chore", "load": 0.40, "place": "宿舍"},
    ],
    "晚上": [
        {"title": "追剧", "kind": "leisure", "load": 0.20, "place": "宿舍"},
        {"title": "刷视频", "kind": "leisure", "load": 0.12, "place": "宿舍"},
        {"title": "和室友聊天", "kind": "social", "load": 0.20, "place": "宿舍"},
        {"title": "煮点东西吃", "kind": "chore", "load": 0.35, "place": "宿舍"},
        {"title": "下楼走走", "kind": "leisure", "load": 0.25, "place": "楼下"},
        {"title": "写点自己的东西", "kind": "leisure", "load": 0.15, "place": "宿舍"},
    ],
    "深夜": [
        {"title": "失眠刷手机", "kind": "leisure", "load": 0.10, "place": "宿舍"},
        {"title": "戴着耳机听歌", "kind": "rest", "load": 0.05, "place": "宿舍"},
        {"title": "翻来覆去睡不着", "kind": "rest", "load": 0.05, "place": "宿舍"},
    ],
}

IDLE_EFFECTS = {
    "rest": {"fatigue": -0.8, "alienation": -0.0020},
    "leisure": {"fatigue": -0.25, "alienation": -0.0015},
    "social": {"fatigue": -0.1, "alienation": -0.0010},
    "chore": {"fatigue": 0.35, "alienation": -0.0005},
    "sleep": {"fatigue": -1.2, "alienation": -0.0020},
}


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


def _minutes(hhmm: str) -> int:
    h, m = str(hhmm).split(":")
    return int(h) * 60 + int(m)


def _generic_stale_title(kind: str, title: str) -> str:
    """旧专业课程名换成通用说法，保留时间/类型/负荷不变。"""
    if "期" in title or "考试" in title:
        return "专业课考试"
    if kind == "class":
        return "上课"
    if kind == "study":
        return "复习"
    if kind == "deadline":
        return "交作业"
    return "专业课"


class PracticeModel:
    name = "practice"

    def __init__(
        self,
        store: Store,
        settings: dict[str, Any],
        clock,
        world=None,
        memory=None,
        intuition=None,
    ):
        self.store = store
        self.clock = clock
        self.world = world
        self.memory = memory
        self.intuition = intuition
        cfg = (settings.get("brainn") or {}).get("practice") or {}
        self.life = settings.get("life") or {}
        self.cfg = {
            "ownership": float(cfg.get("ownership", 0.55)),
            "autonomy": float(cfg.get("autonomy", 0.45)),
            "repetition": float(cfg.get("repetition", 0.65)),
            "alienation_threshold": float(cfg.get("alienation_threshold", 0.65)),
            "alienation_rate": float(cfg.get("alienation_rate", 0.35)),
            "skill_decay": float(cfg.get("skill_decay", 0.004)),
            "artifact_min_minutes": float(cfg.get("artifact_min_minutes", ARTIFACT_MIN_MINUTES)),
            "catchup_hours": float(cfg.get("catchup_hours", 48)),
            "catchup_step_minutes": float(cfg.get("catchup_step_minutes", 15)),
        }
        self.qt_cfg = settings.get("qt") or {}
        self.state = self._load(store.get_state("brainn_practice") or {})

    # ---------- 初始化与迁移 ----------
    def _load(self, raw: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        legacy = not raw.get("version")
        skills: dict[str, dict[str, float]] = {}
        for name, value in (raw.get("skills") or {}).items():
            if isinstance(value, dict):
                skills[str(name)] = {
                    "level": float(value.get("level", 50.0)),
                    "last_used": float(value.get("last_used", now)),
                    "decay_rate": float(value.get("decay_rate", self.cfg["skill_decay"])),
                }
            else:
                skills[str(name)] = {
                    "level": float(value),
                    "last_used": now,
                    "decay_rate": self.cfg["skill_decay"],
                }
        if not skills:
            skills = {
                "奶茶": {"level": 50.0, "last_used": now, "decay_rate": self.cfg["skill_decay"]},
                "做饭": {"level": 40.0, "last_used": now, "decay_rate": self.cfg["skill_decay"]},
                "学习": {"level": 45.0, "last_used": now, "decay_rate": self.cfg["skill_decay"]},
            }
        if legacy:
            ownership = self.cfg["ownership"]
            autonomy = self.cfg["autonomy"]
            repetition = self.cfg["repetition"]
            alienation = 1.0 - ownership
        else:
            ownership = _clamp(raw.get("ownership", self.cfg["ownership"]))
            autonomy = _clamp(raw.get("autonomy", self.cfg["autonomy"]))
            repetition = _clamp(raw.get("repetition", self.cfg["repetition"]))
            alienation = float(raw.get("alienation", 1.0 - ownership))
            if alienation > 1.0:  # 老库用 0~100 表示
                alienation = alienation / 100.0
        fatigue = float(raw.get("fatigue", raw.get("labor_fatigue", 10.0)))
        today = self.clock.now().date().isoformat()
        return {
            "version": 6,
            "skills": skills,
            "occupation": str(raw.get("occupation") or ""),
            "output_log": list(raw.get("output_log") or []),
            "ownership": round(ownership, 3),
            "autonomy": round(autonomy, 3),
            "repetition": round(repetition, 3),
            "alienation": round(_clamp(alienation), 3),
            "day_peak_alienation": round(_clamp(float(raw.get("day_peak_alienation", alienation))), 3),
            "last_day_peak_alienation": round(
                _clamp(float(raw.get("last_day_peak_alienation", alienation))), 3
            ),
            "fatigue": round(min(100.0, max(0.0, fatigue)), 2),
            "fatigue_applied": round(min(100.0, max(0.0, fatigue)), 2),
            "schedule": [],
            "schedule_day": "",
            "current": None,
            "next": None,
            "exam": {},
            "idle": None,
            "idle_log": list(raw.get("idle_log") or []),
            "last_idle_id": str(raw.get("last_idle_id") or ""),
            "catchup": raw.get("catchup") or {},
            "segment": raw.get("segment") if isinstance(raw.get("segment"), dict) else None,
            "day_key": str(raw.get("day_key") or today),
            "day_labor_minutes": dict(raw.get("day_labor_minutes") or {}),
            "last_day_key": str(raw.get("last_day_key") or ""),
            "his_time_minutes": float(raw.get("his_time_minutes") or 0.0),
            "last_his_time_minutes": float(raw.get("last_his_time_minutes") or 0.0),
            "settled_days": list(raw.get("settled_days") or []),
            "feedback_queue": list(raw.get("feedback_queue") or []),
            "last_feedback": str(raw.get("last_feedback") or ""),
            "last_writeback": raw.get("last_writeback") or {},
            "last_tick": float(raw.get("last_tick") or now),
        }

    # ---------- 日程（M11 供料给 M8） ----------
    def _build_schedule(self, now_dt: dt.datetime) -> None:
        weekly = self.life.get("weekly") or {}
        schedule: list[dict[str, Any]] = []
        # 含过去 3 天，供“应用关掉后回填”使用；显示仍只用今天及未来
        for offset in range(-3, 8):
            day = now_dt.date() + dt.timedelta(days=offset)
            items = weekly.get(day.weekday()) or weekly.get(str(day.weekday())) or []
            for index, item in enumerate(items):
                row = list(item) + ["", 0.5, ""]
                start, end, kind, title, load, place = row[:6]
                schedule.append(
                    {
                        "id": f"{day.isoformat()}-{start}-{kind}-{index}",
                        "date": day.isoformat(),
                        "start": str(start),
                        "end": str(end),
                        "kind": str(kind),
                        "title": str(title),
                        "load": float(load or 0.5),
                        "place": str(place or ""),
                    }
                )
        schedule.sort(key=lambda e: (e["date"], _minutes(e["start"])))
        self.state["schedule"] = schedule
        self.state["schedule_day"] = now_dt.date().isoformat()

    def _locate(self, now_dt: dt.datetime):
        now_min = now_dt.hour * 60 + now_dt.minute
        today = now_dt.date().isoformat()
        current: dict[str, Any] | None = None
        upcoming: list[dict[str, Any]] = []
        for event in self.state.get("schedule") or []:
            if event["date"] == today:
                start = _minutes(event["start"])
                end = _minutes(event["end"])
                if start <= now_min < end:
                    current = dict(event)
                    current["minutes_left"] = end - now_min
                elif start > now_min:
                    upcoming.append(event)
            elif event["date"] > today:
                upcoming.append(event)
        upcoming.sort(key=lambda e: (e["date"], _minutes(e["start"])))
        nxt = None
        if upcoming:
            event = upcoming[0]
            start = _minutes(event["start"])
            if event["date"] == today:
                minutes_left = start - now_min
            else:
                days = (dt.date.fromisoformat(event["date"]) - now_dt.date()).days
                minutes_left = days * 1440 + start - now_min
            nxt = dict(event)
            nxt["minutes_left"] = max(0, minutes_left)
        return current, nxt

    def _exam(self, now_dt: dt.datetime) -> dict[str, Any]:
        exam = self.life.get("exam") or {}
        if not exam.get("date"):
            return {}
        try:
            target = dt.date.fromisoformat(str(exam["date"]))
        except ValueError:
            return {}
        return {
            "title": str(exam.get("title") or "考试"),
            "date": target.isoformat(),
            "days_left": (target - now_dt.date()).days,
        }

    def _dt_at(self, ts: float) -> dt.datetime:
        zone = getattr(self.clock, "zone", None)
        return dt.datetime.fromtimestamp(ts, tz=zone) if zone else dt.datetime.fromtimestamp(ts)

    def _is_asleep(self, when_dt: dt.datetime) -> bool:
        try:
            return bool(self.clock.is_asleep(when_dt))
        except Exception:  # noqa: BLE001
            return False

    def _current_at(self, when_dt: dt.datetime) -> dict[str, Any] | None:
        today = when_dt.date().isoformat()
        now_min = when_dt.hour * 60 + when_dt.minute
        for event in self.state.get("schedule") or []:
            if event["date"] != today:
                continue
            start = _minutes(event["start"])
            end = _minutes(event["end"])
            if start <= now_min < end:
                current = dict(event)
                current["minutes_left"] = end - now_min
                return current
        return None

    @staticmethod
    def _part_of(hour: int) -> str:
        if hour < 9:
            return "早上"
        if hour < 12:
            return "上午"
        if hour < 14:
            return "中午"
        if hour < 18:
            return "下午"
        if hour < 23:
            return "晚上"
        return "深夜"

    def _sleep_block(self, when_dt: dt.datetime) -> dict[str, Any]:
        wake = self.clock._minutes(self.clock.schedule.get("wake", "08:00")) if hasattr(
            self.clock, "schedule"
        ) else 480
        sleep = self.clock._minutes(self.clock.schedule.get("sleep", "00:30")) if hasattr(
            self.clock, "schedule"
        ) else 30
        start = when_dt.replace(
            hour=sleep // 60, minute=sleep % 60, second=0, microsecond=0
        )
        end = when_dt.replace(hour=wake // 60, minute=wake % 60, second=0, microsecond=0)
        if end <= start:
            end = end + dt.timedelta(days=1)
        return {
            "id": f"{start.date().isoformat()}-sleep",
            "title": "睡觉",
            "kind": "sleep",
            "load": 1.0,
            "place": "宿舍",
            "start": start.strftime("%H:%M"),
            "end": end.strftime("%H:%M"),
            "start_ts": start.timestamp(),
            "end_ts": end.timestamp(),
        }

    def _idle_at(
        self, when_dt: dt.datetime, current: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """空闲时也要有具体生活：按 30 分钟槽位确定性选一个活动。"""
        if self._is_asleep(when_dt):
            return self._sleep_block(when_dt)
        if current:
            return None
        slot = when_dt.replace(
            minute=(when_dt.minute // 30) * 30, second=0, microsecond=0
        )
        end = slot + dt.timedelta(minutes=30)
        slot_min = slot.hour * 60 + slot.minute
        end_min = slot_min + 30
        for event in self.state.get("schedule") or []:
            if event["date"] != slot.date().isoformat():
                continue
            start = _minutes(event["start"])
            if slot_min < start < end_min:
                end_min = start
                break
        end = slot + dt.timedelta(minutes=end_min - slot_min)
        part = self._part_of(slot.hour)
        pool = IDLE_POOLS.get(part) or IDLE_POOLS["下午"]
        key = f"{slot.date().isoformat()}-{slot.strftime('%H:%M')}"
        seed = int(hashlib.md5(key.encode("utf-8")).hexdigest()[:8], 16)
        item = dict(pool[seed % len(pool)])
        item.update(
            {
                "id": key,
                "start": slot.strftime("%H:%M"),
                "end": end.strftime("%H:%M"),
                "start_ts": slot.timestamp(),
                "end_ts": end.timestamp(),
            }
        )
        return item

    # ---------- 节拍：先实践，后调制 ----------
    def tick(self, now: float, ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ctx = ctx if ctx is not None else {}
        now_dt = self.clock.now()
        if self.state.get("schedule_day") != now_dt.date().isoformat():
            self._build_schedule(now_dt)

        gap = now - float(self.state["last_tick"])
        if gap > self.cfg["catchup_hours"] * 3600:
            gap = self.cfg["catchup_hours"] * 3600
            self.state["catchup"] = {
                "from": now - gap,
                "to": now,
                "truncated": True,
                "hours": round(gap / 3600, 2),
            }
        if gap > 0:
            # 所有间隔都按“段开始时”的活动补算，日程边界不会丢分钟
            self._catch_up(now - gap, now)

        current, nxt = self._locate(now_dt)
        idle = self._idle_at(now_dt, current)
        exam = self._exam(now_dt)
        ctx["activity"] = current
        ctx["idle"] = idle
        ctx["next"] = nxt
        ctx["schedule"] = list(self.state.get("schedule") or [])
        ctx["exam"] = exam
        self.state["current"] = current
        self.state["idle"] = idle
        self._log_idle(idle)
        self.state["next"] = nxt
        self.state["exam"] = exam
        self.state["last_tick"] = now
        self.save()
        return []

    def _catch_up(self, start: float, end: float) -> None:
        """把应用没开/长时间没 tick 的时段按真实时间补算，而不是只算“现在”。"""
        step = max(300.0, self.cfg["catchup_step_minutes"] * 60)
        cursor = start
        steps = 0
        while cursor < end:
            step_end = min(end, cursor + step)
            # 用这一段“开始时”的活动，末尾那 15 分钟才不会被日程边界吃掉
            when = self._dt_at(cursor)
            self._roll_day(when)
            current = self._current_at(when)
            idle = self._idle_at(when, current)
            self.state["last_tick"] = cursor
            self._advance(
                step_end,
                when,
                (step_end - cursor) / 3600,
                current,
                idle,
                self._is_asleep(when),
            )
            cursor = step_end
            steps += 1
        self.state["catchup"] = {
            "from": start,
            "to": end,
            "steps": steps,
            "hours": round((end - start) / 3600, 2),
            "truncated": bool((self.state.get("catchup") or {}).get("truncated")),
        }

    def _roll_day(self, now_dt: dt.datetime) -> None:
        today = now_dt.date().isoformat()
        if self.state.get("day_key") == today:
            return
        self.state["last_day_key"] = str(self.state.get("day_key") or today)
        self.state["last_his_time_minutes"] = float(self.state.get("his_time_minutes") or 0)
        self.state["last_day_peak_alienation"] = max(
            float(self.state.get("day_peak_alienation") or 0),
            float(self.state.get("alienation") or 0),
        )
        self.state["day_peak_alienation"] = float(self.state.get("alienation") or 0)
        self.state["day_key"] = today
        self.state["day_labor_minutes"] = {}
        self.state["his_time_minutes"] = 0.0

    def _advance(
        self,
        now: float,
        now_dt: dt.datetime,
        hours: float,
        current: dict[str, Any] | None,
        idle: dict[str, Any] | None = None,
        asleep: bool = False,
    ) -> None:
        kind = str((current or {}).get("kind") or "")
        if kind in LABOR_KINDS:
            self._advance_segment(now, now_dt, hours, current or {})
            self._log_idle(None)
        else:
            self._finalize_segment(now)
            if asleep or (idle and idle.get("kind") == "sleep"):
                effect = IDLE_EFFECTS["sleep"]
            elif idle:
                effect = IDLE_EFFECTS.get(str(idle.get("kind") or ""), IDLE_EFFECTS["leisure"])
            elif current and kind == "chore":
                effect = IDLE_EFFECTS["chore"]
            else:
                effect = {"fatigue": -0.5, "alienation": -0.0015}
            self.state["fatigue"] = max(
                0.0, float(self.state["fatigue"]) + float(effect["fatigue"]) * hours
            )
            # 异化是累积慢变量，休息只能缓慢稀释，不能一觉归零
            self.state["alienation"] = max(
                0.0, float(self.state["alienation"]) + float(effect["alienation"]) * hours
            )
            self._log_idle(idle)
            if idle and idle.get("kind") == "chore" and any(
                word in str(idle.get("title") or "") for word in ("煮", "做饭", "做菜", "新菜")
            ):
                if "做饭" in self.state["skills"]:
                    self.state["skills"]["做饭"]["level"] = min(
                        100.0,
                        float(self.state["skills"]["做饭"]["level"]) + 0.05 * hours,
                    )
                    self.state["skills"]["做饭"]["last_used"] = now

        if kind in LABOR_KINDS:
            # 异化看的是“这段劳动”的产出归属，而不是被前几段劳动平均过的全局 α
            base = (
                self.world.ownership_for(kind)
                if self.world is not None
                else BASE_OWNERSHIP.get(kind, float(self.state["ownership"]))
            )
            target_alpha = _clamp(
                base + (float(self.state["autonomy"]) - 0.5) * 0.15, 0.05, 0.95
            )
            target = 1.0 - target_alpha
            speed = (1.0 - float(self.state["autonomy"])) * float(self.state["repetition"])
            delta = (target - float(self.state["alienation"])) * speed * self.cfg["alienation_rate"] * hours
            self.state["alienation"] = round(
                _clamp(float(self.state["alienation"]) + delta), 4
            )
        self.state["day_peak_alienation"] = round(
            max(
                float(self.state.get("day_peak_alienation") or 0),
                float(self.state["alienation"]),
            ),
            4,
        )

        used = SKILL_BY_KIND.get(kind)
        for name, skill in self.state["skills"].items():
            if name == used:
                continue
            skill["level"] = max(
                0.0, float(skill["level"]) - float(skill["decay_rate"]) * hours
            )

    def _log_idle(self, idle: dict[str, Any] | None) -> None:
        if not idle:
            self.state["last_idle_id"] = ""
            return
        if str(idle.get("kind") or "") == "sleep":
            return
        idle_id = str(idle.get("id") or "")
        if not idle_id or idle_id == str(self.state.get("last_idle_id") or ""):
            return
        self.state["last_idle_id"] = idle_id
        logs = list(self.state.get("idle_log") or [])
        logs.append(
            {
                "id": idle_id,
                "title": idle.get("title", ""),
                "kind": idle.get("kind", ""),
                "place": idle.get("place", ""),
                "start": idle.get("start", ""),
                "end": idle.get("end", ""),
            }
        )
        self.state["idle_log"] = logs[-80:]

    def _advance_segment(
        self, now: float, now_dt: dt.datetime, hours: float, current: dict[str, Any]
    ) -> None:
        block_id = str(current.get("id") or "")
        seg = self.state.get("segment")
        if seg and seg.get("id") != block_id:
            self._finalize_segment(now)
            seg = None
        if not seg:
            intuition_context = {
                "kind": str(current.get("kind") or ""),
                "title": str(current.get("title") or ""),
                "load": float(current.get("load") or 0.5),
                "place": str(current.get("place") or ""),
                "hour": _minutes(current.get("start") or "12:00") // 60,
            }
            seg = {
                "id": block_id,
                "kind": str(current.get("kind") or ""),
                "title": str(current.get("title") or ""),
                "load": float(current.get("load") or 0.5),
                "place": str(current.get("place") or ""),
                "start_ts": now,
                "minutes": 0.0,
                "day": now_dt.date().isoformat(),
                "intuition_context": intuition_context,
                "intuition_action": (
                    self.intuition.choose(intuition_context)
                    if self.intuition is not None
                    else ""
                ),
            }
            self.state["segment"] = seg
        block_minutes = _minutes(current.get("end") or "00:00") - _minutes(
            current.get("start") or "00:00"
        )
        # 只计算“进入这个日程块之后”的时间，避免把睡觉/空闲的整段时长灌进班次
        start_h, start_m = (int(x) for x in str(current.get("start") or "00:00").split(":"))
        block_start = now_dt.replace(
            hour=start_h, minute=start_m, second=0, microsecond=0
        ).timestamp()
        effective = max(float(self.state["last_tick"]), block_start)
        elapsed = max(0.0, (now - effective) / 60.0)
        room = max(0.0, block_minutes - float(seg["minutes"]))
        add = min(hours * 60.0, elapsed, room if room > 0 else elapsed)
        seg["minutes"] = float(seg["minutes"]) + add
        day_minutes = dict(self.state.get("day_labor_minutes") or {})
        day_minutes[seg["kind"]] = float(day_minutes.get(seg["kind"]) or 0) + add
        self.state["day_labor_minutes"] = day_minutes

        skill_name = SKILL_BY_KIND.get(seg["kind"])
        if skill_name and skill_name in self.state["skills"]:
            skill = self.state["skills"][skill_name]
            skill["level"] = min(
                100.0,
                float(skill["level"]) + SKILL_GAIN_PER_HOUR.get(seg["kind"], 0.04) * hours,
            )
            skill["last_used"] = now

        self.state["fatigue"] = min(
            100.0,
            float(self.state["fatigue"])
            + FATIGUE_PER_HOUR.get(seg["kind"], 2.0) * float(seg["load"]) * hours,
        )

    # ---------- Artifact：产物必须实体化 ----------
    def _artifact_name(self, kind: str, title: str) -> str:
        if kind == "work":
            return f"{title}的产出"
        if kind == "class":
            return f"{title}记录" if "实验" in title else f"{title}的课堂笔记"
        if kind == "study":
            if "小组" in title:
                return f"{title}的讨论记录"
            if "报告" in title:
                return f"{title}的草稿"
            return f"{title}的笔记"
        return f"{title}（已提交）"

    def _owner_hint(self, kind: str, title: str) -> str:
        if kind == "work":
            return "wangjie"
        if "小组" in title:
            return "chenyu"
        if "实验" in title:
            return "laok"
        return "zhang"

    def _finalize_segment(self, now: float | None = None) -> dict[str, Any] | None:
        seg = self.state.get("segment")
        if not seg:
            return None
        self.state["segment"] = None
        minutes = float(seg.get("minutes") or 0)
        if minutes < float(self.cfg["artifact_min_minutes"]):
            return None
        kind = str(seg.get("kind") or "")
        title = str(seg.get("title") or "")
        queue = list(self.state.get("feedback_queue") or [])
        feedback = queue[-1] if queue else "unseen"
        if queue:
            self.state["feedback_queue"] = queue[:-1]
        base = (
            self.world.ownership_for(kind, title)
            if self.world is not None
            else BASE_OWNERSHIP.get(kind, 0.6)
        )
        ownership = _clamp(
            base
            + (float(self.state["autonomy"]) - 0.5) * 0.15
            + (0.05 if feedback == "recognized" else -0.05 if feedback == "denied" else 0.0),
            0.10,
            0.95,
        )
        visibility = {"recognized": 0.85, "denied": 0.75}.get(feedback, 0.15)
        appraisal = {"recognized": 0.7, "denied": -0.7}.get(feedback, 0.0)
        artifact = {
            "id": uuid.uuid4().hex[:10],
            "name": self._artifact_name(kind, title),
            "created_at": float(now or time.time()),
            "day": str(seg.get("day") or self.state["day_key"]),
            "kind": kind,
            "skill_used": SKILL_BY_KIND.get(kind, "学习"),
            "ownership": round(ownership, 3),
            "visibility": round(visibility, 3),
            "appraisal": round(appraisal, 2),
            "irreversible": True,
            "minutes": round(minutes, 1),
            "feedback": feedback,
            "alienation": round(float(self.state.get("alienation") or 0), 3),
            "owner_hint": (
                self.world.owner_for(kind, title)
                if self.world is not None
                else self._owner_hint(kind, title)
            ),
            "colleague": "xiaoyu" if int(str(seg.get("day") or "0")[-2:] or 0) % 2 else "ajie",
        }
        log = list(self.state.get("output_log") or [])
        log.append(artifact)
        self.state["output_log"] = log
        try:
            content_hash = hashlib.sha1(
                f"{artifact['id']}:{artifact['name']}:{artifact['created_at']}".encode("utf-8")
            ).hexdigest()[:16]
            self.store.add_qt_artifact(
                artifact_id=str(artifact["id"]),
                kind=str(artifact["kind"]),
                name=str(artifact["name"]),
                content_hash=content_hash,
                owner=str(artifact.get("owner_hint") or ""),
                meta={
                    "day": artifact.get("day"),
                    "minutes": artifact.get("minutes"),
                    "visibility": artifact.get("visibility"),
                    "appraisal": artifact.get("appraisal"),
                    "feedback": artifact.get("feedback"),
                },
            )
        except Exception:  # noqa: BLE001
            pass
        self.state["ownership"] = round(
            _clamp(float(self.state["ownership"]) * 0.65 + ownership * 0.35), 3
        )
        self.state["autonomy"] = round(
            _clamp(
                float(self.state["autonomy"]) * 0.7
                + BASE_AUTONOMY.get(kind, 0.5) * 0.3
            ),
            3,
        )
        self.state["repetition"] = round(
            _clamp(
                float(self.state["repetition"]) * 0.6
                + BASE_REPETITION.get(kind, 0.6) * 0.4
            ),
            3,
        )
        self.state["occupation"] = self._occupation()
        if self.intuition is not None:
            self.intuition.observe(
                dict(seg.get("intuition_context") or {}),
                str(seg.get("intuition_action") or "work"),
                {"recognized": 1.0, "denied": -1.0}.get(feedback, 0.0),
            )
        if self.memory is not None:
            self.memory.add_facts(
                [
                    {
                        "key": f"实践_{artifact['day']}_{artifact['id']}",
                        "fact": (
                            f"{artifact['name']}：{artifact['minutes']:.0f} 分钟，"
                            f"可见度 {artifact['visibility']:.2f}，"
                            f"评价 {artifact['appraisal']:.1f}"
                        ),
                        "kind": "event",
                        "layer": "L3",
                        "intensity": 3 if feedback != "unseen" else 2,
                        "confidence": 0.9,
                    }
                ],
                source="M11.artifact",
            )
        self.state["last_feedback"] = feedback
        return artifact

    def _occupation(self) -> str:
        day = dict(self.state.get("day_labor_minutes") or {})
        work = float(day.get("work") or 0)
        study = sum(
            float(day.get(k) or 0) for k in ("class", "study", "deadline")
        )
        if work >= 60 and work >= study:
            return "奶茶店兼职"
        if study >= 60:
            return str(self.state.get("identity_short") or "学生")
        return str(self.state.get("occupation") or self.state.get("identity_short") or "学生")

    def set_identity_label(self, label: str) -> bool:
        """职业标签与缓存课表跟随最新人设，清掉旧专业残留。"""
        label = str(label or "").strip()[:40]
        if not label:
            return False
        changed = False
        if str(self.state.get("identity_short") or "") != label:
            self.state["identity_short"] = label
            changed = True
        if str(self.state.get("occupation") or "") != label:
            self.state["occupation"] = label
            changed = True
        for event in self.state.get("schedule") or []:
            if not isinstance(event, dict):
                continue
            title = str(event.get("title") or "")
            if "食品" in title:
                event["title"] = _generic_stale_title(str(event.get("kind") or ""), title)
                changed = True
        exam = self.state.get("exam")
        if isinstance(exam, dict) and "食品" in str(exam.get("title") or ""):
            exam["title"] = _generic_stale_title("exam", str(exam.get("title") or ""))
            changed = True
        if changed:
            self.save()
        return changed

    # ---------- 输入 ----------
    def on_event(self, percept, ctx: dict[str, Any]) -> list:
        text = str(getattr(percept, "text", "") or "")
        if text:
            kind = str((self.state.get("current") or {}).get("kind") or "")
            cost = 2.0 if kind in LABOR_KINDS else 0.5
            self.state["his_time_minutes"] = min(
                240.0, float(self.state.get("his_time_minutes") or 0) + cost
            )
        if any(word in text for word in WORK_WORDS):
            self.state["fatigue"] = min(
                100.0, float(self.state["fatigue"]) + 1.5
            )
        feedback = self.detect_feedback(text)
        if feedback != "unseen":
            if not self._apply_feedback_to_latest(feedback, text):
                queue = list(self.state.get("feedback_queue") or [])
                queue.append(feedback)
                self.state["feedback_queue"] = queue[-5:]
        self.save()
        return []

    @staticmethod
    def detect_feedback(text: str) -> str:
        if any(word in text for word in RECOGNIZED):
            return "recognized"
        if any(word in text for word in DENIED):
            return "denied"
        return "unseen"

    def _apply_feedback_to_latest(self, feedback: str, text: str = "") -> bool:
        """反馈落在最近一个还没被评价的产物上，直接回写 M13/M15/M16。"""
        now = time.time()
        entries = list(self.state.get("output_log") or [])
        for art in reversed(entries):
            if not isinstance(art, dict):
                continue
            if str(art.get("feedback") or "unseen") != "unseen":
                continue
            created = float(art.get("created_at") or 0)
            if created and now - created > 24 * 3600:
                break
            aid = str(art.get("id") or "")
            if not aid:
                continue
            art["feedback"] = feedback
            art["visibility"] = round(
                {"recognized": 0.85, "denied": 0.75}.get(feedback, 0.15), 3
            )
            art["appraisal"] = round(
                {"recognized": 0.7, "denied": -0.7}.get(feedback, 0.0), 2
            )
            try:
                verdict = {"recognized": "confirmed", "denied": "refuted"}.get(
                    feedback, "unverified"
                )
                self.store.set_qt_artifact_feedback(aid, feedback)
                self.store.set_qt_outcome_verdict(
                    aid,
                    verdict,
                    evidence=(f"她的反馈：{text[:120]}" if text else "她的反馈"),
                    confidence=0.6 if verdict != "unverified" else 0.2,
                )
                self.store.set_qt_metric_feedback(aid, feedback)
            except Exception:  # noqa: BLE001
                log.warning("M15/M16 反馈回写失败", exc_info=True)
            self.state["output_log"] = entries
            self.save()
            log.info("M15/M16 反馈回收：%s → %s", aid, feedback)
            return True
        return False

    def modulate_proposals(self, proposals: list, ctx: dict[str, Any]) -> list:
        """System 1 只给拍卖一个很小的强度修正，不产生文本。"""
        if self.intuition is None:
            return proposals
        activity = ctx.get("activity") or self.state.get("current") or {}
        if not activity:
            return proposals
        context = {
            "kind": str(activity.get("kind") or ""),
            "title": str(activity.get("title") or ""),
            "load": float(activity.get("load") or 0.5),
            "place": str(activity.get("place") or ""),
            "hour": self.clock.now().hour,
        }
        return self.intuition.modulate(proposals, context)

    def propose(self, ctx: dict[str, Any]) -> list[Proposal]:
        if str((self.state.get("current") or {}).get("kind") or "") not in LABOR_KINDS:
            return []
        fatigue = float(self.state["fatigue"])
        if fatigue >= 55:
            return []
        autonomy = float(self.state["autonomy"])
        return [
            Proposal(
                source="practice",
                intent="work",
                strength=round(min(1.0, 0.25 + autonomy * 0.35), 3),
                expected_reward=0.45,
                cost={"time": 0.5, "energy": round(fatigue / 100, 2)},
                payload={
                    "kind": "labor",
                    "occupation": self.state.get("occupation", ""),
                    "fatigue": round(fatigue, 1),
                },
            )
        ]

    # ---------- 每日结算：三条回写 ----------
    def settle(self) -> dict[str, Any]:
        """结算所有早于今天的未结算日；产物只增不减。"""
        self._finalize_segment()
        today = self.clock.now().date().isoformat()
        done = set(self.state.get("settled_days") or [])
        days = sorted(
            {
                str(item.get("day") or "")
                for item in self.state.get("output_log") or []
                if str(item.get("day") or "") < today and str(item.get("day") or "") not in done
            }
        )
        if not days:
            self.save()
            return {}
        combined: dict[str, Any] = {
            "self_worth": 0.0,
            "mood": 0.0,
            "grievance": 0.0,
            "agency": 0.0,
            "relation": [],
            "drives": {},
            "narrative": [],
            "days": [],
            "artifact_ids": [],
            "feedback": "unseen",
            "dominant": "",
            "alienation": 0.0,
        }
        for day in days:
            part = self._settle_day(day)
            if not part:
                continue
            for key in ("self_worth", "mood", "grievance", "agency"):
                combined[key] = round(combined[key] + float(part.get(key, 0)), 3)
            combined["relation"].extend(part.get("relation") or [])
            for key, value in (part.get("drives") or {}).items():
                combined["drives"][key] = round(
                    float(combined["drives"].get(key, 0)) + float(value), 2
                )
            combined["narrative"].extend(part.get("narrative") or [])
            combined["days"].append(day)
            combined["artifact_ids"].extend(part.get("artifact_ids") or [])
            combined["feedback"] = part.get("feedback") or combined["feedback"]
            combined["dominant"] = part.get("dominant") or combined["dominant"]
            combined["alienation"] = max(
                float(combined["alienation"]), float(part.get("alienation") or 0)
            )
        self.state["settled_days"] = list(done | set(days))[-60:]
        self.state["feedback_queue"] = []
        self.state["last_writeback"] = combined
        self.save()
        try:
            feedback = str(combined.get("feedback") or "unseen")
            verdict = {"recognized": "confirmed", "denied": "refuted"}.get(feedback, "unverified")
            refs = [str(x) for x in (combined.get("artifact_ids") or []) if str(x)]
            for aid in refs:
                self.store.add_qt_outcome(
                    claim_ref=aid,
                    verdict=verdict,
                    evidence=f"实践结算：{feedback}",
                    confidence=0.6 if verdict != "unverified" else 0.2,
                    source="practice.settle",
                )
                # 每个产物单独一条 M16 度量，避免把多个 id 拼成一条
                self.store.add_qt_metric(
                    prediction=f"practice:{aid}",
                    hit=feedback == "recognized",
                    match_score=0.8 if feedback == "recognized" else 0.2,
                    note=f"M16：劳动产物是否被承认（{feedback}）",
                )
        except Exception:  # noqa: BLE001
            pass
        return combined

    def _settle_day(self, day: str) -> dict[str, Any]:
        arts = [
            item
            for item in self.state.get("output_log") or []
            if str(item.get("day") or "") == day
        ]
        if not arts:
            return {}
        minutes = {"work": 0.0, "study": 0.0}
        for art in arts:
            if art.get("kind") == "work":
                minutes["work"] += float(art.get("minutes") or 0)
            else:
                minutes["study"] += float(art.get("minutes") or 0)
        feedback = str(arts[-1].get("feedback") or "unseen")
        ownership = float(self.state["ownership"])
        if day == str(self.state.get("last_day_key")):
            alienation = float(self.state.get("last_day_peak_alienation") or 0)
        else:
            alienation = max(float(a.get("alienation") or 0) for a in arts)

        writeback: dict[str, Any] = {
            "self_worth": 0.0,
            "mood": 0.0,
            "grievance": 0.0,
            "agency": 0.0,
            "alienation": round(alienation, 3),
            "artifact_ids": [a["id"] for a in arts],
        }
        if feedback == "recognized":
            writeback.update({"self_worth": 1.0, "mood": 2.0})
        elif feedback == "denied":
            writeback.update({"self_worth": -1.0, "grievance": 2.0})
        else:
            writeback.update({"self_worth": -0.4, "mood": -1.0})
        if ownership >= 0.65:
            writeback["self_worth"] += 0.5
            writeback["mood"] += 0.4
            writeback["agency"] += 1.0
        if alienation >= self.cfg["alienation_threshold"]:
            writeback["mood"] -= 0.8
            writeback["self_worth"] -= 0.4
            writeback["grievance"] += 0.6

        relation: list[dict[str, Any]] = []
        targets: dict[str, dict[str, float]] = {}
        for art in arts:
            target = str(art.get("owner_hint") or "zhang")
            if target in ("", "her"):
                continue
            owed = (1.0 - float(art.get("ownership") or 0)) * float(art.get("minutes") or 0) / 60.0 * 1.2
            row = targets.setdefault(target, {"credit": 0.0, "conflict": 0.0, "shared": 0.0})
            row["credit"] += owed
            if art.get("feedback") == "denied":
                row["conflict"] += 1.2
        for target, row in targets.items():
            relation.append(
                {
                    "target": target,
                    "deltas": {
                        "credit": round(min(6.0, row["credit"]), 2),
                        "conflict": round(min(4.0, row["conflict"]), 2),
                    },
                    "event": f"{day} 的产出",
                }
            )
        if minutes["work"] >= 30:
            colleague = next(
                (a.get("colleague") for a in arts if a.get("kind") == "work"), "ajie"
            )
            relation.append(
                {
                    "target": str(colleague or "ajie"),
                    "deltas": {
                        "shared": round(min(6.0, 1.0 + minutes["work"] / 120.0), 2),
                        "debt": round(min(4.0, 0.6 + minutes["work"] / 300.0), 2),
                    },
                    "event": f"一起上了 {minutes['work']:.0f} 分钟班",
                }
            )
        his = float(
            self.state.get("last_his_time_minutes")
            if day == str(self.state.get("last_day_key"))
            else 0.0
        )
        if his >= 5.0:
            relation.append(
                {
                    "target": "user",
                    "deltas": {
                        "credit": round(min(3.0, his / 60.0 * 0.9), 2),
                        "shared": 0.4,
                    },
                    "event": "她忙的时候也把时间分给了他",
                }
            )
        if alienation >= self.cfg["alienation_threshold"]:
            relation.append(
                {
                    "target": "user",
                    "deltas": {"credit": 0.8, "intimacy": 0.3},
                    "event": "累到想在私人关系里要一点补偿",
                }
            )

        autonomy = float(self.state["autonomy"])
        drives: dict[str, float] = {}
        if autonomy >= 0.55 and feedback == "recognized":
            drives = {"autonomy": 2.0, "self_esteem": 2.0, "mattering": 1.0}
        elif autonomy <= 0.40 and feedback == "denied":
            drives = {"autonomy": -2.0, "rest": 3.0, "curiosity": -2.0, "self_esteem": -2.0}
        else:
            drives = {"autonomy": 1.0 if autonomy >= 0.5 else -0.6}
        if alienation >= self.cfg["alienation_threshold"]:
            drives["belonging"] = drives.get("belonging", 0.0) + 3.0
            drives["mattering"] = drives.get("mattering", 0.0) + 2.0
            drives["curiosity"] = drives.get("curiosity", 0.0) - 1.0
        if float(self.state["fatigue"]) >= 65:
            drives["rest"] = drives.get("rest", 0.0) + 2.0

        strongest = max(arts, key=lambda a: float(a.get("minutes") or 0))
        narrative = {
            "day": day,
            "artifact": strongest.get("name"),
            "feedback": feedback,
            "minutes": round(minutes["work"] + minutes["study"], 1),
            "alienation": round(alienation, 3),
            "ownership": round(ownership, 3),
            "compensation": alienation >= self.cfg["alienation_threshold"],
        }
        writeback.update(
            {
                "relation": relation,
                "drives": drives,
                "narrative": [narrative],
                "feedback": feedback,
                "dominant": "work" if minutes["work"] >= minutes["study"] else "study",
            }
        )
        return writeback

    def _writeback_proposal(self, wb: dict[str, Any]) -> dict[str, Any]:
        """把结算结果整理成一条待确认的反观提案（M14）。"""
        feedback = str(wb.get("feedback") or "unseen")
        alienation = float(wb.get("alienation") or self.state.get("alienation") or 0)
        ownership = float(self.state.get("ownership") or 0)
        delta: dict[str, float] = {}
        if feedback == "recognized":
            delta["care_level"] = 0.01
        elif feedback == "denied":
            delta["cuteness"] = -0.01
            delta["tease_level"] = 0.01
        if ownership >= 0.65:
            delta["talkativeness"] = delta.get("talkativeness", 0) + 0.008
            delta["proactive_bias"] = delta.get("proactive_bias", 0) + 0.008
        if alienation >= self.cfg["alienation_threshold"]:
            delta["talkativeness"] = delta.get("talkativeness", 0) - 0.015
            delta["cuteness"] = delta.get("cuteness", 0) - 0.008
            delta["tease_level"] = delta.get("tease_level", 0) + 0.01
        if float(self.state.get("autonomy", 0.5)) >= 0.6:
            delta["proactive_bias"] = delta.get("proactive_bias", 0) + 0.008
        return {
            "kind": "m14_writeback",
            "self_worth": round(float(wb.get("self_worth", 0) or 0), 3),
            "mood": round(float(wb.get("mood", 0) or 0), 3),
            "grievance": round(float(wb.get("grievance", 0) or 0), 3),
            "persona": delta,
            "relation": list(wb.get("relation") or []),
            "drives": dict(wb.get("drives") or {}),
            "feedback": feedback,
            "alienation": round(alienation, 3),
            "artifacts": list(wb.get("artifact_ids") or []),
            "days": list(wb.get("days") or []),
        }

    def _apply_proposal(
        self,
        proposal: dict[str, Any],
        mood=None,
        meaning=None,
        persona=None,
        social=None,
        drives=None,
        reason: str = "实践结算",
    ) -> dict[str, Any]:
        if meaning is not None:
            current = float(meaning.state.get("self_worth", 62))
            meaning.state["self_worth"] = max(
                20.0, min(95.0, current + float(proposal.get("self_worth", 0)))
            )
            meaning.save()
        if mood is not None:
            mood.state.mood = max(
                0.0, min(100.0, float(mood.state.mood) + float(proposal.get("mood", 0)))
            )
            mood.state.grievance = max(
                0.0,
                min(100.0, float(mood.state.grievance) + float(proposal.get("grievance", 0))),
            )
            mood.save()

        changed: dict[str, Any] = {"persona": {}, "relation": [], "drives": {}}
        if persona is not None:
            delta = dict(proposal.get("persona") or {})
            if delta:
                changed["persona"] = persona.evolve(delta, reason=reason)

        if social is not None:
            for op in proposal.get("relation") or []:
                target = str(op.get("target") or "")
                if not target:
                    continue
                social.adjust_edge(
                    "her",
                    target,
                    dict(op.get("deltas") or {}),
                    interactions=1,
                    last_event=str(op.get("event") or "实践"),
                )
                changed["relation"].append(target)

        if drives is not None:
            deltas = dict(proposal.get("drives") or {})
            if deltas:
                drives.apply_practice(deltas)
                changed["drives"] = deltas
        return changed

    def apply_writeback(
        self,
        mood=None,
        meaning=None,
        persona=None,
        social=None,
        drives=None,
    ) -> dict[str, Any]:
        """M14：默认只生成张力，人工确认后才改写自我节点。"""
        wb = self.state.get("last_writeback") or {}
        if not wb:
            return {}
        proposal = self._writeback_proposal(wb)
        if not bool(self.qt_cfg.get("m14_auto_apply", False)):
            try:
                tid = self.store.add_qt_tension(
                    a_ref="M14 反观确证",
                    b_ref="M6 组织中心",
                    topic="自我节点变更待确认",
                    accumulation=1,
                    threshold=1,
                    note="只生成张力，人工确认后才写入",
                    status="pending",
                    meta=proposal,
                )
                self.store.add_qt_transition(
                    "M12 产物结算",
                    "M14 待确认",
                    retained=",".join(str(x) for x in proposal.get("artifacts") or []),
                    reason="反观确证需要人工确认",
                    meta={"tension_id": tid},
                )
                self.state["last_writeback"] = {}
                self.save()
                return {"pending": True, "tension_id": tid, "proposal": proposal}
            except Exception:  # noqa: BLE001
                # 登记失败时宁可不动自我节点，也不静默自动写入
                return {"pending": False, "error": "tension_write_failed"}
        changed = self._apply_proposal(
            proposal, mood, meaning, persona, social, drives, "实践结算"
        )
        self.state["last_writeback"] = {}
        self.save()
        return changed

    def confirm_writeback(
        self,
        tension_id: int,
        mood=None,
        meaning=None,
        persona=None,
        social=None,
        drives=None,
        reason: str = "人工确认",
    ) -> dict[str, Any]:
        """确认一条 M14 反观提案，确认后才改写自我节点。"""
        tension = self.store.qt_tension(int(tension_id))
        if not tension or str(tension.get("status") or "") != "pending":
            return {}
        try:
            proposal = json.loads(tension.get("meta") or "{}")
        except (TypeError, ValueError):
            proposal = {}
        changed = self._apply_proposal(
            proposal, mood, meaning, persona, social, drives, "实践结算（人工确认）"
        )
        note = f"写入：{reason}"[:200]
        self.store.set_qt_tension_status(int(tension_id), "confirmed", note)
        self.store.add_qt_transition(
            "M14 待确认",
            "M14 已确认",
            retained=json.dumps(proposal.get("persona") or {}, ensure_ascii=False),
            reason=note,
            meta={"tension_id": int(tension_id)},
        )
        return {"ok": True, "tension_id": int(tension_id), "changed": changed}

    def reject_writeback(self, tension_id: int, reason: str = "") -> dict[str, Any]:
        """她自己没同意：保留原样，不写自我节点，只记账。"""
        tension = self.store.qt_tension(int(tension_id))
        if not tension or str(tension.get("status") or "") != "pending":
            return {}
        note = f"没同意：{reason}"[:200] if reason else "没同意"
        self.store.set_qt_tension_status(int(tension_id), "rejected", note)
        self.store.add_qt_transition(
            "M14 待确认",
            "M14 未采纳",
            retained="",
            reason=note,
            meta={"tension_id": int(tension_id)},
        )
        return {"ok": True, "tension_id": int(tension_id), "decision": "reject"}

    def drain_fatigue_delta(self) -> float:
        """把劳动疲劳的增量交给 M2；只交一次。"""
        applied = float(self.state.get("fatigue_applied", self.state["fatigue"]))
        current = float(self.state["fatigue"])
        self.state["fatigue_applied"] = current
        return round(current - applied, 3)

    def backfill_qt_ledgers(self) -> int:
        """把历史产物补进 M13/M15/M16 账本；已补过的按 artifact id 记住。"""
        done_art = set(str(x) for x in (self.state.get("qt_artifact_ids") or []))
        done_out = set(str(x) for x in (self.state.get("qt_outcome_ids") or []))
        done_met = set(str(x) for x in (self.state.get("qt_metric_ids") or []))
        added = 0
        changed = False
        for art in self.state.get("output_log") or []:
            aid = str(art.get("id") or "")
            if not aid:
                continue
            feedback = str(art.get("feedback") or "unseen")
            try:
                if aid not in done_art:
                    content_hash = hashlib.sha1(
                        f"{aid}:{art.get('name')}:{art.get('created_at')}".encode("utf-8")
                    ).hexdigest()[:16]
                    self.store.add_qt_artifact(
                        artifact_id=aid,
                        kind=str(art.get("kind") or ""),
                        name=str(art.get("name") or ""),
                        content_hash=content_hash,
                        owner=str(art.get("owner_hint") or ""),
                        meta={
                            "day": art.get("day"),
                            "minutes": art.get("minutes"),
                            "visibility": art.get("visibility"),
                            "appraisal": art.get("appraisal"),
                            "feedback": feedback,
                        },
                    )
                    done_art.add(aid)
                    added += 1
                    changed = True
                if aid not in done_out:
                    verdict = {"recognized": "confirmed", "denied": "refuted"}.get(
                        feedback, "unverified"
                    )
                    self.store.add_qt_outcome(
                        claim_ref=aid,
                        verdict=verdict,
                        evidence=f"实践产物：{str(art.get('name') or '')[:120]}",
                        confidence=0.6 if verdict != "unverified" else 0.2,
                        source="practice.backfill",
                    )
                    done_out.add(aid)
                    changed = True
                if aid not in done_met:
                    self.store.add_qt_metric(
                        prediction=f"practice:{aid}",
                        hit=feedback == "recognized",
                        match_score=0.8 if feedback == "recognized" else 0.2,
                        note=f"M16：劳动产物是否被承认（{feedback}）",
                    )
                    done_met.add(aid)
                    changed = True
            except Exception:  # noqa: BLE001
                continue
        if changed:
            self.state["qt_artifact_ids"] = list(done_art)[-5000:]
            self.state["qt_outcome_ids"] = list(done_out)[-5000:]
            self.state["qt_metric_ids"] = list(done_met)[-5000:]
            self.save()
        return added

    def save(self) -> None:
        self.store.set_state("brainn_practice", self.state)

    def snapshot(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        return dict(self.state)
