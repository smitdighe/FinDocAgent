// Thin fetch wrapper. Base URL from env; empty in dev (Vite proxy handles it).
import { API_BASE_URL } from "@/lib/env";

export class ApiError extends Error {
  readonly status: number;
  readonly detail?: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

async function parseError(res: Response): Promise<never> {
  let detail: unknown;
  let message = `${res.status} ${res.statusText}`;
  try {
    const body = await res.json();
    detail = body;
    if (body && typeof body === "object" && "detail" in body) {
      const d = (body as { detail: unknown }).detail;
      if (typeof d === "string") message = d;
    }
  } catch {
    // non-JSON error body; keep the status-line message
  }
  throw new ApiError(res.status, message, detail);
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(apiUrl(path), {
    headers: { Accept: "application/json" },
    signal,
  });
  if (!res.ok) return parseError(res);
  return res.json() as Promise<T>;
}

export async function postJson<T>(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) return parseError(res);
  return res.json() as Promise<T>;
}
