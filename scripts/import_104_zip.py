"""Import a 104 resume ZIP into the resume database.

Pipeline:
1. safely extract ZIP
2. parse each PDF into candidates, checkpointed per PDF
3. organize DB metadata into import_batches/import_files/candidate_dedupe_status
4. optionally run LLM tier classification and scoring

This script is intentionally non-destructive. Dedupe marks candidates; it does not delete.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path


DEFAULT_OLD_DBS = [
    "resume_ai_v1.db",
    "resume_ai_v2.db",
    "resume_ai_20260420.db",
    "resume_ai_20260429.db",
]


def _safe_extract(zip_path: Path, extract_dir: Path) -> None:
    extract_dir.mkdir(parents=True, exist_ok=True)
    root = extract_dir.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            target = (extract_dir / member.filename).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"Unsafe ZIP member path: {member.filename}")
        zf.extractall(extract_dir)


def _run(cmd: list[str], env: dict[str, str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, env=env)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _pdf_already_imported(db_path: Path, pdf_path: Path) -> bool:
    if not db_path.exists():
        return False
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT count(*) AS count FROM candidates WHERE source_pdf_path=?",
            (str(pdf_path.resolve()),),
        ).fetchone()
        return bool(row and row["count"] > 0)
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _collect_pdfs(extract_dir: Path) -> list[Path]:
    return sorted(p.resolve() for p in extract_dir.rglob("*.pdf") if p.is_file())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import and organize a 104 resume ZIP")
    parser.add_argument("zip_path", help="104 ZIP file")
    parser.add_argument("--db", default="resume_ai.db", help="Target SQLite DB")
    parser.add_argument("--batch-name", help="Import batch name; defaults to ZIP stem")
    parser.add_argument("--extract-dir", help="Extraction directory; defaults to ZIP stem")
    parser.add_argument("--output-root", help="Parsed output root; defaults to output_<ZIP stem>")
    parser.add_argument("--old-db", action="append", dest="old_dbs", help="Old DB to compare against; can repeat")
    parser.add_argument("--force-parse", action="store_true", help="Re-parse PDFs even if already imported")
    parser.add_argument("--run-llm-score", action="store_true", help="Run tier classification and batch scoring after import")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path.cwd()
    zip_path = Path(args.zip_path).expanduser().resolve()
    if not zip_path.exists():
        raise FileNotFoundError(zip_path)

    db_path = Path(args.db).expanduser().resolve()
    batch_name = args.batch_name or zip_path.stem
    extract_dir = Path(args.extract_dir).expanduser().resolve() if args.extract_dir else (root / zip_path.stem).resolve()
    output_root = Path(args.output_root).expanduser().resolve() if args.output_root else (root / f"output_{zip_path.stem}").resolve()
    old_dbs = [Path(p).expanduser().resolve() for p in (args.old_dbs or DEFAULT_OLD_DBS)]

    env = os.environ.copy()
    env["DB_PATH"] = str(db_path)

    print(f"ZIP: {zip_path}")
    print(f"DB: {db_path}")
    print(f"batch: {batch_name}")
    print(f"extract_dir: {extract_dir}")
    print(f"output_root: {output_root}")

    _safe_extract(zip_path, extract_dir)
    pdfs = _collect_pdfs(extract_dir)
    if not pdfs:
        raise RuntimeError(f"No PDF files found under {extract_dir}")
    print(f"PDF files: {len(pdfs)}")

    output_root.mkdir(parents=True, exist_ok=True)
    imported = 0
    skipped = 0
    for pdf_path in pdfs:
        if not args.force_parse and _pdf_already_imported(db_path, pdf_path):
            skipped += 1
            print(f"[SKIP] already imported: {pdf_path}")
            continue
        _run(
            [
                sys.executable,
                "scripts/batch_import.py",
                str(pdf_path),
                "--output-root",
                str(output_root),
                "--save-split-md",
            ],
            env,
        )
        imported += 1

    organize_cmd = [
        sys.executable,
        "scripts/organize_resume_db.py",
        "--db",
        str(db_path),
        "--batch-name",
        batch_name,
        "--zip-path",
        str(zip_path),
        "--output-root",
        str(output_root),
        "--notes",
        "Organized by scripts/import_104_zip.py",
    ]
    for old_db in old_dbs:
        organize_cmd.extend(["--old-db", str(old_db)])
    _run(organize_cmd, env)

    if args.run_llm_score:
        _run([sys.executable, "scripts/reclassify_tiers.py"], env)
        _run([sys.executable, "scripts/batch_score_all.py"], env)

    print("\n=== Import ZIP Summary ===")
    print(f"pdf_imported: {imported}")
    print(f"pdf_skipped: {skipped}")
    print(f"db: {db_path}")
    print(f"batch: {batch_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
