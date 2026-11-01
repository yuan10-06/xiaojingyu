"""联网内容：刷视频（B站热门/关键词搜索）、解析他转发的链接。"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import io
import logging
import random
import re
import time
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from PIL import Image

from .db import Store

log = logging.getLogger("brainn.media")

BILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
}

IMAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://image.baidu.com/",
}

URL_RE = re.compile(r"https?://[^\s\u4e00-\u9fa5]+")


def is_bilibili_video(url: str) -> bool:
    return bool(re.search(r"bilibili\.com/video/(BV[0-9A-Za-z]+)", url))


def is_video_url(url: str) -> bool:
    return any(k in url for k in ("bilibili.com/video", "douyin.com/video", "youtu.be", "youtube.com/watch"))


class Media:
    def __init__(self, store: Store, cfg: dict[str, Any], data_dir: Path | None = None):
        self.store = store
        self.cfg = cfg
        self.keywords = cfg.get("video_keywords", ["美食", "搞笑"])
        self.share_rate = float(cfg.get("video_share_rate", 0.28))
        self.cache_seconds = 1200
        base = Path(data_dir) if data_dir else Path(__file__).resolve().parent.parent / "data"
        self.data_dir = Path(base)
        self.user_images_dir = self.data_dir / "user_images"
        self.life_images_dir = self.data_dir / "life_images"
        self.avatars_dir = self.data_dir / "avatars"
        for folder in (self.user_images_dir, self.life_images_dir, self.avatars_dir):
            folder.mkdir(parents=True, exist_ok=True)

    # ---------- 刷视频 ----------
    async def _fetch_popular(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=20, headers=BILI_HEADERS) as client:
            for url, params in (
                ("https://api.bilibili.com/x/web-interface/popular", {"ps": 30, "pn": 1}),
                ("https://api.bilibili.com/x/web-interface/ranking/v2", {"rid": 0, "type": "all"}),
            ):
                try:
                    resp = await client.get(url, params=params)
                    data = resp.json()
                    raw = data.get("data", {}).get("list", [])
                    for v in raw:
                        bvid = v.get("bvid")
                        if not bvid:
                            continue
                        items.append(
                            {
                                "title": re.sub("<[^>]+>", "", str(v.get("title", ""))).strip(),
                                "url": f"https://www.bilibili.com/video/{bvid}",
                                "author": (v.get("owner") or {}).get("name", ""),
                                "desc": re.sub("<[^>]+>", "", str(v.get("desc", "")))[:80],
                                "category": v.get("tname", ""),
                                "views": (v.get("stat") or {}).get("view", 0),
                            }
                        )
                    if items:
                        break
                except Exception:
                    continue
        return items

    async def videos(self, force: bool = False) -> list[dict[str, Any]]:
        cached = self.store.get_state("video_cache") or {}
        if not force and cached.get("ts") and time.time() - cached["ts"] < self.cache_seconds:
            return cached.get("items", [])
        items = await self._fetch_popular()
        if items:
            self.store.set_state("video_cache", {"ts": time.time(), "items": items[:40]})
        return items

    def _match(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        matched = [
            v for v in items
            if any(k in (v.get("title", "") + v.get("category", "") + v.get("desc", "")) for k in self.keywords)
        ]
        return matched or items

    # ---------- 关键词搜索 ----------
    REQUEST_HINTS = ("视频", "短片", "推荐", "找个", "找点", "看点什么", "想看", "来点", "刷到")
    TOPIC_MAP = {
        "搞笑": "搞笑", "乐子": "搞笑", "沙雕": "沙雕", "整活": "整活",
        "美食": "美食", "吃": "美食", "猫": "猫", "狗": "狗",
        "游戏": "游戏", "电影": "电影解说", "鬼畜": "鬼畜", "音乐": "音乐",
        "动漫": "动漫", "帅哥": "帅哥", "美女": "美女", "学习": "学习",
    }

    def request_keyword(self, text: str) -> str | None:
        """判断是不是在要视频，并提炼搜索词。"""
        if not text or not any(w in text for w in self.REQUEST_HINTS):
            return None
        # 在评价已有的视频，不是让你找新的
        if any(w in text for w in ("你发的", "看过了", "这个视频", "那个视频", "好看吗", "怎么样")):
            return None
        for key, keyword in self.TOPIC_MAP.items():
            if key in text:
                return keyword
        cleaned = re.sub(
            r"(给我|帮我|请你|你|找|一个|个|几|点|推荐|看看|看一下|想看|视频|短片|吧|呗|啊|呀|哦|。|，|！|？|\s)",
            "",
            text,
        ).strip()
        return cleaned[:12] if 1 <= len(cleaned) <= 12 else "搞笑"

    async def search_videos(self, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
        cache_key = f"video_search_{keyword}"
        cached = self.store.get_state(cache_key) or {}
        if cached.get("ts") and time.time() - cached["ts"] < self.cache_seconds:
            return cached.get("items", [])

        items: list[dict[str, Any]] = []
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=20, headers=BILI_HEADERS) as client:
                    resp = await client.get(
                        "https://api.bilibili.com/x/web-interface/search/type",
                        params={"search_type": "video", "keyword": keyword, "page": 1},
                    )
                    data = resp.json()
                for v in (data.get("data") or {}).get("result") or []:
                    bvid = v.get("bvid")
                    if not bvid:
                        continue
                    items.append(
                        {
                            "title": html.unescape(re.sub("<[^>]+>", "", str(v.get("title", "")))).strip(),
                            "url": f"https://www.bilibili.com/video/{bvid}",
                            "author": v.get("author", ""),
                            "desc": html.unescape(re.sub("<[^>]+>", "", str(v.get("description", ""))))[:80],
                            "category": v.get("typename", ""),
                            "views": v.get("play", 0),
                        }
                    )
                if items:
                    break
            except Exception:
                items = []
            await asyncio.sleep(0.6)

        if not items:
            # 搜索失败就退回热门池里按关键词过滤
            pool = await self.videos()
            tokens = [t for t in re.split(r"\s+", keyword) if t]
            items = [
                v for v in pool
                if any(t in (v.get("title", "") + v.get("desc", "") + v.get("category", "")) for t in tokens)
            ]
        if not items:
            # 最后兜底：至少给一个热门视频，别让她编链接
            items = self._match(await self.videos())

        if items:
            # 过滤掉没人看的视频，避免分享 2 播放的冷门结果
            popular = [v for v in items if int(v.get("views") or 0) >= 500]
            items = popular or items
            items.sort(key=lambda v: int(v.get("views") or 0), reverse=True)
            self.store.set_state(cache_key, {"ts": time.time(), "items": items[:limit]})
        return items[:limit]

    async def pick_video(self, keyword: str | None = None) -> dict[str, Any] | None:
        if keyword:
            pool = await self.search_videos(keyword)
        else:
            pool = self._match(await self.videos())
        return random.choice(pool) if pool else None

    # ---------- 解析转发链接 ----------
    async def download_image(self, source: str) -> tuple[bytes, str] | None:
        """下载他发的图片，返回 (原始字节, 后缀)。"""
        s = (source or "").strip()
        if not s:
            return None
        if s.startswith("base64://"):
            try:
                return base64.b64decode(s[len("base64://") :]), ".jpg"
            except Exception:
                return None
        if s.startswith("http://") or s.startswith("https://"):
            try:
                async with httpx.AsyncClient(timeout=20, headers=BILI_HEADERS) as client:
                    resp = await client.get(s)
                    resp.raise_for_status()
                raw = resp.content
            except Exception:
                return None
            if raw.startswith(b"\x89PNG"):
                suffix = ".png"
            elif raw[:3] == b"GIF":
                suffix = ".gif"
            else:
                suffix = ".jpg"
            return raw, suffix
        if s.startswith("file://"):
            s = s[len("file://") :]
        path = Path(s)
        if path.exists():
            return path.read_bytes(), path.suffix.lower() or ".png"
        return None

    # ---------- 网上找真实生活图 / 头像 ----------
    async def search_image_urls(self, keyword: str, limit: int = 12) -> list[str]:
        """多源找图：360 → Bing → 百度；任一源有结果就返回。"""
        keyword = str(keyword or "").strip()
        if not keyword:
            return []
        try:
            async with httpx.AsyncClient(
                headers=IMAGE_HEADERS, timeout=10, follow_redirects=True
            ) as client:
                urls = self._filter_stock_urls(
                    await self._so_image_urls(client, keyword, limit)
                )
                if not urls:
                    urls = self._filter_stock_urls(
                        await self._bing_image_urls(client, keyword, limit)
                    )
                if not urls:
                    urls = self._filter_stock_urls(
                        await self._baidu_image_urls(client, keyword, limit)
                    )
                return urls
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _filter_stock_urls(urls: list[str]) -> list[str]:
        """过滤带水印的图库站，优先保留实拍/社交平台图。"""
        blocked = (
            "699pic", "nipic", "photophoto", "xpccdn", "tukuppt",
            "58pic", "16pic", "veer", "vcg.com", "gettyimages",
            "shutterstock", "dreamstime", "stock.adobe", "istockphoto",
            "depositphotos", "bigstock", "zhutu", "huitu",
        )
        return [
            str(url) for url in (urls or [])
            if url and not any(word in str(url).lower() for word in blocked)
        ]

    @staticmethod
    async def _so_image_urls(
        client: httpx.AsyncClient, keyword: str, limit: int
    ) -> list[str]:
        try:
            resp = await client.get(
                "https://image.so.com/j",
                params={"q": keyword, "src": "srp", "sn": 0, "pn": 30},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception:  # noqa: BLE001
            return []
        urls: list[str] = []
        for item in data.get("list") or []:
            if not isinstance(item, dict):
                continue
            url = item.get("img") or item.get("thumb")
            if url and str(url).startswith("http") and str(url) not in urls:
                urls.append(str(url))
        return urls[:limit]

    @staticmethod
    async def _bing_image_urls(
        client: httpx.AsyncClient, keyword: str, limit: int
    ) -> list[str]:
        try:
            resp = await client.get(
                "https://www.bing.com/images/async",
                params={
                    "q": keyword,
                    "first": 1,
                    "count": 35,
                    "mkt": "zh-CN",
                    "adlt": "off",
                },
            )
            if resp.status_code != 200:
                return []
            text = resp.text
        except Exception:  # noqa: BLE001
            return []
        urls: list[str] = []
        for raw in re.findall(r'murl&quot;:&quot;(.*?)&quot;', text):
            url = html.unescape(raw)
            if url.startswith("http") and url not in urls:
                urls.append(url)
        return urls[:limit]

    @staticmethod
    async def _baidu_image_urls(
        client: httpx.AsyncClient, keyword: str, limit: int
    ) -> list[str]:
        params = {
            "tn": "resultjson_com",
            "ipn": "rj",
            "ct": "201326592",
            "is": "",
            "fp": "result",
            "queryWord": keyword,
            "cl": "2",
            "lm": "-1",
            "ie": "utf-8",
            "oe": "utf-8",
            "word": keyword,
            "pn": "0",
            "rn": "30",
        }
        try:
            resp = await client.get("https://image.baidu.com/search/acjson", params=params)
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception:  # noqa: BLE001
            return []
        urls: list[str] = []
        for item in data.get("data") or []:
            if not isinstance(item, dict):
                continue
            url = item.get("middleURL") or item.get("hoverURL") or item.get("thumbURL")
            if url and str(url).startswith("http") and str(url) not in urls:
                urls.append(str(url))
        return urls[:limit]

    async def _download_valid_image(
        self, url: str, *, square: bool, min_side: int, max_side: int
    ) -> tuple[bytes, str] | None:
        try:
            async with httpx.AsyncClient(
                headers=IMAGE_HEADERS, timeout=10, follow_redirects=True
            ) as client:
                resp = await client.get(url)
            raw = resp.content
        except Exception:  # noqa: BLE001
            return None
        if resp.status_code != 200 or not (5000 <= len(raw) <= 3_000_000):
            return None
        try:
            image = Image.open(io.BytesIO(raw))
            width, height = image.size
            fmt = (image.format or "").upper()
        except Exception:  # noqa: BLE001
            return None
        if min(width, height) < min_side or max(width, height) > max_side:
            return None
        ratio = width / height
        if square and not (0.8 <= ratio <= 1.25):
            return None
        if not square and not (0.55 <= ratio <= 1.9):
            return None
        suffix = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp"}.get(fmt)
        if not suffix:
            return None
        return raw, suffix

    def _save_image(self, raw: bytes, suffix: str, folder: Path, prefix: str) -> Path:
        digest = hashlib.md5(raw).hexdigest()[:10]
        path = folder / f"{prefix}_{digest}{suffix}"
        if not path.exists():
            path.write_bytes(raw)
        return path

    def image_keyword_for_text(self, text: str) -> str:
        """按动态正文选配图关键词，避免“麻辣烫”配成炸土豆。"""
        t = str(text or "")
        mapping = (
            ("麻辣烫", "麻辣烫 实拍"),
            ("奶茶", "奶茶 实拍"),
            ("咖啡", "咖啡 实拍"),
            ("蛋糕", "蛋糕 实拍"),
            ("炸鸡", "炸鸡 实拍"),
            ("烧烤", "烧烤 实拍"),
            ("火锅", "火锅 实拍"),
            ("米线", "米线 实拍"),
            ("面条", "面条 实拍"),
            ("炒饭", "炒饭 实拍"),
            ("食堂", "大学食堂 饭菜 实拍"),
            ("夜宵", "夜宵 小吃 实拍"),
            ("早餐", "早餐 实拍"),
            ("图书馆", "大学图书馆 桌面 实拍"),
            ("实验室", "大学实验室 实拍"),
            ("实验", "大学实验室 实拍"),
            ("教室", "大学教室 实拍"),
            ("上课", "大学教室 实拍"),
            ("宿舍", "大学宿舍 实拍"),
            ("晚霞", "城市 晚霞 天空 实拍"),
            ("下雨", "雨天 窗外 实拍"),
            ("猫", "校园 流浪猫 实拍"),
            ("快递", "快递 包裹 实拍"),
            ("水果", "水果 实拍"),
        )
        for word, keyword in mapping:
            if word in t:
                return keyword
        return ""

    async def pick_life_image(self, keyword: str, count: int = 1) -> list[Path]:
        """按关键词找生活实拍图，下载并保存；失败返回空列表，绝不编图。"""
        keyword = str(keyword or "").strip()
        if not keyword:
            return []
        urls = await self.search_image_urls(keyword, limit=16)
        result: list[Path] = []
        for url in urls:
            if len(result) >= count:
                break
            item = await self._download_valid_image(
                url, square=False, min_side=300, max_side=1600
            )
            if not item:
                continue
            raw, suffix = item
            path = self._save_image(raw, suffix, self.life_images_dir, "life")
            if path not in result:
                result.append(path)
        return result

    async def pick_avatar_image(self, keyword: str) -> Path | None:
        """找一张方形卡通头像；下载失败返回 None。"""
        keyword = str(keyword or "").strip()
        if not keyword:
            return None
        urls = await self.search_image_urls(keyword, limit=20)
        for url in urls:
            item = await self._download_valid_image(
                url, square=True, min_side=200, max_side=1200
            )
            if not item:
                continue
            raw, suffix = item
            return self._save_image(raw, suffix, self.avatars_dir, "avatar")
        return None

    def save_user_image(self, raw: bytes, suffix: str = ".jpg") -> str:
        """把他发的图原样存下来，不覆盖、不压缩。"""
        if not raw:
            return ""
        month = time.strftime("%Y-%m")
        folder = self.user_images_dir / month
        folder.mkdir(parents=True, exist_ok=True)
        path = self._save_image(raw, suffix or ".jpg", folder, time.strftime("%Y%m%d_%H%M%S"))
        log_state = list(self.store.get_state("user_image_log") or [])
        log_state.append({"path": str(path), "ts": time.time(), "size": len(raw)})
        self.store.set_state("user_image_log", log_state[-200:])
        log.info("已保存他发的图片：%s", path)
        return str(path)

    async def link_context(self, url: str) -> dict[str, Any]:
        ctx: dict[str, Any] = {"url": url, "title": "", "desc": "", "text": "", "kind": "link"}
        bv = re.search(r"bilibili\.com/video/(BV[0-9A-Za-z]+)", url)
        try:
            async with httpx.AsyncClient(timeout=20, headers=BILI_HEADERS) as client:
                if bv:
                    resp = await client.get("https://api.bilibili.com/x/web-interface/view", params={"bvid": bv.group(1)})
                    data = resp.json().get("data") or {}
                    ctx.update(
                        kind="video",
                        title=data.get("title", ""),
                        desc=str(data.get("desc", ""))[:300],
                        author=(data.get("owner") or {}).get("name", ""),
                        duration=data.get("duration", 0),
                    )
                    return ctx
                resp = await client.get(url)
                html = resp.text[:400000]
            soup = BeautifulSoup(html, "html.parser")
            title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
            meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
            desc = (meta.get("content", "") if meta else "").strip()
            paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")[:8]]
            ctx.update(kind="web", title=title[:120], desc=desc[:300], text="\n".join(paras)[:600])
        except Exception as exc:  # noqa: BLE001 - 抓不到就按纯链接处理
            ctx["error"] = str(exc)[:120]
        return ctx

    @staticmethod
    def extract_url(text: str) -> str | None:
        m = URL_RE.search(text)
        return m.group(0).rstrip("，。,.）)") if m else None
