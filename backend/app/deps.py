"""Dependency injection: settings, db session, LLM provider, graph, limiter."""

import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_sessionmaker
from app.llm.base import LLMProvider
from app.llm.factory import build_provider
from app.ratelimit.limiter import RateLimitDependency, SlidingWindowLimiter, parse_rate
from app.retrieval.colpali import ColPaliEncoder

logger = logging.getLogger(__name__)


def get_app_settings() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_app_settings)]


async def get_db_session(settings: SettingsDep) -> AsyncIterator[AsyncSession]:
    sessionmaker = get_sessionmaker(settings)
    async with sessionmaker() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_db_session)]

_provider: LLMProvider | None = None
_provider_built = False


def get_optional_provider(settings: Settings) -> LLMProvider | None:
    """Build the configured provider, or None when it can't be constructed
    (e.g. no API key). The pipeline degrades to deterministic synthesis rather
    than 500-ing, so /query works without an LLM key."""
    global _provider, _provider_built
    if not _provider_built:
        try:
            _provider = build_provider(settings)
        except Exception as exc:  # missing key / bad config
            logger.warning("LLM provider unavailable, using deterministic fallback: %s", exc)
            _provider = None
        _provider_built = True
    return _provider


_encoder: ColPaliEncoder | None = None
_encoder_built = False


def get_optional_encoder(settings: Settings) -> ColPaliEncoder | None:
    """The query-embedding encoder, only when QUERY_EMBEDDING is enabled.
    Model load is lazy (on first embed) inside ColPaliEncoder."""
    global _encoder, _encoder_built
    if not _encoder_built:
        if settings.query_embedding:
            _encoder = ColPaliEncoder(
                settings.colpali_model,
                device=settings.colpali_device,
                dtype=settings.colpali_dtype,
            )
        _encoder_built = True
    return _encoder


_graph: Any = None


def get_graph(settings: SettingsDep) -> Any:
    """Process-wide compiled agent graph."""
    global _graph
    if _graph is None:
        from app.agents.graph import build_graph

        _graph = build_graph(
            get_optional_provider(settings),
            get_sessionmaker(settings),
            get_optional_encoder(settings),
        )
    return _graph


GraphDep = Annotated[Any, Depends(get_graph)]

_query_limit: RateLimitDependency | None = None


async def query_rate_limit(request: Request, settings: SettingsDep) -> None:
    """Shared limiter for /query and /query/sync."""
    global _query_limit
    if _query_limit is None:
        limit, window = parse_rate(settings.rate_limit_query)
        _query_limit = RateLimitDependency(SlidingWindowLimiter(limit, window), scope="query")
    await _query_limit(request)
