import { Stamp, type StampTone } from "@/components/Stamp";
import { MonoValue } from "@/components/MonoValue";
import type { StageState } from "./useQueryStream";
import type { VerifyHop } from "@/api/types";

// A single stamped stage in the trace ticker. Verify is special: red stamp when
// passed, amber "HELD" when it fails closed.
interface Props {
  stage: StageState;
  index: number;
}

function verifyTone(payload: VerifyHop | null): {
  tone: StampTone;
  label: string;
} {
  if (!payload) return { tone: "active", label: "verify" };
  if (payload.status === "verified") return { tone: "stamp", label: "verified" };
  if (payload.repairing) return { tone: "caution", label: "verify · repairing" };
  return { tone: "caution", label: "held" };
}

function stageTone(stage: StageState): { tone: StampTone; label: string } {
  const base = stage.name;
  if (stage.name === "verify" && stage.status === "done") {
    return verifyTone(stage.payload as VerifyHop | null);
  }
  switch (stage.status) {
    case "pending":
      return { tone: "idle", label: base };
    case "active":
      return { tone: "active", label: base };
    case "skipped":
      return { tone: "idle", label: `${base} · skipped` };
    case "done":
    default:
      return { tone: "done", label: base };
  }
}

function subline(stage: StageState): string | null {
  const p = stage.payload;
  if (!p) return null;
  switch (stage.name) {
    case "router": {
      const r = p as { query_type: string | null; retrieval_path: string | null };
      return [r.query_type, r.retrieval_path].filter(Boolean).join(" · ") || null;
    }
    case "retrieval":
      return `${(p as { count: number }).count} pages`;
    case "table":
      return `${(p as { count: number }).count} cells`;
    case "synthesis":
      return `${(p as { citations: number }).citations} citations`;
    case "verify": {
      const v = p as VerifyHop;
      return `${v.checks.length} checks`;
    }
    default:
      return null;
  }
}

export function AgentTraceStage({ stage, index }: Props) {
  const { tone, label } = stageTone(stage);
  const sub = subline(stage);
  const wipe = stage.status === "done";
  return (
    <li className="flex items-stretch gap-2">
      <div className="flex flex-col items-start gap-1">
        <Stamp tone={tone} wipe={wipe} as="div" ariaLabel={`stage ${label} ${stage.status}`}>
          <span aria-hidden className="opacity-50">
            {String(index + 1).padStart(2, "0")}
          </span>
          {label}
        </Stamp>
        {sub ? (
          <MonoValue className="pl-1 text-[10px] text-shell-muted">{sub}</MonoValue>
        ) : null}
      </div>
    </li>
  );
}
