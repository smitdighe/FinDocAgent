"""Extract data tables from source filing HTML and map them onto rendered pages.

Why HTML instead of PDF-geometry extraction: SEC financial tables are real
<table> elements in the source document. Parsing them yields *exact* cell
values — which is what the verifier re-checks — whereas line/whitespace
heuristics over the PDF are lossy. The rendered PDF remains the citation
surface: each table is located on a page via anchor-text search, with a
best-effort bbox from pdfplumber.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pdfplumber
from lxml import html as lxml_html

from app.tables.models import TableData

_WS_RE = re.compile(r"\s+")
_DIGIT_RE = re.compile(r"\d")

# Tables bigger than this are almost certainly page-layout scaffolding.
MAX_ROWS = 500
MAX_COLS = 40
MAX_SPAN = 100


def _norm_text(s: str) -> str:
    return _WS_RE.sub(" ", s.replace("\xa0", " ")).strip()


def _match_key(s: str) -> str:
    """Whitespace-free lowercase key; robust to line-wrap differences between
    HTML and PDF text extraction."""
    return _WS_RE.sub("", s.lower())


def _cell_text(el: Any) -> str:
    return _norm_text(" ".join(t for t in el.itertext()))


def _int_attr(el: Any, name: str) -> int:
    raw = el.get(name)
    if raw is None:
        return 1
    try:
        val = int(str(raw).strip() or 1)
    except ValueError:
        return 1
    return max(1, min(val, MAX_SPAN))


def _table_to_grid(table_el: Any) -> list[list[str | None]]:
    """Expand a <table> into a rectangular grid honoring rowspan/colspan.

    The spanning cell's text lands in its top-left position; covered
    positions are None.
    """
    grid: list[list[str | None]] = []
    # col -> (rows_remaining, placeholder) for active rowspans
    carry: dict[int, int] = {}

    rows = table_el.xpath(".//tr")
    for tr in rows[:MAX_ROWS]:
        row: list[str | None] = []
        col = 0

        def _fill_carry(col: int, row: list[str | None]) -> int:
            while carry.get(col, 0) > 0:
                carry[col] -= 1
                if carry[col] <= 0:
                    del carry[col]
                row.append(None)
                col += 1
            return col

        col = _fill_carry(col, row)
        for cell in tr.xpath("./td|./th"):
            col = _fill_carry(col, row)
            colspan = _int_attr(cell, "colspan")
            rowspan = _int_attr(cell, "rowspan")
            text = _cell_text(cell)
            for k in range(colspan):
                row.append(text if k == 0 else None)
                if rowspan > 1:
                    carry[col + k] = rowspan - 1
            col += colspan
        col = _fill_carry(col, row)
        grid.append(row)

    if not grid:
        return []
    width = min(max(len(r) for r in grid), MAX_COLS)
    return [(r + [None] * (width - len(r)))[:width] for r in grid]


def _is_data_table(grid: list[list[str | None]]) -> bool:
    """Heuristic filter for layout scaffolding vs. actual data tables."""
    if len(grid) < 2 or (grid and len(grid[0]) < 2):
        return False
    non_empty = [c for row in grid for c in row if c]
    if len(non_empty) < 4:
        return False
    numeric_cells = sum(1 for c in non_empty if _DIGIT_RE.search(c))
    return numeric_cells >= 2


def _find_caption(table_el: Any) -> str:
    cap = table_el.find("caption")
    if cap is not None:
        return _cell_text(cap)[:300]
    # Best effort: nearest short preceding text block. Filings usually wrap
    # tables in <div> layers, so climb parents when siblings yield nothing.
    node = table_el
    for _ in range(3):
        prev = node.getprevious()
        for _ in range(4):
            if prev is None:
                break
            if prev.tag == "table":  # don't steal another table's heading
                return ""
            text = _cell_text(prev)
            if 0 < len(text) <= 200:
                return text
            prev = prev.getprevious()
        node = node.getparent()
        if node is None or node.tag in ("body", "html"):
            break
    return ""


def _pick_anchors(grid: list[list[str | None]], caption: str, *, max_anchors: int = 4) -> list[str]:
    """Distinctive cell strings used to locate the table in rendered page text."""
    candidates: list[str] = []
    if caption:
        candidates.append(caption)
    cells = [c for row in grid for c in row if c and len(c) >= 6]
    # Prefer longer, letter-bearing strings (labels beat bare numbers).
    cells.sort(key=lambda s: (bool(re.search(r"[A-Za-z]{3}", s)), len(s)), reverse=True)
    seen: set[str] = set()
    for c in candidates + cells:
        key = _match_key(c)
        if len(key) < 6 or key in seen:
            continue
        seen.add(key)
        candidates.append(c)
        if len(candidates) >= max_anchors + 1:
            break
    return candidates[:max_anchors]


def extract_tables_from_html(html_bytes: bytes) -> list[TableData]:
    """All plausible data tables from a filing, in document order."""
    tree = lxml_html.document_fromstring(html_bytes)
    tables: list[TableData] = []
    index = 0
    for el in tree.iter("table"):
        # Keep only leaf tables; outer tables are page layout in SEC docs.
        if el.find(".//table") is not None:
            continue
        grid = _table_to_grid(el)
        if not _is_data_table(grid):
            continue
        caption = _find_caption(el)
        tables.append(
            TableData(
                table_index=index,
                caption=caption,
                grid=grid,
                n_rows=len(grid),
                n_cols=len(grid[0]) if grid else 0,
                anchor_texts=_pick_anchors(grid, caption),
            )
        )
        index += 1
    return tables


def map_tables_to_pages(tables: list[TableData], page_texts: list[str]) -> None:
    """Assign each table a rendered page by anchor-text search.

    Tables appear in document order and pages are sequential, so the scan is
    monotonic with a one-page lookback (tables can straddle a page break).
    Mutates `tables` in place (page_no + match_confidence).
    """
    norm_pages = [_match_key(t) for t in page_texts]
    cursor = 0
    for table in tables:
        anchors = [_match_key(a) for a in table.anchor_texts if a]
        if not anchors:
            continue
        best_page = -1
        best_score = 0.0
        start = max(cursor - 1, 0)
        for pno in range(start, len(norm_pages)):
            page_text = norm_pages[pno]
            hits = sum(1 for a in anchors if a in page_text)
            score = hits / len(anchors)
            if score > best_score:
                best_page, best_score = pno, score
                if score >= 0.999:
                    break
        if best_page >= 0 and best_score >= 0.5:
            table.page_no = best_page + 1
            table.match_confidence = best_score
            cursor = best_page


def locate_table_bboxes(pdf_path: Path, tables: list[TableData]) -> None:
    """Best-effort bbox per mapped table: union of anchor hits on its page.

    bbox is optional by contract; any pdfplumber hiccup simply leaves it None.
    """
    mapped = [t for t in tables if t.page_no is not None and t.anchor_texts]
    if not mapped:
        return
    by_page: dict[int, list[TableData]] = {}
    for t in mapped:
        assert t.page_no is not None
        by_page.setdefault(t.page_no, []).append(t)

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_no, page_tables in by_page.items():
            if page_no < 1 or page_no > len(pdf.pages):
                continue
            page = pdf.pages[page_no - 1]
            for table in page_tables:
                boxes: list[tuple[float, float, float, float]] = []
                for anchor in table.anchor_texts[:3]:
                    pattern = re.escape(anchor)
                    try:
                        hits = page.search(pattern, regex=True, case=False)
                    except Exception:  # pdfplumber internals vary across PDFs
                        continue
                    for h in hits[:2]:
                        boxes.append(
                            (
                                float(h["x0"]),
                                float(h["top"]),
                                float(h["x1"]),
                                float(h["bottom"]),
                            )
                        )
                if boxes:
                    table.bbox = (
                        min(b[0] for b in boxes),
                        min(b[1] for b in boxes),
                        max(b[2] for b in boxes),
                        max(b[3] for b in boxes),
                    )
            page.flush_cache()
