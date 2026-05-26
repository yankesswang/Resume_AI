"""Organize a resume SQLite DB around import batches and dedupe status.

This is a non-destructive maintenance script:
- adds durable import_batches/import_files metadata tables
- annotates candidates with batch/file/hash metadata
- recomputes candidate_dedupe_status against old DB snapshots
- creates convenience views for unique/duplicate candidates

It does not delete candidates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OLD_DBS = [
    "resume_ai_v1.db",
    "resume_ai_v2.db",
    "resume_ai_20260420.db",
    "resume_ai_20260429.db",
]

PLACEHOLDER_PHONES = {
    "0900000000",
    "0912345678",
    "0987654321",
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _add_column(conn: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
    if name not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _norm_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _norm_phone(value: Any) -> str:
    phone = re.sub(r"\D+", "", str(value or ""))
    if len(phone) < 8 or phone in PLACEHOLDER_PHONES:
        return ""
    if len(set(phone)) == 1:
        return ""
    return phone


def _json_list(values: list[Any] | set[Any]) -> str:
    return json.dumps(sorted({str(v) for v in values if v}), ensure_ascii=False)


def backup_db(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{db_path.stem}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db_path) + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, Path(str(backup_path) + suffix))
    return backup_path


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS import_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_name TEXT NOT NULL,
            source_zip_path TEXT,
            zip_sha256 TEXT,
            status TEXT NOT NULL DEFAULT 'organized',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at TEXT,
            total_files INTEGER NOT NULL DEFAULT 0,
            total_candidates INTEGER NOT NULL DEFAULT 0,
            unique_count INTEGER NOT NULL DEFAULT 0,
            duplicate_count INTEGER NOT NULL DEFAULT 0,
            review_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS import_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            source_pdf_path TEXT NOT NULL,
            pdf_sha256 TEXT,
            original_md_path TEXT,
            output_dir TEXT,
            parse_status TEXT NOT NULL DEFAULT 'parsed',
            candidate_count INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(batch_id) REFERENCES import_batches(id) ON DELETE CASCADE
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_import_files_batch_pdf
            ON import_files(batch_id, source_pdf_path);
        CREATE INDEX IF NOT EXISTS idx_import_batches_zip_sha
            ON import_batches(zip_sha256);
        """
    )

    for name, ddl in (
        ("import_batch_id", "INTEGER"),
        ("import_file_id", "INTEGER"),
        ("raw_md_sha256", "TEXT"),
        ("parser_version", "TEXT"),
    ):
        _add_column(conn, "candidates", name, ddl)

    if not _table_exists(conn, "candidate_dedupe_status"):
        conn.execute(
            """
            CREATE TABLE candidate_dedupe_status (
                candidate_id INTEGER PRIMARY KEY,
                is_unique INTEGER NOT NULL DEFAULT 0,
                strong_match_count INTEGER NOT NULL DEFAULT 0,
                match_types TEXT NOT NULL DEFAULT '[]',
                matched_old_dbs TEXT NOT NULL DEFAULT '[]',
                matched_old_refs TEXT NOT NULL DEFAULT '[]',
                weak_name_birth_count INTEGER NOT NULL DEFAULT 0,
                internal_duplicate_key TEXT,
                generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
            )
            """
        )

    for name, ddl in (
        ("import_batch_id", "INTEGER"),
        ("dedupe_status", "TEXT"),
        ("confidence", "TEXT"),
        ("primary_match_type", "TEXT"),
        ("matched_candidate_ids", "TEXT NOT NULL DEFAULT '[]'"),
        ("reason", "TEXT"),
    ):
        _add_column(conn, "candidate_dedupe_status", name, ddl)

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_candidate_dedupe_unique ON candidate_dedupe_status(is_unique)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_candidate_dedupe_status ON candidate_dedupe_status(dedupe_status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_candidates_import_batch ON candidates(import_batch_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_candidates_import_file ON candidates(import_file_id)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(id, applied_at) VALUES (?, ?)",
        ("20260526_import_batch_dedupe_metadata", _now()),
    )


def upsert_batch(
    conn: sqlite3.Connection,
    batch_name: str,
    zip_path: Path | None,
    notes: str,
) -> int:
    zip_abs = str(zip_path.resolve()) if zip_path else ""
    zip_sha = _sha256_file(zip_path) if zip_path and zip_path.exists() else ""

    row = None
    if zip_sha:
        row = conn.execute(
            "SELECT id FROM import_batches WHERE zip_sha256=?", (zip_sha,)
        ).fetchone()
    if row is None and zip_abs:
        row = conn.execute(
            "SELECT id FROM import_batches WHERE source_zip_path=?", (zip_abs,)
        ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT id FROM import_batches WHERE batch_name=? ORDER BY id LIMIT 1",
            (batch_name,),
        ).fetchone()

    if row:
        batch_id = int(row["id"])
        conn.execute(
            """
            UPDATE import_batches
               SET batch_name=?, source_zip_path=?, zip_sha256=?, status='organized',
                   finished_at=?, notes=?
             WHERE id=?
            """,
            (batch_name, zip_abs, zip_sha, _now(), notes, batch_id),
        )
        return batch_id

    cur = conn.execute(
        """
        INSERT INTO import_batches(batch_name, source_zip_path, zip_sha256, status, finished_at, notes)
        VALUES (?, ?, ?, 'organized', ?, ?)
        """,
        (batch_name, zip_abs, zip_sha, _now(), notes),
    )
    return int(cur.lastrowid)


def populate_import_files(
    conn: sqlite3.Connection,
    batch_id: int,
    output_root: Path | None,
) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT source_pdf_path, count(*) AS candidate_count, min(source_md_path) AS first_md
          FROM candidates
         WHERE source_pdf_path IS NOT NULL AND trim(source_pdf_path) != ''
         GROUP BY source_pdf_path
         ORDER BY source_pdf_path
        """
    ).fetchall()

    result: dict[str, int] = {}
    for row in rows:
        pdf_path = Path(row["source_pdf_path"])
        pdf_abs = str(pdf_path)
        pdf_sha = _sha256_file(pdf_path) if pdf_path.exists() else ""
        md_path = str(row["first_md"] or "")
        if output_root and pdf_path.stem:
            output_dir = str((output_root / pdf_path.stem).resolve())
        else:
            output_dir = str(Path(md_path).parent) if md_path else ""
        conn.execute(
            """
            INSERT INTO import_files(
                batch_id, source_pdf_path, pdf_sha256, original_md_path,
                output_dir, parse_status, candidate_count
            )
            VALUES (?, ?, ?, ?, ?, 'parsed', ?)
            ON CONFLICT(batch_id, source_pdf_path) DO UPDATE SET
                pdf_sha256=excluded.pdf_sha256,
                original_md_path=excluded.original_md_path,
                output_dir=excluded.output_dir,
                parse_status=excluded.parse_status,
                candidate_count=excluded.candidate_count
            """,
            (batch_id, pdf_abs, pdf_sha, md_path, output_dir, int(row["candidate_count"])),
        )
        file_id = conn.execute(
            "SELECT id FROM import_files WHERE batch_id=? AND source_pdf_path=?",
            (batch_id, pdf_abs),
        ).fetchone()["id"]
        result[pdf_abs] = int(file_id)
    return result


def update_candidate_source_metadata(
    conn: sqlite3.Connection,
    batch_id: int,
    file_ids: dict[str, int],
    parser_version: str,
) -> None:
    rows = conn.execute("SELECT id, source_pdf_path, raw_markdown FROM candidates").fetchall()
    for row in rows:
        conn.execute(
            """
            UPDATE candidates
               SET import_batch_id=?,
                   import_file_id=?,
                   raw_md_sha256=?,
                   parser_version=?
             WHERE id=?
            """,
            (
                batch_id,
                file_ids.get(str(row["source_pdf_path"] or "")),
                _sha256_text(row["raw_markdown"]),
                parser_version,
                int(row["id"]),
            ),
        )


def _load_old_rows(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists() or db_path.stat().st_size == 0:
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "candidates"):
            return []
        rows = conn.execute(
            """
            SELECT id, name, code_104, email, mobile1, mobile2, birth_year, school
              FROM candidates
            """
        ).fetchall()
        return [{**dict(r), "old_db": db_path.name} for r in rows]
    finally:
        conn.close()


def recompute_dedupe(
    conn: sqlite3.Connection,
    batch_id: int,
    old_dbs: list[Path],
) -> None:
    current_rows = [dict(r) for r in conn.execute(
        """
        SELECT id, name, code_104, email, mobile1, mobile2, birth_year, school
          FROM candidates
        """
    ).fetchall()]

    old_rows: list[dict[str, Any]] = []
    for db_path in old_dbs:
        old_rows.extend(_load_old_rows(db_path))

    old_maps: dict[str, dict[str, list[dict[str, Any]]]] = {
        "code_104": {},
        "email": {},
        "mobile": {},
        "name_birth": {},
    }

    for row in old_rows:
        keys = {
            "code_104": _norm_text(row.get("code_104")),
            "email": _norm_text(row.get("email")),
            "mobile": _norm_phone(row.get("mobile1")) or _norm_phone(row.get("mobile2")),
            "name_birth": f"{_norm_text(row.get('name'))}|{_norm_text(row.get('birth_year'))}",
        }
        for key_type, key in keys.items():
            if key and key != "|":
                old_maps[key_type].setdefault(key, []).append(row)

    current_key_rows: list[tuple[str, str, int]] = []
    for row in current_rows:
        for key_type, key in (
            ("code_104", _norm_text(row.get("code_104"))),
            ("email", _norm_text(row.get("email"))),
            ("mobile", _norm_phone(row.get("mobile1"))),
            ("mobile", _norm_phone(row.get("mobile2"))),
        ):
            if key:
                current_key_rows.append((key_type, key, int(row["id"])))

    key_to_ids: dict[tuple[str, str], set[int]] = {}
    for key_type, key, candidate_id in current_key_rows:
        key_to_ids.setdefault((key_type, key), set()).add(candidate_id)

    internal_dup_by_id: dict[int, set[str]] = {}
    for (key_type, key), ids in key_to_ids.items():
        if len(ids) > 1:
            for candidate_id in ids:
                internal_dup_by_id.setdefault(candidate_id, set()).add(f"{key_type}:{key}")

    generated_at = _now()
    for row in current_rows:
        candidate_id = int(row["id"])
        strong_matches: list[dict[str, Any]] = []
        match_types: set[str] = set()

        lookup_keys = {
            "code_104": _norm_text(row.get("code_104")),
            "email": _norm_text(row.get("email")),
            "mobile": _norm_phone(row.get("mobile1")) or _norm_phone(row.get("mobile2")),
        }
        for match_type, key in lookup_keys.items():
            if not key:
                continue
            matches = old_maps[match_type].get(key, [])
            if matches:
                match_types.add(match_type)
                strong_matches.extend(matches)

        weak_key = f"{_norm_text(row.get('name'))}|{_norm_text(row.get('birth_year'))}"
        weak_matches = old_maps["name_birth"].get(weak_key, []) if weak_key != "|" else []

        seen_refs: set[str] = set()
        matched_refs: list[str] = []
        matched_ids: list[str] = []
        matched_dbs: set[str] = set()
        for match in strong_matches:
            ref = f"{match['old_db']}#{match['id']}:{match.get('name') or ''}"
            if ref in seen_refs:
                continue
            seen_refs.add(ref)
            matched_refs.append(ref)
            matched_ids.append(f"{match['old_db']}#{match['id']}")
            matched_dbs.add(match["old_db"])

        if matched_refs:
            dedupe_status = "duplicate"
            confidence = "exact"
            is_unique = 0
            primary_match_type = sorted(match_types)[0] if match_types else "strong"
            reason = f"Matched previous records by {', '.join(sorted(match_types))}"
        elif weak_matches:
            dedupe_status = "review"
            confidence = "weak"
            is_unique = 1
            primary_match_type = "name_birth"
            reason = "No strong match, but name and birth year matched previous records"
        else:
            dedupe_status = "unique"
            confidence = "none"
            is_unique = 1
            primary_match_type = ""
            reason = "No previous record matched by code_104, email, or mobile"

        conn.execute(
            """
            INSERT INTO candidate_dedupe_status(
                candidate_id, import_batch_id, is_unique, dedupe_status, confidence,
                strong_match_count, match_types, primary_match_type, matched_old_dbs,
                matched_old_refs, matched_candidate_ids, weak_name_birth_count,
                internal_duplicate_key, reason, generated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(candidate_id) DO UPDATE SET
                import_batch_id=excluded.import_batch_id,
                is_unique=excluded.is_unique,
                dedupe_status=excluded.dedupe_status,
                confidence=excluded.confidence,
                strong_match_count=excluded.strong_match_count,
                match_types=excluded.match_types,
                primary_match_type=excluded.primary_match_type,
                matched_old_dbs=excluded.matched_old_dbs,
                matched_old_refs=excluded.matched_old_refs,
                matched_candidate_ids=excluded.matched_candidate_ids,
                weak_name_birth_count=excluded.weak_name_birth_count,
                internal_duplicate_key=excluded.internal_duplicate_key,
                reason=excluded.reason,
                generated_at=excluded.generated_at
            """,
            (
                candidate_id,
                batch_id,
                is_unique,
                dedupe_status,
                confidence,
                len(matched_refs),
                _json_list(match_types),
                primary_match_type,
                _json_list(matched_dbs),
                json.dumps(matched_refs, ensure_ascii=False),
                json.dumps(matched_ids, ensure_ascii=False),
                len({f"{m['old_db']}#{m['id']}" for m in weak_matches}),
                ";".join(sorted(internal_dup_by_id.get(candidate_id, set()))) or None,
                reason,
                generated_at,
            ),
        )


def create_views(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP VIEW IF EXISTS v_candidates_with_dedupe;
        CREATE VIEW v_candidates_with_dedupe AS
        SELECT c.id, c.name, c.code_104, c.email, c.mobile1, c.birth_year,
               c.school, c.major, c.import_batch_id, c.import_file_id,
               c.raw_md_sha256, c.parser_version,
               b.batch_name, f.source_pdf_path,
               d.is_unique, d.dedupe_status, d.confidence, d.strong_match_count,
               d.match_types, d.primary_match_type, d.matched_old_dbs,
               d.weak_name_birth_count, d.internal_duplicate_key, d.reason,
               m.overall_score, m.s_ai, m.m_eng, m.s_total
          FROM candidates c
          LEFT JOIN import_batches b ON c.import_batch_id = b.id
          LEFT JOIN import_files f ON c.import_file_id = f.id
          LEFT JOIN candidate_dedupe_status d ON c.id = d.candidate_id
          LEFT JOIN match_results m ON c.id = m.candidate_id;

        DROP VIEW IF EXISTS v_unique_candidates;
        CREATE VIEW v_unique_candidates AS
        SELECT * FROM v_candidates_with_dedupe WHERE is_unique = 1;

        DROP VIEW IF EXISTS v_duplicate_candidates;
        CREATE VIEW v_duplicate_candidates AS
        SELECT * FROM v_candidates_with_dedupe WHERE is_unique = 0;
        """
    )


def update_batch_counts(conn: sqlite3.Connection, batch_id: int) -> None:
    counts = conn.execute(
        """
        SELECT
          (SELECT count(*) FROM import_files WHERE batch_id=?) AS total_files,
          (SELECT count(*) FROM candidates WHERE import_batch_id=?) AS total_candidates,
          (SELECT count(*) FROM candidate_dedupe_status WHERE import_batch_id=? AND is_unique=1) AS unique_count,
          (SELECT count(*) FROM candidate_dedupe_status WHERE import_batch_id=? AND is_unique=0) AS duplicate_count,
          (SELECT count(*) FROM candidate_dedupe_status WHERE import_batch_id=? AND dedupe_status='review') AS review_count
        """,
        (batch_id, batch_id, batch_id, batch_id, batch_id),
    ).fetchone()
    conn.execute(
        """
        UPDATE import_batches
           SET total_files=?, total_candidates=?, unique_count=?,
               duplicate_count=?, review_count=?, finished_at=?
         WHERE id=?
        """,
        (
            counts["total_files"],
            counts["total_candidates"],
            counts["unique_count"],
            counts["duplicate_count"],
            counts["review_count"],
            _now(),
            batch_id,
        ),
    )


def print_summary(conn: sqlite3.Connection, batch_id: int) -> None:
    print("\n=== Organized DB Summary ===")
    batch = conn.execute("SELECT * FROM import_batches WHERE id=?", (batch_id,)).fetchone()
    print(f"batch_id: {batch_id}")
    print(f"batch_name: {batch['batch_name']}")
    print(f"total_files: {batch['total_files']}")
    print(f"total_candidates: {batch['total_candidates']}")
    print(f"unique_count: {batch['unique_count']}")
    print(f"duplicate_count: {batch['duplicate_count']}")
    print(f"review_count: {batch['review_count']}")

    print("\ndedupe_status:")
    for row in conn.execute(
        """
        SELECT dedupe_status, count(*) AS count
          FROM candidate_dedupe_status
         WHERE import_batch_id=?
         GROUP BY dedupe_status
         ORDER BY dedupe_status
        """,
        (batch_id,),
    ):
        print(f"  {row['dedupe_status']}: {row['count']}")

    print("\nviews:")
    for view in ("v_candidates_with_dedupe", "v_unique_candidates", "v_duplicate_candidates"):
        count = conn.execute(f"SELECT count(*) AS count FROM {view}").fetchone()["count"]
        print(f"  {view}: {count}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Organize resume DB import/dedupe metadata")
    parser.add_argument("--db", required=True, help="Target SQLite DB")
    parser.add_argument("--batch-name", required=True, help="Human-readable import batch name")
    parser.add_argument("--zip-path", help="Source 104 ZIP path")
    parser.add_argument("--output-root", help="Output root for parsed markdown/images")
    parser.add_argument("--parser-version", default="marker-regex-20260526")
    parser.add_argument("--notes", default="")
    parser.add_argument("--old-db", action="append", dest="old_dbs", help="Old DB to compare against; can repeat")
    parser.add_argument("--backup-dir", default="backups")
    parser.add_argument("--no-backup", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    root = Path.cwd()
    old_dbs = [Path(p).expanduser().resolve() for p in (args.old_dbs or DEFAULT_OLD_DBS)]
    old_dbs = [p if p.is_absolute() else (root / p).resolve() for p in old_dbs]
    zip_path = Path(args.zip_path).expanduser().resolve() if args.zip_path else None
    output_root = Path(args.output_root).expanduser().resolve() if args.output_root else None

    if not args.no_backup:
        backup_path = backup_db(db_path, Path(args.backup_dir).expanduser().resolve())
        print(f"Backup written: {backup_path}")

    conn = _connect(db_path)
    try:
        ensure_schema(conn)
        batch_id = upsert_batch(conn, args.batch_name, zip_path, args.notes)
        file_ids = populate_import_files(conn, batch_id, output_root)
        update_candidate_source_metadata(conn, batch_id, file_ids, args.parser_version)
        recompute_dedupe(conn, batch_id, old_dbs)
        create_views(conn)
        update_batch_counts(conn, batch_id)
        conn.commit()
        print_summary(conn, batch_id)
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
