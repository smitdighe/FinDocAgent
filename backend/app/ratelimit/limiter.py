"""In-process sliding-window rate limiter.

Single-instance deployment (one Render web service), so in-memory state is
correct; swap the backing store for Redis if this ever scales horizontally.
Spec format: "<count>/<second|minute|hour>", e.g. "20/minute".
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from collections import deque

from fastapi import HTTPException, Request

_RATE_RE = re.compile(r"^\s*(\d+)\s*/\s*(second|minute|hour)\s*$", re.IGNORECASE)
_UNIT_SECONDS = {"second": 1.0, "minute": 60.0, "hour": 3600.0}
_PRUNE_THRESHOLD = 10_000


def parse_rate(spec: str) -> tuple[int, float]:
    """"20/minute" -> (20, 60.0)."""
    match = _RATE_RE.match(spec)
    if match is None:
        raise ValueError(f"invalid rate spec: {spec!r} (expected e.g. '20/minute')")
    return int(match.group(1)), _UNIT_SECONDS[match.group(2).lower()]


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, key: str) -> tuple[bool, float]:
        """Returns (allowed, retry_after_seconds)."""
        async with self._lock:
            now = time.monotonic()
            hits = self._hits.setdefault(key, deque())
            cutoff = now - self._window
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self._limit:
                return False, max(hits[0] + self._window - now, 0.0)
            hits.append(now)
            if len(self._hits) > _PRUNE_THRESHOLD:
                self._prune(cutoff)
            return True, 0.0

    def _prune(self, cutoff: float) -> None:
        stale = [k for k, dq in self._hits.items() if not dq or dq[-1] <= cutoff]
        for k in stale:
            del self._hits[k]


class RateLimitDependency:
    """FastAPI dependency: 429 problem+json (with Retry-After) on excess."""

    def __init__(self, limiter: SlidingWindowLimiter, scope: str) -> None:
        self._limiter = limiter
        self._scope = scope

    async def __call__(self, request: Request) -> None:
        client_host = request.client.host if request.client else "unknown"
        allowed, retry_after = await self._limiter.acquire(f"{self._scope}:{client_host}")
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="rate limit exceeded",
                headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
            )
