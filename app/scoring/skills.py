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
    raw_markdown: str = "",
) -> SkillVerification:
    """Classify skill ecosystem and detect suspicious claims.

    v2 optimizations:
    - Expanded evidence search: raw_markdown (self-intro, portfolio, thesis) is
      checked as a weaker evidence source to reduce false positives
    - Two-tier suspicious penalty: unsupported (no evidence anywhere) = -5,
      portfolio-only (not in work history) = -2
    - Keyword stuffing detection: penalise candidates whose job_skills are
      disproportionately long vs. job descriptions (-5 penalty)
    """
    skills_text = " ".join(skill_tags)
    work_text = " ".join(
        (we.get("job_description", "") or "") + " " + (we.get("job_skills", "") or "")
        for we in work_experiences
    )

    # Ecosystem determination: scan skill tags, work descriptions AND the full
    # raw markdown. Work descriptions are often empty in parsed resumes; the raw
    # text contains the real evidence (PyTorch, fine-tuning, etc.).
    corpus = skills_text + " " + work_text + " " + raw_markdown
    llm_match = bool(LLM_STACK.search(corpus))
    dl_match = bool(DEEP_LEARNING.search(corpus))
    ml_match = bool(TRADITIONAL_ML.search(corpus))

    if llm_match:
        ecosystem = "LLM Stack"
    elif dl_match:
        ecosystem = "Deep Learning"
    elif ml_match:
        ecosystem = "Traditional ML"
    else:
        ecosystem = "General"

    # Cross-reference: flag skills claimed in tags but not evidenced in structured
    # work history.  Also check raw_markdown (portfolio, self-introduction, thesis
    # descriptions) as a weaker evidence tier — reduces false positives for
    # candidates who describe technical work outside structured job entries.
    suspicious = []
    penalty = 0.0
    high_value_skills = [
        "PyTorch", "TensorFlow", "CUDA", "vLLM", "Fine-tuning",
        "RAG", "LangChain", "Docker", "Kubernetes", "K8s",
    ]
    for skill in high_value_skills:
        skill_lower = skill.lower()
        claimed = any(skill_lower in tag.lower() for tag in skill_tags)
        evidenced_in_work = skill_lower in work_text.lower()
        evidenced_in_raw = skill_lower in raw_markdown.lower()
        if claimed and not evidenced_in_work and work_text.strip():
            if evidenced_in_raw:
                # Found in portfolio/self-intro: weaker signal, smaller penalty
                suspicious.append(
                    f"Claimed '{skill}' found in portfolio/self-intro but not in work history"
                )
                penalty += 2.0
            else:
                # No supporting evidence anywhere
                suspicious.append(
                    f"Claimed '{skill}' but no evidence in work experience or portfolio"
                )
                penalty += 5.0

    # Keyword stuffing detection: if total words in job_skills far outnumber
    # words in job_description, the candidate may be padding with buzzwords.
    total_skills_words = sum(
        len((we.get("job_skills", "") or "").split()) for we in work_experiences
    )
    total_desc_words = sum(
        len((we.get("job_description", "") or "").split()) for we in work_experiences
    )
    if total_skills_words > total_desc_words * 2 and total_skills_words > 20:
        suspicious.append(
            "Keyword stuffing: job_skills list is disproportionately long vs. descriptions"
        )
        penalty += 5.0

    # Base score from ecosystem alignment
    eco_scores = {"LLM Stack": 90, "Deep Learning": 70, "Traditional ML": 50, "General": 30}
    score = float(eco_scores.get(ecosystem, 30))
    score = max(score - penalty, 10.0)

    return SkillVerification(
        skill_ecosystem=ecosystem,
        suspicious_flags=suspicious,
        score=round(score, 1),
    )
