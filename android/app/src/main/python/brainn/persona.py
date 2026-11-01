"""人格旋钮：可被自我学习微调，但受硬性边界保护。"""
from __future__ import annotations

import re
from typing import Any

from .db import Store

BOUNDS = {
    "talkativeness": (0.45, 1.75),
    "clinginess": (0.05, 1.0),
    "tease_level": (0.0, 1.0),
    "care_level": (0.3, 1.0),
    "sticker_rate": (0.0, 1.0),
    "proactive_bias": (0.1, 1.0),
    "cuteness": (0.3, 1.0),
}


def short_identity(identity: str, limit: int = 48) -> str:
    """从人设长身份里取一段能放进关系网/职业标签的短身份。"""
    text = re.sub(r"\s+", " ", str(identity or "")).strip()
    if not text:
        return ""
    for sep in ("：", ":"):
        if sep in text:
            text = text.rsplit(sep, 1)[-1].strip()
    parts = [p.strip() for p in re.split(r"[，,；;。]", text) if p.strip()]
    out = ""
    for part in parts[:4]:
        cand = part if not out else out + "，" + part
        if len(cand) > limit:
            break
        out = cand
        if any(k in part for k in ("兼职", "工作", "上班", "实习", "店员")):
            break
    return out or text[:limit]


class Persona:
    def __init__(self, store: Store, persona: dict[str, Any]):
        self.store = store
        self.cfg = persona
        self._base = dict(persona.get("editable_traits", {}))
        self._knobs = self._base | (store.get_state("persona_knobs") or {})

    def reload(self) -> None:
        """多个入口共用同一份人格旋钮时，从库里重新读一次。"""
        self._knobs = self._base | (self.store.get_state("persona_knobs") or {})

    @property
    def name(self) -> str:
        return self.cfg.get("name", "小鲸鱼")

    def knobs(self) -> dict[str, float]:
        return dict(self._knobs)

    def get(self, key: str, default: float = 0.5) -> float:
        return float(self._knobs.get(key, self._base.get(key, default)))

    def evolve(
        self,
        delta: dict[str, float],
        reason: str = "",
        day: str = "",
        force: bool = False,
    ) -> dict[str, float]:
        """按天微调；单次幅度受 evolution.max_knob_delta_per_day 限制，且不能越过边界。

        force=True 时即使当天没有可调项也留一条日记录，保证演化记录每天都有更新；
        同一天重复补跑会替换旧记录，不叠加。
        """
        max_delta = float(self.cfg.get("evolution", {}).get("max_knob_delta_per_day", 0.08))
        changed: dict[str, float] = {}
        for key, raw in (delta or {}).items():
            if key not in BOUNDS:
                continue
            try:
                step = max(-max_delta, min(max_delta, float(raw)))
            except (TypeError, ValueError):
                continue
            if abs(step) < 0.005:
                continue
            lo, hi = BOUNDS[key]
            new = max(lo, min(hi, float(self._knobs.get(key, self._base.get(key, 0.5))) + step))
            old = float(self._knobs.get(key, 0.5))
            if abs(new - old) < 1e-6:
                continue
            self._knobs[key] = round(new, 3)
            changed[key] = round(new - old, 3)
        if changed:
            self.store.set_state("persona_knobs", self._knobs)
        if changed or force:
            self.record_day(day, changed, reason)
        return changed

    def record_day(self, day: str, changed: dict[str, float] | None = None, reason: str = "") -> None:
        """只记一条人格日记录，不再重复应用旋钮变化。"""
        import time as _time

        now = _time.time()
        day = str(day or _time.strftime("%Y-%m-%d", _time.localtime(now)))
        history = [
            item for item in (self.store.get_state("persona_history") or [])
            if not (isinstance(item, dict) and str(item.get("day") or "") == day)
        ]
        history.append(
            {
                "ts": now,
                "day": day,
                "changed": dict(changed or {}),
                "reason": (reason or "")[:300],
            }
        )
        self.store.set_state("persona_history", history[-90:])

    def record_event(self, day: str, changed: dict[str, float] | None = None, reason: str = "") -> None:
        """应用人设等事件：追加一条，不覆盖当天的夜间复盘记录。"""
        import time as _time

        history = list(self.store.get_state("persona_history") or [])
        history.append(
            {
                "ts": _time.time(),
                "day": str(day or _time.strftime("%Y-%m-%d")),
                "kind": "apply",
                "changed": dict(changed or {}),
                "reason": (reason or "")[:300],
            }
        )
        self.store.set_state("persona_history", history[-90:])

    def summary(self) -> str:
        k = self.knobs()
        return (
            f"话多程度 {k.get('talkativeness', 1):.2f}｜粘人 {k.get('clinginess', .55):.2f}｜"
            f"损人 {k.get('tease_level', .6):.2f}｜关心 {k.get('care_level', .85):.2f}｜"
            f"表情包 {k.get('sticker_rate', .55):.2f}｜主动倾向 {k.get('proactive_bias', .6):.2f}｜"
            f"可爱 {k.get('cuteness', .8):.2f}"
        )
