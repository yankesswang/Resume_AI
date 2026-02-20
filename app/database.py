import hashlib
import json
import sqlite3
from pathlib import Path

from app.models import (
    AttachmentExtract,
    EducationExtract,
    EnhancedMatchResult,
    MatchResultExtract,
    ReferenceExtract,
    ResumeExtract,
    WorkExperienceExtract,
)

DB_PATH = Path(__file__).resolve().parent.parent / "resume_ai.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


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

    conn.commit()
    conn.close()


def insert_candidate(
    extract: ResumeExtract,
    raw_markdown: str,
    source_pdf_path: str = "",
    source_md_path: str = "",
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
            # Update source paths
            c2 = _connect()
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
            raw_markdown, source_pdf_path, source_md_path
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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


def get_all_candidates_summary() -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        """SELECT c.id, c.name, c.code_104, c.birth_year, c.education_level, c.school, c.major,
                  c.years_of_experience, c.ideal_positions,
                  c.desired_job_categories, c.skill_tags,
                  c.photo_path, c.source_md_path,
                  m.overall_score, m.s_ai, m.m_eng, m.s_total,
                  m.experience_detail, m.passed_hard_filter, m.tags
           FROM candidates c
           LEFT JOIN match_results m ON c.id = m.candidate_id
           ORDER BY c.id DESC"""
    ).fetchall()

    # Fetch all education records grouped by candidate
    edu_rows = conn.execute(
        "SELECT candidate_id, school, department, degree_level FROM education ORDER BY candidate_id, seq"
    ).fetchall()
    conn.close()

    edu_map: dict[int, list[dict]] = {}
    for er in edu_rows:
        cid = er["candidate_id"]
        edu_map.setdefault(cid, []).append(dict(er))

    results = []
    for r in rows:
        d = dict(r)
        d["ideal_positions"] = json.loads(d["ideal_positions"] or "[]")
        d["desired_job_categories"] = json.loads(d["desired_job_categories"] or "[]")
        d["skill_tags"] = json.loads(d["skill_tags"] or "[]")
        d["education"] = edu_map.get(d["id"], [])
        # Parse enhanced scoring fields
        if d.get("experience_detail"):
            d["experience_detail"] = json.loads(d["experience_detail"])
        if d.get("tags"):
            d["tags"] = json.loads(d["tags"])
        else:
            d["tags"] = []
        if "passed_hard_filter" in d and d["passed_hard_filter"] is not None:
            d["passed_hard_filter"] = bool(d["passed_hard_filter"])
        results.append(d)
    return results


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
    candidate["education"] = [
        dict(r) for r in conn.execute(
            "SELECT * FROM education WHERE candidate_id = ? ORDER BY seq",
            (candidate_id,),
        ).fetchall()
    ]
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
                tags, interview_suggestions
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                       "skill_detail", "hard_filter_failures", "tags", "interview_suggestions"):
        if json_field in d and d[json_field]:
            d[json_field] = json.loads(d[json_field])
        elif json_field in d:
            d[json_field] = {} if json_field.endswith("_detail") else []
    if "passed_hard_filter" in d:
        d["passed_hard_filter"] = bool(d.get("passed_hard_filter", 1))
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
                   c.skill_tags, c.email, c.mobile1, c.desired_salary,
                   c.desired_job_categories, c.ideal_positions,
                   c.photo_path, c.source_md_path,
                   m.overall_score, m.education_score, m.experience_score,
                   m.skills_score, m.s_ai, m.m_eng, m.s_total,
                   m.strengths, m.gaps, m.analysis_text,
                   m.experience_detail, m.tags, m.passed_hard_filter
            FROM candidates c
            LEFT JOIN match_results m ON c.id = m.candidate_id
            WHERE c.id IN ({placeholders})
            ORDER BY m.overall_score DESC NULLS LAST""",
        candidate_ids,
    ).fetchall()

    # Fetch education and work experiences
    edu_rows = conn.execute(
        f"SELECT candidate_id, school, department, degree_level, date_start, date_end "
        f"FROM education WHERE candidate_id IN ({placeholders}) ORDER BY candidate_id, seq",
        candidate_ids,
    ).fetchall()
    work_rows = conn.execute(
        f"SELECT candidate_id, company_name, job_title, date_start, date_end, duration, industry "
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
        d["education"] = edu_map.get(d["id"], [])
        d["work_experiences"] = work_map.get(d["id"], [])
        results.append(d)
    return results


def get_filter_options() -> dict:
    """Return distinct filter options for the frontend."""
    conn = _connect()
    education_levels = [
        r[0] for r in conn.execute(
            "SELECT DISTINCT education_level FROM candidates WHERE education_level IS NOT NULL AND education_level != '' ORDER BY education_level"
        ).fetchall()
    ]
    skill_tags = sorted({
        r[0] for r in conn.execute(
            "SELECT DISTINCT skill_name FROM skills WHERE skill_name IS NOT NULL AND skill_name != ''"
        ).fetchall()
    })
    conn.close()
    return {
        "education_levels": education_levels,
        "skill_tags": skill_tags,
        "experience_ranges": ["0-2年", "3-5年", "5-10年", "10年+"],
        "score_ranges": ["80+", "60-79", "40-59", "<40", "No Score"],
    }


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def get_cached_llm_tier(conn: sqlite3.Connection, candidate_id: int, raw_markdown: str) -> dict | None:
    """Return cached LLM tier dict if both the resume MD5 and prompt MD5 match, else None."""
    from app.llm import TIER_CLASSIFY_PROMPT_MD5
    row = conn.execute(
        "SELECT llm_tier, llm_tier_reasoning, llm_tier_md5, llm_tier_prompt_md5 FROM candidates WHERE id=?",
        (candidate_id,),
    ).fetchone()
    if (
        row
        and row["llm_tier"]
        and row["llm_tier_md5"] == _md5(raw_markdown or "")
        and row["llm_tier_prompt_md5"] == TIER_CLASSIFY_PROMPT_MD5
    ):
        return {"tier": row["llm_tier"], "reasoning": row["llm_tier_reasoning"]}
    return None


def store_llm_tier_cache(conn: sqlite3.Connection, candidate_id: int, raw_markdown: str, result: dict):
    """Store LLM tier classification result in cache columns."""
    from app.llm import TIER_CLASSIFY_PROMPT_MD5
    conn.execute(
        "UPDATE candidates SET llm_tier=?, llm_tier_reasoning=?, llm_tier_md5=?, llm_tier_prompt_md5=? WHERE id=?",
        (result.get("tier"), result.get("reasoning", ""), _md5(raw_markdown or ""), TIER_CLASSIFY_PROMPT_MD5, candidate_id),
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
