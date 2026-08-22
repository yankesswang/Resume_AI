"""Standalone job-queue worker.

    uv run python -m app.worker_queue

Runs the same loop the in-process threads run, just in its own process.  Point
it at the same DB (``DB_PATH``) as the API and the two coordinate purely
through the ``jobs`` table — no broker, no shared memory.

Use this when scoring should not compete with the API for the same process:
a 3179-candidate rescore is hours of LLM calls, and running it on a separate
machine (or just a separate process that can be restarted independently) keeps
the UI responsive.  Set ``JOB_WORKER_INPROCESS=false`` on the API so it does
not also pull jobs.

Concurrency comes from ``JOB_CONCURRENCY`` and polling from
``JOB_POLL_INTERVAL``.  Ctrl-C (or SIGTERM) stops after the current job's next
item boundary; anything still 'running' is requeued by the stale sweep and
resumes from its checkpointed cursor.
"""

from __future__ import annotations

import logging
import signal
import threading

from app.database import init_db
from app.jobs import init_jobs_schema, worker_loop, _conn
from app.settings import settings

# Registers the rescore handler as a side effect of import.
import app.jobs_scoring  # noqa: F401

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s",
    )

    # The worker may well start before the API has ever run against this DB.
    init_db()
    conn = _conn()
    try:
        init_jobs_schema(conn)
    finally:
        conn.close()

    stop = threading.Event()

    def _shutdown(signum, _frame):
        logger.info("Signal %s received — finishing current item then stopping", signum)
        stop.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    concurrency = max(1, settings.job_concurrency)
    poll = max(0.1, float(settings.job_poll_interval))
    logger.info(
        "Job worker starting: db=%s concurrency=%d poll=%.1fs",
        settings.db_path, concurrency, poll,
    )

    threads = [
        threading.Thread(target=worker_loop, args=(stop, poll),
                         name=f"jobworker-{i}", daemon=False)
        for i in range(concurrency)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    logger.info("Job worker stopped")


if __name__ == "__main__":
    main()
