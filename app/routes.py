import csv
import io
import json
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.database import (
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
    get_candidates_export_data,
    get_filter_options,
    get_interested_ids,
    get_interview_statuses,
    get_invitation_sent_ids,
    get_job_requirement,
    get_match_result,
    set_candidate_interested,
    set_candidate_invitation_sent,
    store_interview_questions,
    update_interview,
    upsert_match_result,
)
from app.parser_service import ingest_pdf
from app.scoring.pipeline import run_full_scoring

logger = logging.getLogger(__name__)

router = APIRouter()

JOB_REQ_PATH = Path(__file__).resolve().parent.parent / "job_requirement.json"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


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


def _get_default_job_id() -> int:
    """Load the default job requirement from JSON and ensure it's in the DB."""
    data = json.loads(JOB_REQ_PATH.read_text(encoding="utf-8"))
    title = data.get("basic_conditions", {}).get("job_title", "Default Job")
    return ensure_job_requirement(title, json.dumps(data, ensure_ascii=False))


# --- Photo resolution ---

_photo_cache: dict[str, str] | None = None


def _build_photo_cache() -> dict[str, str]:
    """Build a relative-path → URL mapping for all images under output/."""
    cache: dict[str, str] = {}
    if OUTPUT_DIR.exists():
        for p in OUTPUT_DIR.rglob("*"):
            if p.is_file() and p.suffix.lower() in (".jpeg", ".jpg", ".png", ".gif", ".webp"):
                rel = str(p.relative_to(OUTPUT_DIR))
                cache[rel] = f"/output/{rel}"
    return cache


def _extract_output_relative_dir(md_path: str) -> str:
    """Extract the directory relative to 'output/' from a source_md_path."""
    idx = md_path.find("output/")
    if idx != -1:
        rel = md_path[idx + len("output/"):]
        return str(Path(rel).parent)
    return ""


def _resolve_photo_url(candidate: dict) -> str:
    """Return the /output/... URL for a candidate's photo."""
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
            candidate_rel = f"{rel_dir}/{photo}"
            if candidate_rel in _photo_cache:
                return _photo_cache[candidate_rel]
            parent_dir = str(Path(rel_dir).parent)
            if parent_dir and parent_dir != ".":
                parent_rel = f"{parent_dir}/{photo}"
                if parent_rel in _photo_cache:
                    return _photo_cache[parent_rel]

    return f"/output/{photo}"


# --- Background task ---

def _run_match(candidate_id: int, job_id: int):
    """Background task: run the full scoring pipeline and persist results."""
    try:
        detail = get_candidate_detail(candidate_id)
        if not detail:
            return

        job_row = get_job_requirement(job_id)
        if not job_row:
            return

        job_data = json.loads(job_row["source_json"])
        result = run_full_scoring(detail, job_data)
        upsert_match_result(candidate_id, job_id, result)
        logger.info("Scoring completed for candidate %d (job %d)", candidate_id, job_id)
    except Exception:
        logger.exception("Scoring failed for candidate %d", candidate_id)


# --- Upload ---

@router.post("/api/upload")
async def api_upload_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    pdf_bytes = await file.read()
    candidate_id = ingest_pdf(pdf_bytes, file.filename or "")
    candidate = get_candidate_detail(candidate_id)
    if candidate:
        candidate["photo_url"] = _resolve_photo_url(candidate)

    job_id = _get_default_job_id()
    background_tasks.add_task(_run_match, candidate_id, job_id)
    logger.info("Auto-queued scoring for candidate %d", candidate_id)

    return {"candidate_id": candidate_id, "candidate": candidate}


# --- Candidates ---

@router.get("/api/candidates")
async def api_candidates():
    candidates = get_all_candidates_summary()
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
    return {"status": "queued", "candidate_id": candidate_id, "job_id": job_id}


@router.post("/api/candidates/{candidate_id}/interview-questions")
async def api_interview_questions(candidate_id: int):
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
async def api_batch_interview_questions(background_tasks: BackgroundTasks):
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
async def api_batch_match(background_tasks: BackgroundTasks):
    """Queue scoring for all candidates that don't have a result yet."""
    job_id = _get_default_job_id()
    candidates = get_all_candidates_summary()
    queued = sum(
        1 for c in candidates
        if c.get("overall_score") is None
        and not background_tasks.add_task(_run_match, c["id"], job_id)
    )
    return {"status": "queued", "count": queued, "job_id": job_id}


# --- Manual candidate creation ---

@router.post("/api/candidates/manual")
async def api_create_manual_candidate(body: ManualCandidateCreate):
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
async def api_delete_candidate(candidate_id: int):
    delete_candidate(candidate_id)
    return {"deleted": candidate_id}


# --- Interested ---

@router.get("/api/interested")
async def api_get_interested():
    return {"ids": get_interested_ids()}


@router.post("/api/candidates/{candidate_id}/interested")
async def api_set_interested(candidate_id: int, body: InterestedRequest):
    set_candidate_interested(candidate_id, body.interested)
    return {"candidate_id": candidate_id, "interested": body.interested}


# --- Invitation sent ---

@router.get("/api/invitation-sent")
async def api_get_invitation_sent():
    return {"ids": get_invitation_sent_ids()}


@router.post("/api/candidates/{candidate_id}/invitation-sent")
async def api_set_invitation_sent(candidate_id: int, body: InvitationSentRequest):
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
async def api_create_interview(body: InterviewCreate):
    interview_id = create_interview(body.model_dump())
    return {"id": interview_id}


@router.put("/api/interviews/{interview_id}")
async def api_update_interview(interview_id: int, body: InterviewUpdate):
    update_interview(interview_id, body.model_dump())
    return {"id": interview_id}


@router.delete("/api/interviews/{interview_id}")
async def api_delete_interview(interview_id: int):
    delete_interview(interview_id)
    return {"deleted": interview_id}


# --- Interview Statuses ---

@router.get("/api/interview-statuses")
async def api_get_interview_statuses():
    return get_interview_statuses()


@router.post("/api/interview-statuses")
async def api_create_interview_status(body: InterviewStatusCreate):
    status_id = create_interview_status(body.label, body.color)
    return {"id": status_id, "label": body.label, "color": body.color}


@router.delete("/api/interview-statuses/{status_id}")
async def api_delete_interview_status(status_id: int):
    delete_interview_status(status_id)
    return {"deleted": status_id}


# --- Filters ---

@router.get("/api/filters")
async def api_filters():
    return get_filter_options()


# --- Export ---

@router.post("/api/export/candidates")
async def api_export_candidates(body: ExportRequest):
    """Return full candidate data + scores for the given IDs."""
    data = get_candidates_export_data(body.candidate_ids)
    for c in data:
        c["photo_url"] = _resolve_photo_url(c)
    return data


@router.post("/api/export/candidates/csv")
async def api_export_candidates_csv(body: ExportRequest):
    """Return a downloadable CSV with UTF-8 BOM (for Excel CJK support)."""
    data = get_candidates_export_data(body.candidate_ids)

    output = io.StringIO()
    output.write("\ufeff")  # UTF-8 BOM for Excel
    writer = csv.writer(output)

    writer.writerow([
        "ID", "姓名", "英文名", "104代碼", "年齡", "學歷", "學校", "科系",
        "年資", "技能", "Email", "手機", "期望薪資",
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
            c.get("english_name", ""),
            c.get("code_104", ""),
            c.get("age", ""),
            c.get("education_level", ""),
            c.get("school", ""),
            c.get("major", ""),
            c.get("years_of_experience", ""),
            ", ".join(c.get("skill_tags", [])),
            c.get("email", ""),
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
