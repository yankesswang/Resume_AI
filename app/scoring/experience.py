"""3-Tier AI Experience Pyramid classification.

Tier 1 (Wrapper/60):  API callers, prompt engineers
Tier 2 (Architect/80): RAG, Agent, vector DB designers
Tier 3 (Expert/100):  Model training, fine-tuning, inference optimization, CUDA, vLLM
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any

from app.models import ExperienceTierDetail

logger = logging.getLogger(__name__)

# Tier keyword definitions with weights
TIER_KEYWORDS: dict[int, dict[str, float]] = {
    3: {
        # Model training & fine-tuning
        "PyTorch": 1.5, "HuggingFace": 1.5, "Hugging Face": 1.5,
        "LoRA": 1.8, "QLoRA": 1.8, "Fine-tuning": 1.8, "Fine tuning": 1.8,
        "SFT": 1.5, "PEFT": 1.8, "RLHF": 2.0, "DPO": 1.8,
        "Quantization": 1.5, "GGUF": 1.5, "AWQ": 1.5, "GPTQ": 1.5,
        "BitsAndBytes": 1.5, "Llama": 1.2, "Mistral": 1.2,
        "Training": 1.0, "Loss Function": 1.5, "Learning Rate": 1.2,
        "Gradient": 1.2, "Backpropagation": 1.2,
        # Inference optimization (formerly Tier 4)
        "vLLM": 2.5, "TensorRT-LLM": 2.5, "TensorRT": 2.5, "TGI": 2.0,
        "CUDA": 2.5, "Flash Attention": 2.5, "KV Cache": 2.0,
        "Speculative Decoding": 2.0, "GPU Optimization": 2.0,
        "NCCL": 2.0, "DeepSpeed": 2.0, "Megatron": 2.0,
        "Model Parallelism": 2.0, "Tensor Parallelism": 2.0,
        "Triton Inference": 2.0,
    },
    2: {
        "Vector Database": 1.5, "Milvus": 1.5, "Qdrant": 1.5,
        "Pinecone": 1.5, "Chroma": 1.2, "Weaviate": 1.5,
        "RAG": 1.8, "Retrieval Augmented": 1.8,
        "Embedding": 1.2, "Embedding optimization": 1.5,
        "Hybrid Search": 1.5, "Reranking": 1.5, "HyDE": 1.5,
        "Function Calling": 1.5, "ReAct": 1.5, "GraphRAG": 1.8,
        "Agent": 1.2, "LlamaIndex": 1.2, "LangGraph": 1.5,
        "Context Window": 1.2, "Hallucination": 1.2,
    },
    1: {
        "OpenAI API": 1.0, "OpenAI": 0.8, "Claude API": 1.0,
        "Prompt Engineering": 1.0, "Prompt": 0.5,
        "Streamlit": 0.8, "Gradio": 0.8,
        "LangChain": 1.0, "Chatbot": 0.8, "ChatGPT": 0.5,
        "GPT-4": 0.8, "GPT-3": 0.8, "API": 0.3,
    },
}

TIER_LABELS = {
    0: "Non-AI",
    1: "Wrapper",
    2: "RAG Architect",
    3: "AI Expert",
}

# Tier 0 exists so candidates with no AI evidence at all stop sharing a floor
# with genuine API-level practitioners.  Without it every non-AI applicant
# scored 60+, which compressed the whole ranking.
#
# Bases leave room for the bonus band WITHOUT crossing into the next tier.
# Previously base+bonus spanned exactly the tier gap (e.g. tier 2 reached 100),
# so a strong Tier-2 candidate outranked a Tier-3 one and the tiers stopped
# meaning anything.  Each tier now owns a distinct band:
#   tier 0: 25-40 | tier 1: 45-62 | tier 2: 67-84 | tier 3: 88-100
TIER_BASE_SCORES = {0: 25, 1: 45, 2: 67, 3: 88}

# Max bonus points addable on top of a tier base (stack + complexity + metric).
TIER_BONUS_CAP = {0: 15, 1: 17, 2: 17, 3: 12}


def _tier_bases() -> dict[int, float]:
    """Live tier bases from the tunable config (falls back to the constants)."""
    from app.scoring.config import tier_base_scores
    try:
        return tier_base_scores()
    except Exception:
        return TIER_BASE_SCORES


def _tier_caps() -> dict[int, float]:
    from app.scoring.config import tier_bonus_caps
    try:
        return tier_bonus_caps()
    except Exception:
        return TIER_BONUS_CAP


def _bonus_cfg() -> dict:
    from app.scoring.config import load
    return load()["bonuses"]

# Skill tags listed in the CV header get only 40% weight vs. the same keyword
# appearing inside a job description or raw narrative text.  This prevents
# candidates from inflating their stack_bonus by stuffing keywords in the
# skill-tag section without demonstrating them in actual work history.
def _tag_weight_factor() -> float:
    from app.scoring.config import load
    return load()["tag_weight_factor"]


# Kept as a module constant for callers/tests that import it directly; the
# scoring paths read the live value via _tag_weight_factor().
TAG_WEIGHT_FACTOR = 0.4

# Complexity indicators
DATA_SCALE_PATTERN = re.compile(
    r"(百萬|million|billion|十萬|hundred thousand|大規模|large.?scale|"
    r"\d+[MBT]\b|\d+萬|\d+億)",
    re.IGNORECASE,
)
SYSTEM_ARCH_PATTERN = re.compile(
    r"(微服務|microservice|分散式|distributed|K8s|Kubernetes|"
    r"cluster|叢集|pipeline|管線|production|生產環境|"
    r"real.?time|即時|線上服務|online serving|inference serving|部署|deploy)",
    re.IGNORECASE,
)
MODEL_SCALE_PATTERN = re.compile(
    r"(7[0B]B|13B|70B|175B|65B|34B|大型模型|large model|"
    r"multi.?GPU|多GPU|A100|H100|V100)",
    re.IGNORECASE,
)

# Quantified metric patterns (防吹牛)
VALID_METRIC_PATTERN = re.compile(
    r"(reduce[d]?\s+.*?\d+%|improve[d]?\s+.*?\d+%|"
    r"降低.*?\d+%|提升.*?\d+%|優化.*?\d+%|加速.*?\d+%|縮短.*?\d+%|"
    r"latency.*?\d+|throughput.*?\d+|QPS.*?\d+|TPS.*?\d+|RPS.*?\d+|"
    r"Recall@|Precision@|F1|BLEU|ROUGE|CER|WER|MOS|PESQ|SDR|SiSDR|EER|"
    r"accuracy.*?\d+%|準確率.*?\d+%|精確率.*?\d+%|召回率.*?\d+%|"
    r"\d+ms\s*->\s*\d+ms|\d+%\s*→|\d+x\s+faster|\d+倍.*?速|"
    r"VRAM|GPU\s*memory|顯存.*?\d+|記憶體.*?\d+)",
    re.IGNORECASE,
)


# High-specificity signals used only by the LLM keyword floor.  Deliberately
# narrower than TIER_KEYWORDS: these are terms that are hard to mention without
# hands-on work.  Generic entries (PyTorch, Training, Llama, API) are excluded
# because they match coursework and skill lists — see _strong_signal_floor.
_STRONG_TIER3_SIGNALS = [
    re.compile(p, re.IGNORECASE) for p in (
        r"vLLM", r"TensorRT[- ]?LLM", r"\bTensorRT\b", r"QLoRA", r"\bLoRA\b",
        r"RLHF", r"\bDPO\b", r"\bPEFT\b", r"DeepSpeed", r"Megatron",
        r"Flash[- ]?Attention", r"KV[- ]?Cache", r"Speculative Decoding",
        r"\bNCCL\b", r"\bCUDA\b", r"Fine[- ]?tun", r"\bSFT\b",
        r"Tensor Parallel", r"Model Parallel",
    )
]
_STRONG_TIER2_SIGNALS = [
    re.compile(p, re.IGNORECASE) for p in (
        r"\bRAG\b", r"Retrieval[- ]?Augmented", r"Milvus", r"Qdrant",
        r"Pinecone", r"Weaviate", r"LangGraph", r"LlamaIndex", r"GraphRAG",
        r"HyDE", r"Rerank", r"Hybrid Search", r"向量資料庫",
    )
]

# Minimum number of DISTINCT strong signals required to raise a tier.
_FLOOR_MIN_SIGNALS = 2


def _strong_signal_floor(evidence_text: str, tag_text: str) -> int:
    """Lowest tier justified by unambiguous keyword evidence.

    Evidence text (job descriptions, resume narrative) counts fully; skill tags
    alone are not enough to raise a tier, since tag stuffing is the main
    inflation vector this pipeline guards against.
    """
    if not evidence_text.strip():
        return 0

    from app.scoring.config import load
    kf = load()["keyword_floor"]
    if not kf.get("enabled", True):
        return 0
    min_signals = int(kf.get("min_signals", _FLOOR_MIN_SIGNALS))

    t3 = sum(1 for p in _STRONG_TIER3_SIGNALS if p.search(evidence_text))
    if t3 >= min_signals:
        return 3

    t2 = sum(1 for p in _STRONG_TIER2_SIGNALS if p.search(evidence_text))
    if t2 >= min_signals:
        return 2

    return 0


def _find_keywords(text: str, keyword_map: dict[str, float]) -> list[tuple[str, float]]:
    """Find matching keywords in text, return list of (keyword, weight)."""
    found = []
    text_lower = text.lower()
    for kw, weight in keyword_map.items():
        if kw.lower() in text_lower:
            found.append((kw, weight))
    return found


def classify_experience_tier(
    work_experiences: list[dict[str, Any]],
    skill_tags: list[str],
    raw_markdown: str = "",
) -> ExperienceTierDetail:
    """Classify candidate into 3-tier AI pyramid using keyword detection.

    v2: position-based stack weighting.  Keywords found only in the skill-tag
    header count at TAG_WEIGHT_FACTOR (0.4×) vs. full weight when found inside
    job descriptions, job skills, or the raw resume narrative.  Tier thresholds
    still use the full combined corpus so tier assignment is not degraded.

    Returns the highest tier matched with evidence and sub-scores.
    """
    # Build separate corpora: structured evidence vs. skill-tag header
    evidence_parts = []
    for we in work_experiences:
        evidence_parts.append(we.get("job_description", "") or "")
        evidence_parts.append(we.get("job_title", "") or "")
        evidence_parts.append(we.get("job_skills", "") or "")
    if raw_markdown:
        evidence_parts.append(raw_markdown)
    evidence_text = " ".join(evidence_parts)
    tag_text = " ".join(skill_tags)
    combined_text = evidence_text + " " + tag_text  # for tier threshold check

    if not combined_text.strip():
        return ExperienceTierDetail(
            tier=0, tier_label=TIER_LABELS[0], score=float(_tier_bases()[0]),
        )

    # --- Tier threshold determination (uses full combined_text, unweighted) ---
    TIER3_MIN_WEIGHT = 3.0
    TIER2_MIN_WEIGHT = 2.0
    tier_threshold_weight: dict[int, float] = {1: 0.0, 2: 0.0, 3: 0.0}
    for tier in [3, 2, 1]:
        for _kw, w in _find_keywords(combined_text, TIER_KEYWORDS[tier]):
            tier_threshold_weight[tier] += w

    if tier_threshold_weight[3] >= TIER3_MIN_WEIGHT:
        best_tier = 3
    elif tier_threshold_weight[3] > 0 or tier_threshold_weight[2] >= TIER2_MIN_WEIGHT:
        best_tier = 2
    elif tier_threshold_weight[2] > 0:
        best_tier = 2
    elif tier_threshold_weight[1] > 0:
        best_tier = 1
    else:
        # No AI keyword anywhere — a general software / non-technical resume.
        best_tier = 0

    # --- Position-weighted stack score (feeds stack_bonus only) ---
    # Keywords in evidence_text → full weight; tag-only → TAG_WEIGHT_FACTOR weight
    all_evidence = []
    total_stack_score = 0.0
    for tier in [3, 2, 1]:
        kw_map = TIER_KEYWORDS[tier]
        evidence_hits = {kw for kw, _ in _find_keywords(evidence_text, kw_map)}
        tag_hits = {kw for kw, _ in _find_keywords(tag_text, kw_map)}
        for kw in evidence_hits | tag_hits:
            weight = kw_map[kw]
            if kw in evidence_hits:
                total_stack_score += weight
                all_evidence.append(f"[Tier {tier}] {kw}")
            else:
                # Tag-only: reduced weight to prevent gaming
                total_stack_score += weight * _tag_weight_factor()
                all_evidence.append(f"[Tier {tier}] {kw} (tag)")

    # Complexity score (0-1)
    complexity = 0.0
    if DATA_SCALE_PATTERN.search(combined_text):
        complexity += 0.33
    if SYSTEM_ARCH_PATTERN.search(combined_text):
        complexity += 0.33
    if MODEL_SCALE_PATTERN.search(combined_text):
        complexity += 0.34

    # Metric score (防吹牛) (0-1)
    metric_matches = VALID_METRIC_PATTERN.findall(combined_text)
    metric_score = min(len(metric_matches) * 0.25, 1.0)

    # Calculate final score. The bonus total is capped per tier so a strong
    # candidate never leaks into the band above their tier.
    bc = _bonus_cfg()
    base_score = _tier_bases()[best_tier]
    stack_bonus = min(total_stack_score * bc["stack_multiplier"], bc["stack_max"])
    complexity_bonus = complexity * bc["complexity_max"]
    metric_bonus = metric_score * bc["metric_max"]
    bonus = min(
        stack_bonus + complexity_bonus + metric_bonus,
        _tier_caps()[best_tier],
    )
    final_score = min(base_score + bonus, 100.0)

    return ExperienceTierDetail(
        tier=best_tier,
        tier_label=TIER_LABELS[best_tier],
        evidence=all_evidence[:15],  # Cap to avoid bloat
        tech_stack_score=round(total_stack_score, 2),
        complexity_score=round(complexity, 2),
        metric_score=round(metric_score, 2),
        score=round(final_score, 1),
    )


def classify_experience_tier_llm(
    work_experiences: list[dict[str, Any]],
    skill_tags: list[str],
    raw_markdown: str,
    candidate_id: int | None,
    db_conn: sqlite3.Connection | None,
) -> ExperienceTierDetail:
    """LLM-only tier classification with DB cache.

    The LLM decides the tier. Keyword sub-scores (complexity, metric, tech_stack)
    are still computed and added as bonus points on top of the LLM base score.
    Falls back to keyword-only classify_experience_tier() if LLM is unavailable.
    """
    from app.llm import classify_ai_tier
    from app.database import get_cached_llm_tier, store_llm_tier_cache

    # Skip LLM if no candidate_id / no db_conn
    if candidate_id is None or db_conn is None:
        return classify_experience_tier(work_experiences, skill_tags, raw_markdown)

    llm_tier: int | None = None
    confidence: float = 1.0

    # 1. Check DB cache
    try:
        cached = get_cached_llm_tier(db_conn, candidate_id, raw_markdown)
        if cached:
            llm_tier = int(cached["tier"])
    except Exception:
        logger.warning("Failed to read LLM tier cache for candidate %s", candidate_id)

    # 2. Call LLM if no valid cache
    if llm_tier is None:
        try:
            result = classify_ai_tier(work_experiences, skill_tags, raw_markdown)
            llm_tier = max(0, min(int(result.get("tier", 0)), 3))
            try:
                confidence = float(result.get("confidence", 1.0))
            except (TypeError, ValueError):
                confidence = 1.0
            store_llm_tier_cache(db_conn, candidate_id, raw_markdown, {
                "tier": llm_tier,
                "reasoning": result.get("reasoning", ""),
            })
        except Exception as e:
            logger.warning("LLM tier classification failed for candidate %s: %s", candidate_id, e)
            return classify_experience_tier(work_experiences, skill_tags, raw_markdown)

    # 3. Compute keyword sub-scores for bonus points (complexity, metrics, tech stack)
    #    These don't affect the tier decision — only the numeric score within the tier.
    #    v2: position-based weighting — tag-only keywords count at TAG_WEIGHT_FACTOR.
    evidence_parts = []
    for we in work_experiences:
        evidence_parts.append(we.get("job_description", "") or "")
        evidence_parts.append(we.get("job_title", "") or "")
        evidence_parts.append(we.get("job_skills", "") or "")
    if raw_markdown:
        evidence_parts.append(raw_markdown)
    evidence_text = " ".join(evidence_parts)
    tag_text = " ".join(skill_tags)
    combined_text = evidence_text + " " + tag_text

    all_evidence = []
    total_stack_score = 0.0
    for tier in [3, 2, 1]:
        kw_map = TIER_KEYWORDS[tier]
        evidence_hits = {kw for kw, _ in _find_keywords(evidence_text, kw_map)}
        tag_hits = {kw for kw, _ in _find_keywords(tag_text, kw_map)}
        for kw in evidence_hits | tag_hits:
            weight = kw_map[kw]
            if kw in evidence_hits:
                total_stack_score += weight
                all_evidence.append(f"[Tier {tier}] {kw}")
            else:
                total_stack_score += weight * _tag_weight_factor()
                all_evidence.append(f"[Tier {tier}] {kw} (tag)")

    complexity = 0.0
    if DATA_SCALE_PATTERN.search(combined_text):
        complexity += 0.33
    if SYSTEM_ARCH_PATTERN.search(combined_text):
        complexity += 0.33
    if MODEL_SCALE_PATTERN.search(combined_text):
        complexity += 0.34

    metric_score = min(len(VALID_METRIC_PATTERN.findall(combined_text)) * 0.25, 1.0)

    # 3b. Keyword floor: the LLM occasionally misses strong signals in long or
    #     badly-formatted resumes.  The floor only ever raises a tier, never
    #     lowers it, so the LLM stays authoritative for inflation control.
    #
    #     Calibrated on the full 3179-resume corpus: a SINGLE tier-3 keyword is
    #     far too permissive (71% of resumes mention PyTorch/Training, 20% match
    #     one strong term — usually in a course or skill list).  Requiring two
    #     DISTINCT high-specificity signals lands at ~7.7%, which matches the
    #     realistic share of model-level engineers in this pool.
    keyword_floor = _strong_signal_floor(evidence_text, tag_text)

    effective_tier = max(llm_tier, keyword_floor)
    tier_source = "llm" if effective_tier == llm_tier else "llm+keyword-floor"

    # 4. Final score: tier base + keyword bonuses, capped inside the tier band.
    bc = _bonus_cfg()
    base = _tier_bases()[effective_tier]
    bonus = min(
        min(total_stack_score * bc["stack_multiplier"], bc["stack_max"])
        + complexity * bc["complexity_max"]
        + metric_score * bc["metric_max"],
        _tier_caps()[effective_tier],
    )
    final_score = min(base + bonus, 100.0)
    return ExperienceTierDetail(
        tier=effective_tier,
        tier_label=TIER_LABELS[effective_tier],
        confidence=round(confidence, 2),
        tier_source=tier_source,
        evidence=all_evidence[:15],
        tech_stack_score=round(total_stack_score, 2),
        complexity_score=round(complexity, 2),
        metric_score=round(metric_score, 2),
        score=round(final_score, 1),
    )
