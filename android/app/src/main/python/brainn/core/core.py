"""BrainN Core 运行时骨架。

P2 只负责：模块注册、状态快照、开关。默认关闭，不影响现有表达系统。
"""
from __future__ import annotations

from typing import Any

from .contracts import Decision, Module, Percept

MODULE_NAMES = (
    "memory",
    "social",
    "body",
    "time",
    "perception",
    "drives",
    "conflict",
    "practice",
    "world",
    "unconscious",
    "narrative",
    "arbitration",
    "expression",
)

MODULE_LABELS = {
    "memory": "记忆库",
    "social": "社会关系神经网络",
    "body": "生理基础库",
    "time": "时间有限性",
    "perception": "对外感知框架",
    "drives": "驱动力模型",
    "conflict": "自我人格冲突",
    "practice": "实践黑箱",
    "world": "虚拟社会",
    "unconscious": "无意识黑箱",
    "narrative": "叙事自我重构",
    "arbitration": "仲裁中枢",
    "expression": "表达系统",
}

# 现有代码的临时映射；P3 替换为正式模块实现
LEGACY_IMPL = {
    "memory": "brainn.memory.Memory",
    "social": "brainn.social.SocialGraph",
    "body": "brainn.body.Body",
    "time": "brainn.clock.Clock",
    "perception": "brainn.emotion / brainn.media / brainn.weather / brainn.onebot",
    "drives": "brainn.meaning.Meaning / brainn.proactive.Proactive",
    "conflict": "brainn.persona.Persona / brainn.mood.Mood",
    "practice": "brainn.meaning.Meaning.daily_practice / brainn.social.SocialGraph.evolve_network",
    "unconscious": "（待实现）",
    "narrative": "brainn.memory + brainn.learner（待拆分）",
    "arbitration": "brainn.brain.Brain（待拆分）",
    "expression": "brainn.prompt / brainn.timing / brainn.stickers / brainn.onebot",
}


class BrainNCore:
    def __init__(self, settings: dict[str, Any]):
        cfg = settings.get("brainn", {}) or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.shadow_enabled = bool(cfg.get("shadow", True))
        self.modules: dict[str, Module] = {}
        self.round = 0
        self.shadow = None

    def bind_shadow(self, runtime) -> None:
        """装配 P3 影子运行时；是否调用由上层决定。"""
        self.shadow = runtime

    def shadow_round(self, percept: Percept, **kwargs):
        if self.shadow is None:
            return None
        return self.shadow.round(percept, **kwargs)

    def observe_expression(self, text: str) -> None:
        """让她从实际说出口的话里加固习惯；只在启用时生效。"""
        if not self.enabled or self.shadow is None:
            return
        self.shadow.unconscious.learn_from_expression(text)

    def intent_bias(self, record: dict[str, Any] | None) -> str:
        """把影子决策压成一句给表达系统的倾向提示。"""
        if not self.enabled or self.shadow_enabled or not record:
            return ""
        intent = str((record.get("action") or {}).get("intent") or "")
        if intent in ("", "do_nothing"):
            return ""
        labels = {
            "reach_out": "想主动找他",
            "maintain_relation": "维持现在的关系",
            "repair": "想修复关系",
            "rest": "想休息",
            "work": "想忙正事",
            "explore": "想看看新东西",
            "seek_recognition": "想被认可",
            "self_direct": "想自己做主",
            "protect_face": "想保住面子",
            "earn": "想赚点钱",
            "probe_user": "想问他一个关于他自己的问题",
        }
        distortion = record.get("distortion") or {}
        approach = float(distortion.get("approach", 0) or 0)
        tone = "偏软" if approach > 0.05 else "偏硬/收着" if approach < -0.05 else "正常"
        directness = float(distortion.get("directness", 0) or 0)
        bias = (
            f"本轮意图：{labels.get(intent, intent or '没有明确意图')}；"
            f"语气{tone}；直接度{directness:+.2f}。"
        )
        bypass = record.get("bypass") or {}
        if bypass.get("triggered"):
            bias += f" 可以带一点「{bypass.get('habit', '习惯')}」的口头习惯。"
        return bias

    def register(self, module: Module) -> None:
        if module.name not in MODULE_NAMES:
            raise ValueError(f"未知模块：{module.name}")
        if module.name in self.modules:
            raise ValueError(f"模块已注册：{module.name}")
        self.modules[module.name] = module

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "shadow_enabled": self.shadow_enabled,
            "shadow_bound": self.shadow is not None,
            "registered": sorted(self.modules),
            "missing": [n for n in MODULE_NAMES if n not in self.modules],
            "round": self.round,
        }

    def decide(self, percept: Percept, ctx: dict[str, Any] | None = None) -> Decision:
        """P2 占位：未启用时什么都不做，启用后由 P3 接入仲裁。"""
        if not self.enabled:
            return Decision(intent="do_nothing", rationale="brainn_disabled")
        return Decision(intent="do_nothing", rationale="brainn_skeleton")

    def tick(self, now: float, ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        events: list[dict[str, Any]] = []
        for module in self.modules.values():
            events.extend(module.tick(now, ctx or {}))
        self.round += 1
        return events
