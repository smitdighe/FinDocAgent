"""In-pipeline table models (persisted via db.models.ExtractedTable)."""

from pydantic import BaseModel, Field


class TableData(BaseModel):
    """A data table extracted from filing HTML, mapped onto rendered pages.

    grid: span-expanded cell matrix; None marks cells covered by a
    rowspan/colspan originating elsewhere.
    """

    table_index: int
    caption: str = ""
    grid: list[list[str | None]]
    n_rows: int
    n_cols: int
    page_no: int | None = None  # 1-based rendered page; None if unmapped
    bbox: tuple[float, float, float, float] | None = None  # PDF points, top-left origin
    anchor_texts: list[str] = Field(default_factory=list)
    match_confidence: float = 0.0
