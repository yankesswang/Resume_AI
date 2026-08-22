"""Authentication, authorisation, and access auditing.

The system stores full resume PII — name, mobile, email, mailing address,
birth year, photo — for thousands of real job applicants. Every route that can
read or mutate that data goes through :func:`require_read` or
:func:`require_write`.

Two credential kinds, resolved into the same :class:`Principal`:

* **User sessions** (``Authorization: Bearer <jwt>``) — a named employee, with
  a role and a PII level that root granted them. This is how people log in.
* **API keys** (``X-API-Key``) — unattended callers: batch scripts, the parse
  worker, CI. ``API_KEYS`` grants full access, ``READONLY_API_KEYS`` may GET
  only.

Keys are kept because scripts cannot log in interactively, but they are the
weaker credential: a shared key has no person behind it, so the audit trail it
produces names a key rather than a human. Prefer an account wherever a human
is involved.

When ``AUTH_ENABLED=false`` both fall open, so existing local development keeps
working unchanged. Startup logs a loud warning in that mode and
:meth:`Settings.validate` refuses the unsafe combinations.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Depends, HTTPException, Request

from app import accounts, tokens
from app.settings import settings

logger = logging.getLogger(__name__)

_WRITE_METHODS = frozenset(("POST", "PUT", "PATCH", "DELETE"))


class Principal:
    """Who is making the request, and what they are allowed to do."""

    __slots__ = (
        "key_id",
        "can_write",
        "anonymous",
        "user_id",
        "email",
        "role",
        "pii_level",
        "permissions",
        "status",
    )

    def __init__(
        self,
        key_id: str,
        can_write: bool,
        anonymous: bool = False,
        *,
        user_id: int | None = None,
        email: str = "",
        role: str = "",
        pii_level: str = "full",
        permissions: frozenset[str] | None = None,
        status: str = "active",
    ) -> None:
        self.key_id = key_id
        self.can_write = can_write
        self.anonymous = anonymous
        self.user_id = user_id
        self.email = email
        self.role = role
        self.pii_level = pii_level
        self.status = status
        if permissions is not None:
            self.permissions = permissions
        elif role:
            self.permissions = accounts.ROLE_PERMISSIONS.get(role, frozenset())
        else:
            # An API key predates roles and carries no grade, so it keeps the
            # blanket access it has always had rather than being silently
            # downgraded into a role it was never assigned.
            self.permissions = frozenset(accounts.ROLE_PERMISSIONS["admin"]) if can_write \
                else frozenset({"read"})

    @property
    def is_root(self) -> bool:
        return self.role == "root"

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"Principal(key_id={self.key_id!r}, role={self.role!r}, "
            f"pii={self.pii_level!r}, can_write={self.can_write})"
        )


ANONYMOUS = Principal(
    key_id="anonymous",
    can_write=True,
    anonymous=True,
    role="root",
    pii_level="full",
    permissions=frozenset(accounts.ROLE_PERMISSIONS["root"]),
)


def _key_id(raw: str) -> str:
    """Short stable identifier for a key, safe to write into audit logs.

    Never log the key itself — audit records outlive the credential.
    """
    import hashlib

    return "k_" + hashlib.sha256(raw.encode()).hexdigest()[:12]


def _match(presented: str, allowed: tuple[str, ...]) -> bool:
    """Constant-time membership test, so timing cannot reveal a valid prefix."""
    ok = False
    for candidate in allowed:
        if hmac.compare_digest(presented, candidate):
            ok = True
    return ok


def _bearer_token(request: Request) -> str:
    authz = request.headers.get("Authorization", "")
    if authz.lower().startswith("bearer "):
        return authz[7:].strip()
    return ""


def _principal_from_session(raw_token: str) -> Principal | None:
    """Resolve a JWT into a Principal, re-reading the grade from the database.

    The token's own ``role``/``pii`` claims are ignored for authorisation.
    They are minted at login and would otherwise stay valid for the token's
    whole lifetime, so a suspension or demotion by root would not take effect
    until the user happened to log in again — precisely when it matters least.
    """
    try:
        payload = tokens.decode(raw_token, settings.session_secret)
    except tokens.TokenError:
        return None

    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError):
        return None

    from app.database import _connect

    conn = _connect()
    try:
        user = accounts.get_user(conn, user_id)
    finally:
        conn.close()

    if user is None:
        return None

    # Status is checked before token_version, even though a suspension bumps
    # both. Otherwise a suspended user's live token fails the version check
    # first and they are told "invalid credentials" — sending them to reset a
    # password that works fine, instead of to the administrator who suspended
    # them.
    if user["status"] != "active":
        raise HTTPException(status_code=403, detail=_status_message(user["status"]))

    if int(payload.get("tv", -1)) != int(user["token_version"]):
        # Password changed or grade edited since this token was minted.
        # See app.tokens for why this beats a blacklist.
        return None

    role = user["role"]
    return Principal(
        key_id=f"u_{user_id}",
        can_write=bool(accounts.ROLE_PERMISSIONS.get(role, frozenset()) - {"read"}),
        user_id=user_id,
        email=user["email"],
        role=role,
        pii_level=user["pii_level"],
        permissions=accounts.ROLE_PERMISSIONS.get(role, frozenset()),
        status=user["status"],
    )


def _status_message(status: str) -> str:
    return {
        "pending": "帳號尚未核准，請等待系統管理者（root）審核。",
        "suspended": "此帳號已被停用，請聯絡系統管理者。",
        "rejected": "此帳號的申請未通過審核。",
    }.get(status, "此帳號無法使用。")


def _authenticate(request: Request) -> Principal:
    if not settings.auth_enabled:
        return ANONYMOUS

    # A user session is tried first: when someone presents both, the named
    # human is the more specific and more accountable identity, and using the
    # shared key instead would file their access under the key's id.
    bearer = _bearer_token(request)
    if bearer:
        principal = _principal_from_session(bearer)
        if principal is not None:
            return principal

    presented = request.headers.get(settings.auth_header, "") or bearer
    if not presented:
        raise HTTPException(
            status_code=401,
            detail="Missing credentials. Log in, or send an API key.",
            headers={"WWW-Authenticate": settings.auth_header},
        )

    if _match(presented, settings.api_keys):
        return Principal(key_id=_key_id(presented), can_write=True)
    if _match(presented, settings.readonly_api_keys):
        return Principal(key_id=_key_id(presented), can_write=False)

    raise HTTPException(status_code=401, detail="Invalid credentials.")


def require_read(request: Request) -> Principal:
    """Dependency for any endpoint that reads candidate data."""
    principal = _authenticate(request)
    request.state.principal = principal
    return principal


def require_write(
    request: Request, principal: Principal = Depends(require_read)
) -> Principal:
    """Dependency for endpoints that create, modify, or delete data."""
    if not principal.can_write:
        raise HTTPException(status_code=403, detail="This credential is read-only.")
    return principal


def require_permission(permission: str):
    """Build a dependency demanding one named permission.

    Used for the finer distinctions a plain read/write split cannot express —
    an interviewer may write their notes but not export the candidate pool.
    """

    def dependency(
        request: Request, principal: Principal = Depends(require_read)
    ) -> Principal:
        if not principal.has(permission):
            raise HTTPException(
                status_code=403,
                detail=f"你的角色（{accounts.ROLE_LABELS_ZH.get(principal.role, principal.role or 'API key')}）"
                f"沒有此操作的權限：{permission}",
            )
        return principal

    return dependency


require_root = require_permission("admin:users")


def pii_level_for(principal: Principal) -> str:
    """The PII level a response for this principal must be trimmed to."""
    return principal.pii_level or "full"


def is_write_request(method: str) -> bool:
    return method.upper() in _WRITE_METHODS
