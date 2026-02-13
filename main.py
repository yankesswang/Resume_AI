import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import ensure_job_requirement, init_db
from app.routes import router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

JOB_REQ_PATH = Path(__file__).resolve().parent / "job_requirement.json"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    logger.info("Database initialized")

    # Load default job requirement
    if JOB_REQ_PATH.exists():
        data = json.loads(JOB_REQ_PATH.read_text(encoding="utf-8"))
        title = data.get("basic_conditions", {}).get("job_title", "Default Job")
        job_id = ensure_job_requirement(title, json.dumps(data, ensure_ascii=False))
        logger.info("Job requirement loaded (id=%d)", job_id)

    yield


app = FastAPI(title="Resume AI", lifespan=lifespan)

# CORS for Electron frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for output directory (candidate photos, etc.)
OUTPUT_DIR.mkdir(exist_ok=True)
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")

# Include routes
app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
