"""用户情绪检测：轻量关键词 + 强度，用于即时调整语气。"""
from __future__ import annotations

LEXICON = {
    "sad": ("难过", "伤心", "想哭", "哭了", "委屈", "失望", "心累", "崩溃", "难受", "郁闷", "不开心"),
    "angry": ("生气", "烦死", "气死", "滚", "闭嘴", "讨厌", "恶心", "离谱", "妈的", "操"),
    "tired": ("好累", "累死", "困死", "熬夜", "没睡", "加班", "体测", "撑不住", "累"),
    "anxious": ("焦虑", "紧张", "担心", "害怕", "慌", "怎么办", "不安", "压力"),
    "happy": ("开心", "高兴", "哈哈", "爽", "太好了", "成功", "赢了", "幸福"),
    "love": ("想你", "喜欢你", "爱你", "宝贝", "老婆", "抱抱", "亲亲"),
}

HINTS = {
    "sad": "他情绪低落，先接住情绪，别开玩笑、别讲大道理，语气放软，多问一句。",
    "angry": "他在气头上，先弄明白他在气什么，别硬顶；如果是冲你来的，先别急着辩解。",
    "tired": "他很累，回复短一点，催他休息或吃点东西，别再给他派活。",
    "anxious": "他有点焦虑，先安抚，帮他拆成一两件能做的事，别轻飘飘说“没事”。",
    "happy": "他心情好，可以陪他闹、接梗，别泼冷水。",
    "love": "他在表达亲近，接住，可以害羞或嘴硬，但别冷淡。",
    "neutral": "他情绪平稳，正常聊天。",
}


def detect(text: str) -> dict[str, object]:
    text = text or ""
    best_label = "neutral"
    best_score = 0.0
    evidence = ""
    for label, words in LEXICON.items():
        hits = [w for w in words if w in text]
        if not hits:
            continue
        score = 0.35 + 0.2 * len(hits)
        if "!" in text or "！" in text or "。。。" in text:
            score += 0.15
        if len(text) <= 8:
            score += 0.1
        score = min(1.0, score)
        if score > best_score:
            best_label, best_score, evidence = label, score, hits[0]
    return {
        "label": best_label,
        "intensity": round(best_score, 2),
        "evidence": evidence,
        "hint": HINTS.get(best_label, ""),
    }
