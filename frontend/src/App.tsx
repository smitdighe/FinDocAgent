import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useFilings } from "@/features/selector/useFilings";
import { useQueryStream } from "@/features/query/useQueryStream";
import { QueryInput } from "@/features/query/QueryInput";
import { AgentTrace } from "@/features/query/AgentTrace";
import { AnswerPanel } from "@/features/query/AnswerPanel";
import { FilingViewer } from "@/features/viewer/FilingViewer";
import { ConnectionStatus } from "@/components/ConnectionStatus";
import { ErrorState } from "@/components/ErrorState";
import type { Citation, QueryFilters, SynthesisHop } from "@/api/types";

export function App() {
  const { filings, loading: filingsLoading, error: filingsError, reload } = useFilings();
  const stream = useQueryStream();

  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [selectedFilingId, setSelectedFilingId] = useState<string | null>(null);

  // The viewer can point at a different filing than the selector when a
  // citation from another filing is clicked.
  const [viewerFilingId, setViewerFilingId] = useState<string | null>(null);
  const [viewerPage, setViewerPage] = useState<number>(1);
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);

  const viewerFiling = useMemo(
    () => filings.find((f) => f.id === (viewerFilingId ?? selectedFilingId)) ?? null,
    [filings, viewerFilingId, selectedFilingId],
  );

  const draftPreview = useMemo(() => {
    const synth = stream.stages.find((s) => s.name === "synthesis");
    return (synth?.payload as SynthesisHop | null)?.draft_preview ?? null;
  }, [stream.stages]);

  const onSubmit = (query: string) => {
    const filters: QueryFilters = {};
    if (selectedTicker) filters.ticker = selectedTicker;
    if (selectedFilingId) filters.filing_id = selectedFilingId;
    setActiveCitation(null);
    stream.submit({ query, filters });
  };

  const onSelectCitation = (c: Citation) => {
    setActiveCitation(c);
    setViewerFilingId(c.filing_id);
    setViewerPage(c.page_no);
  };

  const onSelectFiling = (filingId: string | null) => {
    setSelectedFilingId(filingId);
    if (filingId) {
      setViewerFilingId(filingId);
      setViewerPage(1);
      setActiveCitation(null);
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-shell text-shell-text">
      {/* top bar */}
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-shell-line px-4 py-2.5">
        <div className="flex items-baseline gap-3">
          <span className="font-display text-lg">FinDocAgent</span>
          <span className="mono text-[10px] uppercase tracking-widest text-shell-muted">
            Filing room terminal
          </span>
        </div>
        <div className="flex items-center gap-4">
          <ConnectionStatus state={stream.status} />
          <Link
            to="/eval"
            className="mono text-xs uppercase tracking-widest text-shell-muted transition hover:text-shell-text"
          >
            Eval ›
          </Link>
        </div>
      </header>

      {filingsError ? (
        <div className="px-4 py-3">
          <ErrorState
            title="Backend unreachable"
            message={`Could not load filings: ${filingsError}. Check the API is running and VITE_API_BASE_URL is set.`}
            onRetry={reload}
          />
        </div>
      ) : null}

      {/* two worlds: shell (left) + paper (right) */}
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {/* LEFT — dark operational shell */}
        <section className="flex flex-col gap-5 border-b border-shell-line p-4 lg:w-[38%] lg:border-b-0 lg:border-r lg:overflow-y-auto">
          <QueryInput
            filings={filings}
            filingsLoading={filingsLoading}
            selectedTicker={selectedTicker}
            selectedFilingId={selectedFilingId}
            onTickerChange={setSelectedTicker}
            onFilingChange={onSelectFiling}
            onSubmit={onSubmit}
            streaming={stream.status === "streaming"}
            onStop={stream.reset}
          />

          <div className="flex flex-col gap-2">
            <h2 className="mono text-[10px] uppercase tracking-widest text-shell-muted">
              Agent trace
            </h2>
            <AgentTrace
              status={stream.status}
              stages={stream.stages}
              error={stream.error}
              onRetry={() => stream.lastRequest && stream.submit(stream.lastRequest)}
            />
          </div>

          <div className="flex flex-col gap-2">
            <h2 className="mono text-[10px] uppercase tracking-widest text-shell-muted">
              Answer
            </h2>
            <AnswerPanel
              status={stream.status}
              answer={stream.answer}
              draftPreview={draftPreview}
              activeCitation={activeCitation}
              onSelectCitation={onSelectCitation}
            />
          </div>
        </section>

        {/* RIGHT — paper document viewer */}
        <section className="min-h-0 flex-1 bg-paper p-4 text-ink lg:overflow-y-auto">
          <FilingViewer
            filing={viewerFiling}
            page={viewerPage}
            citation={activeCitation}
            onPageChange={(p) => {
              setViewerPage(p);
              setActiveCitation(null); // manual nav clears the highlight
            }}
          />
        </section>
      </div>
    </div>
  );
}
