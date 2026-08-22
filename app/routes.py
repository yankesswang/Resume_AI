import csv
import io
import json
import logging
import re
import time
import unicodedata
import uuid
from collections import deque
from datetime import date
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.auth import (
    Principal,
    pii_level_for,
    require_permission,
    require_read,
    require_write,
)
from app.pii import redact_candidates, redact_detail
from app.settings import settings

from app.database import (
    _connect,
    create_interview,
    create_interview_status,
    create_manual_candidate,
    delete_candidate,
    delete_interview,
    delete_interview_status,
    ensure_job_requirement,
    get_all_candidates_summary,
    get_all_interviews,
    get_candidate_detail,
    count_batch_candidates,
    delete_import_batch,
    get_candidates_by_import_file,
    get_candidates_export_data,
    get_filter_options,
    get_import_batch_detail,
    get_import_batches,
    get_interested_ids,
    get_interview_statuses,
    get_interview_types,
    create_interview_type,
    delete_interview_type,
    get_invitation_sent_ids,
    get_app_setting,
    get_job_requirement,
    get_match_result,
    set_app_setting,
    set_candidate_interested,
    set_candidate_invitation_sent,
    store_interview_questions,
    update_interview,
    upsert_match_result,
)
from app.parser_service import ingest_pdf
from app.scoring.pipeline import run_full_scoring

logger = logging.getLogger(__name__)

# Auth is applied at the router level rather than on 30-odd individual
# signatures: a NEW endpoint is then protected by default instead of silently
# shipping unauthenticated. Mutating endpoints additionally depend on
# require_write, which rejects read-only keys.
router = APIRouter(dependencies=[Depends(require_read)])

# Health is deliberately outside the authenticated router: container health
# checks and load balancers probe it without credentials.
public_router = APIRouter()

JOB_REQ_PATH = settings.job_requirement_path
ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = settings.output_dir

# Candidate photos live in whichever output_<batch>/ directory produced them,
# so photo paths are resolved relative to this root, which contains them all —
# a single batch dir cannot serve candidates from the other batches. Only
# image files under its output*/ subdirectories are actually served; see
# serve_photo(), which must never expose the DB or source alongside them.
PHOTO_ROOT = settings.photo_root

_IMAGE_SUFFIXES = frozenset((".jpeg", ".jpg", ".png", ".gif", ".webp"))


class ExportRequest(BaseModel):
    candidate_ids: list[int]


class ManualCandidateCreate(BaseModel):
    name: str
    email: str | None = None
    mobile: str | None = None
    education_level: str | None = None
    school: str | None = None
    years_of_experience: str | None = None
    skills_text: str | None = None
    skill_tags: list[str] = []
    desired_salary: str | None = None


class InterestedRequest(BaseModel):
    interested: bool


class InvitationSentRequest(BaseModel):
    invitation_sent: bool


class InterviewCreate(BaseModel):
    candidate_id: int | None = None
    interview_date: str
    interview_time: str | None = None
    interview_type: str = "onsite"
    status: str | None = None
    location: str | None = None
    notes: str | None = None
    assignment_due_date: str | None = None
    available_start_date: str | None = None
    resume_notes: str | None = None


class InterviewUpdate(BaseModel):
    candidate_id: int | None = None
    interview_date: str
    interview_time: str | None = None
    interview_type: str = "onsite"
    status: str | None = None
    location: str | None = None
    notes: str | None = None
    assignment_due_date: str | None = None
    available_start_date: str | None = None
    resume_notes: str | None = None


class InterviewStatusCreate(BaseModel):
    label: str
    color: str = "gray"


class InterviewTypeCreate(BaseModel):
    label: str
    color: str = "gray"
    # Optional stable key stored on the interview row. Generated from the label
    # when omitted; supplying it lets an operator keep an existing value while
    # renaming what the UI shows.
    value: str | None = None


# Which job requirement new scoring runs use. Persisted in app_settings so the
# choice survives a restart — without it, an uploaded job could never actually
# become the active one, because _get_default_job_id() always resolved back to
# job_requirement.json on disk.
_ACTIVE_JOB_SETTING = "active_job_id"


def get_active_job_id() -> int | None:
    """The operator-selected job, or None to fall back to job_requirement.json."""
    try:
        raw = get_app_setting(_ACTIVE_JOB_SETTING)
    except Exception:
        return None
    if not raw:
        return None
    try:
        job_id = int(raw)
    except (TypeError, ValueError):
        return None
    # A job that has since been deleted must not wedge every scoring run.
    return job_id if get_job_requirement(job_id) else None


def set_active_job_id(job_id: int) -> None:
    set_app_setting(_ACTIVE_JOB_SETTING, str(job_id))


def _get_default_job_id() -> int:
    """The job requirement new scoring runs score against.

    An explicitly activated job wins; otherwise fall back to the bundled
    job_requirement.json, which is the pre-existing single-job behaviour.
    """
    active = get_active_job_id()
    if active is not None:
        return active
    data = json.loads(JOB_REQ_PATH.read_text(encoding="utf-8"))
    title = data.get("basic_conditions", {}).get("job_title", "Default Job")
    return ensure_job_requirement(title, json.dumps(data, ensure_ascii=False))


# --- Health ---

@public_router.get("/api/health")
def api_health():
    """Unauthenticated liveness/readiness probe for container health checks.

    Reports only booleans — never config values or key material, since this is
    reachable without credentials.
    """
    db_ok = True
    try:
        conn = _connect()
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
    except Exception:
        db_ok = False
        logger.warning("Health check: database unreachable", exc_info=True)

    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "auth_enabled": settings.auth_enabled,
    }


# --- Photo resolution ---

def _photo_url_for(path: Path) -> str:
    """Map an on-disk image path to its URL under the /output mount."""
    return "/output/" + quote(str(path.relative_to(PHOTO_ROOT)))


def _resolve_photo_url(candidate: dict) -> str:
    """Return the /output/... URL for a candidate's photo.

    Marker writes extracted images into the *batch* directory (e.g.
    ``output_<batch>/1.0/_page_11_Picture_1.jpeg``) while the candidate's
    markdown lives one level deeper, in a per-candidate subdirectory. So the
    photo is resolved against the markdown's own directory first, then its
    ancestors, rather than by string-matching a single configured output dir.
    """
    photo = candidate.get("photo_path", "")
    md_path = candidate.get("source_md_path", "")
    if not photo or not md_path:
        return ""

    # photo_path comes from a markdown image ref and may carry its own
    # relative prefix; only the basename is meaningful on disk.
    name = Path(photo.replace("\\", "/")).name
    md_dir = Path(md_path).parent

    for base in (md_dir, *md_dir.parents):
        try:
            base.relative_to(PHOTO_ROOT)
        except ValueError:
            break  # walked above the served root — stop
        found = base / name
        if found.is_file():
            return _photo_url_for(found)

    return ""


@router.get("/output/{rel_path:path}")
def serve_photo(rel_path: str, principal: Principal = Depends(require_read)):
    """Serve a candidate photo from any output*/ batch directory.

    Deliberately narrower than a StaticFiles mount on PHOTO_ROOT: that root
    also holds the SQLite DB and application source, so only image files
    beneath an ``output*`` subdirectory are served.

    Below ``full`` PII the photo is refused outright. Withholding photo_url
    from the JSON is not enough on its own — the paths are predictable, so a
    masked account that could still GET this route would be one guessed URL
    away from a face to go with the scores.
    """
    if pii_level_for(principal) != "full":
        return JSONResponse(
            {"detail": "你的個資存取等級不允許檢視應徵者照片。"}, status_code=403
        )

    target = (PHOTO_ROOT / rel_path).resolve()

    try:
        parts = target.relative_to(PHOTO_ROOT).parts
    except ValueError:
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    if (
        not parts
        or not parts[0].startswith("output")
        or target.suffix.lower() not in _IMAGE_SUFFIXES
        or not target.is_file()
    ):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    return FileResponse(target)


# --- Background task ---

def _run_match(candidate_id: int, job_id: int):
    """Background task: run the full scoring pipeline and persist results."""
    conn = None
    try:
        detail = get_candidate_detail(candidate_id)
        if not detail:
            return

        job_row = get_job_requirement(job_id)
        if not job_row:
            return

        job_data = json.loads(job_row["source_json"])
        # The db_conn is what enables LLM tier classification at all:
        # classify_experience_tier_llm() returns the keyword-only result when
        # db_conn is None, since it has nowhere to read or write the tier cache.
        # Omitting it here silently downgraded every upload-path score to
        # keyword-only while still looking like a normal result.
        conn = _connect()
        result = run_full_scoring(detail, job_data, conn)
        upsert_match_result(candidate_id, job_id, result)
        logger.info("Scoring completed for candidate %d (job %d)", candidate_id, job_id)
    except Exception:
        logger.exception("Scoring failed for candidate %d", candidate_id)
    finally:
        if conn is not None:
            conn.close()


# --- Upload ---

# PDF magic bytes. The extension is attacker-supplied, so it proves nothing;
# the leading signature is what actually distinguishes a PDF from a script.
_PDF_MAGIC = b"%PDF-"
_UPLOAD_CHUNK = 1 << 20  # 1 MiB

# Sliding-window upload rate limit, keyed by principal (or client IP when auth
# is off). NOTE: this state is per-process. Behind multiple uvicorn workers each
# worker enforces its own window, so the effective limit is N x the configured
# value — move this to Redis before scaling out.
_upload_hits: dict[str, deque] = {}


def _rate_limit_key(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    if principal is not None and not principal.anonymous:
        return principal.key_id
    return request.client.host if request.client else "unknown"


def _check_upload_rate(request: Request) -> None:
    """Raise 429 when this caller has exceeded the upload window."""
    limit = settings.upload_rate_limit
    window = settings.upload_rate_window
    if limit <= 0 or window <= 0:
        return

    key = _rate_limit_key(request)
    now = time.monotonic()
    hits = _upload_hits.setdefault(key, deque())
    while hits and now - hits[0] > window:
        hits.popleft()
    if len(hits) >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"上傳過於頻繁，請於 {window} 秒後再試。",
            headers={"Retry-After": str(window)},
        )
    hits.append(now)


# Filesystem-hostile characters, plus anything that could steer a path.
_UNSAFE_STEM = re.compile(r"[^\w\u4e00-\u9fff.-]+", re.UNICODE)


def _safe_stem(filename: str) -> str:
    """Reduce a client-supplied filename to a harmless, readable stem.

    Only ever used as a *label* inside a generated name — never as the whole
    name — so path traversal cannot survive even if this were bypassed.
    """
    name = Path(filename.replace("\\", "/")).name
    stem = Path(name).stem
    stem = unicodedata.normalize("NFKC", stem)
    stem = _UNSAFE_STEM.sub("_", stem).strip("._-")
    return stem[:60] or "resume"


async def _read_capped(file: UploadFile) -> bytes:
    """Read the upload in chunks, aborting as soon as the cap is passed.

    Chunked so an oversized upload is rejected while it streams, rather than
    after the whole thing has been buffered into this process's memory.
    """
    cap = settings.max_upload_bytes
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            raise HTTPException(
                status_code=413,
                detail=f"檔案超過上限 {cap // (1024 * 1024)} MB。",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _reject_bulk_pdf(pdf_bytes: bytes) -> None:
    """Refuse a multi-candidate 104 export before it reaches the parser.

    `ingest_pdf` inserts everything it parses as a single candidate, so a
    600-page bundle does not fail loudly — it succeeds and merges ~200 people
    into one row. Marker also loads the whole document into host memory, which
    is what exhausted RAM and swap and wedged the server. Both are avoided by
    checking the page count here.

    A PDF whose page count cannot be read is allowed through: the magic-byte
    check already passed, and the parser gives a better error for a damaged
    file than a guess made here.
    """
    cap = settings.max_upload_pages
    if cap <= 0:
        return
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = len(pdf.pages)
    except Exception:
        logger.warning("Could not read page count for upload; allowing it through")
        return

    if pages > cap:
        raise HTTPException(
            status_code=422,
            detail=(
                f"此 PDF 有 {pages} 頁，超過單份履歷上限 {cap} 頁，"
                "看起來是 104 批次匯出檔（內含多位應徵者）。"
                "請改用 scripts/batch_import.py 匯入，它會自動拆分成多位候選人。"
            ),
        )


@router.post("/api/upload")
async def api_upload_pdf(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    _principal: Principal = Depends(require_write),
):
    _check_upload_rate(request)

    pdf_bytes = await _read_capped(file)
    if not pdf_bytes.startswith(_PDF_MAGIC):
        raise HTTPException(status_code=415, detail="僅接受 PDF 檔案。")
    _reject_bulk_pdf(pdf_bytes)

    # The stored filename must not be attacker-controlled: the original name is
    # kept for display only, while the on-disk name is generated here. A short
    # uuid suffix also stops two uploads of the same filename from overwriting
    # each other's PDF — which previously silently repointed an existing
    # candidate's source_pdf_path at a different person's resume.
    stored_name = f"{_safe_stem(file.filename or '')}_{uuid.uuid4().hex[:12]}.pdf"

    candidate_id = ingest_pdf(pdf_bytes, stored_name)
    candidate = get_candidate_detail(candidate_id)
    if candidate:
        candidate["photo_url"] = _resolve_photo_url(candidate)

    job_id = _get_default_job_id()
    background_tasks.add_task(_run_match, candidate_id, job_id)
    logger.info(
        "Auto-queued scoring for candidate %d (uploaded as %s, original %r)",
        candidate_id, stored_name, file.filename,
    )

    return {"candidate_id": candidate_id, "candidate": candidate}


# --- Candidates ---

@router.get("/api/candidates")
async def api_candidates(
    principal: Principal = Depends(require_read),
    scope: str | None = None,
    batch_id: int | None = None,
    file_id: int | None = None,
    limit: int | None = None,
    offset: int = 0,
    sort_by: str | None = None,
    sort_dir: str = "desc",
    search: str | None = None,
    education_level: str | None = None,
    llm_tier: int | None = None,
    interested: bool | None = None,
    invitation_sent: bool | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    candidate_type: str | None = None,
    min_school_tier: str | None = None,
):
    """List candidates.

    Without `limit` this returns the full array, unchanged, so the existing
    frontend and any script hitting this endpoint keeps working. With `limit` it
    returns the paginated envelope {items, total, limit, offset, has_more} — the
    full corpus is ~6.2 MB of JSON, versus ~105 KB for a 50-row page.

    `min_school_tier` (A/B/C) gates on the candidate's best school using the
    same `school_tier()` the scoring pipeline and the hard filter use, so an
    operator override saved from 學校分級 applies here too. It replaces a
    hardcoded keyword list that used to live in the frontend table component and
    could not see those overrides.
    """
    result = get_all_candidates_summary(
        scope=scope,
        batch_id=batch_id,
        file_id=file_id,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_dir=sort_dir,
        search=search,
        education_level=education_level,
        llm_tier=llm_tier,
        interested=interested,
        invitation_sent=invitation_sent,
        min_score=min_score,
        max_score=max_score,
        candidate_type=candidate_type,
        min_school_tier=min_school_tier,
        with_total=limit is not None,
    )
    # Redaction is applied after photo_url is resolved, not before: the
    # resolver reads photo_path, which masking blanks, so redacting first
    # would leave a broken URL instead of no URL.
    level = pii_level_for(principal)
    if limit is None:
        for c in result:
            c["photo_url"] = _resolve_photo_url(c)
        return redact_candidates(result, level)
    for c in result["items"]:
        c["photo_url"] = _resolve_photo_url(c)
    result["items"] = redact_candidates(result["items"], level)
    return result


@router.get("/api/candidates/{candidate_id}")
async def api_candidate_detail(
    candidate_id: int, principal: Principal = Depends(require_read)
):
    candidate = get_candidate_detail(candidate_id)
    if not candidate:
        return JSONResponse({"error": "Candidate not found"}, status_code=404)
    candidate["photo_url"] = _resolve_photo_url(candidate)
    return redact_detail(candidate, pii_level_for(principal))


@router.get("/api/candidates/{candidate_id}/match")
async def api_match_result(candidate_id: int):
    try:
        job_id = _get_default_job_id()
        match = get_match_result(candidate_id, job_id)
    except Exception:
        match = None
    return {"match": match}


@router.post("/api/candidates/{candidate_id}/match")
async def api_run_match(candidate_id: int, background_tasks: BackgroundTasks, _principal: Principal = Depends(require_write)):
    job_id = _get_default_job_id()
    background_tasks.add_task(_run_match, candidate_id, job_id)
    return {"status": "queued", "candidate_id": candidate_id, "job_id": job_id}


@router.post("/api/candidates/{candidate_id}/interview-questions")
async def api_interview_questions(candidate_id: int, _principal: Principal = Depends(require_write)):
    """Generate LLM-based interview questions in Chinese for a candidate."""
    from app.llm import generate_interview_questions

    candidate = get_candidate_detail(candidate_id)
    if not candidate:
        return JSONResponse({"error": "Candidate not found"}, status_code=404)

    try:
        job_id = _get_default_job_id()
        job_row = get_job_requirement(job_id)
        job_data = json.loads(job_row["source_json"]) if job_row else {}
    except Exception:
        job_data = {}

    try:
        result = generate_interview_questions(candidate, job_data)
    except Exception as e:
        err = str(e)
        if "Connection refused" in err or "ConnectError" in err:
            return JSONResponse(
                {"error": "LM Studio is not running. Please start it at http://192.168.0.84:1234."},
                status_code=503,
            )
        logger.exception("Interview questions generation failed for candidate %d", candidate_id)
        return JSONResponse({"error": "LLM error: " + err}, status_code=500)
    store_interview_questions(candidate_id, result)
    return result


def _run_interview_questions(candidate_id: int, job_id: int):
    """Background task: generate and store interview questions for one candidate."""
    from app.llm import generate_interview_questions
    try:
        candidate = get_candidate_detail(candidate_id)
        if not candidate:
            return
        job_row = get_job_requirement(job_id)
        job_data = json.loads(job_row["source_json"]) if job_row else {}
        result = generate_interview_questions(candidate, job_data)
        store_interview_questions(candidate_id, result)
        logger.info("Interview questions generated for candidate %d", candidate_id)
    except Exception:
        logger.exception("Interview questions failed for candidate %d", candidate_id)


@router.post("/api/batch-interview-questions")
async def api_batch_interview_questions(background_tasks: BackgroundTasks, _principal: Principal = Depends(require_write)):
    """Generate interview questions for all interested candidates (background)."""
    ids = get_interested_ids()
    if not ids:
        return {"status": "no_interested_candidates", "count": 0}
    job_id = _get_default_job_id()
    for cid in ids:
        background_tasks.add_task(_run_interview_questions, cid, job_id)
    logger.info("Queued interview question generation for %d candidates", len(ids))
    return {"status": "queued", "count": len(ids), "candidate_ids": ids}


@router.get("/api/candidates/{candidate_id}/scorecard")
async def api_scorecard(candidate_id: int):
    """Return the full scorecard with all dimension breakdowns."""
    try:
        job_id = _get_default_job_id()
        match = get_match_result(candidate_id, job_id)
    except Exception:
        match = None
    if not match:
        return JSONResponse({"error": "No match result found. Run scoring first."}, status_code=404)
    return {"scorecard": match}


@router.post("/api/candidates/batch-match")
async def api_batch_match(background_tasks: BackgroundTasks, _principal: Principal = Depends(require_write)):
    """Enqueue scoring for candidates that don't have a result yet.

    Now backed by the durable queue in app/jobs.py instead of BackgroundTasks:
    pushing 3179 LLM calls into the event loop meant hours of blocking with no
    progress, no cancellation, and total loss on restart.

    The response keeps its original shape — ``status`` / ``count`` / ``job_id``
    (the job REQUIREMENT id, as before) — so the existing frontend call in
    ListView.vue is unaffected. ``queue_job_id`` is additive, for polling
    ``GET /api/jobs/{id}``.
    """
    from app.jobs_routes import enqueue_rescore

    info = enqueue_rescore("unscored")
    return {
        "status": "queued",
        "count": info["count"],
        "job_id": info["requirement_job_id"],
        "queue_job_id": info["job_id"],
    }


# --- Manual candidate creation ---

@router.post("/api/candidates/manual")
async def api_create_manual_candidate(body: ManualCandidateCreate, _principal: Principal = Depends(require_write)):
    candidate_id = create_manual_candidate(
        name=body.name,
        email=body.email,
        mobile=body.mobile,
        education_level=body.education_level,
        school=body.school,
        years_of_experience=body.years_of_experience,
        skills_text=body.skills_text,
        skill_tags=body.skill_tags,
        desired_salary=body.desired_salary,
    )
    return {"id": candidate_id, "name": body.name}


@router.delete("/api/candidates/{candidate_id}")
async def api_delete_candidate(candidate_id: int, _principal: Principal = Depends(require_write)):
    delete_candidate(candidate_id)
    return {"deleted": candidate_id}


# --- Interested ---

@router.get("/api/interested")
async def api_get_interested():
    return {"ids": get_interested_ids()}


@router.post("/api/candidates/{candidate_id}/interested")
async def api_set_interested(candidate_id: int, body: InterestedRequest, _principal: Principal = Depends(require_write)):
    set_candidate_interested(candidate_id, body.interested)
    return {"candidate_id": candidate_id, "interested": body.interested}


# --- Invitation sent ---

@router.get("/api/invitation-sent")
async def api_get_invitation_sent():
    return {"ids": get_invitation_sent_ids()}


@router.post("/api/candidates/{candidate_id}/invitation-sent")
async def api_set_invitation_sent(candidate_id: int, body: InvitationSentRequest, _principal: Principal = Depends(require_write)):
    set_candidate_invitation_sent(candidate_id, body.invitation_sent)
    return {"candidate_id": candidate_id, "invitation_sent": body.invitation_sent}


# --- Interviews ---

@router.get("/api/interviews")
async def api_get_interviews():
    interviews = get_all_interviews()
    for iv in interviews:
        iv["photo_url"] = _resolve_photo_url(iv)
    return interviews


@router.post("/api/interviews")
async def api_create_interview(body: InterviewCreate, _principal: Principal = Depends(require_write)):
    interview_id = create_interview(body.model_dump())
    return {"id": interview_id}


@router.put("/api/interviews/{interview_id}")
async def api_update_interview(interview_id: int, body: InterviewUpdate, _principal: Principal = Depends(require_write)):
    update_interview(interview_id, body.model_dump())
    return {"id": interview_id}


@router.delete("/api/interviews/{interview_id}")
async def api_delete_interview(interview_id: int, _principal: Principal = Depends(require_write)):
    delete_interview(interview_id)
    return {"deleted": interview_id}


# --- Interview Statuses ---

@router.get("/api/interview-statuses")
async def api_get_interview_statuses():
    return get_interview_statuses()


@router.post("/api/interview-statuses")
async def api_create_interview_status(body: InterviewStatusCreate, _principal: Principal = Depends(require_write)):
    status_id = create_interview_status(body.label, body.color)
    return {"id": status_id, "label": body.label, "color": body.color}


@router.delete("/api/interview-statuses/{status_id}")
async def api_delete_interview_status(status_id: int, _principal: Principal = Depends(require_write)):
    delete_interview_status(status_id)
    return {"deleted": status_id}


# --- Interview Types ---
# Symmetrical with statuses above: both are operator vocabulary on the same
# form, and having one editable while the other needed a frontend rebuild was
# an accident of how each grew, not a decision.

@router.get("/api/interview-types")
async def api_get_interview_types():
    return get_interview_types()


@router.post("/api/interview-types")
async def api_create_interview_type(body: InterviewTypeCreate, _principal: Principal = Depends(require_write)):
    return create_interview_type(body.label, body.color, body.value)


@router.delete("/api/interview-types/{type_id}")
async def api_delete_interview_type(type_id: int, _principal: Principal = Depends(require_write)):
    delete_interview_type(type_id)
    return {"deleted": type_id}


# --- Email templates ---

class EmailTemplatesUpdate(BaseModel):
    templates: list[dict]
    sender: dict | None = None


class EmailComposeRequest(BaseModel):
    template_id: str
    interview_id: int | None = None


@router.get("/api/email-templates")
async def api_get_email_templates():
    """All letter templates, the sender block, and the variable vocabulary."""
    from app.email_templates import VARIABLES, load, unknown_variables

    data = load()
    for tpl in data["templates"]:
        tpl["unknown_variables"] = unknown_variables(
            f"{tpl['subject']}\n{tpl['body']}"
        )
    return {
        "templates": data["templates"],
        "sender": data["sender"],
        "variables": [{"key": k, "label": label} for k, label in VARIABLES],
    }


@router.put("/api/email-templates")
async def api_save_email_templates(
    payload: EmailTemplatesUpdate,
    _principal: Principal = Depends(require_permission("write:scoring")),
):
    from app.email_templates import TemplateError, save

    try:
        data = save(payload.templates, payload.sender)
    except TemplateError as e:
        return JSONResponse(status_code=400, content={"error": str(e), "saved": False})
    return {**data, "saved": True}


@router.post("/api/email-templates/reset")
async def api_reset_email_templates(
    _principal: Principal = Depends(require_permission("write:scoring")),
):
    from app.email_templates import default_sender, default_templates, save

    return {**save(default_templates(), default_sender()), "saved": True}


@router.post("/api/candidates/{candidate_id}/compose-email")
async def api_compose_email(
    candidate_id: int,
    body: EmailComposeRequest,
    principal: Principal = Depends(require_read),
):
    """Render one template for one candidate into a copy-ready letter.

    Gated on full PII. The rendered body legitimately contains the candidate's
    name and address, so returning it to a `partial`/`masked` principal would
    hand back through the letter exactly what redact_detail() withholds from
    the profile — the redaction layer would be decorative.
    """
    from app.email_templates import load, render_template

    if pii_level_for(principal) != "full":
        raise HTTPException(
            status_code=403,
            detail="產生信件需要完整的個資檢視權限（信件內文包含候選人姓名與 Email）。",
        )

    candidate = get_candidate_detail(candidate_id)
    if not candidate:
        return JSONResponse({"error": "Candidate not found"}, status_code=404)

    data = load()
    template = next(
        (t for t in data["templates"] if t["id"] == body.template_id), None
    )
    if template is None:
        return JSONResponse({"error": "Template not found"}, status_code=404)

    interview = _pick_interview(candidate_id, body.interview_id)

    job_title = ""
    try:
        job_row = get_job_requirement(_get_default_job_id())
        job_title = json.loads(job_row["source_json"]).get(
            "basic_conditions", {}
        ).get("job_title", "")
    except Exception:
        # A letter with a blank job title is still usable; failing to open the
        # composer because the active job is unreadable is not.
        logger.warning("compose-email: could not read active job title", exc_info=True)

    return render_template(
        template,
        candidate,
        sender=data["sender"],
        job_title=job_title,
        interview=interview,
    )


def _pick_interview(candidate_id: int, interview_id: int | None) -> dict | None:
    """The interview a letter should quote.

    Defaults to the candidate's soonest upcoming interview rather than the most
    recently created one: an invitation letter is about the next meeting, and
    quoting a past date is worse than quoting none.
    """
    rows = [
        i for i in get_all_interviews() if i.get("candidate_id") == candidate_id
    ]
    if not rows:
        return None
    if interview_id is not None:
        return next((i for i in rows if i["id"] == interview_id), None)

    today = date.today().isoformat()
    upcoming = [i for i in rows if (i.get("interview_date") or "") >= today]
    # get_all_interviews() is already ordered by date/time, so the first
    # upcoming row is the soonest; with none upcoming, the last row is the most
    # recent past one.
    return upcoming[0] if upcoming else rows[-1]


# --- Filters ---

def _active_tier_labels() -> list[dict]:
    """Tier levels and names for the list filter, from the active job.

    The tier *names* are per-role data: a job scored through a domain profile
    calls level 2 "獨立業務", not "RAG Architect". The badges already render
    ``experience_detail.tier_label`` from the scored row, so a filter dropdown
    with its own hardcoded copy is the one place the two can disagree — and it
    disagreed for every non-AI role.

    Falls back to the calibrated AI ladder (via ``config.tier_labels()``, so an
    operator rename on /scoring is honoured) when no profile is attached, which
    is the same condition under which the pipeline runs the AI scorers.
    """
    labels: dict[int, str] = {}
    try:
        job_id = get_active_job_id()
        if job_id is not None:
            job = get_job_requirement(job_id)
            if job:
                from app.scoring.pipeline import resolve_profile

                data = job.get("requirements_json") or job
                if isinstance(data, str):
                    data = json.loads(data)
                profile = resolve_profile(data)
                if profile is not None:
                    labels = {i: profile.tier_label(i) for i in range(4)}
    except Exception as e:
        logger.warning("讀取職缺分級名稱失敗，改用預設: %s", e)

    if not labels:
        from app.scoring.config import tier_labels as _cfg_tier_labels

        try:
            labels = _cfg_tier_labels()
        except Exception:
            labels = {}

    fallback = {0: "Non-AI", 1: "Wrapper", 2: "RAG Architect", 3: "AI Expert"}
    return [
        {"value": i, "label": (labels.get(i) or fallback[i])}
        for i in range(4)
    ]


@router.get("/api/filters")
async def api_filters(scope: str | None = None, batch_id: int | None = None):
    options = get_filter_options(scope=scope, batch_id=batch_id)
    options["ai_tiers"] = _active_tier_labels()
    return options


@router.get("/api/import-batches")
async def api_import_batches(_principal: Principal = Depends(require_read)):
    return get_import_batches()


@router.get("/api/import-batches/{batch_id}")
async def api_import_batch_detail(
    batch_id: int, _principal: Principal = Depends(require_read)
):
    batch = get_import_batch_detail(batch_id)
    if not batch:
        return JSONResponse({"error": "Import batch not found"}, status_code=404)
    return batch


class DeleteBatchBody(BaseModel):
    # Default False: removing a mis-attributed *record* must not destroy
    # resumes that parsed correctly. Deleting the people too is a separate,
    # deliberate choice made in the confirmation dialog.
    delete_candidates: bool = False


@router.delete("/api/import-batches/{batch_id}")
async def api_delete_import_batch(
    batch_id: int,
    body: DeleteBatchBody | None = None,
    _principal: Principal = Depends(require_write),
):
    """Delete an import batch, detaching or deleting the candidates it made."""
    delete_candidates = bool(body and body.delete_candidates)
    result = delete_import_batch(batch_id, delete_candidates=delete_candidates)
    if result is None:
        return JSONResponse({"error": "Import batch not found"}, status_code=404)
    logger.info(
        "Deleted import batch %d (%s): %d candidates deleted, %d detached",
        batch_id, result["batch_name"],
        result["candidates_deleted"], result["candidates_detached"],
    )
    return result


@router.get("/api/import-files/{file_id}/candidates")
async def api_import_file_candidates(
    file_id: int, principal: Principal = Depends(require_read)
):
    candidates = get_candidates_by_import_file(file_id)
    for c in candidates:
        c["photo_url"] = _resolve_photo_url(c)
    return redact_candidates(candidates, pii_level_for(principal))


# --- Export ---

# Export leaves the system's control: once a spreadsheet of applicant contact
# details is on someone's laptop, no permission change can pull it back. So it
# needs its own permission (interviewers read candidates but cannot export
# them), and the file itself is redacted to the exporter's PII level — an
# export must not be the way around a mask.

@router.post("/api/export/candidates")
async def api_export_candidates(
    body: ExportRequest, principal: Principal = Depends(require_permission("export"))
):
    """Return full candidate data + scores for the given IDs."""
    data = get_candidates_export_data(body.candidate_ids)
    for c in data:
        c["photo_url"] = _resolve_photo_url(c)
    return redact_candidates(data, pii_level_for(principal))


@router.post("/api/export/candidates/csv")
async def api_export_candidates_csv(
    body: ExportRequest, principal: Principal = Depends(require_permission("export"))
):
    """Return a downloadable CSV with UTF-8 BOM (for Excel CJK support)."""
    data = redact_candidates(
        get_candidates_export_data(body.candidate_ids), pii_level_for(principal)
    )

    output = io.StringIO()
    output.write("\ufeff")  # UTF-8 BOM for Excel
    writer = csv.writer(output)

    writer.writerow([
        "ID", "姓名", "類型", "Email", "備註", "英文名", "104代碼", "年齡", "學歷", "學校", "科系",
        "年資", "技能", "手機", "期望薪資",
        "總分", "學歷分", "經歷分", "技能分", "AI分", "工程分", "加權總分",
        "AI Tier", "優勢", "不足", "分析", "工作經歷",
    ])

    for c in data:
        work_lines = [
            f"{w.get('company_name', '')} - {w.get('job_title', '')} "
            f"({w.get('date_start', '')}~{w.get('date_end', '')})"
            for w in c.get("work_experiences", [])
        ]

        exp_detail = c.get("experience_detail")
        tier_info = (
            f"T{exp_detail['tier']} {exp_detail.get('tier_label', '')}"
            if isinstance(exp_detail, dict) and exp_detail.get("tier")
            else ""
        )

        writer.writerow([
            c.get("id", ""),
            c.get("name", ""),
            c.get("candidate_type", ""),
            c.get("email", ""),
            c.get("resume_notes", "") or "",
            c.get("english_name", ""),
            c.get("code_104", ""),
            c.get("age", ""),
            c.get("education_level", ""),
            c.get("school", ""),
            c.get("major", ""),
            c.get("years_of_experience", ""),
            ", ".join(c.get("skill_tags", [])),
            c.get("mobile1", ""),
            c.get("desired_salary", ""),
            c.get("overall_score", ""),
            c.get("education_score", ""),
            c.get("experience_score", ""),
            c.get("skills_score", ""),
            c.get("s_ai", ""),
            c.get("m_eng", ""),
            c.get("s_total", ""),
            tier_info,
            " | ".join(c.get("strengths", [])),
            " | ".join(c.get("gaps", [])),
            c.get("analysis_text", ""),
            "\n".join(work_lines),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=candidates.csv"},
    )


# --- Scoring configuration -------------------------------------------------
# Lets the scoring algorithm be tuned from the UI without a redeploy.

class ScoringConfigUpdate(BaseModel):
    config: dict


@router.get("/api/scoring-config")
async def api_get_scoring_config():
    """Active scoring config plus the defaults, for the tuning UI."""
    from app.scoring.config import CONFIG_PATH, DEFAULTS, config_version, load
    return {
        "config": load(),
        "defaults": DEFAULTS,
        "version": config_version(),
        "customized": CONFIG_PATH.exists(),
        "path": str(CONFIG_PATH),
    }


@router.get("/api/scoring-config/school-roster")
async def api_school_roster():
    """Built-in tier → school names, so the tuning UI can show real groups.

    The roster is presentation only: `school_tier()` still matches through the
    regex tables, so a school absent here scores exactly as before.
    """
    from app.scoring.education import default_school_roster
    return {"roster": default_school_roster()}


@router.get("/api/scoring-config/major-catalogue")
async def api_major_catalogue():
    """Field → department names, so the profile editor can offer real majors.

    A picker vocabulary only: a major absent here still scores through the
    profile's own tier lists.
    """
    from app.scoring.education import major_catalogue
    return {"catalogue": major_catalogue()}


@router.put("/api/scoring-config")
async def api_save_scoring_config(payload: ScoringConfigUpdate, _principal: Principal = Depends(require_write)):
    """Validate and persist a scoring config."""
    from app.scoring.config import config_version, save
    try:
        cfg = save(payload.config)
    except ValueError as e:
        return JSONResponse(
            status_code=400, content={"error": str(e), "saved": False}
        )
    return {"config": cfg, "version": config_version(), "saved": True}


@router.post("/api/scoring-config/validate")
async def api_validate_scoring_config(payload: ScoringConfigUpdate, _principal: Principal = Depends(require_write)):
    """Check a config without saving it — powers inline UI validation."""
    from app.scoring.config import DEFAULTS, _deep_merge, validate
    errors = validate(_deep_merge(DEFAULTS, payload.config))
    return {"valid": not errors, "errors": errors}


@router.post("/api/scoring-config/reset")
async def api_reset_scoring_config(_principal: Principal = Depends(require_write)):
    """Discard the on-disk override and return to built-in defaults."""
    from app.scoring.config import config_version, reset
    return {"config": reset(), "version": config_version(), "saved": True}


@router.post("/api/scoring-config/preview")
async def api_preview_scoring_config(payload: ScoringConfigUpdate, _principal: Principal = Depends(require_write)):
    """Re-score a sample of candidates under a candidate config.

    Runs against the CURRENT config and the proposed one so the UI can show the
    before/after impact before anything is persisted.  Uses cached LLM tiers,
    so this is fast and costs no LLM calls.
    """
    import copy as _copy

    from app.database import _connect, get_candidate_detail
    from app.scoring import config as cfg_mod
    from app.scoring.pipeline import run_full_scoring

    errors = cfg_mod.validate(cfg_mod._deep_merge(cfg_mod.DEFAULTS, payload.config))
    if errors:
        return JSONResponse(status_code=400, content={"error": "; ".join(errors)})

    job_row = get_job_requirement(_get_default_job_id())
    job_data = json.loads(job_row["source_json"])

    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT c.id FROM candidates c
               JOIN match_results m ON m.candidate_id = c.id
               ORDER BY m.overall_score DESC LIMIT 40"""
        ).fetchall()
        ids = [r[0] for r in rows]

        original = _copy.deepcopy(cfg_mod.load())
        results = []
        try:
            for cid in ids:
                detail = get_candidate_detail(cid)
                if not detail:
                    continue
                cfg_mod._cache = original
                before = run_full_scoring(detail, job_data, conn)
                cfg_mod._cache = cfg_mod._deep_merge(cfg_mod.DEFAULTS, payload.config)
                after = run_full_scoring(detail, job_data, conn)
                results.append({
                    "id": cid,
                    "name": detail.get("name", ""),
                    "before": before.overall_score,
                    "after": after.overall_score,
                    "delta": round(after.overall_score - before.overall_score, 1),
                    "tier": after.experience_detail.tier,
                })
        finally:
            cfg_mod._cache = original
    finally:
        conn.close()

    moved = [r for r in results if abs(r["delta"]) >= 0.1]
    return {
        "sample_size": len(results),
        "changed": len(moved),
        "avg_delta": round(
            sum(r["delta"] for r in results) / len(results), 2
        ) if results else 0.0,
        "results": results,
    }


# --- LLM provider configuration --------------------------------------------
# Lets the chat and embedding backends be pointed at LM Studio or the OpenAI
# API from the UI, without editing .env and restarting the process.

class LLMConfigUpdate(BaseModel):
    config: dict


class LLMTestRequest(BaseModel):
    # Test the *unsaved* form state when supplied, so an operator can verify a
    # key before committing it. Falls back to the stored config when omitted.
    config: dict | None = None
    section: str = "chat"


@router.get("/api/llm-config")
async def api_get_llm_config(_principal: Principal = Depends(require_write)):
    """Active LLM config (secrets masked), defaults, and env-pinned fields.

    Gated on write, not read: the endpoint discloses internal endpoints and
    which credentials exist, which is infrastructure detail rather than
    candidate data.
    """
    from app import llm_config

    cfg = llm_config.load(force=True)
    return {
        "config": llm_config.redacted(cfg),
        "defaults": llm_config.DEFAULTS,
        "providers": list(llm_config.PROVIDERS),
        # Suggestions, not a whitelist — the operator can still type a model
        # name the catalogue does not list (see llm_config.MODEL_CATALOGUE).
        "model_catalogue": llm_config.model_catalogue(),
        "env_pinned": llm_config.env_pinned(),
        "version": llm_config.config_version(),
        "has_secret": {
            "chat": llm_config.has_secret("chat"),
            "embedding": llm_config.has_secret("embedding"),
        },
        "resolved": {
            "chat": llm_config.endpoint("chat"),
            "embedding": llm_config.endpoint("embedding"),
        },
    }


@router.put("/api/llm-config")
async def api_save_llm_config(payload: LLMConfigUpdate, _principal: Principal = Depends(require_write)):
    """Validate and persist the LLM config."""
    from app import llm_config

    try:
        cfg = llm_config.save(payload.config)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e), "saved": False})
    return {
        "config": llm_config.redacted(cfg),
        "version": llm_config.config_version(),
        "env_pinned": llm_config.env_pinned(),
        "resolved": {
            "chat": llm_config.endpoint("chat"),
            "embedding": llm_config.endpoint("embedding"),
        },
        "saved": True,
    }


@router.post("/api/llm-config/validate")
async def api_validate_llm_config(payload: LLMConfigUpdate, _principal: Principal = Depends(require_write)):
    """Check a config without saving it — powers inline UI validation."""
    from app import llm_config

    merged = llm_config._deep_merge(llm_config.DEFAULTS, payload.config or {})
    errors = llm_config.validate(merged)
    return {"valid": not errors, "errors": errors}


@router.post("/api/llm-config/reset")
async def api_reset_llm_config(_principal: Principal = Depends(require_write)):
    """Discard the stored override and return to defaults (plus environment)."""
    from app import llm_config

    cfg = llm_config.reset()
    return {
        "config": llm_config.redacted(cfg),
        "version": llm_config.config_version(),
        "env_pinned": llm_config.env_pinned(),
        "saved": True,
    }


@router.post("/api/llm-config/test")
async def api_test_llm_config(payload: LLMTestRequest, _principal: Principal = Depends(require_write)):
    """Send one tiny real request to the configured backend.

    A settings page that only stores strings tells the operator nothing about
    whether the endpoint answers, the key is accepted, or the model name
    exists — the three ways this configuration actually fails. Each of those
    surfaces here as a distinct message instead of as a failed scoring run
    hours later.
    """
    import copy as _copy

    import httpx

    from app import llm_config

    section = payload.section if payload.section in ("chat", "embedding") else "chat"

    # Test the proposed config without persisting it: swapping the cache under
    # the lock is what the scoring-config preview does for the same reason.
    original = llm_config._cache
    try:
        if payload.config is not None:
            stored = llm_config._read_stored()
            incoming = _copy.deepcopy(payload.config)
            # A masked key means "the one already stored" — resolve it here too,
            # or "test" would check a credential of four bullet characters.
            for sec_name in ("chat", "embedding"):
                sec = incoming.get(sec_name)
                if isinstance(sec, dict) and sec.get("api_key") == llm_config.MASK:
                    previous = (stored.get(sec_name) or {}).get("api_key")
                    if previous:
                        sec["api_key"] = previous
                    else:
                        sec.pop("api_key")
            candidate = llm_config._deep_merge(
                llm_config.DEFAULTS, llm_config._deep_merge(stored, incoming)
            )
            errors = llm_config.validate(candidate)
            if errors:
                return JSONResponse(
                    status_code=400, content={"ok": False, "error": "; ".join(errors)}
                )
            # Deliberately NOT _apply_env: the operator asked to test the values
            # in front of them. Overlaying the environment here would test a
            # different endpoint than the one displayed and report the result as
            # if it belonged to the typed config — a green tick for a URL that
            # was never contacted. Env-pinned fields are marked read-only in the
            # UI, so what is testable is what is editable.
            llm_config._cache = candidate

        url = llm_config.endpoint(section)
        model_name = llm_config.model(section)
        headers = llm_config.headers(section)

        started = time.monotonic()
        if section == "chat":
            body: dict = {
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 5,
                "temperature": 0,
            }
            if model_name:
                body["model"] = model_name
            if llm_config.supports_thinking_toggle("chat"):
                body["thinking"] = {"type": "disabled"}
        else:
            body = {"input": "ping", "model": model_name}

        try:
            # Short timeout: this is a reachability check, not a scoring call.
            resp = httpx.post(url, json=body, headers=headers, timeout=30.0)
        except httpx.ConnectError:
            return {
                "ok": False,
                "url": url,
                "error": f"無法連線到 {url}。請確認服務已啟動且網址正確。",
            }
        except httpx.TimeoutException:
            return {"ok": False, "url": url, "error": f"連線 {url} 逾時（30 秒）。"}

        elapsed_ms = int((time.monotonic() - started) * 1000)

        if resp.status_code == 401 or resp.status_code == 403:
            return {
                "ok": False,
                "url": url,
                "status": resp.status_code,
                "error": "認證失敗：API 金鑰無效或未設定。",
            }
        if resp.status_code == 404:
            return {
                "ok": False,
                "url": url,
                "status": resp.status_code,
                "error": f"找不到端點或模型（404）。請確認網址路徑與模型名稱 {model_name!r}。",
            }
        if resp.status_code != 200:
            detail = resp.text[:300]
            return {
                "ok": False,
                "url": url,
                "status": resp.status_code,
                "error": f"服務回應 {resp.status_code}：{detail}",
            }

        data = resp.json()
        if section == "chat":
            try:
                reply = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                return {
                    "ok": False,
                    "url": url,
                    "error": "回應格式不符 OpenAI 規格，無法解析 choices[0].message.content。",
                }
            return {
                "ok": True,
                "url": url,
                "model": data.get("model") or model_name,
                "elapsed_ms": elapsed_ms,
                "sample": (reply or "").strip()[:120],
            }

        try:
            vector = data["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError):
            return {
                "ok": False,
                "url": url,
                "error": "回應格式不符 OpenAI 規格，無法解析 data[0].embedding。",
            }
        return {
            "ok": True,
            "url": url,
            "model": data.get("model") or model_name,
            "elapsed_ms": elapsed_ms,
            "dimensions": len(vector),
        }
    finally:
        llm_config._cache = original
