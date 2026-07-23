"""Retrieval node: hybrid page retrieval with graceful degradation.

Runs the systems the router asked for:
    visual -> ColPali query embedding + VectorChord MaxSim
    bm25   -> Postgres FTS
    hybrid -> both, fused with reciprocal rank fusion

Degrades instead of failing: if the encoder is unavailable (not configured,
model missing) or MaxSim errors, FTS still answers and the gap is recorded
in `errors` — a server without the model stays functional.
"""

from __future__ import annotations

import asyncio
import time

import numpy as np
from numpy.typing import NDArray
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.state import AgentState, NodeFn, NodeUpdate
from app.retrieval import store
from app.retrieval.bm25 import fts_search
from app.retrieval.colpali import ColPaliEncoder
from app.retrieval.hybrid import reciprocal_rank_fusion
from app.retrieval.store import PageHit
from app.schemas.query import Candidate, NodeTrace, QueryFilters

DEFAULT_TOP_K = 8


def _embed_query(encoder: ColPaliEncoder, query: str) -> NDArray[np.float32]:
    return encoder.embed_queries([query])[0]


def make_retrieval_node(
    sessionmaker: async_sessionmaker[AsyncSession],
    encoder: ColPaliEncoder | None,
    *,
    top_k: int = DEFAULT_TOP_K,
) -> NodeFn:
    async def retrieve(state: AgentState) -> NodeUpdate:
        started = time.perf_counter()
        query = state["query"]
        filters = state.get("filters") or QueryFilters()
        path = state.get("retrieval_path", "hybrid")
        errors: list[str] = []

        want_visual = path in ("visual", "hybrid")
        want_fts = path in ("bm25", "hybrid") or (want_visual and encoder is None)
        if want_visual and encoder is None:
            errors.append("visual retrieval skipped: no ColPali encoder configured")

        result_lists: list[list[PageHit]] = []
        async with sessionmaker() as session:
            if want_fts:
                result_lists.append(
                    await fts_search(session, query, top_k=top_k, filters=filters)
                )
            if want_visual and encoder is not None:
                try:
                    query_vectors = await asyncio.to_thread(_embed_query, encoder, query)
                    result_lists.append(
                        await store.maxsim_search(
                            session, query_vectors, top_k=top_k, filters=filters
                        )
                    )
                except Exception as exc:  # degrade, never fail the query
                    errors.append(f"visual retrieval unavailable: {exc}")

        non_empty = [hits for hits in result_lists if hits]
        if len(non_empty) > 1:
            fused = reciprocal_rank_fusion(non_empty, top_k=top_k)
        elif non_empty:
            fused = list(non_empty[0][:top_k])
        else:
            fused = []

        candidates = [
            Candidate(
                page_id=h.page_id,
                filing_id=h.filing_id,
                page_no=h.page_no,
                score=h.score,
                source_snippet=h.snippet,
            )
            for h in fused
        ]
        trace = NodeTrace(
            name="retrieval",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return {"candidates": candidates, "trace": [trace], "errors": errors}

    return retrieve
