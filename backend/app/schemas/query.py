"""Query API contracts + the component models threaded through AgentState.

These models are the single source of truth for candidates, table answers,
verification results and per-node traces; `app/agents/state.py` reuses them.
"""

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.citation import Citation

QueryType = Literal["numeric", "narrative", "hybrid"]
RetrievalPath = Literal["visual", "bm25", "hybrid"]
VerificationStatus = Literal["verified", "unverified", "failed"]

# Named SSE events emitted by POST /query, in hop order.
SSEEvent = Literal["router", "retrieval", "table", "synthesis", "verify", "answer", "error"]


class QueryFilters(BaseModel):
    ticker: str | None = None
    form_type: str | None = None
    filing_id: uuid.UUID | None = None
    fiscal_period: str | None = None


class QueryRequest(BaseModel):
    query: str = Field(min_length=3, max_length=2000)
    filters: QueryFilters = Field(default_factory=QueryFilters)
    top_k: int = Field(default=8, ge=1, le=25)


class Candidate(BaseModel):
    """A retrieved page candidate (MaxSim / BM25 / fused)."""

    page_id: uuid.UUID
    filing_id: uuid.UUID
    page_no: int
    score: float
    source_snippet: str = ""


class TableAnswer(BaseModel):
    """A numeric answer extracted from a specific table cell."""

    value: str
    unit: str | None = None
    source_cell: str  # human-readable locator, e.g. "row 'Total net sales' x col '2024'"
    row: int
    col: int
    table_id: uuid.UUID
    page_id: uuid.UUID
    confidence: float = 0.0


class VerificationCheck(BaseModel):
    claim: str
    status: Literal["passed", "failed", "unsupported"]
    expected: str | None = None
    found: str | None = None
    citation: Citation | None = None


class VerificationResult(BaseModel):
    status: VerificationStatus
    checks: list[VerificationCheck] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class NodeTrace(BaseModel):
    """Per-agent-hop accounting; rolled up into QueryLog."""

    name: str
    latency_ms: int
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


class CostSummary(BaseModel):
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    verification: VerificationResult
    query_type: QueryType
    cost: CostSummary
    trace: list[NodeTrace]
