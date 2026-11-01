"""让标点更像手机聊天：偶尔丢句号、逗号变空格、问号不规范。"""
from __future__ import annotations

import random
import re


def loosen(text: str, strength: float = 0.55) -> str:
    t = (text or "").strip()
    if not t or "http" in t:
        return t
    if random.random() > max(0.0, min(1.0, strength)):
        return t
    if t.endswith("。"):
        t = t[:-1]
    if random.random() < 0.4:
        t = t.replace("，", " ")
    if random.random() < 0.25:
        t = t.replace("！", "!")
    if random.random() < 0.2:
        t = t.replace("？", "?")
    if random.random() < 0.12 and not t.endswith(("？", "?", "…", "!")):
        t += random.choice(["…", "呀", "啊"])
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()
