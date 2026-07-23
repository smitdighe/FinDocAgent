"""Route-level invariants for the filings API."""

from app.api.routes.filings import page_image_key


def test_page_image_key_matches_ondisk_layout() -> None:
    # Must equal `{accession_nodash}` + the rasterize_pdf filename pattern
    # (page_{n:04d}.jpg), or the prod redirect misses the uploaded object.
    assert (
        page_image_key("0000320193-25-000079", 1)
        == "filings/000032019325000079/pages/page_0001.jpg"
    )
    assert (
        page_image_key("0000320193-25-000079", 85)
        == "filings/000032019325000079/pages/page_0085.jpg"
    )
