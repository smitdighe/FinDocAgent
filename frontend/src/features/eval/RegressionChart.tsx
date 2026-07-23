import { MonoValue } from "@/components/MonoValue";
import { formatDelta } from "@/lib/formatters";
import type { MetricDelta } from "@/api/types";

// Score deltas vs the prior run as a diverging bar chart around a zero axis.
// Bars are labeled with signed mono values so meaning survives without color.
interface Props {
  deltas: MetricDelta[];
}

const MAX = 0.2; // full-width bar magnitude for scaling

export function RegressionChart({ deltas }: Props) {
  const scored = deltas.filter((d) => d.delta !== null);
  if (scored.length === 0) {
    return (
      <p className="mono text-xs text-shell-muted">
        No prior run to compare — this is the first run for this gold version.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {scored.map((d) => {
        const value = d.delta ?? 0;
        const pct = Math.min(Math.abs(value) / MAX, 1) * 50; // half-width each side
        const positive = value >= 0;
        return (
          <div key={d.metric} className="flex items-center gap-3">
            <span className="mono w-40 shrink-0 text-[11px] text-shell-muted">
              {d.metric}
            </span>
            <div className="relative h-4 flex-1 border-x border-shell-line/50">
              {/* zero axis */}
              <div className="absolute inset-y-0 left-1/2 w-px bg-shell-line" />
              <div
                className={[
                  "absolute inset-y-0",
                  positive ? "bg-stamp/70" : "bg-caution/70",
                ].join(" ")}
                style={
                  positive
                    ? { left: "50%", width: `${pct}%` }
                    : { right: "50%", width: `${pct}%` }
                }
              />
            </div>
            <MonoValue
              className={["w-16 text-right text-[11px]", positive ? "text-stamp" : "text-caution"].join(" ")}
            >
              {formatDelta(value)}
            </MonoValue>
          </div>
        );
      })}
    </div>
  );
}
