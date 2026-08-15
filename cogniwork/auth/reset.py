"""Factory-reset the single owner account and all account-owned application data."""

from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from ..personas.registry import DEFAULT_PERSONA_ID
from ..secrets import state_dir

if TYPE_CHECKING:
    from ..server.manager import SessionManager
    from .store import AuthStore

logger = logging.getLogger("cogniwork.auth.reset")

_OWNER_JSON_FILES = (
    "prefs.json",
    "memory-settings.json",
    "inbox.json",
    "inbox_routing.json",
    "unattended.json",
    "wakes.json",
    "subscriptions.json",
    "channels.json",
    "mention_threads.json",
    "parked.json",
    "people.json",
    "persona_connections.json",
    "session_connections.json",
    "session_skills.json",
    "unrouted.json",
    "personas.json",
    "secrets.json",
    "workspace_trust.json",
    "risk_overrides.json",
    "mcp.json",
    "skills-settings.json",
)

_OWNER_DIRS = ("conversations", "skills-staged", "skills")

_GLOBAL_STATE_FILES = ("config.toml", "auth-encryption.key")


def _clear_sqlite_owner_data(conn: sqlite3.Connection) -> None:
    tables = (
        "audit_events",
        "memories",
        "sessions",
        "workspaces",
        "auth_rate_limits",
        "auth_totp_setup",
        "auth_pending_logins",
        "auth_recovery_tokens",
        "auth_sessions",
        "users",
    )
    existing = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.execute("BEGIN IMMEDIATE")
    try:
        for table in tables:
            if table in existing:
                conn.execute(f"DELETE FROM {table}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _remove_file(path: Path) -> None:
    if path.is_file():
        path.unlink()


def _clear_dir(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _purge_data_dir(base: Path) -> None:
    for name in _OWNER_JSON_FILES:
        _remove_file(base / name)
    for name in _OWNER_DIRS:
        _clear_dir(base / name)


def _reload_manager_state(manager: SessionManager) -> None:
    manager._prefs = {}
    manager.inbox._items.clear()
    manager.inbox_routing._load()
    manager.unattended._flags.clear()
    manager.wakes._wakes.clear()
    manager.subscriptions._load()
    manager.channel_buffer._by_channel.clear()
    manager.channel_buffer._names.clear()
    manager.mention_sessions._load()
    manager.parked._load()
    manager._people = {}
    manager.persona_connections._load()
    manager.session_connections._load()
    manager.session_skills._load()
    manager.unrouted._load()
    manager.personas._enabled = {}
    manager.personas._surfaced = {}
    manager.personas._default = DEFAULT_PERSONA_ID
    manager.personas.save()
    manager.model = "gpt-5.6-sol"


def reset_owner_data(*, auth_store: AuthStore, manager: SessionManager) -> None:
    """Delete the owner account and all account-owned persisted data."""
    base = Path(manager._data_base)
    global_base = state_dir()

    manager._engines.clear()
    manager._running_sessions.clear()
    manager._autotitle_inflight.clear()

    with auth_store._lock:
        _clear_sqlite_owner_data(auth_store._conn)

    manager_db = base / "cogniwork.db"
    if manager_db.exists() and manager_db.resolve() != Path(auth_store.path).resolve():
        with sqlite3.connect(manager_db) as conn:
            _clear_sqlite_owner_data(conn)

    _purge_data_dir(base)
    for name in _GLOBAL_STATE_FILES:
        _remove_file(global_base / name)

    if base.resolve() != global_base.resolve():
        _purge_data_dir(global_base)
        alt_db = global_base / "cogniwork.db"
        if alt_db.exists() and alt_db.resolve() != Path(auth_store.path).resolve():
            with sqlite3.connect(alt_db) as conn:
                _clear_sqlite_owner_data(conn)

    _reload_manager_state(manager)
