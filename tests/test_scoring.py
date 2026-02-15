"""Tests for the Smart LLM Engineer Screening Funnel scoring engine.

Run: python3 tests/test_scoring.py
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import (
    EducationExtract,
    EducationScoreDetail,
    EngineeringMaturityDetail,
    EnhancedMatchResult,
    ExperienceTierDetail,
    SkillVerification,
)
from app.scoring.education import score_education
from app.scoring.engineering import score_engineering_maturity
from app.scoring.experience import classify_experience_tier
from app.scoring.hard_filter import apply_hard_filters
from app.scoring.pipeline import run_full_scoring
from app.scoring.skills import verify_skills

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


# ---------------------------------------------------------------------------
# 1. Education Scoring
# ---------------------------------------------------------------------------
def test_education():
    print("\n=== Education Scoring ===")

    # Top school + top major + masters
    edu = [EducationExtract(school="台灣大學", department="資訊工程", degree_level="碩士")]
    r = score_education(edu)
    check("NTU CS Masters -> tier A", r.school_tier == "A")
    check("NTU CS Masters -> degree Masters", r.degree_level == "Masters")
    check("NTU CS Masters -> major Tier1", r.major_relevance == "Tier1")
    check("NTU CS Masters -> score >= 80", r.score >= 80, f"got {r.score}")

    # US top school
    edu2 = [EducationExtract(school="Stanford University", department="Computer Science", degree_level="PhD")]
    r2 = score_education(edu2)
    check("Stanford CS PhD -> tier A", r2.school_tier == "A")
    check("Stanford CS PhD -> degree PhD", r2.degree_level == "PhD")
    check("Stanford CS PhD -> score >= 90", r2.score >= 90, f"got {r2.score}")

    # Mid-tier school + non-CS major
    edu3 = [EducationExtract(school="中央大學", department="企業管理", degree_level="學士")]
    r3 = score_education(edu3)
    check("NCU Business Bachelors -> tier B", r3.school_tier == "B")
    check("NCU Business Bachelors -> major Other", r3.major_relevance == "Other")
    check("NCU Business Bachelors -> score < 50", r3.score < 50, f"got {r3.score}")

    # Unknown school
    edu4 = [EducationExtract(school="某私立大學", department="外文系", degree_level="學士")]
    r4 = score_education(edu4)
    check("Unknown school -> tier C", r4.school_tier == "C")
    check("Unknown school -> score < 30", r4.score < 30, f"got {r4.score}")

    # Empty education
    r5 = score_education([])
    check("Empty education -> score 0", r5.score == 0.0)

    # Multiple education records -> best is picked
    edu6 = [
        EducationExtract(school="某私立大學", department="外文系", degree_level="學士"),
        EducationExtract(school="Stanford", department="CS", degree_level="Masters"),
    ]
    r6 = score_education(edu6)
    check("Multiple edu -> picks best (Stanford)", r6.school_tier == "A")

    # Math/Stats major -> Tier2
    edu7 = [EducationExtract(school="台灣大學", department="數學系", degree_level="碩士")]
    r7 = score_education(edu7)
    check("NTU Math Masters -> major Tier2", r7.major_relevance == "Tier2")


# ---------------------------------------------------------------------------
# 2. Experience Tier Classification
# ---------------------------------------------------------------------------
def test_experience():
    print("\n=== Experience Tier Classification ===")

    # Tier 4: Inference Ops
    work_t4 = [{"job_description": "Optimized inference latency using vLLM and TensorRT-LLM with CUDA kernels. Implemented Flash Attention and KV Cache optimization for high-throughput serving.", "job_title": "MLOps Engineer", "job_skills": "CUDA, vLLM"}]
    r4 = classify_experience_tier(work_t4, ["Python", "CUDA", "vLLM"])
    check("Tier 4 detection (vLLM/CUDA)", r4.tier == 4, f"got tier {r4.tier}")
    check("Tier 4 label", r4.tier_label == "Inference Ops")
    check("Tier 4 score >= 90", r4.score >= 90, f"got {r4.score}")

    # Tier 3: Model Tuner
    work_t3 = [{"job_description": "Fine-tuned Llama 3 using LoRA/QLoRA with PyTorch. Managed HuggingFace model hub deployments and implemented quantization for edge devices.", "job_title": "ML Engineer", "job_skills": "PyTorch, HuggingFace"}]
    r3 = classify_experience_tier(work_t3, ["PyTorch", "HuggingFace", "Fine-tuning"])
    check("Tier 3 detection (Fine-tuning/PyTorch)", r3.tier == 3, f"got tier {r3.tier}")
    check("Tier 3 label", r3.tier_label == "Model Tuner")

    # Tier 2: RAG Architect
    work_t2 = [{"job_description": "Built RAG pipeline with Milvus vector database. Implemented hybrid search with reranking and designed multi-agent system using Function Calling.", "job_title": "AI Engineer", "job_skills": "LangChain, Milvus"}]
    r2 = classify_experience_tier(work_t2, ["LangChain", "RAG", "Milvus"])
    check("Tier 2 detection (RAG/VectorDB)", r2.tier == 2, f"got tier {r2.tier}")
    check("Tier 2 label", r2.tier_label == "RAG Architect")

    # Tier 1: Wrapper
    work_t1 = [{"job_description": "Built a chatbot using OpenAI API with Streamlit UI. Created prompt templates for customer service automation.", "job_title": "Junior Developer", "job_skills": "Python"}]
    r1 = classify_experience_tier(work_t1, ["Python", "OpenAI API", "Streamlit"])
    check("Tier 1 detection (Wrapper)", r1.tier == 1, f"got tier {r1.tier}")
    check("Tier 1 label", r1.tier_label == "Wrapper")
    check("Tier 1 score around 60", 55 <= r1.score <= 75, f"got {r1.score}")

    # Empty experience
    r0 = classify_experience_tier([], [])
    check("Empty experience -> tier 1", r0.tier == 1)

    # Complexity detection
    work_complex = [{"job_description": "Deployed distributed microservice on Kubernetes handling millions of requests. Trained 70B model on multi-GPU A100 cluster.", "job_title": "Senior Engineer", "job_skills": "K8s"}]
    rc = classify_experience_tier(work_complex, [])
    check("Complexity detection (K8s/70B/A100)", rc.complexity_score > 0.5, f"got {rc.complexity_score}")

    # Metric detection (防吹牛)
    work_metric = [{"job_description": "Reduced inference latency by 40% (500ms -> 300ms). Improved RAG retrieval Recall@10 by 15%.", "job_title": "AI Engineer", "job_skills": ""}]
    rm = classify_experience_tier(work_metric, [])
    check("Metric detection (防吹牛)", rm.metric_score > 0, f"got {rm.metric_score}")


# ---------------------------------------------------------------------------
# 3. Engineering Maturity
# ---------------------------------------------------------------------------
def test_engineering():
    print("\n=== Engineering Maturity ===")

    # Full-stack AI engineer
    work = [{"job_description": "Built FastAPI microservice with Docker, deployed on Kubernetes. Used PostgreSQL and pgvector for data. Frontend in React with TypeScript.", "job_title": "Full Stack", "job_skills": "Docker, K8s, React"}]
    r = score_engineering_maturity(work, ["Docker", "FastAPI", "PostgreSQL", "pgvector", "React", "TypeScript"])
    check("Backend L3 (K8s)", r.backend_level == 3, f"got {r.backend_level}")
    check("Database L3 (pgvector)", r.database_level == 3, f"got {r.database_level}")
    check("Frontend L3 (React)", r.frontend_level == 3, f"got {r.frontend_level}")
    check("M_Eng = 0.5 (maxed)", r.m_eng == 0.5, f"got {r.m_eng}")

    # Pure Jupyter user
    work2 = [{"job_description": "Analyzed data in Jupyter notebooks using pandas.", "job_title": "Data Analyst", "job_skills": "Python"}]
    r2 = score_engineering_maturity(work2, ["Python", "Pandas"])
    check("Jupyter-only -> backend 0", r2.backend_level == 0, f"got {r2.backend_level}")
    check("Jupyter-only -> M_Eng low", r2.m_eng <= 0.05, f"got {r2.m_eng}")

    # Basic API developer
    work3 = [{"job_description": "Built REST API with Flask. Used MySQL for data storage.", "job_title": "Backend Dev", "job_skills": "Flask, MySQL"}]
    r3 = score_engineering_maturity(work3, ["Flask", "MySQL"])
    check("Flask/MySQL -> backend L1", r3.backend_level == 1, f"got {r3.backend_level}")
    check("Flask/MySQL -> database L1", r3.database_level == 1, f"got {r3.database_level}")

    # Docker/Async developer
    work4 = [{"job_description": "Built async FastAPI service with Docker and Nginx reverse proxy.", "job_title": "Backend Dev", "job_skills": "Docker, FastAPI"}]
    r4 = score_engineering_maturity(work4, ["Docker", "FastAPI"])
    check("Docker/Async -> backend L2", r4.backend_level == 2, f"got {r4.backend_level}")


# ---------------------------------------------------------------------------
# 4. Skill Verification
# ---------------------------------------------------------------------------
def test_skills():
    print("\n=== Skill Verification ===")

    # LLM Stack ecosystem
    r = verify_skills(
        ["Python", "LangChain", "RAG", "OpenAI", "PyTorch"],
        [{"job_description": "Built LLM-based RAG system using LangChain and PyTorch.", "job_skills": "LangChain, PyTorch"}],
    )
    check("LLM Stack ecosystem", r.skill_ecosystem == "LLM Stack")
    check("No suspicious flags (skills match work)", len(r.suspicious_flags) == 0, f"got {r.suspicious_flags}")

    # Suspicious: claims Docker but no evidence
    r2 = verify_skills(
        ["Python", "Docker", "Kubernetes"],
        [{"job_description": "Wrote Python scripts for data analysis.", "job_skills": "Python"}],
    )
    check("Suspicious Docker flag", any("Docker" in f for f in r2.suspicious_flags), f"got {r2.suspicious_flags}")
    check("Suspicious K8s flag", any("Kubernetes" in f or "K8s" in f for f in r2.suspicious_flags), f"got {r2.suspicious_flags}")
    check("Penalty applied", r2.score < 90, f"got {r2.score}")

    # Traditional ML
    r3 = verify_skills(
        ["Python", "scikit-learn", "XGBoost"],
        [{"job_description": "Built ML models with sklearn.", "job_skills": "sklearn"}],
    )
    check("Traditional ML ecosystem", r3.skill_ecosystem == "Traditional ML")

    # Empty work -> no suspicious flags (can't verify)
    r4 = verify_skills(["Python", "PyTorch", "CUDA"], [])
    check("Empty work -> no suspicious (no evidence to check)", len(r4.suspicious_flags) == 0)


# ---------------------------------------------------------------------------
# 5. Hard Filters
# ---------------------------------------------------------------------------
def test_hard_filter():
    print("\n=== Hard Filters ===")

    config = {
        "required_skills": ["Python"],
        "required_frameworks": ["PyTorch", "TensorFlow"],
        "required_keywords": ["Transformer", "LLM", "BERT"],
    }

    # Passes all filters
    passed, failures = apply_hard_filters(
        ["Python", "PyTorch"],
        [{"job_description": "Built LLM solutions", "job_title": "", "job_skills": ""}],
        "Experience with Transformer and LLM",
        config,
    )
    check("All filters pass", passed)
    check("No failures", len(failures) == 0, f"got {failures}")

    # Missing Python
    passed2, failures2 = apply_hard_filters(
        ["Java", "TensorFlow"],
        [{"job_description": "Built BERT models", "job_title": "", "job_skills": ""}],
        "BERT fine-tuning",
        config,
    )
    check("Missing Python -> fail", not passed2)
    check("Failure mentions Python", any("Python" in f for f in failures2), f"got {failures2}")

    # Missing framework
    passed3, failures3 = apply_hard_filters(
        ["Python"],
        [{"job_description": "Built LLM solutions", "job_title": "", "job_skills": ""}],
        "LLM chatbot",
        config,
    )
    check("Missing framework -> fail", not passed3)
    check("Failure mentions framework", any("framework" in f.lower() for f in failures3))

    # Missing keywords
    passed4, failures4 = apply_hard_filters(
        ["Python", "PyTorch"],
        [{"job_description": "Built web application", "job_title": "", "job_skills": ""}],
        "Web development",
        config,
    )
    check("Missing keywords -> fail", not passed4)
    check("Failure mentions keyword", any("keyword" in f.lower() for f in failures4))

    # Empty config -> all pass
    passed5, failures5 = apply_hard_filters([], [], "", {})
    check("Empty config -> pass", passed5)


# ---------------------------------------------------------------------------
# 6. Full Pipeline (without LLM/embedding calls)
# ---------------------------------------------------------------------------
def test_pipeline():
    print("\n=== Full Pipeline ===")

    candidate = {
        "name": "Test Candidate",
        "education": [
            {"school": "台灣大學", "department": "資訊工程", "degree_level": "碩士"},
        ],
        "work_experiences": [
            {
                "job_description": "Built RAG pipeline with Milvus vector database. Fine-tuned Llama 3 with LoRA. Deployed on FastAPI with Docker.",
                "job_title": "AI Engineer",
                "job_skills": "Python, PyTorch, LangChain, RAG, Docker",
            },
        ],
        "skill_tags": ["Python", "PyTorch", "LangChain", "RAG", "Docker", "FastAPI"],
        "raw_markdown": "NLP research with Transformer architecture and BERT fine-tuning",
        "self_introduction": "Passionate AI engineer with experience in LLM systems.",
    }

    job_data = json.loads(Path(__file__).resolve().parent.parent.joinpath("job_requirement.json").read_text())

    result = run_full_scoring(candidate, job_data)

    check("Result is EnhancedMatchResult", isinstance(result, EnhancedMatchResult))
    check("Overall score > 0", result.overall_score > 0, f"got {result.overall_score}")
    check("S_AI > 0", result.s_ai > 0, f"got {result.s_ai}")
    check("S_Total > 0", result.s_total > 0, f"got {result.s_total}")
    check("Passed hard filter", result.passed_hard_filter)
    check("Education score > 0", result.education_score > 0, f"got {result.education_score}")
    check("Experience tier >= 2", result.experience_detail.tier >= 2, f"got tier {result.experience_detail.tier}")
    check("M_Eng > 0 (has Docker/FastAPI)", result.m_eng > 0, f"got {result.m_eng}")
    check("Tags not empty", len(result.tags) > 0, f"got {result.tags}")
    check("Analysis text not empty", len(result.analysis_text) > 0)
    check("Strengths not empty", len(result.strengths) > 0)
    check("Has education detail", result.education_detail.school_tier == "A")
    check("Has engineering detail", result.engineering_detail.backend_level > 0)


# ---------------------------------------------------------------------------
# 7. Pipeline: Hard Filter Failure
# ---------------------------------------------------------------------------
def test_pipeline_hard_filter_fail():
    print("\n=== Pipeline: Hard Filter Failure ===")

    candidate = {
        "name": "Unqualified Candidate",
        "education": [
            {"school": "某學校", "department": "外文系", "degree_level": "學士"},
        ],
        "work_experiences": [
            {
                "job_description": "Managed social media accounts and wrote blog posts.",
                "job_title": "Content Manager",
                "job_skills": "Writing, Social Media",
            },
        ],
        "skill_tags": ["Writing", "Social Media"],
        "raw_markdown": "Content marketing specialist",
    }

    job_data = json.loads(Path(__file__).resolve().parent.parent.joinpath("job_requirement.json").read_text())

    result = run_full_scoring(candidate, job_data)

    check("Hard filter failed", not result.passed_hard_filter)
    check("Low overall score", result.overall_score <= 20, f"got {result.overall_score}")
    check("Has failure reasons", len(result.hard_filter_failures) > 0, f"got {result.hard_filter_failures}")


# ---------------------------------------------------------------------------
# 8. Edge Cases
# ---------------------------------------------------------------------------
def test_edge_cases():
    print("\n=== Edge Cases ===")

    # Candidate with no work experience
    candidate_no_exp = {
        "name": "Fresh Graduate",
        "education": [
            {"school": "清華大學", "department": "資訊工程", "degree_level": "碩士"},
        ],
        "work_experiences": [],
        "skill_tags": ["Python", "PyTorch", "Deep Learning"],
        "raw_markdown": "Thesis on Transformer-based NLP models",
    }
    job_data = json.loads(Path(__file__).resolve().parent.parent.joinpath("job_requirement.json").read_text())
    r = run_full_scoring(candidate_no_exp, job_data)
    check("No work exp -> still produces result", isinstance(r, EnhancedMatchResult))
    check("No work exp -> has education score", r.education_score > 0, f"got {r.education_score}")
    check("No work exp -> tier 1 default", r.experience_detail.tier >= 1)

    # Candidate with empty everything
    candidate_empty = {
        "name": "",
        "education": [],
        "work_experiences": [],
        "skill_tags": [],
        "raw_markdown": "",
    }
    r2 = run_full_scoring(candidate_empty, job_data)
    check("Empty candidate -> does not crash", isinstance(r2, EnhancedMatchResult))

    # Model validation
    from app.models import EducationScoreDetail, EngineeringMaturityDetail
    ed = EducationScoreDetail()
    check("EducationScoreDetail default score=0", ed.score == 0.0)
    eng = EngineeringMaturityDetail()
    check("EngineeringMaturityDetail default m_eng=0", eng.m_eng == 0.0)


# ---------------------------------------------------------------------------
# 9. Database Migration
# ---------------------------------------------------------------------------
def test_database():
    print("\n=== Database Schema ===")
    import sqlite3
    from app.database import DB_PATH, init_db

    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Check match_results has new columns
    cols = {r[1] for r in conn.execute("PRAGMA table_info(match_results)").fetchall()}
    for col in ["s_ai", "m_eng", "s_total", "education_detail", "experience_detail",
                "engineering_detail", "skill_detail", "passed_hard_filter",
                "hard_filter_failures", "semantic_similarity", "tags", "interview_suggestions"]:
        check(f"match_results has column '{col}'", col in cols, f"missing from {cols}")

    # Check candidates has embedding column
    cand_cols = {r[1] for r in conn.execute("PRAGMA table_info(candidates)").fetchall()}
    check("candidates has 'embedding' column", "embedding" in cand_cols)

    conn.close()


# ---------------------------------------------------------------------------
# 10. Model Serialization
# ---------------------------------------------------------------------------
def test_model_serialization():
    print("\n=== Model Serialization ===")

    result = EnhancedMatchResult(
        overall_score=85.0,
        s_ai=80.0,
        m_eng=0.3,
        s_total=104.0,
        education_score=90.0,
        experience_score=80.0,
        skills_score=75.0,
        tags=["#RAG-Expert", "#Full-Stack"],
        strengths=["Strong RAG experience"],
        gaps=["No deployment experience"],
        interview_suggestions=["Ask about Docker/K8s"],
    )

    # Serialize to dict
    d = result.model_dump()
    check("Serializes to dict", isinstance(d, dict))
    check("Dict has s_total", d["s_total"] == 104.0)
    check("Dict has tags", d["tags"] == ["#RAG-Expert", "#Full-Stack"])
    check("Dict has education_detail", "education_detail" in d)
    check("Dict has experience_detail", "experience_detail" in d)

    # Serialize to JSON
    j = result.model_dump_json()
    check("Serializes to JSON string", isinstance(j, str))
    parsed = json.loads(j)
    check("JSON round-trips correctly", parsed["s_total"] == 104.0)


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    tests = [
        test_education,
        test_experience,
        test_engineering,
        test_skills,
        test_hard_filter,
        test_pipeline,
        test_pipeline_hard_filter_fail,
        test_edge_cases,
        test_database,
        test_model_serialization,
    ]

    for test_fn in tests:
        try:
            test_fn()
        except Exception:
            FAIL += 1
            print(f"  CRASH  {test_fn.__name__}")
            traceback.print_exc()

    print(f"\n{'=' * 50}")
    print(f"Results: {PASS} passed, {FAIL} failed")
    print(f"{'=' * 50}")
    sys.exit(1 if FAIL > 0 else 0)
