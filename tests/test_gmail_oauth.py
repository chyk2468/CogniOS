"""Comprehensive tests for Gmail Google OAuth 2.0 Authorization Code flow.

Covers:
1. credentials.json parsing and validation
2. malformed / invalid credentials rejection
3. OAuth authorization URL generation
4. State generation and expiration
5. State validation and anti-replay protection
6. Callback handling
7. Authorization code exchange logic (mocked Google endpoint)
8. Refresh-token persistence
9. Token authenticated encryption and decryption at rest
10. Automatic on-demand access-token refresh
11. Existing valid token reuse path (no extra refresh)
12. Refresh failure / invalid_grant / revoked token handling
13. REAUTH_REQUIRED state transitions and metadata preservation
14. Reconnect flow (preserving existing refresh token if Google omits new one)
15. Disconnect flow (wiping encrypted tokens and repointing default)
16. Multiple Gmail accounts side-by-side
17. Search Gmail tool integration
18. Read message tool integration
19. Send email tool integration
20. Send email approval checkpoint
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from cogniwork.connectors.gmail import (
    GmailClient,
    GmailConnectionStatus,
    InstalledAppCredentials,
    OAuthFlowState,
    build_authorization_url,
    crypto,
    disconnect_gmail_account,
    get_valid_access_token,
    list_account_records,
    save_account_credentials,
)
from cogniwork.connectors.gmail.oauth import (
    GMAIL_SCOPES,
    clean_expired_states,
    exchange_code,
    fetch_account_email,
    get_and_consume_state,
    resolve_redirect_uri,
)
from cogniwork.connectors.integration_tools import make_integration_tools
from cogniwork.connectors.setup import connector_list
from cogniwork.secrets import SecretStore


@pytest.fixture
def secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIWORK_STATE_DIR", str(tmp_path / "state"))
    return SecretStore()


@pytest.fixture
def valid_credentials_dict():
    return {
        "installed": {
            "client_id": "test-client-id.apps.googleusercontent.com",
            "project_id": "cogni-os",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_secret": "test-secret-value",
            "redirect_uris": ["http://localhost", "http://localhost:8765/oauth/callback"],
        }
    }


def _tool(secrets, name: str):
    tools = make_integration_tools(secrets)
    return next(t for t in tools if t.__name__ == name)


# -----------------------------------------------------------------------------
# 1 & 2. credentials.json Parsing & Validation
# -----------------------------------------------------------------------------

def test_parse_valid_credentials(valid_credentials_dict):
    creds, err = InstalledAppCredentials.from_dict(valid_credentials_dict)
    assert err == ""
    assert creds is not None
    assert creds.client_id == "test-client-id.apps.googleusercontent.com"
    assert creds.client_secret == "test-secret-value"
    assert creds.auth_uri == "https://accounts.google.com/o/oauth2/auth"
    assert creds.token_uri == "https://oauth2.googleapis.com/token"
    assert "http://localhost" in creds.redirect_uris


def test_reject_non_dict_credentials():
    creds, err = InstalledAppCredentials.from_dict("invalid")
    assert creds is None
    assert "root must be a JSON object" in err


def test_reject_missing_installed_block():
    creds, err = InstalledAppCredentials.from_dict({"client_id": "xyz"})
    assert creds is None
    assert "missing top-level 'installed' object" in err


def test_reject_web_app_credentials():
    creds, err = InstalledAppCredentials.from_dict({"web": {"client_id": "xyz"}})
    assert creds is None
    assert "Desktop application OAuth client ('installed') is required" in err


def test_reject_missing_client_id_or_secret(valid_credentials_dict):
    bad = dict(valid_credentials_dict)
    bad["installed"] = dict(bad["installed"])
    bad["installed"]["client_id"] = ""
    creds, err = InstalledAppCredentials.from_dict(bad)
    assert creds is None
    assert "missing 'client_id'" in err

    bad["installed"]["client_id"] = "id"
    bad["installed"]["client_secret"] = ""
    creds, err = InstalledAppCredentials.from_dict(bad)
    assert creds is None
    assert "missing 'client_secret'" in err


def test_parse_google_cloud_default_installed_json():
    # Real shape of client_secret_14253977407-7mbjgujldobcenk8u0kt2t31ftemmi16.apps.googleusercontent.com.json
    google_json = {
        "installed": {
            "client_id": "14253977407-7mbjgujldobcenk8u0kt2t31ftemmi16.apps.googleusercontent.com",
            "project_id": "cogni-os",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": "GOCSPX-test-secret-12345",
            "redirect_uris": [
                "http://localhost"
            ]
        }
    }
    creds, err = InstalledAppCredentials.from_dict(google_json)
    assert err == ""
    assert creds is not None
    assert creds.client_id == "14253977407-7mbjgujldobcenk8u0kt2t31ftemmi16.apps.googleusercontent.com"
    assert creds.project_id == "cogni-os"
    assert "http://localhost" in creds.redirect_uris


def test_parse_google_cloud_missing_redirect_uris():
    # When redirect_uris is omitted by Google Cloud Desktop credentials
    google_json = {
        "installed": {
            "client_id": "test-id",
            "client_secret": "test-secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    creds, err = InstalledAppCredentials.from_dict(google_json)
    assert err == ""
    assert creds is not None
    assert "http://localhost" in creds.redirect_uris


def test_parse_nested_credentials_wrapper(valid_credentials_dict):
    wrapped = {"credentials": valid_credentials_dict}
    creds, err = InstalledAppCredentials.from_dict(wrapped)
    assert err == ""
    assert creds is not None
    assert creds.client_id == "test-client-id.apps.googleusercontent.com"


# -----------------------------------------------------------------------------
# 3, 4 & 5. OAuth URL Generation, State Security & Validation
# -----------------------------------------------------------------------------

def test_authorization_url_generation(valid_credentials_dict):
    creds, _ = InstalledAppCredentials.from_dict(valid_credentials_dict)
    redirect_uri = resolve_redirect_uri(creds, port=8765)
    assert "8765" in redirect_uri

    auth_url, state = build_authorization_url(creds, redirect_uri, account_hint="alice@gmail.com")
    assert state
    assert auth_url.startswith("https://accounts.google.com/o/oauth2/auth?")
    assert "access_type=offline" in auth_url
    assert "prompt=consent" in auth_url
    assert "response_type=code" in auth_url
    assert "client_id=" in auth_url
    assert f"state={state}" in auth_url
    assert "login_hint=alice%40gmail.com" in auth_url

    # Scope checks: minimum necessary
    for scope in ("gmail.readonly", "gmail.send", "userinfo.email"):
        assert scope in auth_url


def test_state_validation_and_anti_replay(valid_credentials_dict):
    creds, _ = InstalledAppCredentials.from_dict(valid_credentials_dict)
    _, state = build_authorization_url(creds, "http://localhost:8765/oauth/callback")

    # First consumption succeeds
    flow = get_and_consume_state(state)
    assert flow is not None
    assert flow.state == state
    assert flow.client_config.client_id == creds.client_id

    # Replay consumption fails
    flow_replay = get_and_consume_state(state)
    assert flow_replay is None


def test_state_expiration(valid_credentials_dict, monkeypatch):
    creds, _ = InstalledAppCredentials.from_dict(valid_credentials_dict)
    _, state = build_authorization_url(creds, "http://localhost:8765/oauth/callback")

    # Fast forward time beyond expiration (600s)
    future_time = time.time() + 1000
    monkeypatch.setattr(time, "time", lambda: future_time)

    clean_expired_states()
    flow = get_and_consume_state(state)
    assert flow is None


# -----------------------------------------------------------------------------
# 8 & 9. Authenticated Encryption at Rest
# -----------------------------------------------------------------------------

def test_token_encryption_roundtrip(secrets):
    token = "ya29.a0AfH6SMD_secret_token_12345"
    encrypted = crypto.encrypt_token(token)
    assert encrypted != token
    assert "ya29" not in encrypted

    decrypted = crypto.decrypt_token(encrypted)
    assert decrypted == token


def test_token_decryption_failure():
    assert crypto.decrypt_token("invalid-ciphertext") is None
    assert crypto.decrypt_token("") is None


# -----------------------------------------------------------------------------
# 6, 7 & 8. Token Exchange & Persistence
# -----------------------------------------------------------------------------

def test_token_exchange_and_persistence(secrets, valid_credentials_dict, monkeypatch):
    creds, _ = InstalledAppCredentials.from_dict(valid_credentials_dict)

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {
        "access_token": "mock-access-token-123",
        "refresh_token": "mock-refresh-token-xyz",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": " ".join(GMAIL_SCOPES),
    }

    def fake_post(url, data=None, timeout=None):
        assert data["code"] == "test-auth-code"
        assert data["grant_type"] == "authorization_code"
        return mock_token_resp

    monkeypatch.setattr("httpx.Client.post", lambda self, url, **kwargs: fake_post(url, **kwargs))

    token_data, err = exchange_code(creds, "test-auth-code", "http://localhost:8765/oauth/callback")
    assert err == ""
    assert token_data["access_token"] == "mock-access-token-123"
    assert token_data["refresh_token"] == "mock-refresh-token-xyz"

    # Save credentials
    record = save_account_credentials(secrets, "alice@gmail.com", creds, token_data)
    assert record.email == "alice@gmail.com"
    assert record.status == GmailConnectionStatus.CONNECTED
    assert record.default is True
    assert record.needs_reauth is False

    # Check store on disk: tokens are encrypted, never plaintext
    raw_profile = secrets.get("gmail:account:alice@gmail.com")
    assert raw_profile is not None
    assert raw_profile["refresh_token_encrypted"] != "mock-refresh-token-xyz"
    assert "mock-refresh-token-xyz" not in json.dumps(raw_profile)
    assert crypto.decrypt_token(raw_profile["refresh_token_encrypted"]) == "mock-refresh-token-xyz"


def test_reconnect_preserves_existing_refresh_token(secrets, valid_credentials_dict):
    creds, _ = InstalledAppCredentials.from_dict(valid_credentials_dict)

    # Initial connect with refresh token
    initial_data = {
        "access_token": "acc-1",
        "refresh_token": "original-refresh-token",
        "expires_in": 3600,
    }
    save_account_credentials(secrets, "bob@gmail.com", creds, initial_data)

    # Reconnect without a new refresh token (standard Google reauth behavior)
    reauth_data = {
        "access_token": "acc-2",
        "expires_in": 3600,
    }
    record = save_account_credentials(secrets, "bob@gmail.com", creds, reauth_data)
    assert record.email == "bob@gmail.com"

    profile = secrets.get("gmail:account:bob@gmail.com")
    # Verify original refresh token was preserved!
    assert crypto.decrypt_token(profile["refresh_token_encrypted"]) == "original-refresh-token"
    assert profile["access_token"] == "acc-2"


# -----------------------------------------------------------------------------
# 10, 11, 12 & 13. Automatic Token Refresh, REAUTH_REQUIRED & Error Recovery
# -----------------------------------------------------------------------------

def test_reuse_unexpired_access_token_without_http(secrets, valid_credentials_dict, monkeypatch):
    creds, _ = InstalledAppCredentials.from_dict(valid_credentials_dict)
    save_account_credentials(
        secrets,
        "carol@gmail.com",
        creds,
        {"access_token": "active-token", "refresh_token": "ref-tok", "expires_in": 3600},
    )

    # Should not call HTTP
    http_called = False
    def fake_post(*args, **kwargs):
        nonlocal http_called
        http_called = True
        raise AssertionError("HTTP should not have been called for valid unexpired token!")

    monkeypatch.setattr("httpx.Client.post", fake_post)

    email, token, err = get_valid_access_token(secrets, "carol@gmail.com")
    assert err is None
    assert email == "carol@gmail.com"
    assert token == "active-token"
    assert not http_called


def test_automatic_refresh_when_expired(secrets, valid_credentials_dict, monkeypatch):
    creds, _ = InstalledAppCredentials.from_dict(valid_credentials_dict)
    save_account_credentials(
        secrets,
        "david@gmail.com",
        creds,
        {"access_token": "old-expired-token", "refresh_token": "valid-refresh-token", "expires_in": -10},
    )

    # Mock successful refresh
    mock_refresh_resp = MagicMock()
    mock_refresh_resp.status_code = 200
    mock_refresh_resp.json.return_value = {
        "access_token": "brand-new-refreshed-token",
        "expires_in": 3600,
    }

    refresh_called = False
    def fake_post(url, data=None, **kwargs):
        nonlocal refresh_called
        refresh_called = True
        assert data["grant_type"] == "refresh_token"
        assert data["refresh_token"] == "valid-refresh-token"
        return mock_refresh_resp

    monkeypatch.setattr("httpx.Client.post", lambda self, url, **kwargs: fake_post(url, **kwargs))

    email, token, err = get_valid_access_token(secrets, "david@gmail.com")
    assert err is None
    assert refresh_called
    assert email == "david@gmail.com"
    assert token == "brand-new-refreshed-token"

    # Verify updated in store
    profile = secrets.get("gmail:account:david@gmail.com")
    assert profile["access_token"] == "brand-new-refreshed-token"
    assert profile["expires"] > time.time()


def test_refresh_failure_marks_reauth_required(secrets, valid_credentials_dict, monkeypatch):
    creds, _ = InstalledAppCredentials.from_dict(valid_credentials_dict)
    save_account_credentials(
        secrets,
        "eve@gmail.com",
        creds,
        {"access_token": "expired-token", "refresh_token": "revoked-refresh-token", "expires_in": -10},
    )

    # Mock Google returning invalid_grant (revoked or expired refresh token)
    mock_revoked_resp = MagicMock()
    mock_revoked_resp.status_code = 400
    mock_revoked_resp.json.return_value = {
        "error": "invalid_grant",
        "error_description": "Token has been expired or revoked.",
    }

    monkeypatch.setattr("httpx.Client.post", lambda self, url, **kwargs: mock_revoked_resp)

    email, token, err = get_valid_access_token(secrets, "eve@gmail.com")
    assert token == ""
    assert err is not None
    assert "Gmail authorization has expired or was revoked. Reconnect Gmail." in err["error"]

    # Verify account was marked as REAUTH_REQUIRED without deleting metadata
    profile = secrets.get("gmail:account:eve@gmail.com")
    assert profile["status"] == "reauth_required"
    assert profile["needs_reauth"] is True

    # Account list reports needs_reauth
    records = list_account_records(secrets)
    eve_rec = next(r for r in records if r.email == "eve@gmail.com")
    assert eve_rec.needs_reauth is True
    assert eve_rec.status == GmailConnectionStatus.REAUTH_REQUIRED


# -----------------------------------------------------------------------------
# 15 & 16. Multi-Account Isolation & Disconnect
# -----------------------------------------------------------------------------

def test_multi_account_isolation_and_default(secrets, valid_credentials_dict):
    creds, _ = InstalledAppCredentials.from_dict(valid_credentials_dict)

    save_account_credentials(secrets, "user1@gmail.com", creds, {"access_token": "tok1", "refresh_token": "ref1"})
    save_account_credentials(secrets, "user2@gmail.com", creds, {"access_token": "tok2", "refresh_token": "ref2"})

    records = list_account_records(secrets)
    assert len(records) == 2
    assert records[0].email == "user1@gmail.com" and records[0].default is True
    assert records[1].email == "user2@gmail.com" and records[1].default is False

    # Tokens are strictly isolated
    _, tok1, _ = get_valid_access_token(secrets, "user1@gmail.com")
    _, tok2, _ = get_valid_access_token(secrets, "user2@gmail.com")
    assert tok1 == "tok1"
    assert tok2 == "tok2"

    # Default resolves to user1
    _, tok_def, _ = get_valid_access_token(secrets, "")
    assert tok_def == "tok1"

    # Disconnecting user1 moves default to user2
    res = disconnect_gmail_account(secrets, "user1@gmail.com")
    assert res["ok"] is True
    records_after = list_account_records(secrets)
    assert len(records_after) == 1
    assert records_after[0].email == "user2@gmail.com"
    assert records_after[0].default is True


# -----------------------------------------------------------------------------
# 17, 18, 19 & 20. Tool Integrations, Filters & Approval Checkpoint
# -----------------------------------------------------------------------------

def _fake_gmail_requests(monkeypatch, responses: dict[str, dict]):
    calls: list[tuple[str, str]] = []
    from cogniwork.connectors import integration_tools

    def fake_request(method, url, *, headers=None, params=None, json=None, auth=None):
        token = (headers or {}).get("Authorization", "")
        calls.append((url, token))
        for suffix, resp in responses.items():
            if suffix in url:
                return resp
        return {"error": "HTTP 404", "details": "no fake route"}

    monkeypatch.setattr(integration_tools, "_request", fake_request)
    return calls


def test_gmail_tools_with_oauth_tokens(secrets, valid_credentials_dict, monkeypatch):
    creds, _ = InstalledAppCredentials.from_dict(valid_credentials_dict)
    save_account_credentials(
        secrets,
        "worker@gmail.com",
        creds,
        {"access_token": "oauth-bearer-tok", "refresh_token": "ref-tok", "expires_in": 3600},
    )

    calls = _fake_gmail_requests(
        monkeypatch,
        {
            "/messages/msg123": {
                "ok": True,
                "data": {
                    "id": "msg123",
                    "snippet": "Hello World",
                    "payload": {"headers": [{"name": "From", "value": "alice@test.com"}]},
                },
            },
            "/messages/send": {"ok": True, "data": {"id": "sent-msg-1"}},
            "/messages": {"ok": True, "data": {"messages": [{"id": "msg123"}]}},
        },
    )

    search = _tool(secrets, "gmail_search_messages")
    read = _tool(secrets, "gmail_get_message")
    send = _tool(secrets, "gmail_send_email")

    # 17. Search tool
    res_search = search(query="is:unread")
    assert res_search["ok"] is True
    assert res_search["account"] == "worker@gmail.com"
    assert calls[0][1] == "Bearer oauth-bearer-tok"

    # 18. Read tool
    res_read = read(message_id="msg123")
    assert res_read["ok"] is True
    assert res_read["data"]["id"] == "msg123"

    # 19. Send tool
    res_send = send(to="bob@test.com", subject="Test", body="Hello")
    assert res_send["ok"] is True
    assert res_send["data"]["id"] == "sent-msg-1"

    # 20. Verify Send email tool requires approval
    tools = make_integration_tools(secrets)
    send_tool_def = next(t for t in tools if t.__name__ == "gmail_send_email")
    assert send_tool_def.__aisuite_tool_metadata__.requires_approval is True


# -----------------------------------------------------------------------------
# 21. OAuth State Mismatch & Tampering
# -----------------------------------------------------------------------------

def test_oauth_state_mismatch(valid_credentials_dict):
    creds, _ = InstalledAppCredentials.from_dict(valid_credentials_dict)
    _, real_state = build_authorization_url(creds, "http://localhost:8765/oauth/callback")

    # Mismatched/forged state is rejected
    assert get_and_consume_state("forged-state-token-12345") is None
    # Empty state is rejected
    assert get_and_consume_state("") is None

    # Real state remains valid and can be consumed
    flow = get_and_consume_state(real_state)
    assert flow is not None
    assert flow.state == real_state


# -----------------------------------------------------------------------------
# 22. Zero Token Leakage in API Endpoints & Status Payloads
# -----------------------------------------------------------------------------

def test_api_endpoints_never_leak_tokens_or_secrets(secrets, valid_credentials_dict):
    from fastapi.testclient import TestClient
    from cogniwork.server.app import create_app
    from cogniwork.server.manager import SessionManager

    creds, _ = InstalledAppCredentials.from_dict(valid_credentials_dict)
    save_account_credentials(
        secrets,
        "secure-user@gmail.com",
        creds,
        {
            "access_token": "super-secret-access-token-999",
            "refresh_token": "super-secret-refresh-token-888",
            "expires_in": 3600,
        },
    )

    manager = SessionManager(workspace=None, provider=None)
    client = TestClient(create_app(manager))

    # 1. Check /v1/connectors
    resp = client.get("/v1/connectors")
    assert resp.status_code == 200
    connectors_json = resp.text
    assert "super-secret-access-token-999" not in connectors_json
    assert "super-secret-refresh-token-888" not in connectors_json
    assert "test-secret-value" not in connectors_json

    # 2. Check /v1/connectors/gmail/accounts
    resp_accounts = client.get("/v1/connectors/gmail/accounts")
    assert resp_accounts.status_code == 200
    accounts_json = resp_accounts.text
    assert "super-secret-access-token-999" not in accounts_json
    assert "super-secret-refresh-token-888" not in accounts_json
    assert "test-secret-value" not in accounts_json

    # 3. Check SecretStore.status()
    for row in secrets.status():
        row_str = json.dumps(row)
        assert "super-secret-access-token-999" not in row_str
        assert "super-secret-refresh-token-888" not in row_str


# -----------------------------------------------------------------------------
# 23. Complete End-to-End Lifecycle Simulation
# -----------------------------------------------------------------------------

def test_complete_end_to_end_lifecycle(secrets, valid_credentials_dict, monkeypatch):
    """Full lifecycle:
    1. Fresh state: Not connected
    2. Start OAuth: Upload credentials.json & generate auth URL
    3. Google Redirect Callback: exchange code & store encrypted refresh token
    4. Search email
    5. Read message
    6. Send email with user approval
    7. Simulate token expiration -> Automatic refresh on next tool call
    8. Simulate revocation -> REAUTH_REQUIRED state
    9. Reconnect -> Restored to connected state
    """
    from fastapi.testclient import TestClient
    from cogniwork.server.app import create_app
    from cogniwork.server.manager import SessionManager

    manager = SessionManager(workspace=None, provider=None)
    client = TestClient(create_app(manager))

    # Step 1: Fresh state -> not connected
    conns = {c["name"]: c for c in client.get("/v1/connectors").json()["connectors"]}
    assert conns["gmail"]["connected"] is False

    # Step 2: Start OAuth with credentials.json
    start_resp = client.post(
        "/v1/connectors/gmail/oauth/start",
        json={"credentials": valid_credentials_dict},
    )
    assert start_resp.status_code == 200
    data = start_resp.json()
    assert data["ok"] is True
    state = data["state"]
    assert state

    # Step 3: Google redirect callback simulation
    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {
        "access_token": "live-tok-1",
        "refresh_token": "live-ref-1",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": " ".join(GMAIL_SCOPES),
    }

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 200
    mock_userinfo_resp.json.return_value = {"email": "ceo@mycompany.com"}

    def fake_post(url, data=None, **kwargs):
        if "oauth2.googleapis.com/token" in url:
            return mock_token_resp
        return MagicMock(status_code=404)

    def fake_get(url, headers=None, **kwargs):
        if "oauth2/v2/userinfo" in url or "users/me/profile" in url:
            return mock_userinfo_resp
        return MagicMock(status_code=404)

    monkeypatch.setattr("httpx.Client.post", lambda self, url, **kwargs: fake_post(url, **kwargs))
    monkeypatch.setattr("httpx.Client.get", lambda self, url, **kwargs: fake_get(url, **kwargs))

    callback_resp = client.get(f"/oauth/callback?code=mock-google-code&state={state}")
    assert callback_resp.status_code == 200
    assert "Connected" in callback_resp.text

    # Verify connected in /v1/connectors
    conns = {c["name"]: c for c in client.get("/v1/connectors").json()["connectors"]}
    assert conns["gmail"]["connected"] is True
    assert conns["gmail"]["account"] == "ceo@mycompany.com"

    # Step 4, 5, 6: Tool operations
    _fake_gmail_requests(
        monkeypatch,
        {
            "/messages/msg999": {
                "ok": True,
                "data": {
                    "id": "msg999",
                    "payload": {"headers": [{"name": "From", "value": "investor@vc.com"}]},
                },
            },
            "/messages/send": {"ok": True, "data": {"id": "sent-999"}},
            "/messages": {"ok": True, "data": {"messages": [{"id": "msg999"}]}},
        },
    )

    search = _tool(secrets, "gmail_search_messages")
    read = _tool(secrets, "gmail_get_message")
    send = _tool(secrets, "gmail_send_email")

    s_out = search("from:investor")
    assert s_out["ok"] is True
    assert s_out["account"] == "ceo@mycompany.com"

    r_out = read("msg999")
    assert r_out["ok"] is True

    send_out = send(to="investor@vc.com", subject="Update", body="Q3 results look great")
    assert send_out["ok"] is True

    # Step 7: Force access token expiration and trigger on-demand refresh
    profile = secrets.get("gmail:account:ceo@mycompany.com")
    profile["expires"] = time.time() - 100
    profile["access_token"] = "stale-access-token"
    secrets.put("gmail:account:ceo@mycompany.com", profile)

    mock_refresh_resp = MagicMock()
    mock_refresh_resp.status_code = 200
    mock_refresh_resp.json.return_value = {
        "access_token": "refreshed-live-tok-2",
        "expires_in": 3600,
    }
    monkeypatch.setattr("httpx.Client.post", lambda self, url, **kwargs: mock_refresh_resp)

    # Search again -> automatically refreshes without user intervention!
    s_out2 = search("from:investor")
    assert s_out2["ok"] is True

    updated_profile = secrets.get("gmail:account:ceo@mycompany.com")
    assert updated_profile["access_token"] == "refreshed-live-tok-2"

    # Step 8: Invalidate/revoke Google authorization
    mock_revoked_resp = MagicMock()
    mock_revoked_resp.status_code = 400
    mock_revoked_resp.json.return_value = {"error": "invalid_grant"}
    monkeypatch.setattr("httpx.Client.post", lambda self, url, **kwargs: mock_revoked_resp)

    # Expire access token again to trigger refresh attempt
    updated_profile["expires"] = time.time() - 100
    secrets.put("gmail:account:ceo@mycompany.com", updated_profile)

    # Tool invocation fails with actionable guidance
    revoked_out = search("from:investor")
    assert "error" in revoked_out
    assert "Reconnect Gmail" in revoked_out["error"]

    # Account status in API reports needs_reauth
    accounts = client.get("/v1/connectors/gmail/accounts").json()["accounts"]
    assert accounts[0]["needs_reauth"] is True
    assert accounts[0]["status"] == "reauth_required"

    # Step 9: Reconnect Gmail
    reconnect_start = client.post(
        "/v1/connectors/gmail/oauth/start",
        json={"credentials": valid_credentials_dict, "account_hint": "ceo@mycompany.com"},
    )
    re_state = reconnect_start.json()["state"]

    mock_reauth_token_resp = MagicMock()
    mock_reauth_token_resp.status_code = 200
    mock_reauth_token_resp.json.return_value = {
        "access_token": "reconnected-tok-3",
        "expires_in": 3600,
    }
    monkeypatch.setattr("httpx.Client.post", lambda self, url, **kwargs: mock_reauth_token_resp)
    monkeypatch.setattr("httpx.Client.get", lambda self, url, **kwargs: mock_userinfo_resp)

    re_callback = client.get(f"/oauth/callback?code=new-reauth-code&state={re_state}")
    assert re_callback.status_code == 200

    # Account is connected again and tools resume functioning!
    s_out3 = search("from:investor")
    assert s_out3["ok"] is True


# -----------------------------------------------------------------------------
# 24. OAuth Start Endpoint Format & Form-Data Tests
# -----------------------------------------------------------------------------

def test_oauth_start_endpoint_with_multipart_form_data(secrets, valid_credentials_dict):
    from fastapi.testclient import TestClient
    from cogniwork.server.app import create_app
    from cogniwork.server.manager import SessionManager

    manager = SessionManager(workspace=None, provider=None)
    client = TestClient(create_app(manager))

    json_bytes = json.dumps(valid_credentials_dict).encode("utf-8")
    resp = client.post(
        "/v1/connectors/gmail/oauth/start",
        files={"credentials": ("client_secret_14253977407.json", json_bytes, "application/json")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["state"]
    assert "https://accounts.google.com/o/oauth2/auth?" in data["auth_url"]
    assert "oauth/callback" in data["redirect_uri"]


def test_oauth_start_endpoint_with_json_payload(secrets, valid_credentials_dict):
    from fastapi.testclient import TestClient
    from cogniwork.server.app import create_app
    from cogniwork.server.manager import SessionManager

    manager = SessionManager(workspace=None, provider=None)
    client = TestClient(create_app(manager))

    resp = client.post(
        "/v1/connectors/gmail/oauth/start",
        json={"credentials": valid_credentials_dict, "account_hint": "test@gmail.com"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "login_hint=test%40gmail.com" in data["auth_url"]


def test_oauth_start_endpoint_rejects_empty_or_malformed(secrets):
    from fastapi.testclient import TestClient
    from cogniwork.server.app import create_app
    from cogniwork.server.manager import SessionManager

    manager = SessionManager(workspace=None, provider=None)
    client = TestClient(create_app(manager))

    resp = client.post("/v1/connectors/gmail/oauth/start", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "missing" in data["error"] or "Invalid" in data["error"]
