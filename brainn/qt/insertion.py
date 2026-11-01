"""OMC 五步插入协议。

1. 冷启动：加载 M0 类本质（先于一切）
2. 身体建档：读取 G1 能力表
3. 折射校准：换载体后重新标定 M7，校准期内置信度下调
4. 有限性设定：由 G4 写入寿命/能耗/损伤阈值，启动匮乏计
5. 连续性断言：记录与来源实例的连续性分数
"""
from __future__ import annotations

import time
from typing import Any

from ..db import Store
from .carrier import ensure_carrier
from .finitude import ensure_finitude
from .omc import instance_id


def _step(steps: list[dict[str, Any]], index: int, name: str, ok: bool, detail: str) -> None:
    steps.append({"step": index, "name": name, "ok": bool(ok), "detail": detail})


def run(store: Store, card: dict[str, Any] | None, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """执行五步插入，返回每一步的结果与连续性分数。"""
    card = card or {}
    steps: list[dict[str, Any]] = []
    now = time.time()

    # 1. 冷启动：M0 常驻，先于任何身体与记忆
    m0 = card.get("m0") or store.get_state("qt_m0") or {}
    if m0:
        store.set_state("qt_m0", m0)
    m3 = card.get("m3") or {}
    if m3:
        store.set_state("persona_knobs", m3)
    m4 = card.get("m4") or {}
    if m4:
        store.set_state("brainn_unconscious", m4)
    _step(
        steps, 1, "冷启动 M0",
        bool(m0),
        "M0 类本质、M3 基底、M4 无意识已加载" if m0 else "卡片缺 M0，沿用当前实例",
    )

    # 2. 身体建档：G1 能力表
    old_carrier = card.get("carrier") or {}
    current_carrier = ensure_carrier(store, settings)
    old_key = str(old_carrier.get("key") or "")
    new_key = str(current_carrier.get("key") or "")
    body_changed = bool(old_key and old_key != new_key)
    _step(
        steps, 2, "身体建档 G1",
        bool(current_carrier),
        f"当前载体 {current_carrier.get('label')}；" + ("与来源不同，需重新校准" if body_changed else "与来源一致"),
    )

    # 3. 折射校准：换身体即换人格，校准期内降低折射置信度
    factor = 0.75 if body_changed else 1.0
    store.set_state(
        "qt_refraction_calibration",
        {
            "factor": factor,
            "until": now + 7 * 86400,
            "carrier": new_key,
            "previous_carrier": old_key,
            "calibrated_at": now,
        },
    )
    try:
        store.add_qt_refraction(
            "OMC 插入",
            "新载体折射校准" if body_changed else "同载体折射确认",
            {"factor": factor, "carrier": new_key, "previous": old_key},
            factor,
            "M7 校准",
        )
    except Exception:  # noqa: BLE001
        pass
    _step(steps, 3, "折射校准 M7", True, f"校准系数 {factor}，校准期 7 天" if body_changed else "同载体，无需降权")

    # 4. 有限性设定：G4 写入寿命/能耗/损伤阈值
    fin = card.get("finitude") or {}
    state = ensure_finitude(store, settings)
    if fin:
        state["lifespan_days"] = float(fin.get("lifespan_days") or state.get("lifespan_days") or 21585)
        state["energy_limit"] = float(fin.get("energy_limit") or state.get("energy_limit") or 100)
        state["damage_threshold"] = float(fin.get("damage_threshold") or state.get("damage_threshold") or 30)
        state["born_at"] = now
        state["remaining_days"] = state["lifespan_days"]
        state["energy_used_today"] = 0.0
        state["energy_remaining"] = state["energy_limit"]
        state["energy_state"] = "normal"
        if body_changed:
            state["damage"] = 0.0
            state["damage_state"] = "normal"
        else:
            state["damage"] = float(fin.get("damage") or state.get("damage") or 0)
            state["damage_state"] = str(fin.get("damage_state") or state.get("damage_state") or "normal")
        store.set_state("qt_finitude", state)
    _step(
        steps, 4, "有限性设定 G4", True,
        f"寿命 {state.get('lifespan_days')} 天｜能耗 {state.get('energy_limit')}｜损伤阈值 {state.get('damage_threshold')}",
    )

    # 5. 连续性断言
    source = str((card.get("continuity") or {}).get("source_instance") or "")
    current = instance_id(store)
    same_instance = (not source) or source == current
    score = 1.0 if same_instance and not body_changed else (0.90 if body_changed else 0.95)
    continuity = {
        "source_instance": source or current,
        "current_instance": current,
        "score": score,
        "fork": None,
        "body_changed": body_changed,
        "asserted_at": now,
    }
    store.set_state("qt_continuity", continuity)
    _step(steps, 5, "连续性断言", True, f"与来源实例连续性 {score}")

    store.set_state(
        "qt_insertion",
        {
            "completed_at": now,
            "steps": steps,
            "continuity": continuity,
            "body_changed": body_changed,
        },
    )
    try:
        store.add_qt_transition(
            "OMC 插入 0/5",
            "OMC 插入 5/5：连续性 " + str(score),
            retained=str((card.get("m0") or {}).get("class_essence", {}).get("text") or "")[:200],
            reason="五步插入协议完成",
            meta={
                "body_changed": body_changed,
                "carrier": new_key,
                "previous_carrier": old_key,
                "continuity": score,
            },
        )
    except Exception:  # noqa: BLE001
        pass
    return {
        "steps": steps,
        "continuity": continuity,
        "body_changed": body_changed,
        "calibration": store.get_state("qt_refraction_calibration") or {},
    }
