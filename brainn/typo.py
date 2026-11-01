"""把一句话打错：同音字替换或相邻字颠倒，用于拟真手滑。"""
from __future__ import annotations

import random

# 常见同音/形近错字
CONFUSIONS = {
    "在": "再", "再": "在", "的": "得", "得": "的", "吗": "嘛", "嘛": "吗",
    "那": "哪", "哪": "那", "他": "她", "她": "他", "是": "事", "事": "是",
    "做": "坐", "坐": "做", "吃": "次", "次": "吃", "好": "号", "号": "好",
    "这": "着", "着": "这", "想": "相", "相": "想", "睡": "谁", "谁": "睡",
    "不": "部", "部": "不", "一": "已", "已": "一",
}


def make_typo(text: str) -> str:
    text = text or ""
    if len(text) < 4:
        return ""
    candidates = [i for i, ch in enumerate(text) if ch in CONFUSIONS]
    if candidates:
        i = random.choice(candidates)
        return text[:i] + CONFUSIONS[text[i]] + text[i + 1 :]
    # 没有同音字可换，就随机颠倒相邻两个字
    indexes = [i for i in range(1, len(text)) if text[i].isalnum() and text[i - 1].isalnum()]
    if not indexes:
        return ""
    i = random.choice(indexes)
    chars = list(text)
    chars[i - 1], chars[i] = chars[i], chars[i - 1]
    return "".join(chars)
