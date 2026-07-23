"""Reciprocal rank fusion of MaxSim and FTS result lists."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.retrieval.store import PageHit

RRF_K = 60


def reciprocal_rank_fusion(
    result_lists: Sequence[Sequence[PageHit]],
    *,
    top_k: int = 8,
    k: int = RRF_K,
) -> list[PageHit]:
    """Fuse ranked lists by summed 1/(k + rank). Scores from different systems
    are incomparable, so only ranks matter; the fused PageHit carries the RRF
    score."""
    fused: dict[uuid.UUID, float] = {}
    first_seen: dict[uuid.UUID, PageHit] = {}
    for hits in result_lists:
        for rank, hit in enumerate(hits, start=1):
            fused[hit.page_id] = fused.get(hit.page_id, 0.0) + 1.0 / (k + rank)
            first_seen.setdefault(hit.page_id, hit)
    ranked = sorted(fused.items(), key=lambda item: item[1], reverse=True)[:top_k]
    return [
        PageHit(
            page_id=page_id,
            filing_id=first_seen[page_id].filing_id,
            page_no=first_seen[page_id].page_no,
            score=score,
            snippet=first_seen[page_id].snippet,
        )
        for page_id, score in ranked
    ]
