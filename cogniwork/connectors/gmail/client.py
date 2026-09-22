"""Centralized Gmail REST API client."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ...secrets import SecretStore
from . import credentials

logger = logging.getLogger(__name__)

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailClient:
    """Client for performing authenticated operations against Google's Gmail API."""

    def __init__(self, secrets: SecretStore, account: str = "") -> None:
        self.secrets = secrets
        self.account = account

    def _auth_headers(self) -> tuple[str, dict[str, str], dict[str, str] | None]:
        """Obtain valid access token and construct Authorization header."""
        email, token, err = credentials.get_valid_access_token(self.secrets, self.account)
        if err:
            return email, {}, err
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        return email, headers, None

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute an API request against the Gmail API with token injection."""
        email, headers, err = self._auth_headers()
        if err:
            return err

        url = f"{GMAIL_API_BASE}/{path.lstrip('/')}" if not path.startswith("http") else path
        try:
            with httpx.Client(timeout=25) as client:
                resp = client.request(method, url, headers=headers, params=params, json=json_data)
                
                # Check for 401 Unauthorized (e.g. revoked token during request)
                if resp.status_code == 401:
                    logger.warning("Gmail API returned 401 Unauthorized for %s, flagging reauth required", email)
                    credentials.mark_reauth_required(self.secrets, email, "Google returned 401 Unauthorized.")
                    return {"error": "Gmail authorization has expired or was revoked. Reconnect Gmail."}

                try:
                    data = resp.json()
                except Exception:
                    data = {}

                if resp.status_code >= 400:
                    err_msg = ""
                    if isinstance(data, dict):
                        err_obj = data.get("error")
                        if isinstance(err_obj, dict):
                            err_msg = err_obj.get("message", "")
                        elif isinstance(err_obj, str):
                            err_msg = err_obj
                    return {
                        "error": f"HTTP {resp.status_code}",
                        "details": {"error": {"code": resp.status_code, "message": err_msg or f"HTTP {resp.status_code}"}},
                    }

                return {"ok": True, "data": data, "account": email}

        except Exception as exc:
            logger.error("Error communicating with Gmail API: %s", type(exc).__name__)
            return {"error": "Failed to communicate with Gmail service."}

    def search_messages(self, query: str, max_results: int = 10) -> dict[str, Any]:
        """Search messages matching a query string."""
        return self._request(
            "GET",
            "messages",
            params={"q": query, "maxResults": max(1, min(int(max_results or 10), 20))},
        )

    def get_message(self, message_id: str, format_type: str = "full") -> dict[str, Any]:
        """Fetch a specific message by ID."""
        return self._request(
            "GET",
            f"messages/{message_id}",
            params={"format": format_type},
        )

    def get_message_metadata(self, message_id: str, headers: list[str]) -> dict[str, Any]:
        """Fetch message metadata headers."""
        return self._request(
            "GET",
            f"messages/{message_id}",
            params={"format": "metadata", "metadataHeaders": headers},
        )

    def get_labels(self) -> dict[str, str]:
        """Fetch label mapping (id -> name) for the connected mailbox."""
        result = self._request("GET", "labels")
        if not result.get("ok"):
            return {}
        labels = (result.get("data") or {}).get("labels") or []
        return {str(l.get("id") or ""): str(l.get("name") or "") for l in labels}

    def send_message(self, raw_b64: str) -> dict[str, Any]:
        """Send a MIME email message encoded as URL-safe base64."""
        return self._request(
            "POST",
            "messages/send",
            json_data={"raw": raw_b64},
        )

    def get_profile(self) -> dict[str, Any]:
        """Fetch the user's Gmail profile."""
        return self._request("GET", "profile")
