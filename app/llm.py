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
