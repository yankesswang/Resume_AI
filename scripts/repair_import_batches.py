"""Repair import batch attribution after organize_resume_db.py over-assigned rows.

Older runs of scripts/organize_resume_db.py rewrote import_batch_id for *every*
candidate in the table, so re-organizing a new ZIP relabelled all previously
imported candidates into the newest batch. It also registered the older batch's
PDFs a second time under the new batch_id, leaving duplicate import_files rows.

The candidate rows themselves were never lost: source_pdf_path / source_md_path
still point at the ZIP and output root the candidate was actually parsed from.
This script uses those paths to restore the correct batch/file attribution.

Usage:
    python scripts/repair_import_batches.py --db resume_ai.db --dry-run
    python scripts/repair_import_batches.py --db resume_ai.db
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def backup_db(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{db_path.stem}.before-batch-repair-{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def _batch_keys(conn: sqlite3.Connection) -> dict[int, str]:
    """Map batch_id -> the ZIP stem that identifies its source paths."""
    keys: dict[int, str] = {}
    for row in conn.execute("SELECT id, batch_name, source_zip_path FROM import_batches"):
        stem = ""
        if row["source_zip_path"]:
            stem = Path(row["source_zip_path"]).stem
        keys[int(row["id"])] = stem or (row["batch_name"] or "")
    return keys


def _canonical_files(conn: sqlite3.Connection, batch_keys: dict[int, str]) -> dict[str, int]:
    """Map source_pdf_path -> the import_files.id that should own it.

    A PDF path belongs to the batch whose ZIP stem appears in the path. When the
    same path is registered under several batches, the row under the owning
    batch wins; ties fall back to the lowest id.
    """
    by_path: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in conn.execute(
        "SELECT id, batch_id, source_pdf_path FROM import_files ORDER BY id"
    ):
        by_path[row["source_pdf_path"]].append(row)

    canonical: dict[str, int] = {}
    for path, rows in by_path.items():
        owning = [r for r in rows if batch_keys.get(int(r["batch_id"]), "") and batch_keys[int(r["batch_id"])] in path]
        chosen = owning[0] if owning else rows[0]
        canonical[path] = int(chosen["id"])
    return canonical


def _resolve_batch(path: str, batch_keys: dict[int, str]) -> int | None:
    for batch_id, key in batch_keys.items():
        if key and key in path:
            return batch_id
    return None


def repair(conn: sqlite3.Connection, dry_run: bool) -> None:
    batch_keys = _batch_keys(conn)
    if not batch_keys:
        print("No import_batches rows; nothing to repair.")
        return

    print("batches:")
    for batch_id, key in sorted(batch_keys.items()):
        print(f"  {batch_id}: {key}")

    canonical = _canonical_files(conn, batch_keys)
    file_batch = {
        int(r["id"]): int(r["batch_id"])
        for r in conn.execute("SELECT id, batch_id FROM import_files")
    }

    # Reattribute candidates from their parse-time source paths.
    moves: dict[tuple[int, int], int] = defaultdict(int)
    updates: list[tuple[int, int | None, int]] = []
    unresolved = 0
    for row in conn.execute(
        "SELECT id, import_batch_id, import_file_id, source_pdf_path, source_md_path FROM candidates"
    ):
        path = row["source_pdf_path"] or row["source_md_path"] or ""
        target_batch = _resolve_batch(path, batch_keys)
        if target_batch is None:
            unresolved += 1
            continue
        target_file = canonical.get(row["source_pdf_path"] or "")
        if target_file is not None and file_batch.get(target_file) != target_batch:
            target_file = None
        if row["import_batch_id"] != target_batch or row["import_file_id"] != target_file:
            updates.append((target_batch, target_file, int(row["id"])))
        moves[(row["import_batch_id"], target_batch)] += 1

    print("\ncandidate batch moves (from -> to: count):")
    for (src, dst), count in sorted(moves.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        marker = "" if src == dst else "  <-- reattributed"
        print(f"  {src} -> {dst}: {count}{marker}")
    if unresolved:
        print(f"  unresolved (no matching batch in source path): {unresolved}")
    print(f"\ncandidate rows to update: {len(updates)}")

    # Duplicate import_files rows registered under a batch that does not own them.
    stale_files = [
        file_id
        for path, keep_id in canonical.items()
        for file_id, batch_id in file_batch.items()
        if file_id != keep_id
        and conn.execute(
            "SELECT source_pdf_path FROM import_files WHERE id=?", (file_id,)
        ).fetchone()["source_pdf_path"] == path
    ]
    print(f"duplicate import_files rows to delete: {len(stale_files)} {sorted(stale_files)}")

    if dry_run:
        print("\n[dry-run] no changes written.")
        return

    for target_batch, target_file, candidate_id in updates:
        conn.execute(
            "UPDATE candidates SET import_batch_id=?, import_file_id=? WHERE id=?",
            (target_batch, target_file, candidate_id),
        )

    # candidate_dedupe_status carries its own batch column; keep it in sync.
    conn.execute(
        """
        UPDATE candidate_dedupe_status
           SET import_batch_id = (
                 SELECT c.import_batch_id FROM candidates c WHERE c.id = candidate_id
               )
         WHERE EXISTS (SELECT 1 FROM candidates c WHERE c.id = candidate_id)
        """
    )

    if stale_files:
        conn.executemany(
            "DELETE FROM import_files WHERE id=?", [(f,) for f in stale_files]
        )

    # Recompute per-file and per-batch counters from the repaired attribution.
    conn.execute(
        """
        UPDATE import_files
           SET candidate_count = (
                 SELECT count(*) FROM candidates c WHERE c.import_file_id = import_files.id
               )
        """
    )
    for batch_id in batch_keys:
        counts = conn.execute(
            """
            SELECT
              (SELECT count(*) FROM import_files WHERE batch_id=?) AS total_files,
              (SELECT count(*) FROM candidates WHERE import_batch_id=?) AS total_candidates,
              (SELECT count(*) FROM candidate_dedupe_status
                WHERE import_batch_id=? AND is_unique=1) AS unique_count,
              (SELECT count(*) FROM candidate_dedupe_status
                WHERE import_batch_id=? AND is_unique=0) AS duplicate_count,
              (SELECT count(*) FROM candidate_dedupe_status
                WHERE import_batch_id=? AND dedupe_status='review') AS review_count
            """,
            (batch_id, batch_id, batch_id, batch_id, batch_id),
        ).fetchone()
        conn.execute(
            """
            UPDATE import_batches
               SET total_files=?, total_candidates=?, unique_count=?,
                   duplicate_count=?, review_count=?
             WHERE id=?
            """,
            (
                counts["total_files"],
                counts["total_candidates"],
                counts["unique_count"],
                counts["duplicate_count"],
                counts["review_count"],
                batch_id,
            ),
        )
    conn.commit()

    print("\n=== repaired batches ===")
    for row in conn.execute(
        """
        SELECT id, batch_name, total_files, total_candidates,
               unique_count, duplicate_count, review_count
          FROM import_batches ORDER BY id
        """
    ):
        print(
            f"  batch {row['id']} {row['batch_name']}: files={row['total_files']} "
            f"candidates={row['total_candidates']} unique={row['unique_count']} "
            f"dup={row['duplicate_count']} review={row['review_count']}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair import batch attribution")
    parser.add_argument("--db", default="resume_ai.db", help="Target SQLite DB")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    parser.add_argument("--backup-dir", default="backups")
    parser.add_argument("--no-backup", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    if not args.dry_run and not args.no_backup:
        print(f"Backup written: {backup_db(db_path, Path(args.backup_dir).resolve())}")

    conn = _connect(db_path)
    try:
        repair(conn, args.dry_run)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
