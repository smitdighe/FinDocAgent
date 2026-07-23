"""Shared fixtures. Deterministic tests never hit live EDGAR/LLM — the EDGAR
client runs against recorded response shapes via httpx.MockTransport.

Integration tests (browser/DB) are opt-in: RUN_INTEGRATION=1.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from app.ingestion.edgar_client import SEC_TICKER_MAP_URL, EdgarClient

requires_integration = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="integration test (browser/DB/network); set RUN_INTEGRATION=1",
)


@pytest.fixture(autouse=True)
async def _reset_db_engine() -> AsyncIterator[None]:
    """Give every async test its own async engine on its own event loop.

    The app caches a process-wide engine (bound to the loop that created it);
    pytest-asyncio runs each test in a fresh loop, so a cached engine from a
    prior test is bound to a closed loop. Reset before and dispose after — in
    the same loop the engine was created in."""
    import app.db.session as session_module

    session_module._engine = None
    session_module._sessionmaker = None
    yield
    try:
        await session_module.dispose_engine()
    except RuntimeError:
        session_module._engine = None
        session_module._sessionmaker = None

# Shapes recorded from the live EDGAR APIs on 2026-07-03 (trimmed).
TICKER_MAP: dict[str, Any] = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
}

SUBMISSIONS_AAPL: dict[str, Any] = {
    "cik": "320193",
    "name": "Apple Inc.",
    "filings": {
        "recent": {
            "form": ["4", "10-K", "8-K", "10-Q", "10-Q", "10-K"],
            "accessionNumber": [
                "0000320193-25-000001",
                "0000320193-25-000073",
                "0000320193-25-000050",
                "0000320193-25-000057",
                "0000320193-25-000023",
                "0000320193-24-000123",
            ],
            "filingDate": [
                "2025-12-01",
                "2025-10-31",
                "2025-09-05",
                "2025-08-01",
                "2025-05-02",
                "2024-11-01",
            ],
            "reportDate": [
                "",
                "2025-09-27",
                "2025-09-04",
                "2025-06-28",
                "2025-03-29",
                "2024-09-28",
            ],
            "primaryDocument": [
                "xslF345X05/wk-form4.xml",
                "aapl-20250927.htm",
                "aapl-8k.htm",
                "aapl-20250628.htm",
                "aapl-20250329.htm",
                "aapl-20240928.htm",
            ],
            "isInlineXBRL": [0, 1, 1, 1, 1, 1],
        }
    },
}

# Synthetic mini-filing: one real financial table (rowspan+colspan), one
# nested data table, and layout scaffolding that must be filtered out.
SAMPLE_FILING_HTML = b"""<html>
<head><title>Sample 10-K</title></head>
<body>
<p>CONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS</p>
<table>
  <tr><th rowspan="2">Line item</th><th colspan="2">Three months ended</th></tr>
  <tr><th>2025</th><th>2024</th></tr>
  <tr><td>Total net sales</td><td>$ 94,930</td><td>$ 90,753</td></tr>
  <tr><td>Net income</td><td>24,780</td><td>23,636</td></tr>
</table>
<table><tr><td><div>layout only</div></td><td>nav</td></tr></table>
<table><tr><td>alpha</td><td>beta</td></tr><tr><td>gamma</td><td>delta</td></tr></table>
<table><tr><td>
  <table>
    <tr><td>Inner metric</td><td>2,000</td></tr>
    <tr><td>Other metric</td><td>4,000</td></tr>
  </table>
</td></tr></table>
</body>
</html>"""


class EdgarMock:
    """MockTransport handler with call recording (for cache assertions)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        if url == SEC_TICKER_MAP_URL:
            return httpx.Response(200, json=TICKER_MAP)
        if "submissions/CIK0000320193" in url:
            return httpx.Response(200, json=SUBMISSIONS_AAPL)
        if "/Archives/edgar/data/320193/" in url:
            return httpx.Response(200, content=SAMPLE_FILING_HTML)
        return httpx.Response(404, json={"error": "not found"})


@pytest.fixture
def edgar_mock() -> EdgarMock:
    return EdgarMock()


@pytest.fixture
async def edgar_client(edgar_mock: EdgarMock) -> AsyncIterator[EdgarClient]:
    client = EdgarClient(
        "FinDocAgent-tests (test@example.com)",
        max_requests_per_sec=0,  # no throttling in tests
        transport=httpx.MockTransport(edgar_mock.handler),
    )
    yield client
    await client.aclose()
