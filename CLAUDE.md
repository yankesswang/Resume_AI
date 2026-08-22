# Resume AI

Resume parsing and candidate screening system with a FastAPI backend and Vue 3 frontend.

## Running the app

```bash
# Backend (FastAPI)
uv run python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

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
| `PARSER_BACKEND` | `marker` | Local PDF parser: `marker` (GPU, OCR) or `plumber` (pure Python, text-layer only) |
| `LM_STUDIO_URL` | `http://localhost:1234/v1/chat/completions` | LM Studio endpoint for LLM scoring |
| `MODEL_CONTEXT_LENGTH` | `32768` | Must match the context length configured in LM Studio. Too low silently truncates resumes and wrecks scoring. |
| `RESPONSE_TOKENS` | `2048` | Tokens reserved for the LLM reply |
| `TIER_MARKDOWN_CHARS` | `12000` | Resume text sent to the AI-tier classifier |
| `JOB_WORKER_INPROCESS` | `true` | Run job workers as threads in the API process |
| `JOB_CONCURRENCY` | `1` | Parallel job workers |
| `JOB_POLL_INTERVAL` | `2` | Seconds between queue polls when idle |

## PDF parser backends

`PARSER_BACKEND` selects the local parser (ignored when `WORKER_URL` is set):

- **`marker`** (default) — runs layout/OCR models on a GPU. Needed for scanned
  or image-only PDFs.
- **`plumber`** — reads the PDF text layer with pdfplumber. No GPU, no models.
  Raises on scanned PDFs, which have no text layer to read.

```bash
PARSER_BACKEND=plumber uv run python -m uvicorn main:app --reload
uv run python scripts/batch_import.py --pdf-dir data_v2 --parser-backend plumber
```

## Scoring pipeline

Full algorithm reference — every dimension, why each constant is calibrated the
way it is, and the tunable frontend: **[docs/SCORING_ALGORITHM.md](docs/SCORING_ALGORITHM.md)**.

Scoring knobs live in `app/scoring/config.py` (defaults) and can be overridden at
runtime from the `/scoring` page, which writes `scoring_config.json`. Set
`SCORING_CONFIG_PATH` to relocate that file. All scoring modules read the live
config, so changes apply on the next scoring run without a redeploy.


`app/scoring/pipeline.py` combines five weighted dimensions (weights live in
`WEIGHTS`, the single source of truth for both the maths and the displayed
breakdown):

| Dimension | Weight | Source |
|---|---|---|
| AI experience tier | 35% | LLM classification + keyword floor |
| Engineering maturity | 20% | Keyword levels (backend/DB/frontend) |
| Semantic similarity | 20% | Embeddings vs. the job's skill-bearing fields |
| Education | 15% | School tier × major relevance |
| Skill verification | 10% | Ecosystem match minus unsupported claims |

### AI tier bands

Tier bases and bonus caps are chosen so tiers never overlap — a strong Tier 2
must not outrank a Tier 3:

```
tier 0 Non-AI       25-40    tier 2 RAG Architect  67-84
tier 1 Wrapper      45-62    tier 3 AI Expert      88-100
```

**Tier 0 matters.** Most applicants to an AI role are not AI engineers; without
it every non-AI candidate floored at 60 and the ranking collapsed.

### Calibration notes (do not regress these)

- **The tier classifier must see `raw_markdown`** (`_INCLUDE_RAW_MARKDOWN=True`).
  ~52% of parsed candidates have no `work_experiences` rows and ~42% have empty
  `skill_tags`; with raw text disabled the LLM was handed `工作經驗 []` and
  replied "no evidence → Tier 1" for **98% of the pool**.
- **`MODEL_CONTEXT_LENGTH` must match LM Studio.** The old 4096 default cut
  resumes to ~2k chars, discarding the evidence the scorer needs.
- **Embed only skill-bearing job fields** (`build_job_embedding_text`). Embedding
  the whole job JSON let boilerplate (salary, address, benefits) dominate, so
  strong and weak candidates landed ~0.01 apart. Raw cosines are then stretched
  through `rescale_similarity` because they cluster in a narrow 0.45-0.80 band.
- **The keyword floor requires 2+ distinct high-specificity signals.** One
  keyword is far too loose — 71% of resumes mention PyTorch/Training, usually in
  a course list. Two distinct strong signals lands at ~7.7%.
- Education has 5 school tiers (S/A/B/C/D). A single flat "C=0" bucket put ~60%
  of all education rows at zero, erasing any distinction between a national
  university and an unranked school.

Changing `_TIER_CLASSIFY_PROMPT` or `_INCLUDE_RAW_MARKDOWN` changes
`TIER_CLASSIFY_PROMPT_MD5`, which auto-invalidates the cached tiers in
`candidates.llm_tier` so the next scoring run re-classifies.

## Job postings and domain profiles

The scoring pipeline was built for exactly one role: AI engineer. Tier labels
("Wrapper", "RAG Architect"), the tier keyword tables, the LLM classifier
prompt and the "engineering maturity" matrix (backend/database/frontend) all
hard-coded that job. Screening a salesperson, an accountant or a mechanical
engineer through it gave everyone the same answer, because none of the evidence
it looks for exists in their resumes.

A **domain profile** (`app/scoring/domain_profile.py`) lifts every role-specific
decision out of the code and into data, so a new role is a document rather than
a patch:

| Field | Replaces |
|---|---|
| `tiers` | the hard-coded AI pyramid — 4 levels, each with the evidence that defines it |
| `tier_keywords` | `experience.TIER_KEYWORDS` |
| `competencies` | `engineering.py`'s backend/database/frontend triple |
| `education` | `education.TIER1_MAJOR` / `TIER2_MAJOR` (school tiers stay global) |
| `ecosystems` | `skills.py`'s ecosystem regexes |
| `hard_filters` | unchanged schema, but stored per job |
| `weights` | per-role override of the five dimension weights |

The profile lives on the job (`job_requirements.domain_profile`), not globally,
so two open roles in different fields can be scored side by side.

**The AI path is untouched.** `resolve_profile()` returns `None` for a job with
no profile, and the pipeline then runs the original hard-coded scorers. That is
why the existing 3179 scores and every calibration note below stay valid. The
calibrated AI standard also exists as data in
`app/scoring/builtin_profiles.py` — as a hand-authoring starting point, and as
the reference showing what a good profile looks like.

### Upload flow

```
POST /api/job-postings/upload        PDF / .docx / text  →  job + draft profile
GET  /api/job-postings               all roles + profile state
GET  /api/job-postings/{id}          job + editable profile + validation errors
PUT  /api/job-postings/{id}/profile  save edits ({"activate": true} to go live)
POST /api/job-postings/{id}/profile/regenerate
POST /api/job-postings/{id}/preview  score N candidates, no LLM calls
POST /api/job-postings/{id}/activate make this the job new scoring runs use
```

Two LLM calls do the work (`app/scoring/profile_builder.py`): one structures the
JD into the app's `job_requirement.json` shape, one designs the scoring
standard. Frontend at `/jobs`.

**A generated profile is a draft and does not score anyone until a human
activates it.** A screening standard nobody read is how a hiring system starts
rejecting people for reasons no one can explain.

### What the generator gets wrong, and the guards for it

- **Placeholder echo.** The model copies the prompt's schema filler ("關鍵字",
  `<實際的專家級關鍵字>`) instead of writing real terms. Such a profile
  *validates* but matches nothing in any resume — it looks configured and
  screens blind. `_clean_keyword` drops them.
- **Too few keywords.** `MIN_TIER_KEYWORDS` is 4, not 1: below that, the tier
  weight thresholds in `classify_tier_by_profile` (3.0 for tier 3, 2.0 for
  tier 2) cannot be reached by a genuine candidate.
- **An unreachable top tier.** Validation rejects a tier 3 whose two heaviest
  keywords sum below 3.0.
- **Hard filters that reject everybody.** Empty groups are dropped and
  `min_matches` is clamped to the group size, but a *plausible* filter can still
  clear the pool — which is what `/preview` is for.

### Minimum degree

`hard_filters.min_education` gates on the candidate's highest **parsed** degree
(`high_school` / `associate` / `bachelor` / `master` / `phd`), editable from the
硬性條件 section of `/jobs/{id}`. It is a floor, not an exact match: a 博士
passes a 碩士 gate.

Unlike every other hard filter, it does **not** match resume text. "碩士" in a
resume is usually a quoted job requirement or a colleague's degree, not the
applicant's own, so the gate reads the `education` rows instead — both
`degree_level` and `department`, because the parser routinely leaves the former
blank and stores "資訊工程學系碩士班" in the latter.

Two deliberate asymmetries:

- **A resume with no parsable education fails the gate.** An unknown degree is not
  evidence of holding one, and letting it pass would make the filter optional in
  exactly the cases it is meant to catch.
- **An unrecognised config value gates on nothing.** A typo that rejected the
  whole pool would look identical to a working filter in the UI; `normalise_degree`
  returns `None` and `_repair` blanks the field, so a broken value screens nobody
  rather than everybody.

### Minimum school

`hard_filters.min_school_tier` gates on the candidate's **best** school across
all education rows, using the same global A/B/C/D ladder as the education
scorer (`台清交成政台科` = A, `中央/中興/中正/中山/北科/師大` = B, other national
and well-known private universities = C). School tiers are global — a top school
is a top school for any role — so this is a level picker, not a per-job name
list.

- **`is_phd=False` is passed deliberately.** `_school_points` promotes *any*
  doctorate to tier "S" regardless of institution; that is a degree premium, and
  reusing it here would let a PhD from an unranked school clear a "top
  university" gate.
- **Tier D is stored as "no gate".** It accepts everyone, so persisting it as a
  filter would imply screening that isn't happening. `_repair` blanks both D and
  the non-school "S".
- Same two asymmetries as the degree gate: no parsable school fails, an
  unrecognised tier rejects nobody.

### Adjusting the school tiers

Which schools a company rates is a judgement call, and the shipped tables
cannot name every institution. The 學校分級 section of `/scoring` shows the
built-in schools as four draggable groups (A/B/C/D); dragging a school to
another group, adding one, or removing one edits
`education.school_overrides` in the scoring config:

```json
"school_overrides": [
  {"pattern": "國立台北科技大學", "tier": "A"},
  {"pattern": "台北", "tier": "D"}
]
```

`school_tier()` in `app/scoring/education.py` checks this list **before** the
built-in `TW_GRADE_*` patterns, so an override always wins. Matching is
case-insensitive substring and **the first match wins** — order most-specific
first, which is why the example above rates 北科 as A while demoting other 台北
schools.

`_fold()` also maps 臺→台 before comparing. NFKC does *not* unify the two, but
Taiwanese institutions use them interchangeably (國立臺北大學 / 國立台北大學), so
an operator typing either form matches both.

One function, two consumers: the education *score* and the `min_school_tier`
*gate* both call `school_tier()`, so an override moves a school in the ranking
and in the filter together — they cannot drift apart.

Editing the list bumps `config_version()`, which invalidates cached LLM tiers
the same way a weight change does.

**The groups are rendered from a roster, the scoring still runs on the regexes.**
`default_school_roster()` names the schools each built-in tier covers and is
served by `GET /api/scoring-config/school-roster`; regexes cannot be listed or
dragged, so the UI needs names. A school absent from the roster is still
classified correctly by the patterns — the roster is presentation, never the
matcher. `test_domain_profiles.py` asserts every rostered school classifies into
the tier it is listed under, so the two cannot drift apart. (That check found
`龍華` in the C pattern, which sits inside a `)大學` group and so never matched
the real name 龍華科技大學.)

Each tier column carries its own colour, climbing neutral → good → info →
expert with rank, the same direction `TierBadge.vue` uses so the two pages read
as one scale. D is neutral rather than red: an unranked school is the common
case, not an error. The tones come from the semantic accent triples in
`style.css` (`*-soft` fill / `*-line` border / `*-ink` text), which carry
light and dark values, so the columns follow the theme instead of hard-coding hex.

A dropped school is inserted at the **top** of its new column, not appended,
and the column is scrolled back to 0. C holds ~68 schools in a fixed-height
scroll box, so appending put the arrival below the fold and the move read as
"the school disappeared". It also gets a brief ring — a static one, since
`animate-pulse` means "loading skeleton" elsewhere in this app.

**Only moved schools are saved.** `syncOverrides()` writes an entry solely when
a school's group differs from its roster tier, so dragging one school back to
where it started removes its override rather than leaving a no-op behind. The
saved list stays a short record of decisions instead of a frozen copy of the
whole roster — which would silently pin the config to today's built-in tables.
Entries are written longest-name-first because matching is substring and
first-match-wins.

Same flow from the command line, without the UI:

```bash
# Generate a standard from a JD and score real candidates against it
uv run python scripts/try_job_profile.py tests/fixtures/job_descriptions/sales.txt

# Re-check a hand-written / saved profile, no LLM call
uv run python scripts/try_job_profile.py --profile tests/fixtures/profiles/sales.json
```

Exits non-zero on a profile that fails validation, so it can gate a script.

`/preview` is the honesty check: it scores real candidates through the
keyword-only path (no LLM calls, seconds not hours) and warns when the standard
cannot discriminate. Warnings are mutually exclusive by root cause — when the
hard filter rejects everyone, the flat scores and single-tier distribution are
symptoms of that one problem, and reporting all of them sends the reviewer
chasing three fixes instead of one.

### Tier cache is keyed per profile

`get_cached_llm_tier` / `store_llm_tier_cache` take a `prompt_key`, defaulting
to `TIER_CLASSIFY_PROMPT_MD5` so existing rows and callers are unaffected. A
profile passes `dp:{fingerprint()}` instead: the same candidate scored for a
sales role and an accounting role has two different correct tiers, and a single
global cache column would happily serve one for the other. Editing a profile
changes its fingerprint, which invalidates the tiers it produced — the same
mechanism that already guards the AI prompt.

### Picking majors

A profile's `tier1_majors` / `tier2_majors` start empty, which left an operator
recalling and typing every relevant department name into a comma-separated box.
`major_catalogue()` in `app/scoring/education.py` groups ~89 common Taiwanese
departments into six fields (資訊 / 理工 / 商管 / 人文社會 / 設計藝術 / 醫護生農),
served by `GET /api/scoring-config/major-catalogue`; the profile editor renders
them as clickable chips under the two chosen-major lanes.

Like the school roster, it is a **picker vocabulary, not a matcher** — a major
absent from it still scores through the profile's own lists. Entries are stored
without a 系/學系 suffix so `_major_matches` can do its containment work; a test
asserts every catalogued name matches both `<name>學系` and
`<name>學系碩士班`, since a picker offering majors the matcher cannot use would
silently score nothing.

Each field carries a **全選** button, since 資訊 alone is 14 chips. It flips to
**全部移除** once the whole field is in the target lane, so the same control
undoes itself; a *partial* selection fills up rather than clearing, because the
label in that state still reads 全選. A bulk add appends in catalogue order
rather than reusing `addMajor`, which unshifts and would leave the group
reversed.

**A major lives in exactly one lane.** `addMajor` strips it from the other lane
first: listed in both, it would be double-counted and the two tiers would
contradict each other. Clicking a catalogue chip already chosen removes it, so
the same click undoes a mistake.

### Chinese major matching

`major_relevance_by_profile` cannot use plain substring matching: Chinese majors
are written both in full and abbreviated ("企管" vs "企業管理學系"), and neither
string contains the other. `_major_matches` strips degree suffixes and checks
containment both ways, then falls back to an ordered-character abbreviation
match. Requiring *order* is what stops 資管 matching 管理資訊.

## Accounts, roles, and PII grading

API keys answer "may this caller write?" and nothing else. They cannot answer
the question a company has about a resume database — *which employee* read an
applicant's phone number, and were they meant to be able to. A shared key has
no person behind it, cannot be revoked for one individual, and grades nobody.

`app/accounts.py` adds named accounts on top of the keys without removing
them: scripts, the worker and CI keep using `API_KEYS`.

### Two independent axes

| Axis | Question | Values |
|---|---|---|
| **Role** | what actions are permitted | viewer / interviewer / recruiter / admin / root |
| **PII level** | how much identity the answer contains | masked / partial / full |

They are deliberately not one ladder. An interviewer writes a scorecard while
seeing a masked name; an auditor may need full contact details while being
unable to change a row. Folding them together forces one of those to be wrong.

`ROLE_PERMISSIONS` is explicit sets, not `rank >= x`, for the same reason:
a recruiter may export the pool, an interviewer may not, and that is not a
statement about seniority.

**`admin:users` belongs to root alone.** It is the only permission that grants
permissions; an admin who could promote themselves makes the approval gate
decorative.

### Registration is a request, not an admission

Anyone may register; nobody is admitted by registering. A new account is
`pending` with role `viewer` and PII `masked` — it can authenticate, and every
data route refuses it. Only root approves, and approval is the moment a human
picks the role and the PII level.

The ordering is the whole point. If registration granted a default role and
root merely revoked the wrong ones, every gap in root's attention would default
to *more* access, and the window between signup and review would be an open
door.

Two guards on top:

- **No approving straight to root.** Creating a second root is legitimate, but
  not in the same click that first admits an unreviewed stranger.
- **The last active root cannot be demoted or suspended.** A system with no
  root can never approve anyone again, and there is no recovery through the
  API — only the CLI.

### The first root

Nobody can approve the first account, so it is created from the machine holding
the database — the same trust boundary as read access to the file:

```bash
python -m app.accounts_cli bootstrap-root --email you@company.com
python -m app.accounts_cli list
python -m app.accounts_cli promote-root --email other@company.com   # lockout recovery
```

The password is prompted, never passed as a flag: `--password` writes the
credential into shell history and into the process list.

Startup warns when `AUTH_ENABLED=true` and no root exists, because in that
state registrations pile up with nobody able to approve them.

### Sessions

`POST /api/auth/login` returns an HS256 JWT (`app/tokens.py`, hand-rolled for
the same reason `migrations.py` is — it is ~60 lines of `hmac` and `base64`).
Two things it does *not* do: it never honours the token's own `alg` field (the
classic forgery), and it never reads a claim before the signature verifies.

**The token's `role`/`pii` claims are ignored for authorisation.** They exist so
the UI knows which controls to draw. `_principal_from_session` re-reads both
from the database on every request, so a demotion by root takes effect on the
next call rather than at the next login.

**Revocation without a blacklist.** Each token carries the user's
`token_version`; a password change, suspension or grade edit bumps that column
and every token minted earlier stops validating. Status is checked *before* the
version, so a suspended user is told they were suspended rather than getting a
generic "invalid credentials" that sends them to reset a password that works.

### PII redaction

`app/pii.py` trims a candidate payload to the caller's level on the way out.

Redaction happens at the API layer, not in the query: the scoring pipeline
legitimately needs the full row, and masking in `database.py` would mean
auditing dozens of SELECTs while breaking scoring.

**Masked is a value, not a blank.** An emptied field makes "no data" and "not
permitted" indistinguishable — a real difference when someone is judging
whether a resume is incomplete. So redacted fields carry a visible marker
(`王＊＊`, `09＊＊＊＊＊678`) and a masked candidate keeps a stable handle
(`候選人 #42`). Scores, tiers, school and skills survive every level, so
ranking still works when identification does not.

Three things that would otherwise walk around the mask, and are closed:

- **Free text.** `self_introduction` opens "我是王小明" and quotes a phone
  number. Masking `name` while serving the same name one field down is the
  appearance of redaction, not redaction — so free text goes at `partial`, not
  just at `masked`. `skills_text` stays (it is a technology list).
- **The photo route.** `photo_url` is withheld below `full`, but the paths are
  predictable, so `/output/{path}` refuses below `full` too. Otherwise a masked
  account is one guessed URL from a face to go with the scores.
- **Export.** It has its own `export` permission and is redacted to the
  exporter's level. Once a spreadsheet of contact details is on a laptop, no
  permission change pulls it back.

`birth_year`/`age` are treated as identity: joined to a school and a graduation
year they re-identify someone with no name present.

### Endpoints

```
POST /api/auth/register            create a pending account
POST /api/auth/login               credentials → session token
GET  /api/auth/config              what the login screen needs (no credentials)
GET  /api/auth/me                  caller's own role, PII level, permissions
POST /api/auth/me/password         change own password (invalidates sessions)

GET  /api/admin/users              list + per-status counts        (root only)
POST /api/admin/users/{id}/approve activate at a chosen role/level (root only)
POST /api/admin/users/{id}/reject  refuse an application           (root only)
PUT  /api/admin/users/{id}/grade   change role and/or PII level    (root only)
PUT  /api/admin/users/{id}/status  suspend / reinstate             (root only)
GET  /api/admin/user-audit         who granted whom what, and when (root only)
```

`user_audit` is separate from `access_audit` on purpose: that one answers "who
read this applicant's data", this one "who granted them the ability to". Mixed
together, the second is unfindable inside the volume of the first.

Frontend at `/login` (login + application form) and `/users` (root's approval
queue). Nav links filter on permission, but that is presentation — the route
guard and the server refuse the same navigation regardless.

**`AUTH_ENABLED=false` is unchanged.** Both dependencies fall open, `/me`
reports `kind: "anonymous"`, and the frontend skips the login flow entirely, so
local development works exactly as before.

```bash
python3 tests/test_accounts.py   # 104 cases: approval guards, tokens, redaction
```

## LLM provider settings

The app addressed exactly one backend: LM Studio on localhost, read from
`os.getenv` at import time. Pointing it at OpenAI — or at a different local
model — meant editing `.env` and restarting, on the machine holding the
process. `app/llm_config.py` makes the provider an operator setting, edited at
`/llm-settings`.

Two independent sections, because the useful combination is real (a local chat
model with OpenAI embeddings, or the reverse, depending on which GPU is busy):

| Section | Drives | Providers |
|---|---|---|
| `chat` | resume extraction, AI-tier classification, JD → profile generation | `lmstudio` / `openai` |
| `embedding` | semantic similarity (20% of the score) | `lmstudio` / `openai` |

`lmstudio` means *any* OpenAI-compatible local server — LM Studio, Ollama,
vLLM, llama.cpp. The wire format is identical; the only real difference is
whether a key is required.

The UI calls it **地端模型**, not "本機 (LM Studio)": naming one vendor made the
other three look unsupported. The stored value stays `lmstudio` — it is the API
contract and the key half of `MODEL_CATALOGUE`, so renaming it would invalidate
every saved config for a label change.

| Endpoint | Purpose |
|---|---|
| `GET /api/llm-config` | Active config (secrets masked), defaults, env-pinned fields |
| `PUT /api/llm-config` | Validate and persist (`write:scoring`) |
| `POST /api/llm-config/validate` | Check without saving — inline UI validation |
| `POST /api/llm-config/test` | Send one tiny real request to the backend |
| `POST /api/llm-config/reset` | Restore defaults, clearing stored keys |

Stored as one JSON document in `app_settings`, like the email templates: the
whole set is read and written together, and it is a handful of fields rather
than a queryable collection.

### Design decisions

- **Precedence is environment > stored document > default**, matching
  `app/settings.py`. A deployment that pins `LM_STUDIO_URL` in its systemd unit
  must not be silently overridden by a row someone saved in the UI months ago.
  `env_pinned()` reports which fields the environment owns and the page renders
  those read-only — an edit that cannot take effect is better refused than
  accepted and ignored.
- **The shipped `.env` pins none of them.** Every `_ENV_MAP` field
  (`LM_STUDIO_URL`, `LM_STUDIO_MODEL`, `MODEL_CONTEXT_LENGTH`,
  `RESPONSE_TOKENS`, `EMBEDDING_URL`, `EMBEDDING_MODEL`) is commented out in
  `.env` / `.env.example`, so `env_pinned()` returns empty lists and the whole
  of `/llm-settings` is editable. These are *user* settings, and their home is
  `app_settings.llm_config`; a value in `.env` makes the page look configured
  while ignoring what the operator types. The overlay stays in the code as the
  deployment escape hatch — uncomment a line to re-pin that one field.
  `TIER_MARKDOWN_CHARS` is still env-only because it has no UI control.
- **The connection test does *not* apply the environment overlay.** Everywhere
  else it wins; here it would test a different endpoint than the one displayed
  and report the result as though it belonged to the typed config — a green
  tick for a URL never contacted. What is testable is what is editable.
- **A masked key echoed back means "keep the stored one".** The client is never
  sent the credential, so `save()` resolves `MASK` to the stored value; without
  that, submitting an untouched form would overwrite the key with four bullet
  characters. `/test` resolves it too, or "test" would verify a credential made
  of bullets.
- **Secrets are excluded from `config_version()` entirely, not masked.** Masking
  still distinguishes "a key is set" from "no key", so merely *adding* a
  credential would invalidate every cached tier for no change in output.
- **The tier cache key covers the model, not just the prompt.**
  `tier_classifier_key()` folds provider+model into `TIER_CLASSIFY_PROMPT_MD5`.
  A tier is one model's judgement under one prompt; keying on the prompt alone
  was correct while there was one backend, but would now serve a local 7B's
  tiers unchanged after a switch to GPT-4o, and the operator would see the old
  distribution and conclude the switch did nothing. **The default config
  reproduces the bare prompt hash exactly**, so the 3179 existing cached rows
  stay valid and this change invalidates nothing on its own. Switching model
  marks tiers stale, which `POST /api/jobs/rescore {"mode":"stale"}` picks up.
- **The `thinking` payload field is withheld from OpenAI.** It disables Qwen3
  chain-of-thought on local servers, which accept unknown keys; the OpenAI API
  400s on an unrecognised body field.
- **The cloud model name is a dropdown, not free text.** OpenAI routes on the
  name, so "which model" is a choice from a list there, and a typo
  (`gpt4o-mini`) surfaces as a 404 mid-scoring-run rather than on this page.
  `MODEL_CATALOGUE` in `llm_config.py` supplies the options, served by
  `GET /api/llm-config` as `model_catalogue`. **It is a suggestion list, never a
  whitelist** — `validate()` does not check the model against it, and the
  dropdown carries a 自訂 row that reveals the free-text field. OpenAI ships
  names faster than this file is edited, and a page that refused a model the
  API accepts would be worse than one that lets a typo through.
  `test_llm_config.py` asserts every catalogued entry passes `validate()`, so
  the picker cannot offer a choice the save button rejects.
- **The local list is reference formats, the cloud list is choices.** LM Studio
  runs whichever model the operator downloaded, so its entries cannot claim what
  is installed — they show the *shape* of an LM Studio identifier
  (`qwen2.5-7b-instruct`: family-size-purpose) so someone copying a name out of
  the LM Studio UI can tell whether theirs looks right. Hence `default_model()`
  returns **blank** for `lmstudio`/`chat` despite the list being non-empty:
  blank means "use whatever is loaded", which is valid and right more often than
  any one name, and pre-selecting an entry would name a model they may not have.
  `LLMSettingsView.vue`'s own `defaultModel()` mirrors that rule — the two
  drifting would pin a local install to a model it cannot load.
- **The free-text box explains the format, the dropdown explains the model.**
  A chosen preset shows its cost/speed note; 自訂 replaces that with the naming
  rule for the current provider, since that is the thing being got wrong at the
  moment someone is typing.
- **Switching provider replaces a *picked* model but keeps a *typed* one.**
  A local model name means nothing to OpenAI, so carrying it across is a request
  that always 404s — but a hand-typed name is the operator's own work, so only a
  name they selected off the old provider's list is swapped for
  `default_model()`. The default is filled in rather than blanked because a
  blank model is invalid for OpenAI and for every embedding section: the form
  would arrive unsaveable.
- **The shipped embedding default is the catalogue's first entry**, so a fresh
  install opens with the dropdown on a real option instead of on 自訂, which
  would read as misconfigured before anyone had touched it.
- **A blank model means different things per provider.** LM Studio serves
  whichever model is loaded, so blank is a legitimate "use that one"; OpenAI
  routes on the name, so validation requires it there. Embeddings always
  require a name — no server we target has a loaded-model fallback for them.
- **A bare host is accepted.** `http://192.168.0.84:1234` is what an operator
  copies out of LM Studio's UI, so `endpoint()` appends the `/v1/...` path
  rather than POSTing to a host with no route.
- **The 服務網址 box is pre-filled with the URL actually in use, not left
  blank.** A stored-blank `base_url` legitimately means "use the provider's
  default", but it rendered as an empty field with grey placeholder text —
  indistinguishable from *unconfigured*, and offering nothing to click into and
  edit. `apply()` fills it from the response's `resolved`, which is the endpoint
  the server reports it is calling, so the box cannot display a URL different
  from the one requests go to. `setProvider` refills it with the new provider's
  default instead of blanking it, for the same reason. Saving then persists the
  URL literally rather than as a blank; this is inert — `endpoint()` resolves
  both to the same string, and `tier_classifier_key()` folds in provider+model
  but **not** the URL, so no cached tier is invalidated by it.
- **`validate()` rejects `response_tokens >= context_length`.** `_truncate_to_fit`
  subtracts one from the other; inverted, every resume collapses to the
  500-char floor and scoring silently reads almost nothing — the same failure
  mode as the old 4096 default.
- **The settings endpoints are gated on write, not read.** They disclose
  internal endpoints and which credentials exist — infrastructure detail rather
  than candidate data.
- Module constants (`LM_STUDIO_URL`, `EMBEDDING_URL`, `RESPONSE_TOKENS`, …)
  remain as the environment defaults, so `scripts/` and the tests are
  unaffected. `llm.py` and `embeddings.py` resolve the live values **per call**,
  so a change applies to the next request rather than the next restart.

```bash
python3 tests/test_llm_config.py   # 64 cases: resolution, masking, precedence, cache keys, model catalogue
```

## Email templates

`app/email_templates.py` renders reusable letter drafts (面試邀約 / 婉謝 / 補件)
with a candidate's own details filled in. **The system never sends mail.** It
produces a subject and body, and the operator copies them into whatever mailbox
the company actually sends from — no SMTP credentials to manage, and no
candidate contact details handed to a third-party relay.

Templates live as one JSON document in `app_settings` rather than a new table:
the whole set is read and written together by the settings page, and it is a
handful of rows, not a queryable collection.

| Endpoint | Purpose |
|---|---|
| `GET /api/email-templates` | Templates + sender block + variable vocabulary |
| `PUT /api/email-templates` | Save the whole set (`write:scoring`) |
| `POST /api/email-templates/reset` | Restore the built-in starter templates |
| `POST /api/candidates/{id}/compose-email` | Render one template for one candidate |

Frontend: 信件範本 at `/email-templates` edits them; the 寄信 button on the
candidate detail page composes one.

### Design decisions

- **Compose is gated on `full` PII, not merely `read`.** The rendered body
  legitimately contains the candidate's name and email, so returning it to a
  `partial`/`masked` principal would hand back through the letter exactly what
  `redact_detail()` withholds from the profile — the redaction layer would be
  decorative.
- **A misspelt variable stays visible; an empty one does not.** `{{nmae}}`
  renders as `⟨未知變數: nmae⟩` because it is an author error that must be seen
  before the letter goes out. An empty *known* variable (a candidate with no
  English name) renders blank, since marking it would put noise in every letter.
  `missing_variables` reports the blanks so the composer can warn instead.
- **Validation rejects an empty subject/body, but never an unfinished
  variable.** An operator mid-word has typed `{{na`; refusing to save at that
  moment loses their work. Unknown names are a warning, not an error.
- **The variable picker and the renderer cannot drift.** Every key in
  `VARIABLES` must be produced by `build_context()`, and the tests assert it —
  a picker offering a variable the renderer does not fill would teach the
  operator to write broken letters.
- **School/major fall back to the parsed `education` rows.** Those candidate
  columns are frequently blank while the rows are not.
- **The quoted interview is the soonest *upcoming* one**, not the most recently
  created: an invitation is about the next meeting, and quoting a past date is
  worse than quoting none.
- **Editing templates needs `write:scoring`, not `write:interview`.** A
  template change alters what every recruiter sends out, which is a
  settings-level action rather than a per-candidate one.

In `EmailTemplatesView.vue`, placeholders shown as UI text are built via
`ph(key)` rather than written literally — a `{{…}}` inside Vue markup is parsed
as an interpolation and fails the build.

```bash
python3 tests/test_email_templates.py   # rendering, validation, picker/renderer parity
```

## Background jobs

Scoring is durable work, not a request-lifetime side effect: 3179 candidates ×
one LLM call each is hours. `POST /api/candidates/batch-match` used to push
that into FastAPI `BackgroundTasks`, which run in the server's event loop after
the response — no progress, no cancellation, everything lost on restart.

`app/jobs.py` is a SQLite-backed queue (no Redis/Celery — this app deploys as
one process beside its DB file). `app/jobs_scoring.py` holds the rescore
handler; `app/jobs_routes.py` the API.

| Endpoint | Purpose |
|---|---|
| `POST /api/jobs/rescore` | Enqueue rescoring (`mode`: `stale`/`unscored`/`degraded`/`all`/`ids`) |
| `GET /api/jobs` | List, filterable by `status` / `job_type` |
| `GET /api/jobs/{id}` | Detail with progress counters |
| `POST /api/jobs/{id}/cancel` | Cooperative cancel |
| `GET /api/scoring-status` | How current the stored rankings actually are |

**Claiming** is a single `UPDATE ... WHERE id=(SELECT ... status='queued') AND
status='queued'`. The repeated predicate is the safety: two workers may pick the
same id in their unlocked sub-SELECTs, but SQLite serialises the writes and the
loser matches 0 rows. The winner stamps a unique token so its read-back cannot
return some other row it owns.

**Resumability.** A batch job checkpoints `cursor` after each item, so a killed
worker resumes from the next unprocessed candidate instead of redoing the
batch. Jobs stuck in `running` with no heartbeat for `STALE_RUNNING_SECONDS`
(900s) are requeued with counters intact. Failures retry with exponential
backoff up to `max_attempts`, recording `last_error`.

**Where workers run.** In-process daemon threads by default
(`JOB_WORKER_INPROCESS=true`), so plain `uvicorn main:app` still drains the
queue — today's single-process experience. For a dedicated worker:

```bash
JOB_WORKER_INPROCESS=false uv run python -m uvicorn main:app --port 8000
uv run python -m app.worker_queue      # honours JOB_CONCURRENCY / JOB_POLL_INTERVAL
```

## Scoring provenance

`_classify_tier` catches every exception and falls back to keyword-only
classification, and the embedding service degrades to keyword overlap. Neither
left a trace, so a score written while LM Studio was down was indistinguishable
from a good one. `match_results` now records:

| Column | Meaning |
|---|---|
| `scoring_mode` | `full` / `degraded` / `unknown` (predates provenance) |
| `degraded_reasons` | JSON list: `llm_tier_fallback`, `embedding_unavailable`, `semantic_error` |
| `scoring_config_version` | `app.scoring.config.config_version()` |
| `tier_prompt_md5` | `app.llm.TIER_CLASSIFY_PROMPT_MD5` |
| `scored_at` | When this result was produced |

Existing rows stay `unknown` rather than being back-filled as `full` — they
genuinely predate provenance, and claiming otherwise would make the flag
worthless. `/api/candidates`, `/api/candidates/{id}/match` and `/scorecard`
expose `scoring_mode`, `is_degraded`, `degraded_reasons` and `tier_is_stale`.

**Re-run only the bad rows:** `POST /api/jobs/rescore {"mode": "degraded"}`.

### Stale AI tiers

`GET /api/scoring-status` surfaces what the cache-invalidation logic already
knew but never showed. As of this writing all 3179 candidates carry prompt hash
`5d85e24efd54` while the live prompt hashes to `0f47676362b3`, so **every**
cached tier predates the current classifier — which is why the distribution is
98.2% Tier 1 with no Tier 0 at all. Re-running a sample under the current prompt
immediately produced tiers 0/1/2/2/3/2, i.e. the spread the ranking is missing.

Fixing it is one call (hours of GPU time — the operator's decision):

```bash
curl -X POST localhost:8000/api/jobs/rescore \
     -H 'Content-Type: application/json' -d '{"mode":"stale"}'
```

Note `_run_match` in `app/routes.py` calls `run_full_scoring` **without** a
`db_conn`, and that argument is what enables the LLM tier path at all — so the
upload/batch path currently scores keyword-only. The job runner passes its own
connection, so rescoring through the queue does use the LLM.

## Single upload vs. batch import

The two ingest paths are not interchangeable, and picking the wrong one fails
in a way that looks like success.

| Path | Handles | Splits candidates? |
|---|---|---|
| `POST /api/upload` (the 上傳履歷 button) | **one** resume | no |
| `scripts/batch_import.py` | 104 bulk exports | yes, via `split_candidates` |

`ingest_pdf()` inserts whatever it parses as a **single** candidate. The 104
exports in `data/` are 595-746 page bundles holding ~200 applicants each, so
uploading one through the UI does not error — it merges hundreds of people into
one row. It also drove Marker to ~24GB RSS on a 601-page file, exhausting RAM
and swap and wedging the API process until it was killed.

**Size cannot distinguish the two.** A genuine 104 resume is already 131-162MB,
which is why `MAX_UPLOAD_BYTES` is 200MB. The page count is the discriminator,
so `_reject_bulk_pdf` rejects an upload over `MAX_UPLOAD_PAGES` (40) with a 422
naming `batch_import.py`. A PDF whose page count cannot be read is allowed
through: the parser gives a better error for a damaged file than a guess here.

```bash
# A bulk export - 200 candidates, ~2.6GB RAM, minutes not hours
uv run python scripts/batch_import.py data/6.pdf --parser-backend plumber
```

`--parser-backend plumber` matters for bundles: Marker loads the whole document
into host memory, while pdfplumber streams it. These exports are digital 104
printouts with a real text layer, so OCR buys nothing.

The upload modal now shows the server's own `detail` instead of a fixed
"請確認檔案格式" line — the format was usually fine, and the generic message
sent the operator to inspect the PDF rather than read the reason.

### Deleting a batch, and seeing what failed

```
DELETE /api/import-batches/{id}   {"delete_candidates": false}
```

**The record and the people it produced are deleted separately.** Removing a
mis-attributed or duplicated batch should not destroy resumes that parsed
correctly, so the default *detaches* candidates (`import_batch_id = NULL`);
their `source_pdf_path` survives, which is what `repair_import_batches.py`
needs to rebuild attribution. Deleting the candidates too is a second checkbox
in the confirmation dialog, and it is irreversible.

The checkbox resets every time the dialog opens: a "delete the people too" from
a previous batch must not carry silently into the next one.

The two read endpoints (`GET /api/import-batches` and `.../{id}`) previously
had **no** auth dependency while the sibling candidates route required
`read` — they now take `require_read`, and delete takes `require_write`.

**Parse failures are recorded, not just printed.** `import_pdf` used to `print`
an exception and, if `parse_pdf` itself raised, abort the whole run — leaving
`import_files` empty. /imports then showed a batch that looked clean while its
candidates were silently missing, which is exactly the "I can't tell where it
went wrong" case. Now each PDF writes a row via `record_import_attempt`:

| `parse_status` | Meaning |
|---|---|
| `parsed` | every candidate in the PDF was inserted |
| `partial` | the PDF parsed, but some candidates failed (first 20 errors kept) |
| `failed` | the PDF could not be parsed at all; the exception is stored |

A failing PDF no longer stops the ones after it. `batch_import.py` also
attributes what it imports to a batch (`--batch-name`, default
`批次匯入 <today>`); previously it left `import_batch_id` NULL and the
candidates appeared on /imports as an unattributed group.

The batch card shows a red "N 個 PDF 解析失敗" banner, and expanding the file on
the detail page shows the stored error verbatim — it names the actual cause (a
damaged PDF, a scan with no text layer), which is what decides whether to
re-export or switch `--parser-backend`.

## Import history

Every import is recorded as an **import batch** (`import_batches`), and each PDF
inside it as an **import file** (`import_files`). Candidates carry
`import_batch_id` / `import_file_id`, so the exact parse run that produced a
candidate stays traceable.

Two kinds of batch, distinguished by `import_batches.status`:

| status | Source | Attribution happens in |
|---|---|---|
| `organized` | 104 ZIP import | `scripts/organize_resume_db.py` |
| `uploaded` | Single PDF via `POST /api/upload` | `register_upload_source()` at ingest time |

Uploads are grouped **by calendar day** — one batch named `手動上傳 YYYY-MM-DD`
per day, with each uploaded PDF as its own file row under it. Without this,
uploaded candidates got `import_batch_id = NULL` and appeared as one
indistinguishable group. Upload batches have no dedupe verdicts (that only runs
in the organize step), so the UI shows "尚未執行去重比對" rather than zeros.

The frontend surfaces this at `/imports`: batch list → PDF files in a batch →
candidates parsed from that PDF → candidate detail page.

```
GET /api/import-batches            # all batches with dedupe counts
GET /api/import-batches/{id}       # one batch + its per-PDF parse results
GET /api/import-files/{id}/candidates
GET /api/candidates?batch_id=&file_id=
```

`organize_resume_db.py` scopes a batch to the PDFs under its own `--extract-dir`
/ `--output-root`. Without that scope it relabels **every** candidate in the DB
into the batch being organized, which is what silently moved an earlier batch's
candidates into a later one. `--reassign-all` restores the old whole-table
behaviour when that is genuinely wanted.

To repair batch attribution damaged by an older run (candidates keep their
`source_pdf_path`, so the correct batch is recoverable):

```bash
python scripts/repair_import_batches.py --db resume_ai.db --dry-run
python scripts/repair_import_batches.py --db resume_ai.db
```

## Frontend reads the backend's vocabulary, not its own copy

Four pieces of business logic had drifted into `.vue` files as hardcoded
tables. Each looked like harmless UI data and each was a second source of truth
for something the backend already owned — which is how a screening rule ends up
being two different rules depending on which page you look at.

| Was hardcoded in | Now comes from | Why it mattered |
|---|---|---|
| `CandidateTable.vue` — ~50 school-name keywords | `school_tier` on each row | 學校分級 overrides were invisible to the filter |
| `FilterPanel.vue` — four AI tier names | `ai_tiers` from `/api/filters` | every non-AI role showed "RAG Architect" |
| `CalendarView.vue` — three interview types | `interview_types` table | statuses beside them were already editable |
| `CandidateTable.vue` — six degree keywords | `degree_rank` on each row | 四技/博士班 matched nothing |

### 頂尖大學 is a tier, not a name list

The 頂尖大學 filter matched a keyword list maintained in the table component.
`school_tier()` — which the scoring pipeline and both hard-filter gates already
share — reads `education.school_overrides` first, so dragging a school in
學校分級 moves it in the ranking. It could not move it in this filter: the list
was frozen at build time. Promoting 逢甲大學 to A moved 67 candidates in the
scoring and none in the filter, with nothing to indicate the two disagreed.

Rows now carry `school_tier` (A/B/C/D) computed by that same function, and the
component compares against `'A'`. `GET /api/candidates?min_school_tier=` gates
server-side using the identical ladder, for callers that want the filtering done
before serialization.

Both live in `app/database.py` as `best_school_tier()` / `meets_school_tier()` —
dict-shaped twins of `hard_filter._best_school_tier`, which takes
`EducationExtract` objects the list query does not have. They call the same
`school_tier()`, so they cannot rate a school differently. `meets_school_tier`
repeats the gate's two asymmetries deliberately: **no parsable school fails**,
and **an unrecognised tier gates on nobody** rather than on everybody.

`min_school_tier` joins `candidate_type` as a filter that cannot be pushed into
SQL — the override list makes it a function call, not a fixed set of names — so
both are applied after the fetch, with the page cut afterwards so `total` stays
truthful.

### Tier names belong to the job

`TierBadge` already accepted a `tier_label` prop and all three call sites passed
`experience_detail.tier_label`, so badges were right. The **filter dropdown** was
not: it carried its own copy of the AI ladder. Scoring the active job (which has
a domain profile) rendered a dropdown reading "T2 - RAG Architect" next to
badges reading 「獨立專案開發者 / 模型工程師」.

`/api/filters` now returns `ai_tiers` from the active job's profile, falling
back to `config.tier_labels()` — so an operator rename on /scoring is honoured —
and to the AI four only when no profile is attached, which is exactly when the
pipeline runs the AI scorers.

### Interview types are operator vocabulary

`interview_statuses` was an editable table with CRUD; `interview_type` was a
`TEXT` column whose three values lived only in `CalendarView.vue`. Same form,
one editable, one needing a rebuild to add 「線上測驗」. `interview_types` mirrors
the statuses table and is seeded with `phone`/`video`/`onsite`, so existing rows
resolve unchanged.

- **`value` is separate from `label`.** The value is a foreign key in every
  scheduled interview; the label is display text someone may reword. Deriving
  the value from the label on every edit would orphan rows.
- **A Chinese label slugifies to nothing**, so `create_interview_type` falls back
  to a synthetic `type-{id}` rather than an empty key.
- **Deleting a type does not touch interviews using it.** An interview that
  happened as a phone screen still did; rewriting that to tidy a list destroys
  the only record of it.
- **Colours are stored as names, not Tailwind classes.** A class string in a data
  column is markup in the database, and breaks silently when a utility is
  renamed; `CalendarView` maps the name to classes.

### Degree level comes from the ladder that gates on it

The 大學/碩士 columns picked rows with six keywords that knew nothing of
四技/二技 (a bachelor's), 五專 (associate) or 博士班 (a doctorate) — so a
university-of-technology graduate showed a blank 大學 column and a PhD appeared
in neither. `annotate_degree_levels()` tags every row with `degree_rank` via
`normalise_degree()`, the same ladder `min_education` gates on, reading
`department` when `degree_level` is blank as that gate does.

A doctorate counts as postgraduate for the 碩士 column: the alternative is
showing someone's highest qualification nowhere. A narrow keyword check survives
for splitting a `department` string that packs both degrees into one field —
`degree_rank` describes the row, not each comma-separated part.

## 實習 / 正職 classification

`calc_candidate_type()` in `app/database.py` derives each candidate's hiring type
(實習 = intern, 正職 = engineer). It is computed on read, not stored, so changing
the rule takes effect without a migration. The frontend renders 正職 as「工程師」.

A candidate is 實習 if they are either **still studying**, or **graduated but
never actually started working**. Inputs: `education.status` / `date_start` /
`date_end`, the work history, and two candidate fields — `work_type` (the
applicant's own 求職身份) and `years_of_experience`.

**Still studying** — enrolled in their **highest-level** programme with a
graduation date not yet past:

- Only the highest degree counts. A 大學畢業 candidate with a leftover 高中
  `就學中` row is an engineer, not an intern.
- A graduation date already past means the programme finished, even if 104 still
  says `就學中` (the resume was written before graduating). The graduation month
  itself still counts as enrolled, since 104 stores only year/month.
- An in-school row with an unparsable `date_end` no longer forces 實習; the
  applicant's `work_type` and experience decide.
- `work_type` is an explicit declaration. Wanting only 實習/工讀 with no career
  track record yields 實習; asking for 全職 yields 正職 once the applicant is
  within `NEW_GRAD_HORIZON_MONTHS` (12) of graduating — i.e. a new grad.
- Bare `肄業` (dropped out) is not enrolled; `肄業中` is.

**Graduated, no career yet** — `has_only_student_work()` checks whether *every*
work record is student work. If so (and `years_of_experience` is still junior),
the candidate stays 實習 rather than being ranked against working engineers. A
record counts as student work when either:

- the title names it — `STUDENT_JOB_KEYWORDS` (實習/工讀/intern/學生/研究助理/
  兼任/助教/獎助生/產學…); or
- it started inside the highest-degree study period **and** ended within
  `STUDENT_JOB_TAIL_MONTHS` (6) of graduation.

That second condition needs both halves. A job started in the final year but
still running years later is a real career — checking overlap alone
misclassified 61 working engineers.

An **empty** work list is deliberately *not* treated as "never worked": 1652
candidates have no parsed work rows, many with years of stated experience, so
that reading would sweep in every resume whose work section failed to parse.

Every query returning `candidate_type` must select `work_type`,
`years_of_experience`, `education.date_start` and the work rows
(`job_title`, `job_category`, `date_start`, `date_end`), otherwise the
classification silently degrades to the education-only path.

```bash
python3 tests/test_candidate_type.py   # 39 cases, dates pinned so results don't drift
python3 tests/test_domain_profiles.py # 78 cases, cross-domain scoring
```

## Project structure

```
main.py                  # FastAPI app entrypoint
app/
  routes.py              # API endpoints
  database.py            # SQLite helpers + calc_candidate_type (實習/正職)
  models.py              # Pydantic models
  document_parser.py     # Marker PDF→Markdown parser
  regex_parser.py        # Regex-based resume field extraction
  parser_service.py      # Local/remote parse orchestration
  llm.py                 # Chat client (LM Studio / OpenAI)
  llm_config.py          # Runtime LLM provider settings (chat + embedding)
  worker.py              # Remote PDF parse worker (FastAPI micro-service)
  accounts.py            # User accounts, roles, PII grades, root approval
  accounts_cli.py        # bootstrap-root / list / approve / reset-password
  auth.py                # Credentials → Principal (sessions + API keys)
  auth_routes.py         # /api/auth/* and /api/admin/users/*
  tokens.py              # HS256 session tokens (sign/verify)
  pii.py                 # Redaction of candidate identity by PII level
  jobs.py                # Durable SQLite job queue (claim/retry/resume)
  jobs_scoring.py        # Rescore job handler + scoring-status report
  jobs_routes.py         # /api/jobs/* and /api/scoring-status
  job_profiles_routes.py # /api/job-postings/* (JD upload → scoring standard)
  email_templates.py     # Letter templates rendered per candidate (copy, not send)
  migrations.py          # Numbered, append-only schema migrations
  worker_queue.py        # Standalone job worker entrypoint
  scoring/               # Rule-based + LLM scoring pipeline
    domain_profile.py    # Per-role scoring standard (schema + validation)
    builtin_profiles.py  # The calibrated AI-engineer standard, as data
    profile_builder.py   # JD document → domain profile (LLM)
    generic.py           # Profile-driven scorers (any domain)
docs/SCORING_ALGORITHM.md # Scoring algorithm reference (calibration rationale)
scoring_config.json      # Runtime scoring overrides (created by the /scoring UI)
frontend/                # Vue 3 SPA (Vite)
  public/favicon.*                 # Tab icon; mirrors the navbar logo (#2563EB)
  src/views/ImportsView.vue        # Import batch list
  src/views/ImportDetailView.vue   # Batch → PDF files → candidates
  src/views/ScoringSettingsView.vue # Tune weights/tiers, drag schools between grades
  src/views/JobPostingsView.vue    # Job list + JD upload
  src/views/JobProfileView.vue     # Review/edit a generated scoring standard
  src/views/EmailTemplatesView.vue # Edit letter templates + sender block
  src/views/LLMSettingsView.vue    # Pick LM Studio / OpenAI, test the connection
  src/components/EmailComposeModal.vue # Render a letter for one candidate, copy it
  src/views/LoginView.vue          # Login + account application
  src/views/UsersView.vue          # Root's approval queue and grade editor
  src/stores/auth.js               # Session token, current role/PII level
scripts/                 # CLI utilities (batch import, dedup, repair, scoring)
  organize_resume_db.py            # Batch/file/dedupe metadata for an import
  repair_import_batches.py         # Fix batch attribution from source paths
  try_job_profile.py               # JD → scoring standard → score the pool (manual check)
tests/fixtures/
  job_descriptions/                # Synthetic JDs: accountant / marketing / sales
  profiles/sales.json              # Hand-written domain profile the tests load
job_requirement.json     # Default job requirement loaded at startup
```
