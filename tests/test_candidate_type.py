"""Tests for 實習/正職 (intern vs full-time engineer) classification.

Run: python3 tests/test_candidate_type.py

All cases pin `today` so results do not drift with the wall clock. Most cases are
taken from real 104 records that the previous "any 就學中 row" rule got wrong.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import calc_candidate_type

TODAY = date(2026, 8, 17)

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def classify(education, **candidate):
    return calc_candidate_type(education, candidate, today=TODAY)


def edu(degree_level, status, date_end="", date_start=""):
    return {
        "degree_level": degree_level,
        "status": status,
        "date_start": date_start,
        "date_end": date_end,
    }


def job(job_title, date_start, date_end="", job_category=""):
    return {
        "job_title": job_title,
        "job_category": job_category,
        "date_start": date_start,
        "date_end": date_end,
    }


IN_SCHOOL = "就學中(日間就讀中)"


# ---------------------------------------------------------------------------
# 1. Current students -> 實習
# ---------------------------------------------------------------------------
def test_current_students():
    print("\n=== Current students ===")

    r = classify([edu("大學", IN_SCHOOL, "2027/06/01")])
    check("undergrad graduating 2027 -> 實習", r == "實習", f"got {r}")

    r = classify([
        edu("碩士", IN_SCHOOL, "2028/06/01"),
        edu("大學", "畢業", "2026/06/01"),
    ])
    check("masters graduating 2028 -> 實習", r == "實習", f"got {r}")

    # Real case 1477: wants 全職 but is two years from graduating.
    r = classify(
        [edu("碩士", IN_SCHOOL, "2027/06/01"), edu("大學", "畢業", "2025/06/01")],
        work_type="全職 / 兼職 / 實習工作 / 寒暑假工讀",
        years_of_experience="3~4年",
    )
    check("far-from-grad student wanting 全職 -> 實習", r == "實習", f"got {r}")

    # Graduation in the current month still counts as enrolled (day is unknown).
    r = classify([edu("碩士", IN_SCHOOL, "2026/08/31")])
    check("graduating later this month -> 實習", r == "實習", f"got {r}")


# ---------------------------------------------------------------------------
# 2. Stale in-school rows -> 正職  (the main old-rule failure)
# ---------------------------------------------------------------------------
def test_stale_in_school_rows():
    print("\n=== Stale 就學中 rows ===")

    # Real case 184: 大學畢業 2022 with a leftover 高中 就學中 row and no end date.
    # The old rule hit `if not grad: return 實習`.
    r = classify(
        [edu("大學", "畢業", "2022/06/01"), edu("高中", IN_SCHOOL, "")],
        work_type="全職",
        years_of_experience="2~3年",
    )
    check("grad w/ stale 高中 就學中 row -> 正職", r == "正職", f"got {r}")

    # Lower-degree in-school row must not outrank the highest degree.
    r = classify(
        [edu("碩士", "畢業", "2024/06/01"), edu("大學", IN_SCHOOL, "2027/06/01")],
        work_type="全職",
        years_of_experience="3~4年",
    )
    check("masters grad w/ 大學 就學中 row -> 正職", r == "正職", f"got {r}")

    # Graduation date already past: resume written before graduating.
    r = classify(
        [edu("大學", IN_SCHOOL, "2025/06/01")],
        work_type="全職",
        years_of_experience="1~2年",
    )
    check("就學中 but graduated 2025 -> 正職", r == "正職", f"got {r}")

    # Real cases 91/132: 碩士 就學中 with end date 2026/08 (already past).
    r = classify(
        [edu("碩士", IN_SCHOOL, "2026/07/01"), edu("大學", "畢業", "2023/06/01")],
        years_of_experience="無",
    )
    check("碩士 就學中 ending last month -> 正職", r == "正職", f"got {r}")


# ---------------------------------------------------------------------------
# 3. work_type is the candidate's own declaration
# ---------------------------------------------------------------------------
def test_work_type_signal():
    print("\n=== work_type signal ===")

    # Real case 16: 大學就學中 graduating 2026/06 (past), wants 實習工作 only.
    r = classify(
        [edu("大學", IN_SCHOOL, "2026/06/01")],
        work_type="實習工作",
        years_of_experience="一年以下",
    )
    check("intern-only work_type, no career -> 實習", r == "實習", f"got {r}")

    # Real case 32: 寒暑假工讀 counts as intern intent.
    r = classify(
        [edu("大學", IN_SCHOOL, "2026/06/01")],
        work_type="寒暑假工讀",
        years_of_experience="無",
    )
    check("寒暑假工讀 -> 實習", r == "實習", f"got {r}")

    # Real case 35: no education rows at all, but declares 實習工作.
    r = classify([], work_type="實習工作", years_of_experience="一年以下")
    check("no education rows + 實習工作 -> 實習", r == "實習", f"got {r}")

    # Asking for 實習 but with a real career track record -> still an engineer.
    r = classify(
        [edu("大學", "畢業", "2018/06/01")],
        work_type="全職 / 實習工作",
        years_of_experience="5~6年",
    )
    check("experienced dev open to 實習 -> 正職", r == "正職", f"got {r}")

    r = classify(
        [edu("大學", "畢業", "2019/06/01")],
        work_type="實習工作",
        years_of_experience="4~5年",
    )
    check("intern-only but 4~5年 experience -> 正職", r == "正職", f"got {r}")

    # Near-graduation student explicitly seeking 全職 = new grad engineer.
    r = classify(
        [edu("碩士", IN_SCHOOL, "2027/06/01")],
        work_type="全職",
        years_of_experience="一年以下",
    )
    check("student graduating within 12mo wanting 全職 -> 正職", r == "正職", f"got {r}")


# ---------------------------------------------------------------------------
# 4. Graduated / dropped out
# ---------------------------------------------------------------------------
def test_graduated_and_dropped_out():
    print("\n=== Graduated / dropped out ===")

    r = classify(
        [edu("碩士", "畢業", "2020/06/01")],
        work_type="全職",
        years_of_experience="5~6年",
    )
    check("masters graduate -> 正職", r == "正職", f"got {r}")

    # Bare 肄業 = dropped out, no longer enrolled.
    r = classify(
        [edu("大學", "肄業", "2021/06/01")],
        work_type="全職",
        years_of_experience="3~4年",
    )
    check("肄業 (dropped out) -> 正職", r == "正職", f"got {r}")

    # 肄業中 = dropped out but still enrolled.
    r = classify([edu("碩士", "肄業中", "2027/06/01")])
    check("肄業中 w/ future end date -> 實習", r == "實習", f"got {r}")

    # Region prefixes appear in the status column in real data.
    r = classify(
        [edu("大學", "台灣畢業", "2021/06/01")],
        work_type="全職",
        years_of_experience="4~5年",
    )
    check("台灣畢業 -> 正職", r == "正職", f"got {r}")

    r = classify([edu("大學", "美國就學中(日間就讀中)", "2027/06/01")])
    check("美國就學中 -> 實習", r == "實習", f"got {r}")


# ---------------------------------------------------------------------------
# 5. Missing / ambiguous data
# ---------------------------------------------------------------------------
def test_missing_data():
    print("\n=== Missing data ===")

    r = classify([])
    check("no education, no signals -> 正職", r == "正職", f"got {r}")

    # In-school, unknown end date, declares 全職 -> trust the declaration.
    r = classify(
        [edu("碩士", IN_SCHOOL, "")],
        work_type="全職",
        years_of_experience="2~3年",
    )
    check("就學中 no end date + 全職 -> 正職", r == "正職", f"got {r}")

    # In-school, unknown end date, no declaration, no career -> assume student.
    r = classify([edu("碩士", IN_SCHOOL, "")], years_of_experience="無")
    check("就學中 no end date, no career -> 實習", r == "實習", f"got {r}")

    # In-school, unknown end date, no declaration, real career -> engineer.
    r = classify([edu("碩士", IN_SCHOOL, "")], years_of_experience="6~7年")
    check("就學中 no end date, 6~7年 career -> 正職", r == "正職", f"got {r}")

    # Malformed date_end (month 13) is unparsable -> falls back to signals.
    r = classify(
        [edu("大學", IN_SCHOOL, "2027/13/01")],
        work_type="全職",
        years_of_experience="1~2年",
    )
    check("unparsable month + 全職 -> 正職", r == "正職", f"got {r}")

    # candidate dict omitted entirely (backwards-compatible call).
    r = calc_candidate_type([edu("大學", IN_SCHOOL, "2027/06/01")], today=TODAY)
    check("single-arg call still works -> 實習", r == "實習", f"got {r}")


# ---------------------------------------------------------------------------
# 6. Graduated but never really worked -> still 實習
# ---------------------------------------------------------------------------
def test_graduate_without_career():
    print("\n=== Graduated, work was all student work ===")

    masters = [
        edu("碩士", "畢業", "2025/06/01", "2023/09/01"),
        edu("大學", "畢業", "2023/06/01", "2019/09/01"),
    ]

    # Real case 4: 學生研究員 started during the masters, still listed as 仍在職.
    r = classify(
        masters,
        work_type="全職",
        years_of_experience="一年以下",
        work_experiences=[job("學生研究員", "2025/01/01", "仍在職")],
    )
    check("grad whose only job is 學生研究員 -> 實習", r == "實習", f"got {r}")

    # Real case 21: 兼任研究助理 during the degree.
    r = classify(
        [edu("碩士", "畢業", "2025/08/01", "2022/09/01")],
        work_type="全職",
        years_of_experience="無",
        work_experiences=[job("兼任研究助理", "2023/01/01", "2024/08/01")],
    )
    check("grad whose only job is 兼任研究助理 -> 實習", r == "實習", f"got {r}")

    # Real case 18: 暑期實習生 well before graduating.
    r = classify(
        [edu("碩士", "畢業", "2024/06/01", "2022/09/01")],
        years_of_experience="一年以下",
        work_experiences=[job("暑期實習生", "2021/07/01", "2021/08/01")],
    )
    check("grad whose only job is 暑期實習生 -> 實習", r == "實習", f"got {r}")

    # English intern titles must match too.
    r = classify(
        masters,
        work_type="全職",
        years_of_experience="無",
        work_experiences=[job("IT support Intern", "2020/06/01", "2020/09/01")],
    )
    check("grad whose only job is an Intern role -> 實習", r == "實習", f"got {r}")

    # Untitled job dated inside the study window is student work.
    r = classify(
        masters,
        work_type="全職",
        years_of_experience="無",
        work_experiences=[job("", "2024/10/01", "2024/12/01")],
    )
    check("untitled job inside study window -> 實習", r == "實習", f"got {r}")

    # Multiple records, all student work.
    r = classify(
        masters,
        work_type="全職",
        years_of_experience="一年以下",
        work_experiences=[
            job("AI 音訊演算法工程師實習生", "2025/07/01", "2025/08/01"),
            job("專任研究助理", "2023/02/01", "2024/12/01"),
        ],
    )
    check("all records are student work -> 實習", r == "實習", f"got {r}")


# ---------------------------------------------------------------------------
# 7. The work-history rule must not swallow real engineers
# ---------------------------------------------------------------------------
def test_real_career_stays_engineer():
    print("\n=== Real post-graduation career stays 正職 ===")

    masters = [
        edu("碩士", "畢業", "2023/12/01", "2021/09/01"),
        edu("大學", "畢業", "2021/06/01", "2017/09/01"),
    ]

    # Real case 15: engineering job starting after graduation.
    r = classify(
        masters,
        work_type="全職",
        years_of_experience="一年以下",
        work_experiences=[job("AI 系統開發工程師", "2024/10/01", "2025/07/01")],
    )
    check("post-grad engineering job -> 正職", r == "正職", f"got {r}")

    # Real case 243: started in the final year but still employed 4 years later.
    # Overlap alone must not label this student work.
    r = classify(
        [edu("碩士", "畢業", "2022/09/01", "2020/09/01")],
        work_type="全職",
        years_of_experience="3~4年",
        work_experiences=[job("電腦視覺 / 人工智慧工程師", "2021/04/01", "仍在職")],
    )
    check("job started in school, still running years later -> 正職", r == "正職", f"got {r}")

    # One student job plus one real job -> real career.
    r = classify(
        masters,
        work_type="全職",
        years_of_experience="一年以下",
        work_experiences=[
            job("暑期實習生", "2021/07/01", "2021/08/01"),
            job("軟體工程師", "2024/05/01", "仍在職"),
        ],
    )
    check("student job + real job -> 正職", r == "正職", f"got {r}")

    # Stated experience above the junior threshold is never overridden.
    r = classify(
        masters,
        work_type="全職",
        years_of_experience="5~6年",
        work_experiences=[job("研究助理", "2022/01/01", "2022/06/01")],
    )
    check("5~6年 experience is never demoted -> 正職", r == "正職", f"got {r}")

    # No work rows at all is a parsing gap, not proof of never having worked.
    # 1652 candidates in the corpus have no work rows, many with real experience.
    r = classify(
        masters,
        work_type="全職",
        years_of_experience="一年以下",
        work_experiences=[],
    )
    check("no work rows -> 正職 (not treated as never worked)", r == "正職", f"got {r}")

    # Caller that never loads work rows must behave the same.
    r = classify(masters, work_type="全職", years_of_experience="一年以下")
    check("work_experiences absent -> 正職", r == "正職", f"got {r}")

    # A job with no dates and no student marker counts as real work.
    r = classify(
        masters,
        work_type="全職",
        years_of_experience="無",
        work_experiences=[job("後端工程師", "", "")],
    )
    check("undated non-student job -> 正職", r == "正職", f"got {r}")

    # Undatable education means no study window; only titles can mark student work.
    r = classify(
        [edu("碩士", "畢業", "", "")],
        work_type="全職",
        years_of_experience="一年以下",
        work_experiences=[job("軟體工程師", "2024/01/01", "仍在職")],
    )
    check("no study window + engineer title -> 正職", r == "正職", f"got {r}")


def main():
    test_current_students()
    test_stale_in_school_rows()
    test_work_type_signal()
    test_graduated_and_dropped_out()
    test_missing_data()
    test_graduate_without_career()
    test_real_career_stays_engineer()
    print(f"\n{'=' * 50}")
    print(f"PASS: {PASS}   FAIL: {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
