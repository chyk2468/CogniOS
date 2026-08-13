"""Authentication — signup, signin, sessions, password recovery."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from coworker.server.app import create_app
from coworker.server.manager import SessionManager


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("COWORKER_API_TOKEN", raising=False)
    monkeypatch.delenv("COWORKER_AUTH_DISABLED", raising=False)
    mgr = SessionManager(workspace=tmp_path / "workspace")
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


def test_signup_signin_me_signout_flow(auth_client: TestClient):
    client = auth_client
    data = _signup(client)
    assert data["user"]["username"] == "alice"
    assert "password" not in data["user"]
    assert "password_hash" not in data

    me = client.get("/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["authenticated"] is True

    client.post("/v1/auth/signout")
    me2 = client.get("/v1/auth/me")
    assert me2.json()["authenticated"] is False

    bad = client.post(
        "/v1/auth/signin",
        json={"identifier": "alice", "password": "wrong"},
    )
    assert bad.status_code == 401
    assert "password" in bad.json()["error"].lower() or "invalid" in bad.json()["error"].lower()

    ok = client.post(
        "/v1/auth/signin",
        json={"identifier": "alice@example.com", "password": "Secret123"},
    )
    assert ok.status_code == 200

    protected = client.get("/v1/sessions")
    assert protected.status_code == 200


def test_unauthenticated_api_blocked(auth_client: TestClient):
    res = auth_client.get("/v1/sessions")
    assert res.status_code == 401


def test_duplicate_username_and_email(auth_client: TestClient):
    _signup(auth_client)
    dup_user = auth_client.post(
        "/v1/auth/signup",
        json={
            "full_name": "Bob",
            "username": "alice",
            "email": "bob@example.com",
            "password": "Secret123",
            "confirm_password": "Secret123",
            "favorite_pet": "Cat",
        },
    )
    assert dup_user.status_code == 400
    assert "username" in dup_user.json()["fields"]

    dup_email = auth_client.post(
        "/v1/auth/signup",
        json={
            "full_name": "Bob",
            "username": "bob",
            "email": "alice@example.com",
            "password": "Secret123",
            "confirm_password": "Secret123",
            "favorite_pet": "Cat",
        },
    )
    assert dup_email.status_code == 400
    assert "email" in dup_email.json()["fields"]


def test_forgot_password_flow(auth_client: TestClient):
    _signup(auth_client)
    auth_client.post("/v1/auth/signout")

    start = auth_client.post(
        "/v1/auth/forgot-password/start",
        json={"identifier": "alice"},
    )
    assert start.status_code == 200
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
    assert good.status_code == 200
    reset_token = good.json()["reset_token"]

    reset = auth_client.post(
        "/v1/auth/forgot-password/reset",
        json={
            "reset_token": reset_token,
            "password": "NewSecret456",
            "confirm_password": "NewSecret456",
        },
    )
    assert reset.status_code == 200

    old = auth_client.post(
        "/v1/auth/signin",
        json={"identifier": "alice", "password": "Secret123"},
    )
    assert old.status_code == 401

    new = auth_client.post(
        "/v1/auth/signin",
        json={"identifier": "alice", "password": "NewSecret456"},
    )
    assert new.status_code == 200


def test_forgot_password_no_enumeration(auth_client: TestClient):
    start = auth_client.post(
        "/v1/auth/forgot-password/start",
        json={"identifier": "nobody"},
    )
    assert start.status_code == 200
    token = start.json()["token"]
    verify = auth_client.post(
        "/v1/auth/forgot-password/verify-pet",
        json={"token": token, "pet_answer": "anything"},
    )
    assert verify.status_code == 401
