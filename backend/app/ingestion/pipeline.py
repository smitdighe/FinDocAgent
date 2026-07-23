"""End-to-end ingest orchestration: fetch -> render -> extract -> persist.

Embedding is intentionally NOT part of this pipeline — it runs separately via
scripts/embed_batch.py (locally, ideally on GPU). A filing lands here with
status=extracted and becomes embedded once all its pages have vectors.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import FILING_STATUS_EMBEDDED, FILING_STATUS_EXTRACTED
from app.ingestion.edgar_client import EdgarClient, FilingMeta
from app.ingestion.fetch import fetch_filing_document
from app.ingestion.render import (
    ChromiumRenderer,
    PageRender,
    build_page_renders,
    extract_page_texts,
    rasterize_pdf,
)
from app.retrieval import store
from app.tables.extractor import (
    extract_tables_from_html,
    locate_table_bboxes,
    map_tables_to_pages,
)
from app.tables.models import TableData

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IngestOutcome:
    ticker: str
    form_type: str
    accession_no: str
    status: str  # "ingested" | "skipped" | "error"
    pages: int = 0
    tables: int = 0
    error: str = ""


@dataclass(slots=True)
class IngestSummary:
    outcomes: list[IngestOutcome] = field(default_factory=list)

    @property
    def ingested(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "ingested")

    @property
    def skipped(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "skipped")

    @property
    def errors(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "error")


def _extract_and_map_tables(
    html_path: Path, pdf_path: Path, page_texts: list[str]
) -> list[TableData]:
    tables = extract_tables_from_html(html_path.read_bytes())
    map_tables_to_pages(tables, page_texts)
    locate_table_bboxes(pdf_path, tables)
    return tables


async def ingest_filing(
    session: AsyncSession,
    settings: Settings,
    client: EdgarClient,
    renderer: ChromiumRenderer,
    meta: FilingMeta,
) -> IngestOutcome:
    existing = await store.get_filing_by_accession(session, meta.accession_no)
    if existing is not None and existing.status in (
        FILING_STATUS_EXTRACTED,
        FILING_STATUS_EMBEDDED,
    ):
        return IngestOutcome(meta.ticker, meta.form_type, meta.accession_no, "skipped")

    html_path = await fetch_filing_document(client, meta, settings.storage_dir)
    workdir = settings.storage_dir / "filings" / meta.accession_nodash
    pdf_path = await renderer.html_to_pdf(html_path, meta.archive_base_url, workdir / "filing.pdf")

    # CPU-bound stages off the event loop.
    image_paths = await asyncio.to_thread(
        rasterize_pdf,
        pdf_path,
        workdir / "pages",
        dpi=settings.render_dpi,
        jpeg_quality=settings.render_jpeg_quality,
    )
    texts = await asyncio.to_thread(extract_page_texts, pdf_path)
    pages: list[PageRender] = build_page_renders(image_paths, texts)
    tables = await asyncio.to_thread(
        _extract_and_map_tables, html_path, pdf_path, [p.text for p in pages]
    )

    await store.upsert_filing_bundle(session, meta, pages, tables)
    await session.commit()
    return IngestOutcome(
        meta.ticker,
        meta.form_type,
        meta.accession_no,
        "ingested",
        pages=len(pages),
        tables=len(tables),
    )


async def ingest_tickers(
    session: AsyncSession,
    settings: Settings,
    client: EdgarClient,
    renderer: ChromiumRenderer,
    tickers: Sequence[str],
    *,
    forms: Sequence[str],
    limit_per_form: int = 2,
) -> IngestSummary:
    summary = IngestSummary()
    for ticker in tickers:
        try:
            company = await client.resolve_ticker(ticker)
            metas = await client.list_filings(company, forms=forms, limit_per_form=limit_per_form)
        except Exception as exc:  # keep the batch going
            logger.exception("listing failed for %s", ticker)
            summary.outcomes.append(
                IngestOutcome(ticker.upper(), "-", "-", "error", error=str(exc)[:300])
            )
            continue
        for meta in metas:
            try:
                outcome = await ingest_filing(session, settings, client, renderer, meta)
            except Exception as exc:  # keep the batch going
                logger.exception("ingest failed for %s %s", meta.ticker, meta.accession_no)
                await session.rollback()
                outcome = IngestOutcome(
                    meta.ticker, meta.form_type, meta.accession_no, "error", error=str(exc)[:300]
                )
            summary.outcomes.append(outcome)
    return summary
