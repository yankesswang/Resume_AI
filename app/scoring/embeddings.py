"""Embedding service for Layer 2 semantic matching.

Calls an OpenAI-compatible /v1/embeddings endpoint — LM Studio by default,
or the OpenAI API — selected per request from ``app.llm_config`` so the
provider can be switched from /llm-settings without a restart.
"""

from __future__ import annotations

import logging
import math
import os
import re
import time

import httpx

logger = logging.getLogger(__name__)

# Environment defaults. The live values come from app.llm_config, which layers
# a UI-editable document underneath these; the names stay for existing callers.
EMBEDDING_URL = os.getenv(
    "EMBEDDING_URL",
    "http://localhost:1234/v1/embeddings",
)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v1.5")


def _resolve() -> tuple[str, str, dict[str, str], float]:
    """Live endpoint / model / headers / timeout for the embedding section."""
    try:
        from app import llm_config

        return (
            llm_config.endpoint("embedding"),
            llm_config.model("embedding"),
            llm_config.headers("embedding"),
            llm_config.timeout("embedding"),
        )
    except Exception:
        return EMBEDDING_URL, EMBEDDING_MODEL, {}, 10.0


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

    url, model_name, request_headers, request_timeout = _resolve()
    payload = {
        "input": text[:8000],
        "model": model_name,
    }
    try:
        resp = httpx.post(url, json=payload, headers=request_headers, timeout=request_timeout)
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
    except Exception:
        if _embedding_available:
            logger.warning(
                "Embedding service unavailable at %s — will retry in %.0fs",
                url,
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


def compute_semantic_similarity_traced(
    candidate_text: str,
    job_text: str,
) -> tuple[float, bool]:
    """Same as :func:`compute_semantic_similarity`, plus whether it degraded.

    The second element is True when the embedding service could not be reached
    and the keyword-overlap fallback produced the number instead.  Callers that
    persist a score need this: a fallback similarity is not comparable with an
    embedding one, and without the flag the two are indistinguishable in the DB.
    """
    cand_emb = get_embedding(candidate_text)
    job_emb = get_embedding(job_text)

    if not cand_emb or not job_emb:
        logger.debug("Embedding service unavailable — using keyword overlap fallback")
        return _keyword_overlap_fallback(candidate_text, job_text), True

    sim = cosine_similarity(cand_emb, job_emb)
    # Clamp to [0, 1] — the pipeline normalises to 0-100 via * 100
    return max(0.0, round(sim, 4)), False


def compute_semantic_similarity(
    candidate_text: str,
    job_text: str,
) -> float:
    """Compute semantic similarity between candidate and job description.

    Returns a value in [0, 1].  The pipeline multiplies by 100 to convert to
    a 0-100 contribution before applying the 20% weight.
    Falls back to keyword overlap when the embedding service is unavailable.
    """
    return compute_semantic_similarity_traced(candidate_text, job_text)[0]


def _flatten(value) -> list[str]:
    """Coerce a JD field of unknown shape into a flat list of strings.

    Accepts a string, a list of strings, or a list of dicts (whose values are
    taken), which covers every requirements-block variant seen from the JD
    extractor and from hand-edited job JSON.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, dict):
        out: list[str] = []
        for v in value.values():
            out.extend(_flatten(v))
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            out.extend(_flatten(v))
        return out
    return [str(value)]


def build_job_embedding_text(job: dict) -> str:
    """Build the text to embed for a job requirement.

    Embedding the raw job JSON compresses every candidate into a narrow band
    (measured 0.49-0.79 across 3179 resumes, with strong and weak candidates
    ~0.01 apart) because boilerplate — salary, address, benefits, leave policy,
    JSON keys — dominates the vector.  Only the skill-bearing fields are kept.
    """
    parts: list[str] = []

    basic = job.get("basic_conditions", {}) or {}
    if basic.get("job_title"):
        parts.append(str(basic["job_title"]))
    for cat in basic.get("job_categories", []) or []:
        parts.append(str(cat))

    if job.get("job_summary"):
        parts.append(str(job["job_summary"]))

    for block in job.get("responsibilities", []) or []:
        if isinstance(block, dict):
            parts.append(str(block.get("category", "")))
            parts.extend(str(i) for i in block.get("items", []) or [])

    # The requirements block's shape varies: the bundled job_requirement.json
    # nests education as a dict, while an uploaded JD is extracted with plain
    # strings and free-form lists. Read every skill-bearing key defensively —
    # a shape mismatch here used to raise, and the pipeline's blanket except
    # then silently zeroed the whole 20% semantic dimension.
    reqs = job.get("requirements", {}) or {}
    if isinstance(reqs, dict):
        for key in (
            "technical_foundation", "core_competencies", "skills",
            "majors", "certifications", "others", "experience_years",
        ):
            parts.extend(_flatten(reqs.get(key)))
        edu = reqs.get("education")
        if isinstance(edu, dict):
            parts.extend(_flatten(edu.get("preferred_majors")))
            parts.extend(_flatten(edu.get("degree")))
        else:
            parts.extend(_flatten(edu))
    else:
        parts.extend(_flatten(reqs))

    parts.extend(_flatten(job.get("preferred_qualifications")))
    # Weighted tech stack names carry the strongest matching signal.
    parts.extend(str(k) for k in (job.get("tech_stack_weights", {}) or {}))

    return " ".join(p for p in parts if p.strip())


def rescale_similarity(sim: float, lo: float | None = None, hi: float | None = None) -> float:
    """Stretch a raw cosine score into [0, 1].

    Sentence-embedding cosines for resume↔job pairs occupy a narrow high band
    (~0.45-0.80 here), so feeding the raw value into a 20% weight makes that
    weight nearly constant.  Rescaling restores discrimination.
    """
    if lo is None or hi is None:
        from app.scoring.config import load
        _sem = load()["semantic"]
        lo = float(_sem["rescale_low"]) if lo is None else lo
        hi = float(_sem["rescale_high"]) if hi is None else hi
    if hi <= lo:
        return max(0.0, min(sim, 1.0))
    return max(0.0, min((sim - lo) / (hi - lo), 1.0))


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
