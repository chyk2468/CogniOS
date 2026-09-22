"""Telegram Agent Bridge package for CogniOS."""

from __future__ import annotations

from .artifacts import (
    SendArtifactRequest,
    TelegramArtifact,
    artifact_dedup_key,
    extract_turn_artifacts,
    parse_artifact_send_intent,
    resolve_requested_artifact,
    resolve_telegram_artifact,
)
from .bridge import TelegramAgentBridge
from .client import TelegramClient, split_telegram_message
from .diagnostic import check_telegram_health
from .events import AgentProgressEvent, normalize_turn_event
from .progress_adapter import TelegramProgressAdapter
from .session_store import ModelSelection, TelegramSessionRecord, TelegramSessionStore

__all__ = [
    "AgentProgressEvent",
    "ModelSelection",
    "SendArtifactRequest",
    "TelegramAgentBridge",
    "TelegramArtifact",
    "TelegramClient",
    "TelegramProgressAdapter",
    "TelegramSessionRecord",
    "TelegramSessionStore",
    "artifact_dedup_key",
    "check_telegram_health",
    "extract_turn_artifacts",
    "normalize_turn_event",
    "parse_artifact_send_intent",
    "resolve_requested_artifact",
    "resolve_telegram_artifact",
    "split_telegram_message",
]

