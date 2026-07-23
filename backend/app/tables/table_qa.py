"""Numeric QA over extracted table grids.

Deterministic engine first: match question terms against row labels and
period/column headers, then read the exact stored cell. The optional LLM
fallback (through the provider abstraction — never an SDK) only proposes
(table, row, col) indices; the answer value is ALWAYS re-read from the
stored grid, so provenance stays exact for the verifier.

Grid semantics (from tables/extractor.py): None marks a cell covered by a
rowspan/colspan whose text lives at the span's top-left; "" is a genuinely
empty cell. Column labels therefore span-fill None from the left but never
propagate across "".
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from app.llm.base import LLMProvider, Message, Usage
from app.schemas.query import TableAnswer

Grid = list[list[str | None]]

MIN_CONFIDENCE = 0.35
MAX_HEADER_ROWS = 5
MAX_LLM_TABLES = 3

_STOPWORDS = frozenset(
    "what was were is are the a an of in for on to and or by at as did do does "
    "how much many report reported company its their".split()
)
_PERIOD_WORDS = frozenset(
    "fiscal fy year years quarter quarters ended ending months month three six nine".split()
)
_MONTHS = frozenset(
    "january february march april may june july august september october november december".split()
)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_QUARTER_RE = re.compile(r"\bq([1-4])\b", re.IGNORECASE)
_NUMERIC_CELL_RE = re.compile(r"^\(?\$?\s*-?[\d,]+(?:\.\d+)?\s*\)?%?$")
_UNIT_RE = re.compile(r"in (millions|billions|thousands)", re.IGNORECASE)
_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)


@dataclass(frozen=True, slots=True)
class TableForQA:
    """A stored table plus the provenance the verifier needs."""

    table_id: uuid.UUID
    page_id: uuid.UUID
    page_no: int | None
    caption: str
    grid: Grid
    table_index: int = 0
    rank: int = 0  # candidate-page rank; lower = better


# ------------------------------------------------------------------ parsing


def is_numeric_cell(text: str) -> bool:
    t = text.strip()
    return bool(t) and any(ch.isdigit() for ch in t) and bool(_NUMERIC_CELL_RE.match(t))


def parse_cell_number(text: str) -> float | None:
    """'(1,234.5)' -> -1234.5; '$ 416,161' -> 416161.0; '7.49' -> 7.49."""
    t = text.strip().replace(",", "").replace("$", "").replace("%", "").strip()
    negative = t.startswith("(") and t.endswith(")")
    t = t.strip("()").strip()
    if not t:
        return None
    try:
        value = float(t)
    except ValueError:
        return None
    return -value if negative else value


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9&]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and (len(w) > 2 or w.isdigit())}


def content_tokens(text: str) -> set[str]:
    """Tokens relevant to ROW labels: periods/years belong to columns."""
    return {
        w
        for w in _tokenize(text)
        if not _YEAR_RE.fullmatch(w) and w not in _PERIOD_WORDS and w not in _MONTHS
    }


def period_tokens(text: str) -> set[str]:
    """Years, quarter markers and month names — matched against column labels."""
    tokens = set(_YEAR_RE.findall(text))
    tokens.update(f"q{m}" for m in _QUARTER_RE.findall(text))
    tokens.update(w for w in _tokenize(text) if w in _MONTHS)
    return tokens


# ------------------------------------------------------------ grid geometry


def _span_fill(row: Sequence[str | None]) -> list[str]:
    """Fill span-covered cells (None) from their origin; '' stays empty."""
    out: list[str] = []
    last = ""
    for cell in row:
        if cell is None:
            out.append(last)
        else:
            out.append(cell)
            last = cell
    return out


def _row_label(row: Sequence[str | None]) -> str:
    for cell in row:
        if cell and cell.strip():
            return cell.strip()
    return ""


def detect_header_rows(grid: Grid) -> int:
    """Rows before the first data row (label + at least one numeric cell)."""
    for i, row in enumerate(grid[:MAX_HEADER_ROWS]):
        label = (row[0] or "").strip() if row else ""
        has_number = any(c is not None and is_numeric_cell(c) for c in row[1:])
        if label and has_number:
            return i
    return min(MAX_HEADER_ROWS, max(len(grid) - 1, 0))


def column_labels(grid: Grid, n_header_rows: int) -> list[str]:
    width = max((len(r) for r in grid), default=0)
    parts: list[list[str]] = [[] for _ in range(width)]
    for row in grid[:n_header_rows]:
        filled = _span_fill(row)
        for c in range(min(len(filled), width)):
            value = filled[c].strip()
            if value and value not in parts[c]:
                parts[c].append(value)
    return [" | ".join(p) for p in parts]


def detect_unit(table: TableForQA, cell_text: str) -> str | None:
    if cell_text.strip().endswith("%"):
        return "percent"
    haystack = table.caption + " " + " ".join(
        c for row in table.grid[:2] for c in row if c
    )
    match = _UNIT_RE.search(haystack)
    if match:
        return f"USD {match.group(1).lower()}"
    return "USD" if "$" in cell_text else None


# ------------------------------------------------------- deterministic path


def answer_from_grid(question: str, table: TableForQA) -> TableAnswer | None:
    """Best (row, col) cell for the question, or None when nothing matches."""
    grid = table.grid
    if not grid:
        return None
    q_content = content_tokens(question)
    q_periods = period_tokens(question)
    if not q_content:
        return None

    header_rows = detect_header_rows(grid)
    labels = column_labels(grid, header_rows)

    # score data rows by label-token overlap
    scored_rows: list[tuple[float, float, int, str]] = []
    for r in range(header_rows, len(grid)):
        label = _row_label(grid[r])
        if not label:
            continue
        label_tokens = content_tokens(label)
        if not label_tokens:
            continue
        overlap = q_content & label_tokens
        if not overlap:
            continue
        coverage = len(overlap) / len(q_content)
        precision = len(overlap) / len(label_tokens)
        scored_rows.append((len(overlap) + precision, coverage, r, label))
    if not scored_rows:
        return None
    scored_rows.sort(reverse=True)
    _, coverage, row_idx, row_label = scored_rows[0]
    unique_best = len(scored_rows) == 1 or scored_rows[0][0] > scored_rows[1][0]

    # pick the value column by period match; leftmost (most recent) on ties
    row = grid[row_idx]
    best_col = -1
    best_col_score = -1.0
    for c, cell in enumerate(row):
        if cell is None or not is_numeric_cell(cell):
            continue
        label_lower = labels[c].lower() if c < len(labels) else ""
        col_score = 0.0
        for token in q_periods:
            if token in label_lower:
                col_score += 2.0
        col_score -= c * 0.01  # leftmost preference on ties
        if col_score > best_col_score:
            best_col_score = col_score
            best_col = c
    if best_col < 0:
        return None
    period_matched = best_col_score > 0
    if q_periods and not period_matched:
        # The question asks for a period this table doesn't have — near-miss.
        col_confidence = 0.0
    elif q_periods:
        col_confidence = 0.25
    else:
        col_confidence = 0.15

    cell_text = (row[best_col] or "").strip()
    col_label = labels[best_col] if best_col < len(labels) else ""
    confidence = min(
        1.0, 0.25 + 0.35 * coverage + col_confidence + (0.15 if unique_best else 0.0)
    )
    return TableAnswer(
        value=cell_text,
        unit=detect_unit(table, cell_text),
        source_cell=f"row {row_idx} ({row_label[:60]!r}) x col {best_col} ({col_label[:60]!r})",
        row=row_idx,
        col=best_col,
        table_id=table.table_id,
        page_id=table.page_id,
        confidence=round(confidence, 3),
    )


# ------------------------------------------------------------- LLM fallback


def _render_grid(grid: Grid, *, max_rows: int = 30, max_cols: int = 16) -> str:
    lines: list[str] = []
    for r, row in enumerate(grid[:max_rows]):
        cells = [(c if c is not None else "") for c in row[:max_cols]]
        lines.append(f"{r}: " + " | ".join(cells))
    return "\n".join(lines)


async def _llm_fallback(
    question: str, tables: Sequence[TableForQA], provider: LLMProvider
) -> tuple[TableAnswer | None, Usage]:
    blocks = [
        f"TABLE {i} (caption: {t.caption[:100] or 'none'}):\n{_render_grid(t.grid)}"
        for i, t in enumerate(tables)
    ]
    messages: list[Message] = [
        {
            "role": "system",
            "content": (
                "You locate the single table cell that answers a financial question. "
                'Reply ONLY with JSON: {"table": <index>, "row": <row>, "col": <col>} '
                'using the printed 0-based indices, or {"table": -1} if no cell answers it.'
            ),
        },
        {
            "role": "user",
            "content": "Question: " + question + "\n\n" + "\n\n".join(blocks),
        },
    ]
    try:
        completion = await provider.complete(messages, temperature=0.0, max_tokens=64)
    except Exception:
        return None, Usage()
    usage = completion.usage
    match = _JSON_RE.search(completion.text)
    if match is None:
        return None, usage
    try:
        payload = json.loads(match.group(0))
        t_idx, r_idx, c_idx = int(payload["table"]), int(payload["row"]), int(payload["col"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None, usage
    if not (0 <= t_idx < len(tables)):
        return None, usage
    table = tables[t_idx]
    grid = table.grid
    if not (0 <= r_idx < len(grid) and 0 <= c_idx < len(grid[r_idx])):
        return None, usage
    cell = grid[r_idx][c_idx]
    if cell is None or not is_numeric_cell(cell):
        return None, usage  # the model must point at a real numeric cell
    labels = column_labels(grid, detect_header_rows(grid))
    col_label = labels[c_idx] if c_idx < len(labels) else ""
    return (
        TableAnswer(
            value=cell.strip(),
            unit=detect_unit(table, cell),
            source_cell=(
                f"row {r_idx} ({_row_label(grid[r_idx])[:60]!r}) "
                f"x col {c_idx} ({col_label[:60]!r})"
            ),
            row=r_idx,
            col=c_idx,
            table_id=table.table_id,
            page_id=table.page_id,
            confidence=0.5,
        ),
        usage,
    )


# ---------------------------------------------------------------- entrypoint


async def answer_from_tables(
    question: str,
    tables: Sequence[TableForQA],
    *,
    provider: LLMProvider | None = None,
    max_answers: int = 3,
) -> tuple[list[TableAnswer], Usage]:
    """Deterministic matches across candidate tables; LLM fallback only when
    nothing clears MIN_CONFIDENCE and a provider is configured."""
    answers = [a for t in tables if (a := answer_from_grid(question, t)) is not None]
    answers.sort(key=lambda a: a.confidence, reverse=True)
    usage = Usage()
    needs_fallback = not answers or answers[0].confidence < MIN_CONFIDENCE
    if needs_fallback and provider is not None and tables:
        fallback, usage = await _llm_fallback(question, tables[:MAX_LLM_TABLES], provider)
        if fallback is not None:
            answers.insert(0, fallback)
    return answers[:max_answers], usage
