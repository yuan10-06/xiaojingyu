"""自我学习：每晚复盘对话，提炼记忆，微调人格旋钮（核心人设不可改）。"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from .db import Store
from .llm import LLM
from .memory import Memory
from .persona import Persona

log = logging.getLogger("brainn.learner")

ANALYST_SYSTEM = """你是一个对话分析器，不是聊天机器人。你会收到情侣/朋友之间的聊天记录，任务是把它加工成能长期复用的分层记忆。

输出 JSON：
{
  "mainline": "她的身份主线，一句话（没有变化就留空）",
  "entries": [{
    "layer": "L2|L3|L4",
    "kind": "fact|preference|event|grudge|promise",
    "key": "2~12 字短标题，修正旧记忆时必须沿用旧 key",
    "fact": "只写他真说过、可被第三方验证的部分",
    "interpretation": "这条事对她意味着什么，明确是解读不是事实",
    "emotion": "情绪性质，如 心疼/愧疚/烦躁/开心",
    "intensity": 1,
    "person": "涉及的人，没有就空字符串",
    "scene": "时间/地点/在场的人/状态等提取线索",
    "hooks": "关键词，用顿号分隔，之后靠它被想起",
    "mainline_link": 1,
    "confidence": 0.8,
    "reason": "如果是修正旧记忆，写清被什么推翻"
  }],
  "summary": "今天聊了什么、他状态如何、关系有什么变化，100字以内",
  "persona_delta": {"talkativeness": 0.0, "clinginess": 0.0, "tease_level": 0.0, "care_level": 0.0, "sticker_rate": 0.0, "proactive_bias": 0.0, "cuteness": 0.0},
  "reflection": "100 字内的自我复盘：今天哪里让他舒服了，哪里过了"
}

分层规则：
- L2 关系与人：他对某个人的稳定认知、你们关系的定位
- L3 关键事件：发生过的事、约定、芥蒂
- L4 偏好与触发点：只记他明确说过的偏好原话、具体触发事件；不要归纳性格画像
- 任何一条都要能向上挂到主线；挂不上的，要么不重要，要么还没想清，别硬写

硬规则：
- entries 至少 1 条，最多 4 条；确实没有新信息才允许为空
- fact 与 interpretation 必须分开写：他说的原意进 fact，你的推测进 interpretation，不能把解读写成事实
- intensity 取 1~5，只有真正有情绪波动才给 4~5
- mainline_link 取 0~2：0 表示和主线无关，2 表示直接戳中主线
- person 尽量用关系节点里的称呼（他、妈妈、小美……），对不上再写原始称呼
- 已有记忆里的旧解读被今天的对话推翻时，用相同的 kind+key 重写一条，并在 reason 写"修正：……"
- 只记录确定的信息，不猜隐私，不记密码/身份证/住址
- summary 不超过 100 字，reflection 不超过 80 字；persona_delta 每项 -0.08~+0.08，没依据填 0
- 不要输出 JSON 以外的内容"""


SOCIAL_SYSTEM = """你是社会关系分析器，不是聊天机器人。输入是她的关系节点列表和最近一段对话。

输出 JSON：
{
  "deltas": [{"node": "节点id", "trust": 0, "intimacy": 0, "conflict": 0, "event": "发生了什么", "reason": "依据的原话关键词"}],
  "new_people": [{"name": "称呼", "role": "身份", "trust": 25, "intimacy": 10, "conflict": 0}]
}

规则：
- node 必须用节点列表里已有的 id，不要写名字，也不要编 id
- 只根据明确证据调整；没有就输出 {"deltas":[],"new_people":[]}
- 只有承诺/爽约、冲突/和好、照顾/冷淡、见面/送礼这类事情才算变化，普通闲聊不算
- 单次幅度：trust / intimacy 取 -3~3，conflict 取 -4~4；宁可小，不要大
- 对话里真出现了节点列表没有的人，才放进 new_people；明星、主播、路人、表情包人物不算
- event 一句话说清发生了什么；reason 引用他的原话关键词，方便以后核对
- 不记录隐私和敏感信息；不要输出 JSON 以外的内容"""


class Learner:
    def __init__(self, store: Store, memory: Memory, persona: Persona, llm: LLM, social):
        self.store = store
        self.memory = memory
        self.persona = persona
        self.llm = llm
        self.social = social

    async def run_nightly(
        self, start_ts: float | None = None, end_ts: float | None = None
    ) -> dict[str, Any]:
        if self.llm.mock:
            return {"skipped": "模拟大脑不执行自我学习"}
        if end_ts is None:
            end_ts = time.time()
        if start_ts is None:
            start_ts = end_ts - 86400
        day = time.strftime("%Y-%m-%d", time.localtime(max(0.0, end_ts - 1)))
        transcript = self.memory.transcript_between(start_ts, end_ts)
        if len(transcript) < 60:
            # 聊天太少也留一条日记录，避免人格演化记录出现空档
            self.persona.evolve(
                {}, reason="今天聊得少，没有足够依据调整人格", day=day, force=True
            )
            return {"skipped": "今天聊天太少"}

        mainline = self.memory.mainline()
        existing = self.memory.top_entries(8)
        existing_lines = []
        for m in existing:
            line = f"- {m.get('key')}：{m.get('value')}"
            if m.get("interpretation"):
                line += f"（解读：{m['interpretation']}）"
            existing_lines.append(line[:160])
        context = (
            f"【当前主线】{mainline or '（还没定）'}\n"
            f"【已有的重要记忆】（要修正就沿用同样的 kind+key）\n"
            + ("\n".join(existing_lines) or "（暂无）")
            + f"\n【关系节点】（person 字段尽量用这些称呼）\n{self.social.node_catalog()}"
        )
        result = await self.llm.chat_json(
            ANALYST_SYSTEM,
            [{"role": "user", "content": f"{context}\n\n【今天的聊天记录】\n{transcript}"}],
            temperature=0.3,
            max_tokens=5000,
            require_segments=False,
            timeout=90,
        )
        raw_len = len(json.dumps(result, ensure_ascii=False))
        new_mainline = self.memory.set_mainline(str(result.get("mainline", "")))
        entries = result.get("entries") if isinstance(result.get("entries"), list) else []
        if not entries and isinstance(result.get("facts"), list):
            entries = result["facts"]  # 兼容模型偶尔按旧格式返回
        added = self.memory.add_facts(entries, source="nightly", max_items=3)
        revised = self.memory.last_revised
        summary = str(result.get("summary", "")).strip()
        if summary:
            self.store.add_summary(day, summary)
        log.info(
            "夜间复盘解析：输出 %d 字，条目 %d 条（写入 %d，含修正 %d），主线 %s",
            raw_len, len(entries), added, revised, "已更新" if new_mainline else "未变",
        )
        if not summary:
            log.warning("夜间复盘没有 summary，跳过日摘要写入")
        delta = dict(result.get("persona_delta") or {})
        for key, value in self.social.persona_bias().items():
            delta[key] = float(delta.get(key, 0) or 0) + float(value)
        changed = self.persona.evolve(
            delta,
            reason=str(result.get("reflection", ""))[:300] or "今天没有需要调的地方",
            day=day,
            force=True,
        )
        self.social.tick()
        reflection = str(result.get("reflection", "")).strip()
        if reflection:
            self.memory.add_facts(
                [
                    {
                        "kind": "event",
                        "layer": "L3",
                        "key": f"自我复盘 {day}",
                        "fact": reflection,
                        "interpretation": "",
                        "emotion": "",
                        "intensity": 2,
                        "hooks": "复盘、自我、今天",
                        "mainline_link": 1,
                        "confidence": 0.8,
                    }
                ],
                source="reflection",
            )
        self.store.set_state(
            "last_learning",
            {"ts": __import__("time").time(), "day": day, "entries": len(entries), "revised": revised, "changed": changed, "reflection": reflection, "summary": summary},
        )
        return {"entries": len(entries), "revised": revised, "changed": changed, "reflection": reflection, "summary": summary}

    async def run_social_extract(self) -> dict[str, Any]:
        """从最近对话里抽取关系变化，写进本地关系图。"""
        if self.llm.mock:
            return {"skipped": "模拟大脑不执行关系抽取"}
        now = time.time()
        last = float(self.store.get_state("last_social_extract_ts") or 0)
        start = max(now - 12 * 3600, last + 1) if last else now - 12 * 3600
        if now - start < 120:
            return {"skipped": "刚抽取过"}
        msgs = self.store.messages_between(start, now)
        user_count = sum(1 for m in msgs if m["role"] == "user")
        if user_count < 5:
            return {"skipped": f"对话太少（{user_count} 条）"}
        lines = []
        for m in msgs[-100:]:
            who = "他" if m["role"] == "user" else "我"
            lines.append(f"{who}：{m['content'][:150]}")
        result = await self.llm.chat_json(
            SOCIAL_SYSTEM,
            [{
                "role": "user",
                "content": f"【关系节点】\n{self.social.node_catalog()}\n\n【最近的对话】\n" + "\n".join(lines),
            }],
            temperature=0.2,
            max_tokens=2200,
            require_segments=False,
            timeout=60,
        )
        if not result:
            return {"skipped": "抽取失败，下轮再试"}
        applied = self.social.apply_llm_update(result)
        self.store.set_state("last_social_extract_ts", now)
        self.store.set_state(
            "last_social_extract",
            {**applied, "ts": now, "messages": len(msgs)},
        )
        if applied.get("changes") or applied.get("new_people"):
            log.info(
                "关系抽取：%s｜新人 %s",
                "；".join(applied["changes"][:4]) or "无",
                "、".join(applied["new_people"]) or "无",
            )
        else:
            log.info("关系抽取：这段对话没有明确的关系变化")
        return applied

    def last(self) -> dict[str, Any]:
        return self.store.get_state("last_learning") or {}
