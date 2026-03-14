# Scoring Algorithm Reference

> Ground-truth documentation derived from source code.
> Files: `app/scoring/{pipeline,experience,education,engineering,skills,embeddings,hard_filter}.py`

---

## Overview — The 3-Layer Funnel

```
Raw Résumés
    │
    ▼
┌─────────────────────────────┐
│  Layer 0 · Hard Filter      │  Boolean gate — fail → score 10, exit
└─────────────────────────────┘
    │ pass
    ▼
┌─────────────────────────────┐
│  Layer 1 · Dimension Scores │  5 independent sub-scores (each 0–100)
│   S_AI · S_Eng · S_Edu      │
│   S_Semantic · S_Skill      │
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│  Layer 2 · Weighted Sum     │  S_Final = weighted sum, max 100
└─────────────────────────────┘
```

---

## Final Score Formula

```
S_Final = S_AI × 0.35 + S_Eng × 0.20 + S_Semantic × 0.20 + S_Edu × 0.15 + S_Skill × 0.10
```

| Dimension | Weight | Max contribution | Source |
|-----------|:------:|:---------------:|--------|
| S_AI — AI experience depth | **35%** | 35 pts | LLM 3-tier pyramid |
| S_Eng — Engineering maturity | **20%** | 20 pts | Keyword capability matrix |
| S_Semantic — Semantic similarity | **20%** | 20 pts | Embedding cosine similarity |
| S_Edu — Education background | **15%** | 15 pts | School + degree + major |
| S_Skill — Skill verification | **10%** | 10 pts | Ecosystem + cross-reference |

---

## Layer 0 · Hard Filter

**Source:** `app/scoring/hard_filter.py`
**Result:** pass/fail. Fail → `overall_score = 10`, pipeline exits.

| Rule | Logic |
|------|-------|
| `required_skills` | **ALL** skills in list must appear in résumé text |
| `required_frameworks` | **At least ONE** framework must appear |
| `required_keywords` | **At least ONE** keyword must appear |
| `must_have_groups` | Each group: at least N of the listed skills must match |

Search scope: `raw_markdown` + `skill_tags` + `job_description` + `job_title` + `job_skills` (combined, case-insensitive).

Set `"hard_filters": {}` in `job_requirement.json` to disable all gates and score every candidate.

---

## S_AI — AI Experience Depth (35%)

**Source:** `app/scoring/experience.py`, `app/llm.py`

### 3-Tier Pyramid

| Tier | Label | Base score | Profile |
|------|-------|:----------:|---------|
| 1 | Wrapper | 60 | API callers, prompt engineers, Streamlit/Gradio demos |
| 2 | RAG Architect | 80 | RAG pipelines, vector DBs, agent loops, hybrid search |
| 3 | AI Expert | 100 | Model training/fine-tuning (LoRA, DPO, SFT, RLHF), inference optimization (vLLM, CUDA, TensorRT-LLM), published ML research |

### Tier Classification — LLM Primary, Keyword Fallback

```
classify_experience_tier_llm()
    │
    ├─ 1. Check DB cache (keyed on MD5(raw_markdown) + TIER_CLASSIFY_PROMPT_MD5)
    │       hit  → use cached tier
    │       miss → call LLM
    │
    ├─ 2. LLM call (app/llm.py · classify_ai_tier)
    │       Input:  work_experiences JSON + skill_tags
    │               + raw_markdown[:3000] (if _INCLUDE_RAW_MARKDOWN = True)
    │       Temp:   0.1    Max tokens: 512
    │       Output: { tier, tier_label, confidence, evidence,
    │                 anti_inflation_flags, reasoning }
    │       Store result → DB cache
    │
    └─ 3. Fallback (LLM unavailable or no candidate_id/db_conn)
            → classify_experience_tier()  [keyword-only]
```

**LLM anti-inflation rules (applied at classification time):**
- `PyTorch` in skills with zero training context → max Tier 2
- `HuggingFace` used only to load a model, no fine-tuning → max Tier 2
- Vague "deep learning project" with no metrics or architecture → Tier 1 or 2
- Published at ICASSP / NeurIPS / CVPR / ICLR / ACL (even co-author) → Tier 3 minimum

### Keyword Fallback — Tier Thresholds

```
TIER3_MIN_WEIGHT = 3.0
TIER2_MIN_WEIGHT = 2.0

tier_3_weight >= 3.0            → Tier 3
tier_3_weight > 0               → Tier 2   (T3 signal present, below threshold)
tier_2_weight >= 2.0            → Tier 2
tier_2_weight > 0               → Tier 2
else                            → Tier 1
```

Threshold weights are computed from the **full combined corpus** (evidence + tags), unweighted.

### Position-Weighted Stack Score

Keywords are detected in two separate corpora with different weights:

| Source | Weight |
|--------|:------:|
| Job descriptions, job titles, job skills, raw_markdown | 1.0× |
| Skill-tag header only (not found in any work entry) | 0.4× (`TAG_WEIGHT_FACTOR`) |

This prevents inflating the `stack_bonus` by stuffing keywords in the skills section without demonstrating them in work history. **Tier thresholds are unaffected** (still use combined corpus at full weight).

### Keyword Weights (selected)

**Tier 3:**

| Keyword | Weight |
|---------|:------:|
| vLLM, TensorRT-LLM, TensorRT, CUDA, Flash Attention | 2.5 |
| RLHF, KV Cache, Speculative Decoding, DeepSpeed, Megatron, Model/Tensor Parallelism | 2.0 |
| LoRA, QLoRA, PEFT, DPO, Fine-tuning | 1.8 |
| PyTorch, HuggingFace, SFT, Quantization, GGUF, AWQ, GPTQ, BitsAndBytes | 1.5 |
| Llama, Mistral, Gradient, Learning Rate, Loss Function, Backpropagation | 1.2 |
| Training | 1.0 |

**Tier 2:**

| Keyword | Weight |
|---------|:------:|
| RAG, Retrieval Augmented, GraphRAG | 1.8 |
| Vector Database, Milvus, Qdrant, Weaviate, Reranking, Hybrid Search, HyDE | 1.5 |
| LangGraph, Function Calling, ReAct | 1.5 |
| Embedding, Agent, LlamaIndex | 1.2 |
| Context Window, Hallucination | 1.2 |

### Score Calculation

```
S_AI = min(base_tier + stack_bonus + complexity_bonus + metric_bonus, 100)
```

| Component | Formula | Cap |
|-----------|---------|:---:|
| `base` | Tier base score (60 / 80 / 100) | — |
| `stack_bonus` | `min(total_weighted_keyword_score × 2, 10)` | +10 |
| `complexity_bonus` | sum of complexity signal matches × (0.33 or 0.34) | +5 |
| `metric_bonus` | quantified metric matches × 0.25 | +5 |

**Complexity signals** (each adds 0.33–0.34 to a 0–1 value, then × 5):
- Data scale: millions/billion/百萬/大規模/`\d+[MBT]`
- System arch: Kubernetes/microservice/distributed/production/real-time/deploy
- Model scale: 7B/13B/70B/175B/A100/H100/multi-GPU

**Metric signals** (防吹牛 — quantified results only):
- Latency: `500ms → 300ms`, `2× faster`, `降低40%`
- ML metrics: Recall@K, F1, BLEU, ROUGE, WER, CER, EER
- Throughput: QPS/TPS/RPS with numbers
- Resource: VRAM, GPU memory with numbers

---

## S_Eng — Engineering Maturity (20%)

**Source:** `app/scoring/engineering.py`

```
M_Eng = B + D + F    (capped at 0.7)
S_Eng = min(M_Eng / 0.7, 1.0) × 100
```

### Backend (B)

| Level | Score | Signals |
|-------|:-----:|---------|
| 0 | 0.00 | No backend evidence |
| 1 | 0.10 | Flask, FastAPI, Django, REST API, backend, API develop |
| 2 | 0.20 | Docker, Asyncio, Gunicorn, Uvicorn, Nginx, CI/CD, GitHub Actions, container |
| 3 | 0.35 | Kubernetes/K8s, Kafka, RabbitMQ, Redis, Celery, gRPC, microservice, Golang, Rust, high-concurrency |

### Database (D)

| Level | Score | Signals |
|-------|:-----:|---------|
| 0 | 0.00 | No DB evidence |
| 1 | 0.05 | MySQL, SQLite, SQL, CSV, Pandas |
| 2 | 0.12 | PostgreSQL, MongoDB, SQLAlchemy, Airflow, Elasticsearch, NoSQL, ORM, ETL, data pipeline |
| 3 | 0.20 | pgvector, Milvus, Qdrant, Pinecone, Weaviate, Chroma, Neo4j, Vector DB, HNSW, IVF |

### Frontend (F)

| Level | Score | Signals |
|-------|:-----:|---------|
| 0 | 0.00 | No frontend evidence |
| 1 | 0.02 | Streamlit, Gradio, Dash, Panel, Chainlit (demo-builder baseline) |
| 2 | 0.05 | HTML/CSS, Bootstrap, JavaScript, jQuery, web develop |
| 3 | 0.15 | React, Vue.js, Next.js, Nuxt, Angular, TypeScript, Tailwind, SSE/streaming UI |

**Maximum:** B=0.35 + D=0.20 + F=0.15 = 0.70 → S_Eng = 100

> v2 changes: cap raised 0.5 → 0.7; Backend L3 0.25 → 0.35; DB L2 0.10 → 0.12, L3 0.15 → 0.20; Frontend L1 0.00 → 0.02, L3 0.10 → 0.15.

---

## S_Semantic — Semantic Similarity (20%)

**Source:** `app/scoring/embeddings.py`

```
S_Semantic = cosine_similarity(embed(candidate_text), embed(job_text)) × 100
```

**Candidate text** is built from: skill tags + work experience titles/descriptions/skills + self-introduction + raw_markdown (truncated at 4000 chars).

**Job text** is the raw JSON of `job_requirement.json`.

**Fallback (embedding service unavailable):** keyword-overlap similarity — asymmetric coverage of English word tokens (≥ 3 chars) and Chinese bigrams, mapped to `[0.15, 0.80]`. This is used automatically when the embedding endpoint fails.

**Availability:** a time-based backoff (60 s) replaces the old session-wide circuit breaker. The service is retried once per minute after a failure, so scoring recovers automatically if LM Studio is started mid-run.

---

## S_Edu — Education Background (15%)

**Source:** `app/scoring/education.py`

All text is NFKC-normalized before matching to handle CJK compatibility ideographs (e.g. `⼤` U+2F23 → `大` U+5927) that appear in PDF-parsed resumes.

### Per-Entry Scoring

```
base = school_pts + major_pts
```

**School tier:**

| Tier | Points | Examples |
|------|:------:|---------|
| S (PhD only) | 15 | Any PhD degree |
| A | 10 | NTU, NTHU, NYCU, NCKU, NCCU, NTUST, Stanford, MIT, CMU, NUS, Tsinghua, Oxford … |
| B | 3 | 中央, 中興, 中正, 中山, 北科 (台北科技), 師大 |
| C | 0 | All others |

**Major relevance:**

| Tier | Points | Fields |
|------|:------:|-------|
| Tier 1 | 10 | CS/資工, EE/電機, EECS, AI, MIS/資管, Data Science, Software Engineering |
| Tier 2 | 3 | Math/Statistics/Physics, Applied Math, Operations Research, Industrial Engineering |
| Other | 0 | All others |

### Hybrid Degree Weighting

```
With master/PhD:   hybrid = bachelor_base × 0.7 + graduate_base × 0.3
Bachelor-only:     hybrid = bachelor_base × 0.9
```

- PhD uses Tier S school points (15) in the graduate slot.
- If a department field contains `碩士班` / `研究所`, that entry is also treated as an implicit master slot.
- Best-scoring entry of each level is used when multiple records exist.

### Normalization & Thesis Bonus

```
base_score_100 = min(hybrid / 24.0 × 100, 95)
thesis_bonus   = AI_keywords ? +2.5 : 0  +  top_venue ? +2.5 : 0
S_Edu          = min(base_score_100 + thesis_bonus, 100)
```

Thesis bonus is **additive on top of the 95-cap** — a top-tier academic with publications can reach 100.

**AI keywords** (scans `raw_markdown`): NLP, Natural Language, Computer Vision, Transformer, BERT, GPT, LLM, Deep Learning, Reinforcement Learning, Neural Network, 機器學習, 深度學習, 自然語言

**Top venues**: NeurIPS/NIPS, ICLR, ICML, CVPR, ICCV, ECCV, ACL, EMNLP, NAACL, COLING, AAAI, IJCAI, ICASSP, KDD, RecSys

**Representative scores (denominator = 24):**

| Profile | hybrid | bonus | S_Edu |
|---------|:------:|:-----:|:-----:|
| NTU CS + master (A + T1, both slots) | 10×0.7 + 10×0.3 = 10.0 | 0 | 41.7 |
| NTU CS master only (no bachelor data) | 0×0.7 + 10×0.3 = 3.0 | 0 | 12.5 |
| NTU CS bachelor only | 10×0.9 = 9.0 | 0 | 37.5 |
| PhD (any school) + T1 major | 15×0.3 + 10×0.7 = 11.5 | 0 | 47.9 |
| Tier-A school, T1 major, bachelor + master | 10.0 | +5.0 | 46.7 (41.7 + 5.0) |
| Tier-B school, CS, bachelor only | 3×0.9 = 2.7 | 0 | 11.25 |

---

## S_Skill — Skill Verification (10%)

**Source:** `app/scoring/skills.py`

### Ecosystem Classification

Corpus: skill tags + work descriptions + `raw_markdown`. First match wins (priority order):

| Ecosystem | Base score | Trigger keywords |
|-----------|:----------:|-----------------|
| LLM Stack | 90 | LangChain, LlamaIndex, vLLM, Ollama, OpenAI, Claude, LLM, GPT, Llama, Mistral, RAG, Prompt, Fine-tuning, LoRA, QLoRA, PEFT, Embedding, Vector, RLHF, DPO, 大型語言模型 |
| Deep Learning | 70 | PyTorch, TensorFlow, Keras, Jax, CNN, RNN, LSTM, GAN, Transformer, Attention, BERT, ResNet, YOLO, Neural Network, 深度學習 |
| Traditional ML | 50 | Sklearn, XGBoost, LightGBM, CatBoost, Random Forest, SVM, Logistic Regression, Feature Engineering, 特徵工程 |
| General | 30 | None of the above |

### Suspicious Claim Penalties

Checks 10 high-value skills: `PyTorch`, `TensorFlow`, `CUDA`, `vLLM`, `Fine-tuning`, `RAG`, `LangChain`, `Docker`, `Kubernetes`, `K8s`.

Flag condition: skill is in `skill_tags` **AND** not found in structured work history (`job_description` + `job_skills`).

| Situation | Penalty |
|-----------|:-------:|
| Claimed in tags, evidenced in `raw_markdown` (portfolio/self-intro/thesis) but **not** in work history | −2 per skill |
| Claimed in tags, **no evidence anywhere** | −5 per skill |
| Keyword stuffing: `total job_skills words > 2× job_description words` AND > 20 total words | −5 (flat) |

```
S_Skill = max(ecosystem_base − total_penalty, 10)
```

---

## LLM Tier Cache

**Source:** `app/database.py`, `app/llm.py`

Stored in the `candidates` table:

| Column | Type | Purpose |
|--------|------|---------|
| `llm_tier` | INTEGER | Cached tier (1 / 2 / 3) |
| `llm_tier_reasoning` | TEXT | LLM explanation (Traditional Chinese) |
| `llm_tier_md5` | TEXT | MD5 of `raw_markdown` at classification time |
| `llm_tier_prompt_md5` | TEXT | MD5 of the system prompt + `_INCLUDE_RAW_MARKDOWN` flag |

**Cache hit:** both MD5s match current values.

**Invalidation triggers:**
- Résumé content changes (`raw_markdown` MD5 differs)
- Prompt edited (`_TIER_CLASSIFY_PROMPT` in `app/llm.py` changes)
- `_INCLUDE_RAW_MARKDOWN` flag toggled

---

## Legacy Display Fields

Computed for the UI but **not** part of `S_Final`:

| Field | Formula | Purpose |
|-------|---------|---------|
| `s_ai` | `exp_detail.score` | AI experience score (same as S_AI input) |
| `m_eng` | `eng_detail.m_eng` | Raw engineering coefficient (0–0.7) |
| `s_total` | `s_ai × (1 + m_eng)` | Legacy blended score (used for display / ranking) |

---

## Batch Workflow

```bash
# 1. Classify tiers with LLM (caches results, skips valid entries)
uv run python scripts/reclassify_tiers.py [--limit N] [--force]

# 2. Re-score all candidates using cached LLM tiers + embeddings
uv run python scripts/batch_score_all.py
```

`batch_score_all.py` reads `llm_tier` from the candidates table. If present → uses that tier directly and computes keyword sub-scores for bonuses. If NULL → falls back to `classify_experience_tier()` (keyword-only).
