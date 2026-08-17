"""PDF→Markdown parser built on pdfplumber (pure Python, no GPU).

An alternative to the Marker-based DocumentParser. Marker runs layout/OCR models
on a GPU; this reads the PDF text layer directly and rebuilds the 104-format
Markdown that regex_parser expects, so it runs anywhere Python does.

Selected via PARSER_BACKEND=plumber (see parser_service).

It emits the two structures split_candidates anchors on — "## 基本資料" headings
and "| 姓/名: | ... |" table rows — plus the section headings and education
table regex_parser keys off.
"""

import logging
import os
import re
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

# Headings regex_parser splits sections on. 才能專長/自我介紹/求職條件/推薦人/附件
# matter because _parse_skills and friends locate their content by these anchors.
SECTION_HEADERS = frozenset({
    "基本資料", "聯絡方式", "工作經驗", "學歷", "專長", "語文能力",
    "自傳", "作品", "證照", "技能", "求職條件", "教育背景", "學歷背景",
    "才能專長", "自我介紹", "推薦人", "附件", "專案成就", "其他作品",
})

# A field label: a short colon-terminated run with no spaces. Scanning for ALL of
# them on a line is what splits 104's multi-column rows
# ("姓/名: 王小明 英文名字: Ming 104代碼: 300...") into one row per field.
# (?![/／]) keeps "https://..." from being read as an "https" label.
_LABEL = re.compile(r"([^\s:：]{1,12})[:：](?![/／])")

# "1. 公司名 , 2025/04/01 ~ 仍在職"
_WORK_ITEM = re.compile(r"^\d+\.\s")

# A job can also start mid-page without a leading number, e.g.
# "精誠資訊股份有限公司 , 2022/02/01 ~ 2022/06/01". Never fold across one of
# these, or the next job's company name lands in the previous job's last cell.
_JOB_BOUNDARY = re.compile(r",\s*\d{4}/\d{2}/\d{2}\s*~")

# Running headers/footers repeated on every page.
_PAGE_NOISE = re.compile(r"^\d{4}/\d{1,2}/\d{1,2}\s|履歷預覽$|^\d+/\d+$")

# Education rows are space-separated rather than label:value:
#   "1. 國立中正大學 資訊工程學系 碩士 2022/09/01~2024/06/01 台灣 畢業"
# _parse_education wants a 7-column table (#, 學校, 科系, 學歷, 就學期間, 地區, 狀況).
_EDU_ROW = re.compile(
    r"^(\d+\.)\s+(\S+)\s+(\S+)\s+(\S+)\s+"
    r"(\d{4}/\d{2}/\d{2}\s*~\s*\d{4}/\d{2}/\d{2}|\S+)\s+(\S+)\s+(\S+)\s*$"
)
_EDU_HEADER = re.compile(r"^#\s+學校\s+科系\s+學歷")

_EDU_TABLE_HEAD = (
    "| # | 學校 | 科系 | 學歷 | 就學期間 | 地區 | 狀況 |\n"
    "|---|---|---|---|---|---|---|"
)

# CJK Radicals Supplement chars NFKC leaves alone (same fixups DocumentParser uses).
_CJK_RADICAL_FIXUP = {0x2EA0: 0x6C11, 0x2ED1: 0x9577, 0x2EE9: 0x9EC3}


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).translate(_CJK_RADICAL_FIXUP)


def _split_kv_line(line: str) -> list[tuple[str, str]] | None:
    """Split "A: v1  B: v2" into [("A", "v1"), ("B", "v2")].

    Returns None when the line does not start with a label, meaning it is prose
    rather than a field row.
    """
    matches = list(_LABEL.finditer(line))
    if not matches or matches[0].start() != 0:
        return None

    pairs = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(line)
        pairs.append((m.group(1), line[start:end].strip()))
    return pairs


def page_to_markdown(text: str) -> str:
    """Convert one page of extracted text into 104-format Markdown."""
    out: list[str] = []
    last_row: int | None = None  # index in `out` of the last emitted field row

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            out.append("")
            last_row = None
            continue

        if line in SECTION_HEADERS:
            out.append(f"## {line}")
            # parse_resume_markdown finds job preferences by searching section
            # BODIES for "求職條件" (Marker leaves it in a table cell). As a
            # heading it would only appear in the section NAME, so repeat it.
            if line == "求職條件":
                out.append(f"| {line} |")
            last_row = None
            continue

        if _EDU_HEADER.match(line):
            out.append(_EDU_TABLE_HEAD)
            last_row = None
            continue

        # Must precede _WORK_ITEM: both start with a number.
        edu = _EDU_ROW.match(line)
        if edu:
            out.append("| " + " | ".join(edu.groups()) + " |")
            last_row = None
            continue

        if _WORK_ITEM.match(line) or _JOB_BOUNDARY.search(line) or _PAGE_NOISE.search(line):
            out.append(line)
            last_row = None
            continue

        pairs = _split_kv_line(line)
        if pairs:
            for label, value in pairs:
                out.append(f"| {label}: | {value} |")
            last_row = len(out) - 1
            continue

        # Continuation line. 104 wraps long values onto following lines, and also
        # puts some values on the line after their label, so either way this text
        # belongs to the row above. The guards above already stopped folding
        # across record boundaries.
        if last_row is not None:
            m = re.match(r"^\| (.+?): \| (.*) \|$", out[last_row])
            if m:
                label, value = m.group(1), m.group(2)
                merged = f"{value}<br>{line}" if value else line
                out[last_row] = f"| {label}: | {merged} |"
                continue

        out.append(line)
        last_row = None

    return "\n".join(out)


class PlumberParser:
    """pdfplumber-backed parser exposing the DocumentParser surface used by the pipeline."""

    def parse_pdf(
        self,
        pdf_path: str,
        output_dir: str,
        return_images: bool = True,
        save_images: bool = True,
        **_ignored,
    ) -> tuple[str, str, dict]:
        """Parse a PDF into 104-format Markdown.

        Mirrors DocumentParser.parse_pdf's signature and (text, md_path, images)
        return. Images are always empty: pdfplumber reads the text layer only, so
        there are no extracted figures to hand back.
        """
        import pdfplumber

        pdf_path = os.path.abspath(pdf_path)
        os.makedirs(output_dir, exist_ok=True)

        chunks: list[str] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    chunks.append(page_to_markdown(_normalize(page_text)))
                # 104 exports run to hundreds of pages; without this pdfplumber
                # retains every page's char objects and memory grows unbounded.
                page.flush_cache()

        text = "\n\n".join(chunks)
        if not text.strip():
            raise RuntimeError(
                f"pdfplumber extracted no text from {pdf_path} — it is likely a "
                "scanned/image-only PDF, which needs the Marker backend (OCR)."
            )

        md_path = os.path.join(output_dir, f"{Path(pdf_path).stem}_original.md")
        Path(md_path).write_text(text, encoding="utf-8")

        return text, md_path, {}

    def split_candidates(self, markdown: str) -> list[str]:
        """Split a multi-resume export into per-candidate chunks.

        Delegates to DocumentParser: the emitted Markdown uses the same anchors,
        so the splitting logic is shared rather than duplicated.
        """
        from app.document_parser import DocumentParser

        return DocumentParser().split_candidates(markdown)

    def convert_to_markdown(self, file_path: str, file_extension: str) -> str:
        """Convert a document to Markdown. Non-PDF types fall back to DocumentParser."""
        if file_extension.lower() != ".pdf":
            from app.document_parser import DocumentParser

            return DocumentParser().convert_to_markdown(file_path, file_extension)

        text, _, _ = self.parse_pdf(file_path, os.path.dirname(file_path))
        return text

    def cleanup(self) -> None:
        """No-op: pdfplumber holds no GPU or model state (kept for interface parity)."""
