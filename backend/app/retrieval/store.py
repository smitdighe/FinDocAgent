"""Vector + document CRUD and MaxSim search execution."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    FILING_STATUS_EMBEDDED,
    FILING_STATUS_EXTRACTED,
    ExtractedTable,
    Filing,
    Page,
    PageEmbedding,
)
from app.ingestion.edgar_client import FilingMeta
from app.ingestion.render import PageRender
from app.retrieval.maxsim import MAXSIM_OP, multivector_literal
from app.schemas.query import QueryFilters
from app.tables.models import TableData


@dataclass(frozen=True, slots=True)
class PageHit:
    page_id: uuid.UUID
    filing_id: uuid.UUID
    page_no: int
    score: float  # higher is better (MaxSim similarity / FTS rank)
    snippet: str


@dataclass(frozen=True, slots=True)
class PendingPage:
    page_id: uuid.UUID
    image_path: str


# ---------------------------------------------------------------- documents


async def get_filing_by_accession(session: AsyncSession, accession_no: str) -> Filing | None:
    filing: Filing | None = await session.scalar(
        select(Filing).where(Filing.accession_no == accession_no)
    )
    return filing


async def upsert_filing_bundle(
    session: AsyncSession,
    meta: FilingMeta,
    pages: list[PageRender],
    tables: list[TableData],
) -> Filing:
    """Persist a rendered filing with pages and tables (status=extracted).

    Re-ingesting an accession replaces the previous bundle (cascade wipes
    pages, embeddings and tables) — renders are deterministic only per
    Chromium version, so we never mix paginations.
    """
    existing = await get_filing_by_accession(session, meta.accession_no)
    if existing is not None:
        await session.delete(existing)
        await session.flush()

    filing = Filing(
        ticker=meta.ticker,
        cik=meta.cik,
        company_name=meta.company_name,
        form_type=meta.form_type,
        accession_no=meta.accession_no,
        filing_date=meta.filing_date,
        period_end=meta.report_date,
        source_url=meta.primary_doc_url,
        primary_doc=meta.primary_document,
        status=FILING_STATUS_EXTRACTED,
        page_count=len(pages),
    )
    session.add(filing)
    await session.flush()

    page_rows: dict[int, Page] = {}
    for render in pages:
        row = Page(
            filing_id=filing.id,
            page_no=render.page_no,
            image_path=str(render.image_path),
            text=render.text,
        )
        session.add(row)
        page_rows[render.page_no] = row
    await session.flush()

    for table in tables:
        page_id = None
        if table.page_no is not None and table.page_no in page_rows:
            page_id = page_rows[table.page_no].id
        session.add(
            ExtractedTable(
                filing_id=filing.id,
                page_id=page_id,
                table_index=table.table_index,
                caption=table.caption,
                n_rows=table.n_rows,
                n_cols=table.n_cols,
                grid=table.grid,
                bbox=list(table.bbox) if table.bbox is not None else None,
                provenance={
                    "anchor_texts": table.anchor_texts,
                    "match_confidence": table.match_confidence,
                },
            )
        )
    await session.flush()
    return filing


async def list_filings_with_page_counts(session: AsyncSession) -> list[tuple[Filing, int]]:
    stmt = (
        select(Filing, func.count(Page.id))
        .outerjoin(Page, Page.filing_id == Filing.id)
        .group_by(Filing.id)
        .order_by(Filing.filing_date.desc())
    )
    rows = (await session.execute(stmt)).all()
    return [(row[0], int(row[1])) for row in rows]


async def get_page_detail(
    session: AsyncSession, filing_id: uuid.UUID, page_no: int
) -> tuple[Filing, Page, list[ExtractedTable]] | None:
    filing = await session.get(Filing, filing_id)
    if filing is None:
        return None
    page = await session.scalar(
        select(Page).where(Page.filing_id == filing_id, Page.page_no == page_no)
    )
    if page is None:
        return None
    tables = (
        (
            await session.execute(
                select(ExtractedTable)
                .where(ExtractedTable.page_id == page.id)
                .order_by(ExtractedTable.table_index)
            )
        )
        .scalars()
        .all()
    )
    return filing, page, list(tables)


# --------------------------------------------------------------- embeddings


async def pages_missing_embeddings(
    session: AsyncSession, *, ticker: str | None = None, limit: int = 0
) -> list[PendingPage]:
    stmt = (
        select(Page.id, Page.image_path)
        .join(Filing, Filing.id == Page.filing_id)
        .outerjoin(PageEmbedding, PageEmbedding.page_id == Page.id)
        .where(PageEmbedding.page_id.is_(None))
        .order_by(Filing.filing_date.desc(), Page.page_no)
    )
    if ticker:
        stmt = stmt.where(Filing.ticker == ticker.upper())
    if limit > 0:
        stmt = stmt.limit(limit)
    rows = (await session.execute(stmt)).all()
    return [PendingPage(page_id=r[0], image_path=r[1]) for r in rows]


async def insert_page_embedding(
    session: AsyncSession,
    page_id: uuid.UUID,
    vectors: NDArray[np.float32],
    *,
    model: str,
    pool_factor: int = 1,
) -> None:
    """Upsert a page's multi-vector. The vector array is inlined as a
    validated literal (built from floats only) — this avoids driver codec
    variance for `vector[]` params; scalars stay bound."""
    literal = multivector_literal(vectors)
    sql = f"""
        INSERT INTO page_embeddings (page_id, embeddings, model, n_vectors, pool_factor, created_at)
        VALUES (:page_id, {literal}, :model, :n_vectors, :pool_factor, now())
        ON CONFLICT (page_id) DO UPDATE SET
            embeddings = EXCLUDED.embeddings,
            model = EXCLUDED.model,
            n_vectors = EXCLUDED.n_vectors,
            pool_factor = EXCLUDED.pool_factor,
            created_at = now()
    """
    await session.execute(
        text(sql),
        {
            "page_id": page_id,
            "model": model,
            "n_vectors": int(vectors.shape[0]),
            "pool_factor": pool_factor,
        },
    )


async def mark_filings_embedded(session: AsyncSession) -> int:
    """Flip status to `embedded` for filings whose pages all have vectors."""
    result = await session.execute(
        text(
            """
            UPDATE filings f SET status = :embedded
            WHERE f.status = :extracted
              AND NOT EXISTS (
                SELECT 1 FROM pages p
                LEFT JOIN page_embeddings pe ON pe.page_id = p.id
                WHERE p.filing_id = f.id AND pe.page_id IS NULL
              )
            """
        ),
        {"embedded": FILING_STATUS_EMBEDDED, "extracted": FILING_STATUS_EXTRACTED},
    )
    return int(getattr(result, "rowcount", 0) or 0)


# ------------------------------------------------------------------ search


def _filter_clause(filters: QueryFilters | None) -> tuple[str, dict[str, object]]:
    if filters is None:
        return "", {}
    clauses: list[str] = []
    params: dict[str, object] = {}
    if filters.ticker:
        clauses.append("AND f.ticker = :f_ticker")
        params["f_ticker"] = filters.ticker.upper()
    if filters.form_type:
        clauses.append("AND f.form_type = :f_form")
        params["f_form"] = filters.form_type.upper()
    if filters.filing_id:
        clauses.append("AND f.id = :f_filing_id")
        params["f_filing_id"] = filters.filing_id
    return " ".join(clauses), params


async def maxsim_search(
    session: AsyncSession,
    query_vectors: NDArray[np.float32],
    *,
    top_k: int = 8,
    filters: QueryFilters | None = None,
    snippet_chars: int = 300,
) -> list[PageHit]:
    """Late-interaction page retrieval via VectorChord MaxSim (`@#`).

    `@#` returns negative MaxSim, so ascending distance == best match;
    reported score is the positive similarity (-distance).
    """
    literal = multivector_literal(query_vectors)
    where, params = _filter_clause(filters)
    sql = f"""
        SELECT p.id AS page_id, p.filing_id AS filing_id, p.page_no AS page_no,
               -(pe.embeddings {MAXSIM_OP} {literal}) AS score,
               left(p.text, :snippet_chars) AS snippet
        FROM page_embeddings pe
        JOIN pages p ON p.id = pe.page_id
        JOIN filings f ON f.id = p.filing_id
        WHERE TRUE {where}
        ORDER BY pe.embeddings {MAXSIM_OP} {literal}
        LIMIT :top_k
    """
    rows = (
        await session.execute(
            text(sql), {**params, "top_k": top_k, "snippet_chars": snippet_chars}
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
