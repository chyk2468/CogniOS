"""FastAPI routes for Gmail OAuth flow and account management."""

from __future__ import annotations

import asyncio
import logging
import webbrowser
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ...secrets import SecretStore
from . import credentials, oauth
from .models import InstalledAppCredentials

logger = logging.getLogger(__name__)


def create_gmail_router(secrets_store: SecretStore, browser_page_renderer: Any) -> APIRouter:
    """Create and configure the Gmail connector API router."""
    router = APIRouter()

    @router.post("/v1/connectors/gmail/oauth/start")
    async def start_oauth(request: Request) -> dict[str, Any]:
        """Start the Google OAuth 2.0 Authorization Code flow with credentials.json."""
        raw_creds = None
        account_hint = ""

        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                body = await request.json()
                if isinstance(body, dict):
                    raw_creds = body.get("credentials") or body
                    account_hint = str(body.get("account_hint") or "").strip()
                elif isinstance(body, str):
                    import json
                    raw_creds = json.loads(body)
            except Exception as e:
                logger.warning("Failed to parse JSON body in oauth/start: %s", e)
                return {"ok": False, "error": f"Invalid JSON payload: {e}"}
        elif "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
            try:
                form = await request.form()
                account_hint = str(form.get("account_hint") or "").strip()
                file_item = form.get("credentials") or form.get("file")
                import json
                if hasattr(file_item, "read"):
                    content = await file_item.read()
                    text = content.decode("utf-8-sig")
                    raw_creds = json.loads(text)
                elif isinstance(file_item, str):
                    raw_creds = json.loads(file_item)
            except Exception as e:
                logger.warning("Failed to parse form data in oauth/start: %s", e)
                return {"ok": False, "error": f"Invalid form data: {e}"}
        else:
            try:
                body = await request.json()
                raw_creds = body.get("credentials") if isinstance(body, dict) and "credentials" in body else body
                account_hint = str(body.get("account_hint") or "").strip() if isinstance(body, dict) else ""
            except Exception:
                try:
                    import json
                    body_bytes = await request.body()
                    if body_bytes:
                        raw_creds = json.loads(body_bytes.decode("utf-8-sig"))
                except Exception as e:
                    return {"ok": False, "error": f"Unsupported content type or empty body: {e}"}

        if raw_creds is None:
            return {"ok": False, "error": "No credentials data provided in request."}

        client_config, err = InstalledAppCredentials.from_dict(raw_creds)
        if err or client_config is None:
            logger.warning("Failed to parse Google OAuth credentials: %s", err)
            return {"ok": False, "error": err or "Invalid Google OAuth credentials."}

        port = request.url.port or oauth.get_sidecar_port()
        redirect_uri = oauth.resolve_redirect_uri(client_config, port=port)
        auth_url, state = oauth.build_authorization_url(
            client_config=client_config,
            redirect_uri=redirect_uri,
            account_hint=account_hint,
        )

        from urllib.parse import urlsplit
        logger.info(
            "Gmail OAuth start: credentials_type=installed, client_id_present=%s, client_secret_present=%s, auth_uri_present=%s, token_uri_present=%s, redirect_uri_count=%d, redirect_uri_host=%s",
            bool(client_config.client_id),
            bool(client_config.client_secret),
            bool(client_config.auth_uri),
            bool(client_config.token_uri),
            len(client_config.redirect_uris),
            urlsplit(redirect_uri).hostname or "localhost",
        )

        # Launch the system browser for the user
        try:
            await asyncio.get_running_loop().run_in_executor(None, webbrowser.open, auth_url)
        except Exception as exc:
            logger.warning("Could not automatically launch browser: %s", exc)

        return {
            "ok": True,
            "auth_url": auth_url,
            "state": state,
            "redirect_uri": redirect_uri,
        }

    @router.get("/v1/connectors/gmail/oauth/callback")
    @router.get("/oauth/callback")
    async def oauth_callback(
        code: str = "", state: str = "", error: str = ""
    ) -> HTMLResponse:
        """Handle the Google OAuth redirect callback."""
        if error:
            logger.warning("Google authorization callback returned error: %s", error)
            error_msg = "Google authorization was denied or cancelled." if error == "access_denied" else f"Google returned error: {error}"
            return HTMLResponse(
                browser_page_renderer(
                    "Google Sign-In Cancelled",
                    error_msg,
                    ok=False,
                    error=error,
                    connector="gmail",
                ),
                status_code=400,
            )

        if not code or not state:
            return HTMLResponse(
                browser_page_renderer(
                    "Sign-In Incomplete",
                    "Missing authorization code or state parameter from Google.",
                    ok=False,
                    connector="gmail",
                ),
                status_code=400,
            )

        flow = oauth.get_and_consume_state(state)
        if flow is None:
            # Check if an async loopback future is waiting
            delivered = oauth.deliver_loopback_callback(code, state)
            if not delivered:
                return HTMLResponse(
                    browser_page_renderer(
                        "Sign-In Expired",
                        "This sign-in session expired or was already completed. Please return to CogniOS and try again.",
                        ok=False,
                        connector="gmail",
                    ),
                    status_code=400,
                )

        token_data, token_err = await asyncio.to_thread(
            oauth.exchange_code,
            flow.client_config,
            code,
            flow.redirect_uri,
        )
        if token_err or token_data is None:
            return HTMLResponse(
                browser_page_renderer(
                    "Token Exchange Failed",
                    token_err or "Failed to exchange authorization code with Google.",
                    ok=False,
                    connector="gmail",
                ),
                status_code=400,
            )

        email, email_err = await asyncio.to_thread(
            oauth.fetch_account_email, token_data["access_token"]
        )
        if email_err or not email:
            return HTMLResponse(
                browser_page_renderer(
                    "Account Identification Failed",
                    email_err or "Could not determine Google account email address.",
                    ok=False,
                    connector="gmail",
                ),
                status_code=400,
            )

        # Store encrypted credentials and update connector state
        credentials.save_account_credentials(
            secrets=secrets_store,
            email=email,
            client_config=flow.client_config,
            token_data=token_data,
        )

        oauth.deliver_loopback_callback(code, state)
        logger.info("Successfully connected Gmail account: %s", email)

        return HTMLResponse(
            browser_page_renderer(
                "Connected",
                f"Successfully connected {email}. You can close this tab and return to CogniOS.",
                ok=True,
                connector="gmail",
            )
        )

    @router.get("/v1/connectors/gmail/accounts")
    def get_accounts() -> dict[str, Any]:
        """List all connected Gmail accounts with safe metadata (no secrets/tokens)."""
        records = credentials.list_account_records(secrets_store)
        return {"accounts": [r.to_dict() for r in records]}

    @router.post("/v1/connectors/gmail/accounts/{email}/disconnect")
    def disconnect_account(email: str) -> dict[str, Any]:
        """Disconnect a Gmail account and securely remove its credentials."""
        return credentials.disconnect_gmail_account(secrets_store, email)

    @router.post("/v1/connectors/gmail/accounts/{email}/default")
    def set_default(email: str) -> dict[str, Any]:
        """Set an account as the default Gmail mailbox."""
        from .. import gmail_accounts
        return gmail_accounts.set_default(secrets_store, email)

    @router.patch("/v1/connectors/gmail/filters")
    def update_filters(body: dict[str, Any]) -> dict[str, Any]:
        """Update the sender and label privacy filters."""
        from .. import gmail_accounts
        senders = body.get("senders") if isinstance(body, dict) else None
        labels = body.get("labels") if isinstance(body, dict) else None
        return gmail_accounts.set_filters(secrets_store, senders, labels)

    return router
