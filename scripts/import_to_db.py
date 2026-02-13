"""
Import resume data into resume_ai.db so the frontend can read it via /api/candidates.

Examples:
  python3 import_to_db.py --markdown-glob "output/**/*.md"
  python3 import_to_db.py --json-file candidates.json
  python3 import_to_db.py --json-file candidates.jsonl --format jsonl
  python3 import_to_db.py --json-file candidates.json --with-match
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import (
    ensure_job_requirement,
    init_db,
    insert_candidate,
    upsert_match_result,
)
from app.models import MatchResultExtract, ResumeExtract
from app.regex_parser import parse_resume_markdown


def _iter_markdown_paths(glob_pattern: str) -> list[Path]:
    paths = [p for p in Path(".").glob(glob_pattern) if p.is_file()]
    return sorted(paths)


def _guess_source_pdf(md_path: Path) -> str:
    data_dir = Path("data")
    stem = md_path.stem.replace("_original", "")
    if not data_dir.exists():
        return ""
    for candidate in data_dir.glob(f"{stem}.*"):
        if candidate.is_file():
            return str(candidate)
    return ""


def import_from_markdown(glob_pattern: str, dry_run: bool) -> int:
    md_files = _iter_markdown_paths(glob_pattern)
    if not md_files:
        print(f"No markdown files matched: {glob_pattern}")
        return 0

    inserted = 0
    for md_path in md_files:
        text = md_path.read_text(encoding="utf-8")
        extract = parse_resume_markdown(text)

        if dry_run:
            print(f"[DRY] {md_path} -> {extract.name or '(no name)'}")
            inserted += 1
            continue

        candidate_id = insert_candidate(
            extract=extract,
            raw_markdown=text,
            source_pdf_path=_guess_source_pdf(md_path),
            source_md_path=str(md_path),
        )
        inserted += 1
        print(f"[OK] id={candidate_id} name={extract.name or '(no name)'} source={md_path}")

    return inserted


def _load_json_records(file_path: Path, fmt: str) -> list[dict]:
    if fmt == "json":
        raw = json.loads(file_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            if isinstance(raw.get("candidates"), list):
                return raw["candidates"]
            return [raw]
        raise ValueError("JSON root must be object or array")

    records: list[dict] = []
    for line_no, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at line {line_no}: {exc}") from exc
        if not isinstance(item, dict):
            raise ValueError(f"JSONL line {line_no} must be an object")
        records.append(item)
    return records


def _extract_resume(record: dict) -> ResumeExtract:
    payload = record.get("extract")
    if isinstance(payload, dict):
        return ResumeExtract.model_validate(payload)
    return ResumeExtract.model_validate(record)


def _extract_match(record: dict) -> MatchResultExtract | None:
    payload = record.get("match")
    if not isinstance(payload, dict):
        return None
    return MatchResultExtract.model_validate(payload)


def import_from_json(
    json_file: Path,
    fmt: str,
    with_match: bool,
    dry_run: bool,
) -> int:
    records = _load_json_records(json_file, fmt)
    if not records:
        print(f"No records found in {json_file}")
        return 0

    job_id = None
    if with_match and not dry_run:
        # Use existing title if already present; otherwise create it.
        job_payload = {"basic_conditions": {"job_title": "Imported Job Requirement"}}
        job_id = ensure_job_requirement(
            title="Imported Job Requirement",
            source_json=json.dumps(job_payload, ensure_ascii=False),
        )

    inserted = 0
    for idx, record in enumerate(records, 1):
        if not isinstance(record, dict):
            print(f"[SKIP] record #{idx} is not an object")
            continue

        try:
            resume = _extract_resume(record)
        except Exception as exc:
            print(f"[SKIP] record #{idx} invalid ResumeExtract payload: {exc}")
            continue

        raw_markdown = str(record.get("raw_markdown", ""))
        source_pdf_path = str(record.get("source_pdf_path", ""))
        source_md_path = str(record.get("source_md_path", ""))
        match_result = _extract_match(record) if with_match else None

        if dry_run:
            print(f"[DRY] #{idx} name={resume.name or '(no name)'}")
            inserted += 1
            continue

        candidate_id = insert_candidate(
            extract=resume,
            raw_markdown=raw_markdown,
            source_pdf_path=source_pdf_path,
            source_md_path=source_md_path,
        )
        inserted += 1
        print(f"[OK] id={candidate_id} name={resume.name or '(no name)'}")

        if with_match and match_result and job_id is not None:
            upsert_match_result(candidate_id=candidate_id, job_id=job_id, result=match_result)
            print(f"     match score={match_result.overall_score}")

    return inserted


def _parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import candidates into resume_ai.db")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--markdown-glob",
        help='Glob for markdown files, e.g. "output/**/*.md"',
    )
    source.add_argument(
        "--json-file",
        help="Path to JSON/JSONL file containing candidate records",
    )
    parser.add_argument(
        "--format",
        choices=("json", "jsonl"),
        default="json",
        help="Input format for --json-file (default: json)",
    )
    parser.add_argument(
        "--with-match",
        action="store_true",
        help="If JSON records include match object, upsert into match_results",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate only, do not write to DB",
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = _parse_args(argv)
    init_db()

    if args.markdown_glob:
        inserted = import_from_markdown(args.markdown_glob, dry_run=args.dry_run)
    else:
        inserted = import_from_json(
            json_file=Path(args.json_file),
            fmt=args.format,
            with_match=args.with_match,
            dry_run=args.dry_run,
        )

    print(f"Done. processed={inserted} dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
