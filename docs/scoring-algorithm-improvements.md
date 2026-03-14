# Scoring Algorithm Improvements

**Date:** 2026-02-19
**Branch:** develop
**Motivation:** Candidate 周成康 (CHENG KANG CHOU) scored 60.8/100 despite being a strong NTU AI engineering candidate with published papers (ICASSP, ASRU) and internships at MediaTek and WorldQuant. The expected range was 85–90. A root-cause analysis revealed five systemic issues in the scoring pipeline.

---

## Problems Found

### 1. Semantic Similarity Defaulted to 0 When Offline (`embeddings.py`)

**What happened:** When the LM Studio embedding service is unavailable, `compute_semantic_similarity()` returned `0.0`. Since semantic similarity carries a **20% weight** in the final score, every candidate scored offline was silently penalised with 0 out of a possible 20 points.

**Why it mattered for 周成康:** His semantic contribution was `0.0 × 0.20 = 0 pts` instead of an estimated `~15 pts` for a well-matched candidate.

**Discovered alongside:** A latent scaling bug — `compute_semantic_similarity` was returning a value in the `0–100` range, but the pipeline then multiplied it by 100 again (`sem_score_normalized = semantic_sim * 100.0`). This would have caused every candidate to score 100/100 the moment the embedding service came online. The return value was corrected to `0–1` to match the pipeline's expectation.

---

### 2. Skill Ecosystem Classified as "General" Instead of "Deep Learning" (`skills.py`)

**What happened:** The ecosystem detector only scanned `skill_tags` (database-stored labels like `"Python"`, `"Machine Learning"`) for framework keywords. It did not look at work experience descriptions or the raw resume markdown.

**Why it mattered:** Job portals store generic skill labels. Framework-specific evidence (`PyTorch`, `深度學習`, `Fine-tuning`) appears in the raw resume text, not in tag lists. Because `PyTorch` was absent from `skill_tags`, the candidate was classified as `"General"` (30 pts base) instead of `"Deep Learning"` (70 pts base) — a 40-point difference that cost **4 weighted points**.

---

### 3. Master's Degree Not Detected (`education.py`)

**What happened:** The resume parser stored 周成康's dual-degree line (`資訊管理學系、電信工程學系碩士班`) as a single education entry with `degree_level = "大學"` (bachelor). The `碩士班` (master's program) suffix in the `department` field was never parsed as a graduate degree.

**Why it mattered:** Without a detected master's, the education formula uses only `bachelor × 0.7` (max 70 before bonus). With a master's at the same Grade-A school: `bachelor × 0.7 + master × 0.3` = 100. The candidate is confirmed to be a graduate student in Prof. Hung-Yi Lee's NTU EE lab. The scoring was factually wrong.

---

### 4. ICASSP and ASRU Not Recognised as Top Venues (`education.py`)

**What happened:** The thesis publication bonus only recognised 9 venues: NeurIPS, ICLR, ICML, CVPR, ICCV, ACL, EMNLP, AAAI, IJCAI. 周成康 published at **ICASSP** (IEEE's flagship signal processing conference) and **ASRU** (IEEE Automatic Speech Recognition and Understanding workshop) — neither was on the list.

**Why it mattered:** One bonus point was missed. More broadly, the list was biased toward NLP/vision conferences and excluded the entire audio/speech ML field.

---

### 5. Metric and Complexity Detection Missed Chinese Text (`experience.py`)

**What happened:** The quantitative metric regex patterns were English-only (`reduced X%`, `improved X%`, `latency`, etc.). The complexity patterns similarly lacked common Chinese deployment/production terms. Most of the candidate's resume content is in Chinese.

**Why it mattered:** Metric score = 0 and complexity score = 0 despite real production internship experience. Audio-specific evaluation metrics (WER, CER, MOS, PESQ, SDR, EER) used in the published papers were also absent from the pattern list.

---

## Changes Made

### `app/scoring/embeddings.py`

| Change | Reason |
|--------|--------|
| Added `_keyword_overlap_fallback()` using CJK bigram + English word tokenization | Replaces the `0.0` fallback so offline candidates are not penalised; returns ~0.20–0.80 based on actual text overlap |
| Changed return type of `compute_semantic_similarity` from `0–100` to `0–1` | Fixed scaling bug — pipeline already multiplies by 100; returning 0–100 would have caused all scores to be capped at 100 once embeddings worked |
| Added `raw_markdown[:4000]` to `build_candidate_embedding_text()` | Structured fields (skill tags, work descriptions) are often sparse; raw text contains the real content for both embedding and keyword fallback |

### `app/scoring/skills.py`

| Change | Reason |
|--------|--------|
| `verify_skills()` now accepts an optional `raw_markdown: str` parameter | Provides the full resume text as an additional signal |
| Ecosystem detection corpus changed from `skills_text` only → `skills_text + work_text + raw_markdown` | Framework names like `PyTorch` appear in resume prose, not skill tag lists; scanning all available text gives the correct ecosystem classification |

### `app/scoring/education.py`

| Change | Reason |
|--------|--------|
| Added `_MASTER_IN_MAJOR` regex to detect `碩士班` / `研究所` in the department field | Parser sometimes stores dual/sequential degrees on a single line; this infers an implicit master's degree from the same school so the candidate is not penalised for a parser limitation |
| Expanded `TOP_VENUE_KEYWORDS` with: ICASSP, ASRU, SLT, INTERSPEECH, SIGKDD, KDD, RecSys, WSDM, CIKM, COLING, NAACL | The original list was NLP/vision-only; audio, speech, data mining, and information retrieval venues are equally rigorous and should award the thesis bonus |

### `app/scoring/experience.py`

| Change | Reason |
|--------|--------|
| Added Chinese metric patterns to `VALID_METRIC_PATTERN`: `加速`, `縮短`, `精確率`, `召回率`, `準確率` with `%` | Most resumes are written in Chinese; English-only patterns silently miss valid quantitative evidence |
| Added audio/speech ML metrics: `WER`, `CER`, `MOS`, `PESQ`, `SDR`, `SiSDR`, `EER` | Published NLP/audio paper authors use domain-standard metrics that weren't recognised |
| Added throughput metrics: `QPS`, `TPS`, `RPS` | Common in backend/serving system descriptions |
| Expanded `SYSTEM_ARCH_PATTERN` with: `real-time`, `即時`, `線上服務`, `online serving`, `inference serving`, `部署`, `deploy` | Production and deployment context in Chinese was not detected as a complexity signal |

### `app/scoring/pipeline.py`

| Change | Reason |
|--------|--------|
| Pass `raw_markdown` to `verify_skills()` | Wires the new parameter added to `skills.py` |

---

## Score Impact — 周成康

| Component | Weight | Before | After | Δ Weighted |
|-----------|--------|--------|-------|------------|
| AI Experience | 35% | 98.6 | 100.0 | +0.5 |
| Engineering Maturity | 20% | 60 | 60 | — |
| Semantic Similarity | 20% | 0 (offline) | 28 (fallback) | +5.6 |
| Education | 15% | 75 | 100 | +3.75 |
| Skill Verification | 10% | 30 (General) | 70 (Deep Learning) | +4.0 |
| **Overall** | | **60.8** | **~75** | **+14** |

**With embedding service running** (estimated cosine ~0.75 for a strong AI candidate matching this job description), semantic would contribute ~15 pts instead of 5.6, pushing the total into the **84–88 range** — within the target of 85–90.

---

## Notes for Future Work

- **Engineering Maturity (M_Eng)** stays at 0.3 for this candidate. Most work descriptions are empty in the database — the parser is not extracting `job_description` from the PDF. Fixing the PDF parser to populate these fields would automatically improve engineering detection for all candidates.
- **Embedding service**: Start LM Studio with the `text-embedding-nomic-embed-text-v1.5` model loaded for production-quality semantic similarity. The keyword fallback is a safety net, not a substitute.
- **Skill tags**: Consider enriching stored skill tags from raw markdown at parse time rather than relying on portal-provided tag lists.
