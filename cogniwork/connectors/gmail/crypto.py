"""Authenticated encryption for Gmail OAuth tokens and credentials at rest.

Uses Fernet (AES-128-CBC + HMAC-SHA256) to ensure sensitive refresh tokens and
client secrets are encrypted before persisting to the SecretStore on disk.
The key is stored with user-only (0600 / restricted ACL) OS protections.
"""

from __future__ import annotations

import logging
from ...auth.crypto import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)


def encrypt_token(plaintext: str) -> str:
    """Encrypt a plaintext secret/token. Returns empty string if plaintext is empty."""
    if not plaintext:
        return ""
    return encrypt_value(plaintext)


def decrypt_token(ciphertext: str) -> str | None:
    """Decrypt an encrypted token. Returns None if decryption fails or ciphertext is empty."""
    if not ciphertext:
        return None
    try:
        return decrypt_value(ciphertext)
    except Exception as exc:
        logger.warning("Failed to decrypt token: %s", exc)
        return None
