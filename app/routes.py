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
from app.models import MatchResultExtract, ResumeExtract
from app.parser_service import ingest_existing_markdown, ingest_pdf, reparse_existing

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


def _resolve_photo_url(candidate: dict) -> str:
    """Build the /output/... URL for a candidate's photo."""
    photo = candidate.get("photo_path", "")
    if not photo:
        return ""
    # Derive the output sub-folder from source_md_path
    md_path = candidate.get("source_md_path", "")
    if md_path:
        folder = Path(md_path).parent
        # Check the markdown's own directory first
        if (Path(OUTPUT_DIR).parent / folder / photo).exists():
            return f"/{folder}/{photo}"
        # For batch imports, images are in the parent directory (e.g. output/many_people/)
        parent_folder = folder.parent
        if (Path(OUTPUT_DIR).parent / parent_folder / photo).exists():
            return f"/{parent_folder}/{photo}"
    # Fallback: search output/ subdirectories recursively
    for sub in OUTPUT_DIR.rglob(photo):
        rel = sub.relative_to(OUTPUT_DIR)
        return f"/output/{rel}"
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
async def upload_pdf(file: UploadFile = File(...)):
    pdf_bytes = await file.read()
    candidate_id = ingest_pdf(pdf_bytes, file.filename)
    return RedirectResponse(url=f"/candidates/{candidate_id}", status_code=303)


@router.post("/api/upload")
async def api_upload_pdf(file: UploadFile = File(...)):
    pdf_bytes = await file.read()
    candidate_id = ingest_pdf(pdf_bytes, file.filename)
    candidate = get_candidate_detail(candidate_id)
    if candidate:
        candidate["photo_url"] = _resolve_photo_url(candidate)
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
    """Background task to run matching."""
    try:
        detail = get_candidate_detail(candidate_id)
        if not detail:
            return

        job_row = get_job_requirement(job_id)
        if not job_row:
            return

        job_data = json.loads(job_row["source_json"])

        # Build a ResumeExtract from the stored detail
        candidate_extract = ResumeExtract(
            name=detail["name"] or "",
            english_name=detail["english_name"] or "",
            birth_year=detail["birth_year"] or "",
            age=detail["age"] or "",
            nationality=detail["nationality"] or "",
            current_status=detail["current_status"] or "",
            earliest_start=detail["earliest_start"] or "",
            education_level=detail["education_level"] or "",
            school=detail["school"] or "",
            major=detail["major"] or "",
            military_status=detail["military_status"] or "",
            desired_salary=detail["desired_salary"] or "",
            desired_job_categories=detail["desired_job_categories"],
            desired_locations=detail["desired_locations"],
            desired_industry=detail["desired_industry"] or "",
            ideal_positions=detail["ideal_positions"],
            years_of_experience=detail["years_of_experience"] or "",
            linkedin_url=detail["linkedin_url"] or "",
            email=detail["email"] or "",
            skills_text=detail["skills_text"] or "",
            skill_tags=detail["skill_tags"],
            self_introduction=detail["self_introduction"] or "",
        )

        result = match_candidate_to_job(candidate_extract, job_data)
        upsert_match_result(candidate_id, job_id, result)
        logger.info("Match completed for candidate %d, job %d", candidate_id, job_id)
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
