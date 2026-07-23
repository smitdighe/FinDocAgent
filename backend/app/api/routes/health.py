"""Liveness and readiness."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app import __version__
from app.deps import SessionDep, SettingsDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(settings: SettingsDep) -> dict[str, str]:
    return {"status": "ok", "version": __version__, "env": settings.app_env}


@router.get("/ready")
async def ready(session: SessionDep) -> dict[str, str]:
    """Ready = database reachable AND the vchord extension installed."""
    try:
        vchord = await session.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vchord'")
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database unavailable: {exc}") from exc
    if not vchord:
        raise HTTPException(status_code=503, detail="vchord extension missing — run migrations")
    return {"status": "ready", "vchord": str(vchord)}
