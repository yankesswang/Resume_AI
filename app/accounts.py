"""User accounts, roles, and root-approved registration.

The API-key model in :mod:`app.auth` answers "may this caller write?" and
nothing else. It cannot answer the question a company actually has about a
resume database: *which employee* looked at an applicant's phone number, and
were they supposed to be able to. A shared key has no name attached, cannot be
revoked for one person, and grades nobody.

This module adds accounts on top of it, without removing it — scripts, the
worker and CI keep using ``API_KEYS``.

Grading
-------
Two independent axes, because they answer different questions:

* **Role** — what actions are permitted (read / write / export / administer).
* **PII level** — how much of a person's identity the answer contains.

They are independent on purpose. An interviewer needs to *write* a scorecard
while seeing a masked name; an auditor may need full contact details while
being unable to change a single row. Folding the two into one ladder forces
one of those to be wrong.

Registration
------------
Anyone can register; nobody is admitted by registering. A new account is
``pending``: it can authenticate, and every data route refuses it. Only a
``root`` account can approve, and approval is the moment a human chooses the
role and PII level — so no account ever acquires access that a person did not
explicitly grant it.

That ordering is the point. If registration granted a default role and root
merely revoked the wrong ones, then every gap in root's attention would
default to *more* access, and the window between signup and review would be an
open door.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------

# Ordered least → most privileged. The ordering is used for "at least this
# role" checks, so inserting a role in the middle shifts nothing else.
ROLES: tuple[str, ...] = ("viewer", "interviewer", "recruiter", "admin", "root")

_ROLE_RANK = {name: i for i, name in enumerate(ROLES)}

# Permissions each role carries. Explicit sets rather than "rank >= x" because
# the two axes are not a single ladder: an interviewer writes interview notes
# but must not export the candidate pool to a spreadsheet, while an admin who
# never interviews anyone can.
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "viewer": frozenset({"read"}),
    "interviewer": frozenset({"read", "write:interview"}),
    "recruiter": frozenset({"read", "write:interview", "write:candidate", "export"}),
    "admin": frozenset(
        {"read", "write:interview", "write:candidate", "export", "write:scoring", "import"}
    ),
    # root additionally holds "admin:users", the only permission that can grant
    # permissions. It is deliberately not in any other role: an admin who could
    # promote themselves to root makes the root approval gate decorative.
    "root": frozenset(
        {
            "read",
            "write:interview",
            "write:candidate",
            "export",
            "write:scoring",
            "import",
            "admin:users",
        }
    ),
}

ROLE_LABELS_ZH: dict[str, str] = {
    "viewer": "檢視者",
    "interviewer": "面試官",
    "recruiter": "招募人員",
    "admin": "管理員",
    "root": "系統管理者",
}


# --------------------------------------------------------------------------
# PII levels
# --------------------------------------------------------------------------

# How much of the applicant's identity a caller may see. Ordered least → most.
PII_LEVELS: tuple[str, ...] = ("masked", "partial", "full")

_PII_RANK = {name: i for i, name in enumerate(PII_LEVELS)}

PII_LABELS_ZH: dict[str, str] = {
    "masked": "全遮罩（僅代號與評分）",
    "partial": "部分遮罩（姓氏與末碼）",
    "full": "完整個資",
}

# Default PII level suggested for each role at approval time. A suggestion,
# not a rule — root sets the level explicitly and may pair any role with any
# level, because "who may act" and "who may identify" are separate decisions.
DEFAULT_PII_FOR_ROLE: dict[str, str] = {
    "viewer": "masked",
    "interviewer": "partial",
    "recruiter": "full",
    "admin": "full",
    "root": "full",
}

STATUSES: tuple[str, ...] = ("pending", "active", "suspended", "rejected")


def role_rank(role: str) -> int:
    return _ROLE_RANK.get(role, -1)


def pii_rank(level: str) -> int:
    return _PII_RANK.get(level, -1)


def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


# --------------------------------------------------------------------------
# Password hashing
# --------------------------------------------------------------------------

# PBKDF2-HMAC-SHA256 from the standard library. bcrypt/argon2 are better, but
# they are C extensions, and this app's whole deployment story is "clone and
# run" against a single SQLite file. 600k iterations is the OWASP 2023 figure
# for PBKDF2-SHA256 and costs ~0.2s per login on this hardware, which is
# acceptable for a login that happens once a session.
_PBKDF2_ITERATIONS = 600_000
_SALT_BYTES = 16


def hash_password(password: str, *, iterations: int = _PBKDF2_ITERATIONS) -> str:
    """Return a self-describing hash: ``pbkdf2_sha256$iters$salt$hash``.

    The parameters travel with the hash so raising the iteration count later
    does not invalidate existing passwords — :func:`verify_password` reads the
    cost from the stored string, not from today's constant.
    """
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time password check. False on any malformed stored hash."""
    try:
        algorithm, iters, salt_hex, digest_hex = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def needs_rehash(encoded: str) -> bool:
    """True when a stored hash uses fewer iterations than today's setting."""
    try:
        algorithm, iters, _salt, _digest = encoded.split("$")
    except (ValueError, AttributeError):
        return True
    return algorithm != "pbkdf2_sha256" or int(iters) < _PBKDF2_ITERATIONS


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MIN_PASSWORD_LENGTH = 1


def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_email(email: str) -> str | None:
    if not _EMAIL_RE.match(email or ""):
        return "電子郵件格式不正確。"
    if len(email) > 254:
        return "電子郵件過長。"
    return None


def validate_password(password: str) -> str | None:
    """Length-first policy, currently with the floor turned off.

    No character-class rules: they push people towards ``Passw0rd!`` and buy
    less than the extra characters do. ``MIN_PASSWORD_LENGTH`` is 1 by
    operator decision, so any non-empty password is accepted; raise it to 10
    before this database of real people's contact details is exposed beyond
    the local network.
    """
    if not (password or ""):
        return "請輸入密碼。"
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"密碼至少需要 {MIN_PASSWORD_LENGTH} 個字元。"
    if len(password) > 1024:
        # Bound the PBKDF2 input so a huge password cannot be a CPU DoS.
        return "密碼過長。"
    return None


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------


def init_accounts_schema(conn: sqlite3.Connection) -> None:
    """Create the account tables. Idempotent; called from the migration."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            company TEXT NOT NULL DEFAULT '',
            department TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'viewer',
            pii_level TEXT NOT NULL DEFAULT 'masked',
            status TEXT NOT NULL DEFAULT 'pending',
            requested_reason TEXT NOT NULL DEFAULT '',
            approved_by INTEGER,
            approved_at TEXT,
            review_note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_login_at TEXT,
            -- Bumped on password change / revocation. Tokens carry the value
            -- they were minted with, so raising it invalidates every session
            -- that user has open without keeping a token blacklist.
            token_version INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            actor_id INTEGER,
            actor_email TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            target_id INTEGER,
            target_email TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_audit_ts ON user_audit(ts)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_audit_target ON user_audit(target_id)"
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Account audit
# --------------------------------------------------------------------------


def record_user_event(
    conn: sqlite3.Connection,
    *,
    action: str,
    actor_id: int | None = None,
    actor_email: str = "",
    target_id: int | None = None,
    target_email: str = "",
    detail: Any = "",
) -> None:
    """Append one account-lifecycle row.

    Separate from ``access_audit``: that answers "who read this applicant's
    data", this answers "who granted them the ability to". Mixing the two makes
    the second impossible to find inside the volume of the first.
    """
    if not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO user_audit
            (ts, actor_id, actor_email, action, target_id, target_email, detail)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (_now(), actor_id, actor_email, action, target_id, target_email, detail),
    )


def list_user_events(
    conn: sqlite3.Connection, *, target_id: int | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    if target_id is None:
        rows = conn.execute(
            "SELECT * FROM user_audit ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM user_audit WHERE target_id = ? ORDER BY id DESC LIMIT ?",
            (target_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# Queries
# --------------------------------------------------------------------------

_PUBLIC_FIELDS = (
    "id",
    "email",
    "display_name",
    "company",
    "department",
    "role",
    "pii_level",
    "status",
    "requested_reason",
    "approved_by",
    "approved_at",
    "review_note",
    "created_at",
    "updated_at",
    "last_login_at",
)


def to_public(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    """Account dict safe to return over the API — never the password hash."""
    data = dict(row)
    out = {k: data.get(k) for k in _PUBLIC_FIELDS}
    out["role_label"] = ROLE_LABELS_ZH.get(out.get("role") or "", out.get("role"))
    out["pii_label"] = PII_LABELS_ZH.get(out.get("pii_level") or "", out.get("pii_level"))
    out["permissions"] = sorted(ROLE_PERMISSIONS.get(out.get("role") or "", frozenset()))
    return out


def get_user_by_email(conn: sqlite3.Connection, email: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM users WHERE email = ?", (normalise_email(email),)
    ).fetchone()
    return dict(row) if row else None


def get_user(conn: sqlite3.Connection, user_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def list_users(
    conn: sqlite3.Connection, *, status: str | None = None
) -> list[dict[str, Any]]:
    if status:
        rows = conn.execute(
            "SELECT * FROM users WHERE status = ? ORDER BY created_at DESC", (status,)
        ).fetchall()
    else:
        # Pending first: the list exists to be acted on, and an approval queue
        # buried under months of active accounts is a queue nobody works.
        rows = conn.execute(
            """
            SELECT * FROM users
            ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END,
                     created_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def count_by_status(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT status, COUNT(*) c FROM users GROUP BY status").fetchall()
    counts = {s: 0 for s in STATUSES}
    for row in rows:
        counts[row["status"]] = row["c"]
    return counts


def has_root(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM users WHERE role = 'root' AND status = 'active' LIMIT 1"
    ).fetchone()
    return row is not None


# --------------------------------------------------------------------------
# Mutations
# --------------------------------------------------------------------------


class AccountError(Exception):
    """A rejected account operation, with a message safe to show the caller."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def register_user(
    conn: sqlite3.Connection,
    *,
    email: str,
    password: str,
    display_name: str = "",
    company: str = "",
    department: str = "",
    requested_reason: str = "",
) -> dict[str, Any]:
    """Create a ``pending`` account. Grants nothing until root approves.

    Role and PII level are written as the lowest values rather than left to a
    parameter: registration is a request, and a request that could name its own
    role would make approval a formality.
    """
    email = normalise_email(email)
    for error in (validate_email(email), validate_password(password)):
        if error:
            raise AccountError(error)

    if get_user_by_email(conn, email) is not None:
        raise AccountError("此電子郵件已註冊。", status_code=409)

    now = _now()
    cur = conn.execute(
        """
        INSERT INTO users
            (email, password_hash, display_name, company, department,
             role, pii_level, status, requested_reason, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'viewer', 'masked', 'pending', ?, ?, ?)
        """,
        (
            email,
            hash_password(password),
            (display_name or "").strip(),
            (company or "").strip(),
            (department or "").strip(),
            (requested_reason or "").strip(),
            now,
            now,
        ),
    )
    user_id = int(cur.lastrowid)
    record_user_event(
        conn,
        action="register",
        target_id=user_id,
        target_email=email,
        detail={"company": company, "department": department},
    )
    conn.commit()
    return get_user(conn, user_id)  # type: ignore[return-value]


def authenticate(
    conn: sqlite3.Connection, *, email: str, password: str
) -> dict[str, Any] | None:
    """Verify credentials. Returns the user row, or None.

    Returns None identically for "no such account" and "wrong password" so the
    response cannot be used to enumerate who has an account here. A dummy hash
    is computed on the missing-user path so the two cost the same time.
    """
    user = get_user_by_email(conn, email)
    if user is None:
        hash_password(password or "", iterations=1_000)  # equalise timing
        return None
    if not verify_password(password or "", user["password_hash"]):
        return None

    updates: list[str] = ["last_login_at = ?", "updated_at = ?"]
    params: list[Any] = [_now(), _now()]
    if needs_rehash(user["password_hash"]):
        updates.insert(0, "password_hash = ?")
        params.insert(0, hash_password(password))
    conn.execute(
        f"UPDATE users SET {', '.join(updates)} WHERE id = ?", (*params, user["id"])
    )
    conn.commit()
    return get_user(conn, int(user["id"]))


def approve_user(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    role: str,
    pii_level: str,
    actor: dict[str, Any],
    note: str = "",
) -> dict[str, Any]:
    """Activate a pending account at an explicitly chosen grade.

    Callers must already have checked that ``actor`` is root; this function
    re-checks anyway, because an approval path that trusts its caller to have
    checked is one refactor away from not being checked at all.
    """
    _require_root(actor)
    if role not in ROLE_PERMISSIONS:
        raise AccountError(f"未知的角色：{role}")
    if pii_level not in _PII_RANK:
        raise AccountError(f"未知的個資等級：{pii_level}")

    user = get_user(conn, user_id)
    if user is None:
        raise AccountError("找不到此帳號。", status_code=404)
    if role == "root" and user["status"] != "active":
        # Creating a second root is legitimate, but not as the same click that
        # first admits an unreviewed stranger to the system.
        raise AccountError(
            "無法在核准的同時指派 root：請先以一般角色核准，再單獨提升權限。"
        )

    conn.execute(
        """
        UPDATE users
           SET status = 'active', role = ?, pii_level = ?, approved_by = ?,
               approved_at = ?, review_note = ?, updated_at = ?
         WHERE id = ?
        """,
        (role, pii_level, actor.get("id"), _now(), (note or "").strip(), _now(), user_id),
    )
    record_user_event(
        conn,
        action="approve",
        actor_id=actor.get("id"),
        actor_email=actor.get("email", ""),
        target_id=user_id,
        target_email=user["email"],
        detail={"role": role, "pii_level": pii_level, "note": note},
    )
    conn.commit()
    return get_user(conn, user_id)  # type: ignore[return-value]


def reject_user(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    actor: dict[str, Any],
    note: str = "",
) -> dict[str, Any]:
    """Mark a pending account rejected. The row is kept, not deleted.

    Deleting it would let the same person re-register into a clean pending
    state, and would erase the record that a decision was ever made.
    """
    _require_root(actor)
    user = get_user(conn, user_id)
    if user is None:
        raise AccountError("找不到此帳號。", status_code=404)

    conn.execute(
        """
        UPDATE users
           SET status = 'rejected', review_note = ?, approved_by = ?,
               approved_at = ?, updated_at = ?, token_version = token_version + 1
         WHERE id = ?
        """,
        ((note or "").strip(), actor.get("id"), _now(), _now(), user_id),
    )
    record_user_event(
        conn,
        action="reject",
        actor_id=actor.get("id"),
        actor_email=actor.get("email", ""),
        target_id=user_id,
        target_email=user["email"],
        detail={"note": note},
    )
    conn.commit()
    return get_user(conn, user_id)  # type: ignore[return-value]


def update_grade(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    actor: dict[str, Any],
    role: str | None = None,
    pii_level: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Change an active account's role and/or PII level."""
    _require_root(actor)
    user = get_user(conn, user_id)
    if user is None:
        raise AccountError("找不到此帳號。", status_code=404)

    new_role = user["role"] if role is None else role
    new_pii = user["pii_level"] if pii_level is None else pii_level
    if new_role not in ROLE_PERMISSIONS:
        raise AccountError(f"未知的角色：{new_role}")
    if new_pii not in _PII_RANK:
        raise AccountError(f"未知的個資等級：{new_pii}")

    if user["role"] == "root" and new_role != "root":
        _guard_last_root(conn, user_id)

    conn.execute(
        """
        UPDATE users SET role = ?, pii_level = ?, review_note = ?, updated_at = ?,
                         token_version = token_version + 1
         WHERE id = ?
        """,
        (new_role, new_pii, (note or "").strip(), _now(), user_id),
    )
    record_user_event(
        conn,
        action="update_grade",
        actor_id=actor.get("id"),
        actor_email=actor.get("email", ""),
        target_id=user_id,
        target_email=user["email"],
        detail={
            "from": {"role": user["role"], "pii_level": user["pii_level"]},
            "to": {"role": new_role, "pii_level": new_pii},
            "note": note,
        },
    )
    conn.commit()
    return get_user(conn, user_id)  # type: ignore[return-value]


def set_status(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    status: str,
    actor: dict[str, Any],
    note: str = "",
) -> dict[str, Any]:
    """Suspend or reinstate an account."""
    _require_root(actor)
    if status not in STATUSES:
        raise AccountError(f"未知的狀態：{status}")
    user = get_user(conn, user_id)
    if user is None:
        raise AccountError("找不到此帳號。", status_code=404)
    if user["role"] == "root" and status != "active":
        _guard_last_root(conn, user_id)

    conn.execute(
        """
        UPDATE users SET status = ?, review_note = ?, updated_at = ?,
                         token_version = token_version + 1
         WHERE id = ?
        """,
        (status, (note or "").strip(), _now(), user_id),
    )
    record_user_event(
        conn,
        action=f"status:{status}",
        actor_id=actor.get("id"),
        actor_email=actor.get("email", ""),
        target_id=user_id,
        target_email=user["email"],
        detail={"note": note},
    )
    conn.commit()
    return get_user(conn, user_id)  # type: ignore[return-value]


def change_password(
    conn: sqlite3.Connection, *, user_id: int, current_password: str, new_password: str
) -> None:
    """Change one's own password, invalidating every existing session."""
    user = get_user(conn, user_id)
    if user is None:
        raise AccountError("找不到此帳號。", status_code=404)
    if not verify_password(current_password or "", user["password_hash"]):
        raise AccountError("目前的密碼不正確。", status_code=403)
    error = validate_password(new_password)
    if error:
        raise AccountError(error)

    conn.execute(
        """
        UPDATE users SET password_hash = ?, updated_at = ?,
                         token_version = token_version + 1
         WHERE id = ?
        """,
        (hash_password(new_password), _now(), user_id),
    )
    record_user_event(
        conn,
        action="password_change",
        actor_id=user_id,
        actor_email=user["email"],
        target_id=user_id,
        target_email=user["email"],
    )
    conn.commit()


def _require_root(actor: dict[str, Any] | None) -> None:
    if not actor or actor.get("role") != "root" or actor.get("status") != "active":
        raise AccountError("只有 root 帳號可以執行此操作。", status_code=403)


def _guard_last_root(conn: sqlite3.Connection, user_id: int) -> None:
    """Refuse to remove the final active root.

    A system with no root can never approve anyone again, and there is no
    recovery path through the API — only the CLI below. Blocking the last
    demotion is cheaper than explaining the lockout afterwards.
    """
    row = conn.execute(
        "SELECT COUNT(*) c FROM users WHERE role = 'root' AND status = 'active' AND id != ?",
        (user_id,),
    ).fetchone()
    if not row or row["c"] == 0:
        raise AccountError(
            "這是最後一個 root 帳號，無法降級或停用；請先建立另一個 root。"
        )


# --------------------------------------------------------------------------
# Bootstrap
# --------------------------------------------------------------------------


def bootstrap_root(
    conn: sqlite3.Connection,
    *,
    email: str,
    password: str,
    display_name: str = "root",
) -> dict[str, Any]:
    """Create the first root account.

    Only works while no active root exists. The first account cannot be
    approved by anyone — there is nobody to approve it — so it is created
    directly, from the machine hosting the database, which is the same trust
    boundary as having the DB file.
    """
    if has_root(conn):
        raise AccountError("已經存在 root 帳號；請由現有 root 指派新的管理者。")
    email = normalise_email(email)
    for error in (validate_email(email), validate_password(password)):
        if error:
            raise AccountError(error)

    existing = get_user_by_email(conn, email)
    now = _now()
    if existing is not None:
        conn.execute(
            """
            UPDATE users
               SET password_hash = ?, role = 'root', pii_level = 'full',
                   status = 'active', approved_at = ?, updated_at = ?,
                   token_version = token_version + 1
             WHERE id = ?
            """,
            (hash_password(password), now, now, existing["id"]),
        )
        user_id = int(existing["id"])
    else:
        cur = conn.execute(
            """
            INSERT INTO users
                (email, password_hash, display_name, role, pii_level, status,
                 approved_at, created_at, updated_at)
            VALUES (?, ?, ?, 'root', 'full', 'active', ?, ?, ?)
            """,
            (email, hash_password(password), display_name or "root", now, now, now),
        )
        user_id = int(cur.lastrowid)

    record_user_event(
        conn,
        action="bootstrap_root",
        actor_id=user_id,
        actor_email=email,
        target_id=user_id,
        target_email=email,
        detail={"source": "cli"},
    )
    conn.commit()
    return get_user(conn, user_id)  # type: ignore[return-value]
