"""Durable, SQLite-backed background job queue.

Why not FastAPI ``BackgroundTasks``: those run in the server's event loop after
the response is sent.  Scoring 3179 candidates that way is many hours of LLM
calls inside the loop that serves the UI — no progress, no cancellation, and
everything lost on restart.  Why not Celery/RQ: this app deploys as one small
self-contained process next to its SQLite file; a broker would be more moving
parts than the whole application.

So: one ``jobs`` table, claimed atomically, retried with backoff, resumable
after a crash.  A worker is either a separate process (``python -m
app.worker_queue``) or a thread inside the API process — the table is the only
thing they coordinate through.

Concurrency model
-----------------
The DB is in WAL mode, so readers never block the single writer.  A claim is::

    UPDATE jobs SET status='running', ... WHERE id=(SELECT ... status='queued')
      AND status='queued'

The repeated ``status='queued'`` in the outer WHERE is what makes it safe: two
workers may pick the same id in their sub-SELECTs, but SQLite serialises the
writes and the loser's UPDATE matches 0 rows, so it simply tries again.
``changes()`` is the claim receipt.

Progress and cancellation
-------------------------
A batch job owns ``total`` / ``completed`` / ``failed`` counters plus a
``cursor`` (the index of the next item to process).  The runner checkpoints the
cursor as it goes, so a killed worker resumes from the next unprocessed item
rather than redoing the batch.  Cancellation flips ``cancel_requested``; the
runner checks it between items, which is the only place it can stop safely.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Job lifecycle.
QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"

TERMINAL = frozenset((SUCCEEDED, FAILED, CANCELLED))

# A 'running' job whose worker has not touched it for this long is presumed
# dead (process killed, machine rebooted) and returned to the queue.  It must
# comfortably exceed one item's runtime: a single LLM tier call against a slow
# local model can take minutes, and requeueing a job that is merely slow would
# have two workers scoring the same candidates.
STALE_RUNNING_SECONDS = 900

# Retry backoff: attempt N waits BACKOFF_BASE * 2**(N-1), capped.
BACKOFF_BASE_SECONDS = 10
BACKOFF_MAX_SECONDS = 600


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --- Schema ----------------------------------------------------------------

def init_jobs_schema(conn: sqlite3.Connection) -> None:
    """Create the jobs table. Idempotent — safe to call on every startup."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_type TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',      -- JSON
            status TEXT NOT NULL DEFAULT 'queued',
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            last_error TEXT,
            total INTEGER NOT NULL DEFAULT 0,
            completed INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            cursor INTEGER NOT NULL DEFAULT 0,       -- resume point
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            result TEXT,                             -- JSON summary
            worker_id TEXT,
            available_at TEXT,                       -- backoff gate (ISO UTC)
            heartbeat_at TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, available_at);
        CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
        """
    )
    conn.commit()


def _conn() -> sqlite3.Connection:
    from app.database import _connect
    conn = _connect()
    # Queue writes are short; wait rather than fail when another worker holds
    # the write lock.
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


# --- Enqueue / read --------------------------------------------------------

def enqueue(job_type: str, payload: dict | None = None, total: int = 0,
            max_attempts: int = 3) -> int:
    conn = _conn()
    try:
        init_jobs_schema(conn)
        cur = conn.execute(
            """INSERT INTO jobs (job_type, payload, status, total, max_attempts,
                                 created_at, available_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                job_type,
                json.dumps(payload or {}, ensure_ascii=False),
                QUEUED,
                total,
                max_attempts,
                _iso(_utcnow()),
                _iso(_utcnow()),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["payload"] = json.loads(d.get("payload") or "{}")
    d["result"] = json.loads(d["result"]) if d.get("result") else None
    d["cancel_requested"] = bool(d.get("cancel_requested", 0))
    total = d.get("total") or 0
    done = (d.get("completed") or 0) + (d.get("failed") or 0)
    d["progress"] = {
        "total": total,
        "completed": d.get("completed") or 0,
        "failed": d.get("failed") or 0,
        "percent": round(done / total * 100, 1) if total else None,
    }
    return d


def get_job(job_id: int) -> dict | None:
    conn = _conn()
    try:
        init_jobs_schema(conn)
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def list_jobs(status: str | None = None, job_type: str | None = None,
              limit: int = 50) -> list[dict]:
    conn = _conn()
    try:
        init_jobs_schema(conn)
        where, params = [], []
        if status:
            where.append("status = ?")
            params.append(status)
        if job_type:
            where.append("job_type = ?")
            params.append(job_type)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(max(1, min(limit, 500)))
        rows = conn.execute(
            f"SELECT * FROM jobs {clause} ORDER BY id DESC LIMIT ?", params
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def request_cancel(job_id: int) -> dict | None:
    """Ask a job to stop.

    A queued job is cancelled outright.  A running one only gets the flag set —
    the runner stops at its next item boundary, because killing it mid-item
    would leave a half-written result.
    """
    conn = _conn()
    try:
        init_jobs_schema(conn)
        row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        if row["status"] in TERMINAL:
            return _row_to_dict(
                conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            )
        if row["status"] == QUEUED:
            conn.execute(
                "UPDATE jobs SET status=?, cancel_requested=1, finished_at=? WHERE id=? AND status=?",
                (CANCELLED, _iso(_utcnow()), job_id, QUEUED),
            )
        else:
            conn.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (job_id,))
        conn.commit()
        return _row_to_dict(
            conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        )
    finally:
        conn.close()


# --- Claiming --------------------------------------------------------------

def requeue_stale(conn: sqlite3.Connection, stale_seconds: int = STALE_RUNNING_SECONDS) -> int:
    """Return abandoned 'running' jobs to the queue.

    This is what makes a worker crash survivable: the job keeps its cursor and
    counters, so the retry resumes rather than restarts.  An attempt is NOT
    charged here — the job did not fail, its worker vanished — but the stale
    sweep still respects max_attempts via the normal failure path.
    """
    cutoff = _iso(_utcnow() - timedelta(seconds=stale_seconds))
    cur = conn.execute(
        """UPDATE jobs SET status=?, worker_id=NULL, available_at=?
           WHERE status=?
             AND COALESCE(heartbeat_at, started_at, created_at) < ?""",
        (QUEUED, _iso(_utcnow()), RUNNING, cutoff),
    )
    conn.commit()
    if cur.rowcount:
        logger.warning("Requeued %d stale running job(s)", cur.rowcount)
    return cur.rowcount


def claim_job(conn: sqlite3.Connection, worker_id: str) -> dict | None:
    """Atomically take one runnable job, or return None.

    Safe against concurrent workers: the outer ``status='queued'`` predicate
    re-checks under SQLite's write lock what the sub-SELECT saw without one, so
    exactly one UPDATE can win.  The winner stamps a token unique to this claim
    so the follow-up SELECT reads back exactly the row it just took, and never
    some other row this worker also owns.
    """
    now = _iso(_utcnow())
    token = f"{worker_id}#{uuid.uuid4().hex}"
    cur = conn.execute(
        """UPDATE jobs
              SET status=?, worker_id=?, attempts=attempts+1,
                  started_at=COALESCE(started_at, ?), heartbeat_at=?
            WHERE id = (
                    SELECT id FROM jobs
                     WHERE status=?
                       AND (available_at IS NULL OR available_at <= ?)
                     ORDER BY id LIMIT 1
                  )
              AND status=?""",
        (RUNNING, token, now, now, QUEUED, now, QUEUED),
    )
    conn.commit()
    if not cur.rowcount:
        return None
    row = conn.execute("SELECT * FROM jobs WHERE worker_id=?", (token,)).fetchone()
    return _row_to_dict(row) if row else None


# --- Progress / completion -------------------------------------------------

def heartbeat(conn: sqlite3.Connection, job_id: int) -> None:
    conn.execute(
        "UPDATE jobs SET heartbeat_at=? WHERE id=?", (_iso(_utcnow()), job_id)
    )
    conn.commit()


def update_progress(conn: sqlite3.Connection, job_id: int, *, cursor: int | None = None,
                    completed: int | None = None, failed: int | None = None,
                    total: int | None = None) -> None:
    sets, params = ["heartbeat_at=?"], [_iso(_utcnow())]
    for name, value in (("cursor", cursor), ("completed", completed),
                        ("failed", failed), ("total", total)):
        if value is not None:
            sets.append(f"{name}=?")
            params.append(value)
    params.append(job_id)
    conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()


def is_cancel_requested(conn: sqlite3.Connection, job_id: int) -> bool:
    row = conn.execute(
        "SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)
    ).fetchone()
    return bool(row and row["cancel_requested"])


def finish_job(conn: sqlite3.Connection, job_id: int, status: str,
               result: dict | None = None, error: str | None = None) -> None:
    conn.execute(
        """UPDATE jobs SET status=?, finished_at=?, result=?, last_error=?,
                           worker_id=NULL
            WHERE id=?""",
        (
            status,
            _iso(_utcnow()),
            json.dumps(result, ensure_ascii=False) if result is not None else None,
            error,
            job_id,
        ),
    )
    conn.commit()


def fail_job(conn: sqlite3.Connection, job_id: int, error: str) -> str:
    """Record a failed attempt: retry with backoff, or give up.

    Returns the resulting status so the caller can log it.
    """
    row = conn.execute(
        "SELECT attempts, max_attempts FROM jobs WHERE id=?", (job_id,)
    ).fetchone()
    attempts = row["attempts"] if row else 1
    max_attempts = row["max_attempts"] if row else 1

    if attempts >= max_attempts:
        finish_job(conn, job_id, FAILED, error=error[:4000])
        return FAILED

    delay = min(BACKOFF_BASE_SECONDS * (2 ** (attempts - 1)), BACKOFF_MAX_SECONDS)
    conn.execute(
        """UPDATE jobs SET status=?, last_error=?, available_at=?, worker_id=NULL
            WHERE id=?""",
        (QUEUED, error[:4000], _iso(_utcnow() + timedelta(seconds=delay)), job_id),
    )
    conn.commit()
    logger.warning(
        "Job %d attempt %d/%d failed (%s); retrying in %ds",
        job_id, attempts, max_attempts, error[:200], delay,
    )
    return QUEUED


# --- Handlers --------------------------------------------------------------

_HANDLERS: dict[str, object] = {}


def register(job_type: str):
    def deco(fn):
        _HANDLERS[job_type] = fn
        return fn
    return deco


def get_handler(job_type: str):
    return _HANDLERS.get(job_type)


def run_job(conn: sqlite3.Connection, job: dict) -> None:
    """Execute one claimed job and record its outcome."""
    handler = get_handler(job["job_type"])
    if handler is None:
        finish_job(conn, job["id"], FAILED,
                   error=f"No handler registered for job_type={job['job_type']!r}")
        return
    try:
        result = handler(conn, job)
    except JobCancelled:
        finish_job(conn, job["id"], CANCELLED, result={"cancelled": True})
        logger.info("Job %d cancelled", job["id"])
        return
    except Exception as e:  # noqa: BLE001 - the queue is the error boundary
        logger.exception("Job %d raised", job["id"])
        fail_job(conn, job["id"], f"{type(e).__name__}: {e}")
        return
    finish_job(conn, job["id"], SUCCEEDED, result=result or {})
    logger.info("Job %d succeeded", job["id"])


class JobCancelled(Exception):
    """Raised by a handler when it observes cancel_requested."""


# --- Worker loop -----------------------------------------------------------

def worker_id() -> str:
    return f"{os.getpid()}:{threading.current_thread().name}"


def work_once(conn: sqlite3.Connection) -> bool:
    """Claim and run at most one job. Returns True if something ran."""
    requeue_stale(conn)
    job = claim_job(conn, worker_id())
    if job is None:
        return False
    logger.info("Job %d claimed (%s, attempt %d/%d)",
                job["id"], job["job_type"], job["attempts"], job["max_attempts"])
    run_job(conn, job)
    return True


def worker_loop(stop: threading.Event, poll_interval: float = 2.0) -> None:
    """Poll for work until ``stop`` is set.

    Each worker owns its own connection: sqlite3 connections are not safe to
    share across threads, and the queue's whole coordination story is the DB.
    """
    conn = _conn()
    try:
        init_jobs_schema(conn)
        while not stop.is_set():
            try:
                did_work = work_once(conn)
            except Exception:
                logger.exception("Worker loop error; backing off")
                did_work = False
            if not did_work:
                stop.wait(poll_interval)
    finally:
        conn.close()


_inprocess_stop: threading.Event | None = None
_inprocess_threads: list[threading.Thread] = []


def start_inprocess_workers(concurrency: int = 1, poll_interval: float = 2.0) -> None:
    """Run workers as daemon threads inside the API process.

    Keeps the app a single process for anyone who just runs uvicorn, which is
    today's user experience.  The threads spend their time blocked on HTTP
    calls to LM Studio, so the GIL is not the bottleneck the way it would be
    for CPU work.
    """
    global _inprocess_stop
    if _inprocess_threads:
        return
    _inprocess_stop = threading.Event()
    for i in range(max(1, concurrency)):
        t = threading.Thread(
            target=worker_loop,
            args=(_inprocess_stop, poll_interval),
            name=f"jobworker-{i}",
            daemon=True,
        )
        t.start()
        _inprocess_threads.append(t)
    logger.info("Started %d in-process job worker(s)", len(_inprocess_threads))


def stop_inprocess_workers(timeout: float = 5.0) -> None:
    if _inprocess_stop is None:
        return
    _inprocess_stop.set()
    for t in _inprocess_threads:
        t.join(timeout=timeout)
    _inprocess_threads.clear()
