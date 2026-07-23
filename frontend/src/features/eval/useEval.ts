import { useCallback, useEffect, useState } from "react";
import { getEvalRun, listEvalRuns, runEval } from "@/api/eval";
import type { EvalRun, EvalRunDetail } from "@/api/types";

interface State {
  runs: EvalRun[];
  selected: EvalRunDetail | null;
  loadingList: boolean;
  loadingDetail: boolean;
  running: boolean;
  error: string | null;
}

export interface UseEval extends State {
  select: (runId: string) => void;
  trigger: () => void;
  reloadList: () => void;
}

// Drives the eval dashboard: run history, a selected run's detail, and the
// synchronous POST /eval/run trigger (blocks until the backend finishes — no
// progress stream, so we show a running state for the duration).
export function useEval(): UseEval {
  const [state, setState] = useState<State>({
    runs: [],
    selected: null,
    loadingList: true,
    loadingDetail: false,
    running: false,
    error: null,
  });

  const reloadList = useCallback((autoSelect = true) => {
    setState((s) => ({ ...s, loadingList: true, error: null }));
    listEvalRuns()
      .then((runs) => {
        setState((s) => ({ ...s, runs, loadingList: false }));
        if (autoSelect && runs.length > 0) {
          setState((s) => (s.selected ? s : { ...s, loadingDetail: true }));
          getEvalRun(runs[0].id)
            .then((detail) =>
              setState((s) => ({ ...s, selected: detail, loadingDetail: false })),
            )
            .catch(() => setState((s) => ({ ...s, loadingDetail: false })));
        }
      })
      .catch((err: unknown) =>
        setState((s) => ({
          ...s,
          loadingList: false,
          error: err instanceof Error ? err.message : "failed to load runs",
        })),
      );
  }, []);

  useEffect(() => {
    reloadList(true);
  }, [reloadList]);

  const select = useCallback((runId: string) => {
    setState((s) => ({ ...s, loadingDetail: true, error: null }));
    getEvalRun(runId)
      .then((detail) =>
        setState((s) => ({ ...s, selected: detail, loadingDetail: false })),
      )
      .catch((err: unknown) =>
        setState((s) => ({
          ...s,
          loadingDetail: false,
          error: err instanceof Error ? err.message : "failed to load run",
        })),
      );
  }, []);

  const trigger = useCallback(() => {
    setState((s) => ({ ...s, running: true, error: null }));
    runEval({})
      .then((detail) => {
        setState((s) => ({
          ...s,
          running: false,
          selected: detail,
          runs: [detail, ...s.runs.filter((r) => r.id !== detail.id)],
        }));
      })
      .catch((err: unknown) =>
        setState((s) => ({
          ...s,
          running: false,
          error: err instanceof Error ? err.message : "eval run failed",
        })),
      );
  }, []);

  return { ...state, select, trigger, reloadList: () => reloadList(false) };
}
