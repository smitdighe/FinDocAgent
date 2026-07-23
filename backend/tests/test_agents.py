"""Agent package: no-SDK rule, state shape, router, retrieval node, table QA."""

from __future__ import annotations

import ast
import uuid
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.retrieval import make_retrieval_node
from app.agents.router import classify_query, make_router_node
from app.agents.state import AgentState
from app.llm.base import Completion, Message, StreamChunk, TokenPrice, Usage
from app.retrieval.store import PageHit
from app.schemas.query import QueryFilters
from app.tables.table_qa import (
    Grid,
    TableForQA,
    answer_from_grid,
    answer_from_tables,
    column_labels,
    detect_header_rows,
    parse_cell_number,
)
from tests.conftest import requires_integration

AGENTS_DIR = Path(__file__).resolve().parents[1] / "app" / "agents"
FORBIDDEN_ROOTS = {"groq", "openai", "anthropic", "cohere", "mistralai", "google"}


class FakeProvider:
    """Protocol-compatible provider returning a canned completion."""

    name = "fake"
    model = "fake-1"
    price = TokenPrice(1.0, 2.0)

    def __init__(self, reply: str, *, raise_error: bool = False) -> None:
        self.reply = reply
        self.raise_error = raise_error
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> Completion:
        self.calls += 1
        if self.raise_error:
            raise RuntimeError("provider down")
        return Completion(
            text=self.reply, usage=Usage(100, 10), model=self.model, provider=self.name
        )

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta=self.reply, usage=Usage(100, 10))


# ------------------------------------------------------------------ ground rules


def test_agents_never_import_llm_sdks() -> None:
    for path in sorted(AGENTS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            for module in modules:
                root = module.split(".")[0]
                assert root not in FORBIDDEN_ROOTS, (
                    f"{path.name} imports {module!r} — agents must use the "
                    "LLMProvider abstraction via DI"
                )


def test_agent_state_minimal_and_fields() -> None:
    state: AgentState = {"query": "What was total net sales?"}
    assert state["query"]
    expected = {
        "query",
        "filters",
        "query_type",
        "retrieval_path",
        "candidates",
        "table_answers",
        "draft_answer",
        "citations",
        "verification",
        "final_answer",
        "repair_count",
        "trace",
        "errors",
    }
    assert expected <= set(AgentState.__annotations__)


# ------------------------------------------------------------------------ router


def test_classify_query_heuristics() -> None:
    assert classify_query("What was total net sales in fiscal 2025?")[0] == "numeric"
    assert classify_query("Summarize the main risk factors")[0] == "narrative"
    kind, _ = classify_query("How did revenue growth relate to the supply chain risks?")
    assert kind == "hybrid"
    kind, confidence = classify_query("Tell me about the filing")
    assert kind == "hybrid"  # no signal -> safe default
    assert confidence < 0.6


async def test_router_node_sets_type_path_and_trace() -> None:
    router = make_router_node(None)
    update = await router({"query": "What was total net sales in fiscal 2025?"})
    assert update["query_type"] == "numeric"
    assert update["retrieval_path"] == "hybrid"
    traces = cast(list[Any], update["trace"])
    assert traces[0].name == "router"
    assert traces[0].cost_usd == 0.0


async def test_router_llm_tie_break_used_when_unsure() -> None:
    provider = FakeProvider("narrative")
    router = make_router_node(provider)
    update = await router({"query": "Tell me about the filing"})
    assert provider.calls == 1
    assert update["query_type"] == "narrative"
    assert update["retrieval_path"] == "visual"
    traces = cast(list[Any], update["trace"])
    assert traces[0].tokens_in == 100
    assert traces[0].cost_usd > 0


async def test_router_survives_provider_failure() -> None:
    router = make_router_node(FakeProvider("x", raise_error=True))
    update = await router({"query": "Tell me about the filing"})
    assert update["query_type"] == "hybrid"  # heuristic fallback


async def test_router_skips_llm_when_confident() -> None:
    provider = FakeProvider("narrative")
    router = make_router_node(provider)
    update = await router({"query": "What was total net sales in fiscal 2025?"})
    assert provider.calls == 0
    assert update["query_type"] == "numeric"


# ---------------------------------------------------------------- retrieval node


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def _fake_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return cast(async_sessionmaker[AsyncSession], _FakeSession)


def _hit(page_no: int, score: float, snippet: str = "") -> PageHit:
    return PageHit(
        page_id=uuid.uuid4(),
        filing_id=uuid.uuid4(),
        page_no=page_no,
        score=score,
        snippet=snippet,
    )


async def test_retrieval_degrades_to_fts_without_encoder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fts_hits = [_hit(4, 0.9, "income statement"), _hit(9, 0.5, "md&a")]

    async def fake_fts(session: object, query: str, **kwargs: object) -> list[PageHit]:
        return fts_hits

    monkeypatch.setattr("app.agents.retrieval.fts_search", fake_fts)
    node = make_retrieval_node(_fake_sessionmaker(), encoder=None)
    state: AgentState = {"query": "total net sales 2025", "retrieval_path": "hybrid"}
    update = await node(state)

    candidates = cast(list[Any], update["candidates"])
    assert [c.page_no for c in candidates] == [4, 9]
    assert candidates[0].source_snippet == "income statement"
    errors = cast(list[str], update["errors"])
    assert any("no ColPali encoder" in e for e in errors)
    traces = cast(list[Any], update["trace"])
    assert traces[0].name == "retrieval"


# -------------------------------------------------------------------- table QA

# Shaped like Apple's consolidated statements of operations after span
# expansion (banner colspan row, dates row, section row, data rows).
OPS_GRID: Grid = [
    ["", "Years ended", None, None],
    ["", "September 27, 2025", "September 28, 2024", "September 30, 2023"],
    ["Net sales:", "", "", ""],
    ["Products", "$ 307,003", "$ 294,866", "$ 298,085"],
    ["Services", "109,158", "96,169", "85,200"],
    ["Total net sales", "416,161", "391,035", "383,285"],
    ["Net income", "112,010", "93,736", "96,995"],
]


def _ops_table(caption: str = "(In millions, except per-share amounts)") -> TableForQA:
    return TableForQA(
        table_id=uuid.uuid4(),
        page_id=uuid.uuid4(),
        page_no=44,
        caption=caption,
        grid=OPS_GRID,
    )


def test_parse_cell_number() -> None:
    assert parse_cell_number("$ 416,161") == 416161.0
    assert parse_cell_number("(1,234.5)") == -1234.5
    assert parse_cell_number("7.49") == 7.49
    assert parse_cell_number("12.3%") == 12.3
    assert parse_cell_number("n/a") is None


def test_header_detection_and_column_labels() -> None:
    header_rows = detect_header_rows(OPS_GRID)
    assert header_rows == 3  # first data row is "Products"
    labels = column_labels(OPS_GRID, header_rows)
    assert "September 27, 2025" in labels[1]
    assert "September 28, 2024" in labels[2]
    assert "Years ended" in labels[1]  # colspan text span-fills across columns


def test_answer_from_grid_total_net_sales_2025() -> None:
    answer = answer_from_grid("What was total net sales in fiscal 2025?", _ops_table())
    assert answer is not None
    assert answer.value == "416,161"
    assert answer.row == 5 and answer.col == 1
    assert "Total net sales" in answer.source_cell
    assert answer.unit == "USD millions"
    assert answer.confidence >= 0.5


def test_answer_from_grid_prior_year_column() -> None:
    answer = answer_from_grid("Net income in fiscal 2024", _ops_table())
    assert answer is not None
    assert answer.value == "93,736"
    assert answer.row == 6 and answer.col == 2


def test_answer_from_grid_no_match() -> None:
    assert answer_from_grid("dividends declared per share", _ops_table()) is None


async def test_llm_fallback_reads_value_from_grid() -> None:
    # Deterministic path finds nothing for this paraphrase; the fake LLM
    # points at a cell and the value comes from the stored grid.
    provider = FakeProvider('{"table": 0, "row": 6, "col": 1}')
    answers, usage = await answer_from_tables(
        "combined bottom line figure most recently", [_ops_table()], provider=provider
    )
    assert provider.calls == 1
    assert answers and answers[0].value == "112,010"
    assert answers[0].row == 6 and answers[0].col == 1
    assert usage.tokens_in == 100


async def test_llm_fallback_rejects_non_numeric_cell() -> None:
    provider = FakeProvider('{"table": 0, "row": 2, "col": 0}')  # "Net sales:"
    answers, _ = await answer_from_tables(
        "combined bottom line figure most recently", [_ops_table()], provider=provider
    )
    assert answers == []


async def test_no_llm_call_when_deterministic_is_confident() -> None:
    provider = FakeProvider('{"table": 0, "row": 6, "col": 1}')
    answers, _ = await answer_from_tables(
        "total net sales 2025", [_ops_table()], provider=provider
    )
    assert provider.calls == 0
    assert answers[0].value == "416,161"


# --------------------------------------------------- phase 2 DoD (integration)


@requires_integration
async def test_numeric_query_routes_to_table_path_with_source_cell() -> None:
    """Phase 2 DoD: a numeric query routes to the table path and returns a
    value with an exact source cell — against the live ingested corpus,
    FTS-only (no encoder), so it must pass even before embeddings exist."""
    from app.agents.table import make_table_node
    from app.config import get_settings
    from app.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker(get_settings())
    router = make_router_node(None)
    retrieve = make_retrieval_node(sessionmaker, encoder=None)
    tables = make_table_node(sessionmaker, provider=None)

    state: AgentState = {
        "query": "What was total net sales in 2025?",
        "filters": QueryFilters(ticker="AAPL", form_type="10-K"),
    }
    update = await router(state)
    assert update["query_type"] == "numeric"
    state.update(cast(Any, update))

    update = await retrieve(state)
    state.update(cast(Any, update))
    assert state["candidates"], "retrieval returned no candidate pages"

    update = await tables(state)
    state.update(cast(Any, update))
    answers = state["table_answers"]
    assert answers, "table QA returned no answers"
    values = [a.value.replace("$", "").strip() for a in answers]
    assert "416,161" in values, f"expected Apple FY2025 net sales, got {values}"
    top = answers[0]
    assert top.source_cell and top.row >= 0 and top.col >= 0
