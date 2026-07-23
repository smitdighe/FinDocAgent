import { useCallback, useRef, useState } from "react";
import { queryStream } from "@/api/query";
import type {
  ErrorHop,
  QueryRequest,
  QueryResponse,
  RetrievalHop,
  RouterHop,
  SynthesisHop,
  TableHop,
  VerifyHop,
} from "@/api/types";

export type StreamStatus = "idle" | "streaming" | "done" | "error";

// Canonical pipeline order. `table` only fires for numeric/hybrid queries; if
// it never arrives it resolves to "skipped" when the answer lands.
export const STAGE_ORDER = [
  "router",
  "retrieval",
  "table",
  "synthesis",
  "verify",
] as const;
export type StageName = (typeof STAGE_ORDER)[number];

export type StageStatus = "pending" | "active" | "done" | "skipped";

export type HopPayload =
  | RouterHop
  | RetrievalHop
  | TableHop
  | SynthesisHop
  | VerifyHop
  | null;

export interface StageState {
  name: StageName;
  status: StageStatus;
  payload: HopPayload;
}

export interface QueryStreamState {
  status: StreamStatus;
  stages: StageState[];
  answer: QueryResponse | null;
  error: string | null;
}

function initialStages(): StageState[] {
  return STAGE_ORDER.map((name) => ({ name, status: "pending", payload: null }));
}

const IDLE: QueryStreamState = {
  status: "idle",
  stages: initialStages(),
  answer: null,
  error: null,
};

export interface UseQueryStream extends QueryStreamState {
  submit: (request: QueryRequest) => void;
  reset: () => void;
  lastRequest: QueryRequest | null;
}

export function useQueryStream(): UseQueryStream {
  const [state, setState] = useState<QueryStreamState>(IDLE);
  const abortRef = useRef<AbortController | null>(null);
  const lastRequestRef = useRef<QueryRequest | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setState(IDLE);
  }, []);

  const submit = useCallback((request: QueryRequest) => {
    // Abort any in-flight stream before starting a new one (spec §3).
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    lastRequestRef.current = request;

    setState({
      status: "streaming",
      stages: initialStages().map((s, i) =>
        i === 0 ? { ...s, status: "active" } : s,
      ),
      answer: null,
      error: null,
    });

    const applyHop = (name: StageName, payload: HopPayload) => {
      setState((prev) => {
        const stages = prev.stages.map((s) =>
          s.name === name ? { ...s, status: "done" as StageStatus, payload } : s,
        );
        // Activate the next still-pending stage so the ticker shows progress.
        const idx = STAGE_ORDER.indexOf(name);
        for (let i = idx + 1; i < stages.length; i++) {
          if (stages[i].status === "pending") {
            stages[i] = { ...stages[i], status: "active" };
            break;
          }
        }
        return { ...prev, stages };
      });
    };

    queryStream(
      request,
      (msg) => {
        let data: unknown = null;
        try {
          data = msg.data ? JSON.parse(msg.data) : null;
        } catch {
          data = null;
        }
        switch (msg.event) {
          case "router":
          case "retrieval":
          case "table":
          case "synthesis":
          case "verify":
            applyHop(msg.event, data as HopPayload);
            break;
          case "answer":
            setState((prev) => ({
              ...prev,
              status: "done",
              answer: data as QueryResponse,
              // Any stage that never fired (e.g. table on a narrative query)
              // resolves to "skipped", not left spinning.
              stages: prev.stages.map((s) =>
                s.status === "done" ? s : { ...s, status: "skipped" },
              ),
            }));
            break;
          case "error":
            setState((prev) => ({
              ...prev,
              status: "error",
              error: (data as ErrorHop)?.detail ?? "stream error",
            }));
            break;
          default:
            break;
        }
      },
      controller.signal,
    ).catch((err: unknown) => {
      if (controller.signal.aborted) return; // superseded / reset — not an error
      setState((prev) =>
        prev.status === "done"
          ? prev
          : {
              ...prev,
              status: "error",
              error: err instanceof Error ? err.message : "connection lost",
            },
      );
    });
  }, []);

  return {
    ...state,
    submit,
    reset,
    lastRequest: lastRequestRef.current,
  };
}
