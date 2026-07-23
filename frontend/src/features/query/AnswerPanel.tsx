import { Fragment, type ReactNode } from "react";
import { MonoValue } from "@/components/MonoValue";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/Skeleton";
import { CitationChip } from "./CitationChip";
import { VerificationBadge } from "./VerificationBadge";
import type { Citation, QueryResponse } from "@/api/types";
import type { StreamStatus } from "./useQueryStream";
import { formatUsd, formatMs } from "@/lib/formatters";

// Financial figures: $-prefixed, grouped-thousands, decimals, or percentages.
// Deliberately does NOT match bare 1-2 digit ints (page refs like "p.44").
const FIGURE_RE =
  /\(?\$?\s*-?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?%?|\(?\$?\s*-?\d+\.\d+\)?%?|\$\s*-?\d+%?|\d+%/g;

/**
 * Render answer text with every figure in mono. When the answer is NOT
 * verified, figures are redacted to a pending stamp rather than shown raw —
 * the UI must not leak an unverified number even if it arrives in the payload
 * (spec §5, mirrors the backend fail-closed contract).
 */
function renderAnswer(text: string, verified: boolean): ReactNode {
  const out: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  FIGURE_RE.lastIndex = 0;
  let key = 0;
  while ((m = FIGURE_RE.exec(text)) !== null) {
    if (m.index > last) out.push(<Fragment key={key++}>{text.slice(last, m.index)}</Fragment>);
    const token = m[0].trim();
    if (verified) {
      out.push(
        <MonoValue key={key++} className="font-medium">
          {token}
        </MonoValue>,
      );
    } else {
      out.push(
        <span
          key={key++}
          className="mono inline-flex items-center gap-1 border border-caution/60 bg-caution/10 px-1 text-caution"
          title="Figure withheld — could not be verified against a cited source"
        >
          <span aria-hidden>▮▮▮</span>
          <span className="text-[10px] uppercase">held</span>
        </span>,
      );
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(<Fragment key={key++}>{text.slice(last)}</Fragment>);
  return out;
}

interface Props {
  status: StreamStatus;
  answer: QueryResponse | null;
  draftPreview?: string | null;
  activeCitation: Citation | null;
  onSelectCitation: (c: Citation) => void;
}

export function AnswerPanel({
  status,
  answer,
  draftPreview,
  activeCitation,
  onSelectCitation,
}: Props) {
  if (status === "idle") {
    return (
      <EmptyState
        title="Answer will appear here"
        hint="Verified figures render in stamp-red mono; unverifiable ones are withheld."
      />
    );
  }

  if (status === "streaming" && !answer) {
    return (
      <div className="flex flex-col gap-3">
        {draftPreview ? (
          <p className="text-sm leading-relaxed text-shell-muted">
            {draftPreview}
            <span className="ml-1 animate-pulse">▍</span>
          </p>
        ) : (
          <>
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </>
        )}
      </div>
    );
  }

  if (!answer) return null;

  const verified = answer.verification.status === "verified";

  return (
    <div className="flex flex-col gap-4">
      <VerificationBadge verification={answer.verification} />

      <div className="prose-none text-[15px] leading-relaxed text-shell-text">
        {renderAnswer(answer.answer, verified)}
      </div>

      {answer.citations.length > 0 ? (
        <div className="flex flex-col gap-2">
          <span className="mono text-[10px] uppercase tracking-widest text-shell-muted">
            Citations
          </span>
          <div className="flex flex-wrap gap-2">
            {answer.citations.map((c, i) => (
              <CitationChip
                key={`${c.filing_id}-${c.page_no}-${i}`}
                citation={c}
                index={i}
                active={
                  activeCitation?.filing_id === c.filing_id &&
                  activeCitation?.page_no === c.page_no
                }
                onSelect={onSelectCitation}
              />
            ))}
          </div>
        </div>
      ) : null}

      <dl className="flex flex-wrap gap-x-6 gap-y-1 border-t border-shell-line pt-3 text-[11px] text-shell-muted">
        <div className="flex gap-1">
          <dt className="uppercase tracking-widest">type</dt>
          <dd className="mono text-shell-text">{answer.query_type}</dd>
        </div>
        <div className="flex gap-1">
          <dt className="uppercase tracking-widest">cost</dt>
          <dd>
            <MonoValue className="text-shell-text">{formatUsd(answer.cost.cost_usd)}</MonoValue>
          </dd>
        </div>
        <div className="flex gap-1">
          <dt className="uppercase tracking-widest">latency</dt>
          <dd>
            <MonoValue className="text-shell-text">{formatMs(answer.cost.latency_ms)}</MonoValue>
          </dd>
        </div>
      </dl>
    </div>
  );
}
