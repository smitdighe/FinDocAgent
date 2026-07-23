import { PAGE_PT, type Citation } from "@/api/types";

// Draws the citation highlight over the page image. bbox is PDF points
// [x0, top, x1, bottom] on a US-Letter page (612 x 792 pt, top-left origin), so
// we position as a percentage of the page box — resolution/DPI independent.
// When there is no bbox, we highlight the whole page and surface the section
// label instead of guessing coordinates (spec §4).
interface Props {
  citation: Citation | null;
}

export function HighlightOverlay({ citation }: Props) {
  if (!citation) return null;

  if (!citation.bbox) {
    return (
      <div className="pointer-events-none absolute inset-0 border-2 border-stamp/70">
        <span className="mono absolute left-0 top-0 -translate-y-full bg-stamp px-1.5 py-0.5 text-[10px] uppercase text-paper">
          {citation.section ?? `page ${citation.page_no}`}
        </span>
      </div>
    );
  }

  const [x0, top, x1, bottom] = citation.bbox;
  const style = {
    left: `${(x0 / PAGE_PT.width) * 100}%`,
    top: `${(top / PAGE_PT.height) * 100}%`,
    width: `${((x1 - x0) / PAGE_PT.width) * 100}%`,
    height: `${((bottom - top) / PAGE_PT.height) * 100}%`,
  };

  return (
    <div
      className="pointer-events-none absolute border-2 border-stamp bg-stamp/15"
      style={style}
    >
      <span className="mono absolute left-0 top-0 -translate-y-full whitespace-nowrap bg-stamp px-1.5 py-0.5 text-[10px] uppercase text-paper">
        {citation.section ?? `p.${citation.page_no}`}
      </span>
    </div>
  );
}
