"""Health diagnostic for CogniOS Telegram Agent Bridge."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ...server.manager import SessionManager

logger = logging.getLogger("cogniwork.connectors.telegram")


def check_telegram_health(manager: SessionManager | None = None) -> dict[str, Any]:
    """Inspect and report the live runtime health of the Telegram Agent Bridge."""
    diag: dict[str, Any] = {
        "telegram_configuration": "FAILED",
        "bot_token_loaded": "NO",
        "bot_api_reachable": "NO",
        "polling_webhook": "FAILED",
        "inbound_handler_registered": "NO",
        "manager_routing": "FAILED",
        "telegram_bridge_initialized": "NO",
        "session_store_initialized": "NO",
        "tool_registered": "NO",
        "details": {},
    }

    # 1. Check bridge & store
    if manager is not None and hasattr(manager, "telegram_bridge"):
        bridge = manager.telegram_bridge
        diag["telegram_bridge_initialized"] = "YES"
        if hasattr(bridge, "store") and bridge.store is not None:
            diag["session_store_initialized"] = "YES"
        diag["manager_routing"] = "OK"

    # 2. Check token from SecretStore or env
    token: str | None = None
    if manager is not None:
        creds = manager.secrets.get("telegram:default") or {}
        token = creds.get("bot_token")
    if not token:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")

    if token:
        diag["bot_token_loaded"] = "YES"
        token_suffix = token[-4:] if len(token) >= 4 else "..."
        diag["details"]["token_suffix"] = f"...{token_suffix}"

        # 3. Check Telegram Bot API reachability & webhook status
        try:
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/getMe",
                headers={"User-Agent": "CogniOS-HealthCheck/1.0"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                if data.get("ok"):
                    diag["bot_api_reachable"] = "YES"
                    diag["details"]["bot_user"] = data.get("result", {}).get("username")
        except Exception as exc:
            diag["details"]["api_error"] = str(exc)

        try:
            req_wh = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/getWebhookInfo",
                headers={"User-Agent": "CogniOS-HealthCheck/1.0"},
            )
            with urllib.request.urlopen(req_wh, timeout=5) as resp:
                data_wh = json.loads(resp.read().decode())
                if data_wh.get("ok"):
                    res = data_wh.get("result", {})
                    url = res.get("url") or ""
                    pending = res.get("pending_update_count", 0)
                    diag["details"]["webhook_url"] = url
                    diag["details"]["pending_update_count"] = pending
                    # Polling is valid when webhook is empty
                    diag["polling_webhook"] = "OK" if not url else f"WEBHOOK_SET({url})"
        except Exception as exc:
            diag["details"]["webhook_error"] = str(exc)

    # 4. Check tool registration
    try:
        from ..tool_defs import TOOL_DEFS
        if any(d.name == "telegram_agent_bridge" for d in TOOL_DEFS):
            diag["tool_registered"] = "YES"
    except Exception:
        pass

    # 5. Inbound handler check
    if manager is not None and getattr(manager, "gateway", None) is not None:
        if getattr(manager.gateway, "_on_inbound_handler", None) or hasattr(manager, "_dispatch_inbound"):
            diag["inbound_handler_registered"] = "YES"

    # 6. Overall config
    if diag["bot_token_loaded"] == "YES" and diag["bot_api_reachable"] == "YES":
        diag["telegram_configuration"] = "OK"

    return diag
