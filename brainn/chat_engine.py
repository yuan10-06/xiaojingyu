"""单机聊天引擎：不依赖 tkinter，桌面和手机共用。

后台 asyncio 线程负责大脑、数据库和调度器，界面只通过 window 回调收消息。
"""
from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from pathlib import Path

from .config import Config
from .timing import ReplyPlan
from .typo import make_typo

log = logging.getLogger(__name__)


class ChatEngine:
    """后台引擎：创建 App、跑调度器、处理消息与回复节奏。"""

    def __init__(self, config: Config, window: "ChatWindow"):
        self.config = config
        self.window = window
        self.app = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.thread: threading.Thread | None = None
        self._ready = threading.Event()
        # 每条待合并输入：text / quote / quote_image / image_path / image_url
        self._buffer: list[dict] = []
        self._merge_task: asyncio.Task | None = None
        self._recall_tasks: set[asyncio.Task] = set()
        # 已经生成入库、但还没真正上屏的回复：手机端历史接口要把它们藏起来，
        # 避免历史重载提前剧透，等事件到点后再显示。
        self._pending_ids: set[int] = set()
        self._closing = False
        # 同一时间只允许一个大脑生成；用输入序号判断这条回复是否已经过时
        self._handle_lock = asyncio.Lock()
        self._input_seq = 0

    # ---------- 生命周期 ----------
    def start(self) -> bool:
        self.thread = threading.Thread(target=self._run, name="brainn-chat", daemon=True)
        self.thread.start()
        self._ready.wait(30)
        return self.app is not None and not self._closing

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        loop.create_task(self._main())
        try:
            loop.run_forever()
        finally:
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for t in pending:
                t.cancel()
            if pending:
                try:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:  # noqa: BLE001
                    pass
            loop.close()

    async def _main(self) -> None:
        from main import App

        from .scheduler import Scheduler

        try:
            app = App(self.config)
        except Exception:
            log.exception("单机版初始化失败")
            self.window.post(self.window.show_system, "（启动失败，详情见 logs/brainn.log）")
            self._ready.set()
            return

        self.app = app
        # ChatEngine 前端（手机/桌面单机）没有 QQ 表情码的图片资源，
        # 20% 的 face 分支会被降级成 Unicode 文本（"发了文字而不是表情包"），这里直接关掉。
        try:
            app.brain.allow_qq_face = False
        except Exception:  # noqa: BLE001
            pass
        # 手机端在启动补跑前做一次性本地初始化（清掉电脑 seed 的今日完成标记）
        prepare = getattr(self.window, "prepare_app", None)
        if prepare is not None:
            try:
                prepare(app)
            except Exception:  # noqa: BLE001
                log.exception("启动前准备失败")
        # 沿用电脑端的夜间策略：睡着时只有 night_reply_chance 的概率迷糊回，
        # 其余进 pending 队列，等醒来由 Scheduler._pending_loop 统一回复。
        self._ready.set()

        self.window.post(self.window.show_history, app.store.recent_messages(30))
        if app.clock.is_asleep():
            self.window.post(self.window.show_system, "（她已经睡了，这会儿回消息会很慢）")

        asyncio.create_task(self._status_loop())

        # 手机常被杀后台：启动时先补算实践时间，再补跑当天漏掉的复盘/自我迭代
        try:
            ctx = {"asleep": app.clock.is_asleep()}
            if getattr(app.shadow, "practice_enabled", True):
                app.shadow.practice.tick(time.time(), ctx)
                app.shadow.time_model.tick(time.time(), ctx)
        except Exception:  # noqa: BLE001
            log.exception("启动时实践补算失败")
        await self._startup_catch_up(app)

        scheduler = Scheduler(
            app.brain,
            app.proactive,
            app.weather,
            app.clock,
            app.store,
            app.mood,
            app.body,
            app.shadow,
            app.memory,
            app.learner,
            app.social,
            app.meaning,
            self._scheduler_send,
            0,
            self._post_dynamic,
            web=app.web,
        )
        # 不阻塞调度器：后台补齐今天缺失的人格日记录（旧版只在跳过时标了日期）
        asyncio.create_task(self._backfill_persona_today(app))
        await scheduler.run()

    async def _backfill_persona_today(self, app) -> None:
        """只做轻量补记：不调 LLM，避免重启后和聊天抢模型造成延迟。"""
        try:
            today_iso = app.clock.now().date().isoformat()
            history = app.store.get_state("persona_history") or []
            # 旧记录没有 day 字段：按时间补上日期，界面上能看出是哪一天
            dirty = False
            for item in history:
                if isinstance(item, dict) and not item.get("day") and float(item.get("ts") or 0) > 0:
                    item["day"] = time.strftime(
                        "%Y-%m-%d", time.localtime(float(item["ts"]))
                    )
                    dirty = True
            if dirty:
                app.store.set_state("persona_history", history)
            has_today = any(
                isinstance(item, dict) and str(item.get("day") or "") == today_iso
                for item in history
            )
            if has_today:
                return
            if str(app.store.get_state("last_learning_date") or "") != today_iso:
                return
            app.persona.record_day(
                today_iso,
                {},
                "今天的复盘已跑过，旧版没有留下日记录；从明天起每天自动记录",
            )
            log.info("轻量补记今天的人格演化记录：%s", today_iso)
        except Exception:  # noqa: BLE001
            log.exception("补齐人格演化记录失败")

    @staticmethod
    def _missing_days(last_value: str, today, max_days: int = 3):
        """返回需要补跑的日期（最多 max_days 天）。第一次没有记录时只补今天。"""
        import datetime as dt

        if not last_value:
            return [today]
        try:
            last = dt.date.fromisoformat(str(last_value))
        except ValueError:
            return [today]
        start = max(last + dt.timedelta(days=1), today - dt.timedelta(days=max_days - 1))
        days = []
        cursor = start
        while cursor <= today and len(days) < max_days:
            days.append(cursor)
            cursor += dt.timedelta(days=1)
        return days

    async def _startup_catch_up(self, app) -> None:
        """手机端启动补跑：按缺失日期补夜间复盘、记忆整理、自我迭代。"""
        import datetime as dt

        today = app.clock.now().date()
        status = {"at": time.time(), "learning_days": [], "selfhood_days": [], "error": ""}
        # 先把最近的点餐/外卖事件补成账本，并按离线时长补算“应该早到了”
        try:
            resolved = app.brain.life.reconcile(time.time())
            status["life_resolved"] = [
                str(event.get("title") or "") for event in (resolved or [])
            ][:5]
        except Exception as exc:  # noqa: BLE001
            status["error"] += "生活事件:" + str(exc)[:80] + ";"
            log.exception("启动补算生活事件失败")
        try:
            # 探针从 5 条扩到 5+7 条后，启动时刷新一次，不用等周日
            if app.store.get_state("memory_probe_version") != 3:
                app.memory.weekly_probe()
                app.store.set_state("memory_probe_version", 3)
                status["probe_refreshed"] = True
        except Exception as exc:  # noqa: BLE001
            status["error"] += "探针:" + str(exc)[:80] + ";"
            log.exception("启动刷新记忆探针失败")
        try:
            days = self._missing_days(str(app.store.get_state("last_learning_date") or ""), today)
            for day in days:
                start = dt.datetime.combine(day, dt.time.min).timestamp()
                end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min).timestamp()
                result = await asyncio.wait_for(
                    app.learner.run_nightly(start, end), timeout=150
                )
                app.store.set_state("last_learning_date", day.isoformat())
                status["learning_days"].append(day.isoformat())
                log.info("启动补跑夜间复盘 %s：%s", day.isoformat(), str(result)[:100])
            if days:
                mem_cfg = app.brain.settings.get("memory", {}) or {}
                if mem_cfg.get("consolidate_enabled", True):
                    app.memory.consolidate(
                        digest_keep_days=int(mem_cfg.get("digest_keep_days", 14))
                    )
                sm_cfg = app.brain.settings.get("self_model", {}) or {}
                if sm_cfg.get("reflect_enabled", True):
                    await asyncio.wait_for(
                        app.brain.self_model.nightly_reflect(app.brain.llm), timeout=120
                    )
        except Exception as exc:  # noqa: BLE001
            status["error"] += "复盘:" + str(exc)[:80] + ";"
            log.exception("启动补跑夜间复盘失败")
        try:
            days = self._missing_days(str(app.store.get_state("last_selfhood_date") or ""), today)
            for day in days:
                app.meaning.daily_practice(app.social)
                app.social.evolve_network()
                app.meaning.update_from_social(app.social, app.mood)
                await asyncio.wait_for(
                    app.meaning.reflect(app.brain.llm, app.social, app.mood), timeout=120
                )
                app.store.set_state("last_selfhood_date", day.isoformat())
                status["selfhood_days"].append(day.isoformat())
                log.info("启动补跑自我迭代 %s 完成", day.isoformat())
        except Exception as exc:  # noqa: BLE001
            status["error"] += "自我迭代:" + str(exc)[:80] + ";"
            log.exception("启动补跑自我迭代失败")
        try:
            app.store.set_state("catchup_status", status)
        except Exception:  # noqa: BLE001
            pass

    async def _status_loop(self) -> None:
        while True:
            if self.app is not None:
                self.window.post(self.window.set_status, self._status_line())
            await asyncio.sleep(60)

    def _status_line(self) -> str:
        app = self.app
        if app is None:
            return "启动中"
        mood = app.mood.state
        if app.clock.is_asleep():
            state = "睡着"
        elif app.clock.is_busy():
            state = "上课"
        else:
            state = "在线"
        return f"{state} · 心情 {int(mood.mood)}"

    # ---------- 已生成但还没上屏的回复 ----------
    def pending_message_ids(self) -> set[int]:
        return set(self._pending_ids)

    def _track_pending(self, plan: ReplyPlan | None) -> int:
        mid = int(getattr(plan, "message_id", 0) or 0) if plan is not None else 0
        if mid:
            self._pending_ids.add(mid)
        return mid

    def _mark_visible(self, message_id: int) -> None:
        if message_id:
            self._pending_ids.discard(int(message_id))

    # ---------- 用户输入 ----------
    def _store_assistant_row(self, text: str, kind: str = "text", media: str = "") -> int:
        """逐段落库：每段文字/表情包各存一条，刷新历史才能保持分条。"""
        try:
            if self.app is None:
                return 0
            mid = int(self.app.store.add_message("assistant", text, kind, media=media))
            if mid:
                self._pending_ids.add(mid)
            return mid
        except Exception:  # noqa: BLE001
            log.exception("回复消息入库失败")
            return 0

    def _store_user_row(self, text: str, kind: str, media: str = "", ts: float = 0) -> int:
        """在界面线程里同步落库，HTTP 返回前就写好，杀后台也不会丢。"""
        try:
            if self.app is None or (not str(text or "").strip() and kind == "text"):
                return 0
            return int(
                self.app.store.add_message(
                    "user", text, kind, ts=float(ts or time.time()), media=media
                )
            )
        except Exception:  # noqa: BLE001
            log.exception("用户消息即时入库失败")
            return 0

    def user_send(self, text: str, quote: str = "", quote_image: str = "") -> None:
        if self.loop is None or not self.loop.is_running() or self.app is None:
            self.window.show_system("（还在启动，稍等两秒再发）")
            return
        now = time.time()
        saved = self._store_user_row(str(text or "").strip(), "text", ts=now)
        asyncio.run_coroutine_threadsafe(
            self._queue_user(
                text, quote, quote_image, db_ids=[saved] if saved else [], ts=now
            ),
            self.loop,
        )

    def user_send_sticker(self, tag: str, path: str) -> None:
        """他发了一个表情包：先上屏，再当一条消息交给大脑。"""
        if self.loop is None or not self.loop.is_running() or self.app is None:
            self.window.show_system("（还在启动，稍等两秒再发）")
            return
        now = time.time()
        saved = self._store_user_row(f"[表情包:{tag}]", "sticker", ts=now)
        asyncio.run_coroutine_threadsafe(
            self._handle_sticker(tag, path, saved, now), self.loop
        )

    def user_send_image(self, path: str, url: str) -> None:
        """他拍了/选了一张照片：先上屏，再和文字一起等合并窗口后交给大脑。"""
        if self.loop is None or not self.loop.is_running() or self.app is None:
            self.window.show_system("（还在启动，稍等两秒再发）")
            return
        poster = getattr(self.window, "show_my_image", None)
        if poster is not None:
            self.window.post(poster, path)
        now = time.time()
        saved = self._store_user_row("[图片]", "image", media=str(path), ts=now)
        asyncio.run_coroutine_threadsafe(
            self._queue_user(
                image_path=path,
                image_url=url,
                db_ids=[saved] if saved else [],
                image_db_id=saved,
                ts=now,
            ),
            self.loop,
        )

    def recall(self, text: str, ts: float | None = None) -> bool:
        """撤回：还没发出去的从缓冲里删，已经入库的从数据库删。"""
        if self.loop is None or not self.loop.is_running():
            return False
        try:
            fut = asyncio.run_coroutine_threadsafe(self._recall(text, ts), self.loop)
            return bool(fut.result(timeout=4))
        except Exception:  # noqa: BLE001
            return False

    async def _recall(self, text: str, ts: float | None) -> bool:
        removed = False
        kept = []
        for item in self._buffer:
            if not removed and item.get("text") == text:
                removed = True
                continue
            kept.append(item)
        self._buffer[:] = kept
        app = self.app
        deleted = app.store.delete_user_message(text, ts) if app else False
        return bool(removed or deleted)

    def _batch_window(self) -> float:
        """连续消息合并窗口，与电脑端共用 settings.reply.batch_window_seconds。"""
        try:
            cfg = self.app.brain.settings.get("reply", {}) if self.app else {}
            return max(1.0, min(20.0, float(cfg.get("batch_window_seconds", 8))))
        except Exception:  # noqa: BLE001
            return 8.0

    async def _queue_user(
        self,
        text: str = "",
        quote: str = "",
        quote_image: str = "",
        image_path: str = "",
        image_url: str = "",
        db_ids: list[int] | None = None,
        image_db_id: int = 0,
        ts: float = 0,
    ) -> None:
        # 正常路径已经在 user_send 里同步落库；这里保留兜底，防止有调用方漏传。
        now = float(ts or time.time())
        if db_ids is None:
            db_ids = []
            chunk = str(text or "").strip()
            if chunk:
                saved = self._store_user_row(chunk, "text", ts=now)
                if saved:
                    db_ids.append(saved)
            if image_path:
                saved = self._store_user_row("[图片]", "image", media=str(image_path), ts=now)
                if saved:
                    image_db_id = saved
                    db_ids.append(saved)
        self._buffer.append(
            {
                "text": str(text or ""),
                "quote": str(quote or ""),
                "quote_image": str(quote_image or ""),
                "image_path": str(image_path or ""),
                "image_url": str(image_url or ""),
                "db_ids": list(db_ids),
                "image_db_id": int(image_db_id or 0),
                "ts": now,
            }
        )
        self._input_seq += 1
        if self._merge_task is not None:
            self._merge_task.cancel()
        self._merge_task = asyncio.create_task(self._flush_after(self._batch_window()))

    async def _flush_after(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        items = list(self._buffer)
        self._buffer.clear()
        self._merge_task = None
        if not items:
            return
        # 与电脑端 _combine 一致：文字和图片同批合并，图片用 [图片] 占位
        texts: list[str] = []
        image_path = ""
        image_url = ""
        for item in items:
            chunk = str(item.get("text") or "").strip()
            if chunk:
                texts.append(chunk)
            if item.get("image_path"):
                image_path = str(item["image_path"])
                image_url = str(item.get("image_url") or "")
                if "[图片]" not in texts:
                    texts.append("[图片]")
        quote = next((str(item.get("quote") or "") for item in reversed(items) if item.get("quote")), "")
        quote_image = next(
            (str(item.get("quote_image") or "") for item in reversed(items) if item.get("quote_image")),
            "",
        )
        anchor = str(items[-1].get("text") or "").strip()
        text = "\n".join(texts)
        if not text and not image_path:
            return
        db_ids = [int(i) for item in items for i in (item.get("db_ids") or [])]
        image_db_id = next(
            (int(item.get("image_db_id") or 0) for item in reversed(items) if item.get("image_db_id")),
            0,
        )
        incoming_ts = float(next((item.get("ts") for item in items if item.get("ts")), 0) or 0)
        await self._handle(
            text,
            quote,
            seq=self._input_seq,
            anchor=anchor,
            image_path=image_path,
            image_url=image_url,
            quote_image=quote_image,
            incoming_saved=bool(db_ids),
            incoming_ts=incoming_ts,
            incoming_image_id=image_db_id,
        )

    async def _handle(
        self,
        text: str,
        quote: str = "",
        seq: int | None = None,
        anchor: str = "",
        image_path: str = "",
        image_url: str = "",
        quote_image: str = "",
        incoming_saved: bool = False,
        incoming_ts: float = 0.0,
        incoming_image_id: int = 0,
    ) -> None:
        from .media import Media

        async with self._handle_lock:
            # 排队期间用户又发了新消息：这条旧批次让位给最新批次，避免回复几条之前的话
            if seq is not None and seq < self._input_seq:
                return
            self.window.post(self.window.set_typing, True)
            try:
                if quote_image:
                    quote = await self._quote_with_vision(quote, quote_image)
                url = Media.extract_url(text)
                kind = "image" if image_path else ("link" if url else "text")
                log.info("单机版收到：%s", (text or kind)[:60])
                plan = await asyncio.wait_for(
                    self.app.brain.handle(
                        text,
                        kind=kind,
                        url=url,
                        image_url=image_url or None,
                        user_id=1,
                        quote=quote,
                        media=image_path,
                        incoming_saved=incoming_saved,
                        incoming_ts=incoming_ts,
                        incoming_image_id=incoming_image_id,
                    ),
                    timeout=120,
                )
            except asyncio.TimeoutError:
                log.warning("回复生成超时（120 秒）")
                self.window.post(self.window.show_system, "（刚脑子卡住了，你再说一遍）")
                return
            except Exception:
                log.exception("生成回复失败")
                self.window.post(self.window.show_system, "（她这边卡了一下，再发一次试试）")
                return
            finally:
                self.window.post(self.window.set_typing, False)
            if plan is None or not plan.segments:
                # 夜间已进 pending 队列时不刷系统提示，安静等她醒来统一回
                if not getattr(plan, "deferred", False):
                    self.window.post(self.window.show_system, "（她睡着了，这条会等她醒来再回）")
                return
            # 生成期间用户又发了新消息：这条回复已经过时，不再发出去，等下一批统一回。
            # 同时删掉刚入库的这条回复，避免下次拉历史时又冒出来。
            if seq is not None and seq < self._input_seq:
                try:
                    mid = int(getattr(plan, "message_id", 0) or 0)
                    if mid and self.app is not None:
                        self.app.store.delete_message(mid)
                except Exception:  # noqa: BLE001
                    pass
                return
            pure_image = kind == "image" and (text or "").strip() in ("", "[图片]")
            if anchor.strip() and not pure_image:
                # 手机端像 QQ 一样：她的回复引用他刚发的那条消息，纯图不引用
                plan.quote = anchor.strip()[:80]
            self._track_pending(plan)
            # 把这条回复所属的输入批次 seq 挂到 plan 上，deliver 里每段发送前都检查，
            # 防止发送延迟期间用户又发了新消息导致过时片段继续冒出来。
            plan._seq = seq if seq is not None else -1  # type: ignore[attr-defined]
            log.info("回复 %d 段，总延迟约 %.0f 秒", len(plan.segments), plan.total_delay)
            await self.deliver(plan)

    async def _handle_sticker(
        self, tag: str, path: str, saved_id: int = 0, ts: float = 0
    ) -> None:
        poster = getattr(self.window, "show_my_sticker", None)
        if poster is not None:
            self.window.post(poster, path, tag)
        now = float(ts or time.time())
        sticker_text = f"[表情包:{tag}]"
        async with self._handle_lock:
            self.window.post(self.window.set_typing, True)
            try:
                plan = await asyncio.wait_for(
                    self.app.brain.handle(
                        sticker_text,
                        kind="sticker",
                        user_id=1,
                        incoming_saved=bool(saved_id),
                        incoming_ts=now,
                    ),
                    timeout=120,
                )
            except asyncio.TimeoutError:
                log.warning("表情包回复超时（120 秒）")
                self.window.post(self.window.show_system, "（刚脑子卡住了，你再说一遍）")
                return
            except Exception:
                log.exception("表情包回复失败")
                self.window.post(self.window.show_system, "（她这边卡了一下，再发一次试试）")
                return
            finally:
                self.window.post(self.window.set_typing, False)
            if plan is not None and plan.segments:
                self._track_pending(plan)
                await self.deliver(plan)

    async def _quote_with_vision(self, quote: str, image_url: str) -> str:
        """他引用了一张图片：像电脑端一样先做视觉描述，再交给大脑。"""
        raw = b""
        try:
            from urllib.parse import unquote, urlparse

            src = str(image_url or "").strip()
            path = ""
            if src.startswith("/media?path="):
                path = unquote(src[len("/media?path=") :])
            elif src.startswith("file://"):
                path = unquote(urlparse(src).path)
            if path and Path(path).is_file():
                raw = Path(path).read_bytes()
            elif src:
                downloaded = await self.app.brain.media.download_image(src)
                if downloaded:
                    raw = downloaded[0]
            if raw:
                note = await asyncio.wait_for(
                    self.app.brain.llm.describe_image_from_bytes(raw), timeout=30
                )
                if note:
                    return ("[图片] " + str(note))[:220]
        except Exception:  # noqa: BLE001
            log.warning("引用图片识别失败", exc_info=True)
        return quote.strip() or "[图片]"

    async def _scheduler_send(self, user_id: int | None, plan: ReplyPlan) -> None:
        await self.deliver(plan)

    async def _post_dynamic(self, text: str, images: list[str] | None = None) -> dict:
        """手机端把动态发到 App 内的朋友圈；桌面窗口没有这个接口就不发。"""
        poster = getattr(self.window, "show_dynamic", None)
        if poster is None:
            return {"platform": "none"}
        self.window.post(poster, text, list(images or []))
        return {"platform": "app"}

    def _typo_pick(self, plan: ReplyPlan) -> tuple[int | None, str]:
        """按电脑端 typo 配置，把最后一句话故意打错（correct_chance=0 时保留错字）。"""
        app = self.app
        if app is None:
            return None, ""
        try:
            cfg = app.brain.settings.get("typo", {}) or {}
        except Exception:  # noqa: BLE001
            return None, ""
        if not cfg.get("enabled", True):
            return None, ""
        candidates = [
            i
            for i, seg in enumerate(plan.segments)
            if seg.kind == "text"
            and len(str(seg.payload or "")) >= 6
            and "http" not in str(seg.payload or "")
        ]
        if not candidates or random.random() >= float(cfg.get("chance", 0.15)):
            return None, ""
        idx = candidates[-1]
        original = str(plan.segments[idx].payload)
        candidate = make_typo(original)
        if candidate and candidate != original:
            return idx, candidate
        return None, ""

    async def deliver(self, plan: ReplyPlan) -> None:
        if plan is None or not plan.segments:
            return
        mid = self._track_pending(plan)
        # 入库已改为逐段进行（brain 不再预存合并消息），所以这里直接取带 id 的上屏方法。
        id_poster = getattr(self.window, "show_text_id", None)
        typo_idx, typo_text = self._typo_pick(plan)
        quote = str(getattr(plan, "quote", "") or "").strip()
        quote_poster = getattr(self.window, "show_text_quote", None) if quote else None
        id_used = False
        first_mid = 0

        for i, seg in enumerate(plan.segments):
            # 每段发送前都检查是否已被新消息覆盖——防止多段延迟期间过时片段继续冒出来。
            plan_seq = getattr(plan, "_seq", -1)
            if plan_seq >= 0 and self._input_seq > plan_seq:
                log.info("回复已过时，跳过剩余 %d 段", len(plan.segments) - i)
                return
            if seg.delay and seg.delay > 0:
                await asyncio.sleep(seg.delay)
            # sleep 之后再检查一次（让出事件循环期间可能已进新消息）
            plan_seq = getattr(plan, "_seq", -1)
            if plan_seq >= 0 and self._input_seq > plan_seq:
                log.info("回复过时（sleep 期间进了新消息），跳过剩余 %d 段", len(plan.segments) - i)
                return
            payload = typo_text if i == typo_idx else seg.payload
            if seg.kind == "text":
                text = str(payload)
                seg_mid = self._store_assistant_row(text, "text")
                if seg_mid and not first_mid:
                    first_mid = seg_mid
                if not id_used and id_poster is not None and seg_mid:
                    # 手机端：带上数据库消息 ID，历史里已有同 ID 时不再重复渲染
                    self.window.post(
                        id_poster,
                        "her",
                        text,
                        seg_mid,
                        quote if quote_poster is not None else "",
                    )
                    quote_poster = None
                elif quote_poster is not None:
                    self.window.post(quote_poster, "her", text, quote)
                    quote_poster = None
                else:
                    self.window.post(self.window.show_text, "her", text)
                id_used = True
                if seg_mid:
                    self._mark_visible(seg_mid)
            elif seg.kind == "sticker":
                tag = str(seg.payload)
                path = self.app.stickers.pick(tag) if self.app else None
                if path:
                    seg_mid = self._store_assistant_row(f"[表情包:{tag}]", "sticker", media=str(path))
                    self.window.post(self.window.show_sticker, path)
                    if seg_mid:
                        self._mark_visible(seg_mid)
                else:
                    self.window.post(self.window.show_text, "her", "[表情包]")
            elif seg.kind == "face":
                # QQ 表情码在手机端没有图片资源，直接映射成 Unicode 表情，避免显示 [QQ表情]
                from .emoji import face as face_emoji

                self.window.post(self.window.show_text, "her", face_emoji(str(seg.payload)))
            elif seg.kind == "link":
                self.window.post(self.window.show_link, seg.payload or {})
        # 每段入库后已单独标记可见，这里不再统一放行。
        # 发完后悔：与电脑端一致，只在单条文本时撤回最后一条并补一句
        if typo_idx is None and plan.recall and len(plan.segments) == 1:
            seg = plan.segments[0]
            if seg.kind == "text" and first_mid:
                task = asyncio.create_task(
                    self._recall_later(first_mid, str(seg.payload), dict(plan.recall))
                )
                self._recall_tasks.add(task)
                task.add_done_callback(self._recall_tasks.discard)

    async def _recall_later(self, message_id: int, text: str, spec: dict) -> None:
        """延迟撤回刚发的那条，删库并通知界面移除气泡，再补一句。"""
        try:
            await asyncio.sleep(float(spec.get("delay", 15)))
        except asyncio.CancelledError:
            return
        app = self.app
        try:
            if app is not None:
                app.store.delete_message(int(message_id))
        except Exception:  # noqa: BLE001
            log.warning("撤回时删除消息失败", exc_info=True)
        poster = getattr(self.window, "show_recall", None)
        if poster is not None:
            try:
                self.window.post(poster, int(message_id), str(text))
            except Exception:  # noqa: BLE001
                pass
        follow = random.choice(
            ["……刚才那句当我没说", "手滑了 别往心里去", "算了 我收回", "发错了 你别看那条"]
        )
        try:
            if app is not None:
                app.store.add_message("assistant", follow, "text")
        except Exception:  # noqa: BLE001
            log.warning("撤回补话入库失败", exc_info=True)
        self.window.post(self.window.show_text, "her", follow)

    def shutdown(self) -> None:
        self._closing = True
        loop = self.loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if self.thread is not None:
            self.thread.join(timeout=3)
