import { useMemo } from "react";
import type { Filing } from "@/api/types";
import { formatDate } from "@/lib/formatters";

// Ticker + filing pickers. "All tickers" leaves the query unscoped; picking a
// ticker then a specific filing narrows the query filters and sets the viewer
// default. Rendered on the dark shell.
interface Props {
  filings: Filing[];
  loading: boolean;
  selectedTicker: string | null;
  selectedFilingId: string | null;
  onTickerChange: (ticker: string | null) => void;
  onFilingChange: (filingId: string | null) => void;
}

const selectClass =
  "mono w-full appearance-none rounded-none border border-shell-line bg-shell-surface px-2 py-1.5 text-sm text-shell-text focus:border-shell-text disabled:opacity-50";

export function TickerFilingSelector({
  filings,
  loading,
  selectedTicker,
  selectedFilingId,
  onTickerChange,
  onFilingChange,
}: Props) {
  const tickers = useMemo(
    () => Array.from(new Set(filings.map((f) => f.ticker))).sort(),
    [filings],
  );

  const filingsForTicker = useMemo(
    () =>
      selectedTicker
        ? filings
            .filter((f) => f.ticker === selectedTicker)
            .sort((a, b) => b.filing_date.localeCompare(a.filing_date))
        : [],
    [filings, selectedTicker],
  );

  return (
    <div className="grid grid-cols-2 gap-2">
      <label className="flex flex-col gap-1">
        <span className="mono text-[10px] uppercase tracking-widest text-shell-muted">
          Ticker
        </span>
        <select
          className={selectClass}
          value={selectedTicker ?? ""}
          disabled={loading}
          onChange={(e) => {
            const v = e.target.value || null;
            onTickerChange(v);
            onFilingChange(null);
          }}
        >
          <option value="">All tickers</option>
          {tickers.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className="mono text-[10px] uppercase tracking-widest text-shell-muted">
          Filing
        </span>
        <select
          className={selectClass}
          value={selectedFilingId ?? ""}
          disabled={loading || !selectedTicker}
          onChange={(e) => onFilingChange(e.target.value || null)}
        >
          <option value="">
            {selectedTicker ? "Latest / any" : "Pick a ticker first"}
          </option>
          {filingsForTicker.map((f) => (
            <option key={f.id} value={f.id}>
              {f.form_type} · {formatDate(f.filing_date)}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
