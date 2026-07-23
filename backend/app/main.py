"""FastAPI app assembly: lifespan, middleware, routers, error handlers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.routes import eval as eval_routes
from app.api.routes import filings, health, query, stats
from app.config import get_settings
from app.db.session import dispose_engine, get_engine
from app.observability.middleware import RequestContextMiddleware
from app.observability.tracing import flush as flush_tracing
from app.observability.tracing import init_tracing


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    get_engine(settings)  # construct the pool early; connections open lazily
    init_tracing(settings)
    yield
    flush_tracing()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="FinDocAgent", version=__version__, lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(filings.router, prefix="/filings")
    app.include_router(query.router)
    app.include_router(eval_routes.router, prefix="/eval")
    app.include_router(stats.router)
    return app


app = create_app()
