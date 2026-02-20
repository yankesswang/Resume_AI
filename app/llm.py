import hashlib
import json
import logging
import os
import re

import httpx

from app.models import MatchResultExtract, ResumeExtract

logger = logging.getLogger(__name__)

LM_STUDIO_URL = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1/chat/completions")
# Context budget: reserve tokens for system prompt + response, rest for user content.
# Adjust MODEL_CONTEXT_LENGTH to match your LM Studio model setting.
MODEL_CONTEXT_LENGTH = int(os.getenv("MODEL_CONTEXT_LENGTH", "4096"))
RESPONSE_TOKENS = int(os.getenv("RESPONSE_TOKENS", "2048"))
# Rough ratio: 1 token ≈ 2 characters for CJK-heavy text
CHARS_PER_TOKEN = 2


def _chat(messages: list[dict], temperature: float = 0.1, max_tokens: int = 4096) -> str:
    """Send a chat completion request to LM Studio and return the content."""
    payload = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    resp = httpx.post(LM_STUDIO_URL, json=payload, timeout=300.0)
    if resp.status_code != 200:
        logger.error("LM Studio error %d: %s", resp.status_code, resp.text[:1000])
        resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _truncate_to_fit(system_prompt: str, user_content: str, response_tokens: int = RESPONSE_TOKENS) -> str:
    """Truncate user content so system + user + response fits in context window."""
    system_tokens_est = len(system_prompt) // CHARS_PER_TOKEN + 50  # +50 overhead
    available_for_user = MODEL_CONTEXT_LENGTH - system_tokens_est - response_tokens
    max_user_chars = max(available_for_user * CHARS_PER_TOKEN, 500)

    if len(user_content) > max_user_chars:
        logger.warning(
            "Truncating input from %d to %d chars to fit context window (%d tokens)",
            len(user_content), max_user_chars, MODEL_CONTEXT_LENGTH,
        )
        user_content = user_content[:max_user_chars] + "\n\n[... truncated ...]"
    return user_content


def _strip_fences(text: str) -> str:
    """Strip markdown code fences from LLM response."""
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        text = re.sub(r"^```\w*\n?", "", text)
        # Remove closing fence
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


_EXTRACT_SYSTEM_PROMPT = """\
You are a resume extraction assistant. Extract structured data from a 104.com format resume.
Return ONLY a valid JSON object with these exact keys:

{
  "name": "", "english_name": "", "code_104": "", "birth_year": "", "age": "", "nationality": "",
  "current_status": "", "earliest_start": "", "education_level": "", "school": "",
  "major": "", "military_status": "", "desired_salary": "",
  "desired_job_categories": [], "desired_locations": [], "desired_industry": "",
  "ideal_positions": [], "years_of_experience": "", "linkedin_url": "",
  "photo_path": "", "email": "", "mobile1": "", "mobile2": "",
  "phone_home": "", "phone_work": "", "district": "", "mailing_address": "",
  "work_type": "", "shift_preference": "", "remote_work_preference": "",
  "skills_text": "", "skill_tags": [], "self_introduction": "",
  "work_experiences": [
    {"seq": 1, "company_name": "", "date_start": "", "date_end": "", "duration": "",
     "industry": "", "company_size": "", "job_category": "",
     "management_responsibility": "", "job_title": "", "job_description": "", "job_skills": ""}
  ],
  "education": [
    {"seq": 1, "school": "", "department": "", "degree_level": "",
     "date_start": "", "date_end": "", "region": "", "status": ""}
  ],
  "references": [
    {"ref_name": "", "ref_email": "", "ref_org": "", "ref_title": ""}
  ],
  "attachments": [
    {"attachment_type": "", "seq": 1, "name": "", "description": "", "url": ""}
  ]
}

Rules:
- Use empty string "" for missing text fields, empty array [] for missing lists
- Keep original Traditional Chinese text as-is
- For skill_tags, extract individual skills as separate items
- Return ONLY the JSON object, no markdown fences, no explanation"""


def extract_resume(markdown: str) -> ResumeExtract:
    """Extract structured resume data from markdown using LLM."""
    user_content = _truncate_to_fit(_EXTRACT_SYSTEM_PROMPT, markdown)
    messages = [
        {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    raw = _chat(messages, temperature=0.1, max_tokens=RESPONSE_TOKENS)
    cleaned = _strip_fences(raw)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error("LLM returned invalid JSON: %s", cleaned[:500])
        raise

    return ResumeExtract.model_validate(data)


_MATCH_SYSTEM_PROMPT = """\
You are a recruitment matching assistant. Score the candidate against the job requirement.

Scoring (0-100 each):
- education_score (20%): degree level, major relevance, school prestige
- experience_score (40%): years, role relevance, industry match
- skills_score (40%): technical skills match, tools, certifications
- overall_score = education_score*0.2 + experience_score*0.4 + skills_score*0.4

Return ONLY valid JSON:
{"overall_score": 0, "education_score": 0, "experience_score": 0, "skills_score": 0,
 "analysis_text": "2-3 paragraphs in Traditional Chinese",
 "strengths": ["strength1"], "gaps": ["gap1"]}

No markdown fences, no explanation."""


def match_candidate_to_job(candidate: ResumeExtract, job: dict) -> MatchResultExtract:
    """Score a candidate against a job requirement using LLM."""
    candidate_summary = json.dumps(
        candidate.model_dump(exclude={"references", "attachments"}),
        ensure_ascii=False,
    )
    job_json = json.dumps(job, ensure_ascii=False)

    user_content = f"=== 候選人 ===\n{candidate_summary}\n\n=== 職位需求 ===\n{job_json}"
    user_content = _truncate_to_fit(_MATCH_SYSTEM_PROMPT, user_content)

    messages = [
        {"role": "system", "content": _MATCH_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    raw = _chat(messages, temperature=0.3, max_tokens=RESPONSE_TOKENS)
    cleaned = _strip_fences(raw)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error("LLM returned invalid JSON for match: %s", cleaned[:500])
        raise

    return MatchResultExtract.model_validate(data)


# --- Enhanced LLM functions for the screening funnel ---

# Set to True to include the raw resume text in the LLM prompt.
# Toggling this changes TIER_CLASSIFY_PROMPT_MD5, which auto-invalidates the DB cache.
_INCLUDE_RAW_MARKDOWN = False

_TIER_CLASSIFY_PROMPT = """\
You are an AI recruitment expert. Read the candidate's work experience, skills, and resume excerpt, \
then classify their AI engineering depth into one of 3 tiers based on EVIDENCE DEPTH, not keyword frequency.

Tier 1 – Wrapper (base 60):
  Evidence: Only calls OpenAI/Claude/Gemini APIs. Writes prompts. Builds demos with Streamlit/Gradio/Chainlit. \
No model internals touched.
  Key signal: "Used GPT-4 to build X", "prompt engineering", chatbot demos.

Tier 2 – RAG Architect (base 80):
  Evidence: Designed full RAG/Agent pipelines, chose & tuned vector DBs, implemented hybrid search / \
reranking / HyDE, built multi-step agent loops with LangGraph / LlamaIndex. Understands retrieval quality tradeoffs.
  Key signal: production RAG deployed, evaluation metrics (Recall@K, MRR).

Tier 3 – AI Expert (base 100):
  Evidence: Trained or fine-tuned models (LoRA, QLoRA, SFT, RLHF, DPO), customised training loops, \
loss functions; OR optimised inference (vLLM, TensorRT-LLM, CUDA kernels, Flash Attention, KV-cache tuning); \
OR published ML research at a peer-reviewed venue.
  Key signal: GPU hours, model size, training loss curves, inference latency numbers, paper citations, \
production serving metrics.

Anti-inflation rules (apply before deciding):
  - Listing "PyTorch" in skills with zero training context → max Tier 2
  - "Used HuggingFace to load a model" without fine-tuning → max Tier 2
  - Vague "deep learning project" with no metrics or architecture details → Tier 1 or 2
  - ICASSP / NeurIPS / CVPR / ICLR / ACL paper (even as co-author) → Tier 3 minimum

Return ONLY valid JSON (no markdown fences, no extra text):
{
  "tier": 2,
  "tier_label": "RAG Architect",
  "confidence": 0.85,
  "evidence": ["phrase from resume supporting this tier"],
  "anti_inflation_flags": ["PyTorch listed but no training details found"],
  "reasoning": "1-2 sentences in Traditional Chinese"
}"""


# Prompt version: MD5 of system prompt text + include-raw-markdown flag.
# Changes automatically whenever the prompt or _INCLUDE_RAW_MARKDOWN is edited.
TIER_CLASSIFY_PROMPT_MD5 = hashlib.md5(
    (_TIER_CLASSIFY_PROMPT + str(_INCLUDE_RAW_MARKDOWN)).encode()
).hexdigest()[:12]


def classify_ai_tier(
    work_experiences: list[dict],
    skill_tags: list[str],
    raw_markdown: str = "",
) -> dict:
    """Use LLM to classify candidate into the 3-tier AI pyramid."""
    exp_text = json.dumps(work_experiences, ensure_ascii=False)
    skills_text = ", ".join(skill_tags) if skill_tags else "None"

    user_content = (
        f"=== 工作經驗 ===\n{exp_text}\n\n"
        f"=== 技能標籤 ===\n{skills_text}\n\n"
    )
    if _INCLUDE_RAW_MARKDOWN:
        md_excerpt = (raw_markdown or "")[:3000]
        user_content += f"=== 履歷原文摘錄 (前3000字) ===\n{md_excerpt}"
    user_content = _truncate_to_fit(_TIER_CLASSIFY_PROMPT, user_content)

    messages = [
        {"role": "system", "content": _TIER_CLASSIFY_PROMPT},
        {"role": "user", "content": user_content},
    ]

    raw = _chat(messages, temperature=0.1, max_tokens=512)
    cleaned = _strip_fences(raw)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error("LLM tier classification returned invalid JSON: %s", cleaned[:500])
        return {"tier": 1, "tier_label": "Wrapper", "evidence": [], "reasoning": "分類失敗"}


_SCORECARD_PROMPT = """\
You are an AI recruitment analyst. Generate a detailed scorecard for a candidate based on the scoring data provided.

Output in Traditional Chinese. Return ONLY valid JSON:
{
  "tags": ["#Fine-tuning", "#RAG-Expert"],
  "analysis_text": "2-3 paragraphs analysis in Traditional Chinese. Include: overall assessment, AI depth evaluation, engineering capability, and recommendation.",
  "strengths": ["strength 1 in Traditional Chinese", "strength 2"],
  "gaps": ["gap 1 in Traditional Chinese"],
  "interview_suggestions": ["suggestion 1 in Traditional Chinese"]
}

Be specific and reference actual evidence from the candidate data. No markdown fences."""


def generate_scorecard(
    candidate: dict,
    scores: dict,
    job_data: dict,
) -> dict:
    """Generate the final scorecard using LLM deep reasoning."""
    scoring_summary = json.dumps(scores, ensure_ascii=False)
    candidate_summary = {
        "name": candidate.get("name", ""),
        "education": candidate.get("education", []),
        "work_experiences": candidate.get("work_experiences", []),
        "skill_tags": candidate.get("skill_tags", []),
        "self_introduction": candidate.get("self_introduction", ""),
    }
    candidate_json = json.dumps(candidate_summary, ensure_ascii=False)
    job_json = json.dumps(job_data, ensure_ascii=False)

    user_content = (
        f"=== 評分數據 ===\n{scoring_summary}\n\n"
        f"=== 候選人資料 ===\n{candidate_json}\n\n"
        f"=== 職位需求 ===\n{job_json}"
    )
    user_content = _truncate_to_fit(_SCORECARD_PROMPT, user_content)

    messages = [
        {"role": "system", "content": _SCORECARD_PROMPT},
        {"role": "user", "content": user_content},
    ]

    raw = _chat(messages, temperature=0.3, max_tokens=RESPONSE_TOKENS)
    cleaned = _strip_fences(raw)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error("LLM scorecard returned invalid JSON: %s", cleaned[:500])
        return {
            "tags": [],
            "analysis_text": "評分卡生成失敗",
            "strengths": [],
            "gaps": [],
            "interview_suggestions": [],
        }
