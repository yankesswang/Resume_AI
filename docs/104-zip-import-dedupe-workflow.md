# 104 ZIP 匯入、DB 整理與去重流程

本文件記錄目前短期架構已完成的改動，以及之後每次從 104 下載 ZIP 後的建議操作流程。

## 目前完成的改動

### DB metadata

這次已把 `unique_0522履歷-20260525T025222Z-3-001.db` 整理成可追蹤批次的結構。新增內容如下：

| 類型 | 名稱 | 用途 |
|---|---|---|
| table | `import_batches` | 記錄每次 104 ZIP 匯入批次、ZIP hash、候選人數、unique/duplicate/review 統計 |
| table | `import_files` | 記錄每個 PDF、PDF hash、parse 狀態、該 PDF 產生的 candidate 數 |
| table | `candidate_dedupe_status` | 記錄每個 candidate 的 unique/duplicate/review 狀態與命中原因 |
| view | `v_candidates_with_dedupe` | candidate + batch + dedupe + score 的整合檢視 |
| view | `v_unique_candidates` | `is_unique = 1` 的候選人 |
| view | `v_duplicate_candidates` | `is_unique = 0` 的候選人 |

`candidates` 也新增了幾個 metadata 欄位：

| 欄位 | 用途 |
|---|---|
| `import_batch_id` | 對應 `import_batches.id` |
| `import_file_id` | 對應 `import_files.id` |
| `raw_md_sha256` | parsed markdown 內容 hash，之後可判斷內容是否變動 |
| `parser_version` | 記錄 parse/整理版本 |

### Dedupe 狀態

目前 dedupe 不會刪資料，只會標記。

| 狀態 | 意義 |
|---|---|
| `unique` | 沒有被舊 DB 的強訊號命中 |
| `duplicate` | 被舊 DB 的 `code_104`、email 或 mobile 命中 |
| `review` | 沒有強命中，但姓名 + 出生年命中，建議人工確認 |

手機比對會排除明顯 placeholder，例如：

- `0900000000`
- `0912345678`
- `0987654321`
- 全部數字相同的電話

### 目前 0522 批次結果

| 項目 | 數量 |
|---|---:|
| PDF files | 11 |
| candidates | 1959 |
| unique | 412 |
| duplicate | 1547 |
| review | 2 |

報表：

- `reports/unique_0522_candidates.csv`
- `reports/dedupe_status_0522.csv`

備份：

- `backups/unique_0522履歷-20260525T025222Z-3-001.backup-20260526-111407.db`

## 後端與前端

### 後端啟動指定 DB

```bash
DB_PATH=/home/trx50/Project/Resume_AI/unique_0522履歷-20260525T025222Z-3-001.db \
OUTPUT_DIR=/home/trx50/Project/Resume_AI/output_unique_0522履歷-20260525T025222Z-3-001 \
uv run python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

### 前端

```bash
cd frontend
npm run dev
```

URL：

- 全部候選人：`http://127.0.0.1:3002/`
- Unique view：`http://127.0.0.1:3002/unique`

前端 filters 已支援：

- Batch 下拉
- `Unique`
- `Duplicate`
- `Review`
- Score / AI Tier / 技能 / 學歷 / 身分 / 感興趣等既有 filter

## API

| API | 用途 |
|---|---|
| `GET /api/import-batches` | 取得所有匯入批次 |
| `GET /api/candidates?scope=unique` | 只看 unique candidates |
| `GET /api/candidates?scope=duplicate` | 只看 duplicate candidates |
| `GET /api/candidates?scope=review` | 只看 review candidates |
| `GET /api/candidates?batch_id=1` | 只看指定 batch |
| `GET /api/filters?batch_id=1` | 取得指定 batch 的 filter options |

`scope` 和 `batch_id` 可合併使用。

## 每次新 104 ZIP 的建議流程

### 一鍵匯入 ZIP

```bash
uv run python scripts/import_104_zip.py /path/to/104.zip \
  --db resume_ai.db
```

這支 script 會做：

1. 安全解壓 ZIP
2. 找出 ZIP 內所有 PDF
3. 逐 PDF 執行 `scripts/batch_import.py`
4. 寫入 candidates
5. 執行 `scripts/organize_resume_db.py`
6. 建立/更新 batch、file、dedupe metadata

預設不跑 LLM/scoring，避免每次匯入都跑很久。

### 匯入後直接跑 LLM + scoring

```bash
uv run python scripts/import_104_zip.py /path/to/104.zip \
  --db resume_ai.db \
  --run-llm-score
```

若 LM Studio 不是預設 localhost，先設定：

```bash
export LM_STUDIO_URL=http://127.0.0.1:1234/v1/chat/completions
export EMBEDDING_URL=http://127.0.0.1:1234/v1/embeddings
export EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
```

### 只整理既有 DB

如果 DB 已經 parse/scoring 完，只想補 batch/dedupe metadata：

```bash
uv run python scripts/organize_resume_db.py \
  --db unique_0522履歷-20260525T025222Z-3-001.db \
  --batch-name '0522履歷-20260525T025222Z-3-001' \
  --zip-path '0522履歷-20260525T025222Z-3-001.zip' \
  --output-root 'output_unique_0522履歷-20260525T025222Z-3-001'
```

`organize_resume_db.py` 會先備份 DB，再做非破壞式 migration。

## 操作原則

- 不刪重複資料，只標記 `unique / duplicate / review`。
- 每次 ZIP 都建立/更新一個 `import_batches`。
- 每個 PDF 都應有一筆 `import_files`。
- 前端透過 batch + dedupe filters 找人，不再靠手工 CSV。
- 舊 DB 短期仍可當 dedupe baseline；中期建議合併成一個 master DB。

