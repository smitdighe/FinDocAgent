"""Human-readable eval report: scores, regression deltas, cost/latency."""

from __future__ import annotations

from app.schemas.eval import EvalRunDetail


def format_report(run: EvalRunDetail) -> str:
    lines: list[str] = []
    lines.append(f"EvalRun {run.id}  gold={run.gold_version}  sha={run.pipeline_git_sha[:8]}")
    lines.append(f"status={run.status}  started={run.started_at:%Y-%m-%d %H:%M:%S}")
    lines.append("")
    lines.append("metric              score     delta vs prev")
    lines.append("-" * 46)
    deltas = {d.metric: d for d in run.regression_vs_previous}
    for key in ("faithfulness", "answer_relevancy", "context_precision", "answer_accuracy"):
        score = run.scores.get(key, 0.0)
        d = deltas.get(key)
        if d is None or d.delta is None:
            delta_str = "   (no prior)"
        else:
            arrow = "up" if d.delta > 0 else ("down" if d.delta < 0 else "==")
            delta_str = f"  {arrow} {d.delta:+.4f}"
        lines.append(f"{key:<18} {score:>6.4f}  {delta_str}")
    lines.append("")
    roll = run.rollup
    lines.append(
        f"n_items={roll.get('n_items', '?')}  "
        f"cost=${roll.get('cost_usd_total', 0)}  "
        f"latency_p50={roll.get('latency_ms_p50', 0)}ms  "
        f"latency_p95={roll.get('latency_ms_p95', 0)}ms"
    )
    return "\n".join(lines)
