"""Job handlers for candidate scoring.

Kept separate from :mod:`app.jobs` so the queue itself stays free of scoring
imports — the worker process can be reasoned about (and tested) without pulling
in the LLM, embedding, and Marker stacks.

Selection modes for a rescore job (``payload["mode"]``):

``all``        every candidate
``unscored``   candidates with no match_results row
``stale``      cached AI tier was produced by a different prompt/config than
               the one this process would use now.  This is the important one:
               all 3179 candidates currently carry prompt hash 5d85e24efd54
               while the live prompt hashes to 0f47676362b3, so every ranking
               on screen predates the current classifier.
``degraded``   rows whose provenance says a service was down when they were
               scored (or that predate provenance entirely)
``ids``        an explicit ``payload["candidate_ids"]`` list
"""

from __future__ import annotations

import json
import logging

from app.jobs import (
    JobCancelled,
    is_cancel_requested,
    register,
    update_progress,
)

logger = logging.getLogger(__name__)

RESCORE = "rescore"

VALID_MODES = ("all", "unscored", "stale", "degraded", "ids")


def _current_versions() -> tuple[str, str]:
    # The classifier identity covers prompt *and* model, so switching provider
    # marks existing tiers stale and `mode="stale"` picks them up.
    from app.llm import tier_classifier_key
    from app.scoring.config import config_version
    return tier_classifier_key(), config_version()


def select_candidate_ids(conn, mode: str, candidate_ids: list[int] | None = None,
                         limit: int | None = None) -> list[int]:
    """Resolve a selection mode to a concrete, ordered id list.

    The list is frozen into the job payload at enqueue time rather than
    re-queried on resume: a job that says "rescore the stale ones" must keep
    meaning the same 3179 rows even as its own work makes some of them current.
    """
    prompt_md5, config_ver = _current_versions()

    if mode == "ids":
        ids = [int(i) for i in (candidate_ids or [])]
    elif mode == "unscored":
        ids = [
            r[0] for r in conn.execute(
                """SELECT c.id FROM candidates c
                   LEFT JOIN match_results m ON m.candidate_id = c.id
                   WHERE m.id IS NULL ORDER BY c.id"""
            )
        ]
    elif mode == "stale":
        # NULL counts as stale — never classified under any prompt.
        ids = [
            r[0] for r in conn.execute(
                """SELECT id FROM candidates
                   WHERE llm_tier_prompt_md5 IS NULL
                      OR llm_tier_prompt_md5 <> ?
                   ORDER BY id""",
                (prompt_md5,),
            )
        ]
    elif mode == "degraded":
        ids = [
            r[0] for r in conn.execute(
                """SELECT c.id FROM candidates c
                   JOIN match_results m ON m.candidate_id = c.id
                   WHERE m.scoring_mode = 'degraded'
                      OR m.scoring_mode IS NULL
                      OR m.scoring_mode = 'unknown'
                   ORDER BY c.id"""
            )
        ]
    elif mode == "all":
        ids = [r[0] for r in conn.execute("SELECT id FROM candidates ORDER BY id")]
    else:
        raise ValueError(f"unknown selection mode {mode!r}")

    if limit:
        ids = ids[:limit]
    return ids


@register(RESCORE)
def run_rescore(conn, job: dict) -> dict:
    """Score a frozen list of candidates, checkpointing after each one.

    Runs with the worker's own DB connection so the tier classifier can read
    and write its cache — ``run_full_scoring`` silently skips the LLM entirely
    when handed ``db_conn=None``, which is exactly the degradation this
    workstream exists to make visible.
    """
    from app.database import get_candidate_detail, get_job_requirement, upsert_match_result
    from app.scoring.pipeline import run_full_scoring

    payload = job["payload"]
    ids: list[int] = [int(i) for i in payload.get("candidate_ids", [])]
    job_id_req = int(payload["job_id"])

    job_row = get_job_requirement(job_id_req)
    if not job_row:
        raise RuntimeError(f"job requirement {job_id_req} not found")
    job_data = json.loads(job_row["source_json"])

    # Resume point. A restarted worker re-enters here with the cursor the
    # previous attempt checkpointed, so completed candidates are not redone.
    start = int(job["cursor"] or 0)
    completed = int(job["completed"] or 0)
    failed = int(job["failed"] or 0)
    degraded = 0

    update_progress(conn, job["id"], total=len(ids))

    for idx in range(start, len(ids)):
        if is_cancel_requested(conn, job["id"]):
            update_progress(conn, job["id"], cursor=idx,
                            completed=completed, failed=failed)
            raise JobCancelled()

        cid = ids[idx]
        try:
            detail = get_candidate_detail(cid)
            if not detail:
                failed += 1
            else:
                result = run_full_scoring(detail, job_data, conn)
                upsert_match_result(cid, job_id_req, result)
                if result.scoring_mode == "degraded":
                    degraded += 1
                completed += 1
        except Exception:
            # One bad candidate must not sink a 3179-item batch; the job's
            # own retry budget is for infrastructure failures, not data ones.
            logger.exception("Rescore failed for candidate %s", cid)
            failed += 1

        # Checkpoint AFTER the item, so the cursor names the next unprocessed
        # index — a crash mid-item re-runs that one item, never skips it.
        update_progress(conn, job["id"], cursor=idx + 1,
                        completed=completed, failed=failed)

    prompt_md5, config_ver = _current_versions()
    return {
        "mode": payload.get("mode"),
        "total": len(ids),
        "completed": completed,
        "failed": failed,
        "degraded": degraded,
        "tier_prompt_md5": prompt_md5,
        "scoring_config_version": config_ver,
    }


def scoring_status() -> dict:
    """Honest snapshot of how current the stored rankings actually are."""
    from app.database import _connect

    prompt_md5, config_ver = _current_versions()
    conn = _connect()
    try:
        one = lambda sql, p=(): conn.execute(sql, p).fetchone()[0]

        total = one("SELECT COUNT(*) FROM candidates")
        scored = one("SELECT COUNT(*) FROM match_results")
        unscored = one(
            """SELECT COUNT(*) FROM candidates c
               LEFT JOIN match_results m ON m.candidate_id = c.id
               WHERE m.id IS NULL"""
        )
        tier_current = one(
            "SELECT COUNT(*) FROM candidates WHERE llm_tier_prompt_md5 = ?",
            (prompt_md5,),
        )
        tier_stale = one(
            """SELECT COUNT(*) FROM candidates
               WHERE llm_tier_prompt_md5 IS NOT NULL
                 AND llm_tier_prompt_md5 <> ?""",
            (prompt_md5,),
        )
        tier_never = one(
            "SELECT COUNT(*) FROM candidates WHERE llm_tier IS NULL OR llm_tier_prompt_md5 IS NULL"
        )

        mode_rows = conn.execute(
            "SELECT COALESCE(scoring_mode, 'unknown') m, COUNT(*) n "
            "FROM match_results GROUP BY 1"
        ).fetchall()
        modes = {r[0]: r[1] for r in mode_rows}

        reason_counts: dict[str, int] = {}
        for (raw,) in conn.execute(
            "SELECT degraded_reasons FROM match_results WHERE degraded_reasons IS NOT NULL"
        ):
            try:
                for reason in json.loads(raw) or []:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
            except (TypeError, ValueError):
                continue

        tier_rows = conn.execute(
            "SELECT llm_tier, COUNT(*) FROM candidates GROUP BY 1 ORDER BY 1"
        ).fetchall()
        tier_dist = {("unclassified" if r[0] is None else str(r[0])): r[1] for r in tier_rows}
    finally:
        conn.close()

    degraded = modes.get("degraded", 0)
    unknown = modes.get("unknown", 0)

    warnings: list[str] = []
    if tier_stale:
        warnings.append(
            f"{tier_stale} 位候選人的 AI 層級是用舊版提示詞分類的，"
            f"目前顯示的排名並非最新標準。"
        )
    if tier_dist.get("0", 0) == 0 and total:
        # Documented calibration invariant: a pool with no Tier 0 at all means
        # the classifier never ran under the current prompt.
        warnings.append("Tier 0（非 AI）人數為 0，代表排名已失真，需重新評分。")
    if unknown:
        warnings.append(f"{unknown} 筆評分結果沒有來源記錄（早於 provenance 功能）。")
    if degraded:
        warnings.append(f"{degraded} 筆評分是在服務降級狀態下產生的，建議重跑。")

    return {
        "total_candidates": total,
        "scored": scored,
        "unscored": unscored,
        "tier_prompt_current": tier_current,
        "tier_prompt_stale": tier_stale,
        "tier_never_classified": tier_never,
        "tier_distribution": tier_dist,
        "scoring_modes": modes,
        "degraded": degraded,
        "unknown_provenance": unknown,
        "degraded_reasons": reason_counts,
        "current_tier_prompt_md5": prompt_md5,
        "current_scoring_config_version": config_ver,
        "warnings": warnings,
        "healthy": not warnings,
    }
