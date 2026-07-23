"""Apply migrations and print a quick corpus census. Convenience for dev.

Usage: python scripts/seed_db.py
"""

from __future__ import annotations

import asyncio
import subprocess
import sys

from sqlalchemy import text

from app.config import get_settings
from app.db.session import dispose_engine, get_sessionmaker


async def _census() -> None:
    settings = get_settings()
    sessionmaker = get_sessionmaker(settings)
    try:
        async with sessionmaker() as session:
            vchord = await session.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vchord'")
            )
            print(f"vchord extension: {vchord or 'MISSING'}")
            for table in ("filings", "pages", "page_embeddings", "tables"):
                count = await session.scalar(text(f"SELECT count(*) FROM {table}"))
                print(f"{table:>17}: {count}")
    finally:
        await dispose_engine()


def main() -> int:
    print("running alembic upgrade head ...")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], check=False
    )
    if result.returncode != 0:
        return result.returncode
    asyncio.run(_census())
    return 0


if __name__ == "__main__":
    sys.exit(main())
