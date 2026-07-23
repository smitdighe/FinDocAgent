import { useState, type FormEvent } from "react";
import { TickerFilingSelector } from "@/features/selector/TickerFilingSelector";
import type { Filing } from "@/api/types";

const EXAMPLES = [
  "What was total net sales in the most recent fiscal year?",
  "How did gross margin change year over year?",
  "What are the principal risk factors disclosed?",
  "What was net income and diluted EPS?",
];

interface Props {
  filings: Filing[];
  filingsLoading: boolean;
  selectedTicker: string | null;
  selectedFilingId: string | null;
  onTickerChange: (t: string | null) => void;
  onFilingChange: (id: string | null) => void;
  onSubmit: (query: string) => void;
  streaming: boolean;
  onStop: () => void;
}

export function QueryInput({
  filings,
  filingsLoading,
  selectedTicker,
  selectedFilingId,
  onTickerChange,
  onFilingChange,
  onSubmit,
  streaming,
  onStop,
}: Props) {
  const [text, setText] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const q = text.trim();
    if (q.length < 3) return;
    onSubmit(q);
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <TickerFilingSelector
        filings={filings}
        loading={filingsLoading}
        selectedTicker={selectedTicker}
        selectedFilingId={selectedFilingId}
        onTickerChange={onTickerChange}
        onFilingChange={onFilingChange}
      />

      <label className="flex flex-col gap-1">
        <span className="mono text-[10px] uppercase tracking-widest text-shell-muted">
          Question
        </span>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e);
          }}
          rows={3}
          placeholder="Ask about a figure, trend, or disclosure…"
          className="resize-none rounded-none border border-shell-line bg-shell-surface px-3 py-2 text-sm text-shell-text placeholder:text-shell-muted focus:border-shell-text"
        />
      </label>

      <div className="flex items-center gap-2">
        {streaming ? (
          <button
            type="button"
            onClick={onStop}
            className="mono border border-caution px-4 py-1.5 text-xs uppercase tracking-wider text-caution transition hover:bg-caution/10"
          >
            Stop
          </button>
        ) : (
          <button
            type="submit"
            disabled={text.trim().length < 3}
            className="mono border border-stamp bg-stamp px-4 py-1.5 text-xs uppercase tracking-wider text-paper transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Run query
          </button>
        )}
        <span className="mono text-[10px] text-shell-muted">⌘/Ctrl + Enter</span>
      </div>

      <div className="flex flex-col gap-1">
        <span className="mono text-[10px] uppercase tracking-widest text-shell-muted">
          Examples
        </span>
        <div className="flex flex-wrap gap-1.5">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => setText(ex)}
              className="rounded-none border border-shell-line px-2 py-1 text-left text-[11px] text-shell-muted transition hover:border-shell-text hover:text-shell-text"
            >
              {ex}
            </button>
          ))}
        </div>
      </div>
    </form>
  );
}
