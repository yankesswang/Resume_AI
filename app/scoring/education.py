"""Education scoring module.

Hybrid scoring based on grade_calculator approach:
- School: S(PhD)=15, A=10, B=3, C=0
- Major:  Tier1=10, Tier2=3, Other=0
- Base score per degree = school + major (max 25 for Tier S)
- Weighted: bachelor * 0.7 + master * 0.3 (or bachelor * 0.9 if no master)
- Thesis bonus: +2.5 for AI keywords, +2.5 for top venue (max +5, outside cap)
- Normalized to 0-100 scale (denominator=24), base capped at 95
"""

from __future__ import annotations

import re
import unicodedata

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
    r"NeurIPS|NIPS|ICLR|ICML|CVPR|ICCV|ECCV|ACL|EMNLP|AAAI|IJCAI|"
    r"ICASSP|INTERSPEECH|ASRU|SLT|SIGKDD|KDD|RecSys|WSDM|CIKM|COLING|NAACL",
    re.IGNORECASE,
)

# Degree-level keywords for classification
_BACHELOR_KEYWORDS = ("大學", "學士", "四技", "二技", "bachelor", "b.s.", "b.a.", "undergraduate")
_MASTER_KEYWORDS = ("碩士", "碩", "master", "mba", "m.s.", "m.a.", "graduate")
_PHD_KEYWORDS = ("博士", "phd", "doctorate", "ph.d.")


def _nfkc(s: str) -> str:
    """Normalize CJK compatibility variants (e.g. ⼤ U+2F23 → 大 U+5927)."""
    return unicodedata.normalize("NFKC", s)


def _school_points(school: str, is_phd: bool = False) -> tuple[str, float]:
    """Return (tier, points) for a school. S(PhD)=15, A=10, B=3, C=0."""
    if is_phd:
        return "S", 15.0
    school_n = _nfkc(school)
    if any(kw.lower() in school_n.lower() for kw in US_GRADE_A):
        return "A", 10.0
    if TW_GRADE_A_PATTERN.search(school_n):
        return "A", 10.0
    if TW_GRADE_B_PATTERN.search(school_n):
        return "B", 3.0
    return "C", 0.0


def _major_points(department: str) -> tuple[str, float]:
    """Return (relevance_tier, points) for a major. Tier1=10, Tier2=3, Other=0."""
    dept_n = _nfkc(department)
    if TIER1_MAJOR.search(dept_n):
        return "Tier1", 10.0
    if TIER2_MAJOR.search(dept_n):
        return "Tier2", 3.0
    return "Other", 0.0


def _degree_level(degree_str: str) -> str:
    """Classify degree string into phd/master/bachelor."""
    dl = _nfkc(degree_str).lower()
    if any(k in dl for k in _PHD_KEYWORDS):
        return "phd"
    if any(k in dl for k in _MASTER_KEYWORDS):
        return "master"
    return "bachelor"


def _score_one(ed: EducationExtract) -> tuple[EducationLevelDetail, str]:
    """Score a single education entry, returning (detail, degree_level)."""
    level = _degree_level(ed.degree_level)
    is_phd = (level == "phd")
    s_tier, s_pts = _school_points(ed.school, is_phd=is_phd)
    m_tier, m_pts = _major_points(ed.department)
    detail = EducationLevelDetail(
        school=ed.school,
        school_tier=s_tier,
        school_points=s_pts,
        major=ed.department,
        major_relevance=m_tier,
        major_points=m_pts,
        base_score=s_pts + m_pts,
    )
    return detail, level


def score_education(
    education_list: list[EducationExtract],
    raw_markdown: str = "",
) -> EducationScoreDetail:
    """Score education using hybrid bachelor/master weighting.

    v2 optimizations:
    - PhD degree → Tier S school points (15 vs Tier A's 10), surfaces PhD premium
    - Bachelor-only: hybrid = b_score * 0.9 (was 0.7), keeps reasonable floor
    - Denominator raised 20 → 24: Tier A+Tier1 master now scores ~83 (not 100)
      so only top-tier academics with publications can reach 95–100
    - Thesis bonus decoupled from cap: base capped at 95, thesis adds up to 5 pts
      (+2.5 for AI keywords, +2.5 for top-venue publication)
    """
    if not education_list:
        return EducationScoreDetail(score=0.0)

    bachelor_best: EducationLevelDetail | None = None
    master_best: EducationLevelDetail | None = None

    _MASTER_IN_MAJOR = re.compile(r"碩士班|研究所|碩士", re.IGNORECASE)

    for ed in education_list:
        detail, level = _score_one(ed)

        if level == "bachelor":
            if bachelor_best is None or detail.base_score > bachelor_best.base_score:
                bachelor_best = detail
            # Detect "碩士班" / "研究所" embedded in the major field.
            # This happens when the parser stores a dual/sequential degree as one
            # entry (e.g. "資訊管理學系、電信工程學系碩士班").  Treat the same school
            # as an implicit master's degree so the candidate isn't penalised.
            if _MASTER_IN_MAJOR.search(ed.department):
                # Re-score as non-PhD master (is_phd=False) for the implicit slot
                s_tier, s_pts = _school_points(ed.school, is_phd=False)
                m_tier, m_pts = _major_points(ed.department)
                implicit_master = EducationLevelDetail(
                    school=ed.school,
                    school_tier=s_tier,
                    school_points=s_pts,
                    major=ed.department,
                    major_relevance=m_tier,
                    major_points=m_pts,
                    base_score=s_pts + m_pts,
                )
                if master_best is None or implicit_master.base_score > master_best.base_score:
                    master_best = implicit_master
        else:
            # master and phd both go into the "master" slot (higher education)
            if master_best is None or detail.base_score > master_best.base_score:
                master_best = detail

    b_score = bachelor_best.base_score if bachelor_best else 0.0
    m_score = master_best.base_score if master_best else 0.0

    if master_best:
        # Has graduate degree: bachelor * 0.7 + master * 0.3
        hybrid = b_score * 0.7 + m_score * 0.3
    else:
        # Bachelor-only: 0.9× preserves most weight, small premium for having a master
        hybrid = b_score * 0.9

    # Normalize base to 0–95 using denominator=24 to spread discrimination.
    # Tier A school + Tier1 major (base=20) with full master: 20/24*100 ≈ 83.3
    # Tier S (PhD, base=25) + Tier1 major with bachelor: (25*0.3+20*0.7)/24*100 ≈ 89.6
    base_score_100 = min(hybrid / 24.0 * 100.0, 95.0)

    # Thesis bonus: fully decoupled from cap.
    # +2.5 pts for AI-related thesis/publications, +2.5 pts for top-venue acceptance.
    thesis_bonus_pts = 0.0
    if raw_markdown:
        if THESIS_AI_KEYWORDS.search(raw_markdown):
            thesis_bonus_pts += 2.5
        if TOP_VENUE_KEYWORDS.search(raw_markdown):
            thesis_bonus_pts += 2.5

    score = min(base_score_100 + thesis_bonus_pts, 100.0)

    return EducationScoreDetail(
        bachelor=bachelor_best,
        master=master_best,
        thesis_bonus=round(thesis_bonus_pts, 1),
        score=round(score, 1),
    )
