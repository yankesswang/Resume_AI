"""Registration, login, and root-only account administration.

Route layout mirrors the trust boundary:

* ``auth_public_router`` — ``/register`` and ``/login``, reachable without
  credentials, because you cannot authenticate before you have an account.
  Both are rate-limited: they are the only unauthenticated write paths in the
  app, and an unlimited login endpoint is a password-guessing oracle.
* ``auth_router`` — ``/me`` and ``/me/password``, any logged-in account.
* ``admin_router`` — ``/api/admin/users/*``, gated on the ``admin:users``
  permission, which only ``root`` holds.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import accounts, tokens
from app.accounts import AccountError
from app.auth import Principal, require_read, require_root
from app.database import _connect
from app.settings import settings

logger = logging.getLogger(__name__)

auth_public_router = APIRouter(prefix="/api/auth", tags=["auth"])
auth_router = APIRouter(prefix="/api/auth", tags=["auth"], dependencies=[Depends(require_read)])
admin_router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_root)]
)


# --------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------

# In-process sliding window, matching the upload limiter already in routes.py.
# It is per-process, so it does not hold across a multi-worker deployment —
# adequate for a single-process app beside its SQLite file, and the honest
# limitation to note rather than to imply otherwise.
_LOGIN_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
_LOGIN_LIMIT = 10
_LOGIN_WINDOW = 300  # seconds


def _rate_limit(bucket: str, limit: int = _LOGIN_LIMIT, window: int = _LOGIN_WINDOW) -> None:
    now = time.time()
    attempts = _LOGIN_ATTEMPTS[bucket]
    while attempts and now - attempts[0] > window:
        attempts.popleft()
    if len(attempts) >= limit:
        raise HTTPException(
            status_code=429,
            detail="嘗試次數過多，請稍後再試。",
            headers={"Retry-After": str(window)},
        )
    attempts.append(now)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# --------------------------------------------------------------------------
# Payloads
# --------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str = ""
    company: str = ""
    department: str = ""
    requested_reason: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class ApproveRequest(BaseModel):
    role: str = "viewer"
    pii_level: str | None = None
    note: str = ""


class GradeRequest(BaseModel):
    role: str | None = None
    pii_level: str | None = None
    note: str = ""


class StatusRequest(BaseModel):
    status: str = Field(..., description="active / suspended / rejected")
    note: str = ""


class ReviewRequest(BaseModel):
    note: str = ""


def _handle(error: AccountError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.message)


# --------------------------------------------------------------------------
# Public
# --------------------------------------------------------------------------


@auth_public_router.get("/config")
def auth_config():
    """What the login screen needs to know before anyone has logged in."""
    conn = _connect()
    try:
        bootstrapped = accounts.has_root(conn)
    finally:
        conn.close()
    return {
        "auth_enabled": settings.auth_enabled,
        "registration_open": settings.registration_open,
        "registration_domains": list(settings.registration_domains),
        # False means nobody can approve anyone yet: the operator has not run
        # the bootstrap CLI. Surfacing it stops a fresh install looking like a
        # broken one when the first registration sits pending forever.
        "root_configured": bootstrapped,
        # The login form's placeholder is drawn from this, so relaxing the
        # floor cannot leave the UI instructing a rule the server dropped.
        "min_password_length": accounts.MIN_PASSWORD_LENGTH,
        "roles": [
            {
                "value": role,
                "label": accounts.ROLE_LABELS_ZH[role],
                "permissions": sorted(accounts.ROLE_PERMISSIONS[role]),
                "default_pii_level": accounts.DEFAULT_PII_FOR_ROLE[role],
            }
            for role in accounts.ROLES
        ],
        "pii_levels": [
            {"value": level, "label": accounts.PII_LABELS_ZH[level]}
            for level in accounts.PII_LEVELS
        ],
    }


@auth_public_router.post("/register", status_code=201)
def register(body: RegisterRequest, request: Request):
    """Create a pending account. Grants no access until root approves it."""
    if not settings.registration_open:
        raise HTTPException(
            status_code=403, detail="目前不開放自行註冊，請聯絡系統管理者建立帳號。"
        )
    _rate_limit(f"register:{_client_ip(request)}", limit=5, window=3600)

    email = accounts.normalise_email(body.email)
    domains = settings.registration_domains
    if domains and not any(email.endswith("@" + d.lower()) for d in domains):
        raise HTTPException(
            status_code=403,
            detail="此電子郵件網域不在允許註冊的範圍內：" + "、".join(domains),
        )

    conn = _connect()
    try:
        user = accounts.register_user(
            conn,
            email=email,
            password=body.password,
            display_name=body.display_name,
            company=body.company,
            department=body.department,
            requested_reason=body.requested_reason,
        )
    except AccountError as exc:
        raise _handle(exc) from None
    finally:
        conn.close()

    logger.info("Registration pending approval: %s", email)
    return {
        "user": accounts.to_public(user),
        "message": "註冊成功，帳號待系統管理者（root）核准後才能使用。",
    }


@auth_public_router.post("/login")
def login(body: LoginRequest, request: Request):
    """Exchange credentials for a session token."""
    if not settings.session_secret:
        raise HTTPException(
            status_code=503,
            detail="伺服器尚未設定 SESSION_SECRET，無法簽發登入權杖。",
        )
    # Bucketed by IP *and* by account, so one attacker cannot lock out a real
    # user by burning their allowance from elsewhere, and cannot dodge the
    # limit by spraying many accounts from one host.
    _rate_limit(f"login-ip:{_client_ip(request)}")
    _rate_limit(f"login-user:{accounts.normalise_email(body.email)}")

    conn = _connect()
    try:
        user = accounts.authenticate(conn, email=body.email, password=body.password)
    finally:
        conn.close()

    if user is None:
        raise HTTPException(status_code=401, detail="電子郵件或密碼不正確。")
    if user["status"] != "active":
        # 403, not 401: the credentials were right. Saying so is not a leak —
        # they already proved they own the account — and "wrong password" for
        # a correctly typed password sends people into a reset loop instead of
        # to the administrator they actually need.
        raise HTTPException(
            status_code=403,
            detail={
                "pending": "帳號尚未核准，請等待系統管理者（root）審核。",
                "suspended": "此帳號已被停用，請聯絡系統管理者。",
                "rejected": "此帳號的申請未通過審核。",
            }.get(user["status"], "此帳號無法使用。"),
        )

    token, expires_at = tokens.issue_session(
        user_id=int(user["id"]),
        email=user["email"],
        role=user["role"],
        pii_level=user["pii_level"],
        token_version=int(user["token_version"]),
        secret=settings.session_secret,
        ttl_seconds=settings.session_ttl_seconds,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at,
        "user": accounts.to_public(user),
    }


# --------------------------------------------------------------------------
# Self-service
# --------------------------------------------------------------------------


@auth_router.get("/me")
def me(principal: Principal = Depends(require_read)):
    """The caller's own identity and grade, for rendering the UI."""
    if principal.user_id is None:
        # An API key or the auth-disabled fall-open path. Reported as such
        # rather than faked into a user, so the frontend can tell the two
        # apart instead of showing a logged-in name that does not exist.
        return {
            "authenticated": not principal.anonymous,
            "kind": "anonymous" if principal.anonymous else "api_key",
            "role": principal.role or "api_key",
            "pii_level": principal.pii_level,
            "permissions": sorted(principal.permissions),
        }
    conn = _connect()
    try:
        user = accounts.get_user(conn, principal.user_id)
    finally:
        conn.close()
    if user is None:
        raise HTTPException(status_code=404, detail="帳號不存在。")
    return {"authenticated": True, "kind": "user", **accounts.to_public(user)}


@auth_router.post("/me/password")
def change_own_password(
    body: PasswordChangeRequest, principal: Principal = Depends(require_read)
):
    if principal.user_id is None:
        raise HTTPException(status_code=400, detail="API 金鑰沒有密碼可以變更。")
    conn = _connect()
    try:
        accounts.change_password(
            conn,
            user_id=principal.user_id,
            current_password=body.current_password,
            new_password=body.new_password,
        )
    except AccountError as exc:
        raise _handle(exc) from None
    finally:
        conn.close()
    # Every token for this user is now invalid, including the one that made
    # this call — token_version moved. Say so, or the next 401 looks like a bug.
    return {"ok": True, "message": "密碼已更新，請重新登入。", "reauth_required": True}


# --------------------------------------------------------------------------
# Root-only administration
# --------------------------------------------------------------------------


@admin_router.get("/users")
def list_users(status: str | None = None):
    conn = _connect()
    try:
        rows = accounts.list_users(conn, status=status)
        counts = accounts.count_by_status(conn)
    finally:
        conn.close()
    return {"users": [accounts.to_public(r) for r in rows], "counts": counts}


@admin_router.get("/users/{user_id}")
def get_user(user_id: int):
    conn = _connect()
    try:
        user = accounts.get_user(conn, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="找不到此帳號。")
        events = accounts.list_user_events(conn, target_id=user_id, limit=50)
    finally:
        conn.close()
    return {"user": accounts.to_public(user), "history": events}


@admin_router.post("/users/{user_id}/approve")
def approve(user_id: int, body: ApproveRequest, principal: Principal = Depends(require_root)):
    """Admit a pending account at an explicitly chosen role and PII level."""
    pii_level = body.pii_level or accounts.DEFAULT_PII_FOR_ROLE.get(body.role, "masked")
    conn = _connect()
    try:
        user = accounts.approve_user(
            conn,
            user_id=user_id,
            role=body.role,
            pii_level=pii_level,
            actor=_actor(principal),
            note=body.note,
        )
    except AccountError as exc:
        raise _handle(exc) from None
    finally:
        conn.close()
    return {"user": accounts.to_public(user)}


@admin_router.post("/users/{user_id}/reject")
def reject(user_id: int, body: ReviewRequest, principal: Principal = Depends(require_root)):
    conn = _connect()
    try:
        user = accounts.reject_user(
            conn, user_id=user_id, actor=_actor(principal), note=body.note
        )
    except AccountError as exc:
        raise _handle(exc) from None
    finally:
        conn.close()
    return {"user": accounts.to_public(user)}


@admin_router.put("/users/{user_id}/grade")
def set_grade(user_id: int, body: GradeRequest, principal: Principal = Depends(require_root)):
    conn = _connect()
    try:
        user = accounts.update_grade(
            conn,
            user_id=user_id,
            actor=_actor(principal),
            role=body.role,
            pii_level=body.pii_level,
            note=body.note,
        )
    except AccountError as exc:
        raise _handle(exc) from None
    finally:
        conn.close()
    return {"user": accounts.to_public(user)}


@admin_router.put("/users/{user_id}/status")
def set_user_status(
    user_id: int, body: StatusRequest, principal: Principal = Depends(require_root)
):
    conn = _connect()
    try:
        user = accounts.set_status(
            conn,
            user_id=user_id,
            status=body.status,
            actor=_actor(principal),
            note=body.note,
        )
    except AccountError as exc:
        raise _handle(exc) from None
    finally:
        conn.close()
    return {"user": accounts.to_public(user)}


@admin_router.get("/user-audit")
def user_audit(limit: int = 100):
    """The account-change trail: who granted whom what, and when."""
    conn = _connect()
    try:
        return {"events": accounts.list_user_events(conn, limit=min(limit, 500))}
    finally:
        conn.close()


def _actor(principal: Principal) -> dict[str, object]:
    return {
        "id": principal.user_id,
        "email": principal.email or principal.key_id,
        "role": principal.role,
        "status": principal.status,
    }
