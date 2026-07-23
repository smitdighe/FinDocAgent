"""Per-agent-hop tracing.

Two sinks, by the spec ("Langfuse or OTel spans + a custom store"):
- Always: the `QueryLog` custom store (see observability/query_log.py) records
  the full per-node trace + cost for every query — this is the source of truth
  and is queryable via GET /stats.
- Optional: Langfuse spans, emitted only when LANGFUSE_* creds are set. The
  integration is best-effort and fully wrapped in try/except so a Langfuse
  outage or API drift can never break the pipeline.

`node_span` wraps each agent hop; `record_node_metrics` attaches the hop's
latency/tokens/cost to the span. Both are safe no-ops when tracing is off.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.config import Settings
from app.schemas.query import NodeTrace

logger = logging.getLogger(__name__)


class _TracingState:
    enabled: bool = False
    client: Any = None


_state = _TracingState()


def init_tracing(settings: Settings) -> None:
    """Called once at startup. Enables Langfuse only when creds are present."""
    _state.enabled = False
    _state.client = None
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return
    try:
        from langfuse import Langfuse

        _state.client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        _state.enabled = True
        logger.info("Langfuse tracing enabled (%s)", settings.langfuse_host)
    except Exception as exc:  # never let observability break startup
        logger.warning("Langfuse init failed, tracing disabled: %s", exc)


@contextmanager
def query_trace(query: str) -> Iterator[Any]:
    """Root span for a whole query, parenting the per-hop spans."""
    if not _state.enabled or _state.client is None:
        yield None
        return
    try:
        with _state.client.start_as_current_observation(
            name="query", as_type="span", input={"query": query}
        ) as span:
            yield span
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("query_trace failed: %s", exc)
        yield None


@contextmanager
def node_span(name: str) -> Iterator[Any]:
    """Span for one agent hop. No-op when tracing is disabled."""
    if not _state.enabled or _state.client is None:
        yield None
        return
    try:
        with _state.client.start_as_current_observation(name=name, as_type="span") as span:
            yield span
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("node_span(%s) failed: %s", name, exc)
        yield None


def record_node_metrics(span: Any, trace: NodeTrace) -> None:
    """Attach a hop's latency/tokens/cost to its span."""
    if span is None:
        return
    try:
        span.update(
            metadata={
                "latency_ms": trace.latency_ms,
                "tokens_in": trace.tokens_in,
                "tokens_out": trace.tokens_out,
                "cost_usd": trace.cost_usd,
            },
            usage_details={"input": trace.tokens_in, "output": trace.tokens_out},
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("record_node_metrics failed: %s", exc)


def flush() -> None:
    if _state.enabled and _state.client is not None:
        try:
            _state.client.flush()
        except Exception:  # pragma: no cover - defensive
            pass
