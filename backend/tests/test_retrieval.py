"""MaxSim literal builder, RRF fusion, filters — plus an opt-in DB roundtrip."""

import uuid

import numpy as np
import pytest

from app.retrieval.hybrid import reciprocal_rank_fusion
from app.retrieval.maxsim import maxsim_distance_expr, multivector_literal
from app.retrieval.store import PageHit, _filter_clause
from app.schemas.query import QueryFilters
from tests.conftest import requires_integration

# ------------------------------------------------------------ literal builder


def test_multivector_literal_exact() -> None:
    literal = multivector_literal([[0.1, 0.2, 0.3], [1.0, 2.0, 3.0]], dim=3)
    assert literal == (
        "ARRAY['[0.100000,0.200000,0.300000]'::vector(3),"
        "'[1.000000,2.000000,3.000000]'::vector(3)]::vector(3)[]"
    )


def test_multivector_literal_rejects_bad_shapes() -> None:
    with pytest.raises(ValueError, match="2-D"):
        multivector_literal([0.1, 0.2, 0.3], dim=3)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="3-dim"):
        multivector_literal([[0.1, 0.2]], dim=3)
    with pytest.raises(ValueError, match="at least one"):
        multivector_literal(np.zeros((0, 3), dtype=np.float32), dim=3)


def test_multivector_literal_rejects_non_finite() -> None:
    bad = np.array([[np.nan, 0.0, 0.0]], dtype=np.float32)
    with pytest.raises(ValueError, match="non-finite"):
        multivector_literal(bad, dim=3)


def test_maxsim_distance_expr() -> None:
    assert maxsim_distance_expr("pe.embeddings", "ARRAY[]") == "pe.embeddings @# ARRAY[]"


# --------------------------------------------------------------------- rrf


def _hit(page: uuid.UUID, score: float, snippet: str = "") -> PageHit:
    return PageHit(
        page_id=page, filing_id=uuid.uuid4(), page_no=1, score=score, snippet=snippet
    )


def test_rrf_prefers_pages_in_both_lists() -> None:
    shared, only_a, only_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    list_a = [_hit(only_a, 0.9, "a"), _hit(shared, 0.5, "shared")]
    list_b = [_hit(only_b, 12.0), _hit(shared, 3.0)]
    fused = reciprocal_rank_fusion([list_a, list_b], top_k=3)
    assert fused[0].page_id == shared
    assert fused[0].snippet == "shared"  # metadata from first appearance
    assert {h.page_id for h in fused} == {shared, only_a, only_b}


def test_rrf_top_k_trim() -> None:
    hits = [_hit(uuid.uuid4(), float(i)) for i in range(10)]
    fused = reciprocal_rank_fusion([hits], top_k=4)
    assert len(fused) == 4
    assert fused[0].page_id == hits[0].page_id  # rank order preserved


# ----------------------------------------------------------------- filters


def test_filter_clause_empty() -> None:
    assert _filter_clause(None) == ("", {})
    assert _filter_clause(QueryFilters()) == ("", {})


def test_filter_clause_uppercases() -> None:
    where, params = _filter_clause(QueryFilters(ticker="aapl", form_type="10-k"))
    assert "f.ticker = :f_ticker" in where
    assert "f.form_type = :f_form" in where
    assert params == {"f_ticker": "AAPL", "f_form": "10-K"}


# -------------------------------------------------- integration: live vchord


@requires_integration
async def test_maxsim_and_fts_roundtrip() -> None:
    """Insert two pages with distinct random multi-vectors; the page whose own
    vectors are used as the query must rank first. Requires the docker DB
    migrated to head."""
    from datetime import date

    from app.config import get_settings
    from app.db.models import Filing, Page
    from app.db.session import get_sessionmaker
    from app.retrieval import store
    from app.retrieval.bm25 import fts_search

    rng = np.random.default_rng(7)
    vecs_a = rng.normal(size=(24, 128)).astype(np.float32)
    vecs_b = rng.normal(size=(24, 128)).astype(np.float32)

    sessionmaker = get_sessionmaker(get_settings())
    async with sessionmaker() as session:
        filing = Filing(
            ticker="TEST",
            cik="0000000001",
            company_name="Test Co",
            form_type="10-K",
            accession_no=f"test-{uuid.uuid4().hex[:12]}",
            filing_date=date(2026, 1, 1),
            source_url="https://example.com",
            status="extracted",
            page_count=2,
        )
        session.add(filing)
        await session.flush()
        page_a = Page(
            filing_id=filing.id, page_no=1, image_path="x.jpg",
            text="alpha revenue discussion with net sales figures",
        )
        page_b = Page(
            filing_id=filing.id, page_no=2, image_path="y.jpg",
            text="beta liquidity and capital resources",
        )
        session.add_all([page_a, page_b])
        await session.flush()
        await store.insert_page_embedding(session, page_a.id, vecs_a, model="test")
        await store.insert_page_embedding(session, page_b.id, vecs_b, model="test")
        await session.commit()

        try:
            hits = await store.maxsim_search(session, vecs_a, top_k=2)
            assert hits[0].page_id == page_a.id
            assert hits[0].score > hits[1].score

            fts_hits = await fts_search(session, "alpha revenue", top_k=5)
            assert any(h.page_id == page_a.id for h in fts_hits)
        finally:
            await session.delete(filing)  # cascade removes pages + embeddings
            await session.commit()
