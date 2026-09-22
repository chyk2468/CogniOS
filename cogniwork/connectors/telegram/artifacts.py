"""Telegram Artifacts — canonical discovery, validation, and delivery helpers.

Integrates with SessionManager.resolve_artifact and the TurnEngine event stream
to securely detect and format deliverables produced during a turn.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ...events import Event
    from ...server.manager import SessionManager

logger = logging.getLogger("cogniwork.connectors.telegram")

_ARTIFACT_LINK_RE = re.compile(r"\[([^\]]*)\]\(artifact:([^\)]+)\)")


@dataclass(frozen=True)
class TelegramArtifact:
    """A verified, deliverable artifact scoped to a session turn."""

    artifact_id: str | None
    relative_path: str
    resolved_path: Path
    filename: str
    mime_type: str
    size: int
    content_hash: str | None = None


def compute_file_hash(path: Path) -> str | None:
    """Compute SHA-256 hash of a file for stable deduplication."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except Exception as exc:
        logger.debug("Failed to compute hash for %s: %s", path, exc)
        return None


def artifact_dedup_key(session_id: str, artifact: TelegramArtifact) -> str:
    """Generate a stable deduplication key for an artifact within a session."""
    if artifact.artifact_id:
        return f"{session_id}:id:{artifact.artifact_id}"
    norm_path = str(artifact.resolved_path.resolve())
    return f"{session_id}:path:{norm_path}:{artifact.content_hash or ''}"


def resolve_telegram_artifact(
    manager: SessionManager,
    session_id: str,
    candidate_path: str | Path,
    artifact_id: str | None = None,
) -> TelegramArtifact | None:
    """Resolve, validate, and construct a TelegramArtifact using SessionManager.resolve_artifact.

    Rejects paths that escape the session workspace, non-existent files, and unreadable files.
    """
    path_str = str(candidate_path).strip()
    if path_str.startswith("artifact:"):
        path_str = path_str[len("artifact:") :].strip()

    if not path_str:
        return None

    resolved_path, err = manager.resolve_artifact(
        session_id, path_str, allow_dir=False
    )
    if resolved_path is None or err:
        logger.warning(
            "[TelegramArtifacts] Artifact resolution rejected for session=%s path=%r: %s",
            session_id,
            path_str,
            err,
        )
        return None

    try:
        st = resolved_path.stat()
        if not resolved_path.is_file():
            return None
        size = st.st_size
    except OSError as exc:
        logger.warning(
            "[TelegramArtifacts] File stat failed for resolved path %s: %s",
            resolved_path,
            exc,
        )
        return None

    filename = resolved_path.name
    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        mime_type = "application/octet-stream"

    content_hash = compute_file_hash(resolved_path)

    return TelegramArtifact(
        artifact_id=artifact_id,
        relative_path=path_str,
        resolved_path=resolved_path,
        filename=filename,
        mime_type=mime_type,
        size=size,
        content_hash=content_hash,
    )


def extract_turn_artifacts(
    manager: SessionManager,
    session_id: str,
    turn_events: list[Event],
    final_answer: str | None = None,
    turn_start_time: float | None = None,
    pre_turn_artifacts: dict[str, float] | None = None,
    tool_candidates: list[str] | None = None,
) -> list[TelegramArtifact]:
    """Extract and resolve artifacts produced or modified in THIS turn following strict priority:

    1. Structured artifact metadata returned by tool execution / TOOL_FINISHED events (in emitted order).
    2. Canonical SessionManager.list_artifacts(session_id) filtered to files created/modified during this turn.
    3. Structured artifact:<path> references in final assistant response as a last-resort fallback.
    """
    discovered_artifacts: list[TelegramArtifact] = []
    seen_resolved_paths: set[str] = set()

    def _add_candidate(
        candidate_path: str | Path, artifact_id: str | None = None
    ) -> None:
        art = resolve_telegram_artifact(
            manager, session_id, candidate_path, artifact_id=artifact_id
        )
        if art is not None:
            norm_path = str(art.resolved_path.resolve())
            if norm_path not in seen_resolved_paths:
                seen_resolved_paths.add(norm_path)
                discovered_artifacts.append(art)

    # Priority 1: Explicit candidate paths tracked from tool executions (in execution order)
    for cand in tool_candidates or []:
        if cand:
            _add_candidate(cand)

    # Structured tool events inspection
    for ev in turn_events:
        if ev.type.value == "tool_finished":
            data = ev.data or {}
            for key in ("path", "file", "artifact_path", "output_path"):
                val = data.get(key)
                if isinstance(val, str) and val:
                    _add_candidate(val, artifact_id=data.get("artifact_id"))
            if "artifacts" in data and isinstance(data["artifacts"], list):
                for item in data["artifacts"]:
                    if isinstance(item, str):
                        _add_candidate(item)
                    elif isinstance(item, dict) and "path" in item:
                        _add_candidate(
                            item["path"],
                            artifact_id=item.get("artifact_id") or item.get("id"),
                        )
            if "files" in data and isinstance(data["files"], list):
                for item in data["files"]:
                    if isinstance(item, str):
                        _add_candidate(item)
                    elif isinstance(item, dict) and "path" in item:
                        _add_candidate(item["path"], artifact_id=item.get("id"))

    # Priority 2: Canonical SessionManager.list_artifacts(session_id) filtered to THIS turn
    try:
        current_artifacts = manager.list_artifacts(session_id)
    except Exception as exc:
        logger.debug("[TelegramArtifacts] list_artifacts failed: %s", exc)
        current_artifacts = []

    pre_snapshot = pre_turn_artifacts or {}
    for art_info in current_artifacts:
        art_path = art_info.get("path")
        mtime = art_info.get("modified_at") or 0.0
        # Check if newly created or modified in this turn
        is_new = art_path not in pre_snapshot
        is_modified = (
            art_path in pre_snapshot
            and (mtime > pre_snapshot[art_path] + 0.001)
        )
        is_in_turn_window = (
            turn_start_time is not None
            and mtime >= (turn_start_time - 2.0)
        )

        if (is_new or is_modified) and is_in_turn_window:
            _add_candidate(art_info.get("abs_path") or art_path)

    # Priority 3: Structured artifact:<path> references in final assistant text
    if final_answer:
        for match in _ARTIFACT_LINK_RE.finditer(final_answer):
            link_target = match.group(2).strip()
            if link_target:
                _add_candidate(link_target)

    return discovered_artifacts


@dataclass(frozen=True)
class SendArtifactRequest:
    """Explicit user request to send a specific or recent artifact to the current chat."""

    session_id: str
    chat_id: str
    thread_id: str | None = None
    artifact_reference: str | None = None


_GENERIC_SEND_PATTERNS = [
    r"^(?:please\s+)?(?:can\s+you\s+)?(?:could\s+you\s+)?(?:send|give|get|download|share|upload|fetch|deliver)(?:\s+me)?(?:\s+(?:the|that|this|my|the\s+generated|the\s+created|the\s+latest|the\s+recent))?\s+(?:file|artifact|code|attachment|deliverable|document|output|script)(?:\s+please)?[\.?!]?$",
    r"^(?:please\s+)?(?:can\s+you\s+)?(?:could\s+you\s+)?(?:send|give|share|upload|deliver)(?:\s+me)?\s+(?:it|that|this)(?:\s+to\s+me)?(?:\s+please)?[\.?!]?$",
    r"^(?:please\s+)?(?:can\s+you\s+)?(?:could\s+you\s+)?send\s+it\s+to\s+me[\.?!]?$",
    r"^(?:please\s+)?(?:can\s+you\s+)?download(?:\s+the)?\s+(?:file|artifact|code|attachment)[\.?!]?$",
    r"^(?:send|download)\s+file[\.?!]?$",
    r"^(?:send|download)\s+artifact[\.?!]?$",
]

_SPECIFIC_SEND_PATTERNS = [
    r"^(?:please\s+)?(?:can\s+you\s+)?(?:could\s+you\s+)?(?:send|give|get|download|share|upload|fetch|deliver)(?:\s+me)?(?:\s+(?:the|that|this|my|the\s+generated|the\s+created))?(?:\s+(?:file|artifact|code|attachment|deliverable|document))?\s+([A-Za-z0-9_\-\.\/\\]+)(?:\s+please)?[\.?!]?$",
]


def parse_artifact_send_intent(text: str) -> tuple[bool, str | None]:
    """Parse a message text to detect explicit artifact send/download intent.

    Returns:
        (True, explicit_target_or_None) if user is requesting to send an artifact.
        (False, None) otherwise.
    """
    clean = (text or "").strip()
    if not clean:
        return False, None

    # Check for generic send patterns first
    for pattern in _GENERIC_SEND_PATTERNS:
        if re.match(pattern, clean, re.IGNORECASE):
            return True, None

    # Check for specific send patterns
    for pattern in _SPECIFIC_SEND_PATTERNS:
        m = re.match(pattern, clean, re.IGNORECASE)
        if m:
            target = m.group(1).strip()
            # Exclude non-file words
            if target.lower() in (
                "a", "an", "the", "it", "this", "that", "me", "to",
                "email", "message", "sms", "dm", "link", "photo", "pic", "image",
                "prompt", "instruction", "task", "job", "help", "info", "details",
            ):
                return False, None
            # Return original case from input text matching target span
            span_start, span_end = m.span(1)
            raw_target = clean[span_start:span_end]
            return True, raw_target

    # Also check if user typed a bare filename with common extensions (e.g. "bubble_sort.c")
    if re.match(r"^[A-Za-z0-9_\-]+\.[A-Za-z0-9_]{1,10}$", clean):
        return True, clean

    return False, None


def resolve_requested_artifact(
    manager: SessionManager,
    session_id: str,
    target_ref: str | None,
) -> tuple[TelegramArtifact | None, str | None, list[str]]:
    """Resolve the requested artifact for an explicit file-send request in this session.

    Returns:
        (artifact, None, []) if resolved successfully.
        (None, error_message, []) if failed/not found or security error.
        (None, None, [filename1, filename2, ...]) if selection is ambiguous across multiple files.
    """
    # Case 1: Explicit filename or path given
    if target_ref:
        normalized_str = target_ref.replace("\\", "/")
        if "/../" in f"/{normalized_str}/" or normalized_str.startswith("../") or normalized_str == "..":
            logger.warning(
                "[TelegramArtifacts] Path traversal attempted in explicit request: %r",
                target_ref,
            )
            return None, "Path escapes session workspace.", []

        # Try direct resolution
        art = resolve_telegram_artifact(manager, session_id, target_ref)
        if art is not None:
            return art, None, []

        # Try matching filename against session's list_artifacts
        try:
            available = manager.list_artifacts(session_id)
        except Exception:
            available = []

        ref_basename = Path(target_ref).name.lower()
        for cand in available:
            cand_name = (cand.get("name") or "").lower()
            cand_path = (cand.get("path") or "").lower()
            if cand_name == ref_basename or cand_path == ref_basename or cand_path.endswith("/" + ref_basename):
                cand_art = resolve_telegram_artifact(
                    manager, session_id, cand.get("abs_path") or cand.get("path")
                )
                if cand_art is not None:
                    return cand_art, None, []

        return None, "I couldn't find that file in this session.", []

    # Case 2: Generic request ("send me the file")
    try:
        available = manager.list_artifacts(session_id)
    except Exception as exc:
        logger.warning("[TelegramArtifacts] Failed to list session artifacts: %s", exc)
        available = []

    if not available:
        return None, "I couldn't find that file in this session.", []

    if len(available) == 1:
        art = resolve_telegram_artifact(
            manager, session_id, available[0].get("abs_path") or available[0].get("path")
        )
        if art is not None:
            return art, None, []
        return None, "I couldn't find that file in this session.", []

    # Multiple artifacts exist: check timestamps
    m0 = available[0].get("modified_at", 0.0)
    m1 = available[1].get("modified_at", 0.0)
    if (m0 - m1) > 2.0:
        # Most recent artifact is clearly distinguished
        art = resolve_telegram_artifact(
            manager, session_id, available[0].get("abs_path") or available[0].get("path")
        )
        if art is not None:
            return art, None, []

    # Ambiguous selection across multiple files
    names = [a.get("name") or a.get("path") for a in available[:5] if a.get("name") or a.get("path")]
    return None, None, names

