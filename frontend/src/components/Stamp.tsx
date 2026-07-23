import type { ReactNode } from "react";

// Base stamped-rectangle primitive: sharp corners, 1px border, no shadow, mono
// label. Used by the agent trace stages and verification badges (spec §1
// signature element). Deliberately NOT rounded and NOT shadowed.
export type StampTone = "idle" | "active" | "done" | "stamp" | "caution" | "error";

interface StampProps {
  children: ReactNode;
  tone?: StampTone;
  /** render the left-to-right clip-path wipe on mount (a completing stage). */
  wipe?: boolean;
  className?: string;
  as?: "div" | "button" | "li";
  onClick?: () => void;
  title?: string;
  ariaLabel?: string;
}

const toneClasses: Record<StampTone, string> = {
  // shell-world tones (dark)
  idle: "border-shell-line text-shell-muted bg-transparent",
  active: "border-shell-text text-shell-text bg-shell-surface",
  done: "border-shell-text/60 text-shell-text bg-shell-surface",
  // strict accent roles
  stamp: "border-stamp text-stamp bg-stamp/10",
  caution: "border-caution text-caution bg-caution/10",
  error: "border-caution text-caution bg-transparent",
};

export function Stamp({
  children,
  tone = "idle",
  wipe = false,
  className = "",
  as = "div",
  onClick,
  title,
  ariaLabel,
}: StampProps) {
  const Tag = as;
  return (
    <Tag
      className={[
        "mono inline-flex items-center gap-2 border px-2.5 py-1 text-xs uppercase tracking-wider",
        "rounded-none select-none",
        toneClasses[tone],
        wipe ? "stamp-wipe" : "",
        onClick ? "cursor-pointer hover:brightness-110 transition" : "",
        className,
      ].join(" ")}
      onClick={onClick}
      title={title}
      aria-label={ariaLabel}
      {...(as === "button" ? { type: "button" as const } : {})}
    >
      {children}
    </Tag>
  );
}
