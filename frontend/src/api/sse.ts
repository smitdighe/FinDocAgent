// SSE over POST. EventSource only does GET, and the backend streams named JSON
// events from POST /query, so we read the fetch body stream and parse the
// `event:` / `data:` frame framing by hand (verified against
// backend/app/agents/run.py::_sse — "event: <name>\ndata: <json>\n\n").
import { apiUrl } from "./client";

export interface SSEMessage {
  event: string;
  data: string; // raw data payload (JSON string for this backend)
}

export interface StreamPostOptions {
  signal?: AbortSignal;
  onMessage: (msg: SSEMessage) => void;
}

/** POST a JSON body and yield parsed SSE frames until the stream closes. */
export async function streamPost(
  path: string,
  body: unknown,
  { signal, onMessage }: StreamPostOptions,
): Promise<void> {
  const res = await fetch(apiUrl(path), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `stream failed: ${res.status} ${res.statusText}${text ? ` — ${text}` : ""}`,
    );
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Frames are separated by a blank line. Handle both \n\n and \r\n\r\n.
      let sep = findFrameEnd(buffer);
      while (sep !== -1) {
        const frame = buffer.slice(0, sep.index);
        buffer = buffer.slice(sep.index + sep.length);
        const msg = parseFrame(frame);
        if (msg) onMessage(msg);
        sep = findFrameEnd(buffer);
      }
    }
    // flush any trailing frame without a terminal blank line
    const tail = parseFrame(buffer);
    if (tail) onMessage(tail);
  } finally {
    reader.releaseLock();
  }
}

function findFrameEnd(buf: string): { index: number; length: number } | -1 {
  const lf = buf.indexOf("\n\n");
  const crlf = buf.indexOf("\r\n\r\n");
  if (lf === -1 && crlf === -1) return -1;
  if (crlf === -1 || (lf !== -1 && lf < crlf)) return { index: lf, length: 2 };
  return { index: crlf, length: 4 };
}

function parseFrame(frame: string): SSEMessage | null {
  const trimmed = frame.trim();
  if (!trimmed) return null;
  let event = "message";
  const dataLines: string[] = [];
  for (const line of trimmed.split(/\r?\n/)) {
    if (line.startsWith(":")) continue; // comment/heartbeat
    const idx = line.indexOf(":");
    const field = idx === -1 ? line : line.slice(0, idx);
    // SSE spec: strip a single leading space after the colon.
    let val = idx === -1 ? "" : line.slice(idx + 1);
    if (val.startsWith(" ")) val = val.slice(1);
    if (field === "event") event = val;
    else if (field === "data") dataLines.push(val);
  }
  if (dataLines.length === 0) return null;
  return { event, data: dataLines.join("\n") };
}
