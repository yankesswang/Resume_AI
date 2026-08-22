import hashlib
import json
import logging
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from app.models import (
    EnhancedMatchResult,
    MatchResultExtract,
    ResumeExtract,
)

from app.settings import settings

logger = logging.getLogger(__name__)

DB_PATH = settings.db_path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _parse_year_month(raw: str | None) -> tuple[int, int] | None:
    if not raw:
        return None
    match = re.search(r"(\d{4})[/-](\d{1,2})", raw.strip())
    if not match:
        return None
    month = int(match.group(2))
    if month < 1 or month > 12:
        return None
    return int(match.group(1)), month


IN_SCHOOL_KEYWORDS = ("就學中", "在學", "修業中")
# 肄業中 = dropped out but still enrolled; bare 肄業 = dropped out, no longer a student.
DROPPED_OUT_ENROLLED = "肄業中"

_DEGREE_RANKS = (
    ("博士", 5),
    ("碩士", 4),
    ("大學", 3), ("學士", 3), ("四技", 3), ("二技", 3), ("科大", 3),
    ("專科", 2), ("五專", 2), ("二專", 2), ("三專", 2),
    ("高中", 1), ("高職", 1),
    ("國中", 0),
)

INTERN_WORK_TYPE_KEYWORDS = ("實習", "工讀")
FULL_TIME_WORK_TYPE_KEYWORD = "全職"

# years_of_experience strings that mean "essentially no career track record yet".
_JUNIOR_YOE = ("", "無", "無工作經驗", "一年以下", "1年以下", "0年")


def _degree_rank(degree_level: str | None) -> int:
    """Rank a degree level so the highest qualification can be identified. -1 = unknown."""
    text = (degree_level or "").strip()
    for keyword, rank in _DEGREE_RANKS:
        if keyword in text:
            return rank
    return -1


def _is_in_school(status: str) -> bool:
    if DROPPED_OUT_ENROLLED in status:
        return True
    # Plain 肄業 must not match the 業 in other words, and is not "in school".
    return any(keyword in status for keyword in IN_SCHOOL_KEYWORDS)


NEW_GRAD_HORIZON_MONTHS = 12

# Job titles that name themselves as student work, whatever the dates say.
STUDENT_JOB_KEYWORDS = (
    "實習", "工讀", "intern", "co-op",
    "學生", "研究助理", "兼任", "獎助生", "助教", "產學", "校內工作",
)

# A student job may run slightly past the graduation month (thesis wrap-up,
# handover). Beyond this it is a real job the candidate simply started early.
STUDENT_JOB_TAIL_MONTHS = 6


def _months_between(start: tuple[int, int], end: tuple[int, int]) -> int:
    return (end[0] - start[0]) * 12 + (end[1] - start[1])


def _highest_degree_window(
    education_list: list[dict],
) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """Study period (start, end) of the highest-level programme, if datable."""
    highest_rank = max((_degree_rank(e.get("degree_level")) for e in education_list), default=-1)
    starts, ends = [], []
    for edu in education_list:
        if _degree_rank(edu.get("degree_level")) != highest_rank:
            continue
        start = _parse_year_month((edu.get("date_start") or "").strip())
        end = _parse_year_month((edu.get("date_end") or "").strip())
        if start:
            starts.append(start)
        if end:
            ends.append(end)
    if not starts or not ends:
        return None
    return min(starts), max(ends)


def _is_student_job(job: dict, study_window: tuple | None, today: date) -> bool:
    """True if this work record looks like work done *as a student*.

    Either the title names it (實習生/工讀/研究助理/助教...), or it both started
    during the highest-degree study period and ended around graduation. The
    second condition matters: a job started in the final year but still running
    years later is a real career, not student work.
    """
    title = f"{job.get('job_title') or ''} {job.get('job_category') or ''}".lower()
    if any(keyword.lower() in title for keyword in STUDENT_JOB_KEYWORDS):
        return True

    if not study_window:
        return False
    study_start, study_end = study_window

    start = _parse_year_month((job.get("date_start") or "").strip())
    if not start or not (study_start <= start <= study_end):
        return False

    # "仍在職" and other unparsable ends mean the job is ongoing.
    end = _parse_year_month((job.get("date_end") or "").strip()) or (today.year, today.month)
    return _months_between(study_end, end) <= STUDENT_JOB_TAIL_MONTHS


def has_only_student_work(
    work_experiences: list[dict],
    education_list: list[dict],
    today: date,
) -> bool:
    """True if the candidate has work history and *all* of it is student work.

    Used to tell a fresh graduate who has never held a real job (still an
    intern-tier candidate) from one who has already started a career.

    Requires at least one work record. An empty list is not evidence of "never
    worked": 1652 candidates in the 104 corpus have no parsed work rows at all,
    many of them with years of stated experience, so treating empty as
    never-worked would sweep in every resume whose work section failed to parse.
    """
    if not work_experiences:
        return False

    study_window = _highest_degree_window(education_list)
    for job in work_experiences:
        # A record with no dates and no student marker is treated as real work,
        # since there is nothing to place it inside a study period.
        if not _is_student_job(job, study_window, today):
            return False
    return True


# School tiers for the list filter. The ladder and the classifier are the
# scoring module's — imported rather than restated, so an operator override
# saved from the 學校分級 page moves the ranking and this filter together.
# A frozen copy here (or in the frontend, where this filter used to live) is
# how the two silently disagree the first time someone drags a school.
SCHOOL_TIER_ORDER = ["D", "C", "B", "A"]


def annotate_degree_levels(education_list: list[dict]) -> list[dict]:
    """Tag each education row with `degree_rank` on the normalised ladder.

    The list UI has to decide which row is "the university one" and which is
    "the master's one". It did that with its own six-keyword table, which knew
    nothing of 四技/二技 (a bachelor's) or 博士班 (a doctorate) — so a
    university-of-technology graduate showed a blank 大學 column and a PhD
    appeared in neither. Reusing normalise_degree() here gives the display the
    same ladder the hard filter gates on, instead of a weaker copy of it.

    Reads `department` when `degree_level` is blank, which the parser routinely
    leaves empty while storing "資訊工程學系碩士班" in the former — the same
    fallback the min_education gate makes.
    """
    from app.scoring.hard_filter import normalise_degree

    for ed in education_list or []:
        rank = None
        for field in ("degree_level", "department"):
            value = (ed.get(field) or "").strip()
            if value:
                rank = normalise_degree(value)
                if rank:
                    break
        ed["degree_rank"] = rank
    return education_list


def best_school_tier(education_list: list[dict]) -> str | None:
    """Highest school tier across a candidate's parsed education rows.

    Dict-shaped twin of ``hard_filter._best_school_tier``, which takes
    EducationExtract objects; the list query has plain rows. Both call the same
    ``school_tier()``, so they cannot rate a school differently.

    Returns None when no row carries a recognisable school — "unknown" is not
    "unranked", and the caller decides which way that falls.
    """
    from app.scoring.education import school_tier

    best: str | None = None
    for ed in education_list or []:
        name = (ed.get("school") or "").strip()
        if not name:
            continue
        tier = school_tier(name)
        if tier not in SCHOOL_TIER_ORDER:
            continue
        if best is None or SCHOOL_TIER_ORDER.index(tier) > SCHOOL_TIER_ORDER.index(best):
            best = tier
    return best


def meets_school_tier(education_list: list[dict], minimum: str | None) -> bool:
    """Whether a candidate's best school reaches ``minimum`` (A/B/C).

    Mirrors the hard filter's two asymmetries deliberately: a resume with no
    parsable school fails the gate (an unknown school is not evidence of a good
    one), and an unrecognised minimum gates on nothing rather than rejecting
    everybody — a typo that emptied the list would look identical to a filter
    that is working.
    """
    want = (minimum or "").strip().upper()
    if not want or want == "D" or want not in SCHOOL_TIER_ORDER:
        return True
    best = best_school_tier(education_list)
    if best is None:
        return False
    return SCHOOL_TIER_ORDER.index(best) >= SCHOOL_TIER_ORDER.index(want)


def calc_candidate_type(
    education_list: list[dict],
    candidate: dict | None = None,
    today: date | None = None,
) -> str:
    """Classify hiring type as 實習 (intern) or 正職 (full-time engineer).

    A candidate is an intern only if they are *currently* a student: enrolled in
    their highest-level programme with a graduation date still ahead of today.

    Refinements over the naive "any 就學中 row" rule, each of which produced
    real misclassifications in the 104 corpus:

    - Only the highest-degree education row counts. A 大學畢業 candidate with a
      stale 高中 row still flagged 就學中 is an engineer, not an intern.
    - A graduation date already in the past means the programme is finished even
      if 104 still says 就學中 (the resume was written before graduating).
    - An in-school row with an unparsable graduation date no longer forces 實習;
      the candidate's own 求職身份 (`work_type`) and years of experience decide.
    - `work_type` is the candidate's explicit statement of what they are applying
      for. Wanting only 實習/工讀 overrides an inferred 正職, and asking for 全職
      overrides an inferred 實習 unless they are still years from graduating.
    - A graduate who has never held a non-student job is still intern-tier. Their
      work history is checked against the study period (and for 實習/工讀/研究助理
      style titles); if none of it is real post-graduation employment they stay 實習.

    `candidate` may carry `work_type`, `years_of_experience` and
    `work_experiences`; each is optional and the rule degrades gracefully without
    them, so older callers keep working.
    """
    today = today or date.today()
    work_type = ((candidate or {}).get("work_type") or "").strip()
    wants_intern = any(k in work_type for k in INTERN_WORK_TYPE_KEYWORDS)
    wants_full_time = FULL_TIME_WORK_TYPE_KEYWORD in work_type
    yoe = ((candidate or {}).get("years_of_experience") or "").strip()
    is_junior = yoe in _JUNIOR_YOE

    highest_rank = max((_degree_rank(e.get("degree_level")) for e in education_list), default=-1)

    studying = False          # enrolled in the highest programme, graduation ahead
    studying_unknown_end = False   # enrolled, but no usable graduation date
    months_to_graduation: int | None = None

    for edu in education_list:
        if not _is_in_school((edu.get("status") or "").strip()):
            continue
        # Ignore lower-level programmes: a stale "still in high school" row on a
        # university graduate's resume does not make them a student.
        if _degree_rank(edu.get("degree_level")) < highest_rank:
            continue

        grad = _parse_year_month((edu.get("date_end") or "").strip())
        if not grad:
            studying_unknown_end = True
            continue

        grad_year, grad_month = grad
        # Already graduated -> not a current student. The graduation month itself
        # counts as still-studying, since 104 records only year/month and a
        # 2026/06 graduation is not complete on 2026-06-01.
        if (grad_year, grad_month) < (today.year, today.month):
            continue

        studying = True
        remaining = (grad_year - today.year) * 12 + (grad_month - today.month)
        if months_to_graduation is None or remaining < months_to_graduation:
            months_to_graduation = remaining

    if studying:
        # A student who explicitly wants 全職 and is close to graduating (within
        # two semesters) is applying as a new grad engineer, not an intern.
        if (
            wants_full_time
            and not wants_intern
            and (months_to_graduation or 0) <= NEW_GRAD_HORIZON_MONTHS
        ):
            return "正職"
        return "實習"

    if studying_unknown_end:
        # No graduation date to reason about: trust the candidate's own stated
        # 求職身份, then fall back to career track record.
        if wants_intern and not wants_full_time:
            return "實習"
        if wants_full_time:
            return "正職"
        return "實習" if is_junior else "正職"

    # Not currently studying. Still an intern applicant if that is the only kind
    # of work they are asking for and they have no career track record yet.
    if wants_intern and not wants_full_time and is_junior:
        return "實習"

    # Graduated but never actually started working: every work record is student
    # work (實習/工讀/研究助理, or dated inside the study period). They have no
    # professional track record yet, so they belong in the intern pool rather
    # than being ranked against working engineers.
    #
    work_experiences = (candidate or {}).get("work_experiences") or []
    if is_junior and has_only_student_work(work_experiences, education_list, today):
        return "實習"

    return "正職"


def init_db():
    conn = _connect()
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            english_name TEXT,
            code_104 TEXT,
            birth_year TEXT,
            age TEXT,
            nationality TEXT,
            current_status TEXT,
            earliest_start TEXT,
            education_level TEXT,
            school TEXT,
            major TEXT,
            military_status TEXT,
            desired_salary TEXT,
            desired_job_categories TEXT,  -- JSON list
            desired_locations TEXT,       -- JSON list
            desired_industry TEXT,
            ideal_positions TEXT,         -- JSON list
            years_of_experience TEXT,
            linkedin_url TEXT,
            photo_path TEXT,
            email TEXT,
            mobile1 TEXT,
            mobile2 TEXT,
            phone_home TEXT,
            phone_work TEXT,
            district TEXT,
            mailing_address TEXT,
            work_type TEXT,
            shift_preference TEXT,
            remote_work_preference TEXT,
            skills_text TEXT,
            skill_tags TEXT,             -- JSON list
            self_introduction TEXT,
            raw_markdown TEXT,
            source_pdf_path TEXT,
            source_md_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS work_experiences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            seq INTEGER,
            company_name TEXT,
            date_start TEXT,
            date_end TEXT,
            duration TEXT,
            industry TEXT,
            company_size TEXT,
            job_category TEXT,
            management_responsibility TEXT,
            job_title TEXT,
            job_description TEXT,
            job_skills TEXT,
            FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS education (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            seq INTEGER,
            school TEXT,
            department TEXT,
            degree_level TEXT,
            date_start TEXT,
            date_end TEXT,
            region TEXT,
            status TEXT,
            FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            skill_name TEXT,
            FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS references_ (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            ref_name TEXT,
            ref_email TEXT,
            ref_org TEXT,
            ref_title TEXT,
            FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            attachment_type TEXT,
            seq INTEGER,
            name TEXT,
            description TEXT,
            url TEXT,
            FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS job_requirements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            source_json TEXT
        );

        CREATE TABLE IF NOT EXISTS interviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER,
            interview_date TEXT NOT NULL,
            interview_time TEXT,
            interview_type TEXT DEFAULT 'onsite',
            status TEXT,
            location TEXT,
            notes TEXT,
            assignment_due_date TEXT,
            available_start_date TEXT,
            resume_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS interview_statuses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL UNIQUE,
            color TEXT DEFAULT 'gray',
            sort_order INTEGER DEFAULT 0
        );

        -- Interview *types* were a three-value enum living only in
        -- CalendarView.vue while *statuses* next to them on the same form were
        -- already an editable table. Adding "線上測驗" meant a frontend rebuild.
        -- `value` is the string stored in interviews.interview_type, kept
        -- stable and separate from `label` so renaming a type in the UI does
        -- not orphan the rows already referencing it.
        CREATE TABLE IF NOT EXISTS interview_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            value TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL,
            color TEXT DEFAULT 'gray',
            sort_order INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS match_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            overall_score REAL,
            education_score REAL,
            experience_score REAL,
            skills_score REAL,
            analysis_text TEXT,
            strengths TEXT,  -- JSON list
            gaps TEXT,       -- JSON list
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE,
            FOREIGN KEY (job_id) REFERENCES job_requirements(id) ON DELETE CASCADE,
            UNIQUE(candidate_id, job_id)
        );
    """)
    # Migrations for existing databases
    # Add code_104 column if missing
    existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(candidates)").fetchall()}
    if "code_104" not in existing_cols:
        conn.execute("ALTER TABLE candidates ADD COLUMN code_104 TEXT")
    if "embedding" not in existing_cols:
        conn.execute("ALTER TABLE candidates ADD COLUMN embedding TEXT")
    for col in ("personal_motto", "personal_traits", "autobiography"):
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE candidates ADD COLUMN {col} TEXT")

    # Interested flag
    if "interested" not in existing_cols:
        conn.execute("ALTER TABLE candidates ADD COLUMN interested INTEGER DEFAULT 0")

    # Invitation sent flag
    if "invitation_sent" not in existing_cols:
        conn.execute("ALTER TABLE candidates ADD COLUMN invitation_sent INTEGER DEFAULT 0")

    # Interview questions cache
    if "interview_questions" not in existing_cols:
        conn.execute("ALTER TABLE candidates ADD COLUMN interview_questions TEXT")

    # LLM tier cache columns
    for col, col_type in (
        ("llm_tier", "INTEGER"),
        ("llm_tier_reasoning", "TEXT"),
        ("llm_tier_md5", "TEXT"),
        ("llm_tier_prompt_md5", "TEXT"),  # invalidates cache when prompt changes
    ):
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE candidates ADD COLUMN {col} {col_type}")

    # Migrate match_results for enhanced scoring columns
    match_cols = {r[1] for r in conn.execute("PRAGMA table_info(match_results)").fetchall()}
    new_match_columns = {
        "s_ai": "REAL DEFAULT 0",
        "m_eng": "REAL DEFAULT 0",
        "s_total": "REAL DEFAULT 0",
        "education_detail": "TEXT",      # JSON
        "experience_detail": "TEXT",     # JSON
        "engineering_detail": "TEXT",    # JSON
        "skill_detail": "TEXT",          # JSON
        "passed_hard_filter": "INTEGER DEFAULT 1",
        "hard_filter_failures": "TEXT",  # JSON
        "semantic_similarity": "REAL DEFAULT 0",
        "tags": "TEXT",                  # JSON
        "interview_suggestions": "TEXT", # JSON
    }
    for col_name, col_type in new_match_columns.items():
        if col_name not in match_cols:
            conn.execute(f"ALTER TABLE match_results ADD COLUMN {col_name} {col_type}")

    # Migrate interviews table for new columns
    interview_cols = {r[1] for r in conn.execute("PRAGMA table_info(interviews)").fetchall()}
    for col in ("status", "assignment_due_date", "available_start_date", "resume_notes"):
        if col not in interview_cols:
            conn.execute(f"ALTER TABLE interviews ADD COLUMN {col} TEXT")

    # Seed default interview statuses if table is empty
    status_count = conn.execute("SELECT COUNT(*) FROM interview_statuses").fetchone()[0]
    if status_count == 0:
        defaults = [
            ("初篩", "blue", 1),
            ("一面", "purple", 2),
            ("二面", "indigo", 3),
            ("HR面試", "orange", 4),
            ("Offer已發", "emerald", 5),
            ("婉拒", "red", 6),
            ("錄取", "green", 7),
        ]
        for label, color, order in defaults:
            conn.execute(
                "INSERT OR IGNORE INTO interview_statuses (label, color, sort_order) VALUES (?, ?, ?)",
                (label, color, order),
            )

    # Seed the three types that were hardcoded in the frontend, with the same
    # values interviews.interview_type already stores, so existing rows keep
    # resolving and the UI looks unchanged on first load after the upgrade.
    type_count = conn.execute("SELECT COUNT(*) FROM interview_types").fetchone()[0]
    if type_count == 0:
        for value, label, color, order in (
            ("phone", "Phone", "blue", 1),
            ("video", "Video", "purple", 2),
            ("onsite", "Onsite", "green", 3),
        ):
            conn.execute(
                "INSERT OR IGNORE INTO interview_types (value, label, color, sort_order) VALUES (?, ?, ?, ?)",
                (value, label, color, order),
            )

    # insert_candidate() always writes import_batch_id/import_file_id, so a DB
    # created by init_db() alone (a fresh one, or any not touched by the organize
    # /upload paths) must already carry those columns — otherwise every insert
    # fails with "no such column".
    _ensure_import_tables(conn)

    # PII access auditing lives in the same DB, so a fresh install gets the
    # table without a separate migration step.
    from app.audit import init_audit_schema

    init_audit_schema(conn)

    # Version-controlled schema changes (app/migrations.py). Everything above is
    # the historical inline-ALTER style, kept so existing behaviour is unchanged;
    # anything NEW belongs in a numbered migration instead. run_migrations()
    # baselines an existing DB rather than re-applying DDL to live rows.
    run_migrations(conn)

    conn.commit()
    conn.close()


def run_migrations(conn: sqlite3.Connection | None = None) -> list[str]:
    """Apply pending schema migrations. Returns the ids applied.

    Safe to call repeatedly and safe on the production DB: `migrate()` stamps
    already-present schema as applied instead of re-running its DDL.
    """
    from app import migrations

    own_conn = conn is None
    conn = conn or _connect()
    try:
        applied = migrations.migrate(conn)
        if own_conn:
            conn.commit()
        return applied
    finally:
        if own_conn:
            conn.close()


def migration_status() -> list[tuple[str, str, bool]]:
    """(id, description, applied) for every known migration."""
    from app import migrations

    conn = _connect()
    try:
        return migrations.status(conn)
    finally:
        conn.close()


UPLOAD_BATCH_PREFIX = "手動上傳"


def _ensure_import_tables(conn: sqlite3.Connection) -> bool:
    """Create the import batch/file tables when missing.

    Single-PDF uploads must be attributable to a batch just like ZIP imports,
    but a fresh DB only gets these tables from scripts/organize_resume_db.py.
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
    cols = {r[1] for r in conn.execute("PRAGMA table_info(candidates)").fetchall()}
    for col in ("import_batch_id", "import_file_id"):
        if col not in cols:
            conn.execute(f"ALTER TABLE candidates ADD COLUMN {col} INTEGER")
    return True


def register_upload_source(source_pdf_path: str, source_md_path: str = "") -> tuple[int, int]:
    """Attribute one uploaded PDF to today's upload batch. Returns (batch_id, file_id).

    Uploads are grouped by calendar day, so the Imports page shows one entry per
    day of manual uploads with each PDF listed under it, instead of every upload
    collapsing into a single indistinguishable group.
    """
    conn = _connect()
    try:
        _ensure_import_tables(conn)
        today = date.today().isoformat()
        batch_name = f"{UPLOAD_BATCH_PREFIX} {today}"

        row = conn.execute(
            "SELECT id FROM import_batches WHERE batch_name = ?", (batch_name,)
        ).fetchone()
        if row:
            batch_id = int(row["id"])
        else:
            cur = conn.execute(
                """
                INSERT INTO import_batches (batch_name, source_zip_path, status, notes)
                VALUES (?, '', 'uploaded', ?)
                """,
                (batch_name, "Single-PDF uploads via /api/upload"),
            )
            batch_id = int(cur.lastrowid)

        conn.execute(
            """
            INSERT INTO import_files (
                batch_id, source_pdf_path, original_md_path, output_dir, parse_status
            ) VALUES (?, ?, ?, ?, 'parsed')
            ON CONFLICT(batch_id, source_pdf_path) DO UPDATE SET
                original_md_path=excluded.original_md_path,
                output_dir=excluded.output_dir,
                parse_status='parsed'
            """,
            (
                batch_id,
                source_pdf_path,
                source_md_path,
                str(Path(source_md_path).parent) if source_md_path else "",
            ),
        )
        file_id = int(
            conn.execute(
                "SELECT id FROM import_files WHERE batch_id=? AND source_pdf_path=?",
                (batch_id, source_pdf_path),
            ).fetchone()["id"]
        )
        conn.commit()
        return batch_id, file_id
    finally:
        conn.close()


def refresh_upload_batch_counts(batch_id: int) -> None:
    """Recompute counters for an upload batch after candidates were attached."""
    conn = _connect()
    try:
        if not _table_exists(conn, "import_batches"):
            return
        conn.execute(
            """
            UPDATE import_files
               SET candidate_count = (
                     SELECT count(*) FROM candidates c
                      WHERE c.import_file_id = import_files.id
                   )
             WHERE batch_id = ?
            """,
            (batch_id,),
        )
        use_dedupe = _dedupe_status_exists(conn)
        if use_dedupe:
            counts = conn.execute(
                """
                SELECT
                  (SELECT count(*) FROM import_files WHERE batch_id=?) AS total_files,
                  (SELECT count(*) FROM candidates WHERE import_batch_id=?) AS total_candidates,
                  (SELECT count(*) FROM candidates c
                     JOIN candidate_dedupe_status d ON d.candidate_id = c.id
                    WHERE c.import_batch_id=? AND d.is_unique=1) AS unique_count,
                  (SELECT count(*) FROM candidates c
                     JOIN candidate_dedupe_status d ON d.candidate_id = c.id
                    WHERE c.import_batch_id=? AND d.is_unique=0) AS duplicate_count,
                  (SELECT count(*) FROM candidates c
                     JOIN candidate_dedupe_status d ON d.candidate_id = c.id
                    WHERE c.import_batch_id=? AND d.dedupe_status='review') AS review_count
                """,
                (batch_id, batch_id, batch_id, batch_id, batch_id),
            ).fetchone()
        else:
            counts = conn.execute(
                """
                SELECT
                  (SELECT count(*) FROM import_files WHERE batch_id=?) AS total_files,
                  (SELECT count(*) FROM candidates WHERE import_batch_id=?) AS total_candidates,
                  0 AS unique_count, 0 AS duplicate_count, 0 AS review_count
                """,
                (batch_id, batch_id),
            ).fetchone()
        conn.execute(
            """
            UPDATE import_batches
               SET total_files=?, total_candidates=?, unique_count=?,
                   duplicate_count=?, review_count=?, finished_at=CURRENT_TIMESTAMP
             WHERE id=?
            """,
            (
                counts["total_files"],
                counts["total_candidates"],
                counts["unique_count"],
                counts["duplicate_count"],
                counts["review_count"],
                batch_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def insert_candidate(
    extract: ResumeExtract,
    raw_markdown: str,
    source_pdf_path: str = "",
    source_md_path: str = "",
    import_batch_id: int | None = None,
    import_file_id: int | None = None,
) -> int:
    conn = _connect()
    cur = conn.cursor()

    # Deduplicate: if code_104 exists, update existing record instead of inserting
    if extract.code_104:
        existing = cur.execute(
            "SELECT id FROM candidates WHERE code_104 = ?", (extract.code_104,)
        ).fetchone()
        if existing:
            candidate_id = existing["id"]
            conn.close()
            # Re-use the update path: delete old child data and update
            delete_candidate_data(candidate_id)
            update_candidate_from_extract(candidate_id, extract, raw_markdown)
            # Update source paths, and re-attribute to the batch that just
            # supplied this resume so the newest upload owns the candidate.
            c2 = _connect()
            if import_batch_id is not None:
                c2.execute(
                    """UPDATE candidates SET source_pdf_path=?, source_md_path=?,
                              import_batch_id=?, import_file_id=? WHERE id=?""",
                    (source_pdf_path, source_md_path, import_batch_id,
                     import_file_id, candidate_id),
                )
            else:
                c2.execute(
                    "UPDATE candidates SET source_pdf_path=?, source_md_path=? WHERE id=?",
                    (source_pdf_path, source_md_path, candidate_id),
                )
            c2.commit()
            c2.close()
            return candidate_id

    cur.execute(
        """INSERT INTO candidates (
            name, english_name, code_104, birth_year, age, nationality, current_status,
            earliest_start, education_level, school, major, military_status,
            desired_salary, desired_job_categories, desired_locations,
            desired_industry, ideal_positions, years_of_experience,
            linkedin_url, photo_path, email, mobile1, mobile2, phone_home,
            phone_work, district, mailing_address, work_type, shift_preference,
            remote_work_preference, skills_text, skill_tags, self_introduction,
            personal_motto, personal_traits, autobiography,
            raw_markdown, source_pdf_path, source_md_path,
            import_batch_id, import_file_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            extract.name,
            extract.english_name,
            extract.code_104,
            extract.birth_year,
            extract.age,
            extract.nationality,
            extract.current_status,
            extract.earliest_start,
            extract.education_level,
            extract.school,
            extract.major,
            extract.military_status,
            extract.desired_salary,
            json.dumps(extract.desired_job_categories, ensure_ascii=False),
            json.dumps(extract.desired_locations, ensure_ascii=False),
            extract.desired_industry,
            json.dumps(extract.ideal_positions, ensure_ascii=False),
            extract.years_of_experience,
            extract.linkedin_url,
            extract.photo_path,
            extract.email,
            extract.mobile1,
            extract.mobile2,
            extract.phone_home,
            extract.phone_work,
            extract.district,
            extract.mailing_address,
            extract.work_type,
            extract.shift_preference,
            extract.remote_work_preference,
            extract.skills_text,
            json.dumps(extract.skill_tags, ensure_ascii=False),
            extract.self_introduction,
            extract.personal_motto,
            extract.personal_traits,
            extract.autobiography,
            raw_markdown,
            source_pdf_path,
            source_md_path,
            import_batch_id,
            import_file_id,
        ),
    )
    candidate_id = cur.lastrowid

    for we in extract.work_experiences:
        cur.execute(
            """INSERT INTO work_experiences (
                candidate_id, seq, company_name, date_start, date_end, duration,
                industry, company_size, job_category, management_responsibility,
                job_title, job_description, job_skills
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                candidate_id, we.seq, we.company_name, we.date_start,
                we.date_end, we.duration, we.industry, we.company_size,
                we.job_category, we.management_responsibility, we.job_title,
                we.job_description, we.job_skills,
            ),
        )

    for ed in extract.education:
        cur.execute(
            """INSERT INTO education (
                candidate_id, seq, school, department, degree_level,
                date_start, date_end, region, status
            ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                candidate_id, ed.seq, ed.school, ed.department,
                ed.degree_level, ed.date_start, ed.date_end,
                ed.region, ed.status,
            ),
        )

    for tag in extract.skill_tags:
        cur.execute(
            "INSERT INTO skills (candidate_id, skill_name) VALUES (?,?)",
            (candidate_id, tag),
        )

    for ref in extract.references:
        cur.execute(
            """INSERT INTO references_ (
                candidate_id, ref_name, ref_email, ref_org, ref_title
            ) VALUES (?,?,?,?,?)""",
            (candidate_id, ref.ref_name, ref.ref_email, ref.ref_org, ref.ref_title),
        )

    for att in extract.attachments:
        cur.execute(
            """INSERT INTO attachments (
                candidate_id, attachment_type, seq, name, description, url
            ) VALUES (?,?,?,?,?,?)""",
            (candidate_id, att.attachment_type, att.seq, att.name, att.description, att.url),
        )

    conn.commit()
    conn.close()
    return candidate_id


def _dedupe_status_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='candidate_dedupe_status'"
    ).fetchone()
    return row is not None


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


# Sortable columns, mapped to SQL. Whitelisted rather than interpolated from the
# request, so a sort key can never become an injection point.
def _fetch_candidate_child_rows(
    conn: sqlite3.Connection, candidate_ids: list[int] | None
):
    """Education + work rows for a set of candidates, in two queries total.

    `candidate_ids=None` means "every candidate" (the unpaginated path). Passing
    a list restricts to those ids, which is what keeps a paginated page from
    loading 5124 education and 3208 work rows to classify 50 candidates.

    Both are needed by calc_candidate_type(): dropping the work rows silently
    degrades the classification to the education-only path.
    """
    edu_sql = (
        "SELECT candidate_id, school, department, degree_level, status, "
        "date_start, date_end FROM education"
    )
    work_sql = (
        "SELECT candidate_id, job_title, job_category, date_start, date_end "
        "FROM work_experiences"
    )
    if candidate_ids is None:
        return (
            conn.execute(f"{edu_sql} ORDER BY candidate_id, seq").fetchall(),
            conn.execute(f"{work_sql} ORDER BY candidate_id, seq").fetchall(),
        )
    if not candidate_ids:
        return [], []

    # SQLITE_MAX_VARIABLE_NUMBER is 999 on older builds; chunk to stay under it.
    edu_rows, work_rows = [], []
    for start in range(0, len(candidate_ids), 500):
        chunk = candidate_ids[start:start + 500]
        placeholders = ",".join("?" * len(chunk))
        edu_rows.extend(
            conn.execute(
                f"{edu_sql} WHERE candidate_id IN ({placeholders}) ORDER BY candidate_id, seq",
                chunk,
            ).fetchall()
        )
        work_rows.extend(
            conn.execute(
                f"{work_sql} WHERE candidate_id IN ({placeholders}) ORDER BY candidate_id, seq",
                chunk,
            ).fetchall()
        )
    return edu_rows, work_rows


CANDIDATE_SORT_COLUMNS = {
    "id": "c.id",
    "name": "c.name",
    "created_at": "c.created_at",
    "birth_year": "c.birth_year",
    "school": "c.school",
    "education_level": "c.education_level",
    "years_of_experience": "c.years_of_experience",
    "llm_tier": "c.llm_tier",
    "overall_score": "m.overall_score",
    "s_ai": "m.s_ai",
    "m_eng": "m.m_eng",
    "s_total": "m.s_total",
}

DEFAULT_CANDIDATE_SORT = "id"

# Page size guard rails. The unpaginated payload for the full 3179-row corpus is
# ~6.2 MB of JSON; capping the page keeps any single response bounded.
MAX_PAGE_LIMIT = 500


def get_all_candidates_summary(
    scope: str | None = None,
    batch_id: int | None = None,
    file_id: int | None = None,
    *,
    limit: int | None = None,
    offset: int = 0,
    sort_by: str | None = None,
    sort_dir: str = "desc",
    search: str | None = None,
    education_level: str | None = None,
    llm_tier: int | None = None,
    interested: bool | None = None,
    invitation_sent: bool | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    candidate_type: str | None = None,
    min_school_tier: str | None = None,
    with_total: bool = False,
) -> list[dict] | dict:
    """Candidate rows for the list page.

    Called bare (`get_all_candidates_summary()`) it still returns **every**
    candidate as a plain list, exactly as before — scripts/batch_score_all.py and
    the batch-match endpoint depend on that and must keep working.

    Pass `limit` to paginate and `with_total=True` to get the
    `{items, total, limit, offset, has_more}` envelope the API returns.

    Pagination is limit/offset rather than keyset. Keyset is the better choice
    for deep, stable scrolling, but it cannot express "jump to page N" and it
    needs the sort key to be unique — neither holds here: the UI sorts by
    `overall_score`, which has thousands of ties and ~0 rows for unscored
    candidates. At 3179 rows the offset scan is far below the cost of
    serialization, so offset's simplicity wins.

    `candidate_type` and `min_school_tier` are the filters that cannot be pushed
    into SQL: the first is derived by calc_candidate_type() from education +
    work rows, the second by school_tier() over the education rows (which honours
    operator overrides, so it is not a fixed set of names SQL could match). Both
    are therefore applied after the fetch, and when either is in play the whole
    matching set is classified before the page is cut, so `total` stays truthful.
    """
    conn = _connect()
    use_dedupe = _dedupe_status_exists(conn)
    dedupe_scope = scope if scope in {"unique", "duplicate", "review"} else None
    if dedupe_scope and not use_dedupe:
        conn.close()
        return {"items": [], "total": 0, "limit": limit, "offset": offset, "has_more": False} if with_total else []

    dedupe_select = (
        """, d.is_unique AS is_unique_candidate,
                  d.dedupe_status, d.confidence,
                  d.strong_match_count, d.match_types AS dedupe_match_types,
                  d.matched_old_dbs, d.matched_old_refs,
                  d.weak_name_birth_count, d.internal_duplicate_key,
                  d.reason AS dedupe_reason"""
        if use_dedupe
        else """, NULL AS is_unique_candidate,
                  NULL AS dedupe_status, NULL AS confidence,
                  0 AS strong_match_count, '[]' AS dedupe_match_types,
                  '[]' AS matched_old_dbs, '[]' AS matched_old_refs,
                  0 AS weak_name_birth_count, NULL AS internal_duplicate_key,
                  NULL AS dedupe_reason"""
    )
    dedupe_join = (
        "JOIN candidate_dedupe_status d ON c.id = d.candidate_id"
        if dedupe_scope
        else (
            "LEFT JOIN candidate_dedupe_status d ON c.id = d.candidate_id"
            if use_dedupe
            else ""
        )
    )
    where_parts: list[str] = []
    params: list[object] = []
    if dedupe_scope == "unique":
        where_parts.append("d.is_unique = 1")
    elif dedupe_scope == "duplicate":
        where_parts.append("d.is_unique = 0")
    elif dedupe_scope == "review":
        where_parts.append("d.dedupe_status = 'review'")
    if batch_id is not None:
        where_parts.append("c.import_batch_id = ?")
        params.append(batch_id)
    if file_id is not None:
        where_parts.append("c.import_file_id = ?")
        params.append(file_id)
    if search:
        # Name / 104 code / school, the three things a recruiter types into the box.
        like = f"%{search.strip()}%"
        where_parts.append("(c.name LIKE ? OR c.code_104 LIKE ? OR c.school LIKE ?)")
        params.extend([like, like, like])
    if education_level:
        where_parts.append("c.education_level = ?")
        params.append(education_level)
    if llm_tier is not None:
        where_parts.append("c.llm_tier = ?")
        params.append(llm_tier)
    if interested is not None:
        where_parts.append("c.interested = ?")
        params.append(1 if interested else 0)
    if invitation_sent is not None:
        where_parts.append("c.invitation_sent = ?")
        params.append(1 if invitation_sent else 0)
    if min_score is not None:
        where_parts.append("m.overall_score >= ?")
        params.append(min_score)
    if max_score is not None:
        where_parts.append("m.overall_score <= ?")
        params.append(max_score)
    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    sort_column = CANDIDATE_SORT_COLUMNS.get(
        sort_by or DEFAULT_CANDIDATE_SORT, CANDIDATE_SORT_COLUMNS[DEFAULT_CANDIDATE_SORT]
    )
    direction = "ASC" if str(sort_dir).lower() == "asc" else "DESC"
    # NULLs last in both directions: an unscored candidate should never outrank a
    # scored one just because SQLite sorts NULL low. c.id breaks ties so a page
    # boundary can't drop or repeat a row between requests.
    order_clause = f"ORDER BY ({sort_column} IS NULL), {sort_column} {direction}, c.id DESC"

    # These filters are computed in Python, so a page cut in SQL would be wrong
    # when filtering by them — fetch the matching set and cut after classifying.
    post_filtered = bool(candidate_type) or bool(
        (min_school_tier or "").strip().upper() not in ("", "D")
    )
    sql_paginated = limit is not None and not post_filtered
    limit_clause = ""
    if sql_paginated:
        limit_clause = "LIMIT ? OFFSET ?"

    total = None
    if with_total or post_filtered:
        total = conn.execute(
            f"""SELECT COUNT(*) FROM candidates c
                {dedupe_join}
                LEFT JOIN match_results m ON c.id = m.candidate_id
                {where_clause}""",
            params,
        ).fetchone()[0]

    row_params = list(params)
    if sql_paginated:
        row_params.extend([min(int(limit), MAX_PAGE_LIMIT), max(int(offset), 0)])

    rows = conn.execute(
        f"""SELECT c.id, c.name, c.code_104, c.birth_year, c.education_level, c.school, c.major,
                  c.import_batch_id, c.import_file_id,
                  c.years_of_experience, c.work_type, c.ideal_positions,
                  c.desired_job_categories, c.skill_tags,
                  c.photo_path, c.source_md_path, c.interested, c.invitation_sent,
                  m.overall_score, m.s_ai, m.m_eng, m.s_total,
                  m.experience_detail, m.passed_hard_filter, m.tags,
                  m.scoring_mode, m.degraded_reasons, m.tier_prompt_md5,
                  c.llm_tier_prompt_md5
                  {dedupe_select}
           FROM candidates c
           {dedupe_join}
           LEFT JOIN match_results m ON c.id = m.candidate_id
           {where_clause}
           {order_clause}
           {limit_clause}""",
        row_params,
    ).fetchall()

    # Child rows for candidate_type. Fetched as ONE query per child table for the
    # whole page (not one per candidate) — a per-row fetch across a page is the
    # classic N+1 and would issue 2xN round trips. When paginating we restrict to
    # the page's ids; unpaginated we take the whole table, as before.
    page_ids = [r["id"] for r in rows]
    edu_rows, work_rows = _fetch_candidate_child_rows(
        conn, page_ids if sql_paginated else None
    )
    conn.close()

    edu_map: dict[int, list[dict]] = {}
    for er in edu_rows:
        cid = er["candidate_id"]
        edu_map.setdefault(cid, []).append(dict(er))

    work_map: dict[int, list[dict]] = {}
    for wr in work_rows:
        work_map.setdefault(wr["candidate_id"], []).append(dict(wr))

    results = []
    current_prompt_md5 = _current_tier_prompt_md5()
    for r in rows:
        d = dict(r)
        d["ideal_positions"] = json.loads(d["ideal_positions"] or "[]")
        d["desired_job_categories"] = json.loads(d["desired_job_categories"] or "[]")
        d["skill_tags"] = json.loads(d["skill_tags"] or "[]")
        edu_list = annotate_degree_levels(edu_map.get(d["id"], []))
        d["education"] = edu_list
        d["candidate_type"] = calc_candidate_type(
            edu_list, {**d, "work_experiences": work_map.get(d["id"], [])}
        )
        # The candidate's best school on the global A/B/C/D ladder, so the list
        # UI can filter by school rank without keeping its own copy of which
        # schools are top-tier. Computed here rather than in the client because
        # school_tier() honours operator overrides from 學校分級 — a frozen
        # client-side list silently ignores every one of them.
        d["school_tier"] = best_school_tier(edu_list)
        # Parse enhanced scoring fields
        if d.get("experience_detail"):
            d["experience_detail"] = json.loads(d["experience_detail"])
        if d.get("tags"):
            d["tags"] = json.loads(d["tags"])
        else:
            d["tags"] = []
        # Provenance, so the list UI can flag a row scored while a service was
        # down or under a prompt that has since changed.
        d["degraded_reasons"] = json.loads(d.get("degraded_reasons") or "[]")
        d["scoring_mode"] = d.get("scoring_mode") or ("unknown" if d.get("overall_score") is not None else None)
        d["is_degraded"] = d["scoring_mode"] == "degraded"
        d["tier_is_stale"] = bool(
            d.get("llm_tier_prompt_md5")
            and d["llm_tier_prompt_md5"] != current_prompt_md5
        )
        if "passed_hard_filter" in d and d["passed_hard_filter"] is not None:
            d["passed_hard_filter"] = bool(d["passed_hard_filter"])
        d["interested"] = bool(d.get("interested", 0))
        d["invitation_sent"] = bool(d.get("invitation_sent", 0))
        if d.get("is_unique_candidate") is not None:
            d["is_unique_candidate"] = bool(d["is_unique_candidate"])
        d["dedupe_match_types"] = json.loads(d.get("dedupe_match_types") or "[]")
        d["matched_old_dbs"] = json.loads(d.get("matched_old_dbs") or "[]")
        d["matched_old_refs"] = json.loads(d.get("matched_old_refs") or "[]")
        results.append(d)

    if post_filtered:
        # Classification is only available now, so the filters, the true total
        # and the page cut all have to happen here rather than in SQL.
        if candidate_type:
            results = [r for r in results if r.get("candidate_type") == candidate_type]
        if min_school_tier:
            results = [
                r for r in results
                if meets_school_tier(r.get("education") or [], min_school_tier)
            ]
        total = len(results)
        if limit is not None:
            start = max(int(offset), 0)
            results = results[start:start + min(int(limit), MAX_PAGE_LIMIT)]

    if not with_total:
        return results

    if total is None:
        total = len(results)
    effective_limit = min(int(limit), MAX_PAGE_LIMIT) if limit is not None else None
    return {
        "items": results,
        "total": total,
        "limit": effective_limit,
        "offset": max(int(offset), 0) if limit is not None else 0,
        "has_more": (
            (max(int(offset), 0) + len(results)) < total if limit is not None else False
        ),
    }


def get_candidate_detail(candidate_id: int) -> dict | None:
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM candidates WHERE id = ?", (candidate_id,)
    ).fetchone()
    if not row:
        conn.close()
        return None

    candidate = dict(row)
    for field in ("desired_job_categories", "desired_locations", "ideal_positions", "skill_tags"):
        candidate[field] = json.loads(candidate[field] or "[]")

    candidate["work_experiences"] = [
        dict(r) for r in conn.execute(
            "SELECT * FROM work_experiences WHERE candidate_id = ? ORDER BY seq",
            (candidate_id,),
        ).fetchall()
    ]
    candidate["education"] = annotate_degree_levels([
        dict(r) for r in conn.execute(
            "SELECT * FROM education WHERE candidate_id = ? ORDER BY seq",
            (candidate_id,),
        ).fetchall()
    ])
    candidate["school_tier"] = best_school_tier(candidate["education"])
    candidate["candidate_type"] = calc_candidate_type(candidate["education"], candidate)
    candidate["skills"] = [
        dict(r) for r in conn.execute(
            "SELECT * FROM skills WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchall()
    ]
    candidate["references"] = [
        dict(r) for r in conn.execute(
            "SELECT * FROM references_ WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchall()
    ]
    candidate["attachments"] = [
        dict(r) for r in conn.execute(
            "SELECT * FROM attachments WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchall()
    ]

    if candidate.get("interview_questions"):
        candidate["interview_questions"] = json.loads(candidate["interview_questions"])
    else:
        candidate["interview_questions"] = None

    conn.close()
    return candidate


def upsert_match_result(candidate_id: int, job_id: int, result: MatchResultExtract | EnhancedMatchResult):
    conn = _connect()

    if isinstance(result, EnhancedMatchResult):
        conn.execute(
            """INSERT INTO match_results (
                candidate_id, job_id, overall_score, education_score,
                experience_score, skills_score, analysis_text, strengths, gaps,
                s_ai, m_eng, s_total,
                education_detail, experience_detail, engineering_detail, skill_detail,
                passed_hard_filter, hard_filter_failures, semantic_similarity,
                tags, interview_suggestions,
                scoring_mode, degraded_reasons, scoring_config_version,
                tier_prompt_md5, scored_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(candidate_id, job_id) DO UPDATE SET
                overall_score=excluded.overall_score,
                education_score=excluded.education_score,
                experience_score=excluded.experience_score,
                skills_score=excluded.skills_score,
                analysis_text=excluded.analysis_text,
                strengths=excluded.strengths,
                gaps=excluded.gaps,
                s_ai=excluded.s_ai,
                m_eng=excluded.m_eng,
                s_total=excluded.s_total,
                education_detail=excluded.education_detail,
                experience_detail=excluded.experience_detail,
                engineering_detail=excluded.engineering_detail,
                skill_detail=excluded.skill_detail,
                passed_hard_filter=excluded.passed_hard_filter,
                hard_filter_failures=excluded.hard_filter_failures,
                semantic_similarity=excluded.semantic_similarity,
                tags=excluded.tags,
                interview_suggestions=excluded.interview_suggestions,
                scoring_mode=excluded.scoring_mode,
                degraded_reasons=excluded.degraded_reasons,
                scoring_config_version=excluded.scoring_config_version,
                tier_prompt_md5=excluded.tier_prompt_md5,
                scored_at=CURRENT_TIMESTAMP,
                created_at=CURRENT_TIMESTAMP""",
            (
                candidate_id, job_id, result.overall_score, result.education_score,
                result.experience_score, result.skills_score, result.analysis_text,
                json.dumps(result.strengths, ensure_ascii=False),
                json.dumps(result.gaps, ensure_ascii=False),
                result.s_ai, result.m_eng, result.s_total,
                json.dumps(result.education_detail.model_dump(), ensure_ascii=False),
                json.dumps(result.experience_detail.model_dump(), ensure_ascii=False),
                json.dumps(result.engineering_detail.model_dump(), ensure_ascii=False),
                json.dumps(result.skill_detail.model_dump(), ensure_ascii=False),
                1 if result.passed_hard_filter else 0,
                json.dumps(result.hard_filter_failures, ensure_ascii=False),
                result.semantic_similarity,
                json.dumps(result.tags, ensure_ascii=False),
                json.dumps(result.interview_suggestions, ensure_ascii=False),
                result.scoring_mode or "full",
                json.dumps(result.degraded_reasons, ensure_ascii=False),
                result.scoring_config_version,
                result.tier_prompt_md5,
            ),
        )
    else:
        conn.execute(
            """INSERT INTO match_results (
                candidate_id, job_id, overall_score, education_score,
                experience_score, skills_score, analysis_text, strengths, gaps
            ) VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(candidate_id, job_id) DO UPDATE SET
                overall_score=excluded.overall_score,
                education_score=excluded.education_score,
                experience_score=excluded.experience_score,
                skills_score=excluded.skills_score,
                analysis_text=excluded.analysis_text,
                strengths=excluded.strengths,
                gaps=excluded.gaps,
                created_at=CURRENT_TIMESTAMP""",
            (
                candidate_id, job_id, result.overall_score, result.education_score,
                result.experience_score, result.skills_score, result.analysis_text,
                json.dumps(result.strengths, ensure_ascii=False),
                json.dumps(result.gaps, ensure_ascii=False),
            ),
        )
    conn.commit()
    conn.close()


def get_match_result(candidate_id: int, job_id: int) -> dict | None:
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM match_results WHERE candidate_id = ? AND job_id = ?",
        (candidate_id, job_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["strengths"] = json.loads(d["strengths"] or "[]")
    d["gaps"] = json.loads(d["gaps"] or "[]")
    # Parse enhanced scoring fields
    for json_field in ("education_detail", "experience_detail", "engineering_detail",
                       "skill_detail", "hard_filter_failures", "tags", "interview_suggestions",
                       "degraded_reasons"):
        if json_field in d and d[json_field]:
            d[json_field] = json.loads(d[json_field])
        elif json_field in d:
            d[json_field] = {} if json_field.endswith("_detail") else []
    if "passed_hard_filter" in d:
        d["passed_hard_filter"] = bool(d.get("passed_hard_filter", 1))
    # Rows written before provenance existed carry no mode; report them as
    # 'unknown' rather than silently implying they were fully scored.
    d["scoring_mode"] = d.get("scoring_mode") or "unknown"
    d["is_degraded"] = d["scoring_mode"] == "degraded"
    return d


def ensure_job_requirement(title: str, source_json: str) -> int:
    conn = _connect()
    row = conn.execute(
        "SELECT id FROM job_requirements WHERE title = ?", (title,)
    ).fetchone()
    if row:
        # Always sync source_json so changes to job_requirement.json take effect
        conn.execute(
            "UPDATE job_requirements SET source_json = ? WHERE id = ?",
            (source_json, row["id"]),
        )
        conn.commit()
        conn.close()
        return row["id"]
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO job_requirements (title, source_json) VALUES (?,?)",
        (title, source_json),
    )
    conn.commit()
    job_id = cur.lastrowid
    conn.close()
    return job_id


def get_app_setting(key: str) -> str | None:
    """Read an operator setting, tolerating a DB that predates the table."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def set_app_setting(key: str, value: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY, value TEXT, updated_at TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at",
            (key, value, _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def _now_iso() -> str:
    """UTC timestamp, second precision — matches app/jobs.py's convention."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def list_job_requirements() -> list[dict]:
    """All job requirements with profile status, newest first."""
    conn = _connect()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(job_requirements)")}
        extra = ", ".join(
            c for c in ("profile_status", "profile_updated_at", "source_document", "created_at")
            if c in cols
        )
        sql = "SELECT id, title, source_json" + (f", {extra}" if extra else "")
        sql += " FROM job_requirements ORDER BY id DESC"
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()

    out = []
    for r in rows:
        d = dict(r)
        try:
            job = json.loads(d.pop("source_json") or "{}")
        except json.JSONDecodeError:
            job = {}
        basic = job.get("basic_conditions", {}) or {}
        d["job_title"] = basic.get("job_title") or d.get("title") or ""
        d["domain"] = job.get("domain", "")
        d["job_summary"] = job.get("job_summary", "")
        d.setdefault("profile_status", "none")
        out.append(d)
    return out


def create_job_requirement(
    title: str,
    source_json: str,
    domain_profile: str | None = None,
    profile_status: str = "none",
    source_document: str = "",
) -> int:
    """Insert a NEW job requirement.

    Distinct from ``ensure_job_requirement``, which upserts by title: two open
    roles can legitimately share a title (two headcounts, different teams), and
    silently overwriting one with the other would swap a live scoring standard
    out from under whichever job was scored second.
    """
    conn = _connect()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(job_requirements)")}
        fields = ["title", "source_json"]
        values: list[object] = [title, source_json]
        for name, val in (
            ("domain_profile", domain_profile),
            ("profile_status", profile_status),
            ("source_document", source_document),
            ("profile_updated_at", _now_iso()),
            ("created_at", _now_iso()),
        ):
            if name in cols:
                fields.append(name)
                values.append(val)
        cur = conn.execute(
            f"INSERT INTO job_requirements ({', '.join(fields)}) "
            f"VALUES ({', '.join('?' * len(fields))})",
            values,
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_job_profile(
    job_id: int,
    domain_profile: str,
    profile_status: str = "ready",
) -> None:
    """Replace a job's scoring standard."""
    conn = _connect()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(job_requirements)")}
        if "domain_profile" not in cols:
            raise RuntimeError("job_requirements 缺少 domain_profile 欄位，請先執行資料庫遷移")
        sets = ["domain_profile = ?", "profile_status = ?"]
        vals: list[object] = [domain_profile, profile_status]
        if "profile_updated_at" in cols:
            sets.append("profile_updated_at = ?")
            vals.append(_now_iso())
        vals.append(job_id)
        conn.execute(
            f"UPDATE job_requirements SET {', '.join(sets)} WHERE id = ?", vals
        )
        conn.commit()
    finally:
        conn.close()


def update_job_source(job_id: int, title: str, source_json: str) -> None:
    """Replace a job's requirement JSON (not its profile)."""
    conn = _connect()
    try:
        conn.execute(
            "UPDATE job_requirements SET title = ?, source_json = ? WHERE id = ?",
            (title, source_json, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_job_requirement(job_id: int) -> bool:
    """Delete a job and, by cascade, its match_results."""
    conn = _connect()
    try:
        cur = conn.execute("DELETE FROM job_requirements WHERE id = ?", (job_id,))
        conn.execute("DELETE FROM match_results WHERE job_id = ?", (job_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_job_requirement(job_id: int) -> dict | None:
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM job_requirements WHERE id = ?", (job_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


def get_candidates_export_data(candidate_ids: list[int]) -> list[dict]:
    """Fetch candidate + match data for export, sorted by overall_score DESC."""
    if not candidate_ids:
        return []
    conn = _connect()
    placeholders = ",".join("?" for _ in candidate_ids)
    rows = conn.execute(
        f"""SELECT c.id, c.name, c.english_name, c.code_104, c.age, c.birth_year,
                   c.education_level, c.school, c.major, c.years_of_experience,
                   c.work_type,
                   c.skill_tags, c.email, c.mobile1, c.desired_salary,
                   c.desired_job_categories, c.ideal_positions,
                   c.photo_path, c.source_md_path,
                   m.overall_score, m.education_score, m.experience_score,
                   m.skills_score, m.s_ai, m.m_eng, m.s_total,
                   m.strengths, m.gaps, m.analysis_text,
                   m.experience_detail, m.tags, m.passed_hard_filter,
                   (SELECT resume_notes FROM interviews
                    WHERE candidate_id = c.id AND resume_notes IS NOT NULL AND resume_notes != ''
                    ORDER BY id DESC LIMIT 1) AS resume_notes
            FROM candidates c
            LEFT JOIN match_results m ON c.id = m.candidate_id
            WHERE c.id IN ({placeholders})
            ORDER BY m.overall_score DESC NULLS LAST""",
        candidate_ids,
    ).fetchall()

    # Fetch education and work experiences
    edu_rows = conn.execute(
        f"SELECT candidate_id, school, department, degree_level, date_start, date_end, status "
        f"FROM education WHERE candidate_id IN ({placeholders}) ORDER BY candidate_id, seq",
        candidate_ids,
    ).fetchall()
    work_rows = conn.execute(
        f"SELECT candidate_id, company_name, job_title, job_category, "
        f"date_start, date_end, duration, industry "
        f"FROM work_experiences WHERE candidate_id IN ({placeholders}) ORDER BY candidate_id, seq",
        candidate_ids,
    ).fetchall()
    conn.close()

    edu_map: dict[int, list[dict]] = {}
    for er in edu_rows:
        cid = er["candidate_id"]
        edu_map.setdefault(cid, []).append(dict(er))

    work_map: dict[int, list[dict]] = {}
    for wr in work_rows:
        cid = wr["candidate_id"]
        work_map.setdefault(cid, []).append(dict(wr))

    results = []
    for r in rows:
        d = dict(r)
        for json_field in ("skill_tags", "desired_job_categories", "ideal_positions"):
            d[json_field] = json.loads(d[json_field] or "[]")
        for json_field in ("strengths", "gaps", "tags"):
            d[json_field] = json.loads(d[json_field] or "[]")
        if d.get("experience_detail"):
            d["experience_detail"] = json.loads(d["experience_detail"])
        if d.get("passed_hard_filter") is not None:
            d["passed_hard_filter"] = bool(d["passed_hard_filter"])
        d["education"] = annotate_degree_levels(edu_map.get(d["id"], []))
        d["school_tier"] = best_school_tier(d["education"])
        d["work_experiences"] = work_map.get(d["id"], [])
        d["candidate_type"] = calc_candidate_type(d["education"], d)
        results.append(d)
    return results


def get_filter_options(scope: str | None = None, batch_id: int | None = None) -> dict:
    """Return distinct filter options for the frontend."""
    conn = _connect()
    use_dedupe = _dedupe_status_exists(conn)
    dedupe_scope = scope if scope in {"unique", "duplicate", "review"} else None
    if dedupe_scope and not use_dedupe:
        conn.close()
        return {
            "education_levels": [],
            "skill_tags": [],
            "experience_ranges": ["0-2年", "3-5年", "5-10年", "10年+"],
            "score_ranges": ["80+", "60-79", "40-59", "<40", "No Score"],
            "candidate_types": ["實習", "正職"],
        }

    dedupe_join = "JOIN candidate_dedupe_status d ON c.id = d.candidate_id" if dedupe_scope else ""
    skill_dedupe_join = "JOIN candidate_dedupe_status d ON s.candidate_id = d.candidate_id" if dedupe_scope else ""

    where_parts = ["c.education_level IS NOT NULL", "c.education_level != ''"]
    skill_where_parts = ["s.skill_name IS NOT NULL", "s.skill_name != ''"]
    params: list[object] = []
    skill_params: list[object] = []
    if dedupe_scope == "unique":
        where_parts.append("d.is_unique = 1")
        skill_where_parts.append("d.is_unique = 1")
    elif dedupe_scope == "duplicate":
        where_parts.append("d.is_unique = 0")
        skill_where_parts.append("d.is_unique = 0")
    elif dedupe_scope == "review":
        where_parts.append("d.dedupe_status = 'review'")
        skill_where_parts.append("d.dedupe_status = 'review'")
    if batch_id is not None:
        where_parts.append("c.import_batch_id = ?")
        skill_where_parts.append(
            "s.candidate_id IN (SELECT id FROM candidates WHERE import_batch_id = ?)"
        )
        params.append(batch_id)
        skill_params.append(batch_id)
    where_clause = " AND ".join(where_parts)
    skill_where_clause = " AND ".join(skill_where_parts)

    education_levels = [
        r[0] for r in conn.execute(
            f"""SELECT DISTINCT c.education_level
                FROM candidates c
                {dedupe_join}
                WHERE {where_clause}
                ORDER BY c.education_level""",
            params,
        ).fetchall()
    ]
    skill_tags = sorted({
        r[0] for r in conn.execute(
            f"""SELECT DISTINCT s.skill_name
                FROM skills s
                {skill_dedupe_join}
                WHERE {skill_where_clause}""",
            skill_params,
        ).fetchall()
    })
    conn.close()
    return {
        "education_levels": education_levels,
        "skill_tags": skill_tags,
        "experience_ranges": ["0-2年", "3-5年", "5-10年", "10年+"],
        "score_ranges": ["80+", "60-79", "40-59", "<40", "No Score"],
        "candidate_types": ["實習", "正職"],
    }


def get_import_batches() -> list[dict]:
    """Return import batch metadata for frontend filters."""
    conn = _connect()
    if not _table_exists(conn, "import_batches"):
        conn.close()
        return []
    rows = conn.execute(
        """
        SELECT id, batch_name, source_zip_path, status, created_at, finished_at,
               total_files, total_candidates, unique_count, duplicate_count,
               review_count, failed_count, notes
          FROM import_batches
         ORDER BY id DESC
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_import_batch_detail(batch_id: int) -> dict | None:
    """Return one import batch plus the per-PDF parse results it produced."""
    conn = _connect()
    if not _table_exists(conn, "import_batches"):
        conn.close()
        return None
    row = conn.execute(
        """
        SELECT id, batch_name, source_zip_path, zip_sha256, status, created_at,
               finished_at, total_files, total_candidates, unique_count,
               duplicate_count, review_count, failed_count, notes
          FROM import_batches WHERE id = ?
        """,
        (batch_id,),
    ).fetchone()
    if not row:
        conn.close()
        return None
    batch = dict(row)

    if not _table_exists(conn, "import_files"):
        conn.close()
        batch["files"] = []
        return batch

    use_dedupe = _dedupe_status_exists(conn)
    dedupe_counts = (
        """,
               (SELECT count(*) FROM candidates c
                 JOIN candidate_dedupe_status d ON d.candidate_id = c.id
                WHERE c.import_file_id = f.id AND d.is_unique = 1) AS unique_count,
               (SELECT count(*) FROM candidates c
                 JOIN candidate_dedupe_status d ON d.candidate_id = c.id
                WHERE c.import_file_id = f.id AND d.is_unique = 0) AS duplicate_count,
               (SELECT count(*) FROM candidates c
                 JOIN candidate_dedupe_status d ON d.candidate_id = c.id
                WHERE c.import_file_id = f.id AND d.dedupe_status = 'review') AS review_count"""
        if use_dedupe
        else """,
               0 AS unique_count, 0 AS duplicate_count, 0 AS review_count"""
    )

    file_rows = conn.execute(
        f"""
        SELECT f.id, f.batch_id, f.source_pdf_path, f.pdf_sha256, f.original_md_path,
               f.output_dir, f.parse_status, f.error_message, f.created_at,
               (SELECT count(*) FROM candidates c WHERE c.import_file_id = f.id)
                   AS candidate_count
               {dedupe_counts}
          FROM import_files f
         WHERE f.batch_id = ?
         ORDER BY f.id
        """,
        (batch_id,),
    ).fetchall()
    conn.close()

    files = []
    for fr in file_rows:
        d = dict(fr)
        d["pdf_name"] = Path(d["source_pdf_path"] or "").name
        files.append(d)
    batch["files"] = files
    return batch


def record_import_attempt(
    batch_name: str,
    source_pdf_path: str,
    parse_status: str,
    error_message: str = "",
    original_md_path: str = "",
    output_dir: str = "",
    notes: str = "",
) -> tuple[int, int]:
    """Record one PDF's parse outcome so failures are visible in the UI.

    Previously a failed parse only printed to the terminal: `import_files` held
    nothing, so /imports showed a batch that looked clean while candidates were
    silently missing. Both outcomes are written here, which is what lets the
    Imports page report "3 of 4 parsed, 1 failed" instead of staying quiet.

    Returns (batch_id, file_id).
    """
    conn = _connect()
    try:
        _ensure_import_tables(conn)
        row = conn.execute(
            "SELECT id FROM import_batches WHERE batch_name = ?", (batch_name,)
        ).fetchone()
        if row:
            batch_id = int(row["id"])
        else:
            batch_id = int(conn.execute(
                "INSERT INTO import_batches (batch_name, source_zip_path, status, notes) "
                "VALUES (?, '', 'organized', ?)",
                (batch_name, notes),
            ).lastrowid)

        conn.execute(
            """
            INSERT INTO import_files (
                batch_id, source_pdf_path, original_md_path, output_dir,
                parse_status, error_message
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(batch_id, source_pdf_path) DO UPDATE SET
                original_md_path=excluded.original_md_path,
                output_dir=excluded.output_dir,
                parse_status=excluded.parse_status,
                error_message=excluded.error_message
            """,
            (batch_id, source_pdf_path, original_md_path, output_dir,
             parse_status, error_message[:2000]),
        )
        file_id = int(conn.execute(
            "SELECT id FROM import_files WHERE batch_id=? AND source_pdf_path=?",
            (batch_id, source_pdf_path),
        ).fetchone()["id"])
        conn.commit()
        return batch_id, file_id
    finally:
        conn.close()


def refresh_import_batch_counts(batch_id: int) -> None:
    """Recompute a batch's file/candidate/failure counters from its rows."""
    conn = _connect()
    try:
        if not _table_exists(conn, "import_batches"):
            return
        files = conn.execute(
            "SELECT count(*) AS c FROM import_files WHERE batch_id=?", (batch_id,)
        ).fetchone()["c"]
        failed = conn.execute(
            "SELECT count(*) AS c FROM import_files WHERE batch_id=? AND parse_status!='parsed'",
            (batch_id,),
        ).fetchone()["c"]
        cands = conn.execute(
            "SELECT count(*) AS c FROM candidates WHERE import_batch_id=?", (batch_id,)
        ).fetchone()["c"]
        conn.execute(
            "UPDATE import_batches SET total_files=?, total_candidates=?, failed_count=? WHERE id=?",
            (files, cands, failed, batch_id),
        )
        conn.commit()
    finally:
        conn.close()


def count_batch_candidates(batch_id: int) -> int:
    """How many candidates this batch produced (for the delete confirmation)."""
    conn = _connect()
    try:
        if not _table_exists(conn, "import_batches"):
            return 0
        row = conn.execute(
            "SELECT count(*) AS c FROM candidates WHERE import_batch_id = ?",
            (batch_id,),
        ).fetchone()
        return int(row["c"]) if row else 0
    finally:
        conn.close()


def delete_import_batch(batch_id: int, delete_candidates: bool = False) -> dict | None:
    """Delete an import batch record, optionally with the candidates it produced.

    The two are separated because they answer different questions. Removing a
    mis-attributed or duplicated *record* should not destroy resumes that were
    parsed correctly, so the default detaches candidates (their
    `source_pdf_path` survives, which is what repair_import_batches.py needs to
    rebuild attribution later). Deleting the people as well is a second,
    explicit choice by the caller.

    Returns a summary of what was removed, or None when the batch is absent.
    """
    conn = _connect()
    try:
        if not _table_exists(conn, "import_batches"):
            return None
        row = conn.execute(
            "SELECT id, batch_name FROM import_batches WHERE id = ?", (batch_id,)
        ).fetchone()
        if not row:
            return None

        affected = conn.execute(
            "SELECT count(*) AS c FROM candidates WHERE import_batch_id = ?",
            (batch_id,),
        ).fetchone()["c"]

        if delete_candidates:
            conn.execute("DELETE FROM candidates WHERE import_batch_id = ?", (batch_id,))
        else:
            conn.execute(
                "UPDATE candidates SET import_batch_id = NULL, import_file_id = NULL "
                "WHERE import_batch_id = ?",
                (batch_id,),
            )

        if _table_exists(conn, "import_files"):
            conn.execute("DELETE FROM import_files WHERE batch_id = ?", (batch_id,))
        conn.execute("DELETE FROM import_batches WHERE id = ?", (batch_id,))
        conn.commit()
        return {
            "batch_id": batch_id,
            "batch_name": row["batch_name"],
            "candidates_deleted": int(affected) if delete_candidates else 0,
            "candidates_detached": 0 if delete_candidates else int(affected),
        }
    finally:
        conn.close()


def get_candidates_by_import_file(file_id: int) -> list[dict]:
    """Return the candidates parsed out of a single source PDF."""
    conn = _connect()
    use_dedupe = _dedupe_status_exists(conn)
    dedupe_select = (
        """, d.is_unique AS is_unique_candidate, d.dedupe_status,
                  d.confidence, d.reason AS dedupe_reason"""
        if use_dedupe
        else """, NULL AS is_unique_candidate, NULL AS dedupe_status,
                  NULL AS confidence, NULL AS dedupe_reason"""
    )
    dedupe_join = (
        "LEFT JOIN candidate_dedupe_status d ON c.id = d.candidate_id" if use_dedupe else ""
    )
    rows = conn.execute(
        f"""
        SELECT c.id, c.name, c.english_name, c.code_104, c.birth_year, c.age,
               c.education_level, c.school, c.major, c.years_of_experience,
               c.work_type,
               c.email, c.mobile1, c.photo_path, c.source_md_path,
               c.import_batch_id, c.import_file_id,
               c.interested, c.invitation_sent, c.skill_tags,
               m.overall_score, m.s_total, m.tags
               {dedupe_select}
          FROM candidates c
          {dedupe_join}
          LEFT JOIN match_results m ON c.id = m.candidate_id
         WHERE c.import_file_id = ?
         ORDER BY c.id
        """,
        (file_id,),
    ).fetchall()

    edu_rows = conn.execute(
        """
        SELECT e.candidate_id, e.school, e.department, e.degree_level, e.status,
               e.date_start, e.date_end
          FROM education e
          JOIN candidates c ON c.id = e.candidate_id
         WHERE c.import_file_id = ?
         ORDER BY e.candidate_id, e.seq
        """,
        (file_id,),
    ).fetchall()
    work_rows = conn.execute(
        """
        SELECT w.candidate_id, w.job_title, w.job_category, w.date_start, w.date_end
          FROM work_experiences w
          JOIN candidates c ON c.id = w.candidate_id
         WHERE c.import_file_id = ?
         ORDER BY w.candidate_id, w.seq
        """,
        (file_id,),
    ).fetchall()
    conn.close()

    edu_map: dict[int, list[dict]] = {}
    for er in edu_rows:
        edu_map.setdefault(er["candidate_id"], []).append(dict(er))

    work_map: dict[int, list[dict]] = {}
    for wr in work_rows:
        work_map.setdefault(wr["candidate_id"], []).append(dict(wr))

    results = []
    for r in rows:
        d = dict(r)
        d["skill_tags"] = json.loads(d.get("skill_tags") or "[]")
        d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
        edu_list = annotate_degree_levels(edu_map.get(d["id"], []))
        d["education"] = edu_list
        d["school_tier"] = best_school_tier(edu_list)
        d["candidate_type"] = calc_candidate_type(
            edu_list, {**d, "work_experiences": work_map.get(d["id"], [])}
        )
        d["interested"] = bool(d.get("interested", 0))
        d["invitation_sent"] = bool(d.get("invitation_sent", 0))
        if d.get("is_unique_candidate") is not None:
            d["is_unique_candidate"] = bool(d["is_unique_candidate"])
        results.append(d)
    return results


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def _current_tier_prompt_md5() -> str:
    """Hash of the tier prompt this process would use right now.

    Imported lazily: app.llm pulls in httpx and the whole LLM config, which the
    pure-DB helpers must not require.
    """
    try:
        from app.llm import tier_classifier_key
        return tier_classifier_key()
    except Exception:
        return ""


def get_cached_llm_tier(
    conn: sqlite3.Connection,
    candidate_id: int,
    raw_markdown: str,
    prompt_key: str | None = None,
) -> dict | None:
    """Return cached LLM tier dict if both the resume MD5 and prompt MD5 match, else None.

    ``prompt_key`` identifies the classifier that produced the tier.  It
    defaults to the builtin AI prompt hash, so existing callers and existing
    cached rows behave exactly as before.  A domain profile passes its own
    fingerprint instead: a tier classified against a sales profile must never be
    reused when scoring the same person for an accounting role, and without a
    per-profile key the single cache column would do exactly that.
    """
    from app.llm import tier_classifier_key
    key = prompt_key or tier_classifier_key()
    row = conn.execute(
        "SELECT llm_tier, llm_tier_reasoning, llm_tier_md5, llm_tier_prompt_md5 FROM candidates WHERE id=?",
        (candidate_id,),
    ).fetchone()
    if (
        row
        # Tier 0 (Non-AI) is a valid cached result — test for None, not falsiness,
        # otherwise every Tier-0 candidate re-queries the LLM on each run.
        and row["llm_tier"] is not None
        and row["llm_tier_md5"] == _md5(raw_markdown or "")
        and row["llm_tier_prompt_md5"] == key
    ):
        return {"tier": row["llm_tier"], "reasoning": row["llm_tier_reasoning"]}
    return None


def store_llm_tier_cache(
    conn: sqlite3.Connection,
    candidate_id: int,
    raw_markdown: str,
    result: dict,
    prompt_key: str | None = None,
):
    """Store LLM tier classification result in cache columns.

    ``prompt_key`` mirrors :func:`get_cached_llm_tier` — the classifier identity
    the tier belongs to, defaulting to the builtin AI prompt hash.
    """
    from app.llm import tier_classifier_key
    key = prompt_key or tier_classifier_key()
    conn.execute(
        "UPDATE candidates SET llm_tier=?, llm_tier_reasoning=?, llm_tier_md5=?, llm_tier_prompt_md5=? WHERE id=?",
        (result.get("tier"), result.get("reasoning", ""), _md5(raw_markdown or ""), key, candidate_id),
    )
    conn.commit()


def update_candidate_embedding(candidate_id: int, embedding: list[float]):
    conn = _connect()
    conn.execute(
        "UPDATE candidates SET embedding = ? WHERE id = ?",
        (json.dumps(embedding), candidate_id),
    )
    conn.commit()
    conn.close()


def get_candidate_embedding(candidate_id: int) -> list[float] | None:
    conn = _connect()
    row = conn.execute(
        "SELECT embedding FROM candidates WHERE id = ?", (candidate_id,)
    ).fetchone()
    conn.close()
    if not row or not row["embedding"]:
        return None
    return json.loads(row["embedding"])


def store_interview_questions(candidate_id: int, questions: dict):
    conn = _connect()
    conn.execute(
        "UPDATE candidates SET interview_questions = ? WHERE id = ?",
        (json.dumps(questions, ensure_ascii=False), candidate_id),
    )
    conn.commit()
    conn.close()


def delete_candidate(candidate_id: int):
    """Permanently delete a candidate and all related rows (cascade)."""
    conn = _connect()
    conn.execute("DELETE FROM candidates WHERE id = ?", (candidate_id,))
    conn.commit()
    conn.close()


def create_manual_candidate(
    name: str,
    email: str | None = None,
    mobile: str | None = None,
    education_level: str | None = None,
    school: str | None = None,
    years_of_experience: str | None = None,
    skills_text: str | None = None,
    skill_tags: list[str] | None = None,
    desired_salary: str | None = None,
) -> int:
    """Insert a manually entered candidate and mark them as interested. Returns new candidate id."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO candidates
               (name, email, mobile1, education_level, school, years_of_experience,
                skills_text, skill_tags, desired_salary, interested)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        (
            name,
            email,
            mobile,
            education_level,
            school,
            years_of_experience,
            skills_text,
            json.dumps(skill_tags or [], ensure_ascii=False),
            desired_salary,
        ),
    )
    candidate_id = cur.lastrowid
    conn.commit()
    conn.close()
    return candidate_id


def set_candidate_interested(candidate_id: int, interested: bool):
    conn = _connect()
    conn.execute(
        "UPDATE candidates SET interested = ? WHERE id = ?",
        (1 if interested else 0, candidate_id),
    )
    conn.commit()
    conn.close()


def get_interested_ids() -> list[int]:
    conn = _connect()
    rows = conn.execute(
        "SELECT id FROM candidates WHERE interested = 1 ORDER BY id"
    ).fetchall()
    conn.close()
    return [r["id"] for r in rows]


def set_candidate_invitation_sent(candidate_id: int, sent: bool):
    conn = _connect()
    conn.execute(
        "UPDATE candidates SET invitation_sent = ? WHERE id = ?",
        (1 if sent else 0, candidate_id),
    )
    conn.commit()
    conn.close()


def get_invitation_sent_ids() -> list[int]:
    conn = _connect()
    rows = conn.execute(
        "SELECT id FROM candidates WHERE invitation_sent = 1 ORDER BY id"
    ).fetchall()
    conn.close()
    return [r["id"] for r in rows]


def get_all_interviews() -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        """SELECT i.id, i.candidate_id, i.interview_date, i.interview_time,
                  i.interview_type, i.status, i.location, i.notes,
                  i.assignment_due_date, i.available_start_date, i.resume_notes,
                  i.created_at,
                  c.name AS candidate_name, c.photo_path, c.source_md_path
           FROM interviews i
           LEFT JOIN candidates c ON i.candidate_id = c.id
           ORDER BY i.interview_date, i.interview_time"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_interview(data: dict) -> int:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO interviews (
               candidate_id, interview_date, interview_time, interview_type,
               status, location, notes, assignment_due_date, available_start_date, resume_notes
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data.get("candidate_id"),
            data.get("interview_date"),
            data.get("interview_time"),
            data.get("interview_type", "onsite"),
            data.get("status"),
            data.get("location"),
            data.get("notes"),
            data.get("assignment_due_date"),
            data.get("available_start_date"),
            data.get("resume_notes"),
        ),
    )
    interview_id = cur.lastrowid
    conn.commit()
    conn.close()
    return interview_id


def update_interview(interview_id: int, data: dict):
    conn = _connect()
    conn.execute(
        """UPDATE interviews SET
               candidate_id=?, interview_date=?, interview_time=?, interview_type=?,
               status=?, location=?, notes=?,
               assignment_due_date=?, available_start_date=?, resume_notes=?
           WHERE id=?""",
        (
            data.get("candidate_id"),
            data.get("interview_date"),
            data.get("interview_time"),
            data.get("interview_type", "onsite"),
            data.get("status"),
            data.get("location"),
            data.get("notes"),
            data.get("assignment_due_date"),
            data.get("available_start_date"),
            data.get("resume_notes"),
            interview_id,
        ),
    )
    conn.commit()
    conn.close()


def get_interview_statuses() -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM interview_statuses ORDER BY sort_order, id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_interview_status(label: str, color: str = "gray") -> int:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO interview_statuses (label, color, sort_order)
           VALUES (?, ?, (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM interview_statuses))""",
        (label, color),
    )
    status_id = cur.lastrowid
    conn.commit()
    conn.close()
    return status_id


def delete_interview_status(status_id: int):
    conn = _connect()
    conn.execute("DELETE FROM interview_statuses WHERE id = ?", (status_id,))
    conn.commit()
    conn.close()


def get_interview_types() -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM interview_types ORDER BY sort_order, id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_interview_type(label: str, color: str = "gray", value: str | None = None) -> dict:
    """Add an interview type. Returns the stored row.

    ``value`` is what lands in interviews.interview_type. It is derived from the
    label only when not given, and never regenerated afterwards: the label is
    display text an operator may reword, while the value is a foreign key in
    everything already scheduled.
    """
    slug = (value or "").strip()
    if not slug:
        # ASCII slug where the label allows one; otherwise fall back to a
        # stable synthetic id, since a Chinese label slugifies to nothing.
        slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
    conn = _connect()
    cur = conn.cursor()
    if not slug:
        slug = "type-%d" % (
            conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM interview_types").fetchone()[0]
        )
    cur.execute(
        """INSERT INTO interview_types (value, label, color, sort_order)
           VALUES (?, ?, ?, (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM interview_types))""",
        (slug, label, color),
    )
    type_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {"id": type_id, "value": slug, "label": label, "color": color}


def delete_interview_type(type_id: int) -> None:
    """Remove a type. Interviews already using it keep their stored value.

    Deliberately not a cascade: an interview that happened as a phone screen
    still happened as one, and rewriting history to make a list tidy loses
    information the row is the only record of.
    """
    conn = _connect()
    conn.execute("DELETE FROM interview_types WHERE id = ?", (type_id,))
    conn.commit()
    conn.close()


def delete_interview(interview_id: int):
    conn = _connect()
    conn.execute("DELETE FROM interviews WHERE id = ?", (interview_id,))
    conn.commit()
    conn.close()


def delete_candidate_data(candidate_id: int):
    """Delete all data for a candidate (used before re-parse)."""
    conn = _connect()
    for table in ("work_experiences", "education", "skills", "references_", "attachments"):
        conn.execute(f"DELETE FROM {table} WHERE candidate_id = ?", (candidate_id,))
    conn.commit()
    conn.close()


def update_candidate_from_extract(candidate_id: int, extract: ResumeExtract, raw_markdown: str):
    """Re-insert extracted data for an existing candidate."""
    conn = _connect()

    # Update scalar fields
    conn.execute(
        """UPDATE candidates SET
            name=?, english_name=?, code_104=?, birth_year=?, age=?, nationality=?,
            current_status=?, earliest_start=?, education_level=?, school=?,
            major=?, military_status=?, desired_salary=?,
            desired_job_categories=?, desired_locations=?, desired_industry=?,
            ideal_positions=?, years_of_experience=?, linkedin_url=?,
            photo_path=?, email=?, mobile1=?, mobile2=?, phone_home=?,
            phone_work=?, district=?, mailing_address=?, work_type=?,
            shift_preference=?, remote_work_preference=?, skills_text=?,
            skill_tags=?, self_introduction=?,
            personal_motto=?, personal_traits=?, autobiography=?,
            raw_markdown=?
        WHERE id=?""",
        (
            extract.name, extract.english_name, extract.code_104, extract.birth_year, extract.age,
            extract.nationality, extract.current_status, extract.earliest_start,
            extract.education_level, extract.school, extract.major,
            extract.military_status, extract.desired_salary,
            json.dumps(extract.desired_job_categories, ensure_ascii=False),
            json.dumps(extract.desired_locations, ensure_ascii=False),
            extract.desired_industry,
            json.dumps(extract.ideal_positions, ensure_ascii=False),
            extract.years_of_experience, extract.linkedin_url, extract.photo_path,
            extract.email, extract.mobile1, extract.mobile2, extract.phone_home,
            extract.phone_work, extract.district, extract.mailing_address,
            extract.work_type, extract.shift_preference, extract.remote_work_preference,
            extract.skills_text,
            json.dumps(extract.skill_tags, ensure_ascii=False),
            extract.self_introduction,
            extract.personal_motto, extract.personal_traits, extract.autobiography,
            raw_markdown, candidate_id,
        ),
    )
    conn.commit()
    conn.close()

    # Delete and re-insert child records
    delete_candidate_data(candidate_id)
    conn = _connect()
    cur = conn.cursor()
    for we in extract.work_experiences:
        cur.execute(
            """INSERT INTO work_experiences (
                candidate_id, seq, company_name, date_start, date_end, duration,
                industry, company_size, job_category, management_responsibility,
                job_title, job_description, job_skills
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                candidate_id, we.seq, we.company_name, we.date_start,
                we.date_end, we.duration, we.industry, we.company_size,
                we.job_category, we.management_responsibility, we.job_title,
                we.job_description, we.job_skills,
            ),
        )
    for ed in extract.education:
        cur.execute(
            """INSERT INTO education (
                candidate_id, seq, school, department, degree_level,
                date_start, date_end, region, status
            ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                candidate_id, ed.seq, ed.school, ed.department,
                ed.degree_level, ed.date_start, ed.date_end,
                ed.region, ed.status,
            ),
        )
    for tag in extract.skill_tags:
        cur.execute(
            "INSERT INTO skills (candidate_id, skill_name) VALUES (?,?)",
            (candidate_id, tag),
        )
    for ref in extract.references:
        cur.execute(
            """INSERT INTO references_ (
                candidate_id, ref_name, ref_email, ref_org, ref_title
            ) VALUES (?,?,?,?,?)""",
            (candidate_id, ref.ref_name, ref.ref_email, ref.ref_org, ref.ref_title),
        )
    for att in extract.attachments:
        cur.execute(
            """INSERT INTO attachments (
                candidate_id, attachment_type, seq, name, description, url
            ) VALUES (?,?,?,?,?,?)""",
            (candidate_id, att.attachment_type, att.seq, att.name, att.description, att.url),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Erasure and retention (GDPR-style right to be forgotten)
# ---------------------------------------------------------------------------

# Child tables holding candidate PII. interviews is included explicitly because
# its FK is ON DELETE SET NULL, not CASCADE — a plain candidate delete would
# leave the interview row behind with its notes intact and the link cut, which
# is exactly the orphan an erasure request must not leave.
CANDIDATE_CHILD_TABLES = (
    "education",
    "skills",
    "work_experiences",
    "attachments",
    "references_",
    "match_results",
    "candidate_dedupe_status",
    "interviews",
)


def _candidate_artifact_paths(conn: sqlite3.Connection, candidate_id: int) -> list[Path]:
    """On-disk files/directories that belong to this candidate alone.

    Deliberately conservative about the source PDF: one 104 export PDF holds up
    to 200 applicants (3179 candidates map to just 18 PDFs in production), so it
    is removed ONLY when no other candidate still references it. The per-candidate
    markdown directory is unique and always removable.
    """
    row = conn.execute(
        "SELECT source_pdf_path, source_md_path FROM candidates WHERE id = ?",
        (candidate_id,),
    ).fetchone()
    if not row:
        return []

    targets: list[Path] = []

    md_path = (row["source_md_path"] or "").strip()
    if md_path:
        md_file = Path(md_path)
        # The candidate's own output directory holds the parsed markdown and the
        # photos extracted from it; both are personal data.
        parent = md_file.parent
        shared = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE id != ? AND source_md_path LIKE ?",
            (candidate_id, f"{parent}/%"),
        ).fetchone()[0]
        targets.append(parent if not shared else md_file)

    pdf_path = (row["source_pdf_path"] or "").strip()
    if pdf_path:
        others = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE id != ? AND source_pdf_path = ?",
            (candidate_id, pdf_path),
        ).fetchone()[0]
        if not others:
            targets.append(Path(pdf_path))

    return targets


def _remove_path(target: Path) -> bool:
    """Delete a file or directory tree. Returns True if something was removed."""
    import shutil

    try:
        if target.is_dir():
            shutil.rmtree(target)
            return True
        if target.is_file():
            target.unlink()
            return True
    except OSError:
        logger.warning("Erasure: could not remove %s", target, exc_info=True)
    return False


def erase_candidate(candidate_id: int, remove_files: bool = True) -> dict:
    """Irreversibly erase a candidate: DB rows AND on-disk artifacts.

    This is the right-to-erasure path, and is stronger than delete_candidate(),
    which relies on FK cascade alone and therefore leaves both the interviews row
    (ON DELETE SET NULL) and every on-disk artifact in place.

    Returns a report of what was removed, for the audit trail. There is no undo.
    """
    conn = _connect()
    try:
        exists = conn.execute(
            "SELECT id, name FROM candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        if not exists:
            return {"candidate_id": candidate_id, "found": False, "rows": {}, "files": []}

        artifacts = _candidate_artifact_paths(conn, candidate_id) if remove_files else []

        rows_deleted: dict[str, int] = {}
        for table in CANDIDATE_CHILD_TABLES:
            if not _table_exists(conn, table):
                continue
            cur = conn.execute(
                f"DELETE FROM {table} WHERE candidate_id = ?", (candidate_id,)
            )
            if cur.rowcount:
                rows_deleted[table] = cur.rowcount

        cur = conn.execute("DELETE FROM candidates WHERE id = ?", (candidate_id,))
        rows_deleted["candidates"] = cur.rowcount
        conn.commit()
    finally:
        conn.close()

    removed_files = [str(p) for p in artifacts if _remove_path(p)]

    logger.info(
        "Erased candidate %d: %s; removed %d artifact path(s)",
        candidate_id, rows_deleted, len(removed_files),
    )
    return {
        "candidate_id": candidate_id,
        "found": True,
        "rows": rows_deleted,
        "files": removed_files,
    }


def find_expired_candidates(retention_days: int) -> list[dict]:
    """Candidates whose created_at is older than the retention window.

    `retention_days <= 0` means retention is disabled and returns nothing — that
    is the default, and it must stay the default so no data is ever removed by
    simply upgrading.
    """
    if not retention_days or retention_days <= 0:
        return []

    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT id, name, created_at, source_md_path
               FROM candidates
               WHERE created_at IS NOT NULL
                 AND created_at < datetime('now', ?)
               ORDER BY created_at""",
            (f"-{int(retention_days)} days",),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
