"""SQLite-backed single-owner account, sessions, and 2FA store."""

from __future__ import annotations

import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .crypto import decrypt_value, encrypt_value
from .passwords import hash_pet_answer, hash_secret, verify_pet_answer, verify_secret
from .totp import generate_secret, verify_code


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
    totp_enabled: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "full_name": self.full_name,
            "username": self.username,
            "email": self.email,
        }

    def account_dict(self) -> dict[str, Any]:
        return {
            **self.public_dict(),
            "created_at": self.created_at,
            "totp_enabled": self.totp_enabled,
        }


@dataclass(frozen=True)
class Session:
    id: str
    user_id: int
    expires_at: str
    created_at: str
    last_activity: str


class AuthStore:
    SESSION_TTL = timedelta(days=7)
    RECOVERY_TTL = timedelta(minutes=15)
    CHALLENGE_TTL = timedelta(minutes=5)
    SETUP_TTL = timedelta(minutes=10)

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
                    totp_enabled INTEGER NOT NULL DEFAULT 0,
                    totp_secret_encrypted TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS auth_sessions (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    expires_at TEXT NOT NULL,
                    last_activity TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS auth_recovery_tokens (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER,
                    stage TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auth_pending_logins (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expires_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auth_totp_setup (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    secret_encrypted TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                """)
            cols = {
                row["name"]
                for row in self._conn.execute("PRAGMA table_info(users)").fetchall()
            }
            if "totp_enabled" not in cols:
                self._conn.execute(
                    "ALTER TABLE users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0"
                )
            if "totp_secret_encrypted" not in cols:
                self._conn.execute(
                    "ALTER TABLE users ADD COLUMN totp_secret_encrypted TEXT"
                )
            sess_cols = {
                row["name"]
                for row in self._conn.execute("PRAGMA table_info(auth_sessions)").fetchall()
            }
            if "last_activity" not in sess_cols:
                self._conn.execute(
                    "ALTER TABLE auth_sessions ADD COLUMN last_activity TEXT"
                )
            self._conn.commit()

    def owner_exists(self) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        return row is not None

    def get_owner(self) -> User | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM users ORDER BY id LIMIT 1").fetchone()
        return _row_to_user(row) if row else None

    def create_user(
        self,
        *,
        full_name: str,
        username: str,
        email: str,
        password: str,
        favorite_pet: str,
    ) -> User:
        if self.owner_exists():
            raise ValueError("owner_exists")
        pw_hash = hash_secret(password)
        pet_hash = hash_pet_answer(favorite_pet)
        now = _iso(_utcnow())
        with self._lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO users (full_name, username, email, password_hash, "
                    "favorite_pet_answer_hash, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        full_name.strip(),
                        username.strip(),
                        email.strip().lower(),
                        pw_hash,
                        pet_hash,
                        now,
                        now,
                    ),
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
        user = self.find_user_by_email_or_username(identifier)
        if not user:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT password_hash FROM users WHERE id = ?", (user.id,)
            ).fetchone()
        if not row or not verify_secret(row["password_hash"], password):
            return None
        return user

    def verify_password_for_user(self, user_id: int, password: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT password_hash FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return bool(row and verify_secret(row["password_hash"], password))

    def create_session(self, user_id: int) -> Session:
        session_id = secrets.token_urlsafe(32)
        now = _utcnow()
        expires = now + self.SESSION_TTL
        now_s = _iso(now)
        with self._lock:
            self._conn.execute(
                "INSERT INTO auth_sessions (id, user_id, expires_at, last_activity) VALUES (?, ?, ?, ?)",
                (session_id, user_id, _iso(expires), now_s),
            )
            self._conn.commit()
        return Session(
            id=session_id,
            user_id=user_id,
            expires_at=_iso(expires),
            created_at=now_s,
            last_activity=now_s,
        )

    def touch_session(self, session_id: str) -> None:
        now_s = _iso(_utcnow())
        with self._lock:
            self._conn.execute(
                "UPDATE auth_sessions SET last_activity = ? WHERE id = ?",
                (now_s, session_id),
            )
            self._conn.commit()

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
        return Session(
            id=row["id"],
            user_id=row["user_id"],
            expires_at=row["expires_at"],
            created_at=row["created_at"],
            last_activity=row["last_activity"] or row["created_at"],
        )

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
        self.touch_session(session_id)
        return self.get_user_by_id(session.user_id)

    def get_session_info(self, session_id: str) -> dict[str, Any] | None:
        session = self.get_session(session_id)
        if not session:
            return None
        return {
            "created_at": session.created_at,
            "last_activity": session.last_activity,
        }

    def create_pending_login(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        expires = _utcnow() + self.CHALLENGE_TTL
        with self._lock:
            self._conn.execute(
                "INSERT INTO auth_pending_logins (token, user_id, expires_at) VALUES (?, ?, ?)",
                (token, user_id, _iso(expires)),
            )
            self._conn.commit()
        return token

    def get_pending_login(self, token: str) -> int | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, expires_at FROM auth_pending_logins WHERE token = ?",
                (token,),
            ).fetchone()
        if not row:
            return None
        expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
        if expires <= _utcnow():
            self.delete_pending_login(token)
            return None
        return row["user_id"]

    def delete_pending_login(self, token: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM auth_pending_logins WHERE token = ?", (token,))
            self._conn.commit()

    def consume_pending_login(self, token: str) -> int | None:
        user_id = self.get_pending_login(token)
        if user_id is not None:
            self.delete_pending_login(token)
        return user_id

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

    def advance_recovery_stage(self, token: str, *, stage: str) -> bool:
        info = self.get_recovery_token(token)
        if not info:
            return False
        expires = _utcnow() + self.RECOVERY_TTL
        with self._lock:
            self._conn.execute(
                "UPDATE auth_recovery_tokens SET stage = ?, expires_at = ? WHERE token = ?",
                (stage, _iso(expires), token),
            )
            self._conn.commit()
        return True

    def verify_pet_for_recovery(self, token: str, pet_answer: str) -> tuple[str | None, bool]:
        """Return (next_token, requires_totp). next_token is reset_token or totp-stage token."""
        info = self.get_recovery_token(token)
        if not info or info[1] != "pet":
            return None, False
        user_id, _ = info
        if user_id is None:
            return None, False
        with self._lock:
            row = self._conn.execute(
                "SELECT favorite_pet_answer_hash, totp_enabled FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if not row or not verify_pet_answer(row["favorite_pet_answer_hash"], pet_answer):
            return None, False
        if row["totp_enabled"]:
            if not self.advance_recovery_stage(token, stage="totp"):
                return None, False
            return token, True
        self.delete_recovery_token(token)
        reset = self.create_recovery_token(user_id, stage="reset")
        return reset, False

    def verify_totp_for_recovery(self, token: str, code: str) -> str | None:
        info = self.get_recovery_token(token)
        if not info or info[1] != "totp" or info[0] is None:
            return None
        user_id = info[0]
        if not self._verify_user_totp(user_id, code):
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

    def change_password(self, user_id: int, new_password: str) -> None:
        pw_hash = hash_secret(new_password)
        now = _iso(_utcnow())
        with self._lock:
            self._conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (pw_hash, now, user_id),
            )
            self._conn.commit()
        self.delete_user_sessions(user_id)

    def change_username(self, user_id: int, username: str) -> None:
        now = _iso(_utcnow())
        with self._lock:
            self._conn.execute(
                "UPDATE users SET username = ?, updated_at = ? WHERE id = ?",
                (username.strip(), now, user_id),
            )
            self._conn.commit()

    def change_email(self, user_id: int, email: str) -> None:
        now = _iso(_utcnow())
        with self._lock:
            self._conn.execute(
                "UPDATE users SET email = ?, updated_at = ? WHERE id = ?",
                (email.strip().lower(), now, user_id),
            )
            self._conn.commit()

    def _get_totp_secret(self, user_id: int) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT totp_secret_encrypted FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        if not row or not row["totp_secret_encrypted"]:
            return None
        return decrypt_value(row["totp_secret_encrypted"])

    def _verify_user_totp(self, user_id: int, code: str) -> bool:
        secret = self._get_totp_secret(user_id)
        if not secret:
            return False
        return verify_code(secret=secret, code=code)

    def verify_user_totp(self, user_id: int, code: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT totp_enabled FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        if not row or not row["totp_enabled"]:
            return False
        return self._verify_user_totp(user_id, code)

    def begin_totp_setup(self, user_id: int) -> tuple[str, str]:
        """Return (setup_token, plaintext_secret). Secret shown only during setup."""
        secret = generate_secret()
        token = secrets.token_urlsafe(32)
        expires = _utcnow() + self.SETUP_TTL
        enc = encrypt_value(secret)
        with self._lock:
            self._conn.execute("DELETE FROM auth_totp_setup WHERE user_id = ?", (user_id,))
            self._conn.execute(
                "INSERT INTO auth_totp_setup (token, user_id, secret_encrypted, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (token, user_id, enc, _iso(expires)),
            )
            self._conn.commit()
        return token, secret

    def confirm_totp_setup(self, user_id: int, setup_token: str, code: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT secret_encrypted, expires_at FROM auth_totp_setup "
                "WHERE token = ? AND user_id = ?",
                (setup_token, user_id),
            ).fetchone()
        if not row:
            return False
        expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
        if expires <= _utcnow():
            self._cancel_totp_setup(setup_token)
            return False
        secret = decrypt_value(row["secret_encrypted"])
        if not secret or not verify_code(secret=secret, code=code):
            return False
        now = _iso(_utcnow())
        with self._lock:
            self._conn.execute(
                "UPDATE users SET totp_enabled = 1, totp_secret_encrypted = ?, updated_at = ? "
                "WHERE id = ?",
                (row["secret_encrypted"], now, user_id),
            )
            self._conn.execute("DELETE FROM auth_totp_setup WHERE token = ?", (setup_token,))
            self._conn.commit()
        return True

    def _cancel_totp_setup(self, setup_token: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM auth_totp_setup WHERE token = ?", (setup_token,))
            self._conn.commit()

    def disable_totp(self, user_id: int) -> None:
        now = _iso(_utcnow())
        with self._lock:
            self._conn.execute(
                "UPDATE users SET totp_enabled = 0, totp_secret_encrypted = NULL, updated_at = ? "
                "WHERE id = ?",
                (now, user_id),
            )
            self._conn.execute("DELETE FROM auth_totp_setup WHERE user_id = ?", (user_id,))
            self._conn.commit()


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        full_name=row["full_name"],
        username=row["username"],
        email=row["email"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        totp_enabled=bool(row["totp_enabled"]) if "totp_enabled" in row.keys() else False,
    )
