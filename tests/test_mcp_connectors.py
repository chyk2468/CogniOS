"""MCP-backed connectors (UX-DECISIONS §42): a descriptor carries a vendor-hosted MCP
URL and a PINNED tool allowlist in tool_defs. One-click connect seeds the server
config from the pin + runs the local OAuth flow; the Connectors page owns the whole
lifecycle (the Settings MCP tab hides these servers); sessions gate the tools by the
effective connector set, per-tool toggles, and the read/write approval classification.
The vendor's catalog can drift under us — every gate here fails CLOSED."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from cogniwork.connectors.descriptors import list_descriptors
from cogniwork.connectors.setup import (
    connector_list,
    disconnect_connector,
    update_connector_tools,
)
from cogniwork.connectors.tool_defs import mcp_pinned_tools, mcp_tool_defs, tool_dicts
from cogniwork.mcp.config import put_global_server, read_global
from cogniwork.secrets import SecretStore
from cogniwork.server.manager import SessionManager


def _state(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIWORK_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)


def test_every_mcp_backed_descriptor_pins_tools():
    """The guard that keeps 'MCP-backed' meaning 'curated': a descriptor with an
    mcp_url must pin at least one tool, and every pin is classified read/write."""
    backed = [d for d in list_descriptors() if d.mcp_url]
    assert {d.name for d in backed} >= {"jira"}
    for d in backed:
        pins = mcp_pinned_tools(d.name)
        assert pins, f"{d.name} is MCP-backed but pins no tools"
        for t in mcp_tool_defs(d.name):
            assert t.name.startswith(f"mcp__{d.name}__")
            assert t.kind in ("read", "write")


def test_tool_dicts_follow_the_profile_mode(tmp_path, monkeypatch):
    """jira has BOTH a manual REST tool set and a pinned MCP set — exactly one is
    live, decided by the profile mode. MCP-only connectors always show their pin."""
    _state(tmp_path, monkeypatch)
    secrets = SecretStore()

    names = [t["name"] for t in tool_dicts(secrets, "jira")]
    assert "jira_search_issues" in names
    assert not any(n.startswith("mcp__") for n in names)

    secrets.put("jira:default", {"mode": "mcp"})
    names = [t["name"] for t in tool_dicts(secrets, "jira")]
    assert names and all(n.startswith("mcp__jira__") for n in names)


def test_mcp_connect_seeds_pinned_config_and_profile(tmp_path, monkeypatch):
    _state(tmp_path, monkeypatch)
    manager = SessionManager(data_dir=tmp_path / "data")

    async def fake_connect(name):
        return {"ok": True, "tools": 9}

    monkeypatch.setattr(manager, "connect_mcp", fake_connect)
    out = asyncio.run(manager.mcp_connect_connector("jira"))
    assert out["ok"]

    raw = read_global()["jira"]
    assert raw["url"] == "https://mcp.atlassian.com/v1/mcp"
    assert raw["auth"] == "oauth"
    # Server-level approval is OFF — per-tool classification gates writes instead.
    assert raw["requires_approval"] is False
    assert set(raw["include_tools"]) == set(mcp_pinned_tools("jira"))
    assert manager.secrets.get("jira:default")["mode"] == "mcp"

    # A connector without an MCP path fails closed.
    out = asyncio.run(manager.mcp_connect_connector("notion"))
    assert not out["ok"]


def test_failed_mcp_connect_removes_the_seeded_config(tmp_path, monkeypatch):
    _state(tmp_path, monkeypatch)
    manager = SessionManager(data_dir=tmp_path / "data")

    async def fail_connect(name):
        return {"ok": False, "error": "no DCR"}

    monkeypatch.setattr(manager, "connect_mcp", fail_connect)
    out = asyncio.run(manager.mcp_connect_connector("jira"))
    assert not out["ok"]
    assert "jira" not in read_global()
    assert manager.secrets.get("jira:default") is None


def test_prepare_mcp_tools_never_starts_an_oauth_flow(tmp_path, monkeypatch):
    """Token-less oauth servers are SKIPPED at turn start — connecting one would
    open a browser and block the session for the whole flow timeout. Tokens
    present → the server connects as usual."""
    _state(tmp_path, monkeypatch)
    manager = SessionManager(data_dir=tmp_path / "data")
    put_global_server(
        "granola",
        {"url": "https://mcp.granola.ai/mcp", "auth": "oauth", "enabled": True},
    )

    async def must_not_connect(server):
        raise AssertionError(f"ensure() reached for token-less {server.name}")

    monkeypatch.setattr(manager.mcp, "ensure", must_not_connect)
    assert asyncio.run(manager.prepare_mcp_tools("s1")) == []

    manager.secrets.put("mcp-oauth:granola", {"tokens": {"access_token": "at"}})
    seen = {}

    async def fake_ensure(server):
        seen["name"] = server.name
        return SimpleNamespace(tools=[])

    monkeypatch.setattr(manager.mcp, "ensure", fake_ensure)
    asyncio.run(manager.prepare_mcp_tools("s2"))
    assert seen["name"] == "granola"


def test_connected_follows_tokens_and_disconnect_forgets_everything(
    tmp_path, monkeypatch
):
    _state(tmp_path, monkeypatch)
    secrets = SecretStore()
    secrets.put("jira:default", {"mode": "mcp", "enabled": True})
    put_global_server("jira", {"url": "https://mcp.atlassian.com/v1/mcp", "auth": "oauth"})

    # Profile alone is just a marker — no tokens, not connected.
    row = {c["name"]: c for c in connector_list(secrets)}["jira"]
    assert row["mcp"] is True and row["connected"] is False

    secrets.put("mcp-oauth:jira", {"tokens": {"access_token": "at"}})
    row = {c["name"]: c for c in connector_list(secrets)}["jira"]
    assert row["connected"] is True and row["mode"] == "mcp"

    # Disconnect forgets tokens + DCR registration, the seeded config, and the profile.
    out = disconnect_connector(secrets, "jira")
    assert out["ok"]
    assert secrets.get("mcp-oauth:jira") is None
    assert "jira" not in read_global()
    row = {c["name"]: c for c in connector_list(secrets)}["jira"]
    assert row["connected"] is False


def test_connector_backed_servers_hidden_from_mcp_tab(tmp_path, monkeypatch):
    _state(tmp_path, monkeypatch)
    manager = SessionManager(data_dir=tmp_path / "data")
    put_global_server("jira", {"url": "https://mcp.atlassian.com/v1/mcp", "auth": "oauth"})
    put_global_server("granola", {"url": "https://mcp.granola.ai/mcp", "auth": "oauth"})
    names = [s["name"] for s in manager.list_mcp()]
    assert "granola" in names and "jira" not in names


def _fake_tool(name):
    return SimpleNamespace(
        name=name, description=f"vendor {name}", inputSchema={"type": "object"}
    )


def test_prepare_mcp_tools_gates_by_session_pin_and_toggles(tmp_path, monkeypatch):
    """The engine path: descriptor pin overrides stale config, per-tool toggles
    subtract, session gating skips connectors outside the effective set, and
    approval follows the read/write classification."""
    _state(tmp_path, monkeypatch)
    manager = SessionManager(data_dir=tmp_path / "data")
    manager.secrets.put("jira:default", {"mode": "mcp", "enabled": True})
    manager.secrets.put("mcp-oauth:jira", {"tokens": {"access_token": "at"}})
    # Stale config: include_tools claims a tool we never pinned.
    put_global_server(
        "jira",
        {
            "url": "https://mcp.atlassian.com/v1/mcp",
            "auth": "oauth",
            "include_tools": ["manage_agent"],
            "enabled": True,
        },
    )
    update_connector_tools(manager.secrets, "jira", {"mcp__jira__searchJiraIssuesUsingJql": False})

    seen = {}

    async def fake_ensure(server):
        seen["include_tools"] = list(server.include_tools or [])
        allow = set(server.include_tools or [])
        tools = [_fake_tool(n) for n in ["searchJiraIssuesUsingJql", "createJiraIssue", "getJiraIssue"]]
        return SimpleNamespace(tools=[t for t in tools if t.name in allow])

    monkeypatch.setattr(manager.mcp, "ensure", fake_ensure)
    monkeypatch.setattr(
        manager, "effective_connectors", lambda sid, agent=None: {"jira"}
    )

    tools = asyncio.run(manager.prepare_mcp_tools("s1"))
    # Pin is authoritative (no manage_agent), the toggled-off search is gone.
    assert set(seen["include_tools"]) == set(mcp_pinned_tools("jira")) - {"searchJiraIssuesUsingJql"}
    by_name = {t.__aisuite_tool_metadata__.name: t for t in tools}
    assert "mcp__jira__searchJiraIssuesUsingJql" not in by_name
    # Reads run free; writes ask first.
    read = by_name["mcp__jira__getJiraIssue"].__aisuite_tool_metadata__
    write = by_name["mcp__jira__createJiraIssue"].__aisuite_tool_metadata__
    assert read.requires_approval is False
    assert write.requires_approval is True

    # Session gating: a session whose effective set excludes jira gets nothing.
    monkeypatch.setattr(manager, "effective_connectors", lambda sid, agent=None: set())
    assert asyncio.run(manager.prepare_mcp_tools("s2")) == []


def test_stale_token_reauth_never_opens_a_browser_mid_turn(tmp_path, monkeypatch):
    """Tokens PRESENT but the vendor rejects the refresh → the SDK wants a browser
    re-auth. Non-interactive contexts refuse (InteractiveAuthRequired, often
    wrapped in an ExceptionGroup by the anyio transport): the session skips the
    server and the failure is recorded — owner-hit 2026-07-20: an Atlassian
    authorize page opened at app LAUNCH from a background session start."""
    from cogniwork.mcp import oauth as mcp_oauth

    _state(tmp_path, monkeypatch)
    manager = SessionManager(data_dir=tmp_path / "data")
    put_global_server(
        "granola",
        {"url": "https://mcp.granola.ai/mcp", "auth": "oauth", "enabled": True},
    )
    manager.secrets.put("mcp-oauth:granola", {"tokens": {"access_token": "stale"}})

    async def refuses(server):
        raise ExceptionGroup(
            "transport", [mcp_oauth.InteractiveAuthRequired("sign-in required")]
        )

    monkeypatch.setattr(manager.mcp, "ensure", refuses)
    assert asyncio.run(manager.prepare_mcp_tools("s1")) == []
    assert "sign-in required" in manager._mcp_errors["granola"]


def test_non_interactive_auth_wiring_refuses_the_browser():
    """build_auth(interactive=False) must never open a browser: its redirect
    handler raises (keeping the authorize URL for the GUI's reopen affordance),
    and is_auth_required() finds the marker bare, wrapped, or chained."""
    import pytest

    from cogniwork.mcp import oauth as mcp_oauth

    with pytest.raises(mcp_oauth.InteractiveAuthRequired):
        asyncio.run(mcp_oauth._refuse_browser("https://vendor/authorize?x=1"))
    assert mcp_oauth.last_authorize_url == "https://vendor/authorize?x=1"

    bare = mcp_oauth.InteractiveAuthRequired("x")
    assert mcp_oauth.is_auth_required(bare)
    assert mcp_oauth.is_auth_required(ExceptionGroup("g", [ValueError(), bare]))
    chained = RuntimeError("wrapped")
    chained.__cause__ = bare
    assert mcp_oauth.is_auth_required(chained)
    assert not mcp_oauth.is_auth_required(ValueError("no"))
