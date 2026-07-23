import { MonoValue } from "./MonoValue";

export type ConnState = "idle" | "streaming" | "done" | "error";

const label: Record<ConnState, string> = {
  idle: "READY",
  streaming: "STREAMING",
  done: "IDLE",
  error: "ERROR",
};

const dot: Record<ConnState, string> = {
  idle: "bg-shell-muted",
  streaming: "bg-stamp",
  done: "bg-shell-muted",
  error: "bg-caution",
};

// SSE connection indicator for the top bar. State-word is mono + a dot; not
// color-only (the word carries the meaning for colorblind users).
export function ConnectionStatus({ state }: { state: ConnState }) {
  return (
    <span className="inline-flex items-center gap-2" aria-live="polite">
      <span
        className={[
          "inline-block h-2 w-2 rounded-full",
          dot[state],
          state === "streaming" ? "animate-pulse" : "",
        ].join(" ")}
        aria-hidden="true"
      />
      <MonoValue className="text-[11px] tracking-widest text-shell-muted">
        {label[state]}
      </MonoValue>
    </span>
  );
}
