"""Verifier tests — fail-closed on numbers is the phase-3 non-negotiable.

The core comparison is a pure function (verify_numbers) so the planted-wrong
-number case needs no DB or LLM.
"""

from __future__ import annotations

import pytest

from app.agents.verifier import (
    CANNOT_VERIFY,
    SourceValue,
    extract_numeric_claims,
    verify_numbers,
)


def _src(raw: float, unit_scale: float | None = None, origin: str = "table cell") -> SourceValue:
    return SourceValue(raw=raw, unit_scale=unit_scale, origin=origin)


# ---------------------------------------------------------- claim extraction


def test_extract_numeric_claims_basic() -> None:
    claims = extract_numeric_claims("Total net sales were $416,161 million in the period.")
    assert len(claims) == 1
    assert claims[0].raw == 416161.0
    assert claims[0].scale == 1_000_000.0
    assert claims[0].base == 416161.0 * 1e6


def test_extract_ignores_years_and_citations() -> None:
    claims = extract_numeric_claims(
        "In fiscal 2025 net income was 112,010 [AAPL 10-K p.44] (see p. 31)."
    )
    values = [c.raw for c in claims]
    assert 112010.0 in values
    assert 2025.0 not in values  # bare year excluded
    assert 44.0 not in values and 31.0 not in values  # citation page numbers excluded


def test_extract_handles_negatives_and_percent() -> None:
    claims = extract_numeric_claims("Other income was (321) and the tax rate was 16.2%.")
    assert any(c.raw == -321.0 for c in claims)
    assert any(c.is_percent and c.raw == 16.2 for c in claims)


# ---------------------------------------------------- verify: pass conditions


def test_verify_exact_match_passes() -> None:
    outcome = verify_numbers("Total net sales were 416,161.", [_src(416161.0, 1e6)])
    assert outcome.status == "verified"
    assert outcome.checks[0].status == "passed"


def test_verify_scaled_restatement_passes() -> None:
    # Draft expresses the value in billions; source cell is in millions.
    outcome = verify_numbers(
        "Total net sales were $416.2 billion.", [_src(416161.0, 1e6)]
    )
    assert outcome.status == "verified"


def test_verify_unknown_unit_multi_scale_passes() -> None:
    # Source scale unknown; draft restates printed digits scaled to billions.
    outcome = verify_numbers("Revenue of $416.16 billion.", [_src(416161.0, None)])
    assert outcome.status == "verified"


def test_verify_narrative_no_numbers_is_unverified() -> None:
    outcome = verify_numbers("The company faces supply-chain and regulatory risks.", [])
    assert outcome.status == "unverified"


# -------------------------------------------- verify: FAIL-CLOSED (the DoD)


def test_planted_wrong_number_is_blocked() -> None:
    """A drafted answer whose figure is NOT in any cited source must fail."""
    sources = [_src(416161.0, 1e6, origin="table cell 'Total net sales' x '2025'")]
    outcome = verify_numbers("Total net sales were $999,999 million.", sources)
    assert outcome.status == "failed"
    assert outcome.checks[0].status == "unsupported"
    assert outcome.reasons  # explains what could not be traced


def test_off_by_100x_is_blocked() -> None:
    # 4.2 billion vs a 416,161-million (=416 billion) source — a 100x error.
    outcome = verify_numbers("Net sales were $4.2 billion.", [_src(416161.0, 1e6)])
    assert outcome.status == "failed"


def test_one_bad_number_among_good_ones_fails_closed() -> None:
    sources = [_src(416161.0, 1e6), _src(112010.0, 1e6)]
    outcome = verify_numbers(
        "Net sales were 416,161 and net income was 500,000.", sources
    )
    assert outcome.status == "failed"
    statuses = {c.claim: c.status for c in outcome.checks}
    assert statuses["416,161"] == "passed"
    assert statuses["500,000"] == "unsupported"


def test_cannot_verify_message_is_distinct() -> None:
    assert "can't return a verified answer" in CANNOT_VERIFY


# ------------------------------------------------- node + graph (integration)


@pytest.mark.asyncio
async def test_verifier_node_blocks_wrong_number_via_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Node-level fail-closed: a planted wrong number routes to a repair pass,
    and if synthesis can't fix it, the final answer becomes 'cannot verify'.
    Uses fakes — no DB/LLM."""
    import uuid

    from app.agents.verifier import make_verifier_node, route_after_verify
    from app.schemas.query import TableAnswer

    tid, pid = uuid.uuid4(), uuid.uuid4()
    true_grid = [["Total net sales", "416,161", "391,035"]]

    class FakeSession:
        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def execute(self, stmt: object) -> object:
            # Return the stored grid for the table-id lookup; empty for pages.
            text = str(stmt).lower()

            class R:
                def __init__(self, rows: list[tuple[object, ...]]) -> None:
                    self._rows = rows

                def all(self) -> list[tuple[object, ...]]:
                    return self._rows

            if "tables" in text:
                return R([(tid, true_grid, "Statements of Operations")])
            return R([])

    def fake_sessionmaker() -> FakeSession:
        return FakeSession()

    ta = TableAnswer(
        value="416,161",
        unit="USD millions",
        source_cell="row 0 x col 1",
        row=0,
        col=1,
        table_id=tid,
        page_id=pid,
        confidence=1.0,
    )
    # Draft claims a number that does NOT match the re-extracted cell (416,161).
    state = {
        "query": "total net sales 2025",
        "draft_answer": "Total net sales were $500,000 million.",
        "table_answers": [ta],
        "candidates": [],
        "repair_count": 0,
        "trace": [],
    }
    verify = make_verifier_node(fake_sessionmaker)  # type: ignore[arg-type]
    update = await verify(state)  # type: ignore[arg-type]
    assert update["verification"].status == "failed"
    assert update["repair_count"] == 1
    assert update["final_answer"] is None
    # first failure routes back to synthesis for a repair pass
    state.update(update)  # type: ignore[arg-type]
    assert route_after_verify(state) == "synthesis"  # type: ignore[arg-type]

    # second pass: still wrong -> terminates with cannot-verify
    state["repair_count"] = 1
    update2 = await verify(state)  # type: ignore[arg-type]
    assert update2["final_answer"] == CANNOT_VERIFY
