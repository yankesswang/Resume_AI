"""Explicit, version-controlled schema migrations for the SQLite database.

Why a hand-rolled runner instead of Alembic
-------------------------------------------
Alembic is the standard answer, but it buys things this app does not need and
costs things it cannot afford:

- It assumes SQLAlchemy models as the source of truth. This codebase talks raw
  ``sqlite3`` everywhere; adopting Alembic means either introducing SQLAlchemy
  (a large, risky rewrite of every query) or running Alembic in "raw SQL only"
  mode, at which point it is just a migration table with extra dependencies.
- SQLite cannot ALTER/DROP columns in place, so Alembic's autogenerate produces
  batch "copy table, rename" operations that are exactly the kind of thing you
  do not want running unsupervised against 3179 rows of real applicant data.
- Deployment is meant to stay "clone and run". An extra CLI, an ``alembic.ini``
  and a ``versions/`` package is real operational weight for a single-file DB.

So: a numbered list of migrations, each a plain function, recorded in the
``schema_migrations`` table that already exists. Small enough to audit in one
sitting, and it reuses the bookkeeping the DB already has.

Rules
-----
- Migrations are **append-only**. Never edit or renumber a released one; add a
  new one instead. The id is the primary key in ``schema_migrations``.
- Every migration must be **idempotent** on its own (``IF NOT EXISTS``,
  column-existence checks). Belt and braces: the runner skips applied ids, but a
  DB predating this runner may already carry the change untracked.
- ``baseline()`` stamps a pre-existing production DB as already-migrated instead
  of re-applying, which is how the live 3179-candidate DB adopts this mechanism
  without touching a single row.
"""

import sqlite3


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _add_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """ALTER TABLE ... ADD COLUMN, but only when the column is genuinely absent.

    The old init_db() style was to run the ALTER inside try/except and swallow
    the failure. That works but hides real errors (a typo'd type raises the same
    OperationalError as "duplicate column"), so check first instead.
    """
    if not _table_exists(conn, table):
        return
    if column in _columns(conn, table):
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def applied_ids(conn: sqlite3.Connection) -> set[str]:
    ensure_migrations_table(conn)
    return {r[0] for r in conn.execute("SELECT id FROM schema_migrations").fetchall()}


def _record(conn: sqlite3.Connection, migration_id: str) -> None:
    """Stamp a migration as applied, and commit it with its own DDL.

    The commit belongs here rather than only in the caller: a caller that passes
    its own connection and never commits leaves the DDL applied but unrecorded,
    so the next run re-applies it. That is survivable only because every
    migration is idempotent — it should not be load-bearing.
    """
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (id) VALUES (?)", (migration_id,)
    )
    conn.commit()


# --------------------------------------------------------------------------
# Migrations. Append only; never edit or renumber an existing entry.
# --------------------------------------------------------------------------


def _m_0001_candidate_columns(conn: sqlite3.Connection) -> None:
    """Columns added to `candidates` piecemeal over the project's life.

    Every one of these already exists on the production DB — this migration is
    what a *fresh* DB needs, and what `baseline()` stamps as done on the old one.
    """
    for column, decl in (
        ("code_104", "TEXT"),
        ("embedding", "TEXT"),
        ("personal_motto", "TEXT"),
        ("personal_traits", "TEXT"),
        ("autobiography", "TEXT"),
        ("interested", "INTEGER DEFAULT 0"),
        ("invitation_sent", "INTEGER DEFAULT 0"),
        ("interview_questions", "TEXT"),
        ("llm_tier", "INTEGER"),
        ("llm_tier_reasoning", "TEXT"),
        ("llm_tier_md5", "TEXT"),
        # Invalidates the cached tier when the classifier prompt changes.
        ("llm_tier_prompt_md5", "TEXT"),
    ):
        _add_column(conn, "candidates", column, decl)


def _m_0002_match_results_enhanced_scoring(conn: sqlite3.Connection) -> None:
    """Per-dimension breakdown columns for the enhanced scoring pipeline."""
    for column, decl in (
        ("s_ai", "REAL DEFAULT 0"),
        ("m_eng", "REAL DEFAULT 0"),
        ("s_total", "REAL DEFAULT 0"),
        ("education_detail", "TEXT"),
        ("experience_detail", "TEXT"),
        ("engineering_detail", "TEXT"),
        ("skill_detail", "TEXT"),
        ("passed_hard_filter", "INTEGER DEFAULT 1"),
        ("hard_filter_failures", "TEXT"),
        ("semantic_similarity", "REAL DEFAULT 0"),
        ("tags", "TEXT"),
        ("interview_suggestions", "TEXT"),
    ):
        _add_column(conn, "match_results", column, decl)


def _m_0003_interviews_columns(conn: sqlite3.Connection) -> None:
    for column in ("status", "assignment_due_date", "available_start_date", "resume_notes"):
        _add_column(conn, "interviews", column, "TEXT")


def _m_0004_import_batch_tables(conn: sqlite3.Connection) -> None:
    """Import batch/file provenance tables plus the candidate FK columns.

    A fresh DB missing `candidates.import_batch_id` / `import_file_id` made every
    insert fail with "no such column", so imports silently inserted 0 rows. That
    is the regression this migration exists to prevent — keep it.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS import_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_name TEXT NOT NULL,
            source_zip_path TEXT,
            zip_sha256 TEXT,
            status TEXT NOT NULL DEFAULT 'organized',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at TEXT,
            total_files INTEGER NOT NULL DEFAULT 0,
            total_candidates INTEGER NOT NULL DEFAULT 0,
            unique_count INTEGER NOT NULL DEFAULT 0,
            duplicate_count INTEGER NOT NULL DEFAULT 0,
            review_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS import_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            source_pdf_path TEXT NOT NULL,
            pdf_sha256 TEXT,
            original_md_path TEXT,
            output_dir TEXT,
            parse_status TEXT NOT NULL DEFAULT 'parsed',
            candidate_count INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(batch_id) REFERENCES import_batches(id) ON DELETE CASCADE
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_import_files_batch_pdf
            ON import_files(batch_id, source_pdf_path);
        """
    )
    for column in ("import_batch_id", "import_file_id"):
        _add_column(conn, "candidates", column, "INTEGER")


def _m_0005_parse_provenance(conn: sqlite3.Connection) -> None:
    """Hash + parser version, so a candidate's parse run stays traceable."""
    _add_column(conn, "candidates", "raw_md_sha256", "TEXT")
    _add_column(conn, "candidates", "parser_version", "TEXT")


def _m_0006_query_indexes(conn: sqlite3.Connection) -> None:
    """Indexes for what the list page actually sorts and filters by.

    Measured on the 3179-candidate production copy (20-run average):

      child fetch by candidate_id   education  0.267 -> 0.038 ms
                                    work_exp   0.177 -> 0.024 ms
                                    skills     1.310 -> 0.116 ms
      llm_tier filter                          2.542 -> 0.004 ms
      interested flag                          2.252 -> 0.009 ms
      invitation_sent flag                     2.070 -> 0.004 ms
      order by overall_score (top 50)          2.163 -> 0.022 ms

    The child-table FK indexes are what make batched, non-N+1 loading of
    education/work rows cheap for a page of candidates.

    Deliberately NOT indexed: match_results(candidate_id) — the UNIQUE
    (candidate_id, job_id) constraint already provides a usable autoindex, so a
    second index would only cost write throughput.
    """
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_education_candidate ON education(candidate_id);
        CREATE INDEX IF NOT EXISTS idx_skills_candidate ON skills(candidate_id);
        CREATE INDEX IF NOT EXISTS idx_work_experiences_candidate ON work_experiences(candidate_id);
        CREATE INDEX IF NOT EXISTS idx_attachments_candidate ON attachments(candidate_id);
        CREATE INDEX IF NOT EXISTS idx_references_candidate ON references_(candidate_id);
        CREATE INDEX IF NOT EXISTS idx_interviews_candidate ON interviews(candidate_id);
        CREATE INDEX IF NOT EXISTS idx_match_results_score ON match_results(overall_score DESC);
        CREATE INDEX IF NOT EXISTS idx_candidates_llm_tier ON candidates(llm_tier);
        CREATE INDEX IF NOT EXISTS idx_candidates_interested ON candidates(interested);
        CREATE INDEX IF NOT EXISTS idx_candidates_invitation_sent ON candidates(invitation_sent);
        """
    )


def _m_0007_scoring_provenance(conn: sqlite3.Connection) -> None:
    """match_results: which path produced the score, and under what config.

    `_classify_tier` catches every exception and falls back to keyword-only
    classification, and the embedding service silently degrades to keyword
    overlap. Neither left a trace, so a result written while LM Studio was down
    was indistinguishable from a good one and nobody could find it afterwards
    to re-run.

    Existing rows keep the 'unknown' default rather than being back-filled as
    'full' — they genuinely predate provenance, and claiming otherwise would
    make the flag worthless. `scoring_config_version` and `tier_prompt_md5`
    tie a result to the exact configuration that produced it, reusing
    `app.scoring.config.config_version()` and `app.llm.TIER_CLASSIFY_PROMPT_MD5`.
    """
    for column, decl in (
        ("scoring_mode", "TEXT DEFAULT 'unknown'"),   # 'full' | 'degraded' | 'unknown'
        ("degraded_reasons", "TEXT"),                 # JSON list of reason codes
        ("scoring_config_version", "TEXT"),
        ("tier_prompt_md5", "TEXT"),
        ("scored_at", "TEXT"),
    ):
        _add_column(conn, "match_results", column, decl)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_results_scoring_mode "
        "ON match_results(scoring_mode)"
    )
    # Finding the stale-tier population is the whole point of C4, and it is a
    # full scan over 3179 rows without this.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_candidates_tier_prompt "
        "ON candidates(llm_tier_prompt_md5)"
    )


def _m_0008_jobs_queue(conn: sqlite3.Connection) -> None:
    """Durable background job queue.

    Defined in app/jobs.py so the worker process can create it without
    importing the whole database module; this migration just records that a
    tracked DB has it.
    """
    from app.jobs import init_jobs_schema
    init_jobs_schema(conn)


def _m_0009_job_domain_profiles(conn: sqlite3.Connection) -> None:
    """job_requirements: per-role scoring standard (domain profile).

    The profile lives on the job, not globally, so two open roles in different
    fields can be scored by two different standards at the same time.  Columns
    rather than a side table: there is exactly one profile per job, and every
    read of a job already fetches the whole row.
    """
    _add_column(conn, "job_requirements", "domain_profile", "TEXT")
    _add_column(conn, "job_requirements", "profile_status", "TEXT DEFAULT 'none'")
    _add_column(conn, "job_requirements", "profile_updated_at", "TEXT")
    _add_column(conn, "job_requirements", "source_document", "TEXT")
    _add_column(conn, "job_requirements", "created_at", "TEXT")


def _m_0010_app_settings(conn: sqlite3.Connection) -> None:
    """Small key/value store for operator choices that must survive a restart.

    First user: which job requirement is active. That cannot live in a config
    file, because it is chosen through the UI at runtime.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        )
        """
    )


def _m_0011_user_accounts(conn: sqlite3.Connection) -> None:
    """User accounts, roles, PII grades, and the account-change audit trail.

    No account is created here. A fresh DB has zero users, which combined with
    ``AUTH_ENABLED=false`` leaves local development exactly as it was; the
    first root is made deliberately, by `python -m app.accounts_cli`.
    """
    from app.accounts import init_accounts_schema

    init_accounts_schema(conn)


# (id, description, function). Order is the apply order.
MIGRATIONS: list[tuple[str, str, object]] = [
    ("0001_candidate_columns", "candidates: 104 code, embedding, flags, LLM tier cache", _m_0001_candidate_columns),
    ("0002_match_results_enhanced_scoring", "match_results: per-dimension scoring breakdown", _m_0002_match_results_enhanced_scoring),
    ("0003_interviews_columns", "interviews: status and date columns", _m_0003_interviews_columns),
    ("0004_import_batch_tables", "import batch/file provenance tables", _m_0004_import_batch_tables),
    ("0005_parse_provenance", "candidates: raw markdown hash and parser version", _m_0005_parse_provenance),
    ("0006_query_indexes", "indexes for list sorting/filtering and child joins", _m_0006_query_indexes),
    ("0007_scoring_provenance", "match_results: scoring mode, degraded reasons, config/prompt version", _m_0007_scoring_provenance),
    ("0008_jobs_queue", "durable background job queue table", _m_0008_jobs_queue),
    ("0009_job_domain_profiles", "job_requirements: per-role domain scoring profile", _m_0009_job_domain_profiles),
    ("0010_app_settings", "app_settings key/value store", _m_0010_app_settings),
    ("0011_user_accounts", "user accounts, roles, PII grades, account audit", _m_0011_user_accounts),
]

# The pre-existing hand-written stamp. A DB carrying it was built by the old
# init_db() and therefore already has everything up to 0005 applied.
LEGACY_STAMP = "20260526_import_batch_dedupe_metadata"

# Migrations whose changes the legacy init_db() already made. 0006 (indexes) is
# new work and must still run on an old DB, so it is not in this set.
_LEGACY_COVERED = {
    "0001_candidate_columns",
    "0002_match_results_enhanced_scoring",
    "0003_interviews_columns",
    "0004_import_batch_tables",
    "0005_parse_provenance",
}


def baseline(conn: sqlite3.Connection) -> list[str]:
    """Stamp an existing DB as already carrying the migrations it clearly has.

    Adoption path for the live database: it was built by the old init_db() and
    already has every column, but `schema_migrations` only knows about the one
    legacy row. Re-running the DDL would be harmless (each migration is
    idempotent) yet pointless and slow, so detect and stamp instead.

    A migration is stamped only when the schema proves it was applied — the
    check is on the actual columns/tables, never on the legacy row alone.
    """
    ensure_migrations_table(conn)
    already = applied_ids(conn)
    stamped: list[str] = []

    if not _table_exists(conn, "candidates"):
        return stamped  # fresh DB: nothing to baseline, everything gets applied

    checks = {
        "0001_candidate_columns": lambda: "llm_tier_prompt_md5" in _columns(conn, "candidates"),
        "0002_match_results_enhanced_scoring": lambda: _table_exists(conn, "match_results")
        and "interview_suggestions" in _columns(conn, "match_results"),
        "0003_interviews_columns": lambda: _table_exists(conn, "interviews")
        and "resume_notes" in _columns(conn, "interviews"),
        "0004_import_batch_tables": lambda: _table_exists(conn, "import_batches")
        and _table_exists(conn, "import_files")
        and "import_file_id" in _columns(conn, "candidates"),
        "0005_parse_provenance": lambda: "parser_version" in _columns(conn, "candidates"),
    }
    for migration_id, present in checks.items():
        if migration_id in already or migration_id not in _LEGACY_COVERED:
            continue
        if present():
            _record(conn, migration_id)
            stamped.append(migration_id)
    return stamped


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply every pending migration in order. Returns the ids applied.

    Baselines first, so an existing production DB records what it already has
    rather than re-running the DDL against 3179 live rows.
    """
    ensure_migrations_table(conn)
    baseline(conn)
    done = applied_ids(conn)

    applied: list[str] = []
    for migration_id, _description, fn in MIGRATIONS:
        if migration_id in done:
            continue
        fn(conn)
        _record(conn, migration_id)
        applied.append(migration_id)
    return applied


def status(conn: sqlite3.Connection) -> list[tuple[str, str, bool]]:
    """(id, description, applied) for every known migration."""
    done = applied_ids(conn)
    return [(mid, desc, mid in done) for mid, desc, _fn in MIGRATIONS]
