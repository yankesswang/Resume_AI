"""
Remote PDF parsing worker service.

Run this on a powerful machine with GPU to offload Marker PDF→Markdown conversion.

Usage:
    uv run python -m app.worker                                  # listens on 0.0.0.0:8100
    uv run python -m uvicorn app.worker:app --host 0.0.0.0 --port 8100
"""

import base64
import io
import logging
import tempfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException

from app.document_parser import DocumentParser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="PDF Parse Worker")


@app.post("/parse-pdf")
async def parse_pdf(file: UploadFile = File(...)):
    """
    Receive a PDF file, run Marker conversion, return markdown + images.

    Returns JSON:
        { "markdown": "...", "images": { "filename.jpeg": "<base64>", ... } }
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    pdf_bytes = await file.read()

    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path = Path(tmp_dir) / file.filename
        pdf_path.write_bytes(pdf_bytes)

        parser = DocumentParser()
        try:
            text, _, images = parser.parse_pdf(
                str(pdf_path), tmp_dir, return_images=True, save_images=False,
            )
        except Exception as e:
            logger.exception("Marker parsing failed")
            raise HTTPException(status_code=500, detail=f"Parsing failed: {e}")
        finally:
            parser.cleanup()

    # Encode PIL images as base64
    images_b64: dict[str, str] = {}
    for name, img in (images or {}).items():
        buf = io.BytesIO()
        fmt = "JPEG" if name.lower().endswith((".jpg", ".jpeg")) else "PNG"
        img.save(buf, format=fmt)
        images_b64[name] = base64.b64encode(buf.getvalue()).decode()

    return {"markdown": text, "images": images_b64}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8100)
