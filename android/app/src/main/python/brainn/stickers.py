"""表情包：只使用真实网络图库（偷来的 + 在线抓取），不再本地生成。"""
from __future__ import annotations

import asyncio
import hashlib
import html
import io
import json
import random
import re
import time
from pathlib import Path

import httpx
from PIL import Image

VERSION = 3

EMOTIONS = {
    "happy": {"face": 13},
    "shy": {"face": 6},
    "angry": {"face": 11},
    "sad": {"face": 15},
    "hungry": {"face": 24},
    "sleepy": {"face": 25},
    "tease": {"face": 178},
    "miss": {"face": 42},
    "proud": {"face": 4},
    "confused": {"face": 32},
    "ok": {"face": 76},
    "refuse": {"face": 103},
    "laugh": {"face": 180},
    "speechless": {"face": 132},
    "popcorn": {"face": 164},
    "aggrieved": {"face": 106},
}

ONLINE_KEYWORDS = {
    "happy": "开心 卡通 表情包",
    "shy": "害羞 卡通 表情包",
    "angry": "生气 卡通 表情包",
    "sad": "难过 卡通 表情包",
    "hungry": "干饭 卡通 表情包",
    "sleepy": "困 卡通 表情包",
    "tease": "就这 卡通 表情包",
    "miss": "想你 卡通 表情包",
    "proud": "得意 卡通 表情包",
    "confused": "问号 卡通 表情包",
    "ok": "OK 卡通 表情包",
    "refuse": "拒绝 卡通 表情包",
    "laugh": "笑死 卡通 表情包",
    "speechless": "无语 卡通 表情包",
    "popcorn": "吃瓜 卡通 表情包",
    "aggrieved": "委屈 卡通 表情包",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://image.baidu.com/",
}


class Stickers:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.online_dir = self.dir / "online"
        self.online_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.dir / "manifest.json"
        self.manifest: dict[str, list[str]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.ensure()

    # ---------- 清单 ----------
    def ensure(self) -> None:
        raw: dict = {}
        if self.manifest_path.exists():
            try:
                raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                raw = {}
        if isinstance(raw, dict):
            raw.pop("_version", None)
        self.manifest = {}
        if isinstance(raw, dict):
            for tag, paths in raw.items():
                if tag not in EMOTIONS or not isinstance(paths, list):
                    continue
                good = [str(p) for p in paths if self._usable(p)]
                if good:
                    self.manifest[tag] = good
        self._scan_online()
        self._save()

    def _save(self) -> None:
        payload = {"_version": VERSION, **self.manifest}
        self.manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _usable(self, path: str | Path) -> bool:
        p = Path(path)
        if not p.exists() or p.parent.name == "custom":
            return False
        return "stolen" in p.stem or "online" in p.stem

    def _scan_online(self) -> None:
        """清单里的绝对路径失效时（换电脑/换手机），按文件名重新认领 online 表情。"""
        for f in sorted(self.online_dir.iterdir()):
            if f.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                continue
            stem = f.stem
            tag = stem.split("_online_")[0] if "_online_" in stem else stem.split("_")[0]
            if tag not in EMOTIONS:
                continue
            bucket = self.manifest.setdefault(tag, [])
            if str(f) not in bucket:
                bucket.append(str(f))

    # ---------- 偷表情包 ----------
    TAG_WORDS = {
        "laugh": ("笑", "哈哈", "绷", "乐死", "搞笑"),
        "speechless": ("无语", "服了", "沉默", "啊这", "离谱"),
        "angry": ("气", "怒", "骂", "凶"),
        "aggrieved": ("委屈", "哭", "难过", "哄"),
        "shy": ("害羞", "脸红", "可爱", "贴贴"),
        "popcorn": ("吃瓜", "看戏", "围观", "八卦"),
        "hungry": ("饿", "吃", "干饭", "馋"),
        "sleepy": ("困", "睡", "晚安"),
        "miss": ("想", "爱", "心", "等你"),
        "tease": ("嘲", "损", "菜", "阴阳"),
    }

    def guess_tag(self, description: str) -> str:
        for tag, words in self.TAG_WORDS.items():
            if any(w in description for w in words):
                return tag
        return "happy"

    def save_stolen(self, raw: bytes, suffix: str, description: str) -> str:
        """把他发的表情包存进图库，返回归类的情绪 tag。"""
        tag = self.guess_tag(description)
        if tag not in EMOTIONS:
            tag = "happy"
        path = self.online_dir / f"{tag}_stolen_{int(time.time() * 1000)}{suffix}"
        try:
            path.write_bytes(raw)
        except OSError:
            return ""
        self.manifest.setdefault(tag, []).append(str(path))
        self._save()
        return tag

    # ---------- 在线抓取 ----------
    async def ensure_online(self, tag: str, count: int = 2) -> int:
        """从网络图库补图；同一情绪已有几张就跳过。"""
        if not tag or tag not in EMOTIONS:
            return 0
        existing = [
            p for p in (self.manifest.get(tag) or [])
            if "online" in Path(p).stem or "stolen" in Path(p).stem
        ]
        if len(existing) >= max(3, count):
            return 0
        lock = self._locks.setdefault(tag, asyncio.Lock())
        async with lock:
            existing = [
                p for p in (self.manifest.get(tag) or [])
                if "online" in Path(p).stem or "stolen" in Path(p).stem
            ]
            if len(existing) >= max(3, count):
                return 0
            keyword = ONLINE_KEYWORDS.get(tag, "表情包 卡通")
            downloaded = 0
            try:
                async with httpx.AsyncClient(headers=HEADERS, timeout=8, follow_redirects=True) as client:
                    urls = await self._search_urls(client, keyword)
                    for url in urls:
                        if downloaded >= count:
                            break
                        try:
                            resp = await client.get(url)
                            raw = resp.content
                            if resp.status_code != 200 or not (5000 <= len(raw) <= 2_000_000):
                                continue
                            if not self._valid_image(raw):
                                continue
                            suffix = self._suffix(raw, resp.headers.get("content-type"))
                            if not suffix:
                                continue
                            digest = hashlib.md5(raw).hexdigest()[:10]
                            path = self.online_dir / f"{tag}_online_{digest}{suffix}"
                            if path.exists():
                                continue
                            path.write_bytes(raw)
                            self.manifest.setdefault(tag, []).append(str(path))
                            downloaded += 1
                        except Exception:  # noqa: BLE001 - 单张图失败不影响其它
                            continue
            except Exception:  # noqa: BLE001 - 搜索失败时保持原图库
                return 0
            if downloaded:
                self._save()
            return downloaded

    async def prefetch(self, per_tag: int = 1) -> int:
        """后台慢慢补图，不阻塞聊天；返回本轮新增张数。"""
        total = 0
        for tag in EMOTIONS:
            try:
                total += await self.ensure_online(tag, per_tag)
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(0.4)
        return total

    async def _search_urls(self, client: httpx.AsyncClient, keyword: str) -> list[str]:
        """多源找图：360 → Bing → 百度，百度被反爬时仍能补图。"""
        for finder in (self._so_urls, self._bing_urls, self._baidu_urls):
            try:
                urls = await finder(client, keyword)
            except Exception:  # noqa: BLE001
                urls = []
            if urls:
                return urls
        return []

    @staticmethod
    async def _so_urls(client: httpx.AsyncClient, keyword: str) -> list[str]:
        resp = await client.get(
            "https://image.so.com/j",
            params={"q": keyword, "src": "srp", "sn": 0, "pn": 30},
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        urls: list[str] = []
        for item in data.get("list") or []:
            if not isinstance(item, dict):
                continue
            url = item.get("img") or item.get("thumb")
            if url and str(url).startswith("http") and str(url) not in urls:
                urls.append(str(url))
        return urls[:12]

    @staticmethod
    async def _bing_urls(client: httpx.AsyncClient, keyword: str) -> list[str]:
        resp = await client.get(
            "https://www.bing.com/images/async",
            params={"q": keyword, "first": 1, "count": 35, "mkt": "zh-CN", "adlt": "off"},
        )
        if resp.status_code != 200:
            return []
        urls: list[str] = []
        for raw in re.findall(r'murl&quot;:&quot;(.*?)&quot;', resp.text):
            url = html.unescape(raw)
            if url.startswith("http") and url not in urls:
                urls.append(url)
        return urls[:12]

    async def _baidu_urls(self, client: httpx.AsyncClient, keyword: str) -> list[str]:
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
        resp = await client.get("https://image.baidu.com/search/acjson", params=params)
        if resp.status_code != 200:
            return []
        data = resp.json()
        urls: list[str] = []
        for item in data.get("data") or []:
            if not isinstance(item, dict):
                continue
            url = item.get("middleURL") or item.get("thumbURL")
            if url and str(url).startswith("http"):
                urls.append(str(url))
        return urls[:12]

    @staticmethod
    def _valid_image(raw: bytes) -> bool:
        try:
            img = Image.open(io.BytesIO(raw))
            width, height = img.size
        except Exception:  # noqa: BLE001
            return False
        if width < 100 or height < 100 or width > 900 or height > 900:
            return False
        return 0.45 <= width / height <= 2.2

    @staticmethod
    def _suffix(raw: bytes, content_type: str | None) -> str:
        ct = (content_type or "").lower()
        if "gif" in ct:
            return ".gif"
        if "png" in ct:
            return ".png"
        if "webp" in ct:
            return ".webp"
        if "jpeg" in ct or "jpg" in ct:
            return ".jpg"
        try:
            fmt = Image.open(io.BytesIO(raw)).format or ""
        except Exception:  # noqa: BLE001
            return ""
        return {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp"}.get(fmt, "")

    # ---------- 取图 ----------
    def pick(self, tag: str | None) -> Path | None:
        pool = [p for p in (self.manifest.get(tag or "") or []) if self._usable(p)]
        stolen = [p for p in pool if "stolen" in Path(p).stem]
        if stolen and random.random() < 0.35:
            pool = stolen
        online = [p for p in pool if "online" in Path(p).stem]
        if online and random.random() < 0.35:
            pool = online
        if not pool:
            for other in ("tease", "happy", "laugh", "speechless"):
                pool = [p for p in (self.manifest.get(other) or []) if self._usable(p)]
                if pool:
                    break
        return Path(random.choice(pool)) if pool else None

    @staticmethod
    def face_id(tag: str | None) -> str | None:
        if not tag:
            return None
        spec = EMOTIONS.get(tag)
        return str(spec["face"]) if spec else None
