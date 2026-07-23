import { getJson, postJson } from "./client";
import type { EvalRun, EvalRunDetail, EvalTriggerRequest } from "./types";

// POST /eval/run is synchronous on the backend — it blocks until the run
// finishes and returns the full detail (no progress stream). The UI shows a
// loading state for the duration.
export function runEval(
  request: EvalTriggerRequest = {},
  signal?: AbortSignal,
): Promise<EvalRunDetail> {
  return postJson<EvalRunDetail>("/eval/run", request, signal);
}

export function listEvalRuns(signal?: AbortSignal): Promise<EvalRun[]> {
  return getJson<EvalRun[]>("/eval/runs", signal);
}

export function getEvalRun(
  runId: string,
  signal?: AbortSignal,
): Promise<EvalRunDetail> {
  return getJson<EvalRunDetail>(`/eval/runs/${runId}`, signal);
}
