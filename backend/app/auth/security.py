"""Password, session-cookie, CSRF, and role checks."""

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import Depends, HTTPException, Request

from backend.app.core.config import get_settings
from backend.app.storage.accounts import AccountStore, public_account

SESSION_COOKIE = "evidence_session"
CSRF_COOKIE = "evidence_csrf"
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


def hash_password(password: str) -> str:
    if len(password) < 12 or len(password) > 1024:
        raise ValueError("Password must have 12 to 1024 characters")
    return _hasher.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return _hasher.verify(encoded, password)
    except (VerifyMismatchError, VerificationError, ValueError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def account_store() -> AccountStore:
    return AccountStore(get_settings().APP_DATABASE_PATH)


def session_tokens(account_id: str):
    token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
    account_store().create_session(token_hash(token), token_hash(csrf), account_id, expires)
    return token, csrf


def get_current_account(request: Request):
    token = request.cookies.get(SESSION_COOKIE, "")
    session = account_store().session(token_hash(token)) if token else None
    if not session:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    request.state.account = session
    return session


def require_ready_account(account=Depends(get_current_account)):
    if account["must_change_password"]:
        raise HTTPException(status_code=403, detail="Change your temporary password before continuing")
    return account


def require_admin(account=Depends(require_ready_account)):
    if account["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return account


def check_origin(request: Request):
    origin = request.headers.get("origin")
    if not origin:
        raise HTTPException(status_code=403, detail="A same-origin request is required")
    sent, received = urlsplit(origin), request.url
    if sent.scheme != received.scheme or sent.netloc != received.netloc:
        raise HTTPException(status_code=403, detail="A same-origin request is required")


def require_csrf(request: Request, account=Depends(get_current_account)):
    check_origin(request)
    supplied = request.headers.get("x-csrf-token", "")
    cookie = request.cookies.get(CSRF_COOKIE, "")
    if not supplied or not cookie or not secrets.compare_digest(supplied, cookie) or not secrets.compare_digest(token_hash(supplied), account["csrf_hash"]):
        raise HTTPException(status_code=403, detail="Invalid request token")
    return account


def require_admin_csrf(account=Depends(require_csrf)):
    if account["must_change_password"] or account["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return account


def require_ready_csrf(account=Depends(require_csrf)):
    if account["must_change_password"]:
        raise HTTPException(status_code=403, detail="Change your temporary password before continuing")
    return account


def public_session(account):
    return public_account(account)
