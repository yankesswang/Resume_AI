"""Central application settings.

Every environment-tunable value in the app is declared here, so deploying no
longer means grepping for ``os.getenv`` across a dozen modules.  Modules keep
reading their own module-level constants (``LM_STUDIO_URL`` and friends) — those
now source their defaults from here rather than each re-reading the environment
with its own spelling of the default.

Config precedence: environment variable > ``.env`` file > default below.
See ``.env.example`` for the documented set.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Populate os.environ from a .env file without adding a dependency.

    Real environment variables always win: a value already exported by the
    container/systemd unit must not be silently overridden by a stale .env
    left in the working copy.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(Path(os.environ.get("ENV_FILE", str(ROOT_DIR / ".env"))))


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


class Settings:
    """Resolved configuration. Instantiate once via ``get_settings()``."""

    def __init__(self) -> None:
        # --- Storage ---
        self.db_path = Path(os.environ.get("DB_PATH", str(ROOT_DIR / "resume_ai.db")))
        self.data_dir = Path(os.environ.get("DATA_DIR", str(ROOT_DIR / "data")))
        self.output_dir = Path(os.environ.get("OUTPUT_DIR", str(ROOT_DIR / "output")))
        # Photos live under whichever output_<batch>/ directory produced them, so
        # this root spans them all. It defaults to the project root for backwards
        # compatibility with existing batch layouts; point it at a dedicated
        # directory in production so the served root holds nothing but photos.
        self.photo_root = Path(os.environ.get("PHOTO_ROOT", str(ROOT_DIR))).resolve()
        self.job_requirement_path = Path(
            os.environ.get("JOB_REQUIREMENT_PATH", str(ROOT_DIR / "job_requirement.json"))
        )

        # --- Auth ---
        # Disabled by default so existing local workflows keep working; the
        # production compose file turns it on. When enabled without any API key
        # configured, the app refuses to start rather than serving PII openly.
        self.auth_enabled = _bool("AUTH_ENABLED", False)
        self.api_keys = _csv("API_KEYS", ())
        self.auth_header = os.environ.get("AUTH_HEADER", "X-API-Key")
        # Read-only keys may GET but not mutate.
        self.readonly_api_keys = _csv("READONLY_API_KEYS", ())

        # --- User accounts / sessions ---
        # Signing key for login tokens. Empty by default; validate() demands a
        # real one once auth is on. It is NOT auto-generated at startup: a
        # random per-process secret would log every user out on each restart
        # and would differ between workers, which reads as "login is broken"
        # rather than as the misconfiguration it is.
        self.session_secret = os.environ.get("SESSION_SECRET", "")
        # 12h: one working day, so a session does not survive the night on an
        # unattended machine, and nobody is logged out mid-review.
        self.session_ttl_seconds = _int("SESSION_TTL_SECONDS", 12 * 60 * 60)
        # Whether strangers may create a pending account at all. On by default
        # — a pending account can see nothing until root approves it, so the
        # exposure is a row in a table. Turn it off to make root-created
        # accounts the only way in.
        self.registration_open = _bool("REGISTRATION_OPEN", True)
        # Optional allow-list of email domains that may register, e.g.
        # "company.com,company.com.tw". Empty means any domain.
        self.registration_domains = _csv("REGISTRATION_DOMAINS", ())

        # --- CORS ---
        # "*" only survives while auth is disabled; see validate().
        self.cors_origins = _csv("CORS_ORIGINS", ("*",))

        # --- Uploads ---
        # 200MB, not the more usual 25MB: 104 resumes are multi-page colour
        # scans. Measured over the 84 PDFs in this repo the median is 131MB and
        # the largest is 162MB, so a 25MB cap would 413 roughly 99% of real
        # uploads. Raise further only alongside MAX_UPLOAD_BYTES in nginx.
        self.max_upload_bytes = _int("MAX_UPLOAD_BYTES", 200 * 1024 * 1024)
        # A single-resume upload is a handful of pages. The 104 exports in
        # data/ are 595-746 page bundles holding ~200 candidates each, and the
        # upload path inserts whatever it parses as ONE candidate — so a bundle
        # arriving here silently merges hundreds of people into one row. Size
        # cannot tell the two apart (a real resume is already 131-162MB), so
        # the page count is the discriminator. Bundles belong in
        # scripts/batch_import.py, which splits them.
        self.max_upload_pages = _int("MAX_UPLOAD_PAGES", 40)
        self.upload_rate_limit = _int("UPLOAD_RATE_LIMIT", 30)  # per window
        self.upload_rate_window = _int("UPLOAD_RATE_WINDOW", 60)  # seconds

        # --- Parsing ---
        self.worker_url = os.environ.get("WORKER_URL", "")
        self.parser_backend = os.environ.get("PARSER_BACKEND", "marker").strip().lower()

        # --- LLM ---
        self.lm_studio_url = os.environ.get(
            "LM_STUDIO_URL", "http://localhost:1234/v1/chat/completions"
        )
        self.lm_studio_model = os.environ.get("LM_STUDIO_MODEL", "")
        self.model_context_length = _int("MODEL_CONTEXT_LENGTH", 32768)
        self.response_tokens = _int("RESPONSE_TOKENS", 2048)
        self.tier_markdown_chars = _int("TIER_MARKDOWN_CHARS", 12000)
        self.embedding_url = os.environ.get(
            "EMBEDDING_URL", "http://localhost:1234/v1/embeddings"
        )
        self.embedding_model = os.environ.get(
            "EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v1.5"
        )

        # --- Scoring ---
        self.scoring_config_path = Path(
            os.environ.get("SCORING_CONFIG_PATH", str(ROOT_DIR / "scoring_config.json"))
        )

        # --- Jobs / worker ---
        self.job_poll_interval = _int("JOB_POLL_INTERVAL", 2)
        self.job_concurrency = _int("JOB_CONCURRENCY", 1)
        # Run job workers as threads inside the API process. On by default so
        # `uvicorn main:app` alone still processes queued work — that is
        # today's single-process user experience. Turn it off when running
        # `python -m app.worker_queue` separately, or both would pull jobs.
        self.job_worker_inprocess = _bool("JOB_WORKER_INPROCESS", True)

        # --- Data retention (PII) ---
        # 0 disables automatic purging.
        self.retention_days = _int("RETENTION_DAYS", 0)
        self.audit_enabled = _bool("AUDIT_ENABLED", True)

    def validate(self) -> list[str]:
        """Return configuration errors that should stop startup."""
        errors: list[str] = []
        if self.auth_enabled and not (self.api_keys or self.readonly_api_keys):
            errors.append(
                "AUTH_ENABLED=true but neither API_KEYS nor READONLY_API_KEYS is set — "
                "the app would reject every request. Set at least one key."
            )
        if self.auth_enabled and "*" in self.cors_origins:
            errors.append(
                "CORS_ORIGINS='*' is not allowed when AUTH_ENABLED=true. "
                "List the exact frontend origins instead."
            )
        if self.max_upload_bytes <= 0:
            errors.append("MAX_UPLOAD_BYTES must be positive.")
        if self.max_upload_pages <= 0:
            errors.append("MAX_UPLOAD_PAGES must be positive.")
        if self.auth_enabled and not self.session_secret:
            errors.append(
                "AUTH_ENABLED=true but SESSION_SECRET is unset — login tokens cannot "
                "be signed. Generate one with: python -c \"import secrets; "
                "print(secrets.token_urlsafe(48))\""
            )
        if self.session_secret and len(self.session_secret) < 32:
            errors.append(
                "SESSION_SECRET is shorter than 32 characters. An HS256 signing key "
                "guessable by brute force lets anyone mint a root session."
            )
        if self.session_ttl_seconds <= 0:
            errors.append("SESSION_TTL_SECONDS must be positive.")
        return errors

    def warnings(self) -> list[str]:
        """Non-fatal configuration concerns worth logging loudly at startup."""
        out: list[str] = []
        if not self.auth_enabled:
            out.append(
                "AUTH_ENABLED=false — every endpoint is unauthenticated. "
                "This exposes candidate PII to anyone who can reach this port. "
                "Do not bind to a public interface in this mode."
            )
        if "*" in self.cors_origins:
            out.append("CORS_ORIGINS='*' — any website can call this API from a browser.")
        if self.photo_root == ROOT_DIR:
            out.append(
                f"PHOTO_ROOT is the project root ({ROOT_DIR}); only output*/ image "
                "files are served, but a dedicated directory is safer."
            )
        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
