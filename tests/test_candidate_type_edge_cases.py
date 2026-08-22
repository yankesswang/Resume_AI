"""Additional 實習/正職 edge cases.

Complements ``tests/test_candidate_type.py`` (39 script-style cases). This file
covers boundaries that file does not: the exact NEW_GRAD_HORIZON_MONTHS and
STUDENT_JOB_TAIL_MONTHS cutoffs, the full STUDENT_JOB_KEYWORDS vocabulary, the
degree-rank comparison, and the deliberate "empty work list is not evidence"
rule.

Every case pins ``today`` so results cannot drift with the wall clock — the same
discipline the original file uses.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import (
    NEW_GRAD_HORIZON_MONTHS,
    STUDENT_JOB_KEYWORDS,
    STUDENT_JOB_TAIL_MONTHS,
    calc_candidate_type,
    has_only_student_work,
)

TODAY = date(2026, 8, 17)


def edu(degree_level, status, date_end="", date_start=""):
    return {
        "degree_level": degree_level,
        "status": status,
        "date_start": date_start,
        "date_end": date_end,
    }


def job(job_title, date_start="", date_end="", job_category=""):
    return {
        "job_title": job_title,
        "job_category": job_category,
        "date_start": date_start,
        "date_end": date_end,
    }


def classify(education, **candidate):
    return calc_candidate_type(education, candidate, today=TODAY)


# ---------------------------------------------------------------------------
# NEW_GRAD_HORIZON_MONTHS boundary
# ---------------------------------------------------------------------------
def test_new_grad_horizon_is_twelve_months():
    """Pin the constant the boundary cases below are written against."""
    assert NEW_GRAD_HORIZON_MONTHS == 12


def test_student_wanting_fulltime_exactly_at_horizon_is_engineer():
    """Exactly 12 months out is inside the horizon (<=), so 正職."""
    education = [edu("碩士", "就學中", date_end="2027/08/01")]
    assert classify(education, work_type="全職") == "正職"


def test_student_wanting_fulltime_one_month_past_horizon_is_intern():
    """13 months out is too early to be treated as a new grad."""
    education = [edu("碩士", "就學中", date_end="2027/09/01")]
    assert classify(education, work_type="全職") == "實習"


def test_student_wanting_fulltime_and_intern_stays_intern():
    """Asking for 實習 too means the 全職 new-grad shortcut must not apply."""
    education = [edu("碩士", "就學中", date_end="2026/09/01")]
    assert classify(education, work_type="全職,實習") == "實習"


def test_student_without_work_type_is_intern_even_near_graduation():
    """The 正職 shortcut requires an explicit 全職 declaration."""
    education = [edu("碩士", "就學中", date_end="2026/09/01")]
    assert classify(education) == "實習"


# ---------------------------------------------------------------------------
# Graduation-month boundary
# ---------------------------------------------------------------------------
def test_graduating_this_exact_month_still_counts_as_studying():
    """104 stores year/month only, so the graduation month is not yet complete."""
    education = [edu("碩士", "就學中", date_end="2026/08/01")]
    assert classify(education) == "實習"


def test_graduated_last_month_is_engineer():
    education = [edu("碩士", "就學中", date_end="2026/07/01")]
    assert classify(education, years_of_experience="2~3年") == "正職"


# ---------------------------------------------------------------------------
# Degree rank: only the highest programme decides
# ---------------------------------------------------------------------------
def test_phd_student_with_graduated_masters_is_intern():
    education = [
        edu("碩士", "畢業", date_end="2024/06/01"),
        edu("博士", "就學中", date_end="2029/06/01"),
    ]
    assert classify(education) == "實習"


def test_masters_graduate_with_stale_bachelor_in_school_row_is_engineer():
    """A leftover lower-degree 就學中 row must not outrank the finished master's."""
    education = [
        edu("大學", "就學中", date_end="2023/06/01"),
        edu("碩士", "畢業", date_end="2025/06/01"),
    ]
    assert classify(education, years_of_experience="2~3年") == "正職"


def test_highschool_in_school_row_ignored_for_university_graduate():
    education = [
        edu("高中", "就學中", date_end="2020/06/01"),
        edu("大學", "畢業", date_end="2024/06/01"),
    ]
    assert classify(education, years_of_experience="2~3年") == "正職"


# ---------------------------------------------------------------------------
# STUDENT_JOB_KEYWORDS vocabulary
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("keyword", list(STUDENT_JOB_KEYWORDS))
def test_every_student_job_keyword_marks_student_work(keyword):
    """Each documented keyword must actually be recognised in a job title."""
    education = [edu("大學", "畢業", date_end="2026/06/01", date_start="2022/09/01")]
    work = [job(f"{keyword}職務", date_start="2025/01/01", date_end="2025/06/01")]
    assert has_only_student_work(work, education, TODAY) is True


def test_graduate_with_only_intern_history_is_intern():
    education = [edu("大學", "畢業", date_end="2026/06/01", date_start="2022/09/01")]
    work = [job("軟體工程實習生", date_start="2025/07/01", date_end="2025/12/01")]
    assert classify(education, work_experiences=work, years_of_experience="一年以下") == "實習"


def test_graduate_with_one_real_job_is_engineer():
    """A single non-student record is enough to end intern-tier treatment."""
    education = [edu("大學", "畢業", date_end="2026/06/01", date_start="2022/09/01")]
    work = [
        job("軟體工程實習生", date_start="2024/07/01", date_end="2024/12/01"),
        job("後端工程師", date_start="2026/07/01", date_end="仍在職"),
    ]
    assert has_only_student_work(work, education, TODAY) is False


# ---------------------------------------------------------------------------
# STUDENT_JOB_TAIL_MONTHS: overlap alone is not enough
# ---------------------------------------------------------------------------
def test_student_job_tail_is_six_months():
    assert STUDENT_JOB_TAIL_MONTHS == 6


def test_job_started_in_study_period_and_ended_just_after_is_student_work():
    """Ending within the tail window reads as a wrap-up, not a career."""
    education = [edu("大學", "畢業", date_start="2022/09/01", date_end="2026/06/01")]
    work = [job("軟體開發", date_start="2025/09/01", date_end="2026/08/01")]
    assert has_only_student_work(work, education, TODAY) is True


def test_job_started_in_final_year_but_still_running_is_a_real_career():
    """Overlap alone misclassified 61 working engineers — both halves required."""
    education = [edu("大學", "畢業", date_start="2018/09/01", date_end="2022/06/01")]
    work = [job("軟體工程師", date_start="2021/09/01", date_end="仍在職")]
    assert has_only_student_work(work, education, TODAY) is False


# ---------------------------------------------------------------------------
# Empty work list is deliberately NOT "never worked"
# ---------------------------------------------------------------------------
def test_empty_work_list_is_not_treated_as_never_worked():
    """1652 corpus candidates have no parsed work rows; empty must stay neutral."""
    education = [edu("大學", "畢業", date_end="2024/06/01", date_start="2020/09/01")]
    assert has_only_student_work([], education, TODAY) is False


def test_graduate_with_unparsed_work_section_is_engineer():
    education = [edu("大學", "畢業", date_end="2024/06/01", date_start="2020/09/01")]
    assert classify(education, work_experiences=[], years_of_experience="一年以下") == "正職"


# ---------------------------------------------------------------------------
# 肄業 handling
# ---------------------------------------------------------------------------
def test_bare_dropped_out_is_not_enrolled():
    assert classify([edu("大學", "肄業", date_end="2028/06/01")]) == "正職"


def test_dropped_out_but_still_enrolled_is_intern():
    assert classify([edu("大學", "肄業中", date_end="2028/06/01")]) == "實習"


# ---------------------------------------------------------------------------
# work_type declarations without usable dates
# ---------------------------------------------------------------------------
def test_in_school_unknown_end_date_defers_to_work_type_fulltime():
    assert classify([edu("碩士", "就學中", date_end="")], work_type="全職") == "正職"


def test_in_school_unknown_end_date_defers_to_work_type_intern():
    assert classify([edu("碩士", "就學中", date_end="")], work_type="實習") == "實習"


def test_in_school_unknown_end_date_uses_experience_when_no_work_type():
    """No date and no declaration: a real career record decides."""
    education = [edu("碩士", "就學中", date_end="")]
    assert classify(education, years_of_experience="6~7年") == "正職"
    assert classify(education, years_of_experience="一年以下") == "實習"


def test_unparsable_graduation_date_is_treated_as_unknown():
    education = [edu("碩士", "就學中", date_end="不詳")]
    assert classify(education, work_type="全職") == "正職"


def test_experienced_candidate_open_to_intern_stays_engineer():
    """Wanting 實習 only downgrades someone with no career track record."""
    education = [edu("大學", "畢業", date_end="2020/06/01")]
    assert classify(education, work_type="實習", years_of_experience="4~5年") == "正職"


# ---------------------------------------------------------------------------
# Degenerate input
# ---------------------------------------------------------------------------
def test_no_education_rows_defaults_to_engineer():
    assert classify([]) == "正職"


def test_single_argument_call_still_supported():
    """Older callers pass education only; the rule must degrade gracefully."""
    assert calc_candidate_type([edu("碩士", "就學中", date_end="2028/06/01")]) == "實習"


def test_none_candidate_is_accepted():
    assert calc_candidate_type([], None, today=TODAY) == "正職"
