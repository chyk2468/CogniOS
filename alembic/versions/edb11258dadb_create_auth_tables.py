"""Alembic migration for user authentication tables.

The runtime uses inline sqlite3 bootstrapping in coworker/auth/store.py (matching the
rest of the codebase). This migration documents the schema for Alembic-based deployments.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "edb11258dadb"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            favorite_pet_answer_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth_sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth_recovery_tokens (
            token TEXT PRIMARY KEY,
            user_id INTEGER,
            stage TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth_rate_limits (
            key TEXT PRIMARY KEY,
            attempts INTEGER NOT NULL DEFAULT 0,
            window_start REAL NOT NULL
        )
        """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth_rate_limits")
    op.execute("DROP TABLE IF EXISTS auth_recovery_tokens")
    op.execute("DROP TABLE IF EXISTS auth_sessions")
    op.execute("DROP TABLE IF EXISTS users")
