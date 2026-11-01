"""影子运行时：把 12 模块中的决策链路跑通，但不影响表达系统。

P3 第一版只做本地规则计算 + 落日志；不调用 LLM、不改线上输出。
"""
from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any

from ..db import Store
from ..qt.evolution import EvolutionModel
from ..qt.finitude import FinitudeModel, ensure_finitude
from ..qt.refraction import refract
from ..modules.conflict import ConflictModel
from ..modules.drives import DriveModel
from ..modules.narrative import NarrativeModel
from ..modules.perception import PersonModels
from ..modules.practice import PracticeModel
from ..modules.social_bridge import SocialBidder
from ..modules.time_model import TimeBudgetModel
from ..modules.unconscious import UnconsciousModel
from ..modules.world import WorldModel
from ..recognition import RecognitionDrive
from .arbitration import Arbitrator, AuctionConfig
from .budget import CombinedBudget
from .contracts import Percept


class ShadowRuntime:
    def __init__(
        self,
        store: Store,
        settings: dict[str, Any],
        clock,
        body,
        social,
        memory,
        affect=None,
        thrownness=None,
        intuition=None,
        user_model=None,
        persona_cfg: dict[str, Any] | None = None,
    ):
        self.store = store
        self.settings = settings
        self.persona_cfg = persona_cfg or {}
        self.last_refraction: dict[str, Any] = {}
        self.affect = affect
        self.thrownness = thrownness
        self.intuition = intuition
        self.user_model = user_model
        cfg = settings.get("brainn", {}) or {}
        weights = cfg.get("weights", {}) or {}
        auction = weights.get("auction", {}) or {}
        self.arbitrator = Arbitrator(
            AuctionConfig(
                threshold=float(auction.get("threshold", 0.35)),
                cost_weight=float(auction.get("cost_weight", 0.50)),
            )
        )
        self.time_model = TimeBudgetModel(store, clock, weights.get("budget", {}))
        self.world = WorldModel(store, settings, clock, social, thrownness)
        self.perception = PersonModels(store, social, self.world, user_model)
        self.drives = DriveModel(store, settings)
        self.practice = PracticeModel(
            store, settings, clock, self.world, memory, intuition
        )
        self.recognition = (
            RecognitionDrive(store, settings, user_model, self.practice)
            if user_model is not None
            else None
        )
        self.practice_enabled = bool((cfg.get("practice") or {}).get("enabled", True))
        self.social = SocialBidder(social)
        self.conflict = ConflictModel(store, weights, thrownness)
        self.unconscious = UnconsciousModel(store, weights)
        self.narrative = NarrativeModel(store, settings)
        self.budget = CombinedBudget(body, self.time_model, weights.get("budget", {}))
        self.memory = memory
        self.body = body
        self.evolution = EvolutionModel(store, memory, settings)
        self.finitude = FinitudeModel(store, settings)
        try:
            self.practice.backfill_qt_ledgers()
        except Exception:  # noqa: BLE001
            pass

    def round(
        self,
        percept: Percept,
        *,
        asleep: bool = False,
        outcome: dict[str, Any] | None = None,
        gap_hours: float | None = None,
    ) -> dict[str, Any]:
        with self.store.batch():
            return self._round(
                percept, asleep=asleep, outcome=outcome, gap_hours=gap_hours
            )

    def _round(
        self,
        percept: Percept,
        *,
        asleep: bool = False,
        outcome: dict[str, Any] | None = None,
        gap_hours: float | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        now = time.time()
        if gap_hours is None:
            last = self.store.last_message_ts()
            gap_hours = (now - last) / 3600 if last else 0.0
        ctx = {"asleep": asleep, "gap_hours": gap_hours, "now": now}
        outcome = outcome or {}
        try:
            ensure_finitude(self.store, self.settings)
        except Exception:  # noqa: BLE001
            pass

        self.perception.on_event(percept, ctx)
        labor_delta = 0.0
        if self.practice_enabled:
            self.practice.tick(now, ctx)
            labor_delta = self.practice.drain_fatigue_delta()
            if abs(labor_delta) >= 0.01:
                self.body.state["fatigue"] = max(
                    0.0, min(100.0, float(self.body.state.get("fatigue", 0)) + labor_delta)
                )
        else:
            ctx["activity"] = None
            ctx["schedule"] = []
            ctx["next"] = None
            ctx["exam"] = {}
        self.world.tick(now, ctx)
        if self.recognition is not None:
            self.recognition.tick(now, ctx)
        world_drive = self.world.consume_drive_deltas()
        self.finitude.tick(
            now,
            getattr(self.body, "state", {}) or {},
            labor_delta=labor_delta,
            asleep=asleep,
        )
        self.time_model.tick(now, ctx)
        self.drives.tick(now, ctx)
        self.drives.apply_finitude(
            self.store.get_state("qt_finitude") or {},
            getattr(self.body, "state", {}) or {},
        )
        if world_drive:
            self.drives.apply_practice(world_drive)
        self.drives.on_event(percept, ctx)
        if self.practice_enabled:
            self.practice.on_event(percept, ctx)
        self.conflict.tick(now, ctx)
        self.unconscious.tick(now, ctx)
        self.unconscious.on_event(percept, ctx)
        self.narrative.tick(now, ctx)

        # M7：四项介质把输入弯折成映像；结果给表达层参考，并写入账本
        self.last_refraction = refract(
            str(getattr(percept, "text", "") or ""),
            getattr(percept, "emotion", {}) or {},
            self.perception.state.get("user") or {},
            (self.drives.snapshot({}).get("levels") or {}),
            self.unconscious.state,
            self.persona_cfg,
        )
        cal = self.store.get_state("qt_refraction_calibration") or {}
        factor = float(cal.get("factor") or 1.0)
        if float(cal.get("until") or 0) and now > float(cal.get("until") or 0):
            factor = 1.0
        if factor < 1.0:
            self.last_refraction["confidence"] = round(
                float(self.last_refraction.get("confidence") or 0) * factor, 2
            )
            self.last_refraction["calibration"] = factor

        proposals = []
        proposals.extend(self.drives.propose(ctx))
        proposals.extend(self.social.propose(ctx))
        proposals.extend(self.practice.propose(ctx))
        if self.recognition is not None:
            proposals.extend(self.recognition.propose(now))
        proposals = self.practice.modulate_proposals(proposals, ctx)

        decision = self.arbitrator.decide(proposals, self.budget)
        distortion = self.conflict.distort(decision, ctx)
        bypass = self.unconscious.maybe_bypass(decision, ctx)
        if self.affect is not None:
            self.affect.tick(now, ctx)
            self.affect.appraise(decision, distortion, outcome, ctx)
        narrative_entry = self.narrative.observe(
            decision, outcome, {**ctx, "distortion": distortion, "bypass": bypass}
        )
        self.drives.learn(outcome)
        self.conflict.learn(outcome)
        # M9→M10→M11：累积过阈值的张力在本轮提升为“两种说法并存”
        evolution = self.evolution.evaluate()

        record = {
            "percept": asdict(percept),
            "states": self.snapshot(),
            "proposals": [asdict(p) for p in proposals],
            "budget": round(self.budget.multiplier(proposals[0]), 3) if proposals else 1.0,
            "winner": asdict(decision.winner) if decision.winner else {},
            "distortion": distortion,
            "bypass": bypass,
            "action": {
                "intent": decision.intent,
                "score": round(decision.score, 3),
                "rationale": decision.rationale,
            },
            "outcome": outcome,
            "narrative": narrative_entry,
            "evolution": evolution,
            "refraction": self.last_refraction,
            "finitude": self.finitude.snapshot(),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        self.store.add_brainn_transition(record)
        record["refraction_id"] = 0
        try:
            record["refraction_id"] = self.store.add_qt_refraction(
                str(self.last_refraction.get("before") or ""),
                str(self.last_refraction.get("after") or ""),
                self.last_refraction.get("medium") or {},
                float(self.last_refraction.get("confidence") or 0),
                "M7 折射计算",
            )
        except Exception:  # noqa: BLE001
            pass
        return record

    def modules(self) -> list:
        return [
            self.time_model,
            self.perception,
            self.drives,
            self.practice,
            self.world,
            self.social,
            self.conflict,
            self.unconscious,
            self.narrative,
        ]

    def snapshot(self) -> dict[str, Any]:
        return {
            "time": self.time_model.snapshot(),
            "persons": self.perception.snapshot(),
            "drives": self.drives.snapshot(),
            "practice": self.practice.snapshot(),
            "world": self.world.snapshot(),
            "affect": self.affect.snapshot() if self.affect is not None else {},
            "thrownness": self.thrownness.snapshot() if self.thrownness is not None else {},
            "user_model": self.user_model.snapshot() if self.user_model is not None else {},
            "recognition": self.recognition.snapshot() if self.recognition is not None else {},
            "social": self.social.snapshot(),
            "conflict": self.conflict.snapshot(),
            "unconscious": self.unconscious.snapshot(),
            "narrative": self.narrative.snapshot(),
            "evolution": self.evolution.snapshot(),
            "finitude": self.finitude.snapshot(),
        }
