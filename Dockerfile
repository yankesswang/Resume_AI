# Slim API image — FastAPI app + in-process job worker. NO torch, NO CUDA.
#
# marker-pdf and torch (~1.7GB) are imported only by app/document_parser.py,
# lazily via parser_service.get_parser(). Verified: importing `main` pulls in
# neither, so this image installs 43 packages / ~50MB instead of 132 / ~1.7GB.
#
# Consequence: this image can only parse PDFs with PARSER_BACKEND=plumber
# (text-layer only). For scanned PDFs, point WORKER_URL at the GPU worker built
# from Dockerfile.worker.
#
#   docker build -t resume-ai-api:latest .

# ---------- Stage 1: build the virtualenv ----------
FROM python:3.10-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

# NOTE: the builder WORKDIR must match the runtime path (/app). uv writes
# absolute interpreter paths into console-script shebangs, so a venv built in
# /build and copied to /app yields "exec /app/.venv/bin/uvicorn: no such file
# or directory" — the shebang still points at /build.

# Only the dependency manifests, so the layer caches until deps actually change.
COPY pyproject.toml uv.lock* Readme.md ./

# --no-default-groups drops the `local` group, which is what pulls in the gpu
# extra. Without it uv would install torch here and defeat the whole split.
RUN uv sync --no-default-groups --no-install-project --frozen 2>/dev/null \
    || uv sync --no-default-groups --no-install-project

# ---------- Stage 2: runtime ----------
FROM python:3.10-slim-bookworm AS runtime

# curl is for the container healthcheck; no build toolchain lands in this layer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 1001 appuser \
    && useradd --system --uid 1001 --gid appuser --create-home appuser

WORKDIR /app

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

# Application source. .dockerignore keeps the databases, resume archives and
# output_*/ directories out — the raw context is 25GB, the filtered one 2.8MB.
COPY --chown=appuser:appuser main.py job_requirement.json ./
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser scripts/ ./scripts/

# Writable mount points. Compose maps volumes over these; creating them here
# means the container still starts without volumes for a smoke test.
RUN mkdir -p /data /app/output /app/data \
    && chown -R appuser:appuser /data /app/output /app/data

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DB_PATH=/data/resume_ai.db \
    OUTPUT_DIR=/app/output \
    DATA_DIR=/app/data \
    PHOTO_ROOT=/app/output \
    PARSER_BACKEND=plumber

USER appuser

EXPOSE 8000

# /api/health is deliberately unauthenticated so this works with AUTH_ENABLED=true.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health >/dev/null || exit 1

# No --reload in production: it restarts on every write into output/.
# Worker count is 1 by default; see docs/DEPLOYMENT.md for why raising it
# needs JOB_WORKER_INPROCESS=false and a separate worker process.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
