"""Authentication — single owner, 2FA, sessions, password recovery."""

from __future__ import annotations

import pyotp
import pytest
from fastapi.testclient import TestClient

from cogniwork.server.app import create_app
from cogniwork.server.manager import SessionManager


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIWORK_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("COGNIWORK_API_TOKEN", raising=False)
    monkeypatch.delenv("COGNIWORK_AUTH_DISABLED", raising=False)
    mgr = SessionManager(workspace=tmp_path / "workspace", data_dir=tmp_path / "state")
    app = create_app(mgr)
    with TestClient(app) as client:
        yield client


def _signup(client: TestClient, *, username: str = "alice", email: str = "alice@example.com") -> dict:
    res = client.post(
        "/v1/auth/signup",
        json={
            "full_name": "Alice Example",
            "username": username,
            "email": email,
            "password": "Secret123",
            "confirm_password": "Secret123",
            "favorite_pet": "Frog",
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def _signin(client: TestClient) -> None:
    res = client.post(
        "/v1/auth/signin",
        json={"identifier": "alice", "password": "Secret123"},
    )
    assert res.status_code == 200, res.text


def test_status_and_single_owner(auth_client: TestClient):
    st = auth_client.get("/v1/auth/status").json()
    assert st["owner_exists"] is False
    assert st["signup_allowed"] is True

    _signup(auth_client)

    st2 = auth_client.get("/v1/auth/status").json()
    assert st2["owner_exists"] is True
    assert st2["signup_allowed"] is False

    blocked = auth_client.post(
        "/v1/auth/signup",
        json={
            "full_name": "Bob",
            "username": "bob",
            "email": "bob@example.com",
            "password": "Secret123",
            "confirm_password": "Secret123",
            "favorite_pet": "Cat",
        },
    )
    assert blocked.status_code == 403


def test_signup_signin_me_signout_flow(auth_client: TestClient):
    client = auth_client
    data = _signup(client)
    assert data["user"]["username"] == "alice"

    me = client.get("/v1/auth/me")
    assert me.json()["authenticated"] is False

    _signin(client)
    me = client.get("/v1/auth/me")
    assert me.json()["authenticated"] is True

    client.post("/v1/auth/signout")
    assert client.get("/v1/auth/me").json()["authenticated"] is False

    bad = client.post("/v1/auth/signin", json={"identifier": "alice", "password": "wrong"})
    assert bad.status_code == 401

    ok = client.post("/v1/auth/signin", json={"identifier": "alice@example.com", "password": "Secret123"})
    assert ok.status_code == 200
    assert client.get("/v1/sessions").status_code == 200


def test_unauthenticated_api_blocked(auth_client: TestClient):
    assert auth_client.get("/v1/sessions").status_code == 401


def test_forgot_password_flow(auth_client: TestClient):
    _signup(auth_client)
    _signin(auth_client)

    start = auth_client.post("/v1/auth/forgot-password/start", json={"identifier": "alice"})
    token = start.json()["token"]

    bad = auth_client.post(
        "/v1/auth/forgot-password/verify-pet",
        json={"token": token, "pet_answer": "Dog"},
    )
    assert bad.status_code == 401

    good = auth_client.post(
        "/v1/auth/forgot-password/verify-pet",
        json={"token": token, "pet_answer": " frog "},
    )
    reset_token = good.json()["reset_token"]

    reset = auth_client.post(
        "/v1/auth/forgot-password/reset",
        json={"reset_token": reset_token, "password": "NewSecret456", "confirm_password": "NewSecret456"},
    )
    assert reset.status_code == 200

    assert auth_client.post("/v1/auth/signin", json={"identifier": "alice", "password": "Secret123"}).status_code == 401
    assert auth_client.post("/v1/auth/signin", json={"identifier": "alice", "password": "NewSecret456"}).status_code == 200


def test_totp_login_flow(auth_client: TestClient):
    _signup(auth_client)
    _signin(auth_client)

    setup = auth_client.post("/v1/auth/totp/setup")
    assert setup.status_code == 200
    body = setup.json()
    secret = body["manual_key"]
    uri = body["otpauth_uri"]
    assert "CogniOS:alice" in uri or "CogniOS%3Aalice" in uri
    assert "alice@example.com" not in uri
    assert "issuer=CogniOS" in uri
    code = pyotp.TOTP(secret).now()

    enabled = auth_client.post(
        "/v1/auth/totp/verify-setup",
        json={"setup_token": body["setup_token"], "code": code},
    )
    assert enabled.status_code == 200

    auth_client.post("/v1/auth/signout")

    step1 = auth_client.post("/v1/auth/signin", json={"identifier": "alice", "password": "Secret123"})
    assert step1.status_code == 200
    assert step1.json()["requires_totp"] is True
    challenge = step1.json()["challenge_token"]

    bad = auth_client.post("/v1/auth/signin/totp", json={"challenge_token": challenge, "code": "000000"})
    assert bad.status_code == 401
    assert auth_client.get("/v1/sessions").status_code == 401

    good = auth_client.post(
        "/v1/auth/signin/totp",
        json={"challenge_token": challenge, "code": pyotp.TOTP(secret).now()},
    )
    assert good.status_code == 200
    assert auth_client.get("/v1/sessions").status_code == 200


def test_change_password_invalidates_session(auth_client: TestClient):
    _signup(auth_client)
    _signin(auth_client)

    res = auth_client.post(
        "/v1/auth/account/password",
        json={
            "current_password": "Secret123",
            "password": "NewSecret456",
            "confirm_password": "NewSecret456",
        },
    )
    assert res.status_code == 200
    assert auth_client.get("/v1/auth/me").json()["authenticated"] is False

    assert auth_client.post("/v1/auth/signin", json={"identifier": "alice", "password": "NewSecret456"}).status_code == 200


def test_remove_account_resets_application(auth_client: TestClient):
    _signup(auth_client)
    _signin(auth_client)

    assert auth_client.get("/v1/auth/status").json()["owner_exists"] is True
    assert auth_client.get("/v1/sessions").status_code == 200

    bad = auth_client.post(
        "/v1/auth/account/remove",
        json={"confirmation": "NOPE", "current_password": "Secret123"},
    )
    assert bad.status_code == 400

    wrong_pw = auth_client.post(
        "/v1/auth/account/remove",
        json={"confirmation": "DELETE", "current_password": "wrong"},
    )
    assert wrong_pw.status_code == 401

    ok = auth_client.post(
        "/v1/auth/account/remove",
        json={"confirmation": "DELETE", "current_password": "Secret123"},
    )
    assert ok.status_code == 200
    assert ok.json()["owner_exists"] is False

    assert auth_client.get("/v1/auth/me").json()["authenticated"] is False
    assert auth_client.get("/v1/auth/status").json()["signup_allowed"] is True
    assert auth_client.get("/v1/sessions").status_code == 401

    blocked = auth_client.post(
        "/v1/auth/signup",
        json={
            "full_name": "Bob",
            "username": "bob",
            "email": "bob@example.com",
            "password": "Secret123",
            "confirm_password": "Secret123",
            "favorite_pet": "Cat",
        },
    )
    assert blocked.status_code == 200
    assert auth_client.get("/v1/auth/status").json()["owner_exists"] is True

    dup = auth_client.post(
        "/v1/auth/signup",
        json={
            "full_name": "Carol",
            "username": "carol",
            "email": "carol@example.com",
            "password": "Secret123",
            "confirm_password": "Secret123",
            "favorite_pet": "Dog",
        },
    )
    assert dup.status_code == 403
