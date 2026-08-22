"""Graceful degradation when the LLM or embedding service fails.

The AI tier carries 35% of the final score, so what happens when LM Studio is
down is not a corner case — it decides whether an outage silently reshuffles the
ranking or is surfaced. Two independent fallback layers exist:

* ``experience.classify_experience_tier_llm`` swallows its own LLM errors and
  returns a keyword-only result (``tier_source`` stays ``"keyword"``).
* ``pipeline._classify_tier`` catches anything that escapes that, including an
  import-time failure.

``run_full_scoring`` must notice either one and record ``llm_tier_fallback`` in
``degraded_reasons`` rather than passing a weaker score off as a full one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import EnhancedMatchResult
from app.scoring import pipeline
from app.scoring.pipeline import DEGRADED_EMBEDDING, DEGRADED_LLM_TIER, _classify_tier

AI_WORK = [
    {
        "job_description": (
            "Built a RAG pipeline with a Milvus vector database and fine-tuned "
            "Llama 3 with LoRA. Deployed with FastAPI behind Docker."
        ),
        "job_title": "AI Engineer",
        "job_skills": "Python, PyTorch, LangChain, RAG, Docker",
    }
]
AI_TAGS = ["Python", "PyTorch", "LangChain", "RAG", "Docker", "FastAPI"]


class _BoomConn:
    """Any DB use raises — stands in for a broken connection."""

    def execute(self, *a, **k):
        raise RuntimeError("db exploded")


# ---------------------------------------------------------------------------
# _classify_tier: the outer safety net
# ---------------------------------------------------------------------------
def test_classify_tier_falls_back_when_llm_raises(monkeypatch):
    """An exception escaping the LLM path must yield a keyword classification."""

    def boom(*args, **kwargs):
        raise RuntimeError("LM Studio unreachable")

    monkeypatch.setattr(
        "app.scoring.experience.classify_experience_tier_llm", boom
    )

    detail = _classify_tier(AI_WORK, AI_TAGS, "", candidate_id=1, db_conn=object())

    # Fell back rather than propagating.
    assert detail.tier_source == "keyword"
    # And the fallback still did real work: the RAG/LoRA evidence is scored.
    assert detail.tier >= 2, f"keyword fallback lost the AI signal (tier={detail.tier})"
    assert detail.score > 0


def test_classify_tier_fallback_is_not_silent(monkeypatch, caplog):
    """The operator needs a log line; a degraded ranking must be explainable."""

    def boom(*args, **kwargs):
        raise RuntimeError("LM Studio unreachable")

    monkeypatch.setattr("app.scoring.experience.classify_experience_tier_llm", boom)

    with caplog.at_level("WARNING"):
        _classify_tier(AI_WORK, AI_TAGS, "", candidate_id=1, db_conn=object())

    assert any("keyword fallback" in r.message or "keyword fallback" in r.getMessage()
               for r in caplog.records), caplog.text


def test_classify_tier_without_db_uses_keywords():
    """No candidate_id / connection means no cache, so the LLM path is skipped."""
    detail = _classify_tier(AI_WORK, AI_TAGS, "", candidate_id=None, db_conn=None)
    assert detail.tier_source == "keyword"


def test_classify_tier_survives_broken_db_connection(monkeypatch):
    """A failing cache read must not take the whole scoring run down."""
    monkeypatch.setattr("app.llm.classify_ai_tier",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no llm")))
    detail = _classify_tier(AI_WORK, AI_TAGS, "", candidate_id=7, db_conn=_BoomConn())
    assert detail.tier_source == "keyword"
    assert isinstance(detail.tier, int)


# ---------------------------------------------------------------------------
# The inner layer: classify_experience_tier_llm swallowing its own error
# ---------------------------------------------------------------------------
def test_inner_llm_failure_reports_keyword_source(monkeypatch):
    """classify_ai_tier raising is handled inside, but must still be visible."""
    monkeypatch.setattr("app.llm.classify_ai_tier",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("timeout")))

    import sqlite3

    conn = sqlite3.connect(":memory:")
    detail = _classify_tier(AI_WORK, AI_TAGS, "", candidate_id=1, db_conn=conn)
    conn.close()

    assert detail.tier_source == "keyword"


# ---------------------------------------------------------------------------
# End-to-end: run_full_scoring flags the degradation
# ---------------------------------------------------------------------------
@pytest.fixture
def candidate():
    return {
        "name": "Test Candidate",
        "education": [{"school": "台灣大學", "department": "資訊工程", "degree_level": "碩士"}],
        "work_experiences": AI_WORK,
        "skill_tags": AI_TAGS,
        "raw_markdown": "NLP research with Transformer architecture",
        "self_introduction": "AI engineer.",
    }


def test_full_scoring_records_llm_tier_degradation(monkeypatch, candidate, job_data):
    monkeypatch.setattr(
        "app.scoring.experience.classify_experience_tier_llm",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")),
    )
    result = pipeline.run_full_scoring(candidate, job_data)

    assert isinstance(result, EnhancedMatchResult)
    assert DEGRADED_LLM_TIER in result.degraded_reasons
    # Degraded, but still a usable score rather than a crash or a zero.
    assert result.overall_score > 0


def test_full_scoring_survives_embedding_outage(monkeypatch, candidate, job_data):
    """An embedding outage must be declared, not silently absorbed.

    The similarity does not drop to zero: compute_semantic_similarity_traced has
    its own keyword-overlap fallback, so the dimension degrades to a coarser
    signal rather than vanishing. What matters is that the coarser path is
    flagged, since a keyword overlap is not comparable to a real cosine.
    """
    monkeypatch.setattr("app.scoring.embeddings.get_embedding", lambda text: [])

    result = pipeline.run_full_scoring(candidate, job_data)

    assert isinstance(result, EnhancedMatchResult)
    assert DEGRADED_EMBEDDING in result.degraded_reasons
    assert result.overall_score > 0
    # Degraded to the keyword fallback, which stays within the normal 0-1 range.
    assert 0.0 <= result.semantic_similarity <= 1.0


def test_healthy_run_reports_no_degradation(candidate, job_data):
    """The stubbed-but-working services path must leave degraded_reasons clean.

    This is the control for the tests above: if it ever starts reporting a
    fallback, the conftest stubs have stopped being wired in correctly and the
    degradation assertions above would pass for the wrong reason.
    """
    import sqlite3

    conn = sqlite3.connect(":memory:")
    candidate["id"] = 1
    try:
        result = pipeline.run_full_scoring(candidate, job_data, db_conn=conn)
    finally:
        conn.close()

    assert DEGRADED_EMBEDDING not in result.degraded_reasons
