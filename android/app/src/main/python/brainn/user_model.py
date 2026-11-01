"""用户模型：只有“他以为的你”，没有 ground truth。

角色可以误解、固执、被纠正后更新；系统不存用户的真实状态。
"""
from __future__ import annotations

import re
import time
from typing import Any

from .db import Store


EMPTY_PERCEPTION = {
    "labor_kind": None,
    "output_owner": None,
    "autonomy_guess": 0.5,
    "evaluators": [],
    "avoidance": None,
    "confidence": 0.55,
}

WORK_WORDS = ("上班", "工作", "打工", "兼职", "项目", "方案", "客户", "老板", "领导", "公司", "店里", "班")
AUTO_LOW = ("必须", "安排", "打卡", "考核", "要求", "加班", "老板", "领导", "客户", "规定")
AUTO_HIGH = ("自己决定", "自由", "想做", "不用", "我说了算", "自主")
EVALUATOR_WORDS = ("老板", "领导", "客户", "导师", "老师", "经理", "主管", "店长", "组长")
AVOID_WORDS = ("躲", "不想", "逃避", "拖", "烦", "应付", "敷衍")
CORRECTION_WORDS = ("你误会", "你猜错", "我不是老板", "我不是上班", "我没上班", "你别乱说", "哪有")


class UserModel:
    """挂在 M10 的结构性用户模型；只存 perceived。"""

    def __init__(self, store: Store, settings: dict[str, Any]):
        self.store = store
        cfg = (settings.get("brainn") or {}).get("recognition") or {}
        self.say_judgment = bool(cfg.get("say_judgment", True))
        self.confidence_bias = float(cfg.get("confidence_bias", 0.15))
        raw = store.get_state("brainn_user_model") or {}
        perceived = {**EMPTY_PERCEPTION, **(raw.get("perceived") or {})}
        perceived["evaluators"] = list(perceived.get("evaluators") or [])
        self.perceived = perceived
        raw_confidence = raw.get("confidence")
        if raw_confidence is None:
            # 人对“自己看懂了别人”的把握天然偏高，这个偏差不校准
            self.confidence = min(0.9, float(perceived.get("confidence", 0.55)) + self.confidence_bias)
        else:
            self.confidence = float(raw_confidence)
        self.revision_count = int(raw.get("revision_count") or 0)
        self.last_updated = float(raw.get("last_updated") or 0)
        self.save()

    # ---------- 观察：只从表面话里猜 ----------
    def observe(self, text: str, corrected: bool = False) -> dict[str, Any]:
        raw = str(text or "")
        if not raw:
            return self.snapshot()
        if corrected or any(word in raw for word in CORRECTION_WORDS):
            self.revision_count += 1
            self.confidence = max(0.35, self.confidence - 0.12)
            if any(word in raw for word in ("老板", "上班", "工作", "公司", "项目")):
                self.perceived["labor_kind"] = None
                self.perceived["output_owner"] = None
                self.perceived["autonomy_guess"] = 0.5
                self.perceived["evaluators"] = []
            self.save()
            return self.snapshot()
        self._infer(raw)
        self.save()
        return self.snapshot()

    def _infer(self, text: str) -> None:
        before = dict(self.perceived)
        if any(word in text for word in ("写方案", "项目", "PPT", "代码", "汇报")):
            self.perceived["labor_kind"] = "被安排的项目工作"
        elif any(word in text for word in ("上班", "打工", "兼职", "店里", "客户")):
            self.perceived["labor_kind"] = "服务/执行类工作"
        elif any(word in text for word in ("自己写", "我的项目", "自己做")):
            self.perceived["labor_kind"] = "自主创作"
        owner = None
        if any(word in text for word in ("老板", "领导", "客户", "公司", "导师", "老师")):
            owner = "老板/公司"
        elif any(word in text for word in ("自己的", "我自己", "归我")):
            owner = "自己"
        if owner:
            self.perceived["output_owner"] = owner
        if any(word in text for word in AUTO_LOW):
            self.perceived["autonomy_guess"] = max(0.05, float(self.perceived["autonomy_guess"]) - 0.08)
        elif any(word in text for word in AUTO_HIGH):
            self.perceived["autonomy_guess"] = min(0.95, float(self.perceived["autonomy_guess"]) + 0.08)
        evaluators = list(self.perceived.get("evaluators") or [])
        for word in EVALUATOR_WORDS:
            if word in text and word not in evaluators:
                evaluators.append(word)
        self.perceived["evaluators"] = evaluators[:6]
        for word in AVOID_WORDS:
            if word in text:
                self.perceived["avoidance"] = text[:80]
                break
        clues = sum(
            1
            for key in ("labor_kind", "output_owner", "avoidance")
            if self.perceived.get(key) != before.get(key)
        )
        if evaluators != before.get("evaluators"):
            clues += 1
        if clues:
            self.confidence = min(0.92, self.confidence + 0.03 * clues)
        else:
            self.confidence = max(0.35, self.confidence - 0.003)
        self.perceived["confidence"] = round(self.confidence, 3)
        self.last_updated = time.time()

    # ---------- 他自己的判断 ----------
    def judgment(self) -> str:
        if self.confidence < 0.55:
            return ""
        owner = str(self.perceived.get("output_owner") or "")
        evaluators = self.perceived.get("evaluators") or []
        autonomy = float(self.perceived.get("autonomy_guess") or 0.5)
        avoidance = self.perceived.get("avoidance")
        if owner and owner != "自己" and autonomy <= 0.45:
            return "你也在给别人白干。"
        if evaluators and autonomy <= 0.5:
            return "你也被别人评价着。"
        if avoidance:
            return "你好像在躲什么。"
        return ""

    def prompt_hint(self) -> str:
        judgment = self.judgment()
        if not judgment:
            return ""
        if self.say_judgment:
            return (
                f"你心里对他有个判断：{judgment} "
                "这轮别只顺着他说烦，用你自己的口气把这句话说出来，一条就够，"
                "不用解释成大道理，说完也不用等他同意。"
            )
        return f"你心里有个判断：{judgment} 但现在先收着，不一定说出口。"

    def perception_line(self) -> str:
        if self.confidence < 0.5:
            return ""
        labor = self.perceived.get("labor_kind") or "说不清在做什么"
        owner = self.perceived.get("output_owner") or "不清楚归谁"
        autonomy = float(self.perceived.get("autonomy_guess") or 0.5)
        if autonomy <= 0.4:
            auto = "他能自己决定的不多"
        elif autonomy >= 0.7:
            auto = "他比较能自己决定"
        else:
            auto = "他的自主度说不准"
        evaluators = "、".join(self.perceived.get("evaluators") or []) or "没看出谁在评价他"
        return f"你猜他现在：{labor}；产出可能归{owner}；{auto}；{evaluators}。"

    def structural_question(self) -> str:
        if not self.perceived.get("output_owner"):
            return "你做的那些，最后算谁的？"
        if abs(float(self.perceived.get("autonomy_guess", 0.5)) - 0.5) < 0.01:
            return "你能自己决定怎么安排吗？"
        if not self.perceived.get("evaluators"):
            return "谁在评价你？"
        if not self.perceived.get("avoidance"):
            return "你最近在躲什么？"
        return "你现在这套，是你自己选的吗？"

    # ---------- 持久化 ----------
    def save(self) -> None:
        self.store.set_state(
            "brainn_user_model",
            {
                "perceived": self.perceived,
                "confidence": round(float(self.confidence), 3),
                "revision_count": int(self.revision_count),
                "last_updated": float(self.last_updated or time.time()),
            },
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "perceived": dict(self.perceived),
            "confidence": round(float(self.confidence), 3),
            "revision_count": int(self.revision_count),
            "last_updated": self.last_updated,
        }
