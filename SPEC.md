# 系統架構：智慧型 LLM 工程師篩選漏斗

本系統旨在解決傳統關鍵字篩選無法識別「API 調用者（Wrapper）」與「模型開發者（Model Developer）」的核心痛點。系統分為三大模組：

1. **特徵工程 (Feature Engineering)：** 解析履歷並結構化。
2. **三階段篩選 (The 3-Layer Funnel)：** 過濾 -> 召回 -> 精排。
3. **動態評分模型 (Scoring Mechanism)：** 結合語意與技術深度的最終算分。

---

## 第一模組：特徵工程與解析 (Data Parsing & Structuring)

在進入評分前，LLM 需將非結構化履歷轉換為 JSON，並針對四大維度進行「標籤化」與「隱性提取」。

### 1. 教育背景 (Education) - 權重 40% (基礎分)

- **目標：** 量化學術含金量。
- **計算公式：**
    
    $Score_{Edu} = (S_{Tier} \times 0.5) + (D_{Level} \times 0.3) + (M_{Relevance} \times 0.2) + Bonus_{Thesis}$
    
    - **$S_{Tier}$ (學校層級)：** 依據 QS 排名或頂尖資工院校列表給分。
    - **$D_{Level}$ (學位)：** 博士 > 碩士 > 學士。
    - **$M_{Relevance}$ (科系相關性)：** CS/EE/Math/Stat 為 Tier 1，其他理工 Tier 2。
    - **$Bonus_{Thesis}$ (碩論加分)：** 若論文題目經 Embedding 比對屬於 NLP/CV/AI 領域，且發表於頂會 (NeurIPS, ICLR, CVPR)，給予額外加權。

### 2. 工作經驗 (Experience) - 權重 30%

---

### AI 工程師經驗匹配核心邏輯：四層金字塔 (The 4-Tier Pyramid)

我們不只看「有沒有做過」，而是看「介入多深」。LLM 應將候選人的每一段工作經驗分類到以下四個層級之一，並給予不同權重。

### **Tier 1: 基礎應用層 (The Wrapper) —— [匹配分：60分]**

- **特徵：** 主要是串接 OpenAI/Claude API，寫 Prompt，做簡單的 Chatbot UI。
- **關鍵字訊號：** `OpenAI API`, `Prompt Engineering`, `Streamlit`, `LangChain (Basic)`, `Chatbot`.
- **LLM 判斷邏輯：**
    
    > "該專案是否僅涉及 API Key 的管理與 Prompt 的調整，而沒有涉及任何資料處理、向量庫優化或模型部署？"
    > 

### **Tier 2: 系統架構層 (The RAG/Agent Architect) —— [匹配分：80分]**

- **特徵：** 處理過幻覺 (Hallucination)、做過 RAG 優化 (Reranking, Hybrid Search)、設計過 Agent 流程 (Function Calling)。
- **關鍵字訊號：** `Vector Database (Milvus/Qdrant)`, `RAG`, `Embedding optimization`, `Hybrid Search`, `Function Calling`, `ReAct`, `GraphRAG`.
- **LLM 判斷邏輯：**
    
    > "該候選人是否解決了 Context Window 限制？是否實作了複雜的檢索策略（如 HyDE, Parent Document Retriever）？"
    > 

### **Tier 3: 模型工程層 (The Model Tuner) —— [匹配分：90分]**

- **特徵：** 碰過模型權重。做過 Fine-tuning (SFT), Parameter-Efficient Fine-Tuning (PEFT), 模型量化。
- **關鍵字訊號：** `PyTorch`, `HuggingFace`, `LoRA/QLoRA`, `Fine-tuning`, `Llama 3`, `Quantization (GGUF/AWQ)`, `BitsAndBytes`.
- **LLM 判斷邏輯：**
    
    > "該候選人是否具備訓練或微調模型的能力？是否理解 Loss Function、Learning Rate Scheduler 對模型收斂的影響？"
    > 

### **Tier 4: 底層優化與部署層 (The Inference/Ops Engineer) —— [匹配分：100分]**

- **特徵：** 解決過推論延遲 (Latency)、高併發 (Throughput)、GPU 記憶體管理、自定義 CUDA Kernel。
- **關鍵字訊號：** `vLLM`, `TensorRT-LLM`, `TGI`, `CUDA`, `Flash Attention`, `KV Cache`, `Speculative Decoding`, `GPU Optimization`.
- **LLM 判斷邏輯：**
    
    > "該候選人是否具備將模型部署到生產環境並優化其性能（TPS/Latency）的能力？"
    > 

---

### 自動化評分演算法設計

針對每一段工作經驗描述 ($Exp_i$)，我們計算其匹配分數。

### 1. 技術棧匹配度 ($S_{stack}$)

LLM 提取經驗中的技術關鍵字，並與 JD 的需求做 **交集加權 (Intersection Weighted Score)**。

$$S_{stack} = \sum (Keyword_i \times Weight_i)$$

- **權重設定範例：**
    - `Python`: 1.0 (基本)
    - `LangChain`: 1.2 (應用)
    - `Pytorch`: 1.5 (框架)
    - `vLLM/TensorRT`: 2.0 (部署優化 - 高價值)
    - `CUDA`: 2.5 (底層 - 稀缺)

### 2. 專案複雜度判定 ($S_{complexity}$)

LLM 需進行語意分析，判斷專案的規模與難度：

- **資料規模 (Data Scale):** 處理百萬級向量 vs. 幾千筆資料。
- **系統架構 (System Architecture):** 單機腳本 vs. 分散式微服務 (K8s)。
- **模型規模 (Model Scale):** 跑 7B 模型 vs. 訓練 70B 模型。

### 3. 落地指標驗證 ($S_{metric}$) —— **「防吹牛」機制**

檢查工作描述中是否包含「AI 專屬的量化指標」。若有，分數加成；若無，視為普通描述。

- **有效指標 (Positive Signals):**
    - "Reduced inference latency by **40%** (500ms -> 300ms)."
    - "Improved RAG retrieval accuracy (Recall@10) by **15%**."
    - "Optimized VRAM usage allowed running Llama-70B on **2x A100**."
- **無效/虛榮指標 (Vanity Metrics):**
    - "Built a chatbot with 99% accuracy." (AI 領域通常不用單純 Accuracy 描述生成任務，這顯示不專業)
    - "Used AI to improve efficiency." (太籠統)

---

### **「工程落地能力加權 (Engineering Maturity Booster)」**。

這會是一個 **「加分項 (Bonus)」**，用來區分 **Research Scientist (學術派)** 與 **AI Product Engineer (實戰派)**。

---

### 新增模組：全端工程能力評估矩陣 (Full-Stack Capability Matrix)

我們將開發經驗分為三大支柱：**Backend (後端與架構)**、**Database (資料庫)**、**Frontend (前端與展示)**。

### 1. Backend & Architecture (後端架構) - 權重最高

AI 模型最終需要被 Serving。這裡重點看 **「併發處理」** 與 **「微服務」**。

- **Level 1 (Basic):** 會寫 `Flask` 或 `FastAPI` 做簡單的 `app.route`。
    - *關鍵字:* Flask, Django (Basic), REST API, Python Scripting.
- **Level 2 (Production):** 懂異步處理 (Async), Docker 容器化, Nginx 反向代理。
    - *關鍵字:* `Asyncio`, `Docker`, `Gunicorn`, `Uvicorn`, `CI/CD`, `GitHub Actions`.
- **Level 3 (High Scale):** 懂微服務、Message Queue (處理大量推理請求)、gRPC。
    - *關鍵字:* `Kubernetes (K8s)`, `RabbitMQ`, `Kafka`, `Redis (Cache)`, `Celery`, `Go (Golang)`, `Rust`.
    - **評分邏輯：** 若出現 Message Queue 或 K8s，代表他能處理「高流量 AI 應用」，大幅加分。

### 2. Database & Data Pipeline (資料庫) - 權重次之

AI 的靈魂是數據。這裡重點看 **「非關聯式資料庫」** 與 **「向量儲存」** 的整合能力。

- **Level 1 (Basic):** 基本 SQL 語法 (Select/Join)。
    - *關鍵字:* MySQL, SQLite, CSV, Pandas.
- **Level 2 (Advanced):** ORM 優化, NoSQL, 資料清理管道 (ETL)。
    - *關鍵字:* `PostgreSQL`, `MongoDB`, `SQLAlchemy`, `Airflow`, `Elasticsearch`.
- **Level 3 (Vector Native):** 懂向量資料庫的索引優化 (HNSW, IVF)，這對 RAG 至關重要。
    - *關鍵字:* `pgvector`, `Milvus`, `Qdrant`, `Pinecone`, `Neo4j (Graph DB)`.
    - **評分邏輯：** 若候選人能同時處理 `PostgreSQL` (關聯數據) 與 `Vector DB` (語意數據)，視為 RAG 系統的即戰力。

### 3. Frontend (前端展示) - 權重最低 (但為亮點)

AI 工程師若能自己刻出 Demo UI，能大幅降低與前端團隊的溝通成本，快速驗證想法 (PoC)。

- **Level 1 (Prototyping):** 只會用 Python 的快速框架。
    - *關鍵字:* `Streamlit`, `Gradio`, `Dash`. (這是 AI 工程師標配，不特別加分)
- **Level 2 (Web Basic):** 懂 HTML/CSS/JS，能修改現成模板。
    - *關鍵字:* HTML5, CSS3, Bootstrap, JavaScript (Vanilla).
- **Level 3 (Modern Framework):** 能寫 React/Vue，串接 API 並處理 Streaming Response (打字機效果)。
    - *關鍵字:* `React`, `Vue.js`, `Next.js`, `TypeScript`, `Tailwind CSS`.
    - **評分邏輯：** 懂得用 React 處理 `SSE (Server-Sent Events)` 來做串流輸出的人，是極稀有的全端 AI 人才。

---

### 修正後的總分公式：加權總和 = 100 分

五大維度各自為 0-100 分，乘以各自權重後加總，滿分恰好為 100 分。

$$S_{Final} = (S_{AI} \times 0.35) + (S_{Eng} \times 0.20) + (S_{Semantic} \times 0.20) + (S_{Edu} \times 0.15) + (S_{Skill} \times 0.10)$$

| **維度** | **權重** | **滿分貢獻** | **來源** |
| --- | --- | --- | --- |
| **$S_{AI}$ (AI 經驗深度)** | **35%** | **35 分** | 4-Tier Pyramid 分數 (0-100) |
| **$S_{Eng}$ (工程落地能力)** | **20%** | **20 分** | M_Eng (0-0.5) 正規化至 0-100 |
| **$S_{Semantic}$ (語意匹配度)** | **20%** | **20 分** | Cosine Similarity (0-1) 正規化至 0-100 |
| **$S_{Edu}$ (教育背景)** | **15%** | **15 分** | 學校層級 + 學位 + 科系 (0-100) |
| **$S_{Skill}$ (技能驗證)** | **10%** | **10 分** | 生態系分類 + 交叉驗證 (0-100) |

### $S_{Eng}$ 工程能力正規化方式：

$M_{Eng}$ (0-0.5) 正規化為 0-100 分：$S_{Eng} = \frac{M_{Eng}}{0.5} \times 100$

1. **Backend Score ($B$):**
    - 無經驗: 0
    - API 開發: +0.1
    - 高併發/K8s: +0.25
2. **Database Score ($D$):**
    - 無經驗: 0
    - SQL/NoSQL: +0.1
    - Vector DB/ETL: +0.15
3. **Frontend Score ($F$):**
    - Streamlit: 0 (預設應具備)
    - React/Vue: +0.1

$$M_{Eng} = B + D + F \quad (\max 0.5)$$

---

### 實際案例演算

**候選人 A (純學術派)**

- **AI 能力:** 熟悉 PyTorch, 訓練過 Llama 2 (Tier 3)。 $\rightarrow S_{AI} = 90$
- **工程能力:** 只會用 Jupyter Notebook，不會寫 API，沒碰過 DB。 $\rightarrow M_{Eng} = 0, S_{Eng} = 0$
- **教育：** 台大碩士 CS。 $\rightarrow S_{Edu} = 100$
- **技能：** LLM Stack。 $\rightarrow S_{Skill} = 90$
- **語意匹配：** 0.7。 $\rightarrow S_{Semantic} = 70$
- **最終得分:** $(90 \times 0.35) + (0 \times 0.20) + (70 \times 0.20) + (100 \times 0.15) + (90 \times 0.10) = 31.5 + 0 + 14 + 15 + 9 = \mathbf{69.5}$

**候選人 B (全端 AI 工程師)**

- **AI 能力:** 只會接 LangChain 做 RAG，沒訓練過模型 (Tier 2)。 $\rightarrow S_{AI} = 80$
- **工程能力:**
    - 後端：寫過 FastAPI 微服務，用 Docker 部署 (+0.25)
    - DB：熟 Postgres 且用過 pgvector (+0.15)
    - 前端：會寫 Next.js 做 Chat 介面 (+0.1)
    - $\rightarrow M_{Eng} = 0.5, S_{Eng} = 100$
- **教育：** B 級學校碩士 EE。 $\rightarrow S_{Edu} = 65$
- **技能：** LLM Stack。 $\rightarrow S_{Skill} = 90$
- **語意匹配：** 0.8。 $\rightarrow S_{Semantic} = 80$
- **最終得分:** $(80 \times 0.35) + (100 \times 0.20) + (80 \times 0.20) + (65 \times 0.15) + (90 \times 0.10) = 28 + 20 + 16 + 9.75 + 9 = \mathbf{82.75}$

### 結論

透過這個公式，系統會**優先推薦候選人 B (82.75 vs 69.5)**。

雖然 B 的 AI 理論深度不如 A，但工程落地能力 (20分 vs 0分) 讓 B 的總分大幅領先。在企業實戰中，**B 一個人可以抵 A + 一個後端工程師**。這符合「技術落地」與「解決商業問題」的核心需求，且所有分數加總不超過 100 分。

### 3. 才能專長 (Skills) - 權重 10%

- **技術棧生態系判定 (Ecosystem Check)：**
    - **容錯機制：** 若 JD 需 React 但候選人會 Vue/Angular $\rightarrow$ 判定為「具備現代前端概念」，不扣分。
    - **分類對齊：**
        - *Traditional ML:* Sklearn, XGBoost.
        - *Deep Learning:* PyTorch, TensorFlow, Jax.
        - *LLM Stack:* LangChain, LlamaIndex, vLLM, Ollama (此類別在 LLM 職位中權重最高)。
- **熟練度驗證 (Verification)：**
    - **防偽檢查：** 若 Skill 寫 "Python Expert"，但 Project 描述全用 Java $\rightarrow$ 標記 **Suspicious (可疑)** 並降權。

### 4. 專案 (Projects) - 權重 20%

- **技術落地 (Business Impact)：** 搜尋關鍵字如「提升精準度 (Accuracy)」、「降低推論時間 (Inference Time/Latency)」、「節省成本 (Cost Reduction)」。
- **亮點偵測 (Tech Spotting)：** 偵測關鍵字：*RAG, PEFT (LoRA/QLoRA), Vector DB (Pinecone/Chroma), Quantization (GGUF/AWQ)*。

---

## 第二模組：三階段過濾流程 (The 3-Layer Filter)

這是一個由寬變窄的漏斗，確保效率與準確度。

### Layer 1: 硬性門檻過濾 (Hard Filters / Boolean)

- **目的：** 秒殺完全不合格者，節省算力。
- **邏輯：** 必須滿足所有 "Must-have"。
- **LLM Engineer 規則範例：**
    - `Python Proficiency == True`
    - `Framework (PyTorch OR TensorFlow) == True`
    - `Keywords (Transformer OR Attention OR BERT OR LLM) == True`

### Layer 2: 向量語意召回 (Semantic Vector Matching)

- **目的：** 找出「概念相似」但「用詞不同」的候選人，建立高召回 (High Recall) 名單 (Top-K)。
- **技術實作：** 使用 `text-embedding-3-large` 或 `bge-m3`。
- **三大應用場景：**
    1. **技能語意對齊：** JD 寫 "Vector Database"，履歷寫 "Milvus/Pinecone" $\rightarrow$ 向量距離近 $\rightarrow$ **Match**。
    2. **專案領域匹配：** JD 寫 "智慧客服"，履歷寫 "LLM-based QA System" $\rightarrow$ **Match**。
    3. **以人找人 (Seed Search)：** 將公司內部的 Top Performer 履歷轉為向量，搜尋最像他的候選人。

### Layer 3: LLM 推理評分 (Deep Reasoning & Grading)

- **目的：** 這是最關鍵的一步，用來區分「調參仔」與「架構師」。
- **執行方式：** 將 Layer 2 篩出的 Top 50 候選人資料丟入 LLM (如 Gemini 1.5 Pro) 進行深度分析。
- **Prompt 邏輯設計：**
    - **深度驗證 (Depth Check):** "分析專案內容。該候選人是僅調用 OpenAI API (Wrapper)，還是涉及 Model Fine-tuning / Quantization / RAG Pipeline Optimization？前者給低分，後者給高分。"
    - **學術 vs 實戰 (Research vs Engineering):** "檢查是否提及 Paper Implementation 或解決 OOM (Out of Memory) 問題。"
    - **文化契合 (Growth Mindset):** "從自傳與專案歷程分析其自學新技術（如上個月才出的新模型）的速度。"

---

## 第三模組：最終加權評分公式 (Final Scoring Algorithm)

結合前面的分析，計算出候選人的最終得分 $S_{Final}$，滿分為 **100 分**。

$$S_{Final} = (S_{AI} \times 0.35) + (S_{Eng} \times 0.20) + (S_{Semantic} \times 0.20) + (S_{Edu} \times 0.15) + (S_{Skill} \times 0.10)$$

**權重配置 (針對 LLM Engineer 職位)：**

| **維度** | **名稱** | **權重** | **來源** | **意義** |
| --- | --- | --- | --- | --- |
| **$S_{AI}$** | **AI 經驗深度** | **35%** | 4-Tier Pyramid | **核心指標。** 判斷 API Caller vs. Model Developer 的技術深度。 |
| **$S_{Eng}$** | **工程落地能力** | **20%** | Engineering Matrix | 評估後端/資料庫/前端的全端能力，區分學術派與實戰派。 |
| **$S_{Semantic}$** | **語意匹配度** | **20%** | Layer 2 (Embedding) | 確保大方向正確，基本技能與 JD 描述吻合。 |
| **$S_{Edu}$** | **教育背景** | **15%** | Education Scoring | 學校層級、學位、科系相關性、論文加分。 |
| **$S_{Skill}$** | **技能驗證** | **10%** | Skill Verification | 技術棧生態系分類 + 防偽交叉驗證。 |

### 輸出結果 (Deliverable)

系統最終會產生一張 **Scorecard (評分卡)**：

1. **總分 (Total Score):** 例如 88/100。
2. **關鍵標籤 (Tags):** 例如 `#Fine-tuning`, `#RAG-Expert`, `#High-Potential`.
3. **理由摘要 (Reasoning):** "該候選人雖然學校非頂尖 (Tier 2)，但在 Github 上有一個 500 stars 的 RAG 專案，且深入解決了 Context Window 的限制問題，技術深度極高，強烈建議面試。"
4. **面試建議 (Gap Analysis):** "履歷中未提及部署經驗，面試時建議詢問 Docker/K8s 相關知識。"