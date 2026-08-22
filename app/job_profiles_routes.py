"""Job posting API — upload a JD, get a scoring standard for that role.

The screening flow this enables:

    POST /api/job-postings/upload   PDF / DOCX / TXT / plain text  →  job + profile
    GET  /api/job-postings          list every open role and its profile state
    GET  /api/job-postings/{id}     the job requirement + its editable profile
    PUT  /api/job-postings/{id}/profile   save a human-edited profile
    POST /api/job-postings/{id}/profile/regenerate   re-run the LLM
    POST /api/job-postings/{id}/preview  score N candidates under this profile
    POST /api/job-postings/{id}/activate make it the default scoring job

Generation is an LLM call over a whole document, so it is slow (tens of
seconds) but one-shot per role — it is not on any candidate's scoring path.

A generated profile is stored with ``profile_status='draft'`` and is NOT used
for scoring until a human reviews it.  That gate is deliberate: a screening
standard nobody read is how a hiring system starts rejecting people for reasons
no one can explain.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth import Principal, require_read, require_write
from app.database import (
    create_job_requirement,
    delete_job_requirement,
    get_job_requirement,
    list_job_requirements,
    update_job_profile,
    update_job_source,
)
from app.scoring.domain_profile import DomainProfile, parse_profile, validate_profile

logger = logging.getLogger(__name__)

# Router-level read auth, matching app/routes.py: a NEW endpoint added here is
# then protected by default rather than silently shipping unauthenticated.
router = APIRouter(dependencies=[Depends(require_read)])

# A JD is a page or two. Anything larger is a mis-upload (someone's resume
# archive, a scanned catalogue) and would waste a long LLM call to find out.
MAX_JD_BYTES = 10 * 1024 * 1024
_PDF_MAGIC = b"%PDF"
_DOCX_MAGIC = b"PK\x03\x04"


# --- JD text extraction -----------------------------------------------------

def _extract_text(data: bytes, filename: str) -> str:
    """Pull plain text out of an uploaded JD.

    PDFs go through pdfplumber rather than the Marker GPU pipeline: a JD is a
    born-digital text document, so the text layer is all that is needed and it
    costs no GPU. A scanned JD raises, which is the honest answer — the operator
    can paste the text instead.
    """
    name = (filename or "").lower()

    if data.startswith(_PDF_MAGIC) or name.endswith(".pdf"):
        try:
            import pdfplumber
        except ImportError as e:
            raise HTTPException(
                status_code=503,
                detail="伺服器未安裝 pdfplumber，無法解析 PDF 職缺文件。",
            ) from e
        import io
        pages = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
        text = "\n".join(pages).strip()
        if not text:
            raise HTTPException(
                status_code=422,
                detail="這份 PDF 沒有文字圖層（可能是掃描檔）。請改貼上純文字內容。",
            )
        return text

    if data.startswith(_DOCX_MAGIC) or name.endswith(".docx"):
        try:
            import docx  # python-docx
        except ImportError as e:
            raise HTTPException(
                status_code=503,
                detail="伺服器未安裝 python-docx，無法解析 Word 職缺文件。請改上傳 PDF 或貼上純文字。",
            ) from e
        import io
        document = docx.Document(io.BytesIO(data))
        parts = [p.text for p in document.paragraphs]
        # Requirements are very often laid out in a table, which paragraph
        # iteration skips entirely.
        for table in document.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        text = "\n".join(x for x in parts if x.strip()).strip()
        if not text:
            raise HTTPException(status_code=422, detail="Word 檔內容為空。")
        return text

    for encoding in ("utf-8", "utf-8-sig", "big5", "cp950"):
        try:
            text = data.decode(encoding).strip()
            if text:
                return text
        except UnicodeDecodeError:
            continue
    raise HTTPException(
        status_code=415,
        detail="無法辨識的檔案格式。支援 PDF、Word (.docx) 與純文字。",
    )


async def _read_capped(file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_JD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"職缺文件超過上限 {MAX_JD_BYTES // (1024 * 1024)} MB。",
            )
        chunks.append(chunk)
    return b"".join(chunks)


# --- Endpoints --------------------------------------------------------------

@router.post("/api/job-postings/upload")
async def api_upload_job_posting(
    file: UploadFile | None = File(None),
    text: str = Form(""),
    title: str = Form(""),
    _principal: Principal = Depends(require_write),
):
    """Upload a job description and build a scoring standard for it.

    Accepts either a file or pasted text.  Returns the job id, the structured
    requirement, the generated profile, and any validation problems the
    reviewer needs to fix before the profile can go live.
    """
    from app.scoring.profile_builder import (
        extract_job_requirement,
        generate_domain_profile,
    )

    filename = ""
    if file is not None:
        raw = await _read_capped(file)
        filename = file.filename or ""
        jd_text = _extract_text(raw, filename)
    elif text.strip():
        jd_text = text.strip()
    else:
        raise HTTPException(status_code=400, detail="請提供職缺文件或貼上職缺內容。")

    if len(jd_text) < 40:
        raise HTTPException(
            status_code=422,
            detail="職缺內容過短，無法據以建立評分標準。請提供完整的職務說明與應徵條件。",
        )

    try:
        job_data = extract_job_requirement(jd_text, filename)
    except Exception as e:
        logger.exception("JD extraction failed")
        raise HTTPException(status_code=502, detail=f"職缺解析失敗：{e}") from e

    if title.strip():
        job_data.setdefault("basic_conditions", {})["job_title"] = title.strip()
    job_title = (
        job_data.get("basic_conditions", {}).get("job_title")
        or title.strip()
        or filename
        or "未命名職缺"
    )

    try:
        profile, errors = generate_domain_profile(job_data, filename)
    except Exception as e:
        # The job requirement itself parsed fine, so persist it: the operator can
        # retry generation or write the profile by hand instead of re-uploading.
        logger.exception("Profile generation failed")
        job_id = create_job_requirement(
            job_title, json.dumps(job_data, ensure_ascii=False),
            profile_status="failed", source_document=filename,
        )
        return JSONResponse(
            status_code=502,
            content={
                "job_id": job_id,
                "job": job_data,
                "profile": None,
                "errors": [f"評分標準生成失敗：{e}"],
                "status": "failed",
            },
        )

    # Draft, not ready: a human must review before this standard screens anyone.
    job_id = create_job_requirement(
        job_title,
        json.dumps(job_data, ensure_ascii=False),
        domain_profile=profile.model_dump_json(),
        profile_status="draft",
        source_document=filename,
    )

    return {
        "job_id": job_id,
        "job": job_data,
        "profile": profile.model_dump(),
        "errors": errors,
        "status": "draft",
        "message": (
            "已從職缺文件產生評分標準草稿。請檢視分級定義與關鍵字，確認後再啟用。"
            if not errors else
            "評分標準草稿有需要修正的項目，請檢視後儲存。"
        ),
    }


@router.get("/api/job-postings")
async def api_list_job_postings():
    """Every job requirement and the state of its scoring standard."""
    from app.routes import get_active_job_id
    return {"jobs": list_job_requirements(), "active_job_id": get_active_job_id()}


@router.get("/api/job-postings/{job_id}")
async def api_get_job_posting(job_id: int):
    row = get_job_requirement(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="找不到這個職缺。")
    d = dict(row)
    try:
        job_data = json.loads(d.get("source_json") or "{}")
    except json.JSONDecodeError:
        job_data = {}
    profile = parse_profile(d.get("domain_profile"))
    return {
        "job_id": job_id,
        "title": d.get("title", ""),
        "job": job_data,
        "profile": profile.model_dump() if profile else None,
        "profile_status": d.get("profile_status", "none"),
        "profile_updated_at": d.get("profile_updated_at"),
        "source_document": d.get("source_document", ""),
        "errors": validate_profile(profile) if profile else [],
    }


class ProfileUpdate(BaseModel):
    profile: dict
    # A reviewer saving a draft they have not finished should not accidentally
    # put it into service, so activation is explicit.
    activate: bool = False


@router.put("/api/job-postings/{job_id}/profile")
async def api_save_job_profile(
    job_id: int,
    payload: ProfileUpdate,
    _principal: Principal = Depends(require_write),
):
    """Persist a human-edited scoring standard."""
    if not get_job_requirement(job_id):
        raise HTTPException(status_code=404, detail="找不到這個職缺。")

    try:
        profile = DomainProfile.model_validate(payload.profile)
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"saved": False, "errors": [f"評分標準格式錯誤：{e}"]},
        )

    errors = validate_profile(profile)
    if errors and payload.activate:
        # Saving a broken draft is fine; putting one into service is not.
        return JSONResponse(
            status_code=400,
            content={"saved": False, "errors": errors,
                     "message": "評分標準尚有問題，無法啟用。"},
        )

    profile.source = "manual" if profile.source == "llm" else profile.source
    update_job_profile(
        job_id,
        profile.model_dump_json(),
        profile_status="ready" if payload.activate else "draft",
    )
    return {
        "saved": True,
        "errors": errors,
        "profile": profile.model_dump(),
        "profile_status": "ready" if payload.activate else "draft",
        "fingerprint": profile.fingerprint(),
    }


@router.post("/api/job-postings/{job_id}/profile/regenerate")
async def api_regenerate_job_profile(
    job_id: int,
    _principal: Principal = Depends(require_write),
):
    """Re-run the generator against the stored job requirement."""
    from app.scoring.profile_builder import generate_domain_profile

    row = get_job_requirement(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="找不到這個職缺。")
    try:
        job_data = json.loads(dict(row).get("source_json") or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="職缺內容毀損，無法重新生成。")

    try:
        profile, errors = generate_domain_profile(
            job_data, dict(row).get("source_document", "") or ""
        )
    except Exception as e:
        logger.exception("Profile regeneration failed")
        raise HTTPException(status_code=502, detail=f"評分標準生成失敗：{e}") from e

    update_job_profile(job_id, profile.model_dump_json(), profile_status="draft")
    return {"profile": profile.model_dump(), "errors": errors, "profile_status": "draft"}


class PreviewRequest(BaseModel):
    profile: dict | None = None    # unsaved edits; falls back to the stored one
    limit: int = 20


@router.post("/api/job-postings/{job_id}/preview")
async def api_preview_job_profile(
    job_id: int,
    payload: PreviewRequest,
    _principal: Principal = Depends(require_write),
):
    """Score a sample of candidates under this profile, without saving anything.

    This is the honesty check on a generated standard: a profile whose keywords
    match nothing in the actual pool scores everybody identically, and that is
    visible here in seconds rather than after a multi-hour rescore.

    Uses the keyword path only (no db_conn), so it costs no LLM calls and gives
    the reviewer an immediate answer.
    """
    from app.database import _connect, get_candidate_detail
    from app.scoring.pipeline import run_full_scoring

    row = get_job_requirement(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="找不到這個職缺。")
    d = dict(row)
    try:
        job_data = json.loads(d.get("source_json") or "{}")
    except json.JSONDecodeError:
        job_data = {}

    if payload.profile is not None:
        try:
            profile = DomainProfile.model_validate(payload.profile)
        except Exception as e:
            return JSONResponse(
                status_code=400, content={"error": f"評分標準格式錯誤：{e}"}
            )
    else:
        profile = parse_profile(d.get("domain_profile"))
        if profile is None:
            raise HTTPException(status_code=422, detail="這個職缺還沒有評分標準。")

    job_data = dict(job_data)
    job_data["domain_profile"] = profile.model_dump()

    limit = max(1, min(payload.limit, 100))
    conn = _connect()
    try:
        ids = [
            r[0] for r in conn.execute(
                "SELECT id FROM candidates ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        ]
        results = []
        for cid in ids:
            detail = get_candidate_detail(cid)
            if not detail:
                continue
            # No db_conn: keyword-only scoring, no LLM calls.
            r = run_full_scoring(detail, job_data)
            results.append({
                "id": cid,
                "name": detail.get("name", ""),
                "score": r.overall_score,
                "tier": r.experience_detail.tier,
                "tier_label": r.experience_detail.tier_label,
                "passed_hard_filter": r.passed_hard_filter,
                "hard_filter_failures": r.hard_filter_failures[:3],
                "axes": r.competency_axes,
            })
    finally:
        conn.close()

    results.sort(key=lambda r: r["score"], reverse=True)
    scores = [r["score"] for r in results]
    tier_dist: dict[int, int] = {}
    for r in results:
        tier_dist[r["tier"]] = tier_dist.get(r["tier"], 0) + 1
    rejected = sum(1 for r in results if not r["passed_hard_filter"])

    # Warnings are ordered by root cause and made mutually exclusive. When the
    # hard filter rejects everybody, the flat scores and single-tier
    # distribution are downstream artifacts of that one problem — reporting all
    # four sends the reviewer chasing three symptoms instead of the cause.
    warnings = []
    if results and rejected == len(results):
        warnings.append(
            "硬性條件過嚴，樣本中所有人都被刷掉了。請放寬條件組，"
            "或降低 min_matches。（分數與級距分布在此情況下沒有參考價值。）"
        )
    elif results:
        scored = [r for r in results if r["passed_hard_filter"]]
        scored_values = [r["score"] for r in scored]
        if scored_values and max(scored_values) - min(scored_values) < 5:
            warnings.append(
                "通過硬性條件的候選人分數幾乎相同，表示這組關鍵字在履歷池中幾乎沒有鑑別度，"
                "建議加入更多該領域的具體工具／制度／證照名稱。"
            )
        elif len(tier_dist) <= 1:
            warnings.append("所有候選人落在同一個級距，分級標準無法區分深淺。")
        # A pool that is overwhelmingly Tier 0 is ambiguous: either the keywords
        # are wrong, or these candidates genuinely applied for a different kind
        # of job. Say both, because the fix differs completely.
        elif tier_dist.get(0, 0) / len(results) > 0.9:
            warnings.append(
                "超過 9 成候選人被判為 Tier 0。若此職缺與現有履歷池的領域本來就不同，"
                "這是正常結果；若不是，請檢查關鍵字是否使用了這個領域履歷中真正會出現的字詞。"
            )
        if rejected and rejected / len(results) > 0.8:
            warnings.append(
                f"硬性條件刷掉了 {rejected}/{len(results)} 人。"
                "若這個職缺與現有履歷池領域不同屬正常，否則建議放寬。"
            )

    return {
        "sample_size": len(results),
        "rejected_by_hard_filter": rejected,
        "score_min": min(scores) if scores else 0,
        "score_max": max(scores) if scores else 0,
        "score_avg": round(sum(scores) / len(scores), 1) if scores else 0,
        "tier_distribution": {str(k): v for k, v in sorted(tier_dist.items())},
        "warnings": warnings,
        "results": results,
    }


@router.post("/api/job-postings/{job_id}/activate")
async def api_activate_job_posting(
    job_id: int,
    _principal: Principal = Depends(require_write),
):
    """Make this job the one new scoring runs use.

    Activation does NOT rescore anything by itself — that is hours of work and
    stays the operator's explicit decision via POST /api/jobs/rescore.
    """
    row = get_job_requirement(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="找不到這個職缺。")
    d = dict(row)
    profile = parse_profile(d.get("domain_profile"))
    if profile:
        errors = validate_profile(profile)
        if errors:
            return JSONResponse(
                status_code=400,
                content={"activated": False, "errors": errors,
                         "message": "評分標準尚有問題，無法啟用。"},
            )
        update_job_profile(job_id, profile.model_dump_json(), profile_status="ready")

    from app.routes import set_active_job_id
    set_active_job_id(job_id)
    return {
        "activated": True,
        "job_id": job_id,
        "profile_status": "ready" if profile else "none",
        "message": "已設為目前使用的職缺。既有分數不會自動更新，"
                   "請至背景工作頁面執行重新評分。",
    }


class JobSourceUpdate(BaseModel):
    job: dict
    title: str = ""


@router.put("/api/job-postings/{job_id}")
async def api_update_job_posting(
    job_id: int,
    payload: JobSourceUpdate,
    _principal: Principal = Depends(require_write),
):
    """Edit the job requirement itself (not its scoring standard)."""
    if not get_job_requirement(job_id):
        raise HTTPException(status_code=404, detail="找不到這個職缺。")
    title = (
        payload.title.strip()
        or payload.job.get("basic_conditions", {}).get("job_title")
        or "未命名職缺"
    )
    update_job_source(job_id, title, json.dumps(payload.job, ensure_ascii=False))
    return {"saved": True, "job_id": job_id, "title": title}


@router.delete("/api/job-postings/{job_id}")
async def api_delete_job_posting(
    job_id: int,
    _principal: Principal = Depends(require_write),
):
    """Delete a job posting and the match results scored against it."""
    from app.routes import get_active_job_id
    if get_active_job_id() == job_id:
        raise HTTPException(
            status_code=409,
            detail="這是目前使用中的職缺，請先切換到其他職缺再刪除。",
        )
    if not delete_job_requirement(job_id):
        raise HTTPException(status_code=404, detail="找不到這個職缺。")
    return {"deleted": True, "job_id": job_id}


@router.get("/api/job-postings/{job_id}/profile/template")
async def api_profile_template(job_id: int):
    """The builtin AI-engineer profile, as a starting point for hand-authoring."""
    from app.scoring.builtin_profiles import ai_engineer_profile
    return {"profile": ai_engineer_profile().model_dump()}
