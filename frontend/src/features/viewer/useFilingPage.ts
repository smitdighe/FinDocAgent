import { useEffect, useState } from "react";
import { getPageDetail } from "@/api/filings";
import type { PageDetail } from "@/api/types";

interface State {
  detail: PageDetail | null;
  loading: boolean;
  error: string | null;
}

// Fetches a single rendered page's detail (text, image_url, tables, page_count)
// whenever the target (filingId, pageNo) changes.
export function useFilingPage(
  filingId: string | null,
  pageNo: number | null,
): State {
  const [state, setState] = useState<State>({
    detail: null,
    loading: false,
    error: null,
  });

  useEffect(() => {
    if (!filingId || !pageNo) {
      setState({ detail: null, loading: false, error: null });
      return;
    }
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    getPageDetail(filingId, pageNo, controller.signal)
      .then((detail) => setState({ detail, loading: false, error: null }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          detail: null,
          loading: false,
          error: err instanceof Error ? err.message : "failed to load page",
        });
      });
    return () => controller.abort();
  }, [filingId, pageNo]);

  return state;
}
