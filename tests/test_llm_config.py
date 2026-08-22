"""Tests for the runtime LLM provider configuration.

Run: python3 tests/test_llm_config.py
"""

import copy
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# A scratch DB, since the config is stored in app_settings.
_DB = tempfile.mktemp(suffix=".db")
os.environ["DB_PATH"] = _DB

_ENV_VARS = (
    "LM_STUDIO_URL", "LM_STUDIO_MODEL", "MODEL_CONTEXT_LENGTH",
    "RESPONSE_TOKENS", "EMBEDDING_URL", "EMBEDDING_MODEL", "OPENAI_API_KEY",
)

from app.database import init_db  # noqa: E402
from app import llm_config as lc  # noqa: E402

# Cleared *after* the imports, not before: importing app.database pulls in
# app.settings, which loads the project's own .env into os.environ. Clearing
# first would be undone by that import, and every endpoint assertion below
# would silently be testing the developer's .env rather than the defaults.
for _var in _ENV_VARS:
    os.environ.pop(_var, None)

PASS = FAIL = 0


def check(label, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}  got {got!r}, want {want!r}")


def fresh(**overrides):
    """Install a config directly into the cache, bypassing the DB."""
    lc._cache = lc._apply_env(lc._deep_merge(lc.DEFAULTS, overrides))
    return lc._cache


print("=== Defaults ===")
fresh()
check("chat endpoint is LM Studio", lc.endpoint("chat"),
      "http://localhost:1234/v1/chat/completions")
check("embedding endpoint is LM Studio", lc.endpoint("embedding"),
      "http://localhost:1234/v1/embeddings")
check("no auth header without a key", lc.headers("chat"), {})
check("thinking toggle sent to local server", lc.supports_thinking_toggle("chat"))
check("defaults validate", lc.validate(lc.DEFAULTS), [])

print("\n=== Provider switching ===")
fresh(chat={"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-x"})
check("openai chat endpoint", lc.endpoint("chat"), lc.OPENAI_CHAT_URL)
check("bearer header set", lc.headers("chat"), {"Authorization": "Bearer sk-x"})
# OpenAI 400s on unknown body fields, so the LM Studio-only key must not be sent.
check("thinking toggle withheld from OpenAI", lc.supports_thinking_toggle("chat"), False)

fresh(embedding={"provider": "openai", "model": "text-embedding-3-small"})
check("openai embedding endpoint", lc.endpoint("embedding"), lc.OPENAI_EMBEDDING_URL)

print("\n=== URL normalisation ===")
# An operator copies "http://192.168.0.84:1234" out of LM Studio's UI; a bare
# host must not silently POST to the wrong path.
fresh(chat={"base_url": "http://192.168.0.84:1234"})
check("bare host gains chat path", lc.endpoint("chat"),
      "http://192.168.0.84:1234/v1/chat/completions")
fresh(embedding={"base_url": "http://192.168.0.84:1234/"})
check("trailing slash handled", lc.endpoint("embedding"),
      "http://192.168.0.84:1234/v1/embeddings")
fresh(chat={"base_url": "http://host:9/v1/chat/completions"})
check("full path left alone", lc.endpoint("chat"),
      "http://host:9/v1/chat/completions")

print("\n=== Validation ===")


def errors_for(**overrides):
    return lc.validate(lc._deep_merge(lc.DEFAULTS, overrides))


check("unknown provider rejected",
      any("服務商" in e for e in errors_for(chat={"provider": "anthropic"})))
check("OpenAI without a model rejected",
      any("模型名稱" in e for e in errors_for(chat={"provider": "openai", "model": ""})))
check("LM Studio without a model accepted",
      errors_for(chat={"provider": "lmstudio", "model": ""}), [])
check("embedding without a model rejected",
      any("模型名稱" in e for e in errors_for(embedding={"model": ""})))
check("non-http url rejected",
      any("http" in e for e in errors_for(chat={"base_url": "localhost:1234"})))
check("zero timeout rejected",
      any("正整數" in e for e in errors_for(chat={"timeout": 0})))
# _truncate_to_fit subtracts one from the other; inverted, every resume
# collapses to the 500-char floor and scoring silently reads almost nothing.
check("response_tokens >= context_length rejected",
      any("context_length" in e
          for e in errors_for(chat={"context_length": 2048, "response_tokens": 4096})))

print("\n=== Secret handling ===")
init_db()
lc._cache = None
saved = lc.save({"chat": {"provider": "openai", "model": "gpt-4o-mini",
                          "api_key": "sk-REAL"}})
check("key persisted in clear text internally", saved["chat"]["api_key"], "sk-REAL")
check("key masked on the way out", lc.redacted(saved)["chat"]["api_key"], lc.MASK)
check("has_secret reports true without revealing", lc.has_secret("chat"))

# The client is shown a mask; echoing it back must not overwrite the key with
# four bullet characters.
lc._cache = None
again = lc.save({"chat": {"model": "gpt-4o", "api_key": lc.MASK}})
check("mask echo preserves the stored key", again["chat"]["api_key"], "sk-REAL")
check("other fields still update", again["chat"]["model"], "gpt-4o")

lc._cache = None
check("survives a reload from the DB", lc.load()["chat"]["api_key"], "sk-REAL")

print("\n=== Cache invalidation ===")
from app.llm import TIER_CLASSIFY_PROMPT_MD5, tier_classifier_key  # noqa: E402

lc._cache = None
lc.reset()
lc._cache = None
# The 3179 existing cached tiers must stay valid: the default config has to
# reproduce the bare prompt hash exactly.
check("default config reproduces the prompt hash",
      tier_classifier_key(), TIER_CLASSIFY_PROMPT_MD5)

version_before = lc.config_version()
lc._cache = None
lc.save({"chat": {"api_key": "sk-ROTATED"}})
lc._cache = None
# Rotating a credential does not change what the model answers.
check("rotating the key leaves the version unchanged",
      lc.config_version(), version_before)

lc._cache = None
lc.save({"chat": {"provider": "openai", "model": "gpt-4o"}})
lc._cache = None
check("changing the model changes the version",
      lc.config_version() != version_before)
# A tier judged by a local 7B is not a tier judged by GPT-4o.
check("changing the model invalidates cached tiers",
      tier_classifier_key() != TIER_CLASSIFY_PROMPT_MD5)

print("\n=== Environment precedence ===")
os.environ["LM_STUDIO_URL"] = "http://env-host:1234/v1/chat/completions"
lc._cache = None
lc.save({"chat": {"provider": "lmstudio", "model": "",
                  "base_url": "http://ui-host:1234/v1/chat/completions"}})
lc._cache = None
check("environment wins over the stored document",
      lc.endpoint("chat"), "http://env-host:1234/v1/chat/completions")
check("the pinned field is reported to the UI",
      "base_url" in lc.env_pinned()["chat"])
os.environ.pop("LM_STUDIO_URL", None)

os.environ["OPENAI_API_KEY"] = "sk-FROM-ENV"
lc._cache = None
lc.save({"chat": {"provider": "openai", "model": "gpt-4o", "api_key": ""}})
lc._cache = None
check("OPENAI_API_KEY fills an unset key",
      lc.headers("chat"), {"Authorization": "Bearer sk-FROM-ENV"})
os.environ.pop("OPENAI_API_KEY", None)

print("\n=== Corrupt / partial documents ===")
from app.database import set_app_setting  # noqa: E402

set_app_setting(lc.SETTING_KEY, "{not json")
lc._cache = None
check("corrupt JSON degrades to defaults, does not raise",
      lc.endpoint("chat"), "http://localhost:1234/v1/chat/completions")

# An invalid stored document must not take the API down either.
set_app_setting(lc.SETTING_KEY, '{"chat": {"provider": "bogus"}}')
lc._cache = None
check("invalid stored config degrades to defaults",
      lc.provider("chat"), lc.PROVIDER_LMSTUDIO)

set_app_setting(lc.SETTING_KEY, '{"chat": {"model": "only-this"}}')
lc._cache = None
check("partial document merges over defaults", lc.model("chat"), "only-this")
check("unspecified keys keep their default", lc.chat_context_length(), 32768)

# --- Model catalogue --------------------------------------------------------
# The catalogue is a picker vocabulary for the settings page. Two things must
# hold or it teaches the operator to configure something broken: every listed
# model must be a valid choice under validate(), and the shipped defaults must
# appear in it — otherwise a fresh install opens on "自訂" and looks
# misconfigured before anyone has touched it.

print("\n-- model catalogue")
cat = lc.model_catalogue()
check("catalogue covers every provider", sorted(cat), sorted(lc.PROVIDERS))

for _provider in lc.PROVIDERS:
    for _section in ("chat", "embedding"):
        entries = cat[_provider][_section]
        ok = all(
            isinstance(e, dict) and e.get("value") and e.get("label")
            for e in entries
        )
        check(f"{_provider}/{_section} entries have value+label", ok)
        values = [e["value"] for e in entries]
        check(f"{_provider}/{_section} has no duplicate models",
              len(values), len(set(values)))

# A listed model must survive validation, or the dropdown offers a choice the
# save button rejects.
for _section in ("chat", "embedding"):
    for _entry in cat[lc.PROVIDER_OPENAI][_section]:
        cfg = copy.deepcopy(lc.DEFAULTS)
        cfg[_section]["provider"] = lc.PROVIDER_OPENAI
        cfg[_section]["model"] = _entry["value"]
        if _section == "chat":
            cfg["embedding"]["model"] = lc.DEFAULTS["embedding"]["model"]
        check(f"catalogued {_entry['value']} validates", lc.validate(cfg), [])

check("openai chat has a default suggestion",
      bool(lc.default_model(lc.PROVIDER_OPENAI, "chat")))
check("openai embedding has a default suggestion",
      bool(lc.default_model(lc.PROVIDER_OPENAI, "embedding")))
# Blank stays correct for a local chat server even though the catalogue now
# lists names there: it serves whichever model is loaded, and those entries are
# format references for someone typing their own, so pre-selecting one would
# name a model the operator may not have downloaded.
check("lmstudio chat suggests nothing",
      lc.default_model(lc.PROVIDER_LMSTUDIO, "chat"), "")
check("lmstudio chat still offers reference formats",
      len(cat[lc.PROVIDER_LMSTUDIO]["chat"]) > 0)

# A local model name must save as-is — the local path has no model-name rule
# beyond "non-empty or blank", and a reference format that failed validation
# would be worse than none.
for _entry in lc.MODEL_CATALOGUE[lc.PROVIDER_LMSTUDIO]["chat"]:
    _local = copy.deepcopy(lc.DEFAULTS)
    _local["chat"]["model"] = _entry["value"]
    check(f"local reference {_entry['value']} validates", lc.validate(_local), [])
check("shipped embedding default is in the catalogue",
      lc.DEFAULTS["embedding"]["model"],
      lc.default_model(lc.PROVIDER_LMSTUDIO, "embedding"))

# Returned as a copy — a caller mutating it must not change what later requests
# are offered.
cat[lc.PROVIDER_OPENAI]["chat"].clear()
check("catalogue is returned as a copy",
      len(lc.model_catalogue()[lc.PROVIDER_OPENAI]["chat"]) > 0)

# It is a suggestion list, not a whitelist: OpenAI ships names faster than this
# file is edited, so an unlisted model must still save.
_unlisted = copy.deepcopy(lc.DEFAULTS)
_unlisted["chat"]["provider"] = lc.PROVIDER_OPENAI
_unlisted["chat"]["model"] = "gpt-6-turbo-not-yet-released"
check("an unlisted model is still accepted", lc.validate(_unlisted), [])

print("\n" + "=" * 50)
print(f"PASS: {PASS}   FAIL: {FAIL}")
print("=" * 50)

try:
    os.unlink(_DB)
except OSError:
    pass

sys.exit(1 if FAIL else 0)
