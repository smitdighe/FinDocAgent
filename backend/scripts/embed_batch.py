"""Batch-embed rendered filing pages into VectorChord.

Runs locally — on GPU when available, CPU otherwise (fine for small corpora).
The deployed API never runs this; it only embeds queries at request time.

Usage:
    python scripts/embed_batch.py                     # embed everything pending
    python scripts/embed_batch.py --ticker AAPL --batch-size 4 --limit 50
    python scripts/embed_batch.py --pool-factor 2     # ~2x smaller storage
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from PIL import Image

from app.config import get_settings
from app.db.session import dispose_engine, get_sessionmaker
from app.retrieval import store
from app.retrieval.colpali import ColPaliEncoder


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=None, help="override COLPALI_MODEL")
    parser.add_argument("--device", default=None, help="auto | cuda | cpu | mps")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0, help="max pages this run (0 = all)")
    parser.add_argument("--ticker", default=None, help="only pages of this ticker")
    parser.add_argument(
        "--pool-factor",
        type=int,
        default=1,
        help="hierarchical token pooling factor (1 = off; 2-3 shrinks storage)",
    )
    parser.add_argument("--dry-run", action="store_true", help="list pending pages and exit")
    return parser


async def amain(args: argparse.Namespace) -> int:
    settings = get_settings()
    sessionmaker = get_sessionmaker(settings)
    try:
        async with sessionmaker() as session:
            pending = await store.pages_missing_embeddings(
                session, ticker=args.ticker, limit=args.limit
            )
        if not pending:
            print("nothing to embed — all pages have vectors")
            return 0
        print(f"{len(pending)} pages pending")
        if args.dry_run:
            return 0

        encoder = ColPaliEncoder(
            args.model or settings.colpali_model,
            device=args.device or settings.colpali_device,
            dtype=settings.colpali_dtype,
        )
        print(f"loading {encoder.model_name} ...")
        encoder.load()
        print(f"model on device={encoder.device}")

        done = 0
        started = time.perf_counter()
        for i in range(0, len(pending), args.batch_size):
            batch = pending[i : i + args.batch_size]
            images = [Image.open(p.image_path).convert("RGB") for p in batch]
            embeddings = await asyncio.to_thread(
                encoder.embed_images, images, batch_size=args.batch_size
            )
            async with sessionmaker() as session:
                for page, emb in zip(batch, embeddings, strict=True):
                    if args.pool_factor > 1:
                        emb = encoder.pool(emb, args.pool_factor)
                    await store.insert_page_embedding(
                        session,
                        page.page_id,
                        emb,
                        model=encoder.model_name,
                        pool_factor=args.pool_factor,
                    )
                await session.commit()
            done += len(batch)
            elapsed = time.perf_counter() - started
            rate = done / elapsed if elapsed > 0 else 0.0
            print(f"  {done}/{len(pending)} pages  ({rate:.2f} pages/s)", flush=True)

        async with sessionmaker() as session:
            flipped = await store.mark_filings_embedded(session)
            await session.commit()
        print(f"done — {done} pages embedded, {flipped} filings now status=embedded")
        return 0
    finally:
        await dispose_engine()


def main() -> int:
    return asyncio.run(amain(build_parser().parse_args()))


if __name__ == "__main__":
    sys.exit(main())
