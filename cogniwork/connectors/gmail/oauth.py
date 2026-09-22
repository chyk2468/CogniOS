"""Google OAuth 2.0 Authorization Code flow coordinator for Gmail."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from .models import InstalledAppCredentials, OAuthFlowState

logger = logging.getLogger(__name__)

# Minimum necessary scopes for Gmail connector:
# - gmail.readonly: Search messages, read messages, read labels
# - gmail.send: Send emails as user (with user approval)
# - userinfo.email + openid: Identify connected Google account email
GMAIL_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

STATE_EXPIRATION_SECONDS = 600  # 10 minutes
FLOW_TIMEOUT_SECONDS = 300  # 5 minutes for interactive loopback wait

# In-flight OAuth states keyed by state token
_pending_states: dict[str, OAuthFlowState] = {}
# Single-slot loopback future for interactive async flow
_pending_future: asyncio.Future | None = None
_expected_future_state: str | None = None


def clean_expired_states() -> None:
    """Remove expired OAuth states."""
    now = time.time()
    expired = [
        st for st, flow in _pending_states.items()
        if now - flow.created_at > STATE_EXPIRATION_SECONDS
    ]
    for st in expired:
        _pending_states.pop(st, None)


def get_sidecar_port() -> int:
    """Get the current running port for the CogniOS sidecar server."""
    port_str = os.environ.get("COGNIWORK_PORT") or "8765"
    try:
        return int(port_str)
    except ValueError:
        return 8765


def resolve_redirect_uri(
    client_config: InstalledAppCredentials, port: int | None = None
) -> str:
    """Determine the loopback redirect URI to provide to Google.

    Google installed/desktop apps allow loopback redirects on any port when
    http://localhost or http://127.0.0.1 is configured.
    """
    actual_port = port if port is not None else get_sidecar_port()
    
    # Check if exact match with port exists in redirect_uris
    port_match = f":{actual_port}/oauth/callback"
    for uri in client_config.redirect_uris:
        if port_match in uri:
            return uri

    # Prefer http://localhost:{port}/oauth/callback if http://localhost in redirect_uris
    for uri in client_config.redirect_uris:
        parsed = urlsplit(uri)
        if parsed.hostname in ("localhost", "127.0.0.1"):
            scheme = parsed.scheme or "http"
            host = parsed.hostname
            # Use /oauth/callback path for the sidecar
            return f"{scheme}://{host}:{actual_port}/oauth/callback"

    # Fallback to first redirect URI if no loopback matched
    return client_config.redirect_uris[0] if client_config.redirect_uris else f"http://localhost:{actual_port}/oauth/callback"


def build_authorization_url(
    client_config: InstalledAppCredentials,
    redirect_uri: str,
    account_hint: str = "",
) -> tuple[str, str]:
    """Generate state, store flow record, and construct the Google OAuth URL.

    Returns (authorization_url, state).
    """
    clean_expired_states()
    state = secrets.token_urlsafe(32)
    flow = OAuthFlowState(
        state=state,
        client_config=client_config,
        redirect_uri=redirect_uri,
        created_at=time.time(),
        account_hint=account_hint,
    )
    _pending_states[state] = flow

    params: dict[str, str] = {
        "client_id": client_config.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(GMAIL_SCOPES),
        "access_type": "offline",  # Requests refresh token
        "prompt": "consent",       # Forces refresh token generation
        "state": state,
    }
    if account_hint:
        params["login_hint"] = account_hint

    auth_url = f"{client_config.auth_uri}?{urlencode(params)}"
    return auth_url, state


def get_and_consume_state(state: str) -> OAuthFlowState | None:
    """Validate and consume in-flight OAuth state to prevent replay attacks."""
    clean_expired_states()
    if not state:
        return None
    flow = _pending_states.pop(state, None)
    if flow is None:
        return None
    if time.time() - flow.created_at > STATE_EXPIRATION_SECONDS:
        return None
    return flow


def exchange_code(
    client_config: InstalledAppCredentials,
    code: str,
    redirect_uri: str,
) -> tuple[dict[str, Any] | None, str]:
    """Exchange authorization code for tokens at Google's token_uri.

    Returns (token_response_dict, error_message).
    """
    if not code:
        return None, "Missing authorization code from Google."

    payload = {
        "code": code,
        "client_id": client_config.client_id,
        "client_secret": client_config.client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(client_config.token_uri, data=payload)
            data = resp.json()
    except Exception as exc:
        logger.error("Failed to connect to Google token endpoint: %s", type(exc).__name__)
        return None, "Failed to connect to Google token endpoint."

    if resp.status_code != 200 or not isinstance(data, dict):
        err_desc = (
            data.get("error_description")
            or data.get("error")
            or f"HTTP {resp.status_code}"
            if isinstance(data, dict)
            else f"HTTP {resp.status_code}"
        )
        logger.warning("Token exchange failed: %s", err_desc)
        return None, f"Google token exchange failed: {err_desc}"

    if "access_token" not in data:
        return None, "Google token response did not contain an access token."

    return data, ""


def fetch_account_email(access_token: str) -> tuple[str, str]:
    """Fetch the authenticated user's email address from Google userinfo / Gmail profile.

    Returns (email, error_message).
    """
    if not access_token:
        return "", "Missing access token."

    headers = {"Authorization": f"Bearer {access_token}"}
    
    # 1. Try Google OAuth2 userinfo endpoint
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get("https://www.googleapis.com/oauth2/v2/userinfo", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                email = str(data.get("email") or "").strip().lower()
                if email:
                    return email, ""
    except Exception:
        pass

    # 2. Fallback to Gmail user profile endpoint
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/profile",
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                email = str(data.get("emailAddress") or "").strip().lower()
                if email:
                    return email, ""
    except Exception as exc:
        logger.error("Failed to fetch Gmail profile: %s", type(exc).__name__)

    return "", "Could not retrieve Google account email address."


# -- Loopback async waiting helpers -------------------------------------------

def deliver_loopback_callback(code: str, state: str) -> bool:
    """Deliver callback result to waiting async task if one is pending with matching state."""
    global _pending_future, _expected_future_state
    if _pending_future is None or _pending_future.done():
        return False
    if _expected_future_state and not secrets.compare_digest(state, _expected_future_state):
        return False
    fut, _pending_future = _pending_future, None
    _expected_future_state = None
    fut.set_result((code, state))
    return True


async def wait_for_callback(expected_state: str, timeout: float = FLOW_TIMEOUT_SECONDS) -> tuple[str, str]:
    """Async wait for the loopback callback with the expected state."""
    global _pending_future, _expected_future_state
    if _pending_future is not None and not _pending_future.done():
        _pending_future.cancel()
    _pending_future = asyncio.get_running_loop().create_future()
    _expected_future_state = expected_state
    try:
        return await asyncio.wait_for(_pending_future, timeout=timeout)
    except asyncio.TimeoutError:
        raise RuntimeError("Google sign-in timed out. Please try connecting again.")
    finally:
        _pending_future = None
        _expected_future_state = None
