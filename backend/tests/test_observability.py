"""Cost accounting, query-log rollup, and stats aggregation."""

from __future__ import annotations

import uuid

from app.llm.base import TokenPrice, Usage
from app.observability.cost import usd_for_usage
from app.observability.query_log import build_query_log
from app.observability.tracing import init_tracing, node_span, record_node_metrics
from app.schemas.citation import Citation
from app.schemas.query import (
    CostSummary,
    NodeTrace,
    QueryRequest,
    QueryResponse,
    VerificationResult,
)
from tests.conftest import requires_integration


class _Provider:
    name = "groq"
    model = "openai/gpt-oss-120b"
    price = TokenPrice(0.15, 0.60)


def test_usd_for_usage() -> None:
    # 1000 in, 500 out at $0.59 / $0.79 per Mtok
    cost = usd_for_usage(Usage(1000, 500), TokenPrice(0.59, 0.79))
    assert cost == round((1000 * 0.59 + 500 * 0.79) / 1_000_000, 8)
    assert usd_for_usage(Usage(0, 0), TokenPrice(1.0, 1.0)) == 0.0


def _response() -> QueryResponse:
    return QueryResponse(
        answer="416,161 [AAPL 10-K p.44].",
        citations=[Citation(filing_id=uuid.uuid4(), page_no=44)],
        verification=VerificationResult(status="verified"),
        query_type="numeric",
        cost=CostSummary(tokens_in=1200, tokens_out=80, cost_usd=0.00077, latency_ms=42),
        trace=[
            NodeTrace(name="router", latency_ms=1),
            NodeTrace(name="synthesis", latency_ms=20, tokens_in=1200, tokens_out=80,
                      cost_usd=0.00077),
        ],
    )


def test_build_query_log_rollup() -> None:
    req = QueryRequest(query="What was total net sales?")
    log = build_query_log(req, _response(), _Provider())
    assert log.query == "What was total net sales?"
    assert log.verification_status == "verified"
    assert log.query_type == "numeric"
    assert log.cost_usd == 0.00077
    assert log.latency_ms == 42
    assert log.provider == "groq"
    assert log.model == "openai/gpt-oss-120b"
    # full per-agent trace is persisted
    assert [t["name"] for t in log.trace] == ["router", "synthesis"]
    assert log.trace[1]["tokens_in"] == 1200


def test_build_query_log_without_provider() -> None:
    log = build_query_log(QueryRequest(query="hello world"), _response(), None)
    assert log.provider == "none"
    assert log.model is None


def test_tracing_disabled_is_noop() -> None:
    # No Langfuse creds -> spans are no-ops that never raise.
    from app.config import Settings

    init_tracing(Settings(langfuse_public_key="", langfuse_secret_key=""))
    with node_span("router") as span:
        assert span is None
        record_node_metrics(span, NodeTrace(name="router", latency_ms=1))


@requires_integration
async def test_query_log_persisted_and_stats(monkeypatch: object) -> None:
    """Phase 5 DoD: a query persists a per-agent trace + cost rollup to
    QueryLog, and GET /stats surfaces it. Needs the ingested corpus."""
    from app.agents.graph import build_graph
    from app.agents.run import run_query_sync
    from app.config import get_settings
    from app.db.session import get_sessionmaker
    from app.observability.query_log import query_stats

    settings = get_settings()
    sm = get_sessionmaker(settings)
    graph = build_graph(provider=None, sessionmaker=sm, encoder=None)

    async with sm() as session:
        before = (await query_stats(session))["n_queries"]

    req = QueryRequest(query="What was Apple's total net sales in fiscal 2025?")
    resp = await run_query_sync(graph, req, sessionmaker=sm, provider=None)
    assert resp.trace  # every hop traced

    async with sm() as session:
        stats = await query_stats(session)
    assert stats["n_queries"] == before + 1
    latest = stats["recent"][0]
    assert latest["query"].startswith("What was Apple")
    # per-agent trace persisted with latency for every hop
    assert {t["name"] for t in latest["trace"]} >= {"router", "retrieval", "synthesis", "verify"}
    assert all("latency_ms" in t for t in latest["trace"])
    assert latest["latency_ms"] is not None
