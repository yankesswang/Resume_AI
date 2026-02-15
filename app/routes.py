import json
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.database import (
    ensure_job_requirement,
    get_all_candidates_summary,
    get_candidate_detail,
    get_filter_options,
    get_job_requirement,
    get_match_result,
    upsert_match_result,
)
from app.llm import match_candidate_to_job
from app.models import EnhancedMatchResult, MatchResultExtract, ResumeExtract
from app.parser_service import ingest_existing_markdown, ingest_pdf, reparse_existing
from app.scoring.pipeline import run_full_scoring

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

JOB_REQ_PATH = Path(__file__).resolve().parent.parent / "job_requirement.json"


def _get_default_job_id() -> int:
    """Load the default job requirement from JSON and ensure it's in the DB."""
    data = json.loads(JOB_REQ_PATH.read_text(encoding="utf-8"))
    title = data.get("basic_conditions", {}).get("job_title", "Default Job")
    return ensure_job_requirement(title, json.dumps(data, ensure_ascii=False))


OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


_photo_cache: dict[str, str] | None = None


def _build_photo_cache() -> dict[str, str]:
    """Build a relative-path -> URL cache for all image files in output/."""
    cache: dict[str, str] = {}
    if OUTPUT_DIR.exists():
        for p in OUTPUT_DIR.rglob("*"):
            if p.is_file() and p.suffix.lower() in (".jpeg", ".jpg", ".png", ".gif", ".webp"):
                rel = str(p.relative_to(OUTPUT_DIR))
                url = f"/output/{rel}"
                cache[rel] = url
    return cache


def _extract_output_relative_dir(md_path: str) -> str:
    """Extract the directory relative to 'output/' from a source_md_path.

    Handles both relative paths like 'output/1/1_original.md'
    and absolute paths from other machines like
    '/home/trx50/gitlab/resume_ai/output/1/1_original.md'.
    """
    # Find 'output/' in the path and take everything after it
    idx = md_path.find("output/")
    if idx != -1:
        # e.g. "output/1/1_original.md" -> "1"
        rel = md_path[idx + len("output/"):]
        return str(Path(rel).parent)
    return ""


def _resolve_photo_url(candidate: dict) -> str:
    """Build the /output/... URL for a candidate's photo."""
    global _photo_cache
    photo = candidate.get("photo_path", "")
    if not photo:
        return ""

    if _photo_cache is None:
        _photo_cache = _build_photo_cache()

    md_path = candidate.get("source_md_path", "")
    if md_path:
        rel_dir = _extract_output_relative_dir(md_path)
        if rel_dir:
            # Check candidate's own directory (e.g. "1/_page_0_Picture_2.jpeg")
            candidate_rel = f"{rel_dir}/{photo}"
            if candidate_rel in _photo_cache:
                return _photo_cache[candidate_rel]
            # Check parent directory (batch imports with subdirs)
            parent_dir = str(Path(rel_dir).parent)
            if parent_dir and parent_dir != ".":
                parent_rel = f"{parent_dir}/{photo}"
                if parent_rel in _photo_cache:
                    return _photo_cache[parent_rel]

    return f"/output/{photo}"


# --- Pages ---

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    candidates = get_all_candidates_summary()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "candidates": candidates,
    })


@router.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})


@router.post("/upload")
async def upload_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    pdf_bytes = await file.read()
    candidate_id = ingest_pdf(pdf_bytes, file.filename)
    # Auto-run scoring after ingestion
    job_id = _get_default_job_id()
    background_tasks.add_task(_run_match, candidate_id, job_id)
    return RedirectResponse(url=f"/candidates/{candidate_id}", status_code=303)


@router.post("/api/upload")
async def api_upload_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    pdf_bytes = await file.read()
    candidate_id = ingest_pdf(pdf_bytes, file.filename)
    candidate = get_candidate_detail(candidate_id)
    if candidate:
        candidate["photo_url"] = _resolve_photo_url(candidate)

    # Auto-run scoring after ingestion
    job_id = _get_default_job_id()
    background_tasks.add_task(_run_match, candidate_id, job_id)
    logger.info("Auto-queued scoring for candidate %d", candidate_id)

    return {"candidate_id": candidate_id, "candidate": candidate}


@router.get("/candidates/{candidate_id}", response_class=HTMLResponse)
async def candidate_detail(request: Request, candidate_id: int):
    candidate = get_candidate_detail(candidate_id)
    if not candidate:
        return HTMLResponse("Candidate not found", status_code=404)

    # Check for existing match result
    try:
        job_id = _get_default_job_id()
        match = get_match_result(candidate_id, job_id)
    except Exception:
        match = None

    return templates.TemplateResponse("candidate.html", {
        "request": request,
        "candidate": candidate,
        "match": match,
    })


def _run_match(candidate_id: int, job_id: int):
    """Background task to run enhanced scoring pipeline."""
    try:
        detail = get_candidate_detail(candidate_id)
        if not detail:
            return

        job_row = get_job_requirement(job_id)
        if not job_row:
            return

        job_data = json.loads(job_row["source_json"])

        # Run the full enhanced scoring pipeline
        result = run_full_scoring(detail, job_data)
        upsert_match_result(candidate_id, job_id, result)
        logger.info("Enhanced match completed for candidate %d, job %d", candidate_id, job_id)
    except Exception:
        logger.exception("Match failed for candidate %d", candidate_id)


@router.post("/candidates/{candidate_id}/match")
async def run_match(candidate_id: int, background_tasks: BackgroundTasks):
    job_id = _get_default_job_id()
    background_tasks.add_task(_run_match, candidate_id, job_id)
    return RedirectResponse(url=f"/candidates/{candidate_id}/match", status_code=303)


@router.get("/candidates/{candidate_id}/match", response_class=HTMLResponse)
async def view_match(request: Request, candidate_id: int):
    candidate = get_candidate_detail(candidate_id)
    if not candidate:
        return HTMLResponse("Candidate not found", status_code=404)

    job_id = _get_default_job_id()
    match = get_match_result(candidate_id, job_id)
    job_row = get_job_requirement(job_id)

    return templates.TemplateResponse("match.html", {
        "request": request,
        "candidate": candidate,
        "match": match,
        "job": json.loads(job_row["source_json"]) if job_row else {},
    })


@router.post("/candidates/{candidate_id}/reparse")
async def reparse(candidate_id: int):
    reparse_existing(candidate_id)
    return RedirectResponse(url=f"/candidates/{candidate_id}", status_code=303)


# --- JSON API ---

@router.get("/api/candidates")
async def api_candidates():
    candidates = get_all_candidates_summary()
    # Enrich each candidate with photo_url
    for c in candidates:
        c["photo_url"] = _resolve_photo_url(c)
    return candidates


@router.get("/api/candidates/{candidate_id}")
async def api_candidate_detail(candidate_id: int):
    candidate = get_candidate_detail(candidate_id)
    if not candidate:
        return JSONResponse({"error": "Candidate not found"}, status_code=404)
    candidate["photo_url"] = _resolve_photo_url(candidate)
    return candidate


@router.get("/api/candidates/{candidate_id}/match")
async def api_match_result(candidate_id: int):
    try:
        job_id = _get_default_job_id()
        match = get_match_result(candidate_id, job_id)
    except Exception:
        match = None
    return {"match": match}


@router.post("/api/candidates/{candidate_id}/match")
async def api_run_match(candidate_id: int, background_tasks: BackgroundTasks):
    job_id = _get_default_job_id()
    background_tasks.add_task(_run_match, candidate_id, job_id)
    return {"status": "matching", "candidate_id": candidate_id, "job_id": job_id}


@router.get("/api/candidates/{candidate_id}/scorecard")
async def api_scorecard(candidate_id: int):
    """Return the full enhanced scorecard with all dimension breakdowns."""
    try:
        job_id = _get_default_job_id()
        match = get_match_result(candidate_id, job_id)
    except Exception:
        match = None
    if not match:
        return JSONResponse({"error": "No match result found. Run match first."}, status_code=404)
    return {"scorecard": match}


@router.post("/api/candidates/batch-match")
async def api_batch_match(background_tasks: BackgroundTasks):
    """Run matching for all candidates that don't have a match result yet."""
    job_id = _get_default_job_id()
    candidates = get_all_candidates_summary()
    queued = 0
    for c in candidates:
        if c.get("overall_score") is None:
            background_tasks.add_task(_run_match, c["id"], job_id)
            queued += 1
    return {"status": "queued", "count": queued, "job_id": job_id}


@router.get("/api/filters")
async def api_filters():
    return get_filter_options()


# --- Ingest existing markdown ---

@router.get("/ingest-existing", response_class=HTMLResponse)
async def ingest_existing_page(request: Request):
    """List available markdown files in output/ that can be ingested."""
    output_dir = Path(__file__).resolve().parent.parent / "output"
    md_files = sorted(output_dir.glob("**/*_original.md"))
    return templates.TemplateResponse("upload.html", {
        "request": request,
        "md_files": [str(f) for f in md_files],
    })


@router.post("/ingest-markdown")
async def ingest_markdown(request: Request):
    form = await request.form()
    md_path = form.get("md_path", "")
    if not md_path or not Path(md_path).exists():
        return HTMLResponse("Markdown file not found", status_code=400)
    candidate_id = ingest_existing_markdown(str(md_path))
    return RedirectResponse(url=f"/candidates/{candidate_id}", status_code=303)
