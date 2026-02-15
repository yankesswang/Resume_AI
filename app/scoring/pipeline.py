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
from typing import Any

from app.models import EnhancedMatchResult
from app.scoring.education import score_education
from app.scoring.engineering import score_engineering_maturity
from app.scoring.experience import classify_experience_tier
from app.scoring.hard_filter import apply_hard_filters
from app.scoring.skills import verify_skills

logger = logging.getLogger(__name__)


def run_full_scoring(
    candidate_detail: dict[str, Any],
    job_data: dict[str, Any],
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

    # --- Step 1: Hard filter ---
    hard_filter_config = job_data.get("hard_filters", {})
    if hard_filter_config:
        passed, failures = apply_hard_filters(
            skill_tags, work_experiences, raw_markdown, hard_filter_config,
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
            experience_detail=ExperienceTierDetail(tier=1, tier_label="Wrapper"),
            analysis_text="候選人未通過硬性門檻篩選。" + " ".join(failures),
        )

    # --- Step 2: Education scoring ---
    edu_detail = score_education(edu_extracts, raw_markdown)

    # --- Step 3: Experience tier classification ---
    exp_detail = classify_experience_tier(work_experiences, skill_tags, raw_markdown)

    # --- Step 4: Engineering maturity ---
    eng_detail = score_engineering_maturity(work_experiences, skill_tags, raw_markdown)

    # --- Step 5: Skill verification ---
    skill_detail = verify_skills(skill_tags, work_experiences)

    # --- Step 6: Semantic similarity (optional, embedding-based) ---
    semantic_sim = 0.0
    try:
        from app.scoring.embeddings import build_candidate_embedding_text, compute_semantic_similarity
        candidate_text = build_candidate_embedding_text(candidate_detail)
        job_text = json.dumps(job_data, ensure_ascii=False)
        if candidate_text.strip():
            semantic_sim = compute_semantic_similarity(candidate_text, job_text)
    except Exception:
        logger.warning("Semantic similarity computation failed, using 0")

    # --- Step 7: Calculate S_AI and M_Eng (legacy, kept for display) ---
    s_ai = exp_detail.score  # AI pyramid score (0-100)
    m_eng = eng_detail.m_eng  # Engineering coefficient (0-0.5)
    s_total = round(s_ai * (1 + m_eng), 1)

    # --- Step 8: Final score composition (weighted sum = 100) ---
    # Each sub-score is 0-100, multiplied by its weight percentage.
    # | AI Experience  35% | Engineering  20% | Semantic  20% | Education  15% | Skills  10% |
    W_EXP = 0.35   # AI depth (experience tier)
    W_ENG = 0.20   # Engineering maturity
    W_SEM = 0.20   # Semantic similarity
    W_EDU = 0.15   # Education background
    W_SKL = 0.10   # Skill verification

    # Normalize engineering m_eng (0-0.5) to 0-100 scale
    eng_score_normalized = min(eng_detail.m_eng / 0.5, 1.0) * 100.0
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

    # Legacy scores for backward compatibility
    education_score = edu_detail.score
    experience_score = exp_detail.score
    skills_score = skill_detail.score

    # --- Step 9: Generate tags ---
    tags = _generate_tags(exp_detail, eng_detail, skill_detail)

    # --- Step 10: Generate analysis, strengths, gaps ---
    strengths, gaps, interview_suggestions = _generate_analysis(
        edu_detail, exp_detail, eng_detail, skill_detail, semantic_sim,
    )
    analysis_text = _build_analysis_text(
        candidate_detail, edu_detail, exp_detail, eng_detail, skill_detail,
        overall, s_ai, m_eng, semantic_sim,
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
        passed_hard_filter=True,
        hard_filter_failures=[],
        semantic_similarity=round(semantic_sim, 2),
        tags=tags,
        analysis_text=analysis_text,
        strengths=strengths,
        gaps=gaps,
        interview_suggestions=interview_suggestions,
    )


def _generate_tags(exp_detail, eng_detail, skill_detail) -> list[str]:
    """Generate hashtag-style tags for the scorecard."""
    tags = []
    tier_tags = {
        1: "#API-Wrapper",
        2: "#RAG-Expert",
        3: "#Model-Tuner",
        4: "#Inference-Ops",
    }
    tags.append(tier_tags.get(exp_detail.tier, "#Unknown"))

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


def _generate_analysis(edu_detail, exp_detail, eng_detail, skill_detail, semantic_sim):
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
        strengths.append("主修資工/電機/AI相關科系，專業對口")
    elif best_edu and best_edu.major_relevance != "Tier1" and edu_detail.score > 0:
        gaps.append("非核心資訊科系背景")

    # Experience strengths/gaps
    if exp_detail.tier >= 3:
        strengths.append(f"AI技術深度達 Tier {exp_detail.tier} ({exp_detail.tier_label})，具備模型層級能力")
    elif exp_detail.tier == 2:
        strengths.append("具備RAG/Agent系統架構經驗")
    else:
        gaps.append("AI經驗主要停留在API調用層級 (Wrapper)")
        interview_suggestions.append("建議面試時深入了解候選人對模型架構的理解程度")

    if exp_detail.metric_score > 0.5:
        strengths.append("工作描述中有具體量化指標，經驗可信度高")
    elif exp_detail.metric_score == 0:
        gaps.append("工作描述缺乏量化指標")
        interview_suggestions.append("建議面試時要求候選人提供具體的專案成效數據")

    if exp_detail.complexity_score > 0.5:
        strengths.append("有處理大規模/生產環境系統的經驗")

    # Engineering strengths/gaps
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


def _build_analysis_text(candidate, edu, exp, eng, skill, overall, s_ai, m_eng, semantic_sim=0.0) -> str:
    """Build a structured analysis text in Traditional Chinese."""
    name = candidate.get("name", "候選人")
    lines = []

    lines.append(f"### {name} 綜合評估")
    lines.append("")
    lines.append(f"**總分：{overall}/100**")
    lines.append(f"- AI經驗深度 (35%): {round(s_ai * 0.35, 1)}")
    lines.append(f"- 工程落地 (20%): {round(min(m_eng / 0.5, 1.0) * 100 * 0.20, 1)}")
    lines.append(f"- 教育背景 (15%): {round(edu.score * 0.15, 1)}")
    lines.append(f"- 技能驗證 (10%): {round(skill.score * 0.10, 1)}")
    lines.append(f"- 語意匹配 (20%): {round(semantic_sim * 100 * 0.20, 1)}")
    lines.append("")

    # AI Pyramid
    lines.append(f"**AI 經驗層級：Tier {exp.tier} ({exp.tier_label})**")
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

    # Engineering
    lines.append(f"**工程成熟度 (M_Eng = {eng.m_eng})：**")
    level_labels = {0: "無", 1: "基礎", 2: "進階", 3: "高級"}
    lines.append(f"- 後端：Level {eng.backend_level} ({level_labels[eng.backend_level]})")
    lines.append(f"- 資料庫：Level {eng.database_level} ({level_labels[eng.database_level]})")
    lines.append(f"- 前端：Level {eng.frontend_level} ({level_labels[eng.frontend_level]})")
    lines.append("")

    # Skill ecosystem
    lines.append(f"**技術棧生態：**{skill.skill_ecosystem}")
    if skill.suspicious_flags:
        lines.append(f"- ⚠️ 可疑聲稱：{len(skill.suspicious_flags)} 項")

    return "\n".join(lines)
