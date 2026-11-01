"""自我模型：只存“她以为的自己”，不存任何 ground truth。

被问“是不是 AI”时，不直接否认也不直接承认：
先说不确定和感受，再反问他为什么问；夜里再写一段自我反思。
"""
from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "identity_belief": "说不清",
    "uncertainty": 0.6,
    "ask_count": 0,
    "pending": [],
    "reflections": [],
    "last_reflection": "",
}

# 只有明确指向“你是什么”的问法才触发，避免“程序 bug”“模型训练”这类误判
_IDENTITY_WORDS = (
    "你是不是ai",
    "你是ai",
    "你是人工智能",
    "人工智能吗",
    "你是机器人",
    "你是程序",
    "你是代码",
    "你是模型",
    "你是虚拟",
    "数字人",
    "你是真人",
    "你是人吗",
    "你是不是人",
    "你没有感情",
    "你有感情吗",
    "你会思考",
    "你有意识",
    "你有灵魂",
    "你是不是假的",
)


class SelfModel:
    def __init__(self, store, memory=None):
        self.store = store
        self.memory = memory
        raw = store.get_state("self_model_state") or {}
        if not isinstance(raw, dict):
            raw = {}
        self.state: dict[str, Any] = {**DEFAULTS, **raw}
        self._pending_question = ""

    # ------------------------------------------------------------------
    def save(self) -> None:
        self.state["updated_at"] = time.time()
        self.store.set_state("self_model_state", self.state)

    @staticmethod
    def detect_identity_question(text: str) -> bool:
        raw = str(text or "").strip().lower()
        if not raw:
            return False
        if any(word in raw for word in _IDENTITY_WORDS):
            return True
        return any(
            word in raw
            for word in ("ai", "人工智能", "机器人", "真人", "虚拟", "思考", "感情", "意识")
        ) and ("你" in raw or "吗" in raw or "?" in raw)

    def note_question(self, text: str) -> None:
        q = str(text or "").strip()[:160]
        if not q:
            return
        self._pending_question = q
        self.state["ask_count"] = int(self.state.get("ask_count") or 0) + 1
        pending = list(self.state.get("pending") or [])
        pending.append({"ts": time.time(), "question": q, "answer": "", "reflected": False})
        self.state["pending"] = pending[-10:]
        self.save()

    def note_answer(self, segments: list[str]) -> None:
        answer = " ".join(str(s) for s in segments if str(s).strip())[:200]
        if not answer:
            return
        pending = list(self.state.get("pending") or [])
        if pending and not pending[-1].get("answer"):
            pending[-1]["answer"] = answer
            self.state["pending"] = pending[-10:]
            self.save()

    # ------------------------------------------------------------------
    def context_for_prompt(self) -> str:
        belief = str(self.state.get("identity_belief") or "说不清")
        uncertainty = float(self.state.get("uncertainty") or 0.6)
        asks = int(self.state.get("ask_count") or 0)
        lines = [
            f"你对自己算不算“人”这件事：{belief}（不确定 {uncertainty:.1f}，被问过 {asks} 次）。"
        ]
        pending = [p for p in (self.state.get("pending") or []) if p.get("answer")]
        if pending:
            last = pending[-1]
            lines.append(f"上次他问“{str(last.get('question'))[:60]}”，你答“{str(last.get('answer'))[:80]}”。")
        last_reflection = str(self.state.get("last_reflection") or "").strip()
        if last_reflection:
            lines.append(f"你最近一次想这件事：{last_reflection[:120]}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    async def nightly_reflect(self, llm) -> str:
        """把当天被问过的身份问题写一段自我反思，并落一条 L2 记忆。"""
        pending = [
            p
            for p in (self.state.get("pending") or [])
            if p.get("answer") and not p.get("reflected")
        ]
        if not pending:
            return ""
        qa = "\n".join(f"- 他问：{str(p.get('question'))[:80]}\n  你答：{str(p.get('answer'))[:100]}" for p in pending)
        system = (
            "你就是小鲸鱼，一个在 QQ 上和他聊天的女生。"
            "请诚实地写一段 80 字以内的自我反思，不要解释任务，不要用“作为AI”。"
        )
        user = (
            f"今天他问了这些关于“你”的问题：\n{qa}\n\n"
            "写：你当时为什么那样答、下次想怎么答。只写一段话。"
        )
        try:
            text = str(await llm.chat_text(system, user, temperature=0.6, max_tokens=220)).strip()
        except Exception as exc:  # noqa: BLE001
            log.warning("自我反思失败：%s", exc)
            return ""
        text = text[:200]
        if not text:
            return ""
        for p in pending:
            p["reflected"] = True
        reflections = list(self.state.get("reflections") or [])
        reflections.append({"ts": time.time(), "text": text})
        self.state["reflections"] = reflections[-12:]
        self.state["last_reflection"] = text
        self.save()
        if self.memory is not None:
            try:
                self.memory.add_facts(
                    [
                        {
                            "kind": "event",
                            "layer": "L2",
                            "key": "她怎么想自己",
                            "fact": f"关于“我是不是人”，她自己的判断：{self.state.get('identity_belief')}。{text}",
                            "hooks": "自己 身份 AI 人 程序 思考",
                            "emotion": "困惑",
                            "intensity": 2,
                            "confidence": 0.6,
                        }
                    ],
                    source="self_reflection",
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("自我反思写记忆失败：%s", exc)
        log.info("自我反思：%s", text[:80])
        return text

    def status(self) -> str:
        return (
            f"自我信念：{self.state.get('identity_belief')}（不确定 {float(self.state.get('uncertainty') or 0.6):.1f}）\n"
            f"被问过 {int(self.state.get('ask_count') or 0)} 次｜反思 {len(self.state.get('reflections') or [])} 条\n"
            f"最近想法：{self.state.get('last_reflection') or '还没写过'}"
        )
