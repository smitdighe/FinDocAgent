"""Table QA node.

For numeric/hybrid queries: pulls extracted tables from the candidate pages
(in candidate-rank order) and answers via tables/table_qa.py — deterministic
grid matching first, LLM fallback through the injected provider. Every
answer carries (table_id, row, col) provenance the verifier re-extracts.
"""

from __future__ import annotations

import time
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.state import AgentState, NodeFn, NodeUpdate
from app.db.models import ExtractedTable, Page
from app.llm.base import LLMProvider, Usage
from app.observability.cost import usd_for_usage
from app.schemas.query import NodeTrace, TableAnswer
from app.tables.table_qa import Grid, TableForQA, answer_from_tables

MAX_CANDIDATE_PAGES = 6
MAX_TABLES = 8


def make_table_node(
    sessionmaker: async_sessionmaker[AsyncSession],
    provider: LLMProvider | None,
) -> NodeFn:
    async def answer_tables_node(state: AgentState) -> NodeUpdate:
        started = time.perf_counter()
        candidates = state.get("candidates") or []
        answers: list[TableAnswer] = []
        usage = Usage()

        if candidates:
            rank = {c.page_id: i for i, c in enumerate(candidates[:MAX_CANDIDATE_PAGES])}
            async with sessionmaker() as session:
                rows = (
                    await session.execute(
                        select(ExtractedTable, Page.page_no)
                        .join(Page, Page.id == ExtractedTable.page_id)
                        .where(ExtractedTable.page_id.in_(list(rank)))
                    )
                ).all()
            tables = [
                TableForQA(
                    table_id=t.id,
                    page_id=t.page_id,
                    page_no=int(page_no),
                    caption=t.caption,
                    grid=cast(Grid, t.grid),
                    table_index=t.table_index,
                    rank=rank.get(t.page_id, len(rank)),
                )
                for t, page_no in rows
                if t.page_id is not None
            ]
            tables.sort(key=lambda t: (t.rank, t.table_index))
            answers, usage = await answer_from_tables(
                state["query"], tables[:MAX_TABLES], provider=provider
            )

        trace = NodeTrace(
            name="table",
            latency_ms=int((time.perf_counter() - started) * 1000),
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            cost_usd=usd_for_usage(usage, provider.price) if provider else 0.0,
        )
        return {"table_answers": answers, "trace": [trace]}

    return answer_tables_node
