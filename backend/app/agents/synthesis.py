"""Synthesis node.

Composes the answer from retrieved pages + exact table answers, with inline
citations. Every numeric claim must be grounded in an evidence item so the
verifier can trace it; the LLM is instructed accordingly, and the verifier is
the backstop that fails closed if it does not.

Works with or without an LLM:
- provider set   -> LLM synthesis over the evidence block.
- provider None  -> deterministic synthesis: state the top table answer (or,
  for narrative, the top page snippet) and cite it. This keeps the whole
  pipeline runnable with no API key.

On a verifier repair pass (repair_count > 0 with a failed verification), the
prompt carries the failed checks and instructs the model to correct or drop
the offending numbers.
"""

from __future__ import annotations

import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.state import AgentState, NodeFn, NodeUpdate
from app.db.models import ExtractedTable, Filing, Page
from app.llm.base import LLMProvider, Message, Usage
from app.observability.cost import usd_for_usage
from app.schemas.citation import Citation
from app.schemas.query import Candidate, NodeTrace, TableAnswer, VerificationResult

MAX_EVIDENCE_PAGES = 5
MAX_SNIPPET_CHARS = 700


class PageRef:
    """Resolved (filing, page) coordinates for a candidate page_id."""

    __slots__ = ("bbox", "filing_id", "form_type", "page_no", "section", "ticker")

    def __init__(
        self,
        filing_id: uuid.UUID,
        ticker: str,
        form_type: str,
        page_no: int,
    ) -> None:
        self.filing_id = filing_id
        self.ticker = ticker
        self.form_type = form_type
        self.page_no = page_no

    def label(self) -> str:
        return f"{self.ticker} {self.form_type} p.{self.page_no}"


async def _resolve_page_refs(
    session: AsyncSession, page_ids: list[uuid.UUID]
) -> dict[uuid.UUID, PageRef]:
    if not page_ids:
        return {}
    rows = (
        await session.execute(
            select(Page.id, Filing.id, Filing.ticker, Filing.form_type, Page.page_no)
            .join(Filing, Filing.id == Page.filing_id)
            .where(Page.id.in_(page_ids))
        )
    ).all()
    return {
        r[0]: PageRef(filing_id=r[1], ticker=r[2], form_type=r[3], page_no=int(r[4]))
        for r in rows
    }


async def _table_bboxes(
    session: AsyncSession, table_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[float, float, float, float] | None]:
    if not table_ids:
        return {}
    rows = (
        await session.execute(
            select(ExtractedTable.id, ExtractedTable.bbox).where(
                ExtractedTable.id.in_(table_ids)
            )
        )
    ).all()
    out: dict[uuid.UUID, tuple[float, float, float, float] | None] = {}
    for tid, bbox in rows:
        out[tid] = tuple(bbox) if bbox else None  # type: ignore[assignment]
    return out


def _format_evidence(
    table_answers: list[TableAnswer],
    candidates: list[Candidate],
    refs: dict[uuid.UUID, PageRef],
) -> str:
    lines: list[str] = []
    if table_answers:
        lines.append("TABLE VALUES (exact, from source cells):")
        for ta in table_answers:
            ref = refs.get(ta.page_id)
            loc = ref.label() if ref else "unknown page"
            unit = f" {ta.unit}" if ta.unit else ""
            lines.append(f"  - {ta.value}{unit}  [{loc}]  ({ta.source_cell})")
    lines.append("\nPAGE EXCERPTS:")
    for cand in candidates[:MAX_EVIDENCE_PAGES]:
        ref = refs.get(cand.page_id)
        loc = ref.label() if ref else f"p.{cand.page_no}"
        snippet = cand.source_snippet[:MAX_SNIPPET_CHARS].replace("\n", " ")
        lines.append(f"  [{loc}] {snippet}")
    return "\n".join(lines)


def _build_citations(
    used_table_answers: list[TableAnswer],
    candidates: list[Candidate],
    refs: dict[uuid.UUID, PageRef],
    bboxes: dict[uuid.UUID, tuple[float, float, float, float] | None],
) -> list[Citation]:
    citations: list[Citation] = []
    seen: set[tuple[uuid.UUID, int]] = set()
    for ta in used_table_answers:
        ref = refs.get(ta.page_id)
        if ref is None:
            continue
        key = (ref.filing_id, ref.page_no)
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            Citation(
                filing_id=ref.filing_id,
                page_no=ref.page_no,
                section="financial statements",
                bbox=bboxes.get(ta.table_id),
            )
        )
    # Include the top page even when no table answer drove it (narrative).
    for cand in candidates[:2]:
        ref = refs.get(cand.page_id)
        if ref is None:
            continue
        key = (ref.filing_id, ref.page_no)
        if key in seen:
            continue
        seen.add(key)
        citations.append(Citation(filing_id=ref.filing_id, page_no=ref.page_no))
    return citations


def _deterministic_answer(
    query: str,
    table_answers: list[TableAnswer],
    candidates: list[Candidate],
    refs: dict[uuid.UUID, PageRef],
) -> str:
    if table_answers:
        ta = table_answers[0]
        ref = refs.get(ta.page_id)
        loc = ref.label() if ref else "the cited filing"
        unit = f" {ta.unit}" if ta.unit else ""
        return f"{ta.value}{unit} [{loc}]."
    if candidates:
        ref = refs.get(candidates[0].page_id)
        loc = ref.label() if ref else f"p.{candidates[0].page_no}"
        snippet = candidates[0].source_snippet.strip()[:400]
        return f"Based on the retrieved filing: {snippet} [{loc}]"
    return "No relevant evidence was found in the ingested filings for this question."


def _repair_directive(verification: VerificationResult | None) -> str:
    if verification is None or verification.status != "failed":
        return ""
    failed = [c for c in verification.checks if c.status != "passed"]
    bullet = "\n".join(
        f"  - claim {c.claim!r}: {c.status}"
        + (f" (source shows {c.found})" if c.found else "")
        for c in failed
    )
    return (
        "\n\nA prior draft failed verification. Correct or REMOVE these "
        f"unverifiable numbers; do not restate them:\n{bullet}"
    )


def make_synthesis_node(
    sessionmaker: async_sessionmaker[AsyncSession],
    provider: LLMProvider | None,
) -> NodeFn:
    async def synthesize(state: AgentState) -> NodeUpdate:
        started = time.perf_counter()
        query = state["query"]
        candidates = state.get("candidates") or []
        table_answers = state.get("table_answers") or []
        usage = Usage()

        page_ids = list({c.page_id for c in candidates} | {t.page_id for t in table_answers})
        async with sessionmaker() as session:
            refs = await _resolve_page_refs(session, page_ids)
            bboxes = await _table_bboxes(session, [t.table_id for t in table_answers])

        if provider is not None:
            evidence = _format_evidence(table_answers, candidates, refs)
            directive = _repair_directive(state.get("verification"))
            messages: list[Message] = [
                {
                    "role": "system",
                    "content": (
                        "You answer questions about SEC filings using ONLY the evidence "
                        "provided. State every number exactly as it appears in the evidence "
                        "and cite it inline as [TICKER FORM p.N]. If the evidence does not "
                        "contain the answer, say so plainly. Never invent figures."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Question: {query}\n\nEVIDENCE:\n{evidence}{directive}",
                },
            ]
            try:
                completion = await provider.complete(messages, temperature=0.1, max_tokens=600)
                draft = completion.text.strip()
                usage = completion.usage
            except Exception as exc:  # fall back rather than fail the query
                draft = _deterministic_answer(query, table_answers, candidates, refs)
                return _finish(
                    draft, table_answers, candidates, refs, bboxes, usage, provider, started,
                    errors=[f"synthesis LLM unavailable, used deterministic answer: {exc}"],
                )
        else:
            draft = _deterministic_answer(query, table_answers, candidates, refs)

        return _finish(
            draft, table_answers, candidates, refs, bboxes, usage, provider, started, errors=[]
        )

    return synthesize


def _finish(
    draft: str,
    table_answers: list[TableAnswer],
    candidates: list[Candidate],
    refs: dict[uuid.UUID, PageRef],
    bboxes: dict[uuid.UUID, tuple[float, float, float, float] | None],
    usage: Usage,
    provider: LLMProvider | None,
    started: float,
    *,
    errors: list[str],
) -> NodeUpdate:
    citations = _build_citations(table_answers, candidates, refs, bboxes)
    trace = NodeTrace(
        name="synthesis",
        latency_ms=int((time.perf_counter() - started) * 1000),
        tokens_in=usage.tokens_in,
        tokens_out=usage.tokens_out,
        cost_usd=usd_for_usage(usage, provider.price) if provider else 0.0,
    )
    update: NodeUpdate = {
        "draft_answer": draft,
        "citations": citations,
        "trace": [trace],
    }
    if errors:
        update["errors"] = errors
    return update
