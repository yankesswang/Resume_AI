"""Shared test fixtures.

Two invariants this file exists to enforce:

1. **No network.** The scoring pipeline calls LM Studio (tier classification,
   analysis text) and an embedding service. Both were being hit for real during
   the test run, so results depended on whether a GPU box happened to be up and
   the suite took ~155s. Everything is stubbed by default here.

2. **No touching the real database.** ``resume_ai.db`` holds thousands of real
   applicants' PII. ``app.database`` binds ``DB_PATH`` at import time from
   ``settings.db_path``, so pointing ``DB_PATH`` at a tmp file has to happen
   *before* that import — see ``_isolate_db`` below, which is session-scoped and
   autouse for exactly that reason.

Tests that genuinely need a live LM Studio / embedding service are marked
``@pytest.mark.integration`` and deselected by default (see ``addopts`` in
pyproject.toml). Run them with ``-m integration``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Database isolation
# ---------------------------------------------------------------------------
# This runs at import time rather than inside a fixture: app.database reads
# settings.db_path into a module-level DB_PATH constant on import, and several
# test modules import it at *their* import time (collection), which happens
# before any fixture body runs. Setting the env var here is the only point that
# reliably precedes that.
_TEST_DB_DIR = Path(os.environ.get("PYTEST_TMP_DB_DIR", "")) if os.environ.get("PYTEST_TMP_DB_DIR") else None
if _TEST_DB_DIR is None:
    import tempfile

    _TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="resume_ai_test_db_"))
os.environ["DB_PATH"] = str(_TEST_DB_DIR / "test_resume_ai.db")
# Keep the real .env from leaking a production DB_PATH / API keys into tests.
os.environ.setdefault("ENV_FILE", str(_TEST_DB_DIR / "nonexistent.env"))

REAL_DB_PATH = ROOT / "resume_ai.db"


@pytest.fixture(scope="session", autouse=True)
def _guard_real_db():
    """Fail loudly if anything in the suite opens the production database."""
    yield
    # A stat here would only catch mtime changes; the DB_PATH override above is
    # the actual guarantee. This assertion documents the invariant and catches a
    # test that hardcodes the path instead of going through settings.
    from app.database import DB_PATH

    assert Path(DB_PATH).resolve() != REAL_DB_PATH.resolve(), (
        f"A test rebound DB_PATH to the production database at {REAL_DB_PATH}."
    )


# ---------------------------------------------------------------------------
# Canned LLM / embedding responses
# ---------------------------------------------------------------------------
# Deterministic tier-classification reply. The pipeline parses this out of a
# chat completion, so the stub returns the JSON shape app.llm expects rather
# than a pre-parsed dict.
CANNED_TIER_JSON = (
    '{"tier": 2, "tier_label": "RAG Architect", "confidence": 0.9, '
    '"evidence": ["Built RAG pipeline with a vector database"], '
    '"analysis": "Candidate has hands-on retrieval-augmented generation experience."}'
)

CANNED_ANALYSIS_JSON = (
    '{"analysis_text": "Solid AI engineer with production RAG experience.", '
    '"strengths": ["RAG pipeline design", "Backend deployment with Docker"], '
    '"gaps": ["No large-scale training experience"], '
    '"interview_suggestions": ["Probe vector database selection trade-offs"], '
    '"tags": ["#RAG-Expert"]}'
)


def _fake_chat(messages, temperature=0.1, max_tokens=4096):
    """Stand-in for app.llm._chat.

    Dispatches on the system prompt so tier classification and the deep-reasoning
    analysis each get a reply of the right shape.
    """
    system = ""
    for m in messages:
        if m.get("role") == "system":
            system = m.get("content", "")
            break
    blob = system + " ".join(m.get("content", "") for m in messages)
    if "tier" in blob.lower():
        return CANNED_TIER_JSON
    return CANNED_ANALYSIS_JSON


def _fake_embedding(text: str) -> list[float]:
    """Deterministic pseudo-embedding derived from the text itself.

    Real cosine values are not reproducible offline, but they must be *stable*
    and must still separate related from unrelated text. Hashing token bucket
    counts into a fixed-width vector gives both: identical text yields identical
    vectors, and texts sharing vocabulary yield closer ones.
    """
    import hashlib
    import re as _re

    dim = 64
    vec = [0.0] * dim
    for token in _re.findall(r"[A-Za-z]+|[一-鿿]", text.lower()):
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = sum(v * v for v in vec) ** 0.5
    if norm == 0:
        return [0.0] * dim
    return [v / norm for v in vec]


@pytest.fixture(autouse=True)
def mock_external_services(request, monkeypatch):
    """Stub LM Studio and the embedding service for every non-integration test."""
    if request.node.get_closest_marker("integration"):
        return

    import app.llm
    import app.scoring.embeddings as emb

    monkeypatch.setattr(app.llm, "_chat", _fake_chat)
    monkeypatch.setattr(emb, "get_embedding", _fake_embedding)

    # embeddings.get_embedding is also imported by name elsewhere; patch the
    # binding wherever it was pulled in so no module keeps the live function.
    import app.scoring.pipeline as pipeline

    for mod in (pipeline,):
        if hasattr(mod, "get_embedding"):
            monkeypatch.setattr(mod, "get_embedding", _fake_embedding)

    # Any stray httpx call is a bug in the stubbing, not something to silently
    # wait 300s on. Fail fast and loudly instead.
    import httpx

    def _blocked(*args, **kwargs):
        raise AssertionError(
            "A test attempted a real HTTP request. Stub it, or mark the test "
            "@pytest.mark.integration."
        )

    monkeypatch.setattr(httpx, "post", _blocked)
    monkeypatch.setattr(httpx, "get", _blocked)


@pytest.fixture
def job_data():
    """The real job requirement document used by the scoring pipeline."""
    import json

    return json.loads((ROOT / "job_requirement.json").read_text(encoding="utf-8"))


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """A fresh initialised database for tests that write rows."""
    import importlib

    db_file = tmp_path / "candidates.db"
    monkeypatch.setenv("DB_PATH", str(db_file))

    import app.database as database

    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.init_db()
    yield db_file
    importlib.invalidate_caches()
