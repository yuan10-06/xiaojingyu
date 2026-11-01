"""手机端本地服务：把 ChatEngine 挂到 127.0.0.1，WebView 只负责显示。

不连 QQ，不需要 NapCat；进程由 Android 前台服务保活。
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import difflib
import json
import logging
import math
import os
import random
import re
import sqlite3
import threading
import time
import traceback
import zipfile
from collections import deque
from hashlib import md5, sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx
import yaml

log = logging.getLogger(__name__)

PORT = 8765
VERSION = "9.3.0"
ROOT: Path | None = None
_STARTED = False
NOTIFY_HOOK = None
DESKTOP_HOOKS: dict | None = None
DESKTOP_TOKEN = ""
SPLASH_HOST = None


def set_notify_hook(fn) -> None:
    """桌面版注入 Windows 通知；手机端不设置，保持走 Java Notifier。"""
    global NOTIFY_HOOK
    NOTIFY_HOOK = fn


def set_desktop_hooks(hooks: dict, token: str) -> None:
    """桌面版注入桌宠控制接口；手机端不设置。"""
    global DESKTOP_HOOKS, DESKTOP_TOKEN
    DESKTOP_HOOKS = hooks or None
    DESKTOP_TOKEN = str(token or "")


def set_splash_host(host) -> None:
    """桌面版注入原生启动画面宿主；手机端不设置，保持现有适配。"""
    global SPLASH_HOST
    SPLASH_HOST = host


def _deep_merge(base: dict, patch: dict) -> dict:
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


# 朋友圈：每个社会关系成员都有昵称、性格和头像底色
PERSONALITY = {
    "her": "嘴硬心软 · 吃货",
    "user": "她眼里最重要的人",
    "mom": "操心 · 爱催回家",
    "dad": "话少 · 可靠",
    "cousin": "学生气 · 爱问作业",
    "xiaomei": "爱占小便宜 · 自来熟",
    "afang": "自律 · 考研卷王",
    "tingting": "追星 · 夜聊话痨",
    "lijing": "安静 · 学习搭子",
    "wanghao": "嘴欠 · 爱开玩笑",
    "chenyu": "强势 · 爱催进度",
    "zhang": "严格 · 点名狂魔",
    "liu": "通知很多 · 辅导员",
    "wangjie": "精明 · 强势店长",
    "ajie": "摸鱼 · 老油条",
    "xiaoyu": "胆小 · 新人",
    "glasses": "常客 · 冰美式",
    "auntie": "热闹 · 带娃",
    "linlin": "异地闺蜜 · 嘴甜",
    "yuanyuan": "恋爱脑 · 闺蜜",
    "jiajia": "表姐 · 已经工作",
    "cat": "网友 · 爱发视频",
    "zhouye": "社团学长 · 爱拉人",
    "canteen": "食堂阿姨 · 手抖",
    "delivery": "外卖小哥 · 总超时",
    "grandma": "外婆 · 最护短",
    "xiaoyi": "小姨 · 爱打听",
    "zhaomin": "同班 · 组队搭子",
    "sunyue": "学委 · 爱催作业",
    "laok": "实验室师兄 · 偶尔带实验",
    "linshe": "社团社长 · 强势",
    "akai": "社团 · 爱起哄",
    "dapeng": "初中同学 · 嘴碎",
    "ali": "网友 · 表情包收藏家",
    "kuaidi": "快递员 · 总送错驿站",
    "landlord": "房东 · 修东西慢",
    "manager": "区域经理 · 巡店",
    "grandpa": "退休教师 · 爱下棋",
    "uncle": "跑运输 · 不常联系",
    "aunt_in_law": "爱张罗 · 家庭群",
    "brother_cousin": "刚工作 · 爱炫耀",
    "younger_cousin": "高中生 · 追星",
    "teacher_gao": "讲课快 · 高数",
    "teacher_li": "爱点名 · 英语",
    "ta_song": "改作业到深夜 · 助教",
    "senior_liu": "保研成功 · 学长",
    "junior_xia": "社团新人 · 学妹",
    "junior_gu": "爱问选课 · 学弟",
    "classmate_qi": "笔记很全 · 同班",
    "classmate_he": "爱打球 · 同班",
    "roommate_shen": "隔壁宿舍 · 爱串门",
    "dorm_aunt": "查寝很严 · 宿管",
    "security": "爱聊两句 · 保安",
    "repairman": "配件没到 · 维修",
    "print_shop": "论文季涨价 · 打印店",
    "fruit_boss": "爱送小橘子 · 水果店",
    "barber": "永远懂一点 · 理发师",
    "laundry": "催取衣服 · 洗衣房",
    "shop_neighbor": "互相借物料 · 隔壁店",
    "courier_station": "催取餐 · 外卖站长",
    "customer_student": "总点同款 · 学生常客",
    "customer_office": "下午必来 · 写字楼常客",
    "club_junior": "海报做得好 · 社团学妹",
    "volunteer": "一起搬物资 · 志愿搭档",
    "game_friend": "只在晚上上线 · 游戏搭子",
    "fan_friend": "互相发物料 · 追星同担",
    "online_senior": "只在深夜聊 · 树洞网友",
}

# 从“他”的视角看，她的家人要带“她”字，避免和用户自己的妈妈混淆
DISPLAY_NAMES = {
    "mom": "她妈妈",
    "dad": "她爸爸",
    "cousin": "她表妹",
    "grandma": "她外婆",
    "grandpa": "她外公",
    "uncle": "她舅舅",
    "aunt_in_law": "她舅妈",
    "brother_cousin": "她表哥",
    "younger_cousin": "她堂妹",
    "xiaoyi": "她小姨",
    "jiajia": "她表姐",
}

AVATAR_EMOJI = {
    "her": "🐟", "user": "😎", "mom": "👩", "dad": "👨", "cousin": "👧",
    "xiaomei": "👩‍🦰", "afang": "👩‍🎓", "tingting": "🎤", "lijing": "📚",
    "wanghao": "😜", "chenyu": "👨‍💼", "zhang": "👨‍🏫", "liu": "👩‍💼",
    "wangjie": "👩‍🍳", "ajie": "🎮", "xiaoyu": "🧋", "glasses": "👓",
    "auntie": "👩‍👶", "linlin": "👩‍🦱", "yuanyuan": "💕", "jiajia": "💼",
    "cat": "🐱", "zhouye": "🧑‍🎓", "canteen": "🍚", "delivery": "🛵",
    "grandma": "👵", "xiaoyi": "👩", "zhaomin": "🧑‍🤝‍🧑", "sunyue": "📝",
    "laok": "🔬", "linshe": "📣", "akai": "🙌", "dapeng": "😆",
    "ali": "🦊", "kuaidi": "📦", "landlord": "🧓", "manager": "🕴",
    "grandpa": "👴", "uncle": "🚚", "aunt_in_law": "👩", "brother_cousin": "👨‍💼",
    "younger_cousin": "👧", "teacher_gao": "📐", "teacher_li": "📖", "ta_song": "🖊",
    "senior_liu": "🎓", "junior_xia": "🌸", "junior_gu": "🧑‍🎓", "classmate_qi": "📒",
    "classmate_he": "🏀", "roommate_shen": "🚪", "dorm_aunt": "🔑", "security": "🛡",
    "repairman": "🔧", "print_shop": "🖨", "fruit_boss": "🍊", "barber": "✂",
    "laundry": "🧺", "shop_neighbor": "🧋", "courier_station": "🛵",
    "customer_student": "🎒", "customer_office": "💼", "club_junior": "🎨",
    "volunteer": "🤝", "game_friend": "🎮", "fan_friend": "🌟", "online_senior": "🌙",
}

AVATAR_COLORS = [
    "#5b8c6e", "#7a6fb0", "#b07a5b", "#5b7fb0", "#b05b7a", "#8c8c5b",
    "#5ba8b0", "#a86b5b", "#6b8ca8", "#8c5b8c", "#7a8c5b", "#b08c5b",
]

NPC_POSTS = {
    "mom": ["降温了，你那边记得加件外套。", "今天买了你爱吃的橘子，等你回来。", "别老熬夜，脸都熬黄了。"],
    "dad": ["发工资了，给你转点生活费。", "少熬夜。", "天冷记得吃饭，别省。"],
    "xiaomei": ["吹风机又不知道被谁拿走了…", "今天谁值日啊，垃圾都满了。", "借用一下充电线，晚上还。"],
    "afang": ["今天的图书馆座位抢到了。", "背到第三遍，脑子已经木了。", "还有八十多天，撑住。"],
    "tingting": ["我担的新歌循环一百遍！", "昨晚又聊到两点，今天起不来。", "谁懂这个舞台啊，我要疯了。"],
    "wangjie": ["周末排班表发了，自己看。", "今天店里忙到脚不沾地。", "迟到一分钟也是迟到。"],
    "ajie": ["摸鱼被抓，笑死。", "今天活都堆给新人了。", "下班那一刻，灵魂回笼。"],
    "xiaoyu": ["今天又做错一杯，幸好没被骂。", "站一天腿要断了。", "求求别再点隐藏菜单了。"],
    "linlin": ["异地第 87 天，想见。", "今天路过一家店，想起你。", "视频完更想你了，烦。"],
    "yuanyuan": ["他今天回我消息了！！", "恋爱脑发作，救不了。", "要不要主动找他啊，急。"],
    "chenyu": ["小组作业截止还有三天，各位。", "进度麻烦今晚报一下。", "别让我一个人收尾。"],
    "zhang": ["下节课随堂测验，范围第三章。", "作业迟交按零分处理。", "上课别玩手机。"],
    "liu": ["请各位同学今天内完成信息填报。", "明天班会，务必到。", "收到请回复。"],
    "lijing": ["今天自习室好安静。", "笔记整理完了，舒服。", "一起复习吗？"],
    "grandma": ["院子里的桂花开了。", "你什么时候回来吃饭？", "外婆给你留了糖。"],
    "cat": ["新视频剪到凌晨，眼睛疼。", "刷到一个超好笑的，等下发你。", "今天不想睡。"],
    "xiaoyi": ["你妈又念叨你了。", "谈对象没有啊？", "有空来小姨家吃饭。"],
    "jiajia": ["上班上到怀疑人生。", "发工资第一件事：吃顿好的。", "你们学校放假了吗？"],
    "zhouye": ["社团招新还差人，来不来？", "这周活动别缺席。", "场地批下来了。"],
    "glasses": ["今天的冰美式有点淡。", "老位置，老时间。", "加班第 N 天。"],
    "auntie": ["今天带娃逛了一天，累瘫。", "小孩子精力怎么这么旺。", "终于哄睡了。"],
    "grandpa": ["今天棋赢了两盘。", "院子里的花该浇了。", "人老了，觉少。"],
    "uncle": ["这趟货跑到半夜。", "路上堵了两个小时。", "到家倒头就睡。"],
    "aunt_in_law": ["家庭群又安静了。", "周末来家里吃饭吗？", "你妈又念叨你了。"],
    "brother_cousin": ["新工作第一周，累。", "发工资了，请自己吃顿好的。", "办公室空调太冷。"],
    "younger_cousin": ["新歌循环中。", "作业写不完，救命。", "今天又被班主任抓了。"],
    "teacher_gao": ["这章作业记得交。", "下周随堂测。", "上课别走神。"],
    "teacher_li": ["今天听写全对的人不多。", "单词回去背。", "明天检查课文。"],
    "ta_song": ["作业堆成山。", "今晚改到十二点。", "有问题早点问。"],
    "senior_liu": ["保研材料终于交完了。", "实验室又通宵。", "导师今天心情不错。"],
    "junior_xia": ["社团第一次开会。", "学姐好凶。", "海报终于做完了。"],
    "junior_gu": ["选课系统又崩了。", "求推荐选修。", "这学期课好多。"],
    "classmate_qi": ["笔记整理好了，要的吱声。", "图书馆今天人好多。", "复习进度到哪了？"],
    "classmate_he": ["球场今天被占了。", "打球吗？", "体育课又跑圈。"],
    "roommate_shen": ["隔壁宿舍来串门。", "今天楼里好安静。", "有人一起点外卖吗？"],
    "dorm_aunt": ["查寝了，收好插排。", "晚归记得登记。", "楼道别堆东西。"],
    "security": ["今天门口车好多。", "晚上记得锁门。", "又有人忘带卡。"],
    "repairman": ["配件还没到。", "今天跑三单。", "这活不好干。"],
    "print_shop": ["论文季，打印排队。", "今天机器又卡纸。", "彩印涨价了。"],
    "fruit_boss": ["今天橘子甜。", "新到草莓。", "来点啥？"],
    "barber": ["今天剪了三个头。", "有人办卡吗？", "这发型适合你。"],
    "laundry": ["衣服洗好了，记得取。", "洗衣机又满了。", "晚了要关机器。"],
    "shop_neighbor": ["隔壁又来借冰块。", "今天两家都爆单。", "外卖骑手堵门口了。"],
    "courier_station": ["午高峰提前了。", "今天骑手不够。", "餐又超时了。"],
    "customer_student": ["今天还是老样子。", "下课又来一杯。", "明天有早八。"],
    "customer_office": ["下午三点，续命。", "今天开会开到吐。", "明天还要早起。"],
    "club_junior": ["海报改到第三版。", "招新还差人。", "场地终于批了。"],
    "volunteer": ["今天搬了一下午物资。", "志愿时长终于够了。", "下次活动还来吗？"],
    "game_friend": ["今晚开黑吗？", "匹配到神仙队友。", "又掉分了。"],
    "fan_friend": ["物料到了！！", "今晚蹲直播。", "我担今天好帅。"],
    "online_senior": ["深夜树洞营业。", "今天也没睡。", "有些话只能晚上说。"],
}

GENERIC_POSTS = {
    "室友": ["今天宿舍好安静。", "谁把阳台门关了？", "垃圾又满了，服了。"],
    "老师": ["下节课记得带教材。", "作业截止时间别记错。", "这次成绩出来了。"],
    "店长": ["今天店里忙到脚不沾地。", "排班表又改了。", "卫生检查别掉链子。"],
    "同事": ["今天又是打工人。", "下班了吗？", "求一个替我上班的人。"],
    "闺蜜": ["今天也想被人抱抱。", "周末有人约吗？", "突然好想你。"],
    "家人": ["家里一切都好，你别惦记。", "记得按时吃饭。", "天冷了，多穿点。"],
    "网友": ["刷到一个很好笑的视频。", "今天不想睡。", "有人在线吗？"],
}

COMMENTS = {
    "mom": ["早点回家", "穿厚点", "别熬夜", "钱够不够花"],
    "dad": ["嗯", "注意身体", "不够就说"],
    "xiaomei": ["借我用一下嘛", "哈哈哈哈", "真的假的", "我也要"],
    "wangjie": ["明天别迟到", "知道了", "排班自己看"],
    "ajie": ["笑死", "摸鱼被抓", "带我一个"],
    "xiaoyu": ["抱抱", "我也是", "今天好难", "加油"],
    "linlin": ["想你了", "抱抱", "改天见面", "视频吗"],
    "yuanyuan": ["啊啊啊真的吗", "他回你了？", "恋爱脑发作"],
    "chenyu": ["进度呢", "别忘了截止", "收到回一下"],
    "zhang": ["上课认真听", "作业记得交"],
    "grandma": ["回来吃饭", "给你留了菜", "别瘦了"],
    "cat": ["哈哈哈哈哈", "发我发我", "笑不活了"],
}

GENERIC_COMMENTS = [
    "哈哈哈哈", "真的假的", "抱抱", "我也是", "改天一起", "早点睡",
    "这也太离谱了", "看饿了", "加油", "别太累", "笑死", "下次叫我",
    "好羡慕", "太真实了", "辛苦啦",
]


# ---- v5.9：动态文案的时段 / 话题分类，避免“半夜发早安”“配图跟文字无关” ----
SLOT_WORDS = {
    "morning": ("早安", "早上", "起床", "早饭", "第一节课", "早八", "晨跑"),
    "noon": ("午饭", "中午", "饭点", "食堂", "干饭", "饿了"),
    "afternoon": ("下午", "午睡"),
    "evening": ("下班", "晚上", "打烊", "收工", "傍晚", "回家"),
    "night": ("晚安", "准备睡", "睡不着", "熬夜", "夜里", "凌晨", "半夜"),
}
SLOT_ORDER = ("night", "morning", "noon", "afternoon", "evening")

TOPIC_WORDS = {
    "food": ("吃", "饭", "奶茶", "咖啡", "冰美式", "夜宵", "干饭", "橘子", "草莓", "蛋糕", "食堂", "外卖", "甜"),
    "study": ("图书馆", "自习", "笔记", "复习", "背书", "作业", "论文", "考试", "上课", "选课", "实验"),
    "outdoor": ("天气", "雨", "太阳", "降温", "冷", "热", "路上", "校园", "街", "院子", "桂花", "花", "天空", "门口"),
    "work": ("店", "排班", "上班", "下班", "忙", "骑手", "送餐", "维修", "巡店", "收银", "客人"),
    "rest": ("睡", "困", "累", "熬夜", "起不来", "躺"),
    "social": ("见面", "视频", "想你", "约", "一起", "聊天", "群"),
}

ROLE_SLOT_POSTS = {
    "student": {
        "morning": ("早八，人已经在教室了。", "今天起得比闹钟早一点。"),
        "noon": ("食堂排队排到怀疑人生。", "午饭随便吃两口，下午还有课。"),
        "afternoon": ("下午的课好长。", "图书馆坐了一下午，腰酸。"),
        "evening": ("今天的作业总算写完一半。", "晚上回去洗个澡就睡。"),
        "night": ("准备睡了，明天还有早八。", "宿舍熄灯了，你也早点睡。"),
    },
    "work": {
        "morning": ("店里刚开门，先把料备上。", "今天的排班又是满的。"),
        "noon": ("午高峰忙到没空喝水。", "刚扒了两口饭又来人。"),
        "afternoon": ("下午稍微空一点。", "站一天，腿已经不是自己的了。"),
        "evening": ("终于打烊了，收拾完就走。", "下班那一刻，灵魂回笼。"),
        "night": ("夜班收尾，回家就倒。", "这个点才吃上饭。"),
    },
    "teacher": {
        "morning": ("第一节课，先点到。", "今天的课准备得差不多了。"),
        "noon": ("中午改作业改到眼花。", "饭点学生还在问问题。"),
        "afternoon": ("下午连上两节，嗓子哑了。", "教研室今天格外安静。"),
        "evening": ("作业终于改完了。", "晚上备明天的课。"),
        "night": ("备完课就睡。", "这届学生问题真多。"),
    },
    "delivery": {
        "morning": ("早高峰单子多，先跑了。", "今天第一单就超时。"),
        "noon": ("午高峰，根本停不下来。", "电梯又坏了，爬了六楼。"),
        "afternoon": ("下午单少一点，歇口气。", "太阳太晒，水喝完了。"),
        "evening": ("晚高峰又开始了。", "最后一单送完就收工。"),
        "night": ("夜宵单还有人点。", "这个点还在路上。"),
    },
    "family": {
        "morning": ("早上买了点菜。", "今天起得早，去公园走了走。"),
        "noon": ("中午做了两个菜。", "记得按时吃饭。"),
        "afternoon": ("下午在家收拾了一下。", "院子里坐了一会儿。"),
        "evening": ("晚饭吃了，你别惦记。", "晚上看会儿电视就睡。"),
        "night": ("早点睡，别熬夜。", "家里都挺好。"),
    },
    "friend": {
        "morning": ("早，今天有什么安排？", "一醒来就在想周末去哪。"),
        "noon": ("中午吃啥，求推荐。", "刚点了个外卖。"),
        "afternoon": ("下午有点困，摸鱼中。", "刷到一个超好笑的视频。"),
        "evening": ("今天终于忙完了。", "晚上有人约吗？"),
        "night": ("还没睡，聊会儿？", "今天就到这，晚安。"),
    },
    "online": {
        "morning": ("刚醒，先刷会儿手机。", "早，今天也上线了。"),
        "noon": ("午饭配视频，绝了。", "中午不睡，下午崩溃。"),
        "afternoon": ("下午摸鱼时间。", "刷到一个离谱的帖子。"),
        "evening": ("晚上上线了。", "今天也没干什么正事。"),
        "night": ("深夜营业中。", "这个点还没睡。"),
    },
    "other": {
        "morning": ("早上好。", "今天起得还行。"),
        "noon": ("吃饭了吗？", "中午随便吃点。"),
        "afternoon": ("下午有点忙。", "今天过得一般。"),
        "evening": ("今天总算结束了。", "晚上歇一会儿。"),
        "night": ("准备睡了。", "今天就这样吧。"),
    },
}

ROLE_CATEGORY_WORDS = (
    ("teacher", ("老师", "助教")),
    ("student", ("学生", "同班", "学妹", "学弟", "室友", "考研", "学委", "社团", "学长", "学姐", "实验室")),
    ("delivery", ("外卖", "快递", "骑手", "维修", "保安")),
    ("work", ("店长", "店员", "同事", "站长", "经理", "奶茶", "宿管", "房东", "打印", "水果", "理发", "洗衣", "老板")),
    ("family", ("妈妈", "爸爸", "外婆", "外公", "舅舅", "舅妈", "表哥", "表姐", "表妹", "堂妹", "小姨", "家人")),
    ("online", ("网友", "线上", "树洞")),
    ("friend", ("闺蜜", "朋友", "同学")),
)

IMAGE_TOPIC_WORDS = {
    "food": ("milk", "tea", "coffee", "cake", "food", "eat"),
    "study": ("library", "book", "study", "paper"),
    "outdoor": ("campus", "street", "road", "sky", "park", "garden"),
    "work": ("shop", "store", "work", "bar"),
    "rest": ("sleep", "bed", "night"),
    "social": ("friend", "meet", "chat", "group"),
}


def _role_category(role: str) -> str:
    role = str(role or "")
    for name, words in ROLE_CATEGORY_WORDS:
        if any(word in role for word in words):
            return name
    return "other"


def _hour_slot(hour: float) -> str:
    if 5 <= hour < 10:
        return "morning"
    if 10 <= hour < 14:
        return "noon"
    if 14 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 22:
        return "evening"
    return "night"


def _text_slot(text: str) -> str | None:
    text = str(text or "")
    for slot in SLOT_ORDER:
        if any(word in text for word in SLOT_WORDS[slot]):
            return slot
    return None


def _text_topic(text: str) -> str:
    text = str(text or "")
    for topic in ("food", "study", "outdoor", "work", "rest", "social"):
        if any(word in text for word in TOPIC_WORDS[topic]):
            return topic
    return ""


def _image_topic(path: Path) -> str:
    name = path.name.lower()
    for topic, words in IMAGE_TOPIC_WORDS.items():
        if any(word in name for word in words):
            return topic
    return ""


def _avatar_color(name: str) -> str:
    seed = int(md5(str(name).encode("utf-8")).hexdigest()[:8], 16)
    return AVATAR_COLORS[seed % len(AVATAR_COLORS)]


def _role_personality(role: str) -> str:
    role = str(role or "")
    for key, value in (
        ("室友", "同居 · 日常摩擦"),
        ("老师", "严格 · 有距离"),
        ("店长", "精明 · 强势"),
        ("闺蜜", "亲近 · 爱聊"),
        ("妈妈", "操心 · 爱催"),
        ("爸爸", "话少 · 可靠"),
        ("同班", "同学 · 各忙各的"),
        ("网友", "线上 · 时差党"),
        ("同事", "一起打工"),
        ("学长", "社团 · 前辈"),
        ("外婆", "护短 · 疼人"),
    ):
        if key in role:
            return value
    return "社会关系 · 普通日常"


def _generic_posts(node: dict) -> list[str]:
    role = str(node.get("role") or "")
    for key, texts in GENERIC_POSTS.items():
        if key in role:
            return texts
    return ["今天有点累，先说晚安。", "有些事想不通，明天再说。", "心情一般，但还能过。", "突然想吃点甜的。"]


def _comment_text(user_id: str, target: str) -> str:
    options = COMMENTS.get(user_id) or GENERIC_COMMENTS
    rng = random.Random(f"{target}:c:{user_id}")
    return rng.choice(options)


# ---- v6.2：NPC 轻量人格层，用一次 LLM 批量写朋友圈评论 ----
NPC_LLM_LOCK = threading.Lock()
NPC_LLM_INFLIGHT: set[str] = set()
NPC_LLM_SEM = threading.Semaphore(2)  # 手机端最多同时跑 2 个评论生成
NPC_LLM_SYSTEM = (
    "你是中文朋友圈里的普通社会关系成员。你只写符合自己身份和关系的短评论，"
    "口语化、有生活气，不解释、不总结、不客服腔，绝不暴露自己是模型或 AI。"
)


def _extract_json_array(raw: str) -> list:
    text = str(raw or "").strip()
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except Exception:  # noqa: BLE001
        return []
    return data if isinstance(data, list) else []


class WebBridge:
    """实现 ChatWindow 的那组回调，把消息塞进事件队列。"""

    def __init__(self, runtime: "MobileRuntime"):
        self.runtime = runtime
        self.events: deque[dict] = deque(maxlen=600)
        self.next_id = 1
        self.lock = threading.Lock()
        self.last_status = "启动中"

    def _emit(self, kind: str, payload: dict) -> None:
        with self.lock:
            self.events.append({"id": self.next_id, "type": kind, **payload})
            self.next_id += 1

    def _notify(self, text: str) -> None:
        """App 在后台时弹通知：手机走 Java，桌面走 Windows 通知钩子。"""
        title = "小鲸鱼"
        try:
            title = str(self.runtime._read_profile().get("her_name") or title)
        except Exception:  # noqa: BLE001
            pass
        try:
            from java import jclass

            jclass("com.ganfanyu.app.Notifier").show(title, str(text)[:120])
            return
        except Exception:  # noqa: BLE001
            pass
        if NOTIFY_HOOK is not None:
            try:
                NOTIFY_HOOK(title, str(text)[:120])
            except Exception:  # noqa: BLE001
                pass

    def post(self, fn, *args) -> None:
        name = getattr(fn, "__name__", "")
        if name in ("show_text", "show_text_quote", "show_text_id"):
            who, text = args[0], args[1]
            payload = {"who": str(who), "text": str(text)}
            if name == "show_text_quote" and len(args) >= 3:
                try:
                    name_ = str(self.runtime._read_profile().get("nickname") or "你")
                except Exception:  # noqa: BLE001
                    name_ = "你"
                payload["quote"] = {"name": name_[:20], "text": str(args[2])[:80]}
            elif name == "show_text_id":
                mid = int(args[2] or 0) if len(args) >= 3 else 0
                quote_text = str(args[3] or "") if len(args) >= 4 else ""
                if mid:
                    payload["message_id"] = mid
                if quote_text:
                    try:
                        name_ = str(self.runtime._read_profile().get("nickname") or "你")
                    except Exception:  # noqa: BLE001
                        name_ = "你"
                    payload["quote"] = {"name": name_[:20], "text": quote_text[:80]}
            self._emit("text", payload)
            if str(who) == "her":
                self._notify(str(text))
        elif name == "show_sticker":
            path = str(args[0])
            self._emit("sticker", {"path": path, "url": "/media?path=" + quote(path)})
            self._notify("发来一个表情包")
        elif name == "show_my_sticker":
            path, tag = str(args[0]), str(args[1])
            self._emit("my_sticker", {"path": path, "tag": tag, "url": "/media?path=" + quote(path)})
        elif name == "show_my_image":
            path = str(args[0])
            self._emit("my_image", {"path": path, "url": "/media?path=" + quote(path)})
        elif name == "show_recall":
            self._emit(
                "recall",
                {"message_id": int(args[0] or 0), "text": str(args[1] or "")[:200]},
            )
        elif name == "show_dynamic":
            text, images = str(args[0]), list(args[1] or [])
            urls = ["/media?path=" + quote(str(p)) for p in images]
            self._emit("dynamic", {"text": text, "images": urls})
            self._notify("发了一条动态")
        elif name == "show_link":
            payload = args[0] or {}
            self._emit("link", {"link": payload})
        elif name == "show_system":
            self._emit("system", {"text": str(args[0])})
        elif name == "set_typing":
            self._emit("typing", {"on": bool(args[0])})
        elif name == "set_status":
            self.last_status = str(args[0])
            self._emit("status", {"text": self.last_status})
        elif name == "show_history":
            rows = []
            for m in args[0] or []:
                media = str(m.get("media") or "")
                media_path = Path(media) if media else None
                rows.append(
                    {
                        "role": str(m.get("role") or ""),
                        "content": str(m.get("content") or ""),
                        "kind": str(m.get("kind") or "text"),
                        "ts": m.get("ts") or m.get("created_at"),
                        "image_url": (
                            self.runtime._media_url(media_path)
                            if media_path is not None and media_path.is_file()
                            else ""
                        ),
                    }
                )
            self._emit("history", {"messages": rows})
        elif name:
            log.debug("未处理界面回调：%s", name)

    def cursor(self) -> int:
        """当前事件游标：拉历史后把 since 对齐到这里，避免历史与事件重复上屏。"""
        with self.lock:
            return self.next_id

    def prepare_app(self, app) -> None:
        """手机端启动前准备：首次导入 seed 时清掉电脑端的今日完成标记。"""
        self.runtime._mobile_local_init(app)

    # ChatEngine 会直接调用这些方法
    def show_system(self, text: str) -> None:
        self._emit("system", {"text": str(text)})

    def show_text(self, who: str, text: str) -> None:
        self._emit("text", {"who": str(who), "text": str(text)})

    def show_text_quote(self, who: str, text: str, quote_text: str) -> None:
        """她的回复引用他刚发的那条消息（手机端 QQ 式引用）。"""
        name = "你"
        try:
            name = str(self.runtime._read_profile().get("nickname") or "你")
        except Exception:  # noqa: BLE001
            pass
        self._emit(
            "text",
            {
                "who": str(who),
                "text": str(text),
                "quote": {"name": name[:20], "text": str(quote_text)[:80]},
            },
        )

    def show_text_id(self, who: str, text: str, message_id: int, quote_text: str = "") -> None:
        """第一段回复带数据库消息 ID，前端用它和已加载的历史去重。"""
        payload = {"who": str(who), "text": str(text)}
        mid = int(message_id or 0)
        if mid:
            payload["message_id"] = mid
        if str(quote_text or "").strip():
            name = "你"
            try:
                name = str(self.runtime._read_profile().get("nickname") or "你")
            except Exception:  # noqa: BLE001
                pass
            payload["quote"] = {"name": name[:20], "text": str(quote_text)[:80]}
        self._emit("text", payload)
        if str(who) == "her":
            self._notify(str(text))

    def show_sticker(self, path: str) -> None:
        self._emit("sticker", {"path": str(path), "url": "/media?path=" + quote(str(path))})

    def show_my_sticker(self, path: str, tag: str) -> None:
        self._emit(
            "my_sticker",
            {"path": str(path), "tag": str(tag), "url": "/media?path=" + quote(str(path))},
        )

    def show_my_image(self, path: str) -> None:
        self._emit("my_image", {"path": str(path), "url": "/media?path=" + quote(str(path))})

    def show_recall(self, message_id: int, text: str) -> None:
        """她撤回了一条消息：界面按内容移除气泡。"""
        self._emit("recall", {"message_id": int(message_id or 0), "text": str(text)[:200]})

    def show_dynamic(self, text: str, images: list[str]) -> None:
        urls = ["/media?path=" + quote(str(p)) for p in (images or [])]
        self._emit("dynamic", {"text": str(text), "images": urls})

    def show_link(self, payload: dict) -> None:
        self._emit("link", {"link": payload or {}})

    def show_history(self, rows) -> None:
        payload = []
        for m in rows or []:
            media = str(m.get("media") or "")
            media_path = Path(media) if media else None
            payload.append(
                {
                    "id": m.get("id"),
                    "role": str(m.get("role") or ""),
                    "content": str(m.get("content") or ""),
                    "kind": str(m.get("kind") or "text"),
                    "ts": m.get("ts") or m.get("created_at"),
                    "image_url": (
                        self.runtime._media_url(media_path)
                        if media_path is not None and media_path.is_file()
                        else ""
                    ),
                }
            )
        self._emit("history", {"messages": payload})

    def set_status(self, text: str) -> None:
        self.last_status = str(text)
        self._emit("status", {"text": self.last_status})

    def set_typing(self, on: bool) -> None:
        self._emit("typing", {"on": bool(on)})

    def snapshot(self, since: int) -> dict:
        with self.lock:
            rows = [e for e in self.events if int(e["id"]) > since]
            # next 返回“已经发出的最后一个 id”；返回 next_id 会漏掉恰好等于它的新事件
            return {"next": self.next_id - 1, "events": rows}


class MobileRuntime:
    def __init__(self, root: Path):
        self.root = root
        # 网页根目录：手机端是解压目录下的 web/，桌面版可以指向源码里的 mobile/web
        web_env = os.getenv("BRAINN_WEB_DIR", "").strip()
        self.web_root = Path(web_env) if web_env else (root / "web")
        self.bridge = WebBridge(self)
        self.engine = None
        self.whale = None
        self.config = None
        self.starting = False
        self.error = ""
        self.profile_file = root / "profile" / "profile.json"
        self.her_avatar = self.web_root / "her.png"
        self.default_me = self.web_root / "me.png"
        self._screen_thread: threading.Thread | None = None
        self._sticker_search_cache: dict[str, dict] = {}
        self._persona_lock = threading.Lock()
        self._persona_busy = False
        self._world_weather_cache: dict[str, dict] = {}
        self.world_sessions: dict[str, dict] = {}
        self.world_lock = threading.Lock()
        self._place_anchors = None
        self._place_store = None

    # ------------------------------------------------------------------
    def _normalize_persona_file(self) -> None:
        """把覆盖文件里的旧名字写成小鲸鱼，避免下次启动又读回旧身份。"""
        path = self.root / "config" / "persona_overrides.yaml"
        if not path.exists():
            return
        try:
            from brainn.config import _unify_persona_name

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                return
            clean = _unify_persona_name(dict(data))
            if clean == data:
                return
            path.write_text(
                yaml.safe_dump(clean, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            log.info("人设旧名字已统一为小鲸鱼")
        except Exception:  # noqa: BLE001
            log.warning("统一人设文件名字失败", exc_info=True)

    def load(self) -> None:
        from brainn.config import load_config

        self._normalize_persona_file()
        self.config = load_config()
        # 9.0 起动态功能已下线：直接停掉定时生成，避免后台继续写没人看的内容
        try:
            self.config.settings.setdefault("dynamic", {})["enabled"] = False
        except Exception:  # noqa: BLE001
            pass
        try:
            from brainn.whale_brain import WhaleBrain

            if self.whale is not None:
                try:
                    self.whale.stop()
                except Exception:  # noqa: BLE001
                    log.warning("停止旧的小鲸鱼大脑失败", exc_info=True)
            # 小鲸鱼与主聊天是同一个存在：共用数据目录、人格、记忆、心情与身体
            self.whale = WhaleBrain(
                self.root,
                self.config.settings,
                shared_data_dir=self.root / "data",
                shared_persona=self.config.persona,
                # 保存写 overrides：主配置先读 persona.yaml 再合并这份，写这里才真正生效
                shared_persona_path=self.root / "config" / "persona_overrides.yaml",
            )
        except Exception:  # noqa: BLE001
            self.whale = None
            log.exception("初始化小鲸鱼大脑失败")

    def _read_profile(self) -> dict:
        try:
            if self.profile_file.exists():
                data = json.loads(self.profile_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:  # noqa: BLE001
            log.warning("读取个人资料失败\n%s", traceback.format_exc())
        return {}

    def profile(self) -> dict:
        data = self._read_profile()
        avatar = str(data.get("avatar") or "")
        avatar_path = self.root / avatar if avatar else self.default_me
        if not avatar_path.exists():
            avatar_path = self.default_me
        her_avatar = str(data.get("her_avatar") or "")
        her_path = self.root / her_avatar if her_avatar else self.her_avatar
        if not her_path.exists():
            her_path = self.her_avatar
        cover = str(data.get("cover") or "")
        cover_path = self.root / cover if cover else None
        chat_bg = str(data.get("chat_bg") or "")
        chat_bg_path = self.root / chat_bg if chat_bg else None
        her_name = str(data.get("her_name") or "小鲸鱼")[:20]
        for old in ("陈雨棠", "干饭鱼", "鱼鱼"):
            her_name = her_name.replace(old, "小鲸鱼")
        return {
            "nickname": str(data.get("nickname") or "我")[:20],
            "signature": str(data.get("signature") or "")[:60],
            "avatar_url": self._media_url(avatar_path) if avatar_path.exists() else "",
            "her_name": her_name,
            "her_avatar_url": self._media_url(her_path) if her_path.exists() else "",
            "cover_url": self._media_url(cover_path) if cover_path and cover_path.exists() else "",
            "chat_bg_url": self._media_url(chat_bg_path) if chat_bg_path and chat_bg_path.exists() else "",
        }

    def save_profile(self, nickname: str, signature: str, her_name: str = "") -> dict:
        data = self._read_profile()
        data["nickname"] = str(nickname or "我").strip()[:20] or "我"
        data["signature"] = str(signature or "").strip()[:60]
        if str(her_name or "").strip():
            name = str(her_name).strip()[:20]
            for old in ("陈雨棠", "干饭鱼", "鱼鱼"):
                name = name.replace(old, "小鲸鱼")
            data["her_name"] = name
        self.profile_file.parent.mkdir(parents=True, exist_ok=True)
        self.profile_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if self.engine and getattr(self.engine, "app", None):
            try:
                self.engine.app.store.set_state("mobile_user_name", data["nickname"])
            except Exception:  # noqa: BLE001
                pass
        return self.profile()

    def save_avatar(self, raw: bytes, target: str = "me") -> dict:
        if target == "her":
            return self._save_avatar(raw, "her.jpg", "her_avatar")
        return self._save_avatar(raw, "me.jpg", "avatar")

    def save_cover(self, raw: bytes) -> dict:
        from io import BytesIO

        from PIL import Image, ImageOps

        if not raw:
            raise ValueError("空图片")
        with Image.open(BytesIO(raw)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img = ImageOps.fit(img, (1080, 540), Image.LANCZOS)
            target = self.root / "profile" / "cover.jpg"
            target.parent.mkdir(parents=True, exist_ok=True)
            img.save(target, "JPEG", quality=88)
        data = self._read_profile()
        data["cover"] = "profile/cover.jpg"
        self.profile_file.parent.mkdir(parents=True, exist_ok=True)
        self.profile_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return self.profile()

    def save_chat_bg(self, raw: bytes) -> dict:
        from io import BytesIO

        from PIL import Image, ImageOps

        if not raw:
            raise ValueError("空图片")
        with Image.open(BytesIO(raw)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.thumbnail((1600, 1600), Image.LANCZOS)
            target = self.root / "profile" / "chat_bg.jpg"
            target.parent.mkdir(parents=True, exist_ok=True)
            img.save(target, "JPEG", quality=88)
        data = self._read_profile()
        data["chat_bg"] = "profile/chat_bg.jpg"
        self.profile_file.parent.mkdir(parents=True, exist_ok=True)
        self.profile_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return self.profile()

    def clear_chat_bg(self) -> dict:
        data = self._read_profile()
        data.pop("chat_bg", None)
        self.profile_file.parent.mkdir(parents=True, exist_ok=True)
        self.profile_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return self.profile()

    def _save_avatar(self, raw: bytes, filename: str, field: str) -> dict:
        from io import BytesIO

        from PIL import Image, ImageOps

        if not raw:
            raise ValueError("空图片")
        with Image.open(BytesIO(raw)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img = ImageOps.fit(img, (384, 384), Image.LANCZOS)
            target = self.root / "profile" / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            img.save(target, "JPEG", quality=88)
        data = self._read_profile()
        data[field] = f"profile/{filename}"
        self.profile_file.parent.mkdir(parents=True, exist_ok=True)
        self.profile_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return self.profile()

    def save_user_photo(self, raw: bytes) -> Path:
        """接收相机/相册照片，压到长边 1600，存进私有 uploads 目录。"""
        from io import BytesIO

        from PIL import Image, ImageOps

        if not raw:
            raise ValueError("空图片")
        with Image.open(BytesIO(raw)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.thumbnail((1600, 1600), Image.LANCZOS)
            folder = self.root / "profile" / "uploads"
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"photo_{time.time_ns()}.jpg"
            img.save(target, "JPEG", quality=88)
        return target

    def save_tool_file(self, raw: bytes, name: str) -> dict:
        safe = re.sub(r"[^0-9A-Za-z_.\-\u4e00-\u9fa5]", "_", str(name or "file"))[:80] or "file"
        suffix = Path(safe).suffix.lower()
        image_ext = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
        text_ext = (".txt", ".md", ".csv", ".json", ".py", ".log", ".html", ".xml", ".yaml", ".yml")
        kind = "image" if suffix in image_ext else ("text" if suffix in text_ext else "binary")
        folder = self.root / "profile" / "tool_uploads"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{time.time_ns()}_{safe}"
        target.write_bytes(raw)
        return {
            "ok": True,
            "path": str(target.resolve()),
            "url": self._media_url(target),
            "name": safe,
            "kind": kind,
        }

    def save_sticker(self, raw: bytes, name: str) -> dict:
        """导入本地表情：png/jpg/gif/webp 原样保存，gif 保留动画。"""
        safe = re.sub(r"[^0-9A-Za-z_.\-\u4e00-\u9fa5]", "_", str(name or "sticker"))[:80] or "sticker"
        suffix = Path(safe).suffix.lower()
        if suffix not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            return {"ok": False, "error": "unsupported_type"}
        if not raw:
            return {"ok": False, "error": "empty"}
        folder = self.root / "assets" / "stickers" / "imported"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{time.time_ns()}_{safe}"
        target.write_bytes(raw)
        url = self._media_url(target)
        return {
            "ok": True,
            "tag": "imported",
            "path": str(target.resolve()),
            "url": url,
            "thumb": url,
            "name": safe,
        }

    def _sticker_thumb(self, path: Path) -> str:
        thumb = self.root / "assets" / "stickers" / "thumbs" / (path.stem + ".jpg")
        return self._media_url(thumb) if thumb.is_file() else self._media_url(path)

    def stickers(self) -> list[dict]:
        base = self.root / "assets" / "stickers"
        out = []
        seen = set()
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                continue
            if path.parent.name not in ("online", "imported"):
                continue
            resolved = str(path.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            stem = path.stem
            if path.parent.name == "imported":
                tag = "imported"
            elif "_online_" in stem:
                tag = stem.split("_online_")[0]
            else:
                tag = stem.split("_")[0]
            if not tag or tag == "custom":
                tag = "happy"
            url = self._media_url(path)
            out.append({"tag": tag, "url": url, "thumb": self._sticker_thumb(path), "path": resolved})
        return out[:160]

    @staticmethod
    def _media_url(path: Path) -> str:
        return "/media?path=" + quote(str(path.resolve()))

    def search_stickers_online(self, query: str, limit: int = 8) -> dict:
        """联网搜表情包：搜图 → 下载到私有缓存 → 返回本地 /media 地址。"""
        q = str(query or "").strip()
        if not q:
            return {"ok": False, "error": "empty", "items": []}
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"ok": False, "error": "not_ready", "items": []}
        cached = self._sticker_search_cache.get(q.lower())
        if cached and time.time() - cached.get("ts", 0) < 600:
            return cached.get("data") or {"ok": False, "items": []}
        folder = self.root / "profile" / "sticker_cache"
        folder.mkdir(parents=True, exist_ok=True)

        async def _run() -> list:
            urls = await app.media.search_image_urls(q, limit=18)
            if not urls:
                urls = await app.media.search_image_urls(q + " 表情包", limit=18)
            if not urls:
                return []
            tasks = [
                app.media._download_valid_image(
                    url, square=False, min_side=80, max_side=1600
                )
                for url in urls[:12]
            ]
            return await asyncio.gather(*tasks, return_exceptions=True)

        try:
            results = asyncio.run(_run())
        except Exception:  # noqa: BLE001
            log.warning("表情包联网搜索失败\n%s", traceback.format_exc())
            results = []
        items = []
        for item in results:
            if not isinstance(item, tuple) or len(item) != 2:
                continue
            raw, suffix = item
            try:
                path = app.media._save_image(raw, suffix, folder, "search")
            except Exception:  # noqa: BLE001
                continue
            items.append(
                {"tag": "search", "url": self._media_url(path), "path": str(path)}
            )
            if len(items) >= limit:
                break
        data = {"ok": bool(items), "items": items, "query": q}
        self._sticker_search_cache[q.lower()] = {"ts": time.time(), "data": data}
        return data

    # ------------------------------------------------------------------
    # 工具鱼：纯模型对话，不接 BrainN 人格/仲裁
    # ------------------------------------------------------------------
    def toolfish_history(self) -> dict:
        app = getattr(self.engine, "app", None) if self.engine else None
        rows = app.store.recent_tool_messages(40) if app is not None else []
        return {
            "messages": [
                {"role": r.get("role"), "content": r.get("content"), "ts": r.get("ts")}
                for r in rows
            ]
        }

    def toolfish_clear(self) -> dict:
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is not None:
            app.store.clear_tool_messages()
        return {"ok": True}

    def _toolfish_tool(self, text: str, app) -> tuple[str, str]:
        """返回 (工具名, 工具结果)。纯规则，不经过 BrainN。"""
        now = app.clock.now() if app is not None else dt.datetime.now()
        if any(w in text for w in ("几点", "时间", "日期", "几号", "星期几", "周几")):
            week = "一二三四五六日"[now.weekday()]
            return "时间", f"当前时间：{now.strftime('%Y-%m-%d %H:%M')} 星期{week}"
        expr_match = re.search(r"([0-9][0-9\s+\-*/().%]{1,60})", text)
        if expr_match:
            expr = expr_match.group(1).strip()
            if re.search(r"\d\s*[+\-*/%]\s*\d", expr):
                try:
                    value = eval(expr, {"__builtins__": {}}, {})  # noqa: S307
                    return "计算器", f"{expr} = {value}"
                except Exception:  # noqa: BLE001
                    pass
        try:
            from brainn.web import WebSurf

            kind, query = WebSurf.request_kind(text)
        except Exception:  # noqa: BLE001
            kind, query = "", ""
        if kind:
            if app is None:
                return "联网搜索", "联网工具不可用：BrainN 服务还没启动。"
            try:
                items = (
                    asyncio.run(app.web.search(query))
                    if kind == "search"
                    else asyncio.run(app.web.trending(force=True))
                )
            except Exception:  # noqa: BLE001
                items = []
            if not items:
                return "联网搜索", "联网搜索没有返回结果，不要编造。"
            lines = []
            for item in items[:6]:
                lines.append(
                    f"- {item.get('title', '')}（{item.get('source', '')}）"
                    f"{str(item.get('desc') or '')[:80]}"
                )
            return ("联网搜索" if kind == "search" else "热榜"), "搜索结果：\n" + "\n".join(lines)
        return "", ""

    def toolfish_chat(self, text: str, attachments: list | None = None) -> dict:
        text = str(text or "").strip()[:2000]
        base = (self.root / "profile" / "tool_uploads").resolve()
        paths: list[Path] = []
        for raw in attachments or []:
            item = Path(str(raw)).resolve()
            if base in item.parents and item.is_file() and len(paths) < 3:
                paths.append(item)
        if not text and not paths:
            return {"ok": False, "error": "empty"}
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"ok": False, "error": "not_ready"}
        if not self.config.deepseek_key:
            return {"ok": False, "error": "no_key"}
        cfg = dict((self.config.settings.get("llm") or {}) if self.config else {})
        current_model = str(getattr(getattr(app, "llm", None), "model", "") or "")
        if current_model:
            cfg["model"] = current_model
        from brainn.llm import LLM

        llm = LLM(cfg, self.config.deepseek_key)
        image_ext = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
        text_ext = (".txt", ".md", ".csv", ".json", ".py", ".log", ".html", ".xml", ".yaml", ".yml")
        attachment_notes: list[str] = []
        names: list[str] = []
        for path in paths:
            names.append(path.name)
            suffix = path.suffix.lower()
            if suffix in image_ext:
                note = ""
                try:
                    note = asyncio.run(llm.describe_image_from_bytes(path.read_bytes()))
                except Exception:  # noqa: BLE001
                    note = ""
                attachment_notes.append(f"【图片：{path.name}】{note or '（图片没能解析）'}")
            elif suffix in text_ext:
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")[:6000]
                except Exception:  # noqa: BLE001
                    content = ""
                attachment_notes.append(f"【文件：{path.name}】\n{content}")
            else:
                attachment_notes.append(f"【文件：{path.name}】不支持直接读取内容，只能根据文件名回答。")
        stored_text = text + (("（附件：" + "、".join(names) + "）") if names else "")
        app.store.add_tool_message("user", stored_text)
        tool_name, tool_note = self._toolfish_tool(text, app)
        rows = app.store.recent_tool_messages(14)
        history_lines = []
        for row in rows:
            who = "用户" if row.get("role") == "user" else "工具鱼"
            history_lines.append(f"{who}：{row.get('content')}")
        system = (
            "你是 BrainN 里的“工具鱼”，一个纯粹的通用 AI 助手和工具代理。"
            "不要扮演小鲸鱼，不要使用 BrainN 的人格、情绪、关系、日程或生活设定，"
            "也不要说自己有身体、住哪里、在做什么。直接、准确、简洁地回答。"
            "不确定就直说，不要编造。若提供了【工具结果】或【用户附件】，"
            "只依据这些内容回答，不要编造没提供的信息。"
        )
        prompt = "以下是最近的对话：\n" + "\n".join(history_lines)
        if tool_note:
            prompt += f"\n\n【工具结果·{tool_name}】\n{tool_note}"
        if attachment_notes:
            prompt += "\n\n【用户附件】\n" + "\n\n".join(attachment_notes)
        prompt += f"\n\n请回答最后一条用户消息：{text or '请看附件'}"
        try:
            reply = asyncio.run(
                llm.chat_text(system, prompt, temperature=0.3, max_tokens=1200)
            )
        except Exception:  # noqa: BLE001
            log.error("工具鱼调用失败\n%s", traceback.format_exc())
            reply = ""
        if not reply:
            reply = "（模型暂时没有返回内容，稍后再试）"
        app.store.add_tool_message("assistant", reply)
        return {
            "ok": True,
            "reply": reply,
            "tool": tool_name,
            "tool_note": tool_note,
            "attachments": names,
        }

    # ------------------------------------------------------------------
    # 架构参数 / 人格旋钮
    # ------------------------------------------------------------------
    _HIDE_SETTINGS = {"onebot", "storage", "owner_qq"}

    def config_payload(self) -> dict:
        if self.config is None:
            self.load()
        settings = json.loads(json.dumps(self.config.settings, ensure_ascii=False, default=str))
        for key in self._HIDE_SETTINGS:
            settings.pop(key, None)
        persona = json.loads(json.dumps(self.config.persona, ensure_ascii=False, default=str))
        knobs: dict = {}
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is not None:
            try:
                knobs = app.persona.knobs()
            except Exception:  # noqa: BLE001
                knobs = {}
        return {"settings": settings, "persona": persona, "knobs": knobs}

    def save_config(self, settings_patch: dict, persona_patch: dict) -> dict:
        cfg_dir = self.root / "config"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        for name, patch in (("settings", settings_patch), ("persona", persona_patch)):
            if not isinstance(patch, dict) or not patch:
                continue
            path = cfg_dir / f"{name}_overrides.yaml"
            current: dict = {}
            if path.exists():
                try:
                    current = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                except Exception:  # noqa: BLE001
                    current = {}
            _deep_merge(current, patch)
            path.write_text(
                yaml.safe_dump(current, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        self.load()
        return {"ok": True}

    def reset_config(self) -> dict:
        for name in ("settings", "persona"):
            path = self.root / "config" / f"{name}_overrides.yaml"
            if path.exists():
                path.unlink()
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is not None:
            try:
                app.store.set_state("persona_knobs", {})
                app.persona._knobs = dict(app.persona._base)
            except Exception:  # noqa: BLE001
                pass
        self.load()
        return {"ok": True}

    def set_knobs(self, patch: dict) -> dict:
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {}
        from brainn.persona import BOUNDS

        state = dict(app.store.get_state("persona_knobs") or {})
        for key, value in (patch or {}).items():
            if key not in BOUNDS:
                continue
            try:
                num = float(value)
            except (TypeError, ValueError):
                continue
            lo, hi = BOUNDS[key]
            state[key] = round(max(lo, min(hi, num)), 3)
        app.store.set_state("persona_knobs", state)
        try:
            app.persona._knobs.update(state)
        except Exception:  # noqa: BLE001
            pass
        return state

    # ------------------------------------------------------------------
    # 对话式人设调整
    # ------------------------------------------------------------------
    _PERSONA_TOP = {
        "name", "nickname", "age", "identity", "city", "core_traits", "speech",
        "relationship", "taboos", "emotion", "body", "proactive", "task_policy",
        "media", "evolution",
    }
    _SETTINGS_TOP = {
        "reply", "schedule", "weather", "dynamic", "memory", "social", "web",
        "brainn", "life", "timezone",
    }

    @staticmethod
    def _filter_patch(current: dict, patch: dict, allowed_top: set) -> dict:
        """只接收已存在字段，类型必须一致；数值/布尔/字符串原样，列表整体替换。"""
        if not isinstance(patch, dict) or not isinstance(current, dict):
            return {}
        out: dict = {}
        by_name = {str(k): k for k in current}
        for key, val in patch.items():
            name = str(key)
            if name not in allowed_top:
                continue
            target = by_name.get(name)
            if target is None:
                continue
            cur = current[target]
            if isinstance(cur, dict):
                if isinstance(val, dict):
                    sub = MobileRuntime._filter_patch(cur, val, {str(k) for k in cur})
                    if sub:
                        out[target] = sub
            elif isinstance(cur, list):
                if isinstance(val, list):
                    out[target] = val
            elif isinstance(cur, bool):
                if isinstance(val, bool):
                    out[target] = val
            elif isinstance(cur, (int, float)):
                try:
                    out[target] = float(val)
                except (TypeError, ValueError):
                    continue
            elif isinstance(cur, str):
                if isinstance(val, str):
                    out[target] = val[:3000]
        return out

    def _persona_prompt(self, persona: dict, settings: dict, knobs: dict) -> str:
        compact_settings = {
            "reply": settings.get("reply") or {},
            "schedule": settings.get("schedule") or {},
            "weather": settings.get("weather") or {},
            "dynamic": settings.get("dynamic") or {},
            "memory": settings.get("memory") or {},
            "social": settings.get("social") or {},
            "web": settings.get("web") or {},
            "brainn": {
                "enabled": (settings.get("brainn") or {}).get("enabled"),
                "shadow": (settings.get("brainn") or {}).get("shadow"),
                "profile": (settings.get("brainn") or {}).get("profile"),
                "drive_priority": (settings.get("brainn") or {}).get("drive_priority"),
            },
            "life": settings.get("life") or {},
        }
        current = {
            "persona": persona,
            "knobs": knobs,
            "settings": compact_settings,
        }
        return (
            "你是 BrainN 的“人设调整助手”。用户会用自然语言提出改人设、改说话方式、"
            "改生活节奏、改她所在城市或调整 BrainN 运行倾向。你要把要求翻译成安全的配置补丁。\n\n"
            "严格只输出一个 JSON 对象：\n"
            "{\n"
            '  "reply": "给用户的中文回复，简短口语，说明你理解了什么",\n'
            '  "summary": "一句话变更摘要",\n'
            '  "persona_patch": {},\n'
            '  "settings_patch": {},\n'
            '  "knobs": {},\n'
            '  "rebuild": false\n'
            "}\n\n"
            "规则：\n"
            "- 只输出真正要改的字段，不要整份复制；没提到的不要动。\n"
            "- persona 可改：name/nickname/age/identity/city/core_traits/speech/relationship/taboos/"
            "emotion/body/proactive/task_policy/media/evolution。\n"
            "- settings 可改：reply/schedule/weather/dynamic/memory/social/web/brainn/life/timezone。\n"
            "- 不能改 core_locked、editable_traits、owner_qq、onebot、storage、密钥。\n"
            "- knobs 只允许：talkativeness/clinginess/tease_level/care_level/sticker_rate/"
            "proactive_bias/cuteness，数值 0~2，单次变化尽量不超过 0.3。\n"
            "- 如果用户要把她换成完全不同的人（名字、身份、背景、城市变了），rebuild 设为 true，"
            "并在 settings_patch.life.weekly 里给出与新身份匹配的一周日程（周一到周日，"
            "每天 3~6 条，格式与当前 life.weekly 完全一致），同时调整 settings_patch.weather.city。\n"
            "- 如果只是语气、习惯、回复速度的微调，rebuild 设为 false。\n"
            "- speech.style 要写成她自己的口吻，不要写成说明书。\n"
            "- 不要输出 JSON 以外的任何文字。\n\n"
            "当前配置：\n"
            + json.dumps(current, ensure_ascii=False)
        )

    def persona_chat_state(self) -> dict:
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"ok": False, "error": "not_ready"}
        draft = app.store.get_state("persona_chat_draft") or {}
        return {
            "ok": True,
            "history": list(app.store.get_state("persona_chat_history") or [])[-20:],
            "draft": draft,
            "persona": self.config.persona if self.config else {},
            "knobs": app.persona.knobs(),
        }

    def persona_chat(self, message: str) -> dict:
        app = getattr(self.engine, "app", None) if self.engine else None
        text = str(message or "").strip()
        if app is None:
            return {"ok": False, "error": "not_ready"}
        if not text:
            return {"ok": False, "error": "empty"}
        llm = getattr(app, "llm", None)
        if llm is None or getattr(llm, "mock", False):
            return {"ok": False, "error": "no_key"}
        store = app.store
        history = list(store.get_state("persona_chat_history") or [])[-14:]
        draft = store.get_state("persona_chat_draft") or {}
        system = self._persona_prompt(
            self.config.persona if self.config else {},
            self.config.settings if self.config else {},
            app.persona.knobs(),
        )
        messages = [
            {"role": str(h.get("role") or "user"), "content": str(h.get("content") or "")[:1200]}
            for h in history
            if str(h.get("content") or "").strip()
        ]
        if draft:
            messages.append(
                {
                    "role": "assistant",
                    "content": "当前待应用的草稿：" + json.dumps(draft, ensure_ascii=False)[:4000],
                }
            )
        messages.append({"role": "user", "content": text})

        async def _run():
            return await llm.chat_json(
                system,
                messages,
                temperature=0.3,
                max_tokens=6000,
                require_segments=False,
                timeout=90,
            )

        try:
            if self.engine is not None and self.engine.loop is not None:
                fut = asyncio.run_coroutine_threadsafe(_run(), self.engine.loop)
                result = fut.result(timeout=100)
            else:
                result = asyncio.run(asyncio.wait_for(_run(), timeout=95))
        except Exception as exc:  # noqa: BLE001
            log.warning("人设调整模型失败：%s", exc)
            return {"ok": False, "error": "model_failed", "detail": str(exc)[:200]}
        if not isinstance(result, dict) or not result:
            return {"ok": False, "error": "model_failed"}
        if not any(k in result for k in ("reply", "summary", "persona_patch", "settings_patch", "knobs")):
            return {"ok": False, "error": "model_failed"}

        reply = str(result.get("reply") or "").strip() or "我记下了，先按这个方向改。"
        summary = str(result.get("summary") or reply)[:300]
        persona_patch = self._filter_patch(
            self.config.persona if self.config else {}, result.get("persona_patch"), self._PERSONA_TOP
        )
        settings_patch = self._filter_patch(
            self.config.settings if self.config else {}, result.get("settings_patch"), self._SETTINGS_TOP
        )
        knobs_patch: dict = {}
        try:
            from brainn.persona import BOUNDS

            for key, value in (result.get("knobs") or {}).items():
                if key not in BOUNDS:
                    continue
                try:
                    num = float(value)
                except (TypeError, ValueError):
                    continue
                lo, hi = BOUNDS[key]
                knobs_patch[key] = round(max(lo, min(hi, num)), 3)
        except Exception:  # noqa: BLE001
            knobs_patch = {}

        draft_persona = _deep_merge(
            json.loads(json.dumps(draft.get("persona") or {}, ensure_ascii=False)), persona_patch
        )
        draft_settings = _deep_merge(
            json.loads(json.dumps(draft.get("settings") or {}, ensure_ascii=False)), settings_patch
        )
        draft_knobs = {**(draft.get("knobs") or {}), **knobs_patch}
        new_draft = {
            "persona": draft_persona,
            "settings": draft_settings,
            "knobs": draft_knobs,
            "rebuild": bool(result.get("rebuild") or draft.get("rebuild")),
            "summary": summary,
            "updated_at": time.time(),
        }
        history.append({"role": "user", "content": text, "ts": time.time()})
        history.append({"role": "assistant", "content": reply, "ts": time.time()})
        store.set_state("persona_chat_history", history[-20:])
        store.set_state("persona_chat_draft", new_draft)
        return {
            "ok": True,
            "reply": reply,
            "summary": summary,
            "draft": new_draft,
            "rebuild": bool(new_draft.get("rebuild")),
            "changed": {
                "persona": sorted(persona_patch.keys()),
                "settings": sorted(settings_patch.keys()),
                "knobs": sorted(knobs_patch.keys()),
            },
        }

    def persona_draft_clear(self) -> dict:
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"ok": False, "error": "not_ready"}
        app.store.set_state("persona_chat_draft", {})
        app.store.set_state("persona_chat_history", [])
        return {"ok": True}

    @staticmethod
    def _normalize_weekly_keys(patch: dict) -> dict:
        try:
            weekly = ((patch.get("life") or {}).get("weekly")) or {}
            if isinstance(weekly, dict):
                patch["life"]["weekly"] = {
                    int(k) if str(k).isdigit() else k: v for k, v in weekly.items()
                }
        except Exception:  # noqa: BLE001
            pass
        return patch

    def persona_apply(self, rebuild: bool = True, reset_social: bool = False) -> dict:
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"ok": False, "error": "not_ready"}
        draft = app.store.get_state("persona_chat_draft") or {}
        if not draft:
            return {"ok": False, "error": "no_draft"}
        with self._persona_lock:
            if self._persona_busy:
                return {"ok": False, "error": "busy"}
            self._persona_busy = True
        try:
            persona_patch = dict(draft.get("persona") or {})
            settings_patch = dict(draft.get("settings") or {})
            knobs = dict(draft.get("knobs") or {})
            summary = str(draft.get("summary") or "应用新人设")[:300]
            old_name = str((self.config.persona or {}).get("name") or "")
            new_name = str(persona_patch.get("name") or "")
            if new_name and "weather" not in settings_patch:
                city = str(persona_patch.get("city") or "").strip()
                if city:
                    settings_patch.setdefault("weather", {})
                    settings_patch["weather"].setdefault("city", city)
            self._normalize_weekly_keys(settings_patch)
            self.save_config(settings_patch, persona_patch)
            if knobs:
                state = dict(app.store.get_state("persona_knobs") or {})
                state.update(knobs)
                app.store.set_state("persona_knobs", state)
                try:
                    app.persona._knobs.update(state)
                except Exception:  # noqa: BLE001
                    pass
            # 她改了名字：同步备注，保证聊天/动态/关系网所有显示一致
            if new_name and new_name != old_name:
                profile = self._read_profile()
                profile["her_name"] = new_name[:20]
                try:
                    self.profile_file.parent.mkdir(parents=True, exist_ok=True)
                    self.profile_file.write_text(
                        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                except Exception:  # noqa: BLE001
                    log.warning("同步她的备注失败")
            today = app.clock.now().date().isoformat()
            try:
                app.persona.record_event(today, knobs, f"应用对话式人设：{summary}")
            except Exception:  # noqa: BLE001
                pass
            app.store.set_state("persona_chat_draft", {})
            app.store.set_state("persona_chat_history", [])
            threading.Thread(
                target=self._apply_persona_worker,
                args=(bool(rebuild), bool(reset_social), summary),
                name="persona-apply",
                daemon=True,
            ).start()
            return {"ok": True, "rebuild": bool(rebuild), "restarting": True}
        except Exception as exc:  # noqa: BLE001
            with self._persona_lock:
                self._persona_busy = False
            log.exception("应用人设失败")
            return {"ok": False, "error": str(exc)[:200]}

    def _apply_persona_worker(self, rebuild: bool, reset_social: bool, summary: str) -> None:
        from brainn.db import Store

        db_path = self.root / "data" / "ganfanyu.db"
        store: Store | None = None
        try:
            self._set_persona_progress(True, 5, "正在停掉旧人格…", rebuild)
            self.stop_engine()
            store = Store(db_path)
            if rebuild:
                backup = db_path.parent / "backups" / f"persona-{time.strftime('%Y%m%d-%H%M%S')}.db"
                self._set_persona_progress(True, 12, "备份当前记忆库…", rebuild)
                store.backup_to(backup)
                store.set_state("last_persona_backup", str(backup))
                self._set_persona_progress(True, 25, "归档旧记忆…", rebuild)
                archived = store.archive_all_memories()
                self._set_persona_progress(True, 40, "清掉旧动态…", rebuild)
                removed = store.delete_her_dynamics()
                store.clear_life_events()
                store.clear_pending_replies()
                if reset_social:
                    self._set_persona_progress(True, 48, "重置关系网…", rebuild)
                    store.reset_social_network()
                self._set_persona_progress(True, 58, "写入新人设记忆…", rebuild)
                self._seed_persona_memories(store)
                self._set_persona_progress(True, 70, "重建日程、身体与情绪基线…", rebuild)
                today = dt.date.today().isoformat()
                for key, value in (
                    ("mood", {}),
                    ("body", {}),
                    ("brainn_practice", {}),
                    ("brainn_time", {}),
                    ("weather_cache", {}),
                    ("last_learning", {}),
                    ("memory_probe_result", {}),
                    ("catchup_status", {}),
                    ("last_social_extract", {}),
                    ("last_social_extract_ts", 0),
                    ("last_dynamic", {}),
                    ("memory_probe_version", 0),
                    ("last_learning_date", today),
                    ("last_selfhood_date", today),
                    ("last_practice_date", today),
                    ("persona_reset_at", time.time()),
                    ("persona_reset_text", summary),
                ):
                    store.set_state(key, value)
                log.info(
                    "人设重建：归档记忆 %s 条，删除她的动态 %s 条，备份 %s",
                    archived, removed, backup,
                )
            self._set_persona_progress(True, 85, "重启她…", rebuild)
            self.load()
            self.start_engine()
            self._set_persona_progress(False, 100, "已完成", rebuild, True)
        except Exception as exc:  # noqa: BLE001
            log.exception("人设重建失败")
            try:
                self._set_persona_progress(False, 100, "重建失败：" + str(exc)[:80], rebuild, False)
            except Exception:  # noqa: BLE001
                pass
            self.load()
            self.start_engine()
        finally:
            with self._persona_lock:
                self._persona_busy = False
            try:
                if store is not None:
                    store.close()
            except Exception:  # noqa: BLE001
                pass

    def _set_persona_progress(
        self, active: bool, percent: int, message: str, rebuild: bool, ok: bool | None = None
    ) -> None:
        try:
            conn = sqlite3.connect(self.root / "data" / "ganfanyu.db", timeout=10)
            try:
                payload = json.dumps(
                    {
                        "active": bool(active),
                        "percent": int(percent),
                        "message": str(message),
                        "rebuild": bool(rebuild),
                        "ok": ok,
                        "at": time.time(),
                    },
                    ensure_ascii=False,
                )
                conn.execute(
                    """INSERT INTO state(key,value,updated_at) VALUES(?,?,?)
                       ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                    ("persona_rebuild", payload, time.time()),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            log.warning("写人设进度失败")

    def _seed_persona_memories(self, store) -> None:
        persona = self.config.persona if self.config else {}
        speech = persona.get("speech") or {}
        relationship = persona.get("relationship") or {}
        rows = [
            ("她的名字", str(persona.get("name") or "")),
            ("她的身份", str(persona.get("identity") or "")),
            ("她的年龄", str(persona.get("age") or "")),
            ("她所在的城市", str(persona.get("city") or "")),
            ("她的性格", "、".join(persona.get("core_traits") or [])),
            ("她说话的方式", str(speech.get("style") or "")[:240]),
            ("她的口头禅", "、".join(speech.get("catch_phrases") or [])),
            ("你们的关系", str(relationship.get("backstory") or "")),
            ("她的禁忌", "；".join(persona.get("taboos") or [])[:240]),
        ]
        for key, value in rows:
            value = str(value or "").strip()
            if not value:
                continue
            store.insert_memory(
                {
                    "kind": "fact",
                    "key": key,
                    "value": value,
                    "confidence": 0.95,
                    "source": "persona_reset",
                    "layer": "L2",
                    "hooks": key + "、新人设",
                    "interpretation": "",
                    "emotion": "",
                    "intensity": 2,
                    "mainline_link": 1,
                    "weight": 0.9,
                }
            )

    def persona_rebuild_status(self) -> dict:
        try:
            conn = sqlite3.connect(self.root / "data" / "ganfanyu.db", timeout=5)
            try:
                row = conn.execute(
                    "SELECT value FROM state WHERE key='persona_rebuild'"
                ).fetchone()
            finally:
                conn.close()
            if not row:
                return {"active": False, "percent": 0, "message": ""}
            data = json.loads(row[0])
            return data if isinstance(data, dict) else {"active": False}
        except Exception:  # noqa: BLE001
            return {"active": False}

    def api_test(self, key: str = "", base_url: str = "", model: str = "", vision_model: str = "") -> dict:
        from brainn.llm import LLM

        cfg = json.loads(
            json.dumps((self.config.settings.get("llm") or {}) if self.config else {}, ensure_ascii=False)
        )
        if base_url:
            cfg["base_url"] = str(base_url).strip()
        if model:
            cfg["model"] = str(model).strip()
        if vision_model:
            cfg["vision_model"] = str(vision_model).strip()
        use_key = str(key or (self.config.deepseek_key if self.config else "") or "").strip()
        if not use_key:
            return {"ok": False, "error": "missing_key"}
        llm = LLM(cfg, use_key)
        if llm.mock:
            return {"ok": False, "error": "missing_key"}

        async def _run():
            started = time.time()
            text = await llm.chat_text("你是连通性测试，只回复 OK。", "ping", temperature=0, max_tokens=64)
            return {
                "ok": bool(text),
                "reply": (text or "")[:80],
                "latency_ms": round((time.time() - started) * 1000),
            }

        try:
            if self.engine is not None and self.engine.loop is not None:
                fut = asyncio.run_coroutine_threadsafe(asyncio.wait_for(_run(), 25), self.engine.loop)
                return fut.result(timeout=30)
            return asyncio.run(asyncio.wait_for(_run(), 25))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:200]}

    def restart_engine(self) -> None:
        self.stop_engine()
        self.load()
        self.start_engine()

    def whale_chat(self, text: str, history: list, session: str = "") -> dict:
        """智能开关打开时走小鲸鱼专属 BrainN；关闭时用本地台词。"""
        if session:
            self._world_feedback(session, text)
        if not self._whale_smart():
            lines = [
                "本鱼在呢，咕。",
                "咕？叫本鱼有事吗。",
                "今天也陪着主人咕。",
                "本鱼在这里，不会走的。",
                "先摸摸头再说正事咕。",
            ]
            return {
                "ok": True,
                "text": random.choice(lines),
                "valence": 0.2,
                "arousal": 0.2,
                "source": "local",
            }
        whale = getattr(self, "whale", None)
        if whale is not None:
            res = whale.chat(text, history)
            if res.get("ok"):
                return res
            log.warning("小鲸鱼 BrainN 未就绪，回退轻量模型：%s", res.get("error"))
        return self._whale_chat_lite(text, history)

    def _whale_chat_lite(self, text: str, history: list) -> dict:
        """小鲸鱼智能回复：独立人设 + 仅 whale 历史，不碰聊天记忆与神经网络。"""
        from brainn.llm import LLM
        key = str(self.config.deepseek_key if self.config else "").strip()
        if not key:
            return {"ok": False, "error": "missing_key"}
        cfg = json.loads(json.dumps((self.config.settings.get("llm") or {}) if self.config else {}, ensure_ascii=False))
        llm = LLM(cfg, key)
        if llm.mock:
            return {"ok": False, "error": "missing_key"}
        persona_path = self.web_root / "whale" / "persona.md"
        try:
            system = persona_path.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            system = "你是小鲸鱼，深海鲸鱼娘见习女仆，自称\"本鱼\"。短句 1-2 句回复，只输出 JSON：{\"text\":...,\"valence\":-1..1,\"arousal\":-1..1}"
        convo = "\n".join(
            ("对方：" if str(h.get("role")) == "user" else "小鲸鱼：") + str(h.get("content") or "")[:80]
            for h in history if isinstance(h, dict)
        )
        prompt = ((convo + "\n") if convo else "") + "对方：" + text + "\n小鲸鱼："

        async def _run() -> str:
            return await llm.chat_text(system, prompt, temperature=0.8, max_tokens=220)

        try:
            if self.engine is not None and self.engine.loop is not None:
                fut = asyncio.run_coroutine_threadsafe(asyncio.wait_for(_run(), 30), self.engine.loop)
                raw = fut.result(timeout=35)
            else:
                raw = asyncio.run(asyncio.wait_for(_run(), 30))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:200]}
        import re as _re
        data: dict = {}
        m = _re.search(r"\{[^{}]*\}", raw or "", _re.S)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:  # noqa: BLE001
                data = {}
        out_text = str(data.get("text") or (raw or "").strip())[:120] or "咕？"
        try:
            valence = max(-1.0, min(1.0, float(data.get("valence", 0.2))))
            arousal = max(-1.0, min(1.0, float(data.get("arousal", 0.2))))
        except Exception:  # noqa: BLE001
            valence, arousal = 0.2, 0.2
        return {"ok": True, "text": out_text, "valence": valence, "arousal": arousal}

    # ------------------------------------------------------------------
    # 视频通话：2D 页里的“世界之窗”
    # ------------------------------------------------------------------
    def world_start(self) -> dict:
        sid = f"world-{int(time.time() * 1000)}-{random.randint(100, 999)}"
        now = time.time()
        with self.world_lock:
            if len(self.world_sessions) >= 12:
                old = sorted(self.world_sessions.values(), key=lambda x: x.get("started", 0))[:4]
                for item in old:
                    self.world_sessions.pop(str(item.get("id") or ""), None)
            self.world_sessions[sid] = {
                "id": sid,
                "started": now,
                "captions": [],
                "said": [],
                "last_caption": "",
                "last_spoke": 0.0,
                "best_caption": "",
                "best_conf": 0.0,
                "frames": 0,
                "claims": 0,
                "last_claim": {},
                "place": {},
                "busy": False,
            }
        log.info("视频通话开始：%s", sid)
        return {"ok": True, "id": sid}

    def world_stop(self, payload: dict) -> dict:
        sid = str((payload or {}).get("session") or "")
        with self.world_lock:
            sess = self.world_sessions.pop(sid, None)
        if not sess:
            return {"ok": False, "error": "session_not_found"}
        captions = [str(x).strip() for x in (sess.get("captions") or []) if str(x).strip()]
        best = str(sess.get("best_caption") or "").strip()
        uniq: list[str] = []
        for item in captions:
            if item and item not in uniq:
                uniq.append(item)
        picked = best or (uniq[-1] if uniq else "")
        place = str((sess.get("place") or {}).get("label") or "") if isinstance(sess.get("place"), dict) else ""
        prefix = f"在{place}，" if place else ""
        summary = ("视频通话里看到：" + prefix + picked) if picked else "这次视频通话没看清什么。"
        summary = summary[:260]
        if captions:
            try:
                self._world_remember(sess, summary)
            except Exception:  # noqa: BLE001
                log.warning("视频通话记忆写入失败", exc_info=True)
        log.info("视频通话结束：%s，抓帧 %s", sid, sess.get("frames"))
        try:
            m16 = self.qt_metrics("world:")
        except Exception:  # noqa: BLE001
            m16 = {"ok": False}
        return {
            "ok": True,
            "summary": summary,
            "farewell": "那先挂啦，下次再让我看看你。",
            "place": place,
            "frames": int(sess.get("frames") or 0),
            "m16": m16,
        }

    def world_frame(self, payload: dict) -> dict:
        data = payload or {}
        sid = str(data.get("session") or "")
        with self.world_lock:
            sess = self.world_sessions.get(sid)
            if sess is None:
                return {"ok": False, "error": "session_not_found"}
            if sess.get("busy"):
                return {"ok": True, "skipped": True}
            sess["busy"] = True
            sess["frames"] = int(sess.get("frames") or 0) + 1
        raw = b""
        try:
            raw = base64.b64decode(str(data.get("image") or ""))
        except Exception:  # noqa: BLE001
            raw = b""
        if not raw:
            with self.world_lock:
                sess["busy"] = False
            return {"ok": False, "error": "empty_frame"}
        if len(raw) > 5 * 1024 * 1024:
            with self.world_lock:
                sess["busy"] = False
            return {"ok": False, "error": "frame_too_large"}
        focus = data.get("focus") if isinstance(data.get("focus"), dict) else {}
        hint = "视频通话中，她正聚焦画面中的一个区域" if focus.get("on") else "视频通话中，她正在看这一帧"
        scene: dict = {}
        try:
            scene = asyncio.run(self._describe_world_frame(raw, hint))
        except Exception:  # noqa: BLE001
            log.warning("视频通话场景理解失败", exc_info=True)
            scene = {}
        finally:
            with self.world_lock:
                cur = self.world_sessions.get(sid)
                if cur is not None:
                    cur["busy"] = False
        if not scene or not str(scene.get("scene") or "").strip():
            return {"ok": False, "error": "no_vision"}
        caption = self._world_caption(scene)
        memo_caption = self._world_memory_caption(scene)
        place = self._world_place(sess, scene, caption)
        place_label = str((place or {}).get("label") or "")
        now = time.time()
        should_speak = False
        with self.world_lock:
            cur = self.world_sessions.get(sid)
            if cur is None:
                return {"ok": False, "error": "session_not_found"}
            cur["place"] = place or {}
            last = str(cur.get("last_caption") or "")
            changed = difflib.SequenceMatcher(None, last, caption).ratio() < 0.78
            cur["last_caption"] = caption
            caps = list(cur.get("captions") or [])
            caps.append(memo_caption)
            cur["captions"] = caps[-12:]
            try:
                conf = float((scene or {}).get("confidence") or 0)
            except (TypeError, ValueError):
                conf = 0
            if memo_caption and conf >= float(cur.get("best_conf") or 0):
                cur["best_caption"] = memo_caption
                cur["best_conf"] = conf
            force = bool(data.get("force"))
            if force or (changed and now - float(cur.get("last_spoke") or 0) >= 22):
                cur["last_spoke"] = now
                should_speak = True
        if not should_speak:
            return {"ok": True, "scene": scene, "caption": caption, "place": place_label, "silent": True}
        reply = self._world_reply(sess, scene, bool(data.get("force")))
        if not reply:
            return {"ok": True, "scene": scene, "caption": caption, "place": place_label, "silent": True}
        claim_id = self._world_claim(sess, reply, caption, place_label)
        with self.world_lock:
            cur = self.world_sessions.get(sid)
            if cur is not None:
                said = list(cur.get("said") or [])
                said.append(str(reply.get("text") or ""))
                cur["said"] = said[-8:]
        reply.update({
            "ok": True, "scene": scene, "caption": caption,
            "place": place_label, "claim_id": claim_id,
        })
        return reply

    async def _describe_world_frame(self, raw: bytes, hint: str = "") -> dict:
        from brainn.llm import LLM

        key = str(self.config.deepseek_key if self.config else "").strip()
        if not key:
            return {}
        cfg = json.loads(json.dumps((self.config.settings.get("llm") or {}) if self.config else {}, ensure_ascii=False))
        llm = LLM(cfg, key)
        if llm.mock:
            return {}
        return await llm.describe_scene_from_bytes(raw, hint=hint or "视频通话中，她正在看这一帧")

    def _world_caption(self, scene: dict) -> str:
        text = str((scene or {}).get("scene") or "").strip()
        objs = [str(x).strip() for x in ((scene or {}).get("objects") or []) if str(x).strip()][:4]
        light = str((scene or {}).get("light") or "").strip()
        change = str((scene or {}).get("change") or "").strip()
        parts = [text] if text else []
        if objs:
            parts.append("物体：" + "、".join(objs))
        if light:
            parts.append("光线：" + light)
        if change:
            parts.append("变化：" + change)
        return "；".join(parts)[:260] or "看不清画面"

    def _world_place(self, sess: dict, scene: dict, caption: str) -> dict | None:
        """G3：把这次画面归到地点锚点，跨会话累积。"""
        app = self._primary_app()
        if app is None:
            return None
        try:
            if self._place_anchors is None or self._place_store is not app.store:
                from brainn.worldsense import PlaceAnchors

                self._place_anchors = PlaceAnchors(app.store)
                self._place_store = app.store
            return self._place_anchors.observe(scene, caption)
        except Exception:  # noqa: BLE001
            log.warning("地点锚点更新失败", exc_info=True)
            return None

    def world_places(self) -> dict:
        app = self._primary_app()
        if app is None:
            return {"ok": False, "error": "not_ready"}
        try:
            if self._place_anchors is None or self._place_store is not app.store:
                from brainn.worldsense import PlaceAnchors

                self._place_anchors = PlaceAnchors(app.store)
                self._place_store = app.store
            return {"ok": True, "places": self._place_anchors.snapshot(12)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:120]}

    def _world_claim(self, sess: dict, reply: dict, caption: str, place_label: str) -> str:
        """M13/M16：把她这次说出口的观察做成一个可回收的 claim。"""
        app = self._primary_app()
        if app is None:
            return ""
        try:
            idx = int(sess.get("claims") or 0) + 1
            sess["claims"] = idx
            cid = f"world:{sess.get('id')}:{idx}"[:60]
            text = str(reply.get("text") or "")[:120]
            app.store.add_qt_artifact(
                cid,
                kind="world_observation",
                name=text,
                owner="her",
                meta={"scene": caption, "place": place_label, "session": sess.get("id")},
            )
            sess["last_claim"] = {
                "id": cid,
                "text": text,
                "scene": caption,
                "place": place_label,
                "at": time.time(),
            }
            return cid
        except Exception:  # noqa: BLE001
            log.warning("视频通话 claim 写入失败", exc_info=True)
            return ""

    def _world_feedback(self, sid: str, text: str) -> dict | None:
        """M15/M16：用户下一句话如果是在确认/否认她，就回收命中率。"""
        with self.world_lock:
            sess = self.world_sessions.get(sid)
            claim = dict((sess or {}).get("last_claim") or {})
        if not sess or not claim or claim.get("feedback"):
            return None
        app = self._primary_app()
        if app is None:
            return None
        try:
            from brainn.world_feedback import WorldFeedback

            result = WorldFeedback(app.store).record(claim, text)
        except Exception:  # noqa: BLE001
            log.warning("视频通话反馈回收失败", exc_info=True)
            return None
        if result:
            with self.world_lock:
                cur = self.world_sessions.get(sid)
                if cur is not None and isinstance(cur.get("last_claim"), dict):
                    last = dict(cur["last_claim"])
                    last["feedback"] = result.get("verdict")
                    cur["last_claim"] = last
            log.info(
                "M16 视频通话反馈：%s %s（%s）",
                result.get("verdict"), result.get("claim_id"), result.get("evidence"),
            )
        return result

    def _world_memory_caption(self, scene: dict) -> str:
        """记忆只留场景和真正发生的变化，不把物体/光线大段抄进去。"""
        scene_text = str((scene or {}).get("scene") or "").strip()
        change = str((scene or {}).get("change") or "").strip()
        if change and not any(k in change for k in ("无", "没有", "静止", "静态", "不变")):
            return (scene_text + "；" + change)[:160]
        return scene_text[:160]

    def _world_reply(self, sess: dict, scene: dict, force: bool) -> dict:
        from brainn.llm import LLM, _extract_json

        key = str(self.config.deepseek_key if self.config else "").strip()
        if not key:
            return {}
        cfg = json.loads(json.dumps((self.config.settings.get("llm") or {}) if self.config else {}, ensure_ascii=False))
        llm = LLM(cfg, key)
        if llm.mock:
            return {}
        persona = ""
        try:
            persona = (self.web_root / "whale" / "persona.md").read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            persona = "你是小鲸鱼，深海鲸鱼娘见习女仆，自称“本鱼”。"
        caption = self._world_caption(scene)
        place = str((sess.get("place") or {}).get("label") or "") if isinstance(sess.get("place"), dict) else ""
        said = "；".join([str(x) for x in (sess.get("said") or []) if str(x).strip()][-3:])
        system = (
            persona
            + "\n你现在正在和他视频通话。你确实能看到这一帧画面，但只根据画面事实说一句自然的话。"
            + "不要念描述、不要分析、不要提AI，1~2句，像真的在视频里。只输出 JSON："
            + '{"text":"...","valence":-1..1,"arousal":-1..1}'
        )
        prompt = (
            f"画面事实：{caption}\n"
            f"地点锚点：{place or '还没认出来'}\n"
            f"你最近说过：{said or '（还没说话）'}\n"
            "写你这一句，只输出 JSON。"
        )

        async def _run() -> str:
            return await llm.chat_text(system, prompt, temperature=0.8, max_tokens=260)

        try:
            raw = asyncio.run(asyncio.wait_for(_run(), 25))
        except Exception:  # noqa: BLE001
            if force:
                return {"text": "看到了，不过有点看不清。", "valence": 0.1, "arousal": 0.15}
            return {}
        data = _extract_json(raw) if raw else {}
        parsed = data if isinstance(data, dict) else {}
        text = str(parsed.get("text") or "").strip()
        if not text and raw:
            m = re.search(r'"text"\s*:\s*"([^"]{1,220})', raw)
            if m:
                text = m.group(1).strip()
        text = re.sub(r"[\r\n]+", " ", text)[:160]
        if not text:
            return {}
        try:
            valence = max(-1.0, min(1.0, float(parsed.get("valence", 0.2))))
            arousal = max(0.0, min(1.0, float(parsed.get("arousal", 0.25))))
        except (TypeError, ValueError):
            valence, arousal = 0.2, 0.25
        return {"text": text, "valence": round(valence, 2), "arousal": round(arousal, 2)}

    def _world_remember(self, sess: dict, summary: str) -> None:
        app = self._primary_app()
        if app is None:
            return
        try:
            app.memory.add_facts([{
                "kind": "event",
                "key": "视频通话",
                "fact": summary,
                "person": "他",
                "layer": "L3",
                "confidence": 0.7,
                "intensity": 2,
                "mainline_link": 1.0,
                "source": "world",
            }], source="world", max_items=1)
        except Exception:  # noqa: BLE001
            log.warning("视频通话记忆写入失败", exc_info=True)
        try:
            aid = f"world:{sess.get('id')}"
            app.store.add_qt_artifact(
                aid, kind="video_call", name=summary[:120],
                content_hash=sha256(summary.encode("utf-8")).hexdigest(),
                owner="her",
                meta={
                    "frames": int(sess.get("frames") or 0),
                    "captions": list(sess.get("captions") or [])[-3:],
                    "place": str((sess.get("place") or {}).get("label") or "") if isinstance(sess.get("place"), dict) else "",
                },
            )
            app.store.add_qt_outcome(
                aid, verdict="unverified", evidence=summary[:300], confidence=0.5, source="world"
            )
        except Exception:  # noqa: BLE001
            log.warning("视频通话账本写入失败", exc_info=True)

    def viz(self) -> dict:
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"ready": False}
        shadow = getattr(app, "shadow", None)
        snap = shadow.snapshot() if shadow is not None and hasattr(shadow, "snapshot") else {}
        practice = snap.get("practice") or {}
        world = snap.get("world") or {}
        world_state = getattr(getattr(shadow, "world", None), "state", {}) or {}
        today = app.clock.now().date().isoformat()
        schedule = [
            e for e in (practice.get("schedule") or [])
            if str(e.get("date") or "") >= today
        ][:10]
        social_nodes = [
            n for n in (app.social.nodes or {}).values() if n.get("active", 1)
        ]
        social_nodes.sort(key=lambda n: float(n.get("depth") or 0), reverse=True)
        active_total = len(social_nodes)
        shown = social_nodes[:30]
        shown_ids = {n.get("id") for n in shown}
        # 手动添加的角色即使关系还浅，也保证出现在图里
        for node in social_nodes:
            if node.get("manual") and node.get("id") not in shown_ids and len(shown) < 34:
                shown.append(node)
                shown_ids.add(node.get("id"))
        social_nodes = shown
        keep_ids = {n.get("id") for n in social_nodes}
        edges = [
            e for e in app.store.social_edges()
            if e.get("a") in keep_ids and e.get("b") in keep_ids
        ]
        events = app.store.recent_social_events(20)
        world_events = list(world_state.get("events") or [])[-12:]
        views = list(world_state.get("views") or [])[-8:]
        output_log = list(practice.get("output_log") or [])[-12:]
        mood = {}
        try:
            mood = app.mood.state.snapshot()
        except Exception:  # noqa: BLE001
            pass
        return {
            "ready": True,
            "time": app.clock.now().strftime("%Y-%m-%d %H:%M"),
            "practice": {
                "occupation": practice.get("occupation"),
                "ownership": practice.get("ownership"),
                "autonomy": practice.get("autonomy"),
                "repetition": practice.get("repetition"),
                "alienation": practice.get("alienation"),
                "day_peak_alienation": practice.get("day_peak_alienation"),
                "fatigue": practice.get("fatigue"),
                "current": practice.get("current"),
                "next": practice.get("next"),
                "idle": practice.get("idle"),
                "skills": practice.get("skills") or {},
                "artifacts": output_log,
                "today_labor_minutes": practice.get("day_labor_minutes") or {},
                "his_time_minutes": practice.get("his_time_minutes"),
                "schedule": schedule,
            },
            "world": {
                "position": world.get("position") or {},
                "clocks": world.get("clocks") or {},
                "materialize_ratio": world.get("materialize_ratio"),
                "exposure": world.get("exposure"),
                "materialized": world.get("materialized"),
                "events": world_events,
                "views": views,
            },
            "social": {"nodes": social_nodes, "edges": edges, "events": events, "total": active_total},
            "selfhood": {
                "last_selfhood_date": app.store.get_state("last_selfhood_date"),
                "last_learning": app.store.get_state("last_learning") or {},
                "last_learning_date": app.store.get_state("last_learning_date"),
                "probe": app.store.get_state("memory_probe_result") or {},
                "persona_history": list(app.store.get_state("persona_history") or [])[-30:],
                "dynamic_last": app.store.get_state("last_dynamic") or {},
            },
            "mood": mood,
            "body": app.body.describe(),
        }

    # ------------------------------------------------------------------
    # 世界（虚拟社会软件层，不改底层 BrainN）
    # ------------------------------------------------------------------
    _PLACE_LAYOUT = (
        ("宿舍", 22, 72, "她的家"),
        ("食堂", 36, 56, "食堂"),
        ("教学楼", 52, 38, "教学楼"),
        ("实验楼", 66, 52, "实验楼"),
        ("图书馆", 46, 68, "图书馆"),
        ("奶茶店", 78, 74, "她打工的奶茶店"),
    )

    def world(self) -> dict:
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"ready": False}
        viz = self.viz()
        profile = self.profile()
        persona = self.config.persona if self.config else {}
        her_city = str(
            (self.config.settings.get("weather") or {}).get("city")
            or persona.get("city")
            or "开封"
        )
        user_city = str(app.store.get_state("world_user_city") or "").strip()[:20]
        her_weather = self._city_weather(her_city)
        if not her_weather:
            cached = app.store.get_state("weather_cache") or {}
            if cached:
                her_weather = {
                    "city": cached.get("city"),
                    "temp": cached.get("temp"),
                    "text": cached.get("text"),
                    "lat": None,
                    "lon": None,
                    "timezone": "",
                }
        user_weather = self._city_weather(user_city) if user_city else None
        her_lat = her_weather.get("lat") if her_weather else None
        her_lon = her_weather.get("lon") if her_weather else None
        user_lat, user_lon = None, None
        try:
            stored_lat = float(app.store.get_state("world_user_lat") or 0)
            stored_lon = float(app.store.get_state("world_user_lon") or 0)
            if -90 <= stored_lat <= 90 and -180 <= stored_lon <= 180 and (stored_lat or stored_lon):
                user_lat, user_lon = stored_lat, stored_lon
        except (TypeError, ValueError):
            pass
        if user_lat is None and user_weather:
            user_lat = user_weather.get("lat")
            user_lon = user_weather.get("lon")
        distance = None
        if (
            her_lat is not None
            and her_lon is not None
            and user_lat is not None
            and user_lon is not None
        ):
            distance = round(
                self._haversine(
                    float(her_lat),
                    float(her_lon),
                    float(user_lat),
                    float(user_lon),
                )
            )
        nodes = (viz.get("social") or {}).get("nodes") or []
        by_id = {str(n.get("id")): n for n in nodes}
        user_node = by_id.get("user") or {}
        timeline = self._world_timeline(app, viz)
        next_event = dict((viz.get("practice") or {}).get("next") or {})
        today = app.clock.now().date().isoformat()
        if next_event.get("date"):
            try:
                days = (
                    dt.date.fromisoformat(str(next_event["date"])) - dt.date.fromisoformat(today)
                ).days
                next_event["day_label"] = {0: "今天", 1: "明天", 2: "后天"}.get(
                    days, f"{days} 天后" if days > 0 else ""
                )
            except ValueError:
                next_event["day_label"] = ""
        return {
            "ready": True,
            "her_city": her_city,
            "user_city": user_city,
            "her_weather": her_weather,
            "user_weather": user_weather,
            "her_lat": her_lat,
            "her_lon": her_lon,
            "user_lat": user_lat,
            "user_lon": user_lon,
            "user_source": app.store.get_state("world_user_source") or "",
            "distance_km": distance,
            "her_time": app.clock.now().strftime("%H:%M"),
            "user_time": self._local_time(user_weather) if user_weather else "",
            "visit_label": "去看看她" if float(user_node.get("trust") or 0) >= 70 else "去这儿",
            "current": (viz.get("practice") or {}).get("current") or {},
            "next": next_event,
            "mood_text": self._mood_text(viz.get("mood") or {}),
            "timeline": timeline,
            "unfinished": [e.get("title") for e in timeline if e.get("state") == "next"][:3],
            "places": self._world_places(app, viz, by_id),
            "people": self._world_people(nodes),
            "rorschach": self._world_rorschach(viz, by_id),
            "traces": self._world_traces(app, viz, by_id),
            "her_name": profile.get("her_name") or "她",
            "her_avatar_url": profile.get("her_avatar_url") or "",
            "persona": {
                "identity": persona.get("identity") or "",
                "age": persona.get("age"),
                "core_traits": persona.get("core_traits") or [],
            },
        }

    def _world_timeline(self, app, viz: dict) -> list[dict]:
        today = app.clock.now().date().isoformat()
        schedule = [
            e
            for e in ((viz.get("practice") or {}).get("schedule") or [])
            if str(e.get("date") or "") == today
        ]
        now_min = app.clock.now().hour * 60 + app.clock.now().minute
        out = []
        for event in schedule:
            try:
                sh, sm = [int(x) for x in str(event.get("start") or "00:00").split(":")]
                eh, em = [int(x) for x in str(event.get("end") or "00:00").split(":")]
                start, end = sh * 60 + sm, eh * 60 + em
            except (TypeError, ValueError):
                continue
            state = "done" if now_min >= end else ("now" if start <= now_min < end else "next")
            out.append(
                {
                    "start": event.get("start"),
                    "end": event.get("end"),
                    "title": event.get("title") or "",
                    "place": event.get("place") or "",
                    "kind": event.get("kind") or "",
                    "state": state,
                }
            )
        return out

    def _world_places(self, app, viz: dict, by_id: dict) -> list[dict]:
        current = (viz.get("practice") or {}).get("current") or {}
        cur_text = str(current.get("place") or "") + " " + str(current.get("title") or "")
        dynamics = app.store.recent_dynamics(30)
        places = []
        for name, x, y, label in self._PLACE_LAYOUT:
            memories: list[str] = []
            try:
                for _, mem in app.memory.recall_scored(
                    name, 2, require_overlap=True, primary=name
                ):
                    val = str(mem.get("value") or "").strip()
                    if val:
                        memories.append(val[:80])
            except Exception:  # noqa: BLE001
                pass
            event = ""
            for dyn in reversed(dynamics):
                text = str(dyn.get("text") or "")
                if str(dyn.get("author") or "her") == "her" and name in text:
                    event = text[:100]
                    break
            places.append(
                {
                    "id": name,
                    "name": name,
                    "label": label,
                    "x": x,
                    "y": y,
                    "here": name in cur_text,
                    "memory": memories[0] if memories else "",
                    "event": event,
                    "people": self._place_people(name, list(by_id.values())),
                    "gone": False,
                }
            )
        return places

    @staticmethod
    def _place_people(name: str, nodes: list[dict]) -> list[dict]:
        keys = {
            "宿舍": ("室友", "妈妈", "外婆"),
            "食堂": ("室友", "同学", "朋友"),
            "教学楼": ("同学", "学习搭子", "老师", "学妹", "学长"),
            "实验楼": ("同学", "学习搭子", "老师", "学妹", "学长"),
            "图书馆": ("学习搭子", "同学", "学长", "学妹"),
            "奶茶店": ("奶茶店", "店长", "同事"),
        }.get(name, ())
        out = []
        for node in nodes:
            if str(node.get("id")) in ("her", "user"):
                continue
            text = str(node.get("role") or "") + str(node.get("last_event") or "")
            if any(k in text for k in keys):
                out.append(
                    {"id": node.get("id"), "name": node.get("name"), "role": node.get("role")}
                )
            if len(out) >= 3:
                break
        if not out:
            for node in nodes:
                if str(node.get("id")) in ("her", "user"):
                    continue
                out.append(
                    {"id": node.get("id"), "name": node.get("name"), "role": node.get("role")}
                )
                if len(out) >= 2:
                    break
        return out

    def _world_people(self, nodes: list[dict]) -> list[dict]:
        by_id = {str(n.get("id")): n for n in nodes}
        wanted = ["mom", "tingting", "xiaoyu", "linlin"]
        selected = [by_id[i] for i in wanted if i in by_id]
        ids = {str(n.get("id")) for n in selected}
        for node in nodes:
            if len(selected) >= 4:
                break
            nid = str(node.get("id"))
            if nid in ("her", "user") or nid in ids:
                continue
            selected.append(node)
            ids.add(nid)
        out = []
        for node in selected[:4]:
            trust = float(node.get("trust") or 0)
            intimacy = float(node.get("intimacy") or 0)
            conflict = float(node.get("conflict") or 0)
            if conflict >= 10:
                attitude = "最近和她有点别扭"
            elif trust >= 75 and intimacy >= 60:
                attitude = "和她很亲近，也很信任她"
            elif trust >= 60:
                attitude = "和她相处得还算放心"
            else:
                attitude = "还在和她慢慢熟起来"
            out.append(
                {
                    "id": node.get("id"),
                    "name": node.get("name"),
                    "role": node.get("role"),
                    "personality": node.get("personality"),
                    "attitude": attitude,
                    "recent": str(node.get("last_event") or "")[:100],
                    "numbers": {
                        "trust": round(trust),
                        "intimacy": round(intimacy),
                        "conflict": round(conflict),
                        "dependency": round(float(node.get("dependency") or 0)),
                        "influence": round(float(node.get("influence") or 0)),
                        "depth": round(float(node.get("depth") or 0)),
                    },
                }
            )
        return out

    def _world_rorschach(self, viz: dict, by_id: dict) -> dict:
        cores = {"mom", "tingting", "xiaoyu", "linlin", "xiaomei"}
        events = (viz.get("world") or {}).get("events") or []
        views = {str(v.get("id")): str(v.get("surface") or "") for v in ((viz.get("world") or {}).get("views") or [])}
        pick = None
        for event in reversed(events):
            if str(event.get("actor")) in cores and event.get("truth"):
                pick = event
                break
        if not pick:
            return {}
        actor_id = str(pick.get("actor"))
        node = by_id.get(actor_id) or {}
        name = str(node.get("name") or actor_id)
        action = str(pick.get("action") or "")
        outcome = str(pick.get("outcome") or "")
        if action == "call" and outcome == "absent":
            her_version = f"{name}打电话过来，没说几句就挂了。"
        elif action == "cold_shoulder":
            her_version = f"{name}今天对我冷冷的，后来又像没事一样。"
        elif action == "chase":
            her_version = f"{name}又在群里点名催我。"
        elif action == "cancel":
            her_version = f"{name}约了我又临时取消。"
        else:
            her_version = views.get(str(pick.get("id"))) or f"{name}最近和我有点小别扭。"
        other_version = str(node.get("last_event") or "").strip() or str(
            pick.get("true_cause") or ""
        ).strip()
        if not other_version:
            other_version = "TA没有跟你提过这件事。"
        return {
            "title": f"{name} · 一件小事",
            "name": name,
            "her": her_version[:160],
            "other": other_version[:160],
            "note": "同一件事，不同人有不同版本；这里不做真相仲裁。",
        }

    def _world_traces(self, app, viz: dict, by_id: dict) -> list[dict]:
        views = {
            str(v.get("id")): str(v.get("surface") or "")
            for v in ((viz.get("world") or {}).get("views") or [])
        }
        out = []
        for event in ((viz.get("world") or {}).get("events") or [])[-8:]:
            node = by_id.get(str(event.get("actor"))) or {}
            text = views.get(str(event.get("id"))) or (
                f"{node.get('name') or event.get('actor')} {event.get('action')} → {event.get('outcome')}"
            )
            out.append({"ts": event.get("ts"), "text": str(text)[:100], "kind": "world"})
        for dyn in app.store.recent_dynamics(20):
            if str(dyn.get("author") or "her") != "her":
                continue
            out.append(
                {
                    "ts": dyn.get("ts"),
                    "text": str(dyn.get("text") or "")[:100],
                    "kind": "dynamic",
                }
            )
        out.sort(key=lambda x: float(x.get("ts") or 0), reverse=True)
        return out[:6]

    @staticmethod
    def _photon_city(client: httpx.Client, city: str) -> dict | None:
        try:
            resp = client.get(
                "https://photon.komoot.io/api/",
                params={"q": city, "limit": 5},
                headers={"User-Agent": "BrainN/1.0"},
            )
            resp.raise_for_status()
            for feature in resp.json().get("features") or []:
                props = feature.get("properties") or {}
                if str(props.get("countrycode") or "").upper() != "CN":
                    continue
                coords = (feature.get("geometry") or {}).get("coordinates") or []
                if len(coords) < 2:
                    continue
                return {
                    "name": str(props.get("name") or city),
                    "lat": float(coords[1]),
                    "lon": float(coords[0]),
                    "timezone": "",
                }
        except Exception as exc:  # noqa: BLE001
            log.info("Photon 城市定位失败 %s：%s", city, exc)
        return None

    def _city_weather(self, city: str) -> dict | None:
        city = str(city or "").strip()
        if not city:
            return None
        cached = self._world_weather_cache.get(city)
        ttl = 1200 if (cached and cached.get("data")) else 180
        if cached and time.time() - float(cached.get("ts") or 0) < ttl:
            return cached.get("data")
        try:
            with httpx.Client(timeout=8) as client:
                photon = self._photon_city(client, city)
                if photon:
                    loc = {
                        "name": city,
                        "latitude": photon["lat"],
                        "longitude": photon["lon"],
                        "timezone": "",
                    }
                else:
                    loc = None
                    queries = [city]
                    if city.endswith("市") and len(city) > 2:
                        queries.append(city[:-1])
                    elif not city.endswith(("县", "区", "镇", "州", "盟")):
                        queries.append(city + "市")
                    fallback = None
                    fallback_score = -1.0
                    for query in queries:
                        geo = client.get(
                            "https://geocoding-api.open-meteo.com/v1/search",
                            params={"name": query, "count": 8, "language": "zh", "format": "json"},
                        )
                        geo.raise_for_status()
                        results = geo.json().get("results") or []
                        cn = [
                            r for r in results
                            if str(r.get("country_code") or "CN").upper() == "CN"
                        ]
                        pool = cn or results
                        admin = [
                            r for r in pool
                            if str(r.get("feature_code") or "") in ("PPLC", "PPLA", "PPLA2", "PPLA3")
                        ]
                        if admin:
                            loc = max(admin, key=lambda r: float(r.get("population") or 0))
                            break
                        if cn:
                            cand = max(cn, key=lambda r: float(r.get("population") or 0))
                            score = float(cand.get("population") or 0)
                            if score > fallback_score:
                                fallback, fallback_score = cand, score
                        elif results and fallback is None:
                            fallback = results[0]
                    if loc is None:
                        loc = fallback
                if loc is None:
                    self._world_weather_cache[city] = {"ts": time.time(), "data": None}
                    return cached.get("data") if cached else None
                lat = float(loc.get("latitude"))
                lon = float(loc.get("longitude"))
                tz = str(loc.get("timezone") or "")
                forecast = client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code",
                        "timezone": "auto",
                    },
                )
                forecast.raise_for_status()
                forecast_data = forecast.json()
                current = forecast_data.get("current") or {}
                tz = str(forecast_data.get("timezone") or tz or "")
                code = int(current.get("weather_code") or 0)
                try:
                    from brainn.weather import WMO

                    text, _ = WMO.get(code, ("天气怪怪的", 0.0))
                except Exception:  # noqa: BLE001
                    text = ""
                data = {
                    "city": str(loc.get("name") or city),
                    "temp": round(float(current.get("temperature_2m") or 20), 1),
                    "feels": round(float(current.get("apparent_temperature") or 20), 1),
                    "humidity": round(float(current.get("relative_humidity_2m") or 50)),
                    "text": text,
                    "lat": lat,
                    "lon": lon,
                    "timezone": tz,
                }
                self._world_weather_cache[city] = {"ts": time.time(), "data": data}
                return data
        except Exception as exc:  # noqa: BLE001
            log.warning("世界天气失败 %s：%s", city, exc)
            self._world_weather_cache[city] = {"ts": time.time(), "data": None}
            return cached.get("data") if cached else None

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371.0
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.asin(math.sqrt(a))

    @staticmethod
    def _local_time(weather: dict | None) -> str:
        tz = str((weather or {}).get("timezone") or "").strip()
        if not tz:
            return ""
        try:
            from zoneinfo import ZoneInfo

            return dt.datetime.now(ZoneInfo(tz)).strftime("%H:%M")
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _mood_text(mood: dict) -> str:
        value = float(mood.get("mood") or 0)
        grievance = float(mood.get("grievance") or 0)
        if grievance >= 25:
            return "心里还有点不痛快"
        if value >= 80:
            return "心情不错"
        if value >= 60:
            return "还行，挺平静"
        if value >= 40:
            return "有点低落"
        return "不太好"

    @staticmethod
    def _reverse_city(lat: float, lon: float) -> str:
        try:
            with httpx.Client(
                timeout=8, headers={"User-Agent": "BrainN/1.0"}, follow_redirects=True
            ) as client:
                resp = client.get(
                    "https://api.bigdatacloud.net/data/reverse-geocode-client",
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "localityLanguage": "zh-Hans",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                city = str(
                    data.get("city")
                    or data.get("locality")
                    or data.get("principalSubdivision")
                    or ""
                ).strip()
                if city:
                    return city[:20]
        except Exception as exc:  # noqa: BLE001
            log.info("BigDataCloud 反向定位失败：%s", exc)
        fallback = ""
        try:
            with httpx.Client(timeout=6, headers={"User-Agent": "BrainN/1.0"}) as client:
                resp = client.get(
                    "https://photon.komoot.io/reverse",
                    params={"lat": lat, "lon": lon, "limit": 8},
                )
                resp.raise_for_status()
                for feature in resp.json().get("features") or []:
                    props = feature.get("properties") or {}
                    if str(props.get("countrycode") or "").upper() != "CN":
                        continue
                    for key in ("city", "county", "name"):
                        name = str(props.get(key) or "").strip()
                        if not name or len(name) > 12:
                            continue
                        if not fallback:
                            fallback = name
                        if any(
                            word in name
                            for word in (
                                "站", "机场", "广场", "路", "街", "大学", "学院",
                                "医院", "酒店", "宾馆", "超市", "公司", "银行",
                                "公园", "小区", "社区", "学校", "中学", "小学",
                                "政府", "中心", "大厦", "写字楼",
                            )
                        ):
                            continue
                        if name.endswith(
                            ("区", "县", "镇", "街道", "村", "庄", "屯", "社区", "小区")
                        ):
                            continue
                        return name
        except Exception as exc:  # noqa: BLE001
            log.info("Photon 反向定位失败：%s", exc)
        return fallback[:20]

    def world_locate(self, lat: float, lon: float) -> dict:
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"ok": False, "error": "not_ready"}
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            return {"ok": False, "error": "bad_coord"}
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return {"ok": False, "error": "bad_coord"}
        city = self._reverse_city(lat, lon)
        app.store.set_state("world_user_lat", round(lat, 6))
        app.store.set_state("world_user_lon", round(lon, 6))
        if city:
            app.store.set_state("world_user_city", city)
        app.store.set_state("world_user_source", "gps")
        return {"ok": True, "city": city, "lat": lat, "lon": lon, "world": self.world()}

    def world_city(
        self, city: str, lat: float | None = None, lon: float | None = None
    ) -> dict:
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"ok": False, "error": "not_ready"}
        app.store.set_state("world_user_city", str(city or "").strip()[:20])
        try:
            has_coord = (
                lat is not None
                and lon is not None
                and -90 <= float(lat) <= 90
                and -180 <= float(lon) <= 180
            )
        except (TypeError, ValueError):
            has_coord = False
        if has_coord:
            app.store.set_state("world_user_lat", round(float(lat), 6))
            app.store.set_state("world_user_lon", round(float(lon), 6))
            app.store.set_state("world_user_source", "gps")
        else:
            app.store.set_state("world_user_lat", "")
            app.store.set_state("world_user_lon", "")
            app.store.set_state("world_user_source", "manual")
        return {"ok": True, "world": self.world()}

    def world_visit(self, place: str) -> dict:
        app = getattr(self.engine, "app", None) if self.engine else None
        place = str(place or "").strip()[:20]
        if app is None:
            return {"ok": False, "error": "not_ready"}
        if not place:
            return {"ok": False, "error": "empty"}
        if place in ("宿舍", "家"):
            text = "我到你楼下啦，你方便下来吗？"
        elif place == "奶茶店":
            text = "我准备去你打工的那家奶茶店坐坐，你在吗？"
        elif place in ("教学楼", "实验楼", "图书馆", "食堂"):
            text = f"我准备去你常去的{place}看看，能碰到你吗？"
        else:
            text = f"我准备去你说的{place}看看，你在吗？"
        self.engine.user_send(text)
        return {"ok": True, "text": text}

    # ------------------------------------------------------------------
    # 朋友圈 / 社会关系成员资料
    # ------------------------------------------------------------------
    def _base_profile(
        self, node_id: str, name: str, role: str = "",
        avatar_url: str = "", personality: str = "",
    ) -> dict:
        name = str(name or node_id)
        return {
            "id": str(node_id),
            "name": DISPLAY_NAMES.get(str(node_id), name)[:20],
            "role": str(role or "")[:40],
            "personality": str(personality or PERSONALITY.get(node_id) or _role_personality(role)),
            "avatar_url": str(avatar_url or ""),
            "color": _avatar_color(name),
            "emoji": AVATAR_EMOJI.get(node_id, "💬"),
        }

    def _profiles(self, app, profile: dict) -> dict[str, dict]:
        persona = (self.config.persona or {}) if self.config else {}
        traits = " · ".join(str(x) for x in (persona.get("core_traits") or [])[:3])
        her_profile = self._base_profile(
            "her",
            profile.get("her_name") or "小鲸鱼",
            "她自己",
            profile.get("her_avatar_url") or "",
        )
        if traits:
            her_profile["personality"] = traits
        data = {
            "her": her_profile,
            "user": self._base_profile(
                "user",
                profile.get("nickname") or "我",
                "男朋友",
                profile.get("avatar_url") or "",
            ),
        }
        if app is not None:
            for node in (app.social.nodes or {}).values():
                if not node.get("active", 1) or node.get("id") in data:
                    continue
                data[node["id"]] = self._base_profile(
                    node.get("id"), node.get("name") or node.get("id"),
                    node.get("role") or "",
                    personality=str(node.get("personality") or ""),
                )
        return data

    def _unknown_profile(self, node_id: str) -> dict:
        return self._base_profile(node_id, node_id, "虚拟社会")

    def _life_image_pool(self, app) -> list[Path]:
        """生活图库 + 带语义的默认图（默认图用于按文案话题精准配图）。"""
        out: list[Path] = []
        seen: set[str] = set()
        bases = [
            getattr(getattr(app, "media", None), "life_images_dir", None),
            self.root / "assets" / "life_default",
        ]
        for base in bases:
            if not base:
                continue
            try:
                files = [
                    p for p in sorted(Path(base).iterdir())
                    if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
                ][-12:]
            except Exception:  # noqa: BLE001
                continue
            for path in files:
                key = str(path.resolve())
                if key not in seen:
                    seen.add(key)
                    out.append(path)
        return out

    def _post_text_recent(self, app, node_id: str) -> set[str]:
        try:
            return set(app.store.recent_social_texts(node_id, 7))
        except Exception:  # noqa: BLE001
            return set()

    def _pick_post_text(self, app, node: dict, slot: str, used: set[str], rng: random.Random) -> str:
        """按时段挑文案，优先用这个角色自己的句子，并避开最近 7 天和当天已用过的。"""
        node_id = str(node.get("id") or "")
        texts = list(NPC_POSTS.get(node_id) or _generic_posts(node))
        recent = self._post_text_recent(app, node_id)

        def fit(text: str, strict_repeat: bool) -> bool:
            if text in used:
                return False
            if strict_repeat and text in recent:
                return False
            return _text_slot(text) in (None, slot)

        pool = [t for t in texts if fit(t, True)]
        if not pool:
            pool = [t for t in texts if fit(t, False)]
        if not pool:
            category = _role_category(str(node.get("role") or ""))
            generic = list(ROLE_SLOT_POSTS.get(category, ROLE_SLOT_POSTS["other"]).get(slot) or ())
            pool = [t for t in generic if t not in used and t not in recent]
            if not pool:
                pool = [t for t in generic if t not in used]
            if not pool:
                pool = generic
        if not pool:
            pool = ["今天没什么特别的。"]
        return rng.choice(pool)

    def _pick_post_image(self, app, text: str, used: dict[str, int], rng: random.Random) -> list[str]:
        """只给能判断话题的文案配同话题的图，宁可不配也不乱配。"""
        topic = _text_topic(text)
        if not topic:
            return []
        pool = [p for p in self._life_image_pool(app) if _image_topic(p) == topic]
        if not pool or rng.random() > 0.78:
            return []
        pool.sort(key=lambda p: used.get(str(p), 0))
        least = used.get(str(pool[0]), 0)
        pool = [p for p in pool if used.get(str(p), 0) == least]
        pick = rng.choice(pool)
        used[str(pick)] = used.get(str(pick), 0) + 1
        return [str(pick)]

    def _npc_available(self, node: dict, now=None) -> bool:
        """每个社会关系成员有自己的作息：睡觉/上课/上班时不点赞不评论。"""
        now = now or dt.datetime.now()
        hour = now.hour + now.minute / 60.0
        node_id = str(node.get("id") or "")
        seed = int(md5(node_id.encode("utf-8")).hexdigest()[:4], 16)
        sleep_start = 22 + seed % 3
        sleep_end = 6 + (seed // 3) % 3
        if hour >= sleep_start or hour < sleep_end:
            return False
        role = str(node.get("role") or "")
        if any(w in role for w in ("学生", "同班", "学妹", "学弟", "室友", "考研")):
            busy = (8 <= hour < 12) or (14 <= hour < 17.5)
        elif any(w in role for w in ("店长", "店员", "同事", "站长", "经理", "奶茶")):
            busy = 10 <= hour < 22
        elif "老师" in role or "助教" in role:
            busy = 8 <= hour < 17
        elif any(w in role for w in ("外卖", "快递", "维修", "保安")):
            busy = 9 <= hour < 21
        else:
            busy = False
        return not busy

    def _ensure_social_posts(self, app) -> list[dict]:
        """每个社会关系成员每天都会发一点生活碎片，第一次读动态时生成并落库。"""
        now = app.clock.now()
        # 以早上 6 点为一天的分界：凌晨仍沿用“昨天”的朋友圈，避免半夜只剩她一个人
        day = (now - dt.timedelta(hours=6)).date().isoformat()
        rows = app.store.social_posts(day)
        life_images = self._life_image_pool(app)
        if rows and life_images:
            changed = False
            for row in rows:
                text = str(row.get("text") or "")
                topic = _text_topic(text)
                images = row.get("images") or []
                pool = [p for p in life_images if _image_topic(p) == topic] if topic else []
                if images:
                    if not topic:
                        # 判断不出话题的旧图直接去掉，宁可不配图也不乱配
                        app.store.update_social_post_images(row["id"], [])
                        changed = True
                    elif not any(_image_topic(Path(str(raw))) == topic for raw in images):
                        if pool:
                            pick = random.Random("pick:" + str(row.get("id"))).choice(pool)
                            app.store.update_social_post_images(row["id"], [str(pick)])
                        else:
                            app.store.update_social_post_images(row["id"], [])
                        changed = True
                elif topic and pool:
                    pick = random.Random("pick:" + str(row.get("id"))).choice(pool)
                    app.store.update_social_post_images(row["id"], [str(pick)])
                    changed = True
            if changed:
                rows = app.store.social_posts(day)
        target = 12
        if len(rows) >= target:
            return rows
        nodes = [
            n for n in (app.social.nodes or {}).values()
            if n.get("id") not in ("her", "user") and n.get("active", 1)
        ]
        awake = [n for n in nodes if self._npc_available(n, now)]
        # 白天优先用醒着的人；深夜/清晨没人醒着时，用其他人白天发过的动态兜底，
        # 不能因为大家都在睡觉就让朋友圈只剩她一个人。
        pool_source = awake if len(awake) >= target else nodes
        pool_source.sort(key=lambda n: float(n.get("depth") or 0), reverse=True)
        pool = pool_source[:26]
        rng = random.Random(f"{day}:society")
        rng.shuffle(pool)
        used_texts = {str(r.get("text") or "") for r in rows}
        used_images: dict[str, int] = {}
        for row in rows:
            for img in row.get("images") or []:
                used_images[str(img)] = used_images.get(str(img), 0) + 1
        start = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(8, 30)).timestamp()
        step = 65 * 60
        for index, node in enumerate(pool):
            if len(rows) >= target:
                break
            pid = f"soc:{day}:{node['id']}"
            if any(r.get("id") == pid for r in rows):
                continue
            ts = start + index * step + rng.randint(0, 18 * 60)
            stamp = dt.datetime.fromtimestamp(ts)
            slot = _hour_slot(stamp.hour + stamp.minute / 60.0)
            text = self._pick_post_text(app, node, slot, used_texts, rng)
            used_texts.add(text)
            images = self._pick_post_image(app, text, used_images, rng)
            app.store.add_social_post(pid, node["id"], text, day, images, ts=ts)
            rows = app.store.social_posts(day)
        return rows

    def _ensure_reactions(self, app, target: str, author: str, ts: float, with_comments: bool = True) -> None:
        """给动态补一批 NPC 点赞/评论；生成一次后不再重复。"""
        likes = app.store.likes_for([target]).get(target, [])
        comments = app.store.comments_for([target]).get(target, [])
        npc_likes = [u for u in likes if u != "user"]
        npc_comments = [c for c in comments if c.get("user") != "user"]
        if npc_likes or npc_comments:
            return
        nodes = [
            n for n in (app.social.nodes or {}).values()
            if n.get("active", 1) and n.get("id") not in ("user", author)
        ]
        nodes = [n for n in nodes if self._npc_available(n)]
        if not nodes:
            return
        nodes.sort(key=lambda n: float(n.get("depth") or 0), reverse=True)
        pool = nodes[:16]
        rng = random.Random(f"{target}:{int(float(ts or 0))}")
        rng.shuffle(pool)
        for node in pool[: rng.randint(1, 3)]:
            app.store.add_like(target, node["id"])
        if with_comments:
            added = []
            for node in pool[3:3 + rng.randint(0, 2)]:
                cid = app.store.add_comment(target, node["id"], _comment_text(node["id"], target))
                if cid:
                    added.append((cid, node["id"]))
            # 再让另一个社会关系成员回复这条评论：NPC 之间也有来有回
            if added and rng.random() < 0.8:
                parent_id, parent_uid = rng.choice(added)
                others = [n for n in pool if n["id"] not in (author, parent_uid)]
                if others:
                    replier = rng.choice(others)
                    reply = rng.choice([
                        "哈哈真的", "我也这么觉得", "你不是一个人", "笑死",
                        "下次一起", "确实", "同感", "这么巧",
                    ])
                    app.store.add_comment(target, replier["id"], reply, parent_id=parent_id)

    # ------------------------------------------------------------------
    # 回复他的朋友圈评论：她先回，再随机带一个社会关系成员
    # ------------------------------------------------------------------
    def _queue_comment_reply(self, app, target: str, comment_id: int, text: str) -> bool:
        comment_id = int(comment_id or 0)
        if not comment_id:
            return False
        comments = app.store.comments_for([target]).get(target, [])
        if any(int(c.get("parent_id") or 0) == comment_id and str(c.get("user")) != "user" for c in comments):
            return True
        threading.Thread(
            target=self._comment_reply_worker,
            args=(app, str(target), comment_id, str(text or "")),
            name="comment-reply",
            daemon=True,
        ).start()
        return True

    def _backfill_comment_replies(self, app) -> None:
        """启动时补回最近没被回复的评论，老评论也能收到回复。"""
        try:
            rows = app.store.unanswered_user_comments(time.time() - 86400, 3)
        except Exception:  # noqa: BLE001
            return
        for row in rows:
            self._queue_comment_reply(
                app, str(row.get("target") or ""), int(row.get("id") or 0), str(row.get("text") or "")
            )

    def _comment_reply_worker(self, app, target: str, comment_id: int, text: str) -> None:
        try:
            time.sleep(random.uniform(3.0, 9.0))
            comments = app.store.comments_for([target]).get(target, [])
            if not any(int(c.get("id") or 0) == comment_id for c in comments):
                return  # 评论已被用户删除，不再追着回
            if any(int(c.get("parent_id") or 0) == comment_id and str(c.get("user")) != "user" for c in comments):
                return
            post_text = app.store.dynamic_text(target)
            her_name = str(self._read_profile().get("her_name") or "小鲸鱼")
            llm = getattr(getattr(app, "brain", None), "llm", None)
            reply = ""
            if llm is not None and getattr(llm, "api_key", ""):
                system = (
                    f"你是{her_name}，一个嘴硬心软、会做饭的女大学生。"
                    "你正在回复他在你朋友圈动态下的评论。只写一句口语回复，10~30 字，"
                    "像微信朋友圈，不客服腔、不解释、不暴露自己是模型。"
                )
                prompt = (
                    f"动态：{post_text[:220] or '一条生活动态'}\n"
                    f"他的评论：{str(text)[:120]}\n"
                    "写你的回复，只输出一句话。"
                )
                with NPC_LLM_SEM:
                    reply = asyncio.run(
                        llm.chat_text(system, prompt, temperature=0.9, max_tokens=100)
                    )
            reply = re.sub(r"[\r\n]+", " ", str(reply or "")).strip().strip('"“”')[:60]
            if not reply:
                reply = random.choice(
                    [
                        "看到了，你倒是挺会挑时候评论",
                        "这条我记下了，等我缓过来回你",
                        "你就盯着我朋友圈看是吧",
                        "哈哈 被你发现了",
                    ]
                )
            cid = app.store.add_comment(target, "her", reply, parent_id=comment_id)
            # 再随机让一个社会关系成员接一句，避免永远只有她一个人回
            if cid and random.random() < 0.55:
                candidates = self._npc_candidates(app, "her", target, limit=2)
                if candidates and llm is not None and getattr(llm, "api_key", ""):
                    node = random.choice(candidates)
                    npc_prompt = (
                        f"你是{node.get('name')}（{node.get('role') or '朋友'}），"
                        f"性格：{self._npc_personality(node)}。\n"
                        f"动态：{post_text[:180] or '一条生活动态'}\n"
                        f"他评论：{str(text)[:100]}\n"
                        f"{her_name}刚回复：{reply[:60]}\n"
                        "写一句你接他的话，4~20 字，口语，不客服腔。只输出一句话。"
                    )
                    npc_reply = asyncio.run(
                        llm.chat_text(
                            NPC_LLM_SYSTEM, npc_prompt, temperature=0.95, max_tokens=80
                        )
                    )
                    npc_reply = re.sub(r"[\r\n]+", " ", str(npc_reply or "")).strip().strip('"“”')[:40]
                    if npc_reply:
                        app.store.add_comment(
                            target, str(node["id"]), npc_reply, parent_id=comment_id
                        )
        except Exception:  # noqa: BLE001
            log.exception("朋友圈评论回复失败")

    # ------------------------------------------------------------------
    # NPC 轻量人格层：LLM 批量写评论，失败回退模板
    # ------------------------------------------------------------------
    def _npc_candidates(self, app, author_id: str, target: str, limit: int = 4) -> list[dict]:
        comments = app.store.comments_for([target]).get(target, [])
        used = {str(c.get("user")) for c in comments}
        nodes = [
            n for n in (app.social.nodes or {}).values()
            if n.get("active", 1)
            and n.get("id") not in ("her", "user", str(author_id))
            and n.get("id") not in used
        ]
        nodes = [n for n in nodes if self._npc_available(n)]
        nodes.sort(key=lambda n: float(n.get("depth") or 0), reverse=True)
        # 尽量让家人、朋友、同学、同事、网友都有人说话，而不是全被最熟的几个人包场
        picked: list[dict] = []
        seen_cat: set[str] = set()
        for node in nodes:
            category = _role_category(str(node.get("role") or ""))
            if category not in seen_cat:
                picked.append(node)
                seen_cat.add(category)
            if len(picked) >= limit:
                break
        if len(picked) < limit:
            for node in nodes:
                if node not in picked:
                    picked.append(node)
                if len(picked) >= limit:
                    break
        return picked

    def _npc_personality(self, node: dict) -> str:
        return str(
            node.get("personality")
            or PERSONALITY.get(str(node.get("id")))
            or _role_personality(str(node.get("role") or ""))
        )

    def _queue_npc_comments(self, app, target: str, author: str, text: str) -> bool:
        text = str(text or "").strip()
        if not text:
            return False
        existing = app.store.comments_for([target]).get(target, [])
        if any(str(c.get("user")) not in ("user", "her") for c in existing):
            return True
        key = "npc_llm_at:" + str(target)
        try:
            last = float(app.store.get_state(key) or 0)
        except Exception:  # noqa: BLE001
            last = 0
        if last and time.time() - last < 6 * 3600:
            return True
        with NPC_LLM_LOCK:
            if target in NPC_LLM_INFLIGHT:
                return True
            NPC_LLM_INFLIGHT.add(target)
        try:
            app.store.set_state(key, time.time())
        except Exception:  # noqa: BLE001
            pass
        threading.Thread(
            target=self._npc_comments_worker,
            args=(app, str(target), str(author), text),
            name="npc-comments",
            daemon=True,
        ).start()
        return True

    def _npc_comments_worker(self, app, target: str, author: str, text: str) -> None:
        try:
            llm = getattr(getattr(app, "brain", None), "llm", None)
            if llm is None or not getattr(llm, "api_key", ""):
                self._add_template_comments(app, target, author)
                return
            with NPC_LLM_SEM:
                candidates = self._npc_candidates(app, author, target)
                added = (
                    self._generate_npc_comments(app, target, author, text, candidates)
                    if candidates else 0
                )
            if not added:
                self._add_template_comments(app, target, author)
        except Exception:  # noqa: BLE001
            log.exception("NPC 评论生成失败")
            self._add_template_comments(app, target, author)
        finally:
            with NPC_LLM_LOCK:
                NPC_LLM_INFLIGHT.discard(target)

    def _generate_npc_comments(
        self, app, target: str, author_id: str, text: str, candidates: list[dict]
    ) -> int:
        author = (app.social.nodes or {}).get(str(author_id)) or {}
        lines = []
        for node in candidates:
            recent = "；".join(app.store.recent_comments_by_user(node["id"], 3))
            lines.append(
                f"- id={node['id']} 昵称={node.get('name')} 关系={node.get('role')} "
                f"性格={self._npc_personality(node)} 关系深度={float(node.get('depth') or 0):.0f} "
                f"最近评论={recent or '无'}"
            )
        prompt = (
            f"动态作者：{author.get('name') or '她'}（{author.get('role') or '朋友'}）\n"
            f"动态内容：{str(text)[:300]}\n"
            "可选评论者：\n" + "\n".join(lines) + "\n"
            "写 2~3 条评论，每条 4~20 字，像微信朋友圈，必须符合各自身份和关系；"
            "可以有一条回复另一条评论，reply_to 填被回复者的 id，没有就填 0。"
            '只输出 JSON 数组：[{"id":"...","text":"...","reply_to":"..."}]'
        )
        raw = asyncio.run(
            app.brain.llm.chat_text(
                NPC_LLM_SYSTEM, prompt, temperature=0.95, max_tokens=420
            )
        )
        items = _extract_json_array(raw)
        if not items:
            return 0
        by_id = {str(n["id"]): n for n in candidates}
        node_comment_ids: dict[str, int] = {}
        for c in app.store.comments_for([target]).get(target, []):
            node_comment_ids.setdefault(str(c.get("user")), int(c.get("id") or 0))
        added = 0
        for item in items[:4]:
            if not isinstance(item, dict):
                continue
            node_id = str(item.get("id") or "")
            content = str(item.get("text") or "").strip()[:60]
            if node_id not in by_id or not content:
                continue
            parent = node_comment_ids.get(str(item.get("reply_to") or ""), 0)
            if parent == node_comment_ids.get(node_id):
                parent = 0
            cid = app.store.add_comment(target, node_id, content, parent_id=parent)
            if cid:
                node_comment_ids[node_id] = cid
                added += 1
        return added

    def _add_template_comments(self, app, target: str, author: str) -> int:
        existing = app.store.comments_for([target]).get(target, [])
        if existing:
            return 0
        nodes = self._npc_candidates(app, author, target, limit=8)
        if not nodes:
            return 0
        rng = random.Random(f"{target}:npc")
        rng.shuffle(nodes)
        added = []
        for node in nodes[: rng.randint(1, 2)]:
            cid = app.store.add_comment(target, node["id"], _comment_text(node["id"], target))
            if cid:
                added.append((cid, node["id"]))
        if added and rng.random() < 0.8:
            parent, parent_uid = rng.choice(added)
            others = [n for n in nodes if n["id"] != parent_uid]
            if others:
                replier = rng.choice(others)
                app.store.add_comment(
                    target, replier["id"], rng.choice(GENERIC_COMMENTS), parent_id=parent
                )
        return len(added)

    def _her_comment_for(self, text: str) -> str:
        text = str(text or "")
        if any(w in text for w in ("吃", "饭", "奶茶", "饿", "夜宵")):
            options = ["看饿了", "下次带我", "你自己吃的？", "怎么不叫我"]
        elif any(w in text for w in ("累", "烦", "难受", "困", "加班")):
            options = ["抱抱", "别太累", "怎么了", "早点休息"]
        elif any(w in text for w in ("好看", "照片", "拍", "风景")):
            options = ["好看", "发我原图", "在哪拍的", "这张不错"]
        elif any(w in text for w in ("上课", "作业", "考试", "复习")):
            options = ["加油", "别熬太晚", "我也在学", "摸摸"]
        elif any(w in text for w in ("想你", "喜欢", "爱你")):
            options = ["……", "突然说这个", "我也", "看到啦"]
        else:
            options = ["看到了", "怎么突然发这个", "给你点了个赞", "嗯嗯", "在呢"]
        return random.Random(f"her:{text[:60]}").choice(options)

    def _her_reaction_allowed(self, app, target: str, ts: float) -> bool:
        """她不会秒赞秒评：先等 1~3 分钟，再等她空闲且醒着。"""
        try:
            delay = random.Random("her-react:" + target).randint(60, 180)
            if time.time() - float(ts or 0) < delay:
                return False
            if app.clock.is_asleep() or app.clock.is_busy():
                return False
        except Exception:  # noqa: BLE001
            return False
        return True

    def _ensure_her_reaction(self, app, target: str, text: str) -> None:
        """他发的动态，她看到后会点赞并留一条评论。"""
        likes = app.store.likes_for([target]).get(target, [])
        comments = app.store.comments_for([target]).get(target, [])
        if "her" not in likes:
            app.store.add_like(target, "her")
        if not any(c.get("user") == "her" for c in comments):
            app.store.add_comment(target, "her", self._her_comment_for(text))

    def _build_posts(self, app, specs: list[dict], profiles: dict[str, dict]) -> list[dict]:
        targets = [s["target"] for s in specs]
        likes_map = app.store.likes_for(targets)
        comments_map = app.store.comments_for(targets)
        out = []
        for spec in specs:
            author = profiles.get(spec["author"]) or self._unknown_profile(spec["author"])
            likes = [profiles.get(uid) or self._unknown_profile(uid) for uid in likes_map.get(spec["target"], [])]
            raw_comments = comments_map.get(spec["target"], [])
            comment_ids = {int(c.get("id") or 0) for c in raw_comments}
            # 用户的评论可能已被删除，保留在库里的回复不再显示，避免幽灵评论和计数错位
            comments = [
                {
                    "id": c.get("id"),
                    "user": profiles.get(c.get("user")) or self._unknown_profile(c.get("user")),
                    "text": c.get("text") or "",
                    "parent_id": int(c.get("parent_id") or 0),
                    "ts": c.get("ts") or 0,
                }
                for c in raw_comments
                if not int(c.get("parent_id") or 0) or int(c.get("parent_id") or 0) in comment_ids
            ]
            out.append(
                {
                    "target": spec["target"],
                    "ts": spec["ts"],
                    "text": spec["text"],
                    "topic": spec.get("topic") or "",
                    "source": spec.get("source") or "",
                    "images": spec.get("images") or [],
                    "author": author,
                    "likes": likes,
                    "comments": comments,
                    "mine_liked": any(x.get("id") == "user" for x in likes),
                }
            )
        return out

    def feed(self, limit: int = 30, before: float = 0) -> dict:
        app = getattr(self.engine, "app", None) if self.engine else None
        profile = self.profile()
        if app is None:
            return {
                "ready": False, "dynamics": [], "virtual": {},
                "posts": [], "virtual_posts": [],
                "her_name": profile.get("her_name"), "her_avatar_url": profile.get("her_avatar_url"),
                "me": None,
            }
        profiles = self._profiles(app, profile)

        specs: list[dict] = []
        for row in app.store.recent_dynamics(120):
            images = []
            for raw in row.get("images") or []:
                path = Path(str(raw))
                if path.is_file():
                    images.append(self._media_url(path))
            author = str(row.get("author") or "her")
            specs.append(
                {
                    "target": f"dyn:{row.get('id')}",
                    "ts": row.get("ts") or 0,
                    "author": author,
                    "text": row.get("text") or "",
                    "topic": row.get("topic") or "",
                    "source": "我的动态" if author == "user" else "她的动态",
                    "images": images,
                }
            )
        # 朋友圈只保留“小鲸鱼”和“我（历史动态）”；其他社会角色不再发动态，只做互动
        specs.sort(key=lambda s: float(s.get("ts") or 0), reverse=True)
        if before and before > 0:
            specs = [s for s in specs if float(s.get("ts") or 0) < float(before)]
        limit = max(1, min(60, int(limit or 30)))
        has_more = len(specs) > limit
        selected = specs[:limit]
        now_ts = time.time()
        for spec in selected:
            target = spec["target"]
            fresh = float(spec.get("ts") or 0) >= now_ts - 86400
            if spec["author"] == "user":
                # 我以前的动态保留；她可以继续互动，但不再让其他角色来补赞补评
                if self._her_reaction_allowed(app, target, spec["ts"]):
                    self._ensure_her_reaction(app, target, spec["text"])
            elif spec["author"] == "her":
                self._ensure_reactions(app, target, spec["author"], spec["ts"], False)
                if fresh:
                    self._queue_npc_comments(app, target, spec["author"], spec["text"])
                else:
                    self._add_template_comments(app, target, spec["author"])
        posts = self._build_posts(app, selected, profiles)
        next_cursor = float(selected[-1].get("ts") or 0) if selected else 0.0

        viz = self.viz()
        virtual_specs: list[dict] = []
        views = {str(v.get("id")): v for v in ((viz.get("world") or {}).get("views") or [])}
        for event in (viz.get("world") or {}).get("events") or []:
            eid = str(event.get("id") or int(float(event.get("ts") or 0) * 1000))
            surface = (views.get(str(event.get("id"))) or {}).get("surface") or ""
            text = surface or f"{event.get('action') or ''} → {event.get('outcome') or ''}"
            virtual_specs.append(
                {
                    "target": f"world:{eid}",
                    "ts": event.get("ts") or 0,
                    "author": event.get("actor") or "her",
                    "text": text,
                    "topic": "",
                    "source": "虚拟社会",
                    "images": [],
                }
            )
        for event in (viz.get("social") or {}).get("events") or []:
            virtual_specs.append(
                {
                    "target": f"social:{int(float(event.get('ts') or 0) * 1000)}:{event.get('node') or 'her'}",
                    "ts": event.get("ts") or 0,
                    "author": event.get("node") or "her",
                    "text": event.get("text") or "",
                    "topic": "",
                    "source": "关系网",
                    "images": [],
                }
            )
        for art in (viz.get("practice") or {}).get("artifacts") or []:
            aid = art.get("id") or int(float(art.get("ts") or 0) * 1000)
            virtual_specs.append(
                {
                    "target": f"art:{aid}",
                    "ts": art.get("ts") or 0,
                    "author": "her",
                    "text": f"完成了{art.get('name') or art.get('title') or '一件小事'}，"
                            f"用了 {art.get('minutes') or 0} 分钟。",
                    "topic": "",
                    "source": "劳动",
                    "images": [],
                }
            )
        for view in (viz.get("world") or {}).get("views") or []:
            vid = view.get("id") or int(float(view.get("ts") or 0) * 1000)
            virtual_specs.append(
                {
                    "target": f"view:{vid}",
                    "ts": view.get("ts") or 0,
                    "author": "her",
                    "text": view.get("surface") or "",
                    "topic": "",
                    "source": "她看到的",
                    "images": [],
                }
            )
        for spec in virtual_specs:
            self._ensure_reactions(app, spec["target"], spec["author"], spec["ts"], False)
        virtual_posts = self._build_posts(app, virtual_specs, profiles)
        virtual_posts.sort(key=lambda p: float(p.get("ts") or 0), reverse=True)

        return {
            "ready": True,
            "her_name": profile.get("her_name"),
            "her_avatar_url": profile.get("her_avatar_url"),
            "me": profiles.get("user"),
            "dynamics": [],
            "posts": posts,
            "next": next_cursor,
            "has_more": has_more,
            "virtual_posts": virtual_posts[:24],
            "virtual": {
                "world_events": (viz.get("world") or {}).get("events") or [],
                "views": (viz.get("world") or {}).get("views") or [],
                "social_events": (viz.get("social") or {}).get("events") or [],
                "artifacts": (viz.get("practice") or {}).get("artifacts") or [],
                "current": (viz.get("practice") or {}).get("current"),
                "selfhood": viz.get("selfhood") or {},
                "time": viz.get("time"),
            },
        }

    def notifications(self) -> dict:
        """轻量动态消息：只查“我的动态”收到的赞和评论，不构建整份朋友圈。"""
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"ready": False, "items": []}
        profile = self.profile()
        profiles = self._profiles(app, profile)
        rows = [
            row for row in app.store.recent_dynamics(120)
            if str(row.get("author") or "her") == "user"
        ]
        targets = [f"dyn:{row.get('id')}" for row in rows]
        likes = app.store.likes_for(targets)
        comments = app.store.comments_for(targets)
        items = []
        for row in rows:
            target = f"dyn:{row.get('id')}"
            post_text = str(row.get("text") or "").strip()[:60] or "[图片]"
            base_ts = float(row.get("ts") or 0)
            for uid in likes.get(target, []):
                if uid == "user":
                    continue
                user = profiles.get(uid) or self._unknown_profile(uid)
                items.append({
                    "key": f"l:{target}:{uid}",
                    "kind": "like",
                    "ts": base_ts,
                    "user": user,
                    "post": post_text,
                    "target": target,
                })
            for c in comments.get(target, []):
                if c.get("user") == "user":
                    continue
                user = profiles.get(c.get("user")) or self._unknown_profile(c.get("user"))
                items.append({
                    "key": f"c:{target}:{c.get('id')}",
                    "kind": "comment",
                    "ts": float(c.get("ts") or base_ts),
                    "user": user,
                    "text": str(c.get("text") or ""),
                    "post": post_text,
                    "target": target,
                })
        items.sort(key=lambda x: float(x.get("ts") or 0), reverse=True)
        return {"ready": True, "items": items[:80]}

    def health(self) -> dict:
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"ready": False}
        beat = float(app.store.get_state("scheduler_beat") or 0)
        practice = getattr(getattr(app, "shadow", None), "practice", None)
        pstate = practice.state if practice is not None else {}
        return {
            "ready": True,
            "now": app.clock.now().strftime("%Y-%m-%d %H:%M:%S"),
            "scheduler_beat": beat,
            "scheduler_age": round(time.time() - beat, 1) if beat else -1,
            "practice_last_tick": pstate.get("last_tick"),
            "practice_current": pstate.get("current"),
            "catchup": pstate.get("catchup") or {},
            "last_learning_date": app.store.get_state("last_learning_date"),
            "last_selfhood_date": app.store.get_state("last_selfhood_date"),
            "last_practice_date": app.store.get_state("last_practice_date"),
            "catchup_status": app.store.get_state("catchup_status") or {},
            "life_events": (
                app.brain.life.health() if getattr(app.brain, "life", None) else {}
            ),
        }

    def toggle_post_like(self, target: str) -> bool:
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return False
        return app.store.toggle_like(str(target)[:160], "user")

    def add_post_comment(self, target: str, text: str, parent_id: int = 0) -> dict:
        app = getattr(self.engine, "app", None) if self.engine else None
        text = str(text or "").strip()
        if app is None or not text:
            return {"ok": False}
        target = str(target)[:160]
        comment_id = app.store.add_comment(target, "user", text, int(parent_id or 0))
        if comment_id:
            # 他评论完，她（以及偶尔一个社会关系成员）过几秒回他
            self._queue_comment_reply(app, target, comment_id, text)
        return {"ok": bool(comment_id), "id": comment_id}

    def history(self, limit: int = 60, before: int = 0, around: int = 0, q: str = "",
                paged: bool = False, kind: str = "", day: str = "") -> dict:
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"messages": []}
        pending: set[int] = set()
        try:
            if self.engine is not None and hasattr(self.engine, "pending_message_ids"):
                pending = set(self.engine.pending_message_ids())
        except Exception:  # noqa: BLE001
            pending = set()
        # 先取事件游标再读数据库：查询期间新产生的事件一定 > 游标，下一轮轮询会补上，
        # 不会出现“历史没读到、游标却已经跳过”的丢消息。
        cursor = self.bridge.cursor()
        has_more = False
        if before or around or q or paged or kind or day:
            page = app.store.history_page(limit=limit, before_id=before, around=around, q=q, kind=kind, day=day)
            rows = page["messages"]
            has_more = bool(page.get("has_more"))
        else:
            rows = app.store.recent_messages(max(1, min(120, int(limit))))
        out = []
        for m in rows:
            # 已经生成入库、但还在等她“真正发出来”的回复：先别让历史提前显示
            if str(m.get("role")) == "assistant" and int(m.get("id") or 0) in pending:
                continue
            media = str(m.get("media") or "")
            media_path = Path(media) if media else None
            image_url = (
                self._media_url(media_path)
                if media_path is not None and media_path.is_file()
                else ""
            )
            out.append(
                {
                    "id": m.get("id"),
                    "role": "her" if m.get("role") == "assistant" else "me",
                    "content": str(m.get("content") or ""),
                    "kind": str(m.get("kind") or "text"),
                    "media": media if str(m.get("kind")) == "transfer" else "",
                    "image_url": image_url,
                    "ts": m.get("ts") or 0,
                }
            )
        return {"messages": out, "next": cursor, "has_more": has_more}

    # ---------- 饭点（本地模拟外卖） ----------
    def food_shops(self) -> dict:
        from brainn.food import SHOPS

        return {"ok": True, "shops": SHOPS}

    def food_orders(self) -> dict:
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"ok": True, "orders": []}
        return {"ok": True, "orders": app.store.recent_food_orders(10)}

    def food_order_create(self, payload: dict) -> dict:
        from brainn.food import eta_minutes, find_shop, price_cart

        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"ok": False, "error": "not_ready"}
        shop = find_shop(str(payload.get("shop_id") or ""))
        if not shop:
            return {"ok": False, "error": "shop_not_found"}
        first_order = False
        try:
            first_order = len(app.store.recent_food_orders(3)) == 0
        except Exception:  # noqa: BLE001
            first_order = False
        cart = price_cart(shop, payload.get("items") or [], first_order=first_order)
        if not cart.get("ok"):
            return {"ok": False, "error": "empty_cart"}
        eta = eta_minutes(shop)
        address = str(payload.get("address") or "家 · 默认地址")[:60]
        note = str(payload.get("note") or "")[:80]
        order = app.store.create_food_order(
            shop["id"], shop["name"], cart["items"], cart["total"], address, note, eta
        )
        try:
            app.store.add_life_event(
                kind="takeout",
                title=f"点了{shop['name']}",
                detail="、".join(f"{i['name']}×{i['qty']}" for i in cart["items"])[:300],
                expected_at=time.time() + eta * 60,
                source="food",
                confidence=0.95,
                notify=True,
            )
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "order": order, "eta_min": eta}

    def food_suggest(self) -> dict:
        """让 2D 小鲸鱼按时间与最近订单给一单推荐（规则版，不依赖模型额度）。"""
        import random

        from brainn.food import SHOPS, price_cart

        hour = time.localtime().tm_hour
        if 5 <= hour < 10:
            prefer, slot = {"快餐", "奶茶"}, "早上"
        elif 10 <= hour < 14:
            prefer, slot = {"快餐", "面食", "汉堡"}, "中午"
        elif 14 <= hour < 17:
            prefer, slot = {"奶茶"}, "下午"
        elif 17 <= hour < 21:
            prefer, slot = {"麻辣烫", "汉堡", "面食"}, "晚上"
        else:
            prefer, slot = {"麻辣烫", "快餐", "奶茶"}, "这个点"
        app = getattr(self.engine, "app", None) if self.engine else None
        recent_ids: set[str] = set()
        if app is not None:
            try:
                recent_ids = {str(o.get("shop_id")) for o in app.store.recent_food_orders(3)}
            except Exception:  # noqa: BLE001
                recent_ids = set()
        cands = [s for s in SHOPS if s.get("cat") in prefer] or list(SHOPS)
        fresh = [s for s in cands if str(s.get("id")) not in recent_ids]
        shop = random.choice(fresh or cands)
        hot = [it for it in shop["items"] if it.get("group") in ("热销", "招牌")] or shop["items"]
        picks = random.sample(hot, min(2, len(hot)))
        lines = [{"id": it["id"], "qty": 1} for it in picks]
        cart = price_cart(shop, lines)
        names = "、".join(it["name"] for it in picks)
        text = f"{slot}想吃点热的，{shop['name']}的{names}看着不错，要不要？"
        return {
            "ok": True,
            "shop_id": shop["id"],
            "shop_name": shop["name"],
            "items": [it["id"] for it in picks],
            "text": text,
            "total": cart["total"],
        }

    def food_order_cancel(self, order_id: int) -> dict:
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"ok": False, "error": "not_ready"}
        order = app.store.food_order(int(order_id))
        if not order:
            return {"ok": False, "error": "not_found"}
        if str(order.get("status")) in ("cancelled", "done"):
            return {"ok": False, "error": "not_cancellable"}
        app.store.update_food_order(int(order_id), "cancelled")
        try:
            app.store.add_life_event(
                kind="takeout",
                title=f"取消了{order.get('shop_name') or '外卖'}",
                detail="订单已取消",
                source="food",
                confidence=0.9,
                notify=False,
            )
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "order": app.store.food_order(int(order_id))}

    # ---------- 拼单商城（本地模拟） ----------
    def mall_goods(self) -> dict:
        from brainn.mall import CATS, GOODS

        return {"ok": True, "cats": CATS, "goods": GOODS}

    def mall_orders(self) -> dict:
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"ok": True, "orders": []}
        return {"ok": True, "orders": app.store.recent_mall_orders(10)}

    def mall_order_create(self, payload: dict) -> dict:
        from brainn.mall import price_lines

        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"ok": False, "error": "not_ready"}
        lines = price_lines(payload.get("items") or [])
        if not lines.get("ok"):
            return {"ok": False, "error": "empty_cart"}
        address = str(payload.get("address") or "家 · 默认地址")[:60]
        order = app.store.create_mall_order(lines["items"], lines["total"], address)
        try:
            app.store.add_life_event(
                kind="parcel",
                title="拼了一单",
                detail="、".join(f"{i['name']}×{i['qty']}" for i in lines["items"])[:300],
                expected_at=time.time() + 3 * 86400,
                source="mall",
                confidence=0.9,
                notify=False,
            )
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "order": order}

    def mall_order_cancel(self, order_id: int) -> dict:
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"ok": False, "error": "not_ready"}
        order = app.store.mall_order(int(order_id))
        if not order:
            return {"ok": False, "error": "not_found"}
        if str(order.get("status")) in ("cancelled", "done"):
            return {"ok": False, "error": "not_cancellable"}
        app.store.update_mall_order(int(order_id), "cancelled")
        return {"ok": True, "order": app.store.mall_order(int(order_id))}

    # ---------- 短视频（本地模拟 + 她参与） ----------
    def shorts_list(self) -> dict:
        from brainn.shorts import list_items, seed_comments

        items = list_items()
        app = getattr(self.engine, "app", None) if self.engine else None
        for item in items:
            count = len(seed_comments(item["id"]))
            if app is not None:
                try:
                    count += len(app.store.short_comments(item["id"]))
                except Exception:  # noqa: BLE001
                    pass
            item["comments"] = count
        return {"ok": True, "items": items}

    def shorts_comments(self, short_id: str) -> dict:
        from brainn.shorts import find_short, seed_comments

        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"ok": False, "error": "not_ready", "comments": []}
        if not find_short(short_id):
            return {"ok": False, "error": "not_found", "comments": []}
        out: list[dict] = []
        for i, c in enumerate(seed_comments(short_id)):
            out.append({
                "id": -(i + 1),
                "user": c["user"],
                "text": c["text"],
                "reply_to": 0,
                "ts": 0,
                "her": False,
            })
        for row in app.store.short_comments(short_id):
            out.append({
                "id": int(row.get("id") or 0),
                "user": str(row.get("user") or ""),
                "text": str(row.get("text") or ""),
                "reply_to": int(row.get("reply_to") or 0),
                "ts": float(row.get("created_at") or 0),
                "her": str(row.get("user") or "") == "her",
            })
        return {"ok": True, "comments": out}

    def shorts_comment_create(self, payload: dict) -> dict:
        from brainn.shorts import find_short

        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"ok": False, "error": "not_ready"}
        short_id = str(payload.get("id") or "")
        text = str(payload.get("text") or "").strip()[:120]
        if not find_short(short_id) or not text:
            return {"ok": False, "error": "bad_request"}
        cid = app.store.add_short_comment(short_id, "user", text)
        threading.Thread(
            target=self._shorts_comment_worker,
            args=(app, short_id, cid, text),
            name="shorts-comment",
            daemon=True,
        ).start()
        return {"ok": True, "id": cid}

    def shorts_watch(self, payload: dict) -> dict:
        from brainn.shorts import find_short

        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"ok": False, "error": "not_ready"}
        video = find_short(str(payload.get("id") or ""))
        if not video:
            return {"ok": False, "error": "not_found"}
        try:
            seconds = float(payload.get("seconds") or 0)
        except (TypeError, ValueError):
            seconds = 0.0
        try:
            day = time.strftime("%Y%m%d")
            seen = str(app.store.get_state("shorts_seen", "") or "")
            key = f"{day}:{video['id']}"
            if key not in seen.split(","):
                app.store.add_life_event(
                    kind="video",
                    title="一起刷短视频",
                    detail=f"和你一起看了「{video['title']}」"[:300],
                    expected_at=time.time(),
                    source="shorts",
                    confidence=0.7,
                    notify=False,
                )
                app.store.set_state("shorts_seen", (seen + "," + key)[-400:])
        except Exception:  # noqa: BLE001
            log.warning("短视频生活记录写入失败", exc_info=True)
        sent = False
        try:
            clock = getattr(app, "clock", None)
            asleep = bool(clock.is_asleep()) if clock is not None else False
            last = float(app.store.get_state("shorts_companion_ts") or 0)
            if seconds >= 8 and not asleep and (time.time() - last) >= 1200 and random.random() < 0.5:
                app.store.set_state("shorts_companion_ts", str(time.time()))
                threading.Thread(
                    target=self._shorts_companion_worker,
                    args=(app, video),
                    name="shorts-companion",
                    daemon=True,
                ).start()
                sent = True
        except Exception:  # noqa: BLE001
            log.warning("短视频陪看消息调度失败", exc_info=True)
        return {"ok": True, "companion": sent}

    def _shorts_line(self, app, system: str, prompt: str, fallback: list[str]) -> str:
        llm = getattr(getattr(app, "brain", None), "llm", None)
        line = ""
        if llm is not None and getattr(llm, "api_key", ""):
            try:
                with NPC_LLM_SEM:
                    line = asyncio.run(
                        llm.chat_text(system, prompt, temperature=0.92, max_tokens=100)
                    )
            except Exception:  # noqa: BLE001
                line = ""
        line = re.sub(r"[\r\n]+", " ", str(line or "")).strip().strip('"“”')[:60]
        return line or random.choice(fallback)

    def _shorts_comment_worker(self, app, short_id: str, comment_id: int, text: str) -> None:
        from brainn.shorts import find_short

        try:
            time.sleep(random.uniform(2.5, 6.0))
            rows = app.store.short_comments(short_id)
            if not any(int(r.get("id") or 0) == int(comment_id) for r in rows):
                return
            if any(int(r.get("reply_to") or 0) == int(comment_id) for r in rows):
                return
            video = find_short(short_id)
            if not video:
                return
            her_name = str(self._read_profile().get("her_name") or "小鲸鱼")
            system = (
                f"你是{her_name}，一个嘴硬心软、会做饭的女大学生。"
                "你们正一起刷短视频，你在评论区回复他。只写一句口语，8~30 字，"
                "可以接梗、可以嫌弃他，但不客服腔、不解释、不暴露自己是模型。"
            )
            prompt = (
                f"视频标题：{video['title']}\n视频文案：{video['desc']}\n"
                f"他的评论：{str(text)[:100]}\n"
                "写你的回复，只输出一句话。"
            )
            reply = self._shorts_line(
                app, system, prompt,
                ["你倒是挺会挑重点", "哈哈哈你也刷到这条了", "评论区就你最积极", "看到了，别急着划走"],
            )
            reply = re.sub(r"（[^）]*）|\([^)]*\)", "", str(reply or "")).strip()[:40]
            app.store.add_short_comment(short_id, "her", reply, reply_to=int(comment_id))
        except Exception:  # noqa: BLE001
            log.exception("短视频评论回复失败")

    def _shorts_companion_worker(self, app, video: dict) -> None:
        try:
            her_name = str(self._read_profile().get("her_name") or "小鲸鱼")
            system = (
                f"你是{her_name}，一个嘴硬心软的女大学生，正在微信上给他发消息。"
                "直接对他说，用第二人称“你”。只写一句口语，8~20 字。"
                "不要旁白、不要括号、不要第三人称、不要解释你在做什么、不提 AI。"
            )
            prompt = (
                f"你们刚一起刷到短视频「{video['title']}」。"
                "写你要发给他的那一句微信，只输出这一句。"
            )
            line = self._shorts_line(
                app, system, prompt,
                ["这条我刷到过，比你会挑", "你先看，别急着划走", "这个配乐有点上头", "看完记得跟我说你在想什么"],
            )
            line = re.sub(r"（[^）]*）|\([^)]*\)", "", str(line or "")).strip()
            if not line or "他" in line or "她" in line or "视频里" in line or "刚刚我们" in line:
                line = random.choice(
                    ["这条我刷到过，比你会挑", "你先看，别急着划走", "这个配乐有点上头"]
                )
            line = line[:30]
            engine = self.engine
            if engine is None or getattr(engine, "loop", None) is None:
                return
            from brainn.timing import OutSegment, ReplyPlan

            plan = ReplyPlan([OutSegment("text", line, random.uniform(2.0, 4.0))])
            asyncio.run_coroutine_threadsafe(engine.deliver(plan), engine.loop)
        except Exception:  # noqa: BLE001
            log.exception("短视频陪看消息发送失败")

    # ---------- 小鲸鱼页独立互动记录 ----------
    @staticmethod
    def _clean_whale_content(content) -> str:
        text = str(content or "")
        if text.strip().startswith('{"text"'):
            m = re.search(r'"text"\s*:\s*"([^"]{1,220})', text)
            if m:
                return m.group(1)
            return ""
        return text

    def whale_history(self, limit: int = 40) -> dict:
        whale = getattr(self, "whale", None)
        if whale is not None and self._whale_smart():
            rows = whale.history(max(1, min(120, int(limit))))
            if rows:
                clean_rows = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    item = dict(row)
                    item["content"] = self._clean_whale_content(item.get("content"))
                    clean_rows.append(item)
                if clean_rows:
                    return {"messages": clean_rows}
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return {"messages": []}
        rows = app.store.recent_whale_messages(max(1, min(120, int(limit))))
        out = []
        for m in rows:
            media = str(m.get("media") or "")
            media_path = Path(media) if media else None
            out.append(
                {
                    "id": m.get("id"),
                    "role": "me" if m.get("role") == "user" else "her",
                    "content": self._clean_whale_content(m.get("content")),
                    "kind": str(m.get("kind") or "text"),
                    "url": (
                        self._media_url(media_path)
                        if media_path is not None and media_path.is_file()
                        else ""
                    ),
                    "ts": m.get("ts") or 0,
                }
            )
        return {"messages": out}

    def whale_say(self, role: str, content: str, kind: str = "text", media: str = "") -> int:
        if not str(content or "").strip():
            return 0
        whale = getattr(self, "whale", None)
        if whale is not None and self._whale_smart():
            line_id = whale.add_line(str(role), str(content)[:400], str(kind or "text"), str(media or ""))
            if line_id:
                return line_id
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return 0
        try:
            return int(
                app.store.add_message(
                    str(role), str(content)[:400], str(kind or "text"), media=str(media or ""), session="whale"
                )
            )
        except Exception:  # noqa: BLE001
            log.warning("小鲸鱼互动记录写入失败\n%s", traceback.format_exc())
            return 0

    # ---------- 小鲸鱼专属 BrainN（独立库 / 独立人设） ----------
    @property
    def _whale_settings_file(self) -> Path:
        return self.root / "whale_brain" / "settings.json"

    def _whale_smart(self) -> bool:
        # 9.0：三个入口已合成一个存在，不再需要手动开关；配了 Key 就直接走 Brain-Truth
        key = str(getattr(self.config, "deepseek_key", "") or "").strip() if self.config else ""
        return bool(key)

    def whale_settings(self) -> dict:
        return {"ok": True, "smart": self._whale_smart()}

    def save_whale_settings(self, payload: dict) -> dict:
        smart = bool(payload.get("smart"))
        path = self._whale_settings_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"smart": smart}, ensure_ascii=False), encoding="utf-8")
        whale = getattr(self, "whale", None)
        if whale is not None:
            if smart:
                threading.Thread(target=whale.start, name="whale-start", daemon=True).start()
            else:
                threading.Thread(target=whale.stop, name="whale-stop", daemon=True).start()
        return {"ok": True, "smart": smart}

    def api_balance(self) -> dict:
        """查 DeepSeek 账户余额，给设置页显示还剩多少额度。"""
        key = str(getattr(self.config, "deepseek_key", "") or "").strip() if self.config else ""
        if not key:
            return {"ok": False, "error": "missing_key"}
        llm = (self.config.settings.get("llm") or {}) if self.config else {}
        base = str(llm.get("base_url") or "https://api.deepseek.com").strip().rstrip("/")
        if "deepseek" not in base:
            return {"ok": False, "error": "unsupported"}
        if base.endswith("/v1"):
            base = base[:-3]
        try:
            resp = httpx.get(
                base + "/user/balance",
                headers={"Authorization": "Bearer " + key},
                timeout=12,
            )
            if resp.status_code != 200:
                return {"ok": False, "error": "http_" + str(resp.status_code)}
            data = resp.json()
            infos = data.get("balance_infos") or []
            if not infos:
                return {"ok": False, "error": "empty"}
            info = infos[0]
            return {
                "ok": True,
                "available": bool(data.get("is_available")),
                "currency": str(info.get("currency") or ""),
                "total": str(info.get("total_balance") or ""),
                "granted": str(info.get("granted_balance") or ""),
                "topped": str(info.get("topped_up_balance") or ""),
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:120]}

    def minimax_balance(self, payload: dict) -> dict:
        """MiniMax 余额：钱包接口需要 Admin Key，TTS Key 只能查 Token Plan。"""
        data = payload or {}
        key = str(data.get("key") or "").strip()
        group = str(data.get("group") or "").strip()
        admin = str(data.get("admin_key") or "").strip()
        if admin:
            try:
                url = "https://api.minimaxi.com/v1/account/balance"
                if group:
                    url += "?GroupId=" + quote(group)
                resp = httpx.get(url, headers={"Authorization": "Bearer " + admin}, timeout=12)
                body = resp.json()
                if resp.status_code == 200:
                    amount, currency = self._pick_balance(body)
                    if amount is not None:
                        return {"ok": True, "balance": amount, "currency": currency, "source": "wallet"}
                    return {"ok": False, "message": "返回里没有余额字段"}
                return {"ok": False, "message": self._minimax_error(body, resp.status_code)}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "message": str(exc)[:120]}
        if key:
            try:
                resp = httpx.get(
                    "https://api.minimaxi.com/v1/token_plan/remains",
                    headers={"Authorization": "Bearer " + key},
                    timeout=12,
                )
                body = resp.json()
                if resp.status_code == 200:
                    amount, currency = self._pick_balance(body)
                    if amount is not None:
                        return {"ok": True, "balance": amount, "currency": currency, "source": "token_plan"}
                msg = self._minimax_error(body, resp.status_code)
                if "no active token plan" in str(msg).lower() or resp.status_code == 200:
                    return {"ok": False, "need_admin": True,
                            "message": "钱包余额需要 Admin Key；当前 TTS Key 没有 Token Plan"}
                return {"ok": False, "message": msg}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "message": str(exc)[:120]}
        return {"ok": False, "need_admin": True, "message": "先填 API Key 或 Admin Key"}

    @staticmethod
    def _minimax_error(data: dict, status: int) -> str:
        try:
            err = data.get("error") if isinstance(data, dict) else None
            if isinstance(err, dict) and err.get("message"):
                return str(err.get("message"))[:160]
            base = data.get("base_resp") if isinstance(data, dict) else None
            if isinstance(base, dict) and base.get("status_msg"):
                return str(base.get("status_msg"))[:160]
        except Exception:  # noqa: BLE001
            pass
        return "http_" + str(status)

    @classmethod
    def _pick_balance(cls, obj) -> tuple[str | None, str]:
        currency = ""
        if isinstance(obj, dict):
            for key in ("currency", "unit", "coin"):
                value = obj.get(key)
                if isinstance(value, str) and value.strip():
                    currency = value.strip().upper()[:8]
                    break
            for key in (
                "balance", "account_balance", "total_balance", "available_balance",
                "cash_balance", "credit_balance", "wallet_balance", "remaining",
                "remains", "total_remains", "token_remains",
            ):
                value = obj.get(key)
                if isinstance(value, bool) or value is None:
                    continue
                if isinstance(value, (int, float)):
                    return cls._fmt_balance(value), currency
                if isinstance(value, str) and value.strip():
                    try:
                        return cls._fmt_balance(float(value)), currency
                    except ValueError:
                        pass
            for key in ("data", "result", "account", "wallet", "balance_infos",
                        "model_remains", "wallet_info", "account_info"):
                value = obj.get(key)
                if isinstance(value, (dict, list)):
                    amount, cur = cls._pick_balance(value)
                    if amount is not None:
                        return amount, cur or currency
        elif isinstance(obj, list):
            for value in obj:
                amount, cur = cls._pick_balance(value)
                if amount is not None:
                    return amount, cur or currency
        return None, currency

    @staticmethod
    def _fmt_balance(value: float) -> str:
        value = float(value)
        if abs(value - round(value)) < 0.0001:
            return str(int(round(value)))
        return f"{value:.2f}"

    # ------------------------------------------------------------------
    def _memory_holder(self):
        """记忆页优先用小鲸鱼实例；它没启动时退回主聊天实例（同一个共享库）。"""
        whale = getattr(self, "whale", None)
        if whale is not None and getattr(whale, "app", None) is not None:
            return whale
        app = getattr(getattr(self, "engine", None), "app", None)
        if app is None:
            return None
        from brainn.whale_brain import WhaleBrain

        proxy = WhaleBrain.__new__(WhaleBrain)
        proxy.app = app
        return proxy

    def _whale_memory(self, method: str, *args) -> dict:
        holder = self._memory_holder()
        if holder is None:
            return {"ok": False, "error": "not_initialized", "items": []}
        return getattr(holder, method)(*args)

    def memory_list(self, query: str = "", status: str = "", limit: int = 60) -> dict:
        return self._whale_memory("memory_list", query, status, limit)

    def memory_update(self, payload: dict) -> dict:
        return self._whale_memory("memory_update", payload or {})

    def memory_delete(self, payload: dict) -> dict:
        return self._whale_memory("memory_delete", payload or {})

    def memory_related(self, memory_id: int) -> dict:
        return self._whale_memory("memory_related", memory_id)

    def memory_rebuild(self) -> dict:
        return self._whale_memory("memory_rebuild")

    def memory_graph(self, limit: int = 80) -> dict:
        return self._whale_memory("memory_graph", limit)

    def memory_export(self) -> dict:
        return self._whale_memory("memory_export")

    def memory_import(self, payload: dict) -> dict:
        return self._whale_memory("memory_import", payload or {})

    # ------------------------------------------------------------------
    # 全量记忆（增援未来）与提取记忆
    # ------------------------------------------------------------------
    def _primary_app(self):
        for holder in (getattr(self, "engine", None), getattr(self, "whale", None)):
            app = getattr(holder, "app", None)
            if app is not None:
                return app
        return None

    def full_memory_dir(self) -> Path:
        app = self._primary_app()
        fm = getattr(app, "full_memory", None) if app is not None else None
        if fm is not None:
            return Path(fm.dir)
        if self.config is not None:
            return Path(self.config.data_dir) / "full_memory"
        return Path(".")

    def full_memory_status(self) -> dict:
        cfg = (self.config.settings if self.config else {}) or {}
        on = bool((cfg.get("memory") or {}).get("full", True))
        app = self._primary_app()
        fm = getattr(app, "full_memory", None) if app is not None else None
        if fm is not None:
            on = bool(fm.enabled)
        hint = str(self.full_memory_dir())
        archive = fm.stats() if fm is not None else {
            "on": on, "files": 0, "bytes": 0, "dir": hint
        }
        counts: dict[str, int] = {}
        if app is not None:
            try:
                counts = app.store.db_counts()
            except Exception:  # noqa: BLE001
                counts = {}
        return {
            "ok": True,
            "on": on,
            "dir": archive.get("dir") or "",
            "files": archive.get("files", 0),
            "bytes": archive.get("bytes", 0),
            "updated_at": archive.get("updated_at", 0),
            "counts": counts,
            "version": VERSION,
        }

    def set_full_memory(self, on: bool, dir_path: str | None = None) -> dict:
        on = bool(on)
        path = self.root / "config" / "settings_overrides.yaml"
        current: dict = {}
        if path.exists():
            try:
                current = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001
                current = {}
        mem_cfg = current.get("memory")
        if not isinstance(mem_cfg, dict):
            mem_cfg = {}
            current["memory"] = mem_cfg
        mem_cfg["full"] = on

        new_dir: Path | None = None
        copied = 0
        if dir_path is not None:
            text = str(dir_path).strip()
            if text:
                new_dir = Path(os.path.expanduser(text)).resolve()
                mem_cfg["full_dir"] = str(new_dir)
            else:
                mem_cfg.pop("full_dir", None)
                if self.config is not None:
                    new_dir = Path(self.config.data_dir) / "full_memory"

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(current, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        if self.config is not None:
            mem = self.config.settings.setdefault("memory", {})
            mem["full"] = on
            if new_dir is not None:
                mem["full_dir"] = str(new_dir)
            elif dir_path is not None:
                mem.pop("full_dir", None)
        # 小鲸鱼实例可能还没启动：同步它保存的设置副本，启动时才会用新值
        base = getattr(getattr(self, "whale", None), "base_settings", None)
        if isinstance(base, dict):
            bmem = base.setdefault("memory", {})
            bmem["full"] = on
            if new_dir is not None:
                bmem["full_dir"] = str(new_dir)
            elif dir_path is not None:
                bmem.pop("full_dir", None)
        for holder in (getattr(self, "engine", None), getattr(self, "whale", None)):
            app = getattr(holder, "app", None)
            if app is None:
                continue
            fm = getattr(app, "full_memory", None)
            if fm is not None:
                if new_dir is not None:
                    info = fm.set_directory(new_dir, copy_existing=True)
                    copied += int(info.get("copied") or 0)
                fm.set_enabled(on)
        # 重新打开时把关闭期间漏掉的聊天补进全量记忆；按 id 去重，不会重复写
        if on:
            app = self._primary_app()
            fm = getattr(app, "full_memory", None) if app is not None else None
            if fm is not None:
                try:
                    added = fm.backfill_messages(app.store.all_messages())
                    app.store.set_state(
                        "full_memory_backfilled_v1",
                        {"at": time.time(), "added": added},
                    )
                except Exception:  # noqa: BLE001
                    log.warning("全量记忆补历史失败", exc_info=True)
        log.info("全量记忆：%s", "开启" if on else "关闭")
        result = self.full_memory_status()
        result["dir_copied"] = copied
        return result

    def memory_extract(self) -> dict:
        """提取记忆：整库 SQLite + 清单 JSON 打包，供 U 盘/高速磁盘带走。"""
        app = self._primary_app()
        if app is None or self.config is None:
            return {"ok": False, "error": "not_ready"}
        out_dir = self.full_memory_dir() / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = f"BrainTruth-memory-{stamp}.zip"
        tmp_db = out_dir / f"memory-{stamp}.db"
        try:
            app.store.backup_to(tmp_db)
            digest = sha256(tmp_db.read_bytes()).hexdigest()
            counts = app.store.db_counts()
            fm = getattr(app, "full_memory", None)
            archive = fm.stats() if fm is not None else {}
            try:
                persona = json.loads(
                    json.dumps(
                        {
                            "persona": self.config.persona,
                            "knobs": app.persona.knobs(),
                            "state": {
                                "mood": app.mood.state.snapshot(),
                                "body": app.body.status(),
                            },
                        },
                        ensure_ascii=False,
                        default=str,
                    )
                )
            except Exception:  # noqa: BLE001
                persona = {}
            manifest = {
                "app": "Brain-Truth",
                "kind": "memory_extract",
                "version": VERSION,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "created_ts": time.time(),
                "database": "memory.db",
                "database_sha256": digest,
                "database_bytes": tmp_db.stat().st_size,
                "tables": counts,
                "persona": persona,
                "full_memory": {
                    "on": bool(archive.get("on")),
                    "dir": archive.get("dir", ""),
                    "files": archive.get("files", 0),
                    "bytes": archive.get("bytes", 0),
                },
                "note": (
                    "memory.db 是完整 SQLite 库（消息、长期记忆、图谱、人格、QT 八账本都在里面）；"
                    "manifest.json 是清单。换载体或未来迁到量子计算机时，直接带上这两个文件。"
                ),
            }
            target = out_dir / name
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                z.write(tmp_db, "memory.db")
                z.writestr(
                    "manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
                )
            return {
                "ok": True,
                "path": str(target),
                "name": name,
                "bytes": target.stat().st_size,
                "counts": counts,
                "manifest": manifest,
            }
        except Exception as exc:  # noqa: BLE001
            log.exception("提取记忆失败")
            return {"ok": False, "error": str(exc)[:200]}
        finally:
            try:
                tmp_db.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass

    def run_memory_probe(self) -> dict:
        """手动跑一次记忆探针，让记忆页的分数不是几天前的旧值。"""
        holder = self._memory_holder()
        app = getattr(holder, "app", None) if holder is not None else None
        if app is None:
            return {"ok": False, "error": "not_ready"}
        try:
            result = app.memory.weekly_probe()
            return {"ok": True, **result}
        except Exception as exc:  # noqa: BLE001
            log.exception("记忆探针失败")
            return {"ok": False, "error": str(exc)[:160]}

    def proactive_items(self, since: float = 0.0, limit: int = 20) -> dict:
        app = self._primary_app()
        if app is None:
            return {"ok": False, "items": [], "last": 0}
        try:
            since = float(since or 0)
        except (TypeError, ValueError):
            since = 0.0
        try:
            items = app.store.proactive_items_since(since, max(1, min(int(limit or 20), 50)))
        except Exception:  # noqa: BLE001
            items = []
        return {
            "ok": True,
            "items": items,
            "last": max([float(i.get("ts") or 0) for i in items], default=since),
        }

    def _qt_store(self):
        # 记忆页属于小鲸鱼；优先用它，未启动时退回主聊天实例
        for holder in (getattr(self, "whale", None), getattr(self, "engine", None)):
            app = getattr(holder, "app", None)
            store = getattr(app, "store", None)
            if store is not None:
                return store
        return None

    def _qt_brain(self):
        for holder in (getattr(self, "whale", None), getattr(self, "engine", None)):
            app = getattr(holder, "app", None)
            brain = getattr(app, "brain", None)
            if brain is not None:
                return brain
        return None

    def qt_modules(self) -> dict:
        """QT 命名映射 + 账本计数 + 有限性状态。只读。"""
        from brainn.qt import carrier_state, finitude_state, summary

        data = summary()
        store = self._qt_store()
        if store is not None:
            try:
                data["ledgers"] = store.qt_ledger_counts()
                data["finitude"] = finitude_state(store)
                data["continuity"] = store.get_state("qt_continuity") or {}
                data["instance"] = store.get_state("qt_instance_id") or ""
                data["metrics"] = store.qt_metrics_summary()
                data["pending_confirm"] = store.qt_pending_count()
                data["carrier"] = carrier_state(store)
                data["insertion"] = store.get_state("qt_insertion") or {}
            except Exception:  # noqa: BLE001
                log.warning("读取 QT 状态失败", exc_info=True)
        data["ok"] = True
        return data

    def qt_ledger(self, table: str, limit: int = 20) -> dict:
        store = self._qt_store()
        if store is None:
            return {"ok": False, "error": "not_ready", "items": []}
        return {"ok": True, "table": table, "items": store.qt_recent(table, limit)}

    def qt_metrics(self, prefix: str = "") -> dict:
        store = self._qt_store()
        if store is None:
            return {"ok": False, "error": "not_ready"}
        data = store.qt_metrics_summary(prefix=prefix)
        data["ok"] = True
        return data

    def qt_confirm_m14(self, payload: dict) -> dict:
        """人工确认一条 M14 反观提案；确认后才改写自我节点。"""
        try:
            tension_id = int((payload or {}).get("id") or 0)
        except (TypeError, ValueError):
            tension_id = 0
        if not tension_id:
            return {"ok": False, "error": "bad_id"}
        brain = self._qt_brain()
        if brain is None:
            return {"ok": False, "error": "not_ready"}
        core = getattr(brain, "core", None)
        shadow = getattr(core, "shadow", None)
        if shadow is None:
            return {"ok": False, "error": "no_runtime"}
        try:
            result = shadow.practice.confirm_writeback(
                tension_id,
                mood=getattr(brain, "mood", None),
                meaning=getattr(brain, "meaning", None),
                persona=getattr(brain, "persona", None),
                social=getattr(brain, "social", None),
                drives=getattr(shadow, "drives", None),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("M14 人工确认失败：%s", exc)
            return {"ok": False, "error": "confirm_failed"}
        return {"ok": bool(result), "result": result}

    def whale_brain_status(self) -> dict:
        whale = getattr(self, "whale", None)
        if whale is None:
            return {"ok": False, "ready": False, "error": "not_initialized"}
        data = whale.status()
        data["ok"] = True
        return data

    def whale_brain_persona(self) -> dict:
        whale = getattr(self, "whale", None)
        if whale is None:
            return {"ok": False, "error": "not_initialized"}
        return {"ok": True, "persona": whale.persona_view()}

    def whale_brain_save_persona(self, payload: dict) -> dict:
        whale = getattr(self, "whale", None)
        if whale is None:
            return {"ok": False, "error": "not_initialized"}
        try:
            view = whale.save_persona(payload or {})
        except Exception as exc:  # noqa: BLE001
            log.exception("保存小鲸鱼人设失败")
            return {"ok": False, "error": str(exc)[:200]}
        threading.Thread(target=whale.restart, name="whale-restart", daemon=True).start()
        return {"ok": True, "persona": view, "restarting": True}

    def whale_brain_start(self) -> dict:
        whale = getattr(self, "whale", None)
        if whale is None:
            return {"ok": False, "error": "not_initialized"}
        if whale.app is None and not whale.starting:
            threading.Thread(target=whale.start, name="whale-start", daemon=True).start()
        data = whale.status()
        data["ok"] = True
        return data

    def whale_brain_stop(self) -> dict:
        whale = getattr(self, "whale", None)
        if whale is None:
            return {"ok": False, "error": "not_initialized"}
        whale.stop()
        data = whale.status()
        data["ok"] = True
        return data

    def whale_brain_restart(self) -> dict:
        whale = getattr(self, "whale", None)
        if whale is None:
            return {"ok": False, "error": "not_initialized"}
        threading.Thread(target=whale.restart, name="whale-restart", daemon=True).start()
        data = whale.status()
        data["ok"] = True
        data["restarting"] = True
        return data

    def screen_info(self) -> dict:
        data = {"ok": False}
        try:
            from java import jclass

            raw = jclass("com.ganfanyu.app.UsageReader").currentAppJson()
            parsed = json.loads(str(raw))
            if isinstance(parsed, dict):
                data = parsed
        except Exception:  # noqa: BLE001
            pass
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is not None and data.get("ok"):
            try:
                app.store.set_state(
                    "mobile_screen_context",
                    {
                        "label": str(data.get("label") or "")[:40],
                        "package": str(data.get("package") or "")[:80],
                        "minutes": int(data.get("minutes") or 0),
                        "ts": time.time(),
                    },
                )
            except Exception:  # noqa: BLE001
                pass
        return data

    def _start_screen_loop(self) -> None:
        if self._screen_thread is not None:
            return

        def _run() -> None:
            while True:
                try:
                    self.screen_info()
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(60)

        self._screen_thread = threading.Thread(target=_run, name="brainn-screen", daemon=True)
        self._screen_thread.start()


    def apikey_info(self) -> dict:
        cfg = self.config
        llm = (cfg.settings.get("llm", {}) if cfg else {}) or {}
        key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        app = getattr(self.engine, "app", None) if self.engine else None
        model = ""
        if app is not None:
            model = str(getattr(app.llm, "model", "") or "")
        return {
            "configured": bool(key),
            "key_mask": (key[:3] + "****" + key[-4:]) if len(key) > 8 else "",
            "base_url": str(llm.get("base_url") or ""),
            "model": model or str(llm.get("model") or ""),
            "vision_model": str(llm.get("vision_model") or ""),
            "models": llm.get("models") or {},
            "status": self.status(),
        }

    def save_api(
        self, key: str, model: str, base_url: str, vision_model: str = ""
    ) -> dict:
        key = str(key or "").strip()
        base_url = str(base_url or "").strip()
        model = str(model or "").strip()
        vision_model = str(vision_model or "").strip()
        if key:
            self._write_key(key)
        patch: dict = {}
        if base_url:
            patch["base_url"] = base_url
        if model:
            patch["model"] = model
            patch["models"] = {model: model}
            patch["vision_model"] = vision_model or model
        elif vision_model:
            patch["vision_model"] = vision_model
        if patch:
            self.save_config({"llm": patch}, {})
            if self.engine and getattr(self.engine, "app", None):
                try:
                    self.engine.app.store.set_state("llm_model", model or "")
                except Exception:  # noqa: BLE001
                    pass
        self.load()
        threading.Thread(target=self.restart_engine, daemon=True).start()
        return {"ok": True}

    def needs_key(self) -> bool:
        return not (self.config and self.config.deepseek_key)

    def start_engine(self) -> None:
        if self.engine is not None or self.starting:
            return
        if self.needs_key():
            self.bridge.show_system("（还没有填 API Key）")
            return
        self.starting = True
        self.bridge.show_system("（正在启动，第一次会慢一点）")

        def _run() -> None:
            try:
                from brainn.chat_engine import ChatEngine

                engine = ChatEngine(self.config, self.bridge)
                if not engine.start():
                    self.error = "初始化失败，请查看 logs/brainn.log"
                    self.bridge.show_system(f"（{self.error}）")
                    return
                self.engine = engine
                log.info("手机端引擎已启动")
                try:
                    self._backfill_comment_replies(engine.app)
                except Exception:  # noqa: BLE001
                    log.exception("补回未回复评论失败")
                nick = self._read_profile().get("nickname")
                if nick:
                    try:
                        engine.app.store.set_state("mobile_user_name", str(nick))
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:
                self.error = "启动异常"
                log.error("手机端引擎启动失败\n%s", traceback.format_exc())
                self.bridge.show_system("（启动异常，请查看 logs/brainn.log）")
            finally:
                self.starting = False

        threading.Thread(target=_run, name="brainn-start", daemon=True).start()

    @staticmethod
    def _mobile_local_init(app) -> None:
        """手机端启动准备：动态规则、一次性清库、首次补跑标记。"""
        # 手机端动态：只有她自己发，每天 3~6 条（电脑 QQ 端仍按原 settings）
        try:
            cfg = app.brain.settings.setdefault("dynamic", {})
            cfg["daily_quota"] = [3, 6]
            cfg["windows"] = [
                ["08:30", "09:30"],
                ["10:30", "11:30"],
                ["13:30", "14:30"],
                ["15:30", "16:30"],
                ["18:30", "19:30"],
                ["20:30", "22:00"],
            ]
            cfg["min_gap_minutes"] = 100
        except Exception:  # noqa: BLE001
            log.exception("手机端动态配置失败")
        # 手机端不自动把照片收进表情包
        try:
            app.brain.allow_image_sticker_steal = False
        except Exception:  # noqa: BLE001
            pass
        # v6.9.5：焕新主动话题库。只在手机端仍是旧默认话题时替换（内存级，不写用户 yaml），
        # 避免覆盖用户在设置页对人设的其他改动。
        try:
            old_defaults = {
                "今天吃什么", "天气吐槽", "刷到的视频", "突然想起你说过的事",
                "学校里遇到的小事", "奶茶店的客人", "单纯想你了", "尬聊（问在干嘛）",
                "抱怨作业/考试", "深夜情绪", "室友/店里/学校的事",
            }
            new_topics = [
                "今天吃什么（具体到纠结哪一家、哪个菜，别只说\"吃啥\"）",
                "天气吐槽",
                "刷到的视频",
                "刷到一个热梗，想讲给他听（挑当下流行的，自己觉得真好笑的）",
                "突然想起你说过的事",
                "学校里遇到的奇葩小事",
                "奶茶店的客人",
                "单纯想你了",
                "室友/店里/学校的事",
                "抱怨作业/考试",
                "深夜情绪",
                "食堂或外卖踩雷/挖到宝",
                "看到一个好笑的东西，想立刻发给他",
                "做了一个奇怪的梦",
                "周末想拉他干点什么",
                "今日份碎碎念（没有主题的废话也行）",
            ]
            proactive_cfg = app.config.persona.setdefault("proactive", {})
            current = [str(t) for t in (proactive_cfg.get("topics") or [])]
            if not current or set(current) <= old_defaults:
                proactive_cfg["topics"] = new_topics
                log.info("主动话题库已焕新：%d 条", len(new_topics))
        except Exception:  # noqa: BLE001
            log.exception("主动话题库焕新失败")
        # 一次性清掉其他社会角色发的动态及它们的赞/评论；我的历史动态保留
        try:
            purge_marker = "mobile_social_purge_v1"
            if not app.store.get_state(purge_marker):
                result = app.store.purge_social_posts()
                app.store.set_state(purge_marker, app.clock.now().strftime("%Y-%m-%d"))
                log.info("手机端已清除其他角色动态：%s 条", (result or {}).get("posts", 0))
        except Exception:  # noqa: BLE001
            log.exception("清除其他角色动态失败")
        try:
            marker = "mobile_local_init_v1"
            if app.store.get_state(marker):
                return
            today = app.clock.now().strftime("%Y-%m-%d")
            for key in ("last_learning_date", "last_selfhood_date", "last_practice_date"):
                if str(app.store.get_state(key) or "") == today:
                    app.store.set_state(key, "")
            app.store.set_state(marker, today)
            log.info("手机端首次本地初始化：已清除电脑端的今日完成标记")
        except Exception:  # noqa: BLE001
            log.exception("手机端本地初始化失败")

    def stop_engine(self) -> None:
        if self.engine is not None:
            try:
                self.engine.shutdown()
            except Exception:  # noqa: BLE001
                pass
            self.engine = None

    # ------------------------------------------------------------------
    def status(self) -> dict:
        engine = self.engine
        app = getattr(engine, "app", None) if engine else None
        model = ""
        if app is not None:
            model = str(getattr(app.llm, "model", "") or "")
        return {
            "ready": engine is not None and app is not None,
            "starting": self.starting,
            "needs_key": self.needs_key(),
            "status": self.bridge.last_status,
            "error": self.error,
            "model": model,
        }

    def _write_key(self, key: str) -> None:
        key = str(key or "").strip()
        if not key:
            raise ValueError("API Key 不能为空")
        env_path = self.root / ".env"
        lines = []
        if env_path.exists():
            for raw in env_path.read_text(encoding="utf-8").splitlines():
                if raw.strip().startswith("DEEPSEEK_API_KEY="):
                    continue
                lines.append(raw)
        lines.append(f"DEEPSEEK_API_KEY={key}")
        env_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        os.environ["DEEPSEEK_API_KEY"] = key

    def save_key(self, key: str, model: str = "") -> None:
        self._write_key(key)
        self.load()
        if model:
            self.config.settings.setdefault("llm", {})["model"] = model
        self.start_engine()

    def set_model(self, model: str) -> str:
        app = getattr(self.engine, "app", None) if self.engine else None
        if app is None:
            return ""
        if app.llm.set_model(model):
            app.store.set_state("llm_model", model)
            return model
        return ""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    runtime: MobileRuntime | None = None

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        log.debug("HTTP %s", fmt % args)

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _raw(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return b""
        return self.rfile.read(length)

    # ------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        rt = self.runtime
        assert rt is not None
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/desktop/theme":
            theme = "sakura"
            if DESKTOP_HOOKS is not None:
                try:
                    theme = str(DESKTOP_HOOKS["theme"]())
                except Exception:  # noqa: BLE001
                    pass
            self._json({"theme": theme})
            return
        if path == "/" or path == "/index.html":
            html = rt.web_root / "index.html"
            if not html.exists():
                self._send(500, b"web/index.html missing", "text/plain; charset=utf-8")
                return
            text = html.read_text(encoding="utf-8")
            if SPLASH_HOST is not None:
                try:
                    text = SPLASH_HOST.inject(text)
                except Exception:  # noqa: BLE001
                    pass
            self._send(200, text.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path.startswith("/dsh-startup/") and SPLASH_HOST is not None:
            name = path[len("/dsh-startup/"):]
            if name in ("splash.css", "splash.js", "asset-data.js"):
                asset = SPLASH_HOST.asset_dir() / name
                if asset.exists():
                    ctype = (
                        "text/css; charset=utf-8"
                        if name.endswith(".css")
                        else "application/javascript; charset=utf-8"
                    )
                    self._send(200, asset.read_bytes(), ctype)
                else:
                    self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            if name == "config":
                self._json(
                    {
                        "ok": True,
                        "version": "1.5.2",
                        "config": SPLASH_HOST.read_config(),
                        "defaults": SPLASH_HOST.DEFAULTS,
                        "file": str(SPLASH_HOST.config_path),
                    }
                )
                return
        if path == "/whale_girl.png":
            self._serve_file(rt.web_root / "whale_girl.png")
            return
        if path == "/whale_smile.png":
            self._serve_file(rt.web_root / "whale_smile.png")
            return
        if path == "/whale_silhouette.png":
            self._serve_file(rt.web_root / "whale_silhouette.png")
            return
        if path == "/app_icon.png":
            self._serve_file(rt.web_root / "app_icon.png")
            return
        if path in (
            "/nav_whale_chat.png",
            "/nav_whale_moments.png",
            "/nav_whale_world.png",
            "/nav_whale_tool.png",
            "/nav_whale_api.png",
            "/nav_whale_settings.png",
        ):
            self._serve_file(rt.web_root / path.lstrip("/"))
            return
        if (path == "/cities.js" or path.startswith("/vendor/")
                or path.startswith("/dsh/") or path.startswith("/desktop/")
                or path.startswith("/whale/") or path.startswith("/food/")
                or path.startswith("/home/")):
            base = rt.web_root.resolve()
            target = (base / unquote(path).lstrip("/")).resolve()
            if base in target.parents and target.is_file():
                self._serve_file(target)
            else:
                self._send(404, b"missing", "text/plain; charset=utf-8")
            return
        if path == "/whale.html":
            page = rt.web_root / "whale.html"
            if not page.exists():
                self._send(404, b"whale.html missing", "text/plain; charset=utf-8")
                return
            self._send(200, page.read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/memory.html":
            page = rt.web_root / "memory.html"
            if not page.exists():
                self._send(404, b"memory.html missing", "text/plain; charset=utf-8")
                return
            self._send(200, page.read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/api/stickers":
            self._json({"items": rt.stickers()})
            return
        if path == "/api/sticker_search":
            query = unquote(parse_qs(parsed.query).get("q", [""])[0] or "")
            self._json(rt.search_stickers_online(query))
            return
        if path == "/api/tool/history":
            self._json(rt.toolfish_history())
            return
        if path == "/api/profile":
            self._json(rt.profile())
            return
        if path == "/api/wallet":
            store = getattr(getattr(rt.engine, "app", None), "store", None) if rt.engine else None
            if store is None:
                self._json({"ok": True, "out": 0, "in": 0})
                return
            out_total = float(store.get_state("wallet_out_total", 0) or 0)
            in_total = float(store.get_state("wallet_in_total", 0) or 0)
            self._json({"ok": True, "out": round(out_total, 2), "in": round(in_total, 2)})
            return
        if path == "/api/config":
            self._json(rt.config_payload())
            return
        if path == "/api/viz":
            self._json(rt.viz())
            return
        if path == "/api/world":
            self._json(rt.world())
            return
        if path == "/api/feed":
            qs = parse_qs(parsed.query)
            limit = int(qs.get("limit", ["30"])[0] or 30)
            before = float(qs.get("before", ["0"])[0] or 0)
            self._json(rt.feed(limit, before))
            return
        if path == "/api/notifications":
            self._json(rt.notifications())
            return
        if path == "/api/health":
            self._json(rt.health())
            return
        if path == "/api/history":
            qs = parse_qs(parsed.query)
            limit = int(qs.get("limit", ["60"])[0] or 60)
            before = int(qs.get("before", ["0"])[0] or 0)
            around = int(qs.get("around", ["0"])[0] or 0)
            keyword = (qs.get("q", [""])[0] or "").strip()
            paged = bool(int(qs.get("paged", ["0"])[0] or 0))
            kind = (qs.get("kind", [""])[0] or "").strip()
            day = (qs.get("day", [""])[0] or "").strip()
            self._json(rt.history(limit, before=before, around=around, q=keyword, paged=paged, kind=kind, day=day))
            return
        if path == "/api/whale/history":
            limit = int(parse_qs(parsed.query).get("limit", ["40"])[0] or 40)
            self._json(rt.whale_history(limit))
            return
        if path == "/api/whale/brain/status":
            self._json(rt.whale_brain_status())
            return
        if path == "/api/whale/settings":
            self._json(rt.whale_settings())
            return
        if path == "/api/memory/full":
            self._json(rt.full_memory_status())
            return
        if path == "/api/proactive":
            qs = parse_qs(parsed.query)
            self._json(rt.proactive_items(
                float(qs.get("since", ["0"])[0] or 0),
                int(qs.get("limit", ["20"])[0] or 20),
            ))
            return
        if path == "/api/whale/brain/persona":
            self._json(rt.whale_brain_persona())
            return
        if path == "/api/memory/extract/download":
            name = Path(unquote(parse_qs(parsed.query).get("name", [""])[0] or "")).name
            if not name.startswith("BrainTruth-memory-") or not name.endswith(".zip"):
                self._send(403, b"forbidden", "text/plain; charset=utf-8")
                return
            target = rt.full_memory_dir() / "exports" / name
            self._serve_file(target)
            return
        if path == "/api/memory/export":
            data = rt.memory_export()
            if not data.get("ok"):
                self._json(data)
                return
            payload = json.dumps(data["data"], ensure_ascii=False, indent=1).encode("utf-8")
            name = "brainn-memories-" + time.strftime("%Y%m%d-%H%M%S") + ".json"
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=\"" + name + "\"")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return
        if path == "/api/memory/graph":
            limit = int(parse_qs(parsed.query).get("limit", ["80"])[0] or 80)
            self._json(rt.memory_graph(limit))
            return
        if path == "/api/qt/modules":
            self._json(rt.qt_modules())
            return
        if path == "/api/qt/ledger":
            qs = parse_qs(parsed.query)
            self._json(rt.qt_ledger(
                str(qs.get("table", ["qt_refractions"])[0] or "qt_refractions"),
                int(qs.get("limit", ["20"])[0] or 20),
            ))
            return
        if path == "/api/qt/metrics":
            self._json(rt.qt_metrics())
            return
        if path == "/api/memory/list":
            qs = parse_qs(parsed.query)
            self._json(rt.memory_list(
                str(qs.get("q", [""])[0] or ""),
                str(qs.get("status", [""])[0] or ""),
                int(qs.get("limit", ["60"])[0] or 60),
            ))
            return
        if path == "/api/memory/links":
            try:
                mid = int(parse_qs(parsed.query).get("id", ["0"])[0] or 0)
            except ValueError:
                mid = 0
            self._json(rt.memory_related(mid))
            return
        if path == "/api/balance":
            self._json(rt.api_balance())
            return
        if path == "/api/food/shops":
            self._json(rt.food_shops())
            return
        if path == "/api/food/suggest":
            self._json(rt.food_suggest())
            return
        if path == "/api/food/orders":
            self._json(rt.food_orders())
            return
        if path == "/api/mall/goods":
            self._json(rt.mall_goods())
            return
        if path == "/api/mall/orders":
            self._json(rt.mall_orders())
            return
        if path == "/api/shorts/list":
            self._json(rt.shorts_list())
            return
        if path == "/api/shorts/comments":
            sid = str(parse_qs(parsed.query).get("id", [""])[0] or "")
            self._json(rt.shorts_comments(sid))
            return
        if path == "/api/screen":
            self._json(rt.screen_info())
            return
        if path == "/api/api":
            self._json(rt.apikey_info())
            return
        if path == "/api/persona/chat":
            self._json(rt.persona_chat_state())
            return
        if path == "/api/persona/rebuild":
            self._json(rt.persona_rebuild_status())
            return
        if path == "/api/events":
            since = int(parse_qs(parsed.query).get("since", ["0"])[0] or 0)
            self._json(rt.bridge.snapshot(since))
            return
        if path == "/api/status":
            self._json(rt.status())
            return
        if path == "/api/models":
            cfg = (rt.config.settings.get("llm", {}) if rt.config else {}) or {}
            self._json({"models": cfg.get("models", {}), "current": rt.status().get("model")})
            return
        if path == "/media":
            target = unquote(parse_qs(parsed.query).get("path", [""])[0] or "")
            self._serve_file(Path(target))
            return
        if path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        rt = self.runtime
        assert rt is not None
        path = urlparse(self.path).path
        if path == "/dsh-startup/config" and SPLASH_HOST is not None:
            body = self._body()
            if body.get("action") == "reset":
                config = SPLASH_HOST.reset_config()
            else:
                patch = body.get("patch") if isinstance(body.get("patch"), dict) else body
                config = SPLASH_HOST.save_config(patch)
            self._json({"ok": True, "version": "1.5.2", "config": config})
            return
        if path.startswith("/api/desktop/"):
            if DESKTOP_HOOKS is None:
                self._json({"ok": False, "error": "desktop_off"}, 404)
                return
            if self.headers.get("X-BrainN-Token", "") != DESKTOP_TOKEN:
                self._json({"ok": False, "error": "forbidden"}, 403)
                return
            body = self._body()
            if path == "/api/desktop/pet/hide":
                DESKTOP_HOOKS["pet_hide"]()
            elif path == "/api/desktop/pet/show-main":
                DESKTOP_HOOKS["show_main"]()
            elif path == "/api/desktop/pet/settings":
                DESKTOP_HOOKS["settings"]()
            elif path == "/api/desktop/pet/pos":
                DESKTOP_HOOKS["pet_pos"](
                    int(body.get("x") or 0), int(body.get("y") or 0)
                )
            elif path == "/api/desktop/quit":
                DESKTOP_HOOKS["quit"]()
            else:
                self._json({"ok": False, "error": "unknown"}, 404)
                return
            self._json({"ok": True})
            return
        try:
            if path in ("/api/profile/avatar", "/api/her/avatar"):
                raw = self._raw()
                if len(raw) > 8 * 1024 * 1024:
                    self._json({"ok": False, "error": "too_large"}, 400)
                    return
                profile = rt.save_avatar(raw, "her" if path.startswith("/api/her") else "me")
                self._json({"ok": True, "profile": profile})
                return
            if path == "/api/cover":
                raw = self._raw()
                if len(raw) > 12 * 1024 * 1024:
                    self._json({"ok": False, "error": "too_large"}, 400)
                    return
                profile = rt.save_cover(raw)
                self._json({"ok": True, "profile": profile})
                return
            if path == "/api/chatbg":
                raw = self._raw()
                if len(raw) > 12 * 1024 * 1024:
                    self._json({"ok": False, "error": "too_large"}, 400)
                    return
                profile = rt.save_chat_bg(raw)
                self._json({"ok": True, "profile": profile})
                return
            if path == "/api/chatbg/clear":
                self._json({"ok": True, "profile": rt.clear_chat_bg()})
                return
            if path == "/api/food/order":
                self._json(rt.food_order_create(self._body()))
                return
            if path == "/api/food/cancel":
                payload = self._body()
                self._json(rt.food_order_cancel(int(payload.get("id") or 0)))
                return
            if path == "/api/mall/order":
                self._json(rt.mall_order_create(self._body()))
                return
            if path == "/api/mall/cancel":
                payload = self._body()
                self._json(rt.mall_order_cancel(int(payload.get("id") or 0)))
                return
            if path == "/api/shorts/comment":
                self._json(rt.shorts_comment_create(self._body()))
                return
            if path == "/api/shorts/watch":
                self._json(rt.shorts_watch(self._body()))
                return
            if path == "/api/dynamic/image":
                raw = self._raw()
                if len(raw) > 12 * 1024 * 1024:
                    self._json({"ok": False, "error": "too_large"}, 400)
                    return
                saved = rt.save_user_photo(raw)
                self._json(
                    {
                        "ok": True,
                        "path": str(saved.resolve()),
                        "url": rt._media_url(saved),
                    }
                )
                return
            if path == "/api/tool/upload":
                raw = self._raw()
                if len(raw) > 12 * 1024 * 1024:
                    self._json({"ok": False, "error": "too_large"}, 400)
                    return
                name = unquote(parse_qs(urlparse(self.path).query).get("name", ["file"])[0] or "file")
                self._json(rt.save_tool_file(raw, name))
                return
            if path == "/api/sticker/import":
                raw = self._raw()
                if len(raw) > 12 * 1024 * 1024:
                    self._json({"ok": False, "error": "too_large"}, 400)
                    return
                name = unquote(
                    parse_qs(urlparse(self.path).query).get("name", ["sticker.gif"])[0]
                    or "sticker.gif"
                )
                self._json(rt.save_sticker(raw, name))
                return
            if path == "/api/send_image":
                raw = self._raw()
                if len(raw) > 12 * 1024 * 1024:
                    self._json({"ok": False, "error": "too_large"}, 400)
                    return
                if rt.engine is None:
                    self._json({"ok": False, "error": "not_ready"}, 409)
                    return
                saved = rt.save_user_photo(raw)
                url = f"http://127.0.0.1:{PORT}/media?path={quote(str(saved.resolve()))}"
                rt.engine.user_send_image(str(saved.resolve()), url)
                self._json({"ok": True, "url": rt._media_url(saved)})
                return
        except ValueError as exc:
            self._json({"ok": False, "error": str(exc)}, 400)
            return
        except Exception:
            log.error("图片上传失败\n%s", traceback.format_exc())
            self._json({"ok": False, "error": "server_error"}, 500)
            return
        body = self._body()
        try:
            if path == "/api/world/start":
                self._json(rt.world_start())
                return
            if path == "/api/world/frame":
                self._json(rt.world_frame(body))
                return
            if path == "/api/world/stop":
                self._json(rt.world_stop(body))
                return
            if path == "/api/minimax/balance":
                self._json(rt.minimax_balance(body))
                return
            if path == "/api/world/places":
                self._json(rt.world_places())
                return
            if path == "/api/whale/brain/start":
                self._json(rt.whale_brain_start())
                return
            if path == "/api/whale/brain/stop":
                self._json(rt.whale_brain_stop())
                return
            if path == "/api/whale/brain/restart":
                self._json(rt.whale_brain_restart())
                return
            if path == "/api/whale/brain/persona":
                self._json(rt.whale_brain_save_persona(body))
                return
            if path == "/api/whale/settings":
                self._json(rt.save_whale_settings(body))
                return
            if path == "/api/memory/update":
                self._json(rt.memory_update(body))
                return
            if path == "/api/memory/delete":
                self._json(rt.memory_delete(body))
                return
            if path == "/api/memory/rebuild":
                self._json(rt.memory_rebuild())
                return
            if path == "/api/memory/import":
                self._json(rt.memory_import(body))
                return
            if path == "/api/memory/full":
                self._json(rt.set_full_memory(
                    bool(body.get("on", True)), body.get("dir")
                ))
                return
            if path == "/api/memory/extract":
                self._json(rt.memory_extract())
                return
            if path == "/api/memory/probe":
                self._json(rt.run_memory_probe())
                return
            if path == "/api/qt/confirm":
                self._json(rt.qt_confirm_m14(body))
                return
            if path == "/api/whale/say":
                role = "user" if str(body.get("role") or "me") == "me" else "assistant"
                rt.whale_say(
                    role,
                    str(body.get("text") or "").strip(),
                    str(body.get("kind") or "text"),
                    str(body.get("media") or ""),
                )
                self._json({"ok": True})
                return
            if path == "/api/whale/chat":
                # 小鲸鱼专属通道：智能开关开启时才被前端调用；与聊天 AI 完全隔离。
                text = str(body.get("text") or "").strip()[:200]
                if not text:
                    self._json({"ok": False, "error": "empty"}, 400)
                    return
                history = body.get("history") if isinstance(body.get("history"), list) else []
                self._json(rt.whale_chat(text, history[-8:], str(body.get("session") or "")))
                return
            if path == "/api/send":
                text = str(body.get("text") or "").strip()
                if not text:
                    self._json({"ok": False, "error": "empty"}, 400)
                    return
                if rt.engine is None:
                    self._json({"ok": False, "error": "not_ready", "status": rt.status()}, 409)
                    return
                rt.engine.user_send(
                    text,
                    str(body.get("quote") or ""),
                    str(body.get("quote_image") or ""),
                )
                self._json({"ok": True})
                return
            if path == "/api/send_sticker":
                target = Path(str(body.get("path") or ""))
                roots = [
                    (rt.root / "assets" / "stickers").resolve(),
                    (rt.root / "profile" / "sticker_cache").resolve(),
                ]
                resolved = target.resolve()
                if not any(base in resolved.parents for base in roots) or not resolved.is_file():
                    self._json({"ok": False, "error": "bad_path"}, 400)
                    return
                if rt.engine is None:
                    self._json({"ok": False, "error": "not_ready"}, 409)
                    return
                tag = str(body.get("tag") or "custom")
                rt.engine.user_send_sticker(tag, str(resolved))
                self._json({"ok": True})
                return
            if path == "/api/transfer":
                store = getattr(getattr(rt.engine, "app", None), "store", None) if rt.engine else None
                if store is None:
                    self._json({"ok": False, "error": "not_ready"}, 409)
                    return
                try:
                    amount = round(float(body.get("amount") or 0), 2)
                except (TypeError, ValueError):
                    amount = 0
                note = str(body.get("note") or "").strip()[:20]
                if amount <= 0 or amount > 2000:
                    self._json({"ok": False, "error": "amount"}, 400)
                    return
                meta = {
                    "amount": amount, "note": note or "转账",
                    "status": "pending", "dir": "out", "ts": time.time(),
                }
                mid = store.add_message(
                    "user", f"转账 ¥{amount:.2f}", kind="transfer",
                    media=json.dumps(meta, ensure_ascii=False), ts=meta["ts"],
                )
                total = float(store.get_state("wallet_out_total", 0) or 0) + amount
                store.set_state("wallet_out_total", round(total, 2))
                self._json({"ok": True, "id": mid, "meta": meta})
                return
            if path == "/api/transfer/receive":
                store = getattr(getattr(rt.engine, "app", None), "store", None) if rt.engine else None
                if store is None:
                    self._json({"ok": False, "error": "not_ready"}, 409)
                    return
                try:
                    mid = int(body.get("id") or 0)
                except (TypeError, ValueError):
                    mid = 0
                row = store.get_message(mid) if mid else None
                if not row or row.get("kind") != "transfer":
                    self._json({"ok": False, "error": "not_found"}, 404)
                    return
                try:
                    meta = json.loads(row.get("media") or "{}")
                except Exception:
                    meta = {}
                if meta.get("status") != "pending":
                    self._json({"ok": True, "reply": "", "back": None})
                    return
                amount = float(meta.get("amount") or 0)
                note = str(meta.get("note") or "转账")
                meta["status"] = "accepted"
                store.update_message_media(mid, json.dumps(meta, ensure_ascii=False))
                if amount >= 100:
                    reply = "收到啦……这么多，我会好好收着的，不会乱花。"
                elif "奶茶" in note or "喝" in note:
                    reply = "收到啦！我这就去买奶茶，晚上回来跟你说谢谢。"
                else:
                    reply = "收到啦，谢谢你，我记着了。"
                reply_ts = time.time() + 0.4
                store.add_message("assistant", reply, ts=reply_ts)
                back = None
                if amount >= 5 and random.random() < 0.35:
                    bamount = round(min(20.0, max(3.0, amount * 0.4)), 2)
                    bmeta = {
                        "amount": bamount, "note": "请你喝奶茶", "status": "accepted",
                        "dir": "in", "ts": reply_ts + 1.2,
                    }
                    store.add_message(
                        "assistant", f"转账 ¥{bamount:.2f}", kind="transfer",
                        media=json.dumps(bmeta, ensure_ascii=False), ts=bmeta["ts"],
                    )
                    btotal = float(store.get_state("wallet_in_total", 0) or 0) + bamount
                    store.set_state("wallet_in_total", round(btotal, 2))
                    back = bmeta
                self._json({"ok": True, "reply": reply, "back": back})
                return
            if path == "/api/recall":
                content = str(body.get("content") or "")
                ts = float(body.get("ts") or time.time())
                if rt.engine is None:
                    self._json({"ok": False, "error": "not_ready"}, 409)
                    return
                deleted = rt.engine.recall(content, ts)
                self._json({"ok": True, "deleted": bool(deleted)})
                return
            if path == "/api/profile":
                profile = rt.save_profile(
                    str(body.get("nickname") or ""),
                    str(body.get("signature") or ""),
                    str(body.get("her_name") or ""),
                )
                self._json({"ok": True, "profile": profile})
                return
            if path == "/api/setup":
                rt.save_key(str(body.get("key") or ""), str(body.get("model") or ""))
                self._json({"ok": True, "status": rt.status()})
                return
            if path == "/api/config":
                rt.save_config(
                    body.get("settings") or {},
                    body.get("persona") or {},
                )
                restart = bool(body.get("restart", True))
                if restart:
                    threading.Thread(target=rt.restart_engine, daemon=True).start()
                self._json({"ok": True, "restarting": restart})
                return
            if path == "/api/config/reset":
                rt.reset_config()
                if bool(body.get("restart", True)):
                    threading.Thread(target=rt.restart_engine, daemon=True).start()
                self._json({"ok": True})
                return
            if path == "/api/persona/knobs":
                knobs = rt.set_knobs(body.get("knobs") or {})
                self._json({"ok": True, "knobs": knobs})
                return
            if path == "/api/api":
                result = rt.save_api(
                    str(body.get("key") or ""),
                    str(body.get("model") or ""),
                    str(body.get("base_url") or ""),
                    str(body.get("vision_model") or ""),
                )
                self._json(result)
                return
            if path == "/api/api/test":
                self._json(
                    rt.api_test(
                        str(body.get("key") or ""),
                        str(body.get("base_url") or ""),
                        str(body.get("model") or ""),
                        str(body.get("vision_model") or ""),
                    )
                )
                return
            if path == "/api/persona/chat":
                self._json(rt.persona_chat(str(body.get("message") or "")))
                return
            if path == "/api/persona/draft/clear":
                self._json(rt.persona_draft_clear())
                return
            if path == "/api/world/city":
                self._json(
                    rt.world_city(
                        str(body.get("city") or ""),
                        body.get("lat"),
                        body.get("lon"),
                    )
                )
                return
            if path == "/api/world/locate":
                self._json(
                    rt.world_locate(body.get("lat"), body.get("lon"))
                )
                return
            if path == "/api/world/visit":
                self._json(rt.world_visit(str(body.get("place") or "")))
                return
            if path == "/api/persona/apply":
                self._json(
                    rt.persona_apply(
                        bool(body.get("rebuild", True)),
                        bool(body.get("reset_social", False)),
                    )
                )
                return
            if path == "/api/model":
                model = rt.set_model(str(body.get("model") or ""))
                self._json({"ok": bool(model), "model": model})
                return
            if path == "/api/tool/chat":
                result = rt.toolfish_chat(
                    str(body.get("text") or ""),
                    body.get("attachments") or [],
                )
                self._json(result)
                return
            if path == "/api/tool/clear":
                self._json(rt.toolfish_clear())
                return
            if path == "/api/dynamic":
                text = str(body.get("text") or "").strip()
                raw_images = body.get("images") or []
                upload_base = (rt.root / "profile" / "uploads").resolve()
                images = []
                for raw in raw_images if isinstance(raw_images, list) else []:
                    item = Path(str(raw)).resolve()
                    if upload_base in item.parents and item.is_file() and len(images) < 3:
                        images.append(str(item))
                if not text and not images:
                    self._json({"ok": False, "error": "empty"}, 400)
                    return
                app = getattr(rt.engine, "app", None) if rt.engine else None
                if app is None:
                    self._json({"ok": False, "error": "not_ready"}, 409)
                    return
                dynamic_id = app.store.add_dynamic(text, "", "app", images, author="user")
                # 写库成功就先返回成功；点赞/评论生成放后台，避免后置动作异常被误报为“发布失败”
                self._json({"ok": True, "id": dynamic_id})
                if dynamic_id:
                    def _after_post() -> None:
                        try:
                            rt._ensure_reactions(
                                app, f"dyn:{dynamic_id}", "user", time.time(), False
                            )
                            rt._queue_npc_comments(
                                app, f"dyn:{dynamic_id}", "user", text or "[图片]"
                            )
                        except Exception:  # noqa: BLE001
                            log.exception("动态后置互动失败（动态已发布）")

                    threading.Thread(target=_after_post, daemon=True).start()
                return
            if path == "/api/dynamic/delete":
                raw_target = str(body.get("target") or body.get("id") or "")
                target = raw_target.split(":")[-1] if raw_target.startswith("dyn:") else raw_target
                try:
                    dynamic_id = int(target)
                except (TypeError, ValueError):
                    self._json({"ok": False, "error": "bad_id"}, 400)
                    return
                app = getattr(rt.engine, "app", None) if rt.engine else None
                if app is None:
                    self._json({"ok": False, "error": "not_ready"}, 409)
                    return
                self._json({"ok": app.store.delete_dynamic(dynamic_id, "user")})
                return
            if path == "/api/post/like":
                target = str(body.get("target") or "").strip()
                if not target:
                    self._json({"ok": False, "error": "empty_target"}, 400)
                    return
                liked = rt.toggle_post_like(target)
                self._json({"ok": True, "liked": liked})
                return
            if path == "/api/post/comment":
                target = str(body.get("target") or "").strip()
                text = str(body.get("text") or "").strip()
                if not target or not text:
                    self._json({"ok": False, "error": "empty"}, 400)
                    return
                self._json(rt.add_post_comment(target, text, int(body.get("parent_id") or 0)))
                return
            if path == "/api/post/comment/delete":
                try:
                    comment_id = int(body.get("id") or 0)
                except (TypeError, ValueError):
                    comment_id = 0
                app = getattr(rt.engine, "app", None) if rt.engine else None
                if app is None or comment_id <= 0:
                    self._json({"ok": False, "error": "not_ready"}, 409)
                    return
                self._json({"ok": app.store.delete_post_comment(comment_id, "user")})
                return
            if path == "/api/restart":
                rt.stop_engine()
                threading.Thread(target=rt.start_engine, daemon=True).start()
                self._json({"ok": True})
                return
        except ValueError as exc:
            self._json({"ok": False, "error": str(exc)}, 400)
            return
        except Exception:
            log.error("接口异常\n%s", traceback.format_exc())
            self._json({"ok": False, "error": "server_error"}, 500)
            return
        self._json({"error": "not found"}, 404)

    def _serve_file(self, target: Path) -> None:
        rt = self.runtime
        assert rt is not None
        try:
            resolved = Path(os.path.realpath(target))
            # 允许的根：运行目录、网页目录、数据目录、表情目录。
            # 桌面版的数据目录在 %LOCALAPPDATA%，网页目录指向源码 mobile/web，
            # 所以这里按 realpath 逐个比对，既支持目录联接也不放开任意路径。
            bases = [rt.root, rt.web_root]
            try:
                if rt.config is not None:
                    bases.append(rt.config.data_dir)
                    bases.append(rt.config.sticker_dir)
            except Exception:  # noqa: BLE001
                pass
            allowed = [Path(os.path.realpath(b)) for b in bases]
            if not any(b in resolved.parents or resolved == b for b in allowed):
                self._send(403, b"forbidden", "text/plain; charset=utf-8")
                return
            if not resolved.is_file():
                self._send(404, b"missing", "text/plain; charset=utf-8")
                return
            suffix = resolved.suffix.lower()
            ctype = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".webp": "image/webp",
                ".mp4": "video/mp4",
                ".webm": "video/webm",
                ".wav": "audio/wav",
                ".mp3": "audio/mpeg",
                ".m4a": "audio/mp4",
                ".html": "text/html; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".svg": "image/svg+xml",
                ".woff2": "font/woff2",
                ".ttf": "font/ttf",
            }.get(suffix, "application/octet-stream")
            self._send(200, resolved.read_bytes(), ctype)
        except Exception:  # noqa: BLE001
            self._send(404, b"missing", "text/plain; charset=utf-8")


def start(root_path: str) -> dict:
    """Android 服务调用：初始化目录、HTTP 服务，再异步启动大脑。"""
    global ROOT, _STARTED
    if _STARTED:
        log.info("手机端服务已在运行，忽略重复启动")
        return {"port": PORT, "already": True}
    _STARTED = True
    ROOT = Path(str(root_path)).resolve()
    os.environ["BRAINN_ROOT"] = str(ROOT)
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(ROOT / "logs" / "brainn.log", encoding="utf-8")],
        force=True,
    )
    runtime = MobileRuntime(ROOT)
    try:
        runtime.load()
    except Exception:
        _STARTED = False
        log.error("配置加载失败\n%s", traceback.format_exc())
        raise
    Handler.runtime = runtime
    runtime.bridge.show_system("（小鲸鱼手机版启动中）")

    def _serve() -> None:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
        server.daemon_threads = True
        log.info("手机端 HTTP 服务：http://127.0.0.1:%d", PORT)
        server.serve_forever()

    threading.Thread(target=_serve, name="brainn-http", daemon=True).start()
    time.sleep(0.2)
    runtime._start_screen_loop()
    if not runtime.needs_key():
        runtime.start_engine()
    return {"port": PORT, "needs_key": runtime.needs_key()}


def shutdown() -> None:
    if Handler.runtime is not None:
        Handler.runtime.stop_engine()
