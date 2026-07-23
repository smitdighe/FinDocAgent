import { pageImageUrl } from "@/api/filings";
import { MonoValue } from "@/components/MonoValue";

// Vertical strip of page thumbnails for multi-page jumps. Renders a windowed
// range around the current page so we don't request the whole filing at once.
interface Props {
  filingId: string;
  pageCount: number;
  currentPage: number;
  onSelect: (pageNo: number) => void;
}

const WINDOW = 6;

export function PageThumbnails({
  filingId,
  pageCount,
  currentPage,
  onSelect,
}: Props) {
  if (pageCount <= 1) return null;

  const start = Math.max(1, currentPage - WINDOW);
  const end = Math.min(pageCount, currentPage + WINDOW);
  const pages: number[] = [];
  for (let p = start; p <= end; p++) pages.push(p);

  return (
    <div className="flex flex-col gap-2 overflow-y-auto pr-1" aria-label="page thumbnails">
      {pages.map((p) => {
        const active = p === currentPage;
        return (
          <button
            key={p}
            type="button"
            onClick={() => onSelect(p)}
            aria-current={active ? "page" : undefined}
            className={[
              "group relative w-16 shrink-0 border transition",
              active ? "border-stamp" : "border-paper-line hover:border-ink/40",
            ].join(" ")}
          >
            <img
              src={pageImageUrl(filingId, p)}
              alt={`page ${p}`}
              loading="lazy"
              className="block w-full bg-paper"
            />
            <MonoValue
              className={[
                "absolute bottom-0 right-0 px-1 text-[9px]",
                active ? "bg-stamp text-paper" : "bg-paper/90 text-ink",
              ].join(" ")}
            >
              {p}
            </MonoValue>
          </button>
        );
      })}
    </div>
  );
}
