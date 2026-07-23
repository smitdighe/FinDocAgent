# FinDocAgent — Backend

Multi-agent RAG over SEC filings (10-K / 10-Q) that answers financial questions with
cited, table-aware evidence, verified against source before returning.

## Architecture (short version)

```
EDGAR (HTML) ──fetch──> raw html ──Chromium print──> PDF ──raster──> page images (JPEG)
                                        │                               │
                                        ├─ pdfplumber ──> per-page text (FTS)
                                        └─ source-HTML tables ──> cell grids + page mapping
page images ──ColPali (ColQwen2, local batch)──> 128-dim multi-vectors ──> VectorChord MaxSim

query ─> router ─> retrieval (MaxSim + BM25 → RRF) [+ table QA if numeric]
      ─> synthesis (LLM via provider abstraction) ─> verifier (fail-closed on numbers) ─> answer
```

Key locked decisions and the *why*:

| Concern | Decision |
|---|---|
| Late interaction | VectorChord `vchordrq` MaxSim over `vector(128)[]` columns — true late interaction (`ORDER BY embeddings @# ARRAY[...]::vector[]`), not pooled single vectors. Verified against VectorChord **1.1.1** docs (MaxSim landed in 0.3.0). |
| Page-level citations | EDGAR serves continuous HTML — there are no native pages. We *manufacture* stable pagination: HTML → Chromium print PDF (Letter, fixed margins) → rasterized page images. Every `page_no` in this system means **our** rendered pagination. |
| Tables | Extracted from the **source HTML** (`<table>` elements, span-expanded into cell grids) because exact cell values are what the verifier re-checks; PDF geometry heuristics are lossy. Each table is then *located* on a rendered page via anchor-text search so citations stay page-level (bbox best-effort). |
| Embedding compute | `scripts/embed_batch.py` runs locally (GPU if available; CPU works, slower). The deployed API never embeds pages — it only embeds *queries* (text-only forward pass) and serves retrieval + LLM calls. |
| Synthesis provider | Groq is the prod default. vLLM is a local-only adapter; OpenAI proves swap-ability. Switching `LLM_PROVIDER=groq|vllm|openai` changes inference with zero edits under `app/agents/`. |
| Numbers | The verifier re-extracts every cited numeric claim from the stored source cells and blocks anything it cannot trace ("fail closed"). |

## Requirements

- Python 3.12 (managed via [uv](https://docs.astral.sh/uv/))
- Docker (local Postgres 17 + VectorChord)
- ~5 GB disk for the ColQwen2 checkpoint on first embed/query

## Quickstart

```bash
cd backend
cp .env.example .env            # fill in EDGAR_USER_AGENT (SEC requires contact info) + GROQ_API_KEY

docker compose up -d            # Postgres 17 + VectorChord 1.1.1 on localhost:5433
uv sync                         # creates .venv with pinned Python 3.12
uv run playwright install chromium

uv run alembic upgrade head     # schema: filings/pages/embeddings/tables + vchordrq maxsim index

# 1) ingest filings (fetch -> render -> extract; no embedding yet)
uv run python -m app.ingestion.cli ingest --tickers AAPL,MSFT --forms 10-K,10-Q --limit-per-form 2

# 2) batch-embed rendered pages (run on a GPU box for real corpora; CPU works for small sets)
uv run python scripts/embed_batch.py --batch-size 4

# 3) serve
uv run uvicorn app.main:app --reload
```

## API

- `POST /query` — SSE stream, one named event per agent hop (`router`, `retrieval`, `table`, `synthesis`, `verify`) then a final `answer` event. *(lands in phase 3)*
- `POST /query/sync` — same result, non-streamed (used by the eval harness). *(phase 3)*
- `GET /filings` — ingested filings + page counts.
- `GET /filings/{id}/pages/{n}` — page text + tables + image URL (citation viewer contract).
- `GET /filings/{id}/pages/{n}/image` — the rendered page JPEG.
- `POST /eval/run`, `GET /eval/runs`, `GET /eval/runs/{id}` — eval harness. *(phase 4)*
- `GET /health`, `GET /ready` — liveness / DB+extension readiness.

Errors are RFC 7807 `application/problem+json`. `/query*` is rate limited
(`RATE_LIMIT_QUERY`, default `20/minute`).

## Notes that will save you a debugging session

- **SEC fair access:** set `EDGAR_USER_AGENT` to something like
  `FinDocAgent/0.1 (you@example.com)` or EDGAR will 403 you. The client also
  throttles to ≤5 req/s.
- **Render deploy:** Render's *managed* Postgres does not ship the `vchord`
  extension. `render.yaml` therefore runs `tensorchord/vchord-postgres` as a
  private service with a persistent disk, and the web service points
  `DATABASE_URL` at it.
- **GPU embedding:** default torch wheels here are CPU. On a CUDA box:
  `uv pip install torch --index-url https://download.pytorch.org/whl/cu126`.
## Eval harness (phase 4)

`app/eval/gold/gold_v1.jsonl` is the fixed, versioned gold set (33 items:
20 verified numeric + 1 verified narrative, plus 12 unverified drafts).
Expected answers are read from the ingested filings' source cells — never
fabricated — and `verified: false` rows are excluded from scoring until a
human confirms them.

**Metric framework — RAGAS triad, implemented deterministically.** The three
required metrics are the RAGAS triad (`faithfulness`, `answer_relevancy`,
`context_precision`). We implement them against the gold ground truth rather
than pulling in the `ragas` package + an LLM judge, because:

1. **Reproducibility is the whole point of regression tracking.** An LLM judge
   makes scores non-deterministic run-to-run, so per-metric deltas would mix
   pipeline change with judge noise. Ground-truth anchoring makes a delta mean
   a pipeline change.
2. **It runs in CI with no paid judge / no key.** The eval must run anywhere.
3. **Ground truth is stricter than self-consistency** for factual financial QA:
   we know the exact expected figure and source page.

Definitions (`app/eval/metrics.py`): `context_precision` = reciprocal rank of
the gold source page in retrieved candidates; `faithfulness` = the verifier's
grounding verdict (a blocked/"failed" answer scores 0); `answer_relevancy` =
expected figure present within tolerance (numeric) or content-word recall
(narrative). An LLM-judge refinement can be layered later via the provider
abstraction.

`POST /eval/run` runs the full pipeline over the verified rows, writes an
`EvalRun` (git SHA + gold version + scores + cost/latency rollup), and returns
per-metric deltas vs. the previous run on the same gold version.

**Baseline (FTS-only, no query embeddings, deterministic synthesis):**
`answer_accuracy ≈ 0.71`, `faithfulness = 1.0`, `context_precision ≈ 0.49`
over 21 verified items at ~30 ms/query, $0 cost. Enabling the visual/MaxSim
path (`QUERY_EMBEDDING=true`) and an LLM synthesizer is expected to raise
accuracy and context precision — and the regression harness is exactly how we
measure that lift commit-to-commit.

## Observability & cost (phase 5)

Every agent hop emits a `NodeTrace` (latency, tokens in/out, cost USD); costs
come from each provider's price table (`app/observability/cost.py`). The full
per-query rollup — answer, verification status, per-agent trace, cost, latency,
provider, model — is persisted to `QueryLog` on every `/query` and
`/query/sync`. That store is the source of truth (the spec's "OTel spans + a
custom store" option); **`GET /stats`** reads it back with aggregate cost /
latency and recent per-query traces.

Langfuse spans are emitted per hop *in addition*, but only when `LANGFUSE_*`
creds are set — the integration is best-effort and wrapped so it can never
break a query.

**Real cost per query:** with the default FTS + deterministic synthesis path
(no LLM key) a query costs **$0** at ~30–45 ms end-to-end. With Groq synthesis
(`openai/gpt-oss-120b`, $0.15/$0.60 per Mtok) a typical answer of ~1.4k
input + ~120 output tokens is **≈ $0.00028/query**, computed from the price
table by the same accounting code.

## Status

- [x] Phase 1 — ingestion + rendering + tables + VectorChord MaxSim store
- [x] Phase 2 — router + hybrid retrieval + table QA agents
- [x] Phase 3 — synthesis + verifier + LangGraph wiring + SSE
- [x] Phase 4 — eval harness + gold set + regression tracking
- [x] Phase 5 — tracing + per-query cost accounting

Query-embedding note: the visual/MaxSim retrieval path is wired and tested; set
`QUERY_EMBEDDING=true` (with the ColPali model available) to load the encoder
in the API process. Left off by default so the server stays light and retrieval
degrades cleanly to FTS.
