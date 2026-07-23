"""HTML -> PDF -> page images + per-page text.

EDGAR filings are continuous HTML with no fixed pagination. We manufacture
stable pages by printing through headless Chromium (Letter, fixed margins),
then rasterizing each PDF page to JPEG (for ColPali) and extracting per-page
text (for FTS + table page-mapping). Every page-level citation in the system
refers to this pagination.

Relative assets (images etc.) inside the filing HTML are resolved against the
EDGAR archive URL via an injected <base> tag; Chromium fetches them live with
our SEC User-Agent. Missing assets degrade gracefully.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pdfplumber
import pypdfium2 as pdfium
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

if TYPE_CHECKING:
    from playwright.async_api import Browser, Playwright

_HEAD_RE = re.compile(r"<head(\s[^>]*)?>", re.IGNORECASE)


@dataclass(slots=True)
class PageRender:
    page_no: int  # 1-based
    image_path: Path
    text: str


@dataclass(slots=True)
class RenderResult:
    pdf_path: Path
    pages: list[PageRender]


def inject_base_href(html: str, base_url: str) -> str:
    """Insert a <base> tag so relative asset URLs resolve to the EDGAR archive.

    Inserted immediately after <head> when present, else prepended.
    """
    tag = f'<base href="{base_url.rstrip("/")}/">'
    match = _HEAD_RE.search(html)
    if match:
        i = match.end()
        return html[:i] + tag + html[i:]
    return tag + html


class ChromiumRenderer:
    """Reusable headless-Chromium printer (one browser for a whole batch)."""

    def __init__(self, user_agent: str, *, timeout_ms: int = 240_000) -> None:
        self._user_agent = user_agent
        self._timeout_ms = timeout_ms
        self._pw: Playwright | None = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> ChromiumRenderer:
        pw = await async_playwright().start()
        self._pw = pw
        self._browser = await pw.chromium.launch()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()
        self._browser = None
        self._pw = None

    async def html_to_pdf(self, html_path: Path, base_url: str, pdf_path: Path) -> Path:
        if self._browser is None:
            raise RuntimeError("use `async with ChromiumRenderer(...)` before rendering")
        html = await asyncio.to_thread(html_path.read_text, encoding="utf-8", errors="replace")
        html = inject_base_href(html, base_url)

        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        page = await self._browser.new_page(user_agent=self._user_agent)
        try:
            await page.set_content(html, wait_until="load", timeout=self._timeout_ms)
            try:
                # Give slow EDGAR-hosted images a bounded chance to arrive.
                await page.wait_for_load_state("networkidle", timeout=15_000)
            except PlaywrightError:
                pass
            await page.emulate_media(media="print")
            await page.pdf(
                path=str(pdf_path),
                format="Letter",
                print_background=True,
                margin={
                    "top": "0.5in",
                    "bottom": "0.5in",
                    "left": "0.5in",
                    "right": "0.5in",
                },
            )
        finally:
            await page.close()
        return pdf_path


def rasterize_pdf(
    pdf_path: Path, images_dir: Path, *, dpi: int = 150, jpeg_quality: int = 85
) -> list[Path]:
    """Render each PDF page to JPEG at `dpi`. Returns paths in page order."""
    images_dir.mkdir(parents=True, exist_ok=True)
    scale = dpi / 72.0
    paths: list[Path] = []
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        for i in range(len(doc)):
            bitmap = doc[i].render(scale=scale)
            pil_image = bitmap.to_pil().convert("RGB")
            out = images_dir / f"page_{i + 1:04d}.jpg"
            pil_image.save(out, "JPEG", quality=jpeg_quality)
            paths.append(out)
    finally:
        doc.close()
    return paths


def extract_page_texts(pdf_path: Path) -> list[str]:
    """Per-page text via pdfplumber (Chromium PDFs carry a clean text layer)."""
    texts: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            texts.append(page.extract_text() or "")
            page.flush_cache()
    return texts


def build_page_renders(image_paths: list[Path], texts: list[str]) -> list[PageRender]:
    if len(image_paths) != len(texts):  # pragma: no cover - both derive from same PDF
        raise ValueError(
            f"page count mismatch: {len(image_paths)} images vs {len(texts)} texts"
        )
    return [
        PageRender(page_no=i + 1, image_path=img, text=txt)
        for i, (img, txt) in enumerate(zip(image_paths, texts, strict=True))
    ]
