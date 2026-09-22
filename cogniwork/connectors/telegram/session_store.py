"""SQLite-backed session store for Telegram-CogniOS session mappings.

Provides transactional, ACID-compliant persistence for active Telegram chat sessions,
ensuring crash resilience and preventing state corruption across restarts or concurrent turns.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ModelSelection:
    provider: str
    model: str
    full_id: str


@dataclass
class TelegramSessionRecord:
    chat_id: str
    session_id: str
    user_id: str | None = None
    user_name: str | None = None
    status: str = "IDLE"  # IDLE, RUNNING, WAITING_APPROVAL, COMPLETED, STOPPING, STOPPED, ERROR
    prompt: str | None = None
    progress_message_id: str | None = None
    started_at: float = 0.0
    last_activity_at: float = 0.0
    stop_requested: bool = False
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_active(self) -> bool:
        return self.status in ("RUNNING", "WAITING_APPROVAL", "STOPPING")


def _compute_full_id(provider: str, model: str) -> str:
    provider = (provider or "").strip().lower()
    model = (model or "").strip()
    if not provider or provider == "openai":
        return model
    if model.startswith(f"{provider}:"):
        return model
    return f"{provider}:{model}"


class TelegramSessionStore:
    """Thread-safe SQLite store for mapping Telegram chats to CogniOS sessions."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.db_path), check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS telegram_sessions (
                    chat_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_id TEXT,
                    user_name TEXT,
                    status TEXT NOT NULL,
                    prompt TEXT,
                    progress_message_id TEXT,
                    started_at REAL,
                    last_activity_at REAL,
                    stop_requested INTEGER DEFAULT 0,
                    error TEXT,
                    metadata TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_tg_sess_id ON telegram_sessions(session_id);
                CREATE INDEX IF NOT EXISTS idx_tg_sess_status ON telegram_sessions(status);

                CREATE TABLE IF NOT EXISTS telegram_preferences (
                    chat_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    selected_provider TEXT,
                    selected_model TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
            self._conn.commit()

    def _row_to_record(self, row: sqlite3.Row | None) -> TelegramSessionRecord | None:
        if row is None:
            return None
        meta = {}
        if row["metadata"]:
            try:
                meta = json.loads(row["metadata"])
            except Exception:
                meta = {}
        return TelegramSessionRecord(
            chat_id=str(row["chat_id"]),
            session_id=str(row["session_id"]),
            user_id=row["user_id"],
            user_name=row["user_name"],
            status=str(row["status"]),
            prompt=row["prompt"],
            progress_message_id=row["progress_message_id"],
            started_at=float(row["started_at"] or 0.0),
            last_activity_at=float(row["last_activity_at"] or 0.0),
            stop_requested=bool(row["stop_requested"]),
            error=row["error"],
            metadata=meta,
        )

    def get(self, chat_id: str | int) -> TelegramSessionRecord | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM telegram_sessions WHERE chat_id = ?",
                (str(chat_id),),
            )
            return self._row_to_record(cur.fetchone())

    def get_by_session_id(self, session_id: str) -> TelegramSessionRecord | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM telegram_sessions WHERE session_id = ?",
                (session_id,),
            )
            return self._row_to_record(cur.fetchone())

    def get_active_session(self, chat_id: str | int) -> TelegramSessionRecord | None:
        rec = self.get(chat_id)
        if rec and rec.is_active():
            return rec
        return None

    def set_active_session(
        self,
        chat_id: str | int,
        session_id: str,
        *,
        user_id: str | None = None,
        user_name: str | None = None,
        prompt: str | None = None,
        status: str = "RUNNING",
        progress_message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TelegramSessionRecord:
        now = time.time()
        meta_json = json.dumps(metadata or {})
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO telegram_sessions (
                    chat_id, session_id, user_id, user_name, status, prompt,
                    progress_message_id, started_at, last_activity_at, stop_requested,
                    error, metadata, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(chat_id) DO UPDATE SET
                    session_id = excluded.session_id,
                    user_id = excluded.user_id,
                    user_name = excluded.user_name,
                    status = excluded.status,
                    prompt = excluded.prompt,
                    progress_message_id = excluded.progress_message_id,
                    started_at = excluded.started_at,
                    last_activity_at = excluded.last_activity_at,
                    stop_requested = 0,
                    error = NULL,
                    metadata = excluded.metadata,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    str(chat_id),
                    session_id,
                    user_id,
                    user_name,
                    status,
                    prompt,
                    progress_message_id,
                    now,
                    now,
                    meta_json,
                ),
            )
            self._conn.commit()
            return TelegramSessionRecord(
                chat_id=str(chat_id),
                session_id=session_id,
                user_id=user_id,
                user_name=user_name,
                status=status,
                prompt=prompt,
                progress_message_id=progress_message_id,
                started_at=now,
                last_activity_at=now,
                stop_requested=False,
                error=None,
                metadata=metadata or {},
            )

    def update_status(
        self,
        chat_id: str | int,
        status: str,
        *,
        error: str | None = None,
        progress_message_id: str | None = None,
        stop_requested: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TelegramSessionRecord | None:
        now = time.time()
        with self._lock:
            rec = self.get(chat_id)
            if not rec:
                return None

            new_stop = (
                int(stop_requested)
                if stop_requested is not None
                else int(rec.stop_requested)
            )
            new_prog = (
                progress_message_id
                if progress_message_id is not None
                else rec.progress_message_id
            )
            new_err = error if error is not None else rec.error
            new_meta = (
                json.dumps(metadata)
                if metadata is not None
                else json.dumps(rec.metadata)
            )

            self._conn.execute(
                """
                UPDATE telegram_sessions SET
                    status = ?,
                    error = ?,
                    progress_message_id = ?,
                    stop_requested = ?,
                    metadata = ?,
                    last_activity_at = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE chat_id = ?
                """,
                (
                    status,
                    new_err,
                    new_prog,
                    new_stop,
                    new_meta,
                    now,
                    str(chat_id),
                ),
            )
            self._conn.commit()
            return self.get(chat_id)

    def clear_session(self, chat_id: str | int) -> bool:
        """Clear active session mapping for chat, so the next prompt creates a new session."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM telegram_sessions WHERE chat_id = ?",
                (str(chat_id),),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def recover_stale_sessions(
        self, active_session_ids: set[str] | None = None
    ) -> list[TelegramSessionRecord]:
        """Mark any in-flight turns orphaned by server restart as IDLE so the session continues."""
        active_ids = active_session_ids or set()
        recovered: list[TelegramSessionRecord] = []
        now = time.time()

        with self._lock:
            cur = self._conn.execute(
                """
                SELECT * FROM telegram_sessions
                WHERE status IN ('RUNNING', 'WAITING_APPROVAL', 'STOPPING')
                """
            )
            stale_rows = cur.fetchall()
            for row in stale_rows:
                sess_id = row["session_id"]
                if sess_id not in active_ids:
                    chat_id = row["chat_id"]
                    self._conn.execute(
                        """
                        UPDATE telegram_sessions SET
                            status = 'IDLE',
                            error = NULL,
                            last_activity_at = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE chat_id = ?
                        """,
                        (now, chat_id),
                    )
                    rec = self.get(chat_id)
                    if rec:
                        recovered.append(rec)
            self._conn.commit()
        return recovered

    def list_all(self) -> list[TelegramSessionRecord]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM telegram_sessions ORDER BY updated_at DESC"
            )
            return [self._row_to_record(r) for r in cur.fetchall() if r]

    def get_model_preference(self, chat_id: str | int) -> ModelSelection | None:
        """Retrieve stored model preference for a given chat."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT selected_provider, selected_model FROM telegram_preferences WHERE chat_id = ?",
                (str(chat_id),),
            )
            row = cur.fetchone()
            if row and row["selected_model"]:
                provider = str(row["selected_provider"] or "")
                model = str(row["selected_model"])
                full_id = _compute_full_id(provider, model)
                return ModelSelection(provider=provider, model=model, full_id=full_id)
            return None

    def set_model_preference(
        self,
        chat_id: str | int,
        user_id: str | None,
        provider: str,
        model: str,
    ) -> ModelSelection:
        """Set or update model preference for a given chat."""
        with self._lock:
            full_id = _compute_full_id(provider, model)
            self._conn.execute(
                """
                INSERT INTO telegram_preferences (chat_id, user_id, selected_provider, selected_model, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(chat_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    selected_provider = excluded.selected_provider,
                    selected_model = excluded.selected_model,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (str(chat_id), str(user_id) if user_id else None, provider, model),
            )
            self._conn.commit()
            return ModelSelection(provider=provider, model=model, full_id=full_id)

    def clear_model_preference(self, chat_id: str | int) -> None:
        """Clear model preference for a given chat, reverting to default."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM telegram_preferences WHERE chat_id = ?",
                (str(chat_id),),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
