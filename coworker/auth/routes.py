"""Auth HTTP routes and session cookie helpers."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .rate_limit import RateLimiter
from .store import AuthStore
from .validation import (
    validate_email,
    validate_full_name,
    validate_password,
    validate_pet_answer,
    validate_username,
)

SESSION_COOKIE = "ow_session"
GENERIC_AUTH_ERROR = "Invalid email/username or password."
GENERIC_RECOVERY_ERROR = "Verification failed. Please try again."
RATE_LIMIT_ERROR = "Too many attempts. Please try again later."


def auth_disabled() -> bool:
    return os.environ.get("COWORKER_AUTH_DISABLED", "").strip() in ("1", "true", "yes")


class SignUpBody(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    username: str = Field(min_length=1, max_length=32)
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)
    confirm_password: str = Field(min_length=1, max_length=128)
    favorite_pet: str = Field(min_length=1, max_length=64)


class SignInBody(BaseModel):
    identifier: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class ForgotStartBody(BaseModel):
    identifier: str = Field(min_length=1, max_length=254)


class VerifyPetBody(BaseModel):
    token: str = Field(min_length=1)
    pet_answer: str = Field(min_length=1, max_length=64)


class ResetPasswordBody(BaseModel):
    reset_token: str = Field(min_length=1)
    password: str = Field(min_length=1, max_length=128)
    confirm_password: str = Field(min_length=1, max_length=128)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _cookie_secure(request: Request) -> bool:
    return request.url.scheme == "https"


def _set_session_cookie(response: Response, request: Request, session_id: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_id,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        max_age=7 * 24 * 3600,
        path="/",
    )


def _json_with_session(
    request: Request, session_id: str, payload: dict[str, Any], *, status: int = 200
) -> JSONResponse:
    resp = JSONResponse(payload, status_code=status)
    _set_session_cookie(resp, request, session_id)
    return resp


def _clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
    )


def _session_id_from_request(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


def create_auth_router(store: AuthStore, limiter: RateLimiter) -> APIRouter:
    router = APIRouter(prefix="/v1/auth", tags=["auth"])

    @router.get("/me")
    def me(request: Request) -> dict[str, Any]:
        if auth_disabled():
            return {"authenticated": True, "user": {"id": 0, "full_name": "Dev", "username": "dev", "email": "dev@local"}}
        sid = _session_id_from_request(request)
        if not sid:
            return {"authenticated": False}
        user = store.get_user_for_session(sid)
        if not user:
            return {"authenticated": False}
        return {"authenticated": True, "user": user.public_dict()}

    @router.post("/signup")
    def signup(body: SignUpBody, request: Request) -> JSONResponse:
        errors: dict[str, str] = {}
        for field, err in (
            ("full_name", validate_full_name(body.full_name)),
            ("username", validate_username(body.username)),
            ("email", validate_email(body.email)),
            ("password", validate_password(body.password)),
            ("favorite_pet", validate_pet_answer(body.favorite_pet)),
        ):
            if err:
                errors[field] = err
        if body.password != body.confirm_password:
            errors["confirm_password"] = "Passwords do not match."
        if errors:
            return JSONResponse({"error": "validation_failed", "fields": errors}, status_code=400)

        try:
            user = store.create_user(
                full_name=body.full_name,
                username=body.username,
                email=body.email,
                password=body.password,
                favorite_pet=body.favorite_pet,
            )
        except ValueError as exc:
            code = str(exc)
            if code == "username_taken":
                return JSONResponse({"error": "validation_failed", "fields": {"username": "Username is already taken."}}, status_code=400)
            if code == "email_taken":
                return JSONResponse({"error": "validation_failed", "fields": {"email": "Email is already registered."}}, status_code=400)
            return JSONResponse({"error": "registration_failed"}, status_code=400)

        session = store.create_session(user.id)
        return _json_with_session(request, session.id, {"ok": True, "user": user.public_dict()})

    @router.post("/signin")
    def signin(body: SignInBody, request: Request) -> JSONResponse:
        key = f"signin:{_client_ip(request)}"
        if not limiter.check(key):
            return JSONResponse({"error": RATE_LIMIT_ERROR}, status_code=429)

        user = store.verify_credentials(body.identifier, body.password)
        if not user:
            return JSONResponse({"error": GENERIC_AUTH_ERROR}, status_code=401)

        limiter.reset(key)
        session = store.create_session(user.id)
        return _json_with_session(request, session.id, {"ok": True, "user": user.public_dict()})

    @router.post("/signout")
    def signout(request: Request) -> JSONResponse:
        sid = _session_id_from_request(request)
        if sid:
            store.delete_session(sid)
        resp = JSONResponse({"ok": True})
        _clear_session_cookie(resp, request)
        return resp

    @router.post("/forgot-password/start")
    def forgot_start(body: ForgotStartBody, request: Request) -> JSONResponse:
        key = f"forgot:{_client_ip(request)}"
        if not limiter.check(key):
            return JSONResponse({"error": RATE_LIMIT_ERROR}, status_code=429)

        user = store.find_user_by_email_or_username(body.identifier)
        token = store.create_recovery_token(user.id if user else None, stage="pet")
        # Always return the same shape — no account enumeration.
        return JSONResponse({"ok": True, "token": token})

    @router.post("/forgot-password/verify-pet")
    def verify_pet(body: VerifyPetBody, request: Request) -> JSONResponse:
        key = f"verify-pet:{_client_ip(request)}:{body.token[:8]}"
        if not limiter.check(key):
            return JSONResponse({"error": RATE_LIMIT_ERROR}, status_code=429)

        reset_token = store.verify_pet_for_recovery(body.token, body.pet_answer)
        if not reset_token:
            return JSONResponse({"error": GENERIC_RECOVERY_ERROR}, status_code=401)

        limiter.reset(key)
        return JSONResponse({"ok": True, "reset_token": reset_token})

    @router.post("/forgot-password/reset")
    def reset_password(body: ResetPasswordBody, request: Request) -> JSONResponse:
        key = f"reset:{_client_ip(request)}"
        if not limiter.check(key):
            return JSONResponse({"error": RATE_LIMIT_ERROR}, status_code=429)

        errors: dict[str, str] = {}
        pw_err = validate_password(body.password)
        if pw_err:
            errors["password"] = pw_err
        if body.password != body.confirm_password:
            errors["confirm_password"] = "Passwords do not match."
        if errors:
            return JSONResponse({"error": "validation_failed", "fields": errors}, status_code=400)

        if not store.reset_password(body.reset_token, body.password):
            return JSONResponse({"error": GENERIC_RECOVERY_ERROR}, status_code=401)

        return JSONResponse({"ok": True})

    return router


def require_user(request: Request, store: AuthStore) -> JSONResponse | None:
    """Return a 401 JSONResponse if the request lacks a valid user session."""
    if auth_disabled():
        return None
    sid = _session_id_from_request(request)
    if not sid or not store.get_user_for_session(sid):
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    return None
