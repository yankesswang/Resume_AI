"""Embedding service for Layer 2 semantic matching.

Uses LM Studio's /v1/embeddings endpoint for vector similarity.
"""

from __future__ import annotations

import logging
import math
import os
import re
import time

import httpx

logger = logging.getLogger(__name__)

EMBEDDING_URL = os.getenv(
    "EMBEDDING_URL",
    "http://localhost:1234/v1/embeddings",
)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v1.5")

_RETRY_AFTER = 60.0  # seconds before retrying a failed embedding service

_embedding_available: bool = True
_embedding_failed_at: float = 0.0


def get_embedding(text: str) -> list[float]:
    """Get embedding vector for a text string from LM Studio.

    Uses a time-based backoff: if the service failed recently, skip the
    request and return [] until _RETRY_AFTER seconds have elapsed.
    """
    global _embedding_available, _embedding_failed_at

    if not _embedding_available:
        if time.monotonic() - _embedding_failed_at < _RETRY_AFTER:
            return []
        # Retry window elapsed — try again
        _embedding_available = True

    payload = {
        "input": text[:8000],
        "model": EMBEDDING_MODEL,
    }
    try:
        resp = httpx.post(EMBEDDING_URL, json=payload, timeout=10.0)
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
    except Exception:
        if _embedding_available:
            logger.warning(
                "Embedding service unavailable at %s — will retry in %.0fs",
                EMBEDDING_URL,
                _RETRY_AFTER,
            )
        _embedding_available = False
        _embedding_failed_at = time.monotonic()
        return []


def batch_embed(texts: list[str]) -> list[list[float]]:
    """Get embeddings for multiple texts."""
    return [get_embedding(t) for t in texts]


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _keyword_overlap_fallback(text_a: str, text_b: str) -> float:
    """Keyword-overlap fallback when embedding service is unavailable.

    Uses asymmetric coverage of the shorter text against the longer one.
    Handles both English (word tokens) and Chinese (2-char bigrams) so the
    score is meaningful for bilingual resumes and job descriptions.

    Returns a value in [0, 1] consistent with the embedding path.
    """
    _CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]+")

    def tokenize(t: str) -> set[str]:
        tokens: set[str] = set()
        # English / alphanumeric words (≥3 chars, case-insensitive)
        tokens.update(w.lower() for w in re.split(r"[\s\W]+", t) if len(w) >= 3 and re.search(r"[a-zA-Z0-9]", w))
        # Chinese character bigrams — each 2-char window is a "word"
        for segment in _CJK.findall(t):
            tokens.update(segment[i:i+2] for i in range(len(segment) - 1))
        return tokens

    tokens_a = tokenize(text_a)
    tokens_b = tokenize(text_b)

    if not tokens_a or not tokens_b:
        return 0.5  # neutral when no usable text

    # Asymmetric coverage: what fraction of the shorter (job) text's tokens
    # appear in the longer (candidate) text.
    ref, other = (tokens_a, tokens_b) if len(tokens_a) <= len(tokens_b) else (tokens_b, tokens_a)
    coverage = len(ref & other) / len(ref)

    # Coverage is typically 0.15-0.45 for a well-matched pair.
    # Map to [0.15, 0.80]: baseline 0.15 + scaled contribution.
    return min(round(0.15 + coverage * 1.3, 3), 0.80)


def compute_semantic_similarity(
    candidate_text: str,
    job_text: str,
) -> float:
    """Compute semantic similarity between candidate and job description.

    Returns a value in [0, 1].  The pipeline multiplies by 100 to convert to
    a 0-100 contribution before applying the 20% weight.
    Falls back to keyword overlap when the embedding service is unavailable.
    """
    cand_emb = get_embedding(candidate_text)
    job_emb = get_embedding(job_text)

    if not cand_emb or not job_emb:
        logger.debug("Embedding service unavailable — using keyword overlap fallback")
        return _keyword_overlap_fallback(candidate_text, job_text)

    sim = cosine_similarity(cand_emb, job_emb)
    # Clamp to [0, 1] — the pipeline normalises to 0-100 via * 100
    return max(0.0, round(sim, 4))


def build_candidate_embedding_text(candidate: dict) -> str:
    """Build the text to embed for a candidate from their structured data."""
    parts = []

    # Skills
    skill_tags = candidate.get("skill_tags", [])
    if isinstance(skill_tags, str):
        parts.append(skill_tags)
    else:
        parts.append(" ".join(skill_tags))

    # Work experience descriptions
    for we in candidate.get("work_experiences", []):
        desc = we.get("job_description", "") or ""
        title = we.get("job_title", "") or ""
        skills = we.get("job_skills", "") or ""
        parts.append(f"{title} {desc} {skills}")

    # Self introduction
    intro = candidate.get("self_introduction", "") or ""
    if intro:
        parts.append(intro)

    # Raw markdown — primary source when structured fields are sparse
    raw_markdown = candidate.get("raw_markdown", "") or ""
    if raw_markdown:
        # Truncate to avoid overwhelming the embedding model
        parts.append(raw_markdown[:4000])

    return " ".join(parts)
