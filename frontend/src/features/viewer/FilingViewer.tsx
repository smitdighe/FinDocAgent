import { useEffect, useState } from "react";
import { pageImageUrl } from "@/api/filings";
import { useFilingPage } from "./useFilingPage";
import { HighlightOverlay } from "./HighlightOverlay";
import { PageThumbnails } from "./PageThumbnails";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Skeleton } from "@/components/Skeleton";
import { MonoValue } from "@/components/MonoValue";
import type { Citation, Filing } from "@/api/types";

// The paper-toned document viewer: page image + citation highlight + page nav +
// thumbnail strip. Clicking a citation chip drives `filingId`/`page`/`citation`
// from the parent; internal nav (prev/next/thumbnail) clears the highlight.
interface Props {
  filing: Filing | null;
  page: number;
  citation: Citation | null;
  onPageChange: (pageNo: number) => void;
}

export function FilingViewer({ filing, page, citation, onPageChange }: Props) {
  const filingId = filing?.id ?? null;
  const { detail, loading, error } = useFilingPage(filingId, filing ? page : null);
  const [imgError, setImgError] = useState(false);

  useEffect(() => {
    setImgError(false);
  }, [filingId, page]);

  if (!filing) {
    return (
      <EmptyState
        paper
        title="No filing open"
        hint="Pick a ticker and filing, or click a citation chip to open the source page here."
      />
    );
  }

  const pageCount = detail?.page_count ?? filing.page_count ?? 0;
  const canPrev = page > 1;
  const canNext = pageCount > 0 && page < pageCount;

  return (
    <div className="flex h-full flex-col gap-3">
      {/* header: filing identity + page nav */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-paper-line pb-2">
        <div className="flex flex-col">
          <span className="font-display text-lg text-ink">
            {filing.ticker} · {filing.form_type}
          </span>
          <MonoValue className="text-[11px] text-paper-muted">
            {filing.accession_no}
          </MonoValue>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => canPrev && onPageChange(page - 1)}
            disabled={!canPrev}
            aria-label="previous page"
            className="mono border border-paper-line px-2 py-1 text-xs text-ink transition hover:border-ink disabled:opacity-30"
          >
            ‹
          </button>
          <label className="flex items-center gap-1">
            <span className="sr-only">page number</span>
            <input
              type="number"
              min={1}
              max={pageCount || undefined}
              value={page}
              onChange={(e) => {
                const n = Number(e.target.value);
                if (Number.isFinite(n) && n >= 1 && (!pageCount || n <= pageCount)) {
                  onPageChange(n);
                }
              }}
              className="mono w-14 rounded-none border border-paper-line bg-paper-surface px-1 py-1 text-center text-xs text-ink"
            />
            <MonoValue className="text-xs text-paper-muted">
              / {pageCount || "—"}
            </MonoValue>
          </label>
          <button
            type="button"
            onClick={() => canNext && onPageChange(page + 1)}
            disabled={!canNext}
            aria-label="next page"
            className="mono border border-paper-line px-2 py-1 text-xs text-ink transition hover:border-ink disabled:opacity-30"
          >
            ›
          </button>
        </div>
      </div>

      {/* body: thumbnails + page image with overlay */}
      <div className="flex min-h-0 flex-1 gap-3">
        {pageCount > 1 && filingId ? (
          <div className="hidden max-h-full w-16 shrink-0 sm:block">
            <PageThumbnails
              filingId={filingId}
              pageCount={pageCount}
              currentPage={page}
              onSelect={onPageChange}
            />
          </div>
        ) : null}

        <div className="min-h-0 flex-1 overflow-auto bg-paper-surface p-3">
          {error ? (
            <ErrorState paper message={error} />
          ) : loading && !detail ? (
            <Skeleton paper className="mx-auto aspect-[612/792] w-full max-w-2xl" />
          ) : imgError ? (
            <ErrorState
              paper
              title="Page image unavailable"
              message="The rendered image for this page is missing from storage."
            />
          ) : filingId ? (
            <figure className="relative mx-auto w-full max-w-2xl">
              <img
                src={pageImageUrl(filingId, page)}
                alt={`${filing.ticker} ${filing.form_type} page ${page}`}
                onError={() => setImgError(true)}
                className="block w-full border border-paper-line bg-paper shadow-sm"
              />
              <HighlightOverlay citation={citation} />
            </figure>
          ) : null}

          {detail?.tables && detail.tables.length > 0 ? (
            <p className="mono mx-auto mt-2 max-w-2xl text-[10px] text-paper-muted">
              {detail.tables.length} table(s) on this page
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
