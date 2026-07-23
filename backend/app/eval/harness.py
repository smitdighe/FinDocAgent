"""Eval runner: load gold set -> run the full pipeline per item -> score ->
persist an EvalRun -> compute regression deltas vs. the previous run.

Runs the SAME graph the API serves (run_query_traced), so a run reflects the
real pipeline. Only verified gold rows are scored; drafts are excluded.
"""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.graph import build_graph
from app.agents.run import run_query_traced
from app.config import Settings
from app.db.models import EvalRun
from app.db.session import get_sessionmaker
from app.deps import get_optional_encoder, get_optional_provider
from app.eval.metrics import ItemScore, aggregate, score_item
from app.schemas.eval import EvalRunDetail, EvalRunOut, GoldItem, MetricDelta
from app.schemas.query import Candidate, QueryFilters, QueryRequest

GOLD_DIR = Path(__file__).parent / "gold"
METRIC_KEYS = ("faithfulness", "answer_relevancy", "context_precision", "answer_accuracy")


def gold_path(version: str) -> Path:
    return GOLD_DIR / f"gold_{version}.jsonl"


def load_gold(version: str, *, verified_only: bool = True) -> list[GoldItem]:
    path = gold_path(version)
    items: list[GoldItem] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = GoldItem.model_validate(json.loads(line))
        if verified_only and not item.verified:
            continue
        items.append(item)
    return items


def _filters_from_ref(filing_ref: str) -> QueryFilters:
    """"AAPL 10-K" / "AAPL 10-K FY2025" -> ticker + form filters."""
    parts = filing_ref.split()
    ticker = parts[0].upper() if parts else None
    form = parts[1].upper() if len(parts) > 1 and "-" in parts[1] else None
    return QueryFilters(ticker=ticker, form_type=form)


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            cwd=Path(__file__).resolve().parents[2],
        )
        return out.stdout.strip()[:40]
    except Exception:
        return ""


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, round((pct / 100.0) * (len(ordered) - 1)))
    return ordered[idx]


async def _previous_run(
    session: AsyncSession, gold_version: str, exclude_id: uuid.UUID
) -> EvalRun | None:
    run: EvalRun | None = await session.scalar(
        select(EvalRun)
        .where(
            EvalRun.gold_version == gold_version,
            EvalRun.status == "completed",
            EvalRun.id != exclude_id,
        )
        .order_by(EvalRun.started_at.desc())
        .limit(1)
    )
    return run


def _deltas(current: dict[str, float], previous: dict[str, float] | None) -> list[MetricDelta]:
    deltas: list[MetricDelta] = []
    for key in METRIC_KEYS:
        cur = current.get(key, 0.0)
        prev = previous.get(key) if previous else None
        deltas.append(
            MetricDelta(
                metric=key,
                previous=prev,
                current=cur,
                delta=round(cur - prev, 4) if prev is not None else None,
            )
        )
    return deltas


async def run_eval(
    settings: Settings, *, gold_version: str = "v1", notes: str = ""
) -> EvalRunDetail:
    sessionmaker: async_sessionmaker[AsyncSession] = get_sessionmaker(settings)
    graph = build_graph(
        get_optional_provider(settings), sessionmaker, get_optional_encoder(settings)
    )
    items = load_gold(gold_version, verified_only=True)

    run_id = uuid.uuid4()
    started = time.perf_counter()
    scores: list[ItemScore] = []
    per_query: list[dict[str, object]] = []
    latencies: list[float] = []
    cost_total = 0.0

    for item in items:
        req = QueryRequest(query=item.question, filters=_filters_from_ref(item.filing_ref))
        t0 = time.perf_counter()
        response, state = await run_query_traced(graph, req)
        latency_ms = (time.perf_counter() - t0) * 1000
        latencies.append(latency_ms)
        cost_total += response.cost.cost_usd

        candidates: list[Candidate] = list(state.get("candidates") or [])
        item_score = score_item(
            item, response.answer, response.verification, candidates, len(response.citations)
        )
        scores.append(item_score)
        per_query.append(
            {
                **asdict(item_score),
                "question": item.question,
                "expected": item.expected_answer,
                "answer": response.answer,
                "verification": response.verification.status,
                "latency_ms": round(latency_ms, 1),
                "cost_usd": response.cost.cost_usd,
            }
        )

    metric_scores = aggregate(scores)
    rollup: dict[str, object] = {
        "cost_usd_total": round(cost_total, 8),
        "latency_ms_p50": round(_percentile(latencies, 50), 1),
        "latency_ms_p95": round(_percentile(latencies, 95), 1),
        "n_items": len(items),
        "per_query": per_query,
    }

    async with sessionmaker() as session:
        previous = await _previous_run(session, gold_version, run_id)
        prev_scores = dict(previous.scores) if previous else None
        eval_run = EvalRun(
            id=run_id,
            gold_version=gold_version,
            pipeline_git_sha=_git_sha(),
            status="completed",
            scores=metric_scores,
            rollup=rollup,
            notes=notes,
        )
        eval_run.finished_at = eval_run.started_at
        session.add(eval_run)
        await session.commit()
        await session.refresh(eval_run)

    _ = time.perf_counter() - started
    detail = EvalRunDetail.model_validate(eval_run, from_attributes=True)
    detail.per_query = per_query
    detail.regression_vs_previous = _deltas(metric_scores, prev_scores)
    return detail


async def list_runs(settings: Settings, *, limit: int = 50) -> list[EvalRunOut]:
    sessionmaker = get_sessionmaker(settings)
    async with sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    select(EvalRun).order_by(EvalRun.started_at.desc()).limit(limit)
                )
            )
            .scalars()
            .all()
        )
    return [EvalRunOut.model_validate(r, from_attributes=True) for r in rows]


async def get_run(settings: Settings, run_id: uuid.UUID) -> EvalRunDetail | None:
    sessionmaker = get_sessionmaker(settings)
    async with sessionmaker() as session:
        run = await session.get(EvalRun, run_id)
        if run is None:
            return None
        previous = await _previous_run(session, run.gold_version, run.id)
        prev_scores = dict(previous.scores) if previous else None
    detail = EvalRunDetail.model_validate(run, from_attributes=True)
    detail.per_query = list(run.rollup.get("per_query", [])) if run.rollup else []
    detail.regression_vs_previous = _deltas(dict(run.scores), prev_scores)
    return detail
