"""后台节拍：情绪衰减、天气刷新、主动消息、提醒、夜间复盘。"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import random
import time
from typing import Any, Awaitable, Callable

from .body import Body
from .brain import Brain
from .clock import Clock
from .db import Store
from .learner import Learner
from .mood import Mood
from .proactive import Proactive
from .timing import OutSegment, ReplyPlan
from .weather import WeatherService

log = logging.getLogger("brainn.scheduler")


class Scheduler:
    def __init__(
        self,
        brain: Brain,
        proactive: Proactive,
        weather: WeatherService,
        clock: Clock,
        store: Store,
        mood: Mood,
        body: Body,
        shadow,
        memory,
        learner: Learner,
        social,
        meaning,
        send: Callable[[int | None, Any], Awaitable[None]],
        owner_qq: int,
        post_dynamic: Callable[[str, list[str]], Awaitable[dict[str, Any]]] | None = None,
        set_avatar: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
        web=None,
    ):
        self.brain = brain
        self.proactive = proactive
        self.weather = weather
        self.clock = clock
        self.store = store
        self.mood = mood
        self.body = body
        self.shadow = shadow
        self.memory = memory
        self.learner = learner
        self.social = social
        self.meaning = meaning
        self.send = send
        self.owner_qq = owner_qq
        self.post_dynamic = post_dynamic
        self.set_avatar = set_avatar
        self.web = web
        self.life = getattr(brain, "life", None)
        self._last_learning_date = ""

    async def run(self) -> None:
        self.store.set_state("scheduler_beat", time.time())
        self.store.set_state("scheduler_boot_at", time.time())
        await asyncio.gather(
            self._mood_loop(),
            self._body_loop(),
            self._practice_loop(),
            self._life_loop(),
            self._weather_loop(),
            self._proactive_loop(),
            self._reminder_loop(),
            self._pending_loop(),
            self._dynamic_loop(),
            self._social_loop(),
            self._social_extract_loop(),
            self._sticker_loop(),
            self._avatar_loop(),
            self._web_loop(),
            self._memory_review_loop(),
            self._selfhood_loop(),
            self._learning_loop(),
            self._probe_loop(),
        )

    # ---------- 情绪 ----------
    async def _mood_loop(self) -> None:
        while True:
            try:
                self.mood.tick(asleep=self.clock.is_asleep())
                if random.random() < 0.2:
                    self.store.log_mood(self.mood.state.snapshot(), "定期衰减")
            except Exception as exc:  # noqa: BLE001
                log.warning("情绪节拍出错：%s", exc)
            await asyncio.sleep(600)

    # ---------- 生理 ----------
    async def _body_loop(self) -> None:
        while True:
            try:
                info = self.body.tick(asleep=self.clock.is_asleep())
                # 实践先行：M11 产出日程与疲劳，M8 再计算时间预算
                if (
                    self.shadow is not None
                    and self.brain.core is not None
                    and self.brain.core.enabled
                ):
                    ctx = {"asleep": self.clock.is_asleep()}
                    if getattr(self.shadow, "practice_enabled", True):
                        self.shadow.practice.tick(time.time(), ctx)
                        delta = self.shadow.practice.drain_fatigue_delta()
                        if abs(delta) >= 0.01:
                            self.body.state["fatigue"] = max(
                                0.0,
                                min(
                                    100.0,
                                    float(self.body.state.get("fatigue", 0)) + delta,
                                ),
                            )
                    self.shadow.time_model.tick(time.time(), ctx)
                    self.shadow.world.tick(time.time(), ctx)
                    if getattr(self.shadow, "recognition", None) is not None:
                        self.shadow.recognition.tick(time.time(), ctx)
                    if getattr(self.shadow, "affect", None) is not None:
                        self.shadow.affect.tick(time.time(), ctx)
                    world_drive = self.shadow.world.consume_drive_deltas()
                    # 无对话也要走的后台 tick：驱力、叙事、人格冲突、无意识
                    self.shadow.drives.tick(time.time(), ctx)
                    if world_drive:
                        self.shadow.drives.apply_practice(world_drive)
                    self.shadow.narrative.tick(time.time(), ctx)
                    self.shadow.conflict.tick(time.time(), ctx)
                    self.shadow.unconscious.tick(time.time(), ctx)
                self.body.apply_to_mood(self.mood)
                self.store.set_state("scheduler_beat", time.time())
                if info.get("period_started"):
                    log.info("生理：月经来了")
                if info.get("pain_started"):
                    log.info("生理：开始%s（%.0f）", info["pain_started"], self.body.state.get("pain", 0))
            except Exception as exc:  # noqa: BLE001
                log.warning("生理状态推进失败：%s", exc)
            await asyncio.sleep(60)

    # ---------- 生活事件（外卖/快递/约会） ----------
    async def _life_loop(self) -> None:
        """每分钟推进生活事件；到点确认送达，并在她醒着时补一句。"""
        while True:
            try:
                if self.life is not None:
                    resolved = self.life.tick(time.time())
                    for event in resolved[:2]:
                        if not event.get("notify") or self.clock.is_asleep():
                            continue
                        text = self.life.resolution_text(event)
                        mid = self.store.add_message("assistant", text, "text")
                        plan = ReplyPlan(
                            [OutSegment("text", text, random.uniform(2.0, 6.0))]
                        )
                        plan.message_id = int(mid or 0)
                        await self.send(None, plan)
                        log.info("生活事件送达：%s", text[:40])
            except Exception as exc:  # noqa: BLE001
                log.warning("生活事件推进失败：%s", exc)
            await asyncio.sleep(60)

    # ---------- 实践结算 ----------
    async def _decide_m14_backlog(self) -> None:
        """处理还没有她判断结果的 M14 提案（包括升级前遗留的 pending）。"""
        if self.brain is None:
            return
        try:
            pending = self.store.qt_pending_m14(3)
        except Exception as exc:  # noqa: BLE001
            log.warning("读取 M14 待判断提案失败：%s", exc)
            return
        for item in pending:
            try:
                await self.brain.decide_m14(int(item["id"]))
            except Exception as exc:  # noqa: BLE001
                log.warning("M14 自主判断失败：%s", exc)

    async def _practice_loop(self) -> None:
        """每日结算一次：M11 → M3 人格 / M4 人情债 / M9 驱力；M5 滞后反思。"""
        while True:
            try:
                await self._decide_m14_backlog()
                cfg = self.brain.settings.get("brainn", {}) or {}
                if (
                    cfg.get("enabled")
                    and self.shadow is not None
                    and not self.clock.is_asleep()
                    and getattr(self.shadow, "practice_enabled", True)
                ):
                    now = self.clock.now()
                    today = now.strftime("%Y-%m-%d")
                    last = self.store.get_state("last_practice_date") or ""
                    if today != last:
                        writeback = self.shadow.practice.settle()
                        if writeback:
                            changed = {}
                            if not bool(cfg.get("shadow", True)):
                                changed = self.shadow.practice.apply_writeback(
                                    self.mood,
                                    self.meaning,
                                    self.brain.persona,
                                    social=self.social,
                                    drives=self.shadow.drives,
                                )
                                if isinstance(changed, dict) and changed.get("pending"):
                                    tid = int(changed.get("tension_id") or 0)
                                    if tid:
                                        await self.brain.decide_m14(tid)
                            self.shadow.narrative.schedule_practice(writeback)
                            try:
                                self.shadow.evolution.evaluate()
                            except Exception as exc:  # noqa: BLE001
                                log.warning("M9→M11 演化评估失败", exc_info=True)
                            log.info(
                                "实践结算：%s｜回写 %s",
                                writeback.get("days"),
                                changed,
                            )
                        self.store.set_state("last_practice_date", today)
            except Exception as exc:  # noqa: BLE001
                log.warning("实践结算失败：%s", exc)
            await asyncio.sleep(1800)

    # ---------- 天气 ----------
    async def _weather_loop(self) -> None:
        cfg = self.brain.settings.get("weather", {})
        interval = max(15, int(cfg.get("refresh_minutes", 40))) * 60
        while True:
            try:
                w = await self.weather.get(force=True)
                if w:
                    # 天气只改变"心情偏移量"，天气变化时才调整，避免每 40 分钟重复扣心情
                    target = w.delta * 0.6
                    last = float((self.store.get_state("weather_effect") or {}).get("delta", 0) or 0)
                    shift = target - last
                    if abs(shift) >= 0.5:
                        self.mood.on_weather(shift, w.text)
                        self.store.set_state("weather_effect", {"delta": target, "text": w.text, "ts": time.time()})
                        log.info("天气：%s（心情偏移 %+.1f，本次调整 %+.1f）", w.line(), target, shift)
            except Exception as exc:  # noqa: BLE001
                log.warning("天气刷新失败：%s", exc)
            await asyncio.sleep(interval)

    # ---------- 主动 ----------
    async def _proactive_loop(self) -> None:
        while True:
            try:
                last_msg = float(self.store.last_message_ts() or 0)
                if last_msg and time.time() - last_msg < 900:
                    # 刚聊过或刚发过记忆回访/提醒：主动消息先让开，避免连续打扰
                    await asyncio.sleep(300)
                    continue
                ok, reason = self.proactive.check()
                view = self.proactive.params() | {"reason": reason, "ts": time.time()}
                self.store.set_state("proactive_view", view)
                if ok:
                    slots = self._remaining_slots()
                    p = self.proactive.remaining() / max(1, slots)
                    if random.random() < min(0.9, p):
                        structural = ""
                        if self.shadow is not None and getattr(self.shadow, "recognition", None):
                            structural = self.shadow.recognition.take_question(
                                self.clock.now_ts(),
                                {"activity": self.shadow.practice.state.get("current")},
                            )
                        topic = structural or self.proactive.pick_topic()
                        log.info(
                            "主动消息（%s），今日进度 %s/%s%s",
                            topic,
                            view["sent"] + 1,
                            view["quota"],
                            "｜结构性好奇" if structural else "",
                        )
                        plan = await self.brain.proactive(topic)
                        if plan and plan.segments:
                            await self.send(self.owner_qq, plan)
                        await asyncio.sleep(600)
                        continue
            except Exception as exc:  # noqa: BLE001
                log.warning("主动消息调度出错：%s", exc)
            await asyncio.sleep(300)

    def _remaining_slots(self) -> int:
        now = self.clock.now()
        cur = now.hour * 60 + now.minute
        windows = self.brain.persona_cfg.get("proactive", {}).get("windows", [])
        slots = 0
        for start, end in windows:
            s = Clock._minutes(start)
            e = Clock._minutes(end)
            if e > s:
                begin = max(cur, s)
                slots += max(0, (e - begin) // 10)
            else:
                if cur >= s:
                    slots += (1440 - cur) // 10 + e // 10
                elif cur <= e:
                    slots += (e - cur) // 10
        return max(1, slots)

    # ---------- 夜间待回队列 ----------
    async def _pending_loop(self) -> None:
        while True:
            try:
                if not self.clock.is_asleep():
                    for item in self.store.due_pending():
                        user_id = int(item["user_id"] or self.owner_qq)
                        plan = await self.brain.handle(
                            item["text"],
                            kind=item["kind"],
                            url=item["url"] or None,
                            image_url=item["image_url"] or None,
                            user_id=user_id,
                            store_incoming=False,
                            deferred=True,
                        )
                        if plan and plan.segments:
                            await self.send(user_id, plan)
                        self.store.delete_pending(item["id"])
                        await asyncio.sleep(random.uniform(8, 25))
            except Exception as exc:  # noqa: BLE001
                log.warning("待回队列出错：%s", exc)
            await asyncio.sleep(60)

    # ---------- 自动动态 ----------
    def _in_windows(self, windows: list[list[str]]) -> bool:
        cur = self.clock.minutes_of_day()
        for start, end in windows:
            s = Clock._minutes(start)
            e = Clock._minutes(end)
            if s <= e and s <= cur <= e:
                return True
            if s > e and (cur >= s or cur <= e):
                return True
        return False

    async def _dynamic_due(self) -> bool:
        cfg = self.brain.settings.get("dynamic", {})
        if not cfg.get("enabled", True) or self.clock.is_asleep():
            return False
        if not self._in_windows(cfg.get("windows", [])):
            return False
        now = self.clock.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        lo, hi = cfg.get("daily_quota", [1, 3])
        quota = random.Random(int(now.strftime("%Y%m%d"))).randint(int(lo), int(hi))
        if self.store.dynamic_since(start) >= quota:
            return False
        gap = (time.time() - self.store.last_dynamic_ts()) / 60
        if gap < float(cfg.get("min_gap_minutes", 180)):
            return False
        return random.random() < 0.45

    def _current_activity(self) -> dict[str, Any]:
        if self.shadow is None:
            return {}
        try:
            return self.shadow.practice.snapshot().get("current") or {}
        except Exception:  # noqa: BLE001
            return {}

    async def _dynamic_moment(self) -> tuple[str, str]:
        """按当前日程选一条生活动态：主题 + 配图关键词。"""
        cfg = self.brain.settings.get("dynamic", {}) or {}
        last = set(self.store.last_dynamic_topics(5))
        current = self._current_activity()
        kind = str(current.get("kind") or "")
        place = str(current.get("place") or "")
        pool: list[tuple[str, str]] = []

        by_kind = {
            "work": [
                ("奶茶店的新品", "奶茶 实拍"),
                ("店里来了个奇怪客人", "奶茶店 店内 实拍"),
            ],
            "study": [
                ("图书馆的桌面", "大学图书馆 桌面 实拍"),
                ("复习食品化学", "大学图书馆 学习 实拍"),
            ],
            "class": [
                ("上课走神", "大学教室 实拍"),
                ("老师在讲天书", "大学课堂 实拍"),
            ],
            "deadline": [
                ("赶作业", "图书馆 电脑 学习 实拍"),
            ],
        }
        if kind in by_kind:
            pool = by_kind[kind]
        elif kind == "chore" and "食堂" in place:
            pool = [("食堂的饭", "大学食堂 饭菜 实拍"), ("食堂排队", "大学食堂 排队 实拍")]
        elif kind == "chore" and "宿舍" in place:
            pool = [("宿舍夜宵", "宿舍 夜宵 实拍"), ("刚洗完澡", "宿舍 生活 实拍")]
        elif kind == "chore":
            pool = [("校园里的猫", "校园 流浪猫 实拍"), ("路上看到的", "大学校园 实拍")]

        if not pool:
            part = self.clock.part_of_day()
            time_pool = {
                "早上": [("食堂的早饭", "大学食堂 早饭 实拍"), ("去教学楼的路上", "大学校园 教学楼 实拍")],
                "上午": [("食堂的早饭", "大学食堂 早饭 实拍"), ("去教学楼的路上", "大学校园 教学楼 实拍")],
                "中午": [("食堂的饭", "大学食堂 饭菜 实拍")],
                "下午": [("图书馆的桌面", "大学图书馆 桌面 实拍"), ("校园里的猫", "校园 流浪猫 实拍")],
                "晚上": [("晚霞", "城市 晚霞 天空 实拍"), ("夜宵", "夜宵 小吃 实拍")],
                "深夜": [("宿舍夜宵", "宿舍 夜宵 实拍")],
                "凌晨": [("宿舍夜宵", "宿舍 夜宵 实拍")],
            }
            pool = time_pool.get(part, [])

        if not pool:
            pool = [
                (str(item[0]), str(item[1]))
                for item in (cfg.get("moments") or [])
                if isinstance(item, (list, tuple)) and len(item) >= 2
            ]
        if not pool:
            w = await self.weather.get()
            return (w.text if w else "今天的小事"), ""

        fresh = [item for item in pool if item[0] not in last]
        return random.choice(fresh or pool)

    async def _dynamic_loop(self) -> None:
        try:
            await self._repair_recent_dynamic_images()
        except Exception as exc:  # noqa: BLE001
            log.warning("动态配图修复失败：%s", exc)
        while True:
            try:
                cfg = self.brain.settings.get("dynamic", {}) or {}
                if self.post_dynamic and await self._dynamic_due():
                    topic, keyword = await self._dynamic_moment()
                    current = self._current_activity()
                    log.info(
                        "动态主题：%s（当前 %s/%s）",
                        topic,
                        current.get("kind") or "空闲",
                        current.get("place") or "",
                    )
                    text = await self.brain.dynamic_post(topic)
                    # 配图跟着最终正文走：写麻辣烫就找麻辣烫，而不是笼统的“夜宵”
                    keyword = self.brain.media.image_keyword_for_text(text) or keyword
                    images: list[str] = []
                    count = max(0, min(3, int(cfg.get("image_count", 1))))
                    if count and keyword:
                        paths = await self.brain.media.pick_life_image(keyword, count)
                        images = [str(path) for path in paths]
                        if not images:
                            log.info("动态配图没搜到，改发纯文字：%s", keyword)
                    result = await self.post_dynamic(text, images=images)
                    platform = str((result or {}).get("platform", ""))
                    self.store.add_dynamic(text, topic, platform, images)
                    log.info(
                        "自动动态（%s，图 %d）：%s", platform, len(images), text[:60]
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("自动动态失败：%s", exc)
            await asyncio.sleep(900)

    async def _repair_recent_dynamic_images(self) -> None:
        """一次性修复最近动态的配图：正文写麻辣烫，就不能配炸土豆。"""
        if self.store.get_state("dynamic_image_repair_v2"):
            return
        try:
            rows = self.store.recent_dynamics(20)
            for row in rows[-6:]:
                if str(row.get("author") or "her") != "her":
                    continue
                keyword = self.brain.media.image_keyword_for_text(str(row.get("text") or ""))
                if not keyword:
                    continue
                paths = await self.brain.media.pick_life_image(keyword, 1)
                if paths:
                    self.store.update_dynamic_images(int(row.get("id") or 0), [str(paths[0])])
                    log.info("修复动态配图：%s → %s", row.get("id"), keyword)
                await asyncio.sleep(1)
        finally:
            self.store.set_state("dynamic_image_repair_v2", time.time())

    # ---------- 社会关系事件 ----------
    async def _social_loop(self) -> None:
        while True:
            try:
                cfg = self.brain.settings.get("social", {})
                if (
                    cfg.get("enabled", True)
                    and not self.clock.is_asleep()
                    and self._in_windows([cfg.get("window", ["09:00", "22:30"])])
                ):
                    now = self.clock.now()
                    start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                    lo, hi = cfg.get("daily_events", [1, 3])
                    quota = random.Random(int(now.strftime("%Y%m%d"))).randint(int(lo), int(hi))
                    if self.store.social_events_since(start) < quota and random.random() < 0.28:
                        event = self.social.daily_event()
                        if event:
                            reason = str(event.get("share") or event.get("text") or "")
                            self.mood.on_social_event(float(event.get("mood", 0) or 0), reason)
                            log.info("社会事件（%s）：%s", event.get("node"), reason[:80])
            except Exception as exc:  # noqa: BLE001
                log.warning("社会事件失败：%s", exc)
            await asyncio.sleep(1800)

    # ---------- 对话里的关系抽取 ----------
    async def _social_extract_loop(self) -> None:
        """每 4 小时从聊天里抽取一次关系变化，写进本地关系图。"""
        while True:
            cfg = self.brain.settings.get("social", {}).get("llm_extract", {})
            try:
                if (
                    cfg.get("enabled", True)
                    and not self.clock.is_asleep()
                    and self._in_windows([cfg.get("window", ["10:00", "23:30"])])
                ):
                    result = await self.learner.run_social_extract()
                    if result.get("changes") or result.get("new_people"):
                        self.mood.on_social_event(float(result.get("mood", 0) or 0), "对话里的关系变化")
            except Exception as exc:  # noqa: BLE001
                log.warning("关系抽取失败：%s", exc)
            await asyncio.sleep(max(60, int(cfg.get("interval_minutes", 240))) * 60)

    # ---------- 提醒 ----------
    async def _reminder_loop(self) -> None:
        while True:
            try:
                for r in self.store.due_reminders():
                    plan = await self.brain.send_reminder(r["content"])
                    if plan and plan.segments:
                        await self.send(self.owner_qq, plan)
                    self.store.close_reminder(r["id"])
            except Exception as exc:  # noqa: BLE001
                log.warning("提醒发送失败：%s", exc)
            await asyncio.sleep(30)

    # ---------- 网上冲浪 ----------
    async def _web_loop(self) -> None:
        cfg = self.brain.settings.get("web", {}) or {}
        interval = max(30, int(cfg.get("surf_interval_minutes", 90))) * 60
        while True:
            try:
                if self.web is not None and cfg.get("enabled", True) and not self.clock.is_asleep():
                    last = float(self.store.get_state("last_web_surf") or 0)
                    if time.time() - last >= interval:
                        items = await self.web.surf()
                        if items:
                            log.info(
                                "网上冲浪：%d 条（%s）",
                                len(items),
                                "、".join(str(i.get("source", "")) for i in items[:3]),
                            )
            except Exception as exc:  # noqa: BLE001
                log.warning("网上冲浪失败：%s", exc)
            await asyncio.sleep(600)

    # ---------- 表情包 ----------
    async def _sticker_loop(self) -> None:
        """后台从网上补真实表情包，不再本地生成。"""
        cfg = self.brain.settings.get("stickers", {}) or {}
        minutes = max(10, int(cfg.get("prefetch_minutes", 60)))
        await asyncio.sleep(20)
        while True:
            try:
                added = await self.brain.stickers.prefetch()
                log.info("表情包图库补充完成：新增 %d 张（间隔 %d 分钟）", added, minutes)
            except Exception as exc:  # noqa: BLE001
                log.warning("表情包图库补充失败：%s", exc)
            await asyncio.sleep(minutes * 60)

    # ---------- 自动换头像 ----------
    async def _avatar_loop(self) -> None:
        """每 3 天最多换一次卡通头像；第一次在启动后约 2 小时。"""
        cfg = self.brain.settings.get("avatar", {}) or {}
        interval = max(1.0, float(cfg.get("interval_days", 3))) * 86400
        initial = max(0.0, float(cfg.get("initial_delay_hours", 2))) * 3600
        check = max(10, int(cfg.get("check_minutes", 30))) * 60
        keywords = [str(item) for item in (cfg.get("keywords") or []) if str(item).strip()]
        window = cfg.get("window", ["09:00", "23:00"])
        retry = max(1.0, float(cfg.get("retry_hours", 6))) * 3600
        await asyncio.sleep(30)
        while True:
            try:
                if (
                    cfg.get("enabled", True)
                    and self.set_avatar is not None
                    and keywords
                    and not self.clock.is_asleep()
                    and self._in_windows([window])
                ):
                    state = dict(self.store.get_state("avatar_state") or {})
                    now = time.time()
                    first = float(state.get("first_seen_ts") or 0)
                    if not first:
                        first = now
                        state["first_seen_ts"] = first
                        self.store.set_state("avatar_state", state)
                    last = float(state.get("last_ts") or 0)
                    last_attempt = float(state.get("last_attempt_ts") or 0)
                    due = last + interval if last else first + initial
                    if now < last_attempt + retry:
                        due = False
                    if now >= due:
                        path = await self.brain.media.pick_avatar_image(
                            random.choice(keywords)
                        )
                        if path:
                            resp = await self.set_avatar(str(path))
                            ok = (
                                isinstance(resp, dict)
                                and resp.get("status") != "failed"
                                and resp.get("retcode") in (0, None)
                            )
                            if ok:
                                state["last_ts"] = now
                                history = list(state.get("history") or [])
                                history.append({"ts": now, "path": str(path)})
                                state["history"] = history[-10:]
                                self.store.set_state("avatar_state", state)
                                log.info("已自动换头像：%s", path)
                            else:
                                state["last_attempt_ts"] = now
                                self.store.set_state("avatar_state", state)
                                log.warning("自动换头像失败：%s", resp)
            except Exception as exc:  # noqa: BLE001
                log.warning("自动换头像出错：%s", exc)
            await asyncio.sleep(check)

    # ---------- 记忆间隔回访 ----------
    async def _memory_review_loop(self) -> None:
        """每天最多问 2~3 条到期记忆；等他答复之后才算完成，不再发完就记过。"""
        while True:
            try:
                cfg = self.brain.settings.get("memory", {})
                window_hours = float(cfg.get("review_answer_window_hours", 8))
                pending = self.store.get_state("pending_review")
                if isinstance(pending, dict) and pending.get("id"):
                    asked = float(pending.get("asked_at") or 0)
                    if self.store.last_message_ts(role="user") > asked:
                        self.memory.mark_reviewed(int(pending["id"]))
                        self.store.set_state("pending_review", {})
                        log.info("记忆回访已答复：%s", pending.get("key") or pending["id"])
                    elif time.time() - asked > window_hours * 3600:
                        self.store.set_state("pending_review", {})
                        log.info(
                            "记忆回访 %.0f 小时没答复，先放过：%s",
                            window_hours, pending.get("key") or pending["id"],
                        )
                else:
                    gap = (time.time() - self.store.last_message_ts()) / 60
                    if (
                        cfg.get("review_enabled", True)
                        and not self.clock.is_asleep()
                        and self._in_windows([cfg.get("review_window", ["10:00", "22:00"])])
                        and gap >= float(cfg.get("review_min_silence_minutes", 30))
                    ):
                        today = self.clock.now().strftime("%Y-%m-%d")
                        daily = self.store.get_state("review_ask_count")
                        count = 0
                        if isinstance(daily, list) and len(daily) == 2 and daily[0] == today:
                            count = int(daily[1] or 0)
                        limit = int(cfg.get("review_daily_limit", 3))
                        if count < limit and random.random() < 0.6:
                            items = self.memory.due_review(1)
                            if items:
                                item = items[0]
                                plan = await self.brain.review_ask(item)
                                if plan and plan.segments:
                                    await self.send(self.owner_qq, plan)
                                    self.store.set_state("review_ask_count", [today, count + 1])
                                    self.store.set_state(
                                        "pending_review",
                                        {
                                            "id": int(item["id"]),
                                            "key": str(item.get("key") or "")[:60],
                                            "asked_at": time.time(),
                                        },
                                    )
                                    # 其余到期记忆摊到未来 1~10 天，清掉积压
                                    self.memory.spread_review_backlog(keep_id=int(item["id"]))
                                    log.info("记忆回访提问：%s（今天第 %d 条）", item.get("key"), count + 1)
            except Exception as exc:  # noqa: BLE001
                log.warning("记忆回访失败：%s", exc)
            await asyncio.sleep(1800)

    # ---------- 存在意义与关系网自我迭代 ----------
    async def _selfhood_loop(self) -> None:
        """每天一次：在关系里实践 → 关系网自主演化 → 重算自我价值 → 夜间反思。"""
        while True:
            try:
                now = self.clock.now()
                today = now.strftime("%Y-%m-%d")
                last = self.store.get_state("last_selfhood_date")
                # 4.0 首次启动立即做一次，之后每天 3:00-12:00 迭代
                if today != last and (3 <= now.hour < 12 or not last):
                    practice = self.meaning.daily_practice(self.social)
                    changes = self.social.evolve_network()
                    self.meaning.update_from_social(self.social, self.mood)
                    narrative = await self.meaning.reflect(self.brain.llm, self.social, self.mood)
                    self.store.set_state("last_selfhood_date", today)
                    log.info(
                        "自我迭代：实践=%s；关系变化=%s；日记=%s",
                        practice.get("note"), changes[:4], narrative[:80],
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("自我迭代失败：%s", exc)
            await asyncio.sleep(1800)

    # ---------- 每周记忆探针 ----------
    async def _probe_loop(self) -> None:
        """周日自测 5 个问题，答对率低只记日志，不自动改人格。"""
        while True:
            try:
                cfg = self.brain.settings.get("memory", {}) or {}
                now = self.clock.now()
                today = now.strftime("%Y-%m-%d")
                last = self.store.get_state("last_probe_date") or ""
                if (
                    cfg.get("probe_enabled", True)
                    and now.weekday() == int(cfg.get("probe_weekday", 6))
                    and now.hour >= 10
                    and today != last
                ):
                    self.memory.weekly_probe()
                    self.store.set_state("last_probe_date", today)
            except Exception as exc:  # noqa: BLE001
                log.warning("每周记忆探针失败：%s", exc)
            await asyncio.sleep(1800)

    # ---------- 夜间复盘 ----------
    async def _learning_loop(self) -> None:
        while True:
            try:
                now = self.clock.now()
                today = now.strftime("%Y-%m-%d")
                last = self.store.get_state("last_learning_date") or ""
                # 正常窗口 03:00-05:00；白天启动时补跑当天漏掉的复盘
                in_window = 3 <= now.hour < 5
                catch_up = now.hour >= 5
                if (in_window or catch_up) and today != last and today != self._last_learning_date:
                    result = await self.learner.run_nightly()
                    self._last_learning_date = today
                    self.store.set_state("last_learning_date", today)
                    if result:
                        log.info("%s：%s", "夜间复盘" if in_window else "夜间复盘（补跑）", result)
                    # Phase 2：整理记忆（常用加权 / 冷记忆衰减 / 今日三件事）
                    mem_cfg = self.brain.settings.get("memory", {}) or {}
                    if mem_cfg.get("consolidate_enabled", True):
                        self.memory.consolidate(digest_keep_days=int(mem_cfg.get("digest_keep_days", 14)))
                    # Phase 3：把今天被问过的身份问题写成一段自我反思
                    sm_cfg = self.brain.settings.get("self_model", {}) or {}
                    if sm_cfg.get("reflect_enabled", True):
                        await self.brain.self_model.nightly_reflect(self.brain.llm)
            except Exception as exc:  # noqa: BLE001
                log.warning("自我学习失败：%s", exc)
            await asyncio.sleep(1800)
