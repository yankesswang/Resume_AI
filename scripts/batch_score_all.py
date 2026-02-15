"""Batch score ALL candidates using the rule-based scoring pipeline.

Loads all candidate data in bulk, then scores without LLM/embedding calls.

Usage: .venv/bin/python scripts/batch_score_all.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("LM_STUDIO_URL", "http://192.168.0.84:1234/v1/chat/completions")
os.environ.setdefault("EMBEDDING_URL", "http://192.168.0.84:1234/v1/embeddings")

from app.database import _connect, init_db, ensure_job_requirement
from app.models import (
    EducationExtract,
    EnhancedMatchResult,
    ExperienceTierDetail,
)
from app.scoring.education import score_education
from app.scoring.engineering import score_engineering_maturity
from app.scoring.experience import classify_experience_tier
from app.scoring.hard_filter import apply_hard_filters
from app.scoring.skills import verify_skills

JOB_REQ_PATH = ROOT / "job_requirement.json"


def load_all_candidates():
    """Load all candidates with their work experiences and education in bulk."""
    conn = _connect()

    # Load all candidates
    candidates = {}
    for r in conn.execute("SELECT * FROM candidates ORDER BY id").fetchall():
        d = dict(r)
        for field in ("desired_job_categories", "desired_locations", "ideal_positions", "skill_tags"):
            d[field] = json.loads(d[field] or "[]")
        d["work_experiences"] = []
        d["education"] = []
        candidates[d["id"]] = d

    # Load all work experiences
    for r in conn.execute("SELECT * FROM work_experiences ORDER BY candidate_id, seq").fetchall():
        cid = r["candidate_id"]
        if cid in candidates:
            candidates[cid]["work_experiences"].append(dict(r))

    # Load all education
    for r in conn.execute("SELECT * FROM education ORDER BY candidate_id, seq").fetchall():
        cid = r["candidate_id"]
        if cid in candidates:
            candidates[cid]["education"].append(dict(r))

    conn.close()
    return candidates


def score_candidate(detail: dict, job_data: dict, hard_filter_config: dict) -> EnhancedMatchResult:
    """Score a single candidate using rule-based pipeline only (no LLM/embedding)."""
    work_experiences = detail.get("work_experiences", [])
    education_list = detail.get("education", [])
    skill_tags = detail.get("skill_tags", [])
    if isinstance(skill_tags, str):
        skill_tags = json.loads(skill_tags) if skill_tags else []
    raw_markdown = detail.get("raw_markdown", "") or ""

    edu_extracts = [
        EducationExtract(
            school=ed.get("school", ""),
            department=ed.get("department", ""),
            degree_level=ed.get("degree_level", ""),
        )
        for ed in education_list
    ]

    # Hard filter
    if hard_filter_config:
        passed, failures = apply_hard_filters(skill_tags, work_experiences, raw_markdown, hard_filter_config)
    else:
        passed, failures = True, []

    if not passed:
        return EnhancedMatchResult(
            overall_score=10.0,
            passed_hard_filter=False,
            hard_filter_failures=failures,
            experience_detail=ExperienceTierDetail(tier=1, tier_label="Wrapper"),
            analysis_text="候選人未通過硬性門檻篩選。" + " ".join(failures),
        )

    # Score all dimensions
    edu_detail = score_education(edu_extracts, raw_markdown)
    exp_detail = classify_experience_tier(work_experiences, skill_tags, raw_markdown)
    eng_detail = score_engineering_maturity(work_experiences, skill_tags, raw_markdown)
    skill_detail = verify_skills(skill_tags, work_experiences)

    s_ai = exp_detail.score
    m_eng = eng_detail.m_eng
    s_total = round(s_ai * (1 + m_eng), 1)

    # Final score: weighted sum = 100 (no semantic similarity in batch mode)
    W_EXP = 0.35   # AI depth
    W_ENG = 0.20   # Engineering maturity
    W_SEM = 0.20   # Semantic similarity (0 in batch mode)
    W_EDU = 0.15   # Education
    W_SKL = 0.10   # Skills

    eng_score_normalized = min(m_eng / 0.5, 1.0) * 100.0
    overall = round(
        s_ai * W_EXP
        + eng_score_normalized * W_ENG
        + 0.0 * W_SEM  # no embedding in batch
        + edu_detail.score * W_EDU
        + skill_detail.score * W_SKL,
        1,
    )
    overall = min(overall, 100.0)

    # Tags
    from app.scoring.pipeline import _generate_tags, _generate_analysis, _build_analysis_text
    tags = _generate_tags(exp_detail, eng_detail, skill_detail)
    strengths, gaps, interview_suggestions = _generate_analysis(
        edu_detail, exp_detail, eng_detail, skill_detail, 0.0,
    )
    analysis_text = _build_analysis_text(
        detail, edu_detail, exp_detail, eng_detail, skill_detail,
        overall, s_ai, m_eng, 0.0,
    )

    return EnhancedMatchResult(
        overall_score=overall,
        s_ai=s_ai, m_eng=m_eng, s_total=s_total,
        education_score=edu_detail.score,
        experience_score=exp_detail.score,
        skills_score=skill_detail.score,
        education_detail=edu_detail,
        experience_detail=exp_detail,
        engineering_detail=eng_detail,
        skill_detail=skill_detail,
        passed_hard_filter=True,
        hard_filter_failures=[],
        semantic_similarity=0.0,
        tags=tags,
        analysis_text=analysis_text,
        strengths=strengths,
        gaps=gaps,
        interview_suggestions=interview_suggestions,
    )


def batch_upsert(results: dict[int, EnhancedMatchResult], job_id: int):
    """Bulk insert/update all match results in a single transaction."""
    conn = _connect()
    cur = conn.cursor()
    for cid, r in results.items():
        cur.execute(
            """INSERT INTO match_results (
                candidate_id, job_id, overall_score, education_score,
                experience_score, skills_score, analysis_text, strengths, gaps,
                s_ai, m_eng, s_total,
                education_detail, experience_detail, engineering_detail, skill_detail,
                passed_hard_filter, hard_filter_failures, semantic_similarity,
                tags, interview_suggestions
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(candidate_id, job_id) DO UPDATE SET
                overall_score=excluded.overall_score,
                education_score=excluded.education_score,
                experience_score=excluded.experience_score,
                skills_score=excluded.skills_score,
                analysis_text=excluded.analysis_text,
                strengths=excluded.strengths,
                gaps=excluded.gaps,
                s_ai=excluded.s_ai,
                m_eng=excluded.m_eng,
                s_total=excluded.s_total,
                education_detail=excluded.education_detail,
                experience_detail=excluded.experience_detail,
                engineering_detail=excluded.engineering_detail,
                skill_detail=excluded.skill_detail,
                passed_hard_filter=excluded.passed_hard_filter,
                hard_filter_failures=excluded.hard_filter_failures,
                semantic_similarity=excluded.semantic_similarity,
                tags=excluded.tags,
                interview_suggestions=excluded.interview_suggestions,
                created_at=CURRENT_TIMESTAMP""",
            (
                cid, job_id, r.overall_score, r.education_score,
                r.experience_score, r.skills_score, r.analysis_text,
                json.dumps(r.strengths, ensure_ascii=False),
                json.dumps(r.gaps, ensure_ascii=False),
                r.s_ai, r.m_eng, r.s_total,
                json.dumps(r.education_detail.model_dump(), ensure_ascii=False),
                json.dumps(r.experience_detail.model_dump(), ensure_ascii=False),
                json.dumps(r.engineering_detail.model_dump(), ensure_ascii=False),
                json.dumps(r.skill_detail.model_dump(), ensure_ascii=False),
                1 if r.passed_hard_filter else 0,
                json.dumps(r.hard_filter_failures, ensure_ascii=False),
                r.semantic_similarity,
                json.dumps(r.tags, ensure_ascii=False),
                json.dumps(r.interview_suggestions, ensure_ascii=False),
            ),
        )
    conn.commit()
    conn.close()


def main():
    init_db()

    job_data = json.loads(JOB_REQ_PATH.read_text(encoding="utf-8"))
    job_id = ensure_job_requirement(
        job_data.get("basic_conditions", {}).get("job_title", "Default Job"),
        json.dumps(job_data, ensure_ascii=False),
    )
    hard_filter_config = job_data.get("hard_filters", {})

    print("Loading all candidates from DB...", flush=True)
    t0 = time.time()
    candidates = load_all_candidates()
    print(f"  Loaded {len(candidates)} candidates in {time.time()-t0:.1f}s", flush=True)

    print("Scoring...", flush=True)
    t1 = time.time()
    results: dict[int, EnhancedMatchResult] = {}
    failed = 0

    for i, (cid, detail) in enumerate(candidates.items()):
        try:
            results[cid] = score_candidate(detail, job_data, hard_filter_config)
        except Exception as e:
            failed += 1
            if failed <= 5:
                print(f"  ERROR ID={cid}: {e}", flush=True)

        if (i + 1) % 200 == 0:
            elapsed = time.time() - t1
            rate = (i + 1) / elapsed
            eta = (len(candidates) - i - 1) / rate
            print(f"  [{i+1:>5}/{len(candidates)}] {rate:.0f}/s | ETA {eta:.0f}s", flush=True)

    t2 = time.time()
    print(f"  Scored {len(results)} in {t2-t1:.1f}s ({len(results)/(t2-t1):.0f}/s)", flush=True)

    print("Saving to DB...", flush=True)
    batch_upsert(results, job_id)
    t3 = time.time()
    print(f"  Saved in {t3-t2:.1f}s", flush=True)

    # Print top 20
    ranked = sorted(results.items(), key=lambda x: x[1].s_total, reverse=True)
    print(f"\nTop 20 candidates:", flush=True)
    print(f"{'Rank':>4} {'ID':>4} {'Name':>10} {'S_Total':>8} {'S_AI':>6} {'M_Eng':>6} {'Tier':>5} {'Label':>15} {'Filter':>7}", flush=True)
    print("-" * 80, flush=True)
    for rank, (cid, r) in enumerate(ranked[:20], 1):
        name = (candidates[cid].get("name") or "?")[:10]
        filt = "PASS" if r.passed_hard_filter else "FAIL"
        print(
            f"{rank:>4} {cid:>4} {name:>10} {r.s_total:>8.1f} {r.s_ai:>6.1f} {r.m_eng:>6.2f} "
            f"  T{r.experience_detail.tier}  {r.experience_detail.tier_label:>14} {filt:>7}",
            flush=True,
        )

    # Stats
    tiers = {1: 0, 2: 0, 3: 0, 4: 0}
    hf_fail = 0
    for r in results.values():
        if not r.passed_hard_filter:
            hf_fail += 1
        else:
            tiers[r.experience_detail.tier] = tiers.get(r.experience_detail.tier, 0) + 1

    print(f"\nTier distribution (passed hard filter):", flush=True)
    for t in [4, 3, 2, 1]:
        print(f"  Tier {t}: {tiers[t]}", flush=True)
    print(f"  Hard filter failed: {hf_fail}", flush=True)
    print(f"  Total: {len(results)} | Failed scoring: {failed}", flush=True)


if __name__ == "__main__":
    main()
