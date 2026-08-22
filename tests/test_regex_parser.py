"""Regex extraction of structured fields from resume markdown.

Fixtures in ``tests/fixtures/`` are synthetic but reproduce the two real shapes
Marker emits for 104.com resumes: a table-heavy layout and a flat-text OCR
layout that uses CJK compatibility codepoints (``⼯作經驗`` with U+2F27 rather
than ``工``). No real applicant data is committed — see fixtures/README.md.

Scope note: these lock down the fields the downstream scoring pipeline actually
depends on (identity, contact, education rows, work dates/skills). One known
parser limitation is pinned explicitly at the bottom rather than asserted as if
it were correct behaviour.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.regex_parser import _normalize_cjk, parse_resume_markdown

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def table_resume():
    return parse_resume_markdown((FIXTURES / "resume_table_format.md").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def flat_resume():
    return parse_resume_markdown((FIXTURES / "resume_flat_format.md").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Basic identity fields
# ---------------------------------------------------------------------------
def test_table_basic_info(table_resume):
    assert table_resume.name == "王小明"
    assert table_resume.english_name == "Ming Wang"
    assert table_resume.code_104 == "30000009999001"
    assert table_resume.birth_year == "1998"


def test_table_education_summary_fields(table_resume):
    """The flat school/major fields feed the candidate list view."""
    assert table_resume.education_level == "碩士"
    assert table_resume.school == "國立清華大學"
    assert table_resume.major == "資訊工程學系"


def test_table_contact_fields(table_resume):
    assert table_resume.email == "ming.wang@example.com"
    assert table_resume.mobile1 == "0900000001"
    assert table_resume.district == "台北市大安區"


def test_table_job_seeking_fields(table_resume):
    """work_type drives the 實習/正職 classification, so it must survive parsing."""
    assert table_resume.years_of_experience == "2~3年"
    assert table_resume.work_type == "全職"


def test_flat_basic_info(flat_resume):
    """Flat OCR layout: no pipe tables, bold-marker separators, CJK variants."""
    assert flat_resume.name == "陳美玲"
    assert flat_resume.code_104 == "30000008888002"
    assert flat_resume.birth_year == "2002"
    assert flat_resume.education_level == "大學"
    assert flat_resume.school == "國立中正大學"


def test_flat_contact_fields(flat_resume):
    assert flat_resume.email == "meiling.chen@example.com"
    assert flat_resume.mobile1 == "0900000002"


# ---------------------------------------------------------------------------
# Education rows
# ---------------------------------------------------------------------------
def test_table_education_rows(table_resume):
    edu = table_resume.education
    assert len(edu) == 2

    masters, bachelor = edu[0], edu[1]
    assert (masters.school, masters.degree_level) == ("國立清華大學", "碩士")
    assert masters.date_start == "2019/09/01"
    assert masters.date_end == "2021/06/01"
    assert masters.status == "畢業"

    assert (bachelor.school, bachelor.degree_level) == ("淡江大學", "大學")


def test_flat_education_rows(flat_resume):
    assert len(flat_resume.education) == 1
    row = flat_resume.education[0]
    assert row.school == "國立中正大學"
    assert row.department == "資訊管理學系"
    assert row.degree_level == "大學"
    assert row.status == "畢業"


def test_education_rows_carry_dates_for_candidate_type(flat_resume):
    """calc_candidate_type needs date_start/date_end/status on every row."""
    for row in flat_resume.education:
        assert row.date_start and row.date_end
        assert row.status


# ---------------------------------------------------------------------------
# Work experience
# ---------------------------------------------------------------------------
def test_table_work_experience_company_and_dates(table_resume):
    work = table_resume.work_experiences
    assert work, "no work experience parsed"

    first = work[0]
    assert "未來智能" in first.company_name
    assert first.date_start == "2023/03/01"
    assert first.date_end == "仍在職"


def test_flat_work_experience_parsed(flat_resume):
    """The flat layout exercises the pass-2 fallback in _parse_work_experience."""
    assert len(flat_resume.work_experiences) == 1
    job = flat_resume.work_experiences[0]
    assert job.company_name == "飛躍資訊股份有限公司"
    assert job.date_start == "2024/07/01"
    assert job.date_end == "2025/01/01"
    assert job.job_title == "軟體工程實習生"
    assert job.job_category == "軟體工程師"
    assert job.job_skills == "Python,Pandas,SQL"


def test_flat_intern_title_is_preserved(flat_resume):
    """`實習` in the title is what STUDENT_JOB_KEYWORDS keys off downstream."""
    assert "實習" in flat_resume.work_experiences[0].job_title


# ---------------------------------------------------------------------------
# CJK compatibility normalisation
# ---------------------------------------------------------------------------
def test_normalize_cjk_maps_compatibility_radicals():
    """Marker emits U+2F27 (⼧-style radicals); parsing must see the normal form."""
    assert _normalize_cjk("⼯作經驗") == "工作經驗"
    assert _normalize_cjk("⾃我介紹") == "自我介紹"


def test_flat_sections_found_despite_cjk_variants(flat_resume):
    """The flat fixture spells its headings with compatibility codepoints."""
    assert flat_resume.work_experiences, "CJK-variant 工作經驗 heading was not matched"
    assert flat_resume.self_introduction


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------
def test_empty_markdown_does_not_crash():
    result = parse_resume_markdown("")
    assert result.name == ""
    assert result.work_experiences == []
    assert result.education == []


def test_garbage_markdown_does_not_crash():
    result = parse_resume_markdown("# Not a resume\n\nJust some prose.\n")
    assert result.education == []


def test_photo_path_empty_when_no_image(flat_resume):
    assert flat_resume.photo_path == ""


def test_photo_path_extracted_when_present(table_resume):
    """The table fixture carries a headshot reference in 基本資料."""
    assert table_resume.photo_path.endswith(".jpeg")


# ---------------------------------------------------------------------------
# Known limitation (documented, not asserted as correct)
# ---------------------------------------------------------------------------
@pytest.mark.xfail(
    reason=(
        "A '### ' sub-heading inside a job entry ends the 工作經驗 section, so "
        "later jobs are dropped and job_title keeps raw table pipes. Real 104 "
        "resumes hit this too (a second employer becomes its own section key). "
        "Pinned as xfail so a future parser fix flips this to XPASS instead of "
        "silently going unnoticed."
    ),
    strict=False,
)
def test_second_job_after_subheading_is_parsed(table_resume):
    work = table_resume.work_experiences
    assert len(work) == 2
    assert "起點科技" in work[1].company_name
    assert work[0].job_title == "AI工程師"  # no leftover '|' padding
