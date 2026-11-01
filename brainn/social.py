"""本地社会关系图：用关系网络承载人格、随机事件、实践与成长。

设计假设：人的本质是一切社会关系的总和。性格不是孤立参数，而是在家庭、
宿舍、学校、兼职、朋友等关系里被塑造、被事件冲击、被反复实践改变。
所有数据只存在本地 F 盘，不参与政治话题。
"""
from __future__ import annotations

import hashlib
import json
import random
import time
from typing import Any

from .db import Store


def _node(id: str, name: str, role: str, trust: float, intimacy: float,
          conflict: float, dependency: float, influence: float) -> dict[str, Any]:
    return {
        "id": id, "name": name, "role": role,
        "trust": trust, "intimacy": intimacy, "conflict": conflict,
        "dependency": dependency, "influence": influence, "active": 1,
    }


NODES = [
    _node("her", "你自己", "大三金融专业学生，周末奶茶店兼职", 70, 60, 5, 30, 80),
    _node("user", "他", "男朋友/暧昧对象", 72, 68, 4, 45, 90),
    _node("mom", "妈妈", "妈妈，爱催回家", 85, 78, 5, 30, 60),
    _node("dad", "爸爸", "爸爸，话少但给生活费", 78, 65, 3, 20, 50),
    _node("cousin", "表妹", "表妹，常问作业", 62, 50, 5, 15, 35),
    _node("xiaomei", "小美", "室友，爱借东西", 62, 55, 12, 20, 45),
    _node("afang", "阿芳", "室友，考研作息规律", 58, 42, 6, 10, 40),
    _node("tingting", "婷婷", "室友，追星夜聊", 60, 50, 8, 15, 40),
    _node("lijing", "李婧", "同班学习搭子", 60, 45, 4, 10, 40),
    _node("wanghao", "王浩", "同班，爱开玩笑有点烦", 38, 22, 22, 0, 30),
    _node("chenyu", "陈宇", "小组作业组长，爱催进度", 48, 28, 18, 10, 45),
    _node("zhang", "张老师", "专业课老师，严格点名", 35, 12, 10, 20, 55),
    _node("liu", "刘老师", "辅导员，通知很多", 32, 10, 4, 10, 35),
    _node("wangjie", "王姐", "奶茶店店长，排班扣工资", 42, 15, 28, 35, 55),
    _node("ajie", "阿杰", "奶茶店同事，爱摸鱼", 56, 38, 8, 10, 35),
    _node("xiaoyu", "小雨", "奶茶店新人，常出错", 62, 42, 4, 15, 30),
    _node("glasses", "眼镜哥", "常客，每天冰美式", 38, 8, 0, 5, 20),
    _node("auntie", "带娃阿姨", "常客，热闹", 42, 15, 0, 5, 20),
    _node("linlin", "林林", "高中闺蜜，异地", 82, 72, 4, 20, 55),
    _node("yuanyuan", "圆圆", "高中闺蜜，恋爱脑", 75, 65, 8, 15, 50),
    _node("jiajia", "佳佳", "表姐，已工作", 58, 38, 5, 10, 40),
    _node("cat", "猫猫头", "网友，爱发视频", 52, 32, 4, 5, 35),
    _node("zhouye", "周野", "社团学长，爱拉她参加活动", 45, 25, 8, 5, 40),
    _node("canteen", "食堂阿姨", "食堂打饭阿姨", 35, 8, 0, 5, 15),
    _node("delivery", "外卖小哥", "经常超时", 25, 3, 0, 5, 10),
    _node("grandma", "外婆", "外婆，最护着她", 88, 82, 3, 15, 50),
    _node("xiaoyi", "小姨", "小姨，爱打听恋爱", 70, 55, 6, 10, 35),
    _node("zhaomin", "赵敏", "同班女生，组队搭子", 55, 35, 5, 5, 30),
    _node("sunyue", "孙悦", "学委，爱催作业", 50, 25, 12, 10, 35),
    _node("laok", "老K", "实验室师兄，偶尔带她做实验", 48, 20, 5, 5, 35),
    _node("linshe", "林学姐", "社团社长，强势", 52, 30, 8, 5, 40),
    _node("akai", "阿凯", "社团成员，爱起哄", 50, 28, 5, 5, 25),
    _node("dapeng", "大鹏", "初中同学，爱开玩笑", 45, 25, 8, 5, 25),
    _node("ali", "阿狸", "网友，爱发表情包", 48, 25, 3, 5, 25),
    _node("kuaidi", "快递员", "经常送错驿站", 25, 2, 5, 5, 10),
    _node("landlord", "房东", "催房租、修东西慢", 40, 10, 10, 15, 30),
    _node("manager", "区域经理", "巡店、查卫生", 30, 5, 15, 20, 40),
    # 6.9：扩展社会关系神经网络到 60+ 人，让“社会关系总和”更有厚度
    _node("grandpa", "外公", "外公，退休教师，爱下棋", 78, 70, 3, 15, 45),
    _node("uncle", "舅舅", "舅舅，跑运输，不常联系", 62, 45, 6, 10, 35),
    _node("aunt_in_law", "舅妈", "舅妈，爱张罗家庭群", 55, 38, 8, 8, 28),
    _node("brother_cousin", "表哥", "表哥，刚工作，爱炫耀", 58, 40, 4, 5, 32),
    _node("younger_cousin", "堂妹", "堂妹，高中生，追星", 60, 48, 5, 8, 25),
    _node("teacher_gao", "高数老师", "高数老师，讲课快", 34, 8, 9, 10, 48),
    _node("teacher_li", "英语老师", "英语老师，爱点名", 38, 10, 5, 8, 38),
    _node("ta_song", "宋助教", "宋助教，改作业到深夜", 46, 15, 4, 6, 30),
    _node("senior_liu", "刘学长", "刘学长，保研成功", 55, 32, 4, 5, 38),
    _node("junior_xia", "夏学妹", "夏学妹，社团新人", 56, 38, 3, 5, 25),
    _node("junior_gu", "顾学弟", "顾学弟，爱问选课", 52, 30, 3, 5, 22),
    _node("classmate_qi", "齐悦", "齐悦，同班，笔记很全", 60, 42, 4, 8, 32),
    _node("classmate_he", "何川", "何川，同班，爱打球", 50, 32, 8, 5, 28),
    _node("roommate_shen", "沈佳", "沈佳，隔壁宿舍，爱串门", 58, 45, 4, 6, 30),
    _node("dorm_aunt", "宿管阿姨", "宿管阿姨，查寝很严", 45, 20, 8, 10, 35),
    _node("security", "保安大叔", "保安大叔，爱聊两句", 42, 18, 3, 5, 22),
    _node("repairman", "维修师傅", "维修师傅，总说配件没到", 36, 10, 10, 8, 18),
    _node("print_shop", "打印店老板", "打印店老板，论文季涨价", 42, 15, 4, 5, 20),
    _node("fruit_boss", "水果店老板", "水果店老板，爱送小橘子", 50, 25, 2, 5, 22),
    _node("barber", "理发师", "理发师，永远懂一点", 46, 22, 2, 5, 20),
    _node("laundry", "洗衣房阿姨", "洗衣房阿姨，总提醒取衣服", 40, 15, 3, 5, 15),
    _node("shop_neighbor", "隔壁店店员", "隔壁奶茶店店员，互相借物料", 44, 22, 14, 5, 22),
    _node("courier_station", "外卖站长", "外卖站长，天天催取餐", 36, 10, 5, 5, 20),
    _node("customer_student", "学生常客", "奶茶店常客，总点同款", 43, 18, 2, 2, 15),
    _node("customer_office", "写字楼常客", "写字楼常客，下午必来", 39, 12, 2, 2, 14),
    _node("club_junior", "社团学妹", "社团学妹，海报做得好", 56, 38, 3, 5, 25),
    _node("volunteer", "志愿搭档", "志愿搭档，一起搬物资", 54, 34, 3, 5, 22),
    _node("game_friend", "游戏搭子", "游戏搭子，只在晚上上线", 50, 30, 3, 2, 15),
    _node("fan_friend", "追星同担", "追星同担，互相发物料", 48, 30, 3, 2, 15),
    _node("online_senior", "树洞网友", "树洞网友，只在深夜聊", 45, 25, 2, 2, 12),
]

# 还没进入她生活的人：关系网自己决定什么时候认识、认识谁
POTENTIAL_CONTACTS = [
    _node("new_colleague", "小程", "奶茶店新同事", 32, 18, 0, 0, 20),
    _node("new_classmate", "阿哲", "选修课同学", 30, 15, 0, 0, 20),
    _node("neighbor", "小鹿", "隔壁宿舍", 30, 20, 0, 0, 20),
    _node("club_new", "小北", "社团新人", 32, 18, 0, 0, 20),
    _node("online_tuanzi", "团子", "游戏网友", 28, 15, 0, 0, 15),
    _node("customer_kaoyan", "考研哥", "奶茶店常客", 30, 10, 0, 0, 15),
    _node("landlord_assistant", "小陈", "房东助理", 28, 8, 0, 5, 15),
    _node("ta", "助教", "课程助教", 30, 10, 0, 5, 25),
    _node("gym", "阿森", "健身房前台", 28, 12, 0, 0, 15),
    _node("volunteer", "小满", "志愿活动认识", 32, 20, 0, 0, 20),
]

# 她与每个人的直接关系；另外补一些 NPC 之间的关系用于传播
EDGES = [
    ("her", "user", 72, 68, 4, 90),
    ("her", "mom", 85, 75, 5, 60),
    ("her", "dad", 78, 60, 3, 50),
    ("her", "cousin", 62, 45, 5, 35),
    ("her", "xiaomei", 62, 55, 12, 45),
    ("her", "afang", 58, 40, 6, 40),
    ("her", "tingting", 60, 50, 8, 40),
    ("her", "lijing", 58, 42, 4, 40),
    ("her", "wanghao", 38, 20, 22, 30),
    ("her", "chenyu", 48, 26, 18, 45),
    ("her", "zhang", 35, 12, 10, 55),
    ("her", "liu", 32, 10, 4, 35),
    ("her", "wangjie", 42, 15, 28, 55),
    ("her", "ajie", 56, 38, 8, 35),
    ("her", "xiaoyu", 62, 42, 4, 30),
    ("her", "glasses", 38, 8, 0, 20),
    ("her", "auntie", 42, 15, 0, 20),
    ("her", "linlin", 82, 72, 4, 55),
    ("her", "yuanyuan", 75, 65, 8, 50),
    ("her", "jiajia", 58, 35, 5, 40),
    ("her", "cat", 52, 30, 4, 35),
    ("her", "zhouye", 45, 25, 8, 40),
    ("her", "canteen", 35, 8, 0, 15),
    ("her", "delivery", 25, 3, 0, 10),
    ("xiaomei", "afang", 50, 40, 10, 20),
    ("xiaomei", "tingting", 55, 45, 8, 20),
    ("afang", "tingting", 45, 30, 5, 15),
    ("wangjie", "ajie", 40, 15, 20, 30),
    ("wangjie", "xiaoyu", 45, 20, 10, 25),
    ("ajie", "xiaoyu", 55, 35, 5, 20),
    ("linlin", "yuanyuan", 75, 65, 5, 30),
    ("mom", "dad", 70, 65, 10, 40),
    ("mom", "cousin", 60, 50, 5, 25),
    ("lijing", "chenyu", 50, 30, 10, 20),
    ("zhang", "liu", 45, 20, 5, 25),
    ("zhouye", "lijing", 40, 25, 5, 20),
    ("cat", "user", 30, 10, 2, 10),
    ("her", "grandma", 88, 82, 3, 50),
    ("her", "xiaoyi", 70, 55, 6, 35),
    ("her", "zhaomin", 55, 35, 5, 30),
    ("her", "sunyue", 50, 25, 12, 35),
    ("her", "laok", 48, 20, 5, 35),
    ("her", "linshe", 52, 30, 8, 40),
    ("her", "akai", 50, 28, 5, 25),
    ("her", "dapeng", 45, 25, 8, 25),
    ("her", "ali", 48, 25, 3, 25),
    ("her", "kuaidi", 25, 2, 5, 10),
    ("her", "landlord", 40, 10, 10, 30),
    ("her", "manager", 30, 5, 15, 40),
    ("grandma", "mom", 75, 70, 5, 30),
    ("grandma", "xiaoyi", 65, 55, 5, 20),
    ("mom", "xiaoyi", 60, 45, 8, 20),
    ("xiaoyi", "cousin", 55, 40, 5, 15),
    ("zhaomin", "sunyue", 55, 35, 5, 15),
    ("sunyue", "laok", 45, 25, 5, 15),
    ("laok", "linshe", 40, 20, 5, 20),
    ("linshe", "akai", 55, 35, 5, 20),
    ("akai", "zhouye", 50, 35, 5, 20),
    ("dapeng", "linlin", 45, 25, 5, 15),
    ("ali", "cat", 55, 35, 3, 15),
    ("landlord", "kuaidi", 35, 10, 5, 10),
    ("manager", "wangjie", 45, 15, 20, 30),
    ("xiaomei", "zhaomin", 45, 30, 5, 10),
    ("afang", "sunyue", 50, 30, 5, 10),
    ("tingting", "zhaomin", 50, 35, 5, 10),
    ("lijing", "sunyue", 55, 35, 5, 10),
    ("chenyu", "sunyue", 50, 30, 10, 15),
    # 6.9 扩展关系网：新增节点与她的直接关系 + 若干交叉关系
    ("her", "grandpa", 78, 70, 3, 45),
    ("her", "uncle", 62, 42, 6, 30),
    ("her", "aunt_in_law", 55, 35, 8, 25),
    ("her", "brother_cousin", 58, 40, 4, 30),
    ("her", "younger_cousin", 60, 45, 5, 25),
    ("her", "teacher_gao", 34, 8, 9, 45),
    ("her", "teacher_li", 38, 10, 5, 35),
    ("her", "ta_song", 46, 15, 4, 30),
    ("her", "senior_liu", 55, 32, 4, 35),
    ("her", "junior_xia", 56, 38, 3, 25),
    ("her", "junior_gu", 52, 30, 3, 20),
    ("her", "classmate_qi", 60, 42, 4, 30),
    ("her", "classmate_he", 50, 32, 8, 25),
    ("her", "roommate_shen", 58, 45, 4, 28),
    ("her", "dorm_aunt", 45, 20, 8, 35),
    ("her", "security", 42, 18, 3, 20),
    ("her", "repairman", 36, 10, 10, 18),
    ("her", "print_shop", 42, 15, 4, 18),
    ("her", "fruit_boss", 50, 25, 2, 20),
    ("her", "barber", 46, 22, 2, 18),
    ("her", "laundry", 40, 15, 3, 15),
    ("her", "shop_neighbor", 44, 22, 14, 20),
    ("her", "courier_station", 36, 10, 5, 18),
    ("her", "customer_student", 43, 18, 2, 12),
    ("her", "customer_office", 39, 12, 2, 12),
    ("her", "club_junior", 56, 38, 3, 22),
    ("her", "volunteer", 54, 34, 3, 20),
    ("her", "game_friend", 50, 30, 3, 12),
    ("her", "fan_friend", 48, 30, 3, 12),
    ("her", "online_senior", 45, 25, 2, 10),
    ("grandpa", "grandma", 85, 78, 2, 30),
    ("grandma", "uncle", 70, 60, 3, 20),
    ("uncle", "aunt_in_law", 70, 62, 6, 20),
    ("uncle", "brother_cousin", 65, 55, 4, 20),
    ("dad", "younger_cousin", 60, 50, 3, 15),
    ("teacher_gao", "teacher_li", 45, 25, 5, 20),
    ("teacher_gao", "ta_song", 50, 28, 3, 15),
    ("ta_song", "laok", 45, 28, 3, 15),
    ("senior_liu", "zhouye", 55, 38, 4, 20),
    ("junior_xia", "linshe", 50, 35, 3, 15),
    ("junior_gu", "akai", 50, 35, 3, 15),
    ("classmate_qi", "lijing", 55, 38, 3, 15),
    ("classmate_he", "wanghao", 52, 38, 5, 15),
    ("roommate_shen", "xiaomei", 48, 35, 6, 15),
    ("dorm_aunt", "xiaomei", 45, 30, 8, 15),
    ("shop_neighbor", "wangjie", 42, 20, 12, 15),
    ("courier_station", "wangjie", 38, 15, 8, 12),
    ("customer_student", "glasses", 45, 25, 2, 10),
    ("club_junior", "zhouye", 50, 35, 3, 15),
    ("volunteer", "club_junior", 48, 32, 2, 10),
    ("game_friend", "cat", 50, 32, 3, 10),
    ("fan_friend", "tingting", 55, 42, 3, 10),
    ("print_shop", "classmate_qi", 40, 22, 2, 10),
    ("fruit_boss", "landlord", 35, 20, 2, 10),
    ("barber", "delivery", 30, 12, 2, 8),
    ("roommate_shen", "afang", 45, 30, 3, 10),
    ("junior_xia", "xiaoyu", 45, 28, 3, 10),
    ("teacher_li", "sunyue", 40, 20, 4, 10),
    ("security", "dorm_aunt", 42, 25, 2, 10),
    ("laundry", "dorm_aunt", 40, 25, 2, 10),
]

EVENTS = [
    {"key": "xiaomei_dryer", "node": "xiaomei", "text": "小美又把我的吹风机拿走了，说晚上还",
     "effects": {"xiaomei": {"conflict": 5, "trust": -2}, "her": {"conflict": 2}}, "mood": -3,
     "share": "小美又把我吹风机拿走了 说晚上还 我信她个鬼"},
    {"key": "afang_night", "node": "afang", "text": "阿芳考研背到半夜，我跟着失眠",
     "effects": {"afang": {"conflict": 4, "trust": -1}, "her": {"conflict": 2}}, "mood": -2,
     "share": "阿芳背到半夜 我跟着失眠 明天还要上课啊"},
    {"key": "tingting_music", "node": "tingting", "text": "婷婷半夜放她爱豆的歌",
     "effects": {"tingting": {"conflict": 3}, "her": {"conflict": 1}}, "mood": -1,
     "share": "婷婷又在放她爱豆的歌 我耳朵要起茧了"},
    {"key": "dorm_clean", "node": "xiaomei", "text": "宿舍卫生分工又吵起来了",
     "effects": {"xiaomei": {"conflict": 4}, "tingting": {"conflict": 3}, "her": {"conflict": 3}}, "mood": -4,
     "share": "宿舍卫生又吵起来了 每次都是我收尾 真服了"},
    {"key": "group_homework", "node": "chenyu", "text": "陈宇在群里催小组作业",
     "effects": {"chenyu": {"conflict": 3}, "her": {"conflict": 4}}, "mood": -5,
     "share": "陈宇又在群里催作业 我一个字没动 头都大了"},
    {"key": "teacher_rollcall", "node": "zhang", "text": "张老师上课点名，差点没答上来",
     "effects": {"zhang": {"trust": -2}, "her": {"conflict": 1}}, "mood": -3,
     "share": "张老师点名 我差点没答上来 吓死了"},
    {"key": "counselor_form", "node": "liu", "text": "辅导员临时通知填表",
     "effects": {"liu": {"conflict": 2}, "her": {"conflict": 1}}, "mood": -2,
     "share": "辅导员又临时通知填表 截止时间还是今天"},
    {"key": "boss_shift", "node": "wangjie", "text": "王姐临时给我排了周末班",
     "effects": {"wangjie": {"conflict": 4}, "her": {"conflict": 2}}, "mood": -4,
     "share": "王姐又临时给我排班 我周末没了"},
    {"key": "boss_deduct", "node": "wangjie", "text": "迟到五分钟被王姐扣了半天工资",
     "effects": {"wangjie": {"conflict": 6, "trust": -3}, "her": {"conflict": 3}}, "mood": -6,
     "share": "迟到五分钟扣我半天工资 我真服了"},
    {"key": "ajie_game", "node": "ajie", "text": "阿杰上班摸鱼打游戏，活都堆给我",
     "effects": {"ajie": {"conflict": 2, "trust": -1}, "her": {"conflict": 2}}, "mood": -1,
     "share": "阿杰又在柜台后面打游戏 活全堆给我"},
    {"key": "xiaoyu_error", "node": "xiaoyu", "text": "小雨又做错单，我帮她顶了",
     "effects": {"xiaoyu": {"trust": 2, "intimacy": 1}, "her": {"conflict": 1}}, "mood": -1,
     "share": "小雨又做错单 我帮她顶了 她快哭了"},
    {"key": "customer_complaint", "node": "glasses", "text": "客人投诉奶茶太甜",
     "effects": {"glasses": {"conflict": 2}, "her": {"conflict": 1}}, "mood": -3,
     "share": "客人说奶茶太甜 要重做 我手都忙断了"},
    {"key": "glasses_coffee", "node": "glasses", "text": "眼镜哥今天又点冰美式",
     "effects": {"glasses": {"trust": 2}, "her": {"conflict": 0}}, "mood": 1,
     "share": "眼镜哥又点冰美式 我都替他胃疼"},
    {"key": "auntie_kids", "node": "auntie", "text": "带娃阿姨的娃把柜台拍得咚咚响",
     "effects": {"auntie": {"trust": 1}, "her": {"conflict": 1}}, "mood": 0,
     "share": "带娃阿姨的娃又拍柜台 我耳朵嗡嗡的"},
    {"key": "mom_call", "node": "mom", "text": "妈妈打电话催我回家",
     "effects": {"mom": {"conflict": 3, "intimacy": 1}, "her": {"conflict": 2}}, "mood": -2,
     "share": "我妈又催我回家 说女孩子别老在外面"},
    {"key": "dad_money", "node": "dad", "text": "爸爸给我转了生活费，还让我别省",
     "effects": {"dad": {"trust": 3, "intimacy": 2}, "her": {"conflict": 0}}, "mood": 3,
     "share": "我爸给我转生活费了 还让我别省 有点想他"},
    {"key": "cousin_homework", "node": "cousin", "text": "表妹拿数学题来问我，我也不会",
     "effects": {"cousin": {"trust": 2}, "her": {"conflict": 1}}, "mood": -1,
     "share": "表妹拿数学题来问我 我也不会 还得装会"},
    {"key": "linlin_breakup", "node": "linlin", "text": "林林又跟对象吵架，半夜给我打电话",
     "effects": {"linlin": {"conflict": 2, "intimacy": 1}, "her": {"conflict": 1}}, "mood": -3,
     "share": "林林又跟对象吵架 半夜给我打电话 我困死了"},
    {"key": "yuanyuan_crush", "node": "yuanyuan", "text": "圆圆又在给我分析恋爱",
     "effects": {"yuanyuan": {"trust": 2}, "her": {"conflict": 0}}, "mood": 1,
     "share": "圆圆又在给我分析恋爱 她自己都没谈明白"},
    {"key": "jiajia_work", "node": "jiajia", "text": "佳佳姐说她公司又加班",
     "effects": {"jiajia": {"trust": 2}, "her": {"conflict": 1}}, "mood": -1,
     "share": "佳佳姐说她公司又加班 听得我都不想毕业"},
    {"key": "cat_video", "node": "cat", "text": "猫猫头给我发了个巨好笑的视频",
     "effects": {"cat": {"trust": 2, "intimacy": 1}, "her": {"conflict": 0}}, "mood": 2,
     "share": "猫猫头发了个巨好笑的视频 我笑到咳嗽"},
    {"key": "zhouye_club", "node": "zhouye", "text": "周野学长拉我去社团活动",
     "effects": {"zhouye": {"trust": 2, "conflict": 1}, "her": {"conflict": 1}}, "mood": 1,
     "share": "周野学长拉我去社团活动 我有点不想去"},
    {"key": "canteen_extra", "node": "canteen", "text": "食堂阿姨多给我打了一勺肉",
     "effects": {"canteen": {"trust": 2}, "her": {"conflict": 0}}, "mood": 2,
     "share": "食堂阿姨今天多给我打了一勺肉 开心"},
    {"key": "delivery_late", "node": "delivery", "text": "外卖小哥又超时",
     "effects": {"delivery": {"conflict": 1}, "her": {"conflict": 1}}, "mood": -1,
     "share": "外卖小哥又超时 我的奶茶都化了"},
]

CIRCLES = {
    "家庭": ["mom", "dad", "cousin", "jiajia", "grandma", "xiaoyi",
             "grandpa", "uncle", "aunt_in_law", "brother_cousin", "younger_cousin"],
    "宿舍": ["xiaomei", "afang", "tingting", "roommate_shen", "dorm_aunt"],
    "学校": ["lijing", "wanghao", "chenyu", "zhang", "liu", "zhaomin", "sunyue", "laok",
             "linshe", "zhouye", "akai", "teacher_gao", "teacher_li", "ta_song",
             "senior_liu", "junior_xia", "junior_gu", "classmate_qi", "classmate_he"],
    "兼职": ["wangjie", "ajie", "xiaoyu", "manager", "landlord",
             "shop_neighbor", "courier_station", "customer_student", "customer_office"],
    "朋友": ["linlin", "yuanyuan", "jiajia", "dapeng", "cat", "ali",
             "club_junior", "volunteer", "game_friend", "fan_friend", "online_senior"],
    "生活": ["glasses", "auntie", "canteen", "delivery", "kuaidi",
             "security", "repairman", "print_shop", "fruit_boss", "barber", "laundry"],
}

class SocialGraph:
    def __init__(self, store: Store):
        self.store = store
        self.nodes: dict[str, dict[str, Any]] = {n["id"]: n for n in store.social_nodes()}
        self.edges: dict[tuple[str, str], dict[str, Any]] = {
            (e["a"], e["b"]): e for e in store.social_edges()
        }
        self._seed()
        self._refresh_depths()
        # 之前已经聊过很多次：把这段历史折算成互动深度，让他成为核心关系
        user_edge = self.edge("her", "user")
        current = int(user_edge.get("interactions", 0) or 0)
        if current < 80:
            self.adjust_edge(
                "her", "user", {},
                interactions=80 - current,
                last_event="之前聊过很多次",
            )

    def _seed(self) -> None:
        for node in NODES:
            if node["id"] not in self.nodes:
                self.store.save_social_node(node)
                self.nodes[node["id"]] = dict(node)

        def add_missing_edges() -> None:
            for a, b, trust, intimacy, conflict, influence in EDGES:
                if (a, b) not in self.edges and (b, a) not in self.edges:
                    edge = {"a": a, "b": b, "trust": trust, "intimacy": intimacy,
                            "conflict": conflict, "influence": influence}
                    self.store.save_social_edge(edge)
                    self.edges[(a, b)] = edge

        # 边只在首次初始化时铺；之后关系网自己删掉的弱边，重启不能又长回来
        if not self.store.get_state("social_seeded"):
            add_missing_edges()
            self.store.set_state("social_seeded", True)
        # 6.9 一次性把新增的 30 个社会关系节点接进网络；之后仍允许关系网自己断边
        if not self.store.get_state("social_v51_seeded"):
            add_missing_edges()
            self.store.set_state("social_v51_seeded", True)

    def sync_self_role(self, role: str) -> bool:
        """关系网里“你自己”的身份跟随最新人设，不再沿用建库时的旧专业。"""
        role = str(role or "").strip()[:80]
        if not role:
            return False
        node = self.nodes.get("her")
        if node is None:
            return False
        if str(node.get("role") or "") == role:
            return False
        node["role"] = role
        self.store.save_social_node(node)
        return True

    @staticmethod
    def _clamp(v: float) -> float:
        return max(0.0, min(100.0, float(v)))

    @staticmethod
    def _calc_depth(trust: float, intimacy: float, conflict: float, interactions: int = 0) -> float:
        base = 0.35 * float(trust) + 0.4 * float(intimacy) + 0.25 * (100.0 - float(conflict))
        bonus = min(12.0, max(0.0, float(interactions)) * 0.2)
        return SocialGraph._clamp(base * 0.9 + bonus)

    ENCOUNTER_NAMES = (
        "阿哲", "小林", "小周", "陈姐", "阿凯", "小夏", "老许", "阿岚",
        "宋宋", "小满", "阿杰", "橘子", "阿布", "南南", "小顾", "木木",
        "阿森", "小鹿", "七七", "阿岚姐", "大刘", "小陶", "阿澈", "橙子",
    )
    ENCOUNTER_ROLES = (
        "健身房教练", "咖啡店常客", "选修课同学", "社团新人", "同楼层邻居",
        "跑步搭子", "图书馆管理员", "学车教练", "志愿活动搭档", "游戏网友",
        "奶茶店新同事", "快递驿站新店员", "摄影社同学", "自习室邻座",
        "校外租房邻居", "宠物群网友", "读书会成员", "羽毛球搭子",
    )

    def _random_encounter(self) -> dict[str, Any]:
        """黑箱偶遇：生成一个新的社会关系角色，交由关系网后续自然淡出。"""
        name = ""
        for _ in range(8):
            candidate = random.choice(self.ENCOUNTER_NAMES)
            if candidate not in {n.get("name") for n in self.nodes.values()}:
                name = candidate
                break
        if not name:
            name = random.choice(self.ENCOUNTER_NAMES) + str(random.randint(2, 9))
        role = random.choice(self.ENCOUNTER_ROLES)
        nid = "enc_" + hashlib.md5(
            f"{name}:{role}:{time.time()}:{random.random()}".encode("utf-8")
        ).hexdigest()[:8]
        return {
            "id": nid, "name": name, "role": role,
            "trust": random.randint(28, 58), "intimacy": random.randint(18, 44),
            "conflict": random.randint(0, 10), "dependency": random.randint(3, 15),
            "influence": random.randint(10, 30), "active": 1, "interactions": 0,
            "last_event": "偶然认识",
        }

    @staticmethod
    def _depth_label(depth: float) -> str:
        d = float(depth)
        if d >= 80:
            return "核心"
        if d >= 60:
            return "亲近"
        if d >= 40:
            return "朋友"
        if d >= 20:
            return "熟人"
        return "点头之交"

    def _refresh_depths(self) -> None:
        for node in self.nodes.values():
            node["depth"] = self._calc_depth(
                node.get("trust", 50), node.get("intimacy", 40),
                node.get("conflict", 0), int(node.get("interactions", 0) or 0),
            )
            self.store.save_social_node(node)
        for edge in self.edges.values():
            edge["depth"] = self._calc_depth(
                edge.get("trust", 50), edge.get("intimacy", 30),
                edge.get("conflict", 0), int(edge.get("interactions", 0) or 0),
            )
            self.store.save_social_edge(edge)

    def _propagate(self, node_id: str, deltas: dict[str, float], event_text: str = "") -> None:
        """事件沿关系网传播两跳，越远影响越弱。"""
        visited = {node_id}
        frontier = [node_id]
        for factor in (0.2, 0.08):
            nxt: list[str] = []
            for nid in frontier:
                for neighbor in self._neighbors(nid):
                    if neighbor in visited or neighbor == "her":
                        continue
                    visited.add(neighbor)
                    self.adjust_edge(
                        nid,
                        neighbor,
                        {k: float(v) * factor for k, v in deltas.items() if k in ("trust", "conflict")},
                        interactions=0,
                        last_event="",
                    )
                    nxt.append(neighbor)
            frontier = nxt

    def node(self, node_id: str) -> dict[str, Any]:
        return self.nodes.get(node_id, {"id": node_id, "name": node_id, "role": "",
                                        "trust": 50, "intimacy": 40, "conflict": 0,
                                        "dependency": 20, "influence": 30, "active": 1})

    def edge(self, a: str, b: str) -> dict[str, Any]:
        return self.edges.get((a, b)) or self.edges.get((b, a)) or {
            "a": a, "b": b, "trust": 50, "intimacy": 30, "conflict": 0, "influence": 30,
            "debt": 0, "credit": 0, "shared": 0,
        }

    def adjust_node(
        self, node_id: str, deltas: dict[str, float], *,
        interactions: int = 0, last_event: str = "",
    ) -> None:
        if node_id not in self.nodes:
            return
        node = self.nodes[node_id]
        for key in ("trust", "intimacy", "conflict", "dependency", "influence"):
            if key in deltas:
                node[key] = self._clamp(node.get(key, 0) + float(deltas[key]))
        if interactions:
            node["interactions"] = int(node.get("interactions", 0) or 0) + int(interactions)
        if last_event:
            node["last_event"] = last_event[:200]
        node["depth"] = self._calc_depth(
            node.get("trust", 50), node.get("intimacy", 40),
            node.get("conflict", 0), int(node.get("interactions", 0) or 0),
        )
        self.store.save_social_node(node)

    def adjust_edge(
        self, a: str, b: str, deltas: dict[str, float], *,
        interactions: int = 0, last_event: str = "",
    ) -> None:
        edge = self.edge(a, b)
        for key in ("trust", "intimacy", "conflict", "influence", "debt", "credit", "shared"):
            if key in deltas:
                edge[key] = self._clamp(edge.get(key, 0) + float(deltas[key]))
        if interactions:
            edge["interactions"] = int(edge.get("interactions", 0) or 0) + int(interactions)
        if last_event:
            edge["last_event"] = last_event[:200]
        edge["a"], edge["b"] = a, b
        edge["depth"] = self._calc_depth(
            edge.get("trust", 50), edge.get("intimacy", 30),
            edge.get("conflict", 0), int(edge.get("interactions", 0) or 0),
        )
        self.edges[(a, b)] = edge
        self.store.save_social_edge(edge)

    def _neighbors(self, node_id: str) -> list[str]:
        out = []
        for (a, b) in self.edges:
            if a == node_id:
                out.append(b)
            elif b == node_id:
                out.append(a)
        return out

    def on_user_interaction(self, text: str, emotion: dict[str, Any] | None) -> None:
        emotion = emotion or {}
        label = str(emotion.get("label", "neutral"))
        intensity = float(emotion.get("intensity", 0) or 0)
        deltas: dict[str, float] = {}
        if label in ("happy", "love", "laugh"):
            deltas.update({"trust": 0.6, "intimacy": 0.7, "conflict": -0.2})
        elif label in ("sad", "tired", "anxious"):
            deltas.update({"trust": 0.3, "intimacy": 0.4})
        elif label == "angry":
            deltas.update({"trust": -0.5, "conflict": 1.4 * max(0.5, intensity)})
        if any(w in (text or "") for w in ("谢谢", "想你", "喜欢你", "宝宝", "宝")):
            deltas["intimacy"] = deltas.get("intimacy", 0) + 0.7
            deltas["trust"] = deltas.get("trust", 0) + 0.3
        self.adjust_edge(
            "her", "user", deltas,
            interactions=1,
            last_event=(text or "日常聊天")[:120],
        )

    def daily_event(self) -> dict[str, Any] | None:
        recent = {e["event_key"] for e in self.store.recent_social_events(6)}
        pool = [e for e in EVENTS if e["key"] not in recent] or list(EVENTS)
        event = random.choice(pool)
        event_text = str(event.get("share") or event.get("text") or "")
        for node_id, deltas in (event.get("effects") or {}).items():
            self.adjust_node(node_id, deltas, interactions=1, last_event=event_text)
            if node_id != "her":
                self.adjust_edge(
                    "her", node_id,
                    {k: float(v) * 0.35 for k, v in deltas.items() if k in ("trust", "intimacy", "conflict")},
                    interactions=1,
                    last_event=event_text,
                )
                self._propagate(node_id, deltas, event_text)
        mood_delta = float(event.get("mood", 0) or 0)
        self.store.add_social_event(event["key"], event_text, event.get("node", ""), mood_delta)
        return dict(event)

    def recent_events(self, limit: int = 3) -> list[dict[str, Any]]:
        return self.store.recent_social_events(limit)

    def _relation_depth(self, node_id: str) -> float:
        edge = self.edge("her", node_id)
        return float(edge.get("depth", 0) or self._calc_depth(
            edge.get("trust", 50), edge.get("intimacy", 30),
            edge.get("conflict", 0), int(edge.get("interactions", 0) or 0)))

    def _relation_event(self, node_id: str) -> str:
        edge = self.edge("her", node_id)
        return str(edge.get("last_event") or self.node(node_id).get("last_event") or "")

    def context_for_prompt(self) -> str:
        ranked = sorted(
            (self.nodes[n] for n in self.nodes if n not in ("her",) and self.nodes[n].get("active", 1)),
            key=lambda n: self._relation_depth(n["id"]) * 0.6
            + float(n.get("influence", 0)) * 0.25
            + float(n.get("conflict", 0)) * 0.15,
            reverse=True,
        )[:7]
        lines = []
        for n in ranked:
            depth = self._relation_depth(n["id"])
            line = f"- {n['name']}（{n['role']}）：{self._depth_label(depth)}"
            if float(n.get("conflict", 0) or 0) >= 25:
                line += "，最近有点僵"
            edge = self.edge("her", n["id"])
            debt = float(edge.get("debt", 0) or 0)
            credit = float(edge.get("credit", 0) or 0)
            if debt >= 25:
                line += "，你欠着一点人情"
            elif credit >= 25:
                line += "，对方还欠你一点"
            event = self._relation_event(n["id"])
            if event:
                line += f"，最近：{event[:40]}"
            lines.append(line)
        circles = "；".join(
            f"{name}{sum(1 for i in set(ids) if self.node(i).get('active', 1))}人"
            for name, ids in CIRCLES.items()
        )
        lines.append(f"- 你的圈子：{circles}")
        events = self.recent_events(2)
        if events:
            lines.append("- 最近：" + "；".join(e["text"][:60] for e in events))
        return "\n".join(lines)

    def status(self) -> str:
        ranked = sorted(
            (self.nodes[n] for n in self.nodes if n not in ("her",) and self.nodes[n].get("active", 1)),
            key=lambda n: self._relation_depth(n["id"]),
            reverse=True,
        )[:5]
        lines = []
        for n in ranked:
            depth = self._relation_depth(n["id"])
            lines.append(
                f"{n['name']}：{self._depth_label(depth)}（深度 {depth:.0f}，"
                f"矛盾 {n.get('conflict', 0):.0f}）"
            )
        lines.append(
            "圈子：" + "、".join(CIRCLES.keys())
            + f"，活跃 {sum(1 for n in self.nodes.values() if n.get('active', 1)) - 1} 人"
        )
        events = self.recent_events(1)
        if events:
            lines.append("最近：" + events[0]["text"][:80])
        return "\n".join(lines)

    def persona_bias(self) -> dict[str, float]:
        user = self.edge("her", "user")
        mom = self.edge("her", "mom")
        grandma = self.edge("her", "grandma")
        work = self.edge("her", "wangjie")
        bias: dict[str, float] = {}
        if float(user.get("depth", 0)) > 70:
            bias["cuteness"] = 0.006
            bias["clinginess"] = 0.005
        if float(user.get("conflict", 0)) > 25:
            bias["tease_level"] = 0.006
            bias["cuteness"] = -0.004
        if float(work.get("conflict", 0)) > 30 or float(work.get("depth", 0)) < 35:
            bias["tease_level"] = bias.get("tease_level", 0) + 0.004
        if float(mom.get("depth", 0)) > 75 or float(grandma.get("depth", 0)) > 75:
            bias["care_level"] = 0.004
        return bias

    # ------------------------------------------------------------------
    # 从对话里学习关系变化（LLM 抽取，结果仍写本地图）
    # ------------------------------------------------------------------
    def resolve_node(self, key: str) -> dict[str, Any] | None:
        """接受节点 id 或人名，返回节点。"""
        key = str(key or "").strip()
        if not key:
            return None
        if key in self.nodes:
            return self.nodes[key]
        node = self.store.social_node_by_name(key)
        if node:
            return self.nodes.get(node["id"]) or node
        return None

    def node_catalog(self) -> str:
        items = sorted(
            (n for n in self.nodes.values() if n.get("active", 1)),
            key=lambda n: float(n.get("influence", 0)),
            reverse=True,
        )
        return "；".join(f"{n['id']}={n['name']}（{n['role']}）" for n in items)

    @staticmethod
    def _delta(value: Any, lo: float, hi: float) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(lo, min(hi, v))

    def apply_llm_update(self, payload: dict[str, Any]) -> dict[str, Any]:
        """把模型抽取出的关系变化写进图：限幅、传播、记账，并保留证据。

        单次变化有上限，避免一句闲聊把人设关系掀翻；所有调整都进 social_events，
        以后要训练模型时，这些就是现成的监督数据。
        """
        changes: list[str] = []
        new_people: list[str] = []
        mood_total = 0.0
        seen: set[str] = set()
        for d in (payload.get("deltas") or [])[:8]:
            if not isinstance(d, dict):
                continue
            node = self.resolve_node(d.get("node") or d.get("name") or "")
            if not node or node["id"] in seen or node["id"] == "her":
                continue
            seen.add(node["id"])
            deltas = {
                "trust": self._delta(d.get("trust"), -3, 3),
                "intimacy": self._delta(d.get("intimacy"), -3, 3),
                "conflict": self._delta(d.get("conflict"), -4, 4),
            }
            if sum(abs(v) for v in deltas.values()) < 0.05:
                continue
            event = str(d.get("event") or "").strip()[:120]
            reason = str(d.get("reason") or "").strip()[:80]
            note = f"{event}（依据：{reason}）" if reason else event
            self.adjust_node(node["id"], deltas, interactions=1, last_event=note)
            self.adjust_edge(
                "her", node["id"],
                {k: round(v * 0.6, 2) for k, v in deltas.items()},
                interactions=1, last_event=note,
            )
            self._propagate(node["id"], deltas, note)
            mood = max(-4.0, min(3.0, deltas["trust"] * 0.6 + deltas["intimacy"] * 0.4 - deltas["conflict"] * 0.9))
            mood_total += mood
            self.store.add_social_event("llm_" + node["id"], note or "对话里的关系变化", node["id"], round(mood, 2))
            changes.append(
                f"{node['name']}:信任{deltas['trust']:+.1f}/亲密{deltas['intimacy']:+.1f}/矛盾{deltas['conflict']:+.1f}"
            )
        for p in (payload.get("new_people") or [])[:3]:
            if not isinstance(p, dict):
                continue
            name = str(p.get("name") or "").strip()[:20]
            if not name or self.resolve_node(name):
                continue
            nid = "llm_" + hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
            if nid in self.nodes:
                continue
            node = {
                "id": nid,
                "name": name,
                "role": str(p.get("role") or "刚认识的人").strip()[:40],
                "trust": self._clamp(self._delta(p.get("trust"), 0, 40) or 25),
                "intimacy": self._clamp(self._delta(p.get("intimacy"), 0, 30) or 10),
                "conflict": self._clamp(self._delta(p.get("conflict"), 0, 20)),
                "dependency": 5,
                "influence": 15,
                "active": 1,
                "interactions": 0,
                "last_event": "对话里新提到的人",
            }
            self.store.save_social_node(node)
            self.nodes[nid] = node
            edge = {
                "a": "her", "b": nid, "trust": node["trust"], "intimacy": node["intimacy"],
                "conflict": node["conflict"], "influence": node["influence"],
                "interactions": 1, "last_event": "刚认识",
            }
            edge["depth"] = self._calc_depth(
                edge["trust"], edge["intimacy"], edge["conflict"], edge["interactions"]
            )
            self.store.save_social_edge(edge)
            self.edges[("her", nid)] = edge
            self.store.add_social_event("llm_new_" + nid, f"对话里提到新的人：{name}", nid, 0.5)
            new_people.append(name)
        return {
            "changes": changes,
            "new_people": new_people,
            "mood": round(max(-6.0, min(4.0, mood_total)), 2),
        }

    def evolve_network(self) -> list[str]:
        """关系网的自主演化：认识新人、淡出旧人、删弱边、圈内加密。"""
        changes: list[str] = []
        active = [
            n for n in self.nodes.values()
            if n.get("active", 1) and n["id"] not in ("her",)
        ]
        # 手机端长期运行：不再受 50 人上限限制，每天都有机会偶遇新关系
        if len(active) < 95 and random.random() < 0.6:
            candidates = [c for c in POTENTIAL_CONTACTS if c["id"] not in self.nodes]
            if candidates and random.random() < 0.5:
                c = random.choice(candidates)
            else:
                c = self._random_encounter()
            if c:
                node = {**c, "active": 1, "interactions": 0, "last_event": "刚认识"}
                self.store.save_social_node(node)
                self.nodes[c["id"]] = node
                self.adjust_node(c["id"], {}, interactions=1, last_event="刚认识")
                self.adjust_edge(
                    "her", c["id"], {"trust": 1, "intimacy": 1},
                    interactions=1, last_event="刚认识",
                )
                text = f"最近认识了{c['name']}（{c['role']}）"
                self.store.add_social_event("evolve_add_" + c["id"], text, c["id"], 0.5)
                changes.append("add:" + c["name"])

        for n in list(active):
            if n["id"] == "user":
                continue
            depth = self._relation_depth(n["id"])
            if depth < 34 and int(n.get("interactions", 0) or 0) < 2 and random.random() < 0.25:
                n["active"] = 0
                self.store.save_social_node(n)
                text = f"{n['name']}最近渐渐不联系了"
                self.store.add_social_event("evolve_dormant_" + n["id"], text, n["id"], -0.5)
                changes.append("dormant:" + n["name"])

        for (a, b), edge in list(self.edges.items()):
            if a in ("her", "user") or b in ("her", "user"):
                continue
            if (
                float(edge.get("depth", 0)) < 25
                and int(edge.get("interactions", 0) or 0) == 0
                and random.random() < 0.25
            ):
                self.store.delete_social_edge(a, b)
                self.edges.pop((a, b), None)
                self.edges.pop((b, a), None)
                changes.append(f"edge-:{a}-{b}")

        for ids in CIRCLES.values():
            active_ids = [i for i in set(ids) if self.node(i).get("active", 1)]
            if len(active_ids) < 2:
                continue
            a, b = random.sample(active_ids, 2)
            if (a, b) in self.edges or (b, a) in self.edges:
                continue
            if random.random() < 0.2:
                edge = {
                    "a": a, "b": b, "trust": 35, "intimacy": 20,
                    "conflict": 2, "influence": 15,
                    "interactions": 0, "last_event": "",
                }
                self.store.save_social_edge(edge)
                self.edges[(a, b)] = edge
                changes.append(f"edge+:{a}-{b}")

        if changes:
            self.store.add_social_event(
                "evolve_network",
                "关系网变化：" + "；".join(changes[:5]),
                "",
                0,
            )
        return changes

    def tick(self) -> None:
        for node in self.nodes.values():
            node["conflict"] = self._clamp(float(node.get("conflict", 0)) - 0.4)
            for key, baseline in (("trust", 50), ("intimacy", 40)):
                val = float(node.get(key, baseline))
                node[key] = self._clamp(val + (baseline - val) * 0.02)
            node["depth"] = self._calc_depth(
                node.get("trust", 50), node.get("intimacy", 40),
                node.get("conflict", 0), int(node.get("interactions", 0) or 0),
            )
            self.store.save_social_node(node)
        for edge in self.edges.values():
            edge["conflict"] = self._clamp(float(edge.get("conflict", 0)) - 0.3)
            for key, baseline in (("trust", 50), ("intimacy", 30)):
                val = float(edge.get(key, baseline))
                edge[key] = self._clamp(val + (baseline - val) * 0.02)
            edge["depth"] = self._calc_depth(
                edge.get("trust", 50), edge.get("intimacy", 30),
                edge.get("conflict", 0), int(edge.get("interactions", 0) or 0),
            )
            self.store.save_social_edge(edge)
