import type { ReactNode } from "react";

// Enforces mono rendering for every numeric display in the app (spec §1 hard
// rule). Route dollar figures, page numbers, tickers, scores, timestamps and
// trace values through this so nothing leaks into a proportional font.
interface MonoValueProps {
  children: ReactNode;
  className?: string;
  /** stamp-red for citation markers / verified figures; amber for held. */
  tone?: "default" | "stamp" | "caution" | "muted";
  title?: string;
}

const toneClass: Record<NonNullable<MonoValueProps["tone"]>, string> = {
  default: "",
  stamp: "text-stamp",
  caution: "text-caution",
  muted: "opacity-70",
};

export function MonoValue({
  children,
  className = "",
  tone = "default",
  title,
}: MonoValueProps) {
  return (
    <span className={`mono ${toneClass[tone]} ${className}`} title={title}>
      {children}
    </span>
  );
}
