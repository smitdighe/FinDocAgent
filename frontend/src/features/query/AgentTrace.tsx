import { AgentTraceStage } from "./AgentTraceStage";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import type { StageState, StreamStatus } from "./useQueryStream";

// The signature element: the stamped chain-of-custody trace. Stages fill
// left-to-right as they complete (clip-path wipe in Stamp). On desktop it flows
// horizontally with arrows; on mobile it stacks vertically (spec §7).
interface Props {
  status: StreamStatus;
  stages: StageState[];
  error: string | null;
  onRetry?: () => void;
}

export function AgentTrace({ status, stages, error, onRetry }: Props) {
  if (status === "idle") {
    return (
      <EmptyState
        title="No trace yet"
        hint="Ask a question — each agent hop stamps in here as it completes."
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <ol className="flex flex-wrap items-start gap-x-1 gap-y-3">
        {stages.map((stage, i) => (
          <div key={stage.name} className="flex items-start gap-1">
            <AgentTraceStage stage={stage} index={i} />
            {i < stages.length - 1 ? (
              <span
                aria-hidden
                className="mono mt-1.5 select-none text-shell-line"
              >
                ›
              </span>
            ) : null}
          </div>
        ))}
      </ol>

      {status === "error" ? (
        <ErrorState
          title="Stream interrupted"
          message={error ?? "The agent trace stopped unexpectedly."}
          onRetry={onRetry}
        />
      ) : null}
    </div>
  );
}
