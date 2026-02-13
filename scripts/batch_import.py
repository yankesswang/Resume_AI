"""
Batch import resumes from PDF(s) and save directly into resume_ai.db.

Usage:
    python3 batch_import.py data/履歷預覽.pdf
    python3 batch_import.py --pdf-glob "data/*.pdf"
    python3 batch_import.py --pdf-dir data --save-split-md
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import DB_PATH, init_db, insert_candidate
from app.regex_parser import parse_resume_markdown
from app.document_parser import DocumentParser


def _safe_name(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in "-_").strip() or "candidate"


def _extract_log_name(md: str, index: int) -> str:
    name_match = re.search(r"姓/名:\s*\|\s*([^\n|]+)", md)
    if name_match:
        return name_match.group(1).strip()
    return f"candidate_{index}"


def _collect_pdfs(pdf_path: str | None, pdf_glob: str | None, pdf_dir: str | None) -> list[Path]:
    paths: list[Path] = []
    if pdf_path:
        p = Path(pdf_path).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"File not found: {p}")
        paths = [p]
    elif pdf_glob:
        paths = sorted(p.resolve() for p in Path(".").glob(pdf_glob) if p.is_file())
    elif pdf_dir:
        d = Path(pdf_dir).expanduser().resolve()
        if not d.is_dir():
            raise FileNotFoundError(f"Directory not found: {d}")
        paths = sorted(p.resolve() for p in d.glob("*.pdf") if p.is_file())

    return paths


def _split_candidates(parser: DocumentParser, text: str) -> list[str]:
    candidates = parser.split_candidates(text)
    if candidates:
        return candidates

    # Fallback split for OCR/noisy headings.
    candidates = re.split(r"(?=^#{1,6}\s*基本資料\s*$)", text, flags=re.MULTILINE)
    candidates = [c.strip() for c in candidates if c.strip()]
    if candidates:
        return candidates

    # Final fallback: treat whole markdown as one candidate.
    return [text]


def import_pdf(
    pdf_path: Path,
    output_root: Path,
    save_split_md: bool,
    dry_run: bool,
    parser: DocumentParser,
) -> tuple[int, int]:
    stem = pdf_path.stem
    output_dir = output_root / stem
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nParsing PDF: {pdf_path}")
    text, original_md_path, _ = parser.parse_pdf(str(pdf_path), str(output_dir))
    print(f"  markdown chars={len(text)} original_md={original_md_path}")

    candidates_md = _split_candidates(parser, text)
    print(f"  detected candidates={len(candidates_md)}")

    inserted = 0
    failed = 0
    for i, md in enumerate(candidates_md, 1):
        log_name = _extract_log_name(md, i)
        md_path = str(original_md_path)

        if save_split_md:
            candidate_dir = output_dir / f"candidate_{i}_{_safe_name(log_name)}"
            candidate_dir.mkdir(parents=True, exist_ok=True)
            split_md = candidate_dir / f"{_safe_name(log_name)}.md"
            split_md.write_text(md, encoding="utf-8")
            md_path = str(split_md)

        try:
            extract = parse_resume_markdown(md)
            if dry_run:
                print(f"  [DRY] [{i}] {extract.name or log_name}")
                inserted += 1
                continue

            candidate_id = insert_candidate(
                extract=extract,
                raw_markdown=md,
                source_pdf_path=str(pdf_path),
                source_md_path=md_path,
            )
            inserted += 1
            print(f"  [OK]  [{i}] id={candidate_id} name={extract.name or log_name}")
        except Exception as exc:
            failed += 1
            print(f"  [ERR] [{i}] {log_name}: {exc}")

    return inserted, failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch import PDF resumes into resume_ai.db")
    parser.add_argument("pdf_path", nargs="?", help="Single PDF path")
    parser.add_argument("--pdf-glob", help='Glob for PDFs, e.g. "data/*.pdf"')
    parser.add_argument("--pdf-dir", help="Directory containing PDFs")
    parser.add_argument("--output-root", default="output", help="Base output directory")
    parser.add_argument(
        "--save-split-md",
        action="store_true",
        help="Save split candidate markdown files under output/",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse only; do not write DB")
    args = parser.parse_args()

    selected = [bool(args.pdf_path), bool(args.pdf_glob), bool(args.pdf_dir)]
    if sum(selected) != 1:
        parser.error("Provide exactly one source: pdf_path OR --pdf-glob OR --pdf-dir")

    try:
        pdfs = _collect_pdfs(args.pdf_path, args.pdf_glob, args.pdf_dir)
    except FileNotFoundError as exc:
        print(str(exc))
        return 1

    if not pdfs:
        print("No PDF files found.")
        return 1

    init_db()
    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    parser_obj = DocumentParser()
    total_inserted = 0
    total_failed = 0
    try:
        for pdf in pdfs:
            inserted, failed = import_pdf(
                pdf_path=pdf,
                output_root=output_root,
                save_split_md=args.save_split_md,
                dry_run=args.dry_run,
                parser=parser_obj,
            )
            total_inserted += inserted
            total_failed += failed
    finally:
        parser_obj.cleanup()

    print("\n=== Summary ===")
    print(f"DB path: {DB_PATH}")
    print(f"PDF files processed: {len(pdfs)}")
    print(f"Candidates processed: {total_inserted + total_failed}")
    print(f"Candidates imported: {total_inserted}")
    print(f"Candidates failed: {total_failed}")
    print(f"dry_run: {args.dry_run}")
    return 0 if total_failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
