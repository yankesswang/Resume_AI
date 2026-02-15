# Resume AI

A full-stack resume management and AI-powered candidate screening system. Upload resume PDFs, automatically extract structured candidate information, and intelligently match candidates against job requirements using a multi-dimensional scoring funnel.

## Features

- **PDF Upload & Parsing** — Upload resume PDFs through the web UI or batch import via CLI. Uses [Marker](https://github.com/VikParuchuri/marker) for advanced PDF-to-Markdown parsing with span-based semantic extraction and image recognition. Supports offloading parsing to a remote GPU worker.
- **Structured Data Extraction** — Regex-based parser optimized for 104.com (Taiwan job board) resume format, with LLM fallback for unstructured resumes. Extracts personal info, work history, education, skills, and more.
- **3-Layer Screening Funnel** — Multi-stage candidate evaluation:
  1. **Hard Filters (Layer 1)** — Boolean checks for must-have skills (Python, PyTorch/TensorFlow, AI keywords). Instant rejection for unqualified candidates.
  2. **Semantic Matching (Layer 2)** — Embedding-based cosine similarity between candidate resume and job description via LM Studio embeddings.
  3. **Deep Reasoning (Layer 3)** — LLM-powered analysis for tech depth, project complexity, and quantified metric verification.
- **4-Tier AI Experience Pyramid** — Classifies candidates into:
  - **Tier 1 (Wrapper)** — API callers, prompt engineers (60 pts)
  - **Tier 2 (RAG Architect)** — Vector DB, RAG pipelines, agent frameworks (80 pts)
  - **Tier 3 (Model Tuner)** — Fine-tuning, LoRA/QLoRA, PyTorch (90 pts)
  - **Tier 4 (Inference Ops)** — vLLM, CUDA, TensorRT-LLM, GPU optimization (100 pts)
- **Weighted Scoring (Total = 100)** — Five dimensions weighted to sum to exactly 100: AI Experience (35%) + Engineering (20%) + Semantic Match (20%) + Education (15%) + Skills (10%)
- **Rich Scorecard UI** — Detailed candidate scorecards with tier badges, engineering matrix, tags, strengths/gaps, and interview suggestions.
- **Searchable Candidate Database** — Filter candidates by education level, skills, years of experience, match score, AI tier, and hard filter status.

## Tech Stack

| Layer    | Technology                                      |
| -------- | ----------------------------------------------- |
| Backend  | FastAPI, SQLite (WAL), Marker, httpx, Pydantic  |
| Frontend | Vue 3, Vuetify 3, Pinia, Vite, Axios            |
| AI/LLM   | LM Studio (local inference + embeddings)       |
| Runtime  | Python 3.10+, Node.js 18+, uv (package manager) |

## Getting Started

### Prerequisites

- Python 3.10+
- Node.js 18+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [LM Studio](https://lmstudio.ai/) (optional, for AI scoring and embeddings)

### Backend

```bash
# Install Python dependencies
uv sync

# Start the API server
uv run python -m uvicorn main:app --reload --port 8000
```

The backend runs at `http://127.0.0.1:8000`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend runs at `http://localhost:5173` and proxies API requests to the backend.

### Remote PDF Worker (Optional)

The worker offloads heavy PDF-to-Markdown parsing (via Marker) to a GPU machine:

```bash
uv run python -m uvicorn app.worker:app --host 0.0.0.0 --port 8100
```

Set `WORKER_URL` on the backend to delegate parsing (e.g. `http://192.168.1.100:8100`).

### LM Studio (Optional)

1. Install and launch [LM Studio](https://lmstudio.ai/)
2. Load a model and start the local server (default: `http://localhost:1234`)
3. For embeddings, load an embedding model (e.g., `nomic-embed-text`)
4. The app will use it for resume extraction, candidate scoring, and semantic similarity

### Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `WORKER_URL` | `""` (local parsing) | Remote PDF parse worker URL |
| `LM_STUDIO_URL` | `http://localhost:1234/v1/chat/completions` | LM Studio endpoint for LLM scoring |

## Scoring Architecture

### Formula (Total = 100)

```
S_Final = (S_AI × 0.35) + (S_Eng × 0.20) + (S_Semantic × 0.20) + (S_Edu × 0.15) + (S_Skill × 0.10)
```

| Dimension | Weight | Max Points | Source |
|-----------|--------|------------|--------|
| AI Experience | 35% | 35 | 4-tier pyramid (0-100 normalized) |
| Engineering | 20% | 20 | Full-stack capability matrix (0-0.5 normalized to 0-100) |
| Semantic Match | 20% | 20 | Cosine similarity (0-1 normalized to 0-100) |
| Education | 15% | 15 | School tier + degree + major (0-100) |
| Skills | 10% | 10 | Ecosystem classification + cross-verification (0-100) |

### Engineering Capability Levels

- **Backend:** Flask/FastAPI (L1) → Docker/Async (L2) → K8s/MQ (L3)
- **Database:** SQL (L1) → ORM/NoSQL (L2) → Vector DB (L3)
- **Frontend:** Streamlit (L1) → HTML/CSS (L2) → React/Vue (L3)

### Education Scoring

```
Score_Edu = (S_Tier × 0.5) + (D_Level × 0.3) + (M_Relevance × 0.2) + Bonus_Thesis
```

### Skill Verification

- Ecosystem classification: Traditional ML / Deep Learning / LLM Stack
- Cross-referencing: flags skills claimed but not evidenced in work experience

## Project Structure

```
├── main.py                    # FastAPI app entrypoint
├── app/
│   ├── routes.py              # API route handlers
│   ├── database.py            # SQLite schema, migrations, and queries
│   ├── models.py              # Pydantic models (including enhanced scoring)
│   ├── document_parser.py     # PDF/DOCX/PPTX parsing via Marker
│   ├── regex_parser.py        # 104.com resume format parser
│   ├── parser_service.py      # Local/remote parse orchestration
│   ├── llm.py                 # LM Studio client + tier classification
│   ├── worker.py              # Remote PDF parse worker (FastAPI micro-service)
│   ├── scoring/               # Scoring engine package
│   │   ├── pipeline.py        # Scoring orchestrator
│   │   ├── hard_filter.py     # Layer 1 boolean filters
│   │   ├── embeddings.py      # Layer 2 semantic matching
│   │   ├── experience.py      # 4-tier AI pyramid classification
│   │   ├── engineering.py     # Full-stack capability matrix
│   │   ├── education.py       # Education scoring (school tier, degree, major)
│   │   └── skills.py          # Skill verification & ecosystem check
│   └── templates/             # Jinja2 HTML templates
├── frontend/
│   └── src/
│       ├── api/               # Axios API client
│       ├── components/        # Vue components (ScoreCard, TierBadge, EngineeringMatrix, etc.)
│       ├── views/             # Page views (ListView, DetailView)
│       ├── stores/            # Pinia state management (filters, bookmarks)
│       ├── router/            # Vue Router config
│       └── plugins/           # Vuetify config
├── scripts/                   # CLI utilities
│   ├── batch_import.py        # Batch PDF import
│   ├── batch_score_all.py     # Score all candidates
│   ├── repair_candidates.py   # Repair broken candidate records
│   ├── dedup_candidates.py    # Deduplicate candidates
│   ├── import_to_db.py        # Import parsed data to DB
│   ├── create_example_db.py   # Create example database
│   └── test_lmstudio.py       # Test LM Studio connection
├── tests/                     # Tests
│   ├── test_scoring.py        # Scoring engine unit tests
│   └── test_e2e_scoring.py    # End-to-end scoring tests
├── data/                      # Uploaded resume PDFs
├── output/                    # Parsed documents & images
├── job_requirement.json       # Target job specification (with hard filters & weights)
└── pyproject.toml             # Python project config
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/upload` | Upload resume PDF |
| `GET` | `/api/candidates` | List all candidates with summary + scores |
| `GET` | `/api/candidates/{id}` | Full candidate detail |
| `POST` | `/api/candidates/{id}/match` | Trigger enhanced scoring pipeline |
| `GET` | `/api/candidates/{id}/match` | Get match result |
| `GET` | `/api/candidates/{id}/scorecard` | Full scorecard with all dimensions |
| `POST` | `/api/candidates/batch-match` | Score all unscored candidates |
| `GET` | `/api/filters` | Available filter options |

## Usage

1. Open the web UI at `http://localhost:5173`
2. Click **Upload** and select a resume PDF
3. The system parses the PDF and extracts candidate data automatically
4. Browse candidates in the list view — filter by education, skills, experience, AI tier, or score
5. Click a candidate to view their full profile
6. Click **Run Match** to execute the scoring pipeline (hard filter → semantic → deep reasoning)
7. View the full scorecard with tier classification, engineering matrix, tags, and interview suggestions

## Testing

```bash
# Run the scoring engine unit tests
python -m pytest tests/test_scoring.py

# Run end-to-end scoring tests
python -m pytest tests/test_e2e_scoring.py
```
