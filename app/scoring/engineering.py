"""Full-Stack Engineering Capability Matrix.

M_Eng = B (Backend) + D (Database) + F (Frontend), max 0.7
"""

from __future__ import annotations

import re
from typing import Any

from app.models import EngineeringMaturityDetail

# Backend levels
BACKEND_L3_PATTERN = re.compile(
    r"(Kubernetes|K8s|RabbitMQ|Kafka|Redis|Celery|gRPC|"
    r"微服務|microservice|Go\b|Golang|Rust|"
    r"Message Queue|高併發|high.?concurrency|load.?balanc)",
    re.IGNORECASE,
)
BACKEND_L2_PATTERN = re.compile(
    r"(Asyncio|async|Docker|Gunicorn|Uvicorn|Nginx|"
    r"CI/CD|GitHub Actions|GitLab CI|容器|container|"
    r"reverse proxy|反向代理)",
    re.IGNORECASE,
)
BACKEND_L1_PATTERN = re.compile(
    r"(Flask|FastAPI|Django|REST\s*API|Python.*API|"
    r"Express|Spring Boot|後端|backend|API\s+develop)",
    re.IGNORECASE,
)

# Database levels
DB_L3_PATTERN = re.compile(
    r"(pgvector|Milvus|Qdrant|Pinecone|Weaviate|Chroma|"
    r"Vector\s*DB|向量資料庫|Neo4j|Graph\s*DB|HNSW|IVF)",
    re.IGNORECASE,
)
DB_L2_PATTERN = re.compile(
    r"(PostgreSQL|MongoDB|SQLAlchemy|Airflow|Elasticsearch|"
    r"NoSQL|ORM|ETL|Redis|資料清理|data pipeline)",
    re.IGNORECASE,
)
DB_L1_PATTERN = re.compile(
    r"(MySQL|SQLite|SQL\b|CSV|Pandas|SELECT|JOIN|"
    r"資料庫|database)",
    re.IGNORECASE,
)

# Frontend levels
FE_L3_PATTERN = re.compile(
    r"(React|Vue\.?js|Vue\b|Next\.?js|Nuxt|Angular|TypeScript|"
    r"Tailwind|SSE|Server.?Sent.?Event|Streaming.*UI|"
    r"前端框架|modern.*frontend)",
    re.IGNORECASE,
)
FE_L2_PATTERN = re.compile(
    r"(HTML5?|CSS3?|Bootstrap|JavaScript|jQuery|"
    r"前端|web\s*develop|網頁)",
    re.IGNORECASE,
)
FE_L1_PATTERN = re.compile(
    r"(Streamlit|Gradio|Dash|Panel|Chainlit)",
    re.IGNORECASE,
)

# Score mapping per level.
# v2: cap raised 0.5 → 0.7 to widen discrimination among senior engineers.
# Backend L3 bumped (0.25→0.35), DB L3 (0.15→0.20), FE L3 (0.10→0.15) to
# utilise the extra headroom.  FE L1 (Streamlit/Gradio) now scores 0.02 to
# acknowledge demo-building ability instead of being a flat zero.
BACKEND_SCORES = {0: 0.0, 1: 0.10, 2: 0.20, 3: 0.35}
DB_SCORES = {0: 0.0, 1: 0.05, 2: 0.12, 3: 0.20}
FE_SCORES = {0: 0.0, 1: 0.02, 2: 0.05, 3: 0.15}


def score_engineering_maturity(
    work_experiences: list[dict[str, Any]],
    skill_tags: list[str],
    raw_markdown: str = "",
) -> EngineeringMaturityDetail:
    """Evaluate full-stack engineering capability.

    Returns M_Eng = B + D + F (capped at 0.5).
    """
    all_text_parts = []
    for we in work_experiences:
        all_text_parts.append(we.get("job_description", "") or "")
        all_text_parts.append(we.get("job_title", "") or "")
        all_text_parts.append(we.get("job_skills", "") or "")
    all_text_parts.extend(skill_tags)
    if raw_markdown:
        all_text_parts.append(raw_markdown)
    combined = " ".join(all_text_parts)

    # Backend level
    if BACKEND_L3_PATTERN.search(combined):
        backend_level = 3
    elif BACKEND_L2_PATTERN.search(combined):
        backend_level = 2
    elif BACKEND_L1_PATTERN.search(combined):
        backend_level = 1
    else:
        backend_level = 0

    # Database level
    if DB_L3_PATTERN.search(combined):
        database_level = 3
    elif DB_L2_PATTERN.search(combined):
        database_level = 2
    elif DB_L1_PATTERN.search(combined):
        database_level = 1
    else:
        database_level = 0

    # Frontend level
    if FE_L3_PATTERN.search(combined):
        frontend_level = 3
    elif FE_L2_PATTERN.search(combined):
        frontend_level = 2
    elif FE_L1_PATTERN.search(combined):
        frontend_level = 1
    else:
        frontend_level = 0

    b = BACKEND_SCORES[backend_level]
    d = DB_SCORES[database_level]
    f = FE_SCORES[frontend_level]
    m_eng = min(b + d + f, 0.7)  # cap raised from 0.5 to 0.7

    return EngineeringMaturityDetail(
        backend_level=backend_level,
        backend_score=b,
        database_level=database_level,
        database_score=d,
        frontend_level=frontend_level,
        frontend_score=f,
        m_eng=round(m_eng, 2),
    )
