"""Data models for Gmail OAuth 2.0 and account connections."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GmailConnectionStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    REAUTH_REQUIRED = "reauth_required"
    ERROR = "error"
    CONNECTING = "connecting"
    REFRESHING = "refreshing"


@dataclass
class InstalledAppCredentials:
    """Parsed and validated Google OAuth client configuration from credentials.json."""
    client_id: str
    client_secret: str
    auth_uri: str
    token_uri: str
    redirect_uris: list[str]
    project_id: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> tuple[InstalledAppCredentials | None, str]:
        """Validate and parse a Google OAuth credentials dict.

        Returns (credentials, error_message).
        """
        if not isinstance(data, dict):
            return None, "Invalid Google OAuth credentials file: root must be a JSON object."

        # Handle nested {"credentials": {...}} wrappers
        if "credentials" in data and isinstance(data["credentials"], dict):
            data = data["credentials"]

        # Google installed application JSON has a top-level "installed" (or sometimes "web") object
        config = data.get("installed")
        if not isinstance(config, dict):
            if isinstance(data.get("web"), dict):
                return None, "Invalid credentials file: Desktop application OAuth client ('installed') is required, not 'web'."
            # Check if fields were provided directly at root level
            if data.get("client_id") and data.get("client_secret"):
                config = data
            else:
                return None, "Invalid Google OAuth credentials file: missing top-level 'installed' object."

        client_id = str(config.get("client_id") or "").strip()
        client_secret = str(config.get("client_secret") or "").strip()
        auth_uri = str(config.get("auth_uri") or "https://accounts.google.com/o/oauth2/auth").strip()
        token_uri = str(config.get("token_uri") or "https://oauth2.googleapis.com/token").strip()
        raw_redirect_uris = config.get("redirect_uris")
        project_id = str(config.get("project_id") or "").strip()

        if not client_id:
            return None, "Invalid Google OAuth credentials file: missing 'client_id'."
        if not client_secret:
            return None, "Invalid Google OAuth credentials file: missing 'client_secret'."
        if not auth_uri or not auth_uri.startswith(("https://", "http://")):
            return None, "Invalid Google OAuth credentials file: missing or invalid 'auth_uri'."
        if not token_uri or not token_uri.startswith(("https://", "http://")):
            return None, "Invalid Google OAuth credentials file: missing or invalid 'token_uri'."

        # Normalize redirect URIs list; default to loopback if omitted in Google Cloud JSON
        redirect_uris: list[str] = []
        if isinstance(raw_redirect_uris, list):
            redirect_uris = [str(u).strip() for u in raw_redirect_uris if str(u).strip()]
        elif isinstance(raw_redirect_uris, str) and raw_redirect_uris.strip():
            redirect_uris = [raw_redirect_uris.strip()]

        if not redirect_uris or not any(
            uri.startswith("http://localhost") or uri.startswith("http://127.0.0.1")
            for uri in redirect_uris
        ):
            redirect_uris.insert(0, "http://localhost")

        return cls(
            client_id=client_id,
            client_secret=client_secret,
            auth_uri=auth_uri,
            token_uri=token_uri,
            redirect_uris=redirect_uris,
            project_id=project_id,
        ), ""


@dataclass
class OAuthFlowState:
    """State tracking for an in-flight OAuth authorization flow."""
    state: str
    client_config: InstalledAppCredentials
    redirect_uri: str
    created_at: float
    account_hint: str = ""  # If reconnecting a specific account


@dataclass
class GmailAccountRecord:
    """Safe, non-secret representation of a Gmail connection profile."""
    email: str
    status: GmailConnectionStatus
    scopes: str
    default: bool = False
    needs_reauth: bool = False
    created_at: float = 0.0
    updated_at: float = 0.0
    last_refresh_at: float = 0.0
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        """User-safe dictionary representation (NEVER contains tokens or secrets)."""
        return {
            "email": self.email,
            "status": self.status.value,
            "scopes": self.scopes,
            "default": self.default,
            "needs_reauth": self.needs_reauth or (self.status == GmailConnectionStatus.REAUTH_REQUIRED),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_refresh_at": self.last_refresh_at,
            "error_message": self.error_message,
        }
