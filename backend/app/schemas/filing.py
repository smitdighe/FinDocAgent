"""API models for filings and page detail (citation viewer contract)."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class FilingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticker: str
    cik: str
    company_name: str
    form_type: str
    accession_no: str
    filing_date: date
    period_end: date | None
    source_url: str
    status: str
    page_count: int | None
    ingested_at: datetime


class FilingListOut(BaseModel):
    items: list[FilingOut]
    total: int


class TableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    table_index: int
    caption: str
    n_rows: int
    n_cols: int
    grid: list[list[str | None]]
    bbox: list[float] | None


class PageDetailOut(BaseModel):
    filing_id: uuid.UUID
    page_no: int
    page_count: int
    text: str
    image_url: str
    tables: list[TableOut]
