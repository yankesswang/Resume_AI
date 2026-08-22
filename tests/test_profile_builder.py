"""Generation safeguards for JD-derived screening standards."""

import copy
import json
import sqlite3
from types import SimpleNamespace

from app.scoring.domain_profile import DomainProfile
from app.scoring.generic import classify_tier_by_profile
from app.scoring.pipeline import _apply_domain_relevance_cap, _classify_tier_by_profile
from app.scoring.profile_builder import _repair, generate_domain_profile
from app.llm import build_tier_prompt


def _job(requirements=None, preferred=None):
    return {
        "basic_conditions": {"job_title": "資料工程師"},
        "requirements": requirements or {},
        "preferred_qualifications": preferred or [],
    }


def test_generated_hard_filters_are_grounded_only_in_required_conditions():
    raw = {
        "hard_filters": {
            "must_have_groups": [{
                "name": "技術門檻",
                "skills": ["Python", "Kubernetes", "Go"],
                "min_matches": 2,
            }],
            "min_education": "master",
            "min_school_tier": "A",
        }
    }
    job = _job(
        requirements={"education": "大學以上", "skills": ["Python"]},
        preferred=["具 Kubernetes 經驗尤佳"],
    )

    out = _repair(raw, job, enforce_grounding=True)["hard_filters"]

    assert out["must_have_groups"] == [
        {"name": "技術門檻", "skills": ["Python"], "min_matches": 1}
    ]
    assert out["min_education"] == "bachelor"
    assert out["min_school_tier"] == ""


def test_responsibilities_and_preferences_never_become_hard_filters():
    raw = {
        "hard_filters": {
            "must_have_groups": [{
                "name": "模型猜測",
                "skills": ["Airflow", "Kubernetes"],
                "min_matches": 1,
            }]
        }
    }
    job = _job(requirements={"skills": []}, preferred=["Kubernetes 加分"])
    job["responsibilities"] = [{"category": "工作內容", "items": ["維護 Airflow"]}]

    out = _repair(raw, job, enforce_grounding=True)["hard_filters"]

    assert out["must_have_groups"] == []


def test_grounding_handles_multiword_skills_without_substring_false_positives():
    raw = {
        "hard_filters": {
            "must_have_groups": [{
                "name": "技術",
                "skills": ["machine learning", "Go"],
                "min_matches": 1,
            }]
        }
    }
    job = _job(requirements={"skills": ["Machine  Learning", "Google Cloud"]})

    out = _repair(raw, job, enforce_grounding=True)["hard_filters"]

    assert out["must_have_groups"][0]["skills"] == ["machine learning"]


def test_prose_experience_and_language_requirements_are_not_literal_gates():
    raw = {
        "hard_filters": {
            "must_have_groups": [
                {
                    "name": "產業經歷",
                    "skills": ["PC or IT related industry experience"],
                    "min_matches": 1,
                },
                {
                    "name": "語言",
                    "skills": ["English: 精通"],
                    "min_matches": 1,
                },
            ]
        }
    }
    job = _job(requirements={
        "skills": ["PC or IT related industry experience"],
        "languages": ["English: 精通"],
    })

    out = _repair(raw, job, enforce_grounding=True)["hard_filters"]

    assert out["must_have_groups"] == []


def test_duplicate_and_out_of_range_tier_signals_are_repaired():
    raw = {
        "tier_keywords": {
            "1": {"Python": 0.1, "SQL": 1.0},
            "2": {"python": 1.8, "ETL": 9},
            "3": {"PYTHON": 2.2, "資料平台架構": 2.0},
        }
    }

    tiers = _repair(raw, {})["tier_keywords"]

    assert tiers["1"]["Python"] == 0.5
    assert "python" not in tiers["2"]
    assert "PYTHON" not in tiers["3"]
    assert tiers["2"]["ETL"] == 2.5


def test_ecosystem_scores_are_clamped_to_prompt_contract():
    raw = {
        "ecosystems": [
            {"name": "專家技能", "score": 95, "keywords": ["RLHF"]},
            {"name": "基礎技能", "score": -5, "keywords": ["Python"]},
        ]
    }

    ecosystems = _repair(raw, {})["ecosystems"]

    assert ecosystems[0]["score"] == 90.0
    assert ecosystems[1]["score"] == 30.0


def test_generic_degree_gate_does_not_create_school_prestige_ranking():
    raw = {
        "education": {
            "matters": True,
            "tier1_majors": ["工商管理學系"],
            "tier2_majors": [],
        }
    }
    job = _job(requirements={"education": "大學", "majors": []})

    education = _repair(raw, job, enforce_grounding=True)["education"]

    assert education["matters"] is False


def test_explicit_required_major_keeps_education_ranking_enabled():
    raw = {
        "education": {
            "matters": True,
            "tier1_majors": ["會計學系"],
            "tier2_majors": [],
        }
    }
    job = _job(requirements={"education": "大學", "majors": ["會計學系"]})

    education = _repair(raw, job, enforce_grounding=True)["education"]

    assert education["matters"] is True


def _valid_generated_profile():
    return {
        "domain": "資料工程",
        "summary": "建立可靠的資料管線",
        "tiers": [
            {"level": level, "label": f"L{level}", "definition": f"等級 {level} 證據"}
            for level in range(4)
        ],
        "tier_keywords": {
            "1": {"entry-0": 1.0, "entry-1": 1.0,
                  "入門訊號一": 1.0, "入門訊號二": 1.0},
            "2": {"mid-0": 1.5, "mid-1": 1.5,
                  "進階訊號一": 1.5, "進階訊號二": 1.5},
            "3": {"expert-0": 2.0, "expert-1": 2.0,
                  "專家訊號一": 2.0, "專家訊號二": 2.0},
        },
        "competencies": [{
            "key": "pipeline",
            "label": "資料管線",
            "weight": 1.0,
            "levels": {
                "1": ["批次處理"],
                "2": ["資料建模"],
                "3": ["平台架構"],
            },
        }],
        "education": {"matters": False, "tier1_majors": [], "tier2_majors": []},
        "ecosystems": [],
        "hard_filters": {"must_have_groups": []},
        "weights": {
            "experience": 0.4,
            "engineering": 0.25,
            "semantic": 0.2,
            "education": 0.05,
            "skills": 0.1,
        },
    }


def test_generation_retries_once_when_quality_validation_fails(monkeypatch):
    invalid = copy.deepcopy(_valid_generated_profile())
    invalid["tier_keywords"]["2"] = {"only-one": 1.5}
    replies = iter((json.dumps(invalid), json.dumps(_valid_generated_profile())))
    calls = []

    def fake_chat(messages, **kwargs):
        calls.append(messages)
        return next(replies)

    monkeypatch.setattr("app.llm._chat", fake_chat)

    profile, errors = generate_domain_profile(_job())

    assert errors == []
    assert len(calls) == 2
    assert len(profile.tier_keywords["2"]) == 4
    assert "品質檢查錯誤" in calls[1][1]["content"]


def test_valid_generation_uses_single_llm_call(monkeypatch):
    calls = []

    def fake_chat(messages, **kwargs):
        calls.append(messages)
        return json.dumps(_valid_generated_profile())

    monkeypatch.setattr("app.llm._chat", fake_chat)

    _, errors = generate_domain_profile(_job())

    assert errors == []
    assert len(calls) == 1


def test_english_only_generated_profile_triggers_bilingual_correction(monkeypatch):
    english_only = copy.deepcopy(_valid_generated_profile())
    english_only["tier_keywords"] = {
        "1": {f"entry-{i}": 1.0 for i in range(4)},
        "2": {f"mid-{i}": 1.5 for i in range(4)},
        "3": {f"expert-{i}": 2.0 for i in range(4)},
    }
    replies = iter((json.dumps(english_only), json.dumps(_valid_generated_profile())))
    calls = []

    def fake_chat(messages, **kwargs):
        calls.append(messages)
        return next(replies)

    monkeypatch.setattr("app.llm._chat", fake_chat)

    _, errors = generate_domain_profile(_job())

    assert errors == []
    assert len(calls) == 2
    assert "繁體中文關鍵字" in calls[1][1]["content"]


def test_chinese_only_generated_profile_triggers_bilingual_correction(monkeypatch):
    chinese_only = copy.deepcopy(_valid_generated_profile())
    chinese_only["tier_keywords"] = {
        "1": {f"入門訊號{i}": 1.0 for i in range(4)},
        "2": {f"進階訊號{i}": 1.5 for i in range(4)},
        "3": {f"專家訊號{i}": 2.0 for i in range(4)},
    }
    replies = iter((json.dumps(chinese_only), json.dumps(_valid_generated_profile())))
    calls = []

    def fake_chat(messages, **kwargs):
        calls.append(messages)
        return next(replies)

    monkeypatch.setattr("app.llm._chat", fake_chat)

    _, errors = generate_domain_profile(_job())

    assert errors == []
    assert len(calls) == 2
    assert "英文關鍵字" in calls[1][1]["content"]


def test_single_intermediate_keyword_only_proves_entry_depth():
    profile = DomainProfile.model_validate(_valid_generated_profile())

    detail = classify_tier_by_profile(profile, [], [], "mid-0")

    assert detail.tier == 1


def test_generated_profile_keywords_do_not_override_successful_llm(monkeypatch):
    raw = _valid_generated_profile()
    raw["source"] = "llm"
    profile = DomainProfile.model_validate(raw)
    monkeypatch.setattr(
        "app.llm.classify_domain_tier",
        lambda *args, **kwargs: {"tier": 1, "confidence": 0.8, "reasoning": "entry"},
    )

    cache = sqlite3.connect(":memory:")
    cache.row_factory = sqlite3.Row
    cache.execute(
        """CREATE TABLE candidates (
            id INTEGER PRIMARY KEY,
            llm_tier INTEGER,
            llm_tier_reasoning TEXT,
            llm_tier_md5 TEXT,
            llm_tier_prompt_md5 TEXT
        )"""
    )
    cache.execute("INSERT INTO candidates(id) VALUES (1)")
    try:
        detail = _classify_tier_by_profile(
            profile, [], [], "expert-0 expert-1", 1, cache
        )
    finally:
        cache.close()

    assert detail.tier == 1
    assert detail.tier_source == "llm"


def test_domain_tier_prompt_counts_internships_and_projects_as_evidence():
    profile = DomainProfile.model_validate(_valid_generated_profile())

    prompt = build_tier_prompt(profile)

    assert "實習" in prompt
    assert "論文" in prompt
    assert "個人專案" in prompt
    assert "判定 Tier 0 前" in prompt
    assert "confidence >= 0.8" in prompt


def test_confirmed_tier_zero_cannot_enter_viable_fit_range():
    detail = SimpleNamespace(tier=0, tier_source="llm")

    assert _apply_domain_relevance_cap(61.0, object(), detail) == 45.0


def test_keyword_fallback_tier_zero_is_not_hard_capped():
    detail = SimpleNamespace(tier=0, tier_source="keyword")

    assert _apply_domain_relevance_cap(61.0, object(), detail) == 61.0
