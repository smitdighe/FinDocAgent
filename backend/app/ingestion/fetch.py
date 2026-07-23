"""Download filing primary documents into local storage (idempotent)."""

from pathlib import Path

from app.ingestion.edgar_client import EdgarClient, FilingMeta


def raw_document_path(storage_dir: Path, meta: FilingMeta) -> Path:
    # primaryDocument can contain a subpath (e.g. "xsl.../doc.htm"); flatten it.
    filename = meta.primary_document.split("/")[-1]
    return storage_dir / "raw" / meta.accession_nodash / filename


async def fetch_filing_document(
    client: EdgarClient, meta: FilingMeta, storage_dir: Path
) -> Path:
    """Fetch the filing's primary HTML document; reuses the local copy if
    already present and non-empty."""
    out = raw_document_path(storage_dir, meta)
    if out.exists() and out.stat().st_size > 0:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    content = await client.download(meta.primary_doc_url)
    out.write_bytes(content)
    return out
