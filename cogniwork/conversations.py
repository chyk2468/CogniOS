"""ConversationStore — global, file-backed session storage shared by all surfaces.

Layout under a base dir (default `~/.config/cogniwork/`):
  cogniwork.db                  SQLite index: sessions(id → project, title, n_msgs), workspaces, memory
  conversations/<id>.jsonl     append-only message log, one file per conversation

Writes append only the new messages each turn (no rewriting history). Legacy rows that
stored messages inline are lazily migrated to a .jsonl on first load/save.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .sessions import SessionRecord


def _load_roots(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _load_grants(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _display_title(row: sqlite3.Row) -> str | None:
    """Title precedence for every read path: a manual rename (renamed=1) always wins,
    then the generated auto_title, then the first-line snapshot `save()` wrote."""
    if row["renamed"]:
        return row["title"]
    return row["auto_title"] or row["title"]


def _extract_last_message(messages: list[dict]) -> str | None:
    """Extract snippet of the most recent message in the conversation."""
    from .attachments import content_to_text

    for m in reversed(messages):
        role = m.get("role")
        if role in ("user", "assistant"):
            text = content_to_text(m.get("content"), image_placeholder="").strip()
            if text:
                line = " ".join(text.split())
                return line[:100]
    return None


def title_from(messages: list[dict]) -> str:
    from .attachments import content_to_text

    for m in messages:
        if m.get("role") == "user":
            text = content_to_text(m.get("content"), image_placeholder="").strip()
            if text:
                return text.splitlines()[0][:60]
    return "New session"


class ConversationStore:
    def __init__(self, base_dir: str | Path) -> None:
        self.base = Path(base_dir).expanduser()
        self.base.mkdir(parents=True, exist_ok=True)
        self.conv_dir = self.base / "conversations"
        self.conv_dir.mkdir(exist_ok=True)
        self.db_path = self.base / "cogniwork.db"

        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY, workspace TEXT, model TEXT, mode TEXT,
                title TEXT, agent TEXT DEFAULT 'code', n_msgs INTEGER DEFAULT 0, messages TEXT,
                extra_roots TEXT, pinned INTEGER DEFAULT 0, archived INTEGER DEFAULT 0,
                origin TEXT, origin_label TEXT,
                auto_title TEXT, renamed INTEGER DEFAULT 0,
                source TEXT DEFAULT 'web',
                status TEXT DEFAULT 'active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_activity_at REAL,
                telegram_chat_id TEXT,
                telegram_username TEXT,
                telegram_display_name TEXT,
                last_message TEXT,
                unread_count INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS telegram_active_sessions (
                chat_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_id TEXT,
                user_name TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS workspaces (
                path TEXT PRIMARY KEY, last_used TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """)
        for ddl in (
            "ALTER TABLE sessions ADD COLUMN title TEXT",
            "ALTER TABLE sessions ADD COLUMN n_msgs INTEGER DEFAULT 0",
            "ALTER TABLE sessions ADD COLUMN agent TEXT DEFAULT 'code'",
            "ALTER TABLE sessions ADD COLUMN extra_roots TEXT",
            "ALTER TABLE sessions ADD COLUMN pinned INTEGER DEFAULT 0",
            "ALTER TABLE sessions ADD COLUMN archived INTEGER DEFAULT 0",
            "ALTER TABLE sessions ADD COLUMN origin TEXT",
            "ALTER TABLE sessions ADD COLUMN origin_label TEXT",
            "ALTER TABLE sessions ADD COLUMN auto_title TEXT",
            "ALTER TABLE sessions ADD COLUMN renamed INTEGER DEFAULT 0",
            "ALTER TABLE sessions ADD COLUMN grants TEXT",
            "ALTER TABLE sessions ADD COLUMN compaction TEXT",
            "ALTER TABLE sessions ADD COLUMN source TEXT DEFAULT 'web'",
            "ALTER TABLE sessions ADD COLUMN status TEXT DEFAULT 'active'",
            "ALTER TABLE sessions ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE sessions ADD COLUMN last_activity_at REAL",
            "ALTER TABLE sessions ADD COLUMN telegram_chat_id TEXT",
            "ALTER TABLE sessions ADD COLUMN telegram_username TEXT",
            "ALTER TABLE sessions ADD COLUMN telegram_display_name TEXT",
            "ALTER TABLE sessions ADD COLUMN last_message TEXT",
            "ALTER TABLE sessions ADD COLUMN unread_count INTEGER DEFAULT 0",
            "CREATE INDEX IF NOT EXISTS idx_sessions_tg_chat ON sessions(telegram_chat_id)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source)",
        ):
            try:
                self._conn.execute(ddl)
            except sqlite3.OperationalError:
                pass
        self._conn.commit()
        self._backfill_counts()

    # -- file helpers -----------------------------------------------------------
    def _file(self, sid: str) -> Path:
        return self.conv_dir / f"{sid}.jsonl"

    def _read_jsonl(self, sid: str) -> list[dict] | None:
        path = self._file(sid)
        if not path.exists():
            return None
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _count(self, sid: str) -> int:
        path = self._file(sid)
        if not path.exists():
            return 0
        return sum(
            1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
        )

    def _append(self, sid: str, messages: list[dict]) -> None:
        with open(self._file(sid), "a", encoding="utf-8") as f:
            f.writelines(json.dumps(m) + "\n" for m in messages)

    def _backfill_counts(self) -> None:
        """One-time per session: move any inline blob into a .jsonl and persist
        title + n_msgs in the index. Skips already-migrated rows on later startups."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id, messages, n_msgs, title FROM sessions"
            ).fetchall()
            for row in rows:
                sid = row["session_id"]
                jsonl = self._file(sid)
                if jsonl.exists() and row["title"] and row["n_msgs"]:
                    continue  # already migrated
                if jsonl.exists():
                    messages = self._read_jsonl(sid) or []
                elif row["messages"]:
                    try:
                        messages = json.loads(row["messages"])
                    except json.JSONDecodeError:
                        messages = []
                    if messages:
                        self._append(sid, messages)
                    self._conn.execute(
                        "UPDATE sessions SET messages = NULL WHERE session_id = ?",
                        (sid,),
                    )
                else:
                    messages = []
                self._conn.execute(
                    "UPDATE sessions SET n_msgs = ?, title = ? WHERE session_id = ?",
                    (len(messages), row["title"] or title_from(messages), sid),
                )
            self._conn.commit()

    # -- API --------------------------------------------------------------------
    def save(self, record: SessionRecord) -> None:
        sid = record.session_id
        with self._lock:
            # lazily migrate a legacy inline blob into the .jsonl
            if not self._file(sid).exists():
                row = self._conn.execute(
                    "SELECT messages FROM sessions WHERE session_id = ?", (sid,)
                ).fetchone()
                if row and row["messages"]:
                    try:
                        legacy = json.loads(row["messages"])
                    except json.JSONDecodeError:
                        legacy = []
                    if legacy:
                        self._append(sid, legacy)

            existing = self._count(sid)
            if len(record.messages) > existing:
                self._append(sid, record.messages[existing:])
            elif len(record.messages) < existing:  # rare; not append-only
                with open(self._file(sid), "w", encoding="utf-8") as f:
                    f.writelines(json.dumps(m) + "\n" for m in record.messages)

            title = record.title or title_from(record.messages)
            last_msg = record.last_message or _extract_last_message(record.messages)
            self._conn.execute(
                """
                INSERT INTO sessions (
                    session_id, workspace, model, mode, title, agent, n_msgs, messages,
                    extra_roots, grants, compaction, source, status, last_activity_at,
                    telegram_chat_id, telegram_username, telegram_display_name,
                    last_message, unread_count, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET
                    workspace = excluded.workspace, model = excluded.model, mode = excluded.mode,
                    title = COALESCE(sessions.title, excluded.title), agent = excluded.agent,
                    n_msgs = excluded.n_msgs, messages = NULL, extra_roots = excluded.extra_roots,
                    grants = excluded.grants, compaction = excluded.compaction,
                    source = COALESCE(excluded.source, sessions.source, 'web'),
                    status = COALESCE(excluded.status, sessions.status, 'active'),
                    last_activity_at = COALESCE(excluded.last_activity_at, sessions.last_activity_at),
                    telegram_chat_id = COALESCE(excluded.telegram_chat_id, sessions.telegram_chat_id),
                    telegram_username = COALESCE(excluded.telegram_username, sessions.telegram_username),
                    telegram_display_name = COALESCE(excluded.telegram_display_name, sessions.telegram_display_name),
                    last_message = COALESCE(excluded.last_message, sessions.last_message),
                    unread_count = COALESCE(excluded.unread_count, sessions.unread_count, 0),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    sid,
                    record.workspace,
                    record.model,
                    record.mode,
                    title,
                    record.agent,
                    len(record.messages),
                    json.dumps(record.extra_roots or []),
                    json.dumps(record.grants or {}),
                    json.dumps(record.compaction or {}),
                    record.source or "web",
                    record.status or "active",
                    record.last_activity_at,
                    record.telegram_chat_id,
                    record.telegram_username,
                    record.telegram_display_name,
                    last_msg,
                    record.unread_count,
                ),
            )
            self._conn.commit()
        self.touch_workspace(record.workspace)

    def load(self, session_id: str) -> SessionRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if not row:
            return None
        messages = self._read_jsonl(session_id)
        if messages is None:
            try:
                messages = json.loads(row["messages"] or "[]")
            except json.JSONDecodeError:
                messages = []
        source = (
            row["source"]
            if "source" in row.keys() and row["source"]
            else ("telegram" if row["origin"] == "telegram" else "web")
        )
        status = row["status"] if "status" in row.keys() and row["status"] else "active"
        created_at = row["created_at"] if "created_at" in row.keys() else None
        last_activity_at = row["last_activity_at"] if "last_activity_at" in row.keys() else None
        tg_chat_id = row["telegram_chat_id"] if "telegram_chat_id" in row.keys() else None
        tg_username = row["telegram_username"] if "telegram_username" in row.keys() else None
        tg_display_name = row["telegram_display_name"] if "telegram_display_name" in row.keys() else None
        last_msg = row["last_message"] if "last_message" in row.keys() else None
        unread_count = int(row["unread_count"] or 0) if "unread_count" in row.keys() else 0

        return SessionRecord(
            session_id=session_id,
            workspace=row["workspace"],
            model=row["model"],
            mode=row["mode"],
            messages=messages,
            title=_display_title(row),
            agent=row["agent"] or "code",
            message_count=len(messages),
            updated_at=row["updated_at"],
            created_at=created_at,
            last_activity_at=last_activity_at,
            status=status,
            extra_roots=_load_roots(
                row["extra_roots"] if "extra_roots" in row.keys() else None
            ),
            grants=_load_grants(row["grants"] if "grants" in row.keys() else None),
            # Auto-compaction state (OPE-27) — same defensive parse as grants.
            compaction=_load_grants(
                row["compaction"] if "compaction" in row.keys() else None
            ),
            pinned=bool(row["pinned"]),
            archived=bool(row["archived"]),
            origin=row["origin"],
            origin_label=row["origin_label"],
            source=source,
            telegram_chat_id=tg_chat_id,
            telegram_username=tg_username,
            telegram_display_name=tg_display_name,
            last_message=last_msg,
            unread_count=unread_count,
        )

    def set_extra_roots(self, session_id: str, extra_roots: list[dict]) -> None:
        """Persist just the session's added folders, independent of its message log — used when
        the user adds/removes a folder (which may happen with no active engine)."""
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET extra_roots = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (json.dumps(extra_roots or []), session_id),
            )
            self._conn.commit()

    def list(
        self, *, workspace: str | None = None, source: str | None = None
    ) -> list[SessionRecord]:
        with self._lock:
            clauses = []
            params: list[Any] = []
            if workspace is not None:
                clauses.append("workspace = ?")
                params.append(workspace)
            if source is not None:
                if source == "web":
                    clauses.append("(source IS NULL OR source = 'web' OR (source != 'telegram' AND (origin IS NULL OR origin != 'telegram')))")
                elif source == "telegram":
                    clauses.append("(source = 'telegram' OR origin = 'telegram')")
                else:
                    clauses.append("source = ?")
                    params.append(source)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = self._conn.execute(
                f"SELECT * FROM sessions {where} ORDER BY pinned DESC, COALESCE(last_activity_at, 0) DESC, updated_at DESC",
                params,
            ).fetchall()

        records = []
        for r in rows:
            src = (
                r["source"]
                if "source" in r.keys() and r["source"]
                else ("telegram" if r["origin"] == "telegram" else "web")
            )
            status = r["status"] if "status" in r.keys() and r["status"] else "active"
            created_at = r["created_at"] if "created_at" in r.keys() else None
            last_activity_at = r["last_activity_at"] if "last_activity_at" in r.keys() else None
            tg_chat_id = r["telegram_chat_id"] if "telegram_chat_id" in r.keys() else None
            tg_username = r["telegram_username"] if "telegram_username" in r.keys() else None
            tg_display_name = r["telegram_display_name"] if "telegram_display_name" in r.keys() else None
            last_msg = r["last_message"] if "last_message" in r.keys() else None
            unread_cnt = int(r["unread_count"] or 0) if "unread_count" in r.keys() else 0
            records.append(
                SessionRecord(
                    session_id=r["session_id"],
                    workspace=r["workspace"],
                    model=r["model"],
                    mode=r["mode"],
                    messages=[],
                    title=_display_title(r),
                    agent=r["agent"] or "code",
                    message_count=r["n_msgs"] or 0,
                    updated_at=r["updated_at"],
                    created_at=created_at,
                    last_activity_at=last_activity_at,
                    status=status,
                    pinned=bool(r["pinned"]),
                    archived=bool(r["archived"]),
                    origin=r["origin"],
                    origin_label=r["origin_label"],
                    source=src,
                    telegram_chat_id=tg_chat_id,
                    telegram_username=tg_username,
                    telegram_display_name=tg_display_name,
                    last_message=last_msg,
                    unread_count=unread_cnt,
                )
            )
        return records

    def touch_workspace(self, path: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO workspaces (path, last_used) VALUES (?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(path) DO UPDATE SET last_used = CURRENT_TIMESTAMP",
                (path,),
            )

            self._conn.commit()

    def recent_workspaces(self, limit: int = 20) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT path FROM workspaces ORDER BY last_used DESC LIMIT ?", (limit,)
            ).fetchall()
        return [r["path"] for r in rows]

    def canonicalize_workspaces(self) -> None:
        with self._lock:
            for (ws,) in self._conn.execute(
                "SELECT DISTINCT workspace FROM sessions WHERE workspace IS NOT NULL"
            ).fetchall():
                real = os.path.realpath(ws)
                if real != ws:
                    self._conn.execute(
                        "UPDATE sessions SET workspace = ? WHERE workspace = ?",
                        (real, ws),
                    )
            latest: dict[str, str] = {}
            for path, last in self._conn.execute(
                "SELECT path, last_used FROM workspaces"
            ).fetchall():
                real = os.path.realpath(path)
                if real not in latest or (last or "") > latest[real]:
                    latest[real] = last
            self._conn.execute("DELETE FROM workspaces")
            for path, last in latest.items():
                self._conn.execute(
                    "INSERT OR REPLACE INTO workspaces (path, last_used) VALUES (?, ?)",
                    (path, last),
                )
            self._conn.commit()

    def delete(self, session_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,)
            )
            self._conn.commit()
        path = self._file(session_id)
        if path.exists():
            path.unlink()
        return cur.rowcount > 0

    def rename(self, session_id: str, title: str) -> bool:
        clean = " ".join((title or "").split())[:120]
        if not clean:
            return False
        with self._lock:
            # renamed=1 makes the manual title final: auto-titling skips the session and
            # `_display_title` ignores any auto_title already there.
            cur = self._conn.execute(
                "UPDATE sessions SET title = ?, renamed = 1, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (clean, session_id),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def set_auto_title(self, session_id: str, title: str) -> bool:
        """Store a generated title. Its own column — never `title` — so a manual rename
        (past or future) always wins; doesn't touch updated_at (a title landing after the
        turn must not reorder the session list)."""
        clean = " ".join((title or "").split())[:60]
        if not clean:
            return False
        with self._lock:
            cur = self._conn.execute(
                "UPDATE sessions SET auto_title = ? WHERE session_id = ? AND renamed = 0",
                (clean, session_id),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def title_state(self, session_id: str) -> dict | None:
        """The auto-title guard inputs: whether the user renamed and whether a generated
        title already exists. None when the session has no row yet."""
        with self._lock:
            row = self._conn.execute(
                "SELECT renamed, auto_title FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return {"renamed": bool(row["renamed"]), "auto_title": row["auto_title"]}

    def set_flags(
        self,
        session_id: str,
        *,
        pinned: bool | None = None,
        archived: bool | None = None,
    ) -> bool:
        """Update pin/archive flags without touching updated_at (so pinning doesn't reorder)."""
        sets, params = [], []
        if pinned is not None:
            sets.append("pinned = ?")
            params.append(1 if pinned else 0)
        if archived is not None:
            sets.append("archived = ?")
            params.append(1 if archived else 0)
        if not sets:
            return False
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE sessions SET {', '.join(sets)} WHERE session_id = ?",
                (*params, session_id),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def set_origin(self, session_id: str, origin: str, origin_label: str = "") -> bool:
        """Mark where a spawned session came from (§31). Set once at spawn; `save()` never
        names these columns, so per-turn saves can't clobber them (the pinned mechanism).
        """
        with self._lock:
            cur = self._conn.execute(
                "UPDATE sessions SET origin = ?, origin_label = ? WHERE session_id = ?",
                (origin, origin_label or None, session_id),
            )
            self._conn.commit()
        return cur.rowcount > 0
    def mark_read(self, session_id: str) -> bool:
        """Mark all unread items in a session as read."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE sessions SET unread_count = 0 WHERE session_id = ?",
                (session_id,),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def update_telegram_metadata(
        self,
        session_id: str,
        *,
        chat_id: str | None = None,
        username: str | None = None,
        last_message: str | None = None,
        increment_unread: bool = False,
    ) -> bool:
        """Update Telegram specific fields on a session."""
        with self._lock:
            # Check if row exists; if not, create initial row
            row = self._conn.execute(
                "SELECT session_id, unread_count FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                unread = 1 if increment_unread else 0
                self._conn.execute(
                    """
                    INSERT INTO sessions (
                        session_id, workspace, model, mode, title, agent,
                        source, telegram_chat_id, telegram_username, last_message, unread_count, updated_at
                    ) VALUES (?, '', 'default', 'interactive', ?, 'code', 'telegram', ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        session_id,
                        username or f"Telegram · {chat_id or session_id}",
                        str(chat_id) if chat_id else None,
                        str(username) if username else None,
                        str(last_message)[:120] if last_message else None,
                        unread,
                    ),
                )
                self._conn.commit()
                return True

            sets = []
            params = []
            if chat_id is not None:
                sets.append("telegram_chat_id = ?")
                params.append(str(chat_id))
            if username is not None:
                sets.append("telegram_username = ?")
                params.append(str(username))
            if last_message is not None:
                sets.append("last_message = ?")
                params.append(str(last_message)[:120])
            if increment_unread:
                sets.append("unread_count = COALESCE(unread_count, 0) + 1")
            sets.append("source = 'telegram'")
            sets.append("last_activity_at = ?")
            params.append(time.time())
            sets.append("updated_at = CURRENT_TIMESTAMP")
            cur = self._conn.execute(
                f"UPDATE sessions SET {', '.join(sets)} WHERE session_id = ?",
                (*params, session_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def update_session_model(self, session_id: str, model: str) -> bool:
        """Update only the active model of an existing session in the SQLite database."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE sessions SET model = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (str(model), str(session_id)),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def get_active_telegram_session(self, chat_id: str | int) -> SessionRecord | None:
        """Resolve the single active CogniOS session for a Telegram chat ID."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT s.session_id FROM telegram_active_sessions a
                JOIN sessions s ON s.session_id = a.session_id
                WHERE a.chat_id = ? AND s.status = 'active'
                """,
                (str(chat_id),),
            ).fetchone()
            if row:
                rec = self.load(row["session_id"])
                if rec and rec.status == "active":
                    return rec

            # Fallback / sync from sessions table if mapping row was missing
            cur = self._conn.execute(
                """
                SELECT session_id FROM sessions
                WHERE telegram_chat_id = ? AND source = 'telegram' AND status = 'active'
                ORDER BY COALESCE(last_activity_at, 0) DESC, updated_at DESC LIMIT 1
                """,
                (str(chat_id),),
            )
            sess_row = cur.fetchone()
            if sess_row:
                sid = sess_row["session_id"]
                self.set_active_telegram_session(chat_id, sid)
                return self.load(sid)
            return None

    def set_active_telegram_session(
        self,
        chat_id: str | int,
        session_id: str,
        *,
        user_id: str | None = None,
        user_name: str | None = None,
    ) -> None:
        """Set or update the active session ID for a Telegram chat ID."""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO telegram_active_sessions (chat_id, session_id, user_id, user_name, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(chat_id) DO UPDATE SET
                    session_id = excluded.session_id,
                    user_id = COALESCE(excluded.user_id, telegram_active_sessions.user_id),
                    user_name = COALESCE(excluded.user_name, telegram_active_sessions.user_name),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (str(chat_id), session_id, user_id, user_name),
            )
            self._conn.commit()

    def create_telegram_session(
        self,
        chat_id: str | int,
        user_name: str | None = None,
        display_name: str | None = None,
        model: str = "default",
        agent: str = "cogniwork",
        workspace: str = "",
    ) -> SessionRecord:
        """Create a new Telegram session and register it as active for the given chat ID."""
        sid = f"tg-{uuid.uuid4().hex[:12]}"
        title_tag = user_name or str(chat_id)
        stable_title = f"Telegram — {title_tag}"
        now = time.time()

        rec = SessionRecord(
            session_id=sid,
            workspace=workspace,
            model=model,
            mode="interactive",
            messages=[],
            title=stable_title,
            agent=agent,
            origin="telegram",
            origin_label=stable_title,
            source="telegram",
            status="active",
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            last_activity_at=now,
            telegram_chat_id=str(chat_id),
            telegram_username=user_name,
            telegram_display_name=display_name or user_name,
            last_message=None,
            unread_count=0,
        )
        self.save(rec)
        self.set_active_telegram_session(chat_id, sid, user_name=user_name)
        return rec

    def close_active_telegram_session(
        self, chat_id: str | int, status: str = "completed"
    ) -> str | None:
        """Close/stop the active Telegram session for this chat ID and remove it from active mapping."""
        with self._lock:
            row = self._conn.execute(
                "SELECT session_id FROM telegram_active_sessions WHERE chat_id = ?",
                (str(chat_id),),
            ).fetchone()
            if row:
                sid = row["session_id"]
                self._conn.execute(
                    "UPDATE sessions SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                    (status, sid),
                )
                self._conn.execute(
                    "DELETE FROM telegram_active_sessions WHERE chat_id = ?",
                    (str(chat_id),),
                )
                self._conn.commit()
                return sid

            # If not in telegram_active_sessions, also check and close any active session with this chat_id
            row_sess = self._conn.execute(
                "SELECT session_id FROM sessions WHERE telegram_chat_id = ? AND status = 'active'",
                (str(chat_id),),
            ).fetchone()
            if row_sess:
                sid = row_sess["session_id"]
                self._conn.execute(
                    "UPDATE sessions SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                    (status, sid),
                )
                self._conn.commit()
                return sid
            return None

    def touch_telegram_activity(
        self,
        session_id: str,
        *,
        last_message: str | None = None,
        increment_unread: bool = False,
    ) -> bool:
        """Update last_activity_at, updated_at, and optional last_message/unread_count."""
        with self._lock:
            sets = ["last_activity_at = ?", "updated_at = CURRENT_TIMESTAMP"]
            params: list[Any] = [time.time()]
            if last_message is not None:
                sets.append("last_message = ?")
                params.append(str(last_message)[:120])
            if increment_unread:
                sets.append("unread_count = COALESCE(unread_count, 0) + 1")
            cur = self._conn.execute(
                f"UPDATE sessions SET {', '.join(sets)} WHERE session_id = ?",
                (*params, session_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()
