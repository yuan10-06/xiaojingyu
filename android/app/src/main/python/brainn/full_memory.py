"""全量记忆 · 增援未来。

开启（默认）后，在应用目录 data/full_memory 下把整个人格的记忆与状态留档：
  chat-YYYY-MM-DD.jsonl    聊天原文（你和她，含表情包/媒体标记）
  mind-YYYY-MM-DD.jsonl    每轮心智快照（心情、身体）
  persona.json             人格配置与旋钮快照（变化时覆盖）
  status.json              留档状态

只写不读：检索、上下文和提示词完全照常；正常记忆的权重衰减、归档和账本清理也照常运行，
全量留档只是额外备份，不改变遗忘策略。关闭后停止新增留档，已留档的文件保留不动。
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import logging

log = logging.getLogger(__name__)


class FullMemory:
    def __init__(
        self,
        data_dir: Path,
        enabled: bool = True,
        directory: Path | str | None = None,
    ):
        self.dir = Path(directory) if directory else Path(data_dir) / "full_memory"
        self.enabled = bool(enabled)
        self._lock = threading.Lock()
        self._last_persona = 0.0
        self._persona_sig = ""
        if self.enabled:
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
            except Exception:  # noqa: BLE001
                log.warning("全量记忆目录创建失败", exc_info=True)

    # ------------------------------------------------------------------
    def set_directory(self, directory: Path | str, copy_existing: bool = True) -> dict[str, Any]:
        """切换留档目录：先把旧目录里的档案复制过去（同名不覆盖），再切新目录。"""
        new_dir = Path(directory)
        old_dir = self.dir
        copied = 0
        failed = 0
        try:
            new_dir.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            log.warning("全量记忆新目录创建失败：%s", new_dir, exc_info=True)
            return {"dir": str(old_dir), "copied": 0, "failed": 0}
        if copy_existing and old_dir != new_dir and old_dir.exists():
            with self._lock:
                for item in old_dir.iterdir():
                    if not item.is_file():
                        continue
                    target = new_dir / item.name
                    if target.exists():
                        continue
                    try:
                        shutil.copy2(item, target)
                        copied += 1
                    except OSError:
                        failed += 1
        self.dir = new_dir
        if self.enabled:
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
            except Exception:  # noqa: BLE001
                pass
        return {"dir": str(new_dir), "copied": copied, "failed": failed}

    def set_enabled(self, on: bool) -> None:
        self.enabled = bool(on)
        if self.enabled:
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
            except Exception:  # noqa: BLE001
                log.warning("全量记忆目录创建失败", exc_info=True)

    def _day_path(self, kind: str, now: float | None = None) -> Path:
        day = time.strftime("%Y-%m-%d", time.localtime(now or time.time()))
        return self.dir / f"{kind}-{day}.jsonl"

    def _append(self, kind: str, row: dict[str, Any]) -> None:
        if not self.enabled:
            return
        path = self._day_path(kind)
        with self._lock:
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            except Exception:  # noqa: BLE001
                log.warning("全量记忆写入失败：%s", path, exc_info=True)

    # ------------------------------------------------------------------
    def on_message(self, row: dict[str, Any]) -> None:
        """Store.add_message 的钩子：每条聊天原文都留档。"""
        if not self.enabled:
            return
        text = str(row.get("content") or "")
        if not text.strip():
            return
        self._append(
            "chat",
            {
                "id": int(row.get("id") or 0),
                "role": str(row.get("role") or ""),
                "content": text,
                "kind": str(row.get("kind") or "text"),
                "media": str(row.get("media") or ""),
                "session": str(row.get("session") or "main"),
                "ts": float(row.get("ts") or time.time()),
            },
        )

    def backfill_messages(self, rows: list[dict[str, Any]]) -> int:
        """把开启前的历史聊天按日期补进 chat-YYYY-MM-DD.jsonl，已存在的 id 跳过。"""
        if not self.enabled or not rows:
            return 0
        by_day: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            text = str(row.get("content") or "")
            if not text.strip():
                continue
            day = time.strftime(
                "%Y-%m-%d", time.localtime(float(row.get("ts") or time.time()))
            )
            by_day.setdefault(day, []).append(row)
        added = 0
        with self._lock:
            for day, items in by_day.items():
                path = self.dir / f"chat-{day}.jsonl"
                existing: set[int] = set()
                if path.exists():
                    try:
                        for line in path.read_text(encoding="utf-8").splitlines():
                            if not line.strip():
                                continue
                            try:
                                obj = json.loads(line)
                                existing.add(int(obj.get("id") or 0))
                            except Exception:  # noqa: BLE001
                                # 单行损坏只跳过这一行，不能把已有 id 清空后整批重写
                                continue
                    except Exception:  # noqa: BLE001
                        existing = set()
                try:
                    self.dir.mkdir(parents=True, exist_ok=True)
                    with path.open("a", encoding="utf-8") as fh:
                        for row in items:
                            mid = int(row.get("id") or 0)
                            if mid and mid in existing:
                                continue
                            fh.write(
                                json.dumps(
                                    {
                                        "id": mid,
                                        "role": str(row.get("role") or ""),
                                        "content": str(row.get("content") or ""),
                                        "kind": str(row.get("kind") or "text"),
                                        "media": str(row.get("media") or ""),
                                        "session": str(row.get("session") or "main"),
                                        "ts": float(row.get("ts") or time.time()),
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n"
                            )
                            if mid:
                                existing.add(mid)
                            added += 1
                except Exception:  # noqa: BLE001
                    log.warning("全量记忆补历史失败：%s", path, exc_info=True)
        return added

    def capture_turn(
        self,
        mood: dict[str, Any],
        body: str,
        persona_cfg: dict[str, Any] | None = None,
        knobs: dict[str, Any] | None = None,
    ) -> None:
        """每轮回复后记一份心智快照；人格变化时覆盖 persona.json。"""
        if not self.enabled:
            return
        snap = {"ts": time.time(), "mood": mood, "body": str(body or "")}
        self._append("mind", snap)
        self._snapshot_persona(persona_cfg, knobs)

    def _snapshot_persona(
        self, persona_cfg: dict[str, Any] | None, knobs: dict[str, Any] | None
    ) -> None:
        if not persona_cfg:
            return
        try:
            payload = {"persona": persona_cfg, "knobs": knobs or {}, "saved_at": time.time()}
            sig = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:  # noqa: BLE001
            return
        now = time.time()
        if sig == self._persona_sig and now - self._last_persona < 600:
            return
        with self._lock:
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
                (self.dir / "persona.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=1, default=str),
                    encoding="utf-8",
                )
                self._persona_sig = sig
                self._last_persona = now
            except Exception:  # noqa: BLE001
                log.warning("人格快照写入失败", exc_info=True)

    # ------------------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        out: dict[str, Any] = {"on": self.enabled, "dir": str(self.dir), "files": 0, "bytes": 0}
        if not self.dir.exists():
            return out
        files = 0
        size = 0
        latest = 0.0
        try:
            for path in self.dir.iterdir():
                if not path.is_file():
                    continue
                files += 1
                size += path.stat().st_size
                latest = max(latest, path.stat().st_mtime)
        except Exception:  # noqa: BLE001
            log.warning("全量记忆统计失败", exc_info=True)
        out.update({"files": files, "bytes": size, "updated_at": latest})
        return out
