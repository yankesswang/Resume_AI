## 評分演算法 (Scoring Algorithm) 優化提案

### 1.  區辨度提升與邊界條件修復

目前  佔總分 15%。但現有公式容易導致頂校生提早封頂失去鑑別度，且對僅有學士學位者懲罰過重。

**現狀痛點：**

* 只要是 Tier A 學校配上 Tier 1 科系，學碩士  分數極易撞到 100 分天花板（如李威、陳雅婷、王思齊皆為 100 分）。
* 頂尖學術成就（如李威的 NeurIPS 論文加分 +2.0，或王思齊的 CMU PhD）在 Cap 限制下被完全抹平。
* 公式  導致「僅有學士」的候選人（如吳明宏）直接喪失 30% 權重，即便學歷優秀也只能拿到極低分（45.5 分）。

**優化建議：**

* **調整學士權重：** 新增條件判斷，若無碩士學位，設定 `hybrid = bachelor_base * 0.9`，保留學士權重並維持碩士微小優勢。
* **放大常態化分母：** 將計算公式的分母從 20 提高到 24 或 25。例如 ，讓純 Tier A 學碩只拿約 83 分，需靠頂會論文加成才能滿分。
* **新增 Tier S 級別：** 將全球 Top 50 名校或 PhD 學位獨立為 Tier S，給予 15 分的 School Points。
* **解綁論文加分：** 將 Thesis Bonus 視為額外加成（不參與 Cap），例如教育基礎分上限 95，靠論文才可頂到 100。

### 2. Layer 0 (Hard Filter) 彈性化

目前 `required_skills` 要求必須符合列表中的「所有」技能（ALL skills in list must appear）。

**現狀痛點：**

* 在真實履歷中，極易因為同義詞、縮寫或未刻意列出基礎技能而誤殺優秀候選人。

**優化建議：**

* **改為分組必備 (Must-have groups)：** * Group A（至少命中 1）：PyTorch / TensorFlow
* Group B（至少命中 1）：LLM / Transformer / Attention / BERT
* Group C（至少命中 1）：RAG / Fine-tuning / Inference serving


* **引入 Threshold 機制：** 將絕對的 ALL 改為 ANY-of 搭配最低命中數（例如：5 個關鍵字中至少命中 2 個）。

### 3.  Stack Bonus 防灌水機制

目前  包含 `stack_bonus`，最高可加 10 分。

**現狀痛點：**

* 候選人僅將高權重關鍵字（如 PyTorch、LoRA）放在標籤區，即可拿滿 Bonus。
* 以吳明宏為例，其為 API Wrapper，但因標籤包含 PyTorch，`stack_bonus` 直接加滿 10 分。
* 雖有 `S_Skill` 扣分機制，但整體權重依然偏寬鬆。

**優化建議：**

* **依出現位置給予權重：** 僅計入 `job_description` / `job_skills` 的命中；或設定 `skill_tags` 命中僅給予 30% 到 50% 的折算權重。
* **分離計算與 Cap：** 將 `job_evidence_weight` 與 `skills_tag_weight` 分開計算並獨立設定上限。
* **連動可疑標記：** 若技能觸發 suspicious flag，則該技能強制不計入 `stack_bonus`。

### 4.  工程成熟度粒度細化

目前工程分數基於  計算。

**現狀痛點：**

* 封頂過快：只要具備 K8s (0.25) + 向量資料庫 (0.15) + React/Vue (0.10) 即可滿分，導致中高階工程師難以拉開差距（如李威 0.5、陳雅婷 0.4）。
* 零分設定突兀：Frontend Level 1 (Streamlit, Gradio) 目前得分為 0.00，雖有分級卻無實質分數回饋。

**優化建議：**

* **拆分工程維度：** 將後端與基礎架構細分為「Production Readiness (Docker/CI/CD/Logging)」與「System Scale (K8s/Microservices/Queue)」。
* **提高 Cap 上限：** 將  的上限從 0.5 提升至 0.7，拉開高端鑑別度。
* **微調前端給分：** 鼓勵快速建立 Demo 的能力，將 Frontend L1 調整為 0.02 到 0.03 的微小加分。

### 5. Skill Verification 可疑標記範圍擴充

目前判定可疑的邏輯為：技能出現在 `skill_tags`，但未出現在 `job_description` 或 `job_skills`。

**現狀痛點：**

* 容易誤判：候選人可能將技術細節寫在 `self_introduction`、專案經歷或論文摘要中。
* 容易漏判：候選人可能在 `job_skills` 中堆疊關鍵字，但工作描述空洞。

**優化建議：**

* **擴大證據搜索範圍：** 將 `self_introduction`、Portfolio 區塊與學歷論文說明納入比對。
* **新增「關鍵字堆疊」懲罰：** 若偵測到 `job_skills` 大量列出高階技術，但 `job_description` 缺乏對應的動詞、成果或系統描述，則加重可疑懲罰 (Suspicious Penalty)。

---

## 實作變更紀錄 (Implementation Changelog — v1 → v2)

> 實作日期：2026-02-20
> 涉及檔案：`app/scoring/education.py` · `app/scoring/hard_filter.py` · `app/scoring/skills.py` · `app/scoring/engineering.py` · `app/scoring/experience.py` · `app/scoring/pipeline.py` · `scripts/batch_score_all.py` · `job_requirement.json`

---

### 1. 教育評分 (`app/scoring/education.py`)

#### 新增 Tier S（PhD）
```python
# v1
def _school_points(school: str) -> tuple[str, float]:
    # A=10, B=3, C=0 — PhD 與碩士皆以相同公式處理

# v2
def _school_points(school: str, is_phd: bool = False) -> tuple[str, float]:
    if is_phd:
        return "S", 15.0   # PhD → Tier S，高於 Tier A 的 10 分
    # A=10, B=3, C=0（其餘不變）
```

#### 學士權重修正
```python
# v1 — 僅有學士時直接乘 0.7，損失 30% 權重
hybrid = b_score * 0.7

# v2 — 改為 0.9×，保留絕大部分學士價值，僅維持碩士微小優勢
hybrid = b_score * 0.9
```

#### 常態化分母與論文加分解綁
```python
# v1 — thesis 併入分母，容易被 Cap 抹平
thesis_bonus = 0.0
if THESIS_AI_KEYWORDS.search(raw_markdown): thesis_bonus += 1.0
if TOP_VENUE_KEYWORDS.search(raw_markdown): thesis_bonus += 1.0
score = min((hybrid + thesis_bonus) / 20.0 * 100.0, 100.0)

# v2 — 分母改 24，基礎分 cap 95，論文另加最多 5 分
base_score_100 = min(hybrid / 24.0 * 100.0, 95.0)
thesis_bonus_pts = 0.0
if THESIS_AI_KEYWORDS.search(raw_markdown): thesis_bonus_pts += 2.5
if TOP_VENUE_KEYWORDS.search(raw_markdown): thesis_bonus_pts += 2.5
score = min(base_score_100 + thesis_bonus_pts, 100.0)
```

| 情境 | v1 分數 | v2 分數 |
|---|---|---|
| Tier A 學校 + Tier1 科系，碩士 | 100.0 | 83.3 |
| 同上 + NeurIPS 論文 | 100.0 (capped) | 88.3 |
| PhD (Tier S) + Tier1 科系 + 論文 | 100.0 (capped) | 94.6 |
| 學士僅有（Tier A + Tier1） | 70.0 | 75.0 |

---

### 2. 硬性篩選 (`app/scoring/hard_filter.py` + `job_requirement.json`)

#### 新增 Must-have Groups
```python
# v1 — required_skills 全部必中（ALL），容易誤殺含同義詞的優秀候選人

# v2 — 新增 must_have_groups：每個 group 只需命中 min_matches 個
must_have_groups = hard_filter_config.get("must_have_groups", [])
for group in must_have_groups:
    hits = sum(1 for skill in group["skills"] if skill.lower() in combined)
    if hits < group["min_matches"]:
        failures.append(f"Group '{group['name']}': need {group['min_matches']} ...")
```

#### 新增 N-of-M Threshold
```python
# v2 新增：required_skills_threshold — 5 個關鍵字中至少命中 N 個
threshold_config = hard_filter_config.get("required_skills_threshold", {})
if threshold_config:
    hits = sum(1 for skill in threshold_config["skills"] if skill.lower() in combined)
    if hits < threshold_config["min_matches"]:
        failures.append(...)
```

#### `job_requirement.json` 結構更新
```jsonc
// v1
"hard_filters": {
  "required_skills": ["Python"],
  "required_frameworks": ["PyTorch", "TensorFlow"],        // ANY-of
  "required_keywords": ["Transformer", "LLM", ...]         // ANY-of
}

// v2 — 改為三組 must_have_groups，每組 ≥1 命中
"hard_filters": {
  "required_skills": ["Python"],
  "must_have_groups": [
    { "name": "Framework",    "skills": ["PyTorch", "TensorFlow"],               "min_matches": 1 },
    { "name": "LLM Concepts", "skills": ["LLM", "Transformer", "Attention", "BERT", "Deep Learning"], "min_matches": 1 },
    { "name": "Applied AI",   "skills": ["RAG", "Fine-tuning", "Inference", "模型微調"], "min_matches": 1 }
  ]
}
```

---

### 3. 技能驗證 (`app/scoring/skills.py`)

#### 擴大證據搜索範圍 + 雙層可疑懲罰
```python
# v1 — 只比對 work_text（job_description + job_skills）
evidenced = skill_lower in work_text.lower()
if claimed and not evidenced and work_text.strip():
    suspicious.append(f"Claimed '{skill}' but no evidence in work experience")
    # 每項 -5 分

# v2 — 加入 raw_markdown（含自傳、作品集、論文描述）作為次要證據
evidenced_in_work = skill_lower in work_text.lower()
evidenced_in_raw  = skill_lower in raw_markdown.lower()
if claimed and not evidenced_in_work and work_text.strip():
    if evidenced_in_raw:
        suspicious.append("...found in portfolio/self-intro but not in work history")
        penalty += 2.0   # 次要來源，輕罰
    else:
        suspicious.append("...no evidence in work experience or portfolio")
        penalty += 5.0   # 完全無佐證，重罰
```

#### 關鍵字堆疊懲罰（新增）
```python
# v2 — 偵測 job_skills 字數遠超 job_description 的情形
total_skills_words = sum(len((we.get("job_skills", "") or "").split()) ...)
total_desc_words   = sum(len((we.get("job_description", "") or "").split()) ...)
if total_skills_words > total_desc_words * 2 and total_skills_words > 20:
    suspicious.append("Keyword stuffing: job_skills list is disproportionately long")
    penalty += 5.0
```

| 情境 | v1 懲罰 | v2 懲罰 |
|---|---|---|
| 技能在 tag 且有工作描述佐證 | 0 | 0 |
| 技能在 tag，無工作描述但有 portfolio | -5 | **-2** |
| 技能在 tag，完全無佐證 | -5 | -5 |
| job_skills 堆疊關鍵字 | 0 | **-5** |

---

### 4. 工程成熟度 (`app/scoring/engineering.py`)

#### 分數表與 Cap 調整
```python
# v1
BACKEND_SCORES = {0: 0.0, 1: 0.10, 2: 0.15, 3: 0.25}
DB_SCORES      = {0: 0.0, 1: 0.05, 2: 0.10, 3: 0.15}
FE_SCORES      = {0: 0.0, 1: 0.00, 2: 0.05, 3: 0.10}  # L1 = 0 (Streamlit 無分)
m_eng = min(b + d + f, 0.5)

# v2
BACKEND_SCORES = {0: 0.0, 1: 0.10, 2: 0.20, 3: 0.35}
DB_SCORES      = {0: 0.0, 1: 0.05, 2: 0.12, 3: 0.20}
FE_SCORES      = {0: 0.0, 1: 0.02, 2: 0.05, 3: 0.15}  # L1 = 0.02 (Streamlit 有分)
m_eng = min(b + d + f, 0.7)                             # cap 0.5 → 0.7
```

| 組合 | v1 M_Eng | v1 Normalized | v2 M_Eng | v2 Normalized |
|---|---|---|---|---|
| Backend L3 only | 0.25 | 50.0 | 0.35 | 50.0 |
| Backend L3 + DB L3 | 0.40 | 80.0 | 0.55 | 78.6 |
| Full-stack (B3+D3+F3) | 0.50 | 100.0 | 0.70 | 100.0 |
| Frontend L1 only | 0.00 | 0.0 | 0.02 | 2.9 |

---

### 5. 經驗評分 Stack Bonus 防灌水 (`app/scoring/experience.py`)

#### 位置加權（Position-based Weighting）
```python
# v1 — skill_tags 與 job_description 同等權重
combined_text = work_text + " " + tag_text
for tier in [3, 2, 1]:
    for kw, weight in _find_keywords(combined_text, TIER_KEYWORDS[tier]):
        total_stack_score += weight  # 不論來源，全重計算

# v2 — 拆分文本來源，tag-only 關鍵字僅 40% 權重
TAG_WEIGHT_FACTOR = 0.4
evidence_hits = {kw for kw, _ in _find_keywords(evidence_text, kw_map)}
tag_hits      = {kw for kw, _ in _find_keywords(tag_text, kw_map)}
for kw in evidence_hits | tag_hits:
    if kw in evidence_hits:
        total_stack_score += weight           # 全重
    else:
        total_stack_score += weight * 0.4     # 僅 tag，折算 40%
```

> Tier 判定閾值（TIER3_MIN_WEIGHT=3.0, TIER2_MIN_WEIGHT=2.0）仍使用完整文本，確保 Tier 升降不受位置加權影響。

---

### 6. Pipeline 常態化修正 (`app/scoring/pipeline.py` + `scripts/batch_score_all.py`)

```python
# v1
eng_score_normalized = min(eng_detail.m_eng / 0.5, 1.0) * 100.0

# v2 — 隨 engineering cap 同步更新
eng_score_normalized = min(eng_detail.m_eng / 0.7, 1.0) * 100.0
```

---

### 7. 實測結果摘要（1,349 位候選人）

```
Sub-score 平均變化（v2 − v1）：
  教育評分   : -5.53  ← 分母放大，區辨度提升（預期）
  經驗評分   : +0.00  ← 無回歸，位置加權不影響 Tier 判定
  工程評分   : -3.49  ← Cap 放大後中階工程師不再早封頂（預期）
  技能評分   : +0.22  ← portfolio 誤判減少，輕罰取代重罰

Experience Tier 升降：
  升等（Tier up）  :  8 位
  降等（Tier down）:  0 位
```

> 比較腳本：`uv run python scripts/compare_scores.py --top 50 --csv out.csv`

