"""Filings + page detail (the frontend citation viewer consumes these)."""

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from starlette.responses import Response

from app.deps import SessionDep, SettingsDep
from app.retrieval import store
from app.schemas.filing import FilingListOut, FilingOut, PageDetailOut, TableOut

router = APIRouter(tags=["filings"])


def page_image_key(accession_no: str, page_no: int) -> str:
    """Object-store key for a rendered page image (stable, forward-slash).

    Mirrors the on-disk layout written by ingestion (rasterize_pdf ->
    `{storage_dir}/filings/{accession_nodash}/pages/page_{n:04d}.jpg`) but
    keyed off the accession so it never depends on the local absolute path
    that happened to be recorded in `Page.image_path` at ingest time.
    """
    accession_nodash = accession_no.replace("-", "")
    return f"filings/{accession_nodash}/pages/page_{page_no:04d}.jpg"


@router.get("", response_model=FilingListOut)
async def list_filings(session: SessionDep) -> FilingListOut:
    rows = await store.list_filings_with_page_counts(session)
    items = [
        FilingOut.model_validate(filing).model_copy(update={"page_count": count})
        for filing, count in rows
    ]
    return FilingListOut(items=items, total=len(items))


@router.get("/{filing_id}/pages/{page_no}", response_model=PageDetailOut)
async def page_detail(filing_id: uuid.UUID, page_no: int, session: SessionDep) -> PageDetailOut:
    found = await store.get_page_detail(session, filing_id, page_no)
    if found is None:
        raise HTTPException(status_code=404, detail="filing or page not found")
    filing, page, tables = found
    return PageDetailOut(
        filing_id=filing.id,
        page_no=page.page_no,
        page_count=filing.page_count or 0,
        text=page.text,
        image_url=f"/filings/{filing.id}/pages/{page.page_no}/image",
        tables=[TableOut.model_validate(t) for t in tables],
    )


@router.get("/{filing_id}/pages/{page_no}/image")
async def page_image(
    filing_id: uuid.UUID, page_no: int, session: SessionDep, settings: SettingsDep
) -> Response:
    found = await store.get_page_detail(session, filing_id, page_no)
    if found is None:
        raise HTTPException(status_code=404, detail="filing or page not found")
    filing, page, _ = found
    # Prod: page JPEGs live in object storage (Render's disk is ephemeral).
    # Redirect to the public bucket URL; the browser's <img> follows it.
    if settings.image_public_base_url:
        key = page_image_key(filing.accession_no, page_no)
        return RedirectResponse(
            f"{settings.image_public_base_url}/{key}", status_code=307
        )
    # Dev: stream the file recorded at ingest time from the local disk.
    image_path = Path(page.image_path)
    if not await asyncio.to_thread(image_path.is_file):
        raise HTTPException(status_code=404, detail="page image missing from storage")
    return FileResponse(image_path, media_type="image/jpeg")
