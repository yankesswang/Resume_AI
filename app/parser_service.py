import base64
import logging
import os
import unicodedata
from pathlib import Path

import httpx

from app.database import (
    delete_candidate_data,
    get_candidate_detail,
    insert_candidate,
    update_candidate_from_extract,
)
from app.regex_parser import parse_resume_markdown

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

# Set WORKER_URL to offload PDF parsing to a remote machine, e.g. "http://192.168.1.100:8100"
WORKER_URL = os.getenv("WORKER_URL", "")

# CJK Radicals Supplement chars that NFKC doesn't normalize
_CJK_RADICAL_FIXUP = str.maketrans({
    "\u2EA0": "\u6C11",  # ⺠ → 民
    "\u2ED1": "\u9577",  # ⻑ → 長
    "\u2EE9": "\u9EC3",  # ⻩ → 黃
})


def _normalize_cjk(text: str) -> str:
    """Normalize CJK Compatibility Ideographs and Radicals to standard forms."""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_CJK_RADICAL_FIXUP)
    return text


def _parse_pdf_remote(pdf_bytes: bytes, filename: str, out_dir: Path) -> tuple[str, str]:
    """Send PDF to remote worker for parsing, save results locally."""
    url = WORKER_URL.rstrip("/") + "/parse-pdf"
    logger.info("Sending %s to remote worker at %s", filename, url)

    resp = httpx.post(
        url,
        files={"file": (filename, pdf_bytes, "application/pdf")},
        timeout=600.0,
    )
    if resp.status_code != 200:
        logger.error("Worker error %d: %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()

    data = resp.json()
    text = data["markdown"]

    # Save images returned by the worker
    for img_name, img_b64 in data.get("images", {}).items():
        img_bytes = base64.b64decode(img_b64)
        (out_dir / img_name).write_bytes(img_bytes)

    # Save markdown locally
    stem = Path(filename).stem
    md_path = str(out_dir / f"{stem}_original.md")
    Path(md_path).write_text(text, encoding="utf-8")

    return text, md_path


def _parse_pdf_local(pdf_path: str, out_dir: str) -> tuple[str, str]:
    """Parse PDF locally using Marker (requires GPU / heavy compute)."""
    from app.document_parser import DocumentParser

    parser = DocumentParser()
    text, md_path, _ = parser.parse_pdf(pdf_path, out_dir)
    parser.cleanup()
    return text, md_path


def ingest_pdf(pdf_bytes: bytes, filename: str) -> int:
    """Full pipeline: save PDF → parse to MD → regex extract → DB insert."""
    # Save uploaded PDF
    DATA_DIR.mkdir(exist_ok=True)
    pdf_path = DATA_DIR / filename
    pdf_path.write_bytes(pdf_bytes)

    stem = Path(filename).stem
    out_dir = OUTPUT_DIR / stem
    out_dir.mkdir(parents=True, exist_ok=True)

    # Parse PDF: remote worker or local
    if WORKER_URL:
        text, md_path = _parse_pdf_remote(pdf_bytes, filename, out_dir)
    else:
        text, md_path = _parse_pdf_local(str(pdf_path), str(out_dir))

    text = _normalize_cjk(text)

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
    text = _normalize_cjk(text)

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

    markdown = _normalize_cjk(markdown)
    extract = parse_resume_markdown(markdown)

    # Delete old child records and update
    delete_candidate_data(candidate_id)
    update_candidate_from_extract(candidate_id, extract, markdown)

    logger.info("Re-parsed candidate %d", candidate_id)
    return candidate_id
