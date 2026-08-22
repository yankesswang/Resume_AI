"""PII access auditing.

Records who accessed candidate data, when, and which candidate — the minimum
needed to answer "who looked at this applicant's resume?" after the fact, which
is a standing obligation for a system holding this much personal data.

Writes go to a dedicated ``access_audit`` table.  Auditing must never break a
request: a failure here is logged and swallowed, because losing an audit row is
strictly better than 500-ing a recruiter mid-review.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timezone

from app.settings import settings

logger = logging.getLogger(__name__)

# Paths whose candidate id we care about capturing individually.
_CANDIDATE_PATH = re.compile(r"/api/candidates/(\d+)")

# High-volume, low-sensitivity endpoints that would swamp the audit table
# without telling us anything about PII access.
_SKIP_PREFIXES = (
    "/api/health",
    "/api/scoring-config",
    "/api/interview-statuses",
    "/docs",
    "/openapi.json",
    "/redoc",
)


def init_audit_schema(conn: sqlite3.Connection) -> None:
    """Create the audit table. Called from init_db()."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS access_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            key_id TEXT NOT NULL,
            method TEXT NOT NULL,
            path TEXT NOT NULL,
            candidate_id INTEGER,
            status_code INTEGER,
            client_ip TEXT,
            row_count INTEGER
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON access_audit(ts)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_candidate ON access_audit(candidate_id)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_key ON access_audit(key_id)")


def should_audit(path: str) -> bool:
    if not settings.audit_enabled:
        return False
    if not path.startswith("/api/"):
        return False
    return not any(path.startswith(p) for p in _SKIP_PREFIXES)


def record(
    *,
    key_id: str,
    method: str,
    path: str,
    status_code: int,
    client_ip: str | None = None,
    row_count: int | None = None,
) -> None:
    """Append one audit row. Never raises."""
    if not should_audit(path):
        return

    match = _CANDIDATE_PATH.search(path)
    candidate_id = int(match.group(1)) if match else None

    try:
        # Imported lazily: app.database imports settings, and importing it at
        # module scope here would make the audit module part of that cycle.
        from app.database import _connect

        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO access_audit
                    (ts, key_id, method, path, candidate_id, status_code,
                     client_ip, row_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    key_id,
                    method,
                    path,
                    candidate_id,
                    status_code,
                    client_ip,
                    row_count,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.warning("Audit write failed for %s %s", method, path, exc_info=True)


def purge_older_than(days: int) -> int:
    """Delete audit rows older than ``days``. Returns rows removed."""
    from app.database import _connect

    conn = _connect()
    try:
        cur = conn.execute(
            "DELETE FROM access_audit WHERE ts < datetime('now', ?)",
            (f"-{int(days)} days",),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
