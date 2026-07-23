"""SQLAlchemy ORM models (schema is managed by Alembic; no create_all in prod).

Coordinate conventions:
- `Page.page_no` is 1-based and refers to OUR rendered pagination (EDGAR HTML
  has no native pages; we manufacture them via Chromium print + raster).
- Table bboxes are in PDF points with a top-left origin (pdfplumber
  convention). Pixel coords on the page image = points * dpi / 72.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# ColPali-family models all project to 128-dim token vectors.
EMBEDDING_DIM = 128

# Filing.status lifecycle
FILING_STATUS_FETCHED = "fetched"
FILING_STATUS_EXTRACTED = "extracted"  # rendered + text/tables persisted
FILING_STATUS_EMBEDDED = "embedded"  # all pages have multi-vectors


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Filing(Base):
    __tablename__ = "filings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ticker: Mapped[str] = mapped_column(String(12), index=True)
    cik: Mapped[str] = mapped_column(String(10), index=True)
    company_name: Mapped[str] = mapped_column(String(255), default="")
    form_type: Mapped[str] = mapped_column(String(10), index=True)
    accession_no: Mapped[str] = mapped_column(String(25), unique=True)
    filing_date: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date, default=None)
    source_url: Mapped[str] = mapped_column(Text)
    primary_doc: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(16), default=FILING_STATUS_FETCHED)
    page_count: Mapped[int | None] = mapped_column(Integer, default=None)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    pages: Mapped[list["Page"]] = relationship(
        back_populates="filing", cascade="all, delete-orphan", passive_deletes=True
    )
    tables: Mapped[list["ExtractedTable"]] = relationship(
        back_populates="filing", cascade="all, delete-orphan", passive_deletes=True
    )


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    filing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("filings.id", ondelete="CASCADE"), index=True
    )
    page_no: Mapped[int] = mapped_column(Integer)
    image_path: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, default="")
    # Generated column powering FTS ("BM25-ish" exact-term retrieval).
    text_tsv: Mapped[Any | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(text, ''))", persisted=True),
        nullable=True,
    )

    filing: Mapped[Filing] = relationship(back_populates="pages")

    __table_args__ = (
        UniqueConstraint("filing_id", "page_no", name="uq_pages_filing_page"),
        Index("ix_pages_text_tsv", "text_tsv", postgresql_using="gin"),
    )


class PageEmbedding(Base):
    """One row per page: the page's ColPali multi-vector (array of 128-dim
    token vectors) served by VectorChord's MaxSim operator (`@#`)."""

    __tablename__ = "page_embeddings"

    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True
    )
    # list of 128-dim vectors; VectorChord indexes vector(128)[] with
    # `USING vchordrq (embeddings vector_maxsim_ops)` (created in migration).
    embeddings: Mapped[list[Any]] = mapped_column(ARRAY(Vector(EMBEDDING_DIM)), nullable=False)
    model: Mapped[str] = mapped_column(String(128))
    n_vectors: Mapped[int] = mapped_column(Integer)
    pool_factor: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExtractedTable(Base):
    """A data table extracted from the source HTML, mapped to a rendered page.

    `grid` holds the span-expanded cell matrix: rows of (text | null); null
    means the cell is covered by a rowspan/colspan from another cell.
    """

    __tablename__ = "tables"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    filing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("filings.id", ondelete="CASCADE"), index=True
    )
    page_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pages.id", ondelete="SET NULL"), index=True, default=None
    )
    table_index: Mapped[int] = mapped_column(Integer)  # order within the filing
    caption: Mapped[str] = mapped_column(Text, default="")
    n_rows: Mapped[int] = mapped_column(Integer)
    n_cols: Mapped[int] = mapped_column(Integer)
    grid: Mapped[list[Any]] = mapped_column(JSONB)
    # none_as_null: absent bbox must be SQL NULL, not JSON null
    bbox: Mapped[list[float] | None] = mapped_column(JSONB(none_as_null=True), default=None)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    filing: Mapped[Filing] = relationship(back_populates="tables")


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    gold_version: Mapped[str] = mapped_column(String(32))
    pipeline_git_sha: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(16), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # {"faithfulness": .., "answer_relevancy": .., "context_precision": ..}
    scores: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # {"cost_usd_total": .., "latency_ms_p50": .., "per_query": [...]}
    rollup: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")


class QueryLog(Base):
    __tablename__ = "query_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    query: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text, default=None)
    query_type: Mapped[str | None] = mapped_column(String(16), default=None)
    verification_status: Mapped[str | None] = mapped_column(String(16), default=None)
    # per-agent trace: [{"name", "latency_ms", "tokens_in", "tokens_out", "cost_usd"}]
    trace: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    cost_usd: Mapped[float | None] = mapped_column(Float, default=None)
    latency_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    provider: Mapped[str | None] = mapped_column(String(32), default=None)
    model: Mapped[str | None] = mapped_column(String(128), default=None)
