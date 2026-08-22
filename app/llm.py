import hashlib
import json
import logging
import os
import re

import httpx

from app.models import MatchResultExtract, ResumeExtract

logger = logging.getLogger(__name__)

# Backwards-compatible module constants. These remain the *environment*
# defaults; the live values now come from app.llm_config, which layers a
# UI-editable document underneath the environment. Anything importing these
# names (scripts, tests) keeps working.
LM_STUDIO_URL = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1/chat/completions")
# Leave empty to use whichever model LM Studio currently has loaded.
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "")
# Context budget: reserve tokens for system prompt + response, rest for user content.
# Adjust from /llm-settings (or MODEL_CONTEXT_LENGTH) to match the served model.
# Default 32768: modern local models (Qwen3.x, Llama 3.x) ship with >=32k context.
# The old 4096 default silently truncated resumes to ~2k chars, which discarded
# most of the evidence the scorer depends on.
MODEL_CONTEXT_LENGTH = int(os.getenv("MODEL_CONTEXT_LENGTH", "32768"))
RESPONSE_TOKENS = int(os.getenv("RESPONSE_TOKENS", "2048"))
# Rough ratio: 1 token ≈ 2 characters for CJK-heavy text
CHARS_PER_TOKEN = 2


def _context_length() -> int:
    """Live context budget, falling back to the module constant.

    Read per call rather than at import: changing the model from the settings
    page must take effect on the next scoring run, not the next restart.
    """
    try:
        from app.llm_config import chat_context_length
        return chat_context_length()
    except Exception:
        return MODEL_CONTEXT_LENGTH


def _response_tokens() -> int:
    try:
        from app.llm_config import chat_response_tokens
        return chat_response_tokens()
    except Exception:
        return RESPONSE_TOKENS


def _chat(messages: list[dict], temperature: float = 0.1, max_tokens: int = 4096) -> str:
    """Send a chat completion request to the configured provider.

    The provider (LM Studio / OpenAI), endpoint, model and credentials are
    resolved per call from app.llm_config, so switching backends from the
    settings page applies to the next request rather than the next restart.
    """
    payload: dict = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    url = LM_STUDIO_URL
    model_name = LM_STUDIO_MODEL
    request_headers: dict[str, str] = {}
    send_thinking = True
    request_timeout = 300.0
    try:
        from app import llm_config

        url = llm_config.endpoint("chat")
        model_name = llm_config.model("chat")
        request_headers = llm_config.headers("chat")
        send_thinking = llm_config.supports_thinking_toggle("chat")
        request_timeout = llm_config.timeout("chat")
    except Exception as e:
        logger.warning("LLM 設定讀取失敗，改用環境變數: %s", e)

    if send_thinking:
        # Disable Qwen3 chain-of-thought. OpenAI 400s on unknown body fields,
        # so this is only sent to OpenAI-compatible local servers.
        payload["thinking"] = {"type": "disabled"}
    if model_name:
        payload["model"] = model_name

    resp = httpx.post(url, json=payload, headers=request_headers, timeout=request_timeout)
    if resp.status_code != 200:
        logger.error("LLM error %d from %s: %s", resp.status_code, url, resp.text[:1000])
        resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _truncate_to_fit(system_prompt: str, user_content: str, response_tokens: int | None = None) -> str:
    """Truncate user content so system + user + response fits in context window."""
    if response_tokens is None:
        response_tokens = _response_tokens()
    context_length = _context_length()
    system_tokens_est = len(system_prompt) // CHARS_PER_TOKEN + 50  # +50 overhead
    available_for_user = context_length - system_tokens_est - response_tokens
    max_user_chars = max(available_for_user * CHARS_PER_TOKEN, 500)

    if len(user_content) > max_user_chars:
        logger.warning(
            "Truncating input from %d to %d chars to fit context window (%d tokens)",
            len(user_content), max_user_chars, context_length,
        )
        # Keep head AND tail: work experience usually sits at the top of a 104
        # resume while skills / self-introduction / projects sit at the bottom.
        # Head-only truncation threw away exactly the tier-3 evidence
        # (fine-tuning, CUDA, publications) the classifier is looking for.
        head = int(max_user_chars * 0.6)
        tail = max_user_chars - head
        user_content = (
            user_content[:head]
            + "\n\n[... 中略 ...]\n\n"
            + user_content[-tail:]
        )
    return user_content


def _job_brief(job: dict) -> str:
    """Compact job description for prompts.

    Dumping the whole requirement JSON spends most of the context budget on
    boilerplate the model must not score on (salary, address, leave policy,
    benefits).  Keep only the fields that describe the work itself.
    """
    keep = {
        k: job[k]
        for k in (
            "job_summary",
            "responsibilities",
            "requirements",
            "preferred_qualifications",
        )
        if job.get(k)
    }
    basic = job.get("basic_conditions", {}) or {}
    if basic.get("job_title"):
        keep["job_title"] = basic["job_title"]
    if basic.get("job_categories"):
        keep["job_categories"] = basic["job_categories"]
    return json.dumps(keep, ensure_ascii=False)


def _strip_fences(text: str) -> str:
    """Strip markdown code fences and Qwen3 <think> blocks from LLM response."""
    text = text.strip()
    # Remove <think>...</think> blocks (Qwen3 chain-of-thought)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
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

    raw = _chat(messages, temperature=0.1, max_tokens=_response_tokens())
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
    job_json = _job_brief(job)

    user_content = f"=== 候選人 ===\n{candidate_summary}\n\n=== 職位需求 ===\n{job_json}"
    user_content = _truncate_to_fit(_MATCH_SYSTEM_PROMPT, user_content)

    messages = [
        {"role": "system", "content": _MATCH_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    raw = _chat(messages, temperature=0.3, max_tokens=_response_tokens())
    cleaned = _strip_fences(raw)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error("LLM returned invalid JSON for match: %s", cleaned[:500])
        raise

    return MatchResultExtract.model_validate(data)


# --- Enhanced LLM functions for the screening funnel ---

# Include the raw resume text in the LLM prompt.
# Toggling this changes TIER_CLASSIFY_PROMPT_MD5, which auto-invalidates the DB cache.
#
# This MUST stay True.  ~52% of parsed candidates have zero work_experience rows
# and ~42% have empty skill_tags, so with raw markdown disabled the classifier
# received literally "工作經驗 [] / 技能標籤 None" and answered "no evidence → Tier 1"
# for 98% of the pool.  The resume text is the only reliable evidence source.
_INCLUDE_RAW_MARKDOWN = True

# How much resume text to feed the tier classifier.
# 12000 chars covers a typical full 104 resume; _truncate_to_fit still guards
# the real context limit.
_TIER_MARKDOWN_CHARS = int(os.getenv("TIER_MARKDOWN_CHARS", "12000"))

TIER_LABELS_MAP = {0: "Non-AI", 1: "Wrapper", 2: "RAG Architect", 3: "AI Expert"}

_TIER_CLASSIFY_PROMPT = """\
You are an AI recruitment expert. Read the candidate's work experience, skills, and resume excerpt, \
then classify their AI engineering depth into one of 3 tiers based on EVIDENCE DEPTH, not keyword frequency.

Tier 0 – Non-AI (base 30):
  Evidence: No AI/ML work at all. General software, IT support, QA, hardware, firmware, \
data entry, or a non-technical background. A student with only coursework and no AI project also lands here.
  Key signal: nothing in the resume shows the candidate ever built, called, or trained an AI model.
  Use this tier freely — most applicants for an AI role are NOT AI engineers, and marking \
them Tier 1 hides that.

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

Evidence-reading rules:
  - The 工作經驗 / 技能標籤 sections come from an imperfect parser and are often EMPTY.
    Empty structured fields are NOT evidence of a weak candidate. When they are marked
    "未擷取到", read the 履歷原文 section and judge from it alone.
  - Judge only on what the resume actually shows. Do not assume unstated experience.
  - Set confidence < 0.5 when the resume is too sparse or unreadable to judge.

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


def tier_classifier_key() -> str:
    """Cache identity of the tier classifier: prompt *and* the model running it.

    A tier is the judgement of one model under one prompt. Keying the cache on
    the prompt alone was correct while there was exactly one backend; now that
    the provider is switchable, a tier classified by a local 7B would be served
    unchanged after switching to GPT-4o, and the operator would see the old
    distribution and conclude the switch did nothing.

    The default provider+model reproduces the bare prompt hash, so the 3179
    existing cached rows stay valid and nothing is invalidated by this change
    alone.
    """
    try:
        from app import llm_config

        suffix = f"{llm_config.provider('chat')}:{llm_config.model('chat')}"
        if suffix == f"{llm_config.PROVIDER_LMSTUDIO}:":
            return TIER_CLASSIFY_PROMPT_MD5
    except Exception:
        return TIER_CLASSIFY_PROMPT_MD5
    return hashlib.md5(
        (TIER_CLASSIFY_PROMPT_MD5 + "|" + suffix).encode()
    ).hexdigest()[:12]


def classify_ai_tier(
    work_experiences: list[dict],
    skill_tags: list[str],
    raw_markdown: str = "",
) -> dict:
    """Use LLM to classify candidate into the 3-tier AI pyramid."""
    exp_text = json.dumps(work_experiences, ensure_ascii=False)
    skills_text = ", ".join(skill_tags) if skill_tags else "None"

    # Structured fields are frequently empty after parsing; label them as
    # "not extracted" rather than "none exist" so the model does not read a
    # parser gap as evidence of an inexperienced candidate.
    if not work_experiences:
        exp_text = "（結構化欄位未擷取到工作經驗，請改以下方履歷原文為準）"
    if not skill_tags:
        skills_text = "（結構化欄位未擷取到技能標籤，請改以下方履歷原文為準）"

    user_content = (
        f"=== 工作經驗 ===\n{exp_text}\n\n"
        f"=== 技能標籤 ===\n{skills_text}\n\n"
    )
    if _INCLUDE_RAW_MARKDOWN:
        md_excerpt = (raw_markdown or "")[:_TIER_MARKDOWN_CHARS]
        if md_excerpt.strip():
            user_content += f"=== 履歷原文 ===\n{md_excerpt}"
        else:
            user_content += "=== 履歷原文 ===\n（無履歷內容）"
    user_content = _truncate_to_fit(_TIER_CLASSIFY_PROMPT, user_content)

    messages = [
        {"role": "system", "content": _TIER_CLASSIFY_PROMPT},
        {"role": "user", "content": user_content},
    ]

    raw = _chat(messages, temperature=0.1, max_tokens=1024)
    cleaned = _strip_fences(raw)

    try:
        data = json.loads(cleaned)
        tier = max(0, min(int(data.get("tier", 0)), 3))
        data["tier"] = tier
        data["tier_label"] = TIER_LABELS_MAP.get(tier, "Non-AI")
        return data
    except (json.JSONDecodeError, TypeError, ValueError):
        # Try to extract partial JSON (truncated responses)
        m = re.search(r'"tier"\s*:\s*(\d+)', cleaned)
        if m:
            tier = max(0, min(int(m.group(1)), 3))
            return {
                "tier": tier,
                "tier_label": TIER_LABELS_MAP.get(tier, "Non-AI"),
                "evidence": [],
                "reasoning": "partial",
            }
        logger.error("LLM tier classification returned invalid JSON: %s", cleaned[:500])
        # Signal failure rather than silently assigning a passing tier.
        return {
            "tier": 0,
            "tier_label": "Non-AI",
            "evidence": [],
            "confidence": 0.0,
            "reasoning": "分類失敗",
        }


_INTERVIEW_Q_PROMPT = """\
你是一位資深的 AI 技術招募專家。根據以下候選人履歷與職位需求，生成一份量身打造的繁體中文面試問題清單。

要求：
- 所有問題使用繁體中文
- 問題必須具體，直接引用候選人履歷中的實際技術、專案或公司
- 覆蓋以下四個類別（每類 2-3 題）：
  1. 技術深度驗證 — 驗證履歷中提到的具體技術能力
  2. 專案經驗深挖 — 探究實際成果、規模與影響力
  3. 問題解決能力 — 針對職位需求的情境式問題
  4. 職位匹配與動機 — 了解與此職位的契合度

Return ONLY valid JSON（不含 markdown fences，不含多餘說明）：
{
  "questions": [
    {
      "category": "技術深度驗證",
      "question": "具體問題內容",
      "purpose": "此問題希望驗證的能力（一句話）"
    }
  ]
}"""


def generate_interview_questions(candidate: dict, job_data: dict) -> dict:
    """Use LLM to generate tailored interview questions in Traditional Chinese."""
    candidate_summary = {
        "name": candidate.get("name", ""),
        "education": candidate.get("education", []),
        "work_experiences": candidate.get("work_experiences", []),
        "skill_tags": candidate.get("skill_tags", []),
        "self_introduction": candidate.get("self_introduction", ""),
        "years_of_experience": candidate.get("years_of_experience", ""),
    }
    candidate_json = json.dumps(candidate_summary, ensure_ascii=False)
    job_json = _job_brief(job_data)

    user_content = (
        f"=== 候選人資料 ===\n{candidate_json}\n\n"
        f"=== 職位需求 ===\n{job_json}"
    )
    user_content = _truncate_to_fit(_INTERVIEW_Q_PROMPT, user_content)

    messages = [
        {"role": "system", "content": _INTERVIEW_Q_PROMPT},
        {"role": "user", "content": user_content},
    ]

    raw = _chat(messages, temperature=0.5, max_tokens=_response_tokens())
    cleaned = _strip_fences(raw)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error("LLM interview questions returned invalid JSON: %s", cleaned[:500])
        return {"questions": []}


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
    job_json = _job_brief(job_data)

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

    raw = _chat(messages, temperature=0.3, max_tokens=_response_tokens())
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


# --- Domain-agnostic tier classification ------------------------------------

_GENERIC_TIER_PROMPT_HEADER = """\
你是一位資深招募評鑑專家。請閱讀候選人的工作經驗、技能與履歷原文，\
依照下方「本職缺專屬的深度分級標準」把候選人歸入 0-3 其中一級。

判斷依據是「證據深度」，不是關鍵字出現次數，也不是年資長短。

=== 本職缺：{job_name} ===
{job_summary}

=== 分級標準 ===
{tier_definitions}

=== 判讀規則 ===
- 工作經驗 / 技能標籤 欄位來自不完美的解析器，經常是空的。欄位空白不代表候選人能力弱；\
當它標示「未擷取到」時，請完全依據「履歷原文」判斷。
- 只依履歷實際呈現的內容判斷，不要推測未寫出的經歷。
- 技能欄列出某項工具、但內文完全沒有對應的實作描述時，不可據此升級。
- 實習、自由接案、論文、產學合作與個人專案都可作為有效證據；依交付範圍、技術深度、
  ownership 與成果判斷，不可只因不是正職或年資短就降級。
- 判定 Tier 0 前，必須確認工作、實習、研究與專案中都沒有本領域實作；只要有具體實作，
  至少應依其證據深度考慮 Tier 1。
- 履歷資訊過於稀少或無法辨讀時，把 confidence 設在 0.5 以下。
- confidence >= 0.8 必須能列出至少兩項彼此獨立的具體證據；若結構化欄位與履歷原文互相
  矛盾，confidence 不得高於 0.7。
- 完全沒有本領域相關證據時就給 Tier 0。多數應徵者本來就不是這個領域的人，\
把他們一律放進 Tier 1 會讓分級失去意義。

只輸出 JSON，不要 markdown 圍欄、不要多餘文字：
{{
  "tier": 2,
  "tier_label": "對應的級距名稱",
  "confidence": 0.85,
  "evidence": ["履歷中支持此判斷的原文片段"],
  "anti_inflation_flags": ["技能列出 X 但無實作描述"],
  "reasoning": "1-2 句繁體中文說明"
}}"""


def build_tier_prompt(profile) -> str:
    """Render the classification prompt for a domain profile.

    The profile's tier definitions ARE the prompt — that is what makes the same
    classifier work for a sales lead and a firmware engineer.
    """
    blocks = []
    for level in (0, 1, 2, 3):
        spec = profile.tier_spec(level)
        if spec is None:
            continue
        block = f"Tier {level} – {spec.label or f'Tier {level}'}\n  判斷依據：{spec.definition}"
        if spec.evidence_examples:
            block += f"\n  典型證據：{', '.join(spec.evidence_examples[:6])}"
        blocks.append(block)

    return _GENERIC_TIER_PROMPT_HEADER.format(
        job_name=profile.name or profile.domain or "未命名職缺",
        job_summary=profile.summary or "（無職位描述）",
        tier_definitions="\n\n".join(blocks),
    )


def classify_domain_tier(
    profile,
    work_experiences: list[dict],
    skill_tags: list[str],
    raw_markdown: str = "",
) -> dict:
    """Classify a candidate's depth against an arbitrary domain profile.

    Mirrors :func:`classify_ai_tier` — same empty-field handling, same JSON
    repair on truncated responses — but takes its tier semantics from the
    profile instead of the hard-coded AI pyramid.
    """
    system_prompt = build_tier_prompt(profile)

    exp_text = json.dumps(work_experiences, ensure_ascii=False)
    skills_text = ", ".join(skill_tags) if skill_tags else "None"
    if not work_experiences:
        exp_text = "（結構化欄位未擷取到工作經驗，請改以下方履歷原文為準）"
    if not skill_tags:
        skills_text = "（結構化欄位未擷取到技能標籤，請改以下方履歷原文為準）"

    user_content = (
        f"=== 工作經驗 ===\n{exp_text}\n\n"
        f"=== 技能標籤 ===\n{skills_text}\n\n"
    )
    md_excerpt = (raw_markdown or "")[:_TIER_MARKDOWN_CHARS]
    user_content += f"=== 履歷原文 ===\n{md_excerpt if md_excerpt.strip() else '（無履歷內容）'}"
    user_content = _truncate_to_fit(system_prompt, user_content)

    raw = _chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.1,
        max_tokens=1024,
    )
    cleaned = _strip_fences(raw)

    try:
        data = json.loads(cleaned)
        tier = max(0, min(int(data.get("tier", 0)), 3))
        data["tier"] = tier
        data["tier_label"] = profile.tier_label(tier)
        return data
    except (json.JSONDecodeError, TypeError, ValueError):
        m = re.search(r'"tier"\s*:\s*(\d+)', cleaned)
        if m:
            tier = max(0, min(int(m.group(1)), 3))
            return {
                "tier": tier,
                "tier_label": profile.tier_label(tier),
                "evidence": [],
                "reasoning": "partial",
            }
        logger.error("Domain tier classify returned invalid JSON: %s", cleaned[:500])
        raise ValueError("LLM 回傳的分級結果不是有效 JSON") from None
