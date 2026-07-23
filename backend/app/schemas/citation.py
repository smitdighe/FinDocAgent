"""Citation contract: page-level references into OUR rendered pagination."""

import uuid

from pydantic import BaseModel, ConfigDict


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)

    filing_id: uuid.UUID
    page_no: int  # 1-based, rendered pagination
    section: str | None = None
    # PDF points, top-left origin: (x0, top, x1, bottom).
    # Pixels on the page image = value * dpi / 72.
    bbox: tuple[float, float, float, float] | None = None
