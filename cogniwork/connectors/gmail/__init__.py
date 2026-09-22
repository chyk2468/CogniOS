"""Gmail connector package for CogniOS."""

from .client import GmailClient
from .credentials import (
    disconnect_gmail_account,
    get_valid_access_token,
    list_account_records,
    save_account_credentials,
)
from .models import (
    GmailAccountRecord,
    GmailConnectionStatus,
    InstalledAppCredentials,
    OAuthFlowState,
)
from .oauth import (
    GMAIL_SCOPES,
    build_authorization_url,
    exchange_code,
    fetch_account_email,
    resolve_redirect_uri,
)
from .routes import create_gmail_router

__all__ = [
    "GmailClient",
    "disconnect_gmail_account",
    "get_valid_access_token",
    "list_account_records",
    "save_account_credentials",
    "GmailAccountRecord",
    "GmailConnectionStatus",
    "InstalledAppCredentials",
    "OAuthFlowState",
    "GMAIL_SCOPES",
    "build_authorization_url",
    "exchange_code",
    "fetch_account_email",
    "resolve_redirect_uri",
    "create_gmail_router",
]
