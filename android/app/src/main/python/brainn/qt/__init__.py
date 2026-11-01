"""CS-SNN（QT）融合层：逻辑命名映射、账本与记忆卡。

不接管任何生产逻辑，只提供：
- mapping：BrainN 旧模块 / 旧 P3 编号 → QT 名称的双向映射
- ledger：QT 八个账本的轻量读写
- finitude：G4 有限性参数
- omc：记忆卡 continuity / finitude
"""
from .mapping import (
    QT_MODULES,
    MODULE_ALIASES,
    LEGACY_TO_QT,
    to_qt,
    from_qt,
    legacy_to_qt,
    qt_to_legacy,
    summary,
)
from .carrier import carrier_state, carrier_text, ensure_carrier
from .finitude import ensure_finitude, finitude_hint, finitude_state
from .insertion import run as run_insertion
from .omc import instance_id, card_fields
from .refraction import refract
from .tensions import detect_conflict

__all__ = [
    "QT_MODULES",
    "MODULE_ALIASES",
    "LEGACY_TO_QT",
    "to_qt",
    "from_qt",
    "legacy_to_qt",
    "qt_to_legacy",
    "summary",
    "ensure_finitude",
    "finitude_state",
    "finitude_hint",
    "instance_id",
    "card_fields",
    "detect_conflict",
    "refract",
    "run_insertion",
    "ensure_carrier",
    "carrier_state",
    "carrier_text",
]
