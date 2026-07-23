"""EDGAR client, fetch, base-href injection, table extraction + page mapping."""

from pathlib import Path

import pytest

from app.ingestion.edgar_client import EdgarClient, EdgarError
from app.ingestion.fetch import fetch_filing_document
from app.ingestion.render import inject_base_href
from app.tables.extractor import extract_tables_from_html, map_tables_to_pages
from tests.conftest import SAMPLE_FILING_HTML, EdgarMock, requires_integration

# ------------------------------------------------------------- edgar client


async def test_resolve_ticker(edgar_client: EdgarClient) -> None:
    info = await edgar_client.resolve_ticker("aapl")
    assert info.cik == "0000320193"
    assert info.ticker == "AAPL"
    assert info.title == "Apple Inc."


async def test_resolve_unknown_ticker(edgar_client: EdgarClient) -> None:
    with pytest.raises(EdgarError, match="unknown ticker"):
        await edgar_client.resolve_ticker("ZZZZZZ")


async def test_list_filings_filters_and_limits(edgar_client: EdgarClient) -> None:
    company = await edgar_client.resolve_ticker("AAPL")
    metas = await edgar_client.list_filings(
        company, forms=["10-K", "10-Q"], limit_per_form=1
    )
    assert [m.form_type for m in metas] == ["10-K", "10-Q"]
    assert metas[0].accession_no == "0000320193-25-000073"  # newest 10-K
    assert metas[1].accession_no == "0000320193-25-000057"  # newest 10-Q
    # form "4" (xml primary) and "8-K" never appear
    assert all(m.form_type in {"10-K", "10-Q"} for m in metas)


async def test_list_filings_limit_two(edgar_client: EdgarClient) -> None:
    company = await edgar_client.resolve_ticker("AAPL")
    metas = await edgar_client.list_filings(
        company, forms=["10-K", "10-Q"], limit_per_form=2
    )
    assert len(metas) == 4
    ten_ks = [m for m in metas if m.form_type == "10-K"]
    assert [m.accession_no for m in ten_ks] == [
        "0000320193-25-000073",
        "0000320193-24-000123",
    ]


async def test_filing_meta_urls(edgar_client: EdgarClient) -> None:
    company = await edgar_client.resolve_ticker("AAPL")
    meta = (await edgar_client.list_filings(company, forms=["10-K"], limit_per_form=1))[0]
    assert meta.accession_nodash == "000032019325000073"
    assert meta.archive_base_url == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019325000073"
    )
    assert meta.primary_doc_url.endswith("/aapl-20250927.htm")
    assert meta.report_date is not None


def test_user_agent_required() -> None:
    with pytest.raises(EdgarError, match="EDGAR_USER_AGENT"):
        EdgarClient("   ")


# -------------------------------------------------------------------- fetch


async def test_fetch_writes_and_caches(
    edgar_client: EdgarClient, edgar_mock: EdgarMock, tmp_path: Path
) -> None:
    company = await edgar_client.resolve_ticker("AAPL")
    meta = (await edgar_client.list_filings(company, forms=["10-K"], limit_per_form=1))[0]

    first = await fetch_filing_document(edgar_client, meta, tmp_path)
    calls_after_first = len(edgar_mock.calls)
    second = await fetch_filing_document(edgar_client, meta, tmp_path)

    assert first == second
    assert first.read_bytes() == SAMPLE_FILING_HTML
    assert len(edgar_mock.calls) == calls_after_first  # cache hit, no re-download


# ---------------------------------------------------------------- rendering


def test_inject_base_href_with_head() -> None:
    html = '<html><head profile="x"><title>t</title></head><body></body></html>'
    out = inject_base_href(html, "https://www.sec.gov/Archives/edgar/data/1/2")
    assert '<head profile="x"><base href="https://www.sec.gov/Archives/edgar/data/1/2/">' in out


def test_inject_base_href_without_head() -> None:
    out = inject_base_href("<p>bare</p>", "https://example.com/base")
    assert out.startswith('<base href="https://example.com/base/">')


# ------------------------------------------------------------------- tables


def test_extract_tables_filters_layout() -> None:
    tables = extract_tables_from_html(SAMPLE_FILING_HTML)
    # financial table + nested inner data table; layout + non-numeric filtered
    assert len(tables) == 2
    assert tables[0].caption == "CONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS"


def test_grid_span_expansion() -> None:
    table = extract_tables_from_html(SAMPLE_FILING_HTML)[0]
    assert table.n_rows == 4
    assert table.n_cols == 3
    assert table.grid[0] == ["Line item", "Three months ended", None]
    assert table.grid[1] == [None, "2025", "2024"]  # rowspan carry
    assert table.grid[2] == ["Total net sales", "$ 94,930", "$ 90,753"]
    assert table.grid[3] == ["Net income", "24,780", "23,636"]


def test_map_tables_to_pages() -> None:
    tables = extract_tables_from_html(SAMPLE_FILING_HTML)
    page_texts = [
        "TABLE OF CONTENTS Item 1 Business Item 8 Financial Statements",
        "CONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS Three months ended "
        "Total net sales $ 94,930 $ 90,753 Net income 24,780 23,636",
    ]
    map_tables_to_pages(tables, page_texts)
    assert tables[0].page_no == 2
    assert tables[0].match_confidence >= 0.5
    assert tables[1].page_no is None  # inner table's anchors appear nowhere


@requires_integration
async def test_render_roundtrip(tmp_path: Path) -> None:
    """Chromium print -> raster -> text. Requires installed browsers."""
    from app.ingestion.render import ChromiumRenderer, extract_page_texts, rasterize_pdf

    html_path = tmp_path / "filing.htm"
    html_path.write_bytes(SAMPLE_FILING_HTML)
    async with ChromiumRenderer("FinDocAgent-tests (test@example.com)") as renderer:
        pdf_path = await renderer.html_to_pdf(
            html_path, "https://example.com", tmp_path / "filing.pdf"
        )
    images = rasterize_pdf(pdf_path, tmp_path / "pages", dpi=100)
    texts = extract_page_texts(pdf_path)
    assert len(images) == len(texts) >= 1
    assert "Total net sales" in texts[0]
    assert images[0].stat().st_size > 1_000
