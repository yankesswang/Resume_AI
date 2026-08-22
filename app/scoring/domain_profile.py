"""Domain profile — a job-agnostic description of how to score one role.

The original pipeline hard-coded a single role: AI engineer.  Tier labels
("Wrapper", "RAG Architect"), the tier keyword tables, the LLM classifier
prompt and the "engineering maturity" matrix (backend/database/frontend) all
assumed that one job.  Screening a sales lead, an accountant or a mechanical
engineer through it produced the same answer for everybody, because none of
the evidence the scorer looks for exists in their resumes.

A ``DomainProfile`` lifts every one of those role-specific decisions out of the
code and into data, so a new role is a document rather than a patch:

- ``tiers``            what "depth" means in this field, 4 levels, with the
                       evidence that distinguishes them (replaces the AI pyramid)
- ``tier_keywords``    per-tier weighted signals for the keyword floor/fallback
- ``competencies``     the capability matrix (replaces backend/database/frontend)
- ``education``        which majors are relevant to *this* role
- ``hard_filters``     boolean gates, reusing the existing hard_filter schema
- ``ecosystems``       skill-cluster buckets for skill verification

Profiles come from two places:

1. ``builtin`` — the calibrated AI-engineer profile, preserved verbatim so the
   existing 3179 scores and every calibration note in docs/SCORING_ALGORITHM.md
   stay valid.
2. generated — ``app.scoring.profile_builder`` asks an LLM to write one from an
   uploaded job description, and a human edits it before it goes live.

A profile is stored on the job requirement it belongs to
(``job_requirements.domain_profile``), never globally, so two open roles can be
scored by two different standards at the same time.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# Profile schema version. Bumped when the shape changes in a way that older
# stored profiles cannot be read as-is; ``migrate()`` handles the upgrade.
SCHEMA_VERSION = 1

# Minimum keywords per tier before a profile is considered able to screen.
# See validate_profile for why this is 4 rather than 1.
MIN_TIER_KEYWORDS = 4

# A profile always describes exactly four depth levels (0..3). Four is not
# arbitrary: it is the smallest number that separates "no evidence at all" from
# "entry", "practitioner" and "expert", and it keeps the tier bands in
# app.scoring.config (which are calibrated to not overlap) reusable unchanged.
TIER_LEVELS = (0, 1, 2, 3)


class TierSpec(BaseModel):
    """One depth level within a domain."""

    level: int
    label: str = ""
    # What a human/LLM should look for to place a candidate at this level.
    # This text is injected into the classifier prompt verbatim, so it is the
    # single most important field in the whole profile.
    definition: str = ""
    # Illustrative evidence, shown in the UI and given to the LLM as examples.
    evidence_examples: list[str] = Field(default_factory=list)

    @field_validator("level")
    @classmethod
    def _level_in_range(cls, v: int) -> int:
        if v not in TIER_LEVELS:
            raise ValueError(f"tier level must be one of {TIER_LEVELS}, got {v}")
        return v


class CompetencySpec(BaseModel):
    """One axis of the capability matrix for this role.

    Generalises the old backend/database/frontend triple.  For a sales role the
    axes might be 通路開發 / 客戶管理 / 報價議約; for an accountant, 帳務處理 /
    稅務法規 / ERP 系統.  Each axis is scored 0-3 by keyword level, exactly like
    engineering maturity, and contributes ``weight`` of the matrix total.
    """

    key: str
    label: str = ""
    # weight is the share of the competency dimension this axis carries.
    # Weights across all competencies are normalised at load, so a profile
    # author does not have to make them sum to 1.0 by hand.
    weight: float = 1.0
    # level -> list of keywords/regex-ish literals proving that level.
    # Level 3 is the strongest signal, level 1 the weakest.
    levels: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("weight")
    @classmethod
    def _weight_positive(cls, v: float) -> float:
        if v < 0:
            raise ValueError("competency weight must be >= 0")
        return v


class EducationSpec(BaseModel):
    """Which fields of study matter for this role.

    School tiers stay global (a top school is a top school regardless of role),
    but major relevance is entirely role-dependent: 財金 is Tier1 for an analyst
    and Other for a firmware engineer.
    """

    tier1_majors: list[str] = Field(default_factory=list)
    tier2_majors: list[str] = Field(default_factory=list)
    # Some roles genuinely do not care about the degree (e.g. 業務, 客服).
    # Setting this lets the profile shift that weight elsewhere.
    matters: bool = True


class EcosystemSpec(BaseModel):
    """A skill cluster and how much credit it carries for this role."""

    name: str
    score: float = 50.0
    keywords: list[str] = Field(default_factory=list)


class DomainProfile(BaseModel):
    """The complete scoring standard for one job."""

    schema_version: int = SCHEMA_VERSION
    # Stable id; "builtin:ai-engineer" for the preserved original.
    profile_id: str = ""
    name: str = ""
    # Free-text domain name from the JD, e.g. "業務開發", "財務會計".
    domain: str = ""
    # Short description of the role, used in the classifier prompt.
    summary: str = ""
    # Language of the generated text, so the UI and prompts stay consistent.
    language: str = "zh-TW"

    tiers: list[TierSpec] = Field(default_factory=list)
    # tier level (as str, JSON-safe) -> {keyword: weight}
    tier_keywords: dict[str, dict[str, float]] = Field(default_factory=dict)
    competencies: list[CompetencySpec] = Field(default_factory=list)
    education: EducationSpec = Field(default_factory=EducationSpec)
    ecosystems: list[EcosystemSpec] = Field(default_factory=list)
    hard_filters: dict[str, Any] = Field(default_factory=dict)

    # Per-role weight override for the five scoring dimensions. Empty means
    # "use the global config", which is what the builtin profile does so that
    # existing scores are untouched.
    weights: dict[str, float] = Field(default_factory=dict)

    # Provenance: how this profile came to exist.
    source: str = "builtin"        # "builtin" | "llm" | "manual"
    source_document: str = ""      # filename of the uploaded JD, if any
    generated_at: str = ""
    edited_by: str = ""

    def tier_label(self, level: int) -> str:
        for t in self.tiers:
            if t.level == level:
                return t.label or f"Tier {level}"
        return f"Tier {level}"

    def tier_spec(self, level: int) -> TierSpec | None:
        for t in self.tiers:
            if t.level == level:
                return t
        return None

    def normalised_competencies(self) -> list[CompetencySpec]:
        """Competencies with weights normalised to sum to 1.0.

        A profile author (human or LLM) writes weights like 3/2/1 or 0.5/0.3/0.2
        interchangeably; normalising here means neither the scorer nor the UI has
        to care which convention was used.
        """
        comps = [c for c in self.competencies if c.weight > 0]
        total = sum(c.weight for c in comps)
        if total <= 0:
            return []
        out = []
        for c in comps:
            c2 = c.model_copy(deep=True)
            c2.weight = c.weight / total
            out.append(c2)
        return out

    def fingerprint(self) -> str:
        """Hash of everything that changes a score.

        Mixed into the LLM tier cache key exactly like TIER_CLASSIFY_PROMPT_MD5,
        so editing a profile automatically invalidates the tiers it produced
        instead of leaving stale classifications behind — the failure mode that
        left 98% of the pool at Tier 1 under an old prompt.
        """
        payload = {
            "tiers": [t.model_dump() for t in self.tiers],
            "tier_keywords": self.tier_keywords,
            "competencies": [c.model_dump() for c in self.competencies],
            "education": self.education.model_dump(),
            "ecosystems": [e.model_dump() for e in self.ecosystems],
            "hard_filters": self.hard_filters,
            "weights": self.weights,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(blob.encode("utf-8")).hexdigest()[:12]


# --- Validation -------------------------------------------------------------

def validate_profile(profile: DomainProfile) -> list[str]:
    """Return a list of human-readable problems; empty means usable.

    Validation is deliberately about *scoring viability*, not schema purity —
    a profile that parses but cannot separate candidates is worse than one that
    fails loudly here.
    """
    errors: list[str] = []

    levels = sorted(t.level for t in profile.tiers)
    if levels != list(TIER_LEVELS):
        errors.append(
            f"tiers 必須完整涵蓋 0-3 四個級距，目前為 {levels or '空'}"
        )

    for t in profile.tiers:
        if not t.definition.strip():
            errors.append(f"Tier {t.level} 缺少 definition，分類器將無從判斷")

    # A tier with too few keywords cannot be reached by the keyword floor or by
    # the fallback path when the LLM is unavailable, which silently degrades the
    # whole role to LLM-only scoring.
    #
    # MIN_TIER_KEYWORDS is 4, not 1, on purpose. A profile carrying one or two
    # terms per tier passes a naive "not empty" check while matching almost no
    # real resume — it looks configured and screens blind, which is worse than
    # failing loudly here. Four is the floor at which the tier-weight thresholds
    # in generic.classify_tier_by_profile (3.0 for tier 3, 2.0 for tier 2) can
    # actually be reached by a genuine candidate.
    for lvl in (1, 2, 3):
        kws = profile.tier_keywords.get(str(lvl)) or {}
        if not kws:
            errors.append(f"Tier {lvl} 沒有任何關鍵字，LLM 離線時無法評分")
        elif len(kws) < MIN_TIER_KEYWORDS:
            errors.append(
                f"Tier {lvl} 只有 {len(kws)} 個關鍵字（至少需要 {MIN_TIER_KEYWORDS} 個），"
                f"實際履歷幾乎不會命中"
            )

    # The top tier must be reachable: if no single keyword carries enough weight
    # and there are too few of them, tier 3 can never be assigned by keywords.
    t3 = profile.tier_keywords.get("3") or {}
    if t3 and sum(sorted(t3.values(), reverse=True)[:2]) < 3.0:
        errors.append(
            "Tier 3 關鍵字權重過低，僅靠關鍵字永遠無法判定為最高級距"
            "（建議專家級訊號給 1.5-2.5 的權重）"
        )

    if not profile.competencies:
        errors.append("competencies 至少需要一項能力面向")
    for c in profile.competencies:
        if not c.key:
            errors.append("competency 缺少 key")
        if not any(c.levels.get(str(l)) for l in (1, 2, 3)):
            errors.append(f"能力面向 '{c.key or c.label}' 沒有任何等級關鍵字")

    if profile.weights:
        total = sum(profile.weights.values())
        if abs(total - 1.0) > 1e-6:
            errors.append(f"weights 總和必須為 1.0，目前為 {round(total, 4)}")
        unknown = set(profile.weights) - {
            "experience", "engineering", "semantic", "education", "skills",
        }
        if unknown:
            errors.append(f"weights 含未知維度：{', '.join(sorted(unknown))}")

    return errors


def migrate(raw: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a stored profile dict to the current schema version."""
    data = copy.deepcopy(raw or {})
    version = int(data.get("schema_version", 0) or 0)
    if version >= SCHEMA_VERSION:
        return data
    # v0 -> v1: profiles predating schema_version had no provenance fields.
    data.setdefault("source", "manual")
    data["schema_version"] = SCHEMA_VERSION
    return data


def parse_profile(raw: dict[str, Any] | str | None) -> DomainProfile | None:
    """Load a profile from stored JSON, tolerating older shapes.

    Returns None (rather than raising) when there is nothing usable, so callers
    can fall back to the builtin profile — a bad profile must never take the
    scoring API down.
    """
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Stored domain profile is not valid JSON, ignoring")
            return None
    if not isinstance(raw, dict):
        return None
    try:
        return DomainProfile.model_validate(migrate(raw))
    except Exception as e:
        logger.warning("Stored domain profile failed validation, ignoring: %s", e)
        return None
