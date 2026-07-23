"""StateGraph wiring + compile.

Flow:
    START -> router -> retrieval
    retrieval -> table        (query_type numeric | hybrid)
              -> synthesis     (narrative)
    table    -> synthesis
    synthesis -> verify
    verify   -> synthesis      (failed, one repair pass)
             -> END            (verified | unverified | repaired-and-still-failed)

Nodes are DI closures built by make_*_node — the compiled graph never imports
an LLM SDK; providers/sessionmaker/encoder are injected here.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.retrieval import make_retrieval_node
from app.agents.router import make_router_node
from app.agents.state import AgentState, NodeFn, NodeUpdate
from app.agents.synthesis import make_synthesis_node
from app.agents.table import make_table_node
from app.agents.verifier import make_verifier_node
from app.llm.base import LLMProvider
from app.observability.tracing import node_span, record_node_metrics
from app.retrieval.colpali import ColPaliEncoder
from app.schemas.query import NodeTrace

# Named hops streamed to the client, in order.
HOP_EVENTS = ("router", "retrieval", "table", "synthesis", "verify")


def _traced(name: str, fn: NodeFn) -> NodeFn:
    """Wrap a node so each hop opens a span and records its NodeTrace metrics
    (latency/tokens/cost) — a no-op when Langfuse tracing is disabled."""

    async def wrapped(state: AgentState) -> NodeUpdate:
        with node_span(name) as span:
            update = await fn(state)
            traces = update.get("trace")
            if span is not None and isinstance(traces, list):
                for tr in traces:
                    if isinstance(tr, NodeTrace):
                        record_node_metrics(span, tr)
            return update

    return wrapped


def _route_after_retrieval(state: AgentState) -> str:
    return "table" if state.get("query_type") in ("numeric", "hybrid") else "synthesis"


def _route_after_verify(state: AgentState) -> str:
    verification = state.get("verification")
    if (
        verification is not None
        and verification.status == "failed"
        and state.get("final_answer") is None
    ):
        return "synthesis"
    return END


def build_graph(
    provider: LLMProvider | None,
    sessionmaker: async_sessionmaker[AsyncSession],
    encoder: ColPaliEncoder | None = None,
) -> Any:
    """Compile the agent graph with dependencies injected into each node."""
    # LangGraph's add_node overloads don't type-check against dynamically built
    # closure nodes under mypy --strict; the runtime contract (AgentState in,
    # partial-update dict out) is enforced by AgentState + NodeFn instead.
    builder: Any = StateGraph(AgentState)
    builder.add_node("router", _traced("router", make_router_node(provider)))
    builder.add_node("retrieval", _traced("retrieval", make_retrieval_node(sessionmaker, encoder)))
    builder.add_node("table", _traced("table", make_table_node(sessionmaker, provider)))
    builder.add_node("synthesis", _traced("synthesis", make_synthesis_node(sessionmaker, provider)))
    builder.add_node("verify", _traced("verify", make_verifier_node(sessionmaker)))

    builder.add_edge(START, "router")
    builder.add_edge("router", "retrieval")
    builder.add_conditional_edges(
        "retrieval", _route_after_retrieval, {"table": "table", "synthesis": "synthesis"}
    )
    builder.add_edge("table", "synthesis")
    builder.add_edge("synthesis", "verify")
    builder.add_conditional_edges(
        "verify", _route_after_verify, {"synthesis": "synthesis", END: END}
    )
    return builder.compile()
