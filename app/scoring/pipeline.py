"""Scoring pipeline orchestrator.

Combines all scoring modules into a single flow:
1. Hard filter (boolean) → reject if fail
2. Education scoring
3. Experience tier classification
4. Engineering maturity
5. Skill verification
6. Semantic similarity (embedding)
7. Calculate S_AI, M_Eng, S_Total
8. LLM deep reasoning for analysis
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from app.models import EnhancedMatchResult
from app.scoring.education import score_education
from app.scoring.engineering import score_engineering_maturity
from app.scoring.experience import classify_experience_tier
from app.scoring.domain_profile import DomainProfile, parse_profile
from app.scoring.hard_filter import apply_hard_filters
from app.scoring.skills import verify_skills

logger = logging.getLogger(__name__)

# Final score weights (must sum to 1.0).
# Single source of truth: both the computation and the displayed breakdown read
# these, so the analysis text can no longer drift from the actual maths.
# Fallback defaults; the live values come from app.scoring.config so they can be
# tuned from the frontend without a redeploy.
WEIGHTS = {
    "experience": 0.35,   # AI depth (experience tier)
    "engineering": 0.20,  # Engineering maturity
    "semantic": 0.20,     # Semantic similarity to the job
    "education": 0.15,    # Education background
    "skills": 0.10,       # Skill verification
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "scoring weights must sum to 1.0"


def _eng_cap_display() -> float:
    """Engineering M_Eng cap, used to normalise the displayed contribution."""
    try:
        from app.scoring.config import load
        return load()["engineering"]["cap"]
    except Exception:
        return 0.7


def _config_version() -> str:
    """Active scoring-config hash, recorded on every result."""
    try:
        from app.scoring.config import config_version
        return config_version()
    except Exception:
        return ""


def _tier_prompt_md5() -> str:
    """Tier-classifier identity, recorded on every result.

    Includes the model that produced the tier, not just the prompt — see
    ``app.llm.tier_classifier_key``.
    """
    try:
        from app.llm import tier_classifier_key
        return tier_classifier_key()
    except Exception:
        return ""


def _weights() -> dict[str, float]:
    """Live weights from the tunable config."""
    try:
        from app.scoring.config import weights
        return weights()
    except Exception:
        logger.warning("Falling back to built-in WEIGHTS")
        return WEIGHTS


# Provenance reason codes written into match_results.degraded_reasons.
DEGRADED_LLM_TIER = "llm_tier_fallback"
DEGRADED_EMBEDDING = "embedding_unavailable"
DEGRADED_SEMANTIC_ERROR = "semantic_error"


def _apply_domain_relevance_cap(overall: float, profile, exp_detail) -> float:
    """Keep a confirmed Tier-0 profile match below the viable-fit range.

    Generic communication, reporting and data terms can score well in every
    industry. Once the LLM has positively determined that none of the resume's
    work or projects belongs to this job domain, those transferable signals
    must not lift an unrelated candidate above a domain-relevant one. Keyword
    fallback is too weak to support this cap, so degraded classifications are
    deliberately excluded.
    """
    if (
        profile is not None
        and exp_detail.tier == 0
        and str(exp_detail.tier_source).startswith("llm")
    ):
        return min(overall, 45.0)
    return overall


def _classify_tier(
    work_experiences: list[dict],
    skill_tags: list[str],
    raw_markdown: str,
    candidate_id: int | None,
    db_conn: sqlite3.Connection | None,
):
    """Try LLM-based tier classification; fall back to keyword-only on any error.

    ``tier_source`` carries the verdict outward: the keyword-only path leaves it
    at its "keyword" default, while every LLM path overwrites it.  That is how
    the caller detects a fallback that happened *inside*
    ``classify_experience_tier_llm`` (which swallows its own LLM errors) as well
    as one raised out to here.
    """
    try:
        from app.scoring.experience import classify_experience_tier_llm
        return classify_experience_tier_llm(
            work_experiences, skill_tags, raw_markdown, candidate_id, db_conn
        )
    except Exception as e:
        logger.warning("LLM tier classify failed, using keyword fallback: %s", e)
        return classify_experience_tier(work_experiences, skill_tags, raw_markdown)


def resolve_profile(job_data: dict[str, Any]) -> DomainProfile | None:
    """The domain profile this job should be scored with, or None for the legacy path.

    Returning None — not the builtin profile — is what keeps existing scores
    stable: a job with no profile attached goes through the original hard-coded
    AI scorers untouched, exactly as before.  Only a job that has had a profile
    generated or assigned takes the generic path.
    """
    return parse_profile(job_data.get("domain_profile"))


def _classify_tier_by_profile(
    profile: DomainProfile,
    work_experiences: list[dict],
    skill_tags: list[str],
    raw_markdown: str,
    candidate_id: int | None,
    db_conn: sqlite3.Connection | None,
):
    """LLM depth classification against a profile, with keyword fallback.

    Same contract as :func:`_classify_tier`: never raises, and leaves
    ``tier_source`` at "keyword" when the LLM did not decide, so the caller can
    mark the result degraded.
    """
    from app.database import get_cached_llm_tier, store_llm_tier_cache
    from app.llm import classify_domain_tier
    from app.scoring.config import (
        load as _cfg,
        tier_base_scores,
        tier_bonus_caps,
    )
    from app.scoring.generic import classify_tier_by_profile

    # Keyword pass first: it supplies the bonus sub-scores (stack/complexity/
    # metric) regardless of which path decides the tier, and it is the fallback.
    detail = classify_tier_by_profile(
        profile, work_experiences, skill_tags, raw_markdown
    )
    if candidate_id is None or db_conn is None:
        return detail

    # The cache key must bind the profile: the same candidate scored for two
    # different roles has two different correct tiers.
    prompt_key = f"dp:{profile.fingerprint()}"

    llm_tier: int | None = None
    confidence = 1.0
    try:
        cached = get_cached_llm_tier(db_conn, candidate_id, raw_markdown, prompt_key)
        if cached:
            llm_tier = int(cached["tier"])
    except Exception:
        logger.warning("Failed to read tier cache for candidate %s", candidate_id)

    if llm_tier is None:
        try:
            result = classify_domain_tier(
                profile, work_experiences, skill_tags, raw_markdown
            )
            llm_tier = max(0, min(int(result.get("tier", 0)), 3))
            try:
                confidence = float(result.get("confidence", 1.0))
            except (TypeError, ValueError):
                confidence = 1.0
            store_llm_tier_cache(
                db_conn, candidate_id, raw_markdown,
                {"tier": llm_tier, "reasoning": result.get("reasoning", "")},
                prompt_key,
            )
        except Exception as e:
            logger.warning(
                "Domain tier classification failed for candidate %s: %s",
                candidate_id, e,
            )
            return detail  # keyword-only, tier_source stays "keyword"

    # Generated keywords have not been corpus-calibrated.  Live review showed
    # that two plausible-sounding literals could raise an intern or an LLM data
    # curator to Tier 3 despite the classifier correctly placing them at Tier
    # 1/2.  Therefore an LLM-generated/manual profile uses keywords as an outage
    # fallback only; it must not override a successful semantic classification.
    # The builtin profile is hand-curated against the full corpus and keeps its
    # deliberately calibrated upward floor.
    effective = llm_tier
    tier_source = "llm"
    if profile.source == "builtin":
        from app.scoring.generic import build_corpora, keyword_floor_by_profile

        evidence_text, _ = build_corpora(
            work_experiences, skill_tags, raw_markdown
        )
        floor = keyword_floor_by_profile(profile, evidence_text)
        effective = max(llm_tier, floor)
        if effective != llm_tier:
            tier_source = "llm+keyword-floor"

    bc = _cfg()["bonuses"]
    bonus = min(
        min(detail.tech_stack_score * bc["stack_multiplier"], bc["stack_max"])
        + detail.complexity_score * bc["complexity_max"]
        + detail.metric_score * bc["metric_max"],
        tier_bonus_caps()[effective],
    )
    detail.tier = effective
    detail.tier_label = profile.tier_label(effective)
    detail.confidence = round(confidence, 2)
    detail.tier_source = tier_source
    detail.score = round(
        min(float(tier_base_scores()[effective]) + bonus, 100.0), 1
    )
    return detail


def run_full_scoring(
    candidate_detail: dict[str, Any],
    job_data: dict[str, Any],
    db_conn: sqlite3.Connection | None = None,
) -> EnhancedMatchResult:
    """Run the complete scoring pipeline on a candidate.

    Args:
        candidate_detail: Full candidate dict from database (with work_experiences, education, etc.)
        job_data: Job requirement JSON data

    Returns:
        EnhancedMatchResult with all dimension scores
    """
    work_experiences = candidate_detail.get("work_experiences", [])
    education_list = candidate_detail.get("education", [])
    skill_tags = candidate_detail.get("skill_tags", [])
    if isinstance(skill_tags, str):
        skill_tags = json.loads(skill_tags) if skill_tags else []
    raw_markdown = candidate_detail.get("raw_markdown", "") or ""

    # Convert education dicts to EducationExtract if needed
    from app.models import EducationExtract
    edu_extracts = []
    for ed in education_list:
        if isinstance(ed, dict):
            edu_extracts.append(EducationExtract(
                school=ed.get("school", ""),
                department=ed.get("department", ""),
                degree_level=ed.get("degree_level", ""),
            ))
        else:
            edu_extracts.append(ed)

    # Fallback: if no education table rows, use flat candidate fields
    if not edu_extracts and candidate_detail.get("school"):
        edu_extracts = [EducationExtract(
            school=candidate_detail.get("school", ""),
            department=candidate_detail.get("major", ""),
            degree_level=candidate_detail.get("education_level", ""),
        )]

    # A profile, when present, supplies every domain-specific decision below.
    # Its absence keeps the original hard-coded AI path, so existing jobs score
    # exactly as they did before.
    profile = resolve_profile(job_data)

    # --- Step 1: Hard filter ---
    # Profile filters take precedence: they were written for this specific role.
    hard_filter_config = (
        profile.hard_filters if profile and profile.hard_filters
        else job_data.get("hard_filters", {})
    )
    if hard_filter_config:
        passed, failures = apply_hard_filters(
            skill_tags, work_experiences, raw_markdown, hard_filter_config,
            education=edu_extracts,
        )
    else:
        passed, failures = True, []

    if not passed:
        # Early return with low score for hard filter failures
        from app.models import ExperienceTierDetail
        return EnhancedMatchResult(
            overall_score=10.0,
            passed_hard_filter=False,
            hard_filter_failures=failures,
            experience_detail=ExperienceTierDetail(
                tier=0,
                tier_label=profile.tier_label(0) if profile else "Non-AI",
            ),
            analysis_text="候選人未通過硬性門檻篩選。" + " ".join(failures),
            # A hard-filter rejection needs no LLM or embedding, so it is a
            # complete result rather than a degraded one.
            scoring_mode="full",
            scoring_config_version=_config_version(),
            tier_prompt_md5=_tier_prompt_md5(),
        )

    # --- Step 2: Education scoring ---
    edu_detail = score_education(edu_extracts, raw_markdown, profile=profile)

    # --- Step 3: Experience tier classification (LLM with keyword floor) ---
    degraded_reasons: list[str] = []
    if profile:
        exp_detail = _classify_tier_by_profile(
            profile, work_experiences, skill_tags, raw_markdown,
            candidate_detail.get("id"), db_conn,
        )
    else:
        exp_detail = _classify_tier(
            work_experiences, skill_tags, raw_markdown,
            candidate_detail.get("id"), db_conn,
        )
    if exp_detail.tier_source == "keyword":
        # AI tier carries 35% of the final score; a keyword-only tier is a
        # materially weaker result and must be marked as such.
        degraded_reasons.append(DEGRADED_LLM_TIER)

    # --- Step 4: Capability matrix (engineering maturity for the AI profile) ---
    competency_axes: list[dict[str, Any]] = []
    if profile:
        from app.scoring.generic import score_competencies
        eng_detail, competency_axes = score_competencies(
            profile, work_experiences, skill_tags, raw_markdown
        )
    else:
        eng_detail = score_engineering_maturity(
            work_experiences, skill_tags, raw_markdown
        )

    # --- Step 5: Skill verification ---
    if profile:
        from app.scoring.generic import verify_skills_by_profile
        skill_detail = verify_skills_by_profile(
            profile, skill_tags, work_experiences, raw_markdown
        )
    else:
        skill_detail = verify_skills(skill_tags, work_experiences, raw_markdown)

    # --- Step 6: Semantic similarity (optional, embedding-based) ---
    semantic_sim = 0.0
    semantic_raw = 0.0
    try:
        from app.scoring.embeddings import (
            build_candidate_embedding_text,
            build_job_embedding_text,
            compute_semantic_similarity_traced,
            rescale_similarity,
        )
        candidate_text = build_candidate_embedding_text(candidate_detail)
        # Embed only the skill-bearing job fields, not the whole JSON blob.
        job_text = build_job_embedding_text(job_data) or json.dumps(job_data, ensure_ascii=False)
        if candidate_text.strip():
            semantic_raw, sem_degraded = compute_semantic_similarity_traced(
                candidate_text, job_text
            )
            if sem_degraded:
                degraded_reasons.append(DEGRADED_EMBEDDING)
            # Raw cosines sit in a narrow high band; stretch for discrimination.
            semantic_sim = rescale_similarity(semantic_raw)
    except Exception:
        # Log the traceback: a bare warning here hid a plain TypeError for as
        # long as it took someone to notice every score was missing 20%.
        logger.warning("Semantic similarity computation failed, using 0", exc_info=True)
        degraded_reasons.append(DEGRADED_SEMANTIC_ERROR)

    # --- Step 7: Calculate S_AI and M_Eng (legacy, kept for display) ---
    s_ai = exp_detail.score  # AI pyramid score (0-100)
    m_eng = eng_detail.m_eng  # Engineering coefficient (0-0.5)
    s_total = round(s_ai * (1 + m_eng), 1)

    # --- Step 8: Final score composition (weighted sum = 100) ---
    # Each sub-score is 0-100, multiplied by its weight percentage.
    # | AI Experience  35% | Engineering  20% | Semantic  20% | Education  15% | Skills  10% |
    # A profile may override the dimension weights for its role (e.g. a sales
    # job that genuinely does not care about the degree).
    _w = dict(profile.weights) if (profile and profile.weights) else _weights()

    # `education.matters = False` means the role genuinely does not screen on a
    # degree. Redistribute that weight across the remaining dimensions rather
    # than zeroing the education SCORE: a zeroed score still consumes its
    # weight, dragging every candidate down by the same amount and making the
    # whole dimension a constant instead of removing it.
    if profile and not profile.education.matters and _w.get("education", 0) > 0:
        freed = _w["education"]
        _w["education"] = 0.0
        others = [k for k in _w if k != "education" and _w[k] > 0]
        if others:
            remaining = sum(_w[k] for k in others)
            for k in others:
                _w[k] = _w[k] + freed * (_w[k] / remaining)
        else:
            # Pathological profile: education was the only weighted dimension.
            # Give it back rather than producing a zero for everybody.
            _w["education"] = freed

    W_EXP = _w["experience"]
    W_ENG = _w["engineering"]
    W_SEM = _w["semantic"]
    W_EDU = _w["education"]
    W_SKL = _w["skills"]

    # Normalize engineering m_eng (0-0.7) to 0-100 scale (cap raised in v2)
    from app.scoring.config import load as _load_cfg
    _eng_cap = _load_cfg()["engineering"]["cap"]
    eng_score_normalized = min(eng_detail.m_eng / _eng_cap, 1.0) * 100.0
    # Normalize semantic similarity (0-1) to 0-100 scale
    sem_score_normalized = semantic_sim * 100.0

    overall = round(
        s_ai * W_EXP
        + eng_score_normalized * W_ENG
        + sem_score_normalized * W_SEM
        + edu_detail.score * W_EDU
        + skill_detail.score * W_SKL,
        1,
    )
    overall = min(overall, 100.0)
    overall = _apply_domain_relevance_cap(overall, profile, exp_detail)

    # Legacy scores for backward compatibility
    education_score = edu_detail.score
    experience_score = exp_detail.score
    skills_score = skill_detail.score

    # --- Step 9: Generate tags ---
    tags = _generate_tags(exp_detail, eng_detail, skill_detail, profile)

    # --- Step 10: Generate analysis, strengths, gaps ---
    strengths, gaps, interview_suggestions = _generate_analysis(
        edu_detail, exp_detail, eng_detail, skill_detail, semantic_sim, profile,
    )
    analysis_text = _build_analysis_text(
        candidate_detail, edu_detail, exp_detail, eng_detail, skill_detail,
        overall, s_ai, m_eng, semantic_sim, profile, competency_axes, _w,
    )

    return EnhancedMatchResult(
        overall_score=overall,
        s_ai=s_ai,
        m_eng=m_eng,
        s_total=s_total,
        education_score=education_score,
        experience_score=experience_score,
        skills_score=skills_score,
        education_detail=edu_detail,
        experience_detail=exp_detail,
        engineering_detail=eng_detail,
        skill_detail=skill_detail,
        competency_axes=competency_axes,
        profile_id=profile.profile_id if profile else "",
        profile_name=profile.name if profile else "",
        passed_hard_filter=True,
        hard_filter_failures=[],
        semantic_similarity=round(semantic_sim, 2),
        tags=tags,
        analysis_text=analysis_text,
        strengths=strengths,
        gaps=gaps,
        interview_suggestions=interview_suggestions,
        scoring_mode="degraded" if degraded_reasons else "full",
        degraded_reasons=degraded_reasons,
        scoring_config_version=_config_version(),
        tier_prompt_md5=_tier_prompt_md5(),
    )


def _generate_tags(exp_detail, eng_detail, skill_detail, profile=None) -> list[str]:
    """Generate hashtag-style tags for the scorecard."""
    tags = []
    if profile:
        # A profile's own tier labels are the only meaningful names for its
        # domain; "#RAG-Expert" on an accountant is noise.
        label = profile.tier_label(exp_detail.tier).replace(" ", "-")
        tags.append(f"#{label}")
    else:
        tier_tags = {
            0: "#Non-AI",
            1: "#API-Wrapper",
            2: "#RAG-Expert",
            3: "#AI-Expert",
        }
        tags.append(tier_tags.get(exp_detail.tier, "#Unknown"))
    if exp_detail.confidence and exp_detail.confidence < 0.5:
        tags.append("#低信心分類")

    if profile:
        # The evidence tags below are AI-vocabulary specific ("#RAG",
        # "#GPU-Optimization"); for another domain they would never fire, so a
        # profile gets domain-neutral tags instead.
        if skill_detail.skill_ecosystem:
            tags.append(f"#{skill_detail.skill_ecosystem.replace(' ', '-')}")
        if exp_detail.confidence and exp_detail.confidence < 0.5:
            tags.append("#低信心分類")
        if exp_detail.metric_score > 0.5:
            tags.append("#有量化成效")
        return tags

    # Add evidence-based tags
    evidence_lower = " ".join(exp_detail.evidence).lower()
    if "fine-tuning" in evidence_lower or "fine tuning" in evidence_lower:
        tags.append("#Fine-tuning")
    if "rag" in evidence_lower:
        tags.append("#RAG")
    if "cuda" in evidence_lower or "vllm" in evidence_lower:
        tags.append("#GPU-Optimization")
    if "langchain" in evidence_lower or "llamaindex" in evidence_lower:
        tags.append("#LLM-Framework")

    # Engineering tags
    if eng_detail.m_eng >= 0.3:
        tags.append("#Full-Stack")
    if eng_detail.backend_level >= 3:
        tags.append("#DevOps")
    if eng_detail.database_level >= 3:
        tags.append("#Vector-DB")

    # Ecosystem tag
    if skill_detail.skill_ecosystem:
        tags.append(f"#{skill_detail.skill_ecosystem.replace(' ', '-')}")

    return tags


def _generate_analysis(edu_detail, exp_detail, eng_detail, skill_detail, semantic_sim, profile=None):
    """Generate strengths, gaps, and interview suggestions."""
    strengths = []
    gaps = []
    interview_suggestions = []

    # Education strengths/gaps (hybrid model: bachelor + master)
    best_edu = edu_detail.master or edu_detail.bachelor
    if best_edu and best_edu.school_tier == "A":
        strengths.append("頂尖學校背景，學術基礎扎實")
    if edu_detail.master:
        strengths.append("碩士/博士學位，具備專業訓練")
    if best_edu and best_edu.major_relevance == "Tier1":
        strengths.append(
            "主修科系與職缺高度對口" if profile
            else "主修資工/電機/AI相關科系，專業對口"
        )
    elif best_edu and best_edu.major_relevance != "Tier1" and edu_detail.score > 0:
        gaps.append("主修科系與本職缺核心科系不符" if profile else "非核心資訊科系背景")

    # Experience strengths/gaps
    if profile:
        domain = profile.domain or profile.name or "本職缺領域"
        label = profile.tier_label(exp_detail.tier)
        if exp_detail.tier >= 3:
            strengths.append(f"{domain}深度達 Tier {exp_detail.tier}（{label}），具備專家級能力")
        elif exp_detail.tier == 2:
            strengths.append(f"{domain}達 Tier 2（{label}），能獨立負責")
        elif exp_detail.tier == 1:
            gaps.append(f"{domain}經驗停留在 Tier 1（{label}）執行層")
            interview_suggestions.append(f"建議面試時深入確認候選人在{domain}的實作深度")
        else:
            gaps.append(f"履歷未顯示{domain}相關經驗")
            interview_suggestions.append(f"建議確認候選人轉入{domain}的基礎與意願")
    elif exp_detail.tier >= 3:
        strengths.append(f"AI技術深度達 Tier {exp_detail.tier} ({exp_detail.tier_label})，具備模型層級能力")
    elif exp_detail.tier == 2:
        strengths.append("具備RAG/Agent系統架構經驗")
    elif exp_detail.tier == 1:
        gaps.append("AI經驗主要停留在API調用層級 (Wrapper)")
        interview_suggestions.append("建議面試時深入了解候選人對模型架構的理解程度")
    else:
        gaps.append("履歷未顯示任何 AI/ML 實作經驗")
        interview_suggestions.append("建議確認候選人是否具備轉入 AI 領域的基礎與意願")

    if exp_detail.confidence and exp_detail.confidence < 0.5:
        gaps.append("履歷資訊不足，AI 層級判定信心偏低，建議人工複核")

    if exp_detail.metric_score > 0.5:
        strengths.append("工作描述中有具體量化指標，經驗可信度高")
    elif exp_detail.metric_score == 0:
        gaps.append("工作描述缺乏量化指標")
        interview_suggestions.append("建議面試時要求候選人提供具體的專案成效數據")

    if exp_detail.complexity_score > 0.5:
        strengths.append("有處理大規模/生產環境系統的經驗")

    # Capability matrix strengths/gaps
    if profile:
        if eng_detail.m_eng >= 0.3:
            strengths.append(f"能力面向覆蓋度高（綜合係數 {eng_detail.m_eng}）")
        elif eng_detail.m_eng > 0:
            strengths.append("具備部分職務所需能力面向")
        else:
            gaps.append("履歷未涵蓋本職缺任何核心能力面向")
    else:
        if eng_detail.m_eng >= 0.3:
            strengths.append(f"工程落地能力強 (M_Eng={eng_detail.m_eng})，具備全端開發能力")
        elif eng_detail.m_eng > 0:
            strengths.append("具備基本工程開發能力")
        else:
            gaps.append("工程落地能力不足，缺乏後端/部署經驗")
            interview_suggestions.append("建議面試時了解候選人的軟體工程實踐經驗（Docker、API開發等）")

        if eng_detail.backend_level == 0:
            interview_suggestions.append("履歷未提及後端開發經驗，面試時建議詢問 Docker/API 相關知識")
        if eng_detail.database_level == 0:
            interview_suggestions.append("履歷未提及資料庫經驗，面試時建議詢問 SQL/NoSQL 基礎")

    # Skill verification
    if skill_detail.suspicious_flags:
        gaps.append("部分技能聲稱缺乏工作經驗佐證")
        interview_suggestions.append("面試時建議針對以下技能進行實作驗證：" +
                                      ", ".join(f.split("'")[1] for f in skill_detail.suspicious_flags if "'" in f))

    return strengths, gaps, interview_suggestions


def _build_analysis_text(
    candidate, edu, exp, eng, skill, overall, s_ai, m_eng, semantic_sim=0.0,
    profile=None, competency_axes=None, weights=None,
) -> str:
    """Build a structured analysis text in Traditional Chinese."""
    name = candidate.get("name", "候選人")
    lines = []

    lines.append(f"### {name} 綜合評估")
    if profile:
        lines.append(f"_評分標準：{profile.name or profile.domain}_")
    lines.append("")
    # Must be the same weights the score was computed with, or the breakdown
    # silently contradicts the total on any profile that overrides them.
    _w = weights or _weights()
    pct = lambda k: int(_w[k] * 100)
    exp_label = f"{profile.domain}深度" if profile and profile.domain else "AI經驗深度"
    eng_label = "能力面向" if profile else "工程落地"
    lines.append(f"**總分：{overall}/100**")
    lines.append(f"- {exp_label} ({pct('experience')}%): {round(s_ai * _w['experience'], 1)}")
    lines.append(
        f"- {eng_label} ({pct('engineering')}%): "
        f"{round(min(m_eng / _eng_cap_display(), 1.0) * 100 * _w['engineering'], 1)}"
    )
    if _w.get("education", 0) > 0:
        lines.append(f"- 教育背景 ({pct('education')}%): {round(edu.score * _w['education'], 1)}")
    else:
        lines.append("- 教育背景：本職缺不採計學歷")
    lines.append(f"- 技能驗證 ({pct('skills')}%): {round(skill.score * _w['skills'], 1)}")
    lines.append(f"- 語意匹配 ({pct('semantic')}%): {round(semantic_sim * 100 * _w['semantic'], 1)}")
    lines.append("")

    # Depth tier
    tier_heading = f"{profile.domain}層級" if profile and profile.domain else "AI 經驗層級"
    lines.append(f"**{tier_heading}：Tier {exp.tier} ({exp.tier_label})**")
    if exp.confidence < 0.5:
        lines.append(f"- ⚠️ 判定信心：{exp.confidence}（履歷資訊不足，建議人工複核）")
    if exp.tier_source == "llm+keyword-floor":
        lines.append("- 層級由履歷關鍵技術證據提升（LLM 判定偏低）")
    if exp.evidence:
        lines.append(f"- 關鍵技術證據：{', '.join(exp.evidence[:5])}")
    lines.append("")

    # Education
    if edu.score > 0:
        best = edu.master or edu.bachelor
        if best:
            level_str = "碩士" if edu.master else "學士"
            lines.append(f"**教育背景：**{best.school_tier}級學校 ({best.school}) / {level_str} / 科系相關性：{best.major_relevance}")
        else:
            lines.append("**教育背景：**無資料")
    lines.append("")

    # Capability matrix
    level_labels = {0: "無", 1: "基礎", 2: "進階", 3: "高級"}
    if profile and competency_axes:
        lines.append(f"**能力面向 (綜合係數 = {eng.m_eng})：**")
        for axis in competency_axes:
            lvl = axis["level"]
            line = f"- {axis['label']}：Level {lvl} ({level_labels[lvl]})"
            if axis.get("matched"):
                line += f" — {', '.join(axis['matched'][:3])}"
            lines.append(line)
    else:
        lines.append(f"**工程成熟度 (M_Eng = {eng.m_eng})：**")
        lines.append(f"- 後端：Level {eng.backend_level} ({level_labels[eng.backend_level]})")
        lines.append(f"- 資料庫：Level {eng.database_level} ({level_labels[eng.database_level]})")
        lines.append(f"- 前端：Level {eng.frontend_level} ({level_labels[eng.frontend_level]})")
    lines.append("")

    # Skill ecosystem
    lines.append(f"**{'技能族群' if profile else '技術棧生態'}：**{skill.skill_ecosystem}")
    if skill.suspicious_flags:
        lines.append(f"- ⚠️ 可疑聲稱：{len(skill.suspicious_flags)} 項")

    return "\n".join(lines)
