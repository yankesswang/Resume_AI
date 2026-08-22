#!/usr/bin/env python3
"""Exercise the JD → scoring standard flow from the command line.

This is the manual counterpart to tests/test_domain_profiles.py: instead of
asserting against a fixed profile, it runs a real job description through the
real generator and shows you what came out and how it scores your actual
candidate pool. Use it to sanity-check a new role before touching the UI.

    # Generate a standard from a JD and score 30 real candidates against it
    uv run python scripts/try_job_profile.py tests/fixtures/job_descriptions/sales.txt

    # Skip the LLM and test a hand-written / previously generated profile
    uv run python scripts/try_job_profile.py --profile tests/fixtures/profiles/sales.json

    # Save the generated profile so you can edit and re-run it
    uv run python scripts/try_job_profile.py <jd.txt> --save out.json

Generation needs LM Studio up (LM_STUDIO_URL); --profile does not.
Scoring here is keyword-only — no LLM calls per candidate — so it takes
seconds, and it is the same path the /preview endpoint uses.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.scoring.domain_profile import DomainProfile, validate_profile


def _load_jd(path: Path) -> str:
    """Read a JD as text, using the same extraction the upload endpoint uses."""
    data = path.read_bytes()
    if data.startswith(b"%PDF") or path.suffix.lower() in (".pdf", ".docx"):
        from app.job_profiles_routes import _extract_text
        return _extract_text(data, path.name)
    return data.decode("utf-8")


def _print_profile(p: DomainProfile) -> None:
    print(f"\n領域：{p.domain}")
    print(f"說明：{p.summary}")

    print("\n深度分級")
    for t in p.tiers:
        print(f"  Tier {t.level}  {t.label}")
        print(f"           {t.definition}")
        if t.evidence_examples:
            print(f"           例：{'、'.join(t.evidence_examples[:5])}")

    print("\n分級關鍵字")
    for lvl in ("1", "2", "3"):
        kws = p.tier_keywords.get(lvl) or {}
        shown = ", ".join(f"{k}({v})" for k, v in list(kws.items())[:10])
        print(f"  Tier {lvl} ({len(kws)} 個)：{shown}")

    print("\n能力面向")
    for c in p.normalised_competencies():
        print(f"  {c.label} (權重 {c.weight:.2f})")
        for lvl in ("1", "2", "3"):
            terms = c.levels.get(lvl) or []
            if terms:
                print(f"    L{lvl}: {'、'.join(terms[:6])}")

    print(f"\n學歷：{'採計' if p.education.matters else '不採計'}"
          f"  對口科系：{'、'.join(p.education.tier1_majors[:6]) or '（無）'}")
    print(f"技能族群：{', '.join(f'{e.name}={e.score}' for e in p.ecosystems) or '（無）'}")

    groups = (p.hard_filters or {}).get("must_have_groups") or []
    if groups:
        print("硬性條件：")
        for g in groups:
            print(f"  {g['name']}：{len(g['skills'])} 選 {g['min_matches']} — {'、'.join(g['skills'])}")
    else:
        print("硬性條件：無")
    print(f"權重：{p.weights or '（沿用全域設定）'}")


def _score_pool(p: DomainProfile, limit: int) -> None:
    """Score real candidates through the keyword-only path."""
    from app.database import _connect, get_candidate_detail
    from app.scoring.pipeline import run_full_scoring

    job = {
        "basic_conditions": {"job_title": p.name},
        "job_summary": p.summary,
        "domain_profile": p.model_dump(),
    }

    conn = _connect()
    try:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM candidates ORDER BY id DESC LIMIT ?", (limit,)
        )]
    finally:
        conn.close()

    rows = []
    for cid in ids:
        detail = get_candidate_detail(cid)
        if not detail:
            continue
        # No db_conn -> keyword path only, no LLM call per candidate.
        r = run_full_scoring(detail, job)
        rows.append((r.overall_score, detail.get("name") or f"#{cid}",
                     r.experience_detail.tier, r.experience_detail.tier_label,
                     r.passed_hard_filter, r.hard_filter_failures))

    if not rows:
        print("\n資料庫中沒有候選人可供試算。")
        return

    rows.sort(reverse=True)
    print(f"\n試算 {len(rows)} 位候選人（純關鍵字，未呼叫 LLM）")
    print(f"{'分數':>6}  {'級距':<22}  {'硬條件':<6}  姓名")
    for score, name, tier, label, passed, fails in rows[:15]:
        mark = "通過" if passed else "刷掉"
        print(f"{score:>6}  T{tier} {label:<20}  {mark:<6}  {name}")
    if len(rows) > 15:
        print(f"  … 其餘 {len(rows) - 15} 位省略")

    scores = [r[0] for r in rows]
    rejected = sum(1 for r in rows if not r[4])
    dist: dict[int, int] = {}
    for r in rows:
        dist[r[2]] = dist.get(r[2], 0) + 1

    print(f"\n分數 {min(scores)} – {max(scores)}（平均 {sum(scores)/len(scores):.1f}）")
    print(f"級距分布：{dict(sorted(dist.items()))}")
    print(f"硬性條件刷掉：{rejected}/{len(rows)}")

    # The same read the /preview endpoint gives a reviewer.
    if rejected == len(rows):
        print("\n⚠ 硬性條件過嚴，所有人都被刷掉了 — 分數與級距分布在此情況下沒有參考價值。")
    elif max(scores) - min(scores) < 5:
        print("\n⚠ 分數幾乎相同，這組關鍵字在履歷池中沒有鑑別度。")
    elif dist.get(0, 0) / len(rows) > 0.9:
        print("\n⚠ 超過 9 成落在 Tier 0。若履歷池本來就是別的領域，這是正常結果。")
    else:
        print("\n✓ 標準能在現有履歷池中區分出高低。")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("jd", nargs="?", type=Path,
                    help="職缺文件（.txt / .pdf / .docx）")
    ap.add_argument("--profile", type=Path,
                    help="改用現成的 profile JSON，不呼叫 LLM 生成")
    ap.add_argument("--save", type=Path, help="把生成的 profile 存成 JSON")
    ap.add_argument("--limit", type=int, default=30, help="試算的候選人數（預設 30）")
    ap.add_argument("--no-score", action="store_true", help="只生成標準，不試算")
    args = ap.parse_args()

    if not args.jd and not args.profile:
        ap.error("請提供職缺文件，或用 --profile 指定現成的 profile")

    if args.profile:
        raw = json.loads(args.profile.read_text(encoding="utf-8"))
        # Accept both a bare profile and an /upload response containing one.
        profile = DomainProfile.model_validate(raw.get("profile", raw))
        print(f"載入 profile：{args.profile}")
    else:
        from app.scoring.profile_builder import (
            extract_job_requirement,
            generate_domain_profile,
        )
        jd_text = _load_jd(args.jd)
        print(f"讀取職缺文件：{args.jd}（{len(jd_text)} 字）")
        print("解析職缺結構…（LLM）")
        job_data = extract_job_requirement(jd_text, args.jd.name)
        print("生成評分標準…（LLM）")
        profile, gen_errors = generate_domain_profile(job_data, args.jd.name)
        if gen_errors:
            print("\n生成時發現問題：")
            for e in gen_errors:
                print(f"  - {e}")

    _print_profile(profile)

    errors = validate_profile(profile)
    print("\n驗證：" + ("通過，可啟用" if not errors else "未通過"))
    for e in errors:
        print(f"  ✗ {e}")

    if args.save:
        args.save.write_text(profile.model_dump_json(indent=1), encoding="utf-8")
        print(f"\n已存檔：{args.save}")

    if not args.no_score:
        _score_pool(profile, args.limit)

    # Exit non-zero on an unusable standard so this can gate a script.
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
