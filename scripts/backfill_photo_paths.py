"""Backfill candidates.photo_path from the parsed resume markdown.

The regex parser used to look for the headshot only inside the 基本資料 section.
OCR splits resumes on arbitrary headings, so the headshot regularly landed under
an unrelated one (自我介紹, 英文自傳, a project table...) and was dropped —
leaving photo_path empty for candidates whose resume does contain a photo.

app.regex_parser._extract_photo_path now scans the whole document and accepts
only Marker's `Picture_1` slot (the headshot position in a 104 resume layout).
This script re-runs that extraction over existing rows, which still reference
their markdown via source_md_path, so no re-parse of the PDFs is needed.

Usage:
    python scripts/backfill_photo_paths.py --db resume_ai.db --dry-run
    python scripts/backfill_photo_paths.py --db resume_ai.db
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.regex_parser import _extract_photo_path  # noqa: E402


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def backup_db(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{db_path.stem}.before-photo-backfill-{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def _photo_on_disk(md_path: Path, photo: str) -> bool:
    """Marker writes images into the batch dir; markdown sits one level deeper."""
    name = Path(photo).name
    for base in (md_path.parent, md_path.parent.parent):
        if (base / name).is_file():
            return True
    return False


def backfill(conn: sqlite3.Connection, *, dry_run: bool) -> dict[str, int]:
    rows = conn.execute(
        "SELECT id, name, photo_path, source_md_path FROM candidates"
    ).fetchall()

    stats = {
        "total": len(rows),
        "filled": 0,
        "unchanged": 0,
        "no_photo": 0,
        "md_missing": 0,
        "not_on_disk": 0,
        "cleared": 0,
    }
    updates: list[tuple[str, int]] = []

    for row in rows:
        md_raw = row["source_md_path"] or ""
        old = row["photo_path"] or ""
        if not md_raw:
            stats["md_missing"] += 1
            continue

        md_path = Path(md_raw)
        if not md_path.is_file():
            stats["md_missing"] += 1
            continue

        new = _extract_photo_path(md_path.read_text(encoding="utf-8", errors="ignore"))

        if new and not _photo_on_disk(md_path, new):
            # Referenced by the markdown but never written out — don't store a
            # path the API would fail to resolve.
            stats["not_on_disk"] += 1
            new = ""

        if new == old:
            stats["no_photo" if not new else "unchanged"] += 1
            continue

        if new:
            stats["filled" if not old else "cleared"] += 1
        else:
            # Old value was a non-headshot (project screenshot); drop it.
            stats["cleared"] += 1

        updates.append((new, int(row["id"])))

    if updates and not dry_run:
        conn.executemany(
            "UPDATE candidates SET photo_path=? WHERE id=?", updates
        )
        conn.commit()

    stats["updated"] = len(updates)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="resume_ai.db", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="report without writing")
    ap.add_argument("--backup-dir", default=Path("backups"), type=Path)
    args = ap.parse_args()

    if not args.db.is_file():
        print(f"error: database not found: {args.db}")
        return 1

    if not args.dry_run:
        backup = backup_db(args.db, args.backup_dir)
        print(f"backup: {backup}")

    conn = _connect(args.db)
    try:
        stats = backfill(conn, dry_run=args.dry_run)
    finally:
        conn.close()

    print(f"candidates scanned      : {stats['total']}")
    print(f"  photo_path filled in  : {stats['filled']}")
    print(f"  already correct       : {stats['unchanged']}")
    print(f"  correctly no photo    : {stats['no_photo']}")
    print(f"  replaced/cleared      : {stats['cleared']}")
    print(f"  image not on disk     : {stats['not_on_disk']}")
    print(f"  markdown unavailable  : {stats['md_missing']}")
    print(f"  rows {'to update' if args.dry_run else 'updated'}        : {stats['updated']}")
    if args.dry_run:
        print("\ndry run — no changes written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
