"""Durable job queue API.

Lives in its own module (rather than app/routes.py) so the queue endpoints and
the candidate CRUD endpoints can be edited independently.

Every route is behind the shared auth dependencies: a rescore job burns hours
of GPU time and rewrites the ranking of 3179 real applicants, so it is a write
operation in the fullest sense.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth import require_read, require_write
from app.jobs import enqueue, get_job, list_jobs, request_cancel
from app.jobs_scoring import RESCORE, VALID_MODES, scoring_status, select_candidate_ids

logger = logging.getLogger(__name__)

router = APIRouter()


class RescoreRequest(BaseModel):
    # "stale" is the default because it is almost always what the operator
    # actually wants: re-run the rows whose cached tier predates the current
    # prompt, not the whole table.
    mode: str = "stale"
    candidate_ids: list[int] = []
    job_id: int | None = None
    limit: int | None = None       # cap the batch, for a trial run
    max_attempts: int = 3


def _default_job_id() -> int:
    from app.routes import _get_default_job_id
    return _get_default_job_id()


def enqueue_rescore(mode: str, candidate_ids: list[int] | None = None,
                    job_id: int | None = None, limit: int | None = None,
                    max_attempts: int = 3) -> dict:
    """Resolve the selection, freeze it into the payload, and enqueue.

    Shared with app/routes.py so ``/api/candidates/batch-match`` and
    ``/api/jobs/rescore`` cannot drift apart.
    """
    from app.database import _connect

    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {', '.join(VALID_MODES)}")

    resolved_job_id = job_id if job_id is not None else _default_job_id()

    conn = _connect()
    try:
        ids = select_candidate_ids(conn, mode, candidate_ids, limit)
    finally:
        conn.close()

    queue_job_id = enqueue(
        RESCORE,
        payload={
            "mode": mode,
            "job_id": resolved_job_id,
            "candidate_ids": ids,
        },
        total=len(ids),
        max_attempts=max_attempts,
    )
    return {"job_id": queue_job_id, "mode": mode, "count": len(ids),
            "requirement_job_id": resolved_job_id}


@router.post("/api/jobs/rescore")
async def api_enqueue_rescore(body: RescoreRequest, _=Depends(require_write)):
    """Enqueue a durable rescoring job.

    Returns immediately with the queue job id; poll ``GET /api/jobs/{id}`` for
    progress.
    """
    try:
        info = enqueue_rescore(
            body.mode, body.candidate_ids, body.job_id, body.limit, body.max_attempts
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    logger.info("Enqueued rescore job %d (%s, %d candidates)",
                info["job_id"], info["mode"], info["count"])
    return {"status": "queued", **info}


@router.get("/api/jobs")
async def api_list_jobs(status: str | None = None, job_type: str | None = None,
                        limit: int = 50, _=Depends(require_read)):
    return {"jobs": list_jobs(status=status, job_type=job_type, limit=limit)}


@router.get("/api/jobs/{queue_job_id}")
async def api_get_job(queue_job_id: int, _=Depends(require_read)):
    job = get_job(queue_job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    # The frozen id list can hold thousands of entries; the caller wants
    # progress, not the manifest.
    job["payload"] = {
        k: v for k, v in job["payload"].items() if k != "candidate_ids"
    }
    job["payload"]["candidate_count"] = job["progress"]["total"]
    return job


@router.post("/api/jobs/{queue_job_id}/cancel")
async def api_cancel_job(queue_job_id: int, _=Depends(require_write)):
    job = request_cancel(queue_job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    job.pop("payload", None)
    return {"status": job["status"], "cancel_requested": job["cancel_requested"],
            "job_id": queue_job_id}


@router.get("/api/scoring-status")
async def api_scoring_status(_=Depends(require_read)):
    """How current the stored rankings actually are.

    Exists because the cache-invalidation logic was correct but invisible: the
    UI happily rendered rankings built under a prompt that no longer exists.
    """
    return scoring_status()
