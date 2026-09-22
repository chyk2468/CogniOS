"""Normalized execution events for CogniOS progress streaming.

Decouples internal engine event representations from external presentation adapters,
ensuring clean abstraction and strictly zero private reasoning/chain-of-thought leakage.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ...events import Event, EventType


@dataclass
class AgentProgressEvent:
    """Normalized progress update describing an agent action or state change."""

    session_id: str
    kind: str  # "started", "planning", "searching", "reading", "executing", "tool", "tool_finished", "approval_required", "question_requested", "synthesizing", "compacting", "completed", "stopped", "failed"
    summary: str
    detail: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


def _preview_cmd(cmd: str, max_len: int = 60) -> str:
    cleaned = " ".join(cmd.split())
    if len(cleaned) > max_len:
        return cleaned[: max_len - 3] + "..."
    return cleaned


def normalize_turn_event(
    event: Event, session_id: str
) -> AgentProgressEvent | None:
    """Translate a raw TurnEngine Event into a clean AgentProgressEvent.

    Returns None for internal/trace events (e.g. reasoning deltas, raw token deltas).
    """
    etype = event.type
    data = event.data or {}

    # Strict invariant: Never leak private reasoning deltas or internal model thoughts
    if etype == EventType.REASONING_DELTA:
        return None

    if etype == EventType.ASSISTANT_DELTA:
        return None

    if etype == EventType.TURN_START:
        user_input = data.get("input") or ""
        return AgentProgressEvent(
            session_id=session_id,
            kind="started",
            summary="🟢 CogniOS session started",
            detail=str(user_input)[:100] if user_input else None,
        )

    if etype in (EventType.TOOL_STARTED, EventType.TOOL_PROPOSED):
        name = data.get("name") or "tool"
        args = data.get("arguments") or {}

        if name in ("web_search", "search"):
            query = args.get("query") or args.get("q") or ""
            summary = f'🔎 Searching the web\n"{query}"' if query else "🔎 Searching the web"
            return AgentProgressEvent(
                session_id=session_id,
                kind="searching",
                summary=summary,
                detail=query or None,
                metadata={"tool": name, "query": query},
            )

        if name in ("browser_read_url", "web_fetch", "browser_open_url", "read_url"):
            url = args.get("url") or args.get("target") or ""
            summary = f"📖 Reading\n{url}" if url else "📖 Reading source"
            return AgentProgressEvent(
                session_id=session_id,
                kind="reading",
                summary=summary,
                detail=url or None,
                metadata={"tool": name, "url": url},
            )

        if name in ("run_command", "bash", "execute_code", "python", "shell"):
            cmd = args.get("command") or args.get("code") or ""
            preview = _preview_cmd(str(cmd)) if cmd else ""
            summary = f"🛠️ Executing code\n{preview}" if preview else "🛠️ Executing code"
            return AgentProgressEvent(
                session_id=session_id,
                kind="executing",
                summary=summary,
                detail=cmd or None,
                metadata={"tool": name},
            )

        if name in ("propose_plan", "plan"):
            return AgentProgressEvent(
                session_id=session_id,
                kind="planning",
                summary="🧠 Planning\nEvaluating approach",
                metadata={"tool": name},
            )

        if name.startswith("todo_"):
            return AgentProgressEvent(
                session_id=session_id,
                kind="planning",
                summary="📋 Updating tasks",
                metadata={"tool": name},
            )

        # Generic tool execution
        return AgentProgressEvent(
            session_id=session_id,
            kind="tool",
            summary=f"🛠️ Running {name}",
            metadata={"tool": name},
        )

    if etype == EventType.TOOL_FINISHED:
        name = data.get("name") or "tool"
        if name in ("web_search", "search"):
            summary = "✅ Search completed"
        elif name in ("browser_read_url", "web_fetch", "browser_open_url", "read_url"):
            summary = "✅ Source read"
        else:
            summary = f"✅ {name} completed"

        return AgentProgressEvent(
            session_id=session_id,
            kind="tool_finished",
            summary=summary,
            metadata={"tool": name, "status": data.get("status")},
        )

    if etype == EventType.PERMISSION_REQUIRED:
        tool_name = data.get("name") or "action"
        reason = data.get("reason") or "Tool requires permission"
        return AgentProgressEvent(
            session_id=session_id,
            kind="approval_required",
            summary="⚠️ Approval required",
            detail=f"{tool_name}: {reason}",
            metadata=data,
        )

    if etype == EventType.QUESTION_REQUESTED:
        question = data.get("question") or ""
        return AgentProgressEvent(
            session_id=session_id,
            kind="question_requested",
            summary="❓ Question from CogniOS",
            detail=question,
            metadata=data,
        )

    if etype == EventType.PLAN_PROPOSED:
        return AgentProgressEvent(
            session_id=session_id,
            kind="planning",
            summary="🧠 Plan proposed for review",
            metadata=data,
        )

    if etype == EventType.ASSISTANT_MESSAGE:
        # If the assistant message does not request more tool calls, it's finalizing the answer
        tool_calls = data.get("tool_calls") or []
        if not tool_calls:
            return AgentProgressEvent(
                session_id=session_id,
                kind="synthesizing",
                summary="🧩 Synthesizing results",
            )
        return None

    if etype == EventType.COMPACTING:
        return AgentProgressEvent(
            session_id=session_id,
            kind="compacting",
            summary="🧹 Compacting context",
        )

    if etype == EventType.TURN_END:
        return AgentProgressEvent(
            session_id=session_id,
            kind="completed",
            summary="✅ Task completed",
            metadata=data,
        )

    if etype == EventType.INTERRUPTED:
        return AgentProgressEvent(
            session_id=session_id,
            kind="stopped",
            summary="⏹️ Session stopped.",
            metadata=data,
        )

    if etype == EventType.ERROR:
        err = data.get("error") or "Unknown error"
        return AgentProgressEvent(
            session_id=session_id,
            kind="failed",
            summary=f"❌ Task failed: {err}",
            detail=str(err),
            metadata=data,
        )

    return None
