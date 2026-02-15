"""End-to-end test: loads real candidates from DB, runs the full scoring pipeline
with LM Studio at http://192.168.0.84:1234, and verifies the results.

Run: python3 tests/test_e2e_scoring.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

# Ensure project root is on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Point LLM + embedding endpoints to the remote LM Studio
os.environ["LM_STUDIO_URL"] = "http://192.168.0.84:1234/v1/chat/completions"
os.environ["EMBEDDING_URL"] = "http://192.168.0.84:1234/v1/embeddings"
# Use a bigger context for real resumes
os.environ.setdefault("MODEL_CONTEXT_LENGTH", "8192")
os.environ.setdefault("RESPONSE_TOKENS", "4096")

import httpx
from app.database import get_candidate_detail, get_match_result, init_db, upsert_match_result
from app.models import EnhancedMatchResult
from app.scoring.pipeline import run_full_scoring

JOB_REQ_PATH = ROOT / "job_requirement.json"
LM_STUDIO_BASE = "http://192.168.0.84:1234"

# Candidate IDs to test (diverse profiles)
TEST_CANDIDATES = [1, 4, 20, 30]

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


def verify_lm_studio():
    """Check LM Studio is reachable."""
    print("=== Verifying LM Studio Connectivity ===")
    try:
        resp = httpx.get(f"{LM_STUDIO_BASE}/v1/models", timeout=10.0)
        resp.raise_for_status()
        models = resp.json().get("data", [])
        print(f"  Connected. Models available: {len(models)}")
        for m in models:
            print(f"    - {m['id']}")
        check("LM Studio reachable", True)
        return True
    except Exception as e:
        print(f"  ERROR: Cannot connect to LM Studio at {LM_STUDIO_BASE}: {e}")
        check("LM Studio reachable", False, str(e))
        return False


def test_candidate_scoring(candidate_id: int, job_data: dict):
    """Run full scoring pipeline on a real candidate."""
    detail = get_candidate_detail(candidate_id)
    if not detail:
        print(f"  SKIP  Candidate {candidate_id} not found in DB")
        return None

    name = detail.get("name", "?")
    school = detail.get("school", "?")
    skill_tags = detail.get("skill_tags", [])
    n_work = len(detail.get("work_experiences", []))
    n_edu = len(detail.get("education", []))

    print(f"\n--- Candidate ID={candidate_id}: {name} ---")
    print(f"    School: {school}")
    print(f"    Skills ({len(skill_tags)}): {skill_tags[:8]}")
    print(f"    Work experiences: {n_work}, Education records: {n_edu}")

    start = time.time()
    result = run_full_scoring(detail, job_data)
    elapsed = time.time() - start

    print(f"\n    Scoring completed in {elapsed:.1f}s")
    print(f"    Overall: {result.overall_score}")
    print(f"    S_AI: {result.s_ai}  |  M_Eng: {result.m_eng}  |  S_Total: {result.s_total}")
    print(f"    Education: {result.education_score} (tier={result.education_detail.school_tier}, "
          f"degree={result.education_detail.degree_level}, major={result.education_detail.major_relevance})")
    print(f"    Experience: tier={result.experience_detail.tier} ({result.experience_detail.tier_label}), "
          f"score={result.experience_detail.score}")
    print(f"    Engineering: backend_L{result.engineering_detail.backend_level} "
          f"db_L{result.engineering_detail.database_level} "
          f"fe_L{result.engineering_detail.frontend_level} "
          f"(M_Eng={result.engineering_detail.m_eng})")
    print(f"    Skills: {result.skill_detail.skill_ecosystem} (score={result.skill_detail.score})")
    print(f"    Hard filter: {'PASS' if result.passed_hard_filter else 'FAIL'}")
    if result.hard_filter_failures:
        for f in result.hard_filter_failures:
            print(f"      - {f}")
    print(f"    Semantic similarity: {result.semantic_similarity}")
    print(f"    Tags: {result.tags}")

    if result.strengths:
        print(f"    Strengths:")
        for s in result.strengths[:3]:
            print(f"      + {s}")
    if result.gaps:
        print(f"    Gaps:")
        for g in result.gaps[:3]:
            print(f"      - {g}")
    if result.interview_suggestions:
        print(f"    Interview suggestions:")
        for s in result.interview_suggestions[:3]:
            print(f"      ? {s}")

    # Validate result structure
    prefix = f"[ID={candidate_id}]"
    check(f"{prefix} Is EnhancedMatchResult", isinstance(result, EnhancedMatchResult))
    check(f"{prefix} Overall score in range", 0 <= result.overall_score <= 150, f"got {result.overall_score}")
    check(f"{prefix} S_AI in range", 0 <= result.s_ai <= 120, f"got {result.s_ai}")
    check(f"{prefix} M_Eng in range", 0 <= result.m_eng <= 0.5, f"got {result.m_eng}")
    check(f"{prefix} S_Total >= S_AI", result.s_total >= result.s_ai or result.s_total == 0,
          f"s_total={result.s_total} < s_ai={result.s_ai}")
    check(f"{prefix} Experience tier 1-4", 1 <= result.experience_detail.tier <= 4,
          f"got {result.experience_detail.tier}")
    check(f"{prefix} Tier label not empty", len(result.experience_detail.tier_label) > 0)
    check(f"{prefix} Tags list exists", isinstance(result.tags, list))
    check(f"{prefix} Analysis text present", len(result.analysis_text) > 0)
    check(f"{prefix} Education detail populated", result.education_detail.score >= 0)
    check(f"{prefix} Engineering detail populated", result.engineering_detail.m_eng >= 0)

    return result


def test_db_persistence(candidate_id: int, result: EnhancedMatchResult, job_id: int):
    """Test that the enhanced result can be saved and loaded from the DB."""
    prefix = f"[DB ID={candidate_id}]"

    # Save
    upsert_match_result(candidate_id, job_id, result)
    check(f"{prefix} Upsert succeeded", True)

    # Load
    loaded = get_match_result(candidate_id, job_id)
    check(f"{prefix} Loaded from DB", loaded is not None)
    if loaded:
        check(f"{prefix} Overall score matches",
              abs(loaded["overall_score"] - result.overall_score) < 0.01,
              f"saved={result.overall_score} loaded={loaded['overall_score']}")
        check(f"{prefix} S_AI matches",
              abs(loaded.get("s_ai", 0) - result.s_ai) < 0.01,
              f"saved={result.s_ai} loaded={loaded.get('s_ai')}")
        check(f"{prefix} S_Total matches",
              abs(loaded.get("s_total", 0) - result.s_total) < 0.01,
              f"saved={result.s_total} loaded={loaded.get('s_total')}")
        check(f"{prefix} Experience detail is dict",
              isinstance(loaded.get("experience_detail"), dict))
        check(f"{prefix} Tags is list",
              isinstance(loaded.get("tags"), list))
        check(f"{prefix} Passed hard filter bool",
              isinstance(loaded.get("passed_hard_filter"), bool))


def test_embedding_similarity():
    """Test embedding-based semantic similarity with real LM Studio."""
    print("\n=== Embedding Similarity Test ===")
    try:
        from app.scoring.embeddings import compute_semantic_similarity, get_embedding

        # Test basic embedding generation
        emb = get_embedding("Python PyTorch machine learning engineer")
        check("Embedding returned non-empty", len(emb) > 0, f"got len={len(emb)}")
        if len(emb) > 0:
            check("Embedding has float values", isinstance(emb[0], float))
            print(f"    Embedding dimension: {len(emb)}")

        # Test similarity between related texts
        sim_high = compute_semantic_similarity(
            "Built RAG pipeline with LangChain and vector database for LLM applications",
            "Looking for AI engineer with RAG and LLM experience",
        )
        sim_low = compute_semantic_similarity(
            "Managed social media campaigns and wrote blog articles",
            "Looking for AI engineer with RAG and LLM experience",
        )
        print(f"    High similarity (RAG/LLM): {sim_high}")
        print(f"    Low similarity (unrelated): {sim_low}")
        check("Related text has higher similarity", sim_high > sim_low,
              f"high={sim_high} low={sim_low}")
        check("High similarity > 0", sim_high > 0, f"got {sim_high}")
    except Exception as e:
        print(f"    Embedding test failed: {e}")
        check("Embedding service works", False, str(e))


def test_llm_tier_classification():
    """Test LLM-based tier classification with real LM Studio."""
    print("\n=== LLM Tier Classification Test ===")
    try:
        from app.llm import classify_ai_tier

        # Tier 3+ candidate
        work_exp = [
            {
                "job_title": "ML Engineer",
                "job_description": "Fine-tuned LLM models using LoRA and QLoRA with PyTorch. "
                                   "Deployed models on vLLM for production serving. "
                                   "Optimized inference latency by 40%.",
                "job_skills": "PyTorch, HuggingFace, vLLM, CUDA",
            }
        ]
        result = classify_ai_tier(work_exp, ["PyTorch", "vLLM", "CUDA", "Fine-tuning"])
        print(f"    Tier: {result.get('tier')} ({result.get('tier_label')})")
        print(f"    Evidence: {result.get('evidence', [])[:5]}")
        print(f"    Analysis: {result.get('analysis', '')[:200]}")

        check("LLM tier classification returns dict", isinstance(result, dict))
        check("LLM classified tier >= 3", result.get("tier", 0) >= 3,
              f"got tier {result.get('tier')}")

        # Tier 1 candidate
        work_exp2 = [
            {
                "job_title": "Junior Developer",
                "job_description": "Used ChatGPT API to build a simple chatbot with Streamlit.",
                "job_skills": "Python, Streamlit",
            }
        ]
        result2 = classify_ai_tier(work_exp2, ["Python", "ChatGPT"])
        print(f"    Wrapper tier: {result2.get('tier')} ({result2.get('tier_label')})")
        check("LLM classified wrapper as tier <= 2", result2.get("tier", 5) <= 2,
              f"got tier {result2.get('tier')}")
    except Exception as e:
        print(f"    LLM tier classification failed: {e}")
        traceback.print_exc()
        check("LLM tier classification works", False, str(e))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Resume AI - End-to-End Scoring Test")
    print(f"LM Studio: {LM_STUDIO_BASE}")
    print(f"DB: {ROOT / 'resume_ai.db'}")
    print()

    # Step 0: Verify connectivity
    if not verify_lm_studio():
        print("\nAborting: LM Studio not reachable.")
        sys.exit(1)

    # Init DB (runs migrations)
    init_db()

    # Load job requirement
    job_data = json.loads(JOB_REQ_PATH.read_text(encoding="utf-8"))
    from app.database import ensure_job_requirement
    job_id = ensure_job_requirement(
        job_data.get("basic_conditions", {}).get("job_title", "Test Job"),
        json.dumps(job_data, ensure_ascii=False),
    )

    # Step 1: Test embedding similarity
    test_embedding_similarity()

    # Step 2: Test LLM tier classification
    test_llm_tier_classification()

    # Step 3: Score real candidates
    print("\n=== Full Pipeline on Real Candidates ===")
    results = {}
    for cid in TEST_CANDIDATES:
        try:
            r = test_candidate_scoring(cid, job_data)
            if r:
                results[cid] = r
        except Exception as e:
            FAIL += 1
            print(f"  CRASH scoring candidate {cid}: {e}")
            traceback.print_exc()

    # Step 4: Test DB persistence
    print("\n=== Database Persistence ===")
    for cid, r in results.items():
        try:
            test_db_persistence(cid, r, job_id)
        except Exception as e:
            FAIL += 1
            print(f"  CRASH DB test candidate {cid}: {e}")
            traceback.print_exc()

    # Step 5: Cross-candidate comparison
    print("\n=== Cross-Candidate Comparison ===")
    if len(results) >= 2:
        sorted_candidates = sorted(results.items(), key=lambda x: x[1].s_total, reverse=True)
        print("  Ranking by S_Total:")
        for rank, (cid, r) in enumerate(sorted_candidates, 1):
            detail = get_candidate_detail(cid)
            name = detail.get("name", "?") if detail else "?"
            print(f"    #{rank}  ID={cid} {name}: S_Total={r.s_total} "
                  f"(S_AI={r.s_ai}, M_Eng={r.m_eng}, Tier={r.experience_detail.tier})")
        check("Ranking produces ordered list", True)
    else:
        print("  Not enough candidates to compare")

    # Summary
    print(f"\n{'=' * 60}")
    print(f"Results: {PASS} passed, {FAIL} failed")
    print(f"{'=' * 60}")
    sys.exit(1 if FAIL > 0 else 0)
