"""Tests for profile-driven, domain-agnostic scoring.

Run: python3 tests/test_domain_profiles.py

The point of these tests is that the same engine screens an accountant, a
salesperson and an AI engineer, and that the built-in AI path is left exactly
as it was.
"""

from __future__ import annotations

import copy
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.scoring.builtin_profiles import ai_engineer_profile
from app.scoring.domain_profile import (
    MIN_TIER_KEYWORDS,
    DomainProfile,
    parse_profile,
    validate_profile,
)
from app.scoring.generic import (
    classify_tier_by_profile,
    keyword_floor_by_profile,
    major_relevance_by_profile,
    score_competencies,
    verify_skills_by_profile,
)
from app.scoring.pipeline import run_full_scoring
from app.scoring.hard_filter import apply_hard_filters, normalise_degree
from app.scoring.profile_builder import _repair
from app.models import EducationExtract

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


# --- Fixtures ---------------------------------------------------------------

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# The sales standard is loaded from a fixture rather than inlined, so the file
# the tests assert against is the same one a human can open, upload through the
# UI, and eyeball. Keeping a second copy in Python drifts from the first.
SALES_PROFILE = json.loads(
    (FIXTURES / "profiles" / "sales.json").read_text(encoding="utf-8")
)


SENIOR_SALES = {
    "name": "資深業務", "skill_tags": ["通路開發", "議價"],
    "work_experiences": [{
        "job_title": "業務經理",
        "job_description": "帶領業務團隊 8 人，負責全國經銷商通路策略與 KA 關鍵客戶經營，"
                           "年度業績目標達成率 118%，毛利提升 12%",
        "job_skills": "通路開發,議價,合約談判",
    }],
    "education": [{"school": "淡江大學", "department": "企業管理學系", "degree_level": "學士"}],
    "raw_markdown": "業務經理 帶領業務團隊 通路策略 KA 關鍵客戶 年度合約談判 毛利管理",
}

JUNIOR_SALES = {
    "name": "初階業務", "skill_tags": ["銷售"],
    "work_experiences": [{
        "job_title": "門市人員", "job_description": "門市銷售與接單，負責報價",
        "job_skills": "銷售",
    }],
    "education": [{"school": "某科技大學", "department": "應用外語系", "degree_level": "學士"}],
    "raw_markdown": "門市銷售 報價 客戶服務",
}

AI_ENGINEER = {
    "name": "AI工程師", "skill_tags": ["PyTorch", "CUDA"],
    "work_experiences": [{
        "job_title": "AI工程師", "job_description": "LoRA 微調與 vLLM 推論優化",
        "job_skills": "PyTorch,CUDA",
    }],
    "education": [{"school": "台大", "department": "資訊工程學系", "degree_level": "碩士"}],
    "raw_markdown": "LoRA 微調 vLLM CUDA 推論優化",
}


def _sales_job():
    return {
        "basic_conditions": {"job_title": "通路業務經理"},
        "job_summary": "負責經銷通路開發",
        "domain_profile": copy.deepcopy(SALES_PROFILE),
    }


# --- Tests ------------------------------------------------------------------

def test_builtin_profile_valid():
    print("\n=== Builtin AI Profile ===")
    p = ai_engineer_profile()
    check("Builtin profile validates", validate_profile(p) == [], f"{validate_profile(p)}")
    check("Has all four tiers", sorted(t.level for t in p.tiers) == [0, 1, 2, 3])
    check("Tier 3 label preserved", p.tier_label(3) == "AI Expert")
    check("Tier 0 label preserved", p.tier_label(0) == "Non-AI")
    comps = p.normalised_competencies()
    check("Competency weights normalise to 1.0",
          abs(sum(c.weight for c in comps) - 1.0) < 1e-9)
    check("Fingerprint is stable", p.fingerprint() == ai_engineer_profile().fingerprint())
    # Editing the standard must change the fingerprint, or stale cached tiers
    # from the previous standard would silently survive.
    p2 = ai_engineer_profile()
    p2.tier_keywords["3"]["NewSignal"] = 2.0
    check("Fingerprint changes when keywords change", p2.fingerprint() != p.fingerprint())


def test_validation_rejects_unusable():
    print("\n=== Profile Validation ===")
    base = copy.deepcopy(SALES_PROFILE)
    check("Good profile passes", validate_profile(DomainProfile.model_validate(base)) == [])

    missing_tier = copy.deepcopy(base)
    missing_tier["tiers"] = missing_tier["tiers"][:3]
    errs = validate_profile(DomainProfile.model_validate(missing_tier))
    check("Missing a tier is rejected", any("0-3" in e for e in errs), f"{errs}")

    # The important one: a profile that "has keywords" but far too few looks
    # configured while matching nothing in a real resume.
    thin = copy.deepcopy(base)
    thin["tier_keywords"]["2"] = {"議價": 1.5}
    errs = validate_profile(DomainProfile.model_validate(thin))
    check(f"Fewer than {MIN_TIER_KEYWORDS} keywords is rejected",
          any("關鍵字" in e for e in errs), f"{errs}")

    weak_t3 = copy.deepcopy(base)
    weak_t3["tier_keywords"]["3"] = {f"k{i}": 0.5 for i in range(8)}
    errs = validate_profile(DomainProfile.model_validate(weak_t3))
    check("Unreachable tier 3 is rejected", any("Tier 3" in e for e in errs), f"{errs}")

    bad_w = copy.deepcopy(base)
    bad_w["weights"] = {"experience": 0.5, "engineering": 0.2, "semantic": 0.2,
                        "education": 0.2, "skills": 0.1}
    errs = validate_profile(DomainProfile.model_validate(bad_w))
    check("Weights not summing to 1.0 rejected", any("1.0" in e for e in errs), f"{errs}")

    empty_axis = copy.deepcopy(base)
    empty_axis["competencies"][0]["levels"] = {}
    errs = validate_profile(DomainProfile.model_validate(empty_axis))
    check("Competency with no keywords rejected", any("能力面向" in e for e in errs), f"{errs}")


def test_tier_classification():
    print("\n=== Domain Tier Classification ===")
    p = DomainProfile.model_validate(SALES_PROFILE)

    senior = classify_tier_by_profile(
        p, SENIOR_SALES["work_experiences"], SENIOR_SALES["skill_tags"],
        SENIOR_SALES["raw_markdown"],
    )
    check("Senior sales reaches tier 3", senior.tier == 3, f"got {senior.tier}")
    check("Senior tier label from profile", senior.tier_label == "業務主管")

    junior = classify_tier_by_profile(
        p, JUNIOR_SALES["work_experiences"], JUNIOR_SALES["skill_tags"],
        JUNIOR_SALES["raw_markdown"],
    )
    check("Junior sales lands at tier 1", junior.tier == 1, f"got {junior.tier}")
    check("Senior outranks junior", senior.score > junior.score,
          f"{senior.score} vs {junior.score}")

    # An AI engineer has no sales vocabulary at all.
    off = classify_tier_by_profile(
        p, AI_ENGINEER["work_experiences"], AI_ENGINEER["skill_tags"],
        AI_ENGINEER["raw_markdown"],
    )
    check("Off-domain candidate lands at tier 0", off.tier == 0, f"got {off.tier}")

    empty = classify_tier_by_profile(p, [], [], "")
    check("Empty resume is tier 0", empty.tier == 0)

    # Tag stuffing must not buy a tier the work history does not support.
    stuffed = classify_tier_by_profile(
        p, [], ["KA", "通路策略", "帶領業務團隊", "關鍵客戶"], "",
    )
    tagged_score = stuffed.score
    evidenced = classify_tier_by_profile(
        p, [{"job_description": "KA 通路策略 帶領業務團隊 關鍵客戶"}], [], "",
    )
    check("Tag-only evidence scores below real work history",
          tagged_score < evidenced.score, f"{tagged_score} vs {evidenced.score}")


def test_keyword_floor():
    print("\n=== Keyword Floor ===")
    p = DomainProfile.model_validate(SALES_PROFILE)
    check("Two strong tier-3 signals raise the floor to 3",
          keyword_floor_by_profile(p, "通路策略 帶領業務團隊") == 3)
    check("One strong signal is not enough",
          keyword_floor_by_profile(p, "通路策略") != 3)
    check("Two tier-2 signals raise the floor to 2",
          keyword_floor_by_profile(p, "業績目標 通路開發") == 2)
    check("Empty evidence gives no floor", keyword_floor_by_profile(p, "") == 0)


def test_competencies():
    print("\n=== Competency Matrix ===")
    p = DomainProfile.model_validate(SALES_PROFILE)
    detail, axes = score_competencies(
        p, SENIOR_SALES["work_experiences"], SENIOR_SALES["skill_tags"],
        SENIOR_SALES["raw_markdown"],
    )
    check("Returns one entry per competency", len(axes) == 3, f"got {len(axes)}")
    check("Axis labels come from the profile",
          [a["label"] for a in axes] == ["通路開發", "客戶經營", "議價談判"])
    by_key = {a["key"]: a for a in axes}
    check("Channel axis reaches level 3", by_key["channel"]["level"] == 3,
          f"got {by_key['channel']['level']}")
    check("m_eng is within the configured cap", 0 < detail.m_eng <= 0.7,
          f"got {detail.m_eng}")
    # Legacy field mirroring keeps every existing consumer working.
    check("First axis mirrors onto backend_level",
          detail.backend_level == by_key["channel"]["level"])

    nothing, axes0 = score_competencies(p, [], [], "")
    check("No evidence gives m_eng 0", nothing.m_eng == 0.0)
    check("Axes still enumerated with level 0",
          len(axes0) == 3 and all(a["level"] == 0 for a in axes0))


def test_skills_and_education():
    print("\n=== Skills & Education ===")
    p = DomainProfile.model_validate(SALES_PROFILE)
    sv = verify_skills_by_profile(
        p, SENIOR_SALES["skill_tags"], SENIOR_SALES["work_experiences"],
        SENIOR_SALES["raw_markdown"],
    )
    check("Ecosystem picked from the profile", sv.skill_ecosystem == "B2B 通路",
          f"got {sv.skill_ecosystem}")
    retail = verify_skills_by_profile(
        p, JUNIOR_SALES["skill_tags"], JUNIOR_SALES["work_experiences"],
        JUNIOR_SALES["raw_markdown"],
    )
    check("Retail resume maps to the B2C ecosystem",
          retail.skill_ecosystem == "B2C 零售", f"got {retail.skill_ecosystem}")
    none = verify_skills_by_profile(p, [], [], "")
    check("No evidence falls back to the keyword-less bucket",
          none.skill_ecosystem == "一般", f"got {none.skill_ecosystem}")

    # Chinese majors are written both in full and abbreviated, and neither form
    # contains the other as a substring, so matching must handle both directions.
    check("企管 is Tier1 for sales", major_relevance_by_profile(p, "企業管理學系") == "Tier1")
    check("Abbreviated resume major matches full listing",
          major_relevance_by_profile(p, "企管系") == "Tier1")
    check("國貿 matches 國際貿易學系",
          major_relevance_by_profile(p, "國際貿易學系") == "Tier1")
    check("Unrelated major with shared characters is not matched",
          major_relevance_by_profile(p, "管理資訊系統研究所") == "Other")
    check("Blank major does not match everything",
          major_relevance_by_profile(p, "   ") == "Other")
    check("經濟 is Tier2 for sales", major_relevance_by_profile(p, "經濟學系") == "Tier2")
    check("資工 is Other for sales", major_relevance_by_profile(p, "資訊工程學系") == "Other")
    check("Empty major is Other", major_relevance_by_profile(p, "") == "Other")


def test_pipeline_with_profile():
    print("\n=== Pipeline with a Domain Profile ===")
    job = _sales_job()

    senior = run_full_scoring(SENIOR_SALES, job)
    junior = run_full_scoring(JUNIOR_SALES, job)
    off = run_full_scoring(AI_ENGINEER, job)

    check("Senior passes the hard filter", senior.passed_hard_filter)
    check("Senior ranks above junior", senior.overall_score > junior.overall_score,
          f"{senior.overall_score} vs {junior.overall_score}")
    check("AI engineer fails the sales hard filter", not off.passed_hard_filter)
    check("Rejection lists a reason", len(off.hard_filter_failures) > 0)
    check("Rejected candidate is tier 0, not tier 1",
          off.experience_detail.tier == 0, f"got {off.experience_detail.tier}")

    check("Result carries the profile identity",
          senior.profile_name == "通路業務經理", f"got {senior.profile_name!r}")
    check("Result carries the competency axes", len(senior.competency_axes) == 3)
    check("Analysis text names the domain", "業務開發" in senior.analysis_text)
    check("Analysis text uses profile tier labels",
          "業務主管" in senior.analysis_text, senior.analysis_text[:200])
    check("Tags use profile labels, not AI ones",
          not any("RAG" in t or "AI-Expert" in t for t in senior.tags), f"{senior.tags}")

    # Per-role weights must actually drive the score AND the displayed breakdown.
    check("Profile weights appear in the breakdown",
          "領域深度" in senior.analysis_text or "業務開發深度" in senior.analysis_text,
          senior.analysis_text[:300])


def test_education_matters_flag():
    print("\n=== education.matters ===")
    # A role that does not screen on degrees must REDISTRIBUTE the education
    # weight, not zero the education score. Zeroing the score still consumes
    # the weight, dragging every candidate down by the same amount — which is
    # a constant penalty, not "this dimension is ignored".
    cand = {
        "name": "業務", "skill_tags": ["通路開發"],
        "work_experiences": [{"job_title": "業務",
                              "job_description": "通路開發 議價 經銷商 業績目標"}],
        "education": [{"school": "台大", "department": "企管系", "degree_level": "碩士"}],
        "raw_markdown": "通路開發 議價 經銷商 業績目標 客戶",
    }
    scores = {}
    for matters in (True, False):
        prof = copy.deepcopy(SALES_PROFILE)
        prof["education"]["matters"] = matters
        job = {"basic_conditions": {"job_title": "X"}, "job_summary": "y",
               "domain_profile": prof}
        r = run_full_scoring(copy.deepcopy(cand), job)
        scores[matters] = r
    check("matters=False changes the score",
          scores[True].overall_score != scores[False].overall_score,
          f"{scores[True].overall_score} vs {scores[False].overall_score}")
    check("Education sub-score itself is still computed",
          scores[False].education_detail.score > 0)
    check("Breakdown says the role ignores education",
          "不採計學歷" in scores[False].analysis_text)
    check("Breakdown shows education when it matters",
          "教育背景 (" in scores[True].analysis_text)

    # Weight-only profile: education is the sole weighted dimension. Zeroing it
    # would give literally everybody 0, so the weight is handed back instead.
    edge = copy.deepcopy(SALES_PROFILE)
    edge["education"]["matters"] = False
    edge["weights"] = {"experience": 0.0, "engineering": 0.0, "semantic": 0.0,
                       "education": 1.0, "skills": 0.0}
    job = {"basic_conditions": {"job_title": "X"}, "domain_profile": edge}
    r = run_full_scoring(copy.deepcopy(cand), job)
    check("Education-only profile does not collapse to zero", r.overall_score > 0,
          f"got {r.overall_score}")


def test_builtin_path_unchanged():
    print("\n=== Builtin AI Path Untouched ===")
    job = json.loads(
        (Path(__file__).resolve().parent.parent / "job_requirement.json").read_text(
            encoding="utf-8"
        )
    )
    check("No domain_profile key in the bundled job", "domain_profile" not in job)

    r = run_full_scoring(AI_ENGINEER, job)
    check("AI candidate scores through the legacy path", r.profile_id == "",
          f"got {r.profile_id!r}")
    check("Legacy path produces no competency axes", r.competency_axes == [])
    check("Legacy tier labels preserved",
          r.experience_detail.tier_label in
          {"Non-AI", "Wrapper", "RAG Architect", "AI Expert"},
          f"got {r.experience_detail.tier_label}")
    check("Legacy analysis mentions engineering maturity",
          "工程成熟度" in r.analysis_text)


def test_repair_of_llm_output():
    print("\n=== LLM Output Repair ===")
    # Placeholder echo: the model copies the prompt's filler instead of writing
    # real domain terms. This validates but screens blind, so it must be dropped.
    raw = {
        "tiers": [{"level": 1, "label": "x", "definition": "d"}],
        "tier_keywords": {
            "3": {"關鍵字": 2.0, "<實際的專家級關鍵字>": 2.0, "IFRS": 2.0, "K": 1.0},
            "2": ["合併報表", "稅務簽證"],
        },
        "competencies": [{"label": "帳務處理", "weight": "0.5",
                          "levels": {"1": "總帳", "2": ["合併報表"], "9": ["ignored"]}}],
        "weights": {"experience": "0.4", "engineering": 0.2, "semantic": 0.2,
                    "education": 0.1, "skills": 0.1},
        "hard_filters": {"must_have_groups": [
            {"name": "空組", "skills": [], "min_matches": 1},
            {"name": "過嚴", "skills": ["A", "B"], "min_matches": 5},
        ]},
    }
    out = _repair(raw, {})

    check("All four tiers are filled in", [t["level"] for t in out["tiers"]] == [0, 1, 2, 3])
    t3 = out["tier_keywords"]["3"]
    check("Placeholder '關鍵字' dropped", "關鍵字" not in t3, f"{t3}")
    check("Bracketed placeholder dropped", "<實際的專家級關鍵字>" not in t3, f"{t3}")
    check("Single-character keyword dropped", "K" not in t3, f"{t3}")
    check("Real keyword kept", "IFRS" in t3, f"{t3}")
    check("Keyword list coerced to a weight map",
          isinstance(out["tier_keywords"]["2"], dict)
          and out["tier_keywords"]["2"].get("合併報表", 0) > 0)

    c = out["competencies"][0]
    check("Missing competency key is derived", bool(c["key"]), f"{c}")
    check("String weight coerced to float", c["weight"] == 0.5, f"{c['weight']}")
    check("String level coerced to a list", c["levels"]["1"] == ["總帳"], f"{c['levels']}")
    check("Out-of-range level dropped", "9" not in c["levels"])

    check("Weights renormalise to exactly 1.0",
          abs(sum(out["weights"].values()) - 1.0) < 1e-9, f"{out['weights']}")

    groups = out["hard_filters"]["must_have_groups"]
    check("Empty filter group dropped", all(g["skills"] for g in groups))
    check("min_matches clamped to the group size",
          all(g["min_matches"] <= len(g["skills"]) for g in groups), f"{groups}")


def test_parse_profile_tolerance():
    print("\n=== Stored Profile Parsing ===")
    check("None is tolerated", parse_profile(None) is None)
    check("Empty string is tolerated", parse_profile("") is None)
    check("Malformed JSON is tolerated", parse_profile("{not json") is None)
    check("Wrong type is tolerated", parse_profile("[1,2,3]") is None)
    check("JSON string round-trips",
          parse_profile(json.dumps(SALES_PROFILE)).domain == "業務開發")
    check("Dict round-trips", parse_profile(SALES_PROFILE).domain == "業務開發")
    # A profile from before schema_version existed must still load.
    old = copy.deepcopy(SALES_PROFILE)
    old.pop("schema_version", None)
    check("Versionless profile migrates", parse_profile(old) is not None)


def test_min_education_filter():
    """The degree gate reads parsed education rows, not the resume text."""
    print("\n=== Hard filter: minimum degree ===")

    def edu(department: str, degree: str = ""):
        return [EducationExtract(school="台大", department=department, degree_level=degree)]

    passed, _ = apply_hard_filters(
        [], [], "", {"min_education": "master"}, education=edu("資工", "碩士"))
    check("碩士 passes a 碩士 gate", passed)

    passed, failures = apply_hard_filters(
        [], [], "", {"min_education": "master"}, education=edu("資工", "學士"))
    check("學士 fails a 碩士 gate", not passed)
    check("Failure names the shortfall", any("碩士" in f for f in failures), f"got {failures}")

    # A floor, not an exact match: a higher degree must still pass.
    passed, _ = apply_hard_filters(
        [], [], "", {"min_education": "master"}, education=edu("資工", "博士"))
    check("博士 passes a 碩士 gate", passed)

    # The parser often leaves degree_level blank and puts 碩士班 in the major.
    passed, _ = apply_hard_filters(
        [], [], "", {"min_education": "master"}, education=edu("資訊工程學系碩士班"))
    check("碩士班 in department counts", passed)

    # Text mentioning a degree must not satisfy the gate: "碩士" in a resume is
    # usually a job requirement being quoted, not the applicant's own degree.
    passed, _ = apply_hard_filters(
        [], [], "碩士以上學歷佳", {"min_education": "master"}, education=edu("資工", "學士"))
    check("Resume text does not satisfy the gate", not passed)

    passed, _ = apply_hard_filters([], [], "", {"min_education": "master"}, education=[])
    check("No education data fails the gate", not passed)

    # An unreadable value must not screen blind — it gates on nothing instead.
    passed, _ = apply_hard_filters(
        [], [], "", {"min_education": "???"}, education=edu("資工", "學士"))
    check("Unrecognised gate value rejects nobody", passed)

    passed, _ = apply_hard_filters([], [], "", {}, education=edu("資工", "學士"))
    check("No gate configured rejects nobody", passed)

    check("normalise_degree reads 碩士以上", normalise_degree("碩士以上") == "master")
    check("normalise_degree reads English", normalise_degree("Master") == "master")
    check("normalise_degree rejects noise", normalise_degree("???") is None)

    # End to end: the pipeline must feed education into the filter.
    candidate = {
        "name": "學士候選人",
        "education": [{"school": "台大", "department": "資工", "degree_level": "學士"}],
        "work_experiences": [],
        "skill_tags": ["Python"],
        "raw_markdown": "Python 工程師",
    }
    result = run_full_scoring(candidate, {"hard_filters": {"min_education": "master"}})
    check("Pipeline applies the degree gate", not result.passed_hard_filter)
    result = run_full_scoring(candidate, {"hard_filters": {"min_education": "bachelor"}})
    check("Pipeline passes a met gate", result.passed_hard_filter)


def test_min_school_filter():
    """The school gate rates the institution, not the degree."""
    print("\n=== Hard filter: minimum school ===")

    def edu(school: str, degree: str = "學士"):
        return [EducationExtract(school=school, department="資工", degree_level=degree)]

    passed, _ = apply_hard_filters(
        [], [], "", {"min_school_tier": "A"}, education=edu("國立台灣大學"))
    check("台大 passes an A gate", passed)

    passed, failures = apply_hard_filters(
        [], [], "", {"min_school_tier": "A"}, education=edu("國立中央大學"))
    check("中央 fails an A gate", not passed)
    check("Failure names the shortfall", any("學校未達" in f for f in failures), f"got {failures}")

    passed, _ = apply_hard_filters(
        [], [], "", {"min_school_tier": "B"}, education=edu("國立中央大學"))
    check("中央 passes a B gate", passed)

    passed, _ = apply_hard_filters(
        [], [], "", {"min_school_tier": "B"}, education=edu("淡江大學"))
    check("淡江 fails a B gate", not passed)

    passed, _ = apply_hard_filters(
        [], [], "", {"min_school_tier": "C"}, education=edu("淡江大學"))
    check("淡江 passes a C gate", passed)

    passed, _ = apply_hard_filters(
        [], [], "", {"min_school_tier": "A"}, education=edu("Stanford University"))
    check("Overseas top school passes an A gate", passed)

    # The best row counts, not the last: a master's at a lesser school must not
    # erase a bachelor's from a top one.
    both = [
        EducationExtract(school="國立台灣大學", department="資工", degree_level="學士"),
        EducationExtract(school="某技術學院", department="資工", degree_level="碩士"),
    ]
    passed, _ = apply_hard_filters([], [], "", {"min_school_tier": "A"}, education=both)
    check("Best school across rows counts", passed)

    # A PhD promotes school points to "S" in the scorer; that is a degree
    # premium and must not clear a top-school gate.
    passed, _ = apply_hard_filters(
        [], [], "", {"min_school_tier": "A"}, education=edu("某技術學院", "博士"))
    check("PhD at a weak school fails an A gate", not passed)

    passed, _ = apply_hard_filters([], [], "", {"min_school_tier": "A"}, education=[])
    check("No school data fails the gate", not passed)

    # D accepts everyone, so it is stored as "no gate" rather than a filter.
    passed, _ = apply_hard_filters(
        [], [], "", {"min_school_tier": "D"}, education=edu("某技術學院"))
    check("D tier rejects nobody", passed)

    passed, _ = apply_hard_filters(
        [], [], "", {"min_school_tier": "???"}, education=edu("某技術學院"))
    check("Unrecognised tier rejects nobody", passed)

    # Text mentioning a school must not satisfy the gate.
    passed, _ = apply_hard_filters(
        [], [], "曾與台灣大學合作專案", {"min_school_tier": "A"}, education=edu("某技術學院"))
    check("Resume text does not satisfy the gate", not passed)

    check("_repair keeps a valid tier",
          _repair({"hard_filters": {"min_school_tier": "b"}}, {})["hard_filters"]["min_school_tier"] == "B")
    check("_repair drops tier D",
          _repair({"hard_filters": {"min_school_tier": "D"}}, {})["hard_filters"]["min_school_tier"] == "")

    # End to end through the pipeline.
    candidate = {
        "name": "一般大學候選人",
        "education": [{"school": "淡江大學", "department": "資工", "degree_level": "學士"}],
        "work_experiences": [],
        "skill_tags": ["Python"],
        "raw_markdown": "Python 工程師",
    }
    result = run_full_scoring(candidate, {"hard_filters": {"min_school_tier": "A"}})
    check("Pipeline applies the school gate", not result.passed_hard_filter)
    result = run_full_scoring(candidate, {"hard_filters": {"min_school_tier": "C"}})
    check("Pipeline passes a met school gate", result.passed_hard_filter)


def test_school_tier_overrides():
    """Operators can re-rank any school without a code change."""
    print("\n=== School tier overrides ===")

    import app.scoring.config as cfgmod
    from app.scoring.education import school_tier

    original = cfgmod._cache
    try:
        # Baseline: the shipped tables.
        cfgmod._cache = copy.deepcopy(cfgmod.DEFAULTS)
        check("台大 defaults to A", school_tier("國立台灣大學") == "A")
        check("淡江 defaults to C", school_tier("淡江大學") == "C")

        cfg = copy.deepcopy(cfgmod.DEFAULTS)
        cfg["education"]["school_overrides"] = [
            {"pattern": "淡江", "tier": "A"},
            {"pattern": "國立台灣大學", "tier": "C"},
        ]
        cfgmod._cache = cfg
        check("Override promotes 淡江 to A", school_tier("淡江大學") == "A")
        check("Override demotes 台大 to C", school_tier("國立台灣大學") == "C")
        check("Unlisted school keeps its built-in tier", school_tier("國立中央大學") == "B")

        # First match wins, so a specific entry placed first shadows a broader one.
        cfg["education"]["school_overrides"] = [
            {"pattern": "國立台北科技大學", "tier": "A"},
            {"pattern": "台北", "tier": "D"},
        ]
        cfgmod._cache = cfg
        check("First match wins", school_tier("國立台北科技大學") == "A")
        check("Broader entry still applies to others", school_tier("台北商業大學") == "D")

        # 臺 and 台 are used interchangeably in Taiwanese school names, and
        # NFKC does not unify them, so matching must fold one onto the other.
        cfg["education"]["school_overrides"] = [{"pattern": "台北大學", "tier": "B"}]
        cfgmod._cache = cfg
        check("Override typed 台 matches 臺", school_tier("國立臺北大學") == "B")
        cfg["education"]["school_overrides"] = [{"pattern": "臺北大學", "tier": "B"}]
        cfgmod._cache = cfg
        check("Override typed 臺 matches 台", school_tier("國立台北大學") == "B")

        # The gate reads the same function, so overrides reach it too.
        cfg["education"]["school_overrides"] = [{"pattern": "某技術學院", "tier": "A"}]
        cfgmod._cache = cfg
        passed, _ = apply_hard_filters(
            [], [], "", {"min_school_tier": "A"},
            education=[EducationExtract(school="某技術學院", department="資工", degree_level="學士")],
        )
        check("Hard filter honours overrides", passed)
    finally:
        cfgmod._cache = original

    # The roster is what the UI shows as draggable groups. Every school it
    # names must actually classify into the tier it is listed under, or the UI
    # would show a school in one group while the scorer rates it as another.
    from app.scoring.education import default_school_roster

    original = cfgmod._cache
    try:
        cfgmod._cache = copy.deepcopy(cfgmod.DEFAULTS)
        roster = default_school_roster()
        check("Roster covers every offered tier",
              set(roster) == {"A", "B", "C", "D"}, f"got {sorted(roster)}")
        mismatched = [
            (name, tier, school_tier(name))
            for tier, names in roster.items()
            for name in names
            if school_tier(name) != tier
        ]
        check("Roster agrees with the matcher", not mismatched, f"got {mismatched[:5]}")
        check("Roster names real schools", len(roster["A"]) > 5 and len(roster["C"]) > 20)
        dupes = [n for n in sum(roster.values(), []) if sum(roster.values(), []).count(n) > 1]
        check("No school listed in two tiers", not dupes, f"got {sorted(set(dupes))[:5]}")
    finally:
        cfgmod._cache = original

    # Validation
    bad = copy.deepcopy(cfgmod.DEFAULTS)
    bad["education"]["school_overrides"] = [{"pattern": "x", "tier": "Z"}]
    check("Invalid tier rejected", any("school_overrides" in e for e in cfgmod.validate(bad)))

    bad["education"]["school_overrides"] = [{"pattern": "", "tier": "A"}]
    check("Empty pattern rejected", any("school_overrides" in e for e in cfgmod.validate(bad)))

    bad["education"]["school_overrides"] = "not a list"
    check("Non-list rejected", any("school_overrides" in e for e in cfgmod.validate(bad)))

    ok = copy.deepcopy(cfgmod.DEFAULTS)
    ok["education"]["school_overrides"] = [{"pattern": "台北大學", "tier": "B"}]
    check("Valid override accepted", not cfgmod.validate(ok))
    check("Default config still valid", not cfgmod.validate(copy.deepcopy(cfgmod.DEFAULTS)))


def test_major_catalogue():
    """The picker vocabulary must produce majors the matcher can actually use."""
    print("\n=== Major catalogue ===")

    from app.scoring.education import major_catalogue

    cat = major_catalogue()
    check("Catalogue has several fields", len(cat) >= 5, f"got {len(cat)}")
    check("Catalogue is substantial", sum(len(v) for v in cat.values()) >= 60)

    flat = [m for v in cat.values() for m in v]
    dupes = sorted({m for m in flat if flat.count(m) > 1})
    # 資訊管理 sits in both 資訊 and 商管 on purpose; anything else is an error.
    check("No unintended duplicates", dupes in ([], ["資訊管理"]), f"got {dupes}")
    check("Names carry no degree suffix",
          not [m for m in flat if m.endswith("系") or m.endswith("學系")])

    # Every catalogued major must match a resume department written the long
    # way, otherwise picking it from the UI would silently score nothing.
    profile = DomainProfile.model_validate({
        "name": "t", "education": {"matters": True, "tier1_majors": flat, "tier2_majors": []},
    })
    unmatched = [
        m for m in flat
        if major_relevance_by_profile(profile, f"{m}學系") != "Tier1"
    ]
    check("Every catalogued major matches '<name>學系'", not unmatched, f"got {unmatched[:5]}")

    unmatched2 = [
        m for m in flat
        if major_relevance_by_profile(profile, f"{m}學系碩士班") != "Tier1"
    ]
    check("...and the master's form", not unmatched2, f"got {unmatched2[:5]}")

    # Bulk-selecting a whole field must stay usable: every major in the largest
    # group has to score as the tier it was filed under.
    biggest = max(cat.values(), key=len)
    bulk = DomainProfile.model_validate({
        "name": "t", "education": {"matters": True, "tier1_majors": biggest, "tier2_majors": []},
    })
    off = [m for m in biggest if major_relevance_by_profile(bulk, f"{m}學系") != "Tier1"]
    check("A whole field can be selected at once", not off, f"got {off[:5]}")

    # A major nobody picked must NOT match, or the picker would be meaningless.
    narrow = DomainProfile.model_validate({
        "name": "t", "education": {"matters": True, "tier1_majors": ["資訊工程"], "tier2_majors": []},
    })
    check("Unpicked major scores Other",
          major_relevance_by_profile(narrow, "中國文學系") == "Other")


def main():
    tests = [
        test_builtin_profile_valid,
        test_validation_rejects_unusable,
        test_tier_classification,
        test_keyword_floor,
        test_competencies,
        test_skills_and_education,
        test_pipeline_with_profile,
        test_education_matters_flag,
        test_builtin_path_unchanged,
        test_repair_of_llm_output,
        test_parse_profile_tolerance,
        test_min_education_filter,
        test_min_school_filter,
        test_school_tier_overrides,
        test_major_catalogue,
    ]
    for t in tests:
        try:
            t()
        except Exception:
            global FAIL
            FAIL += 1
            print(f"  ERROR in {t.__name__}")
            traceback.print_exc()

    print("\n" + "=" * 50)
    print(f"Results: {PASS} passed, {FAIL} failed")
    print("=" * 50)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
