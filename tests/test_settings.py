"""Configuration validation.

``Settings`` is what stands between a misconfigured deploy and thousands of real
applicants' PII being served to the open internet, so the fatal/non-fatal split
is worth pinning down precisely.

Every test builds a fresh ``Settings()`` under a controlled environment rather
than using the module-level singleton, which is cached by ``lru_cache`` and
already bound to whatever the process started with.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.settings import ROOT_DIR, Settings, _load_dotenv, get_settings


@pytest.fixture
def clean_env(monkeypatch):
    """Strip every setting-bearing variable so defaults are what is under test."""
    for var in (
        "AUTH_ENABLED", "API_KEYS", "READONLY_API_KEYS", "AUTH_HEADER",
        "CORS_ORIGINS", "MAX_UPLOAD_BYTES", "DB_PATH", "RETENTION_DAYS",
        "AUDIT_ENABLED", "PHOTO_ROOT", "MODEL_CONTEXT_LENGTH", "ENV_FILE",
    ):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


# ---------------------------------------------------------------------------
# validate() — fatal misconfiguration
# ---------------------------------------------------------------------------
def test_auth_enabled_without_any_key_is_fatal(clean_env):
    """Auth on with no keys would reject 100% of traffic — refuse to start."""
    clean_env.setenv("AUTH_ENABLED", "true")
    clean_env.setenv("CORS_ORIGINS", "https://hr.example.com")
    errors = Settings().validate()
    assert any("API_KEYS" in e for e in errors), errors


def test_auth_enabled_with_readonly_key_only_is_valid(clean_env):
    """A read-only key alone is a legitimate deployment (dashboards)."""
    clean_env.setenv("AUTH_ENABLED", "true")
    clean_env.setenv("READONLY_API_KEYS", "ro-key")
    clean_env.setenv("CORS_ORIGINS", "https://hr.example.com")
    assert Settings().validate() == []


def test_wildcard_cors_rejected_when_auth_enabled(clean_env):
    """`*` + credentials means any site can drive the API from a victim's browser."""
    clean_env.setenv("AUTH_ENABLED", "true")
    clean_env.setenv("API_KEYS", "secret")
    clean_env.setenv("CORS_ORIGINS", "*")
    errors = Settings().validate()
    assert any("CORS_ORIGINS" in e for e in errors), errors


def test_wildcard_cors_allowed_when_auth_disabled(clean_env):
    """Local dev default must keep working untouched."""
    clean_env.setenv("AUTH_ENABLED", "false")
    clean_env.setenv("CORS_ORIGINS", "*")
    assert Settings().validate() == []


def test_explicit_cors_origins_accepted_with_auth(clean_env):
    clean_env.setenv("AUTH_ENABLED", "true")
    clean_env.setenv("API_KEYS", "k1,k2")
    clean_env.setenv("CORS_ORIGINS", "https://a.example.com,https://b.example.com")
    s = Settings()
    assert s.validate() == []
    assert s.cors_origins == ("https://a.example.com", "https://b.example.com")


def test_non_positive_upload_limit_is_fatal(clean_env):
    clean_env.setenv("MAX_UPLOAD_BYTES", "0")
    assert any("MAX_UPLOAD_BYTES" in e for e in Settings().validate())


# ---------------------------------------------------------------------------
# warnings() — non-fatal but loud
# ---------------------------------------------------------------------------
def test_warns_when_auth_disabled(clean_env):
    clean_env.setenv("AUTH_ENABLED", "false")
    warnings = Settings().warnings()
    assert any("AUTH_ENABLED=false" in w for w in warnings), warnings
    assert any("PII" in w for w in warnings), warnings


def test_no_auth_warning_when_auth_enabled(clean_env):
    clean_env.setenv("AUTH_ENABLED", "true")
    clean_env.setenv("API_KEYS", "secret")
    clean_env.setenv("CORS_ORIGINS", "https://hr.example.com")
    assert not any("AUTH_ENABLED=false" in w for w in Settings().warnings())


def test_warns_on_wildcard_cors_even_when_not_fatal(clean_env):
    clean_env.setenv("AUTH_ENABLED", "false")
    clean_env.setenv("CORS_ORIGINS", "*")
    assert any("CORS_ORIGINS" in w for w in Settings().warnings())


def test_warns_when_photo_root_is_project_root(clean_env):
    clean_env.delenv("PHOTO_ROOT", raising=False)
    s = Settings()
    if s.photo_root == ROOT_DIR:
        assert any("PHOTO_ROOT" in w for w in s.warnings())


# ---------------------------------------------------------------------------
# Precedence: real env beats .env file
# ---------------------------------------------------------------------------
def test_real_env_var_beats_dotenv_value(tmp_path, clean_env):
    """A stale .env in the working copy must never override the deploy's env."""
    env_file = tmp_path / ".env"
    env_file.write_text("MODEL_CONTEXT_LENGTH=4096\nAUTH_HEADER=X-From-Dotenv\n", encoding="utf-8")

    clean_env.setenv("MODEL_CONTEXT_LENGTH", "32768")  # already exported
    _load_dotenv(env_file)

    import os

    assert os.environ["MODEL_CONTEXT_LENGTH"] == "32768"  # env wins
    assert os.environ["AUTH_HEADER"] == "X-From-Dotenv"   # unset -> .env fills in
    assert Settings().model_context_length == 32768


def test_dotenv_ignores_comments_and_blank_lines(tmp_path, clean_env):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n# a comment\n\nAUTH_HEADER='X-Quoted'\nNOT_A_PAIR\n", encoding="utf-8"
    )
    _load_dotenv(env_file)

    import os

    assert os.environ["AUTH_HEADER"] == "X-Quoted"  # quotes stripped


def test_missing_dotenv_is_not_an_error(tmp_path):
    _load_dotenv(tmp_path / "does_not_exist.env")  # must not raise


# ---------------------------------------------------------------------------
# Type coercion
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
    ("0", False), ("false", False), ("no", False), ("", False), ("maybe", False),
])
def test_bool_parsing(clean_env, raw, expected):
    clean_env.setenv("AUTH_ENABLED", raw)
    assert Settings().auth_enabled is expected


def test_invalid_int_falls_back_to_default(clean_env):
    """A typo'd number must not crash startup; the documented default applies."""
    clean_env.setenv("MODEL_CONTEXT_LENGTH", "not-a-number")
    assert Settings().model_context_length == 32768


def test_csv_parsing_strips_whitespace_and_empties(clean_env):
    clean_env.setenv("API_KEYS", " a , ,b,  ")
    assert Settings().api_keys == ("a", "b")


def test_get_settings_is_cached():
    assert get_settings() is get_settings()
