"""TOTP helpers (RFC 6238) via pyotp."""

from __future__ import annotations

import base64
import io

import pyotp
import qrcode

APP_NAME = "CogniOS"


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(*, secret: str, username: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=username, issuer_name=APP_NAME)


def verify_code(*, secret: str, code: str) -> bool:
    totp = pyotp.TOTP(secret)
    return totp.verify(code.strip().replace(" ", ""), valid_window=1)


def qr_png_base64(otpauth_uri: str) -> str:
    img = qrcode.make(otpauth_uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")
