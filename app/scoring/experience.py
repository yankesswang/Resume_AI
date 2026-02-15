"""4-Tier AI Experience Pyramid classification.

Tier 1 (Wrapper/60): API callers, prompt engineers
Tier 2 (Architect/80): RAG, Agent, vector DB designers
Tier 3 (Tuner/90): Model fine-tuning, PyTorch, HuggingFace
Tier 4 (Ops/100): Inference optimization, CUDA, vLLM
"""

from __future__ import annotations

import re
from typing import Any

from app.models import ExperienceTierDetail

# Tier keyword definitions with weights
TIER_KEYWORDS: dict[int, dict[str, float]] = {
    4: {
        "vLLM": 2.5, "TensorRT-LLM": 2.5, "TensorRT": 2.5, "TGI": 2.0,
        "CUDA": 2.5, "Flash Attention": 2.5, "KV Cache": 2.0,
        "Speculative Decoding": 2.0, "GPU Optimization": 2.0,
        "NCCL": 2.0, "DeepSpeed": 2.0, "Megatron": 2.0,
        "Model Parallelism": 2.0, "Tensor Parallelism": 2.0,
        "Triton Inference": 2.0,
    },
    3: {
        "PyTorch": 1.5, "HuggingFace": 1.5, "Hugging Face": 1.5,
        "LoRA": 1.8, "QLoRA": 1.8, "Fine-tuning": 1.8, "Fine tuning": 1.8,
        "SFT": 1.5, "PEFT": 1.8, "RLHF": 2.0, "DPO": 1.8,
        "Quantization": 1.5, "GGUF": 1.5, "AWQ": 1.5, "GPTQ": 1.5,
        "BitsAndBytes": 1.5, "Llama": 1.2, "Mistral": 1.2,
        "Training": 1.0, "Loss Function": 1.5, "Learning Rate": 1.2,
        "Gradient": 1.2, "Backpropagation": 1.2,
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
    1: "Wrapper",
    2: "RAG Architect",
    3: "Model Tuner",
    4: "Inference Ops",
}

TIER_BASE_SCORES = {1: 60, 2: 80, 3: 90, 4: 100}

# Complexity indicators
DATA_SCALE_PATTERN = re.compile(
    r"(百萬|million|billion|十萬|hundred thousand|大規模|large.?scale|"
    r"\d+[MBT]\b|\d+萬|\d+億)",
    re.IGNORECASE,
)
SYSTEM_ARCH_PATTERN = re.compile(
    r"(微服務|microservice|分散式|distributed|K8s|Kubernetes|"
    r"cluster|叢集|pipeline|管線|production|生產環境)",
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
    r"降低.*?\d+%|提升.*?\d+%|優化.*?\d+%|"
    r"latency.*?\d+|throughput.*?\d+|"
    r"Recall@|F1|BLEU|ROUGE|accuracy.*?\d+%|"
    r"\d+ms\s*->\s*\d+ms|\d+%\s*→|\d+x\s+faster|"
    r"VRAM|GPU\s*memory|記憶體)",
    re.IGNORECASE,
)


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
    """Classify candidate into 4-tier AI pyramid using keyword detection.

    Returns the highest tier matched with evidence and sub-scores.
    """
    # Combine all text for matching
    all_text_parts = []
    for we in work_experiences:
        all_text_parts.append(we.get("job_description", "") or "")
        all_text_parts.append(we.get("job_title", "") or "")
        all_text_parts.append(we.get("job_skills", "") or "")
    all_text_parts.extend(skill_tags)
    if raw_markdown:
        all_text_parts.append(raw_markdown)
    combined_text = " ".join(all_text_parts)

    if not combined_text.strip():
        return ExperienceTierDetail(
            tier=1, tier_label="Wrapper", score=60.0,
        )

    # Find the highest tier with matches
    best_tier = 1
    all_evidence = []
    total_stack_score = 0.0

    for tier in [4, 3, 2, 1]:
        matches = _find_keywords(combined_text, TIER_KEYWORDS[tier])
        if matches:
            if tier > best_tier:
                best_tier = tier
            for kw, weight in matches:
                all_evidence.append(f"[Tier {tier}] {kw}")
                total_stack_score += weight

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

    # Calculate final score
    base_score = TIER_BASE_SCORES[best_tier]
    # Adjust based on stack coverage and metrics
    stack_bonus = min(total_stack_score * 2, 10.0)  # up to +10
    complexity_bonus = complexity * 5  # up to +5
    metric_bonus = metric_score * 5  # up to +5
    final_score = min(base_score + stack_bonus + complexity_bonus + metric_bonus, 100.0)

    return ExperienceTierDetail(
        tier=best_tier,
        tier_label=TIER_LABELS[best_tier],
        evidence=all_evidence[:15],  # Cap to avoid bloat
        tech_stack_score=round(total_stack_score, 2),
        complexity_score=round(complexity, 2),
        metric_score=round(metric_score, 2),
        score=round(final_score, 1),
    )
