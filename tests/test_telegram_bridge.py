"""Tests for CogniOS Telegram Agent Bridge.

Verifies end-to-end inbound message routing, session creation, live progress streaming,
zero reasoning leakage, /stop cooperative cancellation, /start instructions, approval routing,
authorization allowlists, concurrent task guards, stale session recovery, and message splitting.
"""

import asyncio
import os
import time
from typing import Any

import pytest

from cogniwork.connectors.base import MessageEvent, SendResult, SessionSource
from cogniwork.connectors.setup import connector_list
from cogniwork.connectors.telegram import (
    AgentProgressEvent,
    TelegramAgentBridge,
    TelegramClient,
    TelegramProgressAdapter,
    TelegramSessionStore,
    normalize_turn_event,
    split_telegram_message,
)
from cogniwork.connectors.tool_defs import tool_dicts
from cogniwork.engine import ApprovalOutcome, Event, EventType
from cogniwork.providers import AssistantTurn, ModelCapabilities, ProviderClient, ToolCall
from cogniwork.server.manager import SessionManager


# -- Fake Telegram Client for Testing ------------------------------------------

class FakeTelegramClient(TelegramClient):
    """In-memory fake of TelegramClient recording all sent/edited/deleted messages, documents, and callbacks."""

    def __init__(self, token: str = "fake-token", edit_fails: bool = False, document_fails: bool = False) -> None:
        super().__init__(token)
        self.sent_messages: list[dict[str, Any]] = []
        self.sent_documents: list[dict[str, Any]] = []
        self.edited_messages: list[dict[str, Any]] = []
        self.deleted_messages: list[dict[str, Any]] = []
        self.answered_callbacks: list[dict[str, Any]] = []
        self.edit_fails = edit_fails
        self.document_fails = document_fails
        self._msg_counter = 100

    def send_message(
        self,
        chat_id: str | int,
        text: str,
        *,
        thread_id: str | int | None = None,
        reply_to_message_id: str | int | None = None,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> SendResult:
        self._msg_counter += 1
        msg_id = str(self._msg_counter)
        self.sent_messages.append({
            "message_id": msg_id,
            "chat_id": str(chat_id),
            "text": text,
            "thread_id": str(thread_id) if thread_id else None,
            "reply_markup": reply_markup,
        })
        return SendResult(True, message_id=msg_id)

    def send_document(
        self,
        chat_id: str | int,
        document: Any,
        filename: str,
        *,
        caption: str | None = None,
        thread_id: str | int | None = None,
        mime_type: str | None = None,
    ) -> SendResult:
        if self.document_fails:
            return SendResult(False, error="Simulated Telegram document upload failure")

        self._msg_counter += 1
        msg_id = str(self._msg_counter)

        if hasattr(document, "read_bytes"):
            raw_data = document.read_bytes()
        elif hasattr(document, "read"):
            raw_data = document.read()
        elif isinstance(document, (bytes, bytearray)):
            raw_data = bytes(document)
        elif isinstance(document, str) and os.path.isfile(document):
            with open(document, "rb") as f:
                raw_data = f.read()
        elif isinstance(document, str):
            raw_data = document.encode("utf-8")
        else:
            raw_data = b""

        self.sent_documents.append({
            "message_id": msg_id,
            "chat_id": str(chat_id),
            "document": raw_data,
            "filename": filename,
            "caption": caption,
            "thread_id": str(thread_id) if thread_id else None,
            "mime_type": mime_type,
        })
        return SendResult(True, message_id=msg_id)


    def edit_message_text(
        self,
        chat_id: str | int,
        message_id: str | int,
        text: str,
        *,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> SendResult:
        if self.edit_fails:
            return SendResult(False, error="Bad Request: message to edit not found")

        self.edited_messages.append({
            "message_id": str(message_id),
            "chat_id": str(chat_id),
            "text": text,
            "reply_markup": reply_markup,
        })
        return SendResult(True, message_id=str(message_id))

    def delete_message(self, chat_id: str | int, message_id: str | int) -> bool:
        self.deleted_messages.append({"chat_id": str(chat_id), "message_id": str(message_id)})
        return True

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: str | None = None,
        *,
        show_alert: bool = False,
        url: str | None = None,
        cache_time: int | None = None,
    ) -> bool:
        self.answered_callbacks.append({
            "callback_query_id": str(callback_query_id),
            "text": text,
            "show_alert": show_alert,
        })
        return True


# -- Scripted & Async Provider Helpers ----------------------------------------

class ScriptedTurnProvider(ProviderClient):
    """Returns pre-scripted AssistantTurns per call."""

    def __init__(self, turns: list[AssistantTurn]) -> None:
        self.turns = list(turns)
        self.calls: list[list[dict]] = []

    def complete(self, *, model, messages, tools=None, **settings):
        self.calls.append([dict(m) for m in messages])
        if self.turns:
            return self.turns.pop(0)
        return AssistantTurn(text="Done.", finish_reason="stop")

    def capabilities(self, model):
        return ModelCapabilities()


class SlowInterruptibleProvider(ProviderClient):
    """Simulates a slow LLM call."""

    def __init__(self, sleep_seconds: float = 1.0) -> None:
        self.sleep_seconds = sleep_seconds

    def complete(self, *, model, messages, tools=None, **settings):
        time.sleep(self.sleep_seconds)
        return AssistantTurn(text="Completed slow task.", finish_reason="stop")

    def capabilities(self, model):
        return ModelCapabilities()


def _tg_event(text: str, *, chat_id: str = "12345", user_id: str = "u1", user_name: str = "Alice", chat_type: str = "dm") -> MessageEvent:
    return MessageEvent(
        text=text,
        source=SessionSource(
            platform="telegram",
            chat_id=chat_id,
            user_id=user_id,
            user_name=user_name,
            chat_type=chat_type,
        ),
        message_id="999",
    )


# ==============================================================================
# Unit Tests
# ==============================================================================

def test_split_telegram_message():
    # 1. Short message stays intact
    short = "Hello world"
    assert split_telegram_message(short, max_length=100) == [short]

    # 2. Plain long message split along paragraphs
    long_msg = "Paragraph 1\n\nParagraph 2\n\nParagraph 3"
    chunks = split_telegram_message(long_msg, max_length=20)
    assert len(chunks) >= 2
    assert "Paragraph 1" in chunks[0]
    assert "Paragraph 3" in chunks[-1]

    # 3. Code block continuity across split boundaries
    code_text = "Here is some code:\n```python\ndef foo():\n    return 42\n```\nAnd more text."
    chunks = split_telegram_message(code_text, max_length=40)
    assert len(chunks) >= 2
    # First chunk should close the fence
    assert chunks[0].endswith("```")
    # Second chunk should reopen the python fence
    assert chunks[1].startswith("```python\n")


def test_telegram_session_store_crud(tmp_path):
    store = TelegramSessionStore(tmp_path / "test.db")

    # 1. Initially no active session
    assert store.get_active_session("chat1") is None

    # 2. Set active session
    rec = store.set_active_session("chat1", "sess1", user_id="u1", user_name="Alice", prompt="hi")
    assert rec.chat_id == "chat1"
    assert rec.session_id == "sess1"
    assert rec.status == "RUNNING"
    assert store.get_active_session("chat1") is not None

    # 3. Update status
    updated = store.update_status("chat1", "WAITING_APPROVAL", progress_message_id="msg1")
    assert updated.status == "WAITING_APPROVAL"
    assert updated.progress_message_id == "msg1"
    assert store.get_active_session("chat1") is not None

    # 4. Mark completed/idle
    completed = store.update_status("chat1", "IDLE")
    assert completed.status == "IDLE"
    assert store.get_active_session("chat1") is None  # IDLE = no in-flight turn running

    # 5. Stale recovery
    store.set_active_session("chat2", "sess2", prompt="task2", status="RUNNING")
    store.set_active_session("chat3", "sess3", prompt="task3", status="WAITING_APPROVAL")
    recovered = store.recover_stale_sessions(active_session_ids={"sess2"})
    assert len(recovered) == 1
    assert recovered[0].chat_id == "chat3"
    assert recovered[0].status == "IDLE"

    store.close()


def test_normalize_turn_event_no_reasoning_leakage():
    # 1. Reasoning delta must return None (strictly no leakage)
    assert normalize_turn_event(Event(EventType.REASONING_DELTA, {"text": "internal thought"}), "s1") is None
    assert normalize_turn_event(Event(EventType.ASSISTANT_DELTA, {"text": "chunk"}), "s1") is None

    # 2. Turn start
    ev_start = normalize_turn_event(Event(EventType.TURN_START, {"input": "test prompt"}), "s1")
    assert ev_start is not None and ev_start.kind == "started"

    # 3. Web search tool
    ev_search = normalize_turn_event(
        Event(EventType.TOOL_STARTED, {"name": "web_search", "arguments": {"query": "AI news"}}), "s1"
    )
    assert ev_search is not None and ev_search.kind == "searching"
    assert "AI news" in ev_search.summary

    # 4. Reading tool
    ev_read = normalize_turn_event(
        Event(EventType.TOOL_STARTED, {"name": "browser_read_url", "arguments": {"url": "https://example.com"}}), "s1"
    )
    assert ev_read is not None and ev_read.kind == "reading"
    assert "https://example.com" in ev_read.summary

    # 5. Completion
    ev_end = normalize_turn_event(Event(EventType.TURN_END, {"status": "completed"}), "s1")
    assert ev_end is not None and ev_end.kind == "completed"


@pytest.mark.asyncio
async def test_progress_adapter_live_editing_and_fallback():
    # 1. Live edit mode
    fake_client = FakeTelegramClient()
    adapter = TelegramProgressAdapter(fake_client, "12345", update_interval=0.01, mode="edit")

    msg_id = await adapter.start("🟢 CogniOS session started")
    assert msg_id == "101"
    assert len(fake_client.sent_messages) == 1

    # Send progress events
    await asyncio.sleep(0.02)
    await adapter.on_progress_event(AgentProgressEvent("s1", "searching", "🔎 Searching the web"))
    await asyncio.sleep(0.05)
    await adapter.on_progress_event(AgentProgressEvent("s1", "reading", "📖 Reading source"))
    await asyncio.sleep(0.05)

    # Conclude with final answer
    await adapter.finish(status="completed", final_answer="Here is the final news summary.")

    assert len(fake_client.edited_messages) >= 1
    assert any("final news summary" in m["text"] for m in fake_client.sent_messages)

    # 2. Fallback when edit fails
    failing_client = FakeTelegramClient(edit_fails=True)
    fallback_adapter = TelegramProgressAdapter(failing_client, "12345", update_interval=0.01, mode="edit")
    await fallback_adapter.start()
    await asyncio.sleep(0.02)
    await fallback_adapter.on_progress_event(AgentProgressEvent("s1", "searching", "🔎 Searching"))
    await asyncio.sleep(0.05)
    # Failed edit should have triggered a fallback send_message
    assert len(failing_client.sent_messages) >= 2


# ==============================================================================
# End-to-End Acceptance Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_telegram_e2e_turn_execution(tmp_path, monkeypatch):
    """Send `what is the ai top news today` and verify end-to-end progress and completion."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")

    fake_client = FakeTelegramClient()
    turns = [
        AssistantTurn(text="🗞️ Top AI News — August 26, 2026\n1. Autonomous agents deployed in CogniOS.", finish_reason="stop"),
    ]
    provider = ScriptedTurnProvider(turns)
    mgr = SessionManager(workspace=tmp_path, provider=provider)
    mgr.secrets.put("telegram:default", {"bot_token": "T", "enabled": True})

    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    # Send prompt
    event = _tg_event("what is the ai top news today")
    await bridge.handle_inbound(event)

    # Wait for the background task to complete
    task = bridge._active_tasks.get("12345")
    if task:
        await task

    # Verify session record in SQLite
    active = bridge.store.get_active_session("12345")
    assert active is None  # Finished -> turn is not running
    rec = bridge.store.get("12345")
    assert rec is not None
    assert rec.status == "IDLE"  # Session remains active in store, execution state IDLE

    # Verify messages sent to Telegram
    all_texts = [m["text"] for m in fake_client.sent_messages] + [m["text"] for m in fake_client.edited_messages]
    assert any("CogniOS session started" in t for t in all_texts)
    assert any("Top AI News" in m["text"] for m in fake_client.sent_messages)


@pytest.mark.asyncio
async def test_telegram_stop_and_cancel_command(tmp_path, monkeypatch):
    """Test /stop and /cancel immediately halt active agent execution."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")

    fake_client = FakeTelegramClient()
    provider = SlowInterruptibleProvider(sleep_seconds=1.0)
    mgr = SessionManager(workspace=tmp_path, provider=provider)
    mgr.secrets.put("telegram:default", {"bot_token": "T", "enabled": True})

    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    # Start slow task
    await bridge.handle_inbound(_tg_event("do something slow"))
    old_rec = bridge.store.get("12345")
    assert old_rec is not None
    old_session_id = old_rec.session_id

    # Send /stop
    await bridge.handle_inbound(_tg_event("/stop"))

    # Verify old session marked stopped in conversation store
    old_sess = mgr.session_store.load(old_session_id)
    assert old_sess is not None
    assert old_sess.status == "stopped"

    # Fresh session is active and IDLE for next prompt
    fresh_rec = bridge.store.get("12345")
    assert fresh_rec is not None
    assert fresh_rec.session_id != old_session_id
    assert fresh_rec.status == "IDLE"

    all_texts = [m["text"] for m in fake_client.sent_messages] + [m["text"] for m in fake_client.edited_messages]
    assert any("Session stopped" in t for t in all_texts)


@pytest.mark.asyncio
async def test_telegram_stop_when_idle(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)

    await bridge.handle_inbound(_tg_event("/stop"))
    assert any("No active CogniOS session" in m["text"] for m in fake_client.sent_messages)


@pytest.mark.asyncio
async def test_telegram_start_command(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)

    await bridge.handle_inbound(_tg_event("/start"))
    assert bridge.store.get("12345") is None  # No session spawned
    assert any("Welcome to CogniOS" in m["text"] for m in fake_client.sent_messages)


@pytest.mark.asyncio
async def test_telegram_new_command(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()
    turns = [AssistantTurn(text="Brand new task response.", finish_reason="stop")]
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider(turns))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    # 1. Bare /new
    await bridge.handle_inbound(_tg_event("/new"))
    assert any("New session ready" in m["text"] for m in fake_client.sent_messages)

    # 2. /new with prompt
    await bridge.handle_inbound(_tg_event("/new analyze this task"))
    # Wait for turn
    for _ in range(20):
        if any("Brand new task response" in m["text"] for m in fake_client.sent_messages):
            break
        await asyncio.sleep(0.05)
    assert any("Brand new task response" in m["text"] for m in fake_client.sent_messages)
    assert bridge.store.get("12345").prompt == "analyze this task"


@pytest.mark.asyncio
async def test_telegram_approval_routing(tmp_path, monkeypatch):
    """Test interactive /approve and /deny resolution."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()

    # Tool call needing approval (save_skill has requires_approval=True)
    turns = [
        AssistantTurn(
            tool_calls=[ToolCall(id="tc1", name="save_skill", arguments={"name": "test_skill", "instructions": "test"})],
            text=None,
        ),
        AssistantTurn(text="Skill saved successfully.", finish_reason="stop"),
    ]
    provider = ScriptedTurnProvider(turns)
    mgr = SessionManager(workspace=tmp_path, provider=provider)
    mgr.secrets.put("telegram:default", {"bot_token": "T", "enabled": True})

    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    # Start task
    await bridge.handle_inbound(_tg_event("run directory check"))

    # Wait until approval prompt is sent
    for _ in range(20):
        if any("needs your approval" in m["text"] for m in fake_client.sent_messages):
            break
        await asyncio.sleep(0.05)

    assert any("needs your approval" in m["text"] for m in fake_client.sent_messages)
    assert bridge.store.get("12345").status == "WAITING_APPROVAL"

    # Send /approve
    await bridge.handle_inbound(_tg_event("/approve"))

    # Wait for turn completion
    task = bridge._active_tasks.get("12345")
    if task:
        await task

    # Verify task resumed and finished
    assert bridge.store.get("12345").status == "IDLE"
    assert any("Approved" in m["text"] for m in fake_client.sent_messages)


@pytest.mark.asyncio
async def test_telegram_unauthorized_user(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "allowed_user")
    fake_client = FakeTelegramClient()
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)

    # Unauthorized sender
    await bridge.handle_inbound(_tg_event("hello", user_id="intruder"))
    assert bridge.store.get("12345") is None  # No session
    assert any("not authorized" in m["text"] for m in fake_client.sent_messages)


@pytest.mark.asyncio
async def test_telegram_concurrent_task_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()
    provider = SlowInterruptibleProvider(sleep_seconds=1.0)
    mgr = SessionManager(workspace=tmp_path, provider=provider)
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    # Start first task
    await bridge.handle_inbound(_tg_event("task 1"))
    assert bridge.store.get_active_session("12345") is not None

    # Try starting second task
    await bridge.handle_inbound(_tg_event("task 2"))
    assert any("already have a CogniOS task running" in m["text"] for m in fake_client.sent_messages)

    # Clean up
    await bridge.handle_inbound(_tg_event("/stop"))


def test_telegram_connector_tool_registration(tmp_path):
    secrets = getattr(SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([])), "secrets")
    tools = tool_dicts(secrets, "telegram")
    tool_names = {t["name"] for t in tools}
    assert "telegram_agent_bridge" in tool_names
    # Connector list includes tools
    clist = connector_list(secrets)
    tg_item = next(c for c in clist if c["name"] == "telegram")
    assert tg_item["tools"]
    assert any(t["name"] == "telegram_agent_bridge" for t in tg_item["tools"])


# ==============================================================================
# Model Command & Interactive Selector Tests (Tests 1-17)
# ==============================================================================

@pytest.mark.asyncio
async def test_model_picker_keyboard_display(tmp_path, monkeypatch):
    """Test 1: /model renders inline keyboard with ✓ on active model and others without ✓."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    mgr.model = "gpt-5.6-sol"
    monkeypatch.setattr(mgr, "get_settings", lambda: {
        "model": "ollama:gemma4:e4b",
        "models": ["ollama:gemma4:e4b", "openrouter:glm-5.2", "ollama:gemma4:e2b"],
        "model_labels": {
            "ollama:gemma4:e4b": "gemma4:e4b",
            "openrouter:glm-5.2": "GLM-5.2 • via OpenRouter",
            "ollama:gemma4:e2b": "gemma4:e2b",
        }
    })
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    await bridge.handle_inbound(_tg_event("/model"))

    assert len(fake_client.sent_messages) == 1
    sent = fake_client.sent_messages[0]
    assert "Select Model" in sent["text"]
    assert "gemma4:e4b" in sent["text"]
    assert sent["reply_markup"] is not None
    keyboard = sent["reply_markup"]["inline_keyboard"]
    assert len(keyboard) == 3

    # Check button texts
    texts = [row[0]["text"] for row in keyboard]
    assert "gemma4:e4b ✓" in texts
    assert "GLM-5.2 • via OpenRouter" in texts
    assert "gemma4:e2b" in texts
    assert not any(t == "GLM-5.2 • via OpenRouter ✓" for t in texts)
    assert not any(t == "gemma4:e2b ✓" for t in texts)


@pytest.mark.asyncio
async def test_direct_model_switch(tmp_path, monkeypatch):
    """Test 2: /model <model> direct model change switches model on same session."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    mgr.model = "gpt-5.6-sol"
    monkeypatch.setattr(mgr, "get_settings", lambda: {
        "model": "gpt-5.6-sol",
        "models": ["ollama:gemma4:e4b", "ollama:gemma4:e2b"],
        "model_labels": {"ollama:gemma4:e4b": "gemma4:e4b", "ollama:gemma4:e2b": "gemma4:e2b"}
    })
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    # Create an active session
    sess = mgr.session_store.create_telegram_session(
        chat_id="12345", user_name="u1", model="ollama:gemma4:e4b"
    )
    assert sess.model == "ollama:gemma4:e4b"
    initial_session_id = sess.session_id

    # Switch model directly
    await bridge.handle_inbound(_tg_event("/model gemma4:e2b"))

    # Verify same session updated in DB
    updated_sess = mgr.session_store.get_active_telegram_session("12345")
    assert updated_sess is not None
    assert updated_sess.session_id == initial_session_id
    assert updated_sess.model == "ollama:gemma4:e2b"

    # Verify global default is NOT mutated
    assert mgr.model == "gpt-5.6-sol"

    # Verify confirmation message
    assert "Model changed" in fake_client.sent_messages[-1]["text"]
    assert "gemma4:e2b" in fake_client.sent_messages[-1]["text"]


@pytest.mark.asyncio
async def test_invalid_model_rejection(tmp_path, monkeypatch):
    """Test 3: /model <invalid-model> rejects unknown model without changing state."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    mgr.model = "gpt-5.6-sol"
    monkeypatch.setattr(mgr, "get_settings", lambda: {
        "model": "ollama:gemma4:e4b",
        "models": ["ollama:gemma4:e4b"],
        "model_labels": {}
    })
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    await bridge.handle_inbound(_tg_event("/model does-not-exist"))

    assert mgr.model == "gpt-5.6-sol"
    assert bridge.store.get_model_preference("12345") is None
    assert "Model not available" in fake_client.sent_messages[-1]["text"]
    assert "does-not-exist" in fake_client.sent_messages[-1]["text"]


@pytest.mark.asyncio
async def test_callback_query_selection(tmp_path, monkeypatch):
    """Test 4: Callback selection switches model, acknowledges callback immediately, edits message with updated keyboard."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    mgr.model = "gpt-5.6-sol"
    monkeypatch.setattr(mgr, "get_settings", lambda: {
        "model": "ollama:gemma4:e4b",
        "models": ["ollama:gemma4:e4b", "ollama:gemma4:e2b"],
        "model_labels": {"ollama:gemma4:e4b": "gemma4:e4b", "ollama:gemma4:e2b": "gemma4:e2b"}
    })
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    # Create active session
    sess = mgr.session_store.create_telegram_session(
        chat_id="12345", user_name="u1", model="ollama:gemma4:e4b"
    )

    # Click model button (index 1 -> ollama:gemma4:e2b)
    ok = await bridge.handle_callback_query(
        chat_id="12345",
        user_id="u1",
        callback_data="model_select:1",
        message_id="999",
        callback_query_id="cb-101",
    )
    assert ok is True

    # Verify callback answered immediately
    assert any(cb["callback_query_id"] == "cb-101" for cb in fake_client.answered_callbacks)

    # Verify session model updated on same session_id
    reloaded = mgr.session_store.get_active_telegram_session("12345")
    assert reloaded.session_id == sess.session_id
    assert reloaded.model == "ollama:gemma4:e2b"

    # Verify message edited
    assert len(fake_client.edited_messages) == 1
    edited = fake_client.edited_messages[0]
    assert "Model Changed" in edited["text"]
    assert "gemma4:e4b" in edited["text"]
    assert "gemma4:e2b" in edited["text"]

    # Verify edited message keyboard has checkmark on gemma4:e2b
    new_kb = edited["reply_markup"]["inline_keyboard"]
    new_texts = [row[0]["text"] for row in new_kb]
    assert "gemma4:e2b ✓" in new_texts
    assert "gemma4:e4b" in new_texts


@pytest.mark.asyncio
async def test_callback_same_model_idempotent(tmp_path, monkeypatch):
    """Test 5: Clicking current model is idempotent and returns clean acknowledgement."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    monkeypatch.setattr(mgr, "get_settings", lambda: {
        "model": "ollama:gemma4:e4b",
        "models": ["ollama:gemma4:e4b", "ollama:gemma4:e2b"],
        "model_labels": {"ollama:gemma4:e4b": "gemma4:e4b", "ollama:gemma4:e2b": "gemma4:e2b"}
    })
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    # Create active session with gemma4:e4b
    mgr.session_store.create_telegram_session(
        chat_id="12345", user_name="u1", model="ollama:gemma4:e4b"
    )

    # Click current model (index 0 -> ollama:gemma4:e4b)
    ok = await bridge.handle_callback_query(
        chat_id="12345",
        user_id="u1",
        callback_data="model_select:0",
        message_id="999",
        callback_query_id="cb-same",
    )
    assert ok is True
    assert any("already active" in str(cb.get("text", "")) for cb in fake_client.answered_callbacks)


@pytest.mark.asyncio
async def test_session_preservation_across_switch(tmp_path, monkeypatch):
    """Test 6: Model switch preserves session_id, message_count, conversation history, and workspace."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    monkeypatch.setattr(mgr, "get_settings", lambda: {
        "model": "ollama:gemma4:e4b",
        "models": ["ollama:gemma4:e4b", "ollama:gemma4:e2b"],
        "model_labels": {}
    })
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    # Create session with messages
    sess = mgr.session_store.create_telegram_session(
        chat_id="12345", user_name="u1", model="ollama:gemma4:e4b", workspace=str(tmp_path)
    )
    sess.messages = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
    sess.message_count = len(sess.messages)
    mgr.session_store.save(sess)

    assert sess.message_count == 10
    sid = sess.session_id

    # Switch model
    await bridge.handle_inbound(_tg_event("/model gemma4:e2b"))

    reloaded = mgr.session_store.load(sid)
    assert reloaded.session_id == sid
    assert reloaded.message_count == 10
    assert len(reloaded.messages) == 10
    assert reloaded.workspace == str(tmp_path)
    assert reloaded.model == "ollama:gemma4:e2b"


@pytest.mark.asyncio
async def test_multiple_chats_session_isolation(tmp_path, monkeypatch):
    """Test 7: Chat A switching model does NOT affect Chat B or global manager.model."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1,u2")
    fake_client = FakeTelegramClient()
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    mgr.model = "gpt-5.6-sol"
    monkeypatch.setattr(mgr, "get_settings", lambda: {
        "model": "gpt-5.6-sol",
        "models": ["ollama:gemma4:e4b", "ollama:gemma4:e2b", "openrouter:glm-5.2"],
        "model_labels": {}
    })
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    # Chat A on gemma4:e4b
    sess_a = mgr.session_store.create_telegram_session(chat_id="100", user_name="u1", model="ollama:gemma4:e4b")
    # Chat B on glm-5.2
    sess_b = mgr.session_store.create_telegram_session(chat_id="200", user_name="u2", model="openrouter:glm-5.2")

    # Chat A switches to gemma4:e2b
    await bridge.handle_inbound(_tg_event("/model gemma4:e2b", chat_id="100", user_id="u1"))

    # Verify Chat A changed
    reloaded_a = mgr.session_store.load(sess_a.session_id)
    assert reloaded_a.model == "ollama:gemma4:e2b"

    # Verify Chat B unchanged
    reloaded_b = mgr.session_store.load(sess_b.session_id)
    assert reloaded_b.model == "openrouter:glm-5.2"

    # Verify global manager.model untouched
    assert mgr.model == "gpt-5.6-sol"


@pytest.mark.asyncio
async def test_unauthorized_callback_rejected(tmp_path, monkeypatch):
    """Test 8: Unauthorized user callback is rejected and cannot mutate any session."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "authorized_user")
    monkeypatch.delenv("TELEGRAM_ALLOW_ALL", raising=False)
    fake_client = FakeTelegramClient()
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    sess = mgr.session_store.create_telegram_session(chat_id="12345", user_name="authorized_user", model="ollama:gemma4:e4b")

    # Unauthorized callback
    ok = await bridge.handle_callback_query(
        chat_id="12345",
        user_id="intruder",
        callback_data="model_select:1",
        callback_query_id="cb-intruder",
    )
    assert ok is False

    # Verify session untouched
    reloaded = mgr.session_store.load(sess.session_id)
    assert reloaded.model == "ollama:gemma4:e4b"
    assert any("not authorized" in str(cb.get("text", "")) for cb in fake_client.answered_callbacks)


@pytest.mark.asyncio
async def test_unavailable_model_transactional(tmp_path, monkeypatch):
    """Test 9: Requesting unavailable model preserves old model transactionally."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    monkeypatch.setattr(mgr, "get_settings", lambda: {
        "model": "ollama:gemma4:e4b",
        "models": ["ollama:gemma4:e4b"],
        "model_labels": {}
    })
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    sess = mgr.session_store.create_telegram_session(chat_id="12345", user_name="u1", model="ollama:gemma4:e4b")

    # Direct switch with unknown model
    await bridge.handle_inbound(_tg_event("/model nonexistent:model"))

    reloaded = mgr.session_store.load(sess.session_id)
    assert reloaded.model == "ollama:gemma4:e4b"


@pytest.mark.asyncio
async def test_malformed_callback_safety(tmp_path, monkeypatch):
    """Test 10: Empty, corrupted, or malformed callback data handled gracefully without exceptions."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    for malformed in ["", "garbage", "model_select:", "model_select:9999", "model:"]:
        ok = await bridge.handle_callback_query(
            chat_id="12345",
            user_id="u1",
            callback_data=malformed,
            callback_query_id=f"cb-{malformed}",
        )
        assert ok is False


@pytest.mark.asyncio
async def test_model_preference_and_session_persistence(tmp_path, monkeypatch):
    """Test 11: Switched model persists across restart and reloads in new bridge instance."""
    db_file = tmp_path / "cogniwork.db"
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")

    # Instance 1
    fake1 = FakeTelegramClient()
    mgr1 = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    monkeypatch.setattr(mgr1, "get_settings", lambda: {
        "model": "ollama:gemma4:e4b",
        "models": ["ollama:gemma4:e4b", "ollama:gemma4:e2b"],
        "model_labels": {}
    })
    bridge1 = TelegramAgentBridge(mgr1, db_file, client_factory=lambda tok: fake1)
    mgr1.telegram_bridge = bridge1

    sess = mgr1.session_store.create_telegram_session(chat_id="12345", user_name="u1", model="ollama:gemma4:e4b")
    await bridge1.handle_inbound(_tg_event("/model gemma4:e2b"))
    bridge1.store.close()

    # Instance 2 (Server restart)
    fake2 = FakeTelegramClient()
    mgr2 = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    monkeypatch.setattr(mgr2, "get_settings", lambda: {
        "model": "ollama:gemma4:e4b",
        "models": ["ollama:gemma4:e4b", "ollama:gemma4:e2b"],
        "model_labels": {}
    })
    bridge2 = TelegramAgentBridge(mgr2, db_file, client_factory=lambda tok: fake2)
    mgr2.telegram_bridge = bridge2

    # Verify session and preference survived
    reloaded_sess = mgr2.session_store.get_active_telegram_session("12345")
    assert reloaded_sess is not None
    assert reloaded_sess.model == "ollama:gemma4:e2b"
    pref = bridge2.store.get_model_preference("12345")
    assert pref is not None
    assert pref.model == "ollama:gemma4:e2b"


@pytest.mark.asyncio
async def test_callback_replay_and_concurrency(tmp_path, monkeypatch):
    """Test 12: Concurrent callbacks on the same chat serialize safely without race conditions."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    monkeypatch.setattr(mgr, "get_settings", lambda: {
        "model": "ollama:gemma4:e4b",
        "models": ["ollama:gemma4:e4b", "ollama:gemma4:e2b", "openrouter:glm-5.2"],
        "model_labels": {}
    })
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    mgr.session_store.create_telegram_session(chat_id="12345", user_name="u1", model="ollama:gemma4:e4b")

    # Run 3 concurrent callbacks
    tasks = [
        bridge.handle_callback_query("12345", "u1", "model_select:1", callback_query_id="cb1"),
        bridge.handle_callback_query("12345", "u1", "model_select:2", callback_query_id="cb2"),
        bridge.handle_callback_query("12345", "u1", "model_select:1", callback_query_id="cb3"),
    ]
    results = await asyncio.gather(*tasks)
    assert all(r is True for r in results)

    # Session remains in consistent state
    reloaded = mgr.session_store.get_active_telegram_session("12345")
    assert reloaded.model in ["ollama:gemma4:e2b", "openrouter:glm-5.2"]


@pytest.mark.asyncio
async def test_runtime_model_execution(tmp_path, monkeypatch):
    """Test 13: Switching model causes subsequent prompt turns to execute against the new model."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()
    captured_models: list[str] = []

    class CapturingProvider(ScriptedTurnProvider):
        def complete(self, *, model, messages, tools=None, **settings):
            captured_models.append(model)
            return AssistantTurn(text="Answer from new model", finish_reason="stop")

    provider = CapturingProvider([])
    mgr = SessionManager(workspace=tmp_path, provider=provider)
    mgr.model = "gpt-5.6-sol"
    monkeypatch.setattr(mgr, "get_settings", lambda: {
        "model": "ollama:gemma4:e4b",
        "models": ["ollama:gemma4:e4b", "ollama:gemma4:e2b"],
        "model_labels": {}
    })
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    # Switch model to gemma4:e2b
    await bridge.handle_inbound(_tg_event("/model gemma4:e2b"))

    # Send normal user prompt
    await bridge.handle_inbound(_tg_event("Tell me a story"))

    # Wait for turn execution
    for _ in range(20):
        if any("Answer from new model" in m["text"] for m in fake_client.sent_messages):
            break
        await asyncio.sleep(0.05)

    assert len(captured_models) >= 1
    assert captured_models[-1] == "ollama:gemma4:e2b"


@pytest.mark.asyncio
async def test_provider_routing_switch(tmp_path, monkeypatch):
    """Test 14: Switching between Ollama and OpenRouter routes through the correct provider."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    monkeypatch.setattr(mgr, "get_settings", lambda: {
        "model": "ollama:gemma4:e4b",
        "models": ["ollama:gemma4:e4b", "openrouter:glm-5.2"],
        "model_labels": {}
    })
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    # Switch to OpenRouter
    await bridge.handle_inbound(_tg_event("/model glm-5.2"))
    pref = bridge.store.get_model_preference("12345")
    assert pref.provider == "openrouter"

    # Switch back to Ollama
    await bridge.handle_inbound(_tg_event("/model gemma4:e4b"))
    pref2 = bridge.store.get_model_preference("12345")
    assert pref2.provider == "ollama"


@pytest.mark.asyncio
async def test_model_current(tmp_path, monkeypatch):
    """Test 15: /model current returns active model and provider without changing state."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    mgr.model = "ollama:gemma4:e4b"
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    await bridge.handle_inbound(_tg_event("/model current"))
    assert "Current Model" in fake_client.sent_messages[-1]["text"]
    assert "gemma4:e4b" in fake_client.sent_messages[-1]["text"]


@pytest.mark.asyncio
async def test_model_default_reset(tmp_path, monkeypatch):
    """Test 16: /model default resets chat preference to global default without altering global default."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    mgr.model = "gpt-5.6-sol"
    monkeypatch.setattr(mgr, "get_settings", lambda: {
        "model": "gpt-5.6-sol",
        "models": ["gpt-5.6-sol", "ollama:gemma4:e2b"],
        "model_labels": {}
    })
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    # Set chat preference
    bridge.store.set_model_preference("12345", "u1", "ollama", "ollama:gemma4:e2b")

    # Reset preference
    await bridge.handle_inbound(_tg_event("/model default"))

    assert bridge.store.get_model_preference("12345") is None
    assert mgr.model == "gpt-5.6-sol"
    assert "Model reset to default" in fake_client.sent_messages[-1]["text"]


@pytest.mark.asyncio
async def test_models_alias(tmp_path, monkeypatch):
    """Test 17: /models alias opens the exact same model picker as /model."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    mgr.model = "ollama:gemma4:e4b"
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    await bridge.handle_inbound(_tg_event("/models"))

    assert len(fake_client.sent_messages) == 1
    assert "Select Model" in fake_client.sent_messages[0]["text"]
    assert fake_client.sent_messages[0]["reply_markup"] is not None



@pytest.mark.asyncio
async def test_telegram_session_reuse_across_turns(tmp_path, monkeypatch):
    """Verify that multiple incoming messages from the same Telegram chat reuse the same session ID."""
    fake_client = FakeTelegramClient()
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")

    turns = [
        AssistantTurn(text="First answer"),
        AssistantTurn(text="Second answer"),
    ]
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider(turns))
    bridge = TelegramAgentBridge(
        mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client
    )
    mgr.telegram_bridge = bridge

    # Turn 1
    await bridge.handle_inbound(
        _tg_event("First prompt", chat_id="chat-999", user_id="u1", user_name="Yashwant")
    )
    rec1 = bridge.store.get("chat-999")
    assert rec1 is not None
    session_id_1 = rec1.session_id

    # Verify session in ConversationStore
    sess1 = mgr.session_store.load(session_id_1)
    assert sess1 is not None
    assert sess1.source == "telegram"
    assert sess1.telegram_chat_id == "chat-999"
    assert sess1.telegram_username == "Yashwant"

    # Turn 2: same chat
    await bridge.handle_inbound(
        _tg_event("Second prompt", chat_id="chat-999", user_id="u1", user_name="Yashwant")
    )
    rec2 = bridge.store.get("chat-999")
    assert rec2 is not None
    assert rec2.session_id == session_id_1  # Reused!


@pytest.mark.asyncio
async def test_telegram_new_command_resets_session(tmp_path, monkeypatch):
    """Verify that /new command resets the session so the next prompt creates a new session."""
    fake_client = FakeTelegramClient()
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")

    turns = [
        AssistantTurn(text="First answer"),
        AssistantTurn(text="Fresh session answer"),
    ]
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider(turns))
    bridge = TelegramAgentBridge(
        mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client
    )
    mgr.telegram_bridge = bridge

    # 1. First session
    await bridge.handle_inbound(
        _tg_event("Prompt 1", chat_id="chat-reset-test", user_id="u1")
    )
    first_session_id = bridge.store.get("chat-reset-test").session_id

    # 2. Issue /new
    await bridge.handle_inbound(
        _tg_event("/new", chat_id="chat-reset-test", user_id="u1")
    )
    # /new closes the first session and creates a fresh active session in store
    new_sess_rec = bridge.store.get("chat-reset-test")
    assert new_sess_rec is not None
    assert new_sess_rec.session_id != first_session_id

    # Verify old session marked completed in conversation store
    old_sess = mgr.session_store.load(first_session_id)
    assert old_sess is not None
    assert old_sess.status == "completed"

    # 3. Next message uses the newly active session
    await bridge.handle_inbound(
        _tg_event("Prompt after reset", chat_id="chat-reset-test", user_id="u1")
    )
    used_rec = bridge.store.get("chat-reset-test")
    assert used_rec is not None
    assert used_rec.session_id == new_sess_rec.session_id
    assert used_rec.session_id != first_session_id


@pytest.mark.asyncio
async def test_telegram_session_source_separation(tmp_path, monkeypatch):
    """Verify that web sessions and Telegram sessions are strictly separated in ConversationStore."""
    fake_client = FakeTelegramClient()
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")

    turns = [AssistantTurn(text="Telegram answer")]
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider(turns))
    bridge = TelegramAgentBridge(
        mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client
    )
    mgr.telegram_bridge = bridge

    # Create a web session directly in manager
    from cogniwork.sessions import SessionRecord
    mgr.session_store.save(
        SessionRecord(
            session_id="web-sess-1",
            workspace=str(tmp_path),
            model="gpt-5",
            mode="interactive",
            title="Web Session Title",
            source="web",
        )
    )

    # Create a Telegram session via inbound bridge
    await bridge.handle_inbound(
        _tg_event("Telegram Task", chat_id="tg-chat-source-test", user_id="u1", user_name="Alice")
    )

    # Query Web Recent
    web_sessions = mgr.session_store.list(source="web")
    web_ids = [s.session_id for s in web_sessions]
    assert "web-sess-1" in web_ids
    tg_sess_id = bridge.store.get("tg-chat-source-test").session_id
    assert tg_sess_id not in web_ids

    # Query Telegram
    tg_sessions = mgr.session_store.list(source="telegram")
    tg_ids = [s.session_id for s in tg_sessions]
    assert tg_sess_id in tg_ids
    assert "web-sess-1" not in tg_ids

    # Query via list_sessions with source parameter
    manager_web = mgr.list_sessions(source="web")
    manager_web_ids = [s["session_id"] for s in manager_web]
    assert "web-sess-1" in manager_web_ids
    assert tg_sess_id not in manager_web_ids

    manager_tg = mgr.list_sessions(source="telegram")
    manager_tg_ids = [s["session_id"] for s in manager_tg]
    assert tg_sess_id in manager_tg_ids
    assert "web-sess-1" not in manager_tg_ids


# ==============================================================================
# Dedicated 7 User Acceptance Test Cases
# ==============================================================================

@pytest.mark.asyncio
async def test_user_req_test_1_multi_turn_continuity(tmp_path, monkeypatch):
    """Test 1: Send 'Hello', 'What is 2 + 2?', 'Explain why' -> ALL 3 reuse the same session ID."""
    fake_client = FakeTelegramClient()
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "5506865927")

    turns = [
        AssistantTurn(text="Hello! How can I help you today?"),
        AssistantTurn(text="2 + 2 is 4."),
        AssistantTurn(text="Because addition combines two groups of two objects into four objects."),
    ]
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider(turns))
    bridge = TelegramAgentBridge(
        mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client
    )
    mgr.telegram_bridge = bridge

    # Message 1
    await bridge.handle_inbound(
        _tg_event("Hello", chat_id="5506865927", user_id="5506865927", user_name="chyk2468")
    )
    if bridge._active_tasks.get("5506865927"):
        await bridge._active_tasks["5506865927"]
    s1 = bridge.store.get("5506865927")
    assert s1 is not None
    session_id_1 = s1.session_id

    # Message 2
    await bridge.handle_inbound(
        _tg_event("What is 2 + 2?", chat_id="5506865927", user_id="5506865927", user_name="chyk2468")
    )
    if bridge._active_tasks.get("5506865927"):
        await bridge._active_tasks["5506865927"]
    s2 = bridge.store.get("5506865927")
    assert s2 is not None
    assert s2.session_id == session_id_1

    # Message 3
    await bridge.handle_inbound(
        _tg_event("Explain why", chat_id="5506865927", user_id="5506865927", user_name="chyk2468")
    )
    if bridge._active_tasks.get("5506865927"):
        await bridge._active_tasks["5506865927"]
    s3 = bridge.store.get("5506865927")
    assert s3 is not None
    assert s3.session_id == session_id_1

    # Verify conversation history has all messages appended in the same conversation
    loaded = mgr.session_store.load(session_id_1)
    assert loaded is not None
    assert loaded.message_count >= 3
    assert loaded.source == "telegram"
    assert loaded.telegram_chat_id == "5506865927"


@pytest.mark.asyncio
async def test_user_req_test_2_new_command_creates_new_session(tmp_path, monkeypatch):
    """Test 2: /new closes active session and starts a new session for subsequent messages."""
    fake_client = FakeTelegramClient()
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "5506865927")

    turns = [
        AssistantTurn(text="Response in session 1"),
        AssistantTurn(text="Response in session 2"),
    ]
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider(turns))
    bridge = TelegramAgentBridge(
        mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client
    )
    mgr.telegram_bridge = bridge

    # Message 1
    await bridge.handle_inbound(
        _tg_event("Hello", chat_id="5506865927", user_id="5506865927", user_name="chyk2468")
    )
    if bridge._active_tasks.get("5506865927"):
        await bridge._active_tasks["5506865927"]
    sess1_id = bridge.store.get("5506865927").session_id

    # Send /new
    await bridge.handle_inbound(
        _tg_event("/new", chat_id="5506865927", user_id="5506865927", user_name="chyk2468")
    )
    sess2_id = bridge.store.get("5506865927").session_id
    assert sess2_id != sess1_id

    # Old session is marked completed in DB
    old_sess = mgr.session_store.load(sess1_id)
    assert old_sess.status == "completed"

    # Next message uses new session
    await bridge.handle_inbound(
        _tg_event("Hello again", chat_id="5506865927", user_id="5506865927", user_name="chyk2468")
    )
    if bridge._active_tasks.get("5506865927"):
        await bridge._active_tasks["5506865927"]
    assert bridge.store.get("5506865927").session_id == sess2_id


@pytest.mark.asyncio
async def test_user_req_test_3_stop_command_creates_new_session(tmp_path, monkeypatch):
    """Test 3: /stop stops and closes session, and establishes fresh active session for next prompt."""
    fake_client = FakeTelegramClient()
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "5506865927")

    turns = [
        AssistantTurn(text="Response 1"),
        AssistantTurn(text="Response after stop"),
    ]
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider(turns))
    bridge = TelegramAgentBridge(
        mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client
    )
    mgr.telegram_bridge = bridge

    # Message 1
    await bridge.handle_inbound(
        _tg_event("Hello", chat_id="5506865927", user_id="5506865927", user_name="chyk2468")
    )
    if bridge._active_tasks.get("5506865927"):
        await bridge._active_tasks["5506865927"]
    sess1_id = bridge.store.get("5506865927").session_id

    # Send /stop
    await bridge.handle_inbound(
        _tg_event("/stop", chat_id="5506865927", user_id="5506865927", user_name="chyk2468")
    )
    sess3_id = bridge.store.get("5506865927").session_id
    assert sess3_id != sess1_id

    # Old session marked stopped in DB
    old_sess = mgr.session_store.load(sess1_id)
    assert old_sess.status == "stopped"

    # Next message uses sess3_id
    await bridge.handle_inbound(
        _tg_event("Hello after stop", chat_id="5506865927", user_id="5506865927", user_name="chyk2468")
    )
    if bridge._active_tasks.get("5506865927"):
        await bridge._active_tasks["5506865927"]
    assert bridge.store.get("5506865927").session_id == sess3_id


@pytest.mark.asyncio
async def test_user_req_test_4_sidebar_conversation_count(tmp_path, monkeypatch):
    """Test 4: Multiple Telegram messages for same chat produce exactly 1 active conversation."""
    fake_client = FakeTelegramClient()
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "5506865927")

    turns = [
        AssistantTurn(text="Ans 1"),
        AssistantTurn(text="Ans 2"),
        AssistantTurn(text="Ans 3"),
    ]
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider(turns))
    bridge = TelegramAgentBridge(
        mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client
    )
    mgr.telegram_bridge = bridge

    # Send 3 messages
    await bridge.handle_inbound(_tg_event("msg1", chat_id="5506865927", user_id="5506865927"))
    if bridge._active_tasks.get("5506865927"):
        await bridge._active_tasks["5506865927"]
    await bridge.handle_inbound(_tg_event("msg2", chat_id="5506865927", user_id="5506865927"))
    if bridge._active_tasks.get("5506865927"):
        await bridge._active_tasks["5506865927"]
    await bridge.handle_inbound(_tg_event("msg3", chat_id="5506865927", user_id="5506865927"))
    if bridge._active_tasks.get("5506865927"):
        await bridge._active_tasks["5506865927"]

    tg_sessions = mgr.session_store.list(source="telegram")
    # Exactly ONE Telegram conversation created
    assert len(tg_sessions) == 1
    assert tg_sessions[0].telegram_chat_id == "5506865927"


@pytest.mark.asyncio
async def test_user_req_test_5_server_restart_recovers_active_session(tmp_path, monkeypatch):
    """Test 5: Restart CogniOS -> send Telegram message -> SAME active Telegram session continues."""
    db_file = tmp_path / "cogniwork.db"
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "5506865927")

    # Instance 1: Handle first message
    fake_client1 = FakeTelegramClient()
    turns1 = [AssistantTurn(text="Ans before restart")]
    mgr1 = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider(turns1))
    bridge1 = TelegramAgentBridge(mgr1, db_file, client_factory=lambda tok: fake_client1)
    mgr1.telegram_bridge = bridge1

    await bridge1.handle_inbound(
        _tg_event("Message before restart", chat_id="5506865927", user_id="5506865927", user_name="chyk2468")
    )
    active_id_before = bridge1.store.get("5506865927").session_id
    bridge1.store.close()
    mgr1.session_store.close()

    # Restart CogniOS: Create fresh Manager & Bridge on same DB
    fake_client2 = FakeTelegramClient()
    turns2 = [AssistantTurn(text="Ans after restart")]
    mgr2 = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider(turns2))
    bridge2 = TelegramAgentBridge(mgr2, db_file, client_factory=lambda tok: fake_client2)
    mgr2.telegram_bridge = bridge2

    # Recover sessions on startup
    bridge2.recover_stale_sessions()

    # Send message after restart
    await bridge2.handle_inbound(
        _tg_event("Message after restart", chat_id="5506865927", user_id="5506865927", user_name="chyk2468")
    )
    active_id_after = bridge2.store.get("5506865927").session_id

    # MUST be the exact same session ID
    assert active_id_after == active_id_before
    # Telegram sessions table should still only have 1 session
    assert len(mgr2.session_store.list(source="telegram")) == 1


@pytest.mark.asyncio
async def test_user_req_test_6_telegram_message_in_telegram_not_recent(tmp_path, monkeypatch):
    """Test 6: Send Telegram message -> appears under TELEGRAM, not RECENT."""
    fake_client = FakeTelegramClient()
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "5506865927")

    turns = [AssistantTurn(text="Telegram response")]
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider(turns))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    await bridge.handle_inbound(
        _tg_event("Telegram task", chat_id="5506865927", user_id="5506865927", user_name="chyk2468")
    )

    tg_sess = mgr.session_store.list(source="telegram")
    recent_sess = mgr.session_store.list(source="web")

    assert len(tg_sess) == 1
    assert tg_sess[0].telegram_chat_id == "5506865927"
    assert len(recent_sess) == 0


@pytest.mark.asyncio
async def test_user_req_test_7_web_session_in_recent_not_telegram(tmp_path):
    """Test 7: Create normal web session -> appears under RECENT, not TELEGRAM."""
    from cogniwork.sessions import SessionRecord
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))

    # Create normal web session
    mgr.session_store.save(
        SessionRecord(
            session_id="web-turn-sess-1",
            workspace=str(tmp_path),
            model="gpt-5",
            mode="interactive",
            title="Web Design Session",
            source="web",
        )
    )

    recent_sess = mgr.session_store.list(source="web")
    tg_sess = mgr.session_store.list(source="telegram")

    assert len(recent_sess) == 1
    assert recent_sess[0].session_id == "web-turn-sess-1"
    assert len(tg_sess) == 0


# -- Telegram Artifact Delivery Tests ------------------------------------------

@pytest.mark.asyncio
async def test_telegram_artifact_python_upload(tmp_path, monkeypatch):
    """Test 1: Python artifact upload -> send_document called with test.py and correct chat_id."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()

    artifacts_dir = tmp_path / "Artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    test_py = artifacts_dir / "test.py"
    test_py.write_text("print('hello from python')")

    turns = [
        AssistantTurn(
            tool_calls=[ToolCall(id="t1", name="grep", arguments={"pattern": "hello", "path": "Artifacts/test.py"})],
            text=None,
        ),
        AssistantTurn(
            text="The Python code has been created: [test.py](artifact:Artifacts/test.py)",
            finish_reason="stop",
        ),
    ]
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider(turns))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    await bridge.handle_inbound(_tg_event("create python script", chat_id="12345", user_id="u1"))
    task = bridge._active_tasks.get("12345")
    if task:
        await task

    assert len(fake_client.sent_documents) == 1
    doc = fake_client.sent_documents[0]
    assert doc["chat_id"] == "12345"
    assert doc["filename"] == "test.py"
    assert doc["document"] == b"print('hello from python')"
    assert any("The Python code has been created" in m["text"] for m in fake_client.sent_messages)


@pytest.mark.asyncio
async def test_telegram_artifact_c_bubble_sort_upload(tmp_path, monkeypatch):
    """Test 2: C artifact upload -> actual Telegram document upload, not merely text link."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()

    artifacts_dir = tmp_path / "Artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    c_file = artifacts_dir / "bubble_sort.c"
    c_file.write_text("void bubble_sort(int arr[], int n) { /* sort */ }")

    turns = [
        AssistantTurn(
            text="The C language code for Bubble Sort has been created: [bubble_sort.c](artifact:Artifacts/bubble_sort.c)",
            finish_reason="stop",
        )
    ]
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider(turns))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    await bridge.handle_inbound(_tg_event("write bubble sort in C", chat_id="12345", user_id="u1"))
    task = bridge._active_tasks.get("12345")
    if task:
        await task

    assert len(fake_client.sent_documents) == 1
    doc = fake_client.sent_documents[0]
    assert doc["chat_id"] == "12345"
    assert doc["filename"] == "bubble_sort.c"
    assert b"void bubble_sort" in doc["document"]


@pytest.mark.asyncio
async def test_telegram_artifact_after_approval_flow(tmp_path, monkeypatch):
    """Test 3: Task -> approval request -> /approve -> task resumes -> artifact created & uploaded."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()

    artifacts_dir = tmp_path / "Artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    approved_file = artifacts_dir / "approved.py"

    turns = [
        AssistantTurn(
            tool_calls=[ToolCall(id="tc1", name="save_skill", arguments={"name": "build_tool", "instructions": "build"})],
            text=None,
        ),
        AssistantTurn(
            text="Approved build complete: [approved.py](artifact:Artifacts/approved.py)",
            finish_reason="stop",
        ),
    ]
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider(turns))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    await bridge.handle_inbound(_tg_event("run approval task", chat_id="12345", user_id="u1"))

    for _ in range(30):
        if any("needs your approval" in m["text"] for m in fake_client.sent_messages):
            break
        await asyncio.sleep(0.05)

    assert bridge.store.get("12345").status == "WAITING_APPROVAL"

    approved_file.write_text("# created after approval")

    await bridge.handle_inbound(_tg_event("/approve", chat_id="12345", user_id="u1"))

    task = bridge._active_tasks.get("12345")
    if task:
        await task

    assert len(fake_client.sent_documents) == 1
    doc = fake_client.sent_documents[0]
    assert doc["chat_id"] == "12345"
    assert doc["filename"] == "approved.py"
    assert doc["document"] == b"# created after approval"


@pytest.mark.asyncio
async def test_telegram_artifact_multiple_files_in_emitted_order(tmp_path, monkeypatch):
    """Test 4: Multiple artifacts created -> all uploaded as separate documents in order."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()

    artifacts_dir = tmp_path / "Artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "file1.py").write_text("# py file")
    (artifacts_dir / "file2.json").write_text('{"key": "value"}')
    (artifacts_dir / "report.pdf").write_bytes(b"%PDF-1.4 report")

    turns = [
        AssistantTurn(
            tool_calls=[
                ToolCall(id="t1", name="grep", arguments={"pattern": "py", "path": "Artifacts/file1.py"}),
                ToolCall(id="t2", name="grep", arguments={"pattern": "val", "path": "Artifacts/file2.json"}),
                ToolCall(id="t3", name="grep", arguments={"pattern": "PDF", "path": "Artifacts/report.pdf"}),
            ],
            text="Created multiple deliverables.",
            finish_reason="stop",
        )
    ]
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider(turns))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    await bridge.handle_inbound(_tg_event("generate reports", chat_id="12345", user_id="u1"))
    task = bridge._active_tasks.get("12345")
    if task:
        await task

    assert len(fake_client.sent_documents) == 3
    filenames = [d["filename"] for d in fake_client.sent_documents]
    assert filenames == ["file1.py", "file2.json", "report.pdf"]


@pytest.mark.asyncio
async def test_telegram_artifact_missing_file_no_crash(tmp_path, monkeypatch):
    """Test 5: Missing artifact referenced -> controlled handling, no document sent, no crash."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()

    turns = [
        AssistantTurn(
            text="Here is the link: [missing.py](artifact:Artifacts/nonexistent_file.py)",
            finish_reason="stop",
        )
    ]
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider(turns))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    await bridge.handle_inbound(_tg_event("get missing file", chat_id="12345", user_id="u1"))
    task = bridge._active_tasks.get("12345")
    if task:
        await task

    assert bridge.store.get("12345").status == "IDLE"
    assert len(fake_client.sent_documents) == 0


@pytest.mark.asyncio
async def test_telegram_artifact_path_traversal_rejected(tmp_path, monkeypatch):
    """Test 6: Path traversal attempt outside workspace -> rejected, security logged, no file sent."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()

    secret_file = tmp_path.parent / "secret_passwd.txt"
    secret_file.write_text("root:secret")

    turns = [
        AssistantTurn(
            text="Here is your file: [secret](artifact:../../secret_passwd.txt)",
            finish_reason="stop",
        )
    ]
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider(turns))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    await bridge.handle_inbound(_tg_event("steal file", chat_id="12345", user_id="u1"))
    task = bridge._active_tasks.get("12345")
    if task:
        await task

    assert len(fake_client.sent_documents) == 0


@pytest.mark.asyncio
async def test_telegram_artifact_chat_isolation(tmp_path, monkeypatch):
    """Test 7: Chat isolation -> Chat A receives its artifact while Chat B receives nothing."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1,u2")
    fake_client = FakeTelegramClient()

    ws_a = tmp_path / "ws_a"
    (ws_a / "Artifacts").mkdir(parents=True, exist_ok=True)
    (ws_a / "Artifacts" / "chat_a.py").write_text("print('Chat A')")

    ws_b = tmp_path / "ws_b"
    ws_b.mkdir(parents=True, exist_ok=True)

    turns_a = [AssistantTurn(text="Created: [chat_a.py](artifact:Artifacts/chat_a.py)", finish_reason="stop")]
    mgr_a = SessionManager(workspace=ws_a, provider=ScriptedTurnProvider(turns_a))
    bridge = TelegramAgentBridge(mgr_a, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr_a.telegram_bridge = bridge

    await bridge.handle_inbound(_tg_event("Task A", chat_id="111", user_id="u1"))
    task_a = bridge._active_tasks.get("111")
    if task_a:
        await task_a

    turns_b = [AssistantTurn(text="No files here.", finish_reason="stop")]
    mgr_a.provider = ScriptedTurnProvider(turns_b)
    await bridge.handle_inbound(_tg_event("Task B", chat_id="222", user_id="u2"))
    task_b = bridge._active_tasks.get("222")
    if task_b:
        await task_b

    assert len(fake_client.sent_documents) == 1
    assert fake_client.sent_documents[0]["chat_id"] == "111"
    assert fake_client.sent_documents[0]["filename"] == "chat_a.py"
    assert not any(d["chat_id"] == "222" for d in fake_client.sent_documents)


@pytest.mark.asyncio
async def test_telegram_artifact_deduplication_single_turn(tmp_path, monkeypatch):
    """Test 8: Same artifact observed multiple times in one turn -> uploaded exactly once."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()

    artifacts_dir = tmp_path / "Artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "dup.py").write_text("print('dedup')")

    turns = [
        AssistantTurn(
            tool_calls=[
                ToolCall(id="t1", name="grep", arguments={"pattern": "dedup", "path": "Artifacts/dup.py"}),
                ToolCall(id="t2", name="grep", arguments={"pattern": "dedup", "path": "Artifacts/dup.py"}),
            ],
            text="Created [dup.py](artifact:Artifacts/dup.py)",
            finish_reason="stop",
        )
    ]
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider(turns))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    await bridge.handle_inbound(_tg_event("run dedup test", chat_id="12345", user_id="u1"))
    task = bridge._active_tasks.get("12345")
    if task:
        await task

    assert len(fake_client.sent_documents) == 1
    assert fake_client.sent_documents[0]["filename"] == "dup.py"


@pytest.mark.asyncio
async def test_telegram_artifact_previous_turn_not_resent(tmp_path, monkeypatch):
    """Test 9: Artifact from previous turn is NOT re-sent on a later unrelated turn."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()

    artifacts_dir = tmp_path / "Artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "old_turn.py").write_text("# turn 1 file")

    turns_1 = [AssistantTurn(text="Turn 1: [old_turn.py](artifact:Artifacts/old_turn.py)", finish_reason="stop")]
    provider = ScriptedTurnProvider(turns_1)
    mgr = SessionManager(workspace=tmp_path, provider=provider)
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    await bridge.handle_inbound(_tg_event("start turn 1", chat_id="12345", user_id="u1"))
    task1 = bridge._active_tasks.get("12345")
    if task1:
        await task1

    assert len(fake_client.sent_documents) == 1
    assert fake_client.sent_documents[0]["filename"] == "old_turn.py"

    # Turn 2: unrelated conversation
    provider.turns = [AssistantTurn(text="Turn 2: just text answer.", finish_reason="stop")]
    await bridge.handle_inbound(_tg_event("start turn 2", chat_id="12345", user_id="u1"))
    task2 = bridge._active_tasks.get("12345")
    if task2:
        await task2

    assert len(fake_client.sent_documents) == 1


@pytest.mark.asyncio
async def test_telegram_artifact_modified_file_uploaded_new_version(tmp_path, monkeypatch):
    """Test 10: Modified existing artifact is uploaded as a new version."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()

    artifacts_dir = tmp_path / "Artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    code_file = artifacts_dir / "versioned.py"
    code_file.write_text("# version 1")

    turns_1 = [AssistantTurn(text="V1: [versioned.py](artifact:Artifacts/versioned.py)", finish_reason="stop")]
    provider = ScriptedTurnProvider(turns_1)
    mgr = SessionManager(workspace=tmp_path, provider=provider)
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    await bridge.handle_inbound(_tg_event("v1 task", chat_id="12345", user_id="u1"))
    task1 = bridge._active_tasks.get("12345")
    if task1:
        await task1

    assert len(fake_client.sent_documents) == 1
    assert fake_client.sent_documents[0]["document"] == b"# version 1"

    # Turn 2: modifies versioned.py
    await asyncio.sleep(0.01)
    code_file.write_text("# version 2 - modified content")

    provider.turns = [AssistantTurn(text="V2: [versioned.py](artifact:Artifacts/versioned.py)", finish_reason="stop")]
    await bridge.handle_inbound(_tg_event("v2 task", chat_id="12345", user_id="u1"))
    task2 = bridge._active_tasks.get("12345")
    if task2:
        await task2

    assert len(fake_client.sent_documents) == 2
    assert fake_client.sent_documents[1]["document"] == b"# version 2 - modified content"


@pytest.mark.asyncio
async def test_telegram_artifact_upload_failure_handling(tmp_path, monkeypatch):
    """Test 11: Upload failure does not crash task and sends a user warning."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient(document_fails=True)

    artifacts_dir = tmp_path / "Artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "bubble_sort.c").write_text("int main() {}")

    turns = [
        AssistantTurn(
            text="Created [bubble_sort.c](artifact:Artifacts/bubble_sort.c)",
            finish_reason="stop",
        )
    ]
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider(turns))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    await bridge.handle_inbound(_tg_event("create bubble sort", chat_id="12345", user_id="u1"))
    task = bridge._active_tasks.get("12345")
    if task:
        await task

    assert bridge.store.get("12345").status == "IDLE"
    assert len(fake_client.sent_documents) == 0
    assert any("upload failed" in m["text"] and "bubble_sort.c" in m["text"] for m in fake_client.sent_messages)
    assert len(bridge._delivered_artifacts.get("12345", set())) == 0


# -- Explicit File-Send Intent Tests ("Send Me The File") -----------------------

@pytest.mark.asyncio
async def test_explicit_send_most_recent_artifact(tmp_path, monkeypatch):
    """Test 1: Turn 1 creates file, Turn 2 user says 'Send me the file' -> uploaded to current chat."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "5506865927")
    fake_client = FakeTelegramClient()

    artifacts_dir = tmp_path / "Artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    c_file = artifacts_dir / "bubble_sort.c"
    c_file.write_text("void bubble_sort(int arr[], int n) { /* c code */ }")

    # Turn 1: user asked to create file
    turns_1 = [AssistantTurn(text="Created Artifacts/bubble_sort.c", finish_reason="stop")]
    provider = ScriptedTurnProvider(turns_1)
    mgr = SessionManager(workspace=tmp_path, provider=provider)
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    await bridge.handle_inbound(
        _tg_event("Create a c language file with the bubble sort code", chat_id="5506865927", user_id="5506865927")
    )
    task1 = bridge._active_tasks.get("5506865927")
    if task1:
        await task1

    # Turn 2: user says "Send me the file"
    await bridge.handle_inbound(
        _tg_event("Send me the file", chat_id="5506865927", user_id="5506865927")
    )

    # Document was sent directly to 5506865927
    assert len(fake_client.sent_documents) >= 1
    doc = fake_client.sent_documents[-1]
    assert doc["chat_id"] == "5506865927"
    assert doc["filename"] == "bubble_sort.c"
    assert b"void bubble_sort" in doc["document"]
    # Confirmation message was sent
    assert any("📎 bubble_sort.c sent." in m["text"] for m in fake_client.sent_messages)
    # Never asked for telegram ID
    assert not any("telegram id" in m["text"].lower() for m in fake_client.sent_messages)


@pytest.mark.asyncio
async def test_explicit_send_filename(tmp_path, monkeypatch):
    """Test 2: User says 'send bubble_sort.c' -> correct artifact resolved and uploaded."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()

    artifacts_dir = tmp_path / "Artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    c_file = artifacts_dir / "bubble_sort.c"
    c_file.write_text("void bubble_sort() {}")

    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    # Create session first
    mgr.session_store.create_telegram_session(chat_id="12345", user_name="u1", workspace=str(tmp_path))

    await bridge.handle_inbound(_tg_event("send bubble_sort.c", chat_id="12345", user_id="u1"))

    assert len(fake_client.sent_documents) == 1
    assert fake_client.sent_documents[0]["filename"] == "bubble_sort.c"
    assert any("📎 bubble_sort.c sent." in m["text"] for m in fake_client.sent_messages)


@pytest.mark.asyncio
async def test_explicit_send_artifact_path(tmp_path, monkeypatch):
    """Test 3: User says 'send Artifacts/bubble_sort.c' -> correct artifact resolved and uploaded."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()

    artifacts_dir = tmp_path / "Artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "bubble_sort.c").write_text("void bubble_sort() {}")

    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    mgr.session_store.create_telegram_session(chat_id="12345", user_name="u1", workspace=str(tmp_path))

    await bridge.handle_inbound(_tg_event("send Artifacts/bubble_sort.c", chat_id="12345", user_id="u1"))

    assert len(fake_client.sent_documents) == 1
    assert fake_client.sent_documents[0]["filename"] == "bubble_sort.c"
    assert any("📎 bubble_sort.c sent." in m["text"] for m in fake_client.sent_messages)


@pytest.mark.asyncio
async def test_explicit_send_no_telegram_id_requested(tmp_path, monkeypatch):
    """Test 4: Verify that the bridge never asks for a Telegram ID or destination."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()

    artifacts_dir = tmp_path / "Artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "my_script.py").write_text("print('test')")

    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    mgr.session_store.create_telegram_session(chat_id="9999", user_name="u1", workspace=str(tmp_path))

    await bridge.handle_inbound(_tg_event("send me the file", chat_id="9999", user_id="u1"))

    # Assert no prompt asking for ID/chat/channel
    for msg in fake_client.sent_messages:
        text_lower = msg["text"].lower()
        assert "what is your telegram id" not in text_lower
        assert "telegram id" not in text_lower
        assert "which chat" not in text_lower
        assert "which telegram" not in text_lower
        assert "slack" not in text_lower


@pytest.mark.asyncio
async def test_explicit_send_multiple_artifacts_ambiguous(tmp_path, monkeypatch):
    """Test 5: Multiple files with same timestamp -> asks which filename, never asks destination."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()

    artifacts_dir = tmp_path / "Artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    t = time.time()
    for name in ("file1.py", "file2.json", "report.pdf"):
        f = artifacts_dir / name
        f.write_text("content")
        os.utime(f, (t, t))

    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    mgr.session_store.create_telegram_session(chat_id="12345", user_name="u1", workspace=str(tmp_path))

    await bridge.handle_inbound(_tg_event("send me the file", chat_id="12345", user_id="u1"))

    assert len(fake_client.sent_documents) == 0
    assert any("I found multiple files:" in m["text"] and "Which one should I send?" in m["text"] for m in fake_client.sent_messages)
    # Never asks for a destination
    assert not any("telegram id" in m["text"].lower() for m in fake_client.sent_messages)


@pytest.mark.asyncio
async def test_explicit_send_chat_isolation(tmp_path, monkeypatch):
    """Test 6: Chat A's file cannot be retrieved or sent to Chat B."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1,u2")
    fake_client = FakeTelegramClient()

    ws_a = tmp_path / "ws_a"
    (ws_a / "Artifacts").mkdir(parents=True, exist_ok=True)
    (ws_a / "Artifacts" / "secret_a.py").write_text("# chat a secret")

    ws_b = tmp_path / "ws_b"
    ws_b.mkdir(parents=True, exist_ok=True)

    mgr = SessionManager(workspace=ws_a, provider=ScriptedTurnProvider([]))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    # Setup separate sessions
    mgr.session_store.create_telegram_session(chat_id="111", user_name="u1", workspace=str(ws_a))
    mgr.session_store.create_telegram_session(chat_id="222", user_name="u2", workspace=str(ws_b))

    # Chat B tries to request secret_a.py
    await bridge.handle_inbound(_tg_event("send secret_a.py", chat_id="222", user_id="u2"))

    # Chat B gets not found
    assert len(fake_client.sent_documents) == 0
    chat_b_messages = [m for m in fake_client.sent_messages if m["chat_id"] == "222"]
    assert any("couldn't find that file" in m["text"].lower() for m in chat_b_messages)


@pytest.mark.asyncio
async def test_explicit_send_missing_artifact(tmp_path, monkeypatch):
    """Test 7: Missing artifact requested -> safe message, no crash, no upload."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()

    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    mgr.session_store.create_telegram_session(chat_id="12345", user_name="u1", workspace=str(tmp_path))

    await bridge.handle_inbound(_tg_event("send nonexistent_file.py", chat_id="12345", user_id="u1"))

    assert len(fake_client.sent_documents) == 0
    assert any("couldn't find that file" in m["text"].lower() for m in fake_client.sent_messages)


@pytest.mark.asyncio
async def test_explicit_send_path_traversal(tmp_path, monkeypatch):
    """Test 8: Path traversal in explicit send request is rejected."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()

    # Secret outside workspace
    (tmp_path.parent / "secret_pass.txt").write_text("password123")

    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    mgr.session_store.create_telegram_session(chat_id="12345", user_name="u1", workspace=str(tmp_path))

    await bridge.handle_inbound(_tg_event("send ../../secret_pass.txt", chat_id="12345", user_id="u1"))

    assert len(fake_client.sent_documents) == 0
    assert any("Path escapes session workspace" in m["text"] or "couldn't find" in m["text"].lower() for m in fake_client.sent_messages)


@pytest.mark.asyncio
async def test_explicit_send_upload_failure_message(tmp_path, monkeypatch):
    """Test 9: Explicit send upload failure -> safe error message sent to Telegram."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient(document_fails=True)

    artifacts_dir = tmp_path / "Artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "bubble_sort.c").write_text("int main() {}")

    mgr = SessionManager(workspace=tmp_path, provider=ScriptedTurnProvider([]))
    bridge = TelegramAgentBridge(mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client)
    mgr.telegram_bridge = bridge

    mgr.session_store.create_telegram_session(chat_id="12345", user_name="u1", workspace=str(tmp_path))

    await bridge.handle_inbound(_tg_event("send bubble_sort.c", chat_id="12345", user_id="u1"))

    assert len(fake_client.sent_documents) == 0
    assert any("upload failed" in m["text"] and "bubble_sort.c" in m["text"] for m in fake_client.sent_messages)


# -- P0 / P1 Telegram Reliability Tests -----------------------------------------

def test_telegram_client_429_retry_success(monkeypatch):
    """P1: TelegramClient handles HTTP 429 with retry_after and succeeds on next attempt."""
    import httpx

    calls = {"count": 0}

    def fake_post(url, json=None, data=None, files=None, timeout=None):
        calls["count"] += 1
        if calls["count"] == 1:
            class RateLimitResp:
                status_code = 429

                def json(self):
                    return {
                        "ok": False,
                        "error_code": 429,
                        "description": "Too Many Requests: retry after 0",
                        "parameters": {"retry_after": 0},
                    }

            return RateLimitResp()

        class SuccessResp:
            status_code = 200

            def json(self):
                return {"ok": True, "result": {"message_id": 42901}}

        return SuccessResp()

    monkeypatch.setattr(httpx, "post", fake_post)

    client = TelegramClient("token-123")
    res = client.send_message("12345", "hello after rate limit")

    assert res.ok is True
    assert res.message_id == "42901"
    assert calls["count"] == 2


def test_telegram_client_429_max_retries_exhausted(monkeypatch):
    """P1: TelegramClient stops retrying after exhausting retry budget."""
    import httpx

    calls = {"count": 0}

    def fake_post(url, json=None, data=None, files=None, timeout=None):
        calls["count"] += 1

        class RateLimitResp:
            status_code = 429

            def json(self):
                return {
                    "ok": False,
                    "error_code": 429,
                    "description": "Too Many Requests: retry after 0",
                    "parameters": {"retry_after": 0},
                }

        return RateLimitResp()

    monkeypatch.setattr(httpx, "post", fake_post)

    client = TelegramClient("token-123")
    res = client.send_message("12345", "hello stuck in rate limit")

    assert res.ok is False
    assert "Too Many Requests" in res.error
    assert calls["count"] == 4  # 1 initial attempt + 3 retries


@pytest.mark.asyncio
async def test_telegram_tool_send_file_current_chat(tmp_path, monkeypatch):
    """P0: Agent calls send_file tool without explicit target -> uploaded to current Telegram chat."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1")
    fake_client = FakeTelegramClient()

    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "bubble_sort.c").write_text("void bubble_sort() {}")

    # Turn 1: Model invokes send_file with path ONLY (no target specified)
    turns = [
        AssistantTurn(
            text="Sending file...",
            tool_calls=[
                ToolCall(
                    id="call_01",
                    name="send_file",
                    arguments={"path": "bubble_sort.c"},
                )
            ],
        ),
        AssistantTurn(text="File has been uploaded.", finish_reason="stop"),
    ]
    provider = ScriptedTurnProvider(turns)
    mgr = SessionManager(workspace=ws, provider=provider)
    mgr.secrets.put("telegram:default", {"bot_token": "tg-token", "enabled": True})
    bridge = TelegramAgentBridge(
        mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client
    )
    mgr.telegram_bridge = bridge

    # Create session for chat 88888 and pre-grant send_file
    rec = mgr.session_store.create_telegram_session(
        chat_id="88888", user_name="u1", workspace=str(ws)
    )
    rec.grants = {"tools": ["send_file"]}
    mgr.session_store.save(rec)

    await bridge.handle_inbound(
        _tg_event("upload my code", chat_id="88888", user_id="u1")
    )
    task = bridge._active_tasks.get("88888")
    if task:
        await task

    # Document was sent directly to chat 88888
    assert len(fake_client.sent_documents) == 1
    doc = fake_client.sent_documents[0]
    assert doc["chat_id"] == "88888"
    assert doc["filename"] == "bubble_sort.c"
    assert b"void bubble_sort" in doc["document"]


@pytest.mark.asyncio
async def test_telegram_tool_send_file_chat_isolation(tmp_path, monkeypatch):
    """P0: Chat A tool invocation delivers to Chat A, never Chat B."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "u1,u2")
    fake_client = FakeTelegramClient()

    ws_a = tmp_path / "ws_a"
    ws_a.mkdir(parents=True, exist_ok=True)
    (ws_a / "secret_a.txt").write_text("chat A secret data")

    ws_b = tmp_path / "ws_b"
    ws_b.mkdir(parents=True, exist_ok=True)
    (ws_b / "secret_b.txt").write_text("chat B secret data")

    turns_a = [
        AssistantTurn(
            text="Sending A...",
            tool_calls=[
                ToolCall(
                    id="call_a",
                    name="send_file",
                    arguments={"path": "secret_a.txt"},
                )
            ],
        ),
        AssistantTurn(text="A done.", finish_reason="stop"),
    ]
    mgr = SessionManager(workspace=ws_a, provider=ScriptedTurnProvider(turns_a))
    mgr.secrets.put("telegram:default", {"bot_token": "tg-token", "enabled": True})
    bridge = TelegramAgentBridge(
        mgr, tmp_path / "cogniwork.db", client_factory=lambda tok: fake_client
    )
    mgr.telegram_bridge = bridge

    rec_a = mgr.session_store.create_telegram_session(
        chat_id="1111", user_name="u1", workspace=str(ws_a)
    )
    rec_a.grants = {"tools": ["send_file"]}
    mgr.session_store.save(rec_a)

    mgr.session_store.create_telegram_session(
        chat_id="2222", user_name="u2", workspace=str(ws_b)
    )

    # Chat A runs turn
    await bridge.handle_inbound(
        _tg_event("deliver my secret file", chat_id="1111", user_id="u1")
    )
    task_a = bridge._active_tasks.get("1111")
    if task_a:
        await task_a

    # Only chat 1111 got document
    assert len(fake_client.sent_documents) == 1
    assert fake_client.sent_documents[0]["chat_id"] == "1111"
    assert fake_client.sent_documents[0]["filename"] == "secret_a.txt"
    assert not any(d["chat_id"] == "2222" for d in fake_client.sent_documents)







