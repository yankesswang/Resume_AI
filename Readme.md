# Resume AI

AI-powered resume screening system. Upload PDF resumes, extract structured candidate data, and rank candidates against a job requirement using a multi-layer scoring pipeline.

## Features

- **PDF Parsing** — converts resumes to structured data via OCR ([Marker](https://github.com/VikParuchuri/marker))
- **5-Dimension Scoring** — AI experience depth, engineering maturity, education, skills, semantic similarity
- **LLM Integration** — optional [LM Studio](https://lmstudio.ai/) integration for AI tier classification and smart extraction
- **Semantic Matching** — embedding-based cosine similarity with bilingual keyword-overlap fallback
- **Vue 3 SPA** — filterable candidate list, detailed scorecards, bookmarks
- **Batch Processing** — scripts for bulk ingestion, scoring, and LLM tier classification

---

## Quick Start

### Prerequisites

- Python 3.10+ with [uv](https://docs.astral.sh/uv/)
- Node.js 18+
- (Optional) [LM Studio](https://lmstudio.ai/) for LLM-powered scoring

### 1. Backend

```bash
uv sync
uv run python -m uvicorn main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev        # → http://localhost:5173
```

The Vite dev server proxies `/api`, `/output`, and `/upload` to the backend automatically.

### 3. Environment (optional)

Create a `.env` in the project root:

```env
# LLM scoring (LM Studio)
LM_STUDIO_URL=http://localhost:1234/v1/chat/completions

# Semantic similarity embeddings
EMBEDDING_URL=http://localhost:1234/v1/embeddings
EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5

# Remote PDF worker — leave empty to parse locally
WORKER_URL=
```

---

## Scoring Pipeline

```
S_Final = (S_AI × 0.35) + (S_Eng × 0.20) + (S_Semantic × 0.20) + (S_Edu × 0.15) + (S_Skill × 0.10)
```

| Dimension | Weight | What it measures |
|-----------|:------:|-----------------|
| AI Experience | 35% | 3-tier pyramid: API Wrapper → RAG Architect → AI Expert |
| Engineering Maturity | 20% | Backend, database, and frontend skill levels |
| Semantic Match | 20% | Cosine similarity between resume and job description |
| Education | 15% | School tier + major relevance + thesis/publication bonus |
| Skills | 10% | Ecosystem classification + suspicious-claim detection |

### AI Experience Tiers

| Tier | Label | Evidence |
|------|-------|----------|
| T3 | AI Expert | Model training, fine-tuning (LoRA/DPO/SFT), inference optimization (vLLM, CUDA, TensorRT), published research |
| T2 | RAG Architect | RAG pipelines, vector databases, agent loops, LangChain/LlamaIndex |
| T1 | API Wrapper | LLM API calls, prompt engineering, demo/Streamlit apps |

> See [SCORING_ALGO.md](SCORING_ALGO.md) for the full specification.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI, SQLite (WAL), Marker, httpx, Pydantic |
| Frontend | Vue 3, Tailwind CSS v4, Pinia, Vite, Axios |
| AI/LLM | LM Studio (local inference + embeddings) |
| Runtime | Python 3.10+, Node.js 18+, uv |

---

## Project Structure

```
main.py                  # FastAPI app entry point
job_requirement.json     # Job spec — edit to change the scoring target
pyproject.toml           # Python dependencies (uv)
app/
  routes.py              # REST API endpoints
  database.py            # SQLite helpers and schema migrations
  models.py              # Pydantic schemas
  document_parser.py     # Marker PDF → Markdown converter
  regex_parser.py        # Markdown → structured resume fields (104.com format)
  parser_service.py      # Local / remote parse orchestration
  llm.py                 # LM Studio client
  worker.py              # Optional remote PDF parse worker (FastAPI micro-service)
  scoring/
    pipeline.py          # Orchestrates all scoring modules
    experience.py        # AI tier classification (LLM + keyword fallback)
    education.py         # School tier and major relevance scoring
    engineering.py       # Backend / DB / frontend maturity levels
    skills.py            # Skill ecosystem classification and verification
    embeddings.py        # Semantic similarity via cosine distance
    hard_filter.py       # Boolean gate for must-have requirements
frontend/                # Vue 3 SPA (Vite + Tailwind CSS v4 + Pinia)
scripts/                 # CLI utilities (see below)
tests/                   # Unit and end-to-end tests
```

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/upload` | Upload a PDF resume |
| `GET` | `/api/candidates` | List all candidates with scores |
| `GET` | `/api/candidates/{id}` | Full candidate detail |
| `GET` | `/api/candidates/{id}/scorecard` | Score breakdown with all dimensions |
| `POST` | `/api/candidates/{id}/match` | Re-run scoring (async) |
| `POST` | `/api/candidates/batch-match` | Score all candidates missing a result |
| `GET` | `/api/filters` | Available filter options |
| `POST` | `/api/export/candidates` | Export selected candidates as JSON |
| `POST` | `/api/export/candidates/csv` | Export selected candidates as CSV (UTF-8 BOM) |

---

## Scripts

```bash
# Re-score all candidates using cached LLM tiers
uv run python scripts/batch_score_all.py

# Run LLM tier classification and cache results in DB
uv run python scripts/reclassify_tiers.py [--limit N] [--force]

# Bulk import markdown files from output/
uv run python scripts/batch_import.py

# Remove duplicate candidates (dedup by 104 code)
uv run python scripts/dedup_candidates.py

# Check LM Studio connectivity
uv run python scripts/test_lmstudio.py
```

---

## Remote PDF Worker

Offload heavy PDF parsing to a GPU machine:

```bash
# On the GPU machine
uv run python -m uvicorn app.worker:app --host 0.0.0.0 --port 8100

# Set WORKER_URL on the backend machine
export WORKER_URL=http://192.168.1.100:8100
```

---

## Configuring the Job Requirement

Edit `job_requirement.json` to change the scoring target. The backend syncs this file on every startup. Key fields:

```json
{
  "tech_stack_weights": {
    "PyTorch": 1.5,
    "CUDA": 2.5,
    "Fine-tuning": 1.8
  },
  "hard_filters": {}
}
```

Set `hard_filters` to `{}` to score all candidates. Add filter rules to gate candidates on must-have requirements.

---

## Development

```bash
# Run tests
uv run pytest tests/

# Production frontend build
cd frontend && npm run build   # → frontend/dist/
```
