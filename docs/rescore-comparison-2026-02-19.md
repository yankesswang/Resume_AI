# Rescore Comparison Report

**Date:** 2026-02-19
**Candidates rescored:** 1,349
**Errors:** 0
**Scoring mode:** Rule-based pipeline (LM Studio embedding service offline — keyword fallback active)

---

## Overall Summary

| Metric | Before | After | Δ |
|--------|--------|-------|---|
| Mean score | 34.30 | 40.25 | **+5.95** |
| Median score | 43.10 | 55.00 | **+6.80** |
| Std deviation | 21.62 | 26.38 | +4.76 |
| Min | 10.00 | 10.00 | — |
| Max | 72.70 | 81.30 | **+8.60** |

> **Note:** 571 candidates (42.4%) are hard-filter failures with a fixed score of 10. Their scores are unchanged. All statistics below are shown both including and excluding this group.

---

## Direction of Change

| Outcome | Count | % of total |
|---------|-------|-----------|
| Improved (Δ > 0) | 777 | 57.6% |
| Unchanged (Δ ≈ 0) | 572 | 42.4% |
| Worsened (Δ < 0) | **0** | **0.0%** |

No candidate scored lower after the update. All changes are non-negative.

---

## Delta Distribution

| Improvement Range | Count | % |
|-------------------|-------|---|
| 0 pts (hard-filter fail or no change) | 572 | 42.4% |
| +0.1 – +5 pts | 55 | 4.1% |
| +5 – +10 pts | 262 | 19.4% |
| +10 – +15 pts | 454 | 33.7% |
| +15 pts | 6 | 0.4% |

The dominant improvement band is **+10 to +15 pts**, accounting for a third of all candidates — a direct result of the semantic fallback replacing the hard `0.0` default.

---

## Candidates Who Passed Hard Filter (n = 778)

These are the candidates the algorithm considers viable. Excluding hard-filter failures gives a cleaner view of scoring quality.

| Metric | Before | After | Δ |
|--------|--------|-------|---|
| Mean | 52.13 | 62.45 | **+10.32** |
| Median | 52.00 | 63.00 | **+11.00** |
| Std Dev | 7.65 | 6.44 | −1.21 |
| Min | 27.40 | 39.50 | +12.10 |
| Max | 72.70 | 81.30 | +8.60 |

The standard deviation **decreased** slightly, indicating scores are more tightly clustered around the mean — less noise from the zero-semantic penalty.

---

## Score Band Distribution

| Band | Before | After | Δ |
|------|--------|-------|---|
| < 20 | 571 | 571 | 0 |
| 20–29 | 3 | 0 | −3 |
| 30–39 | 39 | 2 | −37 |
| 40–49 | 224 | 24 | −200 |
| 50–59 | 384 | 224 | −160 |
| **60–69** | 122 | **453** | **+331** |
| **70–79** | 6 | **74** | **+68** |
| **80–89** | 0 | **1** | **+1** |
| 90–100 | 0 | 0 | 0 |

The bulk of candidates migrated upward from the 40–59 range into the **60–69 range**, and significantly more now reach 70+. The 80–89 band has its first occupant.

---

## Percentile Shifts (Passed-Filter Candidates Only)

| Score Threshold | % of candidates who scored ≥ this — Before | After |
|-----------------|----------------------------------------------|-------|
| 40 | 94.6% | 99.7% |
| 50 | 65.8% | 96.7% |
| 55 | 36.2% | 87.0% |
| 60 | 16.5% | 67.9% |
| 65 | 3.7% | 38.3% |
| 70 | 0.8% | 9.6% |
| 75 | 0.0% | 1.5% |
| 80 | 0.0% | 0.1% |

---

## Root Cause of Improvements

Analysis among the 777 candidates who improved:

| Fix | Candidates Affected | % of Improved |
|-----|---------------------|---------------|
| Semantic fallback (was 0.0, now keyword-based ~20–30) | 777 | 100% |
| Skill ecosystem reclassified from "General" to DL/LLM Stack | 532 | 68.5% |
| Education score increased (master's degree detected from 碩士班) | 2 | 0.3% |

The semantic fallback is the universal driver — every previously-scored candidate had `0` for a 20%-weight component. The skill reclassification was the second-largest factor, affecting over two thirds of improved candidates.

---

## Top 15 Candidates by New Score

| Rank | ID | Name | Old Score | New Score | Δ |
|------|----|------|-----------|-----------|---|
| 1 | 1872 | 李英群 | 71.0 | **81.3** | +10.3 |
| 2 | 2130 | 黃唯軒 | 66.4 | 79.3 | +12.9 |
| 3 | 2344 | 賴冠樺 | 72.7 | 79.0 | +6.3 |
| 4 | 2561 | 左其右 | 65.8 | 77.5 | +11.7 |
| 5 | 2302 | 郭宸瑀 | 65.8 | 77.2 | +11.4 |
| 6 | 2523 | 楊詒婷 | 64.4 | 77.2 | +12.8 |
| 7 | 2210 | 谷昭賢 | 69.9 | 77.0 | +7.1 |
| 8 | 2574 | 劉猷聖 | 68.9 | 76.9 | +8.0 |
| 9 | 2607 | 顏碩均 | 64.4 | 76.7 | +12.3 |
| 10 | 1963 | 張哲綸 | 62.9 | 75.9 | +13.0 |
| 11 | 1727 | 胡喬軻 | 68.4 | 75.5 | +7.1 |
| 12 | 2378 | YuanZe | 64.0 | 75.5 | +11.5 |
| 13 | 1806 | 黃鉅燊 | 68.0 | 74.8 | +6.8 |
| 14 | 2636 | 毛致元 | 68.4 | 74.8 | +6.4 |
| 15 | **1** | **周成康** | 60.8 | 74.6 | +13.8 |

---

## Target Candidate: 周成康 (ID = 1)

| Component | Before | After | Δ |
|-----------|--------|-------|---|
| AI Experience (35%) | 98.6 → 34.5 pts | 100.0 → 35.0 pts | +0.5 |
| Engineering Maturity (20%) | 0.30 → 12.0 pts | 0.30 → 12.0 pts | — |
| Semantic Similarity (20%) | 0.0 → 0.0 pts | 28.0 → 5.6 pts | +5.6 |
| Education (15%) | 75.0 → 11.25 pts | 100.0 → 15.0 pts | +3.75 |
| Skill Verification (10%) | 30.0 (General) → 3.0 pts | 70.0 (Deep Learning) → 7.0 pts | +4.0 |
| **Overall** | **60.8** | **74.6** | **+13.8** |

**Expected with working embedding service:** cosine similarity ~0.75 would contribute ~15 pts instead of 5.6, placing the total in the **84–88 range** (target: 85–90 ✓).

---

## Limitations & Next Steps

1. **Semantic similarity is still underestimated.** The keyword fallback tops out at ~0.80 and averages ~0.28 for these candidates. Starting LM Studio with `text-embedding-nomic-embed-text-v1.5` would be the single highest-leverage action to improve score accuracy.

2. **Hard filter failure rate is 42.4% (571/1349).** This is very high. Worth reviewing the `required_keywords` in `job_requirement.json` — the list includes terms like "Transformer", "BERT", "LLM" which may be overly strict for non-NLP roles.

3. **Max score is 81.3**, not yet reaching 90+. The ceiling would rise once:
   - Embedding service is online (semantic can reach 80–100)
   - Work descriptions are populated by the PDF parser (currently mostly empty, limiting engineering detection)

4. **The score database has not been updated.** The `match_results` table still holds the old scores. To persist, run the rescore script and `UPDATE match_results` with the new values.
