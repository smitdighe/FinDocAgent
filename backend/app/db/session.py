"""Async engine + sessionmaker, with the pgvector asyncpg codec registered."""

from typing import Any

from pgvector.asyncpg import register_vector
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine(settings: Settings) -> AsyncEngine:
    """Process-wide engine. The pgvector codec is registered on every new
    connection so `vector` / `vector[]` params and results round-trip."""
    global _engine, _sessionmaker
    if _engine is None:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)

        @event.listens_for(engine.sync_engine, "connect")
        def _on_connect(dbapi_connection: Any, _record: Any) -> None:
            # AdaptedConnection.run_async bridges into asyncpg's loop. Skipped
            # when the `vector` type isn't installed (SKIP_VCHORD / plain
            # Postgres without the vchord/pgvector extension) — the FTS-only
            # path never round-trips vector params, so there's nothing to
            # register a codec for.
            async def _register_if_available(conn: Any) -> None:
                try:
                    await register_vector(conn)
                except ValueError:
                    pass

            dbapi_connection.run_async(_register_if_available)

        _engine = engine
        _sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    return _engine


def get_sessionmaker(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        get_engine(settings)
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None
