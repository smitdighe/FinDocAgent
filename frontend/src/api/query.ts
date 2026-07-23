import { postJson } from "./client";
import { streamPost, type SSEMessage } from "./sse";
import type { QueryRequest, QueryResponse } from "./types";

/** Non-streamed query (mirror of the SSE result). Used for tests/fallback. */
export function querySync(
  request: QueryRequest,
  signal?: AbortSignal,
): Promise<QueryResponse> {
  return postJson<QueryResponse>("/query/sync", request, signal);
}

/** Streamed query: one SSE frame per agent hop, then a final `answer` frame. */
export function queryStream(
  request: QueryRequest,
  onMessage: (msg: SSEMessage) => void,
  signal?: AbortSignal,
): Promise<void> {
  return streamPost("/query", request, { onMessage, signal });
}
