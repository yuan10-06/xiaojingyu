"""emoji：识别他发的表情，也给她挑一个符合情绪的表情。"""
from __future__ import annotations

import random
import re

_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\uFE0F\u200D\u20E3"
    "]+"
)

EMOJI_TAGS = {
    "😭": ("sad", "崩溃、哭、笑到不行"),
    "😢": ("sad", "难过"),
    "🥺": ("aggrieved", "委屈、求哄"),
    "😡": ("angry", "生气"),
    "😠": ("angry", "不爽"),
    "😤": ("proud", "不服气、赌气"),
    "😂": ("laugh", "笑死"),
    "🤣": ("laugh", "笑到打滚"),
    "💀": ("speechless", "无语、笑死"),
    "🙄": ("speechless", "翻白眼、无语"),
    "😅": ("shy", "尴尬、心虚"),
    "😳": ("shy", "害羞"),
    "🥰": ("miss", "喜欢、贴贴"),
    "😍": ("miss", "心动"),
    "😘": ("miss", "亲亲"),
    "🤗": ("care", "抱抱、安慰"),
    "😴": ("sleepy", "困"),
    "💤": ("sleepy", "想睡"),
    "🍚": ("hungry", "干饭"),
    "🍜": ("hungry", "想吃"),
    "😋": ("hungry", "馋"),
    "🤔": ("confused", "思考、疑惑"),
    "😵‍💫": ("confused", "晕"),
    "👀": ("popcorn", "吃瓜、看戏"),
    "🍿": ("popcorn", "吃瓜"),
    "😉": ("tease", "逗你"),
    "😊": ("happy", "开心"),
    "😌": ("happy", "满足"),
}

TAG_EMOJIS = {
    "happy": ["😊", "✨"],
    "shy": ["😅", "😳", "🥺"],
    "angry": ["😡", "😠", "😤"],
    "sad": ["😢", "😭", "🥺"],
    "hungry": ["🍚", "🍜", "😋"],
    "sleepy": ["😴", "💤", "🥱"],
    "tease": ["😉", "🙄", "👀"],
    "miss": ["🥰", "😘", "💗"],
    "proud": ["😤", "😎"],
    "confused": ["🤔", "😵‍💫"],
    "ok": ["👌"],
    "refuse": ["🙅‍♀️", "😤"],
    "laugh": ["😂", "🤣", "💀"],
    "speechless": ["😅", "🙄", "💀"],
    "popcorn": ["👀", "🍿"],
    "aggrieved": ["🥺", "😢"],
    "care": ["🤗", "💗"],
    "neutral": ["😊"],
}

HINTS = {
    "sad": "他用了难过的表情，先接住情绪，别开玩笑。",
    "angry": "他有点火气，先弄明白原因，别硬顶。",
    "laugh": "他在笑，陪他闹。",
    "speechless": "他在无语吐槽，可以接梗。",
    "shy": "他有点害羞或尴尬，可以逗一下但别戳痛。",
    "miss": "他在示好，接住，可以嘴硬但别冷淡。",
    "care": "他在求安慰或抱抱，语气放软。",
    "sleepy": "他困了，回复短一点。",
    "hungry": "他馋了/饿了，可以聊吃的。",
    "confused": "他没看懂，解释清楚一点。",
    "popcorn": "他在吃瓜看戏，可以一起八卦。",
    "tease": "他在逗你，可以怼回去。",
    "proud": "他在嘴硬/赌气，可以顺毛也可以拆台。",
    "aggrieved": "他在委屈/求哄，先哄，别讲道理。",
    "neutral": "他情绪平稳。",
}

QQ_FACE = {
    "5": "😭", "9": "😭", "11": "😡", "15": "😢", "8": "😴",
    "12": "😜", "13": "😁", "14": "🙂", "2": "😍", "6": "😳",
    "10": "😅", "16": "😎", "18": "😱", "20": "🥺", "23": "😭",
}


def face(face_id: str) -> str:
    return QQ_FACE.get(str(face_id), "😐")


def detect(text: str) -> dict | None:
    text = text or ""
    found = []
    label = "neutral"
    meanings = []
    for emoji, (tag, meaning) in EMOJI_TAGS.items():
        if emoji in text:
            found.append(emoji)
            if label == "neutral":
                label = tag
            meanings.append(meaning)
    if not found:
        return None
    if "😭" in found and any(w in text for w in ("笑死", "哈哈", "绷", "乐死", "笑到")):
        label = "laugh"
        meanings = ["笑到哭、绷不住"]
    return {
        "label": label,
        "intensity": 0.75,
        "emojis": found[:4],
        "meaning": "、".join(dict.fromkeys(meanings))[:60],
        "hint": HINTS.get(label, ""),
    }


def pick(tag: str | None) -> str:
    pool = TAG_EMOJIS.get(tag or "neutral") or TAG_EMOJIS["neutral"]
    return random.choice(pool)


def strip(text: str) -> str:
    """去掉模型自己加的 emoji，让她只靠系统按低概率追加表情。"""
    return _EMOJI_RE.sub("", text or "").strip()
