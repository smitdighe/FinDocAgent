"""Exact-term retrieval over per-page text via Postgres FTS.

This is deliberately Postgres-native `tsvector`/`ts_rank_cd` — "BM25-ish"
rather than true BM25. It exists to catch exact terms (tickers, GAAP line
items, figures) that late interaction can miss; RRF fusion (hybrid.py)
combines it with MaxSim. If ranking quality becomes the bottleneck, the
VectorChord-suite `vchord_bm25` extension is the drop-in upgrade path.
"""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.retrieval.store import PageHit, _filter_clause
from app.schemas.query import QueryFilters

_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")

# Grammar + question + fiscal-period words that shouldn't constrain the match.
# `websearch_to_tsquery` ANDs every term, so leaving "fiscal"/"what" in a
# question excludes the financial-statement page (which never says "fiscal")
# while matching a prose page that happens to mention every word. Ranking
# should be driven by the financial nouns instead.
_FTS_STOP = frozenset(
    "what was were is are be been being how much many did does do done which "
    "when where who whom whose the a an of in for on to and or by at as it its "
    "their there this that these those with from we our us you your i my me "
    "fiscal year years quarter quarters ended ending end period periods most "
    "recent recently latest during over about into per had has have".split()
)


def _content_terms(query: str) -> list[str]:
    return [
        w
        for w in _WORD_RE.findall(query.lower())
        if len(w) > 2 and w not in _FTS_STOP and not _YEAR_RE.match(w)
    ]


def _focused_query(query: str) -> str:
    """Space-joined content terms => `websearch_to_tsquery` ANDs the financial
    nouns only (drops question/period words and years)."""
    return " ".join(_content_terms(query))


def _or_query(query: str) -> str:
    """OR-semantics fallback for recall when the focused AND-query is empty."""
    return " OR ".join(_content_terms(query))


async def _run_fts(
    session: AsyncSession,
    query_text: str,
    where: str,
    params: dict[str, object],
    *,
    top_k: int,
    snippet_chars: int,
) -> list[PageHit]:
    sql = f"""
        SELECT p.id AS page_id, p.filing_id AS filing_id, p.page_no AS page_no,
               ts_rank_cd(p.text_tsv, q, 32) AS score,
               left(p.text, :snippet_chars) AS snippet
        FROM pages p
        JOIN filings f ON f.id = p.filing_id,
             websearch_to_tsquery('english', :query) q
        WHERE p.text_tsv @@ q {where}
        ORDER BY score DESC
        LIMIT :top_k
    """
    rows = (
        await session.execute(
            text(sql),
            {**params, "query": query_text, "top_k": top_k, "snippet_chars": snippet_chars},
        )
    ).mappings()
    return [
        PageHit(
            page_id=r["page_id"],
            filing_id=r["filing_id"],
            page_no=int(r["page_no"]),
            score=float(r["score"]),
            snippet=str(r["snippet"] or ""),
        )
        for r in rows
    ]


async def fts_search(
    session: AsyncSession,
    query: str,
    *,
    top_k: int = 8,
    filters: QueryFilters | None = None,
    snippet_chars: int = 300,
) -> list[PageHit]:
    where, params = _filter_clause(filters)
    # Focused AND over financial content terms (high precision), then OR
    # fallback for recall, then the raw question as a last resort.
    for query_text in (_focused_query(query), _or_query(query), query):
        if not query_text.strip():
            continue
        hits = await _run_fts(
            session, query_text, where, params, top_k=top_k, snippet_chars=snippet_chars
        )
        if hits:
            return hits
    return []
