"""Durable job queue: claiming, retry/backoff, cancellation, resumability.

Runs entirely against a temporary SQLite file — never the production DB.
"""

import sqlite3
import threading
import collections

import pytest

import app.jobs as jobs


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Point the queue at a throwaway DB with only the jobs table."""
    path = tmp_path / "queue.db"

    def _connect():
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    monkeypatch.setattr("app.database._connect", _connect)
    conn = _connect()
    jobs.init_jobs_schema(conn)
    yield conn
    conn.close()


def test_init_schema_is_idempotent(db):
    jobs.init_jobs_schema(db)
    jobs.init_jobs_schema(db)
    cols = {r[1] for r in db.execute("PRAGMA table_info(jobs)")}
    assert {"status", "attempts", "cursor", "cancel_requested", "available_at"} <= cols


def test_enqueue_and_get(db):
    jid = jobs.enqueue("demo", {"x": 1}, total=5)
    job = jobs.get_job(jid)
    assert job["status"] == jobs.QUEUED
    assert job["payload"] == {"x": 1}
    assert job["progress"] == {"total": 5, "completed": 0, "failed": 0, "percent": 0.0}


def test_claim_is_exclusive_under_concurrency(db):
    """Two workers must never end up running the same job.

    The guard is the outer `status='queued'` predicate re-checked under
    SQLite's write lock; without it both workers' sub-SELECTs pick the same id.
    """
    ids = [jobs.enqueue("probe") for _ in range(30)]
    claimed, lock = [], threading.Lock()

    def run(w):
        conn = jobs._conn()
        while (job := jobs.claim_job(conn, f"w{w}")) is not None:
            with lock:
                claimed.append(job["id"])
        conn.close()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(claimed) == sorted(ids)
    assert not [i for i, n in collections.Counter(claimed).items() if n > 1]


def test_claimed_job_is_not_reclaimed(db):
    jobs.enqueue("probe")
    assert jobs.claim_job(db, "w1") is not None
    assert jobs.claim_job(db, "w2") is None


def test_retry_with_backoff_then_permanent_failure(db, monkeypatch):
    monkeypatch.setattr(jobs, "BACKOFF_BASE_SECONDS", 0)
    monkeypatch.setattr(jobs, "BACKOFF_MAX_SECONDS", 0)

    @jobs.register("boom")
    def _boom(conn, job):
        raise RuntimeError("kaboom")

    jid = jobs.enqueue("boom", max_attempts=3)
    for _ in range(3):
        jobs.work_once(db)

    job = jobs.get_job(jid)
    assert job["status"] == jobs.FAILED
    assert job["attempts"] == 3
    assert "kaboom" in job["last_error"]


def test_backoff_gates_the_next_attempt(db):
    """A just-failed job must not be re-claimed until available_at passes."""

    @jobs.register("boom2")
    def _boom(conn, job):
        raise RuntimeError("nope")

    jid = jobs.enqueue("boom2", max_attempts=5)
    jobs.work_once(db)

    assert jobs.get_job(jid)["status"] == jobs.QUEUED
    # available_at is in the future, so nothing is claimable right now.
    assert jobs.claim_job(db, "w1") is None


def test_unknown_job_type_fails_cleanly(db):
    jid = jobs.enqueue("no_handler_for_this")
    jobs.work_once(db)
    job = jobs.get_job(jid)
    assert job["status"] == jobs.FAILED
    assert "No handler registered" in job["last_error"]


def test_cancel_queued_job_is_immediate(db):
    jid = jobs.enqueue("demo")
    assert jobs.request_cancel(jid)["status"] == jobs.CANCELLED
    # A cancelled job is not claimable.
    assert jobs.claim_job(db, "w1") is None


def test_cancel_running_job_stops_at_item_boundary(db):
    """Cancellation is cooperative: the handler stops between items."""
    processed = []

    @jobs.register("cancellable")
    def _handler(conn, job):
        for i in range(10):
            if jobs.is_cancel_requested(conn, job["id"]):
                jobs.update_progress(conn, job["id"], cursor=i)
                raise jobs.JobCancelled()
            processed.append(i)
            jobs.update_progress(conn, job["id"], cursor=i + 1, completed=i + 1)
            if i == 2:
                jobs.request_cancel(job["id"])
        return {}

    jid = jobs.enqueue("cancellable", total=10)
    jobs.work_once(db)

    job = jobs.get_job(jid)
    assert job["status"] == jobs.CANCELLED
    # Stopped partway, and the cursor records where to resume from.
    assert processed == [0, 1, 2]
    assert job["cursor"] == 3


def test_stale_running_job_is_requeued_with_progress_intact(db):
    """A killed worker's job returns to the queue WITHOUT losing its cursor.

    This is what makes a crash resumable rather than a restart.
    """
    jid = jobs.enqueue("demo", total=100)
    jobs.claim_job(db, "dead-worker")
    jobs.update_progress(db, jid, cursor=42, completed=42)

    assert jobs.requeue_stale(db, stale_seconds=-1) == 1

    job = jobs.get_job(jid)
    assert job["status"] == jobs.QUEUED
    assert job["cursor"] == 42
    assert job["completed"] == 42
    assert job["worker_id"] is None


def test_handler_resumes_from_checkpointed_cursor(db):
    """The decisive resumability test: attempt 2 starts where attempt 1 died."""
    seen = []

    @jobs.register("resumable")
    def _handler(conn, job):
        for i in range(int(job["cursor"]), 6):
            seen.append(i)
            if i == 2 and job["attempts"] == 1:
                # Simulate the process dying mid-batch: the cursor is already
                # checkpointed, but the job never reaches a terminal state.
                jobs.update_progress(conn, job["id"], cursor=i + 1, completed=i + 1)
                raise RuntimeError("worker died")
            jobs.update_progress(conn, job["id"], cursor=i + 1, completed=i + 1)
        return {"done": True}

    jid = jobs.enqueue("resumable", total=6, max_attempts=3)
    jobs.work_once(db)                      # attempt 1: dies at item 2
    assert jobs.get_job(jid)["cursor"] == 3

    db.execute("UPDATE jobs SET available_at=NULL WHERE id=?", (jid,))
    db.commit()
    jobs.work_once(db)                      # attempt 2: resumes at item 3

    job = jobs.get_job(jid)
    assert job["status"] == jobs.SUCCEEDED
    # Items 0-2 ran once, then 3-5 — no item was processed twice.
    assert seen == [0, 1, 2, 3, 4, 5]


def test_list_jobs_filters_by_status(db):
    a = jobs.enqueue("demo")
    jobs.enqueue("demo")
    jobs.request_cancel(a)

    cancelled = jobs.list_jobs(status=jobs.CANCELLED)
    assert [j["id"] for j in cancelled] == [a]
    assert len(jobs.list_jobs(status=jobs.QUEUED)) == 1
