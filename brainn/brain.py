"""大脑：把消息 → 情绪 → 提示词 → 模型 → 拟真回复计划。"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import random
import re
import time
from typing import Any

from .body import Body
from .clock import Clock
from .config import Config
from .core.contracts import Percept
from .db import Store
from .emotion import detect
from .emoji import detect as detect_emoji
from .emoji import pick as pick_emoji
from .emoji import strip as strip_emoji
from .learner import Learner
from .life import LifeEvents
from .llm import LLM
from .meaning import Meaning
from .media import Media
from .memory import Memory
from .mood import Mood
from .persona import Persona
from .prompt import build_proactive_prompt, build_review_prompt, build_system, build_task_prompt
from .selfmodel import SelfModel
from .stickers import Stickers
from .tasks import Tasks
from .qt import carrier_text, detect_conflict, ensure_carrier, ensure_finitude, finitude_hint
from .text_style import loosen
from .timing import OutSegment, ReplyPlan, Timing
from .weather import WeatherService

log = logging.getLogger(__name__)

# 模型偶尔把表情包写成文字标签（如 [sticekr: aggrieved]），这里统一识别并在文字里剥掉。
_STICKER_TEXT_RE = re.compile(
    r"[\[【(（]\s*(?:sti\w{0,8}k\w{0,8}|表情包?|表情)\s*[:：]\s*([A-Za-z_-]+)\s*[\]】)）]",
    re.I,
)

CLOSE_WORDS = {
    "嗯", "嗯嗯", "嗯呢", "嗯呢嗯呢", "嗯呐", "好", "好的", "好吧", "好滴", "好嘞",
    "行", "行吧", "行行", "行行行", "哦", "哦哦", "ok", "okay", "收到", "知道了",
    "晓得了", "懂了", "明白", "可以", "可以可以", "那行", "那就这样", "先这样",
}

# 热梗词表：命中后她接梗时会优先甩表情包（不只靠 LLM 自觉输出 sticker 字段）。
# 与 prompt.py 梗认知列表保持一致并扩充；ascii 词必须小写，匹配前对文本做 lower()。
MEME_WORDS = {
    "尊嘟假嘟", "尊嘟", "假嘟", "栓q", "芭比q", "破防", "蚌埠住", "绝绝子", "yyds",
    "偷感", "显眼包", "哈基米", "科目三", "挖呀挖", "脆皮", "松弛感", "班味",
    "泰裤辣", "多巴胺", "发疯文学", "已老实求放过", "已老实", "包的", "xswl",
    "u1s1", "社死", "你礼貌吗", "小丑竟是我自己", "纯爱", "抽象", "吗喽",
    "奥德彪", "电子榨菜", "city不city", "那咋了", "紫啧", "红温", "躺平",
    "摆烂", "内卷", "凡尔赛", "笑死", "绷不住", "乐了", "急急急", "典中典",
    "遥遥领先", "公主请", "老铁", "扎心了", "emo了", "破大防", "神金", "人机",
    "闹麻了", "赢麻了", "爽死", "谁懂", "我不理解", "狠狠", "代入感", "开摆",
}

ACTIVITIES = {
    "凌晨": ["躺床上刷手机刷到现在", "刚喝完水准备硬睡", "失眠，脑子里在想乱七八糟的事"],
    "早上": ["刚爬起来，头发乱得像鸡窝", "在洗漱，嘴里还有牙膏味", "正要去食堂买早饭"],
    "上午": ["在上课，老师在讲天书", "偷摸在课桌底下刷手机", "在图书馆占座"],
    "中午": ["在食堂纠结吃什么", "刚抢到最后一份饭", "手头有点事，忙得没空看手机"],
    "下午": ["没课，窝在宿舍", "在图书馆趴着打瞌睡", "刚忙完一阵，腿有点软"],
    "晚上": ["刚洗完澡躺床上", "在宿舍追剧", "在纠结要不要点夜宵"],
    "深夜": ["熬夜刷视频，说明天一定早睡", "肚子饿了但懒得动", "宿舍熄灯了还在看手机"],
}


# 检索扩展：只把同一类意思的词补进查询，避免“想吃什么”只撞上一个“吃”字
_MEMORY_EXPANSIONS = (
    (
        ("吃", "饭", "早餐", "早饭", "午饭", "晚饭", "夜宵", "饿", "奶茶", "火锅", "海底捞", "番茄锅", "食堂"),
        "吃 饭 早餐 早饭 早上 胃口 午饭 晚饭 夜宵 饿 奶茶 火锅 海底捞 番茄锅 清淡 口味 食堂",
    ),
    (("累", "困", "熬夜", "失眠", "没精神", "疲惫", "睡"), "累 困 熬夜 失眠 睡 休息 精力"),
    (("答应", "约定", "约好", "欠", "请我", "叫醒"), "答应 约定 欠 叫醒 请 账 说好"),
    (("名字", "叫什么", "称呼", "昵称"), "名字 大名 小名 名叫 称呼 喊 叫 昵称"),
    (("关系", "喜欢", "女朋友", "男朋友", "暧昧", "在一起"), "关系 喜欢 暧昧 女朋友 男朋友 在一起"),
    (("学习", "复习", "考试", "作业", "课", "图书馆"), "学习 复习 考试 作业 课 图书馆"),
)


class Brain:
    def __init__(
        self,
        config: Config,
        store: Store,
        mood: Mood,
        memory: Memory,
        persona: Persona,
        llm: LLM,
        weather: WeatherService,
        clock: Clock,
        timing: Timing,
        stickers: Stickers,
        media: Media,
        tasks: Tasks,
        learner: Learner,
        social,
        meaning: Meaning,
        body: Body,
        web=None,
    ):
        self.config = config
        self.settings = config.settings
        self.persona_cfg = config.persona
        self.store = store
        self.mood = mood
        self.memory = memory
        self.persona = persona
        self.llm = llm
        self.weather = weather
        self.clock = clock
        self.timing = timing
        self.stickers = stickers
        self.media = media
        self.tasks = tasks
        self.learner = learner
        self.social = social
        self.meaning = meaning
        self.body = body
        self.web = web
        self.self_model = SelfModel(store, memory)
        self.core = None
        self.emitter = None  # async (user_id, ReplyPlan)
        self.avatar_setter = None  # async (image_path) -> OneBot response
        self.proactive_engine = None
        self.allow_defer = True
        # 手机端会关掉：他拍的照片不应该被当成表情包自动收进图库
        self.allow_image_sticker_steal = True
        # QQ 表情码只有在 OneBot（电脑 QQ 端）才有原生图片资源；
        # ChatEngine 前端（手机/桌面单机）会把它降级成 Unicode 文本，看起来"只发了文字"，
        # 所以 ChatEngine 启动时把它关掉，统一走真实表情包图库。
        self.allow_qq_face = True
        # QT 链路：本轮折射快照与召回到的记忆，供 M7 / M9 使用
        self._turn_refraction_id = 0
        self._turn_refraction: dict[str, Any] = {}
        self._last_recall_items: list[dict[str, Any]] = []
        # 语义检索改写缓存：同一句话 2 小时内不重复调模型
        self._rewrite_cache: dict[str, tuple[float, str]] = {}
        # 生活事件账本：点餐/外卖/快递等有时效的事件，离线重启后按时间补算
        self.life = LifeEvents(store, self.settings)
        # G4：写入有限性参数（默认开；只落 state，不改行为）
        try:
            ensure_finitude(store, self.settings)
        except Exception:  # noqa: BLE001
            log.warning("QT 有限性初始化失败", exc_info=True)
        # G1：写入当前载体的能力表，并注入 prompt
        try:
            self.carrier = ensure_carrier(store, self.settings)
            self.persona_cfg["carrier_text"] = carrier_text(self.carrier)
            store.set_state("qt_m0", {
                "class_essence": self.persona_cfg.get("class_essence") or {},
                "core_traits": self.persona_cfg.get("core_traits") or [],
            })
        except Exception:  # noqa: BLE001
            self.carrier = {}
            log.warning("QT 载体能力表初始化失败", exc_info=True)
        # 历史库补救：换人设时把“关于他”的事实一起归档了，只恢复一次
        try:
            if not store.get_state("mem_restore_personal_v1"):
                restored = self.memory.mstore.restore_personal_memories()
                store.set_state("mem_restore_personal_v1", {"at": time.time(), "restored": restored})
                if restored:
                    log.info("恢复关于他的记忆 %d 条", restored)
        except Exception:  # noqa: BLE001
            log.warning("记忆恢复失败", exc_info=True)

    def _prompt_persona(self) -> dict[str, Any]:
        """换过新人设后的 30 天里，不再把旧人设学到的语气和反馈带进提示词。"""
        try:
            reset_at = float(self.store.get_state("persona_reset_at") or 0)
            if reset_at and time.time() - reset_at < 30 * 86400:
                cfg = copy.deepcopy(self.persona_cfg)
                speech = cfg.setdefault("speech", {})
                speech["learned_style"] = {}
                speech["human_feedback"] = []
                return cfg
        except Exception:  # noqa: BLE001
            pass
        return self.persona_cfg

    # ------------------------------------------------------------------
    # 收到他的消息
    # ------------------------------------------------------------------
    async def handle(
        self,
        text: str,
        *,
        kind: str = "text",
        url: str | None = None,
        image_url: str | None = None,
        user_id: int | None = None,
        store_incoming: bool = True,
        deferred: bool = False,
        quote: str = "",
        media: str = "",
        incoming_saved: bool = False,
        incoming_ts: float = 0.0,
        incoming_image_id: int = 0,
    ) -> ReplyPlan | None:
        # 手机端在收到消息的那一刻已经把用户消息写进库（杀后台也不丢）；
        # 这里只要跳过重复写入，同时仍按“上一条用户消息”算时间间隔。
        if incoming_saved and incoming_ts:
            prev_user_ts = self.store.last_message_ts("user", before=float(incoming_ts) - 0.001)
        else:
            prev_user_ts = self.store.last_message_ts("user")
        # 每条消息前先按真实时间推进生理状态，避免用到 10 分钟前的旧值
        self.body.tick(asleep=self.clock.is_asleep())
        self.body.apply_to_mood(self.mood)
        try:
            if kind == "text":
                self.life.observe_user(text or "")
        except Exception:  # noqa: BLE001
            pass
        image_note = ""
        stolen_tag = ""
        avatar_changed = False
        avatar_note = ""
        if kind == "image" and image_url:
            # 图片链接通常是一次性的：只下载一次，视觉和偷图共用
            downloaded = await self.media.download_image(image_url)
            if downloaded:
                raw, suffix = downloaded
                saved_image = self.media.save_user_image(raw, suffix)
                if saved_image:
                    avatar_changed, avatar_note = await self._maybe_change_avatar(
                        text, saved_image
                    )
                image_note = await self.llm.describe_image_from_bytes(raw)
                if image_note:
                    is_meme = any(
                        w in image_note for w in ("表情包", "梗", "搞笑", "笑死", "无语", "吃瓜")
                    ) or ("文字" in image_note and len(raw) < 500_000)
                    if is_meme and len(raw) <= 1_500_000 and self.allow_image_sticker_steal:
                        stolen_tag = self.stickers.save_stolen(raw, suffix, image_note)
            else:
                image_note = await self.llm.describe_image(image_url)
        emotion = detect(text or (image_note if kind == "image" else ""))
        emoji_info = detect_emoji(text)
        if emoji_info and (
            emotion.get("label") == "neutral"
            or float(emoji_info.get("intensity", 0)) >= float(emotion.get("intensity", 0) or 0)
        ):
            emotion = {
                **emotion,
                "label": emoji_info["label"],
                "intensity": emoji_info["intensity"],
                "hint": emoji_info.get("hint", ""),
                "evidence": "".join(emoji_info.get("emojis", [])),
            }
        if store_incoming:
            stored = text or ("[图片]" if kind == "image" else "[消息]")
            if kind == "image" and image_note:
                stored = f"{stored}（图片内容：{image_note[:200]}）"
            if incoming_saved:
                if kind == "image" and incoming_image_id and image_note:
                    # 先落库的占位 [图片] 补上视觉描述，方便以后想起来
                    self.store.update_message_content(int(incoming_image_id), stored)
            else:
                self.store.add_message("user", stored, kind, media=media)
            self.mood.on_user_message(text)
            self.mood.on_user_emotion(str(emotion.get("label", "neutral")), float(emotion.get("intensity", 0)))
            self.social.on_user_interaction(text, emotion)
            self.meaning.on_interaction(emotion, self.social.edge("her", "user"))
            if url:
                self.mood.on_user_shared()

        # 睡着时：小概率迷糊回，其余进队列第二天醒来再回
        if store_incoming and not deferred and self.allow_defer and self.clock.is_asleep():
            night_chance = float(self.settings.get("schedule", {}).get("night_reply_chance", 0.2))
            if random.random() > night_chance:
                due = time.time() + max(
                    60.0, self.clock.seconds_until_wake() + random.uniform(0, 1800)
                )
                self.store.add_pending(text, kind, url, image_url, user_id, due)
                plan = ReplyPlan(segments=[])
                plan.deferred = True
                return plan

        close_signal = self._is_close_signal(text, kind)
        if close_signal:
            self.store.set_state("last_topic_end_ts", time.time())
            close_cfg = self.settings.get("reply", {}).get("close_signal", {})
            silent_chance = float(close_cfg.get("silent_chance", 0.38))
            if close_cfg.get("enabled", True) and random.random() < silent_chance:
                log.info("收尾信号，这次不回：%s", (text or "")[:20])
                return ReplyPlan(segments=[])

        if self._should_skip_low_value(text, kind):
            log.info("低价值短句，这次不回：%s", (text or "")[:20])
            return ReplyPlan(segments=[])

        weather = await self.weather.get()
        weather_line = weather.line() if weather else "天气接口没连上"
        weather_hint = weather.hint() if weather else ""
        semantic_query = ""
        if self._needs_semantic_rewrite(text or ""):
            semantic_query = await self._semantic_rewrite(text or "")
        memories = self._recall_for_prompt(text or kind, semantic_query)
        self._detect_m9_tension(text or "")
        situation = self._situation(text, kind, deferred, prev_user_ts)
        if avatar_note:
            situation += " " + avatar_note
        if emotion.get("label") != "neutral":
            situation += (
                f" 他现在的情绪：{emotion.get('label')}（强度 {emotion.get('intensity')}）。"
                f"{emotion.get('hint', '')}"
            )
        if quote:
            situation += (
                f" 他这条是在引用你之前说的：「{quote[:160]}」。"
                "你的第一句必须先直接回应这句被引用的话，再展开别的；"
                "不要答非所问，也不要把更早的话题重新捡回来。"
            )
        if emoji_info:
            situation += (
                f" 他用了 {'、'.join(emoji_info.get('emojis', []))}，"
                f"像是在表达{emoji_info.get('meaning', '某种情绪')}。"
            )
        if close_signal:
            situation += (
                " 他这句像是收尾（好/嗯呢/嗯嗯这类），不一定想继续聊："
                "你可以只回一个很短的收尾，或者顺口带一句自己的小事再停；"
                "别追问、别连发、别硬找话题。真要接着聊，就抛一个具体的小问题。"
            )
        extra = await self._content_extra(kind, url, image_note)
        if stolen_tag:
            extra += (
                f"\n【你刚把他的表情包偷进了自己的图库（{stolen_tag}）】"
                "可以顺口说一句“这个我收了”“归我了”之类，但别每次都提。"
            )

        # 手机版自己设了昵称时，按他的偏好称呼（QQ 模式没有这个状态）
        call_name = str(self.store.get_state("mobile_user_name") or "").strip()
        if call_name:
            extra += f"\n【他希望你怎么称呼他】叫他“{call_name[:20]}”。"

        # 手机端屏幕感知：只知道他当前开着哪个 App，看不到具体内容
        screen = self.store.get_state("mobile_screen_context") or {}
        if isinstance(screen, dict):
            pkg = str(screen.get("package") or "")
            age = time.time() - float(screen.get("ts") or 0)
            if screen.get("label") and pkg != "com.ganfanyu.app" and age <= 900:
                label = str(screen.get("label") or "")[:30]
                minutes = int(screen.get("minutes") or 0)
                line = f"\n【他手机现在开着「{label}」"
                if minutes:
                    line += f"，今天已经用了 {minutes} 分钟"
                line += "】只有自然的时候才顺口提一句，别每句都说，也别报流水账。"
                extra += line

        # 生活连续性：正在等的外卖/快递、刚完成的事件、你自己发过的动态、离线空档
        try:
            life_text = self.life.context_for_prompt()
            if life_text:
                extra += "\n\n" + life_text
        except Exception:  # noqa: BLE001
            pass

        # 朋友圈互动：他点的赞、他的评论、别人对他的回复，聊天里也能接上
        try:
            feed_text = self._feed_activity_text()
            if feed_text:
                extra += "\n\n" + feed_text
        except Exception:  # noqa: BLE001
            pass

        # 刚换过新人设：旧聊天里的身份/生活不再适用，避免她顺着旧话题说错
        try:
            reset_at = float(self.store.get_state("persona_reset_at") or 0)
            reset_text = str(self.store.get_state("persona_reset_text") or "").strip()
            if reset_at and time.time() - reset_at < 30 * 86400:
                extra += (
                    "\n\n【你最近换过新人设】"
                    + (reset_text[:120] or "她已经按新的身份生活")
                    + "。之前聊天里关于旧身份、旧城市、旧日程的内容已经不再适用；"
                    "以【你记得的事】里的新人设记忆和实时日程为准，不要主动捡起旧身份。"
                )
        except Exception:  # noqa: BLE001
            pass

        # 被问“你是不是 AI / 机器人 / 会不会思考”时，走自我模型，不直接否认也不直接承认
        identity_question = self.self_model.detect_identity_question(text or "")
        if identity_question:
            self.self_model.note_question(text or "")
            extra += (
                "\n【他正在问关于“你”的问题】先停半拍，说自己的不确定和感受，"
                "再用自己的话接住，最后反问他为什么这么问。"
                "不要直接否认，也不要说“作为 AI”，不要长篇讲图灵测试或大模型原理。"
            )

        # 明确要视频：先联网搜，再把真实链接附在回复后
        video_query = None
        video = None
        if not url and kind == "text":
            video_query = self.media.request_keyword(text)
        if video_query:
            video = await self.media.pick_video(video_query)
            if not video:
                video = await self.media.pick_video()
            if video:
                extra += (
                    f"\n【你刚搜到一个视频】{video['title']}（UP主：{video['author']}）。"
                    "回复里自然提一句，链接会在最后自动附上；不要自己写 URL，也不要写 [分享视频] 标签。"
                )
            else:
                extra += "\n【你刚想搜视频】没搜到合适的，直接说没找到，别编标题和链接。"

        # 明确让你上网搜/看热搜：只在这类请求里联网，普通聊天不触发
        web_item = None
        if self.web is not None and not video_query and not url and kind == "text":
            web_ctx = await self.web.context(text)
            if web_ctx.get("kind"):
                if web_ctx.get("items"):
                    extra += (
                        web_ctx.get("text", "")
                        + "\n要求：用你自己的口气说一条你刚看到的，别逐条念，别写 URL；"
                        "链接会在最后自动附上。"
                    )
                    web_item = web_ctx["items"][0]
                else:
                    extra += "\n【你刚上网】没搜到能看的内容，直接说没搜到，别编。"

        intent_bias = ""
        self._turn_refraction_id = 0
        self._turn_refraction = {}
        core = getattr(self, "core", None)
        if core is not None and core.enabled:
            try:
                record = core.shadow_round(
                    Percept(
                        text=text or "",
                        kind=kind,
                        user_id=user_id,
                        ts=time.time(),
                        emotion=emotion,
                        meta={"image_note": image_note} if image_note else {},
                    ),
                    asleep=self.clock.is_asleep(),
                    gap_hours=(time.time() - prev_user_ts) / 3600 if prev_user_ts else 0.0,
                    outcome={"emotion": emotion, "text": text or ""},
                )
                self._turn_refraction_id = int((record or {}).get("refraction_id") or 0)
                self._turn_refraction = dict((record or {}).get("refraction") or {})
                intent_bias = core.intent_bias(record)
                if intent_bias:
                    log.info("BrainN 倾向：%s", intent_bias[:80])
                if record and float(record.get("latency_ms", 0) or 0) > 40:
                    log.warning("BrainN 一轮耗时 %.1fms", float(record.get("latency_ms", 0)))
            except Exception as exc:  # noqa: BLE001
                log.warning("BrainN 影子失败：%s", exc)

        refraction_note = str(self._turn_refraction.get("after") or "").strip()
        if refraction_note:
            situation += f" 你此刻的第一反应：{refraction_note}（这是你的读法，不是事实）"

        sticker_request = any(w in (text or "") for w in ("表情包", "斗图", "斗表情", "发个表情"))
        is_meme_image = kind == "image" and any(
            w in (image_note or "")
            for w in ("表情包", "梗", "搞笑", "笑死", "无语", "吃瓜", "可爱", "凝视", "呆滞")
        )
        if kind == "image":
            sticker_request = random.random() < (0.85 if is_meme_image else 0.5)
        sticker_only = bool(sticker_request and len((text or "").strip()) <= 12 and random.random() < 0.6)
        if is_meme_image:
            sticker_only = random.random() < 0.75
        elif kind == "image":
            sticker_only = bool(sticker_request and random.random() < 0.35)
        if str(emotion.get("label")) in ("sad", "angry", "anxious") and float(emotion.get("intensity", 0)) >= 0.6:
            sticker_request = False
            sticker_only = False

        # 热梗命中：他说了当下流行的梗/缩写。他情绪明显负面时不接梗（上面已关掉 sticker_request）。
        _text_lower = (text or "").lower()
        meme_hit = (
            bool(_text_lower)
            and str(emotion.get("label")) not in ("sad", "angry", "anxious")
            and any(w in _text_lower for w in MEME_WORDS)
        )

        # 任务分流（明确要视频时优先走视频流程）
        intent = self.tasks.detect(text or "")
        if intent.is_task and not video_query:
            return await self._handle_task(
                intent, weather, weather_line, weather_hint, memories, extra, situation
            )

        system = build_system(
            self._prompt_persona(),
            self.persona,
            self.mood,
            self.clock.date_line(),
            f"{weather_line}。{weather_hint}",
            memories,
            situation=situation,
            extra=extra,
            social_text=self.social.context_for_prompt(),
            meaning_text=self.meaning.context_for_prompt(),
            self_text=self.self_model.context_for_prompt(),
            body_text=self.body.describe(),
            intent_bias=intent_bias,
            perception_text=self._perception_text(),
        )
        messages = self._dialogue()
        result = await self.llm.chat_json(system, messages)
        plan = await self._finish(
            result,
            weather_line,
            force_video=bool(video),
            preset_video=video,
            force_sticker=sticker_request,
            sticker_only=sticker_only,
            meme_hit=meme_hit,
            user_emotion=emotion,
            web_link=web_item,
            guard_ctx={
                "user_text": text or "",
                "avatar_changed": avatar_changed,
            },
        )
        if identity_question:
            self.self_model.note_answer([str(s) for s in plan.segments])
        return plan

    async def _handle_task(
        self,
        intent,
        weather,
        weather_line: str,
        weather_hint: str,
        memories: str,
        extra: str,
        situation: str,
    ) -> ReplyPlan:
        accepted = self.mood.should_accept_task(intent.effort)
        mood_extra = build_task_prompt(intent.text, accepted, intent.effort)
        if accepted:
            self.mood.on_task_accepted(intent.effort)
            tool = await self.tasks.execute(intent, weather)
            mood_extra += "\n【工具结果】" + tool.get("tool_result", "")
        system = build_system(
            self._prompt_persona(),
            self.persona,
            self.mood,
            self.clock.date_line(),
            f"{weather_line}。{weather_hint}",
            memories,
            situation=situation,
            extra=f"{extra}\n{mood_extra}",
            social_text=self.social.context_for_prompt(),
            meaning_text=self.meaning.context_for_prompt(),
            self_text=self.self_model.context_for_prompt(),
            body_text=self.body.describe(),
            perception_text=self._perception_text(),
        )
        result = await self.llm.chat_json(system, self._dialogue())
        self.store.set_state(
            "task_stats",
            {
                "last_kind": intent.kind,
                "last_effort": intent.effort,
                "last_accepted": accepted,
                "probability": round(self.mood.accept_probability(intent.effort), 3),
                "ts": time.time(),
            },
        )
        return await self._finish(
            result, weather_line, guard_ctx={"user_text": intent.text}
        )

    def _dialogue(self, drop_night: bool = False) -> list[dict[str, str]]:
        msgs = self.memory.recent_dialogue(28)
        if drop_night:
            night_words = ("昨晚", "昨天", "睡前", "早点躺", "收摊")
            msgs = [
                m for m in msgs
                if not any(w in str(m.get("content") or "") for w in night_words)
            ]
        return [{"role": m["role"], "content": m["content"][:400]} for m in msgs]

    @staticmethod
    def _is_close_signal(text: str, kind: str) -> bool:
        if kind != "text":
            return False
        raw = (text or "").strip()
        if not raw or len(raw) > 8:
            return False
        t = re.sub(r"[\s。！!~～，,、.…?？]+", "", raw.lower())
        return t in CLOSE_WORDS

    def _should_skip_low_value(self, text: str, kind: str) -> bool:
        """不是每句话都要回：纯句号、省略号、哈哈、晚安这类可以不接。"""
        if kind != "text":
            return False
        raw = str(text or "").strip()
        if not raw or len(raw) > 4:
            return False
        t = re.sub(r"[\s。！!~～，,、.…?？]+", "", raw.lower())
        if raw not in ("。", "…", "...") and t not in {"哈", "哈哈", "早", "晚安", "没事", "算了"}:
            return False
        if self.clock.is_asleep():
            chance = 0.8
        elif self.clock.is_busy() or self.body.unwell():
            chance = 0.6
        else:
            chance = float(self.settings.get("reply", {}).get("low_value_chance", 0.35))
        return random.random() < chance

    def _situation(self, text: str, kind: str, deferred: bool, prev_user_ts: float = 0.0) -> str:
        now = self.clock.now()
        activity_line = self._activity_line()
        if activity_line:
            lines = [activity_line]
        else:
            activity = random.choice(ACTIVITIES.get(self.clock.part_of_day(), ["在发呆"]))
            lines = [f"你现在：{activity}。"]
            if self.clock.is_busy():
                lines.append("你在上课，周围有人，回消息是偷偷回的，句子会比平时短。")
        affect = getattr(self, "affect", None)
        if affect is not None:
            hint = affect.hint_line()
            if hint:
                lines.append(hint)
            time_line = affect.time_line()
            if time_line:
                lines.append(time_line)
        thrownness = getattr(self, "thrownness", None)
        if thrownness is not None and any(
            word in (text or "")
            for word in ("家", "父母", "妈", "爸", "钱", "兼职", "外婆", "出身", "老家")
        ):
            lines.append(thrownness.expression_hint())
        user_model = getattr(self, "user_model", None)
        if user_model is not None:
            judgment_hint = user_model.prompt_hint()
            if judgment_hint:
                lines.append(judgment_hint)
        body_hint = self.body.dialogue_hint()
        if body_hint:
            lines.append(body_hint)
        fin_hint = finitude_hint(self.store)
        if fin_hint:
            lines.append(fin_hint)
        if self.clock.is_asleep():
            lines.append("这个点你本来该睡了，被手机震醒，有点迷糊、脾气也冲。")
        gap_min = (now.timestamp() - prev_user_ts) / 60 if prev_user_ts else 0
        if gap_min > 180:
            lines.append(f"他上次说话到现在隔了 {gap_min / 60:.1f} 小时，你等得有点烦，但看到他消息又没那么气了。")
        elif gap_min > 30:
            lines.append(f"隔了 {gap_min:.0f} 分钟他才回你，你有点在意。")
        short = (text or "").strip()
        if len(short) <= 2 and short in ("哦", "哦哦", "。。", "呵"):
            lines.append("他这句有点敷衍，你可以稍微刺他一句，但别真生气。")
        if kind == "image":
            lines.append("他发了张图片，你手机上看不清细节，别装看清了。")
        if deferred:
            lines.append("这条是他昨晚你睡着时发的，你刚醒才看到，要自然地解释一下。")
        return " ".join(lines)

    def _activity_line(self) -> str:
        """只给“结果”不给“劳动过程”：忙、累、麻木，而不是播报在加什么班。"""
        core = getattr(self, "core", None)
        if core is None or not core.enabled:
            return ""
        module = getattr(core, "modules", {}).get("practice")
        if module is None:
            return ""
        try:
            snap = module.snapshot()
        except Exception:  # noqa: BLE001
            return ""
        current = snap.get("current") or {}
        idle = snap.get("idle") or {}
        nxt = snap.get("next") or {}
        exam = snap.get("exam") or {}
        kind = str(current.get("kind") or "")
        title = str(current.get("title") or "手头的事")
        place = str(current.get("place") or "")
        if kind in ("work", "class", "study", "deadline"):
            if kind == "class":
                line = (
                    f"你现在在{place}上{title}，周围有人，回消息是偷空回的，句子会比平时短。"
                )
            elif kind == "deadline":
                line = f"你手头压着{title}这件必须今天弄完的事，心里有点急。"
            elif kind == "work":
                if place and place in title:
                    suffix = title.replace(place, "", 1)
                    where = f"{place}上{suffix}" if suffix else place
                else:
                    where = f"{place}{title}"
                line = (
                    f"你现在在{where}，手上正忙，回消息会慢；"
                    "被问起就照实说，别主动反复提。"
                )
            else:
                line = (
                    f"你现在在{place}{title}，手边是书和电脑，回消息像偷空；"
                    "被问起就照实说，别主动反复提。"
                )
            line += "（这是你现在的真实安排，只在你被问到时自然回答，不要主动播报，也别把一天的计划念出来。）"
        elif kind == "chore":
            line = f"你现在{current.get('title') or '做点杂事'}，没在忙正事。"
        elif idle and str(idle.get("kind") or "") != "sleep":
            line = f"你现在没课也没班，{idle.get('title') or '在自己待着'}。"
            if idle.get("place") and not str(idle.get("title") or "").startswith(
                ("在", "去", "下楼", "出去")
            ):
                line = f"你现在没课也没班，在{idle.get('place')}{idle.get('title')}。"
            if nxt and int(nxt.get("minutes_left") or 0) <= 120:
                line += "待会儿还有事，别聊太久。"
        elif str(idle.get("kind") or "") == "sleep":
            return ""
        else:
            line = "你现在空着，在自己待着的地方。"
            if nxt and int(nxt.get("minutes_left") or 0) <= 120:
                line += "待会儿还有事，别聊太久。"
        if exam:
            days = int(exam.get("days_left", 99))
            if 0 <= days <= 30:
                line += f"离考试还有 {days} 天，心里一直压着这事。"
        today = self.clock.now().date().isoformat()
        work_events = [
            event
            for event in snap.get("schedule") or []
            if str(event.get("date") or "") == today
            and str(event.get("kind") or "") == "work"
        ]
        if work_events:
            shifts = "、".join(
                f"{event.get('start')}-{event.get('end')}" for event in work_events
            )
            line += f"今天奶茶店班是 {shifts}，其余时间不在店里。"
        else:
            line += "今天没有奶茶店班，别从“周末兼职”自己补出班次。"
        line += "（真实安排优先于你之前说过的话；如果之前说岔了，被问起就承认说错，不要继续圆。）"
        alienation = float(snap.get("alienation") or 0)
        threshold = float((getattr(module, "cfg", {}) or {}).get("alienation_threshold", 0.65))
        if alienation >= threshold:
            line += "你最近对很多事有点麻，懒得解释，语气会冷一点，偶尔刺一句。"
        elif alienation >= threshold - 0.12:
            line += "你有点提不起劲，不太想多说。"
        if float(snap.get("fatigue") or 0) >= 70:
            line += "你身上发沉，脑子转得慢。"
        narrative = getattr(core, "modules", {}).get("narrative")
        if narrative is not None:
            try:
                reflection = str(narrative.snapshot().get("last_practice_reflection") or "")
            except Exception:  # noqa: BLE001
                reflection = ""
            if reflection:
                line += (
                    f"你事后给自己找的解释是「{reflection}」"
                    "——不用原话讲出来，它只是影响你现在的口气。"
                )
        return line

    def _needs_semantic_rewrite(self, raw: str) -> bool:
        """只有像在问旧事/问具体信息时才花钱改写，日常闲聊不调模型。"""
        text = str(raw or "").strip()
        if len(text) < 5 or not text:
            return False
        if not bool((self.settings.get("memory") or {}).get("semantic_rewrite", True)):
            return False
        if getattr(self.llm, "mock", False):
            return False
        return any(
            word in text
            for word in ("记得", "之前", "上次", "那天", "以前", "说过", "提过", "什么", "哪", "谁", "吗", "？", "?")
        )

    async def _semantic_rewrite(self, raw: str) -> str:
        """用一次很小的模型调用把问句改写成检索关键词；失败就退回规则改写。"""
        now = time.time()
        cached = self._rewrite_cache.get(raw)
        if cached and now - cached[0] < 7200:
            return cached[1]
        system = (
            "你是记忆检索查询改写器。把用户这句话改写成适合在长期记忆库里检索的中文关键词，"
            "只输出关键词，用空格分隔，最多 30 个字，不要解释、不要回答。"
            "保留人名、地点、食物、时间、承诺、身体状态等具体信息；如果只是寒暄就输出空。"
        )
        try:
            text = await asyncio.wait_for(
                self.llm.chat_text(system, raw, temperature=0, max_tokens=60),
                timeout=6,
            )
            text = re.sub(r"[\r\n]+", " ", str(text or "")).strip().strip("「」\"'")
            text = re.sub(r"^(关键词|检索词)[:：]\s*", "", text)[:60]
        except Exception as exc:  # noqa: BLE001
            log.debug("语义改写失败：%s", exc)
            text = ""
        self._rewrite_cache[raw] = (now, text)
        if len(self._rewrite_cache) > 200:
            oldest = sorted(self._rewrite_cache.items(), key=lambda x: x[1][0])[:50]
            for key, _ in oldest:
                self._rewrite_cache.pop(key, None)
        if text:
            log.info("记忆语义改写：%s → %s", raw[:20], text[:40])
        return text

    def _expand_memory_query(self, raw: str) -> str:
        extra: list[str] = []
        for keys, terms in _MEMORY_EXPANSIONS:
            if any(k in raw for k in keys):
                extra.append(terms)
        return " ".join(extra)

    def _detect_m9_tension(self, text: str) -> None:
        """M9：他明确纠正/否认时，保留旧说法与当前说法的张力，不急着覆盖。"""
        try:
            hit = detect_conflict(text, self._last_recall_items)
            if not hit:
                return
            threshold = float((self.settings.get("qt") or {}).get("m9_threshold", 10) or 10)
            self.store.bump_qt_tension(
                hit["a_ref"], hit["b_ref"], hit["topic"],
                delta=1.0, threshold=threshold, note=hit.get("note") or "",
            )
        except Exception:  # noqa: BLE001
            log.warning("M9 张力检测失败", exc_info=True)

    def _recall_for_prompt(self, text: str, semantic_query: str = "") -> str:
        """按相关性注入记忆：明确 cue 多取，普通消息只取高分；每 N 轮补一条核心记忆。"""
        cfg = self.settings.get("memory", {}) or {}
        raw = str(text or "")
        recent = [
            str(m.get("content") or "")
            for m in self.store.recent_messages(6)
            if m.get("role") == "user"
        ][-3:]
        cue = any(
            word in raw
            for word in (
                "上次", "之前", "那天", "你说过", "说过", "记得", "记不记得", "以前", "那次", "我说过", "提过"
            )
        )
        extra = self._expand_memory_query(raw)
        if semantic_query:
            extra = f"{extra} {semantic_query}".strip()
        context = " ".join(recent[-2:]) if recent else ""
        limit = int(cfg.get("explicit_limit", 4) if cue else cfg.get("ambient_limit", 2))
        threshold = float(
            cfg.get("explicit_min_score", 1.0) if cue else cfg.get("ambient_min_score", 0.55)
        )
        half_life = float(cfg.get("half_life_days", 30))
        floor = float(cfg.get("weight_floor", 0.1))

        def recall(query: str) -> list[tuple[float, dict]]:
            return self.memory.recall_scored(
                query,
                limit,
                require_overlap=True,
                # 只有明确问旧事才给原句加持；日常消息按普通词频算，免得虚词撞上来
                primary=raw if cue else "",
                min_matches=0 if cue else 2,
                half_life_days=half_life,
                weight_floor=floor,
                semantic_weight=float(cfg.get("semantic_weight", 0.35)),
            )

        # 先用“这句 + 同义词扩展”检索；没撞上关键词的记忆一律不注入
        scored = recall(f"{raw} {extra}".strip())
        items = [m for score, m in scored if score >= threshold]
        # 只有指代不清的短句（“那个呢”）或明确问旧事却查不到时，才用最近对话补查
        if not items and context and (cue or len(raw) <= 5):
            scored = recall(f"{raw} {extra} {context}".strip())
            items = [m for score, m in scored if score >= threshold]
        # 日常聊天别整轮空着：分数不够也留一条最相关的兜底
        if not items and not cue and scored and scored[0][0] >= threshold * 0.6:
            items = [scored[0][1]]

        turn = int(self.store.get_state("memory_turn") or 0) + 1
        self.store.set_state("memory_turn", turn)
        every = max(1, int(cfg.get("core_every_turns", 8)))
        if turn % every == 0:
            core = self.memory.core_memory()
            if core and core.get("id") not in {m.get("id") for m in items}:
                items.append(core)

        if not items:
            # 没有相关旧记忆也把主线/最近几天带上，别让她像断片
            self._last_recall_items = []
            return self.memory.format_items([])
        self._last_recall_items = list(items)
        self.memory.note_hits([int(m["id"]) for m in items])
        if cue:
            # 明确问旧事时，顺着记忆图谱再补 1~2 条关联记忆
            direct = [int(m["id"]) for m in items]
            items.extend(self.memory.related_items(direct, 2, exclude=direct))
        return self.memory.format_items(items)

    async def _maybe_change_avatar(self, text: str, image_path: str) -> tuple[bool, str]:
        """他发图并明确说换头像/情头时，真的调用一次换头像。"""
        if self.avatar_setter is None or not image_path:
            return False, ""
        raw = str(text or "")
        if not any(word in raw for word in ("头像", "情头", "换这个", "换成这个")):
            return False, ""
        try:
            resp = await self.avatar_setter(image_path)
        except Exception as exc:  # noqa: BLE001
            log.warning("按他发的图换头像失败：%s", exc)
            return False, "换头像失败了，别跟他说已经换了。"
        ok = (
            isinstance(resp, dict)
            and resp.get("status") != "failed"
            and resp.get("retcode") in (0, None)
        )
        if not ok:
            log.warning("换头像接口返回失败：%s", resp)
            return False, "换头像失败了，别跟他说已经换了。"
        self.store.set_state("last_avatar_action_ts", time.time())
        log.info("已按他发的图换头像：%s", image_path)
        return True, "系统已经真的把QQ头像换成他刚发的这张图，你可以直接说换了，别编别的。"

    def _perception_text(self) -> str:
        """P3 感知模块给表达系统的短印象；关闭或出错时静默为空。"""
        core = getattr(self, "core", None)
        if core is None or not core.enabled:
            return ""
        module = getattr(core, "modules", {}).get("perception")
        if module is None:
            return ""
        try:
            return module.context_for_prompt()
        except Exception:  # noqa: BLE001
            return ""

    async def _content_extra(self, kind: str, url: str | None, image_note: str = "") -> str:
        """他转发链接/视频/图片时，先联网把内容读出来，再让她评价。"""
        if kind == "image":
            if image_note:
                return (
                    f"\n【他刚发了一张图片/表情包】你已经看清了，内容：{image_note}"
                    "\n要求：像真人看到图一样直接反应——可以接梗、吐槽、问他哪来的、发个表情回应；"
                    "不要复述这段描述，不要说看不清。"
                )
            return (
                "\n【他刚发了一张图片】你这边没解析成功，别装看清了。"
                "可以问\"这啥啊\"、让他说重点，或先吐槽一句再问。"
            )
        if not url:
            return ""
        ctx = await self.media.link_context(url)
        title = ctx.get("title", "")
        desc = ctx.get("desc", "")
        body = ctx.get("text", "")
        author = ctx.get("author", "")
        if title or desc or body:
            parts = [f"标题：{title}" if title else ""]
            if author:
                parts.append(f"来源/UP主：{author}")
            if desc:
                parts.append(f"简介：{desc}")
            if body:
                parts.append(f"正文摘录：{body[:500]}")
            kind_word = "视频" if ctx.get("kind") == "video" else "网页内容"
            return (
                f"\n【他刚转发了一个{kind_word}】" + "；".join(p for p in parts if p)
                + "\n要求：你已经看过了，直接给评价——先表态（喜欢/没意思/想吐槽），再给理由，可以顺着你自己的口味挑刺。"
                "不要复述标题，不要总结成要点，不要像客服说\"感谢分享\"。"
            )
        return (
            "\n【他刚转发了一个链接】页面没抓到内容，你打不开。"
            "别装看过，可以问\"这啥啊\"、让他说重点，或先吐槽一句再问。"
        )

    # ------------------------------------------------------------------
    # 主动开口 / 提醒
    # ------------------------------------------------------------------
    async def proactive(self, topic: str) -> ReplyPlan | None:
        weather = await self.weather.get()
        weather_line = weather.line() if weather else ""
        weather_hint = weather.hint() if weather else ""
        hours = (time.time() - self.store.last_message_ts()) / 3600 if self.store.last_message_ts() else 0
        memories = self.memory.format_recall(topic)
        extra = build_proactive_prompt(topic, weather_line, hours)
        if hours >= 3:
            extra += (
                f"\n\n时间断点：现在是 {self.clock.date_line()}，距离上次聊天已经 {hours:.1f} 小时。"
                "之前那段对话（包括他睡前说的话）已经过去了，不要接着回，也不要回答那句；"
                "把这次当成重新开口，说你此刻在做什么，或者问他现在的情况。"
            )
            dialogue: list[dict[str, str]] = []
        else:
            dialogue = self._dialogue(drop_night=hours >= 1.0)
        try:
            life_text = self.life.context_for_prompt()
            if life_text:
                extra += "\n\n" + life_text
        except Exception:  # noqa: BLE001
            pass
        force_video = "视频" in topic
        video = None
        if force_video:
            video = await self.media.pick_video()
            if video:
                extra += f"\n\n你刚刷到：{video['title']}（{video['author']}）。回复里自然提一句，链接系统会自动带上。"

        web_item = None
        if not force_video and self.web is not None:
            web_item = await self.web.pick_for_proactive(topic)
            if web_item:
                extra += (
                    f"\n\n你刚在网上看到：{web_item.get('title', '')}"
                    f"（{web_item.get('source', '网上')}）。"
                    "回复里自然提一句你的感受，别写 URL，链接系统会自动带上。"
                )
        system = build_system(
            self._prompt_persona(),
            self.persona,
            self.mood,
            self.clock.date_line(),
            f"{weather_line}。{weather_hint}",
            memories,
            situation="你现在没有在等他回消息，是你自己想找他。",
            extra=extra,
            social_text=self.social.context_for_prompt(),
            meaning_text=self.meaning.context_for_prompt(),
            self_text=self.self_model.context_for_prompt(),
            body_text=self.body.describe(),
            perception_text=self._perception_text(),
        )
        messages = dialogue + [{"role": "user", "content": "（他还没说话，你想主动找他）"}]
        result = await self.llm.chat_json(system, messages)
        plan = await self._finish(
            result,
            weather_line,
            proactive_topic=topic,
            force_video=force_video and bool(video),
            preset_video=video,
            web_link=web_item,
            guard_ctx={"user_text": ""},
        )
        text = " ".join(str(s) for s in result.get("segments", []) if s)
        self.store.log_proactive(topic, text)
        return plan

    async def decide_m14(self, tension_id: int) -> dict[str, Any]:
        """她自己判断一条 M14 反观提案要不要写进自我节点。"""
        core = self.core
        shadow = getattr(core, "shadow", None) if core is not None else None
        practice = getattr(shadow, "practice", None) if shadow is not None else None
        if practice is None:
            return {"ok": False, "error": "no_runtime"}
        tension = self.store.qt_tension(int(tension_id))
        if not tension or str(tension.get("status") or "") != "pending":
            return {"ok": False, "error": "not_pending"}
        try:
            proposal = json.loads(tension.get("meta") or "{}")
        except (TypeError, ValueError):
            proposal = {}
        try:
            self_worth = float(self.meaning.state.get("self_worth", 62))
        except Exception:  # noqa: BLE001
            self_worth = 62.0
        mood_state = self.mood.state
        proposal_text = json.dumps(proposal, ensure_ascii=False)[:1200]
        system = (
            f"你是{self.persona_cfg.get('name') or '小鲸鱼'}。现在不是聊天，是你自己安静下来回想刚发生的事，"
            "决定要不要按这份提案改自己。\n"
            f"你的身份：{self.persona_cfg.get('identity') or ''}\n"
            f"你此刻：自我价值 {self_worth:.1f}｜心情 {float(getattr(mood_state, 'mood', 60)):.1f}"
            f"｜委屈 {float(getattr(mood_state, 'grievance', 0)):.1f}\n"
            f"昨天实践结算给你的提案：\n{proposal_text}\n\n"
            "判断原则：只有你真心认同、觉得它更像你现在的样子时才写进去；"
            "如果它只是别人期待你变成的样子、和你一贯的样子冲突、或者变化来得太突然，就不写。"
            "不要为了让他满意而接受。\n"
            '只输出 JSON：{"write": true 或 false, "reason": "用第一人称一句话说清为什么", '
            '"confidence": 0 到 1 的小数}'
        )
        messages = [{"role": "user", "content": "（你在心里过了一遍这份提案，决定要不要写进自己。）"}]
        try:
            result = await self.llm.chat_json(
                system, messages, temperature=0.5, max_tokens=400
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("M14 自主判断调用失败：%s", exc)
            return {"ok": False, "error": "llm_failed"}
        write = result.get("write")
        if not isinstance(write, bool):
            write = str(write or "").strip().lower() in ("true", "1", "yes", "是", "写入", "接受", "apply")
        try:
            confidence = float(result.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.0
        reason = str(result.get("reason") or "").strip()[:200]
        if write and confidence >= 0.5:
            changed = practice.confirm_writeback(
                int(tension_id),
                mood=self.mood,
                meaning=self.meaning,
                persona=self.persona,
                social=self.social,
                drives=getattr(shadow, "drives", None),
                reason=reason or "我自己想清楚了",
            )
            log.info("M14 自主判断：写入｜%s", reason or "我自己想清楚了")
            return {"ok": True, "decision": "write", "changed": changed}
        practice.reject_writeback(
            int(tension_id), reason or "这次先不动，保留原来的样子"
        )
        log.info("M14 自主判断：没同意｜%s", reason or "这次先不动")
        return {"ok": True, "decision": "reject"}

    async def send_reminder(self, content: str) -> ReplyPlan:
        weather = await self.weather.get()
        weather_line = weather.line() if weather else ""
        system = build_system(
            self._prompt_persona(),
            self.persona,
            self.mood,
            self.clock.date_line(),
            weather_line,
            self.memory.format_recall(content, 4),
            situation="你之前答应提醒他一件事，现在时间到了。",
            extra=f"要提醒的事：{content}。用女朋友的口吻提醒，像随口一句，不要像闹钟通知，不要念日期格式。",
            social_text=self.social.context_for_prompt(),
            meaning_text=self.meaning.context_for_prompt(),
            self_text=self.self_model.context_for_prompt(),
            body_text=self.body.describe(),
        )
        result = await self.llm.chat_json(system, self._dialogue() + [{"role": "user", "content": "（提醒时间到了）"}])
        return await self._finish(result, weather_line)

    async def review_ask(self, item: dict[str, Any]) -> ReplyPlan | None:
        """提取练习：就一条到期记忆主动提问，而不是复述。"""
        weather = await self.weather.get()
        weather_line = weather.line() if weather else ""
        fact = str(item.get("value") or "")[:80]
        if not fact:
            return None
        extra = build_review_prompt(
            fact,
            str(item.get("interpretation") or "")[:80],
            str(item.get("code") or ""),
            str(item.get("emotion") or ""),
        )
        system = build_system(
            self._prompt_persona(),
            self.persona,
            self.mood,
            self.clock.date_line(),
            weather_line,
            self.memory.format_recall(str(item.get("key") or fact), 4),
            situation="你突然想起一件以前的事，想顺口问问他。",
            extra=extra,
            social_text=self.social.context_for_prompt(),
            meaning_text=self.meaning.context_for_prompt(),
            self_text=self.self_model.context_for_prompt(),
            body_text=self.body.describe(),
        )
        result = await self.llm.chat_json(
            system, self._dialogue() + [{"role": "user", "content": "（你想起了以前的一件事，想问他）"}]
        )
        return await self._finish(result, weather_line, proactive_topic="记忆回访")

    # ------------------------------------------------------------------
    # 结果落地
    # ------------------------------------------------------------------
    async def _finish(
        self,
        result: dict[str, Any],
        weather_line: str,
        *,
        proactive_topic: str | None = None,
        force_video: bool = False,
        preset_video: dict[str, Any] | None = None,
        force_sticker: bool = False,
        sticker_only: bool = False,
        meme_hit: bool = False,
        user_emotion: dict[str, Any] | None = None,
        web_link: dict[str, Any] | None = None,
        guard_ctx: dict[str, Any] | None = None,
    ) -> ReplyPlan:
        self._apply_delta(result.get("mood_delta") or {})
        facts = result.get("memory")
        if not isinstance(facts, list):
            if facts:
                log.warning("memory 字段格式异常：%s", type(facts).__name__)
            facts = []
        if not facts:
            # 模型这轮没给记忆时，用规则兜底抓他明确说出的个人信息
            facts = self.memory.rule_facts(str((guard_ctx or {}).get("user_text") or ""))
        if facts:
            refraction_read = str(self._turn_refraction.get("after") or "").strip()
            if refraction_read:
                for fact in facts:
                    if isinstance(fact, dict) and not str(fact.get("interpretation") or "").strip():
                        fact["interpretation"] = refraction_read[:200]
            # 一律按 chat 记账，别把“记忆回访/热梗”这类话题名写成 source
            added = self.memory.add_facts(
                facts, source="chat", refraction_id=int(self._turn_refraction_id or 0)
            )
            if added:
                log.info("写入长期记忆 %d 条", added)

        segments = self._sanitize(result.get("segments"))
        sticker_tag = result.get("sticker") or self._sticker_tag_in_text(result.get("segments"))
        if force_sticker and not sticker_tag:
            sticker_tag = random.choice(["tease", "laugh", "confused", "proud", "speechless"])
        # 接梗：他抛了热梗而模型没给表情包时，一半概率替她补一个应景的
        if meme_hit and not sticker_tag and random.random() < 0.5:
            sticker_tag = random.choice(["laugh", "tease", "speechless", "popcorn", "proud"])
        # 主动消息的"热梗"话题：她想给他讲梗时，大概率顺手甩个应景表情包
        if proactive_topic and "梗" in str(proactive_topic) and not sticker_tag and random.random() < 0.6:
            sticker_tag = random.choice(["laugh", "tease", "speechless", "popcorn"])
        if sticker_only:
            segments = []
            sticker_tag = sticker_tag or random.choice(["tease", "laugh", "confused", "proud"])
        ctx = guard_ctx or {}
        segments, sticker_tag = self._guard_reply(segments, sticker_tag, ctx)
        segments = self._polish_style(segments)
        segments = self._match_user_length(segments, str(ctx.get("user_text") or ""))
        if self.body.unwell():
            segments = segments[:2]
        rate = self.mood.sticker_probability(float(self.persona.get("sticker_rate", 0.55)))
        if (
            user_emotion
            and str(user_emotion.get("label")) in ("sad", "angry", "anxious", "tired")
            and float(user_emotion.get("intensity", 0) or 0) >= 0.6
        ):
            rate *= 0.35
        if self.body.unwell():
            rate *= 0.5
        send_sticker = bool(sticker_tag) and (
            sticker_only or force_sticker or meme_hit or random.random() < min(0.95, rate)
        )
        face_id: str | None = None
        sticker: str | None = None
        if send_sticker:
            if self.allow_qq_face and random.random() < 0.2:
                face_id = self.stickers.face_id(sticker_tag)
            else:
                picked = self.stickers.pick(sticker_tag)
                if not picked:
                    await self.stickers.ensure_online(sticker_tag, 1)
                    picked = self.stickers.pick(sticker_tag)
                sticker = sticker_tag if picked else None
        if not segments and not send_sticker:
            segments = ["嗯？"]
        emoji_cfg = self.settings.get("emoji", {})
        last_emoji = float(self.store.get_state("last_emoji_ts") or 0)
        emoji_ready = time.time() - last_emoji >= 1800
        if (
            segments
            and emoji_ready
            and not self.body.unwell()
            and not self.clock.is_busy()
            and random.random() < float(emoji_cfg.get("chance", 0.10))
        ):
            tag = sticker_tag or ("happy" if self.mood.state.mood >= 60 else "tease")
            if (
                user_emotion
                and str(user_emotion.get("label")) in ("sad", "angry", "anxious", "tired")
                and float(user_emotion.get("intensity", 0) or 0) >= 0.6
            ):
                tag = "care" if str(user_emotion.get("label")) != "angry" else "aggrieved"
            count = 1 + (
                1
                if random.random() < 0.25 and int(emoji_cfg.get("max", 2)) > 1
                else 0
            )
            picks: list[str] = []
            for _ in range(count):
                e = pick_emoji(tag)
                if e and e not in picks:
                    picks.append(e)
            if picks:
                idx = random.randrange(len(segments))
                segments[idx] = segments[idx].rstrip() + "".join(picks)
                self.store.set_state("last_emoji_ts", time.time())

        try:
            if segments:
                self.life.observe_her(" ".join(segments))
        except Exception:  # noqa: BLE001
            pass

        plan = self.timing.build(
            segments,
            sticker=sticker,
            faces=[face_id] if face_id else None,
            busy=self.clock.is_busy(),
            asleep=self.clock.is_asleep(),
            sanity=self.mood.state.sanity,
            energy=self.mood.state.energy,
            first_delay=random.uniform(5.0, 12.0) if proactive_topic else None,
        )
        # 视频分享
        video_added = False
        want_video = bool(result.get("share_video")) or force_video
        if want_video and (force_video or random.random() < self.media.share_rate):
            video = preset_video or await self.media.pick_video()
            if video:
                plan.segments.append(OutSegment("link", video, random.uniform(1.2, 3.5)))
                video_added = True

        # 网上冲浪/搜索到的那条链接，只附一条，避免刷屏
        if web_link and not video_added:
            url = str(web_link.get("url") or "")
            title = str(web_link.get("title") or "")
            if url:
                plan.segments.append(
                    OutSegment(
                        "link",
                        {"title": title or url, "url": url},
                        random.uniform(1.2, 3.0),
                    )
                )

        # 发完后悔：按概率撤回最后一条，并补一句话
        recall_cfg = self.settings.get("reply", {}).get("recall", {})
        if result.get("recall") and recall_cfg.get("enabled", True) and (segments or send_sticker):
            last_ts = float(self.store.get_state("last_recall_ts") or 0)
            cooldown = float(recall_cfg.get("cooldown_minutes", 8)) * 60
            if time.time() - last_ts >= cooldown and random.random() < float(
                recall_cfg.get("chance", 0.65)
            ):
                plan.recall = {
                    "delay": random.uniform(*recall_cfg.get("delay", [8, 45])),
                    "reason": str(result.get("recall_reason", ""))[:60],
                }
                self.store.set_state("last_recall_ts", time.time())

        text = " ".join(segments)
        if sticker:
            text += " [表情包]"
        core = getattr(self, "core", None)
        if core is not None:
            core.observe_expression(text)
        # 不再把多段回复合并成一条入库：合并会让刷新历史时变成长长一串，表情包也会丢。
        # 现在由 chat_engine.deliver 按段分别落库（文字一条、表情包一条），历史能逐条还原。
        self.mood.save()
        # 全量记忆：留一份这一轮的心智快照（只写文件，不影响检索）
        fm = getattr(self, "full_memory", None)
        if fm is not None:
            try:
                fm.capture_turn(
                    self.mood.state.snapshot(),
                    self.body.status(),
                    getattr(self.persona, "cfg", None),
                    self.persona.knobs(),
                )
            except Exception:  # noqa: BLE001
                log.warning("全量记忆心智快照失败", exc_info=True)
        return plan

    def _apply_delta(self, delta: dict[str, Any]) -> None:
        st = self.mood.state

        def num(key: str) -> float:
            try:
                return float(delta.get(key, 0) or 0)
            except (TypeError, ValueError):
                return 0.0

        st.mood = max(0.0, min(100.0, st.mood + max(-10, min(10, num("mood")))))
        st.affection = max(0.0, min(100.0, st.affection + max(-5, min(5, num("affection")))))
        st.grievance = max(0.0, min(100.0, st.grievance + max(-15, min(15, num("grievance")))))
        st.jealousy = max(0.0, min(100.0, st.jealousy + max(-15, min(15, num("jealousy")))))
        st.sanity = max(0.0, min(100.0, st.sanity + max(-8, min(8, num("sanity")))))

    def _sanitize(self, segments: Any) -> list[str]:
        if isinstance(segments, str):
            segments = [segments]
        if not isinstance(segments, list):
            segments = []
        forbidden = list(self.persona_cfg.get("speech", {}).get("forbidden_words", []))
        sloppiness = float(self.settings.get("reply", {}).get("punctuation_sloppiness", 0.55))
        out: list[str] = []
        for raw in segments:
            s = str(raw).replace("\u200b", "")
            s = re.sub(r"[\r\n]+", " ", s)
            s = re.sub(r"[ \t]{2,}", " ", s).strip().strip('"“”')
            s = re.sub(r"^小鲸鱼[:：]\s*", "", s)
            s = re.sub(r"[\[【(（]\s*(分享视频|视频链接|视频|链接|表情包|图片)\s*[\]】)）]", "", s)
            s = _STICKER_TEXT_RE.sub("", s)
            s = re.sub(r"https?://\S+", "", s)
            s = re.sub(r"\s{2,}", " ", s).strip()
            s = strip_emoji(s)
            if not s or any(w in s for w in forbidden):
                continue
            out.append(loosen(s, sloppiness))
        return out[:3]

    @staticmethod
    def _sticker_tag_in_text(segments: Any) -> str:
        """模型偶尔把表情包写成文字标签（如 [sticekr: aggrieved]），把 tag 捞回来，
        让它仍然真的发出表情包，而不是显示一串括号。"""
        if isinstance(segments, str):
            segments = [segments]
        if not isinstance(segments, list):
            return ""
        for s in segments:
            m = _STICKER_TEXT_RE.search(str(s))
            if m:
                return m.group(1).lower()
        return ""

    def _current_activity(self) -> dict[str, Any]:
        core = getattr(self, "core", None)
        if core is None or not getattr(core, "enabled", False):
            return {}
        module = getattr(core, "modules", {}).get("practice")
        if module is None:
            return {}
        try:
            return module.snapshot().get("current") or {}
        except Exception:  # noqa: BLE001
            return {}

    def _guard_reply(
        self, segments: list[str], sticker_tag: str | None, ctx: dict[str, Any]
    ) -> tuple[list[str], str | None]:
        """拦住“说做过但其实没做”的动作声明，以及和实时日程冲突的回复。"""
        if not segments:
            return segments, sticker_tag
        text = " ".join(segments)
        user_text = str(ctx.get("user_text") or "")

        avatar_changed = bool(ctx.get("avatar_changed"))
        if not avatar_changed:
            state = self.store.get_state("avatar_state") or {}
            avatar_changed = time.time() - float(state.get("last_ts") or 0) < 86400

        honest = ""
        negatives = ("打不了", "不能打", "没法打", "没打", "拍不了", "没拍", "没照片", "不能拍", "没法拍", "加不了", "不能加", "没法加", "没加", "换不了", "没换", "不能换", "没法换")
        ask_call = any(w in user_text for w in ("电话", "叫我", "叫醒", "打电话"))
        if ask_call and any(p in text for p in ("我打", "我给你打", "准时", "行的我打", "行 我打")) and not any(n in text for n in negatives):
            honest = "电话打不了 你自己定个闹钟吧"
        ask_photo = any(w in user_text for w in ("照片", "拍照", "拍张", "看看你"))
        if not honest and ask_photo and any(p in text for p in ("我拍", "我给你拍", "我发你", "等我拍")) and not any(n in text for n in negatives):
            honest = "没拍 手机里没图"
        ask_avatar = any(w in user_text for w in ("头像", "情头")) and not avatar_changed
        if not honest and ask_avatar and any(p in text for p in ("我换", "换吧", "行，我换", "我这就换")) and not any(n in text for n in negatives):
            honest = "头像你发我一张 我看看"
        if (
            any(p in text for p in ("我打了电话", "我打过去", "我打过去了", "我就打过去", "打过去了", "我拨了", "电话我打了", "我七点零三分就打了", "我七点整"))
            or ("我" in text and "电话" in text and "打" in text)
        ) and not any(n in text for n in ("打不了", "不能打", "没法打", "没打")):
            honest = "打不了电话 手机不在手边 别等我了"
        photo_phrases = ("我拍了", "我拍好", "我发照片", "照片我发了", "我给你拍", "我拍张", "我拍照", "我发你照片")
        if not honest and any(p in text for p in photo_phrases) and not any(
            n in text for n in ("拍不了", "没拍", "没照片", "不能拍", "没法拍")
        ):
            honest = "没拍 手机里没图 别等我了"
        wechat_phrases = ("我加了", "我真加", "加你微信", "微信我加", "我加你")
        if not honest and any(p in text for p in wechat_phrases) and not any(
            n in text for n in ("加不了", "不能加", "没法加", "没加")
        ):
            honest = "微信加不了 就在这儿聊吧"
        avatar_context = any(w in text for w in ("头像", "情头")) or any(
            w in user_text for w in ("头像", "情头")
        )
        avatar_phrases = ("我换了", "换了呀", "刚点上", "我换好了", "头像我换了", "我换了头像")
        if (
            not honest
            and avatar_context
            and any(p in text for p in avatar_phrases)
            and not avatar_changed
            and not any(n in text for n in ("换不了", "没换", "不能换", "没法换"))
        ):
            honest = "头像啊 你帮我挑一张 我懒得换"
        if honest:
            log.info("拦截未发生的动作声明：%s", text[:60])
            return [honest], None

        current = self._current_activity()
        kind = str(current.get("kind") or "")
        forbidden = {
            "study": ("食堂", "下楼", "楼下", "床上", "宿舍", "外卖", "奶茶店", "店里", "回家", "躺着"),
            "work": ("图书馆", "宿舍", "床上", "回家", "躺着"),
            "class": ("宿舍", "床上", "图书馆", "店里", "楼下"),
            "sleep": ("在忙", "在外面", "店里", "图书馆", "上课"),
        }.get(kind)
        if (
            forbidden
            and any(word in text for word in forbidden)
            and not any(word in text for word in ("晚点", "等会儿", "下课", "下班", "结束", "之后"))
        ):
            template = {
                "study": "我还在图书馆复习呢，晚点再说",
                "work": "我还在店里忙着，晚点回你",
                "class": "我在上课呢，偷偷回你一句",
                "sleep": "我睡着呢，刚醒",
            }.get(kind, "我这边还忙着，晚点说")
            log.info("回复与当前日程冲突（%s），已替换：%s", kind, text[:60])
            return [template], None
        return segments, sticker_tag

    @staticmethod
    def _polish_style(segments: list[str]) -> list[str]:
        """把模型常见的客服腔换成更随口的说法。"""
        out: list[str] = []
        for raw in segments:
            s = str(raw)
            s = s.replace("我这边", "我")
            s = s.replace("我拍不了照片", "没拍照片")
            s = s.replace("我发不了照片", "没照片")
            s = s.replace("我换不了头像", "头像懒得换")
            s = s.replace("我打不了电话", "打不了电话")
            s = s.replace("我加不了微信", "微信加不了")
            s = s.strip()
            if s:
                out.append(s)
        return out or segments

    def _match_user_length(self, segments: list[str], user_text: str) -> list[str]:
        """他发得很短时，不让她写成小作文。"""
        if not segments:
            return segments
        text = str(user_text or "").strip()
        if len(text) > 10:
            return segments
        if any(q in text for q in ("?", "？", "吗", "咋", "怎么", "为什么", "啥", "哪", "谁", "多少", "几点", "安排")):
            return segments
        if len(" ".join(segments)) <= 26:
            return segments
        first = segments[0]
        if len(first) > 26:
            cuts = [
                m.start()
                for m in re.finditer(r"[。！？!?，,、]", first)
                if 10 <= m.start() <= 26
            ]
            first = first[: max(cuts) + 1] if cuts else first[:22] + "…"
        return [first]

    def _feed_activity_text(self) -> str:
        """最近 24 小时朋友圈互动：他点赞/评论，以及别人对他评论的回复。"""
        now = time.time()
        acts = self.store.recent_post_activity(now - 86400, 12)
        if not acts:
            return ""
        nodes = getattr(self.social, "nodes", {}) or {}
        lines: list[str] = []
        for item in acts[-6:]:
            stamp = time.strftime("%H:%M", time.localtime(float(item.get("ts") or now)))
            user = str(item.get("user") or "")
            text = str(item.get("text") or "").strip()[:60]
            if str(item.get("kind")) == "like":
                lines.append(f"- {stamp} 他给你的动态点了赞")
                continue
            post = str(self.store.dynamic_text(str(item.get("target") or "")) or "")[:28]
            where = f"（动态：{post}…）" if post else ""
            if user == "user":
                lines.append(f"- {stamp} 他在你的动态下评论{where}：{text}")
            elif user == "her":
                lines.append(f"- {stamp} 你回复了他的评论：{text}")
            else:
                name = str((nodes.get(user) or {}).get("name") or user)
                lines.append(f"- {stamp} {name} 回复了他的评论：{text}")
        if not lines:
            return ""
        return (
            "【最近朋友圈互动】\n"
            + "\n".join(lines)
            + "\n这些互动是真的；他提到朋友圈时你可以自然接一句，但别逐条复述，也别每轮都提。"
        )

    # ------------------------------------------------------------------
    # 自动动态
    # ------------------------------------------------------------------
    async def dynamic_post(self, topic: str) -> str:
        weather = await self.weather.get()
        weather_line = weather.line() if weather else ""
        weather_hint = weather.hint() if weather else ""
        current = self._current_activity()
        situation = "你现在想发一条QQ空间说说，不是回他消息。"
        if current:
            situation += (
                f" 你现在在{current.get('place') or '外面'}，"
                f"正在{current.get('title') or '做自己的事'}"
                f"（{current.get('start') or ''}-{current.get('end') or ''}）。"
                "说说要符合这个场景，不要写成另一个时间地点的事。"
            )
        try:
            life_text = self.life.context_for_prompt(include_dynamics=False)
            if life_text:
                situation += "\n" + life_text
        except Exception:  # noqa: BLE001
            pass
        system = build_system(
            self._prompt_persona(),
            self.persona,
            self.mood,
            self.clock.date_line(),
            f"{weather_line}。{weather_hint}",
            self.memory.format_recall(topic, 4),
            situation=situation,
            extra=(
                f"围绕「{topic}」写 1~2 句说说，像随手发的生活动态：可以是吐槽、感慨、分享吃的/看到的。"
                "系统会给这条说说配一张生活图，你不要描述图里具体有什么，只写当下的感受或小事。"
                "不要问句，不要提AI，不要写链接，不要像文案。只输出 JSON，格式同上。"
            ),
            social_text=self.social.context_for_prompt(),
            meaning_text=self.meaning.context_for_prompt(),
            self_text=self.self_model.context_for_prompt(),
            body_text=self.body.describe(),
        )
        result = await self.llm.chat_json(system, self._dialogue()[-12:] + [{"role": "user", "content": "（发一条说说）"}])
        segments = self._sanitize(result.get("segments"))
        text = " ".join(segments[:2]).strip()
        if not text:
            text = random.choice(["今天也要好好吃饭呀", "有点困，但还想再刷会儿手机", "突然想吃点甜的"])
        try:
            self.life.observe_dynamic(text)
        except Exception:  # noqa: BLE001
            pass
        return text[:300]

    # ------------------------------------------------------------------
    def status_text(self) -> str:
        self.body.tick(asleep=self.clock.is_asleep())
        self.body.apply_to_mood(self.mood)
        p = self.proactive_engine.params() if self.proactive_engine else self.proactive_view()
        task = self.store.get_state("task_stats") or {}
        emo = self.store.get_state("last_user_emotion") or {}
        emo_line = ""
        if emo:
            emo_line = f"\n他上次的情绪：{emo.get('label')}（强度 {emo.get('intensity')}）"
        task_line = ""
        if task:
            verdict = "答应了" if task.get("last_accepted") else "拒绝了"
            task_line = (
                f"\n上次任务：{verdict}（{task.get('last_kind')}，难度 {task.get('last_effort')}，"
                f"同意概率 {task.get('probability')}）"
            )
        stats = self.memory.mstore.memory_stats()
        layers = stats.get("layers", {})
        layer_line = "｜".join(
            f"{name} {layers.get(key, 0)}" for key, name in (("L2", "关系"), ("L3", "事件"), ("L4", "偏好"))
        )
        mainline = self.memory.mainline() or "（未定）"
        core = getattr(self, "core", None)
        core_line = ""
        if core is not None and core.enabled:
            mode = "影子" if core.shadow_enabled else "live"
            core_line = f"\nBrainN：{mode}｜模块 {len(core.modules)} 个"
        web_line = ""
        if self.web is not None:
            web_state = self.web.status()
            if web_state.get("enabled"):
                web_line = f"\n网上冲浪：最近 {web_state.get('count', 0)} 条"
                titles = web_state.get("titles") or []
                if titles:
                    web_line += f"（{titles[0]}）"
        extract = self.store.get_state("last_social_extract") or {}
        extract_line = ""
        if extract.get("changes") or extract.get("new_people"):
            bits = list(extract.get("changes") or [])[:2]
            if extract.get("new_people"):
                bits.append("新人：" + "、".join(extract["new_people"]))
            extract_line = f"\n关系学习：{'；'.join(bits)}"
        return (
            f"【小鲸鱼状态】\n"
            f"{self.mood.describe()}\n"
            f"天气：{(self.store.get_state('weather_cache') or {}).get('text', '未知')}\n"
            f"身体：{self.body.status()}\n"
            f"今日主动：{p.get('sent', 0)}/{p.get('quota', 0)} 条，剩余 {p.get('remaining', 0)}{task_line}\n"
            f"人格：{self.persona.summary()}\n"
            f"大脑：{self.llm.mode}\n"
            f"记忆条数：{len(self.memory.mstore.all_memories(999))}（{layer_line}｜已修正 {stats.get('revised', 0)}｜待回访 {stats.get('due_review', 0)}｜旧版本 {stats.get('versions', 0)}）\n"
            f"记忆主线：{mainline}{emo_line}{core_line}{web_line}\n"
            f"【社会关系】\n{self.social.status()}{extract_line}\n"
            f"【存在意义】\n{self.meaning.status()}"
        )

    def proactive_view(self) -> dict[str, Any]:
        return self.store.get_state("proactive_view") or {}
