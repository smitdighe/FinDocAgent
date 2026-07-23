"""Per-query rollup persistence (the custom trace store) + cost/latency stats.

Every /query and /query/sync call is recorded to QueryLog: the answer, the
verification status, the full per-agent trace (name/latency/tokens/cost), and
the query-level cost/latency/provider/model rollup. GET /stats reads it back.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import QueryLog
from app.llm.base import LLMProvider
from app.schemas.query import QueryRequest, QueryResponse

logger = logging.getLogger(__name__)


def build_query_log(
    request: QueryRequest, response: QueryResponse, provider: LLMProvider | None
) -> QueryLog:
    return QueryLog(
        query=request.query,
        answer=response.answer,
        query_type=response.query_type,
        verification_status=response.verification.status,
        trace=[t.model_dump() for t in response.trace],
        cost_usd=response.cost.cost_usd,
        latency_ms=response.cost.latency_ms,
        provider=provider.name if provider else "none",
        model=provider.model if provider else None,
    )


async def record_query_log(
    sessionmaker: async_sessionmaker[AsyncSession],
    request: QueryRequest,
    response: QueryResponse,
    provider: LLMProvider | None,
) -> None:
    """Persist a query rollup. Best-effort: logging must never fail a query."""
    try:
        async with sessionmaker() as session:
            session.add(build_query_log(request, response, provider))
            await session.commit()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("failed to persist QueryLog: %s", exc)


async def query_stats(session: AsyncSession, *, recent: int = 20) -> dict[str, object]:
    """Aggregate cost/latency across all logged queries, plus recent rows."""
    totals = (
        await session.execute(
            select(
                func.count(QueryLog.id),
                func.coalesce(func.sum(QueryLog.cost_usd), 0.0),
                func.coalesce(func.avg(QueryLog.cost_usd), 0.0),
                func.coalesce(func.avg(QueryLog.latency_ms), 0.0),
            )
        )
    ).one()
    n, cost_sum, cost_avg, latency_avg = totals

    by_provider_rows = (
        await session.execute(
            select(
                QueryLog.provider,
                func.count(QueryLog.id),
                func.coalesce(func.sum(QueryLog.cost_usd), 0.0),
            ).group_by(QueryLog.provider)
        )
    ).all()

    recent_rows = (
        (
            await session.execute(
                select(QueryLog).order_by(QueryLog.created_at.desc()).limit(recent)
            )
        )
        .scalars()
        .all()
    )

    return {
        "n_queries": int(n),
        "cost_usd_total": round(float(cost_sum), 8),
        "cost_usd_avg": round(float(cost_avg), 8),
        "latency_ms_avg": round(float(latency_avg), 1),
        "by_provider": [
            {"provider": p or "none", "n": int(c), "cost_usd": round(float(s), 8)}
            for p, c, s in by_provider_rows
        ],
        "recent": [
            {
                "id": str(r.id),
                "created_at": r.created_at.isoformat(),
                "query": r.query[:160],
                "query_type": r.query_type,
                "verification": r.verification_status,
                "cost_usd": r.cost_usd,
                "latency_ms": r.latency_ms,
                "provider": r.provider,
                "model": r.model,
                "trace": r.trace,
            }
            for r in recent_rows
        ],
    }
