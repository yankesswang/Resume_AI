"""Education scoring module.

Hybrid scoring based on grade_calculator approach:
- School: A=10, B=3, C=0
- Major:  Tier1=10, Tier2=3, Other=0
- Base score per degree = school + major (max 20)
- Weighted: bachelor * 0.7 + master * 0.3
- Thesis bonus: +5 for AI keywords, +5 for top venue
- Normalized to 0-100 scale
"""

from __future__ import annotations

import re

from app.models import EducationExtract, EducationLevelDetail, EducationScoreDetail

# Grade A schools: QS top / top CS programs
US_GRADE_A = [
    "Stanford", "MIT", "CMU", "Carnegie Mellon", "UC Berkeley", "Harvard",
    "Yale", "Princeton", "Columbia", "UPenn", "Cornell", "Caltech",
    "Georgia Tech", "UIUC", "UCLA", "USC", "University of Southern California",
    "NYU", "Purdue", "UMD", "UT Austin", "UCSD", "U-Mich",
    "University of Michigan", "UW", "University of Washington",
    "ETH Zurich", "Oxford", "Cambridge", "Imperial College",
    "University of Toronto", "Waterloo", "NUS", "NTU Singapore",
    "Tsinghua", "Peking University", "KAIST", "University of Tokyo",
]

TW_GRADE_A_PATTERN = re.compile(
    r"(台灣|臺灣|清華|交通|陽明交通|陽明|成功|政治|台灣科技|臺灣科技)大學|"
    r"(台|臺|清|交|成|政|台科|臺科|陽明交)大|"
    r"National Taiwan University|National Tsing Hua University|"
    r"National Chiao Tung University|National Yang Ming Chiao Tung University|"
    r"National Cheng Kung University|National Chengchi University|"
    r"National Taiwan University of Science and Technology|Taiwan Tech|"
    r"National Yang.Ming University|"
    r"NTU\b|NTHU|NCTU|NYCU|NCKU|NCCU|NTUST",
    re.IGNORECASE,
)

TW_GRADE_B_PATTERN = re.compile(
    r"(中央|中興|中正|中山|台北科技|臺北科技|台灣師範|臺灣師範)大學|"
    r"中(央|興|正|山)大|北科|師大",
    re.IGNORECASE,
)

# Major relevance patterns
TIER1_MAJOR = re.compile(
    r"資工|資訊工程|資管|資訊管理|電機|EECS|Computer Science|CS\b|"
    r"MIS|EE\b|AI|Artificial Intelligence|Data Science|資訊科學|"
    r"Machine Learning|軟體工程|Software Engineering|電信工程",
    re.IGNORECASE,
)
TIER2_MAJOR = re.compile(
    r"統計|數學|應數|數據|理學院|Math|Stat|Physics|物理|"
    r"應用數學|Applied Math|Operations Research|工業工程",
    re.IGNORECASE,
)

# Thesis/publication bonus keywords
THESIS_AI_KEYWORDS = re.compile(
    r"NLP|Natural Language|Computer Vision|CV|Deep Learning|"
    r"Transformer|BERT|GPT|LLM|Reinforcement Learning|"
    r"Neural Network|機器學習|深度學習|自然語言",
    re.IGNORECASE,
)
TOP_VENUE_KEYWORDS = re.compile(
    r"NeurIPS|NIPS|ICLR|ICML|CVPR|ICCV|ECCV|ACL|EMNLP|AAAI|IJCAI",
    re.IGNORECASE,
)

# Degree-level keywords for classification
_BACHELOR_KEYWORDS = ("大學", "學士", "四技", "二技", "bachelor", "b.s.", "b.a.", "undergraduate")
_MASTER_KEYWORDS = ("碩士", "碩", "master", "mba", "m.s.", "m.a.", "graduate")
_PHD_KEYWORDS = ("博士", "phd", "doctorate", "ph.d.")


def _school_points(school: str) -> tuple[str, float]:
    """Return (tier, points) for a school. A=10, B=3, C=0."""
    if any(kw.lower() in school.lower() for kw in US_GRADE_A):
        return "A", 10.0
    if TW_GRADE_A_PATTERN.search(school):
        return "A", 10.0
    if TW_GRADE_B_PATTERN.search(school):
        return "B", 3.0
    return "C", 0.0


def _major_points(department: str) -> tuple[str, float]:
    """Return (relevance_tier, points) for a major. Tier1=10, Tier2=3, Other=0."""
    if TIER1_MAJOR.search(department):
        return "Tier1", 10.0
    if TIER2_MAJOR.search(department):
        return "Tier2", 3.0
    return "Other", 0.0


def _degree_level(degree_str: str) -> str:
    """Classify degree string into phd/master/bachelor."""
    dl = degree_str.lower()
    if any(k in dl for k in _PHD_KEYWORDS):
        return "phd"
    if any(k in dl for k in _MASTER_KEYWORDS):
        return "master"
    return "bachelor"


def _score_one(ed: EducationExtract) -> EducationLevelDetail:
    """Score a single education entry, returning detail with points."""
    s_tier, s_pts = _school_points(ed.school)
    m_tier, m_pts = _major_points(ed.department)
    return EducationLevelDetail(
        school=ed.school,
        school_tier=s_tier,
        school_points=s_pts,
        major=ed.department,
        major_relevance=m_tier,
        major_points=m_pts,
        base_score=s_pts + m_pts,
    )


def score_education(
    education_list: list[EducationExtract],
    raw_markdown: str = "",
) -> EducationScoreDetail:
    """Score education using hybrid bachelor/master weighting.

    Approach from grade_calculator.py:
    - bachelor weight: 0.7, master weight: 0.3
    - Each degree: school (A=10/B=3/C=0) + major (T1=10/T2=3/Other=0) = max 20
    - Hybrid = bachelor_base * 0.7 + master_base * 0.3 (max 20)
    - PhD holders get master weight bumped (treated as master with higher weight)
    - Thesis bonus: +5 for AI keywords, +5 for top venue
    - Final normalized to 0-100: (hybrid + thesis_bonus) / 20 * 100
    """
    if not education_list:
        return EducationScoreDetail(score=0.0)

    # Separate entries by degree level, pick best of each
    bachelor_best: EducationLevelDetail | None = None
    master_best: EducationLevelDetail | None = None

    for ed in education_list:
        level = _degree_level(ed.degree_level)
        detail = _score_one(ed)

        if level == "bachelor":
            if bachelor_best is None or detail.base_score > bachelor_best.base_score:
                bachelor_best = detail
        else:
            # master and phd both go into the "master" slot (higher education)
            if master_best is None or detail.base_score > master_best.base_score:
                master_best = detail

    # Calculate hybrid weighted score
    b_score = bachelor_best.base_score if bachelor_best else 0.0
    m_score = master_best.base_score if master_best else 0.0

    if master_best:
        # Has graduate degree: bachelor * 0.7 + master * 0.3
        hybrid = b_score * 0.7 + m_score * 0.3
    else:
        # Only bachelor: full weight on bachelor
        hybrid = b_score * 0.7

    # Thesis bonus (check raw markdown)
    thesis_bonus = 0.0
    if raw_markdown:
        if THESIS_AI_KEYWORDS.search(raw_markdown):
            thesis_bonus += 1.0  # +1 point out of 20
        if TOP_VENUE_KEYWORDS.search(raw_markdown):
            thesis_bonus += 1.0  # +1 point out of 20

    # Normalize to 0-100 (max raw = 20 + 2 bonus)
    raw_total = hybrid + thesis_bonus
    score = min(raw_total / 20.0 * 100.0, 100.0)

    return EducationScoreDetail(
        bachelor=bachelor_best,
        master=master_best,
        thesis_bonus=round(thesis_bonus / 20.0 * 100.0, 1),
        score=round(score, 1),
    )
