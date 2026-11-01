"""终端模拟聊天：不接 QQ 也能验证人格、节奏、情绪、任务和主动消息。"""
from __future__ import annotations

import asyncio
import time

from .brain import Brain
from .media import Media
from .timing import ReplyPlan

BANNER = """
┌──────────────────────────────────────────────┐
│   小鲸鱼 · 本地模拟聊天（不连接 QQ）          │
│   /状态   /主动   /天气   /复盘   /退出      │
└──────────────────────────────────────────────┘
"""


class SimAdapter:
    def __init__(self, brain: Brain, fast: bool = True):
        self.brain = brain
        self.fast = fast
        self.scale = 6.0 if fast else 1.0

    async def run(self) -> None:
        print(BANNER)
        print(f"大脑：{self.brain.llm.mode}")
        print(f"人格：{self.brain.persona.summary()}")
        print(f"{self.brain.mood.describe()}\n")
        while True:
            try:
                text = await asyncio.to_thread(input, "你 > ")
            except (EOFError, KeyboardInterrupt):
                print("\n再见。")
                return
            text = text.strip()
            if not text:
                continue
            if text in ("/退出", "/quit", "/exit"):
                print("小鲸鱼：行吧，那你忙。")
                return
            if text in ("/状态", "/status"):
                print(self.brain.status_text())
                continue
            if text == "/天气":
                w = await self.brain.weather.get(force=True)
                print(w.line() if w else "天气没连上")
                continue
            if text == "/主动":
                topic = self.brain_pick_topic()
                print(f"[主动消息 · 话题：{topic}]")
                plan = await self.brain.proactive(topic)
                await self.emit(None, plan)
                continue
            if text == "/复盘":
                result = await self.brain.learner.run_nightly()
                print(result)
                continue

            url = Media.extract_url(text)
            kind = "link" if url else "text"
            began = time.time()
            plan = await self.brain.handle(text, kind=kind, url=url, user_id=1)
            if plan is None or not plan.segments:
                print("（她这会儿睡着了，消息要等她醒来才回。）")
                continue
            print(f"（思考 {time.time() - began:.1f}s）")
            await self.emit(1, plan)

    def brain_pick_topic(self) -> str:
        topics = self.brain.persona_cfg.get("proactive", {}).get("topics", ["尬聊（问在干嘛）"])
        return topics[__import__("random").randrange(len(topics))]

    async def emit(self, user_id, plan: ReplyPlan) -> None:
        for seg in plan.segments:
            delay = seg.delay / self.scale
            if delay > 0.02:
                await asyncio.sleep(min(delay, 6.0))
            if seg.kind == "text":
                print(f"小鲸鱼 > {seg.payload}")
            elif seg.kind == "sticker":
                print(f"小鲸鱼 > [表情包：{seg.payload}]")
            elif seg.kind == "face":
                print(f"小鲸鱼 > [QQ表情 #{seg.payload}]")
            elif seg.kind == "link":
                v = seg.payload or {}
                print(f"小鲸鱼 > [分享视频] {v.get('title', '')}  {v.get('url', '')}")
