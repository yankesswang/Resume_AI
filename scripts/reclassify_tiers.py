"""Batch LLM tier reclassification for all candidates.

Iterates candidates where llm_tier IS NULL or md5(raw_markdown) has changed,
calls the LLM classifier with concurrency=3, and writes results to the cache columns.
Does NOT touch match_results — run batch_score_all.py afterwards to rescore.

Usage:
    uv run python scripts/reclassify_tiers.py [--limit N] [--force]

Options:
    --limit N   Process only the first N candidates needing classification
    --force     Re-classify all candidates regardless of cache state
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("LM_STUDIO_URL", "http://192.168.0.84:1234/v1/chat/completions")

from app.database import _connect, init_db, store_llm_tier_cache
from app.llm import classify_ai_tier

CONCURRENCY = 3


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def load_candidates_needing_classification(force: bool = False, limit: int | None = None) -> list[dict]:
    """Return candidates whose llm_tier cache is missing or stale."""
    conn = _connect()
    rows = conn.execute(
        "SELECT id, name, skill_tags, raw_markdown, llm_tier, llm_tier_md5 "
        "FROM candidates ORDER BY id"
    ).fetchall()

    # Load work experiences in bulk
    work_rows = conn.execute(
        "SELECT candidate_id, seq, job_title, job_description, job_skills "
        "FROM work_experiences ORDER BY candidate_id, seq"
    ).fetchall()
    conn.close()

    work_map: dict[int, list[dict]] = {}
    for wr in work_rows:
        cid = wr["candidate_id"]
        work_map.setdefault(cid, []).append(dict(wr))

    candidates = []
    for r in rows:
        raw_md = r["raw_markdown"] or ""
        current_md5 = _md5(raw_md)
        needs_classify = (
            force
            or r["llm_tier"] is None
            or r["llm_tier_md5"] != current_md5
        )
        if needs_classify:
            d = dict(r)
            d["skill_tags"] = json.loads(d["skill_tags"] or "[]")
            d["work_experiences"] = work_map.get(d["id"], [])
            candidates.append(d)

    if limit is not None:
        candidates = candidates[:limit]
    return candidates


def classify_one(candidate: dict) -> dict:
    """Call LLM classifier for one candidate. Returns result dict with candidate_id."""
    cid = candidate["id"]
    work_experiences = candidate["work_experiences"]
    skill_tags = candidate["skill_tags"]
    raw_markdown = candidate.get("raw_markdown") or ""

    try:
        result = classify_ai_tier(work_experiences, skill_tags, raw_markdown)
        tier = max(1, min(int(result.get("tier", 1)), 3))
        return {
            "candidate_id": cid,
            "name": candidate.get("name", ""),
            "tier": tier,
            "reasoning": result.get("reasoning", ""),
            "confidence": result.get("confidence", 0.0),
            "raw_markdown": raw_markdown,
            "error": None,
        }
    except Exception as e:
        return {
            "candidate_id": cid,
            "name": candidate.get("name", ""),
            "tier": None,
            "reasoning": "",
            "confidence": 0.0,
            "raw_markdown": raw_markdown,
            "error": str(e),
        }


def save_results(results: list[dict]):
    """Bulk write LLM tier cache to DB."""
    conn = _connect()
    for r in results:
        if r["tier"] is None:
            continue
        store_llm_tier_cache(conn, r["candidate_id"], r["raw_markdown"], {
            "tier": r["tier"],
            "reasoning": r["reasoning"],
        })
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Batch LLM tier reclassification")
    parser.add_argument("--limit", type=int, default=None, help="Max candidates to process")
    parser.add_argument("--force", action="store_true", help="Re-classify all regardless of cache")
    args = parser.parse_args()

    init_db()

    print("Loading candidates needing classification...", flush=True)
    candidates = load_candidates_needing_classification(force=args.force, limit=args.limit)
    total = len(candidates)
    print(f"  {total} candidates to classify (concurrency={CONCURRENCY})", flush=True)

    if total == 0:
        print("Nothing to do. All LLM tiers are up-to-date.", flush=True)
        return

    t0 = time.time()
    completed_count = 0
    failed_count = 0
    tier_distribution: Counter = Counter()
    all_results: list[dict] = []

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = {executor.submit(classify_one, c): c for c in candidates}
        for future in as_completed(futures):
            result = future.result()
            all_results.append(result)
            completed_count += 1

            if result["error"]:
                failed_count += 1
                if failed_count <= 5:
                    print(
                        f"  ERROR id={result['candidate_id']} {result['name']}: {result['error']}",
                        flush=True,
                    )
            else:
                tier_distribution[result["tier"]] += 1

            # Progress every 10 candidates
            if completed_count % 10 == 0 or completed_count == total:
                elapsed = time.time() - t0
                rate = completed_count / elapsed if elapsed > 0 else 0
                remaining = total - completed_count
                eta = remaining / rate if rate > 0 else 0
                dist_str = " | ".join(
                    f"T{t}:{n}" for t, n in sorted(tier_distribution.items())
                )
                print(
                    f"  [{completed_count:>4}/{total}] {rate:.1f}/s | ETA {eta:.0f}s | {dist_str}",
                    flush=True,
                )

    # Save all successful results
    print("\nSaving to DB...", flush=True)
    save_results(all_results)
    elapsed = time.time() - t0
    print(f"Done in {elapsed:.1f}s", flush=True)

    # Final tier distribution
    passed = sum(tier_distribution.values())
    print(f"\nTier distribution ({passed} classified, {failed_count} failed):")
    for tier in [3, 2, 1]:
        count = tier_distribution.get(tier, 0)
        pct = 100 * count / passed if passed > 0 else 0
        labels = {1: "Wrapper     ", 2: "RAG Architect", 3: "AI Expert   "}
        bar = "█" * int(pct / 2)
        print(f"  Tier {tier} ({labels[tier]}): {count:>4} ({pct:5.1f}%) {bar}")

    print(
        "\nNext step: run `uv run python scripts/batch_score_all.py` to rescore with updated tiers.",
        flush=True,
    )


if __name__ == "__main__":
    main()
