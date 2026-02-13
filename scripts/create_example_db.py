"""Create an example database with fake candidate data for testing."""

import json
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "resume_ai.example.db")


def create_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Create schema
    c.executescript("""
        CREATE TABLE candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            english_name TEXT,
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
            desired_job_categories TEXT,
            desired_locations TEXT,
            desired_industry TEXT,
            ideal_positions TEXT,
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
            skill_tags TEXT,
            self_introduction TEXT,
            raw_markdown TEXT,
            source_pdf_path TEXT,
            source_md_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            code_104 TEXT
        );

        CREATE TABLE work_experiences (
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

        CREATE TABLE education (
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

        CREATE TABLE skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            skill_name TEXT,
            FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
        );

        CREATE TABLE references_ (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            ref_name TEXT,
            ref_email TEXT,
            ref_org TEXT,
            ref_title TEXT,
            FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
        );

        CREATE TABLE attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            attachment_type TEXT,
            seq INTEGER,
            name TEXT,
            description TEXT,
            url TEXT,
            FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
        );

        CREATE TABLE job_requirements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            source_json TEXT
        );

        CREATE TABLE match_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            overall_score REAL,
            education_score REAL,
            experience_score REAL,
            skills_score REAL,
            analysis_text TEXT,
            strengths TEXT,
            gaps TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE,
            FOREIGN KEY (job_id) REFERENCES job_requirements(id) ON DELETE CASCADE,
            UNIQUE(candidate_id, job_id)
        );
    """)

    # Insert fake candidates
    candidates = [
        {
            "name": "王小明",
            "english_name": "Alex Wang",
            "birth_year": "1990",
            "age": "35",
            "nationality": "台灣",
            "current_status": "在職中",
            "earliest_start": "一個月內",
            "education_level": "碩士",
            "school": "國立台灣大學",
            "major": "資訊工程",
            "military_status": "役畢",
            "desired_salary": "80000-100000",
            "desired_job_categories": json.dumps(["軟體工程師", "後端工程師"]),
            "desired_locations": json.dumps(["台北市", "新北市"]),
            "desired_industry": "資訊科技",
            "ideal_positions": json.dumps(["Senior Software Engineer", "Tech Lead"]),
            "years_of_experience": "10",
            "email": "alex.wang@example.com",
            "mobile1": "0912-345-678",
            "district": "台北市信義區",
            "work_type": "全職",
            "shift_preference": "日班",
            "remote_work_preference": "混合",
            "skills_text": "Python, FastAPI, PostgreSQL, Docker, AWS, React",
            "skill_tags": json.dumps(["Python", "FastAPI", "PostgreSQL", "Docker", "AWS", "React"]),
            "self_introduction": "十年軟體開發經驗，擅長後端架構設計與雲端部署。",
            "code_104": "EX-001",
        },
        {
            "name": "林美玲",
            "english_name": "Mei-Ling Lin",
            "birth_year": "1995",
            "age": "30",
            "nationality": "台灣",
            "current_status": "待業中",
            "earliest_start": "隨時",
            "education_level": "學士",
            "school": "國立成功大學",
            "major": "工業設計",
            "military_status": "免役",
            "desired_salary": "50000-65000",
            "desired_job_categories": json.dumps(["UI/UX設計師", "產品設計師"]),
            "desired_locations": json.dumps(["台北市", "台中市"]),
            "desired_industry": "網際網路",
            "ideal_positions": json.dumps(["UI/UX Designer", "Product Designer"]),
            "years_of_experience": "5",
            "email": "meiling.lin@example.com",
            "mobile1": "0923-456-789",
            "district": "台中市西屯區",
            "work_type": "全職",
            "shift_preference": "日班",
            "remote_work_preference": "遠端優先",
            "skills_text": "Figma, Sketch, Adobe XD, HTML/CSS, User Research",
            "skill_tags": json.dumps(["Figma", "Sketch", "Adobe XD", "HTML/CSS", "User Research"]),
            "self_introduction": "五年UI/UX設計經驗，專注於使用者研究與互動設計。",
            "code_104": "EX-002",
        },
        {
            "name": "陳志豪",
            "english_name": "Jason Chen",
            "birth_year": "1988",
            "age": "37",
            "nationality": "台灣",
            "current_status": "在職中",
            "earliest_start": "兩週內",
            "education_level": "碩士",
            "school": "國立交通大學",
            "major": "電機工程",
            "military_status": "役畢",
            "desired_salary": "100000-130000",
            "desired_job_categories": json.dumps(["資料科學家", "機器學習工程師"]),
            "desired_locations": json.dumps(["台北市", "新竹市"]),
            "desired_industry": "人工智慧",
            "ideal_positions": json.dumps(["Data Scientist", "ML Engineer", "AI Lead"]),
            "years_of_experience": "12",
            "email": "jason.chen@example.com",
            "mobile1": "0934-567-890",
            "district": "新竹市東區",
            "work_type": "全職",
            "shift_preference": "彈性",
            "remote_work_preference": "混合",
            "skills_text": "Python, TensorFlow, PyTorch, SQL, Spark, MLOps",
            "skill_tags": json.dumps(["Python", "TensorFlow", "PyTorch", "SQL", "Spark", "MLOps"]),
            "self_introduction": "十二年資料科學與ML經驗，曾帶領團隊完成多項AI產品。",
            "code_104": "EX-003",
        },
    ]

    for cand in candidates:
        cols = ", ".join(cand.keys())
        placeholders = ", ".join(["?"] * len(cand))
        c.execute(f"INSERT INTO candidates ({cols}) VALUES ({placeholders})", list(cand.values()))

    # Work experiences
    work_experiences = [
        (1, 1, "台灣科技公司", "2020-01", "至今", "5年", "資訊科技", "500-1000人", "軟體工程", "否", "Senior Backend Engineer", "負責核心API開發與微服務架構設計", "Python, FastAPI, Docker"),
        (1, 2, "新創軟體公司", "2016-03", "2019-12", "3年9個月", "資訊科技", "50-100人", "軟體工程", "否", "Software Engineer", "全端開發，維護公司主要產品", "Python, Django, React"),
        (2, 1, "數位設計工作室", "2021-06", "至今", "4年", "設計服務", "10-50人", "UI/UX設計", "否", "Senior UI/UX Designer", "負責產品設計與使用者研究", "Figma, User Research"),
        (2, 2, "網路平台公司", "2019-07", "2021-05", "1年10個月", "網際網路", "100-500人", "UI設計", "否", "UI Designer", "設計Web與Mobile介面", "Sketch, Adobe XD"),
        (3, 1, "AI新創公司", "2019-01", "至今", "6年", "人工智慧", "100-500人", "資料科學", "是", "AI Lead", "帶領ML團隊開發推薦系統與NLP模型", "PyTorch, MLOps, Spark"),
        (3, 2, "半導體公司", "2014-08", "2018-12", "4年4個月", "半導體", "1000人以上", "資料分析", "否", "Data Scientist", "製程良率分析與預測模型開發", "Python, TensorFlow, SQL"),
    ]
    for we in work_experiences:
        c.execute(
            "INSERT INTO work_experiences (candidate_id, seq, company_name, date_start, date_end, duration, industry, company_size, job_category, management_responsibility, job_title, job_description, job_skills) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            we,
        )

    # Education
    education = [
        (1, 1, "國立台灣大學", "資訊工程研究所", "碩士", "2013-09", "2015-06", "台灣", "畢業"),
        (1, 2, "國立台灣大學", "資訊工程學系", "學士", "2009-09", "2013-06", "台灣", "畢業"),
        (2, 1, "國立成功大學", "工業設計學系", "學士", "2013-09", "2017-06", "台灣", "畢業"),
        (3, 1, "國立交通大學", "電機工程研究所", "碩士", "2010-09", "2012-06", "台灣", "畢業"),
        (3, 2, "國立交通大學", "電機工程學系", "學士", "2006-09", "2010-06", "台灣", "畢業"),
    ]
    for edu in education:
        c.execute(
            "INSERT INTO education (candidate_id, seq, school, department, degree_level, date_start, date_end, region, status) VALUES (?,?,?,?,?,?,?,?,?)",
            edu,
        )

    # Skills
    all_skills = [
        (1, "Python"), (1, "FastAPI"), (1, "PostgreSQL"), (1, "Docker"), (1, "AWS"), (1, "React"),
        (2, "Figma"), (2, "Sketch"), (2, "Adobe XD"), (2, "HTML/CSS"), (2, "User Research"),
        (3, "Python"), (3, "TensorFlow"), (3, "PyTorch"), (3, "SQL"), (3, "Spark"), (3, "MLOps"),
    ]
    for s in all_skills:
        c.execute("INSERT INTO skills (candidate_id, skill_name) VALUES (?,?)", s)

    # Job requirement
    job_req = {
        "title": "Senior Backend Engineer",
        "description": "負責後端系統開發與維護",
        "requirements": {
            "education": "碩士以上，資訊相關科系",
            "experience": "5年以上後端開發經驗",
            "skills": ["Python", "FastAPI or Django", "PostgreSQL", "Docker", "AWS"],
        },
    }
    c.execute(
        "INSERT INTO job_requirements (title, source_json) VALUES (?, ?)",
        ("Senior Backend Engineer", json.dumps(job_req, ensure_ascii=False)),
    )

    # Match results
    match_results = [
        (1, 1, 92.0, 95.0, 90.0, 91.0, "非常匹配，具備完整的後端開發經驗與技術棧。",
         json.dumps(["碩士資工背景完全符合", "10年開發經驗豐富", "技術棧高度吻合"]),
         json.dumps(["缺少Kubernetes經驗"])),
        (2, 1, 35.0, 40.0, 20.0, 45.0, "背景偏設計領域，與後端工程師需求差距較大。",
         json.dumps(["具備HTML/CSS基礎"]),
         json.dumps(["非資訊相關科系", "無後端開發經驗", "缺少核心技術棧"])),
        (3, 1, 78.0, 90.0, 75.0, 70.0, "資料科學背景強，Python能力佳，但後端框架經驗不足。",
         json.dumps(["碩士電機背景相關", "Python能力強", "12年資深經驗"]),
         json.dumps(["缺少FastAPI/Django經驗", "未使用過Docker部署"])),
    ]
    for mr in match_results:
        c.execute(
            "INSERT INTO match_results (candidate_id, job_id, overall_score, education_score, experience_score, skills_score, analysis_text, strengths, gaps) VALUES (?,?,?,?,?,?,?,?,?)",
            mr,
        )

    conn.commit()
    conn.close()
    print(f"Example database created at: {DB_PATH}")


if __name__ == "__main__":
    create_db()
