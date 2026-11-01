"""生活事件账本：点餐、外卖、快递等有时效的生活事件。

手机端被杀后台时，内存里的“正在等外卖”会丢；这个模块把事件落库，
重启后按预计时间补算，并把最近事件和自己发过的动态带进提示词。
"""
from __future__ import annotations

import random
import re
import time
from typing import Any

FOOD_ITEMS = (
    "麻辣烫", "奶茶", "咖啡", "蛋糕", "水果", "零食", "烧烤", "炸鸡",
    "汉堡", "米线", "面条", "炒饭", "粥", "药", "快递", "花", "礼物", "外卖",
)
ORDER_HINTS = (
    "给你点", "帮你点", "给你买", "帮你买", "给你叫", "帮你叫",
    "给你寄", "帮你寄", "送过去", "送到", "放楼下", "快递柜", "外卖",
    "点了", "买了", "叫了",
)
ASK_HINTS = ("拿到了吗", "到了吗", "送到了吗", "好吃吗", "吃了吗", "还没到")
NEGATIVE = ("没拿到", "还没到", "没到", "没送来", "没收到", "不要了", "退了吧", "取消了", "不想吃")
DONE_RE = re.compile(r"(拿到了|拿到手|取到了|取到|吃上了|在吃了|收着了|放快递柜|拿上楼|拿回来|收下了)")
LOCATION_RE = re.compile(r"(女生\s*\d+\s*号楼|男生\s*\d+\s*号楼|宿舍楼?下?|楼下|快递柜|门口|教学楼)")


class LifeEvents:
    def __init__(self, store, settings: dict[str, Any] | None = None):
        self.store = store
        cfg = (settings or {}).get("life_events", {}) or {}
        self.enabled = bool(cfg.get("enabled", True))
        self.default_eta = max(5.0, float(cfg.get("default_eta_minutes", 40))) * 60
        self.grace = max(0.0, float(cfg.get("grace_minutes", 10))) * 60
        self.max_prompt_events = max(1, int(cfg.get("max_prompt_events", 3)))
        self.max_age_hours = max(2.0, float(cfg.get("max_age_hours", 8)))

    # ---------- 识别 ----------
    @staticmethod
    def _item(text: str) -> str:
        for item in FOOD_ITEMS:
            if item in text:
                return item
        return ""

    @staticmethod
    def _ask(text: str) -> bool:
        return any(word in text for word in ASK_HINTS)

    @staticmethod
    def _negative(text: str) -> bool:
        return any(word in text for word in NEGATIVE)

    def _is_order(self, text: str) -> bool:
        if len(text) < 4 or self._ask(text) or self._negative(text):
            return False
        if not any(word in text for word in ORDER_HINTS):
            return False
        return bool(self._item(text) or "外卖" in text or "快递" in text or "吃的" in text)

    def _done(self, text: str) -> bool:
        if self._negative(text) or self._ask(text):
            return False
        return bool(DONE_RE.search(text))

    @staticmethod
    def _eta(text: str) -> float:
        if "马上" in text:
            return 10 * 60
        if "半小时" in text:
            return 30 * 60
        if "一小时" in text or "1小时" in text or "一个小时" in text:
            return 60 * 60
        match = re.search(r"(\d+)\s*分钟", text)
        if match:
            return max(5.0, min(120.0, float(match.group(1)))) * 60
        return 0.0

    @staticmethod
    def _location(text: str) -> str:
        match = LOCATION_RE.search(text)
        return match.group(1) if match else ""

    @staticmethod
    def _summary(kind: str, title: str, detail: str) -> str:
        parts = [str(title or "").strip()]
        if detail:
            parts.append(str(detail).strip())
        return "；".join(p for p in parts if p)[:300]

    def _active(self, now: float | None = None) -> dict[str, Any] | None:
        now = float(now or time.time())
        for event in reversed(self.store.recent_life_events(self.max_age_hours, 30)):
            if str(event.get("status")) == "waiting" and float(event.get("created_at") or 0) >= now - self.max_age_hours * 3600:
                return event
        return None

    def _latest(self, now: float | None = None) -> dict[str, Any] | None:
        now = float(now or time.time())
        events = self.store.recent_life_events(self.max_age_hours, 30)
        recent = []
        for event in events:
            stamp = max(
                float(event.get("created_at") or 0),
                float(event.get("updated_at") or 0),
            )
            if now - stamp <= 21600:
                recent.append(event)
        return recent[-1] if recent else None

    # ---------- 观察 ----------
    def observe_user(self, text: str, ts: float | None = None, source: str = "chat", notify: bool = True):
        if not self.enabled:
            return None
        raw = str(text or "").strip()
        if not raw:
            return None
        # 图片/表情包的入库文本会带视觉描述，里面可能出现“还没到”，不能当成本人陈述
        if raw.startswith("[图片]") or raw.startswith("[表情包") or "[图片]（" in raw:
            return None
        now = float(ts or time.time())
        latest = self._latest(now)
        if latest and self._negative(raw) and "吗" not in raw and not raw.rstrip().endswith("?"):
            stamp = float(latest.get("updated_at") or latest.get("created_at") or 0)
            if now - stamp <= 7200:
                self.store.update_life_event(
                    int(latest["id"]), status="expired", note="他说没拿到/取消了"
                )
                return self.store.life_event(int(latest["id"]))
        active = self._active(now)
        if active:
            fields: dict[str, Any] = {}
            item = self._item(raw)
            generic = str(active.get("title") or "") in ("外卖", "吃的", "快递")
            if item and generic and item not in str(active.get("title") or ""):
                location = self._location(raw)
                fields["title"] = item
                fields["detail"] = self._summary(
                    str(active.get("kind") or "food_delivery"), item, location
                )
            else:
                location = self._location(raw)
                if location and location not in str(active.get("detail") or ""):
                    detail = str(active.get("detail") or "")
                    fields["detail"] = (detail + ("；" if detail else "") + location)[:300]
            if notify and any(word in raw for word in ("给我发", "说一声", "发个消息", "到了说")):
                fields["notify"] = 1
            if fields:
                self.store.update_life_event(int(active["id"]), **fields)
                return self.store.life_event(int(active["id"]))
            return active
        if not self._is_order(raw):
            return None
        item = self._item(raw) or ("快递" if "快递" in raw else "外卖")
        if "快递" in item:
            kind = "parcel"
        elif item in ("花", "礼物"):
            kind = "gift"
        else:
            kind = "food_delivery"
        eta = self._eta(raw) or self.default_eta
        location = self._location(raw)
        detail = self._summary(kind, item, location)
        # 同一件事最近已经记过，就不要重复建（八小时内）
        for event in self.store.recent_life_events(self.max_age_hours, 30):
            if now - float(event.get("created_at") or 0) > self.max_age_hours * 3600:
                continue
            if str(event.get("title") or "") == item or (
                str(event.get("kind") or "") == kind and item == "外卖"
            ):
                return event
        event_id = self.store.add_life_event(
            kind,
            item,
            detail,
            expected_at=now + eta,
            source=source,
            confidence=0.65,
            notify=notify,
            created_at=now,
        )
        return self.store.life_event(event_id)

    def observe_her(self, text: str, ts: float | None = None):
        if not self.enabled:
            return None
        raw = str(text or "").strip()
        if not raw:
            return None
        active = self._active(ts)
        if not active:
            return None
        if self._negative(raw):
            self.store.update_life_event(int(active["id"]), note="她还没拿到")
            return self.store.life_event(int(active["id"]))
        if self._done(raw):
            self.store.update_life_event(
                int(active["id"]),
                status="done",
                note="她在聊天里确认拿到了",
            )
            return self.store.life_event(int(active["id"]))
        return None

    def observe_dynamic(self, text: str, ts: float | None = None):
        if not self.enabled:
            return None
        raw = str(text or "").strip()
        if not raw:
            return None
        active = self._active(ts)
        if not active:
            return None
        title = str(active.get("title") or "")
        if (title and title in raw) or "外卖" in raw or "等" in raw:
            if self._done(raw) and not self._negative(raw):
                self.store.update_life_event(
                    int(active["id"]), status="done", note="她在动态里说拿到了"
                )
            else:
                self.store.update_life_event(
                    int(active["id"]), note="她在动态里提到正在等"
                )
            return self.store.life_event(int(active["id"]))
        return None

    # ---------- 时间推进 / 离线补算 ----------
    def tick(self, now: float | None = None) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        now = float(now or time.time())
        last_alive = float(self.store.get_state("last_alive_ts") or 0)
        offline = bool(last_alive and now - last_alive >= 120)
        gap_minutes = round((now - last_alive) / 60, 1) if last_alive else 0.0
        if offline:
            self.store.set_state(
                "offline_gap",
                {"from": last_alive, "to": now, "minutes": gap_minutes},
            )
        resolved: list[dict[str, Any]] = []
        for event in self.store.pending_life_events():
            expected = float(event.get("expected_at") or 0)
            if not expected or now < expected + self.grace:
                continue
            if offline:
                note = f"手机断线 {gap_minutes:.0f} 分钟后补算：预计早已送达"
            else:
                note = "到点自动确认已送达（他若说没拿到会改回未到）"
            self.store.update_life_event(int(event["id"]), status="done", note=note)
            fresh = self.store.life_event(int(event["id"])) or event
            fresh = dict(fresh)
            fresh["notify"] = bool(event.get("notify")) and not offline
            resolved.append(fresh)
        self.store.set_state("last_alive_ts", now)
        self.store.set_state("last_life_tick", now)
        return resolved

    def backfill_recent(self, now: float | None = None) -> None:
        """升级/重启时把最近几小时的点餐消息补成事件，旧数据也能接上。"""
        if not self.enabled:
            return
        now = float(now or time.time())
        try:
            messages = self.store.messages_between(now - self.max_age_hours * 3600, now)
        except Exception:  # noqa: BLE001
            return
        for message in messages:
            if str(message.get("role")) != "user":
                continue
            if str(message.get("kind") or "text") != "text":
                continue
            self.observe_user(
                str(message.get("content") or ""),
                ts=float(message.get("ts") or now),
                source="backfill",
                notify=False,
            )

    def reconcile(self, now: float | None = None) -> list[dict[str, Any]]:
        now = float(now or time.time())
        self.backfill_recent(now)
        return self.tick(now)

    # ---------- 提示词 ----------
    def context_for_prompt(self, now: float | None = None, include_dynamics: bool = True) -> str:
        if not self.enabled:
            return ""
        now = float(now or time.time())
        lines: list[str] = []
        events = self.store.recent_life_events(self.max_age_hours, 20)[-self.max_prompt_events:]
        for event in events:
            stamp = time.strftime("%H:%M", time.localtime(float(event.get("created_at") or now)))
            status = str(event.get("status") or "waiting")
            if status == "done":
                status_text = "已拿到/已送达"
            elif status == "expired":
                status_text = "没拿到/已取消"
            else:
                expected = float(event.get("expected_at") or 0)
                due = time.strftime("%H:%M", time.localtime(expected)) if expected else "时间不定"
                status_text = f"还在等，预计 {due} 到"
            detail = str(event.get("detail") or "")
            note = str(event.get("note") or "")
            line = f"- {stamp} {event.get('title') or '生活事件'}"
            if detail:
                line += f"（{detail}）"
            line += f"：{status_text}"
            if note:
                line += f"；{note}"
            lines.append(line)
        if include_dynamics:
            dynamics = [
                row for row in self.store.recent_dynamics(20)
                if str(row.get("author") or "her") == "her"
                and float(row.get("ts") or 0) >= now - 86400
            ][-4:]
            for row in dynamics:
                stamp = time.strftime("%H:%M", time.localtime(float(row.get("ts") or now)))
                text = str(row.get("text") or "").strip()
                if text:
                    lines.append(f"- 你 {stamp} 发过动态：{text[:100]}")
        gap = self.store.get_state("offline_gap") or {}
        if isinstance(gap, dict):
            try:
                gap_minutes = float(gap.get("minutes") or 0)
                gap_to = float(gap.get("to") or 0)
            except (TypeError, ValueError):
                gap_minutes, gap_to = 0.0, 0.0
            if gap_minutes >= 2 and now - gap_to <= 21600:
                start = time.strftime("%H:%M", time.localtime(float(gap.get("from") or 0)))
                end = time.strftime("%H:%M", time.localtime(gap_to))
                lines.append(
                    f"- 你刚才手机被清后台/断线了 {gap_minutes:.0f} 分钟（{start}-{end}），"
                    "这期间你不在线；按上面的状态补算，别装作一直在线。"
                )
        if not lines:
            return ""
        head = (
            "【生活连续性·真实性约束】下面是你自己刚经历的事和发过的动态。"
            "他问起时要承认，不要否认自己发过动态，也不要说和状态相反的话。"
        )
        return head + "\n" + "\n".join(lines)

    def resolution_text(self, event: dict[str, Any]) -> str:
        title = str(event.get("title") or "外卖")
        if "麻辣烫" in title:
            choices = [
                "拿到了，麻辣烫烫得我直哈气，豆腐都吸满汤了",
                "拿到了，麻辣烫有点烫，我正蹲楼下吃两口",
            ]
        elif "奶茶" in title:
            choices = ["拿到了，奶茶还是冰的，正好解馋", "拿到了，奶茶封口没洒，运气不错"]
        elif str(event.get("kind")) == "parcel":
            choices = ["快递拿到了，盒子比我想的沉", "快递取到了，我拆开看看是什么"]
        else:
            choices = ["拿到了，刚下楼取的，还热着", "到了到了，我拿上楼了"]
        return random.choice(choices)

    def health(self) -> dict[str, Any]:
        now = time.time()
        events = self.store.recent_life_events(self.max_age_hours, 20)
        pending = [e for e in events if str(e.get("status")) == "waiting"]
        return {
            "pending": len(pending),
            "recent": [
                {
                    "title": e.get("title"),
                    "status": e.get("status"),
                    "expected_at": e.get("expected_at"),
                    "note": e.get("note"),
                }
                for e in events[-5:]
            ],
            "offline_gap": self.store.get_state("offline_gap") or {},
            "now": now,
        }
