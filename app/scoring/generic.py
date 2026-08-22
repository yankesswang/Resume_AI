"""Profile-driven scoring — the domain-agnostic half of the pipeline.

Each function here is the generic counterpart of a hard-coded scorer:

    experience.classify_experience_tier   →  classify_tier_by_profile
    engineering.score_engineering_maturity →  score_competencies
    skills.verify_skills                   →  verify_skills_by_profile
    education.TIER1_MAJOR / TIER2_MAJOR    →  major_relevance_by_profile

They share the calibrated maths (tier bands, bonus caps, tag-weight
discounting, ecosystem penalties) with the originals and read the same
``app.scoring.config``; only the *domain evidence* — which keywords mean what —
comes from the profile.  That split is deliberate: the numbers were calibrated
against a real pool and should not be re-derived per role, while the evidence
is exactly what differs between an AI engineer and an accountant.

Keyword matching is literal-substring, case-insensitive, matching the existing
``_find_keywords``.  Profiles come from an LLM, so treating their entries as
regex would let a stray ``(`` take scoring down for that whole role.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.models import (
    EngineeringMaturityDetail,
    ExperienceTierDetail,
    SkillVerification,
)
from app.scoring.domain_profile import DomainProfile

logger = logging.getLogger(__name__)


def build_corpora(
    work_experiences: list[dict[str, Any]],
    skill_tags: list[str],
    raw_markdown: str = "",
) -> tuple[str, str]:
    """Split a resume into (evidence_text, tag_text).

    Same split the AI scorer uses: keywords that appear only in the self-declared
    skill-tag header are discounted, because tag stuffing is the cheapest way to
    game any keyword-based screen — in any field, not just engineering.
    """
    parts = []
    for we in work_experiences:
        parts.append(we.get("job_description", "") or "")
        parts.append(we.get("job_title", "") or "")
        parts.append(we.get("job_skills", "") or "")
    if raw_markdown:
        parts.append(raw_markdown)
    return " ".join(parts), " ".join(skill_tags)


def _find(text_lower: str, keywords: dict[str, float]) -> list[tuple[str, float]]:
    return [(kw, w) for kw, w in keywords.items() if kw.lower() in text_lower]


def _hits(text_lower: str, keywords: list[str]) -> list[str]:
    return [kw for kw in keywords if kw.lower() in text_lower]


# --- Tier classification ----------------------------------------------------

# Domain-neutral complexity signals: scale, structure and stakes read the same
# way whether the work is a training run, a product launch or an audit.
_SCALE_PATTERN = re.compile(
    r"(百萬|million|billion|十萬|hundred thousand|大規模|large.?scale|"
    r"\d+[MBT]\b|\d+萬|\d+億|全國|跨國|multi.?national|enterprise)",
    re.IGNORECASE,
)
_STRUCTURE_PATTERN = re.compile(
    r"(跨部門|cross.?functional|分散式|distributed|流程再造|導入|"
    r"制度|SOP|專案管理|project management|建置|架構|架設|"
    r"production|生產環境|上線|部署|deploy|落地)",
    re.IGNORECASE,
)
_LEADERSHIP_PATTERN = re.compile(
    r"(帶領|領導|主導|統籌|管理\s*\d+\s*(人|名)|team lead|lead\b|"
    r"supervis|mentor|負責人|專案經理|PM\b|主管)",
    re.IGNORECASE,
)

# Quantified-outcome signals. The original is AI-flavoured (Recall@, VRAM);
# this one adds the business metrics every other field reports in.
_METRIC_PATTERN = re.compile(
    r"(reduce[d]?\s+.*?\d+%|improve[d]?\s+.*?\d+%|increase[d]?\s+.*?\d+%|"
    r"降低.*?\d+%|提升.*?\d+%|優化.*?\d+%|加速.*?\d+%|縮短.*?\d+%|"
    r"成長.*?\d+%|達成率.*?\d+%|業績.*?\d+|營收.*?\d+|毛利.*?\d+|"
    r"節省.*?\d+|良率.*?\d+|周轉.*?\d+|客訴.*?\d+|滿意度.*?\d+|"
    r"latency.*?\d+|throughput.*?\d+|QPS.*?\d+|TPS.*?\d+|"
    r"accuracy.*?\d+%|準確率.*?\d+%|\d+x\s+faster|\d+倍)",
    re.IGNORECASE,
)

# Weight a tier's keyword hits must reach before that tier is claimed.
# Mirrors TIER3_MIN_WEIGHT / TIER2_MIN_WEIGHT in experience.py.
_TIER_MIN_WEIGHT = {3: 3.0, 2: 2.0, 1: 0.0}


def classify_tier_by_profile(
    profile: DomainProfile,
    work_experiences: list[dict[str, Any]],
    skill_tags: list[str],
    raw_markdown: str = "",
) -> ExperienceTierDetail:
    """Keyword-based depth classification against a profile's tier keywords.

    This is the fallback path (and the keyword floor) for any domain — it runs
    when the LLM is unavailable, so it must never raise.
    """
    from app.scoring.config import load, tier_base_scores, tier_bonus_caps

    evidence_text, tag_text = build_corpora(
        work_experiences, skill_tags, raw_markdown
    )
    combined = f"{evidence_text} {tag_text}"
    bases = tier_base_scores()
    caps = tier_bonus_caps()

    if not combined.strip():
        return ExperienceTierDetail(
            tier=0, tier_label=profile.tier_label(0), score=float(bases[0]),
        )

    combined_lower = combined.lower()
    evidence_lower = evidence_text.lower()
    tag_lower = tag_text.lower()

    # --- Which tier does the evidence reach? ---
    weight_by_tier = {1: 0.0, 2: 0.0, 3: 0.0}
    for tier in (3, 2, 1):
        kw_map = profile.tier_keywords.get(str(tier)) or {}
        weight_by_tier[tier] = sum(w for _, w in _find(combined_lower, kw_map))

    if weight_by_tier[3] >= _TIER_MIN_WEIGHT[3]:
        best_tier = 3
    elif weight_by_tier[3] > 0 or weight_by_tier[2] >= _TIER_MIN_WEIGHT[2]:
        best_tier = 2
    elif weight_by_tier[2] > 0 or weight_by_tier[1] > 0:
        # One isolated intermediate term is evidence of domain exposure, not
        # enough proof of independent delivery.  The old branch promoted any
        # Tier-2 literal (for example generic "Docker") straight to Tier 2.
        best_tier = 1
    else:
        best_tier = 0

    # --- Stack bonus, discounting tag-only hits ---
    tag_factor = float(load()["tag_weight_factor"])
    evidence_list: list[str] = []
    stack_score = 0.0
    for tier in (3, 2, 1):
        kw_map = profile.tier_keywords.get(str(tier)) or {}
        ev_hits = {kw for kw, _ in _find(evidence_lower, kw_map)}
        tag_hits = {kw for kw, _ in _find(tag_lower, kw_map)}
        for kw in ev_hits | tag_hits:
            weight = kw_map[kw]
            if kw in ev_hits:
                stack_score += weight
                evidence_list.append(f"[Tier {tier}] {kw}")
            else:
                stack_score += weight * tag_factor
                evidence_list.append(f"[Tier {tier}] {kw} (tag)")

    complexity = 0.0
    if _SCALE_PATTERN.search(combined):
        complexity += 0.33
    if _STRUCTURE_PATTERN.search(combined):
        complexity += 0.33
    if _LEADERSHIP_PATTERN.search(combined):
        complexity += 0.34

    metric_score = min(len(_METRIC_PATTERN.findall(combined)) * 0.25, 1.0)

    bc = load()["bonuses"]
    bonus = min(
        min(stack_score * bc["stack_multiplier"], bc["stack_max"])
        + complexity * bc["complexity_max"]
        + metric_score * bc["metric_max"],
        caps[best_tier],
    )
    final = min(float(bases[best_tier]) + bonus, 100.0)

    return ExperienceTierDetail(
        tier=best_tier,
        tier_label=profile.tier_label(best_tier),
        confidence=1.0,
        tier_source="keyword",
        evidence=evidence_list[:10],
        tech_stack_score=round(stack_score, 2),
        complexity_score=round(complexity, 2),
        metric_score=round(metric_score, 2),
        score=round(final, 1),
    )


def keyword_floor_by_profile(
    profile: DomainProfile, evidence_text: str
) -> int:
    """Lowest tier justified by unambiguous keyword evidence.

    The AI profile hand-picks "strong signals" that are hard to mention without
    hands-on work.  A generated profile has no such curation, so the generic
    floor uses the tier's own high-weight keywords (>= 1.5) as the proxy — the
    profile prompt asks for weight to track how hard a signal is to fake.
    Skill tags are excluded entirely, exactly as in the original floor.
    """
    from app.scoring.config import load

    kf = load()["keyword_floor"]
    if not kf.get("enabled", True) or not evidence_text.strip():
        return 0
    min_signals = int(kf.get("min_signals", 2))

    evidence_lower = evidence_text.lower()
    for tier in (3, 2):
        kw_map = profile.tier_keywords.get(str(tier)) or {}
        strong = {kw: w for kw, w in kw_map.items() if w >= 1.5}
        if len(_find(evidence_lower, strong)) >= min_signals:
            return tier
    return 0


# --- Competency matrix ------------------------------------------------------

# Level -> share of that axis's weight. Mirrors the shape of BACKEND_SCORES:
# reaching level 3 on an axis earns its full weight, level 1 earns a token
# amount.  Expressed as fractions so any profile's weights work unchanged.
_LEVEL_FRACTION = {0: 0.0, 1: 0.29, 2: 0.57, 3: 1.0}


def score_competencies(
    profile: DomainProfile,
    work_experiences: list[dict[str, Any]],
    skill_tags: list[str],
    raw_markdown: str = "",
) -> tuple[EngineeringMaturityDetail, list[dict[str, Any]]]:
    """Score the profile's capability axes.

    Returns ``(detail, axes)`` where ``detail`` reuses
    ``EngineeringMaturityDetail`` so every existing consumer (API responses,
    the frontend matrix, stored match_results) keeps working, and ``axes``
    carries the full per-axis breakdown for profiles with axes that are not
    backend/database/frontend.

    The first three axes are mirrored onto the legacy backend/database/frontend
    fields.  That mapping is positional and only meaningful for the builtin
    profile; ``axes`` is the truthful representation and is what the UI should
    render when a profile is in use.
    """
    from app.scoring.config import load

    evidence_text, tag_text = build_corpora(
        work_experiences, skill_tags, raw_markdown
    )
    combined_lower = f"{evidence_text} {tag_text}".lower()
    cap = float(load()["engineering"]["cap"])

    axes: list[dict[str, Any]] = []
    total = 0.0
    for comp in profile.normalised_competencies():
        level = 0
        matched: list[str] = []
        for lvl in (3, 2, 1):
            hits = _hits(combined_lower, comp.levels.get(str(lvl)) or [])
            if hits:
                level = lvl
                matched = hits[:5]
                break
        # comp.weight is normalised to sum to 1.0 across axes, so scaling by the
        # engineering cap keeps the total in the same 0..cap range the
        # calibrated m_eng normalisation expects.
        score = _LEVEL_FRACTION[level] * comp.weight * cap
        total += score
        axes.append({
            "key": comp.key,
            "label": comp.label or comp.key,
            "level": level,
            "score": round(score, 3),
            "weight": round(comp.weight, 3),
            "matched": matched,
        })

    m_eng = min(total, cap)

    def _axis(i: int) -> tuple[int, float]:
        return (axes[i]["level"], axes[i]["score"]) if i < len(axes) else (0, 0.0)

    b_lvl, b_score = _axis(0)
    d_lvl, d_score = _axis(1)
    f_lvl, f_score = _axis(2)

    detail = EngineeringMaturityDetail(
        backend_level=b_lvl, backend_score=round(b_score, 2),
        database_level=d_lvl, database_score=round(d_score, 2),
        frontend_level=f_lvl, frontend_score=round(f_score, 2),
        m_eng=round(m_eng, 2),
    )
    return detail, axes


# --- Skill verification -----------------------------------------------------

def verify_skills_by_profile(
    profile: DomainProfile,
    skill_tags: list[str],
    work_experiences: list[dict[str, Any]],
    raw_markdown: str = "",
) -> SkillVerification:
    """Ecosystem classification + unsupported-claim penalties, per profile.

    Keeps the two-tier penalty from ``skills.verify_skills``: a claim with no
    evidence anywhere costs more than one evidenced only outside work history.
    """
    from app.scoring.config import load

    cfg = load()["skills"]
    skills_text = " ".join(skill_tags)
    work_text = " ".join(
        (we.get("job_description", "") or "") + " " + (we.get("job_skills", "") or "")
        for we in work_experiences
    )
    corpus_lower = f"{skills_text} {work_text} {raw_markdown}".lower()
    work_lower = work_text.lower()
    raw_lower = (raw_markdown or "").lower()

    # Highest-scoring ecosystem with any evidence wins; a profile lists them
    # best-first but does not have to, so pick by score rather than order.
    best_name, best_score = "", 0.0
    fallback = None
    for eco in profile.ecosystems:
        if not eco.keywords:
            # A keyword-less ecosystem is the profile's "everything else"
            # bucket; hold it aside instead of matching it against nothing.
            if fallback is None or eco.score < fallback.score:
                fallback = eco
            continue
        if _hits(corpus_lower, eco.keywords) and eco.score > best_score:
            best_name, best_score = eco.name, float(eco.score)

    if not best_name:
        if fallback is not None:
            best_name, best_score = fallback.name, float(fallback.score)
        else:
            best_name, best_score = "General", float(
                cfg["ecosystem_scores"].get("General", 30)
            )

    # Verify claimed skills against evidence.
    suspicious: list[str] = []
    score = best_score
    for tag in skill_tags:
        t = tag.strip().lower()
        if len(t) < 2:
            continue
        if t in work_lower:
            continue
        if t in raw_lower:
            score -= float(cfg["penalty_portfolio_only"])
            suspicious.append(f"技能 '{tag}' 僅見於自述/作品，未見於工作經歷")
        else:
            score -= float(cfg["penalty_unsupported"])
            suspicious.append(f"技能 '{tag}' 無任何佐證")

    # Keyword stuffing: a skill list far longer than the work descriptions that
    # should support it.
    if len(skills_text) > 200 and len(skills_text) > len(work_text) * 2:
        score -= float(cfg["penalty_keyword_stuffing"])
        suspicious.append("技能列表長度顯著超過工作描述，疑似關鍵字堆砌")

    return SkillVerification(
        skill_ecosystem=best_name,
        suspicious_flags=suspicious[:10],
        score=round(max(score, float(cfg["floor"])), 1),
    )


# --- Education --------------------------------------------------------------

def _major_matches(major_lower: str, listed: str) -> bool:
    """Does a resume's major match a profile's listed field of study?

    Plain substring matching in one direction is not enough for Chinese majors,
    which are written both in full and abbreviated: a profile saying "企管" must
    match a resume saying "企業管理學系", and vice versa. Neither string contains
    the other, so the abbreviation is compared against the full form with its
    common suffixes stripped, and containment is checked both ways.
    """
    x = (listed or "").strip().lower()
    # An empty entry on either side matches nothing: `"" in anything` is True,
    # which would otherwise classify every candidate as Tier1.
    if not x or not major_lower.strip():
        return False
    if x in major_lower or major_lower in x:
        return True
    # "企業管理學系" -> "企業管理"; then "企管" is checked character-wise against it.
    stem = major_lower
    for suffix in ("研究所", "碩士班", "博士班", "學位學程", "學系", "系所", "學程",
                   " department", " dept"):
        stem = stem.replace(suffix, "")
    # Bare 系/所/組 only at the END, so "系統工程" is not mangled into "統工程".
    while stem and stem[-1] in "系所組班":
        stem = stem[:-1]
    stem = stem.strip("　 ·・-")
    if not stem:
        return False
    if x in stem or stem in x:
        return True
    # Abbreviation check, run BOTH ways — the profile may hold the short form
    # ("企管" vs a resume's "企業管理學系") or the long one ("企業管理" vs a
    # resume's "企管系"). It succeeds when every character of the shorter CJK
    # string appears in the longer one IN ORDER; requiring order, and 2+ CJK
    # characters, is what stops "資管" matching "管理資訊".
    short, long = (x, stem) if len(x) <= len(stem) else (stem, x)
    if len(short) >= 2 and all("\u4e00" <= ch <= "\u9fff" for ch in short):
        pos = 0
        for ch in short:
            pos = long.find(ch, pos)
            if pos < 0:
                return False
            pos += 1
        return True
    return False


def major_relevance_by_profile(profile: DomainProfile, major: str) -> str:
    """Classify a major as Tier1 / Tier2 / Other for this role."""
    m = (major or "").lower()
    if not m:
        return "Other"
    if any(_major_matches(m, x) for x in profile.education.tier1_majors):
        return "Tier1"
    if any(_major_matches(m, x) for x in profile.education.tier2_majors):
        return "Tier2"
    return "Other"
