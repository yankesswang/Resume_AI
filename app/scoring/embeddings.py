"""Embedding service for Layer 2 semantic matching.

Uses LM Studio's /v1/embeddings endpoint for vector similarity.
"""

from __future__ import annotations

import logging
import math
import os

import httpx

logger = logging.getLogger(__name__)

EMBEDDING_URL = os.getenv(
    "EMBEDDING_URL",
    "http://localhost:1234/v1/embeddings",
)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v1.5")


_embedding_available: bool | None = None  # Circuit breaker


def get_embedding(text: str) -> list[float]:
    """Get embedding vector for a text string from LM Studio."""
    global _embedding_available
    # Circuit breaker: skip if previously failed
    if _embedding_available is False:
        return []

    payload = {
        "input": text[:8000],  # Truncate to fit model limits
        "model": EMBEDDING_MODEL,
    }
    try:
        resp = httpx.post(EMBEDDING_URL, json=payload, timeout=10.0)
        resp.raise_for_status()
        _embedding_available = True
        return resp.json()["data"][0]["embedding"]
    except Exception:
        if _embedding_available is None:
            logger.warning("Embedding service unavailable, disabling for this session")
        _embedding_available = False
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


def compute_semantic_similarity(
    candidate_text: str,
    job_text: str,
) -> float:
    """Compute semantic similarity between candidate and job description.

    Returns similarity score in 0-100 range.
    """
    cand_emb = get_embedding(candidate_text)
    job_emb = get_embedding(job_text)

    if not cand_emb or not job_emb:
        return 0.0

    sim = cosine_similarity(cand_emb, job_emb)
    # Normalize from [-1, 1] to [0, 100]
    return max(0.0, round(sim * 100, 2))


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

    return " ".join(parts)
