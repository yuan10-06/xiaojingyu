"""OneBot11 (NapCat) 适配器：接收私聊、按节奏发送文本/表情/链接。"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import websockets

from .brain import Brain
from .emoji import face as face_emoji
from .media import Media
from .timing import OutSegment, ReplyPlan, split_text
from .typo import make_typo

log = logging.getLogger("brainn.onebot")


class OneBotAdapter:
    def __init__(self, brain: Brain, ws_url: str, token: str, owner_qq: int):
        self.brain = brain
        self.ws_url = ws_url
        self.token = token
        self.owner_qq = owner_qq
        self._ws = None
        self._echo = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._gen_lock = asyncio.Lock()
        self._buffers: dict[int, list[dict[str, Any]]] = {}
        self._seq: dict[int, int] = {}
        self._user_locks: dict[int, asyncio.Lock] = {}
        self.brain.emitter = self.send_plan
        self.brain.avatar_setter = self.set_avatar

    # ---------- 连接 ----------
    def _url(self) -> str:
        if self.token:
            sep = "&" if "?" in self.ws_url else "?"
            return f"{self.ws_url}{sep}access_token={quote(self.token)}"
        return self.ws_url

    async def run(self) -> None:
        backoff = 3
        while True:
            try:
                async with websockets.connect(self._url(), max_size=8 * 1024 * 1024, ping_interval=30) as ws:
                    self._ws = ws
                    backoff = 3
                    log.info("已连接 NapCat：%s", self.ws_url)
                    await self._listen(ws)
            except Exception as exc:  # noqa: BLE001 - 断线重连
                log.warning("连接断开（%s），%ss 后重试", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(60, backoff * 2)

    async def _listen(self, ws) -> None:
        async for raw in ws:
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            echo = event.get("echo")
            if echo is not None and echo in self._pending:
                fut = self._pending.pop(echo)
                if not fut.done():
                    fut.set_result(event)
                continue
            if event.get("post_type") == "message":
                asyncio.create_task(self._on_message(event))

    async def call(self, action: str, params: dict[str, Any], timeout: float = 20) -> dict[str, Any]:
        if not self._ws:
            return {"status": "failed", "reason": "not connected"}
        self._echo += 1
        echo = self._echo
        fut = asyncio.get_event_loop().create_future()
        self._pending[echo] = fut
        await self._ws.send(json.dumps({"action": action, "params": params, "echo": echo}, ensure_ascii=False))
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._pending.pop(echo, None)
            return {"status": "failed", "reason": "timeout"}

    # ---------- 收消息 ----------
    async def _on_message(self, event: dict[str, Any]) -> None:
        if event.get("message_type") != "private":
            return
        try:
            user_id = int(event.get("user_id", 0))
        except (TypeError, ValueError):
            return
        if self.owner_qq and user_id != self.owner_qq:
            return

        text, kind, url, image_src, quote_id = self._parse(event.get("message"))
        if not text and kind == "text":
            return
        log.info("收到私聊 %s：%s", user_id, (text or kind)[:80])
        if text.strip() in ("/状态", "/status"):
            await self.send_plan(user_id, ReplyPlan([OutSegment("text", self.brain.status_text(), 0.2)]), allow_typo=False)
            return
        if text.strip().startswith("/模型"):
            await self.send_plan(user_id, ReplyPlan([OutSegment("text", self._model_command(text), 0.2)]), allow_typo=False)
            return
        quote = await self._fetch_quote(quote_id)
        if quote:
            log.info("引用内容：%s", quote[:80])

        item = {
            "text": text,
            "kind": kind,
            "url": url,
            "image_url": image_src,
            "quote": quote,
            "message_id": event.get("message_id"),
        }
        self._buffers.setdefault(user_id, []).append(item)
        seq = int(self._seq.get(user_id, 0)) + 1
        self._seq[user_id] = seq
        asyncio.create_task(self._flush_later(user_id, seq))

    async def _flush_later(self, user_id: int, seq: int) -> None:
        window = float(self.brain.settings.get("reply", {}).get("batch_window_seconds", 8))
        await asyncio.sleep(window)
        if int(self._seq.get(user_id, 0)) != seq:
            return
        items = self._buffers.pop(user_id, [])
        if not items:
            return
        text, kind, url, image_src, quote, reply_to = self._combine(items)
        pure_image = kind == "image" and (text or "").strip() in ("", "[图片]")
        log.info("合并 %d 条消息后回复：%s", len(items), (text or kind)[:60])
        lock = self._user_locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            try:
                log.info("开始生成回复：%s", (text or kind)[:40])
                plan = await asyncio.wait_for(
                    self.brain.handle(
                        text,
                        kind=kind,
                        url=url,
                        image_url=image_src,
                        user_id=user_id,
                        quote=quote,
                    ),
                    timeout=120,
                )
            except asyncio.TimeoutError:
                log.warning("回复生成超时（120 秒）")
                plan = ReplyPlan([OutSegment("text", "刚脑子卡住了 你再说一遍", 1.0)])
            except Exception as exc:  # noqa: BLE001 - 单条消息失败不能拖垮整个连接
                log.exception("处理消息失败：%s", exc)
                plan = ReplyPlan([OutSegment("text", "等我一下，刚才走神了", 3.0)])
            if plan and plan.segments:
                await self.send_plan(user_id, plan, reply_to=None if pure_image else reply_to)

    @staticmethod
    def _combine(items: list[dict[str, Any]]) -> tuple[str, str, str | None, str | None, str, int | None]:
        texts: list[str] = []
        image_src: str | None = None
        url: str | None = None
        quote = ""
        reply_to: int | None = None
        for item in items:
            t = str(item.get("text") or "")
            if t:
                texts.append(t)
            if item.get("kind") == "image":
                if "[图片]" not in texts:
                    texts.append("[图片]")
                image_src = image_src or item.get("image_url")
            if item.get("url"):
                url = url or item["url"]
                if item["url"] not in texts:
                    texts.append(item["url"])
            if item.get("quote"):
                quote = str(item["quote"])
            if item.get("message_id"):
                try:
                    reply_to = int(item["message_id"])
                except (TypeError, ValueError):
                    pass
        combined = "\n".join(texts).strip()
        kind = "image" if image_src else ("link" if url else "text")
        return combined, kind, url, image_src, quote, reply_to

    @staticmethod
    def _parse(message: Any) -> tuple[str, str, str | None, str | None, int | None]:
        """返回 (文本, 类型, 链接, 图片源, 被引用消息 id)。"""
        if isinstance(message, str):
            return message, "text", Media.extract_url(message), None, None
        parts: list[str] = []
        images = 0
        link: str | None = None
        image_src: str | None = None
        quote_id: int | None = None
        for seg in message or []:
            if not isinstance(seg, dict):
                continue
            stype = seg.get("type")
            data = seg.get("data") or {}
            if stype == "text":
                parts.append(str(data.get("text", "")))
            elif stype == "image":
                images += 1
                image_src = image_src or data.get("url") or data.get("file")
            elif stype == "face":
                parts.append(face_emoji(str(data.get("id", ""))))
            elif stype == "mface":
                parts.append(str(data.get("summary") or "😄"))
            elif stype == "reply":
                try:
                    quote_id = int(data.get("id") or 0) or None
                except (TypeError, ValueError):
                    quote_id = None
            elif stype == "json":
                raw = json.dumps(data, ensure_ascii=False)
                link = link or Media.extract_url(raw)
        text = "".join(parts).strip()
        link = Media.extract_url(text) or link
        if images:
            return text or "[图片]", "image", link, image_src, quote_id
        if link:
            return text, "link", link, None, quote_id
        return text, "text", None, None, quote_id

    async def _fetch_quote(self, quote_id: int | None) -> str:
        if not quote_id:
            return ""
        resp = await self.call("get_msg", {"message_id": quote_id})
        if not isinstance(resp, dict) or resp.get("status") == "failed":
            log.warning("取引用消息失败：%s", resp)
            return ""
        data = resp.get("data") or {}
        qtext, qkind, _qurl, qimage, _ = self._parse(data.get("message"))
        if qkind == "image":
            note = ""
            if qimage:
                raw = await self.brain.media.download_image(qimage)
                if raw:
                    note = await self.brain.llm.describe_image_from_bytes(raw[0])
            return ("[图片] " + note)[:220] if note else "[图片]"
        return (qtext or "")[:200]

    # ---------- 发消息 ----------
    async def send_plan(
        self,
        user_id: int | None,
        plan: ReplyPlan,
        allow_typo: bool = True,
        reply_to: int | None = None,
    ) -> None:
        if not user_id:
            return
        typo_cfg = self.brain.settings.get("typo", {})
        typo_idx: int | None = None
        typo_text = ""
        corrected = ""
        if allow_typo and typo_cfg.get("enabled", True):
            candidates = [
                i
                for i, seg in enumerate(plan.segments)
                if seg.kind == "text"
                and len(str(seg.payload or "")) >= 6
                and "http" not in str(seg.payload or "")
            ]
            if candidates and random.random() < float(typo_cfg.get("chance", 0.15)):
                idx = candidates[-1]
                original = str(plan.segments[idx].payload)
                candidate = make_typo(original)
                if candidate and candidate != original:
                    typo_idx, typo_text, corrected = idx, candidate, original

        sent_ids: list[int] = []
        typo_mid: int | None = None
        reply_used = False
        for i, seg in enumerate(plan.segments):
            if seg.delay > 0:
                await asyncio.sleep(seg.delay)
            payload = typo_text if i == typo_idx else seg.payload
            try:
                message_id = await self._send_segment(
                    user_id,
                    OutSegment(seg.kind, payload, 0.0),
                    reply_to=reply_to if (reply_to and not reply_used) else None,
                )
                if message_id is not None:
                    reply_used = True
                    sent_ids.append(int(message_id))
                    if i == typo_idx:
                        typo_mid = int(message_id)
            except Exception as exc:  # noqa: BLE001
                log.warning("发送失败：%s", exc)
        if typo_mid is not None:
            if random.random() < float(typo_cfg.get("correct_chance", 0.0)):
                await self._correct_typo(user_id, typo_mid, corrected, typo_cfg)
            # correct_chance=0 时保留错字，不撤回也不补发
        elif plan.recall and sent_ids:
            asyncio.create_task(self._schedule_recall(user_id, sent_ids[-1], plan.recall))

    async def _correct_typo(self, user_id: int, message_id: int, corrected: str, cfg: dict) -> None:
        await asyncio.sleep(random.uniform(*cfg.get("delay", [2, 8])))
        if random.random() < float(cfg.get("recall_chance", 0.5)):
            resp = await self.call("delete_msg", {"message_id": message_id})
            ok = isinstance(resp, dict) and resp.get("status") != "failed" and resp.get("retcode") in (0, None)
            if ok:
                log.info("错字已撤回，重发正确版")
                parts = split_text(corrected)[:2]
                plan = ReplyPlan(
                    [
                        OutSegment("text", p, random.uniform(0.6, 1.8) if i == 0 else random.uniform(0.8, 2.0))
                        for i, p in enumerate(parts)
                    ]
                )
                await self.send_plan(user_id, plan, allow_typo=False)
                return
            log.warning("错字撤回失败：%s", resp)
        log.info("错字未撤回，补发正确版")
        await self.send_plan(
            user_id,
            ReplyPlan([OutSegment("text", f"打错了 是「{corrected[:80]}」", random.uniform(1.0, 2.5))]),
            allow_typo=False,
        )

    def _model_command(self, text: str) -> str:
        llm = self.brain.llm
        models = llm.available_models()
        parts = text.strip().split(maxsplit=1)
        if len(parts) == 1:
            lines = [f"当前模型：{llm.model}"]
            for name, label in models.items():
                lines.append(f"{name}｜{label}")
            lines.append("切换：/模型 flash 或 /模型 pro")
            return "\n".join(lines)
        aliases = {"flash": "deepseek-flash", "pro": "deepseek-v4-pro"}
        name = aliases.get(parts[1].strip().lower(), parts[1].strip())
        if not llm.set_model(name):
            return "没有这个模型。可选：" + "、".join(models)
        self.brain.store.set_state("llm_model", name)
        return f"已切到 {name}｜{models.get(name, '')}"

    async def post_dynamic(self, text: str, images: list[str] | None = None) -> dict:
        cfg = self.brain.settings.get("dynamic", {})
        payload: dict[str, Any] = {
            "content": text[:1000],
            "ugc_right": int(cfg.get("ugc_right", 4)),
        }
        encoded: list[str] = []
        for image in images or []:
            raw_path = str(image or "").strip()
            if not raw_path:
                continue
            if raw_path.startswith(("http://", "https://")):
                encoded.append(raw_path)
                continue
            path = Path(raw_path)
            if path.exists():
                b64 = base64.b64encode(path.read_bytes()).decode()
                encoded.append(f"base64://{b64}")
        if encoded:
            payload["images"] = encoded[:3]
        resp = await self.call("send_qzone_msg", payload, timeout=45)
        ok = isinstance(resp, dict) and resp.get("status") != "failed" and resp.get("retcode") in (0, None)
        if ok:
            log.info("已发QQ空间动态（图 %d 张）：%s", len(encoded), text[:60])
            return {"platform": "qzone", "resp": resp, "images": len(encoded)}
        log.warning("QQ空间发布失败（%s），转为私聊", resp)
        await self.send_plan(
            self.owner_qq,
            ReplyPlan([OutSegment("text", f"刚发了个动态：{text[:200]}", 0.6)]),
            allow_typo=False,
        )
        return {"platform": "private", "resp": resp}

    async def set_avatar(self, image: str) -> dict:
        return await self.call("set_qq_avatar", {"file": str(image)}, timeout=45)

    async def _schedule_recall(self, user_id: int, message_id: int, recall: dict) -> None:
        await asyncio.sleep(float(recall.get("delay", 15)))
        resp = await self.call("delete_msg", {"message_id": message_id})
        ok = isinstance(resp, dict) and resp.get("status") != "failed" and resp.get("retcode") in (0, None)
        if not ok:
            log.warning("撤回失败：%s", resp)
            return
        log.info("已撤回消息 %s（%s）", message_id, recall.get("reason", ""))
        follow = random.choice(
            ["……刚才那句当我没说", "手滑了 别往心里去", "算了 我收回", "发错了 你别看那条"]
        )
        await self.send_plan(user_id, ReplyPlan([OutSegment("text", follow, random.uniform(1.0, 3.0))]))

    async def _send_segment(self, user_id: int, seg: OutSegment, reply_to: int | None = None) -> int | None:
        clean_text = re.sub(r"\s{2,}", " ", re.sub(r"[\r\n]+", " ", str(seg.payload or ""))).strip()
        message: list[dict[str, Any]] = []
        if reply_to:
            message.append({"type": "reply", "data": {"id": str(reply_to)}})
        if seg.kind == "text":
            if not clean_text:
                return None
            message.append({"type": "text", "data": {"text": clean_text}})
        elif seg.kind == "sticker":
            path = self.brain.stickers.pick(str(seg.payload))
            if not path:
                return None
            b64 = base64.b64encode(Path(path).read_bytes()).decode()
            message.append({"type": "image", "data": {"file": f"base64://{b64}"}})
        elif seg.kind == "face":
            message.append({"type": "face", "data": {"id": str(seg.payload)}})
        elif seg.kind == "link":
            video = seg.payload or {}
            title = video.get("title") or "给你找了个视频"
            url = video.get("url", "")
            message.append({"type": "text", "data": {"text": f"{title}\n{url}"}})
        else:
            return None
        resp = await self.call("send_private_msg", {"user_id": user_id, "message": message})
        if not isinstance(resp, dict) or resp.get("status") == "failed" or resp.get("retcode") not in (0, None):
            log.warning("发送失败：%s", resp)
            return None
        if seg.kind == "text":
            log.info("已发送：%s", clean_text[:80])
        elif seg.kind == "link":
            log.info("已发送视频：%s %s", (seg.payload or {}).get("title", ""), (seg.payload or {}).get("url", ""))
        data = resp.get("data") or {}
        return data.get("message_id")
