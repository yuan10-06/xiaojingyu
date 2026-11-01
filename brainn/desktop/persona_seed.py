"""新用户首次启动时生成随机初始人设。

只改表层信息（学校、专业、城市、爱好、兼职），核心设定（名字、年龄、
鲸鱼娘身份、核心性格、说话方式、关系、禁忌）完全不动。
生成结果写进 config/persona_overrides.yaml 和 config/settings_overrides.yaml，
以后用户可以在设置页自己改；种子存在数据目录，升级/重启不会重随机。
"""
from __future__ import annotations

import json
import logging
import os
import random
import secrets
import time
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

VERSION = 1
MARKER_NAME = "persona_seed.json"

# 城市 / 省份 / 学校：学校放在城市里，保证“城市”和“学校”不是互相打架的
CITIES: list[dict] = [
    {
        "city": "郑州", "province": "河南",
        "schools": [
            "郑州大学", "河南财经政法大学", "华北水利水电大学", "河南工业大学",
            "郑州轻工业大学", "郑州航空工业管理学院", "河南农业大学", "河南中医药大学",
        ],
    },
    {
        "city": "开封", "province": "河南",
        "schools": ["河南大学", "河南开封科技传媒学院"],
    },
    {
        "city": "洛阳", "province": "河南",
        "schools": ["河南科技大学", "洛阳师范学院", "洛阳理工学院"],
    },
    {
        "city": "新乡", "province": "河南",
        "schools": ["河南师范大学", "新乡医学院", "河南科技学院"],
    },
    {
        "city": "南阳", "province": "河南",
        "schools": ["南阳师范学院", "南阳理工学院"],
    },
    {
        "city": "信阳", "province": "河南",
        "schools": ["信阳师范大学", "信阳农林学院"],
    },
    {
        "city": "许昌", "province": "河南",
        "schools": ["许昌学院"],
    },
    {
        "city": "驻马店", "province": "河南",
        "schools": ["黄淮学院"],
    },
    {
        "city": "安阳", "province": "河南",
        "schools": ["安阳师范学院"],
    },
    {
        "city": "焦作", "province": "河南",
        "schools": ["河南理工大学"],
    },
    {
        "city": "平顶山", "province": "河南",
        "schools": ["河南城建学院", "平顶山学院"],
    },
    {
        "city": "商丘", "province": "河南",
        "schools": ["商丘师范学院"],
    },
    {
        "city": "周口", "province": "河南",
        "schools": ["周口师范学院"],
    },
    {
        "city": "北京", "province": "北京",
        "schools": ["中国人民大学", "北京师范大学", "北京外国语大学", "中央财经大学", "中国传媒大学"],
    },
    {
        "city": "上海", "province": "上海",
        "schools": ["上海财经大学", "华东师范大学", "上海大学", "东华大学"],
    },
    {
        "city": "武汉", "province": "湖北",
        "schools": ["武汉大学", "华中师范大学", "中南财经政法大学", "武汉理工大学"],
    },
    {
        "city": "西安", "province": "陕西",
        "schools": ["陕西师范大学", "西北大学", "西安外国语大学", "长安大学"],
    },
    {
        "city": "南京", "province": "江苏",
        "schools": ["南京大学", "南京师范大学", "南京财经大学", "南京审计大学"],
    },
    {
        "city": "成都", "province": "四川",
        "schools": ["四川大学", "西南财经大学", "四川师范大学"],
    },
    {
        "city": "杭州", "province": "浙江",
        "schools": ["浙江财经大学", "浙江工商大学", "杭州师范大学"],
    },
    {
        "city": "广州", "province": "广东",
        "schools": ["中山大学", "华南师范大学", "广东财经大学"],
    },
]

MAJORS = [
    "金融", "会计学", "汉语言文学", "新闻学", "广告学", "法学", "英语", "日语",
    "计算机科学与技术", "软件工程", "电子信息工程", "心理学", "学前教育",
    "小学教育", "护理学", "视觉传达设计", "环境设计", "食品科学与工程",
    "工商管理", "市场营销", "国际经济与贸易", "物流管理", "旅游管理",
    "数学与应用数学", "化学", "生物科学", "地理科学", "历史学",
    "思想政治教育", "体育教育", "音乐学", "美术学",
]

HOBBIES = [
    "拍照", "撸猫", "跑步", "羽毛球", "烘焙", "打游戏", "听歌", "逛超市",
    "拼乐高", "看小说", "画小画", "做手账", "散步", "探店", "看电影",
    "养多肉", "收集贴纸", "看剧", "追综艺", "跳绳", "逛公园",
]

PART_TIMES = [
    "周末在奶茶店兼职",
    "周末在咖啡店兼职",
    "周末在便利店兼职",
    "周末在书店兼职",
    "周末在花店兼职",
    "周末在超市做理货",
    "周末在宠物店帮忙",
    "周末在蛋糕店兼职",
    "周末在快递驿站帮忙",
    "周末做家教",
    "周末在图书馆整理书架",
    "周末在服装店做导购",
]


def _province_for_city(city: str) -> str:
    """种子城市 → 省份；用于人设改了城市后把天气省份一起对齐。"""
    name = str(city or "").strip()
    for place in CITIES:
        if place["city"] == name:
            return place["province"]
    return ""


def _majors_for(school: str) -> list[str]:
    """按学校类型挑专业，避免出现“财经政法大学食品工程”这类明显不搭的组合。"""
    if any(k in school for k in ("财经", "工商", "审计")):
        return ["金融", "会计学", "国际经济与贸易", "市场营销", "工商管理", "物流管理", "旅游管理", "法学"]
    if "政法" in school:
        return ["法学", "思想政治教育", "新闻学", "心理学"]
    if any(k in school for k in ("师范", "师范学院", "师范大学")):
        return [
            "汉语言文学", "英语", "小学教育", "学前教育", "心理学", "数学与应用数学",
            "化学", "生物科学", "地理科学", "历史学", "思想政治教育", "体育教育",
            "音乐学", "美术学", "新闻学", "广告学",
        ]
    if "外国语" in school:
        return ["英语", "日语", "新闻学", "广告学", "国际经济与贸易"]
    if "传媒" in school:
        return ["新闻学", "广告学", "视觉传达设计", "环境设计"]
    if any(k in school for k in ("医科", "医学", "中医药")):
        return ["护理学", "心理学"]
    if any(k in school for k in ("工业", "理工", "科技", "航空", "水利", "邮电", "电子", "轻工", "城建")):
        return [
            "计算机科学与技术", "软件工程", "电子信息工程", "数学与应用数学",
            "化学", "食品科学与工程", "环境设计", "物流管理", "工商管理",
        ]
    if any(k in school for k in ("农业", "农林")):
        return ["食品科学与工程", "生物科学", "环境设计", "市场营销"]
    return MAJORS


def _make_profile(rng: random.Random) -> dict:
    place = rng.choice(CITIES)
    school = rng.choice(place["schools"])
    major = rng.choice(_majors_for(school))
    hobby = rng.choice(HOBBIES)
    part_time = rng.choice(PART_TIMES)
    identity = f"{school}大三{major}专业学生，{part_time}，喜欢{hobby}"
    return {
        "city": place["city"],
        "province": place["province"],
        "school": school,
        "major": major,
        "hobby": hobby,
        "part_time": part_time,
        "identity": identity,
    }


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _merge_weather(cfg_dir: Path, profile: dict, *, force: bool) -> None:
    """把当前人设的城市写进天气覆盖，保证「人格页」和「架构页」同一个城市。

    force=True：人设（种子或用户改过的人设）是城市的唯一来源，直接同步；
    force=False：只在 weather.city 缺失时补，仅用于没有可信人设时的兜底。
    """
    settings_path = cfg_dir / "settings_overrides.yaml"
    data = _load_yaml(settings_path)
    weather = data.get("weather")
    if not isinstance(weather, dict):
        weather = {}
    city = str(profile.get("city") or "").strip()
    if not city:
        return
    if not force and str(weather.get("city") or "").strip():
        return
    old_city = str(weather.get("city") or "").strip()
    weather = dict(weather)
    weather.update(
        {
            "province": profile.get("province") or "",
            "city": city,
        }
    )
    # 城市变了才清坐标，让天气按新城市重新地理编码；同城保留已有经纬度。
    if old_city != city:
        weather["lat"] = None
        weather["lon"] = None
    data["weather"] = weather
    _write_yaml(settings_path, data)


def _write_overrides(cfg_dir: Path, profile: dict, *, settings_mode: str) -> None:
    """写人设覆盖；settings_mode=force/if_missing 时同步天气城市。"""
    _write_yaml(
        cfg_dir / "persona_overrides.yaml",
        {
            "identity": profile["identity"],
            "city": profile["city"],
            "province": profile.get("province") or "",
        },
    )
    if settings_mode in ("force", "if_missing"):
        _merge_weather(cfg_dir, profile, force=(settings_mode == "force"))


def _marker_profile(marker: Path) -> dict | None:
    if not marker.exists():
        return None
    try:
        raw = json.loads(marker.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    profile = raw.get("profile") if isinstance(raw, dict) else None
    if isinstance(profile, dict) and profile.get("identity") and profile.get("city"):
        return profile
    return None


def ensure_initial_persona(root: Path | str, data_dir: Path | str) -> dict | None:
    """首次启动生成一次；已有人设/种子时保持不动。返回本次使用的人设信息。"""
    root = Path(root)
    data_dir = Path(data_dir)
    cfg_dir = root / "config"
    base = cfg_dir / "persona.yaml"
    if not base.exists():
        return None
    overrides = cfg_dir / "persona_overrides.yaml"
    marker = data_dir / MARKER_NAME
    profile = _marker_profile(marker)

    # 用户已经改过人设：人设里的城市就是权威，天气必须跟着它，不能停在旧城市
    if overrides.exists():
        current = _load_yaml(overrides)
        city = str(current.get("city") or "").strip()
        if city:
            _merge_weather(
                cfg_dir,
                {
                    "city": city,
                    "province": _province_for_city(city)
                    or str(current.get("province") or "").strip()
                    or str((profile or {}).get("province") or ""),
                },
                force=True,
            )
        elif profile is not None:
            _merge_weather(cfg_dir, profile, force=True)
        return None

    # 有种子但人设覆盖被删（例如重装/清理）：按原种子恢复，保证人设不变
    if profile is not None:
        _write_overrides(cfg_dir, profile, settings_mode="force")
        log.info("按已存种子恢复初始人设：%s", profile.get("identity"))
        return profile

    # 全新用户：随机生成一套
    seed = secrets.randbits(64)
    rng = random.Random(seed)
    profile = _make_profile(rng)
    _write_overrides(cfg_dir, profile, settings_mode="force")
    data_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "version": VERSION,
                "seed": seed,
                "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                "profile": profile,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    log.info("首次启动生成初始人设：%s（种子 %s）", profile["identity"], seed)
    return profile
