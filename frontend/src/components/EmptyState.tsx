import type { ReactNode } from "react";

interface EmptyStateProps {
  title: string;
  hint?: ReactNode;
  icon?: ReactNode;
  paper?: boolean; // render on paper surface instead of shell
}

export function EmptyState({ title, hint, icon, paper = false }: EmptyStateProps) {
  return (
    <div
      className={[
        "flex h-full min-h-40 flex-col items-center justify-center gap-2 border border-dashed p-8 text-center",
        paper ? "border-paper-line text-paper-muted" : "border-shell-line text-shell-muted",
      ].join(" ")}
    >
      {icon}
      <p className="font-display text-lg">{title}</p>
      {hint ? <div className="max-w-sm text-sm opacity-80">{hint}</div> : null}
    </div>
  );
}
