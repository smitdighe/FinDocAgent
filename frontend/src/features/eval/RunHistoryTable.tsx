import { MonoValue } from "@/components/MonoValue";
import { Skeleton } from "@/components/Skeleton";
import { EmptyState } from "@/components/EmptyState";
import { formatDateTime, formatScore, shortSha } from "@/lib/formatters";
import type { EvalRun } from "@/api/types";

// Runs over time: git SHA, gold version, timestamp, headline scores. Rows are
// selectable to load full detail into the cards/chart.
interface Props {
  runs: EvalRun[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (runId: string) => void;
}

const COLS = ["faithfulness", "answer_relevancy", "context_precision", "answer_accuracy"];

export function RunHistoryTable({ runs, loading, selectedId, onSelect }: Props) {
  if (loading && runs.length === 0) {
    return (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    );
  }
  if (runs.length === 0) {
    return (
      <EmptyState
        title="No eval runs yet"
        hint="Trigger a run to score the pipeline against the gold set."
      />
    );
  }

  return (
    <div className="overflow-x-auto border border-shell-line">
      <table className="w-full border-collapse text-left text-xs">
        <thead>
          <tr className="border-b border-shell-line text-shell-muted">
            <th className="px-3 py-2 font-normal uppercase tracking-widest">When</th>
            <th className="px-3 py-2 font-normal uppercase tracking-widest">SHA</th>
            <th className="px-3 py-2 font-normal uppercase tracking-widest">Gold</th>
            {COLS.map((c) => (
              <th key={c} className="px-3 py-2 text-right font-normal uppercase tracking-widest">
                {c.split("_")[0]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const active = run.id === selectedId;
            return (
              <tr
                key={run.id}
                onClick={() => onSelect(run.id)}
                className={[
                  "cursor-pointer border-b border-shell-line/60 transition",
                  active ? "bg-stamp/10" : "hover:bg-shell-surface",
                ].join(" ")}
              >
                <td className="px-3 py-2">
                  <MonoValue className="text-shell-text">
                    {formatDateTime(run.started_at)}
                  </MonoValue>
                </td>
                <td className="px-3 py-2">
                  <MonoValue tone={active ? "stamp" : "default"} className="text-shell-text">
                    {shortSha(run.pipeline_git_sha)}
                  </MonoValue>
                </td>
                <td className="px-3 py-2">
                  <MonoValue className="text-shell-text">{run.gold_version}</MonoValue>
                </td>
                {COLS.map((c) => (
                  <td key={c} className="px-3 py-2 text-right">
                    <MonoValue className="text-shell-text">
                      {run.scores[c] !== undefined ? formatScore(run.scores[c], 3) : "—"}
                    </MonoValue>
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
