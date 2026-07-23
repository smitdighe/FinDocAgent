"""Eval harness API contracts (phase 4 fills in the runner)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GoldItem(BaseModel):
    """One row of the versioned gold set (app/eval/gold/gold_v1.jsonl).

    `verified=False` rows are drafts awaiting human confirmation and are
    excluded from scoring. Expected numbers are never fabricated.
    """

    id: str
    question: str
    filing_ref: str  # accession number or "TICKER FORM FY", resolved by the harness
    expected_answer: str
    expected_source_page: int | None = None
    type: Literal["numeric", "narrative"]
    verified: bool = False


class EvalTriggerRequest(BaseModel):
    gold_version: str = "v1"
    notes: str = ""


class EvalRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    gold_version: str
    pipeline_git_sha: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    scores: dict[str, float]
    rollup: dict[str, object]


class MetricDelta(BaseModel):
    metric: str
    previous: float | None
    current: float
    delta: float | None


class EvalRunDetail(EvalRunOut):
    per_query: list[dict[str, object]] = Field(default_factory=list)
    regression_vs_previous: list[MetricDelta] = Field(default_factory=list)
