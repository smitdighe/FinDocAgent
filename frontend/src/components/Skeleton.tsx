interface SkeletonProps {
  className?: string;
  paper?: boolean;
}

// Low-key loading placeholder. Pulse is disabled under prefers-reduced-motion
// via the global rule in index.css.
export function Skeleton({ className = "", paper = false }: SkeletonProps) {
  return (
    <div
      className={[
        "animate-pulse",
        paper ? "bg-paper-line/60" : "bg-shell-line/70",
        className,
      ].join(" ")}
      aria-hidden="true"
    />
  );
}
