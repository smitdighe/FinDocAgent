"""Query endpoints.

POST /query        — SSE stream: named events per agent hop (router,
                     retrieval, table, synthesis, verify) then `answer`.
POST /query/sync   — same result non-streamed (eval harness path).

Both persist a per-query rollup to QueryLog (queryable via GET /stats).
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.responses import StreamingResponse

from app.agents.run import run_query_sync, stream_query
from app.db.session import get_sessionmaker
from app.deps import GraphDep, SettingsDep, get_optional_provider, query_rate_limit
from app.schemas.query import QueryRequest, QueryResponse

router = APIRouter(tags=["query"])

RateLimited = Annotated[None, Depends(query_rate_limit)]


@router.post("/query")
async def query_stream(
    request: QueryRequest, graph: GraphDep, settings: SettingsDep, _rl: RateLimited
) -> StreamingResponse:
    sessionmaker = get_sessionmaker(settings)
    provider = get_optional_provider(settings)
    return StreamingResponse(
        stream_query(graph, request, sessionmaker=sessionmaker, provider=provider),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/query/sync", response_model=QueryResponse)
async def query_sync(
    request: QueryRequest, graph: GraphDep, settings: SettingsDep, _rl: RateLimited
) -> QueryResponse:
    sessionmaker = get_sessionmaker(settings)
    provider = get_optional_provider(settings)
    return await run_query_sync(graph, request, sessionmaker=sessionmaker, provider=provider)
