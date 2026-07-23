"""AgentState — the single source of truth threaded through the graph.

Graph flow (wired in phase 3, see graph.py):

    router -> retrieval (visual | bm25 | hybrid) [-> table if numeric/hybrid]
           -> synthesis -> verifier -> END

The verifier may route back to synthesis exactly once (repair pass, tracked
by `repair_count`); after that it must terminate — fail closed, never loop.

Component models live in app/schemas/query.py so the API layer and the graph
share one contract. Nodes are built by factories (make_*_node) that close
over their dependencies — provider, sessionmaker, encoder — so the graph
never touches SDKs or globals.
"""

from collections.abc import Awaitable, Callable
from operator import add
from typing import Annotated, TypedDict

from app.schemas.citation import Citation
from app.schemas.query import (
    Candidate,
    NodeTrace,
    QueryFilters,
    QueryType,
    RetrievalPath,
    TableAnswer,
    VerificationResult,
)


class _AgentStateRequired(TypedDict):
    query: str


class AgentState(_AgentStateRequired, total=False):
    filters: QueryFilters

    # router output
    query_type: QueryType
    retrieval_path: RetrievalPath

    # retrieval output
    candidates: list[Candidate]

    # table agent output
    table_answers: list[TableAnswer]

    # synthesis output
    draft_answer: str
    citations: list[Citation]

    # verifier output
    verification: VerificationResult
    final_answer: str | None
    repair_count: int

    # accounting: appended by every node (reducers make these append-only)
    trace: Annotated[list[NodeTrace], add]
    errors: Annotated[list[str], add]


# A node returns a partial state update; LangGraph merges it via reducers.
NodeUpdate = dict[str, object]
NodeFn = Callable[[AgentState], Awaitable[NodeUpdate]]
