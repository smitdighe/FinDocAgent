interface ErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  paper?: boolean;
}

export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
  paper = false,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={[
        "flex h-full min-h-32 flex-col items-center justify-center gap-3 border p-6 text-center",
        paper ? "border-caution/60 bg-caution/5 text-ink" : "border-caution/60 bg-caution/5 text-shell-text",
      ].join(" ")}
    >
      <p className="font-display text-lg text-caution">{title}</p>
      <p className="max-w-md text-sm opacity-90">{message}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mono border border-caution px-3 py-1 text-xs uppercase tracking-wider text-caution transition hover:bg-caution/10"
        >
          Retry
        </button>
      ) : null}
    </div>
  );
}
