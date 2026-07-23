<div align="center">

<pre>
███████╗ ██╗ ███╗   ██╗ ██████╗   ██████╗   ██████╗  █████╗   ██████╗  ███████╗ ███╗   ██╗ ████████╗
██╔════╝ ██║ ████╗  ██║ ██╔══██╗ ██╔═══██╗ ██╔════╝ ██╔══██╗ ██╔════╝  ██╔════╝ ████╗  ██║ ╚══██╔══╝
█████╗   ██║ ██╔██╗ ██║ ██║  ██║ ██║   ██║ ██║      ███████║ ██║  ███╗ █████╗   ██╔██╗ ██║    ██║   
██╔══╝   ██║ ██║╚██╗██║ ██║  ██║ ██║   ██║ ██║      ██╔══██║ ██║   ██║ ██╔══╝   ██║╚██╗██║    ██║   
██║      ██║ ██║ ╚████║ ██████╔╝ ╚██████╔╝ ╚██████╗ ██║  ██║ ╚██████╔╝ ███████╗ ██║ ╚████║    ██║   
╚═╝      ╚═╝ ╚═╝  ╚═══╝ ╚═════╝   ╚═════╝   ╚═════╝ ╚═╝  ╚═╝  ╚═════╝  ╚══════╝ ╚═╝  ╚═══╝    ╚═╝   
</pre>

### It won't hand you a number it can't trace back to the filing.

</div>

> 🌐 **Live Demo:** https://fin-doc-agent.vercel.app

<div align="center">

**FinDocAgent** is a multi-agent RAG system over SEC filings (10-K/10-Q) on LangGraph. It routes each question, retrieves at the page level (visual MaxSim + lexical BM25), reads the *actual table cells*, and re-checks every number against its source before answering — if a figure can't be traced to a cited cell, it refuses to emit it. Naive RAG chunks prose, but SEC financials are dense HTML tables where meaning lives in the row/column grid: chunk them and you shred it. FinDocAgent is built around that failure mode.

</div>

---

## 🔍 How It Works

```
question → Router      (classify: numeric | narrative | hybrid)
         → Retrieval   (VectorChord MaxSim over page images  ⊕  Postgres BM25 → RRF)
              ├─ numeric | hybrid → Table QA   (read exact cells from stored source-HTML grids)
              └─ narrative        → Synthesis
         → Table QA    → Synthesis
         → Synthesis   (LLM via provider abstraction — drafts a cited answer)
         → Verify      (re-extract every numeric claim from source cells; fail closed)
              ├─ failed  → Synthesis   (ONE repair pass, then give up)
              └─ passed  → answer      (streamed live via SSE)
```

The graph is a real LangGraph `StateGraph`, not a linear script — routing after retrieval and the verify→synthesis repair edge are conditional. Every node is a dependency-injected closure (`make_*_node`); the compiled graph never imports an LLM SDK, so providers, the DB sessionmaker, and the optional encoder are all injected at build time. Each hop emits a validated Pydantic `NodeTrace` (latency, tokens, cost) and is streamed to the client as a named SSE event.

---

## ✨ Features

<table>
  <tr>
    <td align="center" width="220">
      <h3>⚖️</h3>
      <b>Fail-Closed Verifier</b><br/>
      <sub>Re-extracts every cited number from the source cells and blocks any claim it can't trace — never emits an unverified figure</sub><br/>
    </td>
    <td align="center" width="220">
      <h3>📊</h3>
      <b>Table-Aware Retrieval</b><br/>
      <sub>Parses source-HTML <code>&lt;table&gt;</code> elements into span-expanded cell grids — exact cell values, not shredded text chunks</sub><br/>
    </td>
    <td align="center" width="220">
      <h3>👁️</h3>
      <b>Visual + Lexical Hybrid</b><br/>
      <sub>ColQwen2 late-interaction MaxSim over page images, fused with Postgres BM25 via reciprocal rank fusion</sub><br/>
    </td>
  </tr>
  <tr>
    <td align="center" width="220">
      <h3>📄</h3>
      <b>Page-Level Citations</b><br/>
      <sub>EDGAR HTML has no native pages — we manufacture stable pagination (HTML → PDF → page images) so every citation points at a real rendered page</sub><br/>
    </td>
    <td align="center" width="220">
      <h3>📡</h3>
      <b>Live Agent Trace</b><br/>
      <sub>SSE-streamed graph execution — watch router → retrieval → table → synthesis → verify fire in real time</sub><br/>
    </td>
    <td align="center" width="220">
      <h3>🔁</h3>
      <b>Provider-Swappable LLM</b><br/>
      <sub>Groq / vLLM / OpenAI behind one abstraction — flip <code>LLM_PROVIDER</code> with zero edits under <code>app/agents/</code></sub><br/>
    </td>
  </tr>
</table>

---

## ⚖️ The Differentiator — Fail-Closed Verification

Most financial-QA demos stop at "the LLM cited a page." That's not verification — the model can cite a real page and still state a wrong number. FinDocAgent's verifier node treats **every numeric claim in the draft as guilty until traced.**

For each number in the drafted answer, the verifier:

1. **Re-extracts the authoritative value from the cited source** — table cells read back from the database by `(table_id, row, col)` (never trusting the draft), plus numbers present in the retrieved page text.
2. **Compares with unit/scale normalization and a small tolerance** (`REL_TOLERANCE = 0.02`) — exact when the printed digits match, scale-aware for "millions/billions" restatements, sign-aware for parenthesized negatives.
3. **Fails closed.** Any claim that can't be traced, or mismatches beyond tolerance, sets `verification.status = "failed"`. A failure triggers **one** repair round-trip back to synthesis (`MAX_REPAIRS = 1`); if it still fails, the answer is replaced with a *cannot-verify* message — the number is never returned.

### A blocked claim, concretely

> **Question:** "What was Apple's total net sales in fiscal 2025?"
> **Source cell** (AAPL 10-K, p.44, `Total net sales`): **416,161** (millions)

A model that confuses fiscal years drafts:

> *"Apple's total net sales were **$391,035 million** [AAPL 10-K p.44]."*

`$391,035M` is a real figure — it's Apple's **FY2024** total net sales. The verifier re-reads the cited FY2025 cell (`416,161`), computes the relative gap — `|391,035 − 416,161| / 416,161 ≈ 6.0%`, well beyond the 2% tolerance — and marks the claim `unsupported`. One repair pass fires; if synthesis can't ground it, the pipeline returns:

> "I can't return a verified answer: one or more figures in the drafted response could not be traced to a cited source in the filings."

The correct draft (`$416,161 million`) matches the cell on printed digits and passes as `verified`. This is why `faithfulness` is a hard `1.0` in the eval below — a blocked answer scores **0**, so the only way to score is to be right.

> The comparison core (`verify_numbers`) is a pure function — the planted-wrong-number regression test needs neither a DB nor an LLM.

---

## 🛠️ Tech Stack

### Backend

| Layer | Technology | Purpose |
|:------|:-----------|:--------|
| 🗄️ API | FastAPI (async) + Uvicorn | SSE-streamed multi-agent API |
| 🕸️ Orchestration | LangGraph `StateGraph` | Router → Retrieval → Table → Synthesis → Verify state machine |
| 🧮 Vector store | Postgres 17 + VectorChord (`vchordrq`) | True late-interaction MaxSim over `vector(128)[]` columns |
| 🔤 Lexical | Postgres FTS (`tsvector`, BM25-style) | Fused with MaxSim via reciprocal rank fusion |
| 👁️ Embeddings | ColPali / ColQwen2 (`colpali-engine`) | 128-dim multi-vectors; batch-embedded offline |
| 🤖 LLM | Groq `openai/gpt-oss-120b` (default) · vLLM · OpenAI | Provider-swappable synthesis + routing |
| 📥 Ingestion | httpx · Playwright/Chromium · pdfplumber · pypdfium2 · lxml | EDGAR fetch → print PDF → page images → cell grids |
| 🧱 ORM / migrations | SQLAlchemy 2 (async) + Alembic + asyncpg | Schema + `vchordrq` MaxSim index |
| ✅ Validation | Pydantic v2 + pydantic-settings | Schema at every node boundary; env-driven config |
| 📈 Observability | Custom `QueryLog` store + Langfuse (optional) | Per-hop trace, cost, latency; `GET /stats` rollup |
| 🐍 Runtime | Python 3.12 via [uv](https://docs.astral.sh/uv/) | Pinned, reproducible env |

### Frontend

| Layer | Technology | Purpose |
|:------|:-----------|:--------|
| ⚛️ Framework | React 19 + Vite 7 + TypeScript | Core UI + bundler |
| 🎨 Styling | Tailwind CSS v4 | Agent-trace, citation viewer, eval dashboard |
| 🧭 Routing | react-router-dom 7 | Query / viewer / eval views |
| 📡 Live data | SSE (`EventSource`) | Streamed per-hop agent trace |
| 🧪 Testing | Vitest + Testing Library | Component + hook tests |
| ☁️ Hosting | Vercel | Static SPA deploy |

---

## 📁 Project Structure

```bash
FinDocAgent/
├── backend/
│   ├── app/
│   │   ├── api/routes/          # query (SSE) · filings · eval · stats · health
│   │   ├── agents/
│   │   │   ├── graph.py         # compiled StateGraph (router→retrieval→table→synthesis→verify)
│   │   │   ├── router.py        # question classification
│   │   │   ├── retrieval.py     # MaxSim ⊕ BM25 → RRF, degrades to FTS
│   │   │   ├── table.py         # exact-cell table QA
│   │   │   ├── synthesis.py     # cited-answer draft via LLM provider
│   │   │   └── verifier.py      # fail-closed numeric verification
│   │   ├── retrieval/           # colpali · bm25 · maxsim · hybrid · store
│   │   ├── tables/              # source-HTML → cell grids, table QA
│   │   ├── llm/                 # base Protocol · factory · groq/vllm/openai adapters
│   │   ├── eval/                # harness · metrics · gold/gold_v1.jsonl
│   │   ├── observability/       # tracing · cost · query_log
│   │   ├── ingestion/           # edgar_client · fetch · render · pipeline · cli
│   │   ├── db/                  # models · session · migrations (alembic)
│   │   └── config.py            # env-driven settings (no secrets in code)
│   ├── scripts/embed_batch.py   # offline page embedding (GPU optional)
│   ├── Dockerfile               # CPU image; migrations run on start
│   ├── .env.example
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── features/
│   │   │   ├── query/           # QueryInput · AgentTrace · AnswerPanel · VerificationBadge
│   │   │   ├── viewer/          # FilingViewer · HighlightOverlay · PageThumbnails
│   │   │   ├── selector/        # TickerFilingSelector
│   │   │   └── eval/            # EvalDashboard · ScoreCards · RegressionChart
│   │   ├── api/                 # client · sse · query · filings · eval
│   │   └── lib/env.ts           # VITE_API_BASE_URL
│   ├── vercel.json
│   └── vite.config.ts
├── render.yaml                  # Render blueprint (web + vchord private service)
└── README.md
```

---

## 📊 Eval Scores

Scores from the versioned gold set (`app/eval/gold/gold_v1.jsonl`) — **33 items: 21 human-verified (20 numeric + 1 narrative) + 12 unverified drafts.** Unverified rows are excluded from scoring until a human confirms them. Expected answers are read from the ingested filings' source cells — never fabricated.

**Measured baseline** — FTS-only retrieval, deterministic synthesis, `QUERY_EMBEDDING=false`, over the 21 verified items:

| Metric | Score | What it measures |
|:-------|:-----:|:-----------------|
| `faithfulness` | **1.00** | The verifier's grounding verdict — a blocked/failed answer scores **0** |
| `answer_accuracy` | **≈ 0.71** | Expected figure present within 2% tolerance (numeric) / content-word recall (narrative) |
| `context_precision` | **≈ 0.49** | Reciprocal rank of the gold source page among retrieved candidates |

**How it's measured.** `POST /eval/run` runs the full pipeline over the verified gold rows and writes an `EvalRun` (git SHA + gold version + scores + cost/latency rollup), returning per-metric deltas vs. the previous run on the same gold version. Metrics are the **RAGAS triad implemented deterministically** — anchored to ground truth rather than an LLM judge — so a run-to-run delta reflects a *pipeline* change, not judge noise, and the harness runs in CI with no paid judge and no key.

> ⚠️ The visual/MaxSim path (`QUERY_EMBEDDING=true`) and an LLM synthesizer are wired and tested but their accuracy lift over this FTS baseline is **not yet measured** on the gold set — measuring that commit-to-commit is exactly what the regression harness exists for. The numbers above are the honest, reproducible floor, not a peak.

---

## 💰 Cost & Latency

From actual per-hop tracing: every agent hop emits a `NodeTrace` (latency, tokens in/out, cost USD); the full per-query rollup is persisted to `QueryLog` on every `/query` and `/query/sync`, and `GET /stats` reads back aggregate cost/latency. Costs are computed from each provider's price table in `app/observability/cost.py`.

| Path | Cost / query | Latency | Notes |
|:-----|:------------:|:-------:|:------|
| FTS + deterministic synthesis (no LLM key) | **$0** | **~30–45 ms** e2e | Default / regression baseline |
| Groq synthesis (`openai/gpt-oss-120b`) | **≈ $0.00028** | + one LLM round-trip | ~1.4k input + ~120 output tokens @ **$0.15 / $0.60** per Mtok |

---

## ⚙️ Getting Started

### Prerequisites

- **Python 3.12** (managed via [uv](https://docs.astral.sh/uv/))
- **Node.js 22.x** (frontend)
- **Docker** (local Postgres 17 + VectorChord)
- A **Groq API key** ([console.groq.com](https://console.groq.com)) — optional; without it the pipeline runs the free deterministic-synthesis path
- An **EDGAR User-Agent** string with contact info (SEC requires it, or it 403s)

### 1. Clone

```bash
git clone https://github.com/smitdighe/FinDocAgent.git
cd FinDocAgent
```

### 2. Backend

```bash
cd backend
cp .env.example .env            # set EDGAR_USER_AGENT + GROQ_API_KEY

docker compose up -d            # Postgres 17 + VectorChord 1.1.1 on localhost:5433
uv sync                         # creates .venv with pinned Python 3.12
uv run playwright install chromium
uv run alembic upgrade head     # schema + vchordrq maxsim index

# ingest a few filings (fetch → render → extract; no embedding yet)
uv run python -m app.ingestion.cli ingest --tickers AAPL,MSFT --forms 10-K,10-Q --limit-per-form 2

# (optional) batch-embed rendered pages for the visual/MaxSim path — GPU box for real corpora
uv run python scripts/embed_batch.py --batch-size 4

# serve
uv run uvicorn app.main:app --reload
```

> API at `http://localhost:8000` — Swagger docs at `http://localhost:8000/docs`

Key env vars (`backend/.env`):

```env
DATABASE_URL=postgresql+asyncpg://findoc:findoc@localhost:5433/findoc
LLM_PROVIDER=groq
GROQ_API_KEY=your_groq_key
GROQ_MODEL=openai/gpt-oss-120b
EDGAR_USER_AGENT=FinDocAgent/0.1 (you@example.com)
QUERY_EMBEDDING=false           # true loads ColQwen2 in the API to embed queries
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
IMAGE_PUBLIC_BASE_URL=          # empty = serve page JPEGs from local disk (dev)
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

> Frontend at `http://localhost:5173`. In dev, leave `VITE_API_BASE_URL` empty — Vite proxies `/query`, `/filings`, `/eval`, `/stats` to the backend. Both servers must run simultaneously.

---

## 🔌 API

| Method | Path | Purpose |
|:-------|:-----|:--------|
| `POST` | `/query` | **SSE stream** — one named event per agent hop (`router`, `retrieval`, `table`, `synthesis`, `verify`) then a final `answer` event |
| `POST` | `/query/sync` | Same result, non-streamed (used by the eval harness) |
| `GET`  | `/filings` | Ingested filings + page counts |
| `GET`  | `/filings/{id}/pages/{n}` | Page text + tables + image URL (citation-viewer contract) |
| `GET`  | `/filings/{id}/pages/{n}/image` | The rendered page JPEG — streamed from local disk, or 307-redirected to object storage when `IMAGE_PUBLIC_BASE_URL` is set |
| `POST` | `/eval/run` | Run the eval harness over the verified gold rows → `EvalRun` |
| `GET`  | `/eval/runs` · `/eval/runs/{id}` | Eval run history + detail (regression tracking) |
| `GET`  | `/stats` | Aggregate cost/latency + recent per-query traces |
| `GET`  | `/health` · `/ready` | Liveness / DB + `vchord` extension readiness |

Errors are RFC 7807 `application/problem+json`. `/query*` is rate limited (`RATE_LIMIT_QUERY`, default `20/minute`).

---

## 🔧 What Broke & How I Fixed It

Real issues from this build:

- **Docker Desktop flakiness (local DB).** VectorChord isn't in managed Postgres, so the stack runs the official image locally — and Docker Desktop dropped connections intermittently. Pinned `tensorchord/vchord-postgres:pg17-v1.1.1`, put the DB on non-default port `5433` to dodge port clashes, made `docker compose up -d` idempotent, and gated readiness on `GET /ready` actually checking the `vchord` extension is installed rather than assuming.
- **ColQwen2 CPU embedding (no local GPU).** Embedding page images on CPU is slow enough to be unusable in a request. Fix: pulled embedding out of the request path entirely — `scripts/embed_batch.py` embeds pages **offline** (GPU optional), the API only ever embeds *queries* and only when `QUERY_EMBEDDING=true`; with it off, retrieval degrades cleanly to FTS so a CPU-only box still serves against precomputed vectors.
- **Groq model deprecation.** `llama-3.3-70b-versatile` was deprecated by Groq. Switched the default to `openai/gpt-oss-120b` across config, `.env(.example)`, the Render blueprint, and the cost price table, and verified provider wiring end-to-end.
- **Table bboxes stored as `NULL` + caption misdetection.** On real EDGAR filings, bounding boxes were persisting as SQL `NULL` and caption detection was misfiring. Fixed the bbox NULL storage path and caption detection against real filings (commit `f26bf8a`).
- **Vite proxy 404s via `localhost`.** Uvicorn binds IPv4, but `localhost` resolved to `::1` first (Docker's wslrelay answered there and 404'd). Fix: proxy targets `127.0.0.1` explicitly — IPv4 is unambiguous.
- **CORS blocked the deployed frontend.** `cors_origins` defaulted to localhost only and was never set for prod, so the Vercel frontend would have been rejected. Added a `CORS_ORIGINS` env var (comma-separated, JSON-decoding disabled so a plain list works in the dashboard) wired into config and the Render blueprint.
- **Page images vanished in prod (ephemeral disk).** Rendered page JPEGs are written to `STORAGE_DIR` at ingest, but Render's free-tier disk is ephemeral and ingestion runs locally — so the deployed viewer 404'd every page ("image unavailable"). Fix: uploaded the images to Supabase Storage (S3-compatible, public bucket) via `scripts/upload_images.py`, and made `/filings/{id}/pages/{n}/image` 307-redirect to `IMAGE_PUBLIC_BASE_URL` (key derived from the accession, not the local path) when set — falling back to a local `FileResponse` in dev. Object storage is decoupled from the store: R2, S3, or Supabase all work.
- **EDGAR 403s.** SEC fair-access requires a descriptive `User-Agent` with contact info. Made `EDGAR_USER_AGENT` required and throttled the client to ≤5 req/s.

---

## ⚠️ Known Limitations

- **Visual/MaxSim lift unmeasured.** The path is wired and tested but off by default; its accuracy gain over the FTS baseline isn't yet recorded on the gold set.
- **Verifier only checks numbers.** Narrative answers with no numeric claims pass through labeled `unverified` — there's no factual grounding check on prose yet.
- **Small gold set.** 21 verified items — scores are directional, not a large benchmark.
- **No auth, no multi-turn.** Single question in, single verified answer out.
- **CPU embedding is slow.** Batch offline; don't embed at request time.

---

## 🔮 Future Improvements

- **Measure the lift:** record MaxSim + LLM synthesis vs. the FTS baseline commit-to-commit via the regression harness.
- **Narrative faithfulness:** layer an LLM-judge refinement (via the provider abstraction) for non-numeric claims.
- **Grow the gold set:** human-verify the 12 draft rows and expand coverage beyond AAPL/MSFT.
- **Multi-turn:** follow-up questions scoped to a single filing.
- **Auth + per-user rate limits.**
