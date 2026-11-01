"""本地 SQLite 存储：消息、记忆、情绪状态、主动消息、提醒。"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable


SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    kind TEXT DEFAULT 'text',
    media TEXT DEFAULT '',
    session TEXT DEFAULT 'main',
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts);

CREATE TABLE IF NOT EXISTS life_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT DEFAULT '',
    status TEXT DEFAULT 'waiting',
    created_at REAL NOT NULL,
    expected_at REAL DEFAULT 0,
    updated_at REAL DEFAULT 0,
    source TEXT DEFAULT 'chat',
    confidence REAL DEFAULT 0.6,
    notify INTEGER DEFAULT 1,
    note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_life_events_status ON life_events(status, expected_at);

CREATE TABLE IF NOT EXISTS food_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id TEXT DEFAULT '',
    shop_name TEXT DEFAULT '',
    items TEXT DEFAULT '[]',
    total REAL DEFAULT 0,
    address TEXT DEFAULT '',
    note TEXT DEFAULT '',
    eta_min INTEGER DEFAULT 30,
    status TEXT DEFAULT 'paid',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_food_orders_ts ON food_orders(created_at);

CREATE TABLE IF NOT EXISTS mall_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    items TEXT DEFAULT '[]',
    total REAL DEFAULT 0,
    address TEXT DEFAULT '',
    status TEXT DEFAULT 'paid',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mall_orders_ts ON mall_orders(created_at);

CREATE TABLE IF NOT EXISTS short_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT DEFAULT '',
    user TEXT DEFAULT '',
    text TEXT DEFAULT '',
    reply_to INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_short_comments_vid ON short_comments(video_id, id);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL DEFAULT 0.7,
    source TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(kind, key)
);

CREATE TABLE IF NOT EXISTS memory_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id INTEGER NOT NULL,
    kind TEXT DEFAULT '',
    key TEXT DEFAULT '',
    value TEXT DEFAULT '',
    interpretation TEXT DEFAULT '',
    reason TEXT DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_versions_mid ON memory_versions(memory_id);

-- 记忆图谱：无向边，a<b 存一条，查询时两头都查
CREATE TABLE IF NOT EXISTS memory_links (
    a INTEGER NOT NULL,
    b INTEGER NOT NULL,
    weight REAL DEFAULT 0,
    reason TEXT DEFAULT '',
    updated_at REAL NOT NULL,
    PRIMARY KEY(a, b)
);
CREATE INDEX IF NOT EXISTS idx_memory_links_a ON memory_links(a);
CREATE INDEX IF NOT EXISTS idx_memory_links_b ON memory_links(b);

CREATE TABLE IF NOT EXISTS brainn_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    percept TEXT DEFAULT '',
    states TEXT DEFAULT '',
    proposals TEXT DEFAULT '',
    budget REAL DEFAULT 1.0,
    winner TEXT DEFAULT '',
    distortion TEXT DEFAULT '',
    bypass TEXT DEFAULT '',
    action TEXT DEFAULT '',
    outcome TEXT DEFAULT '',
    latency_ms REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_brainn_transitions_ts ON brainn_transitions(ts);

-- ---------- CS-SNN / QT 账本（只写不接管，读接口单独开） ----------
CREATE TABLE IF NOT EXISTS qt_refractions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    before TEXT DEFAULT '',
    after TEXT DEFAULT '',
    medium TEXT DEFAULT '{}',
    confidence REAL DEFAULT 0,
    note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_qt_refractions_ts ON qt_refractions(ts);

CREATE TABLE IF NOT EXISTS qt_tensions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    a_ref TEXT DEFAULT '',
    b_ref TEXT DEFAULT '',
    topic TEXT DEFAULT '',
    accumulation REAL DEFAULT 0,
    threshold REAL DEFAULT 10,
    status TEXT DEFAULT 'open',
    note TEXT DEFAULT '',
    meta TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_qt_tensions_ts ON qt_tensions(ts);

CREATE TABLE IF NOT EXISTS qt_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    from_state TEXT DEFAULT '',
    to_state TEXT DEFAULT '',
    retained TEXT DEFAULT '',
    reason TEXT DEFAULT '',
    meta TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_qt_transitions_ts ON qt_transitions(ts);

CREATE TABLE IF NOT EXISTS qt_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    artifact_id TEXT DEFAULT '',
    kind TEXT DEFAULT '',
    name TEXT DEFAULT '',
    content_hash TEXT DEFAULT '',
    owner TEXT DEFAULT '',
    meta TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_qt_artifacts_ts ON qt_artifacts(ts);
CREATE INDEX IF NOT EXISTS idx_qt_artifacts_hash ON qt_artifacts(content_hash);

CREATE TABLE IF NOT EXISTS qt_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    claim_ref TEXT DEFAULT '',
    verdict TEXT DEFAULT 'unverified',
    evidence TEXT DEFAULT '',
    confidence REAL DEFAULT 0,
    source TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_qt_outcomes_ts ON qt_outcomes(ts);

CREATE TABLE IF NOT EXISTS qt_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    prediction TEXT DEFAULT '',
    hit INTEGER DEFAULT 0,
    match_score REAL DEFAULT 0,
    score REAL DEFAULT 0,
    note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_qt_metrics_ts ON qt_metrics(ts);

CREATE TABLE IF NOT EXISTS qt_internalization (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    person_ref TEXT DEFAULT '',
    source_event TEXT DEFAULT '',
    window_state TEXT DEFAULT 'unknown',
    note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_qt_internalization_person ON qt_internalization(person_ref);

CREATE TABLE IF NOT EXISTS qt_absences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT DEFAULT '',
    since REAL DEFAULT 0,
    intensity REAL DEFAULT 0,
    note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_qt_absences_ts ON qt_absences(ts);

CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS mood_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    mood REAL, affection REAL, grievance REAL, jealousy REAL, sanity REAL,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS proactive_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    topic TEXT,
    text TEXT
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    due_at REAL NOT NULL,
    content TEXT NOT NULL,
    done INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE NOT NULL,
    summary TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    due_at REAL NOT NULL,
    text TEXT NOT NULL,
    kind TEXT DEFAULT 'text',
    url TEXT DEFAULT '',
    image_url TEXT DEFAULT '',
    user_id INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_pending_due ON pending_replies(due_at);

CREATE TABLE IF NOT EXISTS dynamics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    text TEXT NOT NULL,
    topic TEXT DEFAULT '',
    platform TEXT DEFAULT '',
    images TEXT DEFAULT '',
    author TEXT DEFAULT 'her'
);

CREATE TABLE IF NOT EXISTS social_posts (
    id TEXT PRIMARY KEY,
    node TEXT NOT NULL,
    ts REAL NOT NULL,
    text TEXT NOT NULL,
    day TEXT NOT NULL,
    images TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_social_posts_day ON social_posts(day);

CREATE TABLE IF NOT EXISTS post_likes (
    target TEXT NOT NULL,
    user TEXT NOT NULL,
    ts REAL NOT NULL,
    PRIMARY KEY(target, user)
);

CREATE TABLE IF NOT EXISTS post_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target TEXT NOT NULL,
    user TEXT NOT NULL,
    text TEXT NOT NULL,
    parent_id INTEGER DEFAULT 0,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_post_comments_target ON post_comments(target);

CREATE TABLE IF NOT EXISTS tool_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    ts REAL NOT NULL
);


CREATE TABLE IF NOT EXISTS social_nodes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    trust REAL DEFAULT 50,
    intimacy REAL DEFAULT 40,
    conflict REAL DEFAULT 0,
    dependency REAL DEFAULT 20,
    influence REAL DEFAULT 50,
    depth REAL DEFAULT 0,
    interactions INTEGER DEFAULT 0,
    last_event TEXT DEFAULT '',
    active INTEGER DEFAULT 1,
    personality TEXT DEFAULT '',
    manual INTEGER DEFAULT 0,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS social_edges (
    a TEXT NOT NULL,
    b TEXT NOT NULL,
    trust REAL DEFAULT 50,
    intimacy REAL DEFAULT 30,
    conflict REAL DEFAULT 0,
    influence REAL DEFAULT 30,
    depth REAL DEFAULT 0,
    debt REAL DEFAULT 0,
    credit REAL DEFAULT 0,
    shared REAL DEFAULT 0,
    interactions INTEGER DEFAULT 0,
    last_event TEXT DEFAULT '',
    updated_at REAL NOT NULL,
    PRIMARY KEY(a, b)
);

CREATE TABLE IF NOT EXISTS social_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    event_key TEXT NOT NULL,
    text TEXT NOT NULL,
    node TEXT DEFAULT '',
    mood_delta REAL DEFAULT 0
);
"""


class Store:
    def __init__(self, path: Path):
        self._lock = threading.Lock()
        self._batch_depth = 0
        self._transition_writes = 0
        self._qt_writes = 0
        # 全量记忆：开启后不再裁剪账本/情绪日志，并由 FullMemory 留档（只影响保存，不影响检索）
        self.full_retention = False
        self.archive_message = None
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        try:
            # 手机上动态生成、聊天、发布可能同时写库：WAL + 等待锁，避免 database is locked
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:  # noqa: BLE001
            pass
        self._conn.executescript(SCHEMA)
        self._migrate_social()
        self._migrate_memory()
        self._migrate_dynamics()
        self._migrate_posts()
        self._migrate_messages()
        self._migrate_qt()
        self._dedupe_qt_ledgers()
        self._conn.commit()

    @contextmanager
    def batch(self):
        """把多次状态写入合并成一次提交，供影子运行时使用。"""
        with self._lock:
            self._batch_depth += 1
        try:
            yield
        finally:
            with self._lock:
                self._batch_depth = max(0, self._batch_depth - 1)
                if self._batch_depth == 0:
                    self._conn.commit()

    def _commit(self) -> None:
        if self._batch_depth == 0:
            self._conn.commit()

    def _migrate_memory(self) -> None:
        """老库补列：记忆分层、情绪、权重、回访状态。"""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(memories)")}
        fresh = "layer" not in cols
        for name, ddl in (
            ("layer", "TEXT DEFAULT 'L3'"),
            ("person", "TEXT DEFAULT ''"),
            ("person_id", "TEXT DEFAULT ''"),
            ("domain", "TEXT DEFAULT ''"),
            ("scene", "TEXT DEFAULT ''"),
            ("emotion", "TEXT DEFAULT ''"),
            ("intensity", "INTEGER DEFAULT 2"),
            ("hooks", "TEXT DEFAULT ''"),
            ("interpretation", "TEXT DEFAULT ''"),
            ("weight", "REAL DEFAULT 0.2"),
            ("status", "TEXT DEFAULT 'active'"),
            ("review_count", "INTEGER DEFAULT 0"),
            ("last_review_at", "REAL DEFAULT 0"),
            ("next_review_at", "REAL DEFAULT 0"),
            ("mainline_link", "REAL DEFAULT 1.0"),
            ("code", "TEXT DEFAULT ''"),
            ("valid_until", "REAL DEFAULT 0"),
        ):
            if name not in cols:
                self._conn.execute(f"ALTER TABLE memories ADD COLUMN {name} {ddl}")
        if fresh:
            # 老数据按类型粗分层：偏好/触发点归 L4，其余归 L3
            self._conn.execute("UPDATE memories SET layer='L4' WHERE kind='preference'")
            self._conn.execute("UPDATE memories SET hooks=key WHERE hooks='' OR hooks IS NULL")
        rows = self._conn.execute("SELECT id,layer,code FROM memories WHERE code='' OR code IS NULL").fetchall()
        for r in rows:
            self._conn.execute(
                "UPDATE memories SET code=? WHERE id=?",
                (f"{r['layer'] or 'L3'}-{r['id']:03d}", r["id"]),
            )
        # 老记忆没有情绪强度和回访计划：按类型补一个合理初值，并分批排进回访队列
        legacy = self._conn.execute(
            "SELECT id,kind FROM memories WHERE next_review_at=0 OR next_review_at IS NULL"
        ).fetchall()
        base_intensity = {"grudge": 4, "promise": 4, "event": 3, "preference": 3}
        now = time.time()
        for r in legacy:
            intensity = base_intensity.get(r["kind"], 2)
            weight = max(0.2, round(intensity * 1.0 / 10, 3))
            self._conn.execute(
                "UPDATE memories SET intensity=?, weight=?, next_review_at=? WHERE id=?",
                (intensity, weight, now + 3600 + (r["id"] % 3) * 86400, r["id"]),
            )
        # 记忆里写了人物名但还没有人物主键：按关系节点名回填
        if "person_id" not in cols:
            for r in self._conn.execute(
                "SELECT id,person FROM memories WHERE (person_id IS NULL OR person_id='') AND person!=''"
            ).fetchall():
                node = self._find_node(r["person"])
                if node:
                    self._conn.execute(
                        "UPDATE memories SET person_id=? WHERE id=?", (node["id"], r["id"])
                    )
        # 旧版本曾把主动话题当 source 写进记忆；统一收回成 chat，避免来源标签污染
        allowed = (
            "chat", "nightly", "reflection", "self_reflection", "digest", "backfill",
            "M11.artifact", "import", "persona_reset", "practice", "practice.settle",
            "practice.backfill", "drives", "social", "memory", "food", "mall", "shorts",
            "life", "reminder", "tool",
        )
        marks = ",".join("?" for _ in allowed)
        self._conn.execute(
            f"UPDATE memories SET source='chat' WHERE source!='' AND source NOT IN ({marks})",
            allowed,
        )

    def _migrate_dynamics(self) -> None:
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(dynamics)")}
        if "images" not in cols:
            self._conn.execute("ALTER TABLE dynamics ADD COLUMN images TEXT DEFAULT ''")
        if "author" not in cols:
            self._conn.execute("ALTER TABLE dynamics ADD COLUMN author TEXT DEFAULT 'her'")

    def _migrate_messages(self) -> None:
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(messages)")}
        if "media" not in cols:
            self._conn.execute("ALTER TABLE messages ADD COLUMN media TEXT DEFAULT ''")

    def _migrate_qt(self) -> None:
        """QT 融合层：记忆补证伪条件；版本链补扬弃三字段。只加列，不删改。"""
        mem_cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(memories)")}
        if "falsifier" not in mem_cols:
            self._conn.execute("ALTER TABLE memories ADD COLUMN falsifier TEXT DEFAULT ''")
        if "refraction_id" not in mem_cols:
            self._conn.execute("ALTER TABLE memories ADD COLUMN refraction_id INTEGER DEFAULT 0")
        ver_cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(memory_versions)")}
        for name in ("overcame", "kept", "raised"):
            if name not in ver_cols:
                self._conn.execute(f"ALTER TABLE memory_versions ADD COLUMN {name} TEXT DEFAULT ''")
        tension_cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(qt_tensions)")}
        if "meta" not in tension_cols:
            self._conn.execute("ALTER TABLE qt_tensions ADD COLUMN meta TEXT DEFAULT '{}'")

    def _dedupe_qt_ledgers(self) -> None:
        """清理旧版本重复回填的 M13/M15/M16 行，并加唯一索引防再次重复。"""
        # 旧账本里偶发把多个产物 id 逗号拼成一个 claim_ref，先拆回单条
        split_rows = self._conn.execute(
            "SELECT * FROM qt_outcomes WHERE claim_ref LIKE '%,%'"
        ).fetchall()
        for row in split_rows:
            parts = [p.strip() for p in str(row["claim_ref"]).split(",") if p.strip()]
            for part in parts:
                self.add_qt_outcome(
                    claim_ref=part,
                    verdict=str(row["verdict"] or "unverified"),
                    evidence=str(row["evidence"] or ""),
                    confidence=float(row["confidence"] or 0),
                    source=str(row["source"] or "practice.backfill"),
                )
            self._conn.execute("DELETE FROM qt_outcomes WHERE id=?", (int(row["id"]),))
        split_metrics = self._conn.execute(
            "SELECT * FROM qt_metrics WHERE prediction LIKE '%,%'"
        ).fetchall()
        for row in split_metrics:
            parts = [
                p.strip() for p in str(row["prediction"]).split(",") if p.strip()
            ]
            for part in parts:
                self.add_qt_metric(
                    prediction=part,
                    hit=bool(int(row["hit"] or 0)),
                    match_score=float(row["match_score"] or 0),
                    note=str(row["note"] or ""),
                )
            self._conn.execute("DELETE FROM qt_metrics WHERE id=?", (int(row["id"]),))
        removed = 0
        cur = self._conn.execute(
            """DELETE FROM qt_artifacts WHERE id NOT IN
               (SELECT MIN(id) FROM qt_artifacts GROUP BY artifact_id)"""
        )
        removed += cur.rowcount or 0
        cur = self._conn.execute(
            """DELETE FROM qt_outcomes WHERE source='practice.backfill' AND id NOT IN
               (SELECT MIN(id) FROM qt_outcomes WHERE source='practice.backfill' GROUP BY claim_ref)"""
        )
        removed += cur.rowcount or 0
        cur = self._conn.execute(
            """DELETE FROM qt_metrics WHERE id NOT IN
               (SELECT MIN(id) FROM qt_metrics GROUP BY prediction)"""
        )
        removed += cur.rowcount or 0
        cur = self._conn.execute(
            """DELETE FROM qt_tensions WHERE a_ref='QT.M9' AND status='open' AND id NOT IN
               (SELECT MIN(id) FROM qt_tensions WHERE a_ref='QT.M9' AND status='open'
                GROUP BY b_ref,topic)"""
        )
        removed += cur.rowcount or 0
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_qt_artifacts_artifact ON qt_artifacts(artifact_id)"
        )
        self._conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS uq_qt_outcomes_backfill_claim
               ON qt_outcomes(claim_ref) WHERE source='practice.backfill'"""
        )
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_qt_metrics_prediction ON qt_metrics(prediction)"
        )
        if removed:
            self._conn.commit()

    def _migrate_posts(self) -> None:
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(social_posts)")}
        if "images" not in cols:
            self._conn.execute("ALTER TABLE social_posts ADD COLUMN images TEXT DEFAULT ''")
        comment_cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(post_comments)")}
        if "parent_id" not in comment_cols:
            self._conn.execute("ALTER TABLE post_comments ADD COLUMN parent_id INTEGER DEFAULT 0")

    def _migrate_social(self) -> None:
        """老库补列：关系深度、互动次数、最近事件、人情账。"""
        for table in ("social_nodes", "social_edges"):
            cols = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            for name, ddl in (
                ("depth", "REAL DEFAULT 0"),
                ("interactions", "INTEGER DEFAULT 0"),
                ("last_event", "TEXT DEFAULT ''"),
                ("active", "INTEGER DEFAULT 1"),
            ):
                if name not in cols:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        node_cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(social_nodes)")}
        for name, ddl in (
            ("personality", "TEXT DEFAULT ''"),
            ("manual", "INTEGER DEFAULT 0"),
        ):
            if name not in node_cols:
                self._conn.execute(f"ALTER TABLE social_nodes ADD COLUMN {name} {ddl}")
        edge_cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(social_edges)")}
        for name, ddl in (
            ("debt", "REAL DEFAULT 0"),
            ("credit", "REAL DEFAULT 0"),
            ("shared", "REAL DEFAULT 0"),
        ):
            if name not in edge_cols:
                self._conn.execute(f"ALTER TABLE social_edges ADD COLUMN {name} {ddl}")

    # ---------- 消息 ----------
    def add_message(self, role: str, content: str, kind: str = "text", ts: float | None = None, media: str = "", session: str = "main") -> int:
        stamp = ts or time.time()
        sess = str(session or "main")
        with self._lock:
            # 2D 页和聊天通道可能同时落同一条消息：2 秒内同角色同内容只留一条
            prev = self._conn.execute(
                "SELECT id, content, ts FROM messages WHERE role=? AND session=? ORDER BY id DESC LIMIT 1",
                (role, sess),
            ).fetchone()
            if prev and str(prev["content"]) == str(content) and abs(stamp - float(prev["ts"] or 0)) < 2.0:
                return int(prev["id"])
            cur = self._conn.execute(
                "INSERT INTO messages(role, content, kind, media, session, ts) VALUES(?,?,?,?,?,?)",
                (role, content, kind, str(media or ""), sess, stamp),
            )
            self._conn.commit()
            mid = int(cur.lastrowid or 0)
        hook = self.archive_message
        if hook is not None and mid:
            try:
                hook(
                    {
                        "id": mid,
                        "role": role,
                        "content": content,
                        "kind": kind,
                        "media": media,
                        "session": session,
                        "ts": stamp,
                    }
                )
            except Exception:  # noqa: BLE001
                pass
        return mid

    def dedupe_messages(self, window_seconds: float = 10.0) -> int:
        """清理 2D/聊天双通道造成的同角色同内容重复（只动文本，不动表情/图片）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, role, content, kind, ts FROM messages ORDER BY id ASC"
            ).fetchall()
            last: dict[tuple[str, str], float] = {}
            remove: list[int] = []
            for row in rows:
                if str(row["kind"] or "text") != "text":
                    continue
                key = (str(row["role"] or ""), str(row["content"] or ""))
                ts = float(row["ts"] or 0)
                prev = last.get(key)
                if prev is not None and abs(ts - prev) <= window_seconds:
                    remove.append(int(row["id"]))
                    continue
                last[key] = ts
            for start in range(0, len(remove), 200):
                chunk = remove[start:start + 200]
                self._conn.execute(
                    "DELETE FROM messages WHERE id IN (" + ",".join("?" for _ in chunk) + ")",
                    tuple(chunk),
                )
            if remove:
                self._conn.commit()
        return len(remove)

    def update_message_content(self, message_id: int, content: str) -> bool:
        """用户消息先落库、后补视觉描述时用。"""
        try:
            mid = int(message_id or 0)
        except (TypeError, ValueError):
            return False
        if mid <= 0:
            return False
        with self._lock:
            cur = self._conn.execute(
                "UPDATE messages SET content=? WHERE id=?", (str(content or ""), mid)
            )
            self._conn.commit()
            return cur.rowcount > 0

    def update_message_media(self, message_id: int, media: str) -> bool:
        """转账、卡片类消息更新状态用。"""
        try:
            mid = int(message_id or 0)
        except (TypeError, ValueError):
            return False
        if mid <= 0:
            return False
        with self._lock:
            cur = self._conn.execute(
                "UPDATE messages SET media=? WHERE id=?", (str(media or ""), mid)
            )
            self._conn.commit()
            return cur.rowcount > 0

    def get_message(self, message_id: int) -> dict[str, Any] | None:
        try:
            mid = int(message_id or 0)
        except (TypeError, ValueError):
            return None
        if mid <= 0:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT id,role,content,kind,media,session,ts FROM messages WHERE id=?", (mid,)
            ).fetchone()
        return dict(row) if row else None

    def delete_message(self, message_id: int) -> bool:
        """删除一条刚写入但最终没有发出去的消息（用于丢弃过期回复）。"""
        try:
            mid = int(message_id or 0)
        except (TypeError, ValueError):
            return False
        if mid <= 0:
            return False
        with self._lock:
            cur = self._conn.execute("DELETE FROM messages WHERE id=?", (mid,))
            self._conn.commit()
            return cur.rowcount > 0

    def recent_messages(self, limit: int = 16) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, role, content, kind, media, ts FROM messages WHERE session='main' ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def all_messages(self, limit: int = 0) -> list[dict[str, Any]]:
        """全量留档补历史用；按时间正序，默认不截断。"""
        sql = "SELECT id, role, content, kind, media, session, ts FROM messages ORDER BY id ASC"
        args: tuple[Any, ...] = ()
        if limit and int(limit) > 0:
            sql += " LIMIT ?"
            args = (int(limit),)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def recent_whale_messages(self, limit: int = 40) -> list[dict[str, Any]]:
        """小鲸鱼页的独立互动记录：不进主聊天上下文，只在她的页面里显示。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, role, content, kind, media, ts FROM messages WHERE session='whale' ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def history_page(self, limit: int = 40, before_id: int = 0, around: int = 0,
                     q: str = "", kind: str = "", day: str = "",
                     session: str = "main") -> dict[str, Any]:
        """聊天记录分页 / 关键词搜索 / 取某条前后上下文。"""
        limit = max(1, min(120, int(limit or 40)))
        q = str(q or "").strip()
        with self._lock:
            if around:
                row = self._conn.execute(
                    "SELECT id FROM messages WHERE id=? AND session=?", (int(around), session)
                ).fetchone()
                if not row:
                    return {"messages": [], "has_more": False}
                head = self._conn.execute(
                    "SELECT id,role,content,kind,media,ts FROM messages "
                    "WHERE session=? AND id<=? ORDER BY id DESC LIMIT ?",
                    (session, int(around), limit // 2 + 1),
                ).fetchall()
                tail = self._conn.execute(
                    "SELECT id,role,content,kind,media,ts FROM messages "
                    "WHERE session=? AND id>? ORDER BY id ASC LIMIT ?",
                    (session, int(around), limit // 2),
                ).fetchall()
                rows = [dict(r) for r in reversed(head)] + [dict(r) for r in tail]
                return {"messages": rows, "has_more": False}
            where = ["session=?"]
            params: list[Any] = [session]
            if q:
                where.append("(content LIKE ? OR media LIKE ?)")
                params.extend([f"%{q}%", f"%{q}%"])
            if kind == "media":
                where.append("kind IN ('image', 'video')")
            elif kind:
                where.append("kind=?")
                params.append(kind)
            if day:
                try:
                    day_start = time.mktime(time.strptime(day, "%Y-%m-%d"))
                except ValueError:
                    day_start = 0.0
                if day_start:
                    where.append("ts >= ? AND ts < ?")
                    params.extend([day_start, day_start + 86400])
            if before_id:
                where.append("id < ?")
                params.append(int(before_id))
            params.append(limit + 1)
            rows = self._conn.execute(
                "SELECT id,role,content,kind,media,ts FROM messages WHERE "
                + " AND ".join(where) + " ORDER BY id DESC LIMIT ?", params
            ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        return {"messages": [dict(r) for r in reversed(rows)], "has_more": has_more}

    def delete_user_message(self, content: str, ts: float | None = None, window: float = 120) -> bool:
        """撤回用：按内容 + 最近时间删掉一条用户消息，返回是否删到。"""
        text = str(content or "").strip()
        if not text:
            return False
        ts = float(ts or time.time())
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM messages WHERE role='user' AND content=? AND ABS(ts-?)<=? "
                "ORDER BY ABS(ts-?) ASC LIMIT 1",
                (text, ts, window, ts),
            ).fetchone()
            if not row:
                return False
            self._conn.execute("DELETE FROM messages WHERE id=?", (int(row["id"]),))
            self._conn.commit()
        return True

    def messages_between(self, start: float, end: float) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content, kind, ts FROM messages WHERE ts BETWEEN ? AND ? ORDER BY id",
                (start, end),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------- 生活事件账本 ----------
    def add_life_event(
        self,
        kind: str,
        title: str,
        detail: str = "",
        expected_at: float = 0.0,
        source: str = "chat",
        confidence: float = 0.6,
        notify: bool = True,
        created_at: float | None = None,
    ) -> int:
        now = float(created_at or time.time())
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO life_events(kind,title,detail,status,created_at,expected_at,"
                "updated_at,source,confidence,notify) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    str(kind),
                    str(title)[:80],
                    str(detail)[:300],
                    "waiting",
                    now,
                    float(expected_at or 0),
                    now,
                    str(source),
                    float(confidence),
                    1 if notify else 0,
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def update_life_event(self, event_id: int, **fields: Any) -> bool:
        allowed = {"status", "title", "detail", "expected_at", "notify", "note", "confidence"}
        sets = [f"{key}=?" for key in fields if key in allowed]
        values = [fields[key] for key in fields if key in allowed]
        if not sets:
            return False
        values.extend([time.time(), int(event_id)])
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE life_events SET {', '.join(sets)}, updated_at=? WHERE id=?",
                values,
            )
            self._conn.commit()
            return cur.rowcount > 0

    # ---------- 饭点订单 ----------
    def create_food_order(self, shop_id: str, shop_name: str, items: list[dict[str, Any]],
                          total: float, address: str, note: str, eta_min: int) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO food_orders(shop_id,shop_name,items,total,address,note,eta_min,"
                "status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    str(shop_id), str(shop_name), json.dumps(items, ensure_ascii=False),
                    float(total), str(address), str(note), int(eta_min), "paid", now, now,
                ),
            )
            self._conn.commit()
            order_id = int(cur.lastrowid or 0)
        return self.food_order(order_id) or {}

    def update_food_order(self, order_id: int, status: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE food_orders SET status=?, updated_at=? WHERE id=?",
                (str(status), time.time(), int(order_id)),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def food_order(self, order_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM food_orders WHERE id=?", (int(order_id),)
            ).fetchone()
        if not row:
            return None
        return self._food_row(row)

    def recent_food_orders(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM food_orders ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [self._food_row(r) for r in rows]

    @staticmethod
    def _food_row(row: Any) -> dict[str, Any]:
        d = dict(row)
        try:
            d["items"] = json.loads(d.get("items") or "[]")
        except Exception:  # noqa: BLE001
            d["items"] = []
        return d

    def create_mall_order(self, items: list[dict[str, Any]], total: float,
                          address: str) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO mall_orders(items,total,address,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)",
                (json.dumps(items, ensure_ascii=False), float(total), str(address), "paid", now, now),
            )
            self._conn.commit()
            order_id = int(cur.lastrowid or 0)
        return self.mall_order(order_id) or {}

    def update_mall_order(self, order_id: int, status: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE mall_orders SET status=?, updated_at=? WHERE id=?",
                (str(status), time.time(), int(order_id)),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def mall_order(self, order_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM mall_orders WHERE id=?", (int(order_id),)
            ).fetchone()
        if not row:
            return None
        return self._food_row(row)

    def recent_mall_orders(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM mall_orders ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [self._food_row(r) for r in rows]

    def add_short_comment(self, video_id: str, user: str, text: str,
                          reply_to: int = 0) -> int:
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO short_comments(video_id,user,text,reply_to,created_at) "
                "VALUES(?,?,?,?,?)",
                (str(video_id), str(user), str(text)[:300], int(reply_to), now),
            )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def short_comments(self, video_id: str, limit: int = 80) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM short_comments WHERE video_id=? ORDER BY id ASC LIMIT ?",
                (str(video_id), int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    def life_event(self, event_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM life_events WHERE id=?", (int(event_id),)
            ).fetchone()
        return dict(row) if row else None

    def pending_life_events(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM life_events WHERE status='waiting' "
                "ORDER BY CASE WHEN expected_at>0 THEN expected_at ELSE created_at END"
            ).fetchall()
        return [dict(r) for r in rows]

    def recent_life_events(self, hours: float = 8, limit: int = 12) -> list[dict[str, Any]]:
        since = time.time() - max(1.0, float(hours)) * 3600
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM life_events WHERE created_at>=? ORDER BY created_at DESC LIMIT ?",
                (since, max(1, min(50, int(limit)))),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass

    def backup_to(self, path: Path) -> Path:
        """整库备份（换人设前用），返回备份路径。"""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            dst = sqlite3.connect(target)
            try:
                with dst:
                    self._conn.backup(dst)
            finally:
                dst.close()
        return target

    def archive_all_memories(self, keep_personal: bool = True) -> int:
        """换人设：旧记忆归档，不再进入检索，但不物理删除。

        默认保留“关于他”的事实/偏好/承诺——换掉的是人设，不是这个人。
        自我设定（person 为空）照常归档，避免旧身份和新身份打架。
        """
        with self._lock:
            if keep_personal:
                cur = self._conn.execute(
                    """UPDATE memories SET status='archived'
                       WHERE status!='archived'
                         AND NOT (kind IN ('fact','preference','promise')
                                  AND TRIM(person)!='')"""
                )
            else:
                cur = self._conn.execute(
                    "UPDATE memories SET status='archived' WHERE status!='archived'"
                )
            self._conn.commit()
            return int(cur.rowcount or 0)

    def restore_personal_memories(self) -> int:
        """把被换人设误伤的“关于他”的事实恢复回检索池，只用于历史库补救。"""
        with self._lock:
            cur = self._conn.execute(
                """UPDATE memories SET status='active'
                   WHERE status='archived'
                     AND kind IN ('fact','preference','promise')
                     AND TRIM(person) IN ('他','袁伟航')"""
            )
            self._conn.commit()
            return int(cur.rowcount or 0)

    def delete_her_dynamics(self) -> int:
        """换人设：删掉她以前发的动态及对应赞/评论，保留用户自己的动态。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM dynamics WHERE author='her'"
            ).fetchall()
            ids = [int(r["id"]) for r in rows]
            if not ids:
                return 0
            targets = [f"dyn:{i}" for i in ids]
            marks = ",".join("?" for _ in targets)
            self._conn.execute(
                f"DELETE FROM post_likes WHERE target IN ({marks})", tuple(targets)
            )
            self._conn.execute(
                f"DELETE FROM post_comments WHERE target IN ({marks})", tuple(targets)
            )
            self._conn.execute(
                f"DELETE FROM dynamics WHERE id IN ({','.join('?' for _ in ids)})",
                tuple(ids),
            )
            # 她以前在用户动态下的赞和评论也属于旧人设，一起清掉
            self._conn.execute("DELETE FROM post_likes WHERE user='her'")
            self._conn.execute("DELETE FROM post_comments WHERE user='her'")
            self._conn.commit()
            return len(ids)

    def clear_life_events(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM life_events")
            self._conn.commit()

    def clear_pending_replies(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM pending_replies")
            self._conn.commit()

    def reset_social_network(self) -> None:
        """可选：只留下她和用户，其余关系清空后重新生长。"""
        with self._lock:
            self._conn.execute("DELETE FROM social_edges")
            self._conn.execute("DELETE FROM social_nodes WHERE id NOT IN ('her','user')")
            self.store_state_unlocked("social_seeded", False)
            self.store_state_unlocked("social_v51_seeded", False)
            self._conn.commit()

    def store_state_unlocked(self, key: str, value: Any) -> None:
        """调用方已持有锁时使用。"""
        self._conn.execute(
            """INSERT INTO state(key,value,updated_at) VALUES(?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, json.dumps(value, ensure_ascii=False), time.time()),
        )

    def last_message_ts(self, role: str | None = None, before: float | None = None) -> float:
        sql = "SELECT MAX(ts) FROM messages"
        params: list[Any] = []
        clauses = []
        if role:
            clauses.append("role=?")
            params.append(role)
        if before is not None:
            clauses.append("ts<?")
            params.append(float(before))
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        with self._lock:
            row = self._conn.execute(sql, tuple(params)).fetchone()
        return float(row[0] or 0)

    # ---------- 记忆 ----------
    def upsert_memory(self, kind: str, key: str, value: str, confidence: float = 0.7, source: str = "") -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                """INSERT INTO memories(kind,key,value,confidence,source,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(kind,key) DO UPDATE SET
                     value=excluded.value,
                     confidence=MAX(memories.confidence, excluded.confidence),
                     updated_at=excluded.updated_at""",
                (kind, key, value, confidence, source, now, now),
            )
            self._conn.commit()

    def all_memories(self, limit: int = 300, include_archived: bool = False) -> list[dict[str, Any]]:
        sql = """SELECT id,kind,key,value,confidence,created_at,updated_at,source,layer,person,person_id,
                          domain,scene,emotion,intensity,hooks,interpretation,weight,status,review_count,
                          last_review_at,next_review_at,mainline_link,code,valid_until,falsifier,refraction_id
                   FROM memories"""
        if not include_archived:
            sql += " WHERE status!='archived'"
        sql += " ORDER BY updated_at DESC LIMIT ?"
        with self._lock:
            rows = self._conn.execute(sql, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def adjust_memory(
        self,
        memory_id: int,
        *,
        weight: float | None = None,
        status: str | None = None,
        confidence: float | None = None,
        value: str | None = None,
    ) -> None:
        """调权重/状态/置信度；只有改内容才动 updated_at 并留一条版本。"""
        sets: list[str] = []
        args: list[Any] = []
        if value is not None:
            text = str(value).strip()[:300]
            if text:
                old = self.memory_by_id(memory_id) or {}
                if str(old.get("value") or "") and str(old.get("value")) != text:
                    with self._lock:
                        self._conn.execute(
                            """INSERT INTO memory_versions(memory_id,kind,key,value,interpretation,reason,created_at)
                               VALUES(?,?,?,?,?,?,?)""",
                            (
                                memory_id, str(old.get("kind") or ""), str(old.get("key") or ""),
                                str(old.get("value") or ""), str(old.get("interpretation") or ""),
                                "手动修正", time.time(),
                            ),
                        )
                        self._conn.commit()
                sets.append("value=?")
                args.append(text)
                sets.append("updated_at=?")
                args.append(time.time())
                sets.append("status='revised'")
        if weight is not None:
            sets.append("weight=?")
            args.append(max(0.1, min(1.0, float(weight))))
        if status:
            sets.append("status=?")
            args.append(str(status)[:20])
        if confidence is not None:
            sets.append("confidence=?")
            args.append(max(0.3, min(0.95, float(confidence))))
        if not sets:
            return
        args.append(memory_id)
        with self._lock:
            self._conn.execute(f"UPDATE memories SET {','.join(sets)} WHERE id=?", args)
            self._conn.commit()

    def rename_identity_terms(
        self,
        old_names: Iterable[str] = ("陈雨棠", "干饭鱼", "鱼鱼"),
        new_name: str = "小鲸鱼",
    ) -> int:
        """把记忆正文、标题和版本链里的旧名字统一替换成新名字。"""
        olds = tuple(str(n) for n in old_names if str(n) and str(n) != new_name)
        if not olds or not new_name:
            return 0

        def sub(text: str) -> str:
            for old in olds:
                text = text.replace(old, new_name)
            return text

        changed = 0
        with self._lock:
            rows = self._conn.execute(
                "SELECT id,key,value,interpretation,hooks FROM memories"
            ).fetchall()
            for row in rows:
                mid = int(row["id"])
                old_key = str(row["key"] or "")
                old_value = str(row["value"] or "")
                old_interp = str(row["interpretation"] or "")
                old_hooks = str(row["hooks"] or "")
                new_key = sub(old_key)
                new_value = sub(old_value)
                new_interp = sub(old_interp)
                new_hooks = sub(old_hooks)
                if old_key == "小名鱼鱼":
                    new_key = "小名"
                    if any(old in old_value for old in olds):
                        new_value = f"她叫{new_name}，不喜欢被连名带姓喊，直接叫她{new_name}就好。"
                if (
                    new_key == old_key
                    and new_value == old_value
                    and new_interp == old_interp
                    and new_hooks == old_hooks
                ):
                    continue
                try:
                    self._conn.execute(
                        "UPDATE memories SET key=?,value=?,interpretation=?,hooks=? WHERE id=?",
                        (new_key, new_value, new_interp, new_hooks, mid),
                    )
                except sqlite3.IntegrityError:
                    # 改标题撞上唯一键时，正文照改，标题保留原样
                    self._conn.execute(
                        "UPDATE memories SET value=?,interpretation=?,hooks=? WHERE id=?",
                        (new_value, new_interp, new_hooks, mid),
                    )
                changed += 1

            versions = self._conn.execute(
                "SELECT id,key,value,interpretation FROM memory_versions"
            ).fetchall()
            for row in versions:
                old_key = str(row["key"] or "")
                old_value = str(row["value"] or "")
                old_interp = str(row["interpretation"] or "")
                new_key = sub(old_key)
                new_value = sub(old_value)
                new_interp = sub(old_interp)
                if old_key == "小名鱼鱼":
                    new_key = "小名"
                    if any(old in old_value for old in olds):
                        new_value = f"她叫{new_name}，不喜欢被连名带姓喊，直接叫她{new_name}就好。"
                if new_key == old_key and new_value == old_value and new_interp == old_interp:
                    continue
                self._conn.execute(
                    "UPDATE memory_versions SET key=?,value=?,interpretation=? WHERE id=?",
                    (new_key, new_value, new_interp, int(row["id"])),
                )
                changed += 1
            self._conn.commit()
        return changed

    def memory_by_key(self, kind: str, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """SELECT * FROM memories WHERE kind=? AND key=? AND status!='archived'
                   ORDER BY id LIMIT 1""",
                (kind, key),
            ).fetchone()
        return dict(row) if row else None

    def memory_by_id(self, memory_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        return dict(row) if row else None

    def memory_by_code(self, code: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memories WHERE code=? AND status!='archived' ORDER BY id LIMIT 1",
                (str(code or ""),),
            ).fetchone()
        return dict(row) if row else None

    def add_memory_version(
        self,
        memory_id: int,
        kind: str,
        key: str,
        value: str,
        interpretation: str,
        reason: str,
        overcame: str = "",
        kept: str = "",
        raised: str = "",
    ) -> None:
        """M11 扬弃：旧版本永不删除，并显式写出克服/保留/提升。"""
        with self._lock:
            self._conn.execute(
                """INSERT INTO memory_versions(memory_id,kind,key,value,interpretation,reason,
                     overcame,kept,raised,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    int(memory_id), str(kind or "")[:20], str(key or "")[:60],
                    str(value or "")[:300], str(interpretation or "")[:300],
                    str(reason or "")[:200], str(overcame or "")[:200],
                    str(kept or "")[:200], str(raised or "")[:300], time.time(),
                ),
            )
            self._conn.commit()

    def apply_evolution(self, memory_id: int, interpretation: str, status: str = "revised") -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE memories SET interpretation=?,status=?,updated_at=? WHERE id=?",
                (
                    str(interpretation or "")[:300], str(status or "revised")[:20],
                    time.time(), int(memory_id),
                ),
            )
            self._conn.commit()

    def _find_node(self, name: str) -> dict[str, Any] | None:
        """按人名找关系节点：先精确匹配，再在称呼里找最长的节点名。"""
        name = str(name or "").strip()
        if not name:
            return None
        rows = self._conn.execute("SELECT id,name,role FROM social_nodes").fetchall()
        for r in rows:
            if r["name"] == name:
                return dict(r)
        contain = [r for r in rows if len(r["name"]) >= 2 and r["name"] in name]
        if contain:
            contain.sort(key=lambda r: len(r["name"]), reverse=True)
            return dict(contain[0])
        return None

    def social_node_by_name(self, name: str) -> dict[str, Any] | None:
        with self._lock:
            return self._find_node(name)

    def social_relation(self, node_id: str) -> dict[str, Any] | None:
        """某个人此刻和她（her）的关系状态。"""
        if not node_id:
            return None
        with self._lock:
            row = self._conn.execute(
                """SELECT n.id,n.name,n.role,n.active,e.depth,e.trust,e.intimacy,e.conflict
                   FROM social_nodes n
                   LEFT JOIN social_edges e
                     ON (e.a='her' AND e.b=n.id) OR (e.b='her' AND e.a=n.id)
                   WHERE n.id=?""",
                (node_id,),
            ).fetchone()
        return dict(row) if row else None

    def insert_memory(self, rec: dict[str, Any]) -> tuple[int, bool]:
        """写入一条结构化记忆；同 kind+key 已存在则先快照旧版，再原地修正。

        返回 (记忆 id, 是否属于修正)。
        """
        now = time.time()
        kind = str(rec.get("kind") or "fact")[:20]
        key = str(rec.get("key") or "")[:60]
        falsifier = str(rec.get("falsifier") or "").strip()[:300]
        if not falsifier:
            falsifier = "若他明确否认，或与后续事实相反，此条作废"
        with self._lock:
            old = self._conn.execute(
                "SELECT id,code,value,interpretation,review_count,status,falsifier FROM memories WHERE kind=? AND key=?",
                (kind, key),
            ).fetchone()
            revised = False
            if old:
                same_text = (
                    old["value"] == rec.get("value", "")
                    and (old["interpretation"] or "") == rec.get("interpretation", "")
                )
                revised = not same_text
                if revised:
                    self._conn.execute(
                        """INSERT INTO memory_versions(memory_id,kind,key,value,interpretation,reason,created_at)
                           VALUES(?,?,?,?,?,?,?)""",
                        (
                            old["id"], kind, key, old["value"], old["interpretation"] or "",
                            str(rec.get("reason") or "新版覆盖")[:200], now,
                        ),
                    )
                self._conn.execute(
                    """UPDATE memories SET value=?,confidence=MAX(confidence,?),updated_at=?,
                         layer=?,person=?,person_id=?,domain=?,scene=?,emotion=?,intensity=?,hooks=?,
                         interpretation=?,weight=?,mainline_link=?,valid_until=?,
                         falsifier=COALESCE(NULLIF(?, ''), falsifier),
                         refraction_id=COALESCE(NULLIF(?, 0), refraction_id),
                         status=CASE WHEN ? THEN 'revised' ELSE status END
                       WHERE id=?""",
                    (
                        rec.get("value", ""), rec.get("confidence", 0.7), now,
                        rec.get("layer", "L3"), rec.get("person", ""), rec.get("person_id", ""),
                        rec.get("domain", ""), rec.get("scene", ""), rec.get("emotion", ""),
                        rec.get("intensity", 2), rec.get("hooks", ""), rec.get("interpretation", ""),
                        rec.get("weight", 0.1), rec.get("mainline_link", 1.0),
                        float(rec.get("valid_until") or 0), falsifier,
                        int(rec.get("refraction_id") or 0),
                        1 if revised else 0, old["id"],
                    ),
                )
                mid = int(old["id"])
            else:
                cur = self._conn.execute(
                    """INSERT INTO memories(kind,key,value,confidence,source,created_at,updated_at,
                         layer,person,person_id,domain,scene,emotion,intensity,hooks,interpretation,weight,
                         status,review_count,last_review_at,next_review_at,mainline_link,valid_until,
                         falsifier,refraction_id)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,?,?,?,?,?)""",
                    (
                        kind, key, rec.get("value", ""), rec.get("confidence", 0.7),
                        rec.get("source", ""), now, now,
                        rec.get("layer", "L3"), rec.get("person", ""), rec.get("person_id", ""),
                        rec.get("domain", ""), rec.get("scene", ""), rec.get("emotion", ""),
                        rec.get("intensity", 2), rec.get("hooks", ""), rec.get("interpretation", ""),
                        rec.get("weight", 0.1), "active", now + 86400, rec.get("mainline_link", 1.0),
                        float(rec.get("valid_until") or 0), falsifier,
                        int(rec.get("refraction_id") or 0),
                    ),
                )
                mid = int(cur.lastrowid or 0)
            layer = str(rec.get("layer") or "L3")[:2].upper()
            self._conn.execute(
                "UPDATE memories SET code=? WHERE id=?", (f"{layer}-{mid:03d}", mid)
            )
            self._conn.commit()
        if revised and old and str(old["code"] or ""):
            try:
                self.add_qt_outcome(
                    str(old["code"]), "refuted", "新版覆盖旧说法", 0.5, "memory.revise"
                )
            except Exception:  # noqa: BLE001
                pass
        person = str(rec.get("person") or "").strip()
        if person and mid:
            try:
                self.add_qt_internalization(
                    person,
                    str(rec.get("source") or "memory"),
                    str(rec.get("window_state") or "unknown"),
                    f"{kind}:{key}",
                )
            except Exception:  # noqa: BLE001
                pass
        return mid, revised

    def memory_versions(self, memory_id: int, limit: int = 5) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT value,interpretation,reason,overcame,kept,raised,created_at
                   FROM memory_versions WHERE memory_id=? ORDER BY id DESC LIMIT ?""",
                (memory_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def due_review_memories(self, now: float | None = None, limit: int = 3) -> list[dict[str, Any]]:
        now = now or time.time()
        with self._lock:
            rows = self._conn.execute(
                """SELECT id,kind,key,value,interpretation,emotion,intensity,layer,code,
                          weight,review_count,next_review_at
                   FROM memories
                   WHERE status!='archived' AND weight>=0.2 AND next_review_at>0
                     AND next_review_at<=?
                   ORDER BY weight DESC, next_review_at LIMIT ?""",
                (now, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_memory_reviewed(self, memory_id: int, next_ts: float) -> None:
        with self._lock:
            self._conn.execute(
                """UPDATE memories SET review_count=review_count+1, last_review_at=?,
                     next_review_at=? WHERE id=?""",
                (time.time(), next_ts, memory_id),
            )
            self._conn.commit()

    def set_memory_next_review(self, memory_id: int, next_ts: float) -> None:
        """只挪下次回访时间，不动 review_count（错峰积压用）。"""
        with self._lock:
            self._conn.execute(
                "UPDATE memories SET next_review_at=? WHERE id=?", (float(next_ts), memory_id)
            )
            self._conn.commit()

    def replace_memory_links(self, pairs: list[tuple[int, int, float, str]]) -> int:
        """整表重建记忆图谱；pairs=(a,b,weight,reason)，无向，按 a<b 存。"""
        now = time.time()
        with self._lock:
            self._conn.execute("DELETE FROM memory_links")
            self._conn.executemany(
                "INSERT OR REPLACE INTO memory_links(a,b,weight,reason,updated_at) VALUES(?,?,?,?,?)",
                [(min(a, b), max(a, b), float(w), str(r), now) for a, b, w, r in pairs],
            )
            self._conn.commit()
        return len(pairs)

    def memory_link_count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM memory_links").fetchone()
        return int(row["n"] or 0)

    def memory_links(self, memory_id: int, limit: int = 5) -> list[dict[str, Any]]:
        """查 1 跳关联记忆（同一人、同一话题、共现过的）。"""
        with self._lock:
            rows = self._conn.execute(
                """SELECT l.weight AS link_weight, l.reason AS link_reason, m.*
                     FROM memory_links l
                     JOIN memories m ON m.id = CASE WHEN l.a=? THEN l.b ELSE l.a END
                    WHERE (l.a=? OR l.b=?) AND m.status!='archived'
                    ORDER BY l.weight DESC LIMIT ?""",
                (memory_id, memory_id, memory_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def memory_links_all(self) -> list[dict[str, Any]]:
        """全量图谱边（图谱可视化/导出用；量级≈节点数×5，直接全取）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT a,b,weight,reason FROM memory_links"
            ).fetchall()
        return [dict(r) for r in rows]

    def export_memories(self) -> dict[str, Any]:
        """完整备份：含已归档记忆；图谱边用 kind+key 引用，换设备导入后也能对上。"""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM memories ORDER BY id").fetchall()
        mems = [dict(r) for r in rows]
        by_id = {int(m["id"]): m for m in mems}
        links = []
        for link in self.memory_links_all():
            a, b = by_id.get(int(link["a"])), by_id.get(int(link["b"]))
            if not a or not b:
                continue
            links.append({
                "a": {"kind": a["kind"], "key": a["key"]},
                "b": {"kind": b["kind"], "key": b["key"]},
                "weight": float(link.get("weight") or 0),
                "reason": str(link.get("reason") or ""),
            })
        return {"memories": mems, "links": links}

    def add_brainn_transition(self, record: dict[str, Any]) -> None:
        """影子运行日志：为以后训练拍卖/提案/叙事留样本。"""
        def dump(value: Any) -> str:
            return json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value

        with self._lock:
            self._conn.execute(
                """INSERT INTO brainn_transitions(ts,percept,states,proposals,budget,winner,
                     distortion,bypass,action,outcome,latency_ms)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    time.time(),
                    dump(record.get("percept", {})),
                    dump(record.get("states", {})),
                    dump(record.get("proposals", [])),
                    float(record.get("budget", 1.0) or 1.0),
                    dump(record.get("winner", {})),
                    dump(record.get("distortion", {})),
                    dump(record.get("bypass", {})),
                    dump(record.get("action", {})),
                    dump(record.get("outcome", {})),
                    float(record.get("latency_ms", 0.0) or 0.0),
                ),
            )
            self._transition_writes += 1
            if self._transition_writes % 200 == 0:
                self._conn.execute(
                    """DELETE FROM brainn_transitions WHERE id NOT IN
                       (SELECT id FROM brainn_transitions ORDER BY id DESC LIMIT 5000)"""
                )
            self._commit()

    # ---------- QT 账本 ----------
    def _qt_insert(self, table: str, columns: tuple[str, ...], values: tuple[Any, ...],
                   ignore: bool = False) -> int:
        with self._lock:
            prefix = "INSERT OR IGNORE" if ignore else "INSERT"
            cur = self._conn.execute(
                f"{prefix} INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                values,
            )
            self._qt_writes += 1
            if self._qt_writes % 500 == 0:
                for name in (
                    "qt_refractions", "qt_tensions", "qt_transitions", "qt_artifacts",
                    "qt_outcomes", "qt_metrics", "qt_internalization", "qt_absences",
                ):
                    self._conn.execute(
                        f"""DELETE FROM {name} WHERE id NOT IN
                           (SELECT id FROM {name} ORDER BY id DESC LIMIT 5000)"""
                    )
            self._commit()
            return int(cur.lastrowid or 0)

    def add_qt_refraction(
        self,
        before: str,
        after: str,
        medium: dict[str, Any] | None = None,
        confidence: float = 0,
        note: str = "",
    ) -> int:
        """M7：记录一次折射前后的差。"""
        return self._qt_insert(
            "qt_refractions",
            ("ts", "before", "after", "medium", "confidence", "note"),
            (
                time.time(), str(before or "")[:500], str(after or "")[:500],
                json.dumps(medium or {}, ensure_ascii=False),
                float(confidence or 0), str(note or "")[:200],
            ),
        )

    def add_qt_tension(
        self,
        a_ref: str = "",
        b_ref: str = "",
        topic: str = "",
        accumulation: float = 0,
        threshold: float = 10,
        note: str = "",
        status: str = "open",
        meta: dict[str, Any] | None = None,
    ) -> int:
        """M9：登记一条尚未消解的认识张力。"""
        return self._qt_insert(
            "qt_tensions",
            ("ts", "a_ref", "b_ref", "topic", "accumulation", "threshold", "note", "status", "meta"),
            (
                time.time(), str(a_ref or "")[:80], str(b_ref or "")[:80],
                str(topic or "")[:120], float(accumulation or 0),
                float(threshold or 10), str(note or "")[:200],
                str(status or "open")[:20], json.dumps(meta or {}, ensure_ascii=False),
            ),
        )

    def bump_qt_tension(
        self,
        a_ref: str,
        b_ref: str,
        topic: str,
        delta: float = 1.0,
        threshold: float = 10,
        note: str = "",
    ) -> dict[str, Any]:
        """同一对认识再次冲突时累加；没有则新建。"""
        with self._lock:
            row = self._conn.execute(
                """SELECT id,accumulation FROM qt_tensions
                   WHERE a_ref=? AND b_ref=? AND topic=? AND status='open'
                   ORDER BY id DESC LIMIT 1""",
                (str(a_ref or "")[:80], str(b_ref or "")[:80], str(topic or "")[:120]),
            ).fetchone()
        if row:
            acc = float(row["accumulation"] or 0) + float(delta or 0)
            with self._lock:
                self._conn.execute(
                    "UPDATE qt_tensions SET accumulation=?, ts=? WHERE id=?",
                    (round(acc, 3), time.time(), int(row["id"])),
                )
                self._conn.commit()
            return {"id": int(row["id"]), "accumulation": round(acc, 3), "created": False}
        tid = self.add_qt_tension(a_ref, b_ref, topic, delta, threshold, note)
        return {"id": tid, "accumulation": round(float(delta), 3), "created": True}

    def qt_tensions_ready(self, threshold: float = 10, limit: int = 5) -> list[dict[str, Any]]:
        """M10 入口：累积到阈值的认识张力；自我人格冲突与 M14 待确认不算。"""
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM qt_tensions
                   WHERE status='open' AND accumulation>=?
                     AND a_ref NOT IN ('QT.M9','M14 反观确证')
                     AND topic NOT IN ('自我节点变更待确认')
                   ORDER BY accumulation DESC, id ASC LIMIT ?""",
                (float(threshold), int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    def qt_tension(self, tension_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM qt_tensions WHERE id=?", (int(tension_id),)
            ).fetchone()
        return dict(row) if row else None

    def qt_pending_m14(self, limit: int = 5) -> list[dict[str, Any]]:
        """等待她自己判断的 M14 反观提案；按登记顺序先处理旧的。"""
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM qt_tensions
                   WHERE status='pending'
                     AND (a_ref='M14 反观确证' OR topic='自我节点变更待确认')
                   ORDER BY id ASC LIMIT ?""",
                (int(limit),),
            ).fetchall()
        return [dict(r) for r in rows]


    def set_qt_tension_status(self, tension_id: int, status: str, note: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE qt_tensions SET status=?, note=CASE WHEN ?='' THEN note ELSE ? END, ts=? WHERE id=?",
                (str(status or "open")[:20], str(note or "")[:200], str(note or "")[:200], time.time(), int(tension_id)),
            )
            self._conn.commit()

    def add_qt_transition(
        self,
        from_state: str,
        to_state: str,
        retained: str = "",
        reason: str = "",
        meta: dict[str, Any] | None = None,
    ) -> int:
        """M10：结构变化日志；与单轮的 brainn_transitions 区分。"""
        return self._qt_insert(
            "qt_transitions",
            ("ts", "from_state", "to_state", "retained", "reason", "meta"),
            (
                time.time(), str(from_state or "")[:120], str(to_state or "")[:120],
                str(retained or "")[:300], str(reason or "")[:200],
                json.dumps(meta or {}, ensure_ascii=False),
            ),
        )

    def add_qt_artifact(
        self,
        artifact_id: str,
        kind: str = "",
        name: str = "",
        content_hash: str = "",
        owner: str = "",
        meta: dict[str, Any] | None = None,
    ) -> int:
        """M13：产物档案，内容寻址。"""
        return self._qt_insert(
            "qt_artifacts",
            ("ts", "artifact_id", "kind", "name", "content_hash", "owner", "meta"),
            (
                time.time(), str(artifact_id or "")[:60], str(kind or "")[:40],
                str(name or "")[:160], str(content_hash or "")[:64],
                str(owner or "")[:60], json.dumps(meta or {}, ensure_ascii=False),
            ),
            ignore=True,
        )

    def add_qt_outcome(
        self,
        claim_ref: str,
        verdict: str = "unverified",
        evidence: str = "",
        confidence: float = 0,
        source: str = "",
    ) -> int:
        """M15：证实 / 证伪 / 未定。"""
        verdict = verdict if verdict in ("confirmed", "refuted", "unverified") else "unverified"
        return self._qt_insert(
            "qt_outcomes",
            ("ts", "claim_ref", "verdict", "evidence", "confidence", "source"),
            (
                time.time(), str(claim_ref or "")[:120], verdict,
                str(evidence or "")[:300], float(confidence or 0), str(source or "")[:60],
            ),
            ignore=True,
        )

    def add_qt_metric(
        self,
        prediction: str,
        hit: bool,
        match_score: float = 0,
        note: str = "",
    ) -> int:
        """M16：一次预判的命中与匹配度；score = hit × match。"""
        hit_i = 1 if hit else 0
        match = max(0.0, min(1.0, float(match_score or 0)))
        return self._qt_insert(
            "qt_metrics",
            ("ts", "prediction", "hit", "match_score", "score", "note"),
            (
                time.time(), str(prediction or "")[:200], hit_i,
                round(match, 3), round(hit_i * match, 3), str(note or "")[:200],
            ),
            ignore=True,
        )

    def set_qt_artifact_feedback(self, artifact_id: str, feedback: str) -> None:
        """用户承认/否认后，把反馈写回 M13 产物档案。"""
        aid = str(artifact_id or "")[:60]
        if not aid:
            return
        with self._lock:
            row = self._conn.execute(
                "SELECT id,meta FROM qt_artifacts WHERE artifact_id=? ORDER BY id DESC LIMIT 1",
                (aid,),
            ).fetchone()
            if not row:
                return
            try:
                meta = json.loads(row["meta"] or "{}")
            except (TypeError, ValueError):
                meta = {}
            meta["feedback"] = str(feedback or "unseen")[:20]
            self._conn.execute(
                "UPDATE qt_artifacts SET meta=? WHERE id=?",
                (json.dumps(meta, ensure_ascii=False), int(row["id"])),
            )
            self._conn.commit()

    def set_qt_outcome_verdict(
        self,
        claim_ref: str,
        verdict: str,
        evidence: str = "",
        confidence: float = 0.0,
    ) -> None:
        """用户反馈回来后更新 M15 判定；没有对应行就补一条。"""
        ref = str(claim_ref or "")[:120]
        if not ref:
            return
        verdict = verdict if verdict in ("confirmed", "refuted", "unverified") else "unverified"
        with self._lock:
            row = self._conn.execute(
                """SELECT id FROM qt_outcomes
                   WHERE claim_ref=? AND source='practice.backfill'
                   ORDER BY id DESC LIMIT 1""",
                (ref,),
            ).fetchone()
            if row:
                self._conn.execute(
                    "UPDATE qt_outcomes SET verdict=?, evidence=?, confidence=?, ts=? WHERE id=?",
                    (verdict, str(evidence or "")[:300], float(confidence or 0),
                     time.time(), int(row["id"])),
                )
                self._conn.commit()
                return
        self.add_qt_outcome(
            claim_ref=ref,
            verdict=verdict,
            evidence=evidence,
            confidence=confidence,
            source="practice.backfill",
        )

    def set_qt_metric_feedback(self, artifact_id: str, feedback: str) -> None:
        """用户反馈回来后更新 M16 命中与匹配度。"""
        aid = str(artifact_id or "")[:60]
        if not aid:
            return
        prediction = f"practice:{aid}"[:200]
        hit = 1 if str(feedback or "") == "recognized" else 0
        match = 0.8 if str(feedback or "") in ("recognized", "denied") else 0.2
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM qt_metrics WHERE prediction=? ORDER BY id DESC LIMIT 1",
                (prediction,),
            ).fetchone()
            if row:
                self._conn.execute(
                    """UPDATE qt_metrics SET hit=?, match_score=?, score=?, note=?, ts=?
                       WHERE id=?""",
                    (hit, match, round(hit * match, 3),
                     f"M16：劳动产物反馈（{feedback}）"[:200], time.time(), int(row["id"])),
                )
                self._conn.commit()

    def add_qt_internalization(
        self,
        person_ref: str,
        source_event: str = "",
        window_state: str = "unknown",
        note: str = "",
    ) -> int:
        """M2：内化来源与窗口状态。"""
        return self._qt_insert(
            "qt_internalization",
            ("ts", "person_ref", "source_event", "window_state", "note"),
            (
                time.time(), str(person_ref or "")[:80], str(source_event or "")[:120],
                str(window_state or "unknown")[:40], str(note or "")[:200],
            ),
        )

    def add_qt_absence(self, kind: str, since: float = 0, intensity: float = 0, note: str = "") -> int:
        """M6：缺失本身被体验到的记录。"""
        return self._qt_insert(
            "qt_absences",
            ("ts", "kind", "since", "intensity", "note"),
            (time.time(), str(kind or "")[:80], float(since or 0), float(intensity or 0), str(note or "")[:200]),
        )

    def db_counts(self) -> dict[str, int]:
        """提取记忆时写进清单：整库主要表的行数。"""
        tables = (
            "messages", "memories", "memory_links", "dynamics", "life_events",
            "mood_log", "proactive_log",
            "qt_refractions", "qt_tensions", "qt_transitions", "qt_artifacts",
            "qt_outcomes", "qt_metrics", "qt_internalization", "qt_absences",
        )
        counts: dict[str, int] = {}
        with self._lock:
            for name in tables:
                try:
                    row = self._conn.execute(f"SELECT COUNT(*) AS n FROM {name}").fetchone()
                    counts[name] = int(row["n"] or 0)
                except Exception:  # noqa: BLE001
                    counts[name] = 0
        return counts

    def qt_ledger_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self._lock:
            for name in (
                "qt_refractions", "qt_tensions", "qt_transitions", "qt_artifacts",
                "qt_outcomes", "qt_metrics", "qt_internalization", "qt_absences",
            ):
                row = self._conn.execute(f"SELECT COUNT(*) AS n FROM {name}").fetchone()
                counts[name] = int(row["n"] or 0)
        return counts

    def qt_recent(self, table: str, limit: int = 20) -> list[dict[str, Any]]:
        allowed = {
            "qt_refractions", "qt_tensions", "qt_transitions", "qt_artifacts",
            "qt_outcomes", "qt_metrics", "qt_internalization", "qt_absences",
        }
        if table not in allowed:
            return []
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (int(limit or 20),)
            ).fetchall()
        return [dict(r) for r in rows]

    def qt_pending_count(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM qt_tensions WHERE status='pending'"
            ).fetchone()
        return int(row["n"] or 0)

    def qt_metrics_summary(self, window: int = 30, prefix: str = "") -> dict[str, Any]:
        """M16 自由度：P = 命中率，M = 平均匹配度，D = P × M；只看趋势。"""
        limit = int(window or 30)
        like = (str(prefix or "") + "%")
        with self._lock:
            if prefix:
                rows = self._conn.execute(
                    "SELECT hit,match_score,score FROM qt_metrics WHERE prediction LIKE ? "
                    "ORDER BY id DESC LIMIT ?",
                    (like, limit),
                ).fetchall()
                total = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM qt_metrics WHERE prediction LIKE ?", (like,)
                ).fetchone()["n"]
            else:
                rows = self._conn.execute(
                    "SELECT hit,match_score,score FROM qt_metrics ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                total = self._conn.execute("SELECT COUNT(*) AS n FROM qt_metrics").fetchone()["n"]
        items = [dict(r) for r in rows]
        n = len(items)
        hits = sum(1 for r in items if int(r.get("hit") or 0))
        p = round(hits / n, 3) if n else 0.0
        m = round(sum(float(r.get("match_score") or 0) for r in items) / n, 3) if n else 0.0
        return {
            "total": int(total or 0),
            "window": n,
            "hits": hits,
            "hit_rate": p,
            "match_rate": m,
            "freedom": round(p * m, 3),
        }

    def memory_stats(self) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT layer, COUNT(*) AS n FROM memories WHERE status!='archived' GROUP BY layer"
            ).fetchall()
            revised = self._conn.execute(
                "SELECT COUNT(*) FROM memories WHERE status='revised'"
            ).fetchone()[0]
            due = self._conn.execute(
                "SELECT COUNT(*) FROM memories WHERE status!='archived' AND weight>=0.2 AND next_review_at>0 AND next_review_at<=?",
                (time.time(),),
            ).fetchone()[0]
            versions = self._conn.execute("SELECT COUNT(*) FROM memory_versions").fetchone()[0]
        return {
            "layers": {r["layer"]: int(r["n"]) for r in rows},
            "revised": int(revised or 0),
            "due_review": int(due or 0),
            "versions": int(versions or 0),
        }

    # ---------- 状态 ----------
    def get_state(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def set_state(self, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, json.dumps(value, ensure_ascii=False), time.time()),
            )
            self._commit()

    # ---------- 情绪日志 ----------
    def log_mood(self, snap: dict[str, float], reason: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO mood_log(ts,mood,affection,grievance,jealousy,sanity,reason) VALUES(?,?,?,?,?,?,?)",
                (time.time(), snap.get("mood"), snap.get("affection"), snap.get("grievance"), snap.get("jealousy"), snap.get("sanity"), reason),
            )
            self._conn.commit()

    # ---------- 主动消息 ----------
    def log_proactive(self, topic: str, text: str, ts: float | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO proactive_log(ts, topic, text) VALUES(?,?,?)",
                (ts or time.time(), topic, text[:500]),
            )
            self._conn.commit()

    def proactive_since(self, start: float) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM proactive_log WHERE ts>=?", (start,)).fetchone()
        return int(row[0] or 0)

    def last_proactive_ts(self) -> float:
        with self._lock:
            row = self._conn.execute("SELECT MAX(ts) FROM proactive_log").fetchone()
        return float(row[0] or 0)

    def proactive_items_since(self, since: float, limit: int = 20) -> list[dict[str, Any]]:
        """主动消息增量：2D 页气泡 / 桌宠气泡按时间戳拉取。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, topic, text FROM proactive_log WHERE ts>? AND TRIM(text)!=''"
                " ORDER BY id ASC LIMIT ?",
                (float(since or 0), int(limit or 20)),
            ).fetchall()
        return [dict(r) for r in rows]

    def last_topic(self, n: int = 6) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT topic FROM proactive_log ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return [r["topic"] for r in rows if r["topic"]]

    # ---------- 提醒 ----------
    def add_reminder(self, due_at: float, content: str) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO reminders(due_at,content) VALUES(?,?)", (due_at, content))
            self._conn.commit()

    def due_reminders(self, now: float | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id,due_at,content FROM reminders WHERE done=0 AND due_at<=? ORDER BY due_at",
                (now or time.time(),),
            ).fetchall()
        return [dict(r) for r in rows]

    def close_reminder(self, rid: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE reminders SET done=1 WHERE id=?", (rid,))
            self._conn.commit()

    def clear_mood_history(self, keep: int = 2000) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM mood_log WHERE id NOT IN (SELECT id FROM mood_log ORDER BY id DESC LIMIT ?)", (keep,)
            )
            self._conn.commit()

    # ---------- 每日总结 ----------
    def add_summary(self, date: str, summary: str) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO daily_summaries(date,summary,created_at) VALUES(?,?,?)
                   ON CONFLICT(date) DO UPDATE SET summary=excluded.summary, created_at=excluded.created_at""",
                (date, summary[:1200], time.time()),
            )
            self._conn.commit()

    def recent_summaries(self, limit: int = 3) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT date,summary,created_at FROM daily_summaries ORDER BY date DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------- 夜间待回队列 ----------
    def add_pending(
        self,
        text: str,
        kind: str,
        url: str | None,
        image_url: str | None,
        user_id: int | None,
        due_at: float,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO pending_replies(ts,due_at,text,kind,url,image_url,user_id) VALUES(?,?,?,?,?,?,?)",
                (time.time(), due_at, text[:1000], kind, url or "", image_url or "", int(user_id or 0)),
            )
            self._conn.commit()

    def due_pending(self, now: float | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id,ts,due_at,text,kind,url,image_url,user_id FROM pending_replies WHERE due_at<=? ORDER BY id",
                (now or time.time(),),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_pending(self, pid: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM pending_replies WHERE id=?", (pid,))
            self._conn.commit()

    # ---------- 自动动态 ----------
    def add_dynamic(
        self, text: str, topic: str, platform: str, images: list[str] | None = None,
        author: str = "her",
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO dynamics(ts,text,topic,platform,images,author) VALUES(?,?,?,?,?,?)",
                (
                    time.time(),
                    text[:1200],
                    topic[:200],
                    platform,
                    json.dumps(images or [], ensure_ascii=False),
                    str(author or "her")[:20],
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def recent_comments_by_user(self, user: str, limit: int = 3) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT text FROM post_comments WHERE user=? ORDER BY ts DESC LIMIT ?",
                (str(user), max(1, int(limit))),
            ).fetchall()
        return [str(r["text"] or "") for r in rows if r["text"]]

    def recent_dynamics(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id,ts,text,topic,platform,images,author FROM dynamics ORDER BY id DESC LIMIT ?",
                (max(1, min(100, limit)),),
            ).fetchall()
        out = []
        for row in reversed(rows):
            item = dict(row)
            try:
                item["images"] = json.loads(item.get("images") or "[]")
            except Exception:  # noqa: BLE001
                item["images"] = []
            out.append(item)
        return out

    def update_dynamic_images(self, dynamic_id: int, images: list[str]) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE dynamics SET images=? WHERE id=?",
                (json.dumps(images or [], ensure_ascii=False), int(dynamic_id)),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def delete_post_comment(self, comment_id: int, user: str = "user") -> bool:
        """他只能删自己的评论；连带删掉别人对这条评论的回复。"""
        cid = int(comment_id or 0)
        if cid <= 0:
            return False
        with self._lock:
            row = self._conn.execute(
                "SELECT user FROM post_comments WHERE id=?", (cid,)
            ).fetchone()
            if not row or str(row["user"]) != str(user):
                return False
            self._conn.execute(
                "DELETE FROM post_comments WHERE id=? OR parent_id=?", (cid, cid)
            )
            self._conn.commit()
        return True

    def dynamic_since(self, start: float) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM dynamics WHERE ts>=?", (start,)).fetchone()
        return int(row[0] or 0)

    def last_dynamic_ts(self) -> float:
        with self._lock:
            row = self._conn.execute("SELECT MAX(ts) FROM dynamics").fetchone()
        return float(row[0] or 0)

    def delete_dynamic(self, dynamic_id: int, author: str = "user") -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT author FROM dynamics WHERE id=?", (int(dynamic_id),)
            ).fetchone()
            if not row:
                return False
            if str(row["author"] or "her") != str(author):
                return False
            target = f"dyn:{int(dynamic_id)}"
            self._conn.execute("DELETE FROM dynamics WHERE id=?", (int(dynamic_id),))
            self._conn.execute("DELETE FROM post_likes WHERE target=?", (target,))
            self._conn.execute("DELETE FROM post_comments WHERE target=?", (target,))
            self._conn.commit()
            return True

    def last_dynamic_topics(self, n: int = 5) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT topic FROM dynamics ORDER BY id DESC LIMIT ?", (n,)
            ).fetchall()
        return [r["topic"] for r in rows if r["topic"]]

    # ---------- 朋友圈：社会动态、点赞、评论 ----------
    def social_posts(self, day: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id,node,ts,text,day,images FROM social_posts WHERE day=? ORDER BY ts",
                (str(day),),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            try:
                item["images"] = json.loads(item.get("images") or "[]")
            except Exception:  # noqa: BLE001
                item["images"] = []
            out.append(item)
        return out

    def social_posts_recent(self, limit: int = 300) -> list[dict[str, Any]]:
        """历史朋友圈：不按天截断，长期保留，默认取最近 300 条。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id,node,ts,text,day,images FROM social_posts ORDER BY ts DESC LIMIT ?",
                (max(1, min(800, int(limit))),),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            try:
                item["images"] = json.loads(item.get("images") or "[]")
            except Exception:  # noqa: BLE001
                item["images"] = []
            out.append(item)
        return out

    def recent_social_texts(self, node: str, days: int = 7) -> list[str]:
        """该成员最近几天发过的文案，用于避免重复。"""
        since = time.time() - max(1, int(days)) * 86400
        with self._lock:
            rows = self._conn.execute(
                "SELECT text FROM social_posts WHERE node=? AND ts>=?",
                (str(node), since),
            ).fetchall()
        return [str(r["text"] or "") for r in rows if r["text"]]

    def add_social_post(
        self, post_id: str, node: str, text: str, day: str,
        images: list[str] | None = None, ts: float | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO social_posts(id,node,ts,text,day,images) VALUES(?,?,?,?,?,?)",
                (
                    str(post_id), str(node), float(ts or time.time()), str(text)[:400], str(day),
                    json.dumps(images or [], ensure_ascii=False),
                ),
            )
            self._conn.commit()

    def purge_social_posts(self) -> dict[str, int]:
        """一次性清掉“其他社会角色发的动态”及其点赞/评论；她自己的 dynamics 不动。"""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM social_posts").fetchone()
            count = int(row[0] or 0) if row else 0
            self._conn.execute("DELETE FROM post_likes WHERE target LIKE 'soc:%'")
            self._conn.execute("DELETE FROM post_comments WHERE target LIKE 'soc:%'")
            self._conn.execute("DELETE FROM social_posts")
            self._conn.commit()
        return {"posts": count}

    def update_social_post_images(self, post_id: str, images: list[str]) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE social_posts SET images=? WHERE id=?",
                (json.dumps(images or [], ensure_ascii=False), str(post_id)),
            )
            self._conn.commit()

    def add_like(self, target: str, user: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO post_likes(target,user,ts) VALUES(?,?,?)",
                (str(target), str(user), time.time()),
            )
            self._conn.commit()

    def toggle_like(self, target: str, user: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM post_likes WHERE target=? AND user=?",
                (str(target), str(user)),
            ).fetchone()
            if row:
                self._conn.execute(
                    "DELETE FROM post_likes WHERE target=? AND user=?",
                    (str(target), str(user)),
                )
                liked = False
            else:
                self._conn.execute(
                    "INSERT INTO post_likes(target,user,ts) VALUES(?,?,?)",
                    (str(target), str(user), time.time()),
                )
                liked = True
            self._conn.commit()
        return liked

    def add_comment(self, target: str, user: str, text: str, parent_id: int = 0) -> int:
        text = str(text or "").strip()[:300]
        if not text:
            return 0
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO post_comments(target,user,text,parent_id,ts) VALUES(?,?,?,?,?)",
                (str(target), str(user), text, int(parent_id or 0), time.time()),
            )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def likes_for(self, targets: list[str]) -> dict[str, list[str]]:
        targets = [str(t) for t in (targets or []) if t]
        if not targets:
            return {}
        marks = ",".join("?" for _ in targets)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT target,user FROM post_likes WHERE target IN ({marks}) ORDER BY ts",
                targets,
            ).fetchall()
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(str(r["target"]), []).append(str(r["user"]))
        return out

    def comments_for(self, targets: list[str]) -> dict[str, list[dict[str, Any]]]:
        targets = [str(t) for t in (targets or []) if t]
        if not targets:
            return {}
        marks = ",".join("?" for _ in targets)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT id,target,user,text,parent_id,ts FROM post_comments WHERE target IN ({marks}) ORDER BY id",
                targets,
            ).fetchall()
        out: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            out.setdefault(str(r["target"]), []).append(
                {
                    "id": r["id"], "user": str(r["user"]), "text": str(r["text"]),
                    "parent_id": int(r["parent_id"] or 0), "ts": r["ts"],
                }
            )
        return out

    def recent_post_activity(self, since: float, limit: int = 12) -> list[dict[str, Any]]:
        """最近朋友圈互动：他点的赞、他的评论，以及别人对他评论的回复。"""
        since = float(since or 0)
        if since <= 0:
            return []
        with self._lock:
            likes = self._conn.execute(
                "SELECT target, user, ts FROM post_likes WHERE ts>=? AND user='user' "
                "ORDER BY ts DESC LIMIT ?",
                (since, max(1, int(limit))),
            ).fetchall()
            comments = self._conn.execute(
                "SELECT id,target,user,text,parent_id,ts FROM post_comments "
                "WHERE ts>=? ORDER BY ts DESC LIMIT ?",
                (since, max(1, int(limit) * 3)),
            ).fetchall()
        user_ids = {int(r["id"]) for r in comments if str(r["user"]) == "user"}
        rows: list[dict[str, Any]] = []
        for r in likes:
            rows.append(
                {
                    "kind": "like",
                    "target": str(r["target"]),
                    "user": "user",
                    "text": "",
                    "parent_id": 0,
                    "ts": float(r["ts"] or 0),
                }
            )
        for r in comments:
            uid = str(r["user"] or "")
            parent = int(r["parent_id"] or 0)
            if uid == "user" or (parent and parent in user_ids):
                rows.append(
                    {
                        "kind": "comment",
                        "id": int(r["id"]),
                        "target": str(r["target"]),
                        "user": uid,
                        "text": str(r["text"] or ""),
                        "parent_id": parent,
                        "ts": float(r["ts"] or 0),
                    }
                )
        rows.sort(key=lambda item: float(item.get("ts") or 0))
        return rows[-max(1, int(limit)):]

    def unanswered_user_comments(self, since: float, limit: int = 5) -> list[dict[str, Any]]:
        """最近他评论过、但还没有任何人回复的评论。"""
        since = float(since or 0)
        with self._lock:
            rows = self._conn.execute(
                "SELECT c.id,c.target,c.text,c.ts FROM post_comments c "
                "WHERE c.user='user' AND c.ts>=? AND NOT EXISTS ("
                " SELECT 1 FROM post_comments r WHERE r.parent_id=c.id AND r.user!='user'"
                ") ORDER BY c.ts ASC LIMIT ?",
                (since, max(1, int(limit))),
            ).fetchall()
        return [dict(r) for r in rows]

    def dynamic_text(self, target: str) -> str:
        target = str(target or "")
        if not target.startswith("dyn:"):
            return ""
        try:
            dynamic_id = int(target.split(":")[-1])
        except (TypeError, ValueError):
            return ""
        with self._lock:
            row = self._conn.execute(
                "SELECT text FROM dynamics WHERE id=?", (dynamic_id,)
            ).fetchone()
        return str(row["text"] or "") if row else ""

    # ---------- 工具鱼（纯模型对话，不接 BrainN） ----------
    def add_tool_message(self, role: str, content: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO tool_messages(role,content,ts) VALUES(?,?,?)",
                (str(role), str(content)[:8000], time.time()),
            )
            self._conn.commit()

    def recent_tool_messages(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id,role,content,ts FROM tool_messages ORDER BY id DESC LIMIT ?",
                (max(1, min(100, int(limit))),),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def clear_tool_messages(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM tool_messages")
            self._conn.commit()

    # ---------- 社会关系图 ----------
    def social_nodes(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id,name,role,trust,intimacy,conflict,dependency,influence,depth,interactions,last_event,active,personality,manual,updated_at FROM social_nodes"
            ).fetchall()
        return [dict(r) for r in rows]

    def save_social_node(self, node: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO social_nodes(id,name,role,trust,intimacy,conflict,dependency,influence,depth,interactions,last_event,active,personality,manual,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, role=excluded.role,
                     trust=excluded.trust, intimacy=excluded.intimacy, conflict=excluded.conflict,
                     dependency=excluded.dependency, influence=excluded.influence,
                     depth=excluded.depth, interactions=excluded.interactions,
                     last_event=excluded.last_event, active=excluded.active,
                     personality=excluded.personality, manual=excluded.manual,
                     updated_at=excluded.updated_at""",
                (
                    node["id"],
                    node.get("name", ""),
                    node.get("role", ""),
                    node.get("trust", 50),
                    node.get("intimacy", 40),
                    node.get("conflict", 0),
                    node.get("dependency", 20),
                    node.get("influence", 50),
                    node.get("depth", 0),
                    node.get("interactions", 0),
                    node.get("last_event", "")[:200],
                    int(node.get("active", 1) or 1),
                    str(node.get("personality", "") or "")[:80],
                    int(node.get("manual", 0) or 0),
                    time.time(),
                ),
            )
            self._conn.commit()

    def social_edges(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT a,b,trust,intimacy,conflict,influence,depth,debt,credit,shared,interactions,last_event,updated_at FROM social_edges"
            ).fetchall()
        return [dict(r) for r in rows]

    def save_social_edge(self, edge: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO social_edges(a,b,trust,intimacy,conflict,influence,depth,debt,credit,shared,interactions,last_event,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(a,b) DO UPDATE SET trust=excluded.trust, intimacy=excluded.intimacy,
                     conflict=excluded.conflict, influence=excluded.influence,
                     depth=excluded.depth, debt=excluded.debt, credit=excluded.credit,
                     shared=excluded.shared, interactions=excluded.interactions,
                     last_event=excluded.last_event, updated_at=excluded.updated_at""",
                (
                    edge["a"],
                    edge["b"],
                    edge.get("trust", 50),
                    edge.get("intimacy", 30),
                    edge.get("conflict", 0),
                    edge.get("influence", 30),
                    edge.get("depth", 0),
                    edge.get("debt", 0),
                    edge.get("credit", 0),
                    edge.get("shared", 0),
                    edge.get("interactions", 0),
                    edge.get("last_event", "")[:200],
                    time.time(),
                ),
            )
            self._conn.commit()

    def add_social_event(self, key: str, text: str, node: str, mood_delta: float) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO social_events(ts,event_key,text,node,mood_delta) VALUES(?,?,?,?,?)",
                (time.time(), key, text[:500], node, mood_delta),
            )
            self._conn.commit()

    def recent_social_events(self, limit: int = 5) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts,event_key,text,node,mood_delta FROM social_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def social_events_since(self, start: float) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM social_events WHERE ts>=?", (start,)).fetchone()
        return int(row[0] or 0)

    def delete_social_edge(self, a: str, b: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM social_edges WHERE (a=? AND b=?) OR (a=? AND b=?)",
                (a, b, b, a),
            )
            self._conn.commit()
