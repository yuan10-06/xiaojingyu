"""M7 折射：用四项介质把输入弯折成映像，而不只是记一条日志。

四项介质：
- 内化结构（人物模型里的关系深度/信任/矛盾）
- 个体基底（人格核心特质）
- 无意识（习惯与条件反射链）
- 当前匮乏（驱力模型里最高的需求）

输出一段可读的“读法”，供表达层参考；不替代模型判断。
"""
from __future__ import annotations

from typing import Any

NEED_WORDS: dict[str, tuple[str, ...]] = {
    "rest": ("累", "困", "熬夜", "睡", "没精神", "疲惫", "休息"),
    "belonging": ("想你", "陪", "一个人", "无聊", "冷落", "在吗"),
    "relationship": ("我们", "关系", "喜欢", "讨厌", "冷淡"),
    "mattering": ("夸", "厉害", "谢谢", "没用", "失望", "看不起"),
    "curiosity": ("为什么", "怎么", "你知道", "听说", "是不是"),
    "task": ("帮我", "作业", "考试", "上班", "兼职"),
}

NEED_FRAME = {
    "rest": "先把这句话读成了“他累了/他需要歇一下”",
    "belonging": "先注意到“他是不是想我了/他需要人陪”",
    "relationship": "先在意“我们之间现在是什么状态”",
    "mattering": "先在意“他有没有把我当回事”",
    "curiosity": "先被“为什么会这样”勾住",
    "task": "先判断“这是不是要我帮忙”",
}

TRAIT_FRAME = {
    "护短": "会先护着他，不急着讲道理",
    "嘴硬心软": "嘴上会硬一点，心里其实在担心",
    "小傲娇": "会先端着，不马上承认在意",
    "吃货": "容易把话题拐到吃的上",
}


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


def refract(
    text: str,
    emotion: dict[str, Any] | None,
    person: dict[str, Any] | None,
    drive_levels: dict[str, Any] | None,
    unconscious: dict[str, Any] | None,
    persona_cfg: dict[str, Any] | None,
) -> dict[str, Any]:
    raw = str(text or "").strip()
    emotion = emotion or {}
    person = person or {}
    persona = persona_cfg or {}
    levels = drive_levels or {}
    un = unconscious or {}

    # 1) 当前匮乏：取最高的驱力，并看它有没有在句子里被触发
    ranked = sorted(
        ((str(k), float(v or 0)) for k, v in levels.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    top_drive, top_level = (ranked[0] if ranked else ("belonging", 50.0))
    need_hits = [w for w in NEED_WORDS.get(top_drive, ()) if w in raw]
    need_note = ""
    if need_hits:
        need_note = NEED_FRAME.get(top_drive, "先按自己的需要去理解这句话")
    elif top_level >= 65:
        need_note = f"此刻{top_drive}偏高，注意力会先往那边偏"

    # 2) 内化结构：关系越近越软，矛盾越高越容易读成对抗
    rel = person.get("relation") or {}
    depth = float(rel.get("depth", 0) or 0)
    conflict = float(rel.get("conflict", 0) or 0)
    relation_note = ""
    if conflict >= 30:
        relation_note = "关系里有矛盾，这句话容易被读成带刺"
    elif depth >= 55:
        relation_note = "关系近，会先往亲近的方向理解"
    elif depth <= 15:
        relation_note = "关系还浅，会先保持客气和距离"

    # 3) 个体基底：核心特质决定第一反应
    traits = [str(t) for t in (persona.get("core_traits") or [])]
    trait_note = next((TRAIT_FRAME[t] for t in traits if t in TRAIT_FRAME), "")

    # 4) 无意识：条件反射链被触发时，先冒出一个旧反应
    unconscious_note = ""
    for chain in un.get("chains") or []:
        trigger = str(chain.get("trigger") or "")
        if trigger and trigger in raw and float(chain.get("strength", 0) or 0) >= 0.3:
            unconscious_note = f"旧反应先冒出来：{chain.get('response')}"
            break
    if not unconscious_note:
        habits = un.get("habits") or {}
        hit = next((h for h in habits if h and h in raw), "")
        if hit:
            unconscious_note = f"习惯性地带出“{hit}”"

    # 5) 情绪读数：他此刻的情绪会改变读法的温度
    label = str(emotion.get("label") or "neutral")
    intensity = float(emotion.get("intensity") or 0)
    emotion_note = ""
    if label in ("sad", "tired", "anxious") and intensity >= 0.4:
        emotion_note = "他情绪低，会先接住情绪，不急着讲道理"
    elif label in ("angry",) and intensity >= 0.4:
        emotion_note = "他在气头上，会先防着一点"
    elif label in ("happy", "love") and intensity >= 0.4:
        emotion_note = "他心情好，会跟着松一点"

    notes = [x for x in (need_note, relation_note, trait_note, unconscious_note, emotion_note) if x]
    after = "；".join(notes) if notes else "先按字面听，不急着下判断"
    confidence = _clamp(0.35 + len(notes) * 0.1, 0.35, 0.85)
    return {
        "before": raw[:200],
        "after": after[:240],
        "focus": need_hits,
        "medium": {
            "need": {"drive": top_drive, "level": round(top_level, 2), "hits": need_hits},
            "internalized": {"depth": depth, "conflict": conflict},
            "baseline": traits,
            "unconscious": unconscious_note,
            "emotion": {"label": label, "intensity": intensity},
        },
        "confidence": round(confidence, 2),
    }
