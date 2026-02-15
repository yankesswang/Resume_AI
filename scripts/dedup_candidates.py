"""
Remove duplicate candidates from resume_ai.db.

For each group of duplicates (same code_104), keeps the record with the
highest id (most recently imported = freshest parse) and deletes the rest,
including all child records (work_experiences, education, skills, etc.).

Also removes candidates with empty name AND empty code_104 (unparseable junk).

Usage:
    python3 scripts/dedup_candidates.py              # preview
    python3 scripts/dedup_candidates.py --apply       # actually delete
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import DB_PATH, init_db

CHILD_TABLES = ("work_experiences", "education", "skills", "references_", "attachments", "match_results")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def find_duplicates(conn: sqlite3.Connection) -> list[tuple[str, list[int]]]:
    """Find groups of duplicate candidates by code_104.

    Returns list of (code_104, [ids_to_delete]) where we keep the max id.
    """
    rows = conn.execute("""
        SELECT code_104, GROUP_CONCAT(id) as ids, COUNT(*) as cnt
        FROM candidates
        WHERE code_104 IS NOT NULL AND code_104 <> ''
        GROUP BY code_104
        HAVING cnt > 1
        ORDER BY cnt DESC
    """).fetchall()

    groups = []
    for r in rows:
        ids = sorted(int(x) for x in r["ids"].split(","))
        keep = ids[-1]  # keep highest id
        delete = ids[:-1]
        groups.append((r["code_104"], keep, delete))
    return groups


def find_junk(conn: sqlite3.Connection) -> list[int]:
    """Find candidates with no name and no code_104 (unparseable entries)."""
    rows = conn.execute("""
        SELECT id FROM candidates
        WHERE (name IS NULL OR name = '')
          AND (code_104 IS NULL OR code_104 = '')
    """).fetchall()
    return [r["id"] for r in rows]


def delete_candidates(conn: sqlite3.Connection, ids: list[int]):
    """Delete candidates and all their child records."""
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    for table in CHILD_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE candidate_id IN ({placeholders})", ids)
    conn.execute(f"DELETE FROM candidates WHERE id IN ({placeholders})", ids)


def main():
    parser = argparse.ArgumentParser(description="Deduplicate candidates in resume_ai.db")
    parser.add_argument("--apply", action="store_true", help="Actually delete duplicates (default: preview only)")
    args = parser.parse_args()

    init_db()
    conn = _connect()

    # Count before
    total_before = conn.execute("SELECT COUNT(*) as c FROM candidates").fetchone()["c"]
    print(f"Total candidates before: {total_before}")

    # Find duplicates
    groups = find_duplicates(conn)
    total_dup_delete = sum(len(delete) for _, _, delete in groups)
    print(f"\nDuplicate groups (by code_104): {len(groups)}")
    print(f"Duplicate records to delete: {total_dup_delete}")

    if groups:
        print("\nTop 10 duplicate groups:")
        for code, keep, delete in groups[:10]:
            print(f"  code_104={code}: keep id={keep}, delete ids={delete}")

    # Find junk
    junk_ids = find_junk(conn)
    print(f"\nJunk records (no name, no code): {len(junk_ids)}")

    all_delete = []
    for _, _, delete in groups:
        all_delete.extend(delete)
    all_delete.extend(junk_ids)

    if not all_delete:
        print("\nNo duplicates or junk found. Database is clean.")
        conn.close()
        return

    print(f"\nTotal records to delete: {len(all_delete)}")
    expected_after = total_before - len(all_delete)
    print(f"Expected candidates after cleanup: {expected_after}")

    if not args.apply:
        print("\n--- DRY RUN --- Pass --apply to actually delete.")
        conn.close()
        return

    print("\nDeleting...")
    delete_candidates(conn, all_delete)
    conn.commit()

    # Verify
    total_after = conn.execute("SELECT COUNT(*) as c FROM candidates").fetchone()["c"]
    remaining_dups = conn.execute("""
        SELECT COUNT(*) as c FROM (
            SELECT code_104 FROM candidates
            WHERE code_104 IS NOT NULL AND code_104 <> ''
            GROUP BY code_104
            HAVING COUNT(*) > 1
        )
    """).fetchone()["c"]

    print(f"\nDone!")
    print(f"  Before: {total_before}")
    print(f"  Deleted: {total_before - total_after}")
    print(f"  After: {total_after}")
    print(f"  Remaining duplicate groups: {remaining_dups}")

    conn.close()


if __name__ == "__main__":
    main()
