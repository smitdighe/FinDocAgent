import { MonoValue } from "@/components/MonoValue";
import { formatUsd, formatMs, formatInt } from "@/lib/formatters";
import type { EvalRunDetail } from "@/api/types";

// Cost + latency for the run. The eval rollup exposes aggregate cost and p50/p95
// latency plus per-query cost/latency (see backend harness.rollup); the per-hop
// NodeTrace breakdown lives on the live /query path (rendered in AnswerPanel),
// not in the eval payload — so this panel reports what the run actually carries.
interface Props {
  run: EvalRunDetail;
}

function num(v: unknown, fallback = 0): number {
  return typeof v === "number" ? v : fallback;
}

export function CostLatencyPanel({ run }: Props) {
  const r = run.rollup;
  const costTotal = num(r.cost_usd_total);
  const p50 = num(r.latency_ms_p50);
  const p95 = num(r.latency_ms_p95);
  const nItems = num(r.n_items, run.per_query.length);

  const maxLatency = Math.max(
    1,
    ...run.per_query.map((q) => num(q.latency_ms)),
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Tile label="Total cost" value={formatUsd(costTotal)} />
        <Tile label="Latency p50" value={formatMs(p50)} />
        <Tile label="Latency p95" value={formatMs(p95)} />
        <Tile label="Items scored" value={formatInt(nItems)} />
      </div>

      {run.per_query.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          <span className="mono text-[10px] uppercase tracking-widest text-shell-muted">
            Per-query latency
          </span>
          {run.per_query.slice(0, 12).map((q, i) => {
            const latency = num(q.latency_ms);
            const cost = num(q.cost_usd);
            const width = (latency / maxLatency) * 100;
            const question = typeof q.question === "string" ? q.question : `item ${i + 1}`;
            return (
              <div key={i} className="flex items-center gap-2">
                <span className="w-48 shrink-0 truncate text-[11px] text-shell-muted" title={question}>
                  {question}
                </span>
                <div className="h-3 flex-1 bg-shell-surface">
                  <div className="h-full bg-shell-text/40" style={{ width: `${width}%` }} />
                </div>
                <MonoValue className="w-16 text-right text-[10px] text-shell-text">
                  {formatMs(latency)}
                </MonoValue>
                <MonoValue className="w-16 text-right text-[10px] text-shell-muted">
                  {formatUsd(cost)}
                </MonoValue>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1 border border-shell-line bg-shell-surface p-3">
      <span className="mono text-[10px] uppercase tracking-widest text-shell-muted">
        {label}
      </span>
      <MonoValue className="text-lg text-shell-text">{value}</MonoValue>
    </div>
  );
}
