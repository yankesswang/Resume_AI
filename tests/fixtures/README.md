# Test fixtures

These resume markdown files are **entirely synthetic**. They reproduce the
structure of Marker's output for a 104.com resume PDF — section headings, table
layouts, the CJK compatibility characters (`⼯`/`⾃`) Marker emits, and the
flat-text OCR variant — but every name, phone number, email address, mailing
address and company name is invented.

No real applicant data is committed here. `output_*/` holds the real parsed
resumes and is deliberately not used as a fixture source: it is live PII.

## `job_descriptions/`

Synthetic job descriptions in three non-engineering fields, used to check that
the scoring engine works outside the AI-engineer role it was originally built
for. They are written the way a real 104/company JD is — 職務說明, numbered
responsibility groups, 應徵條件, 加分條件 — because the generator reads that
structure, and a JD stripped to bullet points does not exercise it.

| File | Field | What it exercises |
|---|---|---|
| `accountant.txt` | 財務會計 | Certifications (CPA/CIA), standards (IFRS), ERP systems |
| `marketing.txt` | 數位行銷 | Platform tools (GA4, Meta Ads), metrics (ROAS/CPA) |
| `sales.txt` | 業務開發 | Vocabulary with no technical nouns at all — the hardest case |

No company or product in them is real.

## `profiles/`

`sales.json` is a hand-written domain profile (the scoring standard for a
通路業務經理). `tests/test_domain_profiles.py` loads it rather than inlining a
copy, so the file the tests assert against is the same one you can open, upload
through the UI, and eyeball.

It is hand-written on purpose: a generated profile changes every time the model
runs, which would make the tests non-deterministic. To see what generation
actually produces, run the script instead:

```bash
# Generate from a JD and score real candidates against the result
uv run python scripts/try_job_profile.py tests/fixtures/job_descriptions/sales.txt

# Re-check a hand-written profile without calling the LLM
uv run python scripts/try_job_profile.py --profile tests/fixtures/profiles/sales.json
```
