"""Scoring provenance and stale-tier detection.

Uses a small synthetic DB rather than the production one, but reproduces the
exact shape of the real problem: cached tiers written under a prompt hash that
no longer matches the live classifier.
"""

import json
import sqlite3

import pytest

from app.jobs_scoring import scoring_status, select_candidate_ids

OLD_PROMPT = "5d85e24efd54"   # the hash every production row currently carries


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "prov.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE candidates (
            id INTEGER PRIMARY KEY,
            llm_tier INTEGER,
            llm_tier_prompt_md5 TEXT
        );
        CREATE TABLE match_results (
            id INTEGER PRIMARY KEY,
            candidate_id INTEGER,
            scoring_mode TEXT,
            degraded_reasons TEXT
        );
        """
    )

    def _connect():
        c = sqlite3.connect(str(path))
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr("app.database._connect", _connect)
    monkeypatch.setattr("app.llm.TIER_CLASSIFY_PROMPT_MD5", "current123456")
    yield conn
    conn.close()


def _seed(conn, rows):
    """rows: (candidate_id, tier, prompt_md5, scoring_mode | None, reasons)."""
    for cid, tier, prompt, mode, reasons in rows:
        conn.execute(
            "INSERT INTO candidates (id, llm_tier, llm_tier_prompt_md5) VALUES (?,?,?)",
            (cid, tier, prompt),
        )
        if mode is not None:
            conn.execute(
                "INSERT INTO match_results (candidate_id, scoring_mode, degraded_reasons) "
                "VALUES (?,?,?)",
                (cid, mode, json.dumps(reasons)),
            )
    conn.commit()


def test_scoring_status_counts_stale_tiers(db):
    _seed(db, [
        (1, 1, OLD_PROMPT, "unknown", []),
        (2, 1, OLD_PROMPT, "unknown", []),
        (3, 2, "current123456", "full", []),
        (4, 0, "current123456", "degraded", ["llm_tier_fallback"]),
    ])

    st = scoring_status()
    assert st["total_candidates"] == 4
    assert st["tier_prompt_stale"] == 2
    assert st["tier_prompt_current"] == 2
    assert st["degraded"] == 1
    assert st["unknown_provenance"] == 2
    assert st["degraded_reasons"] == {"llm_tier_fallback": 1}
    assert st["current_tier_prompt_md5"] == "current123456"
    assert not st["healthy"]


def test_scoring_status_warns_when_no_tier_zero(db):
    """A pool with zero Tier 0 means the ranking has collapsed (see CLAUDE.md)."""
    _seed(db, [(i, 1, "current123456", "full", []) for i in range(1, 4)])

    st = scoring_status()
    assert any("Tier 0" in w for w in st["warnings"])


def test_scoring_status_healthy_when_everything_current(db):
    _seed(db, [
        (1, 0, "current123456", "full", []),
        (2, 2, "current123456", "full", []),
    ])

    st = scoring_status()
    assert st["tier_prompt_stale"] == 0
    assert st["degraded"] == 0
    assert st["warnings"] == []
    assert st["healthy"]


def test_select_stale_targets_exactly_the_outdated_rows(db):
    _seed(db, [
        (1, 1, OLD_PROMPT, "unknown", []),
        (2, 1, "current123456", "full", []),
        (3, None, None, None, []),        # never classified counts as stale
    ])

    assert select_candidate_ids(db, "stale") == [1, 3]


def test_select_degraded_includes_rows_without_provenance(db):
    """Pre-provenance rows are 'unknown', not 'full' — they need re-running too."""
    _seed(db, [
        (1, 1, OLD_PROMPT, "unknown", []),
        (2, 1, "current123456", "degraded", ["embedding_unavailable"]),
        (3, 1, "current123456", "full", []),
    ])

    assert select_candidate_ids(db, "degraded") == [1, 2]


def test_select_unscored_and_ids_and_limit(db):
    _seed(db, [
        (1, 1, OLD_PROMPT, "full", []),
        (2, 1, OLD_PROMPT, None, []),     # no match_results row
        (3, 1, OLD_PROMPT, None, []),
    ])

    assert select_candidate_ids(db, "unscored") == [2, 3]
    assert select_candidate_ids(db, "ids", candidate_ids=[3, 1]) == [3, 1]
    assert select_candidate_ids(db, "all") == [1, 2, 3]
    assert select_candidate_ids(db, "all", limit=2) == [1, 2]


def test_unknown_mode_rejected(db):
    with pytest.raises(ValueError):
        select_candidate_ids(db, "sideways")
