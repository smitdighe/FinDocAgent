import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { AgentTrace } from "@/features/query/AgentTrace";
import type { StageState } from "@/features/query/useQueryStream";
import { STAGE_ORDER } from "@/features/query/useQueryStream";

function stages(overrides: Partial<Record<string, StageState>> = {}): StageState[] {
  return STAGE_ORDER.map((name) => ({
    name,
    status: "pending" as const,
    payload: null,
    ...overrides[name],
  }));
}

describe("AgentTrace", () => {
  it("shows an empty state before any query", () => {
    render(<AgentTrace status="idle" stages={stages()} error={null} />);
    expect(screen.getByText(/no trace yet/i)).toBeInTheDocument();
  });

  it("renders a stamp per pipeline stage while streaming", () => {
    render(<AgentTrace status="streaming" stages={stages()} error={null} />);
    // each stage label appears (router, retrieval, table, synthesis, verify)
    for (const name of STAGE_ORDER) {
      expect(screen.getByLabelText(new RegExp(`stage ${name}`, "i"))).toBeInTheDocument();
    }
  });

  it("marks verify as a red 'verified' stamp when verification passed", () => {
    const s = stages({
      verify: {
        name: "verify",
        status: "done",
        payload: { status: "verified", checks: [], repairing: false },
      },
    });
    render(<AgentTrace status="done" stages={s} error={null} />);
    expect(screen.getByLabelText(/stage verified done/i)).toBeInTheDocument();
  });

  it("marks verify as amber 'held' when verification failed closed", () => {
    const s = stages({
      verify: {
        name: "verify",
        status: "done",
        payload: { status: "failed", checks: [], repairing: false },
      },
    });
    render(<AgentTrace status="done" stages={s} error={null} />);
    expect(screen.getByLabelText(/stage held done/i)).toBeInTheDocument();
  });

  it("shows a retry-able error on stream interruption", () => {
    render(<AgentTrace status="error" stages={stages()} error="boom" />);
    expect(screen.getByRole("alert")).toHaveTextContent(/boom/i);
  });
});
