# Deployment

Resume AI holds full resume PII — names, mobiles, emails, mailing addresses,
birth years, photos and raw resume text — for thousands of real applicants.
Read [Security](#security-read-this-first) before exposing it to anything wider
than localhost.

Two supported shapes:

| | Use when |
|---|---|
| [Docker Compose](#option-a-docker-compose) | Normal production deployment |
| [systemd](#option-b-systemd-no-docker) | Single machine, no container runtime |

---

## Security: read this first

The system ships with `AUTH_ENABLED=false` so local development works out of the
box. **In that mode every endpoint is unauthenticated** and anyone who can reach
the port can download every resume in the database.

Before any deployment beyond localhost you MUST set:

```bash
AUTH_ENABLED=true
API_KEYS=<generated key>            # comma-separated for multiple
CORS_ORIGINS=https://recruiting.example.com   # exact origins, never "*"
```

The app **refuses to start** if `AUTH_ENABLED=true` with no keys, or with
`CORS_ORIGINS=*`. That check is deliberate — it turns a silent PII exposure into
a loud startup failure.

Generate keys with real entropy:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Clients send `X-API-Key: <key>` (or `Authorization: Bearer <key>`).
`READONLY_API_KEYS` may GET but are rejected with 403 on any write.

API keys travel in a plaintext header. **Terminate TLS in front of nginx** for
anything outside a trusted LAN.

### Access auditing

Every PII-touching request is recorded in the `access_audit` table with a
*hashed* key id (never the key itself), method, path, candidate id, status and
client IP. To see who accessed a candidate:

```sql
SELECT ts, key_id, method, path, status_code
FROM access_audit WHERE candidate_id = 123 ORDER BY ts DESC;
```

### Retention and erasure

`RETENTION_DAYS=0` (the default) disables automatic purging — nothing is ever
deleted on its own. To review and apply a retention policy:

```bash
python scripts/purge_expired.py              # dry run: reports only
python scripts/purge_expired.py --apply      # actually deletes
```

Erasure removes the candidate, all child rows, and on-disk artifacts.
**Note:** candidates share source PDFs (in the current database 3179 candidates
come from just 18 PDFs), so a source PDF is deleted only when no other candidate
still references it.

---

## Option A: Docker Compose

### Prerequisites
- Docker 24+ with Compose v2
- For the GPU parse worker: NVIDIA drivers + NVIDIA Container Toolkit

### First run

```bash
cp .env.example .env
# edit .env: AUTH_ENABLED=true, API_KEYS=..., CORS_ORIGINS=...

docker compose up -d --build
curl -fsS http://127.0.0.1:8080/api/health
```

The SPA is served at http://127.0.0.1:8080 and proxies `/api` and `/output` to
the API container, so the frontend needs no build-time backend URL.

### Images

| Image | Size | Contents |
|---|---|---|
| `resume-ai-api` | **195 MB** | FastAPI + job worker, 26 packages, **no torch** |
| `resume-ai-worker` | ~6 GB | Marker + torch + CUDA, GPU only |
| `resume-ai-frontend` | ~50 MB | nginx + built SPA |

The API image is slim because `torch` and `marker-pdf` (~1.7 GB) are imported
only by `app/document_parser.py`, lazily through `parser_service.get_parser()`.
Importing `main` pulls in neither, so they live in the `gpu` extra and only the
worker image installs them.

The trade-off: the API image can only parse **text-layer** PDFs
(`PARSER_BACKEND=plumber`). Scanned resumes need the GPU worker.

### Enabling the GPU parse worker

```bash
docker compose --profile gpu up -d --build
```

Then point the API at it by adding to `.env`:

```bash
WORKER_URL=http://worker:8100
```

Marker downloads several GB of model weights on first use; they persist in the
`model-cache` volume.

### Volumes

| Volume | Holds |
|---|---|
| `db-data` | `resume_ai.db` |
| `resume-pdfs` | Uploaded source PDFs |
| `resume-output` | Parsed markdown + extracted photos |
| `model-cache` | Marker/HuggingFace weights |

> **SQLite and network storage.** The DB runs in WAL mode, which needs real
> POSIX locking. Named local volumes are fine. **Do not** put `db-data` on NFS
> or SMB — WAL will corrupt or deadlock there.

### How many uvicorn workers?

Default is **1**, and raising it is not free:

1. `JOB_WORKER_INPROCESS=true` (the default) starts a job-worker thread *per
   uvicorn worker*. Job claiming is atomic so this is safe, but it multiplies
   concurrent LLM calls.
2. The upload rate limit is in-process, so N workers give N× the configured
   limit.
3. SQLite tolerates one writer at a time; scoring runs hold write transactions.

To scale out properly: set `JOB_WORKER_INPROCESS=false`, raise `--workers`, and
run the queue worker as its own process (`python -m app.worker_queue`).

---

## Option B: systemd (no Docker)

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/*.service ~/.config/systemd/user/
# edit WorkingDirectory / EnvironmentFile if your checkout is elsewhere

systemctl --user daemon-reload
systemctl --user enable --now resume-ai-api
loginctl enable-linger $USER        # survive logout

journalctl --user -u resume-ai-api -f
```

`resume-ai-worker.service` is only needed when `JOB_WORKER_INPROCESS=false`.
Do not run it while the in-process worker is also enabled — that just duplicates
attempts and wastes LLM capacity.

The frontend still needs building and serving separately:

```bash
cd frontend && npm ci && npm run build   # emits frontend/dist
```

Serve `frontend/dist` with `deploy/nginx/default.conf` as the reference config.

---

## Backup and restore

The database is the only irreplaceable state. **Never copy `resume_ai.db` with
`cp` while the app is running** — WAL mode means you would capture a torn file.
Use SQLite's online backup:

```bash
# Docker
docker compose exec api sh -c 'sqlite3 /data/resume_ai.db ".backup /data/backup.db"'
docker compose cp api:/data/backup.db ./backup-$(date +%F).db

# systemd / local
sqlite3 resume_ai.db ".backup backup-$(date +%F).db"
```

Backups contain complete applicant PII — encrypt them at rest and apply the same
retention policy you apply to the live database.

Restore by stopping the service, replacing the file, and starting it again.
`init_db()` runs pending migrations automatically at startup.

---

## Upload size

`MAX_UPLOAD_BYTES` defaults to **200 MB**, not the more usual 25 MB, because 104
resumes are multi-page colour scans: across the 84 PDFs in this repo the median
is 131 MB and the largest 162 MB. A 25 MB cap would reject ~99% of real uploads
with HTTP 413.

**nginx must agree.** `client_max_body_size` in `deploy/nginx/default.conf` is
set to `200m`; the lower of the two limits wins, so raising one alone has no
effect.

---

## Post-deployment checklist

- [ ] `AUTH_ENABLED=true` with real generated keys
- [ ] `CORS_ORIGINS` lists exact origins, not `*`
- [ ] TLS terminating in front of nginx
- [ ] `curl /api/health` returns `{"status":"ok",...}`
- [ ] An unauthenticated `/api/candidates` returns **401**
- [ ] Backups scheduled and encrypted
- [ ] **Check `/api/scoring-status`** — if `tier_prompt_stale` is non-zero the
      rankings predate the current classifier prompt and are not trustworthy.
      Fix with a rescore (~2.3 s/candidate; cancellable and resumable):
      ```bash
      curl -X POST localhost:8000/api/jobs/rescore \
           -H 'X-API-Key: <key>' -H 'Content-Type: application/json' \
           -d '{"mode":"stale"}'
      ```
