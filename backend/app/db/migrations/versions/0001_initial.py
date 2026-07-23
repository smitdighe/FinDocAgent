import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SKIP_VCHORD = os.environ.get("SKIP_VCHORD", "").lower() in ("1", "true", "yes")


def upgrade() -> None:
    if not _SKIP_VCHORD:
        op.execute("CREATE EXTENSION IF NOT EXISTS vchord CASCADE")

    op.create_table(
        "filings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("ticker", sa.String(12), nullable=False),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("form_type", sa.String(10), nullable=False),
        sa.Column("accession_no", sa.String(25), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("primary_doc", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("accession_no", name="uq_filings_accession_no"),
    )
    op.create_index("ix_filings_ticker", "filings", ["ticker"])
    op.create_index("ix_filings_cik", "filings", ["cik"])
    op.create_index("ix_filings_form_type", "filings", ["form_type"])

    op.create_table(
        "pages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "filing_id",
            sa.Uuid(),
            sa.ForeignKey("filings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("image_path", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "text_tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', coalesce(text, ''))", persisted=True),
            nullable=True,
        ),
        sa.UniqueConstraint("filing_id", "page_no", name="uq_pages_filing_page"),
    )
    op.create_index("ix_pages_filing_id", "pages", ["filing_id"])
    op.create_index("ix_pages_text_tsv", "pages", ["text_tsv"], postgresql_using="gin")

    if not _SKIP_VCHORD:
        op.create_table(
            "page_embeddings",
            sa.Column(
                "page_id",
                sa.Uuid(),
                sa.ForeignKey("pages.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("embeddings", postgresql.ARRAY(Vector(128)), nullable=False),
            sa.Column("model", sa.String(128), nullable=False),
            sa.Column("n_vectors", sa.Integer(), nullable=False),
            sa.Column("pool_factor", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.execute(
            "CREATE INDEX ix_page_embeddings_maxsim ON page_embeddings "
            "USING vchordrq (embeddings vector_maxsim_ops)"
        )

    op.create_table(
        "tables",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "filing_id",
            sa.Uuid(),
            sa.ForeignKey("filings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "page_id",
            sa.Uuid(),
            sa.ForeignKey("pages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("table_index", sa.Integer(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("n_rows", sa.Integer(), nullable=False),
        sa.Column("n_cols", sa.Integer(), nullable=False),
        sa.Column("grid", postgresql.JSONB(), nullable=False),
        sa.Column("bbox", postgresql.JSONB(), nullable=True),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_tables_filing_id", "tables", ["filing_id"])
    op.create_index("ix_tables_page_id", "tables", ["page_id"])

    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("gold_version", sa.String(32), nullable=False),
        sa.Column("pipeline_git_sha", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scores", postgresql.JSONB(), nullable=False),
        sa.Column("rollup", postgresql.JSONB(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
    )

    op.create_table(
        "query_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("query_type", sa.String(16), nullable=True),
        sa.Column("verification_status", sa.String(16), nullable=True),
        sa.Column("trace", postgresql.JSONB(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("query_logs")
    op.drop_table("eval_runs")
    op.drop_table("tables")
    if not _SKIP_VCHORD:
        op.drop_table("page_embeddings")
    op.drop_table("pages")
    op.drop_table("filings")
