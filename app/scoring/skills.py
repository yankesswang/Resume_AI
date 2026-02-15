"""Skill verification and ecosystem classification."""

from __future__ import annotations

import re
from typing import Any

from app.models import SkillVerification

# Ecosystem classification patterns
TRADITIONAL_ML = re.compile(
    r"(Sklearn|scikit.?learn|XGBoost|LightGBM|CatBoost|"
    r"Random Forest|SVM|Logistic Regression|Decision Tree|"
    r"Feature Engineering|特徵工程)",
    re.IGNORECASE,
)
DEEP_LEARNING = re.compile(
    r"(PyTorch|TensorFlow|Keras|Jax|CNN|RNN|LSTM|GAN|"
    r"Transformer|Attention|BERT|ResNet|YOLO|"
    r"Neural Network|深度學習|神經網路)",
    re.IGNORECASE,
)
LLM_STACK = re.compile(
    r"(LangChain|LlamaIndex|vLLM|Ollama|OpenAI|Claude|"
    r"LLM|GPT|Llama|Mistral|RAG|Prompt|Fine.?tun|"
    r"LoRA|QLoRA|PEFT|Embedding|Vector|RLHF|DPO|"
    r"大型語言模型|語言模型)",
    re.IGNORECASE,
)


def verify_skills(
    skill_tags: list[str],
    work_experiences: list[dict[str, Any]],
) -> SkillVerification:
    """Classify skill ecosystem and detect suspicious claims."""
    skills_text = " ".join(skill_tags)
    work_text = " ".join(
        (we.get("job_description", "") or "") + " " + (we.get("job_skills", "") or "")
        for we in work_experiences
    )

    # Determine primary ecosystem
    llm_match = bool(LLM_STACK.search(skills_text))
    dl_match = bool(DEEP_LEARNING.search(skills_text))
    ml_match = bool(TRADITIONAL_ML.search(skills_text))

    if llm_match:
        ecosystem = "LLM Stack"
    elif dl_match:
        ecosystem = "Deep Learning"
    elif ml_match:
        ecosystem = "Traditional ML"
    else:
        ecosystem = "General"

    # Cross-reference: flag skills claimed but not evidenced in work
    suspicious = []
    high_value_skills = [
        "PyTorch", "TensorFlow", "CUDA", "vLLM", "Fine-tuning",
        "RAG", "LangChain", "Docker", "Kubernetes", "K8s",
    ]
    for skill in high_value_skills:
        skill_lower = skill.lower()
        claimed = any(skill_lower in tag.lower() for tag in skill_tags)
        evidenced = skill_lower in work_text.lower()
        if claimed and not evidenced and work_text.strip():
            suspicious.append(f"Claimed '{skill}' but no evidence in work experience")

    # Base score from ecosystem alignment
    eco_scores = {"LLM Stack": 90, "Deep Learning": 70, "Traditional ML": 50, "General": 30}
    score = float(eco_scores.get(ecosystem, 30))

    # Penalty for suspicious flags
    penalty = len(suspicious) * 5
    score = max(score - penalty, 10.0)

    return SkillVerification(
        skill_ecosystem=ecosystem,
        suspicious_flags=suspicious,
        score=round(score, 1),
    )
