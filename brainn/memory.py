"""记忆：分层记忆网 + 情绪权重 + 间隔回访 + 短期对话窗口。

分层沿用人类记忆法则：
L0 身份主线（一句话）→ L1 生活领域 → L2 关系与人 → L3 关键事件 → L4 偏好与触发点。
每条记忆区分「事实 / 我的解读 / 情绪」，权重 ≈ 情绪强度 × 主线关联度 × 时间衰减。
"""
from __future__ import annotations

import logging
import math
import random
import re
import time
import zlib
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from .affect import VALENCE_BY_LABEL
from .db import Store

log = logging.getLogger(__name__)

# 中文停用词（检索时忽略）
_STOP = set("的了是我你他她它吗呢吧啊哦嗯在就都也很和与这那个什么怎么可以一下一")
# 高频虚词组合：撞上也说明不了相关，检索时直接丢掉
_NOISE = set(
    "自己 我们 你们 他们 什么 怎么 可以 这个 那个 现在 时候 还是 觉得 知道 不是 没有 一个 就是 "
    "因为 所以 但是 如果 然后 已经 开始 起来 出来 下来 一下 有点 真的 其实 这里 那里 这样 那样 "
    "之前 事情 东西 还是 的话".split()
)

# 同义词 / 别名组：查一句“外卖”，也要能撞上“麻辣烫/夜宵/点餐”
_ALIAS_GROUPS = (
    ("外卖", "点餐", "美团", "饿了么", "送餐", "夜宵", "麻辣烫"),
    ("火锅", "海底捞", "番茄锅", "涮锅", "锅底"),
    ("奶茶", "饮品", "蜜雪", "杯奶茶", "喝"),
    ("吃", "饭", "早餐", "早饭", "午饭", "晚饭", "零食", "口味", "饿了"),
    ("睡", "熬夜", "困", "作息", "失眠", "凌晨", "起床", "睡觉"),
    ("家人", "外婆", "妈妈", "爸爸", "奶奶", "爷爷", "家里"),
    ("考试", "体测", "复习", "期中", "期末", "成绩", "测验", "累", "疲劳"),
    ("学习", "课", "上课", "作业", "老师", "自习", "忙", "赶"),
    ("兼职", "打工", "上班", "工资", "奶茶店", "老板"),
    ("头像", "情头", "照片", "换图"),
    ("游戏", "打游戏", "王者", "手游", "开黑"),
    ("朋友", "舍友", "同学", "室友", "闺蜜"),
    ("学校", "学院", "大学", "新乡", "开封", "河南", "校"),
    ("专业", "金融", "数学", "食品", "学科"),
    ("名字", "叫", "称呼", "大名", "小名"),
    ("答应", "请客", "约定", "欠", "承诺", "请我", "什么时候", "找你"),
    ("喜欢", "爱", "爱吃", "爱喝", "偏好"),
    ("讨厌", "不喜欢", "不爱", "不吃", "受不了"),
)

# 检索候选池：全量记忆开启后活跃记忆会持续增长，不能只看最近 400 条
_RECALL_POOL = 2000

# 用户属性的规范键：同一属性只保留最新一条，旧值归档但仍在库里
_CANON_FACTS = (
    (("名字", "叫什么"), "他的名字"),
    (("学校", "学院", "大学", "在哪", "不同校"), "他的学校"),
    (("专业",), "他的专业"),
    (("年龄", "几岁"), "他的年龄"),
    (("老家", "家乡"), "他的老家"),
)

_QUESTION_RE = re.compile(r"(叫什么来着|还记得吗|你猜|是不是|好不好|行不行|吗|呢|？|\?)")

# 轻量查询改写：先判意图，再补该意图的常用词；不调 LLM，不增加 token 成本
_INTENT_RULES = (
    ("identity", ("名字", "叫什么", "称呼", "年龄", "几岁", "生日")),
    ("promise", ("答应", "约定", "什么时候", "请客", "欠", "承诺", "找你")),
    ("school", ("学校", "学院", "大学", "在哪上学", "专业")),
    ("preference", ("喜欢", "爱吃", "爱喝", "不喜欢", "讨厌", "口味")),
    ("tired", ("累", "体测", "疲劳")),
    ("busy", ("忙", "最近在忙", "考试", "作业", "复习")),
    ("family", ("家人", "外婆", "妈妈", "爸爸", "家里")),
    ("food", ("早餐", "早饭", "吃什么", "喝什么", "外卖", "火锅", "奶茶")),
)
_INTENT_HINTS = {
    "identity": ("名字", "叫", "称呼", "年龄", "岁"),
    "promise": ("答应", "约定", "请客", "欠", "下次", "下周"),
    "school": ("学校", "学院", "大学", "专业", "新乡", "开封", "河南"),
    "preference": ("喜欢", "爱吃", "爱喝", "喝", "奶茶", "口味", "不喜欢", "讨厌"),
    "tired": ("体测", "累", "疲劳", "困"),
    "busy": ("忙", "考试", "作业", "学习", "复习"),
    "family": ("家人", "妈妈", "爸爸", "外婆", "家里"),
    "food": ("早餐", "早饭", "吃", "喝", "奶茶", "火锅", "外卖"),
}
_INTENT_KEYS = {
    "identity": ("他的名字", "他的年龄"),
    "school": ("他的学校", "他的专业"),
    "preference": ("他的口味",),
}
# 越具体的词权重越高；“累/困”这种泛词不能压过“体测”
_INTENT_WEIGHTS = {
    "identity": {"名字": 0.9, "叫": 0.9, "称呼": 0.9, "年龄": 0.7, "岁": 0.7},
    "promise": {"答应": 0.7, "约定": 0.7, "请客": 0.7, "欠": 0.6, "下周": 0.8, "下次": 0.6},
    "school": {"学校": 0.5, "学院": 0.6, "大学": 0.6, "专业": 0.7, "新乡": 0.8, "开封": 0.8, "河南": 0.8},
    "preference": {"喜欢": 0.4, "爱喝": 0.6, "喝": 0.5, "奶茶": 0.9, "火锅": 0.7, "口味": 0.6,
                   "不喜欢": 0.4, "讨厌": 0.4},
    "tired": {"体测": 1.0, "累": 0.7, "疲劳": 0.6, "困": 0.4},
    "busy": {"忙": 0.5, "考试": 0.7, "作业": 0.8, "学习": 0.6, "复习": 0.6},
    "family": {"家人": 0.8, "妈妈": 0.8, "爸爸": 0.8, "外婆": 0.8, "家里": 0.5},
    "food": {"早餐": 0.8, "早饭": 0.8, "吃": 0.3, "喝": 0.4, "奶茶": 0.8, "火锅": 0.8, "外卖": 0.7},
}


def _rewrite_query(query: str) -> tuple[str, str]:
    """判断问句意图并补常用词；返回（改写文本，意图）。"""
    raw = str(query or "")
    intent = ""
    for name, words in _INTENT_RULES:
        if any(word in raw for word in words):
            intent = name
            break
    hints = " ".join(_INTENT_HINTS.get(intent, ()))
    return (raw + " " + hints).strip(), intent


def _target_terms(query: str, intent: str) -> tuple[str, ...]:
    """抽出这句到底在问哪个对象，防止“喜欢喝什么”被早饭记忆抢答。"""
    raw = str(query or "")
    if intent == "preference":
        if "喝" in raw:
            return ("喝", "奶茶", "饮料", "咖啡", "水")
        if "吃" in raw:
            return ("吃", "饭", "菜", "火锅", "外卖", "零食", "奶茶")
        if "讨厌" in raw or "不喜欢" in raw:
            return ("不喜欢", "讨厌", "不吃", "不爱")
        return ("喜欢", "爱吃", "爱喝", "口味")
    if intent == "food":
        if "早" in raw:
            return ("早餐", "早饭", "吃", "饭", "胃口", "不吃")
        if "午" in raw:
            return ("午饭", "午餐", "吃", "饭", "外卖")
        if "晚" in raw:
            return ("晚饭", "晚餐", "吃", "饭", "外卖")
        return ("吃", "饭", "外卖", "火锅", "奶茶")
    return _INTENT_HINTS.get(intent, ())

_ALIASES: dict[str, set[str]] = {}
for _group in _ALIAS_GROUPS:
    for _word in _group:
        _ALIASES.setdefault(_word, set()).update(_group)

# 只有这些来源的记忆才允许落库，防止模型自造的标题/话题污染记忆库
_ALLOWED_SOURCES = {
    "chat", "nightly", "reflection", "self_reflection", "digest", "backfill", "M11.artifact",
    "import",  # 手动备份导入
    "world",  # 视频通话里她亲眼看到的内容
}

# 短期时效：命中的是“今晚/明天/周末”这类会过期的事
_TEMPORAL_HINTS = (
    ("今晚", 0, 6),
    ("待会", 0, 6),
    ("等会", 0, 6),
    ("一会儿", 0, 6),
    ("明天", 1, 0),
    ("明早", 1, 0),
    ("后天", 2, 0),
    ("这周末", 7, 0),
    ("周末", 7, 0),
    ("这周", 7, 0),
    ("下周", 14, 0),
)

_LAYERS = {"L1", "L2", "L3", "L4"}
_LAYER_NAME = {"L1": "生活领域", "L2": "关系与人", "L3": "关键事件", "L4": "偏好与触发点"}
_KIND_NAME = {
    "fact": "事实",
    "preference": "偏好",
    "event": "经历",
    "grudge": "在意",
    "promise": "约定",
}
# 间隔回访节点：1 天 / 1 周 / 1 月 / 1 季
_REVIEW_DAYS = (1, 7, 30, 90)


def _tokens(text: str) -> list[str]:
    chunks = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]+", text.lower())
    out: list[str] = []
    for chunk in chunks:
        if len(chunk) <= 2:
            if chunk and chunk[0] not in _STOP:
                out.append(chunk)
        else:
            out.extend(chunk[i : i + 2] for i in range(len(chunk) - 1))
    return [t for t in out if t not in _NOISE][:40]


def _alias_tokens(tokens: set[str], raw: str) -> set[str]:
    """把查询里的词扩成同组别名，扩出来的词只做补充匹配，不算主词。"""
    out: set[str] = set()
    for token in tokens:
        for word in _ALIASES.get(token, ()):
            out.update(_tokens(word))
    low = str(raw or "").lower()
    for word, group in _ALIASES.items():
        if word in low:
            for alt in group:
                out.update(_tokens(alt))
    return out


_VEC_DIM = 160  # 每行维度；特征变多之后把维度抬高一点，降低撞桶概率
_VEC_ROWS = 2  # 双哈希行数（count-min 思路）


def _stable_hash(text: str) -> int:
    """跨进程稳定的哈希。内置 hash() 每次启动都会变，离线对比和排障都麻烦。"""
    return zlib.crc32(text.encode("utf-8")) & 0x7FFFFFFF


def _char_grams(text: str) -> list[str]:
    """原文的字符 2/3-gram：分词之外的兜底，让“麻辣烫”和“麻辣香锅”也能互相检索到。"""
    grams: list[str] = []
    for chunk in re.findall(r"[一-龥A-Za-z0-9]+", str(text or "").lower()):
        for n in (2, 3):
            if len(chunk) >= n:
                grams.extend(chunk[i : i + n] for i in range(len(chunk) - n + 1))
    return grams[:120]


def _vector(
    tokens: list[str], idf: dict[str, float] | None = None, raw: str = ""
) -> list[float]:
    """本地轻量语义向量（纯 Python，无外部依赖）。

    相比最初的纯词计数哈希做了三件事：
    - 词 + 字符 2/3-gram 混合特征：分词没切好或说法不完全一致时也能蹭上分；
    - 双哈希两行（count-min 思路）：同一特征进两行、余弦取两行较小值，
      撞桶造成的无关文本虚高会被另一行压下去，实测无关句对噪声降约三成；
    - 可传 IDF：越稀有的词权重越高，避免高频虚词带偏向量方向。

    返回长度为 _VEC_ROWS * _VEC_DIM 的拼接向量，两行各自归一。
    """
    rows = [[0.0] * _VEC_DIM for _ in range(_VEC_ROWS)]
    feats: list[tuple[str, float]] = []
    for token, tf in Counter(tokens).items():
        w = (1.0 + math.log(tf)) * (idf.get(token, 1.0) if idf else 1.0)
        feats.append(("w:" + token, w))
    for gram, tf in Counter(_char_grams(raw)).items():
        feats.append(("g:" + gram, 0.5 * (1.0 + math.log(tf))))
    for feat, w in feats:
        for r in range(_VEC_ROWS):
            pos = _stable_hash("~" * r + feat) % _VEC_DIM
            rows[r][pos] += w
    out: list[float] = []
    for row in rows:
        norm = math.sqrt(sum(v * v for v in row)) or 1.0
        out.extend(v / norm for v in row)
    return out


def _cosine(a: list[float], b: list[float]) -> float:
    """双行向量取各行余弦的较小值（压撞桶虚高）；普通向量直接算。"""
    total = _VEC_ROWS * _VEC_DIM
    if _VEC_ROWS > 1 and len(a) == total and len(b) == total:
        return min(
            sum(
                x * y
                for x, y in zip(
                    a[r * _VEC_DIM : (r + 1) * _VEC_DIM],
                    b[r * _VEC_DIM : (r + 1) * _VEC_DIM],
                )
            )
            for r in range(_VEC_ROWS)
        )
    return sum(x * y for x, y in zip(a, b))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _valid_until(text: str, now: float | None = None) -> float:
    """命中短期时效词就返回失效时间；否则 0（长期有效）。"""
    now = now or time.time()
    for word, days, hours in _TEMPORAL_HINTS:
        if word in text:
            if hours and not days:
                return now + hours * 3600
            end_of_today = datetime.fromtimestamp(now).replace(hour=23, minute=59, second=59, microsecond=0)
            return (end_of_today + timedelta(days=days)).timestamp()
    return 0.0


def _clean(value: Any, limit: int) -> str:
    return re.sub(r"[\r\n]+", " ", str(value or "")).strip()[:limit]


def _question_like(value: str) -> bool:
    """问句不能当成事实入库（例如“我叫什么来着？还记得吗”）。"""
    text = str(value or "").strip()
    if len(text) > 80:
        return False
    if text.endswith(("？", "?")):
        return True
    return "叫什么来着" in text or "还记得吗" in text


def _canonical_key(kind: str, key: str, person: str) -> str:
    """把“他在哪 / 异地不同校 / 名字和称呼”收敛成同一个属性键。"""
    if str(kind) != "fact" or str(person) not in ("他", "袁伟航"):
        return key
    for words, canonical in _CANON_FACTS:
        if any(word in str(key) for word in words):
            return canonical
    return key


def _falsifier(kind: str, value: str, key: str) -> str:
    """M8：为一条记忆生成可执行的证伪条件；写不出来就不收。"""
    text = _clean(value, 60)
    topic = _clean(key, 30) or text
    templates = {
        "preference": f"若他明确说“不是这样/我不喜欢”，或后续选择与「{text}」相反，此条作废",
        "event": f"若他否认「{topic}」发生过，或时间/人物对不上，此条作废",
        "promise": f"若他明确取消「{topic}」这个约定，或到期未兑现，此条作废",
        "grudge": f"若他解释清楚并道歉，或同类事不再发生，此条作废",
        "fact": f"若他明确否认「{topic}」，或与后续事实相反，此条作废",
    }
    return templates.get(str(kind or "fact"), f"若他明确否认「{topic}」，或与后续事实相反，此条作废")


class Memory:
    def __init__(self, store: Store, memory_store: Store | None = None):
        # store 管状态、消息与账本；mstore 只管记忆表。
        # 小鲸鱼接入后两者不同：记忆共用主库，运行状态各自独立。
        self.store = store
        self.mstore = memory_store or store
        self.last_revised = 0
        self._narrative_bias = None
        self._narrative_bias_weight = 0.2
        self._affect = None
        self._affect_bias_weight = 0.8
        self._hits: dict[int, int] = {}
        # 图谱为空但已有记忆时补建一次（老库升级后也能用）
        try:
            if self.mstore.memory_link_count() == 0 and len(self.mstore.all_memories(_RECALL_POOL)) >= 5:
                self.rebuild_links()
        except Exception as exc:  # noqa: BLE001
            log.warning("记忆图谱初始化失败：%s", exc)
        try:
            self._cleanup_bad_facts()
        except Exception as exc:  # noqa: BLE001
            log.warning("旧记忆质检失败：%s", exc)

    def _cleanup_bad_facts(self) -> int:
        """一次性清掉历史里被当成事实的问句，只归档不删除。"""
        if self.store.get_state("mem_quality_v1"):
            return 0
        archived = 0
        for m in self.mstore.all_memories(_RECALL_POOL):
            if str(m.get("kind") or "") not in ("fact", "preference", "promise"):
                continue
            if _question_like(str(m.get("value") or "")):
                self.mstore.adjust_memory(int(m["id"]), status="archived")
                archived += 1
        self.store.set_state("mem_quality_v1", {"at": time.time(), "archived": archived})
        if archived:
            log.info("旧记忆质检：归档问句式事实 %d 条", archived)
        return archived

    def set_affect(self, affect, weight: float = 0.8) -> None:
        self._affect = affect
        self._affect_bias_weight = max(0.0, min(1.5, float(weight)))

    def set_narrative_bias(self, fn, weight: float = 0.2) -> None:
        """接入叙事一致性偏置；fn 接收记忆列表并返回带 narrative_bias 的副本。"""
        self._narrative_bias = fn
        self._narrative_bias_weight = max(0.0, min(0.3, float(weight)))

    # ------------------------------------------------------------------
    # L0 身份主线
    # ------------------------------------------------------------------
    def mainline(self) -> str:
        return str(self.store.get_state("memory_mainline") or "")

    def set_mainline(self, text: str) -> str:
        line = _clean(text, 120)
        if line:
            self.store.set_state("memory_mainline", line)
        return line

    # ------------------------------------------------------------------
    # 短期：给 LLM 的对话上下文
    # ------------------------------------------------------------------
    def recent_dialogue(self, limit: int = 24, exclude_last: bool = False) -> list[dict[str, str]]:
        msgs = self.store.recent_messages(limit + (1 if exclude_last else 0))
        if exclude_last:
            msgs = msgs[:-1]
        return [{"role": m["role"], "content": m["content"]} for m in msgs if m["content"].strip()]

    # ------------------------------------------------------------------
    # 长期写入
    # ------------------------------------------------------------------
    def add_facts(
        self,
        facts: list[dict[str, Any]],
        source: str = "chat",
        max_items: int = 8,
        refraction_id: int = 0,
    ) -> int:
        added = 0
        self.last_revised = 0
        # 当天的同类记忆池：用于“同日同人相似事件”去重
        day_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        all_pool = self.mstore.all_memories(_RECALL_POOL)
        day_pool = [
            m
            for m in all_pool
            if float(m.get("created_at") or 0) >= day_start
            and str(m.get("kind") or "") in ("event", "fact")
        ]
        recent_cutoff = time.time() - 30 * 86400
        recent_pool = [
            m
            for m in all_pool
            if float(m.get("created_at") or 0) >= recent_cutoff
            and str(m.get("kind") or "") in ("event", "fact")
        ]
        for f in facts[:max_items]:
            if not isinstance(f, dict):
                continue
            src = _clean(f.get("source") or source, 40) or "chat"
            if src not in _ALLOWED_SOURCES:
                log.warning("拒绝来源 %r 的记忆写入：%s", src, str(f.get("fact") or f.get("value"))[:40])
                continue
            # 兼容老字段：value = 事实；新字段：fact = 事实（严格可验证部分）
            value = _clean(f.get("fact") or f.get("value"), 300)
            if not value:
                continue
            raw_key = _clean(f.get("key"), 60) or value[:20]
            kind = _clean(f.get("kind"), 20) or "fact"
            if kind in ("fact", "preference", "promise") and _question_like(value):
                log.info("拒绝把问句写成记忆：%s", value[:40])
                continue
            person = _clean(f.get("person"), 40)
            key = _canonical_key(kind, raw_key, person)
            supplied_falsifier = _clean(f.get("falsifier"), 300)
            if supplied_falsifier and len(supplied_falsifier) < 8:
                log.warning("M8 拒收：证伪条件太短 %r", supplied_falsifier)
                continue
            falsifier = supplied_falsifier or _falsifier(kind, value, key)
            try:
                conf = float(f.get("confidence", 0.7))
            except (TypeError, ValueError):
                conf = 0.7
            layer = str(f.get("layer") or "").upper()
            if layer not in _LAYERS:
                layer = "L4" if kind == "preference" else "L3"
            try:
                intensity = int(float(f.get("intensity", 2)))
            except (TypeError, ValueError):
                intensity = 2
            intensity = max(1, min(5, intensity))
            try:
                link = float(f.get("mainline_link", 1) or 1)
            except (TypeError, ValueError):
                link = 1.0
            link = max(0.0, min(2.0, link))
            # 权重重标定：情绪强度(1-5) 与主线关联度(0-2) 合成，落在 0.1~1.0
            weight = round(min(1.0, max(0.1, 0.15 + intensity * 0.12 + link * 0.15)), 3)
            person_id = _clean(f.get("person_id"), 40)
            if not person_id and person:
                node = self.mstore.social_node_by_name(person)
                if node:
                    person_id = str(node["id"])
            # 同日同人同类的相似事件只留一条，避免同一段话被写五遍
            if self._is_duplicate(value, kind, person, day_pool):
                log.info("相似记忆已在今天写过，跳过：%s", value[:40])
                continue
            # 跨天近似重复：阈值更高，只挡几乎同义的复述
            if self._is_duplicate(value, kind, person, recent_pool, threshold=0.72):
                log.info("相似记忆最近写过，跳过：%s", value[:40])
                continue
            mid, revised = self.mstore.insert_memory(
                {
                    "kind": kind,
                    "key": key,
                    "value": value,
                    "confidence": max(0.3, min(0.95, conf)),
                    "source": src,
                    "layer": layer,
                    "person": person,
                    "person_id": person_id,
                    "domain": _clean(f.get("domain"), 40),
                    "scene": _clean(f.get("scene"), 120),
                    "emotion": _clean(f.get("emotion"), 20),
                    "intensity": intensity,
                    "hooks": _clean(f.get("hooks"), 120) or key,
                    "interpretation": _clean(f.get("interpretation"), 200),
                    "weight": weight,
                    "mainline_link": link,
                    "valid_until": _valid_until(f"{value} {key}"),
                    "reason": _clean(f.get("reason"), 200),
                    "refraction_id": int(refraction_id or f.get("refraction_id") or 0),
                    "falsifier": falsifier,
                }
            )
            if mid and key != raw_key:
                self._archive_conflicts(key, person, mid)
            day_pool.append({"id": mid, "kind": kind, "value": value, "person": person})
            if revised:
                self.last_revised += 1
                log.info("记忆修正 %s：%s → %s", mid, key, value[:40])
            added += 1
        if facts and added == 0:
            log.warning("收到 %d 条记忆但没有一条可写入", len(facts))
        return added

    _RULE_FACTS = (
        ("fact", "他的名字", re.compile(r"我(?:叫|名字是|名字叫)([\u4e00-\u9fa5A-Za-z]{1,12})")),
        ("fact", "他的年龄", re.compile(r"我(?:今年)?([一二三四五六七八九十两0-9]{1,3})岁")),
        ("fact", "他在哪", re.compile(r"我(?:在|就读于)([\u4e00-\u9fa5]{2,12}(?:上学|读书|读|上班|工作|大学|学院))")),
        ("preference", "", re.compile(r"我(?:喜欢|爱|爱吃|超爱|最爱)([\u4e00-\u9fa5A-Za-z0-9]{2,10})")),
        ("preference", "", re.compile(r"我(?:不喜欢|不爱|不吃|讨厌|受不了)([\u4e00-\u9fa5A-Za-z0-9]{2,10})")),
        ("preference", "", re.compile(r"[，,、](?:不喜欢|不爱|不吃|讨厌|受不了)([\u4e00-\u9fa5A-Za-z0-9]{2,10})")),
        ("event", "", re.compile(r"我(明早|明天|后天|周末|今晚|这周|下周)(?:要|去|得|准备|想)([\u4e00-\u9fa5A-Za-z0-9]{1,16})")),
        ("promise", "他答应的事", re.compile(r"我(?:答应|保证|承诺)(?:你)?([\u4e00-\u9fa5A-Za-z0-9]{2,20})")),
    )
    _RULE_SKIP = {"你", "他", "她", "它", "这", "那", "什么", "干嘛", "咋"}

    def rule_facts(self, text: str) -> list[dict[str, Any]]:
        """LLM 没给记忆时的兜底：只抓他明确说出口的个人信息，不猜。"""
        raw = _clean(text, 200)
        if len(raw) < 6 or raw.startswith("你"):
            return []
        found: list[dict[str, Any]] = []
        seen: set[str] = set()
        for kind, fixed_key, pattern in self._RULE_FACTS:
            for match in pattern.finditer(raw):
                groups = [g for g in match.groups() if g]
                if not groups:
                    continue
                head = groups[-1]
                if head in self._RULE_SKIP:
                    continue
                if fixed_key:
                    key = fixed_key
                elif kind == "preference":
                    neg = any(w in match.group(0) for w in ("不喜欢", "不爱", "不吃", "讨厌", "受不了"))
                    key = f"他{'不喜欢' if neg else '喜欢'}{head[:8]}"
                elif kind == "event":
                    key = f"他的安排·{groups[0]}"
                else:
                    key = f"他{head[:10]}"
                if key in seen:
                    continue
                seen.add(key)
                found.append(
                    {
                        "kind": kind,
                        "key": key,
                        "fact": f"他说：{raw[:80]}",
                        "person": "他",
                        "confidence": 0.75,
                        "intensity": 2,
                        "hooks": key,
                    }
                )
                if len(found) >= 2:
                    return found
        return found

    def evolve_tension(self, tension: dict[str, Any]) -> dict[str, Any] | None:
        """M11 扬弃：把一条累积到阈值的张力提升为“两种说法并存”的新版本。

        旧 value 不删；只写 interpretation 与版本链，并显式给出克服/保留/提升。
        """
        code = str(tension.get("a_ref") or "")
        if not code:
            return None
        memory = self.mstore.memory_by_code(code)
        if not memory:
            return None
        old_value = str(memory.get("value") or "")
        old_interp = str(memory.get("interpretation") or "")
        note = str(tension.get("note") or "").strip()
        topic = str(tension.get("topic") or memory.get("key") or "这件事")
        overcame = "只按旧说法理解"
        kept = old_value or old_interp
        raised = (
            f"两种说法并存：旧「{old_value[:60]}」/ 新「{note[:60]}」；"
            f"暂不判定谁对，保留「{topic}」的张力，等后续实践再定。"
        )
        self.mstore.add_memory_version(
            int(memory["id"]),
            str(memory.get("kind") or "fact"),
            str(memory.get("key") or ""),
            old_value,
            raised,
            "M9→M10→M11 扬弃",
            overcame=overcame,
            kept=kept,
            raised=raised,
        )
        self.mstore.apply_evolution(int(memory["id"]), raised, "revised")
        return {
            "memory_id": int(memory["id"]),
            "code": code,
            "topic": topic,
            "overcame": overcame,
            "kept": kept,
            "raised": raised,
        }

    def _is_duplicate(
        self,
        value: str,
        kind: str,
        person: str,
        pool: list[dict[str, Any]],
        threshold: float = 0.55,
    ) -> bool:
        """同一天、同一人、同一类记忆里，Jaccard 过阈值的算重复。"""
        if str(kind) not in ("event", "fact"):
            return False
        tokens = set(_tokens(value))
        if not tokens:
            return False
        for m in pool:
            if str(m.get("kind") or "") != str(kind):
                continue
            if str(m.get("person") or "") != str(person or ""):
                continue
            if _jaccard(tokens, set(_tokens(str(m.get("value") or "")))) >= threshold:
                return True
        return False

    def _archive_conflicts(self, canonical: str, person: str, keep_id: int) -> int:
        """同一用户属性只留最新一条：旧值归档，仍在库里，不物理删除。"""
        if not canonical:
            return 0
        archived = 0
        for m in self.mstore.all_memories(_RECALL_POOL):
            mid = int(m.get("id") or 0)
            if mid == keep_id or str(m.get("kind") or "") != "fact":
                continue
            if str(m.get("person") or "") != str(person or ""):
                continue
            if _canonical_key("fact", str(m.get("key") or ""), person) != canonical:
                continue
            self.mstore.adjust_memory(mid, status="archived")
            archived += 1
        if archived:
            log.info("属性冲突收敛：%s 归档旧值 %d 条", canonical, archived)
        return archived

    # ------------------------------------------------------------------
    # 长期检索
    # ------------------------------------------------------------------
    def recall_scored(
        self,
        query: str,
        limit: int = 6,
        require_overlap: bool = False,
        primary: str = "",
        min_matches: int = 0,
        half_life_days: float = 30.0,
        weight_floor: float = 0.1,
        semantic_weight: float = 0.35,
    ) -> list[tuple[float, dict[str, Any]]]:
        memories = self.mstore.all_memories(_RECALL_POOL)
        if not memories:
            return []
        texts: list[str] = []
        token_lists: list[list[str]] = []
        for m in memories:
            text = " ".join(
                str(m.get(k) or "")
                for k in ("key", "value", "hooks", "person", "emotion", "interpretation")
            ).lower()
            texts.append(text)
            token_lists.append(_tokens(text))
        n_docs = len(memories)
        # 文档频率：越常见的词越不值钱，避免“自己/什么”这种词把无关记忆顶上来
        df: dict[str, int] = {}
        for toks in token_lists:
            for t in set(toks):
                df[t] = df.get(t, 0) + 1
        avgdl = sum(len(t) for t in token_lists) / max(1, n_docs)
        idf_max = math.log(1 + (n_docs + 0.5) / 1.5) or 1.0
        # 归一化 IDF（单词出现 1 次 ≈ 1.0，满库都是 ≈ 0），给语义向量加权用
        idf = {
            t: math.log(1 + (n_docs - d + 0.5) / (d + 0.5)) / idf_max
            for t, d in df.items()
        }
        k1, b = 1.2, 0.75

        def bm25(t: str, tf: int, dl: int) -> float:
            d = df.get(t, 0)
            if not d:
                return 0.0
            idf = math.log(1 + (n_docs - d + 0.5) / (d + 0.5))
            denom = tf + k1 * (1 - b + b * dl / max(1.0, avgdl))
            # 除以 idf_max，把词权重压回 0~1，分数尺度和老版本可比
            return idf * tf * (k1 + 1) / denom / idf_max

        query_tokens = _tokens(query)
        rewrite_text, intent = _rewrite_query(query)
        tokens = set(query_tokens) | set(_tokens(rewrite_text))
        # 同义词只补充匹配，不算主词
        tokens |= _alias_tokens(tokens, query)
        query_vec = _vector(query_tokens, idf, query) if semantic_weight else []
        targets = _target_terms(query, intent) if intent else ()
        primary_tokens = set(_tokens(primary)) if primary else set()
        exact = primary.strip().lower()
        now = time.time()
        scored: list[tuple[float, dict[str, Any]]] = []
        for m, toks, text in zip(memories, token_lists, texts):
            m_tokens = set(toks)
            counts = Counter(toks)
            dl = len(toks)
            matched = tokens & m_tokens
            prime = primary_tokens & m_tokens
            if require_overlap and not matched:
                continue
            # 普通消息至少要有两处重合，除非他这句原话就写在记忆里
            if min_matches and len(matched) < min_matches and not (exact and exact in text):
                continue
            score = float(m["confidence"] or 0) * 0.1
            if prime:
                # 当前这句话里的词权重最高；同义扩展只做补充
                score += sum(bm25(t, counts[t], dl) for t in prime) * 2.5
                rest = matched - prime
                score += sum(bm25(t, counts[t], dl) for t in rest)
            else:
                score += sum(bm25(t, counts[t], dl) for t in matched)
            if query_vec:
                # 词面之外的相近说法补一点分（本地混合特征向量，不是外部 embedding）
                score += semantic_weight * _cosine(query_vec, _vector(toks, idf, text))
            # 修正过的记忆按创建时间计龄，避免改一次就“返老还童”
            base = m.get("created_at") if m.get("status") == "revised" and m.get("created_at") else m.get("updated_at")
            age_days = max(0.0, (now - float(base or now)) / 86400)
            decay = 0.5 ** (age_days / max(1.0, half_life_days))  # 30 天半衰期
            reviews = int(m.get("review_count") or 0)
            weight = max(
                weight_floor,
                float(m.get("weight") or 0.1) * decay * (1 + min(0.5, reviews * 0.1)),
            )
            # 权重只在词面确实相关时加分，且封顶：基础设定不该压过相关性
            if matched:
                score += min(0.55, weight * 1.1)
            else:
                score += weight * 0.2
            valid_until = float(m.get("valid_until") or 0)
            if valid_until and now > valid_until:
                # 短期事实过期：不是删掉，只是别再让它抢戏
                score -= 0.6
            if self._affect is not None:
                try:
                    current = float(self._affect.state.get("valence", 0) or 0)
                except Exception:  # noqa: BLE001
                    current = 0.0
                memory_valence = VALENCE_BY_LABEL.get(str(m.get("emotion") or ""), 0.0)
                if current and memory_valence:
                    score += current * memory_valence * self._affect_bias_weight
            if m.get("status") == "revised":
                score += 0.05
            # 查询改写后的意图重排：让“问什么就答什么”的记忆排到前面
            if matched:
                key_tokens = set(_tokens(str(m.get("key") or "")))
                overlap = tokens & key_tokens
                if overlap:
                    score += min(0.5, 0.2 * len(overlap))
            if intent:
                kind = str(m.get("kind") or "")
                weights = _INTENT_WEIGHTS.get(intent, {})
                best = sum(weight for word, weight in weights.items() if word in text)
                best = min(1.2, best)
                score += best
                if best <= 0:
                    # 有明确意图却一个相关词都没有，不能靠泛词排到前面
                    score -= 0.7
                target_hit = sum(1 for word in targets if word in text)
                if targets:
                    score += min(0.6, 0.18 * target_hit) if target_hit else -0.8
                if best > 0:
                    if intent == "promise" and kind == "promise":
                        score += 0.4
                    if intent == "preference" and kind == "preference":
                        score += 0.25
                if best > 0 and str(m.get("key") or "") in _INTENT_KEYS.get(intent, ()):
                    score += 0.5
                if best > 0 and intent in ("identity", "school", "preference", "promise", "family") and str(
                    m.get("person") or ""
                ) in ("他", "袁伟航"):
                    score += 0.2
            if not matched:
                # 没撞上关键词就不该主动冒头；核心记忆由 core_memory 单独补
                score -= 0.8
            # 明确问“喝什么/吃什么”却没碰到该对象：降到候选末尾，避免抢答
            if targets and target_hit == 0 and intent in ("preference", "food"):
                score = min(score, 0.25)
            # “喝什么”要的是具体饮品；只有“喝水”的记录不算偏好
            if intent == "preference" and "喝" in query:
                if not any(w in text for w in ("奶茶", "饮料", "咖啡", "果汁", "可乐", "酒")):
                    score = min(score, 0.3)
            # “我家里人”优先真正的家人，而不是只提到外婆的小名记忆
            if intent == "family" and any(w in text for w in ("妈妈", "爸爸", "家人", "家里")):
                score += 0.5
            scored.append((score, m))
        if self._narrative_bias is not None:
            biased = self._narrative_bias([m for _, m in scored])
            boost = {
                item["id"]: float(item.get("narrative_bias", 0) or 0)
                for item in biased
            }
            scored = [
                (score + boost.get(m["id"], 0.0) * self._narrative_bias_weight, m)
                for score, m in scored
            ]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [(score, m) for score, m in scored[:limit] if score > 0.3]

    def recall(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        return [m for _, m in self.recall_scored(query, limit)]

    def core_memory(self) -> dict[str, Any] | None:
        """每 N 轮补一条核心记忆，避免彻底断片；不要每轮都拿出来。"""
        memories = self.mstore.all_memories(_RECALL_POOL)
        pool = [
            m
            for m in memories
            if m.get("kind") in ("event", "grudge", "promise")
            and float(m.get("weight") or 0) >= 0.3
        ]
        if not pool:
            return None
        last = int(self.store.get_state("last_core_memory_id") or 0)
        pool.sort(
            key=lambda m: (float(m.get("weight") or 0) * 2 + (m.get("updated_at") or 0) / 1e9),
            reverse=True,
        )
        choice = next((m for m in pool if int(m["id"]) != last), pool[0])
        self.store.set_state("last_core_memory_id", int(choice["id"]))
        return choice

    def format_items(self, items: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        mainline = self.mainline()
        if mainline:
            lines.append(f"主线：{mainline}")
        for m in items[:4]:
            code = m.get("code") or f"{m.get('layer') or 'L3'}-{m['id']:03d}"
            tags = [code, _LAYER_NAME.get(str(m.get("layer")), "记忆")]
            if m.get("emotion"):
                tags.append(f"{m['emotion']}·{int(m.get('intensity') or 2)}")
            line = f"- [{'·'.join(tags)}] {_clean(m['value'], 90)}（事实）"
            if m.get("interpretation"):
                line += f"；我的解读：{_clean(m['interpretation'], 60)}（是猜的，可能被推翻）"
            if m.get("person_id") and str(m["person_id"]) != "user":
                rel = self.store.social_relation(str(m["person_id"]))
                if rel:
                    note = f"（关于{rel['name']}"
                    if float(rel.get("conflict") or 0) >= 20:
                        note += f"，你们最近有点僵，矛盾{float(rel['conflict']):.0f}"
                    elif float(rel.get("depth") or 0) >= 60:
                        note += "，你们很亲近"
                    line += note + "）"
            lines.append(line)
        summaries = self.store.recent_summaries(3)
        if summaries:
            lines.append("【最近几天】")
            for s in summaries:
                lines.append(f"- {s['date']}：{s['summary']}")
        return "\n".join(lines) or "（还没记下什么特别的事）"

    def format_recall(self, query: str, limit: int = 6) -> str:
        return self.format_items(self.recall(query, limit))

    # ------------------------------------------------------------------
    # 提取练习 / 间隔回访
    # ------------------------------------------------------------------
    def due_review(self, limit: int = 1) -> list[dict[str, Any]]:
        return self.mstore.due_review_memories(limit=limit)

    def mark_reviewed(self, memory_id: int) -> None:
        mem = self.mstore.memory_by_id(memory_id) or {}
        count = int(mem.get("review_count") or 0)
        days = _REVIEW_DAYS[min(count, len(_REVIEW_DAYS) - 1)]
        self.mstore.mark_memory_reviewed(memory_id, time.time() + days * 86400)
        log.info("记忆回访完成：%s（下次 %d 天后）", mem.get("code") or memory_id, days)

    def spread_review_backlog(self, keep_id: int = 0, limit: int = 200) -> int:
        """把已经到期的一堆记忆摊到未来 1~10 天，别让它们同一天全砸过来。"""
        due = self.mstore.due_review_memories(limit=limit)
        moved = 0
        for m in due:
            if keep_id and int(m["id"]) == int(keep_id):
                continue
            self.mstore.set_memory_next_review(
                int(m["id"]), time.time() + random.randint(1, 10) * 86400
            )
            moved += 1
        if moved:
            log.info("回访积压错峰：%d 条到期记忆摊到未来 1~10 天", moved)
        return moved

    def rebuild_links(self, per_node: int = 5) -> int:
        """重建记忆图谱：同一人、或共享稀有词（相近话题）连一条边。"""
        # event/fact/promise/relationship 等都连，只有每日摘要不参与
        mems = [m for m in self.mstore.all_memories(_RECALL_POOL) if str(m.get("source")) != "digest"]
        raw_toks: dict[int, set[str]] = {}
        for m in mems:
            raw_toks[int(m["id"])] = set(
                _tokens(" ".join(str(m.get(k) or "") for k in ("key", "value", "hooks", "person")))
            )
        # 剔掉“今天/他/我”这类满库都是的虚词双字，否则连出来的边全是噪声
        df: Counter = Counter()
        for ts in raw_toks.values():
            df.update(ts)
        common_cut = max(3, len(mems) // 10)
        toks = {mid: {t for t in ts if df[t] <= common_cut} for mid, ts in raw_toks.items()}
        # 先算所有候选边，再按每个节点的 top-K 取，避免只朝“后面”连
        cands: dict[int, list[tuple[float, str, int]]] = defaultdict(list)
        for i, a in enumerate(mems):
            aid = int(a["id"])
            for b in mems[i + 1:]:
                bid = int(b["id"])
                weight, reason = 0.0, ""
                pa, pb = str(a.get("person_id") or ""), str(b.get("person_id") or "")
                if pa and pa == pb:
                    weight, reason = 0.7, "同一人"
                overlap = _jaccard(toks[aid], toks[bid])
                shared = len(toks[aid] & toks[bid])
                if overlap >= 0.06 or shared >= 2:
                    topic = min(0.95, 0.3 + max(overlap, shared * 0.05))
                    if topic > weight:
                        weight, reason = topic, "共同话题"
                if weight >= 0.3:
                    cands[aid].append((weight, reason, bid))
                    cands[bid].append((weight, reason, aid))
        pairs: list[tuple[int, int, float, str]] = []
        seen: set[tuple[int, int]] = set()
        for aid, items in cands.items():
            for weight, reason, bid in sorted(items, reverse=True)[:per_node]:
                key = (min(aid, bid), max(aid, bid))
                if key in seen:
                    continue
                seen.add(key)
                pairs.append((aid, bid, round(weight, 3), reason))
        n = self.mstore.replace_memory_links(pairs)
        log.info("记忆图谱重建：%d 个节点，%d 条边", len(mems), n)
        return n

    def related_items(
        self, ids: list[int], limit: int = 2, exclude: list[int] | None = None
    ) -> list[dict[str, Any]]:
        """顺着图谱取 1 跳关联记忆，用于明确问旧事时补上下文。"""
        skip = {int(i) for i in (exclude or [])} | {int(i) for i in ids}
        out: list[dict[str, Any]] = []
        for mid in ids:
            for m in self.mstore.memory_links(int(mid), 4):
                m = dict(m)
                mid2 = int(m["id"])
                if mid2 in skip:
                    continue
                skip.add(mid2)
                out.append(m)
                if len(out) >= limit:
                    return out
        return out

    def top_entries(self, limit: int = 10, min_weight: float = 0.4) -> list[dict[str, Any]]:
        """给夜间复盘用：目前权重最高的几条，方便它发现自己被推翻的解读。"""
        items = [m for m in self.mstore.all_memories(_RECALL_POOL) if float(m.get("weight") or 0) >= min_weight]
        items.sort(key=lambda m: float(m.get("weight") or 0), reverse=True)
        return items[:limit]

    def transcript_between(self, start: float, end: float) -> str:
        msgs = self.store.messages_between(start, end)
        lines = []
        for m in msgs[-120:]:
            who = "他" if m["role"] == "user" else "我"
            lines.append(f"{who}：{m['content'][:120]}")
        return "\n".join(lines) or "（今天没聊几句）"

    def today_transcript(self, now: float | None = None) -> str:
        now = now or time.time()
        return self.transcript_between(now - 86400, now)

    # ------------------------------------------------------------------
    # 夜间整理 / 每周探针（Phase 2）
    # ------------------------------------------------------------------
    def note_hits(self, ids: list[int]) -> None:
        """记下这轮真正被用到的记忆：即时 +0.02（同一天每条最多加 3 次），夜里再结算。"""
        today = datetime.now().strftime("%Y-%m-%d")
        saved = self.store.get_state("memory_hit_bump")
        day, counts = ("", {})
        if isinstance(saved, list) and len(saved) == 2:
            day, counts = str(saved[0]), dict(saved[1] or {})
        if day != today:
            day, counts = today, {}
        for mid in ids:
            mid = int(mid)
            self._hits[mid] = self._hits.get(mid, 0) + 1
            used = int(counts.get(str(mid), 0))
            if used >= 3:
                continue
            mem = self.mstore.memory_by_id(mid) or {}
            weight = float(mem.get("weight") or 0)
            if weight:
                self.mstore.adjust_memory(mid, weight=min(1.0, weight + 0.02))
            counts[str(mid)] = used + 1
        self.store.set_state("memory_hit_bump", [day, counts])

    def consolidate(self, digest_keep_days: int = 14, now: float | None = None) -> dict[str, Any]:
        """每晚整理：常用记忆加权、冷记忆衰减、生成今日三件事、清理旧摘要。"""
        now = now or time.time()
        memories = self.mstore.all_memories(_RECALL_POOL)
        hits, self._hits = self._hits, {}
        boosted = decayed = 0
        for m in memories:
            mid = int(m["id"])
            weight = float(m.get("weight") or 0.1)
            if hits.get(mid):
                new_weight = min(1.0, weight + 0.05 * min(3, hits[mid]))
            elif now - float(m.get("updated_at") or now) > 30 * 86400 and weight > 0.1:
                new_weight = max(0.1, weight - 0.03)
            else:
                continue
            new_weight = round(new_weight, 3)
            if abs(new_weight - weight) < 1e-6:
                continue
            self.mstore.adjust_memory(mid, weight=new_weight)
            if new_weight > weight:
                boosted += 1
            else:
                decayed += 1

        # 今日关于他的三件事：不调 LLM，取今天新写、权重最高的三条
        day_start = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
        today_items = [
            m
            for m in memories
            if float(m.get("created_at") or 0) >= day_start.timestamp()
            and str(m.get("source") or "") != "digest"
            and str(m.get("value") or "").strip()
        ]
        today_items.sort(key=lambda m: float(m.get("weight") or 0), reverse=True)
        digest = ""
        if today_items:
            digest = "；".join(
                _clean(m.get("key") or m["value"], 30) for m in today_items[:3]
            )[:120]
            self.mstore.insert_memory(
                {
                    "kind": "event",
                    "key": f"今日三件事·{datetime.fromtimestamp(now).strftime('%Y-%m-%d')}",
                    "value": digest,
                    "confidence": 0.8,
                    "source": "digest",
                    "layer": "L2",
                    "hooks": "今日 摘要 三件事",
                    "interpretation": "",
                    "intensity": 2,
                    "weight": 0.25,
                }
            )

        # 旧摘要只归档，不删事实；正常遗忘策略与全量留档开关无关
        cutoff = now - digest_keep_days * 86400
        archived = 0
        for m in memories:
            if str(m.get("source") or "") != "digest":
                continue
            if float(m.get("created_at") or now) < cutoff:
                self.mstore.adjust_memory(int(m["id"]), status="archived")
                archived += 1
        links = self.rebuild_links()
        log.info(
            "记忆整理：加权 %d 条，衰减 %d 条，今日摘要 %s，归档旧摘要 %d 条，图谱 %d 条边",
            boosted,
            decayed,
            "有" if digest else "无",
            archived,
            links,
        )
        return {
            "boosted": boosted,
            "decayed": decayed,
            "digest": digest,
            "archived": archived,
            "links": links,
        }

    _PROBES = (
        ("我早餐吃什么", ("早餐", "早饭", "早上"), "他早餐吃什么"),
        ("你答应请我吃什么", ("海底捞", "番茄锅"), "他答应过你哪顿饭"),
        ("你记得我答应过你什么", ("叫醒", "海底捞", "奶茶"), "他答应过你什么"),
        ("体测", ("体测",), "他今天为什么累"),
        ("你叫什么名字", ("名字", "小名", "大名", "称呼"), "你知道他/你怎么被叫"),
    )

    _FALLBACK_PROBES = (
        ("我在哪个学校", ("学校", "学院", "大学", "新乡", "开封", "河南"), "他在哪个学校"),
        ("我为什么累", ("体测", "累", "疲劳"), "他为什么累"),
        ("我最近一次点外卖/吃东西", ("外卖", "麻辣烫", "奶茶", "火锅", "夜宵"), "最近的吃的"),
        ("我最近在忙什么", ("课", "考试", "实验", "工作", "复习", "作业", "计量", "学习", "忙"), "最近在忙的事"),
        ("我家里人", ("外婆", "妈妈", "爸爸", "家里"), "他的家人"),
        ("我最近几点睡", ("睡", "熬夜", "凌晨", "困"), "他的作息"),
        ("我喜欢吃什么", ("火锅", "麻辣烫", "奶茶", "饭"), "他的口味"),
        ("我不喜欢什么", ("不", "讨厌", "烦"), "他的雷区"),
        ("你最近发过什么动态", ("动态",), "她在朋友圈说过什么"),
        ("你最近在学什么", ("学", "课", "考试"), "她最近的学习"),
    )

    def _dynamic_probes(self, limit: int = 7) -> tuple:
        """只用独立改写题，不再把记忆 key 写进问题里（避免自己考自己）。"""
        fixed = {q for q, _, _ in self._PROBES}
        probes = []
        used = set(fixed)
        for probe in self._FALLBACK_PROBES:
            if probe[0] in used:
                continue
            probes.append(probe)
            used.add(probe[0])
            if len(probes) >= limit:
                break
        return tuple(probes)

    def weekly_probe(self) -> dict[str, Any]:
        """周日自测：5 条固定问题 + 最多 7 条独立改写题，不调 LLM，答错只调检索不编记忆。"""
        details: list[dict[str, Any]] = []
        passed = 0
        for query, expected, label in self._PROBES + self._dynamic_probes():
            scored = self.recall_scored(query, 3, require_overlap=True, primary=query)
            values = [str(m.get("value") or "") + str(m.get("key") or "") for _, m in scored[:3]]
            hit = any(token in text for text in values for token in expected)
            passed += 1 if hit else 0
            details.append({"q": query, "label": label, "hit": hit})
        total = len(details)
        rate = round(passed / total, 2) if total else 0.0
        result = {
            "ts": time.time(),
            "passed": passed,
            "total": total,
            "rate": rate,
            "details": details,
        }
        self.store.set_state("memory_probe_result", result)
        if rate < 0.6:
            log.warning("每周记忆探针答对率偏低：%d/%d", passed, total)
        else:
            log.info("每周记忆探针：%d/%d", passed, total)
        return result
