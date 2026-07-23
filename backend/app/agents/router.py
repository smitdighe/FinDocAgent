"""Router node: classify the query and choose the retrieval path.

Heuristics run first — fast, free, deterministic. The injected provider is
consulted only when the heuristics are genuinely unsure (low confidence) AND
a provider is configured; otherwise the heuristic answer stands. This keeps
the node functional with no LLM at all.

Path mapping:
    numeric   -> "hybrid"  (BM25 nails exact line items; MaxSim finds tables)
    hybrid    -> "hybrid"
    narrative -> "visual"  (late interaction shines on prose + layout)
"""

from __future__ import annotations

import re
import time

from app.agents.state import AgentState, NodeFn, NodeUpdate
from app.llm.base import LLMProvider, Message, Usage
from app.observability.cost import usd_for_usage
from app.schemas.query import NodeTrace, QueryType, RetrievalPath

# Confidence below this asks the LLM to break the tie (when configured).
TIE_BREAK_THRESHOLD = 0.6

_NUMERIC_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\$|\busd\b",
        r"\b(million|billion|thousand)s?\b",
        r"\bhow (much|many)\b",
        r"\b(revenue|net sales|total sales|net income|gross margin|operating (income|expenses"
        r"|margin)|earnings per share|\beps\b|cash flow|free cash|cost of (sales|revenue)"
        r"|r&d|research and development|capital expenditures?|capex|dividends?|buybacks?"
        r"|shares? outstanding|total assets|total liabilities|stockholders.? equity"
        r"|deferred revenue|effective tax rate|interest expense)\b",
        r"\b(fy\s?20\d\d|fiscal (year )?20\d\d|q[1-4]\s?(20\d\d)?|quarter ended|year ended"
        r"|three months ended|six months ended|nine months ended)\b",
        r"\b(increase|decrease|grow(th)?|change) (in|of|from)\b",
        r"\b20\d\d\b",
    )
]

_NARRATIVE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\brisk factors?\b",
        r"\b(describe|explain|discuss|summariz|why|what are)\b",
        r"\b(strateg|outlook|competiti|litigation|regulat|management.s discussion"
        r"|going concern|supply chain|seasonalit|human capital|climate|cybersecurit)\w*\b",
    )
]

_PATH_FOR: dict[QueryType, RetrievalPath] = {
    "numeric": "hybrid",
    "hybrid": "hybrid",
    "narrative": "visual",
}


def classify_query(query: str) -> tuple[QueryType, float]:
    """Heuristic classification -> (query_type, confidence in [0, 1])."""
    numeric_hits = sum(1 for p in _NUMERIC_PATTERNS if p.search(query))
    narrative_hits = sum(1 for p in _NARRATIVE_PATTERNS if p.search(query))
    if numeric_hits and narrative_hits:
        return "hybrid", 0.7
    if numeric_hits >= 2:
        return "numeric", 0.9
    if numeric_hits == 1:
        return "numeric", 0.55
    if narrative_hits:
        return "narrative", 0.8
    # No signal either way: hybrid retrieval is the safe default.
    return "hybrid", 0.4


async def _llm_tie_break(
    provider: LLMProvider, query: str, fallback: QueryType
) -> tuple[QueryType, Usage]:
    messages: list[Message] = [
        {
            "role": "system",
            "content": (
                "You classify questions about SEC filings. Reply with exactly one word: "
                "'numeric' if the answer is a number/figure from financial statements, "
                "'narrative' if it is prose (risks, strategy, discussion), "
                "'hybrid' if it needs both."
            ),
        },
        {"role": "user", "content": query},
    ]
    try:
        completion = await provider.complete(messages, temperature=0.0, max_tokens=4)
    except Exception:  # provider trouble must never kill the pipeline
        return fallback, Usage()
    word = completion.text.strip().lower().strip(".\"'")
    if word in ("numeric", "narrative", "hybrid"):
        return word, completion.usage  # type: ignore[return-value]
    return fallback, completion.usage


def make_router_node(provider: LLMProvider | None) -> NodeFn:
    async def route_query(state: AgentState) -> NodeUpdate:
        started = time.perf_counter()
        query = state["query"]
        query_type, confidence = classify_query(query)
        usage = Usage()
        if confidence < TIE_BREAK_THRESHOLD and provider is not None:
            query_type, usage = await _llm_tie_break(provider, query, query_type)
        trace = NodeTrace(
            name="router",
            latency_ms=int((time.perf_counter() - started) * 1000),
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            cost_usd=usd_for_usage(usage, provider.price) if provider else 0.0,
        )
        return {
            "query_type": query_type,
            "retrieval_path": _PATH_FOR[query_type],
            "trace": [trace],
        }

    return route_query
