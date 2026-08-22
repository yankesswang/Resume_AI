"""Runtime LLM provider configuration.

The app was wired to exactly one backend: LM Studio on localhost, addressed by
three module-level constants read from the environment at import time. Pointing
it at OpenAI — or at a different local model — meant editing ``.env`` and
restarting, on the machine holding the process. This module makes the provider
an operator setting instead, editable from ``/llm-settings``.

Design rules, mirroring ``app.scoring.config``:

- ``DEFAULTS`` is the authoritative schema *and* the fallback.
- A stored document only carries the keys it overrides.
- Every value is validated on load; a bad document degrades to defaults with a
  warning rather than taking the API down.
- The environment still wins where it is set, so existing deployments,
  ``scripts/`` and the tests keep the behaviour they have today.

Two independent sections — ``chat`` (extraction, tier classification, profile
generation) and ``embedding`` (semantic similarity). They are separate because
the useful combination is real: a local chat model with OpenAI embeddings, or
the reverse, depending on which GPU is busy. Folding them into one provider
switch would force one of those to be wrong.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

# Provider identifiers. "lmstudio" covers any OpenAI-compatible local server
# (LM Studio, Ollama, vLLM, llama.cpp) — the wire format is identical and the
# only real difference is whether an API key is required.
PROVIDER_LMSTUDIO = "lmstudio"
PROVIDER_OPENAI = "openai"
PROVIDERS = (PROVIDER_LMSTUDIO, PROVIDER_OPENAI)

SETTING_KEY = "llm_config"

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_EMBEDDING_URL = "https://api.openai.com/v1/embeddings"

# --- Model catalogue --------------------------------------------------------
# A cloud provider routes on the model name, so "which model" is a *choice from
# a list* there, not free text — and an operator who mistypes "gpt-4o-mini" as
# "gpt4o-mini" learns about it from a 404 during a scoring run rather than from
# the settings page. The catalogue turns that field into a picker.
#
# It is a suggestion list, never a whitelist: `validate()` does not check the
# model against it. OpenAI ships new names faster than this file is edited, and
# a settings page that refused a model the API accepts would be worse than one
# that lets a typo through. The UI keeps the free-text field alongside the
# dropdown for exactly that case.
#
# The local list serves a different purpose from the cloud one. LM Studio runs
# whichever model the operator has downloaded, so this cannot be an authoritative
# list of what is available on their machine — it is a set of *reference
# formats*, showing the shape LM Studio's own identifiers take
# ("qwen2.5-7b-instruct", vendor-prefixed and size-tagged) so someone copying a
# name out of the LM Studio UI can see whether theirs looks right. That is why
# the local entries name the family rather than promising the exact file, and
# why blank ("use whatever is loaded") stays the first option.

MODEL_CATALOGUE: dict[str, dict[str, list[dict[str, str]]]] = {
    PROVIDER_OPENAI: {
        "chat": [
            {
                "value": "gpt-4o-mini",
                "label": "GPT-4o mini",
                "description": "便宜快速，適合大量履歷分級。預設建議。",
            },
            {
                "value": "gpt-4o",
                "label": "GPT-4o",
                "description": "判斷較穩，成本約 GPT-4o mini 的十倍以上。",
            },
            {
                "value": "gpt-4.1-mini",
                "label": "GPT-4.1 mini",
                "description": "長 context，適合完整履歷原文輸入。",
            },
            {
                "value": "gpt-4.1",
                "label": "GPT-4.1",
                "description": "長 context 的完整版本。",
            },
            {
                "value": "o4-mini",
                "label": "o4-mini",
                "description": "推理型模型，分級邊界案例較準，但回應較慢。",
            },
        ],
        "embedding": [
            {
                "value": "text-embedding-3-small",
                "label": "text-embedding-3-small",
                "description": "1536 維，語意相似度的預設建議。",
            },
            {
                "value": "text-embedding-3-large",
                "label": "text-embedding-3-large",
                "description": "3072 維，較準也較貴。",
            },
        ],
    },
    PROVIDER_LMSTUDIO: {
        "chat": [
            {
                "value": "qwen2.5-7b-instruct",
                "label": "Qwen2.5 7B Instruct",
                "description": "中文履歷表現穩定，8GB 顯卡跑得動，地端首選。",
            },
            {
                "value": "qwen2.5-14b-instruct",
                "label": "Qwen2.5 14B Instruct",
                "description": "分級判斷比 7B 準，約需 12GB 以上顯存。",
            },
            {
                "value": "qwen3-8b",
                "label": "Qwen3 8B",
                "description": "支援 thinking 模式，地端路徑會送出該參數。",
            },
            {
                "value": "llama-3.1-8b-instruct",
                "label": "Llama 3.1 8B Instruct",
                "description": "英文履歷為主時的常見選擇。",
            },
            {
                "value": "gemma-2-9b-it",
                "label": "Gemma 2 9B IT",
                "description": "體積小、載入快，適合先跑通流程。",
            },
        ],
        "embedding": [
            {
                "value": "text-embedding-nomic-embed-text-v1.5",
                "label": "nomic-embed-text v1.5",
                "description": "地端常用的 embedding 模型，LM Studio / Ollama 皆有。",
            },
            {
                "value": "text-embedding-bge-m3",
                "label": "BGE-M3",
                "description": "多語系表現好，中文履歷可優先考慮。",
            },
        ],
    },
}


def model_catalogue() -> dict[str, dict[str, list[dict[str, str]]]]:
    """Suggested model names per provider and section, for the settings UI.

    Returned as a copy: the settings page renders it, and a caller mutating the
    module-level table would change what every later request is offered.
    """
    return copy.deepcopy(MODEL_CATALOGUE)


def default_model(provider_name: str, section: str) -> str:
    """What to pre-fill when a provider switch invalidates the current model.

    Switching to OpenAI with a blank model is invalid (validation requires one),
    so the UI pre-fills a name rather than presenting a form that cannot be
    saved until the operator guesses one.

    A local chat model is the exception and returns blank even though the
    catalogue now lists names: blank means "use whatever LM Studio has loaded",
    which is both valid and right far more often than any particular name would
    be. Those entries are reference formats for someone typing their own, not a
    claim about what is installed — pre-selecting one would name a model the
    operator may not have downloaded.
    """
    if provider_name == PROVIDER_LMSTUDIO and section == "chat":
        return ""
    entries = MODEL_CATALOGUE.get(provider_name, {}).get(section) or []
    return entries[0]["value"] if entries else ""


DEFAULTS: dict[str, Any] = {
    "chat": {
        "provider": PROVIDER_LMSTUDIO,
        # Empty base_url means "use the provider's own default", which keeps a
        # provider switch to one click instead of also demanding a URL.
        "base_url": "",
        # Empty model means "whatever LM Studio currently has loaded". OpenAI
        # has no such notion, so validation requires a model name there.
        "model": "",
        "api_key": "",
        "context_length": 32768,
        "response_tokens": 2048,
        "timeout": 300,
    },
    "embedding": {
        "provider": PROVIDER_LMSTUDIO,
        "base_url": "",
        "model": "text-embedding-nomic-embed-text-v1.5",
        "api_key": "",
        "timeout": 10,
    },
}

# Fields whose value must never leave the process in clear text.
SECRET_FIELDS = ("api_key",)
# What a stored key looks like on the way out. Not an empty string: an emptied
# field makes "no key configured" and "key withheld" indistinguishable, and the
# operator needs to tell those apart before debugging a 401.
MASK = "••••"

_lock = threading.Lock()
_cache: dict[str, Any] | None = None


# --- Environment overrides --------------------------------------------------
# Precedence is environment > stored document > default, matching app/settings.py.
# A deployment that sets LM_STUDIO_URL in its systemd unit must not have that
# silently overridden by a row someone saved in the UI months ago; the UI
# reports which fields are env-pinned so the operator sees why an edit is inert.

_ENV_MAP = {
    ("chat", "base_url"): "LM_STUDIO_URL",
    ("chat", "model"): "LM_STUDIO_MODEL",
    ("chat", "context_length"): "MODEL_CONTEXT_LENGTH",
    ("chat", "response_tokens"): "RESPONSE_TOKENS",
    ("embedding", "base_url"): "EMBEDDING_URL",
    ("embedding", "model"): "EMBEDDING_MODEL",
    # No env var for provider/api_key of the local path: OPENAI_API_KEY below
    # is handled separately because it applies to whichever section is set to
    # the OpenAI provider.
}

_INT_FIELDS = {"context_length", "response_tokens", "timeout"}


def env_pinned() -> dict[str, list[str]]:
    """Which fields the environment is currently overriding, per section.

    Rendered by the settings page so an ignored edit is visibly ignored rather
    than appearing to save and then doing nothing.
    """
    pinned: dict[str, list[str]] = {"chat": [], "embedding": []}
    for (section, field), env_name in _ENV_MAP.items():
        raw = os.environ.get(env_name)
        if raw is not None and raw.strip():
            pinned[section].append(field)
    return pinned


def _apply_env(cfg: dict[str, Any]) -> dict[str, Any]:
    """Overlay environment variables onto a resolved config."""
    out = copy.deepcopy(cfg)
    for (section, field), env_name in _ENV_MAP.items():
        raw = os.environ.get(env_name)
        if raw is None or not raw.strip():
            continue
        value: Any = raw.strip()
        if field in _INT_FIELDS:
            try:
                value = int(value)
            except ValueError:
                logger.warning("%s=%r is not an integer — ignoring", env_name, raw)
                continue
        out[section][field] = value

    # OPENAI_API_KEY applies to any section running on OpenAI, so that the
    # standard variable works without being re-typed into the UI.
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if openai_key:
        for section in ("chat", "embedding"):
            if out[section]["provider"] == PROVIDER_OPENAI and not out[section]["api_key"]:
                out[section]["api_key"] = openai_key
    return out


# --- Validation -------------------------------------------------------------

def validate(cfg: dict[str, Any]) -> list[str]:
    """Return human-readable problems with ``cfg``. Empty list == valid."""
    errors: list[str] = []

    for section, label in (("chat", "對話模型"), ("embedding", "Embedding 模型")):
        sec = cfg.get(section)
        if not isinstance(sec, dict):
            errors.append(f"{section}: 缺少設定區塊")
            continue

        provider = sec.get("provider")
        if provider not in PROVIDERS:
            errors.append(
                f"{label}: 服務商必須是 {' 或 '.join(PROVIDERS)}（目前 {provider!r}）"
            )
            continue

        base_url = str(sec.get("base_url", "") or "").strip()
        if base_url and not base_url.startswith(("http://", "https://")):
            errors.append(f"{label}: 網址必須以 http:// 或 https:// 開頭")

        model = str(sec.get("model", "") or "").strip()
        # LM Studio serves whichever model is loaded, so a blank model is a
        # legitimate "use the loaded one". OpenAI routes on the model name, so
        # a blank one there is a request that always 400s.
        if provider == PROVIDER_OPENAI and not model:
            errors.append(f"{label}: 使用 OpenAI 時必須指定模型名稱")
        # An embedding request has no "currently loaded" fallback in practice —
        # every server we target requires the field.
        if section == "embedding" and not model:
            errors.append(f"{label}: 必須指定模型名稱")

        for field in ("context_length", "response_tokens", "timeout"):
            if field not in sec:
                continue
            value = sec[field]
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                errors.append(f"{label}: {field} 必須是正整數")

    chat = cfg.get("chat", {})
    if isinstance(chat, dict):
        ctx = chat.get("context_length")
        reserved = chat.get("response_tokens")
        if isinstance(ctx, int) and isinstance(reserved, int) and reserved >= ctx:
            # _truncate_to_fit subtracts one from the other; if the remainder is
            # negative every resume collapses to the 500-char floor and scoring
            # silently reads almost nothing.
            errors.append(
                f"對話模型: response_tokens ({reserved}) 必須小於 "
                f"context_length ({ctx})，否則履歷內容會被截斷到只剩幾百字"
            )

    return errors


# --- Load / save ------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_stored() -> dict[str, Any]:
    """Read the stored document, tolerating a DB that predates the table."""
    try:
        from app.database import get_app_setting

        raw = get_app_setting(SETTING_KEY)
    except Exception as e:  # pragma: no cover - DB unavailable at import time
        logger.warning("讀取 LLM 設定失敗，改用預設值: %s", e)
        return {}
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("LLM 設定 JSON 損毀，改用預設值: %s", e)
        return {}
    return parsed if isinstance(parsed, dict) else {}


def load(force: bool = False) -> dict[str, Any]:
    """Return the active config: defaults < stored document < environment."""
    global _cache
    with _lock:
        if _cache is not None and not force:
            return _cache

        cfg = copy.deepcopy(DEFAULTS)
        stored = _read_stored()
        if stored:
            merged = _deep_merge(DEFAULTS, stored)
            problems = validate(merged)
            if problems:
                logger.error(
                    "儲存的 LLM 設定驗證失敗，改用預設值: %s", "; ".join(problems)
                )
            else:
                cfg = merged

        _cache = _apply_env(cfg)
        return _cache


def save(new_cfg: dict[str, Any]) -> dict[str, Any]:
    """Validate and persist a config. Raises ValueError on invalid input.

    A masked secret means "keep what is stored": the UI never receives the real
    key, so echoing back what it was shown must not overwrite the stored value
    with four bullet characters.
    """
    stored = _read_stored()
    incoming = copy.deepcopy(new_cfg or {})
    for section in ("chat", "embedding"):
        sec = incoming.get(section)
        if not isinstance(sec, dict):
            continue
        for field in SECRET_FIELDS:
            if field not in sec:
                continue
            value = sec[field]
            if value == MASK or (isinstance(value, str) and set(value.strip()) == {"•"}):
                previous = (stored.get(section) or {}).get(field)
                if previous is None:
                    sec.pop(field)
                else:
                    sec[field] = previous

    merged = _deep_merge(DEFAULTS, _deep_merge(stored, incoming))
    problems = validate(merged)
    if problems:
        raise ValueError("; ".join(problems))

    from app.database import set_app_setting

    global _cache
    with _lock:
        set_app_setting(SETTING_KEY, json.dumps(merged, ensure_ascii=False))
        _cache = _apply_env(merged)
    return _cache


def reset() -> dict[str, Any]:
    """Discard the stored document and return to defaults (+ environment)."""
    from app.database import set_app_setting

    global _cache
    with _lock:
        set_app_setting(SETTING_KEY, json.dumps({}, ensure_ascii=False))
        _cache = _apply_env(copy.deepcopy(DEFAULTS))
    return _cache


def config_version() -> str:
    """Short hash of the active config, secrets excluded.

    Mixed into the LLM tier cache key: a tier produced by a 7B local model and
    one produced by GPT-4o are not interchangeable, so switching provider must
    invalidate cached classifications the same way editing the prompt does.
    The key is excluded because rotating a credential does not change what the
    model answers.
    """
    payload = copy.deepcopy(load())
    for section in ("chat", "embedding"):
        sec = payload.get(section)
        if isinstance(sec, dict):
            # Dropped entirely rather than masked: masking still distinguishes
            # "a key is set" from "no key", so merely *adding* a credential
            # would invalidate every cached tier for no change in output.
            for field in SECRET_FIELDS:
                sec.pop(field, None)
    return hashlib.md5(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:12]


# --- Accessors used by the client modules ----------------------------------

def _section(name: str) -> dict[str, Any]:
    return load()[name]


def _default_url(provider: str, section: str) -> str:
    if provider == PROVIDER_OPENAI:
        return OPENAI_CHAT_URL if section == "chat" else OPENAI_EMBEDDING_URL
    return (
        "http://localhost:1234/v1/chat/completions"
        if section == "chat"
        else "http://localhost:1234/v1/embeddings"
    )


def endpoint(section: str) -> str:
    """Resolved URL for a section, filling in the provider's default."""
    sec = _section(section)
    url = str(sec.get("base_url", "") or "").strip()
    if not url:
        return _default_url(sec["provider"], section)
    # Accept a bare host ("http://192.168.0.84:1234") as well as a full path,
    # because that is what an operator copies out of LM Studio's UI.
    if "/v1/" not in url:
        suffix = "/v1/chat/completions" if section == "chat" else "/v1/embeddings"
        url = url.rstrip("/") + suffix
    return url


def headers(section: str) -> dict[str, str]:
    """Auth headers for a section. Local servers usually need none."""
    key = str(_section(section).get("api_key", "") or "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def provider(section: str) -> str:
    return _section(section)["provider"]


def model(section: str) -> str:
    return str(_section(section).get("model", "") or "").strip()


def timeout(section: str) -> float:
    return float(_section(section).get("timeout") or DEFAULTS[section]["timeout"])


def chat_context_length() -> int:
    return int(_section("chat")["context_length"])


def chat_response_tokens() -> int:
    return int(_section("chat")["response_tokens"])


def supports_thinking_toggle(section: str = "chat") -> bool:
    """Whether to send the LM Studio ``thinking`` payload field.

    Local servers accept unknown keys; the OpenAI API rejects the request with
    a 400 on an unrecognised body field, so the Qwen3 chain-of-thought switch
    must not be sent there.
    """
    return provider(section) == PROVIDER_LMSTUDIO


def redacted(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """A copy safe to serialise to the client: secrets replaced by a marker."""
    out = copy.deepcopy(cfg if cfg is not None else load())
    for section in ("chat", "embedding"):
        sec = out.get(section)
        if not isinstance(sec, dict):
            continue
        for field in SECRET_FIELDS:
            if sec.get(field):
                sec[field] = MASK
    return out


def has_secret(section: str) -> bool:
    """Whether a key is stored for this section, without revealing it."""
    return bool(str(_section(section).get("api_key", "") or "").strip())
