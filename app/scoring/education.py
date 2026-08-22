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
    "University of California, San Diego", "University of California, Los Angeles",
    "University of California, Berkeley", "University of Illinois",
    "Johns Hopkins", "Northwestern University", "Duke University",
    "University of Chicago", "Brown University", "Dartmouth",
]

# Reputable international universities that are not top-tier CS programs.
# Prevents a legitimate overseas degree from scoring the same as an unranked one.
INTL_GRADE_C = [
    "University of Sydney", "University of Melbourne", "Monash",
    "University of Queensland", "University of New South Wales",
    "Arizona State University", "Boston University", "American University",
    "Pennsylvania State", "Michigan State", "Ohio State",
    "Texas A&M", "University of Manchester", "University of Leeds",
    "University of Birmingham", "University of Glasgow", "Auckland",
    "Osaka University", "Kyoto University", "Waseda", "Keio",
    "Yonsei", "Korea University", "Hong Kong", "Fudan", "Shanghai Jiao Tong",
    "Zhejiang University", "Nanjing University",
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

# Grade C: established national universities and well-regarded private ones.
# Without this tier ~60% of all education rows scored a flat 0, which erased
# any distinction between a national university and an unranked institution.
TW_GRADE_C_PATTERN = re.compile(
    r"(雲林科技|高雄科技|台北|臺北|海洋|東華|嘉義|彰化師範|高雄師範|"
    r"台南|臺南|宜蘭|聯合|屏東|金門|台東|臺東|虎尾科技|勤益科技|"
    r"雲科|高科|北大)大學|"
    r"(淡江|逢甲|輔仁|中原|元智|東吳|銘傳|世新|實踐|靜宜|大同|中國文化|"
    r"文化|長庚|東海|義守|中華|真理|龍華科技|明志科技|朝陽科技|南臺科技|"
    r"崑山科技|嶺東科技|樹德科技)大學|"
    r"National (Yunlin|Kaohsiung|Taipei|Ilan|Chiayi|Changhua|Pingtung|Taitung|"
    r"United|Quemoy|Dong Hwa|Taiwan Ocean)\b|"
    r"NTOU|NPUST|NFU|NYUST|NKUST|NTPU|Tamkang|Feng Chia|Fu Jen|Chung Yuan|"
    r"Yuan Ze|Soochow|Ming Chuan|Tunghai|Chang Gung",
    re.IGNORECASE,
)

# --- Named school roster -----------------------------------------------------
# The tier tables above are regexes, which cannot be listed, checked off or
# dragged in a UI.  This roster names the schools each built-in tier covers so
# the /scoring page can show them as editable groups.  It is presentation and a
# starting point for overrides — the regexes above remain the matcher, so a
# school missing from this list still scores correctly.
DEFAULT_SCHOOL_ROSTER: dict[str, list[str]] = {
    "A": [
        "國立台灣大學", "國立清華大學", "國立陽明交通大學", "國立交通大學",
        "國立成功大學", "國立政治大學", "國立台灣科技大學", "國立陽明大學",
    ],
    "B": [
        "國立中央大學", "國立中興大學", "國立中正大學", "國立中山大學",
        "國立台北科技大學", "國立台灣師範大學",
    ],
    "C": [
        "國立台灣海洋大學", "國立東華大學", "國立嘉義大學", "國立宜蘭大學",
        "國立聯合大學", "國立屏東大學", "國立台東大學", "國立高雄大學",
        "國立台北大學", "國立雲林科技大學", "國立高雄科技大學",
        "國立彰化師範大學", "國立高雄師範大學", "國立虎尾科技大學",
        "國立勤益科技大學", "國立屏東科技大學",
        "淡江大學", "逢甲大學", "輔仁大學", "中原大學", "元智大學", "東吳大學",
        "銘傳大學", "世新大學", "實踐大學", "靜宜大學", "大同大學",
        "中國文化大學", "長庚大學", "東海大學", "義守大學", "中華大學",
        "真理大學", "龍華科技大學", "明志科技大學", "朝陽科技大學",
        "南臺科技大學", "崑山科技大學", "嶺東科技大學", "樹德科技大學",
    ],
}


def default_school_roster() -> dict[str, list[str]]:
    """Built-in tier → school names, for the tuning UI.

    Overseas schools are appended from the same tables the matcher uses, so the
    roster cannot drift from the ranking it is meant to describe.
    """
    roster = {k: list(v) for k, v in DEFAULT_SCHOOL_ROSTER.items()}
    roster["A"] = roster["A"] + list(US_GRADE_A)
    roster["C"] = roster["C"] + list(INTL_GRADE_C)
    roster.setdefault("D", [])
    return roster


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

# --- Named major catalogue ---------------------------------------------------
# The TIER*_MAJOR regexes above cover the AI role only, and a job profile's
# tier1/tier2 major lists start empty — leaving an operator to recall and type
# every relevant department name. This catalogue groups the common Taiwanese
# university departments by field so the UI can offer them as one-click
# suggestions.  It is a picker vocabulary, not a matcher: a major absent here
# still scores through the profile's own lists / the regexes above.
MAJOR_CATALOGUE: dict[str, list[str]] = {
    "資訊": [
        "資訊工程", "資訊管理", "資訊科學", "軟體工程", "電機工程", "電子工程",
        "通訊工程", "電信工程", "人工智慧", "資料科學", "網路多媒體",
        "醫學資訊", "生物資訊", "資訊傳播",
    ],
    "理工": [
        "數學", "應用數學", "統計", "應用統計", "物理", "化學", "材料工程",
        "機械工程", "土木工程", "化學工程", "工業工程", "環境工程",
        "航空太空工程", "生物醫學工程", "光電工程", "能源工程",
    ],
    "商管": [
        "企業管理", "國際企業", "財務金融", "會計", "經濟", "統計與精算",
        "行銷", "行銷與流通管理", "風險管理與保險", "財政", "運輸管理",
        "科技管理", "人力資源管理", "資訊管理",
    ],
    "人文社會": [
        "中國文學", "外國語文", "英美語文", "日本語文", "應用外語",
        "歷史", "哲學", "社會學", "社會工作", "心理", "教育", "政治",
        "法律", "公共行政", "新聞", "廣告", "大眾傳播", "圖書資訊",
    ],
    "設計藝術": [
        "視覺傳達設計", "工業設計", "商業設計", "多媒體設計", "數位媒體設計",
        "建築", "室內設計", "美術", "音樂", "戲劇", "時尚設計",
    ],
    "醫護生農": [
        "醫學", "牙醫", "藥學", "護理", "公共衛生", "物理治療", "職能治療",
        "醫學檢驗", "食品科學", "營養", "生命科學", "生物科技",
        "農藝", "園藝", "獸醫", "動物科學",
    ],
}


def major_catalogue() -> dict[str, list[str]]:
    """Field → department names, for the profile editor's major picker."""
    return {k: list(v) for k, v in MAJOR_CATALOGUE.items()}


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


def _school_pts_map() -> dict[str, float]:
    from app.scoring.config import load
    return load()["education"]["school_points"]


def _major_pts_map() -> dict[str, float]:
    from app.scoring.config import load
    return load()["education"]["major_points"]


def _school_overrides() -> list[dict]:
    from app.scoring.config import load
    return load()["education"].get("school_overrides") or []


def _fold(s: str) -> str:
    """Normalise for override matching: NFKC, casefold, 臺→台.

    NFKC does not unify 臺 and 台, but Taiwanese institutions use them
    interchangeably (國立臺北大學 / 國立台北大學), so an operator typing either
    form must match both.
    """
    return _nfkc(s).replace("臺", "台").lower()


def school_tier(school: str) -> str:
    """The tier for a school name, ignoring any degree premium.

    Split out of _school_points so the hard filter can rate an institution
    without "S" (which _school_points returns for any PhD) leaking in.
    """
    school_n = _nfkc(school)
    low = school_n.lower()

    # Operator overrides win over the built-in patterns: they exist precisely
    # to correct a school the shipped tables get wrong. First match wins, so a
    # more specific entry can shadow a broader one placed after it.
    folded = _fold(school)
    for row in _school_overrides():
        pattern = _fold(str(row.get("pattern", ""))).strip()
        if pattern and pattern in folded:
            return str(row.get("tier", "D")).strip().upper() or "D"

    if any(kw.lower() in low for kw in US_GRADE_A):
        return "A"
    if TW_GRADE_A_PATTERN.search(school_n):
        return "A"
    if TW_GRADE_B_PATTERN.search(school_n):
        return "B"
    if TW_GRADE_C_PATTERN.search(school_n):
        return "C"
    if any(kw.lower() in low for kw in INTL_GRADE_C):
        return "C"
    # Catch-all for national/municipal universities not named above (e.g.
    # 國立高雄大學, 國立暨南國際大學, 臺北市立大學).  Enumerating every institution is
    # unmaintainable, and dropping them to 0 understates a real credential.
    if re.search(r"(國立|臺?北市立|市立).{0,8}大學|National .*University", school_n, re.IGNORECASE):
        return "C"
    return "D"


def _school_points(school: str, is_phd: bool = False) -> tuple[str, float]:
    """Return (tier, points) for a school. Points come from the tunable config."""
    pts = _school_pts_map()
    if is_phd:
        return "S", float(pts["S"])
    tier = school_tier(school)
    return tier, float(pts.get(tier, pts["D"]))


def _major_points(department: str, profile=None) -> tuple[str, float]:
    """Return (relevance_tier, points) for a major. Tier1=10, Tier2=3, Other=0.

    School tiers stay global — a top school is a top school for any job — but
    major relevance is role-dependent: 財金 is Tier1 for an analyst and Other
    for a firmware engineer.  A profile therefore replaces only this half.
    """
    dept_n = _nfkc(department)
    mp = _major_pts_map()
    if profile is not None:
        from app.scoring.generic import major_relevance_by_profile
        tier = major_relevance_by_profile(profile, dept_n)
        return tier, float(mp[tier])
    if TIER1_MAJOR.search(dept_n):
        return "Tier1", float(mp["Tier1"])
    if TIER2_MAJOR.search(dept_n):
        return "Tier2", float(mp["Tier2"])
    return "Other", float(mp["Other"])


def _degree_level(degree_str: str) -> str:
    """Classify degree string into phd/master/bachelor."""
    dl = _nfkc(degree_str).lower()
    if any(k in dl for k in _PHD_KEYWORDS):
        return "phd"
    if any(k in dl for k in _MASTER_KEYWORDS):
        return "master"
    return "bachelor"


def _score_one(ed: EducationExtract, profile=None) -> tuple[EducationLevelDetail, str]:
    """Score a single education entry, returning (detail, degree_level)."""
    level = _degree_level(ed.degree_level)
    is_phd = (level == "phd")
    s_tier, s_pts = _school_points(ed.school, is_phd=is_phd)
    m_tier, m_pts = _major_points(ed.department, profile)
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
    profile=None,
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
        detail, level = _score_one(ed, profile)

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
                m_tier, m_pts = _major_points(ed.department, profile)
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

    from app.scoring.config import load
    _edu = load()["education"]
    if master_best:
        hybrid = b_score * float(_edu["bachelor_weight"]) + m_score * float(_edu["master_weight"])
    else:
        hybrid = b_score * float(_edu["bachelor_only_weight"])

    # Normalize base to 0–95 using denominator=24 to spread discrimination.
    # Tier A school + Tier1 major (base=20) with full master: 20/24*100 ≈ 83.3
    # Tier S (PhD, base=25) + Tier1 major with bachelor: (25*0.3+20*0.7)/24*100 ≈ 89.6
    base_score_100 = min(hybrid / float(_edu["denominator"]) * 100.0, float(_edu["base_cap"]))

    # Thesis bonus: fully decoupled from cap.
    # +2.5 pts for AI-related thesis/publications, +2.5 pts for top-venue acceptance.
    thesis_bonus_pts = 0.0
    if raw_markdown:
        if THESIS_AI_KEYWORDS.search(raw_markdown):
            thesis_bonus_pts += float(_edu["thesis_ai_bonus"])
        if TOP_VENUE_KEYWORDS.search(raw_markdown):
            thesis_bonus_pts += float(_edu["thesis_venue_bonus"])

    score = min(base_score_100 + thesis_bonus_pts, 100.0)

    return EducationScoreDetail(
        bachelor=bachelor_best,
        master=master_best,
        thesis_bonus=round(thesis_bonus_pts, 1),
        score=round(score, 1),
    )
