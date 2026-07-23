# Gold QA set

`gold_v1.jsonl` — one JSON object per line, schema = `app.schemas.eval.GoldItem`:

```json
{"id": "aapl-10k-2025-net-sales", "question": "...", "filing_ref": "0000320193-25-000073",
 "expected_answer": "...", "expected_source_page": 31, "type": "numeric", "verified": false}
```

Rules (non-negotiable):

- 30–50 items spanning numeric/table and narrative questions.
- Candidate rows are **drafted from ingested filings** (phase 4 adds a draft
  helper that proposes Q/A pairs with source pages from the corpus).
- Every row starts `"verified": false` and is **excluded from scoring** until
  a human confirms the expected answer against the filing. Expected numbers
  are never fabricated.
- The file is versioned: edits after a scored run go into `gold_v2.jsonl`,
  never in-place, so regression comparisons stay meaningful.
