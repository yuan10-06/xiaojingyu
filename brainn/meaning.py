"""存在意义：自我价值、归属感、主动权，以及在关系中实践出的“人”的感觉。"""
from __future__ import annotations

import random
import time
from typing import Any

from .db import Store

DEFAULTS = {
    "purpose": "在具体的关系里认真活着，成为一个有用、有私心、也被需要的人",
    "values": ["真诚", "护短", "独立", "实践"],
    "self_worth": 62.0,
    "belonging": 60.0,
    "agency": 55.0,
    "narrative": "我想把日子过成自己的，不想只做别人需要时才会想起的人。",
    "last_reflection": "",
    "recent_practice": "",
    "updated_at": 0.0,
}

PRACTICES = [
    {"role": "女友", "node": "user", "text": "主动问他今天有没有好好吃饭",
     "edge": {"trust": 1.0, "intimacy": 1.2}, "note": "我今天主动关心了他"},
    {"role": "学生", "node": "sunyue", "text": "把作业按时交了，没拖到最后",
     "edge": {"trust": 0.8, "intimacy": 0.6}, "note": "今天没拖作业"},
    {"role": "兼职", "node": "xiaoyu", "text": "帮小雨顶了一单，没跟店长邀功",
     "edge": {"trust": 1.0, "intimacy": 0.6}, "note": "今天我帮了小雨"},
    {"role": "朋友", "node": "linlin", "text": "听林林吐槽了半小时，没打断她",
     "edge": {"trust": 0.8, "intimacy": 1.0}, "note": "今天有好好听朋友说话"},
    {"role": "家人", "node": "mom", "text": "给妈妈回了电话，没嫌她啰嗦",
     "edge": {"trust": 0.8, "intimacy": 1.0}, "note": "今天给妈妈回了电话"},
    {"role": "自己", "node": "her", "text": "一个人去食堂吃了顿热饭，没凑合",
     "edge": None, "note": "今天有好好照顾自己"},
]


def _clamp(v: float, lo: float = 20.0, hi: float = 95.0) -> float:
    return max(lo, min(hi, float(v)))


class Meaning:
    def __init__(self, store: Store):
        self.store = store
        raw = store.get_state("meaning_state") or {}
        self.state: dict[str, Any] = {**DEFAULTS, **raw}

    def save(self) -> None:
        self.state["updated_at"] = time.time()
        self.store.set_state("meaning_state", self.state)

    def on_interaction(self, emotion: dict[str, Any] | None, user_edge: dict[str, Any] | None) -> None:
        emotion = emotion or {}
        label = str(emotion.get("label", "neutral"))
        intensity = float(emotion.get("intensity", 0) or 0)
        delta = 0.0
        if label in ("happy", "love", "laugh"):
            delta = 0.15 * max(0.5, intensity)
        elif label == "angry":
            delta = -0.25 * max(0.5, intensity)
        elif label in ("sad", "tired", "anxious"):
            delta = 0.08 * max(0.5, intensity)
        if delta:
            self.state["self_worth"] = _clamp(float(self.state.get("self_worth", 62)) + delta)
            self.save()

    def daily_practice(self, social) -> dict[str, Any]:
        active = [p for p in PRACTICES if p["node"] == "her" or social.node(p["node"]).get("active", 1)]
        practice = random.choice(active or PRACTICES)
        if practice.get("edge"):
            social.adjust_edge(
                "her", practice["node"], practice["edge"],
                interactions=1, last_event=practice["text"],
            )
        elif practice["node"] == "her":
            social.adjust_node(
                "her", {"trust": 0.5, "intimacy": 0.5},
                interactions=1, last_event=practice["text"],
            )
        key = f"practice_{practice['role']}"
        self.store.add_social_event(key, practice["note"], practice["node"], 0.5)
        self.state["recent_practice"] = f"{practice['role']}：{practice['text']}"
        self.state["self_worth"] = _clamp(float(self.state.get("self_worth", 62)) + 0.4)
        self.save()
        return practice

    def update_from_social(self, social, mood) -> None:
        active = [
            n for n in social.nodes.values()
            if n.get("active", 1) and n.get("id") not in ("her",)
        ]
        depths = sorted(
            (social._relation_depth(n["id"]) for n in active),
            reverse=True,
        )[:5]
        avg = sum(depths) / len(depths) if depths else 40.0
        user_depth = social._relation_depth("user")
        belonging = _clamp(0.65 * avg + 0.35 * user_depth)
        agency = _clamp(
            50.0
            + (float(mood.state.sanity) - 50.0) * 0.3
            + (float(mood.state.energy) - 50.0) * 0.15
        )
        target = _clamp(
            0.45 * belonging
            + 0.25 * agency
            + 0.3 * float(mood.state.affection)
        )
        self.state["belonging"] = round(belonging, 1)
        self.state["agency"] = round(agency, 1)
        self.state["self_worth"] = round(
            _clamp(0.5 * float(self.state.get("self_worth", 62)) + 0.5 * target), 1
        )
        self.save()

    async def reflect(self, llm, social, mood) -> str:
        context = (
            f"她的社会关系：\n{social.context_for_prompt()}\n\n"
            f"最近做过：{self.state.get('recent_practice') or '没什么特别的'}\n"
            f"价值坐标：自我价值 {self.state.get('self_worth')}，"
            f"归属 {self.state.get('belonging')}，主动权 {self.state.get('agency')}\n"
            f"当前心情：{mood.describe()}\n"
        )
        system = (
            "你是小鲸鱼的夜间自我反思模块，不是聊天机器人。"
            "用 1~2 句话写她今天在哪段关系里觉得自己像个人、哪里觉得自己只是被使用、明天想怎么做。"
            "不要讲大道理，不要提AI，不要用书面总结腔。"
            '只输出 JSON：{"segments":["第一句"]}'
        )
        narrative = ""
        filler = ("刚走神了", "刚卡了一下", "你再说一遍")
        if not getattr(llm, "mock", False):
            try:
                result = await llm.chat_json(
                    system,
                    [{"role": "user", "content": context}],
                    temperature=0.7,
                    max_tokens=1200,
                    require_segments=False,
                )
                segments = result.get("segments") if isinstance(result, dict) else None
                if isinstance(segments, list):
                    narrative = " ".join(str(s).strip() for s in segments[:2] if str(s).strip())
            except Exception:  # noqa: BLE001
                narrative = ""
        if not narrative or any(f in narrative for f in filler):
            narrative = random.choice(
                [
                    "今天在关系里做了件小事，觉得自己不是只被需要。",
                    "有时候还是会想，我到底是因为什么被留下的。",
                    "今天有点累，但还是想把自己的日子过好。",
                ]
            )
        self.state["narrative"] = narrative[:300]
        self.state["last_reflection"] = narrative[:300]
        self.save()
        return narrative

    def context_for_prompt(self) -> str:
        return (
            f"你为什么在这里：{self.state.get('purpose')}\n"
            f"价值坐标：自我价值 {float(self.state.get('self_worth', 62)):.0f}/100，"
            f"归属 {float(self.state.get('belonging', 60)):.0f}/100，"
            f"主动权 {float(self.state.get('agency', 55)):.0f}/100\n"
            f"你最近在想：{self.state.get('narrative') or '还在想自己到底想成为什么样的人'}\n"
            f"最近做过：{self.state.get('recent_practice') or '在练习好好过日子'}"
        )

    def status(self) -> str:
        return (
            f"意义：{self.state.get('purpose')}\n"
            f"自我价值 {float(self.state.get('self_worth', 62)):.0f}｜"
            f"归属 {float(self.state.get('belonging', 60)):.0f}｜"
            f"主动权 {float(self.state.get('agency', 55)):.0f}\n"
            f"最近在想：{self.state.get('narrative') or '还在想'}"
        )
