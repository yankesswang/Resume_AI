import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import audit
from app.auth_routes import admin_router, auth_public_router, auth_router
from app.database import ensure_job_requirement, init_db
from app.job_profiles_routes import router as job_profiles_router
from app.jobs_routes import router as jobs_router
from app.routes import public_router, router
from app.settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

JOB_REQ_PATH = settings.job_requirement_path
OUTPUT_DIR = settings.output_dir


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    # Refuse to boot on a configuration that would serve PII unsafely (auth on
    # with no keys, wildcard CORS with auth on, ...) — failing loudly here beats
    # discovering it from an access log.
    errors = settings.validate()
    if errors:
        for err in errors:
            logger.error("Configuration error: %s", err)
        raise RuntimeError(
            "Invalid configuration: " + "; ".join(errors)
        )
    for warning in settings.warnings():
        logger.warning("%s", warning)

    init_db()
    logger.info("Database initialized")

    # Auth on with no root means registrations pile up with nobody able to
    # approve them, and the only fix is a shell on this machine. Say so at
    # boot rather than letting the first user discover it by waiting.
    if settings.auth_enabled:
        from app.accounts import count_by_status, has_root
        from app.database import _connect

        conn = _connect()
        try:
            if not has_root(conn):
                logger.warning(
                    "AUTH_ENABLED=true but no active root account exists — no one can "
                    "approve registrations. Create one: "
                    "python -m app.accounts_cli bootstrap-root --email you@company.com"
                )
            pending = count_by_status(conn).get("pending", 0)
            if pending:
                logger.info("%d account(s) awaiting root approval", pending)
        finally:
            conn.close()

    # Load default job requirement
    if JOB_REQ_PATH.exists():
        data = json.loads(JOB_REQ_PATH.read_text(encoding="utf-8"))
        title = data.get("basic_conditions", {}).get("job_title", "Default Job")
        job_id = ensure_job_requirement(title, json.dumps(data, ensure_ascii=False))
        logger.info("Job requirement loaded (id=%d)", job_id)

    # Background job workers. In-process by default so `uvicorn main:app` alone
    # still drains the queue — that is today's single-process experience. Set
    # JOB_WORKER_INPROCESS=false when running `python -m app.worker_queue`.
    if settings.job_worker_inprocess:
        from app.jobs import start_inprocess_workers, stop_inprocess_workers
        import app.jobs_scoring  # noqa: F401 - registers the rescore handler
        start_inprocess_workers(
            concurrency=settings.job_concurrency,
            poll_interval=settings.job_poll_interval,
        )
    else:
        stop_inprocess_workers = None
        logger.info("In-process job workers disabled (JOB_WORKER_INPROCESS=false)")

    yield

    if stop_inprocess_workers is not None:
        stop_inprocess_workers()


app = FastAPI(title="Resume AI", lifespan=lifespan)

# CORS for the Electron/Vite frontend. Defaults to "*" so local development is
# unchanged; production must list exact origins (validate() enforces that once
# auth is on).
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def audit_middleware(request, call_next):
    """Record who touched candidate PII, after the response is known.

    Auditing must never turn a working request into a 500, so the record call
    is wrapped even though audit.record() already swallows its own errors.
    """
    response = await call_next(request)
    try:
        principal = getattr(request.state, "principal", None)
        audit.record(
            key_id=principal.key_id if principal is not None else "anonymous",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            client_ip=request.client.host if request.client else None,
        )
    except Exception:
        logger.warning("Audit middleware failed", exc_info=True)
    return response


# Candidate photos are served by the /output route in app.routes, which spans
# every output_<batch>/ directory while exposing only image files — a
# StaticFiles mount here would also serve the DB and source beside them.
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Include routes
app.include_router(public_router)
# Registration and login must precede the authenticated router: they are the
# endpoints you call precisely because you have no credentials yet.
app.include_router(auth_public_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(router)
app.include_router(jobs_router)
app.include_router(job_profiles_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
