"""小鲸鱼专属 BrainN：独立人设、独立数据库、独立实例，与聊天完全隔离。

- 只有鲸鱼页「智能」开关打开时才会启动；
- 不挂调度器/主动消息，不写聊天库，不向聊天页推送事件；
- 共用模型 Key 与网络能力，其余状态各自独立。
"""
from __future__ import annotations

import asyncio
import copy
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

import yaml
from .qt.insertion import run as run_insertion
from .qt.omc import card_fields, instance_id

log = logging.getLogger(__name__)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class WhaleBrain:
    def __init__(
        self,
        root: Path,
        base_settings: dict[str, Any],
        shared_data_dir: Path | None = None,
        shared_persona: dict[str, Any] | None = None,
        shared_persona_path: Path | None = None,
    ):
        self.dir = Path(root) / "whale_brain"
        # 合并模式：数据目录、人格、记忆、心情、身体全部与主聊天共用同一个库，
        # 两个入口背后是同一个存在，不再是两个实例。
        self.shared_data_dir = Path(shared_data_dir) if shared_data_dir else None
        self.shared_persona = copy.deepcopy(shared_persona) if shared_persona else None
        self.shared_persona_path = Path(shared_persona_path) if shared_persona_path else None
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "data").mkdir(parents=True, exist_ok=True)
        (self.dir / "assets" / "stickers").mkdir(parents=True, exist_ok=True)
        self.base_settings = copy.deepcopy(base_settings or {})
        self.app = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.thread: threading.Thread | None = None
        self.starting = False
        self.error = ""
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._chat_lock = threading.Lock()
    # ---------- 人设（只保留主聊天那一份） ----------
    def persona(self) -> dict[str, Any]:
        return copy.deepcopy(self.shared_persona) if self.shared_persona else {}

    def persona_view(self) -> dict[str, Any]:
        p = self.persona()
        speech = p.get("speech") or {}
        return {
            "name": str(p.get("name") or "小鲸鱼"),
            "nickname": str(p.get("nickname") or ""),
            "identity": str(p.get("identity") or ""),
            "personality": "、".join(str(x) for x in (p.get("core_traits") or [])),
            "speech": str(speech.get("style") or ""),
            "catch": "、".join(str(x) for x in (speech.get("catch_phrases") or [])),
            "addressing": "、".join(str(x) for x in (speech.get("addressing_user") or [])),
        }

    def save_persona(self, patch: dict[str, Any]) -> dict[str, Any]:
        p = self.persona()
        name = str(patch.get("name") or "").strip()[:12]
        identity = str(patch.get("identity") or "").strip()[:120]
        personality = str(patch.get("personality") or "").strip()[:120]
        speech_style = str(patch.get("speech") or "").strip()[:240]
        catch = str(patch.get("catch") or "").strip()[:60]
        addressing = str(patch.get("addressing") or "").strip()[:60]
        if name:
            p["name"] = name
            p["nickname"] = name
        if identity:
            p["identity"] = identity
        traits = [x.strip() for x in re.split(r"[、,，\s]+", personality) if x.strip()]
        if traits:
            p["core_traits"] = traits[:6]
        speech = p.setdefault("speech", {})
        if speech_style:
            speech["style"] = speech_style
        if catch:
            speech["catch_phrases"] = [x.strip() for x in re.split(r"[、,，\s]+", catch) if x.strip()][:8]
        if addressing:
            speech["addressing_user"] = [x.strip() for x in re.split(r"[、,，\s]+", addressing) if x.strip()][:6]
        if self.shared_persona_path:
            self.shared_persona_path.write_text(
                yaml.safe_dump(p, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            self.shared_persona = p
        return self.persona_view()

    # ---------- 生命周期 ----------
    def _settings(self) -> dict[str, Any]:
        settings = copy.deepcopy(self.base_settings)
        storage = settings.setdefault("storage", {})
        storage["data_dir"] = str(self.shared_data_dir) if self.shared_data_dir else "data"
        storage["log_dir"] = "logs"
        storage["sticker_dir"] = "assets/stickers"
        # 鲸鱼不按人类作息睡：随时可以回话
        settings["schedule"] = {"wake": "00:00", "sleep": "23:59", "class_blocks": []}
        settings.setdefault("dynamic", {})["daily_quota"] = [0, 0]
        settings.setdefault("proactive", {})["daily_quota"] = [0, 0]
        return settings

    def start(self) -> bool:
        with self._lock:
            if self.app is not None:
                return True
            if not self.starting:
                self.starting = True
                self.error = ""
                self._ready.clear()
                self.thread = threading.Thread(target=self._run, name="whale-brain", daemon=True)
                self.thread.start()
        # 正在启动时也要等，避免刚打开智能模式就说话拿到 not_ready
        self._ready.wait(25)
        return self.app is not None

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        try:
            from brainn.config import Config
            from main import App

            cfg = Config(settings=self._settings(), persona=self.persona(), root=self.dir)
            app = App(cfg)
            try:
                app.brain.allow_qq_face = False
                app.brain.allow_image_sticker_steal = False
            except Exception:  # noqa: BLE001
                pass
            try:
                body = app.body
                if self.shared_data_dir:
                    # 同一具身体：不重置任何生理状态，也不在这里推进，
                    # 由主聊天负责 tick，鲸鱼只读真实状态。
                    body.tick = lambda *args, **kwargs: None
                    body.apply_to_mood = lambda mood: None
                else:
                    # 独立模式：鲸鱼不做人类生理周期
                    state = body.state
                    for key in ("pain", "cramp", "hunger", "fatigue", "period_pain"):
                        state[key] = 0
                    state["phase"] = "正常"
                    state["cycle_day"] = 0
                    body.save()
                    body.tick = lambda *args, **kwargs: None
                    body.apply_to_mood = lambda mood: None
                    body.status = lambda: "身体：正常，不饿也不困。"
            except Exception:  # noqa: BLE001
                log.warning("小鲸鱼身体状态初始化失败", exc_info=True)
            self._merge_own_memories(app)
            self.app = app
            log.info("小鲸鱼 BrainN 已启动：%s（共享同一存在：%s）", self.dir, self.shared_data_dir or "独立")
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)[:200]
            log.exception("小鲸鱼 BrainN 启动失败")
            self._ready.set()
            return
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            app = self.app
            self.app = None
            self.loop = None
            if app is not None:
                try:
                    app.store.close()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    ms = getattr(app, "memory_store", None)
                    if ms is not None and ms is not app.store:
                        ms.close()
                except Exception:  # noqa: BLE001
                    pass

    def _merge_own_memories(self, app) -> None:
        """旧版小鲸鱼独立库并入共享库，只做一次；合并后两者就是同一个存在。"""
        legacy_persona = self.dir / "persona.yaml"
        if self.shared_persona and legacy_persona.exists():
            try:
                legacy_persona.unlink()
                log.info("已删除小鲸鱼旧人设文件，统一用主人格")
            except Exception:  # noqa: BLE001
                pass
        own = self.dir / "data" / "ganfanyu.db"
        if not self.shared_data_dir or not own.exists():
            return
        if app.store.get_state("whale_memory_merged_v2"):
            return
        from brainn.db import Store

        src = Store(own)
        try:
            rows = src.export_memories().get("memories") or []
        finally:
            src.close()
        mstore = app.store
        added = merged = 0
        for m in rows[:500]:
            kind = str(m.get("kind") or "fact")[:20]
            key = str(m.get("key") or "")[:60].strip()
            value = str(m.get("value") or "")[:300].strip()
            if not key or not value:
                continue
            existed = mstore.memory_by_key(kind, key) is not None
            rec = {
                "kind": kind, "key": key, "value": value,
                "confidence": float(m.get("confidence") or 0.7),
                "source": "import",
                "layer": str(m.get("layer") or "L3")[:2],
                "person": str(m.get("person") or "")[:40],
                "hooks": str(m.get("hooks") or "")[:120],
                "interpretation": str(m.get("interpretation") or "")[:300],
                "weight": float(m.get("weight") or 0.3),
                "falsifier": str(m.get("falsifier") or "")[:300],
                "reason": "小鲸鱼库合并",
            }
            mid, _ = mstore.insert_memory(rec)
            if existed:
                merged += 1
            else:
                added += 1
            if str(m.get("status") or "") == "archived" and mid:
                mstore.adjust_memory(mid, status="archived")
        try:
            app.store.set_state("whale_memory_merged_v2", {"at": time.time(), "added": added, "merged": merged})
        except Exception:  # noqa: BLE001
            pass
        log.info("小鲸鱼旧库记忆已合并：新增 %d 条，覆盖 %d 条", added, merged)

    def stop(self) -> None:
        with self._lock:
            self.starting = False
            loop, thread = self.loop, self.thread
            self.thread = None
        if loop is not None:
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:  # noqa: BLE001
                pass
        if thread is not None and thread.is_alive():
            thread.join(timeout=6)
        self.app = None
        self.loop = None
        self._ready.clear()

    def restart(self) -> None:
        self.stop()
        self.start()

    # ---------- 对话 ----------
    def chat(self, text: str, history: list | None = None) -> dict[str, Any]:
        text = str(text or "").strip()[:300]
        if not text:
            return {"ok": False, "error": "empty"}
        if not self.start() or self.app is None or self.loop is None:
            return {"ok": False, "error": self.error or "not_ready"}
        with self._chat_lock:
            try:
                fut = asyncio.run_coroutine_threadsafe(self._handle(text), self.loop)
                plan = fut.result(timeout=50)
            except Exception as exc:  # noqa: BLE001
                log.exception("小鲸鱼 BrainN 回复失败")
                return {"ok": False, "error": str(exc)[:200]}
        segments = [str(seg.payload) for seg in getattr(plan, "segments", []) if seg.kind == "text"]
        out = " ".join(s for s in segments if s).strip()
        out = re.sub(r"[\r\n]+", " ", out)[:160] or "咕？"
        try:
            self.app.store.add_message("assistant", out, "text")
        except Exception:  # noqa: BLE001
            log.warning("小鲸鱼回复落库失败", exc_info=True)
        mood = self.app.mood.state
        valence = _clamp((float(mood.mood) - 50.0) / 40.0, -1.0, 1.0)
        arousal = _clamp((float(mood.energy) - 50.0) / 40.0, -1.0, 1.0)
        return {
            "ok": True,
            "text": out,
            "valence": round(valence, 2),
            "arousal": round(arousal, 2),
            "source": "brainn",
        }

    async def _handle(self, text: str):
        self._sync_shared_state()
        return await self.app.brain.handle(text, store_incoming=True)

    def _sync_shared_state(self) -> None:
        """共用同一存在时，每轮先同步心情和身体，避免覆盖另一个入口刚写下的状态。"""
        app = self.app
        if not self.shared_data_dir or app is None:
            return
        try:
            app.mood.reload()
            app.body.reload()
            app.persona.reload()
        except Exception:  # noqa: BLE001
            log.warning("小鲸鱼状态同步失败", exc_info=True)

    # ---------- 记录 ----------
    def history(self, limit: int = 40) -> list[dict[str, Any]]:
        """读小鲸鱼自己的库，给 2D 页记录和桌面面板共用。"""
        app = self.app
        if app is None:
            return []
        try:
            rows = app.store.recent_messages(max(1, min(int(limit), 200)))
        except Exception:  # noqa: BLE001
            log.warning("小鲸鱼记录读取失败", exc_info=True)
            return []
        return [
            {
                "id": r.get("id"),
                "role": "me" if str(r.get("role")) == "user" else "her",
                "content": str(r.get("content") or ""),
                "kind": str(r.get("kind") or "text"),
                "ts": r.get("ts"),
            }
            for r in rows
        ]

    def add_line(self, role: str, content: str, kind: str = "text", media: str = "") -> int:
        """本地台词（点头像、道具反应）也记进小鲸鱼的库。"""
        app = self.app
        if app is None or not str(content or "").strip():
            return 0
        try:
            return int(app.store.add_message(
                str(role), str(content)[:400], str(kind or "text"), media=str(media or "")
            ))
        except Exception:  # noqa: BLE001
            return 0

    # ---------- 记忆管理 ----------
    @staticmethod
    def _memory_view(m: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "id", "kind", "key", "value", "layer", "person", "source", "weight",
            "confidence", "status", "created_at", "updated_at", "review_count",
            "next_review_at", "valid_until", "code",
        )
        return {k: m.get(k) for k in keys}

    def _mstore(self):
        """记忆表所在的库；共享时是主聊天库，不是小鲸鱼自己的状态库。"""
        app = self.app
        if app is None:
            return None
        return getattr(app.memory, "mstore", None) or app.store

    def memory_list(self, query: str = "", status: str = "", limit: int = 60) -> dict[str, Any]:
        app = self.app
        store = self._mstore()
        if app is None or store is None:
            return {"ok": False, "error": "not_ready", "items": []}
        q = str(query or "").strip().lower()
        # 记忆页要能显式查看/搜索已归档的旧记忆
        rows = store.all_memories(2000, include_archived=True)
        if status:
            rows = [m for m in rows if str(m.get("status") or "") == status]
        if q:
            rows = [
                m for m in rows
                if q in str(m.get("key") or "").lower() or q in str(m.get("value") or "").lower()
            ]
        rows.sort(key=lambda m: float(m.get("weight") or 0), reverse=True)
        page = rows[: max(1, min(int(limit or 60), 200))]
        return {
            "ok": True,
            "total": len(rows),
            "items": [self._memory_view(m) for m in page],
            "stats": store.memory_stats(),
        }

    def memory_update(self, payload: dict[str, Any]) -> dict[str, Any]:
        app = self.app
        store = self._mstore()
        if app is None or store is None:
            return {"ok": False, "error": "not_ready"}
        try:
            mid = int(payload.get("id") or 0)
        except (TypeError, ValueError):
            mid = 0
        if not mid:
            return {"ok": False, "error": "bad_id"}
        weight = payload.get("weight")
        try:
            weight = float(weight) if weight not in (None, "") else None
        except (TypeError, ValueError):
            weight = None
        store.adjust_memory(
            mid,
            value=payload.get("value") if payload.get("value") not in (None, "") else None,
            weight=weight,
            status=str(payload.get("status") or "") or None,
        )
        return {"ok": True, "item": self._memory_view(store.memory_by_id(mid) or {})}

    def memory_delete(self, payload: dict[str, Any]) -> dict[str, Any]:
        app = self.app
        store = self._mstore()
        if app is None or store is None:
            return {"ok": False, "error": "not_ready"}
        try:
            mid = int(payload.get("id") or 0)
        except (TypeError, ValueError):
            mid = 0
        if not mid:
            return {"ok": False, "error": "bad_id"}
        store.adjust_memory(mid, status="archived")
        return {"ok": True, "id": mid}

    def memory_related(self, memory_id: int) -> dict[str, Any]:
        app = self.app
        store = self._mstore()
        if app is None or store is None:
            return {"ok": False, "error": "not_ready", "items": []}
        try:
            mid = int(memory_id)
        except (TypeError, ValueError):
            return {"ok": False, "error": "bad_id", "items": []}
        links = store.memory_links(mid, 6)
        return {"ok": True, "items": [self._memory_view(m) | {"link_weight": m.get("link_weight"), "link_reason": m.get("link_reason")} for m in links]}

    def memory_rebuild(self) -> dict[str, Any]:
        app = self.app
        if app is None:
            return {"ok": False, "error": "not_ready"}
        n = app.brain.memory.rebuild_links()
        return {"ok": True, "links": n}

    def memory_export(self) -> dict[str, Any]:
        """导出全部记忆（含已归档）+ 图谱边，作为手动备份/迁移文件。"""
        app = self.app
        if app is None:
            return {"ok": False, "error": "not_ready"}
        store = self._mstore() or app.store
        data = store.export_memories()
        data["app"] = "BrainN"
        data["kind"] = "memory_export"
        data["version"] = 2
        data["exported_at"] = time.time()
        try:
            data["card"] = card_fields(app.store)
        except Exception:  # noqa: BLE001
            log.warning("OMC 卡片字段生成失败", exc_info=True)
        return {"ok": True, "data": data, "count": len(data["memories"])}

    def memory_import(self, payload: dict[str, Any]) -> dict[str, Any]:
        """导入备份：按 kind+key 合并去重，来源统一标 import，完成后重建图谱。"""
        app = self.app
        if app is None:
            return {"ok": False, "error": "not_ready"}
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            data = payload if isinstance(payload, dict) else {}
        mems = data.get("memories")
        if not isinstance(mems, list) or not mems:
            return {"ok": False, "error": "bad_file"}
        store = app.store
        mstore = self._mstore() or store
        continuity = {}
        try:
            card = data.get("card") if isinstance(data.get("card"), dict) else {}
            source = str(((card.get("continuity") or {}).get("source_instance")) or "")
            current = instance_id(store)
            continuity = {
                "source_instance": source or current,
                "current_instance": current,
                "score": 1.0 if source in ("", current) else 0.95,
                "fork": None,
                "imported_at": time.time(),
            }
            store.set_state("qt_continuity", continuity)
        except Exception:  # noqa: BLE001
            log.warning("OMC continuity 记录失败", exc_info=True)
        added = merged = skipped = 0
        for m in mems[:2000]:
            if not isinstance(m, dict):
                skipped += 1
                continue
            kind = str(m.get("kind") or "fact")[:20]
            key = str(m.get("key") or "")[:60].strip()
            value = str(m.get("value") or "")[:300].strip()
            if not key or not value:
                skipped += 1
                continue
            try:
                weight = max(0.1, min(1.0, float(m.get("weight") or 0.3)))
            except (TypeError, ValueError):
                weight = 0.3
            try:
                conf = max(0.3, min(0.95, float(m.get("confidence") or 0.7)))
            except (TypeError, ValueError):
                conf = 0.7
            existed = mstore.memory_by_key(kind, key) is not None
            rec = {
                "kind": kind, "key": key, "value": value, "confidence": conf,
                "source": "import",
                "layer": str(m.get("layer") or "L3")[:2],
                "person": str(m.get("person") or "")[:40],
                "person_id": str(m.get("person_id") or "")[:40],
                "domain": str(m.get("domain") or "")[:40],
                "scene": str(m.get("scene") or "")[:40],
                "emotion": str(m.get("emotion") or "")[:20],
                "intensity": int(m.get("intensity") or 2),
                "hooks": str(m.get("hooks") or "")[:120],
                "interpretation": str(m.get("interpretation") or "")[:300],
                "weight": weight,
                "mainline_link": float(m.get("mainline_link") or 1.0),
                "valid_until": float(m.get("valid_until") or 0),
                "reason": "备份导入合并",
            }
            try:
                mid, _ = mstore.insert_memory(rec)
            except Exception:  # noqa: BLE001
                skipped += 1
                continue
            if existed:
                merged += 1
            else:
                added += 1
            # 已归档的保持归档，别一导入就全部复活
            if str(m.get("status") or "") == "archived" and mid:
                mstore.adjust_memory(mid, status="archived")
        links = 0
        try:
            links = app.brain.memory.rebuild_links()
        except Exception:  # noqa: BLE001
            log.warning("导入后重建图谱失败", exc_info=True)
        insertion = {}
        try:
            card = data.get("card") if isinstance(data.get("card"), dict) else {}
            insertion = run_insertion(
                store, card, getattr(getattr(app, "brain", None), "settings", {}) or {}
            )
        except Exception:  # noqa: BLE001
            log.warning("OMC 五步插入失败", exc_info=True)
        return {
            "ok": True,
            "added": added,
            "merged": merged,
            "skipped": skipped,
            "links": links,
            "continuity": continuity,
            "insertion": insertion,
        }

    def memory_graph(self, limit: int = 80) -> dict[str, Any]:
        """图谱可视化数据：权重最高的 N 个节点 + 它们之间的边。"""
        app = self.app
        if app is None:
            return {"ok": False, "error": "not_ready", "nodes": [], "edges": []}
        store = self._mstore() or app.store
        mems = [m for m in store.all_memories(400) if str(m.get("source") or "") != "digest"]
        mems.sort(key=lambda m: float(m.get("weight") or 0), reverse=True)
        limit = max(10, min(int(limit or 80), 200))
        top = mems[:limit]
        ids = {int(m["id"]) for m in top}
        nodes = [
            {
                "id": int(m["id"]),
                "code": str(m.get("code") or ""),
                "key": str(m.get("key") or ""),
                "value": str(m.get("value") or "")[:120],
                "kind": str(m.get("kind") or ""),
                "layer": str(m.get("layer") or ""),
                "weight": float(m.get("weight") or 0),
                "person": str(m.get("person") or ""),
                "emotion": str(m.get("emotion") or ""),
                "status": str(m.get("status") or ""),
            }
            for m in top
        ]
        edges = [
            {
                "a": int(link["a"]), "b": int(link["b"]),
                "weight": float(link.get("weight") or 0),
                "reason": str(link.get("reason") or ""),
            }
            for link in store.memory_links_all()
            if int(link["a"]) in ids and int(link["b"]) in ids
        ]
        return {"ok": True, "nodes": nodes, "edges": edges, "total": len(mems)}

    # ---------- 状态 ----------
    def status(self) -> dict[str, Any]:
        p = self.persona()
        out: dict[str, Any] = {
            "ready": self.app is not None,
            "starting": bool(self.starting and self.app is None),
            "error": self.error,
            "name": str(p.get("name") or "小鲸鱼"),
            "dir": str(self.dir),
            "db": str((self.shared_data_dir or (self.dir / "data")) / "ganfanyu.db"),
            "shared": bool(self.shared_data_dir),
            "persona": self.persona_view(),
        }
        app = self.app
        if app is None:
            return out
        try:
            mood = app.mood.state
            mem = app.store.memory_stats()
            total = sum(int(v) for v in (mem.get("layers") or {}).values())
            nodes = app.store.social_nodes()
            out["stats"] = {
                "mood": round(float(mood.mood)),
                "affection": round(float(mood.affection)),
                "grievance": round(float(mood.grievance)),
                "sanity": round(float(mood.sanity)),
                "energy": round(float(mood.energy)),
                "memories": total,
                "relations": len([n for n in nodes if int(n.get("active") or 1)]),
            }
        except Exception:  # noqa: BLE001
            log.warning("小鲸鱼大脑状态读取失败", exc_info=True)
        return out
