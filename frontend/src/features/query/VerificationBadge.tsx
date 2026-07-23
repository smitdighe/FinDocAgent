import { Stamp } from "@/components/Stamp";
import type { VerificationResult } from "@/api/types";

// Verification state must be visually distinct, not decorative (spec §5).
//   verified            -> stamp-red, filled stamp
//   unverified / held   -> ink-amber, "held — unverifiable"
//   failed (post-repair) -> ink-amber + explicit reason text
interface Props {
  verification: VerificationResult;
}

export function VerificationBadge({ verification }: Props) {
  const { status, reasons } = verification;

  if (status === "verified") {
    return (
      <div className="flex flex-col gap-1">
        <Stamp tone="stamp" ariaLabel="verification: verified against source">
          ✓ Verified
        </Stamp>
        <p className="text-xs text-paper-muted">
          Every figure re-extracted from a cited source cell.
        </p>
      </div>
    );
  }

  const label = status === "failed" ? "Held — unverifiable" : "Unverified";
  return (
    <div className="flex flex-col gap-1">
      <Stamp tone="caution" ariaLabel={`verification: ${label}`}>
        ⚠ {label}
      </Stamp>
      {status === "failed" ? (
        <p className="text-xs text-caution">
          Figures could not be traced to a cited source — the number is withheld.
        </p>
      ) : (
        <p className="text-xs text-paper-muted">
          Narrative answer — no numeric claim was machine-verified.
        </p>
      )}
      {reasons.length > 0 ? (
        <ul className="mt-1 list-inside list-disc text-xs text-caution/90">
          {reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
