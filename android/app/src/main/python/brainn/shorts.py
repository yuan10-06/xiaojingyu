"""短视频：内置示例视频与初始评论（本地模拟，不接真实短视频平台）。

视频使用公开的 Mixkit 免费素材直链（可商用、无水印），在线播放，不占安装包；
断网时页面会提示加载失败，不影响其他功能。
"""
from __future__ import annotations

from typing import Any

BASE = "https://assets.mixkit.co/videos/{vid}/{vid}-720.mp4"

SHORTS: list[dict[str, Any]] = [
    {
        "id": "v1",
        "title": "猫主子陪我加班",
        "desc": "它非要坐键盘上，赶都赶不走。",
        "author": "@猫饼日记",
        "music": "原声 · 猫饼日记",
        "likes": 128000,
        "url": BASE.format(vid=1779),
        "tags": ["猫", "日常"],
        "comments": [
            {"user": "@熬夜冠军", "text": "猫：这个键盘是我的窝"},
            {"user": "@小满", "text": "它是不是在帮你删文件"},
            {"user": "@阿蓝", "text": "同款猫，同款加班"},
        ],
    },
    {
        "id": "v2",
        "title": "戴墨镜的猫",
        "desc": "这猫比我还会装酷。",
        "author": "@一只装酷猫",
        "music": "原声 · 一只装酷猫",
        "likes": 96000,
        "url": BASE.format(vid=49058),
        "tags": ["猫", "搞笑"],
        "comments": [
            {"user": "@奶盖", "text": "这眼神，下一秒就要开口说话"},
            {"user": "@路过的狗", "text": "猫界顶流没跑了"},
        ],
    },
    {
        "id": "v3",
        "title": "下锅前的三十秒",
        "desc": "油一热，魂就回来了。",
        "author": "@阿May做饭",
        "music": "轻快小调 · 阿May",
        "likes": 54000,
        "url": BASE.format(vid=49231),
        "tags": ["美食", "做饭"],
        "comments": [
            {"user": "@干饭人", "text": "这个声音太治愈了"},
            {"user": "@小厨娘", "text": "已经饿了，赔我一份"},
            {"user": "@夜宵搭子", "text": "半夜刷到这个是真的折磨"},
        ],
    },
    {
        "id": "v4",
        "title": "切菜这件小事",
        "desc": "刀工一般，但很解压。",
        "author": "@厨房日记",
        "music": "原声 · 厨房日记",
        "likes": 78000,
        "url": BASE.format(vid=40524),
        "tags": ["美食", "解压"],
        "comments": [
            {"user": "@刀工废物", "text": "我切成这样得半小时"},
            {"user": "@番茄炒蛋", "text": "看别人做饭比自己做香"},
        ],
    },
    {
        "id": "v5",
        "title": "走进海里那一步",
        "desc": "海风大到说话都听不清。",
        "author": "@海边散步",
        "music": "海浪白噪音",
        "likes": 112000,
        "url": BASE.format(vid=1114),
        "tags": ["海边", "治愈"],
        "comments": [
            {"user": "@想去海边", "text": "这个浪声我可以听一整天"},
            {"user": "@橘子汽水", "text": "下次带我一起"},
            {"user": "@咸鱼", "text": "看着就很凉快"},
        ],
    },
    {
        "id": "v6",
        "title": "在花田里跑一段",
        "desc": "跑到喘不上气才算出来玩。",
        "author": "@周末出逃",
        "music": "夏日 · 轻电子",
        "likes": 210000,
        "url": BASE.format(vid=46656),
        "tags": ["周末", "户外"],
        "comments": [
            {"user": "@不想上班", "text": "这才是周末该有的样子"},
            {"user": "@小雏菊", "text": "跑起来的时候头发都在发光"},
        ],
    },
    {
        "id": "v7",
        "title": "椰树底下的日落",
        "desc": "这个颜色只存在十分钟。",
        "author": "@日落收藏家",
        "music": "落日 · 纯音乐",
        "likes": 340000,
        "url": BASE.format(vid=1170),
        "tags": ["日落", "风景"],
        "comments": [
            {"user": "@追光的人", "text": "每天蹲日落的人举手"},
            {"user": "@晚风", "text": "这个粉橙色太不真实了"},
            {"user": "@看海计划", "text": "存下了，当壁纸"},
        ],
    },
    {
        "id": "v8",
        "title": "码头上的海鸥",
        "desc": "海鸥比人还准时。",
        "author": "@码头日常",
        "music": "海鸥叫 · 现场声",
        "likes": 67000,
        "url": BASE.format(vid=1197),
        "tags": ["海边", "慢生活"],
        "comments": [
            {"user": "@钓鱼佬", "text": "它们在等谁投喂呢"},
            {"user": "@风平浪静", "text": "这种地方发呆最合适"},
        ],
    },
    {
        "id": "v9",
        "title": "白伞和绿浪",
        "desc": "从上往下看，海是果冻色的。",
        "author": "@航拍中国",
        "music": "轻音乐 · 航拍",
        "likes": 150000,
        "url": BASE.format(vid=51500),
        "tags": ["航拍", "海边"],
        "comments": [
            {"user": "@夏天限定", "text": "这个海水颜色我可以看一年"},
            {"user": "@墨镜", "text": "伞下面应该很晒吧"},
        ],
    },
    {
        "id": "v10",
        "title": "山里的那条瀑布",
        "desc": "声音比画面还大。",
        "author": "@山里信号差",
        "music": "流水声 · 现场",
        "likes": 88000,
        "url": "https://assets.mixkit.co/active_storage/video_items/100174/1721166924/100174-video-720.mp4",
        "tags": ["旅行", "自然"],
        "comments": [
            {"user": "@徒步中", "text": "走到这儿腿已经不是自己的了"},
            {"user": "@山系", "text": "隔着屏幕都能听见水声"},
        ],
    },
    {
        "id": "v11",
        "title": "泳池里的光斑",
        "desc": "夏天的声音就是这个。",
        "author": "@夏日游泳",
        "music": "水声 · 氛围",
        "likes": 45000,
        "url": BASE.format(vid=1280),
        "tags": ["夏天", "解压"],
        "comments": [
            {"user": "@旱鸭子", "text": "不会游泳但爱看这个"},
            {"user": "@蓝色", "text": "这个蓝好干净"},
        ],
    },
    {
        "id": "v12",
        "title": "黑底上的烟",
        "desc": "盯着看会走神。",
        "author": "@视觉实验",
        "music": "低频 · 实验",
        "likes": 23000,
        "url": BASE.format(vid=1968),
        "tags": ["视觉", "氛围"],
        "comments": [
            {"user": "@失眠患者", "text": "凌晨三点看这个更睡不着"},
            {"user": "@雾", "text": "像一段循环的梦"},
        ],
    },
]


def find_short(short_id: str) -> dict[str, Any] | None:
    for s in SHORTS:
        if s["id"] == short_id:
            return s
    return None


def list_items() -> list[dict[str, Any]]:
    """列表接口不把初始评论打包进去，避免首屏数据过大。"""
    out = []
    for s in SHORTS:
        out.append({
            "id": s["id"],
            "title": s["title"],
            "desc": s["desc"],
            "author": s["author"],
            "music": s["music"],
            "likes": s["likes"],
            "url": s["url"],
            "tags": s["tags"],
        })
    return out


def seed_comments(short_id: str) -> list[dict[str, Any]]:
    s = find_short(short_id)
    if not s:
        return []
    return [{"user": c["user"], "text": c["text"]} for c in s.get("comments", [])]
