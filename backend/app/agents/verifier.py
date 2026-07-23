"""Verifier node — fail closed on numbers. Non-negotiable.

For every numeric claim in the draft answer:
  1. re-extract the authoritative values from the cited sources — table cells
     read back from the DB by (table_id, row, col), plus numbers present in
     the retrieved page text,
  2. compare, with unit/scale normalization and a small tolerance for rounded
     figures (exact when the printed digits match).

Any claim that cannot be traced to a source, or mismatches beyond tolerance,
sets verification.status = "failed". A failed verification triggers ONE repair
round-trip to synthesis (repair_count); if it still fails, the final answer is
a "cannot verify" message instead of the number — we never emit an unverified
figure.

The comparison core (`verify_numbers`) is a pure function so the planted-wrong
-number test needs neither DB nor LLM.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.state import AgentState, NodeFn, NodeUpdate
from app.db.models import ExtractedTable, Page
from app.schemas.query import (
    NodeTrace,
    VerificationCheck,
    VerificationResult,
)
from app.tables.table_qa import Grid, parse_cell_number

# Relative tolerance for scaled/rounded matches; exact when printed digits match.
REL_TOLERANCE = 0.02
MAX_REPAIRS = 1

_SCALE_WORDS: dict[str, float] = {
    "thousand": 1e3,
    "thousands": 1e3,
    "million": 1e6,
    "millions": 1e6,
    "billion": 1e9,
    "billions": 1e9,
    "trillion": 1e12,
    "trillions": 1e12,
}
# When a source's own scale is unknown, a claim may restate it at any of these.
_CANDIDATE_SCALES = (1.0, 1e3, 1e6, 1e9)

# A number token: optional $, digits with thousands separators, optional
# decimal, or a bare decimal; optional trailing %. Parentheses => negative.
_NUMBER_RE = re.compile(
    r"\(?\$?\s*-?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?%?"  # grouped thousands
    r"|\(?\$?\s*-?\d+\.\d+\)?%?"  # decimal
    r"|\(?\$?\s*-?\d+\)?%?"  # integer
)
_SCALE_AFTER_RE = re.compile(r"\s*(thousand|million|billion|trillion)s?\b", re.IGNORECASE)
# Citation markers like "[AAPL 10-K p.44]" or "p. 44" — their page numbers are
# not financial claims and must be stripped before extraction.
_CITATION_RE = re.compile(r"\[[^\]]*\]|p\.?\s*\d+", re.IGNORECASE)
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")


@dataclass(frozen=True, slots=True)
class SourceValue:
    """An authoritative number re-extracted from a cited source."""

    raw: float  # the number as printed in the source
    unit_scale: float | None  # known multiplier (1e6 for "millions"), else None
    origin: str  # human-readable provenance

    def candidate_bases(self) -> list[float]:
        if self.unit_scale is not None:
            return [self.raw * self.unit_scale, self.raw]
        return [self.raw * s for s in _CANDIDATE_SCALES]


@dataclass(frozen=True, slots=True)
class NumericClaim:
    text: str  # the claim as it appears in the draft
    raw: float  # printed value (sign-applied)
    scale: float  # scale word following it, else 1.0
    is_percent: bool

    @property
    def base(self) -> float:
        return self.raw * self.scale


@dataclass(slots=True)
class VerifyOutcome:
    status: str
    checks: list[VerificationCheck] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


# --------------------------------------------------------------- parsing


def _clean_number(token: str) -> tuple[float | None, bool]:
    """Parse a matched number token -> (value, is_percent)."""
    is_percent = token.rstrip().endswith("%")
    value = parse_cell_number(token)
    return value, is_percent


def extract_numeric_claims(text: str) -> list[NumericClaim]:
    """Financial numbers stated in the draft (years and citation page numbers
    excluded)."""
    stripped = _CITATION_RE.sub(" ", text)
    claims: list[NumericClaim] = []
    for match in _NUMBER_RE.finditer(stripped):
        token = match.group(0)
        value, is_percent = _clean_number(token)
        if value is None:
            continue
        # Skip bare years (e.g. "2025") — period references, not claims.
        digits = token.strip().lstrip("$(").rstrip(")%").strip()
        if not is_percent and "," not in digits and "." not in digits and _YEAR_RE.match(digits):
            continue
        tail = stripped[match.end() : match.end() + 12]
        scale_match = _SCALE_AFTER_RE.match(tail)
        scale = _SCALE_WORDS[scale_match.group(1).lower()] if scale_match else 1.0
        claims.append(
            NumericClaim(text=token.strip(), raw=value, scale=scale, is_percent=is_percent)
        )
    return claims


# ------------------------------------------------------------ comparison


def _values_match(claim: NumericClaim, source: SourceValue) -> bool:
    # Percentages compare on their face value, no scaling.
    if claim.is_percent:
        return _close(claim.raw, source.raw)
    # Exact printed-digit match (integers/rounded restatements).
    if _close(claim.raw, source.raw, tol=0.0):
        return True
    # Scale-normalized match against every plausible base of the source.
    return any(_close(claim.base, base) for base in source.candidate_bases())


def _close(a: float, b: float, *, tol: float = REL_TOLERANCE) -> bool:
    if b == 0:
        return abs(a) <= (tol or 1e-9)
    return abs(a - b) / abs(b) <= tol


def verify_numbers(
    draft: str, sources: Sequence[SourceValue]
) -> VerifyOutcome:
    """Pure fail-closed check: every numeric claim must match a source value."""
    claims = extract_numeric_claims(draft)
    if not claims:
        # No numbers to verify — narrative answer passes through, but labeled
        # so callers know no numeric verification occurred.
        return VerifyOutcome(status="unverified", reasons=["no numeric claims in answer"])

    checks: list[VerificationCheck] = []
    all_passed = True
    for claim in claims:
        match = next((s for s in sources if _values_match(claim, s)), None)
        if match is not None:
            checks.append(
                VerificationCheck(claim=claim.text, status="passed", found=match.origin)
            )
        else:
            all_passed = False
            nearest = _nearest(claim, sources)
            checks.append(
                VerificationCheck(
                    claim=claim.text,
                    status="unsupported",
                    found=nearest,
                )
            )
    if all_passed:
        return VerifyOutcome(status="verified", checks=checks)
    reasons = [
        f"claim {c.claim!r} could not be traced to a cited source"
        for c in checks
        if c.status != "passed"
    ]
    return VerifyOutcome(status="failed", checks=checks, reasons=reasons)


def _nearest(claim: NumericClaim, sources: Sequence[SourceValue]) -> str | None:
    best: tuple[float, str] | None = None
    for s in sources:
        for base in s.candidate_bases():
            if base == 0:
                continue
            diff = abs(claim.base - base) / abs(base)
            if best is None or diff < best[0]:
                best = (diff, s.origin)
    return best[1] if best is not None else None


CANNOT_VERIFY = (
    "I can't return a verified answer: one or more figures in the drafted "
    "response could not be traced to a cited source in the filings."
)


# ------------------------------------------------------------------ node


async def _sources_from_state(
    session: AsyncSession, state: AgentState
) -> list[SourceValue]:
    """Re-extract authoritative numbers from the cited sources: table cells
    (read back from the DB, not trusting the draft) and page text numbers."""
    sources: list[SourceValue] = []

    table_answers = state.get("table_answers") or []
    table_ids = list({ta.table_id for ta in table_answers})
    grids: dict[uuid.UUID, tuple[Grid, str]] = {}
    if table_ids:
        rows = (
            await session.execute(
                select(ExtractedTable.id, ExtractedTable.grid, ExtractedTable.caption).where(
                    ExtractedTable.id.in_(table_ids)
                )
            )
        ).all()
        grids = {r[0]: (r[1], r[2]) for r in rows}

    for ta in table_answers:
        entry = grids.get(ta.table_id)
        if entry is None:
            continue
        grid, _caption = entry
        if 0 <= ta.row < len(grid) and 0 <= ta.col < len(grid[ta.row]):
            cell = grid[ta.row][ta.col]
            value = parse_cell_number(cell) if cell else None
            if value is not None:
                sources.append(
                    SourceValue(
                        raw=value,
                        unit_scale=_unit_scale(ta.unit),
                        origin=f"table cell {ta.source_cell}",
                    )
                )

    # Numbers present in the retrieved page text broaden support for figures
    # quoted from prose rather than tables.
    candidates = state.get("candidates") or []
    page_ids = list({c.page_id for c in candidates})
    if page_ids:
        rows = (
            await session.execute(
                select(Page.id, Page.page_no, Page.text).where(Page.id.in_(page_ids))
            )
        ).all()
        for _pid, page_no, text in rows:
            for claim in extract_numeric_claims(text or ""):
                sources.append(
                    SourceValue(
                        raw=claim.raw,
                        unit_scale=None,
                        origin=f"page p.{page_no} text",
                    )
                )
    return sources


def _unit_scale(unit: str | None) -> float | None:
    if not unit:
        return None
    lowered = unit.lower()
    for word, scale in _SCALE_WORDS.items():
        if word in lowered:
            return scale
    return None


def make_verifier_node(sessionmaker: async_sessionmaker[AsyncSession]) -> NodeFn:
    async def verify(state: AgentState) -> NodeUpdate:
        started = time.perf_counter()
        draft = state.get("draft_answer", "")
        async with sessionmaker() as session:
            sources = await _sources_from_state(session, state)
        outcome = verify_numbers(draft, sources)
        result = VerificationResult(
            status=outcome.status, checks=outcome.checks, reasons=outcome.reasons
        )
        repair_count = state.get("repair_count", 0)

        trace = NodeTrace(
            name="verify", latency_ms=int((time.perf_counter() - started) * 1000)
        )
        update: NodeUpdate = {"verification": result, "trace": [trace]}

        if result.status == "failed" and repair_count < MAX_REPAIRS:
            # Route back to synthesis for one repair pass.
            update["repair_count"] = repair_count + 1
            update["final_answer"] = None
            return update

        if result.status == "failed":
            update["final_answer"] = CANNOT_VERIFY
        else:
            update["final_answer"] = draft
        return update

    return verify


def route_after_verify(state: AgentState) -> str:
    """Conditional edge: repair once on failure, else terminate."""
    verification = state.get("verification")
    repair_count = state.get("repair_count", 0)
    if (
        verification is not None
        and verification.status == "failed"
        and repair_count <= MAX_REPAIRS
        and state.get("final_answer") is None
    ):
        return "synthesis"
    return "__end__"
