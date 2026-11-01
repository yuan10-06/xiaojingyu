"""虚拟社会层：位置、交换、评价，以及角色看不见的内部状态。

模拟原则：
- 世界层纯规则、永远不调 LLM；
- 只有产生后果 / 预测误差 / 关系变化的事件才实体化；
- 角色只拿到 EventView（表象），永远拿不到 Event（真相）。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import random
import time
from typing import Any

from ..db import Store


class PermissionDenied(Exception):
    """角色侧试图读取他者内部状态时抛出。"""


WARMTH = {"warm": 1.0, "asking": 0.55, "cold": 0.25, "refuse": 0.05, "absent": 0.08}


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


def _weighted(rng: random.Random, policy: dict[str, float]) -> str:
    total = sum(max(0.0, float(v)) for v in policy.values()) or 1.0
    pick = rng.random() * total
    upto = 0.0
    for key, value in policy.items():
        upto += max(0.0, float(value))
        if pick <= upto:
            return key
    return "warm"


DEFAULT_POSITION = {
    "id": "milk_tea_student",
    "tier": 0.35,
    "origin": {
        "family": "普通工薪家庭",
        "constraints": ["生活费有限", "需要兼职", "不能脱产"],
    },
    "org": "奶茶店",
    "role_in_org": "兼职店员",
    "secondary_org": "课程小组",
    "available_labor": ["work", "group", "study", "class", "deadline"],
    "obligations": [{"target": "wangjie", "kind": "shift", "amount": 1.0}],
    "evaluators": ["wangjie", "chenyu"],
    "output_owner": {
        "work": "wangjie",
        "group": "chenyu",
        "class": "chenyu",
        "study": "her",
        "deadline": "chenyu",
    },
    "alpha": {"work": 0.18, "group": 0.55, "class": 0.55, "study": 0.72, "deadline": 0.58},
    "kappa": {"work": 0.30, "group": 0.42, "class": 0.28, "study": 0.72, "deadline": 0.45},
    "lambda": {"work": 0.80, "group": 0.58, "class": 0.56, "study": 0.55, "deadline": 0.66},
}

DEFAULT_OTHERS = {
    "wangjie": {
        "name": "王姐", "role": "奶茶店店长", "org": "奶茶店",
        "power": True,
        "policy": {"warm": 0.12, "cold": 0.28, "asking": 0.20, "refuse": 0.20, "absent": 0.20},
        "availability": {"work": [9, 22], "other": [8, 22]},
        "own_interest": "盯成本、别被区域经理抓到问题",
        "_internal": {"true_affinity": 32, "true_strategy": "把备料和收尾压给你", "secret": "总部下周查卫生"},
    },
    "xiaoyu": {
        "name": "小雨", "role": "奶茶店新人", "org": "奶茶店",
        "power": False,
        "policy": {"warm": 0.35, "cold": 0.10, "asking": 0.20, "refuse": 0.20, "absent": 0.15},
        "availability": {"work": [17, 22], "other": [9, 23]},
        "own_interest": "少出错、早点下班",
        "_internal": {"true_affinity": 55, "true_strategy": "出错时希望你替她兜", "secret": "想辞职"},
    },
    "ajie": {
        "name": "阿杰", "role": "奶茶店同事", "org": "奶茶店",
        "power": False,
        "policy": {"warm": 0.25, "cold": 0.15, "asking": 0.25, "refuse": 0.15, "absent": 0.20},
        "availability": {"work": [17, 22], "other": [10, 23]},
        "own_interest": "摸鱼、少干活",
        "_internal": {"true_affinity": 48, "true_strategy": "把活推给新人", "secret": "在准备专升本"},
    },
    "xiaomei": {
        "name": "小美", "role": "室友", "org": "宿舍",
        "power": False,
        "policy": {"warm": 0.15, "cold": 0.35, "asking": 0.30, "refuse": 0.10, "absent": 0.10},
        "availability": {"work": [0, 24], "other": [0, 24]},
        "own_interest": "占小便宜、不想被管",
        "_internal": {"true_affinity": 28, "true_strategy": "先借再拖，能拖就拖", "secret": "她也在背后说你计较"},
    },
    "linlin": {
        "name": "林林", "role": "高中闺蜜", "org": "朋友",
        "power": False,
        "policy": {"warm": 0.45, "cold": 0.10, "asking": 0.10, "refuse": 0.05, "absent": 0.30},
        "availability": {"work": [20, 24], "other": [12, 24]},
        "own_interest": "找个人听她吐槽",
        "_internal": {"true_affinity": 78, "true_strategy": "半夜找你，但她也真的在乎你", "secret": "和对象又吵了"},
    },
    "mom": {
        "name": "妈妈", "role": "妈妈", "org": "家庭",
        "power": True,
        "policy": {"warm": 0.40, "cold": 0.05, "asking": 0.35, "refuse": 0.05, "absent": 0.15},
        "availability": {"work": [8, 21], "other": [8, 21]},
        "own_interest": "让你别太累、早点回家",
        "_internal": {"true_affinity": 88, "true_strategy": "用催回家表达担心", "secret": "她最近腰疼没跟你说"},
    },
    "chenyu": {
        "name": "陈宇", "role": "小组作业组长", "org": "课程小组",
        "power": True,
        "policy": {"warm": 0.15, "cold": 0.20, "asking": 0.40, "refuse": 0.10, "absent": 0.15},
        "availability": {"work": [10, 23], "other": [10, 23]},
        "own_interest": "保绩点、把活分出去",
        "_internal": {"true_affinity": 42, "true_strategy": "在群里点名催你", "secret": "他自己那部分也没做完"},
    },
}

DEFAULT_GROUPS = {
    "shop_staff": {
        "name": "奶茶店店员圈", "members": ["wangjie", "ajie", "xiaoyu", "her"],
        "threshold": 0.50, "exclusion": [],
    },
    "dorm": {
        "name": "宿舍圈", "members": ["xiaomei", "afang", "tingting", "her"],
        "threshold": 0.55, "exclusion": [],
    },
    "course_group": {
        "name": "课程小组", "members": ["chenyu", "lijing", "zhaomin", "her"],
        "threshold": 0.45, "exclusion": [],
    },
}

DEFAULT_ORGS = {
    "奶茶店": {"name": "奶茶店", "kind": "shop", "pressure": 0.55, "members": ["her", "wangjie", "ajie", "xiaoyu"], "power": ["wangjie"]},
    "课程小组": {"name": "课程小组", "kind": "group", "pressure": 0.50, "members": ["her", "chenyu", "lijing", "zhaomin"], "power": ["chenyu"]},
    "宿舍": {"name": "宿舍", "kind": "dorm", "pressure": 0.35, "members": ["her", "xiaomei", "afang", "tingting"], "power": []},
}

ACTIONS = {
    "wangjie": ["critique", "shift_change", "ask_overtime"],
    "xiaoyu": ["help", "refuse_help", "leave_early"],
    "ajie": ["slack", "ask_cover", "help"],
    "xiaomei": ["borrow", "complain", "cold_shoulder"],
    "linlin": ["call", "vent", "cancel"],
    "mom": ["call", "ask_home", "send_money"],
    "chenyu": ["chase", "praise", "assign"],
}

ACTION_PHRASES = {
    ("critique", "cold"): "看了一眼你做的，只说“先这样吧”，没多讲",
    ("critique", "refuse"): "说你今天弄得不合格，让你重来",
    ("critique", "warm"): "难得说了句“还行”",
    ("critique", "asking"): "问你能不能再多留一会儿",
    ("critique", "absent"): "没回你消息",
    ("shift_change", "cold"): "把你排好的班又改了，只丢下一句“临时调”",
    ("shift_change", "refuse"): "说今天不用你来了，排班砍掉",
    ("shift_change", "warm"): "说这次排班尽量照顾你",
    ("shift_change", "asking"): "问你周末能不能再多顶一个班",
    ("shift_change", "absent"): "一直没回你排班的消息",
    ("ask_overtime", "cold"): "让你晚点走，没提加班费",
    ("ask_overtime", "refuse"): "拒绝了你调班的请求",
    ("ask_overtime", "warm"): "说这次算她欠你个人情",
    ("ask_overtime", "asking"): "问你今晚能不能帮她顶班",
    ("ask_overtime", "absent"): "没接你电话",
    ("help", "warm"): "帮你顶了一单，让你先喘口气",
    ("help", "cold"): "嘴上说帮，最后还是把活推回给你",
    ("help", "refuse"): "说自己忙，没接你递过去的单子",
    ("help", "asking"): "说可以帮你，但你得先帮她做一杯",
    ("help", "absent"): "装没看见，走开了",
    ("refuse_help", "refuse"): "直接说“我也没办法”",
    ("refuse_help", "cold"): "嘴上答应，转头就忘了",
    ("leave_early", "cold"): "提前走了，收尾全留给你",
    ("leave_early", "warm"): "走前把台面帮你收了",
    ("leave_early", "absent"): "人不见了，消息也不回",
    ("slack", "cold"): "在柜台后面刷手机，活堆给你",
    ("slack", "warm"): "难得主动来搭了把手",
    ("ask_cover", "asking"): "让你替他顶半小时",
    ("ask_cover", "refuse"): "你拒绝后，他脸色不太好",
    ("borrow", "asking"): "又开口借你的充电宝",
    ("borrow", "cold"): "没问一声就把东西拿走了",
    ("borrow", "refuse"): "被你拒绝后啧了一声",
    ("complain", "cold"): "在宿舍阴阳你“什么都要计较”",
    ("complain", "warm"): "主动跟你说了句软话",
    ("cold_shoulder", "cold"): "没接你的话，转身出门",
    ("call", "warm"): "打电话来问你最近怎么样",
    ("call", "cold"): "接起来没说两句就挂了",
    ("call", "absent"): "打了两个都没接",
    ("vent", "warm"): "半夜给你发了一大段语音",
    ("vent", "absent"): "消息发到一半又撤回了",
    ("cancel", "refuse"): "说好的见面又取消了",
    ("ask_home", "asking"): "问你今晚回不回家吃饭",
    ("ask_home", "cold"): "催你回家，语气有点冲",
    ("send_money", "warm"): "给你转了生活费，还说别省",
    ("chase", "cold"): "在群里点名催你进度",
    ("chase", "refuse"): "说这部分不算你的，让你别管了",
    ("chase", "asking"): "问你今晚能不能把剩下的做完",
    ("praise", "warm"): "在群里说这次你做得不错",
    ("assign", "asking"): "又给你分了一块活",
    ("assign", "cold"): "把最麻烦的部分丢给你",
}


class OtherAgent:
    """他者包装：角色只能拿 surface，内部字段读取直接拒绝。"""

    __internal__ = {"policy", "true_affinity", "own_interest", "true_cause", "secret"}

    def __init__(self, data: dict[str, Any]):
        self.data = dict(data)

    @property
    def name(self) -> str:
        return str(self.data.get("name") or self.data.get("id") or "")

    def surface(self) -> dict[str, Any]:
        return {
            "id": self.data.get("id", ""),
            "name": self.name,
            "role": self.data.get("role", ""),
            "org": self.data.get("org", ""),
            "available_hint": "有时回，有时不回",
        }

    def internal(self) -> dict[str, Any]:
        raise PermissionDenied("社会内部状态对角色不可见")


class WorldModel:
    name = "world"

    def __init__(
        self,
        store: Store,
        settings: dict[str, Any],
        clock,
        social=None,
        thrownness=None,
    ):
        self.store = store
        self.settings = settings
        self.clock = clock
        self.social = social
        self.thrownness = thrownness
        self.life = settings.get("life") or {}
        cfg = (settings.get("brainn") or {}).get("world") or {}
        self.cfg = {
            "enabled": bool(cfg.get("enabled", True)),
            "event_interval_minutes": list(cfg.get("event_interval_minutes", [50, 100])),
            "materialize_delta": float(cfg.get("materialize_delta", 0.35)),
            "materialize_sample": float(cfg.get("materialize_sample", 0.12)),
            "shock_chance": float(cfg.get("shock_chance", 0.04)),
        }
        self.state = self._load(store.get_state("brainn_world") or {})

    # ---------- 状态 ----------
    def _load(self, raw: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        others: dict[str, dict[str, Any]] = {}
        for key, base in DEFAULT_OTHERS.items():
            item = {**base, **(raw.get("others", {}).get(key) or {})}
            item["id"] = key
            item["_internal"] = {**base.get("_internal", {}), **item.get("_internal", {})}
            others[key] = item
        state = {
            "version": 1,
            "tick_count": int(raw.get("tick_count") or 0),
            "exposure": int(raw.get("exposure") or 0),
            "materialized": int(raw.get("materialized") or 0),
            "conflict_ticks": int(raw.get("conflict_ticks") or 0),
            "last_conflict_date": str(raw.get("last_conflict_date") or ""),
            "shock_date": str(raw.get("shock_date") or ""),
            "position": {**DEFAULT_POSITION, **(raw.get("position") or {})},
            "orgs": {**DEFAULT_ORGS, **(raw.get("orgs") or {})},
            "others": others,
            "groups": {**DEFAULT_GROUPS, **(raw.get("groups") or {})},
            "exchanges": list(raw.get("exchanges") or []),
            "appraisals": list(raw.get("appraisals") or []),
            "events": list(raw.get("events") or []),
            "views": list(raw.get("views") or []),
            "deltas": list(raw.get("deltas") or []),
            "shocks": list(raw.get("shocks") or []),
            "expectations": dict(raw.get("expectations") or {}),
            "drive_queue": list(raw.get("drive_queue") or []),
            "clocks": raw.get("clocks") or {},
            "next_event_ts": float(raw.get("next_event_ts") or (now + random.uniform(10, 20) * 60)),
            "last_tick": float(raw.get("last_tick") or now),
        }
        return state

    # ---------- 节拍 ----------
    def tick(self, now: float, ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ctx = ctx or {}
        if not self.cfg["enabled"]:
            return []
        if now < float(self.state.get("last_tick") or 0):
            return []
        self.state["tick_count"] = int(self.state.get("tick_count") or 0) + 1
        self.state["last_tick"] = now
        self._advance_clocks(now, ctx)
        self._clock_conflict(now, ctx)
        if now >= float(self.state.get("next_event_ts") or 0):
            self._spawn_candidate(now, ctx)
            low, high = self.cfg["event_interval_minutes"]
            self.state["next_event_ts"] = now + random.uniform(float(low), float(high)) * 60
        self._maybe_shock(now, ctx)
        self.save()
        return []

    def _advance_clocks(self, now: float, ctx: dict[str, Any]) -> None:
        now_dt = self.clock.now()
        exam = self.life.get("exam") or {}
        days_left = 99
        if exam.get("date"):
            try:
                target = dt.date.fromisoformat(str(exam["date"]))
                days_left = (target - now_dt.date()).days
            except ValueError:
                pass
        activity = ctx.get("activity") or {}
        kind = str(activity.get("kind") or "")
        personal = activity.get("title") or (ctx.get("idle") or {}).get("title") or ""
        due = [x for x in self.state.get("exchanges") or [] if float(x.get("settled") or 0) < float(x.get("amount") or 0)]
        self.state["clocks"] = {
            "institutional_days_left": days_left,
            "org": "奶茶店" if kind == "work" else "课程小组" if kind in ("study", "class", "deadline") else "宿舍",
            "personal": personal,
            "relational_due": len(due),
            "now": now_dt.strftime("%Y-%m-%d %H:%M"),
        }

    def _clock_conflict(self, now: float, ctx: dict[str, Any]) -> None:
        activity = ctx.get("activity") or {}
        if str(activity.get("kind") or "") != "work":
            return
        days_left = int((self.state.get("clocks") or {}).get("institutional_days_left", 99) or 99)
        due = int((self.state.get("clocks") or {}).get("relational_due", 0) or 0)
        if days_left > 3 and due < 2:
            return
        today = self.clock.now().date().isoformat()
        if self.state.get("last_conflict_date") == today:
            return
        self.state["last_conflict_date"] = today
        self.state["conflict_ticks"] = int(self.state.get("conflict_ticks") or 0) + 1
        actor = "mom" if due >= 2 else "wangjie"
        self._materialize(
            now,
            actor,
            "ask_overtime",
            "asking",
            force_surface="手机一直在震：工作和考试的事同时压过来，你只能先顾一头。",
            kind="clock_conflict",
        )

    def _maybe_shock(self, now: float, ctx: dict[str, Any]) -> None:
        today = self.clock.now().date().isoformat()
        if self.state.get("shock_date") == today:
            return
        self.state["shock_date"] = today
        if random.random() >= self.cfg["shock_chance"]:
            return
        kind = random.choice(["policy_change", "dismissal", "estrangement", "departure"])
        target = "xiaomei" if kind in ("estrangement", "departure") else "wangjie"
        self.force_shock(kind, target)

    # ---------- 事件 ----------
    def _pick_actor(self, ctx: dict[str, Any], rng: random.Random) -> str:
        kind = str((ctx.get("activity") or {}).get("kind") or "")
        if kind == "work":
            pool = ["wangjie", "wangjie", "xiaoyu", "ajie"]
        elif kind in ("study", "class", "deadline"):
            pool = ["chenyu", "chenyu", "mom", "linlin"]
        else:
            pool = ["xiaomei", "xiaomei", "linlin", "mom"]
        return rng.choice(pool)

    def _spawn_candidate(self, now: float, ctx: dict[str, Any]) -> None:
        rng = random.Random(int(now) ^ int(self.state.get("tick_count") or 0))
        actor = self._pick_actor(ctx, rng)
        action = rng.choice(ACTIONS.get(actor) or ["help"])
        data = self.state["others"][actor]
        policy = data.get("policy") or {"warm": 0.3, "cold": 0.2, "asking": 0.2, "refuse": 0.15, "absent": 0.15}
        outcome = _weighted(rng, policy)
        key = f"{actor}:{action}"
        expected = float(
            self.state.get("expectations", {}).get(
                key, self._expected_warmth(policy)
            )
        )
        delta_true = round(WARMTH.get(outcome, 0.2) - expected, 3)
        material = (
            outcome in ("refuse", "absent")
            or abs(delta_true) >= self.cfg["materialize_delta"]
            or rng.random() < self.cfg["materialize_sample"]
        )
        if not material:
            self.state["exposure"] = int(self.state.get("exposure") or 0) + 1
            return
        self._materialize(now, actor, action, outcome)

    @staticmethod
    def _expected_warmth(policy: dict[str, float]) -> float:
        total = sum(max(0.0, float(v)) for v in policy.values()) or 1.0
        return sum(WARMTH.get(k, 0.2) * max(0.0, float(v)) for k, v in policy.items()) / total

    def _surface(self, actor: str, action: str, outcome: str) -> str:
        name = str(self.state["others"][actor].get("name") or actor)
        phrase = ACTION_PHRASES.get((action, outcome)) or {
            "warm": "主动来找你说了句话",
            "cold": "态度有点冷",
            "asking": "开口找你帮个忙",
            "refuse": "拒绝了你",
            "absent": "没有出现",
        }.get(outcome, "做了点让你意外的事")
        return f"{name}{phrase}。"

    def _materialize(
        self,
        now: float,
        actor: str,
        action: str,
        outcome: str,
        *,
        force_surface: str = "",
        kind: str = "social",
    ) -> dict[str, Any]:
        rng = random.Random(int(now) ^ int(self.state.get("tick_count") or 0))
        data = self.state["others"][actor]
        policy = data.get("policy") or {}
        key = f"{actor}:{action}"
        expected = float(self.state.get("expectations", {}).get(key, self._expected_warmth(policy)))
        delta_true = round(WARMTH.get(outcome, 0.2) - expected, 3)
        delta_perception = round(
            (0.15 + rng.random() * 0.45) if outcome in ("cold", "refuse", "absent", "asking") else rng.random() * 0.15,
            3,
        )
        surface = force_surface or self._surface(actor, action, outcome)
        missing = ["对方真实的评价和原因", "对方没说出的一部分"]
        distorted = {"cause": rng.choice(["以为她只是今天心情差", "以为是自己想多了", "以为对方在针对你"])}
        truth = f"{data['name']}真实想法：{data.get('own_interest', '')}；实际结果：{outcome}"
        event = {
            "id": hashlib.md5(f"{now}-{actor}-{action}-{outcome}".encode()).hexdigest()[:10],
            "ts": now,
            "kind": kind,
            "actor": actor,
            "action": action,
            "outcome": outcome,
            "truth": truth,
            "true_cause": str(data.get("own_interest") or ""),
            "actor_state": dict(data.get("_internal") or {}),
            "delta_true": delta_true,
            "delta_perception": delta_perception,
        }
        view = {
            "id": event["id"],
            "ts": now,
            "surface": surface,
            "missing": missing,
            "distorted": distorted,
        }
        self.state["events"] = (list(self.state.get("events") or []) + [event])[-120:]
        self.state["views"] = (list(self.state.get("views") or []) + [view])[-30:]
        self.state["deltas"] = (list(self.state.get("deltas") or []) + [
            {
                "ts": now,
                "kind": kind,
                "actor": actor,
                "action": action,
                "outcome": outcome,
                "delta_true": delta_true,
                "delta_perception": delta_perception,
            }
        ])[-300:]
        self.state["materialized"] = int(self.state.get("materialized") or 0) + 1
        # w 表只在实体化事件上更新
        lam = float((self.state.get("position") or {}).get("lambda", {}).get("work", 0.65))
        new_expected = _clamp(expected + 0.2 * lam * delta_true * 1.0)
        expectations = dict(self.state.get("expectations") or {})
        expectations[key] = round(new_expected, 4)
        self.state["expectations"] = expectations
        self._apply_effects(now, actor, action, outcome, rng)
        return event

    def _apply_effects(
        self,
        now: float,
        actor: str,
        action: str,
        outcome: str,
        rng: random.Random,
    ) -> None:
        deltas: dict[str, float] = {}
        if outcome in ("cold", "refuse", "absent"):
            deltas["conflict"] = round(1.0 + rng.random() * 1.5, 2)
            deltas["intimacy"] = -0.2
        elif outcome in ("warm",):
            deltas["trust"] = 0.3
            deltas["debt"] = 0.6
            deltas["shared"] = 0.4
        elif outcome == "asking":
            deltas["credit"] = 0.3
        if self.social is not None and deltas:
            self.social.adjust_edge(
                "her", actor, deltas, interactions=1,
                last_event=str(self.state["views"][-1].get("surface") or "")[:100],
            )
        # 交换：人情账只增不减到清零
        if action in ("help", "ask_cover", "ask_overtime") and outcome in ("warm", "asking"):
            from_id, to_id = (actor, "her") if outcome == "warm" else ("her", actor)
            self.state["exchanges"] = (list(self.state.get("exchanges") or []) + [
                {
                    "id": hashlib.md5(f"{now}-{actor}-{action}".encode()).hexdigest()[:8],
                    "from_id": from_id,
                    "to_id": to_id,
                    "kind": "favor",
                    "amount": round(0.5 + rng.random() * 1.5, 2),
                    "settled": 0.1,
                    "created_at": now,
                }
            ])[-80:]
        # 评价：允许 grounded=False，且永不自动纠正
        if action in ("critique", "chase", "slack", "complain") and outcome in ("cold", "refuse"):
            grounded = rng.random() < 0.35
            self.state["appraisals"] = (list(self.state.get("appraisals") or []) + [
                {
                    "id": hashlib.md5(f"{now}-{actor}-appraisal".encode()).hexdigest()[:8],
                    "appraiser": actor,
                    "content": f"{self.state['others'][actor]['name']}觉得你{ '不上心' if action == 'critique' else '拖进度'}",
                    "grounded": grounded,
                    "created_at": now,
                }
            ])[-100:]
        drive = {}
        if outcome in ("cold", "refuse", "absent"):
            drive = {"autonomy": -0.6, "belonging": -0.5}
        elif outcome == "warm":
            drive = {"belonging": 0.5, "mattering": 0.4}
        elif outcome == "asking":
            drive = {"autonomy": -0.2}
        if drive:
            self.state["drive_queue"] = (list(self.state.get("drive_queue") or []) + [drive])[-20:]

    # ---------- 位置 ----------
    def ownership_for(self, kind: str, title: str = "") -> float:
        position = self.state.get("position") or DEFAULT_POSITION
        if "小组" in str(title) or "实验" in str(title):
            return float(position.get("alpha", {}).get("group", 0.55))
        return float(position.get("alpha", {}).get(kind, 0.55))

    def owner_for(self, kind: str, title: str = "") -> str:
        position = self.state.get("position") or DEFAULT_POSITION
        if "小组" in str(title) or "实验" in str(title):
            return str(position.get("output_owner", {}).get("group", "chenyu"))
        return str(position.get("output_owner", {}).get(kind, "her"))

    # ---------- 对外可读 ----------
    def views_for_prompt(self, limit: int = 2) -> str:
        views = [v for v in (self.state.get("views") or []) if time.time() - float(v.get("ts") or 0) <= 86400]
        if not views:
            return ""
        return "你最近碰到的（只是你看到的表象，不一定知道真实原因）：" + "；".join(
            str(v.get("surface") or "") for v in views[-limit:]
        )

    def agent(self, agent_id: str) -> OtherAgent:
        data = self.state.get("others", {}).get(agent_id)
        if not data:
            raise KeyError(agent_id)
        return OtherAgent({"id": agent_id, **data})

    def consume_drive_deltas(self) -> dict[str, float]:
        queue = list(self.state.get("drive_queue") or [])
        self.state["drive_queue"] = []
        total: dict[str, float] = {}
        for item in queue:
            for key, value in (item or {}).items():
                total[key] = round(total.get(key, 0.0) + float(value), 2)
        return total

    # ---------- 测试 / 人工触发 ----------
    def force_event(self, actor: str, action: str, outcome: str) -> dict[str, Any]:
        return self._materialize(time.time(), actor, action, outcome)

    def force_appraisal(self, appraiser: str, content: str, grounded: bool = False) -> dict[str, Any]:
        """测试/构造：写入一条可能错误且不会自动纠正的评价。"""
        item = {
            "id": hashlib.md5(f"{time.time()}-{appraiser}-{content}".encode()).hexdigest()[:8],
            "appraiser": appraiser,
            "content": str(content)[:120],
            "grounded": bool(grounded),
            "created_at": time.time(),
        }
        self.state["appraisals"] = (list(self.state.get("appraisals") or []) + [item])[-100:]
        self.save()
        return item

    def force_shock(self, kind: str, target: str = "wangjie") -> dict[str, Any]:
        now = time.time()
        surface = {
            "policy_change": "店里突然换了排班规则，之前的安排全不算了。",
            "dismissal": "王姐说下周班次先不给你排了。",
            "estrangement": "小美突然不怎么跟你说话了，宿舍气氛变了。",
            "departure": "有人要搬走，原来的关系一下悬空了。",
        }.get(kind, "生活里出了件没法当没发生的事。")
        event = self._materialize(
            now,
            target,
            "shift_change" if kind in ("policy_change", "dismissal") else "cold_shoulder",
            "refuse" if kind in ("dismissal", "estrangement") else "cold",
            force_surface=surface,
            kind=f"shock:{kind}",
        )
        if self.thrownness is not None:
            try:
                # 结构性冲击是 M13 唯一允许追加的时刻之一
                self.thrownness.add_wound(surface, 0.85, kind)
            except Exception:  # noqa: BLE001
                pass
        self.state["shocks"] = (list(self.state.get("shocks") or []) + [
            {"kind": kind, "target": target, "ts": now, "event_id": event["id"]}
        ])[-40:]
        if kind == "dismissal":
            group = dict(self.state["groups"].get("shop_staff") or {})
            exclusion = list(group.get("exclusion") or [])
            if "her" not in exclusion:
                exclusion.append("her")
            group["exclusion"] = exclusion
            self.state["groups"]["shop_staff"] = group
        elif kind == "estrangement":
            group = dict(self.state["groups"].get("dorm") or {})
            exclusion = list(group.get("exclusion") or [])
            if "her" not in exclusion:
                exclusion.append("her")
            group["exclusion"] = exclusion
            self.state["groups"]["dorm"] = group
        return event

    def repay_exchange(self, exchange_id: str, amount: float) -> float:
        for item in self.state.get("exchanges") or []:
            if item.get("id") == exchange_id:
                total = float(item.get("amount") or 0)
                settled = min(total - 0.01, float(item.get("settled") or 0) + max(0.0, float(amount)))
                item["settled"] = round(max(0.0, settled), 3)
                return item["settled"]
        return 0.0

    def save(self) -> None:
        self.store.set_state("brainn_world", self.state)

    def snapshot(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        ticks = int(self.state.get("tick_count") or 0)
        materialized = int(self.state.get("materialized") or 0)
        return {
            "tick_count": ticks,
            "exposure": int(self.state.get("exposure") or 0),
            "materialized": materialized,
            "materialize_ratio": round(materialized / ticks, 3) if ticks else 0.0,
            "position": {
                "org": self.state["position"].get("org"),
                "role": self.state["position"].get("role_in_org"),
                "evaluators": self.state["position"].get("evaluators"),
                "alpha": self.state["position"].get("alpha"),
            },
            "clocks": self.state.get("clocks"),
            "exchanges": len(self.state.get("exchanges") or []),
            "appraisals": len(self.state.get("appraisals") or []),
            "shocks": len(self.state.get("shocks") or []),
            "conflict_ticks": int(self.state.get("conflict_ticks") or 0),
            "last_views": [v.get("surface") for v in (self.state.get("views") or [])[-2:]],
        }

    def on_event(self, percept, ctx: dict[str, Any]) -> list:
        return []

    def learn(self, experience: dict[str, Any]) -> None:
        return None
