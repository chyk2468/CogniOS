"""Tests for the messaging connector core (C2 increment 1): targets, the send_message
tool, settings/authorization, and the gateway inbound loop — all offline via FakeAdapter.
"""

from __future__ import annotations

import pytest

from cogniwork.connectors import (
    ConnectorSettings,
    FakeAdapter,
    Gateway,
    MessageEvent,
    SessionSource,
    format_target,
    is_authorized,
    make_send_message_tool,
    parse_target,
)
from cogniwork.connectors.base import SendResult
from cogniwork.secrets import SecretStore


# -- target tokens -------------------------------------------------------------
def test_target_round_trip():
    assert format_target("telegram", "12345") == "telegram:12345"
    assert format_target("slack", "C1", "168.9") == "slack:C1:168.9"
    assert parse_target("telegram:12345") == ("telegram", "12345", None)
    assert parse_target("slack:C1:168.9") == ("slack", "C1", "168.9")


def test_target_invalid():
    for bad in ("", "telegram", "telegram:", ":123"):
        with pytest.raises(ValueError):
            parse_target(bad)


def test_session_source_target_and_label():
    s = SessionSource(
        platform="telegram", chat_id="42", user_name="Alice", chat_type="dm"
    )
    assert s.target == "telegram:42"
    assert "Alice" in s.label() and "telegram" in s.label()


def test_message_tagged_text_carries_reply_handle():
    s = SessionSource(
        platform="slack", chat_id="C9", user_name="Bob", chat_type="channel"
    )
    ev = MessageEvent(text="ship it", source=s)
    tag = ev.tagged_text()
    assert "reply→slack:C9" in tag and "ship it" in tag


# -- send_message tool ---------------------------------------------------------
def _fake_senders(record):
    def sender(token, chat_id, text, thread_id=None):
        record.append(
            {"token": token, "chat_id": chat_id, "text": text, "thread_id": thread_id}
        )
        return SendResult(True, message_id="99")

    return {"telegram": sender, "slack": sender}


def test_send_message_success(tmp_path):
    secrets = SecretStore(tmp_path / "secrets.json")
    secrets.put("telegram:default", {"type": "token", "bot_token": "T0K"})
    record = []
    tool = make_send_message_tool(secrets, senders=_fake_senders(record))

    out = tool(target="telegram:12345", text="hello")
    assert out == {"ok": True, "message_id": "99", "target": "telegram:12345"}
    assert record == [
        {"token": "T0K", "chat_id": "12345", "text": "hello", "thread_id": None}
    ]
    # tool carries gating metadata + an explicit schema
    assert tool.__aisuite_tool_metadata__.requires_approval is True
    assert tool.__cogniwork_schema__["function"]["name"] == "send_message"


def test_send_message_missing_token(tmp_path):
    secrets = SecretStore(tmp_path / "secrets.json")
    tool = make_send_message_tool(secrets, senders=_fake_senders([]))
    assert "error" in tool(target="telegram:1", text="x")


def test_send_message_unknown_platform(tmp_path):
    tool = make_send_message_tool(
        SecretStore(tmp_path / "secrets.json"), senders=_fake_senders([])
    )
    assert "unknown platform" in tool(target="discord:1", text="x")["error"]


def test_send_message_bad_target(tmp_path):
    tool = make_send_message_tool(
        SecretStore(tmp_path / "secrets.json"), senders=_fake_senders([])
    )
    assert "error" in tool(target="nonsense", text="x")


# -- settings / authorization --------------------------------------------------
def test_is_authorized():
    s = ConnectorSettings(platform="telegram", allowed_users={"u1"})
    assert is_authorized(s, SessionSource("telegram", "c", user_id="u1"))
    assert not is_authorized(s, SessionSource("telegram", "c", user_id="u2"))
    # empty allowlist = nobody
    assert not is_authorized(
        ConnectorSettings("telegram"), SessionSource("telegram", "c", user_id="u1")
    )
    # allow_all opens it
    assert is_authorized(
        ConnectorSettings("telegram", allow_all=True),
        SessionSource("telegram", "c", user_id="x"),
    )


def test_load_settings_from_secretstore(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_ALLOWED_USERS", raising=False)
    secrets = SecretStore(tmp_path / "secrets.json")
    secrets.put(
        "telegram:default", {"type": "token", "bot_token": "T", "allowed_users": ["u1"]}
    )
    settings = __import__(
        "cogniwork.connectors.config", fromlist=["load_settings"]
    ).load_settings(secrets)
    assert settings["telegram"].enabled is True
    assert settings["telegram"].allowed_users == {"u1"}
    assert settings["slack"].enabled is False  # no token


def test_load_settings_env_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "a, b ,c")
    secrets = SecretStore(tmp_path / "secrets.json")
    secrets.put("telegram:default", {"bot_token": "T"})
    settings = __import__(
        "cogniwork.connectors.config", fromlist=["load_settings"]
    ).load_settings(secrets)
    assert settings["telegram"].allowed_users == {"a", "b", "c"}


# -- gateway inbound loop (FakeAdapter) ----------------------------------------
async def test_gateway_dispatches_authorized():
    received: list[MessageEvent] = []

    async def handler(ev: MessageEvent) -> None:
        received.append(ev)

    settings = {"fake": ConnectorSettings("fake", enabled=True, allowed_users={"u1"})}
    gw = Gateway(settings=settings, handler=handler)
    fake = FakeAdapter()
    gw.register(fake)
    live = await gw.start()
    assert live == ["fake"] and fake.connected

    await fake.inject("hi", user_id="u1")
    assert len(received) == 1 and received[0].text == "hi"

    await fake.inject("nope", user_id="intruder")  # not in allowlist
    assert len(received) == 1  # dropped

    await gw.stop()
    assert not fake.connected


async def test_gateway_deliver_via_adapter():
    gw = Gateway(
        settings={"fake": ConnectorSettings("fake", enabled=True, allow_all=True)}
    )
    fake = FakeAdapter()
    gw.register(fake)
    result = await gw.deliver("fake:c9", "pong")
    assert result.ok
    assert fake.outbox == [{"chat_id": "c9", "text": "pong", "thread_id": None}]


async def test_gateway_full_echo_loop():
    """Inbound → handler replies via deliver → lands in the adapter outbox."""
    gw = Gateway(
        settings={"fake": ConnectorSettings("fake", enabled=True, allow_all=True)}
    )
    fake = FakeAdapter()

    async def echo(ev: MessageEvent) -> None:
        await gw.deliver(ev.source.target, f"echo: {ev.text}")

    gw.set_handler(echo)
    gw.register(fake)
    await fake.inject("ping", chat_id="c1", user_id="u1")
    assert fake.outbox == [{"chat_id": "c1", "text": "echo: ping", "thread_id": None}]


# -- engine integration: send_message appears only when a connector is configured ----
class _StubProvider:
    """Minimal ProviderClient stand-in (build_engine never calls it)."""

    def complete(self, **_kw):  # pragma: no cover - never invoked at build time
        from cogniwork.providers import AssistantTurn

        return AssistantTurn()

    def capabilities(self, _model):  # pragma: no cover
        from cogniwork.providers.base import ModelCapabilities

        return ModelCapabilities()

    def stream(self, **_kw):  # pragma: no cover
        from cogniwork.providers.base import StreamChunk

        yield StreamChunk(turn=self.complete())


def test_engine_connector_tools_are_cogniwork_scoped(tmp_path):
    from cogniwork.agent import build_engine
    from cogniwork.agents import chat_agent, code_agent, cogniwork_agent, myhelper_agent

    secrets = SecretStore(tmp_path / "secrets.json")
    eng = build_engine(agent=chat_agent(), provider=_StubProvider(), secrets=secrets)
    assert "send_message" not in eng.registry.names()  # no connector yet
    assert "browser_read_url" not in eng.registry.names()

    secrets.put("telegram:default", {"bot_token": "T"})
    chat = build_engine(agent=chat_agent(), provider=_StubProvider(), secrets=secrets)
    code = build_engine(
        agent=code_agent(),
        workspace=tmp_path,
        provider=_StubProvider(),
        secrets=secrets,
    )
    cogniwork = build_engine(
        agent=cogniwork_agent(),
        workspace=tmp_path,
        provider=_StubProvider(),
        secrets=secrets,
    )
    helper = build_engine(
        agent=myhelper_agent(),
        workspace=tmp_path,
        provider=_StubProvider(),
        secrets=secrets,
    )

    assert "send_message" not in chat.registry.names()
    assert "send_message" not in code.registry.names()
    assert "browser_read_url" not in chat.registry.names()
    assert "browser_read_url" not in code.registry.names()

    assert "send_message" in cogniwork.registry.names()
    assert "browser_read_url" in cogniwork.registry.names()
    assert "browser_open_url" in cogniwork.registry.names()
    assert "browser_click" in cogniwork.registry.names()
    assert "browser_type" in cogniwork.registry.names()
    assert "github_search" not in cogniwork.registry.names()
    assert "send_message" in helper.registry.names()
    assert "browser_read_url" not in helper.registry.names()
    assert "browser_open_url" not in helper.registry.names()

    # §36: browser READS (registry kind) are free; interactions still gate.
    assert cogniwork.registry.get("browser_open_url").metadata.requires_approval is False
    assert cogniwork.registry.get("browser_snapshot").metadata.requires_approval is False
    assert cogniwork.registry.get("browser_click").metadata.requires_approval is True
    assert cogniwork.registry.get("browser_type").metadata.requires_approval is True
    cogniwork.permissions.allow_tool_for_session("browser_click")
    decision = cogniwork.permissions.evaluate(
        "browser_click",
        {"target": "button"},
        cogniwork.registry.get("browser_click").metadata,
    )
    assert decision.needs_user is True

    secrets.put("github:default", {"token": "ghp_test", "enabled": True})
    cogniwork_with_github = build_engine(
        agent=cogniwork_agent(),
        workspace=tmp_path,
        provider=_StubProvider(),
        secrets=secrets,
    )
    assert "github_search" in cogniwork_with_github.registry.names()
    # §36: github_search is a registry READ — free; the write sibling still gates.
    assert (
        cogniwork_with_github.registry.get("github_search").metadata.requires_approval
        is False
    )
    assert (
        cogniwork_with_github.registry.get(
            "github_create_issue"
        ).metadata.requires_approval
        is True
    )


# -- connector setup (descriptors / connect / disconnect / list) ---------------
def test_connector_list_descriptors(tmp_path):
    from cogniwork.connectors import connector_list

    by_name = {
        c["name"]: c for c in connector_list(SecretStore(tmp_path / "secrets.json"))
    }
    assert (
        by_name["telegram"]["two_way"] is True
        and by_name["telegram"]["connected"] is False
    )
    # channels (chat capability) is narrower than two_way: GitHub is two-way via the
    # relay (inbound mentions) but sessions can't subscribe to "GitHub channels".
    assert by_name["telegram"]["channels"] is True
    assert by_name["slack"]["channels"] is True
    assert (
        by_name["github"]["two_way"] is True and by_name["github"]["channels"] is False
    )
    assert (
        by_name["gmail"]["available"] is True and by_name["gmail"]["connected"] is False
    )
    assert (
        by_name["browser"]["available"] is True
        and by_name["browser"]["connected"] is True
    )
    assert (
        by_name["github"]["available"] is True
        and by_name["github"]["connected"] is False
    )
    assert any(
        t["name"] == "browser_open_url" and t["requires_approval"]
        for t in by_name["browser"]["tools"]
    )
    # telegram exposes a bot_token field + setup instructions
    keys = {f["key"] for f in by_name["telegram"]["fields"]}
    assert "bot_token" in keys and by_name["telegram"]["instructions"]


def test_connector_list_pre_connect_copy(tmp_path):
    """Every connectable connector ships Access bullets for the pre-connect
    detail page (UX-DECISIONS §38) — an empty Access section would render as
    'this app tells you nothing about what it can do'."""
    from cogniwork.connectors import connector_list
    from cogniwork.connectors.catalog_copy import ACCESS
    from cogniwork.connectors.descriptors import list_descriptors

    for c in connector_list(SecretStore(tmp_path / "secrets.json")):
        assert isinstance(c["about"], str)
        assert c["access"] and all(
            isinstance(line, str) and line for line in c["access"]
        ), f"{c['name']} has no access copy"
    # Curated (non-fallback) copy is required for every AVAILABLE connector —
    # the fallback line is only a net for experimental/placeholder entries.
    missing = [
        d.name
        for d in list_descriptors()
        if d.available and not d.experimental and d.name not in ACCESS
    ]
    assert not missing, f"connectors missing curated access copy: {missing}"


def test_connector_list_connected_for_required_profiles(tmp_path):
    from cogniwork.connectors import (
        connect_connector,
        connector_list,
        update_connector_tools,
    )

    secrets = SecretStore(tmp_path / "secrets.json")
    assert (
        connect_connector(secrets, "github", {"token": "ghp_test"}, validate=False)[
            "ok"
        ]
        is True
    )
    assert (
        connect_connector(
            secrets,
            "jira",
            {
                "base_url": "https://example.atlassian.net",
                "email": "me@example.com",
                "api_token": "tok",
            },
            validate=False,
        )["ok"]
        is True
    )

    by_name = {c["name"]: c for c in connector_list(secrets)}
    assert (
        by_name["github"]["connected"] is True and by_name["github"]["enabled"] is True
    )
    assert by_name["jira"]["connected"] is True and by_name["jira"]["enabled"] is True

    assert (
        update_connector_tools(secrets, "github", {"github_search": False})["ok"]
        is True
    )
    by_name = {c["name"]: c for c in connector_list(secrets)}
    gh_tools = {t["name"]: t for t in by_name["github"]["tools"]}
    assert gh_tools["github_search"]["enabled"] is False
    assert gh_tools["github_get_issue"]["enabled"] is True


def test_connect_disconnect_no_validate(tmp_path):
    from cogniwork.connectors import (
        connect_connector,
        connector_list,
        disconnect_connector,
    )

    secrets = SecretStore(tmp_path / "secrets.json")
    res = connect_connector(
        secrets,
        "telegram",
        {"bot_token": "T0K", "allowed_users": "u1, u2"},
        validate=False,
    )
    assert res["ok"] is True
    profile = secrets.get("telegram:default")
    assert profile["bot_token"] == "T0K" and profile["allowed_users"] == ["u1", "u2"]
    assert profile["enabled"] is True

    listed = {c["name"]: c for c in connector_list(secrets)}["telegram"]
    assert (
        listed["connected"] is True
        and listed["enabled"] is True
        and listed["allowed_users"] == ["u1", "u2"]
    )

    assert disconnect_connector(secrets, "telegram")["ok"] is True
    assert secrets.get("telegram:default") is None


def test_reconnect_does_not_clobber_secret_or_allowlist(tmp_path):
    # Regression: a re-submit carrying the masked placeholder (or a blank allow-list) must not
    # overwrite a stored real token / wipe the live allow-list.
    from cogniwork.connectors import connect_connector
    from cogniwork.connectors.descriptors import get_descriptor

    secrets = SecretStore(tmp_path / "secrets.json")
    placeholder = next(
        f.placeholder for f in get_descriptor("telegram").fields if f.key == "bot_token"
    )
    connect_connector(
        secrets,
        "telegram",
        {"bot_token": "REAL-TOKEN-123", "allowed_users": "u1, u2"},
        validate=False,
    )

    # Re-submit with the field's mask + an empty allow-list → both must be preserved.
    connect_connector(
        secrets,
        "telegram",
        {"bot_token": placeholder, "allowed_users": ""},
        validate=False,
    )
    prof = secrets.get("telegram:default")
    assert prof["bot_token"] == "REAL-TOKEN-123"  # not reset to the placeholder
    assert prof["allowed_users"] == ["u1", "u2"]  # not wiped

    # A genuinely new token still updates.
    connect_connector(
        secrets, "telegram", {"bot_token": "NEW-TOKEN-999"}, validate=False
    )
    assert secrets.get("telegram:default")["bot_token"] == "NEW-TOKEN-999"
    assert secrets.get("telegram:default")["allowed_users"] == [
        "u1",
        "u2",
    ]  # still preserved


def test_connect_missing_required_field(tmp_path):
    from cogniwork.connectors import connect_connector

    secrets = SecretStore(tmp_path / "secrets.json")
    res = connect_connector(
        secrets, "slack", {"bot_token": "xoxb"}, validate=False
    )  # app_token missing
    assert res["ok"] is False and "missing" in res["error"]


def test_manual_slack_reconnect_preserves_approval_owners(tmp_path):
    from cogniwork.connectors import connect_connector

    secrets = SecretStore(tmp_path / "secrets.json")
    secrets.put(
        "slack:default",
        {
            "bot_token": "xoxb-old",
            "app_token": "xapp-old",
            "allowed_users": ["U_OWNER"],
            "approval_owner_ids": ["U_OWNER"],
        },
    )
    result = connect_connector(
        secrets,
        "slack",
        {"bot_token": "xoxb-new", "app_token": "xapp-new"},
        validate=False,
    )
    assert result["ok"] is True
    profile = secrets.get("slack:default")
    assert profile["approval_owner_ids"] == ["U_OWNER"]
    assert profile["allowed_users"] == ["U_OWNER"]


def test_connect_validation_runs(tmp_path):
    from cogniwork.connectors import connect_connector
    from cogniwork.connectors.descriptors import ValidationResult, get_descriptor

    secrets = SecretStore(tmp_path / "secrets.json")
    desc = get_descriptor("telegram")
    orig = desc.validate
    desc.validate = lambda creds: ValidationResult(True, identity="@mybot")
    try:
        res = connect_connector(
            secrets, "telegram", {"bot_token": "T"}
        )  # validate=True
    finally:
        desc.validate = orig
    assert res == {"ok": True, "account": "@mybot"}
    assert secrets.get("telegram:default")["account"] == "@mybot"


def test_connectors_rest(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from cogniwork.connectors.descriptors import ValidationResult, get_descriptor
    from cogniwork.server.app import create_app
    from cogniwork.server.manager import SessionManager

    monkeypatch.setenv("COGNIWORK_STATE_DIR", str(tmp_path / "state"))
    desc = get_descriptor("telegram")
    monkeypatch.setattr(
        desc, "validate", lambda creds: ValidationResult(True, identity="@testbot")
    )

    client = TestClient(create_app(SessionManager(data_dir=tmp_path / "data")))

    listed = client.get("/v1/connectors").json()["connectors"]
    assert any(c["name"] == "telegram" for c in listed)

    r = client.post(
        "/v1/connectors/telegram/connect",
        json={"fields": {"bot_token": "T0K", "allowed_users": "u1"}},
    )
    assert r.json() == {"ok": True, "account": "@testbot"}

    tg = {c["name"]: c for c in client.get("/v1/connectors").json()["connectors"]}[
        "telegram"
    ]
    assert tg["connected"] is True and tg["account"] == "@testbot"
    # secrets never leak over REST
    assert "T0K" not in client.get("/v1/connectors").text

    assert client.post("/v1/connectors/telegram/disconnect").json()["ok"] is True
    assert {c["name"]: c for c in client.get("/v1/connectors").json()["connectors"]}[
        "telegram"
    ]["connected"] is False


# -- inbound: event mappers ----------------------------------------------------
def test_telegram_message_mapper():
    from types import SimpleNamespace

    from cogniwork.connectors import telegram_message_to_event

    msg = SimpleNamespace(
        text="hello",
        message_id=7,
        chat=SimpleNamespace(id=12345, type="private"),
        from_user=SimpleNamespace(id=99, full_name="Alice"),
        message_thread_id=None,
    )
    ev = telegram_message_to_event(msg)
    assert ev.text == "hello" and ev.source.target == "telegram:12345"
    assert ev.source.user_id == "99" and ev.source.chat_type == "dm"
    # non-text (e.g. a sticker) maps to None
    assert (
        telegram_message_to_event(
            SimpleNamespace(text=None, chat=SimpleNamespace(id=1, type="private"))
        )
        is None
    )


def test_slack_event_mapper_and_loop_guard():
    from cogniwork.connectors import slack_event_to_event

    ev = slack_event_to_event(
        {
            "text": "ship it",
            "channel": "C9",
            "user": "U1",
            "channel_type": "channel",
            "ts": "1.2",
        },
        "BOT",
    )
    assert (
        ev.text == "ship it"
        and ev.source.target == "slack:C9"
        and ev.source.chat_type == "channel"
    )
    # bot echo / edits / empty → dropped (reply-loop guard)
    assert slack_event_to_event({"text": "x", "user": "BOT"}, "BOT") is None
    assert slack_event_to_event({"text": "x", "bot_id": "B1"}, None) is None
    assert (
        slack_event_to_event({"subtype": "message_changed", "text": "x"}, None) is None
    )


def test_make_adapter():
    from cogniwork.connectors import SlackAdapter, TelegramAdapter, make_adapter

    assert isinstance(make_adapter("telegram", {"bot_token": "T"}), TelegramAdapter)
    assert isinstance(
        make_adapter("slack", {"bot_token": "x", "app_token": "y"}), SlackAdapter
    )
    assert make_adapter("slack", {"bot_token": "x"}) is None  # app_token missing
    assert make_adapter("telegram", {}) is None


async def test_slack_resolves_and_caches_display_name():
    from cogniwork.connectors import SlackAdapter

    calls: list[str] = []

    class _Client:
        async def users_info(self, user):
            calls.append(user)
            return {"user": {"name": "ann", "profile": {"display_name": "Ann"}}}

    class _App:
        client = _Client()

    a = SlackAdapter("b", "x")
    a._app = _App()
    assert await a._display_name("U1") == "Ann"
    assert await a._display_name("U1") == "Ann"  # served from cache
    assert calls == ["U1"]  # only one API round-trip

    class _BadClient:
        async def users_info(self, user):
            raise RuntimeError("nope")

    a._app.client = _BadClient()
    assert (
        await a._display_name("U2") is None
    )  # failure → None (caller falls back to the id)
    assert await a._display_name("") is None  # no id → no call


async def test_slack_resolve_channel_name():
    from cogniwork.connectors import SlackAdapter

    calls: list[str] = []

    class _Client:
        async def conversations_info(self, channel):
            calls.append(channel)
            return {"channel": {"id": channel, "name": "ocw-test"}}

    class _App:
        client = _Client()

    a = SlackAdapter("b", "x")
    a._app = _App()
    assert await a._channel_name("C1") == "ocw-test"
    assert await a._channel_name("C1") == "ocw-test"  # served from cache
    assert calls == ["C1"]  # only one API round-trip
    # public §2.1 wrapper delegates to the cached resolver (no extra call)
    assert await a.resolve_channel_name("C1") == "ocw-test"
    assert calls == ["C1"]

    class _BadClient:
        async def conversations_info(self, channel):
            raise RuntimeError("nope")

    a._app.client = _BadClient()
    assert (
        await a._channel_name("C2") is None
    )  # failure → None (caller falls back to the id)
    assert await a._channel_name("") is None  # no id → no call


# -- chat-ID auto-capture + connector allow-list -------------------------------
async def test_gateway_records_recent_senders():
    gw = Gateway(
        settings={"fake": ConnectorSettings("fake", enabled=True, allowed_users={"u1"})}
    )
    fake = FakeAdapter()
    gw.register(fake)
    await fake.inject(
        "hi", user_id="u2", user_name="Bob"
    )  # unauthorized → dropped but captured
    await fake.inject("yo", user_id="u1", user_name="Al")  # authorized
    recent = gw.recent_senders()
    assert [r["user_id"] for r in recent] == ["u1", "u2"]  # most-recent first
    assert recent[1]["user_name"] == "Bob"
    # same sender again de-dupes and moves to front
    await fake.inject("again", user_id="u2")
    assert [r["user_id"] for r in gw.recent_senders("fake")] == ["u2", "u1"]


def test_manager_allow_disallow(tmp_path, monkeypatch):
    from cogniwork.connectors import connect_connector
    from cogniwork.server.manager import SessionManager

    monkeypatch.setenv("COGNIWORK_STATE_DIR", str(tmp_path / "state"))
    m = SessionManager(data_dir=tmp_path / "data")
    connect_connector(m.secrets, "telegram", {"bot_token": "T"}, validate=False)

    assert m.allow_user("telegram", "12345")["allowed_users"] == ["12345"]
    assert m.secrets.get("telegram:default")["allowed_users"] == ["12345"]
    assert m.disallow_user("telegram", "12345")["allowed_users"] == []
    assert m.allow_user("slack", "x")["ok"] is False  # slack not connected


# -- new tool connectors (gitlab / discord / hubspot / box / whatsapp /
#    mixpanel / notion / attio / figma / google_drive / canva) --------------
_NEW_CONNECTORS = {
    "gitlab": {"token": "glpat-x"},
    "discord": {"bot_token": "B0T"},
    "hubspot": {"token": "pat-x"},
    "box": {"access_token": "boxtok"},
    "whatsapp": {"access_token": "wa_tok", "phone_number_id": "555111"},
    "mixpanel": {"username": "svc.user", "secret": "mp_sec", "project_id": "88"},
    "notion": {"access_token": "ntn_x"},
    "attio": {"access_token": "attio_x"},
    "figma": {"access_token": "figd_x"},
    "google_drive": {"access_token": "ya29.x"},
    "canva": {"access_token": "cnv_x"},
}


def test_new_connector_descriptors_listed(tmp_path):
    from cogniwork.connectors import connector_list

    by_name = {
        c["name"]: c for c in connector_list(SecretStore(tmp_path / "secrets.json"))
    }
    for name in _NEW_CONNECTORS:
        assert by_name[name]["available"] is True
        assert by_name[name]["connected"] is False
        assert by_name[name]["two_way"] is False
        assert by_name[name]["instructions"]
        assert by_name[name]["tools"], f"{name} has no tools in the catalog"
    # box, google_drive (scope discipline), and canva (exports are renders) are read-only
    assert all(t["kind"] == "read" for t in by_name["box"]["tools"])
    assert all(t["kind"] == "read" for t in by_name["google_drive"]["tools"])
    assert all(t["kind"] == "read" for t in by_name["canva"]["tools"])


def test_new_connectors_connect_and_gate_tools(tmp_path):
    from cogniwork.connectors import connect_connector, connector_list
    from cogniwork.connectors.integration_tools import make_integration_tools

    secrets = SecretStore(tmp_path / "secrets.json")
    for name, fields in _NEW_CONNECTORS.items():
        assert connect_connector(secrets, name, fields, validate=False)["ok"] is True

    by_name = {c["name"]: c for c in connector_list(secrets)}
    for name in _NEW_CONNECTORS:
        assert by_name[name]["connected"] is True and by_name[name]["enabled"] is True

    # only the enabled connectors' tools survive the filter
    tools = make_integration_tools(secrets, enabled_connectors={"gitlab", "box"})
    names = {t.__name__ for t in tools}
    assert "gitlab_search" in names and "box_search" in names
    assert "hubspot_search" not in names and "figma_get_file" not in names


def test_new_tools_error_when_not_connected(tmp_path):
    from cogniwork.connectors.integration_tools import make_integration_tools

    tools = {
        t.__name__: t
        for t in make_integration_tools(SecretStore(tmp_path / "secrets.json"))
    }
    assert "not connected" in tools["gitlab_search"](query="q")["error"]
    assert "not connected" in tools["discord_send_message"]("1", "hi")["error"]
    assert "not connected" in tools["hubspot_search"]("acme")["error"]
    assert "not connected" in tools["mixpanel_top_events"]()["error"]
    assert "not connected" in tools["box_read_file"]("1")["error"]
    assert "not connected" in tools["figma_get_file"]("KEY1")["error"]
    assert "not connected" in tools["drive_search_files"]("plan")["error"]
    assert "not connected" in tools["canva_list_designs"]()["error"]


def _connected_tools(tmp_path, monkeypatch, calls):
    """All new connectors connected + _request recorded instead of hitting the network."""
    import cogniwork.connectors.integration_tools as it

    secrets = SecretStore(tmp_path / "secrets.json")
    for name, fields in _NEW_CONNECTORS.items():
        secrets.put(f"{name}:default", {**fields, "enabled": True})

    def fake_request(method, url, *, headers=None, params=None, json=None, auth=None):
        calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "params": params,
                "json": json,
                "auth": auth,
            }
        )
        return {"ok": True, "data": {"id": "1", "name": "fake"}}

    monkeypatch.setattr(it, "_request", fake_request)
    return {t.__name__: t for t in it.make_integration_tools(secrets)}


def test_new_tools_request_routing(tmp_path, monkeypatch):
    calls = []
    tools = _connected_tools(tmp_path, monkeypatch, calls)

    tools["gitlab_get_issue"]("group/repo", 7)
    assert (
        calls[-1]["url"] == "https://gitlab.com/api/v4/projects/group%2Frepo/issues/7"
    )
    assert calls[-1]["headers"]["PRIVATE-TOKEN"] == "glpat-x"

    tools["discord_send_message"]("123", "x" * 3000)
    assert calls[-1]["url"] == "https://discord.com/api/v10/channels/123/messages"
    assert calls[-1]["headers"]["Authorization"] == "Bot B0T"
    assert len(calls[-1]["json"]["content"]) == 2000  # discord hard limit

    tools["hubspot_search"]("acme", object_type="bogus")
    assert calls[-1]["url"].endswith("/crm/v3/objects/contacts/search")  # fallback

    tools["box_read_file"]("f1")
    assert calls[-1]["url"] == "https://api.box.com/2.0/files/f1/content"

    tools["whatsapp_send_message"]("15551234567", "x" * 5000)
    assert calls[-1]["url"] == "https://graph.facebook.com/v21.0/555111/messages"
    assert calls[-1]["json"]["messaging_product"] == "whatsapp"
    assert len(calls[-1]["json"]["text"]["body"]) == 4096  # whatsapp hard limit

    tools["whatsapp_send_template"]("15551234567", "order_update")
    assert calls[-1]["json"]["template"] == {
        "name": "order_update",
        "language": {"code": "en_US"},
    }


def test_registry_has_no_duplicate_names():
    from cogniwork.connectors.descriptors import DESCRIPTORS
    from cogniwork.connectors.tool_defs import TOOL_DEFS

    names = [d.name for d in DESCRIPTORS]
    assert len(names) == len(set(names)), sorted(n for n in names if names.count(n) > 1)
    tools = [t.name for t in TOOL_DEFS]
    assert len(tools) == len(set(tools)), sorted(t for t in tools if tools.count(t) > 1)


def test_batch2_tools_request_routing(tmp_path, monkeypatch):
    calls = []
    tools = _connected_tools(tmp_path, monkeypatch, calls)

    tools["mixpanel_segmentation"]("purchase", "2026-07-01", "2026-07-07", unit="bogus")
    assert calls[-1]["url"] == "https://mixpanel.com/api/query/segmentation"
    assert calls[-1]["params"]["project_id"] == "88"
    assert calls[-1]["params"]["unit"] == "day"  # bogus unit falls back

    tools["mixpanel_top_events"]()
    assert calls[-1]["url"].endswith("/api/query/events/top")

    tools["notion_search"]("roadmap", max_results=5)
    assert calls[-1]["url"] == "https://api.notion.com/v1/search"
    assert calls[-1]["headers"]["Notion-Version"] == "2022-06-28"
    assert calls[-1]["json"] == {"query": "roadmap", "page_size": 5}

    tools["notion_query_database"]("db1")
    assert calls[-1]["url"].endswith("/v1/databases/db1/query")
    assert (
        "must be a Notion filter"
        in tools["notion_query_database"]("db1", "nope")["error"]
    )

    tools["notion_create_page"]("pg1", "Weekly notes", "line one\n\nline two")
    assert calls[-1]["json"]["parent"] == {"page_id": "pg1"}
    assert len(calls[-1]["json"]["children"]) == 2  # blank lines dropped

    tools["attio_list_objects"]()
    assert calls[-1]["url"] == "https://api.attio.com/v2/objects"
    assert calls[-1]["headers"]["Authorization"] == "Bearer attio_x"

    tools["attio_query_records"]("companies", max_results=50)
    assert calls[-1]["url"].endswith("/v2/objects/companies/records/query")
    assert calls[-1]["json"] == {"limit": 50}

    tools["attio_get_record"]("people", "r1")
    assert calls[-1]["url"].endswith("/v2/objects/people/records/r1")

    tools["attio_create_note"]("companies", "r1", "Call notes", "went well")
    assert calls[-1]["url"] == "https://api.attio.com/v2/notes"
    assert calls[-1]["json"]["data"]["parent_record_id"] == "r1"
    assert calls[-1]["json"]["data"]["format"] == "plaintext"


def test_batch3_tools_request_routing(tmp_path, monkeypatch):
    calls = []
    tools = _connected_tools(tmp_path, monkeypatch, calls)

    # Figma: PAT in X-Figma-Token.
    tools["figma_get_comments"]("KEY1")
    assert calls[-1]["url"] == "https://api.figma.com/v1/files/KEY1/comments"
    assert calls[-1]["headers"]["X-Figma-Token"] == "figd_x"

    tools["figma_post_comment"]("KEY1", "looks good", reply_to="c9")
    assert calls[-1]["json"] == {"message": "looks good", "comment_id": "c9"}

    tools["figma_export_images"]("KEY1", "1:2,1:3", format="svg")
    assert calls[-1]["url"] == "https://api.figma.com/v1/images/KEY1"
    assert calls[-1]["params"]["ids"] == "1:2,1:3"

    # Drive: bearer token; quotes escaped into the q expression.
    tools["drive_search_files"]("Q3 plan's", max_results=5)
    assert calls[-1]["url"] == "https://www.googleapis.com/drive/v3/files"
    assert calls[-1]["headers"]["Authorization"] == "Bearer ya29.x"
    assert "Q3 plan\\'s" in calls[-1]["params"]["q"]
    assert "trashed=false" in calls[-1]["params"]["q"]

    tools["drive_list_folder"]()
    assert calls[-1]["params"]["q"] == "'root' in parents and trashed=false"

    # Canva: bearer token; export is a job POST.
    tools["canva_list_designs"]("deck", max_results=5)
    assert calls[-1]["url"] == "https://api.canva.com/rest/v1/designs"
    assert calls[-1]["headers"]["Authorization"] == "Bearer cnv_x"
    assert calls[-1]["params"] == {"limit": 5, "query": "deck"}

    tools["canva_export_design"]("d1", format="png")
    assert calls[-1]["url"] == "https://api.canva.com/rest/v1/exports"
    assert calls[-1]["json"] == {"design_id": "d1", "format": {"type": "png"}}

    tools["canva_get_export"]("exp1")
    assert calls[-1]["url"] == "https://api.canva.com/rest/v1/exports/exp1"


def test_drive_read_file_exports_google_docs(tmp_path, monkeypatch):
    import cogniwork.connectors.integration_tools as it

    secrets = SecretStore(tmp_path / "secrets.json")
    secrets.put("google_drive:default", {"access_token": "ya29.x", "enabled": True})

    def fake_request(method, url, *, headers=None, params=None, json=None, auth=None):
        if url.endswith("/export"):
            return {"ok": True, "data": "Doc body text"}
        return {
            "ok": True,
            "data": {
                "id": "f1",
                "name": "Plan",
                "mimeType": "application/vnd.google-apps.document",
            },
        }

    monkeypatch.setattr(it, "_request", fake_request)
    tools = {t.__name__: t for t in it.make_integration_tools(secrets)}
    out = tools["drive_read_file"]("f1")
    assert out["ok"] is True and out["content"] == "Doc body text"

    # Native Google types with no text export refuse instead of dumping binary.
    def fake_request_drawing(method, url, **kw):
        return {
            "ok": True,
            "data": {"mimeType": "application/vnd.google-apps.drawing"},
        }

    monkeypatch.setattr(it, "_request", fake_request_drawing)
    tools = {t.__name__: t for t in it.make_integration_tools(secrets)}
    assert "cannot read" in tools["drive_read_file"]("f2")["error"]


def test_notion_read_page_flattens_blocks(tmp_path, monkeypatch):
    import cogniwork.connectors.integration_tools as it
    from cogniwork.connectors import accounts

    secrets = SecretStore(tmp_path / "secrets.json")
    accounts.add_account(secrets, "notion", "ws1", {"access_token": "t"})

    def fake_request(method, url, *, headers=None, params=None, json=None, auth=None):
        if "/blocks/" in url:
            return {
                "ok": True,
                "data": {
                    "results": [
                        {
                            "type": "heading_1",
                            "heading_1": {"rich_text": [{"plain_text": "Title"}]},
                        },
                        {
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": [{"plain_text": "First line."}],
                            },
                        },
                        {
                            "type": "to_do",
                            "to_do": {
                                "rich_text": [{"plain_text": "Ship feature"}],
                                "checked": True,
                            },
                        },
                        {
                            "type": "bulleted_list_item",
                            "bulleted_list_item": {
                                "rich_text": [{"plain_text": "Point A"}],
                            },
                        },
                    ]
                },
            }
        return {
            "ok": True,
            "data": {
                "id": "pg1",
                "properties": {
                    "title": {"title": [{"plain_text": "Page Title"}]}
                },
            },
        }

    monkeypatch.setattr(it, "_request", fake_request)
    tools = {t.__name__: t for t in it.make_integration_tools(secrets)}
    out = tools["notion_read_page"]("pg1")
    assert out["ok"] is True
    assert "Title" in out["text"]
    assert "First line." in out["text"]
    assert "Ship feature" in out["text"]


def test_batch2_account_param_picks_the_profile(tmp_path, monkeypatch):
    import cogniwork.connectors.integration_tools as it
    from cogniwork.connectors import accounts

    calls = []
    secrets = SecretStore(tmp_path / "secrets.json")
    accounts.add_account(
        secrets, "mixpanel", "11", {"username": "u11", "secret": "s11", "project_id": "11"}
    )
    accounts.add_account(
        secrets, "mixpanel", "22", {"username": "u22", "secret": "s22", "project_id": "22"}
    )

    def fake_request(method, url, *, headers=None, params=None, json=None, auth=None):
        calls.append({"url": url, "headers": headers or {}, "params": params or {}})
        return {"ok": True, "data": {}}

    monkeypatch.setattr(it, "_request", fake_request)
    tools = {t.__name__: t for t in it.make_integration_tools(secrets)}

    out = tools["mixpanel_top_events"](account="22")
    assert calls[-1]["params"]["project_id"] == "22"
    assert out["account"] == "22"

    out = tools["mixpanel_top_events"]()  # default = first added
    assert calls[-1]["params"]["project_id"] == "11" and out["account"] == "11"

    out = tools["mixpanel_top_events"](account="99")
    assert "no mixpanel account matching" in out["error"]


def test_hubspot_search_properties_and_filters(tmp_path, monkeypatch):
    calls = []
    tools = _connected_tools(tmp_path, monkeypatch, calls)

    tools["hubspot_search"](
        object_type="companies",
        properties="org_type, check_min,check_max",
        filters='[{"property":"org_type","operator":"EQ","value":"VC"}]',
        max_results=50,
    )
    body = calls[-1]["json"]
    assert body["properties"] == ["org_type", "check_min", "check_max"]
    assert body["filterGroups"] == [
        {"filters": [{"property": "org_type", "operator": "EQ", "value": "VC"}]}
    ]
    assert body["limit"] == 50 and "query" not in body

    tools["hubspot_search"]("acme")  # plain free-text still works
    assert calls[-1]["json"]["query"] == "acme"

    n = len(calls)  # none of the error paths below may reach the network
    assert "JSON array" in tools["hubspot_search"](filters="not json")["error"]
    assert "property" in tools["hubspot_search"](filters='[{"value":"x"}]')["error"]
    assert "query" in tools["hubspot_search"]()["error"]
    assert len(calls) == n

    tools["hubspot_get_object"](
        "deals", "42", properties="round,portfolio_company", associations="companies"
    )
    assert calls[-1]["params"] == {
        "properties": "round,portfolio_company",
        "associations": "companies",
    }
    tools["hubspot_get_object"]("deals", "42")  # no params → none sent
    assert calls[-1]["params"] is None


def test_new_write_tools_require_approval(tmp_path, monkeypatch):
    tools = _connected_tools(tmp_path, monkeypatch, [])
    for name in (
        "gitlab_create_issue",
        "discord_send_message",
        "hubspot_create_contact",
        "whatsapp_send_message",
        "whatsapp_send_template",
        "notion_create_page",
        "attio_create_note",
        "figma_post_comment",
    ):
        assert tools[name].__aisuite_tool_metadata__.requires_approval is True, name
    for name in (
        "box_search",
        "drive_read_file",
        "figma_export_images",
        "canva_export_design",
    ):
        assert tools[name].__aisuite_tool_metadata__.requires_approval is False, name


def test_gitlab_self_hosted_base_url(tmp_path, monkeypatch):
    import cogniwork.connectors.integration_tools as it

    secrets = SecretStore(tmp_path / "secrets.json")
    secrets.put(
        "gitlab:default",
        {"token": "t", "base_url": "https://git.example.com/", "enabled": True},
    )
    calls = []
    monkeypatch.setattr(
        it, "_request", lambda m, url, **kw: calls.append(url) or {"ok": True}
    )
    tools = {t.__name__: t for t in it.make_integration_tools(secrets)}
    tools["gitlab_search"]("q")
    assert calls[0] == "https://git.example.com/api/v4/search"


def test_new_connector_validators_wired():
    from cogniwork.connectors.descriptors import get_descriptor

    for name in (
        "gitlab",
        "discord",
        "hubspot",
        "box",
        "whatsapp",
        "figma",
        "google_drive",
        "canva",
    ):
        assert get_descriptor(name).validate is not None, name


def test_validate_whoami_helper(monkeypatch):
    import cogniwork.connectors.descriptors as d

    class _Resp:
        def __init__(self, status, payload):
            self.status_code = status
            self._payload = payload

        def json(self):
            return self._payload

    def fake(status, payload):
        import httpx

        monkeypatch.setattr(httpx, "request", lambda *a, **k: _Resp(status, payload))

    fake(200, {"username": "alice"})
    res = d._validate_gitlab({"token": "t"})
    assert res.ok and res.identity == "@alice"

    fake(401, {"message": "401 Unauthorized"})
    res = d._validate_gitlab({"token": "bad"})
    assert not res.ok and "Unauthorized" in res.error

    fake(200, {"errors": [{"message": "auth"}]})
    res = d._validate_gitlab({"token": "bad"})
    assert not res.ok


# -- experimental connector gating ----------------------------------------------
@pytest.fixture
def experimental_descriptor():
    import cogniwork.connectors.descriptors as d

    desc = d.ConnectorDescriptor(
        name="dangerzone",
        title="Danger Zone",
        icon="!",
        blurb="Test-only experimental connector.",
        auth="token",
        two_way=False,
        fields=[d.Field("token", "Token", secret=True)],
        instructions=["test only"],
        experimental=True,
        risk_notice="This may eat your laundry.",
    )
    d.register_descriptor(desc)
    yield desc
    d.DESCRIPTORS.remove(desc)
    d._BY_NAME.pop(desc.name, None)


def test_experimental_hidden_until_enabled(tmp_path, experimental_descriptor):
    from cogniwork.connectors import connector_list, set_experimental_enabled

    secrets = SecretStore(tmp_path / "secrets.json")
    assert "dangerzone" not in {c["name"] for c in connector_list(secrets)}

    assert set_experimental_enabled(secrets, True)["enabled"] is True
    listed = {c["name"]: c for c in connector_list(secrets)}
    assert listed["dangerzone"]["experimental"] is True
    assert "laundry" in listed["dangerzone"]["risk_notice"]
    # first-party connectors are never flagged
    assert listed["github"]["experimental"] is False
    assert listed["whatsapp"]["experimental"] is False

    set_experimental_enabled(secrets, False)
    assert "dangerzone" not in {c["name"] for c in connector_list(secrets)}


def test_experimental_connect_requires_optin_and_ack(tmp_path, experimental_descriptor):
    from cogniwork.connectors import (
        connect_connector,
        connector_list,
        set_experimental_enabled,
    )

    secrets = SecretStore(tmp_path / "secrets.json")
    res = connect_connector(secrets, "dangerzone", {"token": "t"}, validate=False)
    assert res["ok"] is False and "disabled" in res["error"]

    set_experimental_enabled(secrets, True)
    res = connect_connector(secrets, "dangerzone", {"token": "t"}, validate=False)
    assert res["ok"] is False and "acknowledgment" in res["error"]
    assert "laundry" in res["risk_notice"]  # surfaced so the UI can show it

    res = connect_connector(
        secrets, "dangerzone", {"token": "t"}, validate=False, acknowledged=True
    )
    assert res["ok"] is True

    # turning the setting off hides it (and gates its tools) even though connected
    set_experimental_enabled(secrets, False)
    assert "dangerzone" not in {c["name"] for c in connector_list(secrets)}


def test_experimental_does_not_gate_regular_connectors(tmp_path):
    from cogniwork.connectors import connect_connector

    secrets = SecretStore(tmp_path / "secrets.json")
    res = connect_connector(
        secrets, "github", {"token": "ghp_x"}, validate=False
    )  # no acknowledged flag
    assert res["ok"] is True


def test_experimental_rest_roundtrip(tmp_path, monkeypatch, experimental_descriptor):
    from fastapi.testclient import TestClient

    from cogniwork.server.app import create_app
    from cogniwork.server.manager import SessionManager

    monkeypatch.setenv("COGNIWORK_STATE_DIR", str(tmp_path / "state"))
    client = TestClient(create_app(SessionManager(data_dir=tmp_path / "data")))

    assert client.get("/v1/settings").json()["experimental_connectors"] is False
    names = {c["name"] for c in client.get("/v1/connectors").json()["connectors"]}
    assert "dangerzone" not in names

    assert (
        client.post(
            "/v1/settings/experimental-connectors", json={"value": True}
        ).json()["enabled"]
        is True
    )
    assert client.get("/v1/settings").json()["experimental_connectors"] is True
    names = {c["name"] for c in client.get("/v1/connectors").json()["connectors"]}
    assert "dangerzone" in names

    r = client.post(
        "/v1/connectors/dangerzone/connect", json={"fields": {"token": "T"}}
    ).json()
    assert r["ok"] is False and "acknowledgment" in r["error"]
    r = client.post(
        "/v1/connectors/dangerzone/connect",
        json={"fields": {"token": "T"}, "acknowledge_risk": True},
    ).json()
    assert r["ok"] is True


def test_experimental_package_loads_cleanly():
    from cogniwork.connectors.descriptors import DESCRIPTORS
    from cogniwork.connectors.experimental import EXPERIMENTAL_DESCRIPTORS

    assert EXPERIMENTAL_DESCRIPTORS == []
    assert all(d.experimental is False for d in DESCRIPTORS if d.name != "dangerzone")
