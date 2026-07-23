"""Ingestion CLI.

Usage:
    python -m app.ingestion.cli ingest --tickers AAPL,MSFT --forms 10-K,10-Q --limit-per-form 2
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.config import get_settings
from app.db.session import dispose_engine, get_sessionmaker
from app.ingestion.edgar_client import EdgarClient
from app.ingestion.pipeline import IngestSummary, ingest_tickers
from app.ingestion.render import ChromiumRenderer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.ingestion.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="fetch, render and extract filings")
    ingest.add_argument(
        "--tickers",
        "--ticker",
        dest="tickers",
        required=True,
        help="comma-separated tickers, e.g. AAPL,MSFT",
    )
    ingest.add_argument("--forms", default="10-K,10-Q", help="comma-separated form types")
    ingest.add_argument("--limit-per-form", type=int, default=2, help="filings per form type")
    return parser


async def _run_ingest(tickers: list[str], forms: list[str], limit_per_form: int) -> IngestSummary:
    settings = get_settings()
    sessionmaker = get_sessionmaker(settings)
    try:
        async with (
            EdgarClient(
                settings.edgar_user_agent,
                max_requests_per_sec=settings.edgar_max_requests_per_sec,
            ) as client,
            ChromiumRenderer(settings.edgar_user_agent) as renderer,
            sessionmaker() as session,
        ):
            return await ingest_tickers(
                session,
                settings,
                client,
                renderer,
                tickers,
                forms=forms,
                limit_per_form=limit_per_form,
            )
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "ingest":  # pragma: no cover - argparse enforces this
        return 2

    tickers = [t.strip().upper() for t in str(args.tickers).split(",") if t.strip()]
    forms = [f.strip().upper() for f in str(args.forms).split(",") if f.strip()]
    summary = asyncio.run(_run_ingest(tickers, forms, args.limit_per_form))

    for o in summary.outcomes:
        line = (
            f"[{o.status:^8}] {o.ticker:<6} {o.form_type:<6} {o.accession_no:<22} "
            f"pages={o.pages:<4} tables={o.tables:<4}"
        )
        if o.error:
            line += f"  {o.error}"
        print(line)
    print(
        f"\ningested={summary.ingested} skipped={summary.skipped} errors={summary.errors}"
    )
    return 1 if summary.errors else 0


if __name__ == "__main__":
    sys.exit(main())
