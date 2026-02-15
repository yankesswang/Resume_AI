"""Repair candidates with broken/missing data by re-parsing their stored raw_markdown.

Targets:
  - Candidates with empty or broken names
  - Candidates missing code_104
  - Candidates with name artifacts (e.g. "英⽂名字:" leaked into name)

Usage:
    python repair_candidates.py [--dry-run]
"""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

# Ensure app modules are importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import DB_PATH, init_db, delete_candidate_data
from app.regex_parser import parse_resume_markdown


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def find_broken_candidates(conn: sqlite3.Connection) -> list[dict]:
    """Find candidates that need repair."""
    # Find candidates with broken names, missing code_104, or bad education data
    rows = conn.execute("""
        SELECT DISTINCT c.id, c.name, c.code_104, c.raw_markdown
        FROM candidates c
        LEFT JOIN education e ON c.id = e.candidate_id
        WHERE c.raw_markdown IS NOT NULL AND c.raw_markdown != ''
          AND (
            c.name IS NULL OR c.name = ''
            OR c.name LIKE '%英⽂名字%' OR c.name LIKE '%英文名字%'
            OR c.name LIKE '%|%'
            OR c.code_104 IS NULL OR c.code_104 = ''
            OR c.school LIKE '%<br>%'
            OR e.school LIKE '%職務%' OR e.school LIKE '%工作%' OR e.school LIKE '%⼯作%'
            OR e.school LIKE '%,%'
            OR (e.school IS NOT NULL AND e.school = '' AND e.department = '')
          )
    """).fetchall()
    return [dict(r) for r in rows]


def repair_candidate(candidate: dict, dry_run: bool) -> dict:
    """Re-parse a candidate's raw_markdown and return repair info."""
    cid = candidate["id"]
    old_name = candidate["name"] or ""
    old_code = candidate["code_104"] or ""
    raw_md = candidate["raw_markdown"]

    try:
        extract = parse_resume_markdown(raw_md)
    except Exception as e:
        return {"id": cid, "status": "error", "error": str(e)}

    new_name = extract.name
    new_code = extract.code_104

    changes = {}
    if not old_name or "英⽂名字" in old_name or "英文名字" in old_name or "|" in old_name:
        if new_name and new_name != old_name:
            changes["name"] = (old_name, new_name)
    if not old_code and new_code:
        changes["code_104"] = (old_code, new_code)

    # Always mark as needing repair if education/school data is being re-parsed
    # (the caller already filtered for broken education data)
    if not changes:
        changes["education"] = ("(re-parsed)", f"{len(extract.education)} entries")

    if not dry_run:
        conn = _connect()
        # Update scalar fields from the re-parsed extract
        conn.execute(
            """UPDATE candidates SET
                name=?, english_name=?, code_104=?, birth_year=?, age=?,
                nationality=?, current_status=?, earliest_start=?,
                education_level=?, school=?, major=?, military_status=?,
                desired_salary=?, desired_job_categories=?, desired_locations=?,
                desired_industry=?, ideal_positions=?, years_of_experience=?,
                linkedin_url=?, photo_path=?, email=?, mobile1=?, mobile2=?,
                phone_home=?, phone_work=?, district=?, mailing_address=?,
                work_type=?, shift_preference=?, remote_work_preference=?,
                skills_text=?, skill_tags=?, self_introduction=?
            WHERE id=?""",
            (
                extract.name, extract.english_name, extract.code_104,
                extract.birth_year, extract.age, extract.nationality,
                extract.current_status, extract.earliest_start,
                extract.education_level, extract.school, extract.major,
                extract.military_status, extract.desired_salary,
                json.dumps(extract.desired_job_categories, ensure_ascii=False),
                json.dumps(extract.desired_locations, ensure_ascii=False),
                extract.desired_industry,
                json.dumps(extract.ideal_positions, ensure_ascii=False),
                extract.years_of_experience, extract.linkedin_url,
                extract.photo_path, extract.email, extract.mobile1,
                extract.mobile2, extract.phone_home, extract.phone_work,
                extract.district, extract.mailing_address,
                extract.work_type, extract.shift_preference,
                extract.remote_work_preference, extract.skills_text,
                json.dumps(extract.skill_tags, ensure_ascii=False),
                extract.self_introduction, cid,
            ),
        )
        conn.commit()

        # Re-insert child records
        delete_candidate_data(cid)
        cur = conn.cursor()
        for we in extract.work_experiences:
            cur.execute(
                """INSERT INTO work_experiences (
                    candidate_id, seq, company_name, date_start, date_end, duration,
                    industry, company_size, job_category, management_responsibility,
                    job_title, job_description, job_skills
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    cid, we.seq, we.company_name, we.date_start,
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
                    cid, ed.seq, ed.school, ed.department,
                    ed.degree_level, ed.date_start, ed.date_end,
                    ed.region, ed.status,
                ),
            )
        for tag in extract.skill_tags:
            cur.execute(
                "INSERT INTO skills (candidate_id, skill_name) VALUES (?,?)",
                (cid, tag),
            )
        for ref in extract.references:
            cur.execute(
                """INSERT INTO references_ (
                    candidate_id, ref_name, ref_email, ref_org, ref_title
                ) VALUES (?,?,?,?,?)""",
                (cid, ref.ref_name, ref.ref_email, ref.ref_org, ref.ref_title),
            )
        for att in extract.attachments:
            cur.execute(
                """INSERT INTO attachments (
                    candidate_id, attachment_type, seq, name, description, url
                ) VALUES (?,?,?,?,?,?)""",
                (cid, att.attachment_type, att.seq, att.name, att.description, att.url),
            )
        conn.commit()
        conn.close()

    return {"id": cid, "status": "repaired", "changes": changes}


def main():
    parser = argparse.ArgumentParser(description="Repair broken candidate records")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing to DB")
    args = parser.parse_args()

    # Ensure DB schema is up to date (applies migrations like code_104 column)
    init_db()

    conn = _connect()
    broken = find_broken_candidates(conn)
    conn.close()

    print(f"Found {len(broken)} candidates to check")
    if args.dry_run:
        print("=== DRY RUN — no changes will be written ===\n")

    stats = {"repaired": 0, "skip": 0, "error": 0, "still_empty_name": 0}

    for candidate in broken:
        result = repair_candidate(candidate, dry_run=args.dry_run)
        status = result["status"]
        stats[status] = stats.get(status, 0) + 1

        if status == "repaired":
            changes_str = ", ".join(
                f"{k}: '{old}' -> '{new}'" for k, (old, new) in result["changes"].items()
            )
            print(f"  [REPAIR] id={result['id']}  {changes_str}")
        elif status == "error":
            print(f"  [ERROR]  id={result['id']}  {result['error']}")

    # Report candidates still missing name after repair
    if not args.dry_run:
        conn = _connect()
        still_broken = conn.execute(
            "SELECT id FROM candidates WHERE name IS NULL OR name = ''"
        ).fetchall()
        conn.close()
        stats["still_empty_name"] = len(still_broken)

    print(f"\n--- Summary ---")
    print(f"Repaired:         {stats['repaired']}")
    print(f"Skipped (no fix): {stats['skip']}")
    print(f"Errors:           {stats['error']}")
    if not args.dry_run:
        print(f"Still empty name: {stats['still_empty_name']}")


if __name__ == "__main__":
    main()
