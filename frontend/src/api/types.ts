// Mirrors backend Pydantic schemas (app/schemas/*). Keep in sync with the
// backend — field names are verified against the live contract, not guessed.
// Source of truth: backend/app/schemas/{query,filing,citation,eval}.py

export type UUID = string;

export type QueryType = "numeric" | "narrative" | "hybrid";
export type RetrievalPath = "visual" | "bm25" | "hybrid";
export type VerificationStatus = "verified" | "unverified" | "failed";

// Named SSE events, in hop order. `answer` carries the full QueryResponse.
export type SSEEventName =
  | "router"
  | "retrieval"
  | "table"
  | "synthesis"
  | "verify"
  | "answer"
  | "error";

// ---- citation.py -----------------------------------------------------------
// bbox is PDF points, top-left origin: [x0, top, x1, bottom].
// Page box is US Letter = 612 x 792 pt (see PAGE_PT below).
export interface Citation {
  filing_id: UUID;
  page_no: number; // 1-based, rendered pagination
  section: string | null;
  bbox: [number, number, number, number] | null;
}

export const PAGE_PT = { width: 612, height: 792 } as const;

// ---- query.py --------------------------------------------------------------
export interface QueryFilters {
  ticker?: string | null;
  form_type?: string | null;
  filing_id?: UUID | null;
  fiscal_period?: string | null;
}

export interface QueryRequest {
  query: string;
  filters?: QueryFilters;
  top_k?: number;
}

export interface VerificationCheck {
  claim: string;
  status: "passed" | "failed" | "unsupported";
  expected: string | null;
  found: string | null;
  citation: Citation | null;
}

export interface VerificationResult {
  status: VerificationStatus;
  checks: VerificationCheck[];
  reasons: string[];
}

export interface NodeTrace {
  name: string;
  latency_ms: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
}

export interface CostSummary {
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  latency_ms: number;
}

export interface QueryResponse {
  answer: string;
  citations: Citation[];
  verification: VerificationResult;
  query_type: QueryType;
  cost: CostSummary;
  trace: NodeTrace[];
}

// ---- SSE hop payloads (backend app/agents/run.py::_hop_payload) -------------
export interface RouterHop {
  query_type: QueryType | null;
  retrieval_path: RetrievalPath | null;
}
export interface RetrievalHopCandidate {
  page_no: number;
  filing_id: string;
  score: number;
}
export interface RetrievalHop {
  count: number;
  candidates: RetrievalHopCandidate[];
}
export interface TableHopAnswer {
  value: string;
  unit: string | null;
  source_cell: string;
}
export interface TableHop {
  count: number;
  answers: TableHopAnswer[];
}
export interface SynthesisHop {
  draft_preview: string;
  citations: number;
}
export interface VerifyHop {
  status: VerificationStatus;
  checks: { claim: string; status: string; found: string | null }[];
  repairing: boolean;
}
export interface ErrorHop {
  detail: string;
}

// ---- filing.py -------------------------------------------------------------
export interface Filing {
  id: UUID;
  ticker: string;
  cik: string;
  company_name: string;
  form_type: string;
  accession_no: string;
  filing_date: string; // ISO date
  period_end: string | null;
  source_url: string;
  status: string;
  page_count: number | null;
  ingested_at: string; // ISO datetime
}

export interface FilingList {
  items: Filing[];
  total: number;
}

export interface ExtractedTable {
  id: UUID;
  table_index: number;
  caption: string;
  n_rows: number;
  n_cols: number;
  grid: (string | null)[][];
  bbox: number[] | null;
}

export interface PageDetail {
  filing_id: UUID;
  page_no: number;
  page_count: number;
  text: string;
  image_url: string; // relative: /filings/{id}/pages/{n}/image
  tables: ExtractedTable[];
}

// ---- eval.py ---------------------------------------------------------------
export interface EvalTriggerRequest {
  gold_version?: string;
  notes?: string;
}

export interface EvalRun {
  id: UUID;
  gold_version: string;
  pipeline_git_sha: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  scores: Record<string, number>;
  rollup: Record<string, unknown>;
}

export interface MetricDelta {
  metric: string;
  previous: number | null;
  current: number;
  delta: number | null;
}

export interface EvalRunDetail extends EvalRun {
  per_query: Record<string, unknown>[];
  regression_vs_previous: MetricDelta[];
}
