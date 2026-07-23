import { Link } from "react-router-dom";
import { useEval } from "./useEval";
import { ScoreCards } from "./ScoreCards";
import { RegressionChart } from "./RegressionChart";
import { RunHistoryTable } from "./RunHistoryTable";
import { CostLatencyPanel } from "./CostLatencyPanel";
import { ErrorState } from "@/components/ErrorState";
import { Skeleton } from "@/components/Skeleton";
import { MonoValue } from "@/components/MonoValue";
import { shortSha, formatDateTime } from "@/lib/formatters";

// Route: /eval. Regression tracking over the gold set.
export function EvalDashboard() {
  const {
    runs,
    selected,
    loadingList,
    loadingDetail,
    running,
    error,
    select,
    trigger,
    reloadList,
  } = useEval();

  return (
    <div className="min-h-screen bg-shell text-shell-text">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-shell-line px-5 py-3">
        <div className="flex items-baseline gap-3">
          <Link to="/" className="mono text-xs uppercase tracking-widest text-shell-muted hover:text-shell-text">
            ‹ Filing room
          </Link>
          <h1 className="font-display text-xl">Eval regression</h1>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={reloadList}
            className="mono border border-shell-line px-3 py-1.5 text-xs uppercase tracking-wider text-shell-muted transition hover:border-shell-text hover:text-shell-text"
          >
            Refresh
          </button>
          <button
            type="button"
            onClick={trigger}
            disabled={running}
            className="mono border border-stamp bg-stamp px-3 py-1.5 text-xs uppercase tracking-wider text-paper transition hover:brightness-110 disabled:opacity-50"
          >
            {running ? "Running…" : "Run eval"}
          </button>
        </div>
      </header>

      <main className="mx-auto flex max-w-6xl flex-col gap-6 px-5 py-6">
        {error ? <ErrorState message={error} onRetry={reloadList} /> : null}

        {running ? (
          <div className="border border-stamp/40 bg-stamp/5 p-4">
            <MonoValue className="text-sm text-stamp">
              Running gold set through the pipeline… this blocks until the
              backend finishes (no progress stream).
            </MonoValue>
          </div>
        ) : null}

        <section className="flex flex-col gap-3">
          <h2 className="font-display text-lg">Latest scores</h2>
          {loadingDetail && !selected ? (
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Skeleton className="h-24" />
              <Skeleton className="h-24" />
              <Skeleton className="h-24" />
              <Skeleton className="h-24" />
            </div>
          ) : selected ? (
            <>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-shell-muted">
                <span>
                  run <MonoValue className="text-shell-text">{shortSha(selected.id)}</MonoValue>
                </span>
                <span>
                  sha{" "}
                  <MonoValue className="text-shell-text">
                    {shortSha(selected.pipeline_git_sha)}
                  </MonoValue>
                </span>
                <span>
                  gold <MonoValue className="text-shell-text">{selected.gold_version}</MonoValue>
                </span>
                <span>
                  <MonoValue className="text-shell-text">
                    {formatDateTime(selected.started_at)}
                  </MonoValue>
                </span>
              </div>
              <ScoreCards run={selected} />
            </>
          ) : (
            <p className="mono text-sm text-shell-muted">
              No run selected. Trigger a run or pick one from the history below.
            </p>
          )}
        </section>

        {selected ? (
          <>
            <section className="flex flex-col gap-3">
              <h2 className="font-display text-lg">Regression vs previous</h2>
              <RegressionChart deltas={selected.regression_vs_previous} />
            </section>

            <section className="flex flex-col gap-3">
              <h2 className="font-display text-lg">Cost &amp; latency</h2>
              <CostLatencyPanel run={selected} />
            </section>
          </>
        ) : null}

        <section className="flex flex-col gap-3">
          <h2 className="font-display text-lg">Run history</h2>
          <RunHistoryTable
            runs={runs}
            loading={loadingList}
            selectedId={selected?.id ?? null}
            onSelect={select}
          />
        </section>
      </main>
    </div>
  );
}
