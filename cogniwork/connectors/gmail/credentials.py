"""Credential Manager for Gmail OAuth connections.

Handles:
- Encrypted storage of refresh tokens and client secrets at rest
- On-demand automatic access-token refresh
- Graceful detection of revoked/expired refresh tokens (REAUTH_REQUIRED state)
- Preserving refresh tokens when Google reauthorization does not return a new one
- Multi-account isolation
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from ...secrets import SecretStore
from . import crypto
from .models import GmailAccountRecord, GmailConnectionStatus, InstalledAppCredentials

logger = logging.getLogger(__name__)

PREFIX = "gmail:account:"
DEFAULT_KEY = "gmail:default"
SAFETY_MARGIN_SECONDS = 60  # Refresh if within 60s of expiry


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def list_account_records(secrets: SecretStore) -> list[GmailAccountRecord]:
    """Return all connected Gmail accounts as safe GmailAccountRecord objects (no secrets)."""
    default_email = get_default_account_email(secrets)
    out: list[GmailAccountRecord] = []
    
    for meta in secrets.status():
        key = meta.get("profile", "")
        if key.startswith(PREFIX):
            email = key[len(PREFIX) :]
            profile = secrets.get(key) or {}
            
            raw_status = profile.get("status")
            try:
                status = GmailConnectionStatus(raw_status)
            except (ValueError, TypeError):
                status = GmailConnectionStatus.CONNECTED if profile.get("access_token") else GmailConnectionStatus.ERROR

            expires = float(profile.get("expires") or 0)
            has_refresh = bool(profile.get("refresh_token_encrypted") or profile.get("refresh_token"))
            expired_unrefreshable = bool(expires and expires < time.time() and not has_refresh)
            
            needs_reauth = bool(
                profile.get("needs_reauth")
                or status == GmailConnectionStatus.REAUTH_REQUIRED
                or expired_unrefreshable
            )

            out.append(
                GmailAccountRecord(
                    email=email,
                    status=GmailConnectionStatus.REAUTH_REQUIRED if needs_reauth else status,
                    scopes=str(profile.get("scope") or ""),
                    default=email == default_email,
                    needs_reauth=needs_reauth,
                    created_at=float(profile.get("created_at") or 0.0),
                    updated_at=float(profile.get("updated_at") or 0.0),
                    last_refresh_at=float(profile.get("last_refresh_at") or 0.0),
                    error_message=str(profile.get("error_message") or ""),
                )
            )
    return sorted(out, key=lambda a: a.email)


def get_default_account_email(secrets: SecretStore) -> str:
    """Return the default connected Gmail account email."""
    pointer = _norm((secrets.get(DEFAULT_KEY) or {}).get("default_account"))
    if pointer and secrets.get(PREFIX + pointer):
        return pointer
    
    # Fallback to the first connected account
    for meta in secrets.status():
        key = meta.get("profile", "")
        if key.startswith(PREFIX):
            return key[len(PREFIX) :]
    return ""


def save_account_credentials(
    secrets: SecretStore,
    email: str,
    client_config: InstalledAppCredentials,
    token_data: dict[str, Any],
) -> GmailAccountRecord:
    """Store/update a connected Google account with encrypted refresh token.

    If Google did not return a new refresh token on reauthorization, preserves
    the existing encrypted refresh token for this email.
    """
    email = _norm(email)
    key = PREFIX + email
    existing_profile = secrets.get(key) or {}

    # Extract tokens
    new_refresh = str(token_data.get("refresh_token") or "").strip()
    existing_encrypted_refresh = existing_profile.get("refresh_token_encrypted") or ""

    if new_refresh:
        encrypted_refresh = crypto.encrypt_token(new_refresh)
    elif existing_encrypted_refresh:
        encrypted_refresh = existing_encrypted_refresh
    elif existing_profile.get("refresh_token"):
        # Upgrade legacy plaintext refresh token to encrypted
        encrypted_refresh = crypto.encrypt_token(existing_profile["refresh_token"])
    else:
        encrypted_refresh = ""

    encrypted_client_secret = crypto.encrypt_token(client_config.client_secret)
    access_token = str(token_data.get("access_token") or existing_profile.get("access_token") or "").strip()
    expires_in = float(token_data.get("expires_in") or 3600)
    now = time.time()

    profile: dict[str, Any] = {
        "type": "oauth",
        "account": email,
        "status": GmailConnectionStatus.CONNECTED.value,
        "client_id": client_config.client_id,
        "client_secret_encrypted": encrypted_client_secret,
        "auth_uri": client_config.auth_uri,
        "token_uri": client_config.token_uri,
        "redirect_uris": client_config.redirect_uris,
        "project_id": client_config.project_id,
        "refresh_token_encrypted": encrypted_refresh,
        "access_token": access_token,
        "expires": now + expires_in,
        "scope": str(token_data.get("scope") or existing_profile.get("scope") or ""),
        "created_at": float(existing_profile.get("created_at") or now),
        "updated_at": now,
        "last_refresh_at": now,
        "needs_reauth": False,
        "error_message": "",
        "enabled": True,
    }
    secrets.put(key, profile)

    # Update default account pointer
    pointer = secrets.get(DEFAULT_KEY) or {}
    pointer.setdefault("default_account", email)
    pointer.update({"type": "oauth", "enabled": True})
    secrets.put(DEFAULT_KEY, pointer)

    return GmailAccountRecord(
        email=email,
        status=GmailConnectionStatus.CONNECTED,
        scopes=profile["scope"],
        default=(email == pointer.get("default_account")),
        needs_reauth=False,
        created_at=profile["created_at"],
        updated_at=profile["updated_at"],
        last_refresh_at=profile["last_refresh_at"],
    )


def mark_reauth_required(
    secrets: SecretStore, email: str, reason: str = "Authorization has expired or was revoked."
) -> None:
    """Flag a connection as REAUTH_REQUIRED without wiping identity metadata."""
    email = _norm(email)
    key = PREFIX + email
    profile = secrets.get(key)
    if not profile:
        return
    profile["status"] = GmailConnectionStatus.REAUTH_REQUIRED.value
    profile["needs_reauth"] = True
    profile["error_message"] = reason
    profile["updated_at"] = time.time()
    secrets.put(key, profile)


def get_valid_access_token(
    secrets: SecretStore, account: str = ""
) -> tuple[str, str, dict[str, str] | None]:
    """Retrieve an active access token for the requested (or default) Gmail account.

    Automatically refreshes the token on demand using the stored encrypted refresh token
    if the cached access token is expired or close to expiration.

    Returns: (email, access_token, error_dict)
    """
    email = _norm(account) or get_default_account_email(secrets)
    if not email:
        hint = f"no gmail account matching {account!r}" if account else "gmail is not connected"
        return "", "", {"error": hint}

    key = PREFIX + email
    profile = secrets.get(key)
    if not profile:
        hint = f"no gmail account matching {account!r}" if account else "gmail is not connected"
        return "", "", {"error": hint}

    # If already marked as requiring reauthorization, fail fast with actionable guidance
    if profile.get("status") == GmailConnectionStatus.REAUTH_REQUIRED.value or profile.get("needs_reauth"):
        return email, "", {"error": "Gmail authorization has expired or was revoked. Reconnect Gmail."}

    access_token = str(profile.get("access_token") or "").strip()
    expires = float(profile.get("expires") or 0)
    now = time.time()

    # 1. Reuse valid unexpired access token (expires == 0 indicates a legacy / static test token)
    if access_token and (expires == 0 or expires > now + SAFETY_MARGIN_SECONDS):
        return email, access_token, None

    # 2. Token is missing or expired -> attempt on-demand refresh
    encrypted_refresh = profile.get("refresh_token_encrypted") or ""
    refresh_token = crypto.decrypt_token(encrypted_refresh) if encrypted_refresh else ""

    # Legacy plaintext fallback if unmigrated
    if not refresh_token and profile.get("refresh_token"):
        refresh_token = str(profile["refresh_token"]).strip()

    if not refresh_token:
        # Cannot refresh silently
        mark_reauth_required(secrets, email, "No refresh token available.")
        return email, "", {"error": "Gmail authorization has expired or was revoked. Reconnect Gmail."}

    client_id = str(profile.get("client_id") or "").strip()
    encrypted_secret = profile.get("client_secret_encrypted") or ""
    client_secret = crypto.decrypt_token(encrypted_secret) if encrypted_secret else ""
    if not client_secret and profile.get("client_secret"):
        client_secret = str(profile["client_secret"]).strip()

    token_uri = str(profile.get("token_uri") or "https://oauth2.googleapis.com/token").strip()

    if not client_id or not client_secret:
        mark_reauth_required(secrets, email, "Missing OAuth client credentials.")
        return email, "", {"error": "Gmail authorization configuration is incomplete. Reconnect Gmail."}

    # Execute refresh request against Google token endpoint
    refresh_payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    try:
        with httpx.Client(timeout=20) as client:
            resp = client.post(token_uri, data=refresh_payload)
            data = resp.json()
    except Exception as exc:
        logger.error("Network error during Gmail token refresh for %s: %s", email, type(exc).__name__)
        return email, "", {"error": "Could not connect to Google to refresh Gmail access token."}

    if resp.status_code != 200 or not isinstance(data, dict) or "access_token" not in data:
        error_code = data.get("error") if isinstance(data, dict) else ""
        error_desc = data.get("error_description") if isinstance(data, dict) else ""
        logger.warning(
            "Gmail token refresh failed for %s: HTTP %s (error=%s, desc=%s)",
            email, resp.status_code, error_code, error_desc
        )
        if error_code in ("invalid_grant", "unauthorized_client") or resp.status_code in (400, 401):
            mark_reauth_required(secrets, email, f"Token refresh rejected by Google ({error_code or 'invalid_grant'}).")
            return email, "", {"error": "Gmail authorization has expired or was revoked. Reconnect Gmail."}
        return email, "", {"error": f"Failed to refresh Gmail access token: {error_desc or 'Google error'}."}

    # Refresh succeeded: update stored cached credentials
    new_access_token = str(data["access_token"]).strip()
    new_expires_in = float(data.get("expires_in") or 3600)
    
    profile["access_token"] = new_access_token
    profile["expires"] = now + new_expires_in
    profile["last_refresh_at"] = now
    profile["status"] = GmailConnectionStatus.CONNECTED.value
    profile["needs_reauth"] = False
    profile["error_message"] = ""

    # If Google returned a rotated new refresh token, encrypt and store it
    if data.get("refresh_token"):
        profile["refresh_token_encrypted"] = crypto.encrypt_token(str(data["refresh_token"]).strip())

    secrets.put(key, profile)
    return email, new_access_token, None


def disconnect_gmail_account(secrets: SecretStore, email: str) -> dict[str, Any]:
    """Drop one mailbox and securely wipe its stored encrypted credentials."""
    email = _norm(email)
    key = PREFIX + email
    if not secrets.get(key):
        return {"ok": False, "error": "account not connected"}
    
    secrets.delete(key)
    
    remaining = [rec.email for rec in list_account_records(secrets)]
    pointer = secrets.get(DEFAULT_KEY) or {}
    
    if _norm(pointer.get("default_account")) == email:
        if remaining:
            pointer["default_account"] = remaining[0]
            secrets.put(DEFAULT_KEY, pointer)
        else:
            pointer.pop("default_account", None)
            pointer.pop("managed", None)
            if pointer.get("filters"):
                secrets.put(DEFAULT_KEY, pointer)
            else:
                secrets.delete(DEFAULT_KEY)
                
    return {"ok": True, "remaining_accounts": len(remaining)}
