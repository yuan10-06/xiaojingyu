"""BrainN · 启动入口（小鲸鱼人格）。

用法：
  python main.py --check      检查配置、依赖、天气与 NapCat 连通性
  python main.py --sim        终端模拟聊天（不连 QQ）
  python main.py              连接 NapCat 跑真实 QQ
  python main.py --sim --real-time   模拟聊天但按真实延迟等待
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import platform
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from brainn.affect import AffectField
from brainn.body import Body
from brainn.brain import Brain
from brainn.clock import Clock
from brainn.config import Config, load_config
from brainn.core.core import BrainNCore
from brainn.core.runtime import ShadowRuntime
from brainn.db import Store
from brainn.full_memory import FullMemory
from brainn.learner import Learner
from brainn.llm import LLM
from brainn.meaning import Meaning
from brainn.media import Media
from brainn.memory import Memory
from brainn.mood import Mood
from brainn.onebot import OneBotAdapter
from brainn.persona import Persona, short_identity
from brainn.practical_intuition import PracticalIntuition
from brainn.proactive import Proactive
from brainn.scheduler import Scheduler
from brainn.sim import SimAdapter
from brainn.social import SocialGraph
from brainn.stickers import Stickers
from brainn.tasks import Tasks
from brainn.thrownness import Thrownness
from brainn.user_model import UserModel
from brainn.timing import Timing
from brainn.weather import WeatherService
from brainn.web import WebSurf

log = logging.getLogger("brainn")


def _migrate_stale_life(settings: dict) -> None:
    """换过人设后，把旧专业写死的课表标题换成通用说法，避免身份和课表对不上。"""
    weekly = ((settings.get("life") or {}).get("weekly") or {})
    changed = 0
    for items in weekly.values():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, list) or len(item) < 4:
                continue
            title = str(item[3] or "")
            if "食品" not in title:
                continue
            kind = str(item[2] or "")
            if "期" in title or "考试" in title:
                item[3] = "专业课考试"
            elif kind == "class":
                item[3] = "上课"
            elif kind == "study":
                item[3] = "复习"
            elif kind == "deadline":
                item[3] = "交作业"
            else:
                item[3] = "专业课"
            changed += 1
    if changed:
        log.info("旧专业课程标题已迁移为通用课表：%d 条", changed)


def _retire_stale_identity_memories(mstore, label: str) -> None:
    """人设换了专业后，旧专业事实不再参与检索；承诺类只改掉过期的课程名。"""
    stale_terms = ("食品科学", "食品微生物", "食品化学", "食品营养", "食品工程")
    if any(term in str(label or "") for term in stale_terms):
        return
    try:
        memories = mstore.all_memories(400)
    except Exception:  # noqa: BLE001
        log.warning("读取旧身份记忆失败", exc_info=True)
        return
    replacements = (
        ("食品微生物学", "专业课"),
        ("食品化学实验", "专业课实验"),
        ("食品营养学", "专业课"),
        ("食品工程原理", "专业课"),
        ("食品化学", "专业课"),
        ("食品科学", "专业课"),
    )
    archived = updated = 0
    for m in memories:
        text = " ".join(
            str(m.get(k) or "") for k in ("key", "value", "interpretation")
        )
        if not any(term in text for term in stale_terms):
            continue
        mid = int(m.get("id") or 0)
        if not mid:
            continue
        kind = str(m.get("kind") or "")
        if kind in ("promise", "grudge"):
            value = str(m.get("value") or "")
            for old, new in replacements:
                value = value.replace(old, new)
            try:
                mstore.adjust_memory(mid, value=value)
                updated += 1
            except Exception:  # noqa: BLE001
                log.warning("修正旧专业承诺失败：%s", mid, exc_info=True)
        else:
            try:
                mstore.adjust_memory(mid, status="archived")
                archived += 1
            except Exception:  # noqa: BLE001
                log.warning("归档旧专业记忆失败：%s", mid, exc_info=True)
    if archived or updated:
        log.info("旧专业记忆清理：归档 %d 条，修正 %d 条", archived, updated)


class App:
    def __init__(self, config: Config):
        self.config = config
        settings = config.settings
        _migrate_stale_life(settings)
        self.core = BrainNCore(settings)
        self.store = Store(config.db_path)
        # 一次性清理 2D 与聊天双通道留下的近时重复消息（只删文本）
        try:
            if not self.store.get_state("messages_deduped_v1"):
                removed = self.store.dedupe_messages(5)
                self.store.set_state(
                    "messages_deduped_v1", {"at": time.time(), "removed": removed}
                )
                if removed:
                    log.info("清理重复消息 %d 条", removed)
        except Exception:  # noqa: BLE001
            log.warning("重复消息清理失败", exc_info=True)
        # 全量记忆（增援未来）：默认开启，只留档不改变检索与遗忘
        mem_settings = settings.get("memory") or {}
        full_on = bool(mem_settings.get("full", True))
        full_dir = str(mem_settings.get("full_dir") or "").strip()
        self.full_memory = FullMemory(config.data_dir, full_on, full_dir or None)
        self.store.archive_message = self.full_memory.on_message
        # 记忆库可以和运行状态库分开：小鲸鱼与主聊天共用一份记忆
        mem_path = config.memory_db_path
        if mem_path and mem_path != config.db_path:
            self.memory_store = Store(mem_path)
            self.memory = Memory(self.store, self.memory_store)
            log.info("记忆库共享：%s", mem_path)
        else:
            self.memory_store = self.store
            self.memory = Memory(self.store)
        if self.memory_store is not self.store:
            self.memory_store.archive_message = self.full_memory.on_message
        if full_on and not self.store.get_state("full_memory_backfilled_v1"):
            try:
                added = self.full_memory.backfill_messages(self.store.all_messages())
                self.store.set_state(
                    "full_memory_backfilled_v1", {"at": time.time(), "added": added}
                )
                if added:
                    log.info("全量记忆补历史：%d 条", added)
            except Exception:  # noqa: BLE001
                log.warning("全量记忆补历史失败", exc_info=True)
        # 旧版本的名字统一为小鲸鱼：人设已在配置层收口，这里清历史记忆和版本链
        try:
            if not self.store.get_state("name_unified_v1"):
                renamed = self.memory.mstore.rename_identity_terms()
                self.store.set_state(
                    "name_unified_v1", {"at": time.time(), "renamed": renamed}
                )
                if renamed:
                    log.info("旧名字记忆统一为小鲸鱼：%d 条", renamed)
        except Exception:  # noqa: BLE001
            log.warning("统一旧名字记忆失败", exc_info=True)
        self.mood = Mood(self.store, config.persona)
        self.body = Body(self.store, config.persona)
        self.persona = Persona(self.store, config.persona)
        self.social = SocialGraph(self.store)
        self.meaning = Meaning(self.store)
        self.llm = LLM(settings.get("llm", {}), config.deepseek_key)
        saved_model = str(self.store.get_state("llm_model") or "")
        if saved_model and self.llm.set_model(saved_model):
            log.info("模型切换沿用上次选择：%s", saved_model)
        self.clock = Clock(settings.get("timezone", "Asia/Shanghai"), settings.get("schedule", {}))
        thrown_path = config.root / "config" / "thrownness.yaml"
        thrown_data = {}
        if thrown_path.exists():
            thrown_data = yaml.safe_load(thrown_path.read_text(encoding="utf-8")) or {}
        threshold = float(
            (settings.get("brainn", {}).get("thrownness", {}) or {}).get(
                "big_shock_threshold", 0.8
            )
        )
        self.thrownness = Thrownness(self.store, thrown_data, threshold)
        self.affect = AffectField(
            self.store, settings, self.clock, self.social, self.thrownness
        )
        self.intuition = PracticalIntuition(self.store, settings)
        self.user_model = UserModel(self.store, settings)
        self.memory.set_affect(
            self.affect,
            float(
                (settings.get("brainn", {}).get("affect", {}) or {}).get(
                    "memory_bias", 0.8
                )
            ),
        )
        self.shadow = ShadowRuntime(
            self.store,
            settings,
            self.clock,
            self.body,
            self.social,
            self.memory,
            affect=self.affect,
            thrownness=self.thrownness,
            intuition=self.intuition,
            user_model=self.user_model,
            persona_cfg=config.persona,
        )
        self.core.bind_shadow(self.shadow)
        for module in self.shadow.modules():
            self.core.register(module)
        self.weather = WeatherService(self.store, settings.get("weather", {}))
        self.timing = Timing(settings.get("reply", {}))
        self.stickers = Stickers(config.sticker_dir)
        self.media = Media(self.store, config.persona.get("media", {}), config.data_dir)
        self.web = WebSurf(self.store, settings.get("web", {}), self.media)
        self.tasks = Tasks(self.store, config.persona.get("task_policy", {}), self.clock)
        self.learner = Learner(self.store, self.memory, self.persona, self.llm, self.social)
        self.brain = Brain(
            config,
            self.store,
            self.mood,
            self.memory,
            self.persona,
            self.llm,
            self.weather,
            self.clock,
            self.timing,
            self.stickers,
            self.media,
            self.tasks,
            self.learner,
            self.social,
            self.meaning,
            self.body,
            web=self.web,
        )
        self.proactive = Proactive(
            self.store, self.persona, self.clock, self.mood, config.persona.get("proactive", {})
        )
        self.brain.full_memory = self.full_memory
        self.brain.proactive_engine = self.proactive
        self.brain.core = self.core
        self.brain.affect = self.affect
        self.brain.thrownness = self.thrownness
        self.brain.user_model = self.user_model
        # 关系网“你自己”和实践职业跟随当前人设，避免旧专业残留
        label = short_identity(config.persona.get("identity") or "")
        if label:
            try:
                self.social.sync_self_role(label)
            except Exception:  # noqa: BLE001
                log.warning("同步关系网自我身份失败", exc_info=True)
            try:
                self.shadow.practice.set_identity_label(label)
            except Exception:  # noqa: BLE001
                log.warning("同步实践身份失败", exc_info=True)
            try:
                _retire_stale_identity_memories(self.memory.mstore, label)
            except Exception:  # noqa: BLE001
                log.warning("清理旧身份记忆失败", exc_info=True)
        if self.core.enabled and not self.core.shadow_enabled:
            weights = settings.get("brainn", {}).get("weights", {}) or {}
            self.memory.set_narrative_bias(
                self.shadow.narrative.bias, float(weights.get("narrative_bias", 0.2))
            )
        self.store.set_state("proactive_view", self.proactive.params())


def setup_logging(log_dir: Path) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_dir / "brainn.log", encoding="utf-8"),
        ],
    )


_LOCK_HANDLE = None


def acquire_instance_lock(path: Path):
    """Windows 文件锁：保证同一时间只有一个 QQ 模式实例，避免重复回复。"""
    global _LOCK_HANDLE
    handle = open(path, "a+", encoding="utf-8")
    try:
        handle.seek(0)
        if handle.read(1) == "":
            handle.write("1")
            handle.flush()
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        _LOCK_HANDLE = handle
        return handle
    except OSError:
        handle.close()
        return None


async def run_check(app: App) -> None:
    cfg = app.config
    print("=" * 56)
    print("BrainN · 环境自检（小鲸鱼人格）")
    print("=" * 56)
    print(f"Python      : {platform.python_version()} ({platform.system()})")
    print(f"人设        : {cfg.persona_name()} / {cfg.persona.get('city', '未设置')}")
    print(f"大脑        : {app.llm.mode}")
    print(f"DeepSeek Key: {'已配置' if cfg.deepseek_key else '未配置（会使用离线模拟大脑）'}")
    print(f"你的 QQ      : {cfg.owner_qq or '未配置（QQ 模式下必须填）'}")
    print(f"NapCat WS   : {cfg.onebot_ws}")
    print(f"表情包      : {sum(len(v) for v in app.stickers.manifest.values())} 张，{len(app.stickers.manifest)} 种情绪")
    print(f"数据库      : {cfg.db_path}")
    print(f"记忆条数    : {len(app.store.all_memories(999))}")
    print(f"当前情绪    : {app.mood.state.snapshot()}")
    print(f"当前身体    : {app.body.status()}")
    print(f"BrainN      : {'已启用' if app.core.enabled else '骨架未启用'}（模块 {len(app.core.modules)} 个）")
    if app.core.shadow is None:
        p3_mode = "未装配"
    elif not app.core.enabled:
        p3_mode = "已装配（未启用）"
    elif app.core.shadow_enabled:
        p3_mode = "影子里运行"
    else:
        p3_mode = "live 运行"
    print(f"P3 状态      : {p3_mode}")
    print("-" * 56)

    w = await app.weather.get(force=True)
    print(f"天气        : {w.line() + f'（心情 {w.delta:+.1f}）' if w else '获取失败（检查网络）'}")

    if cfg.owner_qq:
        try:
            import websockets

            async with websockets.connect(cfg.onebot_ws, open_timeout=4):
                print("NapCat      : 连接成功")
        except Exception as exc:  # noqa: BLE001
            print(f"NapCat      : 未连接（{type(exc).__name__}）。请先启动 NapCat 并开启 OneBot11 反向 WS。")
    print("-" * 56)
    print("自检完成。")


async def run_sim(app: App, fast: bool) -> None:
    app.brain.allow_defer = False
    await SimAdapter(app.brain, fast=fast).run()


async def run_bot(app: App) -> None:
    cfg = app.config
    if not cfg.owner_qq:
        print("未配置 OWNER_QQ：请先在 .env 里填你的 QQ 号，否则她不会回复任何人。")
        return
    if acquire_instance_lock(cfg.data_dir / "bot.lock") is None:
        print("检测到已有小鲸鱼实例在运行，本次启动自动退出。")
        return
    # 让她在线期间电脑不进入睡眠，否则消息会积压到醒来
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
        except Exception:  # noqa: BLE001
            pass
    adapter = OneBotAdapter(app.brain, cfg.onebot_ws, cfg.onebot_token, cfg.owner_qq)
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
        adapter.send_plan,
        cfg.owner_qq,
        adapter.post_dynamic,
        adapter.set_avatar,
        web=app.web,
    )
    print(f"BrainN（小鲸鱼）已启动｜{app.llm.mode}｜{'影子' if app.core.shadow_enabled else 'live'} 模式｜主人 QQ {cfg.owner_qq}")
    log.info("BrainN 模式：%s｜模块 %d 个", "影子" if app.core.shadow_enabled else "live", len(app.core.modules))
    print(f"私聊她即可；发送 /状态 查看情绪。NapCat: {cfg.onebot_ws}")
    await asyncio.gather(adapter.run(), scheduler.run())


def main() -> None:
    parser = argparse.ArgumentParser(description="小鲸鱼 · 虚拟女友智能体")
    parser.add_argument("--check", action="store_true", help="环境自检")
    parser.add_argument("--sim", action="store_true", help="终端模拟聊天")
    parser.add_argument("--real-time", action="store_true", help="模拟模式按真实延迟发送")
    args = parser.parse_args()

    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    config = load_config()
    setup_logging(config.log_dir)

    env_file = config.root / ".env"
    if not env_file.exists():
        env_file.write_text((config.root / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
        print("已生成 .env，请填入 DEEPSEEK_API_KEY 和 OWNER_QQ。\n")

    app = App(config)
    try:
        if args.check:
            asyncio.run(run_check(app))
        elif args.sim:
            asyncio.run(run_sim(app, fast=not args.real_time))
        else:
            asyncio.run(run_bot(app))
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
