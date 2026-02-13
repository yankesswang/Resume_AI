import logging
import os
from pathlib import Path

from app.database import (
    delete_candidate_data,
    get_candidate_detail,
    insert_candidate,
    update_candidate_from_extract,
)
from app.regex_parser import parse_resume_markdown
from app.document_parser import DocumentParser

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def ingest_pdf(pdf_bytes: bytes, filename: str) -> int:
    """Full pipeline: save PDF → parse to MD → LLM extract → DB insert."""
    # Save uploaded PDF
    DATA_DIR.mkdir(exist_ok=True)
    pdf_path = DATA_DIR / filename
    pdf_path.write_bytes(pdf_bytes)

    # Parse with DocumentParser
    stem = Path(filename).stem
    out_dir = OUTPUT_DIR / stem
    out_dir.mkdir(parents=True, exist_ok=True)

    parser = DocumentParser()
    text, md_path, _ = parser.parse_pdf(str(pdf_path), str(out_dir))
    parser.cleanup()

    # LLM extraction
    extract = parse_resume_markdown(text)

    # Insert into DB
    candidate_id = insert_candidate(
        extract,
        raw_markdown=text,
        source_pdf_path=str(pdf_path),
        source_md_path=md_path,
    )
    logger.info("Ingested PDF %s → candidate %d", filename, candidate_id)
    return candidate_id


def ingest_existing_markdown(md_path: str) -> int:
    """Ingest an already-parsed markdown file via LLM → DB."""
    text = Path(md_path).read_text(encoding="utf-8")

    extract = parse_resume_markdown(text)

    # Try to find the source PDF
    stem = Path(md_path).stem.replace("_original", "")
    pdf_candidates = list(DATA_DIR.glob(f"{stem}.*"))
    source_pdf = str(pdf_candidates[0]) if pdf_candidates else ""

    candidate_id = insert_candidate(
        extract,
        raw_markdown=text,
        source_pdf_path=source_pdf,
        source_md_path=md_path,
    )
    logger.info("Ingested markdown %s → candidate %d", md_path, candidate_id)
    return candidate_id


def reparse_existing(candidate_id: int) -> int:
    """Re-run LLM extraction on stored markdown for an existing candidate."""
    detail = get_candidate_detail(candidate_id)
    if not detail:
        raise ValueError(f"Candidate {candidate_id} not found")

    markdown = detail["raw_markdown"]
    if not markdown:
        raise ValueError(f"Candidate {candidate_id} has no stored markdown")

    extract = parse_resume_markdown(markdown)

    # Delete old child records and update
    delete_candidate_data(candidate_id)
    update_candidate_from_extract(candidate_id, extract, markdown)

    logger.info("Re-parsed candidate %d", candidate_id)
    return candidate_id
