"""饭点：内置外卖店铺与菜单。

纯本地模拟：不做真实下单、不接任何外卖平台。
订单只落本机数据库，进度由前端按时间推算。
"""
from __future__ import annotations

import random
from typing import Any

SHOPS: list[dict[str, Any]] = [
    {
        "id": "laoshengchang",
        "name": "老盛昌汤包",
        "cat": "快餐",
        "rate": 4.8,
        "sales": 3200,
        "fee": 2,
        "min": 15,
        "dist": 1.2,
        "emoji": "🥟",
        "color": "#f6a623",
        "cover": "food/shop_laoshengchang.jpg",
        "tags": ["满减", "准时宝"],
        "promos": [{"min": 25, "off": 3, "name": "满 25 减 3"}],
        "notice": "本店汤包现包现蒸，出餐约 12 分钟。",
        "items": [
            {"id": "s1", "group": "热销", "name": "鲜肉汤包", "price": 12, "sales": 860, "desc": "6 只 / 笼，皮薄汁多", "emoji": "🥟", "img": "food/item_s1.jpg"},
            {"id": "s2", "group": "热销", "name": "小笼包", "price": 10, "sales": 720, "desc": "6 只 / 笼，蘸醋更香", "emoji": "🥟"},
            {"id": "s3", "group": "主食", "name": "葱油拌面", "price": 9, "sales": 430, "desc": "现拌，葱油另装", "emoji": "🍜"},
            {"id": "s4", "group": "主食", "name": "排骨年糕", "price": 18, "sales": 260, "desc": "炸猪排 + 宁波年糕", "emoji": "🍖"},
            {"id": "s5", "group": "小吃", "name": "茶叶蛋", "price": 2.5, "sales": 980, "desc": "卤足 4 小时", "emoji": "🥚"},
            {"id": "s6", "group": "饮品", "name": "现磨豆浆", "price": 4, "sales": 610, "desc": "无糖 / 微糖", "emoji": "🥛"},
        ],
    },
    {
        "id": "yangguofu",
        "name": "杨国福麻辣烫",
        "cat": "麻辣烫",
        "rate": 4.7,
        "sales": 4100,
        "fee": 3,
        "min": 20,
        "dist": 1.8,
        "emoji": "🌶",
        "color": "#e04b3a",
        "cover": "food/shop_yangguofu.jpg",
        "tags": ["满 30 减 5", "新客立减"],
        "promos": [{"min": 30, "off": 5, "name": "满 30 减 5"}],
        "notice": "自选菜品按份计价，辣度可在备注里写。",
        "items": [
            {"id": "y1", "group": "热销", "name": "自选麻辣烫", "price": 22, "sales": 1560, "desc": "荤素搭配，微辣 / 中辣", "emoji": "🍲", "img": "food/item_y1.jpg"},
            {"id": "y2", "group": "热销", "name": "肥牛麻辣烫", "price": 28, "sales": 990, "desc": "肥牛 + 宽粉 + 蔬菜", "emoji": "🥩"},
            {"id": "y3", "group": "加菜", "name": "宽粉", "price": 6, "sales": 870, "desc": "一份", "emoji": "🍥"},
            {"id": "y4", "group": "加菜", "name": "藕片", "price": 4, "sales": 540, "desc": "脆藕，一份", "emoji": "🥬"},
            {"id": "y5", "group": "加菜", "name": "午餐肉", "price": 8, "sales": 620, "desc": "四片", "emoji": "🥓"},
            {"id": "y6", "group": "饮品", "name": "酸梅汤", "price": 5, "sales": 700, "desc": "冰镇，解辣", "emoji": "🧃"},
        ],
    },
    {
        "id": "mcd",
        "name": "麦当劳（人民广场店）",
        "cat": "汉堡",
        "rate": 4.9,
        "sales": 6800,
        "fee": 1,
        "min": 20,
        "dist": 0.6,
        "emoji": "🍔",
        "color": "#f7b500",
        "cover": "food/shop_mcd.jpg",
        "tags": ["30 分钟达", "满 40 减 6"],
        "promos": [{"min": 40, "off": 6, "name": "满 40 减 6"}],
        "notice": "高峰期可能延迟，出餐后骑手优先取餐。",
        "items": [
            {"id": "m1", "group": "汉堡", "name": "巨无霸", "price": 22, "sales": 2300, "desc": "双层牛肉，经典款", "emoji": "🍔", "img": "food/item_m1.jpg"},
            {"id": "m2", "group": "汉堡", "name": "麦辣鸡腿堡", "price": 19, "sales": 1980, "desc": "微辣，现炸鸡腿", "emoji": "🍔"},
            {"id": "m3", "group": "汉堡", "name": "板烧鸡腿堡", "price": 21, "sales": 1200, "desc": "黑椒味，不辣", "emoji": "🍔"},
            {"id": "m4", "group": "小食", "name": "薯条（中）", "price": 12, "sales": 3100, "desc": "现炸，配番茄酱", "emoji": "🍟"},
            {"id": "m5", "group": "甜品", "name": "麦旋风", "price": 14, "sales": 1650, "desc": "奥利奥碎，可选草莓", "emoji": "🍦"},
            {"id": "m6", "group": "饮品", "name": "可乐（中）", "price": 9, "sales": 2600, "desc": "冰 / 常温", "emoji": "🥤"},
        ],
    },
    {
        "id": "shaxian",
        "name": "沙县小吃",
        "cat": "快餐",
        "rate": 4.6,
        "sales": 2600,
        "fee": 2,
        "min": 12,
        "dist": 0.9,
        "emoji": "🥢",
        "color": "#6d9e3f",
        "cover": "food/shop_shaxian.jpg",
        "tags": ["起送低", "出餐快"],
        "promos": [{"min": 20, "off": 2, "name": "满 20 减 2"}],
        "notice": "小店现做，米饭类出餐稍慢。",
        "items": [
            {"id": "x1", "group": "主食", "name": "蒸饺", "price": 9, "sales": 640, "desc": "8 只，皮薄馅足", "emoji": "🥟", "img": "food/item_x1.jpg"},
            {"id": "x2", "group": "主食", "name": "拌面", "price": 7, "sales": 780, "desc": "花生酱 + 葱油", "emoji": "🍜"},
            {"id": "x3", "group": "主食", "name": "蛋炒饭", "price": 13, "sales": 520, "desc": "现炒，加葱", "emoji": "🍚"},
            {"id": "x4", "group": "汤类", "name": "扁肉", "price": 10, "sales": 690, "desc": "清汤，8 只", "emoji": "🥣"},
            {"id": "x5", "group": "汤类", "name": "炖罐", "price": 12, "sales": 310, "desc": "排骨 / 鸡腿，二选一", "emoji": "🍲"},
            {"id": "x6", "group": "卤味", "name": "卤鸡腿", "price": 8, "sales": 460, "desc": "卤足 2 小时", "emoji": "🍗"},
        ],
    },
    {
        "id": "aunt",
        "name": "沪上阿姨（鲜果茶）",
        "cat": "奶茶",
        "rate": 4.8,
        "sales": 5200,
        "fee": 0,
        "min": 15,
        "dist": 0.4,
        "emoji": "🧋",
        "color": "#c86ba6",
        "cover": "food/shop_aunt.jpg",
        "tags": ["免配送费", "第二杯半价"],
        "promos": [{"min": 28, "off": 4, "name": "满 28 减 4"}],
        "notice": "糖度冰量可在备注写：少糖 / 去冰。",
        "items": [
            {"id": "a1", "group": "招牌", "name": "血糯米奶茶", "price": 15, "sales": 2100, "desc": "大半杯料，少糖推荐", "emoji": "🧋", "img": "food/item_a1.jpg"},
            {"id": "a2", "group": "招牌", "name": "珍珠奶茶", "price": 13, "sales": 1850, "desc": "黑糖珍珠，现煮", "emoji": "🧋"},
            {"id": "a3", "group": "果茶", "name": "杨枝甘露", "price": 18, "sales": 1300, "desc": "芒果 + 西柚 + 西米", "emoji": "🥭"},
            {"id": "a4", "group": "果茶", "name": "芝士葡萄", "price": 19, "sales": 980, "desc": "整颗葡萄，芝士奶盖", "emoji": "🍇"},
            {"id": "a5", "group": "纯茶", "name": "茉莉绿茶", "price": 10, "sales": 760, "desc": "无糖可选，清爽", "emoji": "🍵"},
            {"id": "a6", "group": "奶茶", "name": "双拼奶茶", "price": 17, "sales": 890, "desc": "珍珠 + 椰果", "emoji": "🧋"},
        ],
    },
    {
        "id": "lanzhou",
        "name": "兰州牛肉拉面",
        "cat": "面食",
        "rate": 4.7,
        "sales": 1900,
        "fee": 3,
        "min": 18,
        "dist": 2.1,
        "emoji": "🍜",
        "color": "#b5763a",
        "cover": "food/shop_lanzhou.jpg",
        "tags": ["现拉", "免费加汤"],
        "promos": [{"min": 25, "off": 3, "name": "满 25 减 3"}],
        "notice": "面型可选：细 / 二细 / 宽。",
        "items": [
            {"id": "l1", "group": "面食", "name": "牛肉拉面", "price": 16, "sales": 920, "desc": "一清二白三红四绿", "emoji": "🍜", "img": "food/item_l1.jpg"},
            {"id": "l2", "group": "加料", "name": "加牛肉", "price": 8, "sales": 640, "desc": "一份，切薄片", "emoji": "🥩"},
            {"id": "l3", "group": "小食", "name": "凉拌小菜", "price": 5, "sales": 520, "desc": "土豆丝 / 海带丝", "emoji": "🥗"},
            {"id": "l4", "group": "小食", "name": "烤羊肉串", "price": 6, "sales": 780, "desc": "一串，孜然辣", "emoji": "🍢"},
            {"id": "l5", "group": "饮品", "name": "老酸奶", "price": 8, "sales": 410, "desc": "冰镇，解腻", "emoji": "🥛"},
            {"id": "l6", "group": "加料", "name": "卤蛋", "price": 2, "sales": 690, "desc": "一枚", "emoji": "🥚"},
        ],
    },
]


def find_shop(shop_id: str) -> dict[str, Any] | None:
    for s in SHOPS:
        if s["id"] == shop_id:
            return s
    return None


def find_item(shop: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    for it in shop.get("items") or []:
        if it["id"] == item_id:
            return it
    return None


def price_cart(shop: dict[str, Any], lines: list[dict[str, Any]], first_order: bool = False) -> dict[str, Any]:
    """按菜单价重算，不信前端传的金额；顺带算满减与新客红包。"""
    out: list[dict[str, Any]] = []
    subtotal = 0.0
    for ln in lines or []:
        item = find_item(shop, str(ln.get("id") or ""))
        if not item:
            continue
        try:
            qty = int(ln.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        qty = max(0, min(20, qty))
        if qty <= 0:
            continue
        price = float(item["price"])
        subtotal += price * qty
        out.append({
            "id": item["id"],
            "name": item["name"],
            "price": price,
            "qty": qty,
            "emoji": item.get("emoji", ""),
            "img": item.get("img", ""),
        })
    if not out:
        return {"items": [], "pack": 0.0, "fee": 0.0, "total": 0.0, "discount": 0.0,
                "discount_label": "", "ok": False}
    pack = 1.0
    fee = float(shop.get("fee") or 0)
    discount = 0.0
    labels: list[str] = []
    best = 0.0
    best_label = ""
    for promo in shop.get("promos") or []:
        if subtotal >= float(promo.get("min") or 0) and float(promo.get("off") or 0) > best:
            best = float(promo["off"])
            best_label = str(promo.get("name") or f"满{promo['min']}减{promo['off']}")
    if best:
        discount += best
        labels.append(best_label)
    if first_order:
        discount += 6.0
        labels.append("新客红包 6")
    total = round(max(0.0, subtotal + pack + fee - discount), 2)
    return {
        "items": out,
        "pack": pack,
        "fee": fee,
        "discount": round(discount, 2),
        "discount_label": " + ".join(labels),
        "total": total,
        "ok": True,
    }


def eta_minutes(shop: dict[str, Any]) -> int:
    base = 14 + int(round(float(shop.get("dist") or 1.0) * 6))
    return max(16, min(42, base + random.randint(-2, 3)))
