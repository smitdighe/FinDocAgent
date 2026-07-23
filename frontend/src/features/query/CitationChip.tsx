import { MonoValue } from "@/components/MonoValue";
import type { Citation } from "@/api/types";

// A citation marker. Stamp-red is reserved for exactly this + verification, per
// spec §1. Clicking selects the page in the FilingViewer (jump + highlight).
interface Props {
  citation: Citation;
  index: number;
  active?: boolean;
  onSelect: (citation: Citation) => void;
}

export function CitationChip({ citation, index, active = false, onSelect }: Props) {
  const section = citation.section?.trim();
  return (
    <button
      type="button"
      onClick={() => onSelect(citation)}
      aria-pressed={active}
      title={section ? `${section} — page ${citation.page_no}` : `page ${citation.page_no}`}
      className={[
        "mono inline-flex items-center gap-1.5 border px-2 py-0.5 text-xs transition",
        "rounded-none",
        active
          ? "border-stamp bg-stamp text-paper"
          : "border-stamp/70 text-stamp hover:bg-stamp/10",
      ].join(" ")}
    >
      <span aria-hidden className="opacity-70">
        ¶
      </span>
      <span className="uppercase tracking-wide">[{index + 1}]</span>
      <MonoValue className={active ? "text-paper" : "text-stamp"}>
        p.{citation.page_no}
      </MonoValue>
      {section ? (
        <span className="max-w-28 truncate font-ui text-[10px] normal-case opacity-80">
          {section}
        </span>
      ) : null}
    </button>
  );
}
