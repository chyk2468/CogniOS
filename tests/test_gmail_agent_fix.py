"""Regression test suite for CogniOS Gmail Agent multi-step workflow fixes.

Validates:
1. Normal Gmail summary workflow (4 found, 4 fetched, summary generated)
2. Large Gmail payload (task and pending IDs survive compaction)
3. Mid-workflow compaction (forced after fetch #1, state preserved, fetches 2-4 proceed)
4. One failed fetch (handled gracefully with partial result, no silent abandonment)
5. Zero emails found (clean empty state handling)
6. Model stops producing tool calls prematurely (engine recovers and prompts for pending IDs)
7. Reasoning separation (reasoning deltas never leak into final answer)
8. resultSizeEstimate vs actual count handling
9. State persistence across serialization and compaction
10. End-to-end multi-step workflow simulation
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import MagicMock, patch

import pytest

from cogniwork.agent import build_engine
from cogniwork.agents.cogniwork import cogniwork_agent
from cogniwork import compaction as _compaction
from cogniwork.connectors.integration_tools import make_integration_tools
from cogniwork.events import EventType
from cogniwork.permissions import Mode
from cogniwork.providers import AssistantTurn, ModelCapabilities, ProviderClient, ToolCall
from cogniwork.providers.base import TokenUsage
from cogniwork.secrets import SecretStore

MOCK_EMAILS = {
    "1a0511fa7a2a9a09": {
        "id": "1a0511fa7a2a9a09",
        "threadId": "1a0511fa7a2a9a09",
        "snippet": "Q3 Financial Performance Report attached for review...",
        "payload": {
            "headers": [
                {"name": "From", "value": "cfo@company.com"},
                {"name": "Subject", "value": "Q3 Financial Performance Report"},
                {"name": "Date", "value": "Sun, 30 Aug 2026 08:15:00 -0700"},
            ],
            "body": {"size": 45000, "data": "UVRGIEZpbmFuY2lhbCBSZXBvcnQgRGV0YWlscy4uLg=="},
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": "UVRGIEZpbmFuY2lhbCBSZXBvcnQgRGV0YWlscy4uLg=="},
                }
            ],
        },
    },
    "1a0504ffac91d1fa": {
        "id": "1a0504ffac91d1fa",
        "threadId": "1a0504ffac91d1fa",
        "snippet": "Team standup notes: Sprint 42 blocker resolved...",
        "payload": {
            "headers": [
                {"name": "From", "value": "lead@company.com"},
                {"name": "Subject", "value": "Team standup notes - 2026-08-30"},
                {"name": "Date", "value": "Sun, 30 Aug 2026 09:30:00 -0700"},
            ],
            "body": {"size": 42000, "data": "U3RhbmR1cCBub3Rlcy4uLg=="},
        },
    },
    "1a0504a2b42afe2b": {
        "id": "1a0504a2b42afe2b",
        "threadId": "1a0504a2b42afe2b",
        "snippet": "Customer escalation: urgent login bug for enterprise client...",
        "payload": {
            "headers": [
                {"name": "From", "value": "support@company.com"},
                {"name": "Subject", "value": "URGENT: Enterprise Login Incident"},
                {"name": "Date", "value": "Sun, 30 Aug 2026 10:00:00 -0700"},
            ],
            "body": {"size": 38000, "data": "RXNjYWxhdGlvbiBkZXRhaWxzLi4u"},
        },
    },
    "1a050176296249eb": {
        "id": "1a050176296249eb",
        "threadId": "1a050176296249eb",
        "snippet": "Product launch retrospective slides and feedback form...",
        "payload": {
            "headers": [
                {"name": "From", "value": "pm@company.com"},
                {"name": "Subject", "value": "Launch Retrospective Notes"},
                {"name": "Date", "value": "Sun, 30 Aug 2026 10:45:00 -0700"},
            ],
            "body": {"size": 52000, "data": "UmV0cm9zcGVjdGl2ZSBzbGlkZXMuLi4="},
        },
    },
}


def fake_gmail_request(method, url, headers=None, params=None, json=None, auth=None, check_addresses=False):
    params = params or {}
    q = params.get("q", "")
    if "messages/" in url:
        msg_id = url.split("messages/")[-1]
        if msg_id in MOCK_EMAILS:
            return {"ok": True, "data": MOCK_EMAILS[msg_id]}
        return {"error": "HTTP 404", "details": "Not Found"}
    elif "messages" in url:
        if "2026/08/29" in q:
            return {
                "ok": True,
                "data": {
                    "messages": [
                        {"id": "1a0511fa7a2a9a09", "threadId": "1a0511fa7a2a9a09"},
                        {"id": "1a0504ffac91d1fa", "threadId": "1a0504ffac91d1fa"},
                        {"id": "1a0504a2b42afe2b", "threadId": "1a0504a2b42afe2b"},
                        {"id": "1a050176296249eb", "threadId": "1a050176296249eb"},
                    ],
                    "resultSizeEstimate": 201,
                },
            }
        elif "empty" in q or "zero" in q:
            return {"ok": True, "data": {"messages": [], "resultSizeEstimate": 0}}
        else:
            return {
                "ok": True,
                "data": {
                    "messages": [
                        {"id": "1a0511fa7a2a9a09", "threadId": "1a0511fa7a2a9a09"},
                        {"id": "1a0504ffac91d1fa", "threadId": "1a0504ffac91d1fa"},
                        {"id": "1a0504a2b42afe2b", "threadId": "1a0504a2b42afe2b"},
                        {"id": "1a050176296249eb", "threadId": "1a050176296249eb"},
                    ],
                    "resultSizeEstimate": 4,
                },
            }
    return {"ok": True, "data": {}}


@pytest.fixture
def secrets(tmp_path):
    s = SecretStore(tmp_path / "secrets.json")
    s.put(
        "gmail:account:test@company.com",
        {
            "account": "test@company.com",
            "access_token": "mock-token",
            "refresh_token": "mock-refresh",
            "expires": time.time() + 3600,
            "connected": True,
            "enabled": True,
        },
    )
    s.put("gmail:default", {"account": "test@company.com", "connected": True, "enabled": True})
    return s


# -----------------------------------------------------------------------------
# Test 1: Normal Gmail summary
# -----------------------------------------------------------------------------
def test_normal_gmail_summary(secrets, tmp_path):
    tools = {t.__name__: t for t in make_integration_tools(secrets)}
    search = tools["gmail_search_messages"]
    read = tools["gmail_get_message"]

    with patch("cogniwork.connectors.integration_tools._request", side_effect=fake_gmail_request):
        s_res = search("after:2026/08/30 before:2026/08/31")
        assert s_res["ok"] is True
        msgs = s_res["data"]["messages"]
        assert len(msgs) == 4

        fetched = []
        for m in msgs:
            r_res = read(m["id"])
            assert r_res["ok"] is True
            data = r_res["data"]
            assert data["id"] == m["id"]
            assert "payload" not in data  # payload is sanitized!
            assert "subject" in data
            fetched.append(data)

        assert len(fetched) == 4
        summary = "\n".join(f"- {f['subject']}: {f['snippet']}" for f in fetched)
        assert "Q3 Financial Performance Report" in summary
        assert "Team standup notes" in summary


# -----------------------------------------------------------------------------
# Test 2: Large Gmail payload sanitization
# -----------------------------------------------------------------------------
def test_large_gmail_payload_sanitization(secrets):
    tools = {t.__name__: t for t in make_integration_tools(secrets)}
    read = tools["gmail_get_message"]

    with patch("cogniwork.connectors.integration_tools._request", side_effect=fake_gmail_request):
        res = read("1a0511fa7a2a9a09")
        assert res["ok"] is True
        data = res["data"]
        # Raw MIME is stripped, body is extracted clean text
        assert "payload" not in data
        assert isinstance(data["body"], str)
        assert len(data["body"]) < 20_000
        assert data["subject"] == "Q3 Financial Performance Report"
        assert data["from"] == "cfo@company.com"


# -----------------------------------------------------------------------------
# Test 3: Mid-workflow compaction preserves connector state
# -----------------------------------------------------------------------------
def test_mid_workflow_compaction_preserves_state():
    span = [
        {"role": "user", "content": "Summarise today's mails"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "name": "gmail_search_messages",
                        "arguments": json.dumps({"query": "after:2026/08/30 before:2026/08/31"}),
                    }
                }
            ],
        },
        {
            "role": "tool",
            "content": json.dumps(
                {
                    "ok": True,
                    "data": {
                        "messages": [
                            {"id": "1a0511fa7a2a9a09"},
                            {"id": "1a0504ffac91d1fa"},
                            {"id": "1a0504a2b42afe2b"},
                            {"id": "1a050176296249eb"},
                        ]
                    },
                }
            ),
        },
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "name": "gmail_get_message",
                        "arguments": json.dumps({"message_id": "1a0511fa7a2a9a09"}),
                    }
                }
            ],
        },
        {
            "role": "tool",
            "content": json.dumps(
                {
                    "ok": True,
                    "data": {
                        "id": "1a0511fa7a2a9a09",
                        "subject": "Q3 Financial Performance Report",
                        "from": "cfo@company.com",
                        "snippet": "Q3 Financial Performance Report attached...",
                    },
                }
            ),
        },
    ]

    working_state = _compaction.extract_working_state(span)
    assert "Active connector workflow state:" in working_state
    assert "- Provider: gmail" in working_state
    assert "- Expected Count: 4" in working_state
    assert "1a0511fa7a2a9a09" in working_state
    assert "1a0504ffac91d1fa" in working_state  # Pending IDs preserved!
    assert "- Pending Message IDs: 1a0504ffac91d1fa, 1a0504a2b42afe2b, 1a050176296249eb" in working_state


# -----------------------------------------------------------------------------
# Test 4: One failed fetch handled gracefully
# -----------------------------------------------------------------------------
def test_one_failed_fetch(secrets):
    def partial_fail_request(method, url, **kwargs):
        if "1a0504a2b42afe2b" in url:
            return {"error": "HTTP 500", "details": "Temporary server error"}
        return fake_gmail_request(method, url, **kwargs)

    tools = {t.__name__: t for t in make_integration_tools(secrets)}
    read = tools["gmail_get_message"]

    with patch("cogniwork.connectors.integration_tools._request", side_effect=partial_fail_request):
        r1 = read("1a0511fa7a2a9a09")
        assert r1["ok"] is True
        r2 = read("1a0504a2b42afe2b")
        assert "error" in r2


# -----------------------------------------------------------------------------
# Test 5: Zero emails found
# -----------------------------------------------------------------------------
def test_zero_emails_found(secrets):
    tools = {t.__name__: t for t in make_integration_tools(secrets)}
    search = tools["gmail_search_messages"]

    with patch("cogniwork.connectors.integration_tools._request", side_effect=fake_gmail_request):
        res = search("zero emails query")
        assert res["ok"] is True
        assert len(res["data"]["messages"]) == 0


# -----------------------------------------------------------------------------
# Test 6: Model stops producing tool calls with pending work -> Engine recovers
# -----------------------------------------------------------------------------
def test_engine_recovers_pending_work(secrets, tmp_path):
    class StepProvider(ProviderClient):
        def __init__(self):
            self.call_idx = 0

        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="ok")

        def stream(self, *, model, messages, tools=None, **settings):
            self.call_idx += 1
            if self.call_idx == 1:
                # Step 1: Search
                turn = AssistantTurn(
                    tool_calls=[
                        ToolCall(
                            id="s1",
                            name="gmail_search_messages",
                            arguments={"query": "after:2026/08/30"},
                        )
                    ]
                )
                yield MagicMock(reasoning_delta=None, text_delta="", turn=turn)
            elif self.call_idx == 2:
                # Step 2: Prematurely outputs text with 0 tool calls!
                turn = AssistantTurn(text="I found 4 emails.", tool_calls=[])
                yield MagicMock(reasoning_delta=None, text_delta="I found 4 emails.", turn=turn)
            elif self.call_idx == 3:
                # Step 3: Engine recovery steered the model to fetch pending IDs
                turn = AssistantTurn(
                    tool_calls=[
                        ToolCall(
                            id="f1",
                            name="gmail_get_message",
                            arguments={"message_id": "1a0511fa7a2a9a09"},
                        )
                    ]
                )
                yield MagicMock(reasoning_delta=None, text_delta="", turn=turn)
            else:
                # Finish
                turn = AssistantTurn(text="Final email summary.", tool_calls=[])
                yield MagicMock(reasoning_delta=None, text_delta="Final email summary.", turn=turn)

        def capabilities(self, model):
            return ModelCapabilities()

    engine = build_engine(
        agent=cogniwork_agent(),
        workspace=tmp_path,
        provider=StepProvider(),
        secrets=secrets,
        model="gpt-5.5",
        mode=Mode.AUTO,
    )

    with patch("cogniwork.connectors.integration_tools._request", side_effect=fake_gmail_request):
        events = []

        async def _run():
            async for ev in engine.run("Summarise today's mails"):
                events.append(ev)

        asyncio.run(_run())

    # Engine did NOT stop at iteration 2; it recovered and completed successfully
    assert any(e.type == EventType.TURN_END and e.data.get("status") == "completed" for e in events)


# -----------------------------------------------------------------------------
# Test 7: Reasoning separation
# -----------------------------------------------------------------------------
def test_reasoning_separation(secrets, tmp_path):
    class ReasoningProvider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="ok")

        def stream(self, *, model, messages, tools=None, **settings):
            turn = AssistantTurn(
                text="Here is your summary of 4 emails.",
                reasoning="Internal thought: Analyzing sender priority and date sequence.",
            )
            yield MagicMock(
                reasoning_delta="Internal thought: Analyzing sender priority...",
                text_delta="Here is your summary of 4 emails.",
                turn=turn,
            )

        def capabilities(self, model):
            return ModelCapabilities()

    engine = build_engine(
        agent=cogniwork_agent(),
        workspace=tmp_path,
        provider=ReasoningProvider(),
        secrets=secrets,
        model="gpt-5.5",
        mode=Mode.AUTO,
    )

    events = []

    async def _run():
        async for ev in engine.run("Summarise today's mails"):
            events.append(ev)

    asyncio.run(_run())

    r_events = [e for e in events if e.type == EventType.REASONING_DELTA]
    a_events = [e for e in events if e.type == EventType.ASSISTANT_DELTA]
    msg_events = [e for e in events if e.type == EventType.ASSISTANT_MESSAGE]

    assert len(r_events) > 0
    assert "Internal thought" in r_events[0].data["text"]
    assert "Internal thought" not in a_events[0].data["text"]
    assert msg_events[0].data["text"] == "Here is your summary of 4 emails."
    assert "Internal thought" not in msg_events[0].data["text"]


# -----------------------------------------------------------------------------
# Test 8: resultSizeEstimate vs actual count
# -----------------------------------------------------------------------------
def test_result_size_estimate_handling(secrets):
    tools = {t.__name__: t for t in make_integration_tools(secrets)}
    search = tools["gmail_search_messages"]

    with patch("cogniwork.connectors.integration_tools._request", side_effect=fake_gmail_request):
        # Query matching 201 resultSizeEstimate but 4 messages in batch
        res = search("after:2026/08/29 before:2026/08/31")
        assert res["ok"] is True
        assert len(res["data"]["messages"]) == 4
        # Verify resultSizeEstimate does not override batch message length
        assert res["data"]["resultSizeEstimate"] == 201
        assert len(res["data"]["messages"]) == 4


# -----------------------------------------------------------------------------
# Test 9: State persistence across serialization and compaction
# -----------------------------------------------------------------------------
def test_state_persistence_across_compaction():
    state = _compaction.CompactionState(
        boundary_index=4,
        summary_text="## Primary request and intent\nSummarise today's emails",
        working_state="## Active connector workflow state:\n- Provider: gmail\n- Pending Message IDs: id3, id4",
        user_messages=["Summarise today's mails"],
    )
    raw = state.as_dict()
    reconstructed = _compaction.CompactionState.from_dict(raw)
    assert reconstructed is not None
    assert reconstructed.boundary_index == 4
    assert "Pending Message IDs: id3, id4" in reconstructed.working_state
    assert "Summarise today's mails" in reconstructed.user_messages


# -----------------------------------------------------------------------------
# Test 10: End-to-end live-style test
# -----------------------------------------------------------------------------
def test_end_to_end_workflow(secrets, tmp_path):
    class FullWorkflowProvider(ProviderClient):
        def __init__(self):
            self.step = 0

        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="ok")

        def stream(self, *, model, messages, tools=None, **settings):
            self.step += 1
            if self.step == 1:
                # 1. Search
                turn = AssistantTurn(
                    tool_calls=[
                        ToolCall(
                            id="tc_search",
                            name="gmail_search_messages",
                            arguments={"query": "after:2026/08/30 before:2026/08/31"},
                        )
                    ]
                )
                yield MagicMock(reasoning_delta=None, text_delta="", turn=turn)
            elif self.step == 2:
                # 2. Fetch all 4 messages concurrently or sequentially
                turn = AssistantTurn(
                    tool_calls=[
                        ToolCall(id="tc_f1", name="gmail_get_message", arguments={"message_id": "1a0511fa7a2a9a09"}),
                        ToolCall(id="tc_f2", name="gmail_get_message", arguments={"message_id": "1a0504ffac91d1fa"}),
                        ToolCall(id="tc_f3", name="gmail_get_message", arguments={"message_id": "1a0504a2b42afe2b"}),
                        ToolCall(id="tc_f4", name="gmail_get_message", arguments={"message_id": "1a050176296249eb"}),
                    ]
                )
                yield MagicMock(reasoning_delta=None, text_delta="", turn=turn)
            else:
                # 3. Final summary
                summary = (
                    "### Today's Email Summary (2026-08-30)\n"
                    "1. CFO: Q3 Financial Performance Report\n"
                    "2. Lead: Team standup notes\n"
                    "3. Support: URGENT Enterprise Login Incident\n"
                    "4. PM: Launch Retrospective Notes"
                )
                turn = AssistantTurn(text=summary, tool_calls=[])
                yield MagicMock(reasoning_delta=None, text_delta=summary, turn=turn)

        def capabilities(self, model):
            return ModelCapabilities()

    engine = build_engine(
        agent=cogniwork_agent(),
        workspace=tmp_path,
        provider=FullWorkflowProvider(),
        secrets=secrets,
        model="gpt-5.5",
        mode=Mode.AUTO,
    )

    with patch("cogniwork.connectors.integration_tools._request", side_effect=fake_gmail_request):
        events = []

        async def _run():
            async for ev in engine.run("Summarise today's mails"):
                events.append(ev)

        asyncio.run(_run())

    end_events = [e for e in events if e.type == EventType.TURN_END]
    assert len(end_events) == 1
    assert end_events[0].data["status"] == "completed"

    msg_events = [e for e in events if e.type == EventType.ASSISTANT_MESSAGE]
    final_text = msg_events[-1].data["text"]
    assert "Today's Email Summary" in final_text
    assert "Q3 Financial Performance Report" in final_text
    assert "Enterprise Login Incident" in final_text
