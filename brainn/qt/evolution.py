"""M9 → M10 → M11 演化闭环。

- M9：认识张力累积；
- M10：累积到阈值，登记一次结构重组（不是简单条目 +1）；
- M11：把旧记忆提升为“两种说法并存”的新版本，写克服/保留/提升，旧版本永不删除。
"""
from __future__ import annotations

from typing import Any

from ..db import Store
from ..memory import Memory

class EvolutionModel:
    name = "evolution"

    def __init__(self, store: Store, memory: Memory, settings: dict[str, Any] | None = None):
        self.store = store
        self.memory = memory
        cfg = (settings or {}).get("qt") or {}
        self.threshold = float(cfg.get("m9_threshold", 10) or 10)
        self.last: list[dict[str, Any]] = []

    def evaluate(self) -> list[dict[str, Any]]:
        """每轮最多处理 5 条已达阈值的张力；返回本次扬弃结果。"""
        ready = self.store.qt_tensions_ready(self.threshold, limit=5)
        results: list[dict[str, Any]] = []
        for tension in ready:
            evolved = self.memory.evolve_tension(tension)
            tid = int(tension.get("id") or 0)
            if not evolved:
                self.store.set_qt_tension_status(
                    tid, "orphan", "张力没有对应记忆，保留原样，不再自动升级"
                )
                continue
            self.store.set_qt_tension_status(tid, "evolved", "M11 已扬弃")
            self.store.add_qt_transition(
                f"张力累积 {float(tension.get('accumulation') or 0):.1f}/{self.threshold:.0f}",
                f"结构重组：{evolved.get('topic')}",
                retained=str(evolved.get("kept") or "")[:200],
                reason="M9→M10→M11：累积过阈值，旧说法保留并提升",
                meta={
                    "tension_id": tid,
                    "memory_id": evolved.get("memory_id"),
                    "code": evolved.get("code"),
                    "overcame": evolved.get("overcame"),
                    "raised": str(evolved.get("raised") or "")[:200],
                },
            )
            results.append(evolved)
        self.last = results
        return results

    def snapshot(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"threshold": self.threshold, "last_evolved": len(self.last)}
