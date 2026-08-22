"""Layer 1: Hard boolean filters for quick rejection."""

from __future__ import annotations

from typing import Any

from app.models import EducationExtract

# Degree ladder, lowest to highest. A filter of "master" accepts a master's or
# a doctorate, never a bachelor's — the gate is a floor, not an exact match.
_DEGREE_ORDER = ["high_school", "associate", "bachelor", "master", "phd"]

# School tiers, lowest to highest, matching app/scoring/education.py's global
# ladder. "S" is deliberately absent: _school_points returns it for any PhD
# regardless of institution, so it rates the degree, not the school.
_SCHOOL_ORDER = ["D", "C", "B", "A"]

_SCHOOL_LABELS = {
    "A": "頂尖大學",
    "B": "中字輩以上",
    "C": "一般大學以上",
    "D": "不限",
}

_DEGREE_LABELS = {
    "high_school": "高中",
    "associate": "專科",
    "bachelor": "學士",
    "master": "碩士",
    "phd": "博士",
}


def apply_hard_filters(
    skill_tags: list[str],
    work_experiences: list[dict[str, Any]],
    raw_markdown: str,
    hard_filter_config: dict[str, Any],
    education: list[EducationExtract] | None = None,
) -> tuple[bool, list[str]]:
    """Check boolean hard filters from job requirement config.

    Returns (passed, list_of_failure_reasons).
    """
    failures = []

    # Combine all searchable text
    all_text_parts = [raw_markdown]
    all_text_parts.extend(skill_tags)
    for we in work_experiences:
        all_text_parts.append(we.get("job_description", "") or "")
        all_text_parts.append(we.get("job_title", "") or "")
        all_text_parts.append(we.get("job_skills", "") or "")
    combined = " ".join(all_text_parts).lower()

    # Check required_skills (ALL must be present) — backward-compatible hard gate
    required_skills = hard_filter_config.get("required_skills", [])
    for skill in required_skills:
        if skill.lower() not in combined:
            failures.append(f"Missing required skill: {skill}")

    # Check required_frameworks (at least ONE must be present) — backward-compat
    required_frameworks = hard_filter_config.get("required_frameworks", [])
    if required_frameworks:
        found_any = any(fw.lower() in combined for fw in required_frameworks)
        if not found_any:
            failures.append(
                f"Missing required framework (need at least one of: {', '.join(required_frameworks)})"
            )

    # Check required_keywords (at least ONE must be present) — backward-compat
    required_keywords = hard_filter_config.get("required_keywords", [])
    if required_keywords:
        found_any = any(kw.lower() in combined for kw in required_keywords)
        if not found_any:
            failures.append(
                f"Missing required keyword (need at least one of: {', '.join(required_keywords)})"
            )

    # Check must_have_groups: each group needs at least min_matches hits.
    # Replaces ALL-must-match with flexible group-based filtering, e.g.:
    #   Group A (≥1): PyTorch / TensorFlow
    #   Group B (≥1): LLM / Transformer / Attention / BERT
    #   Group C (≥1): RAG / Fine-tuning / Inference serving
    must_have_groups = hard_filter_config.get("must_have_groups", [])
    for group in must_have_groups:
        group_name = group.get("name", "Group")
        group_skills = group.get("skills", [])
        min_matches = int(group.get("min_matches", 1))
        hits = sum(1 for skill in group_skills if skill.lower() in combined)
        if hits < min_matches:
            failures.append(
                f"Group '{group_name}': need {min_matches} of "
                f"[{', '.join(group_skills)}], found {hits}"
            )

    # Check required_skills_threshold: N-of-M matching (e.g. 2 of 5 keywords)
    threshold_config = hard_filter_config.get("required_skills_threshold", {})
    if threshold_config:
        threshold_skills = threshold_config.get("skills", [])
        min_matches = int(threshold_config.get("min_matches", 1))
        hits = sum(1 for skill in threshold_skills if skill.lower() in combined)
        if hits < min_matches:
            failures.append(
                f"Skills threshold: need {min_matches} of {len(threshold_skills)} "
                f"[{', '.join(threshold_skills)}], found {hits}"
            )

    # Check min_education: the candidate's highest degree must reach this rung.
    # Unlike every filter above, this is not a text match — "碩士" appearing in
    # a resume usually means a colleague's degree or a job requirement, not the
    # applicant's own, so the gate reads the parsed education rows instead.
    min_education = (hard_filter_config.get("min_education") or "").strip()
    if min_education:
        required = normalise_degree(min_education)
        if required is None:
            # An unrecognised value is a misconfiguration, not a reason to
            # reject everyone: screening blind is worse than not screening.
            pass
        else:
            highest = _highest_degree(education or [])
            if highest is None:
                failures.append(
                    f"學歷未達 {_DEGREE_LABELS[required]}：履歷無可辨識的學歷資料"
                )
            elif _DEGREE_ORDER.index(highest) < _DEGREE_ORDER.index(required):
                failures.append(
                    f"學歷未達 {_DEGREE_LABELS[required]}："
                    f"最高學歷為 {_DEGREE_LABELS[highest]}"
                )

    # Check min_school_tier: the candidate's best school must reach this rung.
    # Same reasoning as min_education — school names in resume text belong to
    # previous employers and clients as often as to the applicant.
    min_school = (hard_filter_config.get("min_school_tier") or "").strip().upper()
    if min_school and min_school in _SCHOOL_ORDER and min_school != "D":
        best = _best_school_tier(education or [])
        if best is None:
            failures.append(
                f"學校未達 {_SCHOOL_LABELS[min_school]}：履歷無可辨識的學校資料"
            )
        elif _SCHOOL_ORDER.index(best) < _SCHOOL_ORDER.index(min_school):
            failures.append(
                f"學校未達 {_SCHOOL_LABELS[min_school]}：最佳學校為第 {best} 級"
            )

    return len(failures) == 0, failures


# Keyword tables for reading a degree out of free text. Ordered checks below go
# highest-first so "碩士" inside "碩士班" is not shadowed by a bachelor keyword.
_PHD_KEYWORDS = ("博士", "phd", "ph.d", "doctor", "doctorate")
_MASTER_KEYWORDS = ("碩士", "碩", "master", "mba", "m.s.", "m.a.", "研究所", "graduate")
_BACHELOR_KEYWORDS = (
    "大學", "學士", "四技", "二技", "bachelor", "b.s.", "b.a.", "university", "college",
)
_ASSOCIATE_KEYWORDS = ("專科", "五專", "二專", "三專", "副學士", "associate")
_HIGH_SCHOOL_KEYWORDS = ("高中", "高職", "高級中學", "high school")


def normalise_degree(value: str) -> str | None:
    """Map a config value ("master", "碩士", "碩士以上") onto the ladder."""
    v = value.strip().lower()
    if v in _DEGREE_ORDER:
        return v
    for level, keywords in (
        ("phd", _PHD_KEYWORDS),
        ("master", _MASTER_KEYWORDS),
        ("bachelor", _BACHELOR_KEYWORDS),
        ("associate", _ASSOCIATE_KEYWORDS),
        ("high_school", _HIGH_SCHOOL_KEYWORDS),
    ):
        if any(k in v for k in keywords):
            return level
    return None


def _highest_degree(education: list[EducationExtract]) -> str | None:
    """The highest rung any education row reaches, or None if none parse.

    Both ``degree_level`` and ``department`` are consulted: the parser often
    leaves ``degree_level`` blank and stores "資訊工程學系碩士班" in the major.
    """
    best: str | None = None
    for ed in education:
        text = f"{ed.degree_level} {ed.department}"
        level = normalise_degree(text)
        if level is None:
            continue
        if best is None or _DEGREE_ORDER.index(level) > _DEGREE_ORDER.index(best):
            best = level
    return best


def _best_school_tier(education: list[EducationExtract]) -> str | None:
    """The highest school tier across all education rows, or None if none parse.

    ``school_tier`` rather than ``_school_points`` is deliberate: the latter
    promotes any PhD to "S" irrespective of institution, which is a degree
    premium and would let a doctorate from an unranked school clear a "top
    university" gate. Operator overrides from the scoring config apply here
    too, since they live inside ``school_tier``.
    """
    from app.scoring.education import school_tier

    best: str | None = None
    for ed in education:
        if not (ed.school or "").strip():
            continue
        tier = school_tier(ed.school)
        if tier not in _SCHOOL_ORDER:
            continue
        if best is None or _SCHOOL_ORDER.index(tier) > _SCHOOL_ORDER.index(best):
            best = tier
    return best
