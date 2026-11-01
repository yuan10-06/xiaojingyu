"""互联网冲浪：热榜、网页搜索、页面摘要。

只做公开页面的轻量抓取，不登录、不调用付费 API。
普通聊天不触发网络请求；只有他明确让你搜/看热搜，或主动消息需要素材时才用。
"""
from __future__ import annotations

import asyncio
import html
import logging
import random
import re
import time
from typing import Any
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from .db import Store
from .media import Media

log = logging.getLogger("brainn.web")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 人设有禁忌：政治、军事、灾难、血腥、违法内容不进感知
BLOCK_WORDS = (
    "总书记", "主席", "总理", "总统", "首相", "防长", "外长", "部长", "省长", "市长",
    "书记", "领导", "访问", "会见", "会谈", "外交", "国防", "军事", "军机", "军方",
    "军队", "子弟兵", "战区", "导弹", "战机", "舰", "制裁", "关税", "出口", "经济",
    "GDP", "CPI", "政策", "新规", "医保", "养老金", "楼市", "股市", "芯片",
    "金正恩", "特朗普", "拜登", "普京", "泽连斯基", "美国", "日本", "朝鲜", "俄罗斯",
    "乌克兰", "以色列", "伊朗", "菲律宾", "台海", "南海", "台湾", "台独",
    "战争", "俄乌", "地震", "震区", "灾区", "洪水", "火灾", "事故", "相撞", "坠机",
    "车祸", "爆炸", "起火", "死亡", "遇难", "伤亡", "失联", "遗体", "尸体",
    "凶杀", "强奸", "嫌犯", "警方", "通报", "判刑", "法院", "检察", "纪委", "落马",
    "反腐", "色情", "赌博", "毒品", "违法", "犯罪", "疫情", "肺炎",
)

TRENDING_HINTS = ("热搜", "冲浪", "网上新闻", "今天新闻", "最近新闻", "网上有什么", "网上都在说")
SEARCH_HINTS = (
    "搜一下", "搜搜", "搜索", "查一下", "查查", "帮我查", "帮我搜", "你搜",
    "你查", "百度一下", "上网查", "上网看看", "网上搜",
)


def _safe(title: str) -> bool:
    text = str(title or "").strip()
    if not text:
        return False
    return not any(word in text for word in BLOCK_WORDS)


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", html.unescape(str(text or ""))).strip()
    # Bing 会把 <strong> 拆成独立词，中文与中文/数字/字母之间不要留空格
    text = re.sub(r"(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5A-Za-z0-9])", "", text)
    return re.sub(r"(?<=[A-Za-z0-9])\s+(?=[\u4e00-\u9fa5])", "", text)


class WebSurf:
    def __init__(self, store: Store, cfg: dict[str, Any], media: Media):
        self.store = store
        self.cfg = cfg or {}
        self.media = media
        self.enabled = bool(self.cfg.get("enabled", True))
        self.cache_seconds = float(self.cfg.get("cache_minutes", 45)) * 60
        self.max_items = int(self.cfg.get("max_items", 8))
        self.timeout = float(self.cfg.get("search_timeout", 8))
        self.proactive_chance = float(self.cfg.get("proactive_chance", 0.35))

    # ---------- 热搜 / 热门内容 ----------
    async def _toutiao(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=HEADERS) as client:
                resp = await client.get(
                    "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
                )
                data = resp.json()
            for row in data.get("data") or []:
                title = _clean(row.get("Title"))
                if not _safe(title):
                    continue
                items.append(
                    {
                        "title": title,
                        "url": str(row.get("Url") or ""),
                        "source": "头条",
                        "hot": row.get("HotValue") or 0,
                    }
                )
        except Exception as exc:  # noqa: BLE001
            log.info("头条热榜抓取失败：%s", str(exc)[:120])
        return items

    async def _baidu(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=HEADERS) as client:
                resp = await client.get("https://top.baidu.com/board?tab=realtime")
            words = re.findall(r'"word":"([^"]+)"', resp.text)
            for title in words:
                title = _clean(title)
                if not _safe(title):
                    continue
                items.append(
                    {
                        "title": title,
                        "url": f"https://www.baidu.com/s?wd={quote(title)}",
                        "source": "百度",
                    }
                )
        except Exception as exc:  # noqa: BLE001
            log.info("百度热榜抓取失败：%s", str(exc)[:120])
        return items

    async def _bili(self, force: bool) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        try:
            videos = await self.media.videos(force=force)
            for v in videos:
                title = _clean(v.get("title"))
                if not _safe(title):
                    continue
                items.append(
                    {
                        "title": title,
                        "url": v.get("url", ""),
                        "source": "B站",
                        "desc": v.get("desc", ""),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            log.info("B站热门抓取失败：%s", str(exc)[:120])
        return items

    async def trending(self, force: bool = False) -> list[dict[str, Any]]:
        cached = self.store.get_state("web_trending") or {}
        if not force and cached.get("ts") and time.time() - cached["ts"] < self.cache_seconds:
            return list(cached.get("items") or [])

        groups = list(await asyncio.gather(self._toutiao(), self._baidu()))
        if force or sum(len(g) for g in groups) < self.max_items:
            groups.append(await self._bili(force))
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        # 每个来源轮流取，避免被单一榜单占满
        for index in range(max((len(g) for g in groups), default=0)):
            for group in groups:
                if index >= len(group):
                    continue
                item = group[index]
                title = item.get("title", "")
                if not title or title in seen:
                    continue
                seen.add(title)
                items.append(item)
                if len(items) >= self.max_items * 2:
                    break
            if len(items) >= self.max_items * 2:
                break

        if items:
            self.store.set_state(
                "web_trending", {"ts": time.time(), "items": items[: self.max_items * 2]}
            )
        return items[: self.max_items]

    # ---------- 搜索 ----------
    async def _bing(self, query: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        url = "https://www.bing.com/search"
        params = {"q": query, "setlang": "zh-CN", "count": 10}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=HEADERS, follow_redirects=True) as client:
                resp = await client.get(url, params=params)
            soup = BeautifulSoup(resp.text, "html.parser")
            for li in soup.select("li.b_algo")[:8]:
                a = li.select_one("h2 a")
                if not a:
                    continue
                title = _clean(a.get_text(" ", strip=True))
                if not _safe(title):
                    continue
                href = str(a.get("href") or "")
                p = li.select_one("p")
                desc = _clean(p.get_text(" ", strip=True)) if p else ""
                items.append(
                    {"title": title, "url": href, "source": "网页", "desc": desc[:120]}
                )
        except Exception as exc:  # noqa: BLE001
            log.info("Bing 搜索失败：%s", str(exc)[:120])
        return items

    async def search(self, query: str) -> list[dict[str, Any]]:
        q = str(query or "").strip()
        if not q:
            return []
        cache_key = f"web_search_{q[:24]}"
        cached = self.store.get_state(cache_key) or {}
        if cached.get("ts") and time.time() - cached["ts"] < self.cache_seconds:
            return list(cached.get("items") or [])

        items = await self._bing(q)
        if not items:
            # 搜索兜底：B站关键词结果（至少是真实可点的链接）
            try:
                videos = await self.media.search_videos(q, limit=8)
                items = [
                    {
                        "title": _clean(v.get("title")),
                        "url": v.get("url", ""),
                        "source": "B站",
                        "desc": v.get("desc", ""),
                    }
                    for v in videos
                    if _safe(v.get("title"))
                ]
            except Exception:  # noqa: BLE001
                items = []
        if items:
            self.store.set_state(cache_key, {"ts": time.time(), "items": items[:8]})
        return items[:8]

    # ---------- 意图 ----------
    @staticmethod
    def request_kind(text: str) -> tuple[str | None, str]:
        raw = str(text or "").strip()
        if not raw:
            return None, ""
        if any(word in raw for word in TRENDING_HINTS):
            return "trending", ""
        if not any(word in raw for word in SEARCH_HINTS):
            return None, ""
        cleaned = re.sub(
            r"(帮我|给我|请你|你|我|搜一下|搜搜|搜索|查一下|查查|百度一下|上网查|"
            r"上网看看|网上搜|一下|看看|查|搜|吧|呗|啊|呀|呢|？|。|，|！|\s)",
            "",
            raw,
        ).strip()
        if len(cleaned) < 1:
            cleaned = raw[:24]
        return "search", cleaned[:30]

    async def context(self, text: str) -> dict[str, Any]:
        """按他的请求抓取真实内容；失败返回空，不编造。"""
        kind, query = self.request_kind(text)
        if not kind:
            return {"kind": "", "query": "", "items": [], "text": ""}
        items = await self.trending() if kind == "trending" else await self.search(query)
        if not items:
            return {"kind": kind, "query": query, "items": [], "text": ""}
        lines = []
        for index, item in enumerate(items[:3], 1):
            title = item.get("title", "")
            source = item.get("source", "")
            desc = str(item.get("desc") or "")[:60]
            lines.append(
                f"{index}. {title}（{source}）" + (f"：{desc}" if desc else "")
            )
        label = "你刚刷到的热搜/热门" if kind == "trending" else f"你刚搜「{query}」看到的"
        return {
            "kind": kind,
            "query": query,
            "items": items,
            "text": f"\n【{label}】\n" + "\n".join(lines),
        }

    # ---------- 主动素材 ----------
    def recent_items(self, limit: int = 6) -> list[dict[str, Any]]:
        cached = self.store.get_state("web_surf") or {}
        items = list(cached.get("items") or [])
        return items[:limit]

    async def surf(self) -> list[dict[str, Any]]:
        items = await self.trending(force=True)
        if items:
            self.store.set_state(
                "web_surf", {"ts": time.time(), "items": items[: self.max_items]}
            )
            self.store.set_state("last_web_surf", time.time())
        return items

    async def pick_for_proactive(self, topic: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        items = self.recent_items()
        if not items:
            items = await self.surf()
        if not items:
            return None
        if any(word in topic for word in ("热搜", "网上", "冲浪", "新闻")):
            return random.choice(items)
        if random.random() < self.proactive_chance:
            return random.choice(items)
        return None

    def status(self) -> dict[str, Any]:
        cached = self.store.get_state("web_surf") or {}
        items = cached.get("items") or []
        return {
            "enabled": self.enabled,
            "count": len(items),
            "last_surf": float(cached.get("ts") or 0),
            "titles": [item.get("title", "") for item in items[:3]],
        }
