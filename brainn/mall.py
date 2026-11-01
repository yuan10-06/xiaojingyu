"""拼单商城：内置商品与订单（本地模拟，不接真实电商平台）。"""
from __future__ import annotations

from typing import Any

GOODS: list[dict[str, Any]] = [
    {
        "id": "g1", "cat": "9.9 包邮", "name": "原木抽纸 4 层 30 包整箱",
        "price": 9.9, "origin": 19.9, "sales": 128000, "emoji": "🧻", "color": "#f2f2f2",
        "tags": ["9.9 包邮", "30 天最低价"],
        "specs": ["整箱 30 包", "整箱 24 包"],
    },
    {
        "id": "g2", "cat": "家居", "name": "洗衣液 2kg 补充装 除菌留香",
        "price": 19.9, "origin": 39.9, "sales": 86000, "emoji": "🧴", "color": "#dfe9f7",
        "tags": ["百亿补贴", "买一送一"],
        "specs": ["2kg 单袋", "2kg 两袋"],
    },
    {
        "id": "g3", "cat": "数码", "name": "半入耳蓝牙耳机 5.3 长续航",
        "price": 39.9, "origin": 129, "sales": 210000, "emoji": "🎧", "color": "#e8e8e8",
        "tags": ["百亿补贴", "30 天试用"],
        "specs": ["白色", "黑色"],
    },
    {
        "id": "g4", "cat": "数码", "name": "Type-C 快充数据线 2 米 3 条装",
        "price": 12.9, "origin": 29.9, "sales": 156000, "emoji": "🔌", "color": "#f5efe4",
        "tags": ["9.9 包邮", "支持 66W"],
        "specs": ["1.5 米 2 条", "2 米 3 条"],
    },
    {
        "id": "g5", "cat": "零食", "name": "零食大礼包 混合 20 包",
        "price": 29.9, "origin": 59.9, "sales": 94000, "emoji": "🍪", "color": "#ffe6d6",
        "tags": ["百亿补贴", "坏果包赔"],
        "specs": ["20 包混合", "30 包加量"],
    },
    {
        "id": "g6", "cat": "零食", "name": "柳州螺蛳粉 5 袋装 加臭加辣",
        "price": 24.9, "origin": 39.9, "sales": 73000, "emoji": "🍜", "color": "#ffe3c2",
        "tags": ["9.9 包邮", "送腐竹"],
        "specs": ["5 袋", "10 袋"],
    },
    {
        "id": "g7", "cat": "家居", "name": "棉拖鞋 加厚防滑 一对装",
        "price": 16.9, "origin": 35, "sales": 48000, "emoji": "🩴", "color": "#e9e2f7",
        "tags": ["买一送一", "包退换"],
        "specs": ["38-39", "40-41", "42-43"],
    },
    {
        "id": "g8", "cat": "家居", "name": "厨房抽拉式水龙头 全铜",
        "price": 59, "origin": 129, "sales": 23000, "emoji": "🚰", "color": "#e2eef7",
        "tags": ["百亿补贴", "上门安装"],
        "specs": ["标准款", "加长款"],
    },
    {
        "id": "g9", "cat": "数码", "name": "手机壳 透明防摔 送钢化膜",
        "price": 6.9, "origin": 19.9, "sales": 320000, "emoji": "📱", "color": "#f0f0f0",
        "tags": ["9.9 包邮", "型号齐全"],
        "specs": ["iPhone 15", "小米 14", "华为 Mate 60"],
    },
    {
        "id": "g10", "cat": "家居", "name": "保温杯 316 不锈钢 500ml",
        "price": 29.9, "origin": 69, "sales": 67000, "emoji": "🥤", "color": "#e6f2ea",
        "tags": ["百亿补贴", "24 小时保温"],
        "specs": ["雾蓝", "奶白", "墨绿"],
    },
    {
        "id": "g11", "cat": "零食", "name": "每日坚果 30 包 混合装",
        "price": 34.9, "origin": 79, "sales": 58000, "emoji": "🥜", "color": "#f7eddb",
        "tags": ["百亿补贴", "独立小包"],
        "specs": ["30 包", "60 包"],
    },
    {
        "id": "g12", "cat": "9.9 包邮", "name": "加厚垃圾袋 100 只 抽绳",
        "price": 8.9, "origin": 16.9, "sales": 210000, "emoji": "🗑", "color": "#ececec",
        "tags": ["9.9 包邮", "加厚不易破"],
        "specs": ["45×50cm 100 只", "60×80cm 50 只"],
    },
]

CATS = ["推荐", "百亿补贴", "9.9 包邮", "家居", "零食", "数码"]


def find_goods(goods_id: str) -> dict[str, Any] | None:
    for g in GOODS:
        if g["id"] == goods_id:
            return g
    return None


def price_lines(lines: list[dict[str, Any]]) -> dict[str, Any]:
    """按商品价重算；同规格合并数量。"""
    out: list[dict[str, Any]] = []
    total = 0.0
    for ln in lines or []:
        goods = find_goods(str(ln.get("id") or ""))
        if not goods:
            continue
        spec = str(ln.get("spec") or (goods["specs"][0] if goods.get("specs") else ""))[:40]
        try:
            qty = int(ln.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        qty = max(0, min(20, qty))
        if qty <= 0:
            continue
        price = float(goods["price"])
        total += price * qty
        out.append({
            "id": goods["id"],
            "name": goods["name"],
            "spec": spec,
            "price": price,
            "qty": qty,
            "emoji": goods.get("emoji", ""),
        })
    if not out:
        return {"items": [], "total": 0.0, "ok": False}
    return {"items": out, "total": round(total, 2), "ok": True}
