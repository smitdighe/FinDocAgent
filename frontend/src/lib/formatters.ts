// All numeric formatting funnels through here so figures render consistently in
// mono (the hard rule from spec §1). These return strings; <MonoValue> applies
// the mono font.

export function formatUsd(value: number): string {
  if (value === 0) return "$0.00";
  // sub-cent costs are common (per-query LLM cost) — show enough precision.
  if (Math.abs(value) < 0.01) {
    return `$${value.toPrecision(2)}`;
  }
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function formatInt(value: number): string {
  return value.toLocaleString("en-US");
}

export function formatScore(value: number, digits = 4): string {
  return value.toFixed(digits);
}

export function formatDelta(value: number | null, digits = 4): string {
  if (value === null) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "" : "±";
  return `${sign}${value.toFixed(digits)}`;
}

/** Colorblind-safe direction glyph for deltas (never color-only, spec §6). */
export function deltaArrow(value: number | null): string {
  if (value === null || value === 0) return "→";
  return value > 0 ? "▲" : "▼";
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function shortSha(sha: string): string {
  return sha.slice(0, 8);
}
