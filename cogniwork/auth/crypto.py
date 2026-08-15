"""Encrypt sensitive auth material at rest (TOTP secrets)."""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from ..secrets import state_dir, write_private_text


def _key_path() -> Path:
    return state_dir() / "auth-encryption.key"


def _load_fernet() -> Fernet:
    path = _key_path()
    if path.is_file():
        key = path.read_text(encoding="utf-8").strip().encode("ascii")
    else:
        key = Fernet.generate_key()
        write_private_text(path, key.decode("ascii"))
    return Fernet(key)


def encrypt_value(plaintext: str) -> str:
    return _load_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_value(ciphertext: str) -> str | None:
    try:
        return _load_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
