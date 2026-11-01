"""任务处理：识别 → 加权同意/拒绝 → 能做的真做，做不了的用她的话说清楚。"""
from __future__ import annotations

import datetime as dt
import random
import re
from dataclasses import dataclass
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .db import Store

TASK_MARKERS = ("帮我", "能不能帮", "可以帮", "替我", "给我做", "给我写", "帮我查", "帮我找", "提醒我", "帮我记", "教我", "你来写", "你帮我")

WEATHER_WORDS = ("天气", "下雨", "温度", "冷不冷", "热不热", "带伞")
REMINDER_WORDS = ("提醒我", "提醒", "叫我", "别忘了")
NOTE_WORDS = ("记一下", "记住", "帮我记", "备忘")
SEARCH_WORDS = ("查一下", "搜一下", "帮我查", "找一下", "搜搜")


@dataclass
class TaskIntent:
    is_task: bool
    kind: str
    effort: int
    text: str


class Tasks:
    def __init__(self, store: Store, cfg: dict[str, Any], clock: Any = None):
        self.store = store
        self.cfg = cfg
        self.clock = clock

    def _now(self) -> dt.datetime:
        return self.clock.now() if self.clock else dt.datetime.now()

    def _fmt(self, ts: float) -> str:
        if self.clock and getattr(self.clock, "zone", None):
            return dt.datetime.fromtimestamp(ts, self.clock.zone).strftime("%m月%d日 %H:%M")
        return dt.datetime.fromtimestamp(ts).strftime("%m月%d日 %H:%M")

    # ---------- 识别 ----------
    def detect(self, text: str) -> TaskIntent:
        if not any(m in text for m in TASK_MARKERS):
            return TaskIntent(False, "none", 0, text)
        effort = 2
        if len(text) > 60:
            effort += 1
        if any(w in text for w in ("写", "方案", "代码", "总结", "翻译", "报告", "计划")):
            effort += 1
        if any(w in text for w in ("马上", "现在", "着急", "今晚就要")):
            effort += 1
        effort = min(5, effort)

        if any(w in text for w in WEATHER_WORDS):
            return TaskIntent(True, "weather", 1, text)
        if any(w in text for w in REMINDER_WORDS):
            return TaskIntent(True, "reminder", 1, text)
        if any(w in text for w in NOTE_WORDS):
            return TaskIntent(True, "note", 1, text)
        if any(w in text for w in SEARCH_WORDS):
            return TaskIntent(True, "search", 2, text)
        if any(w in text for w in ("写", "总结", "翻译", "计划", "方案", "取个名", "想个")):
            return TaskIntent(True, "write", effort, text)
        return TaskIntent(True, "general", effort, text)

    # ---------- 执行 ----------
    async def execute(self, intent: TaskIntent, weather: Any) -> dict[str, Any]:
        if intent.kind == "weather":
            if not weather:
                return {"tool_result": "天气接口暂时没连上，别装作知道。"}
            advice = "带伞" if any(w in weather.text for w in ("雨", "雪", "雷")) else "不用带伞"
            return {"tool_result": f"实时天气：{weather.line()}。提醒他{advice}，按温度提醒穿什么。"}

        if intent.kind == "reminder":
            due = self._parse_time(intent.text)
            content = self._clean_reminder(intent.text)
            if due:
                self.store.add_reminder(due, content)
                when = self._fmt(due)
                return {"tool_result": f"提醒已设好：{when} 提醒他「{content}」。确认时用你自己的说话方式，别念时间戳格式。"}
            return {"tool_result": "没解析出具体时间，回复时要顺口问一句几点提醒他。"}

        if intent.kind == "note":
            content = intent.text
            self.store.upsert_memory("note", content[:40], content[:200], 0.9, "task")
            return {"tool_result": "已经记进长期记忆，回复可以简短确认，别郑重其事。"}

        if intent.kind == "search":
            query = self._clean_query(intent.text)
            result = await self.web_search(query)
            if result:
                return {"tool_result": f"联网搜到的信息：\n{result}\n用自己的话转述，不要照搬。"}
            return {"tool_result": "联网搜索没成功，别编造结果，直接说没查到，并让他把知道的先说说。"}

        if intent.kind == "write":
            return {"tool_result": "这是纯写作/思考任务，直接在回复里给出成品，别只说\"我可以帮你\"。"}

        return {"tool_result": "普通请求，按你的能力直接回应；做不了的部分说清楚，不要假装完成。"}

    # ---------- 工具 ----------
    @staticmethod
    async def web_search(query: str) -> str:
        if not query:
            return ""
        try:
            async with httpx.AsyncClient(
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"},
            ) as client:
                resp = await client.get("https://www.bing.com/search", params={"q": query, "setlang": "zh-CN"})
            soup = BeautifulSoup(resp.text[:300000], "html.parser")
            lines = []
            for li in soup.select("li.b_algo")[:4]:
                h2 = li.find("h2")
                p = li.find("p")
                if h2:
                    lines.append(f"- {h2.get_text(' ', strip=True)}：{p.get_text(' ', strip=True) if p else ''}")
            return "\n".join(lines)[:900]
        except Exception:
            return ""

    @staticmethod
    def _clean_reminder(text: str) -> str:
        cleaned = re.sub(r"^(帮我|提醒我|叫我|别忘了|记住|一下)+", "", text).strip("，。 ")
        cleaned = re.sub(
            r"^(今天|明天|后天|今晚|明早)?\s*(早上|上午|中午|下午|晚上|半夜)?\s*\d{1,2}[点:：]\d{0,2}(分)?(左右|之前|以后)?",
            "",
            cleaned,
        ).strip("，。 ")
        return (cleaned or text)[:80]

    @staticmethod
    def _clean_query(text: str) -> str:
        q = re.sub(r"(帮我|能不能帮|可以帮|替我|给我|查一下|搜一下|找一下|搜搜|一下|吗|？|\?)", "", text)
        return q.strip()[:60]

    def _parse_time(self, text: str) -> float | None:
        now = self._now()
        # 相对时间
        m = re.search(r"(\d+)\s*分钟后", text)
        if m:
            return (now + dt.timedelta(minutes=int(m.group(1)))).timestamp()
        m = re.search(r"(\d+)\s*小时后", text)
        if m:
            return (now + dt.timedelta(hours=int(m.group(1)))).timestamp()
        if "半小时后" in text:
            return (now + dt.timedelta(minutes=30)).timestamp()
        if "一小时后" in text:
            return (now + dt.timedelta(hours=1)).timestamp()
        if "明天" in text and not re.search(r"\d", text):
            return (now + dt.timedelta(days=1)).replace(hour=9, minute=0, second=0).timestamp()
        # 绝对时间
        m = re.search(r"(\d{1,2})[点:：](\d{1,2})?", text)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2) or 0)
            target = now.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
            if "下午" in text and hour < 12:
                target += dt.timedelta(hours=12)
            if "晚上" in text and hour < 12:
                target += dt.timedelta(hours=12)
            if "明天" in text:
                target += dt.timedelta(days=1)
            if target <= now:
                target += dt.timedelta(days=1)
            return target.timestamp()
        return None
