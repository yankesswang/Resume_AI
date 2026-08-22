# JD 篩選標準生成演算法

本文件說明 Resume AI 如何把一份職缺說明（Job Description，以下簡稱 JD）轉換為
可編輯、可驗證的履歷篩選標準 `DomainProfile`。

本文聚焦於「篩選標準如何生成」；候選人取得分數後如何加權與排序，請參考
[履歷評分演算法](SCORING_ALGORITHM.md)。

---

## 1. 設計目標

生成演算法必須同時滿足以下要求：

1. **跨領域**：能處理工程、業務、財會、人資、行銷、製造、醫療、法務等職缺。
2. **可解釋**：每個層級、能力面向、關鍵字與硬門檻都能由人員檢視及修改。
3. **可降級**：LLM 無法使用時，仍能依關鍵字完成基本評分。
4. **避免誤殺**：不得把加分條件、工作內容或模型常識擅自升格為淘汰門檻。
5. **先驗證再啟用**：LLM 產出的內容只會成為草稿，不會自動投入正式篩選。

演算法的核心安全原則是：

> LLM 可以依領域知識補充「排序訊號」，但所有會直接淘汰候選人的「硬門檻」都必須
> 能反查到 JD 的明確必要條件。

因此，模型可以推導某職缺的專家級證據，例如資料工程師的資料平台架構、資料治理或
串流處理經驗；但如果 JD 沒有明確要求 Kubernetes，演算法不得因為 Kubernetes 在業界
常見，就把它設成「沒有便淘汰」的條件。

---

## 2. 整體流程

一次完整的生成包含兩個 LLM 階段，以及兩層程式化品質控制：

```text
PDF / DOCX / TXT / 貼上文字
              │
              ▼
       擷取 JD 純文字
              │
              ▼
  LLM ①：結構化職缺內容
  extract_job_requirement()
              │
              ▼
       Job Requirement JSON
              │
              ▼
  LLM ②：生成篩選標準初稿
  generate_domain_profile()
              │
              ▼
  結構修補 + 硬門檻反查 JD
            _repair()
              │
              ▼
  Schema 驗證 + 可用性驗證
              │
       ┌──────┴──────┐
       │             │
     合格          不合格
       │             │
       │      LLM 定向修正一次
       │             │
       └──────┬──────┘
              ▼
       儲存為 draft 草稿
              │
              ▼
     人工檢視 / 試算 / 編輯
              │
              ▼
       驗證通過後啟用
```

職缺生成是「每個職缺執行一次」的離線流程，不在每位候選人的即時評分路徑上。

主要程式位置：

- `app/job_profiles_routes.py`：上傳、重新生成、預覽與啟用 API
- `app/scoring/profile_builder.py`：兩階段 LLM 生成、修補與硬門檻反查
- `app/scoring/domain_profile.py`：輸出 Schema、可用性驗證與 fingerprint
- `app/scoring/hard_filter.py`：候選人硬門檻判斷
- `tests/test_profile_builder.py`：生成安全規則測試

---

## 3. 輸入處理

### 3.1 支援格式

`POST /api/job-postings/upload` 接受：

- PDF：使用 `pdfplumber` 讀取文字層
- DOCX：讀取段落與表格文字
- TXT 或其他可辨識文字檔：依序嘗試 UTF-8、UTF-8 BOM、Big5、CP950
- 前端直接貼上的純文字

檔案上限為 10 MB。若 PDF 沒有文字層，系統回傳 422，要求使用者改貼純文字；目前
不會為 JD 啟動 OCR。

JD 文字少於 40 個字時不進入 LLM 流程，避免模型根據過少資訊杜撰標準。

### 3.2 Context 截斷

送入 LLM 前，`_truncate_to_fit()` 會根據 `MODEL_CONTEXT_LENGTH` 預留 system prompt 與
輸出 token 空間：

- JD 結構化階段預留 3,072 output tokens
- Profile 生成與修正階段預留 4,096 output tokens

內容超過可用 context 時保留頭部 60% 與尾部 40%，中間插入省略標記。這能同時保留
JD 開頭的職務摘要與尾端常見的資格、加分條件。

---

## 4. 第一階段：JD 結構化

`extract_job_requirement(jd_text, filename)` 使用低溫度 `temperature=0.1`，把非結構化
JD 轉換為統一格式：

```json
{
  "basic_conditions": {
    "job_title": "",
    "employment_type": "",
    "department": "",
    "job_categories": []
  },
  "job_summary": "",
  "responsibilities": [
    {"category": "", "items": []}
  ],
  "requirements": {
    "education": "",
    "experience_years": "",
    "majors": [],
    "skills": [],
    "languages": [],
    "certifications": [],
    "others": []
  },
  "preferred_qualifications": [],
  "domain": ""
}
```

### 4.1 必要、加分與工作內容分流

這一步不只抽取欄位，也建立後續安全判斷所需的邊界：

| JD 語意 | 目的欄位 | 可否成為硬門檻 |
|---|---|---|
| 「必須、需具備、必要、required」 | `requirements` | 可以，但仍須經 grounding |
| 「加分、尤佳、優先、preferred、nice to have」 | `preferred_qualifications` | 不可以 |
| 日常任務、負責項目 | `responsibilities` | 不可以 |

如果原文沒有資料，欄位保持空值；模型不得根據職稱或業界常識補寫必要條件。

系統另外保留：

- `source_document`：原始檔名
- `source_text`：原始 JD 前 20,000 字

保留原文有兩個目的：讓審核者能比對模型解析結果，以及讓後續重新生成時不必再次
上傳檔案。

---

## 5. 第二階段：生成 DomainProfile

`generate_domain_profile(job_data, source_document)` 會把精簡過的結構化 JD 與最多
6,000 字原文節錄送入 LLM。溫度為 `0.2`，最大輸出為 4,096 tokens。

結構化資料提供明確欄位邊界；原文節錄則保留可能在抽取時遺失的工具名稱、證照與
產業術語。

### 5.1 輸出欄位

| 欄位 | 用途 |
|---|---|
| `domain` | 職缺所屬專業領域 |
| `summary` | 職位核心價值，供分類模型理解職務 |
| `tiers` | 0–3 四個領域深度層級及可觀察證據 |
| `tier_keywords` | 各深度層級的字面比對訊號與權重 |
| `competencies` | 2–4 個職務能力面向及各面向的分級關鍵字 |
| `education` | 學歷是否重要，以及核心／相關科系 |
| `ecosystems` | 技能族群及其基準價值 |
| `hard_filters` | 缺少便不能錄用的必要條件 |
| `weights` | 五個評分構面的職缺專屬權重 |

完整 Schema 定義在 `DomainProfile`。

### 5.2 四個領域深度層級

Tier 描述的是實作深度，不直接等同年資：

| 層級 | 一般定義 | 應觀察的履歷證據 |
|---|---|---|
| 0 | 無相關領域經驗 | 沒有可驗證的領域工作、專案或成果 |
| 1 | 入門／執行層 | 能依既定流程執行工作 |
| 2 | 獨立負責 | 能設計方法、獨立交付或帶領專案 |
| 3 | 領域專家 | 能定義策略、建立制度或解決高難度問題 |

`definition` 必須描述「看得到的證據」，不能只寫「能力優秀」「經驗豐富」等抽象形容詞，
因為此文字會直接提供給候選人領域分級模型。

### 5.3 Tier 關鍵字

每個 Tier 的關鍵字是履歷中可進行字面比對的工具、方法、制度、證照或專有名詞。

- LLM prompt 要求 Tier 1–3 每級至少 8 個關鍵字，其中至少 4 個繁體中文、4 個英文
- 關鍵字權重範圍為 0.5–2.5
- 越難取得或造假的訊號，權重越高
- 同一概念可以中英對照詞並存，避免英文 JD 對中文履歷只得到低字面分數
- 不接受「認真」「負責」等不可驗證形容詞

程式的最低可用性驗證是每級 4 個。Prompt 要求 8 個是為了提供安全餘裕；4 個是避免
LLM 離線時關鍵字 fallback 幾乎無法命中的最低門檻。

生成式或人工 Profile 在候選人 LLM 分級成功時，以 LLM Tier 為準；關鍵字只在 LLM
無法使用時作為 fallback，不得向上覆蓋成功的語意判斷。只有內建且經完整履歷池校準的
Profile 保留關鍵字向上保底。

候選人的實習、接案、論文、產學合作與個人專案都屬有效證據，分類器必須依交付範圍、
技術深度、ownership 與成果判讀，不得只因不是正職或年資短而降級。判 Tier 0 前必須
確認所有工作、研究與專案都沒有領域實作；`confidence >= 0.8` 則至少需要兩項獨立的
具體證據。

### 5.4 能力面向與權重

`competencies` 把通用的工程能力矩陣替換為職缺專屬能力。例如：

- 業務：通路開發、客戶經營、議價談判
- 會計：帳務處理、稅務法規、ERP 系統
- 資料工程：資料管線、資料建模、平台可靠性

每個能力面向包含 1–3 級關鍵字及面向權重。Profile 的五個總評分構面為：

```text
experience + engineering + semantic + education + skills = 1.0
```

其中 `engineering` 是歷史欄位名稱；套用 DomainProfile 時，它代表職缺專屬的
`competencies` 能力矩陣，不限於軟體工程職務。

---

## 6. 程式化修補

LLM 輸出先經 `_repair()` 正規化，才交給 Pydantic 與可用性驗證。修補只處理可確定的
結構問題，不會自行補造領域內容。

### 6.1 Tier 修補

- 將 `level` 轉為整數
- 丟棄 0–3 以外的層級
- 補齊缺少的 Tier 結構，但把 `definition` 留空，交由驗證回報
- 確保 `evidence_examples` 存在

### 6.2 關鍵字修補

- 接受 `{keyword: weight}` 或關鍵字陣列
- 移除 placeholder、尖括號填空文字及單字元雜訊
- 將權重限制在 `[0.5, 2.5]`
- 比較時忽略大小寫與空白
- 同一關鍵字出現在多個 Tier 時，只保留最低層級的版本

重複訊號保留最低層級，是因為一個同時被模型標成入門與專家的字面訊號具有歧義；它
可以證明入門能力，但不能單獨作為專家證據。

能力面向內的關鍵字也使用相同的低層級優先去重策略。

### 6.3 其他結構修補

- 缺少 competency `key` 時，由 label 產生 slug
- 字串型 competency level 轉成陣列
- 缺少核心科系時，使用 JD `requirements.majors`
- 移除沒有名稱的 ecosystem
- 將 ecosystem 分數限制在 30–90
- 移除空的 hard-filter group
- `min_matches` 最低為 1，最高不超過該組技能數
- 五構面權重轉成非負浮點數並重新正規化為 1.0

正規化後若因四捨五入造成 0.0001 的誤差，差值會加到目前權重最大的構面。

---

## 7. 硬門檻 Grounding

`_repair(..., enforce_grounding=True)` 會呼叫 `_ground_hard_filters()`，以程式強制執行
「淘汰條件必須來自 JD 必要條件」的規則。

### 7.1 Grounding 資料來源

只有 `job_data.requirements` 可以作為技能硬門檻的依據：

```text
可搜尋：requirements.skills / certifications
不搜尋：responsibilities
不搜尋：preferred_qualifications
不搜尋：source_text
不搜尋：languages / experience_years / 產業經驗敘述
```

不直接搜尋原始 JD，是為了避免模型看到「Kubernetes 經驗尤佳」後，只因 Kubernetes
確實出現在原文中，就把它誤判為必要條件。

### 7.2 比對方式

每個 LLM 生成的 `must_have_groups[].skills` 必須在必要條件文字中有字面證據：

- 忽略英文大小寫
- 容許多餘空白，例如 `Machine Learning` 與 `Machine  Learning`
- 中文與包含符號的技術詞使用正規化後的字面包含
- 短英文詞使用單字邊界，避免把 `Go` 錯誤命中 `Google`
- 只保留原子工具、技術與證照名稱；完整句子、產業／年資經驗、語言程度及軟技能會被移除

未命中的技能會被移除。若整組都沒有任何 grounded 技能，整組門檻會被移除；若移除後
技能數少於原本 `min_matches`，門檻會降至剩餘技能數。

### 7.3 學歷與學校門檻

- `min_education` 不信任 LLM 生成值，直接由 `requirements.education` 正規化得出
- 支援 `high_school`、`associate`、`bachelor`、`master`、`phd`
- 無法辨識或沒有明確最低學歷時保持空值
- `min_school_tier` 自動生成時永遠清空

`min_school_tier` 是系統內部 A/B/C 分級，JD 沒有可靠且公平的欄位可以直接對應，因此
不能由 LLM 自動推測。審核者仍可在人工確認後設定。

### 7.4 偽程式碼

```text
requirements = job.requirements
required_text = flatten(requirements excluding education and experience_years)

grounded_groups = []
for group in llm_profile.hard_filters.must_have_groups:
    grounded_skills = []
    for skill in group.skills:
        if literal_match(skill, required_text):
            grounded_skills.append(skill)

    if grounded_skills is not empty:
        group.skills = grounded_skills
        group.min_matches = clamp(group.min_matches, 1, len(grounded_skills))
        grounded_groups.append(group)

min_education = normalize_degree(requirements.education)
min_school_tier = ""
```

### 7.5 範例

JD 結構化結果：

```json
{
  "requirements": {
    "education": "大學以上",
    "skills": ["Python"]
  },
  "preferred_qualifications": ["具 Kubernetes 經驗尤佳"]
}
```

LLM 初稿：

```json
{
  "must_have_groups": [
    {
      "name": "技術門檻",
      "skills": ["Python", "Kubernetes", "Go"],
      "min_matches": 2
    }
  ],
  "min_education": "master",
  "min_school_tier": "A"
}
```

Grounding 後：

```json
{
  "must_have_groups": [
    {
      "name": "技術門檻",
      "skills": ["Python"],
      "min_matches": 1
    }
  ],
  "min_education": "bachelor",
  "min_school_tier": ""
}
```

Kubernetes 被移除是因為它只存在於加分條件；Go 在 JD 中沒有證據；最低學歷依 JD
校正為 bachelor；學校等級不允許自動推測。

---

## 8. 驗證與定向重試

修補後的資料先經 `DomainProfile.model_validate()` 驗證 Schema，再由
`validate_profile()` 檢查實際評分可用性。

### 8.1 可用性檢查

目前檢查項目包括：

1. Tier 必須完整涵蓋 0、1、2、3。
2. 每個 Tier 都必須有非空白 `definition`。
3. Tier 1–3 各至少有 4 個關鍵字。
4. Tier 3 權重最高的兩個關鍵字合計至少 3.0，確保最高級距可由 fallback 到達。
5. 至少有一個 competency。
6. 每個 competency 至少有一級包含關鍵字。
7. 五構面權重總和必須是 1.0，且不可含未知維度。
8. 自動生成的每個 Tier 至少要有 2 個繁體中文與 2 個英文關鍵字。
9. 有內容的 competency level 與 ecosystem 必須包含繁體中文訊號；若學歷重要且有科系，
   科系清單也必須包含繁體中文名稱。

這裡檢查的是「能否有效篩選」，不只是 JSON 能否解析。格式合法但每個 Tier 只有一個
冷門詞的 Profile，實際上幾乎無法區分候選人，因此仍判定為不合格。

第 8–9 項是生成品質檢查，不會套用到既有人工 Profile。它們用來避免英文 JD 生成
全英文訊號後，因中文履歷沒有相同字面而被系統性低估；語言覆蓋不足會觸發同一次定向重試。

若 JD 只要求最低學位、沒有指定相關科系，生成修補會把 `education.matters` 設為 false：
最低學位仍由 hard filter 驗證，但學校名氣或無關領域的碩士不會額外拉高排序。只有 JD
明確指定科系時，教育背景才保留為加權評分構面。

### 8.2 定向修正一次

若第一版 Profile 有可用性錯誤，演算法才會進行第二次 LLM 呼叫：

1. 將驗證錯誤、原職缺內容及待修正初稿送回模型。
2. 將溫度降至 `0.1`。
3. 要求只修正列出的問題，禁止新增 JD 未要求的硬門檻。
4. 修正版重新經過完整修補、grounding 與驗證。
5. 只有修正版的錯誤數量少於初稿時，才採用修正版。
6. 修正呼叫失敗、JSON 無效或品質沒有改善時，保留初稿與原錯誤。

因此，合格輸出只消耗一次 Profile LLM 呼叫；不合格輸出最多再呼叫一次，不會無限重試。

注意：第一個 LLM 回應若完全不是可解析的 JSON，會直接視為生成失敗，由 API 回傳 502；
目前的定向重試只處理已能解析、但未通過可用性驗證的 Profile。

---

## 9. 人工審核與生命週期

生成完成不代表可以直接使用。Profile 狀態與「目前使用中的職缺」是兩個不同概念：
狀態表示標準是否可用；active job id 表示新評分工作實際採用哪一個職缺。

| 狀態 | 意義 | 是否可供正式評分 |
|---|---|---|
| `none` | 尚無 Profile | 否 |
| `failed` | JD 已保存，但 Profile 生成失敗 | 否 |
| `draft` | 已生成或人工編輯，等待確認 | 否 |
| `ready` | Profile 已通過驗證 | 可以，但職缺仍須設為 active |

### 9.1 審核流程

1. 上傳 JD 後，Profile 一律以 `draft` 儲存。
2. 前端同時顯示解析後 JD 與生成標準，供使用者逐項比對。
3. 使用者可修改 Tier、關鍵字、能力面向、學歷、技能族群、硬門檻及權重。
4. `POST /api/job-postings/{id}/preview` 可用尚未儲存的 Profile 對候選人樣本試算。
5. Preview 使用關鍵字路徑，不呼叫候選人 LLM，也不寫入正式分數。
6. 啟用時再次執行 `validate_profile()`；有任何錯誤便拒絕啟用。
7. 啟用只影響之後的評分工作，不會自動重新計算既有候選人分數。

人工編輯 LLM Profile 後，`source` 會從 `llm` 改為 `manual`，保留來源可追溯性。

### 9.2 Fingerprint 與快取失效

`DomainProfile.fingerprint()` 對所有會影響分數的欄位產生 12 字元 MD5 摘要，包括：

- tiers
- tier_keywords
- competencies
- education
- ecosystems
- hard_filters
- weights

Fingerprint 會加入候選人 LLM Tier 快取鍵。只要審核者修改標準，舊 Profile 產生的分類
快取便不再命中，避免沿用過期結果。

---

## 10. API 與錯誤處理

| API | 用途 |
|---|---|
| `POST /api/job-postings/upload` | 上傳／貼上 JD，執行兩階段生成 |
| `GET /api/job-postings/{id}` | 取得結構化 JD、Profile 與驗證錯誤 |
| `PUT /api/job-postings/{id}/profile` | 儲存人工編輯內容，可選擇啟用 |
| `POST /api/job-postings/{id}/profile/regenerate` | 使用已保存的 JD 重新生成草稿 |
| `POST /api/job-postings/{id}/preview` | 使用候選人樣本試算，不儲存 |
| `POST /api/job-postings/{id}/activate` | 將職缺設為正式評分職缺 |

主要失敗情境：

| 情境 | 處理方式 |
|---|---|
| 無檔案且無文字 | 400 |
| 檔案超過 10 MB | 413 |
| 無法辨識檔案格式 | 415 |
| 掃描 PDF、空 Word、內容過短 | 422 |
| JD 結構化 LLM 失敗 | 502，不建立職缺 |
| Profile LLM 失敗 | 502，但保存 JD，狀態設為 `failed` |
| 修正 LLM 失敗 | 保留可解析初稿及其驗證錯誤 |
| 有驗證錯誤卻要求啟用 | 400，草稿不得投入正式篩選 |

---

## 11. 測試策略

`tests/test_profile_builder.py` 專門覆蓋生成演算法的安全邊界：

- 只有 `requirements` 能提供硬門檻證據
- `preferred_qualifications` 與 `responsibilities` 不會成為硬門檻
- 多字英文技能能正確比對
- `Go` 不會錯誤命中 `Google`
- 跨 Tier 重複訊號會被移除
- 關鍵字權重會限制在 0.5–2.5
- 首輪品質不合格時只修正一次
- 首輪合格時只呼叫一次 LLM

執行相關測試：

```bash
pytest -q tests/test_profile_builder.py tests/test_domain_profiles.py
```

執行完整測試與靜態檢查：

```bash
ruff check app/scoring/profile_builder.py tests/test_profile_builder.py
pytest -q
```

---

## 12. 修改演算法時的檢查清單

調整 prompt、Schema 或修補邏輯時，至少確認：

- [ ] 加分條件仍不會流入 `requirements`
- [ ] 工作內容仍不會直接成為 hard filter
- [ ] 自動硬門檻仍只使用結構化 `requirements` grounding
- [ ] 沒有將原始 JD 全文加入 hard-filter grounding
- [ ] `min_school_tier` 沒有由 LLM 自動推測
- [ ] Tier 0–3 定義仍描述可觀察證據，而非只描述年資
- [ ] Tier 關鍵字仍可支援 LLM 離線 fallback
- [ ] 生成式 Profile 的關鍵字不會覆蓋成功的候選人 LLM Tier
- [ ] 跨 Tier 重複關鍵字不會讓低階訊號觸發高階分類
- [ ] 權重正規化後總和精確為 1.0
- [ ] 品質修正最多執行一次
- [ ] 有驗證錯誤的 Profile 仍無法啟用
- [ ] Profile 內容變更仍會改變 fingerprint

---

## 13. 已知限制

1. JD 結構化本身仍由 LLM 完成；如果模型把「加分」錯分到 `requirements`，後續 grounding
   會把它視為必要條件。人工審核仍是必要防線。
2. 技能 grounding 採字面比對，不做同義詞推論。例如 JD 寫 `PostgreSQL`，模型生成
   `Postgres` 時可能被移除。這是刻意偏保守的設計。
3. Profile 初始回應若完全無法解析為 JSON，目前不會進行格式修復重試。
4. 掃描版 JD PDF 目前不做 OCR。
5. 自動驗證能發現結構與可達性問題，但無法完全判斷領域內容是否合理，因此 Profile
   必須維持 draft → 人工確認 → ready → active 的啟用流程。
6. 人工修改結構化 JD 後不會自動重建 Profile；應由使用者明確執行重新生成，再次審核
   新草稿。
7. 最低年資、指定產業經驗與語言熟練度目前尚無結構化 hard-filter evaluator；系統會將
   它們保留在 JD 與語意評分中，但不以脆弱的字面句子比對自動淘汰候選人。
