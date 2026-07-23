"""Metric computation: faithfulness, answer relevancy, context precision.

We adopt the RAGAS metric *triad* (the spec's three required metrics) but
implement them deterministically against the versioned gold set rather than
via an LLM judge. Rationale (see README): eval must run in CI without a paid
judge, and every score must be reproducible so regression deltas mean
something. Ground-truth anchoring (expected answer + expected source page)
also makes these stricter than self-consistency judging for a factual QA task.

Definitions used here:
- context_precision : did retrieval surface the gold source page, ranked high?
  Reciprocal rank of the expected page within the retrieved candidate pages.
  (Items without a known page are excluded from this metric.)
- faithfulness      : is the answer grounded / not hallucinated? Driven by the
  verifier — "verified" numeric answers and cited narrative answers score 1.0;
  a "failed" (blocked) answer scores 0.0.
- answer_relevancy  : does the answer actually deliver what was asked? Numeric
  items: the expected figure appears in the answer within tolerance. Narrative
  items: token-recall of the expected answer's content words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.eval import GoldItem
from app.schemas.query import Candidate, VerificationResult
from app.tables.table_qa import parse_cell_number

NUMERIC_REL_TOLERANCE = 0.01

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "the a an of in for on to and or by at as is are was were be it its their "
    "this that with from company companys yes no does do did which what".split()
)


@dataclass(frozen=True, slots=True)
class ItemScore:
    item_id: str
    type: str
    faithfulness: float
    answer_relevancy: float
    context_precision: float | None  # None when the item has no gold page
    answer_correct: bool


def _content_words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS and len(w) > 2}


def numeric_answer_matches(expected: str, answer: str) -> bool:
    """True if the expected figure appears in the answer within tolerance."""
    target = parse_cell_number(expected)
    if target is None:
        return expected.strip() in answer
    for token in re.findall(r"\(?\$?-?[\d,]+(?:\.\d+)?\)?%?", answer):
        value = parse_cell_number(token)
        if value is None:
            continue
        if target == 0:
            if abs(value) < 1e-9:
                return True
        elif abs(value - target) / abs(target) <= NUMERIC_REL_TOLERANCE:
            return True
    return False


def narrative_recall(expected: str, answer: str) -> float:
    """Fraction of the expected answer's content words present in the answer."""
    expected_words = _content_words(expected)
    if not expected_words:
        return 1.0 if answer.strip() else 0.0
    answer_words = _content_words(answer)
    hits = len(expected_words & answer_words)
    return hits / len(expected_words)


def context_precision_rr(expected_page: int | None, candidates: list[Candidate]) -> float | None:
    """Reciprocal rank of the expected source page in retrieved candidates."""
    if expected_page is None:
        return None
    for rank, cand in enumerate(candidates, start=1):
        if cand.page_no == expected_page:
            return 1.0 / rank
    return 0.0


def faithfulness_score(
    verification: VerificationResult, answer: str, has_citations: bool
) -> float:
    if verification.status == "failed":
        return 0.0
    if verification.status == "verified":
        return 1.0
    # unverified = narrative with no numeric claims: grounded iff it cites.
    return 1.0 if has_citations else 0.5


def score_item(
    item: GoldItem,
    answer: str,
    verification: VerificationResult,
    candidates: list[Candidate],
    n_citations: int,
) -> ItemScore:
    if item.type == "numeric":
        correct = numeric_answer_matches(item.expected_answer, answer)
        relevancy = 1.0 if correct else 0.0
    else:
        recall = narrative_recall(item.expected_answer, answer)
        correct = recall >= 0.5
        relevancy = recall
    return ItemScore(
        item_id=item.id,
        type=item.type,
        faithfulness=faithfulness_score(verification, answer, n_citations > 0),
        answer_relevancy=relevancy,
        context_precision=context_precision_rr(item.expected_source_page, candidates),
        answer_correct=correct,
    )


def aggregate(scores: list[ItemScore]) -> dict[str, float]:
    if not scores:
        return {
            "faithfulness": 0.0,
            "answer_relevancy": 0.0,
            "context_precision": 0.0,
            "answer_accuracy": 0.0,
            "n_scored": 0.0,
        }
    cp = [s.context_precision for s in scores if s.context_precision is not None]
    return {
        "faithfulness": round(sum(s.faithfulness for s in scores) / len(scores), 4),
        "answer_relevancy": round(sum(s.answer_relevancy for s in scores) / len(scores), 4),
        "context_precision": round(sum(cp) / len(cp), 4) if cp else 0.0,
        "answer_accuracy": round(sum(1 for s in scores if s.answer_correct) / len(scores), 4),
        "n_scored": float(len(scores)),
    }
