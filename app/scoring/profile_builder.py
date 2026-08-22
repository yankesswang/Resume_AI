"""Build a DomainProfile from an uploaded job description.

The company uploads a JD (PDF / Word / plain text) and gets back a complete,
editable scoring standard for that role — whatever the field.  Two LLM calls do
the work:

1. ``extract_job_requirement`` turns unstructured JD text into the same
   ``job_requirement.json`` shape the app already uses everywhere.
2. ``generate_domain_profile`` writes the scoring standard: what the four depth
   tiers mean *in this field*, the evidence keywords for each, the capability
   axes that replace backend/database/frontend, which majors count, and the
   hard filters.

Both are LLM output, so both are validated and repaired before use.  A profile
that fails validation is returned WITH its errors rather than silently
sanitised — a scoring standard nobody reviewed is exactly how a screening
system starts rejecting people for reasons no one can explain.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.scoring.domain_profile import (
    DomainProfile,
    TIER_LEVELS,
    validate_profile,
)
from app.scoring.hard_filter import normalise_degree

logger = logging.getLogger(__name__)


# --- Step 1: JD text → structured job requirement ---------------------------

_JD_EXTRACT_PROMPT = """\
你是一位招募資料結構化助理。使用者會給你一份職缺說明（JD），可能來自 PDF、Word 或純文字，\
內容可能是任何領域：工程、業務、行銷、財會、人資、營運、設計、製造、醫療、法務等。

請把它轉成 JSON。只輸出 JSON，不要 markdown 圍欄、不要說明文字。

{
  "basic_conditions": {
    "job_title": "", "employment_type": "", "headcount": 1, "department": "",
    "job_categories": [], "management_responsibility": "",
    "work_location": {"address": ""}
  },
  "job_summary": "一段話說明這個職位在做什麼",
  "responsibilities": [{"category": "", "items": [""]}],
  "requirements": {
    "education": "", "experience_years": "", "majors": [],
    "skills": [], "languages": [], "certifications": [], "others": []
  },
  "preferred_qualifications": [],
  "domain": "這個職缺所屬的專業領域，用中文簡短描述，例如：業務開發、財務會計、機構設計、數位行銷"
}

規則：
- 缺漏欄位用空字串 "" 或空陣列 []，不要杜撰內容
- 保留原文的繁體中文用詞
- responsibilities 依原文分組；若原文是平鋪的條列，就放在單一 category 內
- requirements 只能收錄原文明確要求的必要條件；「加分、尤佳、優先、preferred、nice to have」
  一律放 preferred_qualifications，不可混入 requirements
- 同一句若同時包含學歷、年資與產業經驗，三者都必須保留，不可只抽其中一項；年資放
  requirements.experience_years，產業經驗放 requirements.others
- 工作內容不等於任用門檻；不要因 responsibilities 提到某工具，就自行把它列為必要技能
- domain 必填，這是後續建立評分標準的依據"""


def extract_job_requirement(jd_text: str, filename: str = "") -> dict[str, Any]:
    """Turn raw JD text into the app's job requirement JSON shape."""
    from app.llm import _chat, _strip_fences, _truncate_to_fit

    user_content = _truncate_to_fit(
        _JD_EXTRACT_PROMPT, jd_text, response_tokens=3072
    )
    raw = _chat(
        [
            {"role": "system", "content": _JD_EXTRACT_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.1,
        max_tokens=3072,
    )
    data = _loads_or_raise(_strip_fences(raw), "job requirement")

    # The JD text itself is kept so a human can check what the model read, and
    # so the profile can be regenerated later without re-uploading the file.
    data.setdefault("basic_conditions", {})
    data["source_document"] = filename
    data["source_text"] = jd_text[:20000]
    return data


# --- Step 2: job requirement → domain profile -------------------------------

_PROFILE_PROMPT = """\
你是一位資深招募評鑑設計師。使用者會給你一份職缺需求，領域不限（工程、業務、行銷、財會、\
人資、營運、設計、製造、醫療、法務…）。請為這個職缺設計一套「履歷篩選評分標準」。

只輸出 JSON，不要 markdown 圍欄、不要說明文字。格式：

{
  "domain": "職缺所屬專業領域",
  "summary": "一兩句話描述這個職位的核心價值",
  "tiers": [
    {"level": 0, "label": "", "definition": "", "evidence_examples": []},
    {"level": 1, "label": "", "definition": "", "evidence_examples": []},
    {"level": 2, "label": "", "definition": "", "evidence_examples": []},
    {"level": 3, "label": "", "definition": "", "evidence_examples": []}
  ],
  "tier_keywords": {
    "1": {"<實際的入門級關鍵字>": 1.0, "<另一個>": 0.8},
    "2": {"<實際的進階關鍵字>": 1.5, "<另一個>": 1.8},
    "3": {"<實際的專家級關鍵字>": 2.0, "<另一個>": 2.5}
  },
  "competencies": [
    {"key": "<英文代號>", "label": "<中文名稱>", "weight": 0.4,
     "levels": {"1": ["<入門關鍵字>"], "2": ["<進階關鍵字>"], "3": ["<高階關鍵字>"]}}
  ],
  "education": {"matters": true, "tier1_majors": [], "tier2_majors": []},
  "ecosystems": [{"name": "", "score": 90, "keywords": []}],
  "hard_filters": {
    "must_have_groups": [
      {"name": "", "skills": [], "min_matches": 1}
    ],
    "min_education": "",
    "min_school_tier": ""
  },
  "weights": {"experience": 0.35, "engineering": 0.20, "semantic": 0.20,
              "education": 0.15, "skills": 0.10}
}

設計規則（務必遵守）：

1. tiers 一定是 0-3 四級，代表這個領域的「實作深度」，不是年資：
   - level 0：完全沒有這個領域的經驗（其他行業轉職者、無相關證據）
   - level 1：入門／執行層，照既定流程做事
   - level 2：能獨立負責、設計方法或帶專案
   - level 3：該領域的專家，能定義策略、解決同行解不了的問題
   definition 要寫「該看到什麼證據」，不是抽象形容詞。這段文字會直接餵給分類模型。

2. tier_keywords 是履歷中可字面比對的字串（工具、方法、制度、證照、專有名詞）。
   - 上面 JSON 範例中 <尖括號> 內是填空說明，不是要你照抄的內容。
     務必換成這個領域真實存在的詞，例如會計職應該是「IFRS」「稅務簽證」「SAP」
     「會計師執照」「合併報表」，絕對不要出現「關鍵字」「keywords」這類字樣。
   - 每一級至少 8 個，其中至少 4 個繁體中文、4 個英文；可放同一概念的中英對照詞
   - level 3 要是這個領域最難造假的硬訊號
   - 權重 0.5-2.5，越難取得的訊號權重越高
   - 不要放「認真」「負責」這種無法比對的形容詞
   - 中英文都要放（履歷可能任一種語言書寫）

3. competencies 是這個職缺的能力面向，2-4 項，weight 加總為 1.0。
   例如業務職可能是「通路開發／客戶經營／議價談判」，會計職可能是
   「帳務處理／稅務法規／ERP 系統」。每個面向的 levels 1/2/3 各至少 3 個關鍵字，
   且每級至少包含 1 個繁體中文詞。

4. education.matters：這個職缺是否要用「學校與科系」拉開候選人分數。只有最低學位要求、
   但未指定科系時填 false（最低學位仍由 hard filter 驗證）；業務、客服、技術員等通常填 false。
   tier1_majors 填最對口的科系，tier2_majors 填相關但非核心的科系；保留常見繁體中文科系名。

5. ecosystems 是技能族群分類，2-4 組，score 30-90，代表該族群技能的價值高低；
   每組 keywords 都要同時包含繁體中文與英文訊號，並涵蓋履歷常見的產品類別、產業別名、
   縮寫及代表性公司／品牌名稱。例如筆電業務應包含「筆記型電腦」「消費性電子」「PC」、
   「MSI」等，而非只列 JD 內的完整句子。

6. hard_filters 只放職缺 requirements 中「明確寫成必要」且能從履歷可靠驗證的條件，寧可少不要多：
   - 不可從職稱、工作內容、常見業界慣例推測門檻，也不可把 preferred_qualifications 變成門檻
   - skills 只允許履歷可直接字面驗證的原子工具、技術或證照名稱，例如 Python、IFRS、PMP
   - 不可把完整句子、產業經驗、年資、語言程度或溝通能力放進 skills；這些不能靠字面命中淘汰
   - skills 必須使用 requirements 內實際出現的字串；同一組代表 OR，通常 min_matches=1
   - min_education 只在 requirements 明確要求最低學歷時填 high_school/associate/bachelor/master/phd
   - min_school_tier 一律留空；JD 的校名偏好不能自動轉換成淘汰門檻
   - 若沒有真正的硬性門檻，must_have_groups 給空陣列，其餘留空

7. weights 五個維度加總必須是 1.0：
   - experience：該領域深度  - engineering：能力面向矩陣
   - semantic：語意相似度    - education：學歷  - skills：技能驗證
   依職缺性質調整。學歷不重要的職缺就把 education 調低、把權重移到 experience。

8. 全部用繁體中文書寫（關鍵字保留原文英文）。"""

_PROFILE_REPAIR_INSTRUCTION = """\
上一版評分標準未通過系統品質檢查。請根據同一份職缺需求修正完整 JSON。
只修正檢查指出的問題，不可新增 JD 未明確要求的硬門檻；仍只輸出 JSON。"""


def generate_domain_profile(
    job_data: dict[str, Any],
    source_document: str = "",
) -> tuple[DomainProfile, list[str]]:
    """Ask the LLM to design a scoring standard for this job.

    Returns ``(profile, errors)``.  A non-empty ``errors`` list means the
    profile needs human attention before it should be used to reject anybody;
    the caller decides whether to surface it for editing or refuse it.
    """
    from app.llm import _chat, _job_brief, _strip_fences, _truncate_to_fit

    brief = _job_brief(job_data)
    # The raw JD text carries wording the structured extract drops (tools named
    # in passing, industry jargon), and that wording is exactly what makes
    # generated keywords match real resumes.
    src = (job_data.get("source_text") or "")[:6000]
    user_content = f"=== 職缺需求 ===\n{brief}"
    if src:
        user_content += f"\n\n=== 原始職缺文件（節錄）===\n{src}"
    user_content = _truncate_to_fit(
        _PROFILE_PROMPT, user_content, response_tokens=4096
    )

    def build(raw_text: str) -> tuple[DomainProfile, list[str], dict[str, Any]]:
        generated = _loads_or_raise(_strip_fences(raw_text), "domain profile")
        generated = _repair(generated, job_data, enforce_grounding=True)
        generated["source"] = "llm"
        generated["source_document"] = source_document
        generated["profile_id"] = _profile_id(job_data)
        generated["name"] = (
            job_data.get("basic_conditions", {}).get("job_title")
            or generated.get("domain")
            or "未命名職缺"
        )
        parsed = DomainProfile.model_validate(generated)
        errors = validate_profile(parsed) + _generation_quality_errors(parsed)
        return parsed, errors, generated

    raw = _chat(
        [
            {"role": "system", "content": _PROFILE_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
        max_tokens=4096,
    )
    profile, errors, generated = build(raw)

    # Most generations pass in one call.  A thin keyword set or an incomplete
    # capability axis cannot screen reliably, so give the model one targeted
    # correction rather than returning a predictably unusable draft.  Keep the
    # first version if the correction is malformed or does not improve it.
    if errors:
        repair_content = (
            f"{_PROFILE_REPAIR_INSTRUCTION}\n\n"
            f"=== 品質檢查錯誤 ===\n" + "\n".join(f"- {e}" for e in errors)
            + f"\n\n=== 原職缺需求 ===\n{user_content}"
            + "\n\n=== 待修正初稿 ===\n"
            + json.dumps(generated, ensure_ascii=False)
        )
        repair_content = _truncate_to_fit(
            _PROFILE_PROMPT, repair_content, response_tokens=4096
        )
        try:
            corrected_raw = _chat(
                [
                    {"role": "system", "content": _PROFILE_PROMPT},
                    {"role": "user", "content": repair_content},
                ],
                temperature=0.1,
                max_tokens=4096,
            )
            corrected, corrected_errors, _ = build(corrected_raw)
            if len(corrected_errors) < len(errors):
                profile, errors = corrected, corrected_errors
        except Exception:
            logger.warning("LLM profile correction failed; keeping first draft", exc_info=True)

    return profile, errors


# --- Repair -----------------------------------------------------------------

def _repair(
    data: dict[str, Any],
    job_data: dict[str, Any],
    *,
    enforce_grounding: bool = False,
) -> dict[str, Any]:
    """Fix the LLM's predictable structural mistakes.

    This normalises *shape* only (missing tiers, string weights, keyword lists
    where a weight map was asked for).  It never invents domain content — a
    tier with no keywords stays empty so validation reports it, rather than
    being quietly filled with something nobody chose.
    """
    data = dict(data or {})

    # Tiers: guarantee all four levels exist, preserving whatever the model gave.
    by_level = {}
    for t in data.get("tiers") or []:
        if not isinstance(t, dict):
            continue
        try:
            lvl = int(t.get("level"))
        except (TypeError, ValueError):
            continue
        if lvl in TIER_LEVELS:
            t["level"] = lvl
            t.setdefault("evidence_examples", [])
            by_level[lvl] = t
    _DEFAULT_LABELS = {0: "無相關經驗", 1: "入門", 2: "獨立負責", 3: "領域專家"}
    data["tiers"] = [
        by_level.get(
            lvl,
            {"level": lvl, "label": _DEFAULT_LABELS[lvl], "definition": "",
             "evidence_examples": []},
        )
        for lvl in TIER_LEVELS
    ]

    # tier_keywords: accept {"3": ["a","b"]} as well as {"3": {"a": 2.0}}.
    # Placeholder echoes are dropped: a model that copies the schema's filler
    # words produces a profile that validates but matches nothing in any real
    # resume — the worst outcome, because it looks configured and screens blind.
    # A bare list is a common model slip; default weights by tier keep the
    # higher tiers weighted more heavily, matching the calibrated profile.
    _DEFAULT_W = {"0": 0.5, "1": 1.0, "2": 1.5, "3": 2.0}
    kws_in = data.get("tier_keywords") or {}
    kws_out: dict[str, dict[str, float]] = {}
    for lvl, kws in kws_in.items():
        key = str(lvl)
        if key not in {"0", "1", "2", "3"}:
            continue
        bucket: dict[str, float] = {}
        if isinstance(kws, dict):
            for k, w in kws.items():
                k = _clean_keyword(k)
                if not k:
                    continue
                bucket[k] = min(2.5, max(0.5, _as_float(w, _DEFAULT_W.get(key, 1.0))))
        elif isinstance(kws, list):
            for k in kws:
                k = _clean_keyword(k)
                if k:
                    bucket[k] = _DEFAULT_W.get(key, 1.0)
        if bucket:
            kws_out[key] = bucket
    # The same literal at two depths makes keyword classification contradictory.
    # Keep it at the lowest claimed level; a generic signal must not become proof
    # of expertise merely because the model repeated it in Tier 3.
    seen_keywords: set[str] = set()
    for key in ("0", "1", "2", "3"):
        bucket = kws_out.get(key, {})
        deduplicated: dict[str, float] = {}
        for keyword, weight in bucket.items():
            normalised = _keyword_key(keyword)
            if normalised in seen_keywords:
                continue
            seen_keywords.add(normalised)
            deduplicated[keyword] = weight
        kws_out[key] = deduplicated
    data["tier_keywords"] = {k: v for k, v in kws_out.items() if v}

    # Competencies: coerce level keys to strings, weights to floats.
    comps = []
    for c in data.get("competencies") or []:
        if not isinstance(c, dict):
            continue
        levels = {}
        seen_competency_keywords: set[str] = set()
        for lvl in ("1", "2", "3"):
            kws = (c.get("levels") or {}).get(lvl)
            if kws is None:
                kws = (c.get("levels") or {}).get(int(lvl))
            if kws is None:
                continue
            if isinstance(kws, str):
                kws = [kws]
            cleaned_level = []
            for raw_keyword in kws or []:
                cleaned = _clean_keyword(raw_keyword)
                normalised = _keyword_key(cleaned)
                if not cleaned or normalised in seen_competency_keywords:
                    continue
                seen_competency_keywords.add(normalised)
                cleaned_level.append(cleaned)
            levels[lvl] = cleaned_level
        key = str(c.get("key") or "").strip()
        label = str(c.get("label") or "").strip()
        if not key:
            # A missing key is recoverable: slugify the label rather than
            # dropping a whole capability axis the model did design.
            key = _slug(label) or f"c{len(comps) + 1}"
        comps.append({
            "key": key,
            "label": label or key,
            "weight": _as_float(c.get("weight"), 1.0),
            "levels": levels,
        })
    data["competencies"] = comps

    # Education
    edu = data.get("education")
    if not isinstance(edu, dict):
        edu = {}
    edu.setdefault("matters", True)
    edu["tier1_majors"] = _str_list(edu.get("tier1_majors"))
    edu["tier2_majors"] = _str_list(edu.get("tier2_majors"))
    # Fall back to the majors named in the JD itself when the model gave none.
    if not edu["tier1_majors"]:
        edu["tier1_majors"] = _str_list(
            (job_data.get("requirements") or {}).get("majors")
        )
    if enforce_grounding and not _str_list(
        (job_data.get("requirements") or {}).get("majors")
    ):
        # A generic minimum degree is an eligibility gate, not evidence that a
        # prestigious school or an unrelated master's predicts job performance.
        # The hard filter still enforces the degree; education scoring is removed
        # unless the JD explicitly names a relevant field of study.
        edu["matters"] = False
    data["education"] = edu

    # Ecosystems
    ecos = []
    for e in data.get("ecosystems") or []:
        if not isinstance(e, dict):
            continue
        name = str(e.get("name") or "").strip()
        if not name:
            continue
        ecos.append({
            "name": name,
            "score": min(90.0, max(30.0, _as_float(e.get("score"), 50.0))),
            "keywords": _str_list(e.get("keywords")),
        })
    data["ecosystems"] = ecos

    # Hard filters: drop empty groups so they cannot reject everybody.
    hf = data.get("hard_filters")
    if not isinstance(hf, dict):
        hf = {}
    groups = []
    for g in hf.get("must_have_groups") or []:
        if not isinstance(g, dict):
            continue
        skills = _str_list(g.get("skills"))
        if not skills:
            continue
        try:
            min_matches = max(1, int(g.get("min_matches", 1)))
        except (TypeError, ValueError):
            min_matches = 1
        groups.append({
            "name": str(g.get("name") or "必要條件"),
            "skills": skills,
            # A group demanding more matches than it lists can never pass.
            "min_matches": min(min_matches, len(skills)),
        })
    hf["must_have_groups"] = groups

    # Minimum degree: normalise onto the ladder and drop anything unrecognised.
    # A value the filter cannot read would gate on nothing while still looking
    # configured in the UI.
    min_edu = hf.get("min_education")
    hf["min_education"] = (
        normalise_degree(str(min_edu)) or "" if min_edu else ""
    )

    # Minimum school tier: same reasoning — an unreadable rung gates on nothing.
    min_school = str(hf.get("min_school_tier") or "").strip().upper()
    hf["min_school_tier"] = min_school if min_school in ("A", "B", "C") else ""

    if enforce_grounding:
        hf = _ground_hard_filters(hf, job_data)

    data["hard_filters"] = hf

    # Weights: renormalise instead of rejecting. Models routinely emit
    # 0.35/0.2/0.2/0.15/0.1 as strings, or sum to 0.99.
    weights = data.get("weights")
    if isinstance(weights, dict) and weights:
        known = ("experience", "engineering", "semantic", "education", "skills")
        cleaned = {k: max(0.0, _as_float(weights.get(k), 0.0)) for k in known}
        total = sum(cleaned.values())
        if total > 0:
            data["weights"] = {k: round(v / total, 4) for k, v in cleaned.items()}
            # Rounding can leave the sum at 0.9999; push the drift onto the
            # largest dimension so validation's exact-1.0 check passes.
            drift = round(1.0 - sum(data["weights"].values()), 4)
            if drift:
                top = max(data["weights"], key=lambda k: data["weights"][k])
                data["weights"][top] = round(data["weights"][top] + drift, 4)
        else:
            data["weights"] = {}
    else:
        data["weights"] = {}

    return data


# --- helpers ----------------------------------------------------------------

def _loads_or_raise(text: str, what: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Models sometimes wrap the object in prose despite instructions.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                logger.error("LLM returned invalid JSON for %s: %s", what, text[:500])
                raise ValueError(f"LLM 回傳的 {what} 不是有效 JSON") from None
        else:
            logger.error("LLM returned invalid JSON for %s: %s", what, text[:500])
            raise ValueError(f"LLM 回傳的 {what} 不是有效 JSON") from None
    if not isinstance(data, dict):
        raise ValueError(f"LLM 回傳的 {what} 不是 JSON 物件")
    return data


def _as_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _str_list(v: Any) -> list[str]:
    if isinstance(v, str):
        v = [v]
    return [str(x).strip() for x in (v or []) if str(x).strip()]


def _flatten_strings(value: Any) -> list[str]:
    """Return the textual leaves of an extracted JD field."""
    if isinstance(value, dict):
        out: list[str] = []
        for child in value.values():
            out.extend(_flatten_strings(child))
        return out
    if isinstance(value, (list, tuple, set)):
        out = []
        for child in value:
            out.extend(_flatten_strings(child))
        return out
    text = str(value or "").strip()
    return [text] if text else []


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text or ""))


def _contains_latin(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", text or ""))


def _generation_quality_errors(profile: DomainProfile) -> list[str]:
    """Check language coverage needed when scoring Chinese and English resumes.

    This is intentionally generation-only. Existing manually curated profiles
    remain valid even if they are designed for a single-language candidate pool.
    """
    errors: list[str] = []
    for level in (1, 2, 3):
        keywords = profile.tier_keywords.get(str(level), {})
        cjk_count = sum(_contains_cjk(keyword) for keyword in keywords)
        if cjk_count < 2:
            errors.append(
                f"Tier {level} 至少需要 2 個繁體中文關鍵字，目前只有 {cjk_count} 個"
            )
        latin_count = sum(_contains_latin(keyword) for keyword in keywords)
        if latin_count < 2:
            errors.append(
                f"Tier {level} 至少需要 2 個英文關鍵字，目前只有 {latin_count} 個"
            )

    for competency in profile.competencies:
        for level, terms in competency.levels.items():
            if terms and not any(_contains_cjk(term) for term in terms):
                errors.append(
                    f"能力面向「{competency.label}」Level {level} 缺少繁體中文關鍵字"
                )

    majors = profile.education.tier1_majors + profile.education.tier2_majors
    if profile.education.matters and majors and not any(_contains_cjk(x) for x in majors):
        errors.append("學歷科系缺少常見繁體中文名稱")

    for ecosystem in profile.ecosystems:
        if ecosystem.keywords and not any(
            _contains_cjk(keyword) for keyword in ecosystem.keywords
        ):
            errors.append(f"技能族群「{ecosystem.name}」缺少繁體中文關鍵字")
    return errors


def _keyword_key(keyword: str) -> str:
    """Case/spacing-insensitive identity used to remove repeated signals."""
    return re.sub(r"\s+", "", keyword).casefold()


def _literal_in_required_text(literal: str, required_text: str) -> bool:
    """Whether a generated gate is literally grounded in required JD fields."""
    needle = _keyword_key(literal)
    haystack = _keyword_key(required_text)
    if not needle:
        return False
    # Avoid treating a short ASCII skill such as Go or R as a substring of a
    # different word (Google, reporting). CJK terms and punctuated names such as
    # C++ use literal containment because word boundaries are not meaningful.
    ascii_literal = literal.strip().casefold()
    if re.fullmatch(r"[a-z0-9\s.#-]+", ascii_literal):
        # Permit harmless spacing variation ("Machine Learning" versus
        # "machine  learning") without turning it into fuzzy synonym matching.
        parts = [re.escape(part) for part in ascii_literal.split()]
        pattern = r"\s+".join(parts)
        return re.search(
            rf"(?<![a-z0-9]){pattern}(?![a-z0-9])",
            required_text.casefold(),
        ) is not None
    return needle in haystack


_UNRELIABLE_GATE_PATTERN = re.compile(
    r"\b(ability|experience|skills?|fluent|proficien(?:t|cy)|excellent|"
    r"communication|relationship|independent|self[ -]?starter|creative|organized|"
    r"related industry)\b|能力|經驗|精通|流利|溝通|關係|獨立|主動|相關產業",
    re.IGNORECASE,
)
_AMBIGUOUS_SHORT_GATES = {"ai", "it", "ml", "pc"}


def _is_reliable_literal_gate(literal: str) -> bool:
    """Whether a resume text hit can reliably prove this rejection gate.

    Hard-filter matching is literal substring search, not semantic assessment.
    Sentences such as "3 years of PC industry experience" or "fluent English"
    cannot be proven by the sentence merely appearing somewhere in a resume.
    Keep this path for atomic tools and credentials; structured evaluators own
    education today and can own experience/language in a future schema.
    """
    text = str(literal or "").strip()
    if not text or ":" in text or _UNRELIABLE_GATE_PATTERN.search(text):
        return False
    if _keyword_key(text) in _AMBIGUOUS_SHORT_GATES:
        return False
    # Long prose is not an atomic skill even if it avoids the common phrases.
    if len(text) > 40 or len(text.split()) > 5:
        return False
    return True


def _ground_hard_filters(
    hard_filters: dict[str, Any], job_data: dict[str, Any]
) -> dict[str, Any]:
    """Remove LLM-invented rejection gates using the structured JD as authority.

    The scorer may infer useful ranking signals from professional knowledge, but
    rejecting a candidate is different: every automatic gate must trace to the
    extracted ``requirements`` section. Preferences and responsibilities are
    intentionally absent from the searchable text.
    """
    requirements = job_data.get("requirements")
    requirements = requirements if isinstance(requirements, dict) else {}

    # Only fields whose values can be verified through literal resume text.
    # Languages, years and industry background require structured comparisons;
    # treating their prose as keywords rejects qualified candidates whenever the
    # resume uses different wording.
    searchable = {
        key: requirements.get(key)
        for key in ("skills", "certifications")
        if requirements.get(key)
    }
    required_text = "\n".join(_flatten_strings(searchable))

    grounded_groups = []
    for group in hard_filters.get("must_have_groups") or []:
        skills = [
            skill for skill in _str_list(group.get("skills"))
            if _is_reliable_literal_gate(skill)
            and _literal_in_required_text(skill, required_text)
        ]
        if not skills:
            continue
        grounded_groups.append({
            "name": str(group.get("name") or "必要條件"),
            "skills": skills,
            "min_matches": min(
                max(1, int(group.get("min_matches", 1))), len(skills)
            ),
        })

    # Education is structured separately and can therefore be derived more
    # reliably than trusting the generated value. No equivalent source field
    # exists for the app's internal A/B/C school ladder, so it is never inferred.
    education_text = " ".join(_flatten_strings(requirements.get("education")))
    required_degree = normalise_degree(education_text) if education_text else None

    return {
        "must_have_groups": grounded_groups,
        "min_education": required_degree or "",
        "min_school_tier": "",
    }


# Filler the model copies out of the prompt's JSON schema instead of replacing.
# Matched case-insensitively against the WHOLE trimmed keyword, so a real term
# that merely contains one of these words survives.
_PLACEHOLDERS = {
    "關鍵字", "keyword", "keywords", "字串", "詞彙",
    "入門關鍵字", "進階關鍵字", "高階關鍵字", "專家級關鍵字",
    "中文名稱", "英文代號", "名稱", "代號",
    "string", "example", "範例", "示例", "填入", "待填", "tbd", "n/a",
}


def _clean_keyword(raw: Any) -> str:
    """Normalise one keyword, dropping schema placeholders and angle brackets.

    Returns "" for anything unusable, so callers can filter with a truth test.
    """
    k = str(raw or "").strip()
    # "<實際的入門級關鍵字>" — the model kept the brackets around the filler.
    if k.startswith("<") and k.endswith(">"):
        return ""
    k = k.strip("<>「」\"' ").strip()
    if len(k) < 2:
        # A single character matches almost any resume and is never a real
        # domain signal.
        return ""
    if k.lower() in _PLACEHOLDERS:
        return ""
    return k


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def _profile_id(job_data: dict[str, Any]) -> str:
    title = job_data.get("basic_conditions", {}).get("job_title", "") or "job"
    return f"job:{_slug(title) or 'job'}"
