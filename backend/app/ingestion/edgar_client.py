"""Async EDGAR client: ticker resolution, filing listings, full-text search.

SEC fair-access rules require a descriptive User-Agent with contact info and
at most ~10 req/s; this client refuses to run without a UA and throttles well
under the ceiling.

API shapes verified live on 2026-07-03:
- https://www.sec.gov/files/company_tickers.json
    {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
- https://data.sec.gov/submissions/CIK##########.json
    filings.recent = columnar arrays: form, accessionNumber, filingDate,
    reportDate, primaryDocument, isInlineXBRL, ...  (covers ~last 1000 filings,
    plenty for recent 10-K/10-Q; older ranges would need the paged files)
- https://efts.sec.gov/LATEST/search-index?q=...&forms=...
    Elasticsearch-style {"hits": {"hits": [{"_id": "accession:doc", "_source": ...}]}}
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from types import TracebackType
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
SEC_FULL_TEXT_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"


class EdgarError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CompanyInfo:
    cik: str  # zero-padded to 10 digits
    ticker: str
    title: str


@dataclass(frozen=True, slots=True)
class FilingMeta:
    cik: str
    ticker: str
    company_name: str
    form_type: str
    accession_no: str  # dashed form: 0000320193-25-000073
    filing_date: date
    report_date: date | None
    primary_document: str
    is_inline_xbrl: bool

    @property
    def accession_nodash(self) -> str:
        return self.accession_no.replace("-", "")

    @property
    def archive_base_url(self) -> str:
        # EDGAR archives use the unpadded CIK in the path.
        return f"{SEC_ARCHIVES_BASE}/{int(self.cik)}/{self.accession_nodash}"

    @property
    def primary_doc_url(self) -> str:
        return f"{self.archive_base_url}/{self.primary_document}"


class _Throttle:
    """Min-interval async throttle; keeps us politely under SEC's 10 req/s."""

    def __init__(self, max_per_sec: float) -> None:
        self._interval = 1.0 / max_per_sec if max_per_sec > 0 else 0.0
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        if self._interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            delay = self._last + self._interval - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = time.monotonic()


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return False


class EdgarClient:
    def __init__(
        self,
        user_agent: str,
        *,
        max_requests_per_sec: float = 5.0,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not user_agent.strip():
            raise EdgarError(
                "EDGAR_USER_AGENT must be set — SEC requires a User-Agent with contact info"
            )
        self._client = httpx.AsyncClient(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )
        self._throttle = _Throttle(max_requests_per_sec)
        self._ticker_map: dict[str, CompanyInfo] | None = None

    async def __aenter__(self) -> EdgarClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(4),
            wait=wait_exponential(multiplier=0.5, max=8),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        ):
            with attempt:
                await self._throttle.wait()
                resp = await self._client.get(url, params=params)
                resp.raise_for_status()
                return resp
        raise EdgarError(f"unreachable retry state for {url}")  # pragma: no cover

    async def resolve_ticker(self, ticker: str) -> CompanyInfo:
        tmap = await self._load_ticker_map()
        info = tmap.get(ticker.strip().upper())
        if info is None:
            raise EdgarError(f"unknown ticker: {ticker!r}")
        return info

    async def _load_ticker_map(self) -> dict[str, CompanyInfo]:
        if self._ticker_map is None:
            data: dict[str, Any] = (await self._get(SEC_TICKER_MAP_URL)).json()
            tmap: dict[str, CompanyInfo] = {}
            for row in data.values():
                info = CompanyInfo(
                    cik=f"{int(row['cik_str']):010d}",
                    ticker=str(row["ticker"]).upper(),
                    title=str(row["title"]),
                )
                tmap.setdefault(info.ticker, info)
            self._ticker_map = tmap
        return self._ticker_map

    async def list_filings(
        self,
        company: CompanyInfo,
        *,
        forms: Sequence[str],
        limit_per_form: int = 3,
    ) -> list[FilingMeta]:
        """Most-recent filings of the requested forms (exact match, so 10-K/A
        amendments are excluded unless asked for), newest first."""
        url = SEC_SUBMISSIONS_URL.format(cik=company.cik)
        data: dict[str, Any] = (await self._get(url)).json()
        recent: dict[str, list[Any]] = data["filings"]["recent"]
        wanted = {f.strip().upper() for f in forms}
        company_name = str(data.get("name") or company.title)

        out: list[FilingMeta] = []
        counts: dict[str, int] = {}
        forms_col = recent["form"]
        inline_col = recent.get("isInlineXBRL")
        for i, form in enumerate(forms_col):
            form_u = str(form).upper()
            if form_u not in wanted or counts.get(form_u, 0) >= limit_per_form:
                continue
            primary = str(recent["primaryDocument"][i] or "")
            if not primary.lower().endswith((".htm", ".html")):
                continue
            report_raw = str(recent["reportDate"][i] or "")
            counts[form_u] = counts.get(form_u, 0) + 1
            out.append(
                FilingMeta(
                    cik=company.cik,
                    ticker=company.ticker,
                    company_name=company_name,
                    form_type=form_u,
                    accession_no=str(recent["accessionNumber"][i]),
                    filing_date=date.fromisoformat(str(recent["filingDate"][i])),
                    report_date=date.fromisoformat(report_raw) if report_raw else None,
                    primary_document=primary,
                    is_inline_xbrl=bool(inline_col[i]) if inline_col else False,
                )
            )
        return out

    async def full_text_search(
        self, query: str, *, forms: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        """EDGAR full-text search (2001+). Returns raw ES-style hits; used for
        gold-set drafting, not the ingestion path."""
        params: dict[str, str] = {"q": query}
        if forms:
            params["forms"] = forms
        data: dict[str, Any] = (await self._get(SEC_FULL_TEXT_SEARCH_URL, params=params)).json()
        hits: list[dict[str, Any]] = data.get("hits", {}).get("hits", [])
        return hits[:limit]

    async def download(self, url: str) -> bytes:
        return (await self._get(url)).content
