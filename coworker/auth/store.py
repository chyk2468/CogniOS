"""SQLite-backed user and session store."""

from __future__ import annotations

import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .passwords import hash_pet_answer, hash_secret, verify_pet_answer, verify_secret


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class User:
    id: int
    full_name: str
    username: str
    email: str
    created_at: str
    updated_at: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "full_name": self.full_name,
            "username": self.username,
            "email": self.email,
        }


@dataclass(frozen=True)
class Session:
    id: str
    user_id: int
    expires_at: str


class AuthStore:
    SESSION_TTL = timedelta(days=7)
    RECOVERY_TTL = timedelta(minutes=15)

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    favorite_pet_answer_hash TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS auth_sessions (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS auth_recovery_tokens (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER,
                    stage TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                """)
            self._conn.commit()

    def create_user(
        self,
        *,
        full_name: str,
        username: str,
        email: str,
        password: str,
        favorite_pet: str,
    ) -> User:
        pw_hash = hash_secret(password)
        pet_hash = hash_pet_answer(favorite_pet)
        now = _iso(_utcnow())
        with self._lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO users (full_name, username, email, password_hash, "
                    "favorite_pet_answer_hash, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (full_name.strip(), username.strip(), email.strip().lower(), pw_hash, pet_hash, now, now),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                msg = str(exc).lower()
                if "username" in msg:
                    raise ValueError("username_taken") from exc
                if "email" in msg:
                    raise ValueError("email_taken") from exc
                raise ValueError("duplicate") from exc
            user = self.get_user_by_id(cur.lastrowid)
        assert user is not None
        return user

    def get_user_by_id(self, user_id: int) -> User | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_user(row) if row else None

    def find_user_by_email_or_username(self, identifier: str) -> User | None:
        ident = identifier.strip()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE email = ? COLLATE NOCASE OR username = ? COLLATE NOCASE",
                (ident.lower(), ident),
            ).fetchone()
        return _row_to_user(row) if row else None

    def verify_credentials(self, identifier: str, password: str) -> User | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE email = ? COLLATE NOCASE OR username = ? COLLATE NOCASE",
                (identifier.strip().lower(), identifier.strip()),
            ).fetchone()
        if not row or not verify_secret(row["password_hash"], password):
            return None
        return _row_to_user(row)

    def create_session(self, user_id: int) -> Session:
        session_id = secrets.token_urlsafe(32)
        expires = _utcnow() + self.SESSION_TTL
        with self._lock:
            self._conn.execute(
                "INSERT INTO auth_sessions (id, user_id, expires_at) VALUES (?, ?, ?)",
                (session_id, user_id, _iso(expires)),
            )
            self._conn.commit()
        return Session(id=session_id, user_id=user_id, expires_at=_iso(expires))

    def get_session(self, session_id: str) -> Session | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM auth_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if not row:
            return None
        expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
        if expires <= _utcnow():
            self.delete_session(session_id)
            return None
        return Session(id=row["id"], user_id=row["user_id"], expires_at=row["expires_at"])

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM auth_sessions WHERE id = ?", (session_id,))
            self._conn.commit()

    def delete_user_sessions(self, user_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
            self._conn.commit()

    def get_user_for_session(self, session_id: str) -> User | None:
        session = self.get_session(session_id)
        if not session:
            return None
        return self.get_user_by_id(session.user_id)

    def create_recovery_token(self, user_id: int | None, *, stage: str = "pet") -> str:
        token = secrets.token_urlsafe(32)
        expires = _utcnow() + self.RECOVERY_TTL
        with self._lock:
            self._conn.execute(
                "INSERT INTO auth_recovery_tokens (token, user_id, stage, expires_at) VALUES (?, ?, ?, ?)",
                (token, user_id, stage, _iso(expires)),
            )
            self._conn.commit()
        return token

    def get_recovery_token(self, token: str) -> tuple[int | None, str] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, stage, expires_at FROM auth_recovery_tokens WHERE token = ?",
                (token,),
            ).fetchone()
        if not row:
            return None
        expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
        if expires <= _utcnow():
            self.delete_recovery_token(token)
            return None
        return row["user_id"], row["stage"]

    def delete_recovery_token(self, token: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM auth_recovery_tokens WHERE token = ?", (token,))
            self._conn.commit()

    def verify_pet_for_recovery(self, token: str, pet_answer: str) -> str | None:
        """Verify pet answer; return a reset-stage token on success."""
        info = self.get_recovery_token(token)
        if not info or info[1] != "pet":
            return None
        user_id, _ = info
        if user_id is None:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT favorite_pet_answer_hash FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        if not row or not verify_pet_answer(row["favorite_pet_answer_hash"], pet_answer):
            return None
        self.delete_recovery_token(token)
        return self.create_recovery_token(user_id, stage="reset")

    def reset_password(self, reset_token: str, new_password: str) -> bool:
        info = self.get_recovery_token(reset_token)
        if not info or info[1] != "reset" or info[0] is None:
            return False
        user_id = info[0]
        pw_hash = hash_secret(new_password)
        now = _iso(_utcnow())
        with self._lock:
            self._conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (pw_hash, now, user_id),
            )
            self._conn.commit()
        self.delete_recovery_token(reset_token)
        self.delete_user_sessions(user_id)
        return True


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        full_name=row["full_name"],
        username=row["username"],
        email=row["email"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
