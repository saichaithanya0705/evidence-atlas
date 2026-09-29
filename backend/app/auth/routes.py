"""Session and administrator-managed account API."""

from collections import defaultdict, deque
from threading import Lock
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from backend.app.core.config import get_settings
from backend.app.storage.accounts import public_account
from .security import (
    CSRF_COOKIE, SESSION_COOKIE, account_store, check_origin, get_current_account,
    hash_password, public_session, require_admin, require_admin_csrf,
    require_csrf, session_tokens, token_hash, verify_password,
)

router = APIRouter()
_attempts = defaultdict(deque)
_attempt_lock = Lock()


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class NewAccount(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=120)
    role: str = "user"
    temporary_password: str


class AccountUpdate(BaseModel):
    active: bool | None = None
    role: str | None = None
    temporary_password: str | None = None


def _throttle(key, failed=False, success=False):
    now = time.monotonic()
    with _attempt_lock:
        attempts = _attempts[key]
        while attempts and attempts[0] < now - 300:
            attempts.popleft()
        if len(attempts) >= 5:
            raise HTTPException(status_code=429, detail="Too many sign-in attempts; try again later")
        if failed:
            attempts.append(now)
        elif success:
            attempts.clear()


@router.post("/auth/login")
def login(payload: Credentials, request: Request, response: Response):
    check_origin(request)
    key = (request.client.host if request.client else "unknown", payload.username.strip().casefold())
    _throttle(key)
    account = account_store().by_username(payload.username)
    if not account or not account["active"] or not verify_password(payload.password, account["password_hash"]):
        _throttle(key, failed=True)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    _throttle(key, success=True)
    token, csrf = session_tokens(account["id"])
    secure = get_settings().APP_ENV == "production"
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=secure, samesite="lax", max_age=43200, path="/")
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, secure=secure, samesite="lax", max_age=43200, path="/")
    return {"account": public_session(account)}


@router.get("/auth/me")
def me(account=Depends(get_current_account)):
    return {"account": public_session(account)}


@router.post("/auth/logout")
def logout(response: Response, request: Request, account=Depends(require_csrf)):
    account_store().revoke_session(token_hash(request.cookies.get(SESSION_COOKIE, "")))
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"signed_out": True}


@router.post("/auth/password")
def change_password(payload: PasswordChange, request: Request, response: Response, account=Depends(require_csrf)):
    if not verify_password(payload.current_password, account_store().by_id(account["id"])["password_hash"]):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    try:
        encoded = hash_password(payload.new_password)
        account_store().update(account["id"], account["id"], password_hash=encoded, must_change_password=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"password_changed": True, "sign_in_again": True}


@router.get("/admin/accounts")
def list_accounts(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), account=Depends(require_admin)):
    return account_store().list_accounts(limit, offset)


@router.post("/admin/accounts", status_code=201)
def create_account(payload: NewAccount, account=Depends(require_admin_csrf)):
    try:
        return public_account(account_store().create(payload.username, payload.display_name, payload.role, hash_password(payload.temporary_password), account["id"], True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/admin/accounts/{account_id}")
def update_account(account_id: str, payload: AccountUpdate, account=Depends(require_admin_csrf)):
    try:
        encoded = hash_password(payload.temporary_password) if payload.temporary_password else None
        return public_account(account_store().update(account_id, account["id"], active=payload.active, role=payload.role, password_hash=encoded, must_change_password=True if encoded else None))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
