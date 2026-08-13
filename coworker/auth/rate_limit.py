"""Simple sliding-window rate limiter for auth endpoints."""

from __future__ import annotations

import sqlite3
import threading
import time


class RateLimiter:
    def __init__(self, conn: sqlite3.Connection, *, max_attempts: int = 5, window_seconds: float = 900.0) -> None:
        self._conn = conn
        self._lock = threading.RLock()
        self._max = max_attempts
        self._window = window_seconds
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS auth_rate_limits (
                key TEXT PRIMARY KEY,
                attempts INTEGER NOT NULL DEFAULT 0,
                window_start REAL NOT NULL
            )
            """)
        self._conn.commit()

    def check(self, key: str) -> bool:
        """Return True if the attempt is allowed."""
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT attempts, window_start FROM auth_rate_limits WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO auth_rate_limits (key, attempts, window_start) VALUES (?, 1, ?)",
                    (key, now),
                )
                self._conn.commit()
                return True
            attempts, window_start = row["attempts"], row["window_start"]
            if now - window_start >= self._window:
                self._conn.execute(
                    "UPDATE auth_rate_limits SET attempts = 1, window_start = ? WHERE key = ?",
                    (now, key),
                )
                self._conn.commit()
                return True
            if attempts >= self._max:
                return False
            self._conn.execute(
                "UPDATE auth_rate_limits SET attempts = attempts + 1 WHERE key = ?",
                (key,),
            )
            self._conn.commit()
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM auth_rate_limits WHERE key = ?", (key,))
            self._conn.commit()
