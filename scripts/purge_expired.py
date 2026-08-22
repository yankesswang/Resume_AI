#!/usr/bin/env python3
"""Purge candidates whose retention window has expired.

Retention is driven by ``settings.retention_days`` (env ``RETENTION_DAYS``).
**0 disables retention entirely and is the default**, so an install that never
configures it never deletes anything — upgrading must not start destroying data.

This script is NOT wired to any scheduler. Run it deliberately.

    # report only (default)
    uv run python scripts/purge_expired.py
    uv run python scripts/purge_expired.py --retention-days 365

    # actually erase — irreversible
    uv run python scripts/purge_expired.py --retention-days 365 --apply

Erasure removes the candidate row, every child row carrying their PII, and the
per-candidate on-disk artifacts. A source PDF shared with other candidates is
kept (one 104 export PDF can hold 200 applicants).
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import erase_candidate, find_expired_candidates  # noqa: E402
from app.settings import settings  # noqa: E402

logger = logging.getLogger("purge_expired")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--retention-days",
        type=int,
        default=None,
        help="Override settings.retention_days for this run. 0 disables.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually erase. Without this the script only reports (dry run).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicitly request a dry run. This is already the default.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Process at most N candidates.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # Dry run unless --apply is passed: the safe reading wins, and --dry-run
    # alongside --apply resolves to a dry run rather than to deletion.
    dry_run = not args.apply or args.dry_run

    retention_days = args.retention_days if args.retention_days is not None else settings.retention_days
    if not retention_days or retention_days <= 0:
        print("保留期限未設定 (retention_days=0)，不刪除任何資料。")
        print("Retention is disabled; nothing to purge. Set RETENTION_DAYS or pass --retention-days.")
        return 0

    expired = find_expired_candidates(retention_days)
    if args.limit and args.limit > 0:
        expired = expired[: args.limit]

    mode = "DRY RUN" if dry_run else "APPLY"
    print(f"[{mode}] retention_days={retention_days}  database={settings.db_path}")
    print(f"[{mode}] {len(expired)} candidate(s) past the retention window.")

    if not expired:
        return 0

    for row in expired:
        print(f"  - id={row['id']:<6} created_at={row['created_at']}  name={row['name'] or '(unnamed)'}")

    if dry_run:
        print("\n未執行刪除。加上 --apply 才會真正刪除（不可復原）。")
        print("Nothing was deleted. Re-run with --apply to erase (irreversible).")
        return 0

    erased = 0
    for row in expired:
        report = erase_candidate(row["id"])
        if report.get("found"):
            erased += 1
            logger.info(
                "Purged candidate %s (%s): rows=%s files=%d",
                row["id"], row["name"], report["rows"], len(report["files"]),
            )
    print(f"\n已刪除 {erased} 位應徵者資料（不可復原）。")
    print(f"Erased {erased} candidate(s). This cannot be undone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
