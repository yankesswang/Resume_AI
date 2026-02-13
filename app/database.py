import json
import sqlite3
from pathlib import Path

from app.models import (
    AttachmentExtract,
    EducationExtract,
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
        conn.commit()

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

    cur.execute(
        """INSERT INTO candidates (
            name, english_name, code_104, birth_year, age, nationality, current_status,
            earliest_start, education_level, school, major, military_status,
            desired_salary, desired_job_categories, desired_locations,
            desired_industry, ideal_positions, years_of_experience,
            linkedin_url, photo_path, email, mobile1, mobile2, phone_home,
            phone_work, district, mailing_address, work_type, shift_preference,
            remote_work_preference, skills_text, skill_tags, self_introduction,
            raw_markdown, source_pdf_path, source_md_path
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
        """SELECT c.id, c.name, c.code_104, c.education_level, c.school, c.major,
                  c.years_of_experience, c.ideal_positions,
                  c.desired_job_categories, c.skill_tags,
                  c.photo_path, c.source_md_path,
                  m.overall_score
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


def upsert_match_result(candidate_id: int, job_id: int, result: MatchResultExtract):
    conn = _connect()
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
    return d


def ensure_job_requirement(title: str, source_json: str) -> int:
    conn = _connect()
    row = conn.execute(
        "SELECT id FROM job_requirements WHERE title = ?", (title,)
    ).fetchone()
    if row:
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
            skill_tags=?, self_introduction=?, raw_markdown=?
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
            extract.self_introduction, raw_markdown, candidate_id,
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
