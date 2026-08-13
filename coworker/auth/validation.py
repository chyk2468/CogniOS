"""Input validation for registration and password reset."""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")


def validate_email(email: str) -> str | None:
    email = email.strip()
    if not email:
        return "Email is required."
    if not _EMAIL_RE.match(email):
        return "Enter a valid email address."
    return None


def validate_username(username: str) -> str | None:
    username = username.strip()
    if not username:
        return "Username is required."
    if not _USERNAME_RE.match(username):
        return "Username must be 3–32 characters (letters, numbers, underscores)."
    return None


def validate_full_name(full_name: str) -> str | None:
    full_name = full_name.strip()
    if not full_name:
        return "Full name is required."
    if len(full_name) > 120:
        return "Full name is too long."
    return None


def validate_password(password: str) -> str | None:
    if not password:
        return "Password is required."
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if len(password) > 128:
        return "Password is too long."
    if not re.search(r"[a-z]", password):
        return "Password must include a lowercase letter."
    if not re.search(r"[A-Z]", password):
        return "Password must include an uppercase letter."
    if not re.search(r"\d", password):
        return "Password must include a number."
    return None


def validate_pet_answer(answer: str) -> str | None:
    answer = answer.strip()
    if not answer:
        return "Favorite pet animal is required."
    if len(answer) > 64:
        return "Answer is too long."
    return None
