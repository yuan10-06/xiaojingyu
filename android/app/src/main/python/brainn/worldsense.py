"""G3 空间锚定：把视频通话里反复出现的画面记成地点锚点。

只存场景标签和少量描述，不存原图、不做人脸识别。
"""
from __future__ import annotations

import difflib
import re
import time
from typing import Any

from .db import Store

# 固定优先级：先具体地点，再宽泛地点；同一画面永远归到同一个标签。
PLACE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("书桌", ("书桌", "桌面", "键盘", "显示器", "笔记本电脑", "文具", "台灯")),
    ("窗边", ("窗边", "窗台", "窗外", "窗帘", "窗外晚霞")),
    ("床/宿舍", ("床铺", "床上", "枕头", "被子", "床头", "宿舍", "靠垫")),
    ("食堂", ("食堂", "餐盘", "打饭", "饭菜窗口")),
    ("奶茶店", ("奶茶店", "奶茶", "吧台", "收银台", "饮品杯")),
    ("教室", ("教室", "黑板", "讲台", "课桌", "同学")),
    ("图书馆", ("图书馆", "书架", "自习室", "借书")),
    ("户外/校园", ("户外", "校园", "道路", "落叶", "林荫道", "天空", "街边")),
    ("室内", ("室内", "房间", "白墙", "天花板", "墙面")),
]


class PlaceAnchors:
    """地点锚点持久化在 Store state，跨视频通话累积。"""

    def __init__(self, store: Store):
        self.store = store
        self.state = self._load()
        if self._normalize():
            self.store.set_state("world_place_anchors", self.state)

    def _load(self) -> dict[str, Any]:
        raw = self.store.get_state("world_place_anchors") or {}
        if not isinstance(raw, dict):
            raw = {}
        places = raw.get("places")
        if not isinstance(places, dict):
            places = {}
        return {"places": places}

    def observe(self, scene: dict[str, Any], caption: str = "") -> dict[str, Any] | None:
        label = self._label(scene, caption)
        if not label:
            return None
        now = time.time()
        places = self.state["places"]
        item = places.get(label)
        if not isinstance(item, dict):
            item = {
                "id": "place-" + re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", label)[:24],
                "label": label,
                "first_seen": now,
                "visits": 0,
                "samples": [],
            }
            places[label] = item
        item["last_seen"] = now
        item["visits"] = int(item.get("visits") or 0) + 1
        samples = list(item.get("samples") or [])
        text = str(caption or (scene or {}).get("scene") or "").strip()
        if text and text not in samples:
            samples.append(text[:160])
        item["samples"] = samples[-3:]
        self.state["places"] = places
        self.store.set_state("world_place_anchors", self.state)
        return dict(item)

    def _label(self, scene: dict[str, Any], caption: str) -> str:
        parts = [str((scene or {}).get("scene") or ""), str(caption or "")]
        objs = (scene or {}).get("objects") or []
        if isinstance(objs, list):
            parts.extend(str(x) for x in objs)
        text = " ".join(parts).lower()
        # 固定优先级：同一张“窗边书桌”永远归到“书桌”，避免每次建一个新地点。
        for label, words in PLACE_RULES:
            if any(str(word).lower() in text for word in words):
                return label
        return ""

    def _normalize(self) -> bool:
        """把同一场景被分成两个地点的情况合并，保留更具体的地点标签。"""
        places = self.state.get("places") or {}
        if not isinstance(places, dict) or len(places) < 2:
            return False
        priority = {label: i for i, (label, _) in enumerate(PLACE_RULES)}
        labels = list(places.keys())
        changed = False
        for i, left_label in enumerate(labels):
            if left_label not in places:
                continue
            left = places.get(left_label)
            if not isinstance(left, dict):
                continue
            for right_label in labels[i + 1:]:
                if right_label not in places:
                    continue
                right = places.get(right_label)
                if not isinstance(right, dict):
                    continue
                if not self._similar(left, right):
                    continue
                keep_label = left_label if priority.get(left_label, 999) <= priority.get(right_label, 999) else right_label
                drop_label = right_label if keep_label == left_label else left_label
                keep = places.get(keep_label) if isinstance(places.get(keep_label), dict) else {}
                drop = places.get(drop_label) if isinstance(places.get(drop_label), dict) else {}
                keep["visits"] = int(keep.get("visits") or 0) + int(drop.get("visits") or 0)
                keep["first_seen"] = min(
                    float(keep.get("first_seen") or time.time()),
                    float(drop.get("first_seen") or time.time()),
                )
                keep["last_seen"] = max(
                    float(keep.get("last_seen") or 0),
                    float(drop.get("last_seen") or 0),
                )
                samples = []
                for text in list(keep.get("samples") or []) + list(drop.get("samples") or []):
                    if text and text not in samples:
                        samples.append(str(text)[:160])
                keep["samples"] = samples[-3:]
                places[keep_label] = keep
                places.pop(drop_label, None)
                changed = True
                left = keep
                if drop_label == left_label:
                    break
        return changed

    @staticmethod
    def _similar(left: dict[str, Any], right: dict[str, Any]) -> bool:
        a = " ".join(str(x) for x in (left.get("samples") or [])[-2:])
        b = " ".join(str(x) for x in (right.get("samples") or [])[-2:])
        if not a or not b:
            return False
        return difflib.SequenceMatcher(None, a, b).ratio() >= 0.62

    def snapshot(self, limit: int = 8) -> list[dict[str, Any]]:
        items = list(self.state["places"].values())
        items.sort(key=lambda x: float(x.get("last_seen") or 0), reverse=True)
        return [dict(x) for x in items[: max(1, limit)]]

    def recent_label(self) -> str:
        items = self.snapshot(1)
        return str(items[0].get("label") or "") if items else ""
