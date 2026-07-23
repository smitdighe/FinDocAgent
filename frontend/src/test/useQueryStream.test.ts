import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { SSEMessage } from "@/api/sse";

// Capture the onMessage callback the hook registers so the test can push frames.
let captured: ((m: SSEMessage) => void) | null = null;
vi.mock("@/api/query", () => ({
  queryStream: vi.fn(
    (_req: unknown, onMessage: (m: SSEMessage) => void) => {
      captured = onMessage;
      return new Promise<void>(() => {
        /* stays open until the test drives frames */
      });
    },
  ),
}));

import { useQueryStream } from "@/features/query/useQueryStream";

function frame(event: string, data: unknown): SSEMessage {
  return { event, data: JSON.stringify(data) };
}

describe("useQueryStream", () => {
  beforeEach(() => {
    captured = null;
  });

  it("moves idle -> streaming on submit and marks the first stage active", () => {
    const { result } = renderHook(() => useQueryStream());
    expect(result.current.status).toBe("idle");

    act(() => result.current.submit({ query: "total net sales" }));
    expect(result.current.status).toBe("streaming");
    expect(result.current.stages[0].status).toBe("active");
  });

  it("marks stages done as hop frames arrive", async () => {
    const { result } = renderHook(() => useQueryStream());
    act(() => result.current.submit({ query: "q" }));

    act(() => captured?.(frame("router", { query_type: "numeric", retrieval_path: "hybrid" })));
    await waitFor(() =>
      expect(result.current.stages.find((s) => s.name === "router")?.status).toBe("done"),
    );
    // next stage becomes active
    expect(result.current.stages.find((s) => s.name === "retrieval")?.status).toBe("active");
  });

  it("populates the answer and finishes on the answer frame", async () => {
    const { result } = renderHook(() => useQueryStream());
    act(() => result.current.submit({ query: "q" }));

    const answer = {
      answer: "Total net sales were $416,161 million.",
      citations: [],
      verification: { status: "verified", checks: [], reasons: [] },
      query_type: "numeric",
      cost: { tokens_in: 0, tokens_out: 0, cost_usd: 0, latency_ms: 30 },
      trace: [],
    };
    act(() => captured?.(frame("answer", answer)));

    await waitFor(() => expect(result.current.status).toBe("done"));
    expect(result.current.answer?.answer).toContain("416,161");
    // unfired stages resolve to skipped, never left spinning
    expect(result.current.stages.find((s) => s.name === "table")?.status).toBe("skipped");
  });

  it("surfaces an error frame", async () => {
    const { result } = renderHook(() => useQueryStream());
    act(() => result.current.submit({ query: "q" }));
    act(() => captured?.(frame("error", { detail: "router exploded" })));
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error).toMatch(/router exploded/);
  });
});
