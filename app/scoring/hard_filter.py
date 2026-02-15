"""Layer 1: Hard boolean filters for quick rejection."""

from __future__ import annotations

from typing import Any


def apply_hard_filters(
    skill_tags: list[str],
    work_experiences: list[dict[str, Any]],
    raw_markdown: str,
    hard_filter_config: dict[str, Any],
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

    # Check required_skills (ALL must be present)
    required_skills = hard_filter_config.get("required_skills", [])
    for skill in required_skills:
        if skill.lower() not in combined:
            failures.append(f"Missing required skill: {skill}")

    # Check required_frameworks (at least ONE must be present)
    required_frameworks = hard_filter_config.get("required_frameworks", [])
    if required_frameworks:
        found_any = any(fw.lower() in combined for fw in required_frameworks)
        if not found_any:
            failures.append(
                f"Missing required framework (need at least one of: {', '.join(required_frameworks)})"
            )

    # Check required_keywords (at least ONE must be present)
    required_keywords = hard_filter_config.get("required_keywords", [])
    if required_keywords:
        found_any = any(kw.lower() in combined for kw in required_keywords)
        if not found_any:
            failures.append(
                f"Missing required keyword (need at least one of: {', '.join(required_keywords)})"
            )

    return len(failures) == 0, failures
