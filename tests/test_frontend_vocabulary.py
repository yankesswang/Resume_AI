"""The frontend must read the backend's vocabulary, not keep its own copy.

Four tables of business logic used to live in .vue files. Each was a second
source of truth that could not see operator edits, and each drifted silently —
there is no error when two copies of "which schools are top tier" disagree.

These tests fail if a copy comes back, or if the API stops serving the fields
the components now depend on.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

PASS = FAIL = 0


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}\n          got={got!r}\n         want={want!r}")


def ok(name, cond, detail=""):
    check(name + (f" ({detail})" if detail else ""), bool(cond), True)


print("=" * 50)
print("1. school tiers: one function, every consumer")
print("=" * 50)

from app.database import best_school_tier, meets_school_tier, SCHOOL_TIER_ORDER
from app.scoring.education import school_tier

check("台大 is A", best_school_tier([{"school": "國立臺灣大學"}]), "A")
check("best of many wins", best_school_tier(
    [{"school": "逢甲大學"}, {"school": "國立臺灣大學"}]), "A")
check("blank school -> None", best_school_tier([{"school": "  "}]), None)
check("no rows -> None", best_school_tier([]), None)

# The two asymmetries the hard filter documents, repeated here on purpose.
check("no parsable school FAILS a gate", meets_school_tier([], "A"), False)
check("tier D is no gate", meets_school_tier([], "D"), True)
check("unrecognised tier gates nobody", meets_school_tier([], "ZZ"), True)
check("blank gate passes", meets_school_tier([], ""), True)
check("A satisfies B gate", meets_school_tier([{"school": "國立臺灣大學"}], "B"), True)
check("C fails B gate", meets_school_tier([{"school": "逢甲大學"}], "B"), False)

# The regression that started this: an override must move the filter too.
# CONFIG_PATH is resolved at import time, so the module attribute is patched
# rather than the environment variable — setting the latter here would be read
# by nothing and the test would silently assert the baseline twice.
from app.scoring import config as _cfg

check("baseline: 逢甲 is C", school_tier("逢甲大學"), "C")

_tmp = Path(tempfile.mktemp(suffix=".json"))
_tmp.write_text(json.dumps(
    {"education": {"school_overrides": [{"pattern": "逢甲大學", "tier": "A"}]}}
), encoding="utf-8")
_original = _cfg.CONFIG_PATH
_cfg.CONFIG_PATH = _tmp
try:
    _cfg.load(force=True)
    check("an override promotes the school", school_tier("逢甲大學"), "A")
    check("...and the gate honours it",
          meets_school_tier([{"school": "逢甲大學"}], "A"), True)
finally:
    _cfg.CONFIG_PATH = _original
    _cfg.load(force=True)
    _tmp.unlink(missing_ok=True)

check("baseline restored", meets_school_tier([{"school": "逢甲大學"}], "A"), False)

print()
print("=" * 50)
print("2. degree ranks cover what the keyword list missed")
print("=" * 50)

from app.database import annotate_degree_levels

cases = [
    ("四技", "bachelor"), ("二技", "bachelor"), ("大學", "bachelor"),
    ("碩士", "master"), ("碩士班", "master"), ("研究所", "master"),
    ("博士", "phd"), ("博士班", "phd"),
    ("五專", "associate"), ("高中", "high_school"),
]
for value, want in cases:
    rows = annotate_degree_levels([{"degree_level": value}])
    check(f"degree_level {value!r}", rows[0]["degree_rank"], want)

# The parser routinely leaves degree_level blank and puts it in department.
rows = annotate_degree_levels([{"degree_level": "", "department": "資訊工程學系碩士班"}])
check("falls back to department", rows[0]["degree_rank"], "master")
rows = annotate_degree_levels([{"degree_level": None, "department": None}])
check("nothing parsable -> None", rows[0]["degree_rank"], None)

print()
print("=" * 50)
print("3. tier names come from the active job")
print("=" * 50)

from app.routes import _active_tier_labels

labels = _active_tier_labels()
check("four tiers", len(labels), 4)
check("levels 0..3", [t["value"] for t in labels], [0, 1, 2, 3])
ok("every tier is named", all((t["label"] or "").strip() for t in labels))

print()
print("=" * 50)
print("4. no hardcoded copies left in the frontend")
print("=" * 50)

table = (SRC / "components" / "CandidateTable.vue").read_text(encoding="utf-8")
panel = (SRC / "components" / "FilterPanel.vue").read_text(encoding="utf-8")
cal = (SRC / "views" / "CalendarView.vue").read_text(encoding="utf-8")

ok("no school keyword list", "TOP_UNIVERSITY_KEYWORDS" not in table)
ok("table reads school_tier", "school_tier" in table)
ok("table reads degree_rank", "degree_rank" in table)

# The tier names may remain only as an explicitly-named fallback, never as the
# value the dropdown renders directly.
ok("panel takes tier names as a prop", "aiTiers" in panel)
# The names may survive as an explicitly-named fallback constant (and in the
# comment explaining why), never as the array the dropdown renders directly.
ok("tier names live in a named fallback", "FALLBACK_TIERS" in panel)
ok("dropdown renders the prop, not the constant",
   "props.aiTiers.length" in panel and "const tierItems = computed(" in panel)

ok("calendar has no hardcoded type array",
   not re.search(r"const interviewTypes\s*=\s*\[", cal))
ok("calendar reads types from the store", "types: interviewTypes" in cal)

print()
print("=" * 50)
print("5. the API serves what the components now need")
print("=" * 50)

from app.database import get_all_candidates_summary, get_interview_types

rows = get_all_candidates_summary(limit=25, with_total=True)["items"]
if rows:
    ok("rows carry school_tier", all("school_tier" in r for r in rows))
    ok("education rows carry degree_rank",
       all("degree_rank" in e for r in rows for e in (r.get("education") or [])))
    ok("school_tier is on the ladder or None",
       all(r.get("school_tier") in (*SCHOOL_TIER_ORDER, None) for r in rows))
else:
    print("  SKIP  no candidates in this database")

types = get_interview_types()
ok("the three seeded types exist",
   {t["value"] for t in types} >= {"phone", "video", "onsite"})
ok("every type has a label", all((t.get("label") or "").strip() for t in types))
ok("values are unique", len({t["value"] for t in types}) == len(types))

print()
print("=" * 50)
print(f"PASS: {PASS}   FAIL: {FAIL}")
print("=" * 50)
sys.exit(1 if FAIL else 0)
