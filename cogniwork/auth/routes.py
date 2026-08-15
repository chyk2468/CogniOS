"""Auth HTTP routes — single-owner account, sessions, 2FA, and account management."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .rate_limit import RateLimiter
from .reset import reset_owner_data
from .store import AuthStore
from .totp import provisioning_uri, qr_png_base64
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
GENERIC_TOTP_ERROR = "Invalid authentication code."
RATE_LIMIT_ERROR = "Too many attempts. Please try again later."

logger = logging.getLogger("cogniwork.auth")


def auth_disabled() -> bool:
    flag = os.environ.get("COGNIWORK_AUTH_DISABLED") or os.environ.get("COWORKER_AUTH_DISABLED", "")
    return flag.strip() in ("1", "true", "yes")


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


class SignInTotpBody(BaseModel):
    challenge_token: str = Field(min_length=1)
    code: str = Field(min_length=6, max_length=8)


class ForgotStartBody(BaseModel):
    identifier: str = Field(min_length=1, max_length=254)


class VerifyPetBody(BaseModel):
    token: str = Field(min_length=1)
    pet_answer: str = Field(min_length=1, max_length=64)


class VerifyRecoveryTotpBody(BaseModel):
    token: str = Field(min_length=1)
    code: str = Field(min_length=6, max_length=8)


class ResetPasswordBody(BaseModel):
    reset_token: str = Field(min_length=1)
    password: str = Field(min_length=1, max_length=128)
    confirm_password: str = Field(min_length=1, max_length=128)


class ChangePasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)
    confirm_password: str = Field(min_length=1, max_length=128)


class ChangeUsernameBody(BaseModel):
    username: str = Field(min_length=1, max_length=32)


class ChangeEmailBody(BaseModel):
    email: str = Field(min_length=1, max_length=254)


class TotpSetupVerifyBody(BaseModel):
    setup_token: str = Field(min_length=1)
    code: str = Field(min_length=6, max_length=8)


class TotpDisableBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=6, max_length=8)


class RemoveAccountBody(BaseModel):
    confirmation: str = Field(min_length=1, max_length=32)
    current_password: str = Field(min_length=1, max_length=128)
    totp_code: str | None = Field(default=None, max_length=8)


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


def _require_session_user(request: Request, store: AuthStore) -> tuple[JSONResponse | None, Any]:
    sid = _session_id_from_request(request)
    if not sid:
        return JSONResponse({"error": "authentication_required"}, status_code=401), None
    user = store.get_user_for_session(sid)
    if not user:
        return JSONResponse({"error": "authentication_required"}, status_code=401), None
    return None, user


def create_auth_router(store: AuthStore, limiter: RateLimiter, manager: Any = None) -> APIRouter:
    router = APIRouter(prefix="/v1/auth", tags=["auth"])

    @router.get("/status")
    def status() -> dict[str, bool]:
        if auth_disabled():
            return {"owner_exists": True, "signup_allowed": False}
        exists = store.owner_exists()
        return {"owner_exists": exists, "signup_allowed": not exists}

    @router.get("/me")
    def me(request: Request) -> dict[str, Any]:
        if auth_disabled():
            return {
                "authenticated": True,
                "user": {"id": 0, "full_name": "Dev", "username": "dev", "email": "dev@local"},
            }
        sid = _session_id_from_request(request)
        if not sid:
            return {"authenticated": False}
        user = store.get_user_for_session(sid)
        if not user:
            return {"authenticated": False}
        return {"authenticated": True, "user": user.public_dict()}

    @router.get("/account")
    def account(request: Request) -> JSONResponse:
        err, user = _require_session_user(request, store)
        if err:
            return err
        assert user is not None
        sid = _session_id_from_request(request)
        session_info = store.get_session_info(sid or "") if sid else None
        return JSONResponse(
            {
                "account": user.account_dict(),
                "session": session_info,
            }
        )

    @router.post("/signup")
    def signup(body: SignUpBody, request: Request) -> JSONResponse:
        if store.owner_exists():
            return JSONResponse({"error": "owner_exists"}, status_code=403)

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
            if str(exc) == "owner_exists":
                return JSONResponse({"error": "owner_exists"}, status_code=403)
            return JSONResponse({"error": "registration_failed"}, status_code=400)

        return JSONResponse({"ok": True, "user": user.public_dict()})

    @router.post("/signin")
    def signin(body: SignInBody, request: Request) -> JSONResponse:
        key = f"signin:{_client_ip(request)}"
        if not limiter.check(key):
            return JSONResponse({"error": RATE_LIMIT_ERROR}, status_code=429)

        user = store.verify_credentials(body.identifier, body.password)
        if not user:
            return JSONResponse({"error": GENERIC_AUTH_ERROR}, status_code=401)

        limiter.reset(key)
        if user.totp_enabled:
            challenge = store.create_pending_login(user.id)
            return JSONResponse({"ok": True, "requires_totp": True, "challenge_token": challenge})

        session = store.create_session(user.id)
        return _json_with_session(request, session.id, {"ok": True, "user": user.public_dict()})

    @router.post("/signin/totp")
    def signin_totp(body: SignInTotpBody, request: Request) -> JSONResponse:
        key = f"signin-totp:{_client_ip(request)}"
        if not limiter.check(key):
            return JSONResponse({"error": RATE_LIMIT_ERROR}, status_code=429)

        user_id = store.get_pending_login(body.challenge_token)
        if user_id is None:
            return JSONResponse({"error": GENERIC_TOTP_ERROR}, status_code=401)

        if not store.verify_user_totp(user_id, body.code):
            return JSONResponse({"error": GENERIC_TOTP_ERROR}, status_code=401)

        store.delete_pending_login(body.challenge_token)

        limiter.reset(key)
        user = store.get_user_by_id(user_id)
        if not user:
            return JSONResponse({"error": GENERIC_TOTP_ERROR}, status_code=401)

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

    @router.patch("/account/username")
    def change_username(body: ChangeUsernameBody, request: Request) -> JSONResponse:
        err, user = _require_session_user(request, store)
        if err:
            return err
        assert user is not None
        uerr = validate_username(body.username)
        if uerr:
            return JSONResponse({"error": "validation_failed", "fields": {"username": uerr}}, status_code=400)
        try:
            store.change_username(user.id, body.username)
        except Exception:
            return JSONResponse({"error": "update_failed"}, status_code=400)
        updated = store.get_user_by_id(user.id)
        return JSONResponse({"ok": True, "user": updated.public_dict() if updated else user.public_dict()})

    @router.patch("/account/email")
    def change_email(body: ChangeEmailBody, request: Request) -> JSONResponse:
        err, user = _require_session_user(request, store)
        if err:
            return err
        assert user is not None
        eerr = validate_email(body.email)
        if eerr:
            return JSONResponse({"error": "validation_failed", "fields": {"email": eerr}}, status_code=400)
        try:
            store.change_email(user.id, body.email)
        except Exception:
            return JSONResponse({"error": "update_failed"}, status_code=400)
        updated = store.get_user_by_id(user.id)
        return JSONResponse({"ok": True, "user": updated.public_dict() if updated else user.public_dict()})

    @router.post("/account/password")
    def change_password(body: ChangePasswordBody, request: Request) -> JSONResponse:
        err, user = _require_session_user(request, store)
        if err:
            return err
        assert user is not None
        if not store.verify_password_for_user(user.id, body.current_password):
            return JSONResponse({"error": "Invalid current password."}, status_code=401)

        errors: dict[str, str] = {}
        pw_err = validate_password(body.password)
        if pw_err:
            errors["password"] = pw_err
        if body.password != body.confirm_password:
            errors["confirm_password"] = "Passwords do not match."
        if errors:
            return JSONResponse({"error": "validation_failed", "fields": errors}, status_code=400)

        store.change_password(user.id, body.password)
        resp = JSONResponse({"ok": True})
        _clear_session_cookie(resp, request)
        return resp

    @router.post("/totp/setup")
    def totp_setup(request: Request) -> JSONResponse:
        err, user = _require_session_user(request, store)
        if err:
            return err
        assert user is not None
        if user.totp_enabled:
            return JSONResponse({"error": "totp_already_enabled"}, status_code=400)

        setup_token, secret = store.begin_totp_setup(user.id)
        uri = provisioning_uri(secret=secret, username=user.username)
        return JSONResponse(
            {
                "setup_token": setup_token,
                "otpauth_uri": uri,
                "manual_key": secret,
                "qr_png_base64": qr_png_base64(uri),
            }
        )

    @router.post("/totp/verify-setup")
    def totp_verify_setup(body: TotpSetupVerifyBody, request: Request) -> JSONResponse:
        err, user = _require_session_user(request, store)
        if err:
            return err
        assert user is not None
        if not store.confirm_totp_setup(user.id, body.setup_token, body.code):
            return JSONResponse({"error": GENERIC_TOTP_ERROR}, status_code=401)
        updated = store.get_user_by_id(user.id)
        return JSONResponse({"ok": True, "totp_enabled": True, "account": updated.account_dict() if updated else {}})

    @router.post("/totp/disable")
    def totp_disable(body: TotpDisableBody, request: Request) -> JSONResponse:
        err, user = _require_session_user(request, store)
        if err:
            return err
        assert user is not None
        if not user.totp_enabled:
            return JSONResponse({"error": "totp_not_enabled"}, status_code=400)
        if not store.verify_password_for_user(user.id, body.current_password):
            return JSONResponse({"error": "Invalid current password."}, status_code=401)
        if not store.verify_user_totp(user.id, body.code):
            return JSONResponse({"error": GENERIC_TOTP_ERROR}, status_code=401)

        store.disable_totp(user.id)
        updated = store.get_user_by_id(user.id)
        return JSONResponse({"ok": True, "totp_enabled": False, "account": updated.account_dict() if updated else {}})

    @router.post("/account/remove")
    def remove_account(body: RemoveAccountBody, request: Request) -> JSONResponse:
        if body.confirmation != "DELETE":
            return JSONResponse({"error": "Confirmation must be exactly DELETE."}, status_code=400)

        err, user = _require_session_user(request, store)
        if err:
            return err
        assert user is not None

        if not store.verify_password_for_user(user.id, body.current_password):
            return JSONResponse({"error": "Invalid current password."}, status_code=401)

        if user.totp_enabled:
            code = (body.totp_code or "").strip()
            if not code or not store.verify_user_totp(user.id, code):
                return JSONResponse({"error": GENERIC_TOTP_ERROR}, status_code=401)

        if manager is None:
            return JSONResponse({"error": "Account was not removed. Please try again."}, status_code=500)

        try:
            reset_owner_data(auth_store=store, manager=manager)
        except Exception:
            logger.exception("Account removal failed")
            return JSONResponse({"error": "Account was not removed. Please try again."}, status_code=500)

        resp = JSONResponse({"ok": True, "owner_exists": False})
        _clear_session_cookie(resp, request)
        return resp

    @router.post("/forgot-password/start")
    def forgot_start(body: ForgotStartBody, request: Request) -> JSONResponse:
        key = f"forgot:{_client_ip(request)}"
        if not limiter.check(key):
            return JSONResponse({"error": RATE_LIMIT_ERROR}, status_code=429)

        owner = store.get_owner()
        token = store.create_recovery_token(owner.id if owner else None, stage="pet")
        return JSONResponse({"ok": True, "token": token})

    @router.post("/forgot-password/verify-pet")
    def verify_pet(body: VerifyPetBody, request: Request) -> JSONResponse:
        key = f"verify-pet:{_client_ip(request)}:{body.token[:8]}"
        if not limiter.check(key):
            return JSONResponse({"error": RATE_LIMIT_ERROR}, status_code=429)

        next_token, requires_totp = store.verify_pet_for_recovery(body.token, body.pet_answer)
        if not next_token:
            return JSONResponse({"error": GENERIC_RECOVERY_ERROR}, status_code=401)

        limiter.reset(key)
        if requires_totp:
            return JSONResponse({"ok": True, "requires_totp": True, "token": next_token})
        return JSONResponse({"ok": True, "reset_token": next_token})

    @router.post("/forgot-password/verify-totp")
    def verify_recovery_totp(body: VerifyRecoveryTotpBody, request: Request) -> JSONResponse:
        key = f"recovery-totp:{_client_ip(request)}"
        if not limiter.check(key):
            return JSONResponse({"error": RATE_LIMIT_ERROR}, status_code=429)

        reset_token = store.verify_totp_for_recovery(body.token, body.code)
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
    if auth_disabled():
        return None
    sid = _session_id_from_request(request)
    if not sid or not store.get_user_for_session(sid):
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    return None
