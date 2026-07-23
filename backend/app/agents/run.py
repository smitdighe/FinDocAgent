"""Run the compiled agent graph: sync result + SSE hop streaming.

Keeps the API route thin — the route just serializes what these produce.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.state import AgentState
from app.llm.base import LLMProvider
from app.observability.query_log import record_query_log
from app.observability.tracing import flush, query_trace
from app.schemas.query import (
    CostSummary,
    NodeTrace,
    QueryRequest,
    QueryResponse,
    VerificationResult,
)


def _initial_state(request: QueryRequest) -> AgentState:
    return {
        "query": request.query,
        "filters": request.filters,
        "repair_count": 0,
        "trace": [],
        "errors": [],
    }


def _cost_summary(traces: list[NodeTrace]) -> CostSummary:
    return CostSummary(
        tokens_in=sum(t.tokens_in for t in traces),
        tokens_out=sum(t.tokens_out for t in traces),
        cost_usd=round(sum(t.cost_usd for t in traces), 8),
        latency_ms=sum(t.latency_ms for t in traces),
    )


def _final_response(state: AgentState) -> QueryResponse:
    traces = state.get("trace", [])
    verification = state.get("verification") or VerificationResult(status="unverified")
    answer = state.get("final_answer") or state.get("draft_answer") or ""
    return QueryResponse(
        answer=answer,
        citations=state.get("citations", []),
        verification=verification,
        query_type=state.get("query_type", "hybrid"),
        cost=_cost_summary(traces),
        trace=traces,
    )


async def run_query_sync(
    graph: Any,
    request: QueryRequest,
    *,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    provider: LLMProvider | None = None,
) -> QueryResponse:
    with query_trace(request.query):
        final_state: AgentState = await graph.ainvoke(_initial_state(request))
    response = _final_response(final_state)
    if sessionmaker is not None:
        await record_query_log(sessionmaker, request, response, provider)
    flush()
    return response


async def run_query_traced(graph: Any, request: QueryRequest) -> tuple[QueryResponse, AgentState]:
    """Same full-pipeline run as /query/sync, but also returns the final graph
    state (retrieved candidates, table answers) for the eval harness to score
    retrieval quality. The API path uses run_query_sync; this is internal."""
    final_state: AgentState = await graph.ainvoke(_initial_state(request))
    return _final_response(final_state), final_state


def _hop_payload(node: str, update: dict[str, Any]) -> dict[str, Any]:
    """Compact, JSON-safe payload for a single agent hop."""
    if node == "router":
        return {
            "query_type": update.get("query_type"),
            "retrieval_path": update.get("retrieval_path"),
        }
    if node == "retrieval":
        cands = update.get("candidates", [])
        return {
            "count": len(cands),
            "candidates": [
                {"page_no": c.page_no, "filing_id": str(c.filing_id), "score": round(c.score, 4)}
                for c in cands[:8]
            ],
        }
    if node == "table":
        answers = update.get("table_answers", [])
        return {
            "count": len(answers),
            "answers": [
                {"value": a.value, "unit": a.unit, "source_cell": a.source_cell}
                for a in answers[:5]
            ],
        }
    if node == "synthesis":
        draft = update.get("draft_answer", "") or ""
        return {"draft_preview": draft[:280], "citations": len(update.get("citations", []))}
    if node == "verify":
        verification = update.get("verification")
        if isinstance(verification, VerificationResult):
            return {
                "status": verification.status,
                "checks": [
                    {"claim": c.claim, "status": c.status, "found": c.found}
                    for c in verification.checks
                ],
                "repairing": update.get("final_answer") is None
                and verification.status == "failed",
            }
    return {}


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def stream_query(
    graph: Any,
    request: QueryRequest,
    *,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    provider: LLMProvider | None = None,
) -> AsyncIterator[str]:
    """Yield an SSE frame per agent hop, then a final `answer` frame.

    The accumulated state is rebuilt locally from the streamed updates so the
    final frame carries the full response without a second graph run. The
    query rollup is persisted to QueryLog after the answer frame.
    """
    state: AgentState = _initial_state(request)
    try:
        with query_trace(request.query):
            async for step in graph.astream(_initial_state(request), stream_mode="updates"):
                for node, update in step.items():
                    if not isinstance(update, dict):
                        continue
                    _merge(state, update)
                    yield _sse(node, _hop_payload(node, update))
    except Exception as exc:  # surface a terminal error frame, never hang the stream
        yield _sse("error", {"detail": str(exc)})
        return
    response = _final_response(state)
    yield _sse("answer", response.model_dump(mode="json"))
    if sessionmaker is not None:
        await record_query_log(sessionmaker, request, response, provider)
    flush()


def _merge(state: AgentState, update: dict[str, Any]) -> None:
    """Apply a node update to the local mirror of graph state (append reducers
    for trace/errors, replace otherwise)."""
    for key, value in update.items():
        if key in ("trace", "errors"):
            existing = cast("list[Any]", state.get(key) or [])
            state[key] = [*existing, *value]  # type: ignore[literal-required]
        else:
            state[key] = value  # type: ignore[literal-required]
