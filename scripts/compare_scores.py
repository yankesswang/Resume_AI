"""Compare v1 (old) vs v2 (new) scoring side-by-side for all DB candidates.

Runs both scoring pipelines on every candidate and prints a ranked diff table.

Usage:
    uv run python scripts/compare_scores.py
    uv run python scripts/compare_scores.py --top 30       # show top N rows
    uv run python scripts/compare_scores.py --csv out.csv  # also save CSV
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("LM_STUDIO_URL", "http://192.168.0.84:1234/v1/chat/completions")
os.environ.setdefault("EMBEDDING_URL", "http://192.168.0.84:1234/v1/embeddings")

from app.database import _connect, init_db
from app.models import EducationExtract
from app.scoring.hard_filter import apply_hard_filters

# ── v2 modules (current state of codebase) ──────────────────────────────────
from app.scoring.education import score_education as score_education_v2
from app.scoring.engineering import score_engineering_maturity as score_eng_v2
from app.scoring.experience import (
    TIER_BASE_SCORES,
    TIER_KEYWORDS,
    DATA_SCALE_PATTERN,
    SYSTEM_ARCH_PATTERN,
    MODEL_SCALE_PATTERN,
    VALID_METRIC_PATTERN,
    _find_keywords,
    classify_experience_tier as classify_exp_v2,
)
from app.scoring.skills import verify_skills as verify_skills_v2

JOB_REQ_PATH = ROOT / "job_requirement.json"


# ─────────────────────────────────────────────────────────────────────────────
# V1 (OLD) scoring — inline so we don't need git stash
# ─────────────────────────────────────────────────────────────────────────────

import re

_US_GRADE_A = [
    "Stanford", "MIT", "CMU", "Carnegie Mellon", "UC Berkeley", "Harvard",
    "Yale", "Princeton", "Columbia", "UPenn", "Cornell", "Caltech",
    "Georgia Tech", "UIUC", "UCLA", "USC", "NYU", "Purdue", "UMD",
    "UT Austin", "UCSD", "U-Mich", "University of Michigan", "UW",
    "University of Washington", "ETH Zurich", "Oxford", "Cambridge",
    "Imperial College", "University of Toronto", "Waterloo", "NUS",
    "NTU Singapore", "Tsinghua", "Peking University", "KAIST",
    "University of Tokyo",
]
_TW_A = re.compile(
    r"(台灣|臺灣|清華|交通|陽明交通|陽明|成功|政治|台灣科技|臺灣科技)大學|"
    r"(台|臺|清|交|成|政|台科|臺科|陽明交)大|"
    r"National Taiwan University|National Tsing Hua University|"
    r"National Chiao Tung University|National Yang Ming Chiao Tung University|"
    r"National Cheng Kung University|National Chengchi University|"
    r"National Taiwan University of Science and Technology|Taiwan Tech|"
    r"NTU\b|NTHU|NCTU|NYCU|NCKU|NCCU|NTUST",
    re.IGNORECASE,
)
_TW_B = re.compile(
    r"(中央|中興|中正|中山|台北科技|臺北科技|台灣師範|臺灣師範)大學|"
    r"中(央|興|正|山)大|北科|師大",
    re.IGNORECASE,
)
_T1_MAJOR = re.compile(
    r"資工|資訊工程|資管|資訊管理|電機|EECS|Computer Science|CS\b|"
    r"MIS|EE\b|AI|Artificial Intelligence|Data Science|資訊科學|"
    r"Machine Learning|軟體工程|Software Engineering|電信工程",
    re.IGNORECASE,
)
_T2_MAJOR = re.compile(
    r"統計|數學|應數|數據|理學院|Math|Stat|Physics|物理|"
    r"應用數學|Applied Math|Operations Research|工業工程",
    re.IGNORECASE,
)
_THESIS_AI = re.compile(
    r"NLP|Natural Language|Computer Vision|CV|Deep Learning|Transformer|"
    r"BERT|GPT|LLM|Reinforcement Learning|Neural Network|機器學習|深度學習|自然語言",
    re.IGNORECASE,
)
_TOP_VENUE = re.compile(
    r"NeurIPS|NIPS|ICLR|ICML|CVPR|ICCV|ECCV|ACL|EMNLP|AAAI|IJCAI|"
    r"ICASSP|INTERSPEECH|KDD|COLING|NAACL",
    re.IGNORECASE,
)
_PHD_KW = ("博士", "phd", "doctorate", "ph.d.")
_MASTER_KW = ("碩士", "碩", "master", "mba", "m.s.", "m.a.", "graduate")


def _v1_edu_score(education_list: list, raw_markdown: str) -> float:
    """Old education scoring: denominator=20, bachelor 0.7×, thesis in 20-scale."""
    def school_pts(school):
        if any(k.lower() in school.lower() for k in _US_GRADE_A):
            return 10.0
        if _TW_A.search(school): return 10.0
        if _TW_B.search(school): return 3.0
        return 0.0

    def major_pts(dept):
        if _T1_MAJOR.search(dept): return 10.0
        if _T2_MAJOR.search(dept): return 3.0
        return 0.0

    def deg_level(s):
        sl = s.lower()
        if any(k in sl for k in _PHD_KW): return "phd"
        if any(k in sl for k in _MASTER_KW): return "master"
        return "bachelor"

    _MIM = re.compile(r"碩士班|研究所|碩士", re.IGNORECASE)
    b_best = m_best = None
    for ed in education_list:
        sp = school_pts(ed.get("school", ""))
        mp = major_pts(ed.get("department", ""))
        base = sp + mp
        level = deg_level(ed.get("degree_level", ""))
        if level == "bachelor":
            if b_best is None or base > b_best: b_best = base
            if _MIM.search(ed.get("department", "")):
                if m_best is None or base > m_best: m_best = base
        else:
            if m_best is None or base > m_best: m_best = base

    b = b_best or 0.0
    m = m_best or 0.0
    hybrid = (b * 0.7 + m * 0.3) if m_best else (b * 0.7)

    thesis = 0.0
    if raw_markdown:
        if _THESIS_AI.search(raw_markdown): thesis += 1.0
        if _TOP_VENUE.search(raw_markdown): thesis += 1.0

    return min((hybrid + thesis) / 20.0 * 100.0, 100.0)


# Old engineering constants
_V1_BACKEND = {0: 0.0, 1: 0.1, 2: 0.15, 3: 0.25}
_V1_DB      = {0: 0.0, 1: 0.05, 2: 0.10, 3: 0.15}
_V1_FE      = {0: 0.0, 1: 0.0,  2: 0.05, 3: 0.10}

from app.scoring.engineering import (
    BACKEND_L3_PATTERN, BACKEND_L2_PATTERN, BACKEND_L1_PATTERN,
    DB_L3_PATTERN, DB_L2_PATTERN, DB_L1_PATTERN,
    FE_L3_PATTERN, FE_L2_PATTERN, FE_L1_PATTERN,
)


def _v1_eng_score(work_experiences, skill_tags, raw_markdown) -> float:
    """Old engineering maturity: cap=0.5, FE_L1=0."""
    parts = []
    for we in work_experiences:
        parts.append(we.get("job_description", "") or "")
        parts.append(we.get("job_title", "") or "")
        parts.append(we.get("job_skills", "") or "")
    parts.extend(skill_tags)
    if raw_markdown: parts.append(raw_markdown)
    combined = " ".join(parts)

    bl = 3 if BACKEND_L3_PATTERN.search(combined) else \
         2 if BACKEND_L2_PATTERN.search(combined) else \
         1 if BACKEND_L1_PATTERN.search(combined) else 0
    dl = 3 if DB_L3_PATTERN.search(combined) else \
         2 if DB_L2_PATTERN.search(combined) else \
         1 if DB_L1_PATTERN.search(combined) else 0
    fl = 3 if FE_L3_PATTERN.search(combined) else \
         2 if FE_L2_PATTERN.search(combined) else \
         1 if FE_L1_PATTERN.search(combined) else 0

    return min(_V1_BACKEND[bl] + _V1_DB[dl] + _V1_FE[fl], 0.5)


def _v1_exp_score(work_experiences, skill_tags, raw_markdown) -> float:
    """Old experience scoring: no position weighting on stack score."""
    parts = []
    for we in work_experiences:
        parts.append(we.get("job_description", "") or "")
        parts.append(we.get("job_title", "") or "")
        parts.append(we.get("job_skills", "") or "")
    parts.extend(skill_tags)
    if raw_markdown: parts.append(raw_markdown)
    combined = " ".join(parts)

    if not combined.strip():
        return 60.0

    tier_w = {1: 0.0, 2: 0.0, 3: 0.0}
    total_stack = 0.0
    for tier in [3, 2, 1]:
        for _kw, w in _find_keywords(combined, TIER_KEYWORDS[tier]):
            tier_w[tier] += w
            total_stack += w

    if tier_w[3] >= 3.0:    best = 3
    elif tier_w[3] > 0 or tier_w[2] >= 2.0: best = 2
    elif tier_w[2] > 0:     best = 2
    else:                   best = 1

    complexity = 0.0
    if DATA_SCALE_PATTERN.search(combined):  complexity += 0.33
    if SYSTEM_ARCH_PATTERN.search(combined): complexity += 0.33
    if MODEL_SCALE_PATTERN.search(combined): complexity += 0.34
    metric_score = min(len(VALID_METRIC_PATTERN.findall(combined)) * 0.25, 1.0)

    base = TIER_BASE_SCORES[best]
    return min(base + min(total_stack * 2, 10.0) + complexity * 5 + metric_score * 5, 100.0)


def _v1_skills_score(skill_tags, work_experiences, raw_markdown="") -> float:
    """Old skill verification: no keyword-stuffing check, no portfolio tier."""
    from app.scoring.skills import LLM_STACK, DEEP_LEARNING, TRADITIONAL_ML
    skills_text = " ".join(skill_tags)
    work_text = " ".join(
        (we.get("job_description", "") or "") + " " + (we.get("job_skills", "") or "")
        for we in work_experiences
    )
    corpus = skills_text + " " + work_text + " " + raw_markdown
    if LLM_STACK.search(corpus):       eco_score = 90.0
    elif DEEP_LEARNING.search(corpus): eco_score = 70.0
    elif TRADITIONAL_ML.search(corpus):eco_score = 50.0
    else:                              eco_score = 30.0

    high_value = ["PyTorch", "TensorFlow", "CUDA", "vLLM", "Fine-tuning",
                  "RAG", "LangChain", "Docker", "Kubernetes", "K8s"]
    suspicious = sum(
        1 for sk in high_value
        if any(sk.lower() in t.lower() for t in skill_tags)
        and sk.lower() not in work_text.lower()
        and work_text.strip()
    )
    return max(eco_score - suspicious * 5, 10.0)


# ─────────────────────────────────────────────────────────────────────────────
# Scoring wrappers
# ─────────────────────────────────────────────────────────────────────────────

W_EXP, W_ENG, W_SEM, W_EDU, W_SKL = 0.35, 0.20, 0.20, 0.15, 0.10


def score_v1(detail: dict, hard_filter_config: dict) -> dict:
    work  = detail.get("work_experiences", [])
    edu   = detail.get("education", [])
    tags  = detail.get("skill_tags", [])
    raw   = detail.get("raw_markdown", "") or ""

    if hard_filter_config:
        passed, _ = apply_hard_filters(tags, work, raw, hard_filter_config)
        if not passed:
            return {"overall": 10.0, "edu": 0.0, "exp": 0.0, "eng": 0.0, "skl": 0.0,
                    "m_eng": 0.0, "tier": 1, "filter": "FAIL"}

    edu_s = _v1_edu_score(edu, raw)
    exp_s = _v1_exp_score(work, tags, raw)
    m_eng = _v1_eng_score(work, tags, raw)
    skl_s = _v1_skills_score(tags, work, raw)
    eng_n = min(m_eng / 0.5, 1.0) * 100.0

    overall = round(exp_s * W_EXP + eng_n * W_ENG + edu_s * W_EDU + skl_s * W_SKL, 1)
    # Determine old tier for display
    parts = []
    for we in work:
        parts.append(we.get("job_description", "") or "")
        parts.append(we.get("job_skills", "") or "")
    parts.extend(tags)
    if raw: parts.append(raw)
    combined = " ".join(parts)
    tw = {1: 0.0, 2: 0.0, 3: 0.0}
    for t in [3, 2, 1]:
        for _k, w in _find_keywords(combined, TIER_KEYWORDS[t]):
            tw[t] += w
    tier = 3 if tw[3] >= 3.0 else (2 if (tw[3] > 0 or tw[2] >= 2.0) else 1)

    return {"overall": min(overall, 100.0), "edu": round(edu_s, 1),
            "exp": round(exp_s, 1), "eng": round(eng_n, 1), "skl": round(skl_s, 1),
            "m_eng": round(m_eng, 2), "tier": tier, "filter": "PASS"}


def score_v2(detail: dict, hard_filter_config: dict) -> dict:
    work  = detail.get("work_experiences", [])
    edu   = detail.get("education", [])
    tags  = detail.get("skill_tags", [])
    raw   = detail.get("raw_markdown", "") or ""

    if hard_filter_config:
        passed, _ = apply_hard_filters(tags, work, raw, hard_filter_config)
        if not passed:
            return {"overall": 10.0, "edu": 0.0, "exp": 0.0, "eng": 0.0, "skl": 0.0,
                    "m_eng": 0.0, "tier": 1, "filter": "FAIL"}

    edu_extracts = [
        EducationExtract(
            school=e.get("school", ""),
            department=e.get("department", ""),
            degree_level=e.get("degree_level", ""),
        ) for e in edu
    ]

    edu_d = score_education_v2(edu_extracts, raw)
    exp_d = classify_exp_v2(work, tags, raw)
    eng_d = score_eng_v2(work, tags, raw)
    skl_d = verify_skills_v2(tags, work, raw)

    eng_n = min(eng_d.m_eng / 0.7, 1.0) * 100.0
    overall = round(
        exp_d.score * W_EXP + eng_n * W_ENG + edu_d.score * W_EDU + skl_d.score * W_SKL,
        1,
    )

    return {"overall": min(overall, 100.0), "edu": round(edu_d.score, 1),
            "exp": round(exp_d.score, 1), "eng": round(eng_n, 1),
            "skl": round(skl_d.score, 1), "m_eng": round(eng_d.m_eng, 2),
            "tier": exp_d.tier, "filter": "PASS"}


# ─────────────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────────────

def load_candidates() -> dict[int, dict]:
    conn = _connect()
    candidates = {}
    for r in conn.execute("SELECT * FROM candidates ORDER BY id").fetchall():
        d = dict(r)
        for f in ("desired_job_categories", "desired_locations", "ideal_positions", "skill_tags"):
            d[f] = json.loads(d[f] or "[]")
        d["work_experiences"] = []
        d["education"] = []
        candidates[d["id"]] = d
    for r in conn.execute("SELECT * FROM work_experiences ORDER BY candidate_id, seq").fetchall():
        cid = r["candidate_id"]
        if cid in candidates:
            candidates[cid]["work_experiences"].append(dict(r))
    for r in conn.execute("SELECT * FROM education ORDER BY candidate_id, seq").fetchall():
        cid = r["candidate_id"]
        if cid in candidates:
            candidates[cid]["education"].append(dict(r))
    conn.close()
    return candidates


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Compare v1 vs v2 scoring")
    parser.add_argument("--top", type=int, default=50, help="Show top N rows (default 50)")
    parser.add_argument("--csv", type=str, default="", help="Also save full results to CSV")
    args = parser.parse_args()

    init_db()
    job_data = json.loads(JOB_REQ_PATH.read_text(encoding="utf-8"))
    hf = job_data.get("hard_filters", {})

    print("Loading candidates...", flush=True)
    candidates = load_candidates()
    print(f"  {len(candidates)} candidates loaded", flush=True)

    rows = []
    for cid, detail in candidates.items():
        name = (detail.get("name") or "?")[:12]
        v1 = score_v1(detail, hf)
        v2 = score_v2(detail, hf)
        delta = round(v2["overall"] - v1["overall"], 1)
        rows.append({
            "id": cid, "name": name,
            "v1_overall": v1["overall"], "v2_overall": v2["overall"], "delta": delta,
            "v1_edu": v1["edu"], "v2_edu": v2["edu"],
            "v1_exp": v1["exp"], "v2_exp": v2["exp"],
            "v1_eng": v1["eng"], "v2_eng": v2["eng"],
            "v1_skl": v1["skl"], "v2_skl": v2["skl"],
            "v1_tier": v1["tier"], "v2_tier": v2["tier"],
            "v1_m_eng": v1["m_eng"], "v2_m_eng": v2["m_eng"],
            "filter": v2["filter"],
        })

    # Sort by v2 overall desc
    rows.sort(key=lambda r: r["v2_overall"], reverse=True)

    # ── Print table ──────────────────────────────────────────────────────────
    HDR = (
        f"{'#':>3} {'ID':>4} {'Name':<12} "
        f"{'V1':>6} {'V2':>6} {'Δ':>6}  "
        f"{'Edu_v1':>6} {'Edu_v2':>6}  "
        f"{'Exp_v1':>6} {'Exp_v2':>6}  "
        f"{'Eng_v1':>6} {'Eng_v2':>6}  "
        f"{'Skl_v1':>6} {'Skl_v2':>6}  "
        f"{'T1':>2}{'T2':>2}  {'Flt':>4}"
    )
    SEP = "─" * len(HDR)
    print()
    print(f"  Top {min(args.top, len(rows))} candidates (sorted by v2 overall)")
    print(SEP)
    print(HDR)
    print(SEP)

    for i, r in enumerate(rows[: args.top], 1):
        delta_str = f"{r['delta']:+.1f}"
        print(
            f"{i:>3} {r['id']:>4} {r['name']:<12} "
            f"{r['v1_overall']:>6.1f} {r['v2_overall']:>6.1f} {delta_str:>6}  "
            f"{r['v1_edu']:>6.1f} {r['v2_edu']:>6.1f}  "
            f"{r['v1_exp']:>6.1f} {r['v2_exp']:>6.1f}  "
            f"{r['v1_eng']:>6.1f} {r['v2_eng']:>6.1f}  "
            f"{r['v1_skl']:>6.1f} {r['v2_skl']:>6.1f}  "
            f"T{r['v1_tier']:>1} T{r['v2_tier']:>1}  {r['filter']:>4}"
        )

    print(SEP)

    # ── Summary stats ─────────────────────────────────────────────────────────
    passed = [r for r in rows if r["filter"] == "PASS"]
    failed = [r for r in rows if r["filter"] == "FAIL"]
    gainers = [r for r in passed if r["delta"] > 0]
    losers  = [r for r in passed if r["delta"] < 0]
    unchanged = [r for r in passed if r["delta"] == 0]
    avg_delta = sum(r["delta"] for r in passed) / len(passed) if passed else 0

    print()
    print("Summary (passed hard filter only):")
    print(f"  Total candidates : {len(rows):>4}  (passed: {len(passed)}, hard-filter fail: {len(failed)})")
    print(f"  Score increased  : {len(gainers):>4}  (avg Δ for gainers: {sum(r['delta'] for r in gainers)/max(len(gainers),1):+.1f})")
    print(f"  Score decreased  : {len(losers):>4}  (avg Δ for losers: {sum(r['delta'] for r in losers)/max(len(losers),1):+.1f})")
    print(f"  Unchanged        : {len(unchanged):>4}")
    print(f"  Average Δ overall: {avg_delta:+.2f}")

    # Edu sub-score change
    edu_deltas = [r["v2_edu"] - r["v1_edu"] for r in passed]
    eng_deltas = [r["v2_eng"] - r["v1_eng"] for r in passed]
    exp_deltas = [r["v2_exp"] - r["v1_exp"] for r in passed]
    skl_deltas = [r["v2_skl"] - r["v1_skl"] for r in passed]
    print()
    print("Sub-score avg change (v2 − v1):")
    print(f"  Education  : {sum(edu_deltas)/max(len(edu_deltas),1):+.2f}")
    print(f"  Experience : {sum(exp_deltas)/max(len(exp_deltas),1):+.2f}")
    print(f"  Engineering: {sum(eng_deltas)/max(len(eng_deltas),1):+.2f}")
    print(f"  Skills     : {sum(skl_deltas)/max(len(skl_deltas),1):+.2f}")

    # Tier shifts
    tier_up   = sum(1 for r in passed if r["v2_tier"] > r["v1_tier"])
    tier_down = sum(1 for r in passed if r["v2_tier"] < r["v1_tier"])
    print()
    print("Experience tier shifts:")
    print(f"  Tier up   : {tier_up}")
    print(f"  Tier down : {tier_down}")
    print(f"  Unchanged : {len(passed) - tier_up - tier_down}")

    # ── CSV export ────────────────────────────────────────────────────────────
    if args.csv:
        import csv
        out = Path(args.csv)
        fields = [
            "id", "name", "filter",
            "v1_overall", "v2_overall", "delta",
            "v1_edu", "v2_edu", "v1_exp", "v2_exp",
            "v1_eng", "v2_eng", "v1_skl", "v2_skl",
            "v1_tier", "v2_tier", "v1_m_eng", "v2_m_eng",
        ]
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        print(f"\n  CSV saved → {out.resolve()}")


if __name__ == "__main__":
    main()
