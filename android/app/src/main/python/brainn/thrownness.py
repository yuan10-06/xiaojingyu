"""M13 被抛层：不可选择、不可撤销的起点。

事实在初始化后封存；只有显式的大冲击可以**追加**创伤，不能改写旧事实。
M5 可以重新解释这些事实，但事实本身不变。
"""
from __future__ import annotations

import hashlib
import json
import time
from types import MappingProxyType
from typing import Any

from .db import Store


class ImmutableError(Exception):
    """试图修改被抛层时抛出。"""


class Thrownness:
    def __init__(
        self,
        store: Store,
        data: dict[str, Any],
        big_shock_threshold: float = 0.8,
    ):
        self.store = store
        self.threshold = float(big_shock_threshold)
        object.__setattr__(self, "_sealed", False)
        self.origin = MappingProxyType(dict(data.get("origin") or {}))
        self.era = MappingProxyType(dict(data.get("era") or {}))
        self.mother_tongue = str(data.get("mother_tongue") or "河南话")
        self.body_given = MappingProxyType(dict(data.get("body_given") or {}))
        self.class_position = float(data.get("class_position", 0.30))
        self._childhood = [MappingProxyType(dict(item)) for item in (data.get("childhood") or [])]
        raw = store.get_state("brainn_thrownness") or {}
        self.interpretations = list(raw.get("interpretations") or [])
        for wound in raw.get("added_wounds") or []:
            if isinstance(wound, dict):
                self._childhood.append(MappingProxyType(dict(wound)))
        self._sealed = True
        self.save()

    @property
    def childhood(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self._childhood)

    def __setattr__(self, key: str, value: Any) -> None:
        if getattr(self, "_sealed", False) and key != "_sealed":
            raise ImmutableError("M13 被抛层不可修改")
        super().__setattr__(key, value)

    def add_wound(self, event: str, impact: float, kind: str = "shock") -> None:
        """只有显式标记的大冲击可以追加，且只能追加。"""
        if float(impact) < self.threshold:
            raise ImmutableError(
                f"冲击强度 {impact:.2f} 低于阈值 {self.threshold:.2f}，不能写入被抛层"
            )
        item = {
            "event": str(event)[:200],
            "impact": round(float(impact), 3),
            "kind": str(kind)[:40],
            "added_at": time.time(),
        }
        self._childhood.append(MappingProxyType(item))
        raw = self.store.get_state("brainn_thrownness") or {}
        added = list(raw.get("added_wounds") or [])
        added.append(item)
        raw["added_wounds"] = added[-20:]
        self.store.set_state("brainn_thrownness", raw)

    def reinterpret(self, text: str, source: str = "M5") -> dict[str, Any]:
        """M5 可以重新解释事实，但不能改事实本身。"""
        item = {
            "ts": time.time(),
            "source": str(source)[:20],
            "text": str(text)[:300],
        }
        self.interpretations.append(item)
        del self.interpretations[:-30]
        self.save()
        return item

    def pressure(self) -> float:
        wounds = sum(float(w.get("impact") or 0) for w in self._childhood)
        return round(
            max(0.0, min(1.0, self.class_position * 0.5 + min(1.0, wounds / 2.5) * 0.5)),
            3,
        )

    def expression_hint(self) -> str:
        return (
            "你身上有些东西不是自己选的：小城工薪家庭，父母长期在外，外婆把你带大；"
            "小学转学被排挤过。你不主动讲这些，被问到家里、钱、兼职、外婆时会收着点。"
            "这不是台词，只是你说话时的一层底色。"
        )

    def facts(self) -> dict[str, Any]:
        return {
            "origin": dict(self.origin),
            "era": dict(self.era),
            "mother_tongue": self.mother_tongue,
            "body_given": dict(self.body_given),
            "childhood": [dict(item) for item in self._childhood],
            "class_position": self.class_position,
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "facts": self.facts(),
            "interpretations": list(self.interpretations),
            "pressure": self.pressure(),
            "sealed": True,
        }

    def fact_hash(self) -> str:
        raw = json.dumps(self.facts(), ensure_ascii=False, sort_keys=True)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def save(self) -> None:
        raw = self.store.get_state("brainn_thrownness") or {}
        raw["interpretations"] = list(self.interpretations)[-30:]
        raw["feedback"] = "M13 facts are sealed"
        self.store.set_state("brainn_thrownness", raw)
