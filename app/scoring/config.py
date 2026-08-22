"""Tunable scoring configuration.

Single source of truth for every knob in the scoring pipeline.  Values live in
a JSON file on disk (``scoring_config.json``) so they can be edited from the
frontend at runtime without a redeploy or a code change.

Design rules:
- ``DEFAULTS`` below is the authoritative schema *and* the fallback.  A config
  file only needs to carry the keys it overrides.
- Every value is validated on load; a bad file degrades to defaults with a
  warning rather than taking the API down.
- ``bump_version()`` changes ``config_version``, which is mixed into the LLM
  tier cache key, so edited weights automatically invalidate stale scores.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(
    os.getenv(
        "SCORING_CONFIG_PATH",
        str(Path(__file__).resolve().parent.parent.parent / "scoring_config.json"),
    )
)

# --- Authoritative defaults -------------------------------------------------
# These mirror the calibrated values documented in docs/SCORING_ALGORITHM.md.
DEFAULTS: dict[str, Any] = {
    # Final score = sum(dimension_score * weight). Must sum to 1.0.
    "weights": {
        "experience": 0.35,
        "engineering": 0.20,
        "semantic": 0.20,
        "education": 0.15,
        "skills": 0.10,
    },
    # AI experience tier bands. base = floor of the tier, bonus_cap keeps a
    # strong candidate from leaking into the tier above.
    "tiers": {
        "0": {"base": 25, "bonus_cap": 15, "label": "Non-AI"},
        "1": {"base": 45, "bonus_cap": 17, "label": "Wrapper"},
        "2": {"base": 67, "bonus_cap": 17, "label": "RAG Architect"},
        "3": {"base": 88, "bonus_cap": 12, "label": "AI Expert"},
    },
    # Bonus points added on top of a tier base.
    "bonuses": {
        "stack_multiplier": 2.0,
        "stack_max": 10.0,
        "complexity_max": 5.0,
        "metric_max": 5.0,
    },
    # Keyword floor: how many DISTINCT high-specificity signals are required
    # before the floor overrides a low LLM tier.
    "keyword_floor": {
        "enabled": True,
        "min_signals": 2,
    },
    # Skill-tag keywords count at this fraction of an in-work-history mention,
    # so tag stuffing cannot inflate the stack bonus.
    "tag_weight_factor": 0.4,
    # Engineering maturity: M_Eng = backend + database + frontend, capped.
    "engineering": {
        "cap": 0.7,
        "backend": {"0": 0.0, "1": 0.10, "2": 0.20, "3": 0.35},
        "database": {"0": 0.0, "1": 0.05, "2": 0.12, "3": 0.20},
        "frontend": {"0": 0.0, "1": 0.02, "2": 0.05, "3": 0.15},
    },
    # Education: school tier points, major relevance points, normalisation.
    "education": {
        "school_points": {"S": 15.0, "A": 10.0, "B": 5.0, "C": 2.0, "D": 0.0},
        # User-defined school→tier assignments, checked BEFORE the built-in
        # patterns in education.py so an operator can promote or demote any
        # institution without a code change. Each entry is
        # {"pattern": "<school name or fragment>", "tier": "A"|"B"|"C"|"D"}.
        # Matching is case-insensitive substring, NFKC-normalised, and the
        # FIRST match wins — so order the list most-specific first.
        "school_overrides": [],
        "major_points": {"Tier1": 10.0, "Tier2": 3.0, "Other": 0.0},
        "bachelor_weight": 0.7,      # when a graduate degree exists
        "master_weight": 0.3,
        "bachelor_only_weight": 0.9,  # when there is no graduate degree
        "denominator": 24.0,
        "base_cap": 95.0,
        "thesis_ai_bonus": 2.5,
        "thesis_venue_bonus": 2.5,
    },
    # Skill verification: ecosystem base score and penalties for unsupported
    # claims.
    "skills": {
        "ecosystem_scores": {
            "LLM Stack": 90,
            "Deep Learning": 70,
            "Traditional ML": 50,
            "General": 30,
        },
        "penalty_unsupported": 5.0,   # claimed, no evidence anywhere
        "penalty_portfolio_only": 2.0,  # evidenced only outside work history
        "penalty_keyword_stuffing": 5.0,
        "floor": 10.0,
    },
    # Semantic similarity rescaling. Raw cosines cluster in a narrow band, so
    # they are stretched into [0,1] before the weight is applied.
    "semantic": {
        "rescale_low": 0.45,
        "rescale_high": 0.80,
    },
}

_lock = threading.Lock()
_cache: dict[str, Any] | None = None


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` onto a copy of ``base``."""
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def validate(cfg: dict) -> list[str]:
    """Return a list of human-readable problems with ``cfg``. Empty == valid."""
    errors: list[str] = []

    w = cfg.get("weights", {})
    if not w:
        errors.append("weights: 缺少權重設定")
    else:
        for k, v in w.items():
            if not isinstance(v, (int, float)) or v < 0:
                errors.append(f"weights.{k}: 必須是 >= 0 的數字")
        total = sum(v for v in w.values() if isinstance(v, (int, float)))
        if abs(total - 1.0) > 1e-6:
            errors.append(f"weights: 總和必須為 1.0（目前 {round(total, 4)}）")

    tiers = cfg.get("tiers", {})
    ordered = []
    for key in sorted(tiers, key=lambda x: int(x)):
        t = tiers[key]
        base, cap = t.get("base"), t.get("bonus_cap")
        if not isinstance(base, (int, float)) or not 0 <= base <= 100:
            errors.append(f"tiers.{key}.base: 必須介於 0-100")
            continue
        if not isinstance(cap, (int, float)) or cap < 0:
            errors.append(f"tiers.{key}.bonus_cap: 必須 >= 0")
            continue
        ordered.append((int(key), base, base + cap))
    # Bands must not overlap, otherwise a strong low tier outranks a high one.
    for (t1, _b1, top1), (t2, b2, _top2) in zip(ordered, ordered[1:]):
        # >= because a tier topping out at exactly the next tier's base makes the
        # two indistinguishable at the boundary — the original overlap bug.
        if top1 >= b2:
            errors.append(
                f"tiers: Tier {t1} 上限 {top1} 觸及 Tier {t2} 起始 {b2}，"
                "區間重疊會讓低層級候選人贏過高層級"
            )

    eng = cfg.get("engineering", {})
    if not isinstance(eng.get("cap"), (int, float)) or eng.get("cap", 0) <= 0:
        errors.append("engineering.cap: 必須 > 0")

    sem = cfg.get("semantic", {})
    if sem.get("rescale_high", 1) <= sem.get("rescale_low", 0):
        errors.append("semantic: rescale_high 必須大於 rescale_low")

    edu = cfg.get("education", {})
    overrides = edu.get("school_overrides", [])
    if not isinstance(overrides, list):
        errors.append("education.school_overrides: 必須是清單")
    else:
        valid_tiers = set(cfg.get("education", {}).get("school_points", {}))
        for i, row in enumerate(overrides):
            if not isinstance(row, dict):
                errors.append(f"education.school_overrides[{i}]: 必須是物件")
                continue
            pattern = str(row.get("pattern", "")).strip()
            tier = str(row.get("tier", "")).strip()
            if not pattern:
                errors.append(f"education.school_overrides[{i}]: 學校名稱不可空白")
            if tier not in valid_tiers:
                errors.append(
                    f"education.school_overrides[{i}]: 等級必須是 "
                    f"{'/'.join(sorted(valid_tiers))} 之一（目前 {tier or '空白'}）"
                )

    kf = cfg.get("keyword_floor", {})
    if not isinstance(kf.get("min_signals"), int) or kf.get("min_signals", 0) < 1:
        errors.append("keyword_floor.min_signals: 必須是 >= 1 的整數")

    return errors


def load(force: bool = False) -> dict[str, Any]:
    """Return the active config, reading from disk on first use."""
    global _cache
    with _lock:
        if _cache is not None and not force:
            return _cache

        cfg = copy.deepcopy(DEFAULTS)
        if CONFIG_PATH.exists():
            try:
                raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                merged = _deep_merge(DEFAULTS, raw)
                problems = validate(merged)
                if problems:
                    logger.error(
                        "scoring_config.json 驗證失敗，改用預設值: %s", "; ".join(problems)
                    )
                else:
                    cfg = merged
            except Exception as e:
                logger.error("讀取 %s 失敗，改用預設值: %s", CONFIG_PATH, e)

        _cache = cfg
        return _cache


def save(new_cfg: dict) -> dict:
    """Validate and persist a config. Raises ValueError on invalid input."""
    merged = _deep_merge(DEFAULTS, new_cfg)
    problems = validate(merged)
    if problems:
        raise ValueError("; ".join(problems))

    global _cache
    with _lock:
        CONFIG_PATH.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _cache = merged
    return merged


def reset() -> dict:
    """Restore defaults, removing any on-disk override."""
    global _cache
    with _lock:
        if CONFIG_PATH.exists():
            CONFIG_PATH.unlink()
        _cache = copy.deepcopy(DEFAULTS)
    return _cache


def config_version() -> str:
    """Short hash of the active config.

    Mixed into the LLM tier cache key so that changing the knobs invalidates
    previously cached scores instead of silently serving stale numbers.
    """
    payload = json.dumps(load(), ensure_ascii=False, sort_keys=True)
    return hashlib.md5(payload.encode()).hexdigest()[:12]


# --- Typed accessors used by the scoring modules ---------------------------

def weights() -> dict[str, float]:
    return load()["weights"]


def tier_base_scores() -> dict[int, float]:
    return {int(k): v["base"] for k, v in load()["tiers"].items()}


def tier_bonus_caps() -> dict[int, float]:
    return {int(k): v["bonus_cap"] for k, v in load()["tiers"].items()}


def tier_labels() -> dict[int, str]:
    return {int(k): v.get("label", "") for k, v in load()["tiers"].items()}
