"""Gold set integrity + metric math + regression-delta logic.

The live scored run (needs the DB) is an opt-in integration test.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from app.eval.harness import _deltas, _filters_from_ref, _percentile, load_gold
from app.eval.metrics import (
    ItemScore,
    aggregate,
    context_precision_rr,
    narrative_recall,
    numeric_answer_matches,
    score_item,
)
from app.schemas.eval import GoldItem
from app.schemas.query import Candidate, VerificationResult
from tests.conftest import requires_integration

GOLD_PATH = Path(__file__).resolve().parents[1] / "app" / "eval" / "gold" / "gold_v1.jsonl"


# ------------------------------------------------------------------ gold set


def test_gold_file_exists_and_rows_validate() -> None:
    lines = [ln for ln in GOLD_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 30, "gold set should span 30-50 items"
    ids: set[str] = set()
    for line_no, line in enumerate(lines, 1):
        item = GoldItem.model_validate(json.loads(line))
        assert item.id and item.id not in ids, f"row {line_no}: missing/duplicate id"
        ids.add(item.id)
        assert item.expected_answer, f"row {line_no}: empty expected_answer"


def test_gold_has_verified_and_unverified_and_both_types() -> None:
    items = [
        GoldItem.model_validate(json.loads(ln))
        for ln in GOLD_PATH.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert any(i.verified for i in items) and any(not i.verified for i in items)
    assert any(i.type == "numeric" for i in items)
    assert any(i.type == "narrative" for i in items)


def test_load_gold_filters_unverified() -> None:
    verified = load_gold("v1", verified_only=True)
    every = load_gold("v1", verified_only=False)
    assert 0 < len(verified) < len(every)
    assert all(i.verified for i in verified)


def test_filters_from_ref() -> None:
    f = _filters_from_ref("AAPL 10-K")
    assert f.ticker == "AAPL" and f.form_type == "10-K"
    assert _filters_from_ref("MSFT").ticker == "MSFT"


# -------------------------------------------------------------------- metrics


def test_numeric_answer_matches_with_tolerance() -> None:
    assert numeric_answer_matches("416,161", "Total net sales were 416,161 [AAPL 10-K p.44].")
    assert numeric_answer_matches("7.49", "Basic EPS was $7.49.")
    assert not numeric_answer_matches("416,161", "Net income was 112,010.")


def test_narrative_recall() -> None:
    expected = "The price of the Company's stock is subject to volatility."
    assert narrative_recall(expected, "Apple's stock price is subject to volatility.") >= 0.5
    assert narrative_recall(expected, "Revenue grew this year.") < 0.5


def test_context_precision_reciprocal_rank() -> None:
    cands = [
        Candidate(page_id=uuid.uuid4(), filing_id=uuid.uuid4(), page_no=p, score=0.0)
        for p in (44, 55, 70)
    ]
    assert context_precision_rr(44, cands) == 1.0
    assert context_precision_rr(70, cands) == 1.0 / 3
    assert context_precision_rr(999, cands) == 0.0
    assert context_precision_rr(None, cands) is None


def test_score_item_numeric_correct() -> None:
    item = GoldItem(
        id="x", question="q", filing_ref="AAPL 10-K", expected_answer="416,161",
        expected_source_page=44, type="numeric", verified=True,
    )
    cands = [Candidate(page_id=uuid.uuid4(), filing_id=uuid.uuid4(), page_no=44, score=1.0)]
    s = score_item(
        item, "416,161 [AAPL 10-K p.44].", VerificationResult(status="verified"), cands, 1
    )
    assert s.answer_correct and s.answer_relevancy == 1.0
    assert s.faithfulness == 1.0 and s.context_precision == 1.0


def test_score_item_numeric_wrong_fails_faithfulness() -> None:
    item = GoldItem(
        id="x", question="q", filing_ref="AAPL 10-K", expected_answer="416,161",
        expected_source_page=44, type="numeric", verified=True,
    )
    s = score_item(item, "I can't verify this.", VerificationResult(status="failed"), [], 0)
    assert not s.answer_correct
    assert s.faithfulness == 0.0  # blocked answers are unfaithful


def test_aggregate_and_deltas() -> None:
    scores = [
        ItemScore("a", "numeric", 1.0, 1.0, 1.0, True),
        ItemScore("b", "numeric", 1.0, 0.0, 0.5, False),
        ItemScore("c", "narrative", 1.0, 0.8, None, True),
    ]
    agg = aggregate(scores)
    assert agg["faithfulness"] == 1.0
    assert agg["answer_accuracy"] == round(2 / 3, 4)
    assert agg["context_precision"] == round((1.0 + 0.5) / 2, 4)  # None excluded
    assert agg["n_scored"] == 3.0

    deltas = _deltas(agg, {"faithfulness": 0.8, "answer_relevancy": 0.5,
                           "context_precision": 0.5, "answer_accuracy": 0.5})
    by_metric = {d.metric: d for d in deltas}
    assert by_metric["faithfulness"].delta == round(1.0 - 0.8, 4)
    assert _deltas(agg, None)[0].delta is None  # no prior run


def test_percentile() -> None:
    assert _percentile([10, 20, 30, 40], 50) in (20.0, 30.0)
    assert _percentile([], 50) == 0.0


# ---------------------------------------------------- live scored run (DoD)


@requires_integration
async def test_eval_run_scores_and_regresses() -> None:
    """Phase 4 DoD: /eval/run scores the gold set and a second run produces a
    comparison vs the first (per-metric deltas). Needs the ingested corpus."""
    from app.config import get_settings
    from app.eval.harness import run_eval

    settings = get_settings()
    first = await run_eval(settings, gold_version="v1", notes="test-run-1")
    assert first.scores["n_scored"] >= 15
    # numeric Apple items answerable FTS-only should score well
    assert first.scores["answer_accuracy"] >= 0.6
    assert first.rollup["n_items"] >= 15

    second = await run_eval(settings, gold_version="v1", notes="test-run-2")
    assert second.regression_vs_previous
    faith = next(d for d in second.regression_vs_previous if d.metric == "faithfulness")
    assert faith.previous is not None  # compared against the first run
    assert faith.delta is not None
