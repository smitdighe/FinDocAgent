"""Cost/latency observability: per-query rollups are queryable here."""

from fastapi import APIRouter

from app.deps import SessionDep
from app.observability.query_log import query_stats

router = APIRouter(tags=["observability"])


@router.get("/stats")
async def stats(session: SessionDep) -> dict[str, object]:
    """Aggregate cost + latency across logged queries, with recent per-query
    rollups (including the full per-agent trace)."""
    return await query_stats(session)
