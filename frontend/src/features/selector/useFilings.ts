import { useCallback, useEffect, useState } from "react";
import { listFilings } from "@/api/filings";
import type { Filing } from "@/api/types";

interface State {
  filings: Filing[];
  loading: boolean;
  error: string | null;
}

export interface UseFilings extends State {
  reload: () => void;
}

// Loads the filing corpus once for the ticker/filing selector and viewer.
export function useFilings(): UseFilings {
  const [state, setState] = useState<State>({
    filings: [],
    loading: true,
    error: null,
  });

  const load = useCallback((signal?: AbortSignal) => {
    setState((s) => ({ ...s, loading: true, error: null }));
    listFilings(signal)
      .then((res) =>
        setState({ filings: res.items, loading: false, error: null }),
      )
      .catch((err: unknown) => {
        if (signal?.aborted) return;
        setState({
          filings: [],
          loading: false,
          error: err instanceof Error ? err.message : "failed to load filings",
        });
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load]);

  return { ...state, reload: () => load() };
}
