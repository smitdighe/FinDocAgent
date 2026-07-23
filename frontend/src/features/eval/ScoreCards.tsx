import { MonoValue } from "@/components/MonoValue";
import { formatScore, formatDelta, deltaArrow } from "@/lib/formatters";
import type { EvalRunDetail, MetricDelta } from "@/api/types";

// Faithfulness / answer relevancy / context precision (+ accuracy) with the
// current-vs-previous delta. Direction is a glyph AND a word, never color-only
// (colorblind-safe, spec §6).
const LABELS: Record<string, string> = {
  faithfulness: "Faithfulness",
  answer_relevancy: "Answer relevancy",
  context_precision: "Context precision",
  answer_accuracy: "Answer accuracy",
};
const ORDER = ["faithfulness", "answer_relevancy", "context_precision", "answer_accuracy"];

interface Props {
  run: EvalRunDetail;
}

export function ScoreCards({ run }: Props) {
  const deltas = new Map<string, MetricDelta>(
    run.regression_vs_previous.map((d) => [d.metric, d]),
  );

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {ORDER.map((key) => {
        const score = run.scores[key];
        if (score === undefined) return null;
        const d = deltas.get(key);
        const delta = d?.delta ?? null;
        const dir =
          delta === null || delta === 0 ? "flat" : delta > 0 ? "up" : "down";
        return (
          <div
            key={key}
            className="flex flex-col gap-2 border border-shell-line bg-shell-surface p-3"
          >
            <span className="mono text-[10px] uppercase tracking-widest text-shell-muted">
              {LABELS[key] ?? key}
            </span>
            <MonoValue className="text-2xl text-shell-text">
              {formatScore(score)}
            </MonoValue>
            <span
              className={[
                "mono text-[11px]",
                dir === "up"
                  ? "text-stamp"
                  : dir === "down"
                    ? "text-caution"
                    : "text-shell-muted",
              ].join(" ")}
              title={`change vs previous run (${dir})`}
            >
              {deltaArrow(delta)} {formatDelta(delta)}{" "}
              <span className="uppercase opacity-70">{dir}</span>
            </span>
          </div>
        );
      })}
    </div>
  );
}
