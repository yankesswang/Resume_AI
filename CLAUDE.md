# Resume AI

Resume parsing and candidate screening system with a FastAPI backend and Vue 3 frontend.

## Running the app

```bash
# Backend (FastAPI)
uv run python -m uvicorn main:app --reload --port 8000

# Frontend (Vue 3 + Vite)
cd frontend && npm run dev
```

## Remote PDF worker

The worker offloads heavy PDF→Markdown parsing (via Marker) to a GPU machine.

```bash
uv run python -m uvicorn app.worker:app --host 0.0.0.0 --port 8100
```

Set `WORKER_URL` on the backend to delegate parsing to the worker (e.g. `http://192.168.1.100:8100`).

## Key environment variables

| Variable | Default | Purpose |
|---|---|---|
| `WORKER_URL` | `""` (local parsing) | Remote PDF parse worker URL |
| `LM_STUDIO_URL` | `http://localhost:1234/v1/chat/completions` | LM Studio endpoint for LLM scoring |

## Project structure

```
main.py                  # FastAPI app entrypoint
app/
  routes.py              # API endpoints
  database.py            # SQLite helpers
  models.py              # Pydantic models
  document_parser.py     # Marker PDF→Markdown parser
  regex_parser.py        # Regex-based resume field extraction
  parser_service.py      # Local/remote parse orchestration
  llm.py                 # LM Studio client
  worker.py              # Remote PDF parse worker (FastAPI micro-service)
  scoring/               # Rule-based + LLM scoring pipeline
frontend/                # Vue 3 SPA (Vite)
scripts/                 # CLI utilities (batch import, dedup, repair, scoring)
job_requirement.json     # Default job requirement loaded at startup
```
