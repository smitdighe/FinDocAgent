import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

// Stub the page-detail fetch so the viewer renders without a backend.
vi.mock("@/features/viewer/useFilingPage", () => ({
  useFilingPage: () => ({
    detail: {
      filing_id: "f1",
      page_no: 5,
      page_count: 40,
      text: "…",
      image_url: "/filings/f1/pages/5/image",
      tables: [],
    },
    loading: false,
    error: null,
  }),
}));

import { FilingViewer } from "@/features/viewer/FilingViewer";
import { HighlightOverlay } from "@/features/viewer/HighlightOverlay";
import type { Citation, Filing } from "@/api/types";

const filing: Filing = {
  id: "f1",
  ticker: "AAPL",
  cik: "0000320193",
  company_name: "Apple Inc.",
  form_type: "10-K",
  accession_no: "0000320193-24-000123",
  filing_date: "2024-11-01",
  period_end: "2024-09-28",
  source_url: "https://example.com",
  status: "ingested",
  page_count: 40,
  ingested_at: "2024-11-02T00:00:00Z",
};

describe("FilingViewer", () => {
  it("prompts to open a filing when none is selected", () => {
    render(<FilingViewer filing={null} page={1} citation={null} onPageChange={() => {}} />);
    expect(screen.getByText(/no filing open/i)).toBeInTheDocument();
  });

  it("renders the page image and identity when a filing is open", () => {
    render(<FilingViewer filing={filing} page={5} citation={null} onPageChange={() => {}} />);
    expect(screen.getByText(/AAPL/)).toBeInTheDocument();
    const img = screen.getByAltText(/AAPL 10-K page 5/i) as HTMLImageElement;
    expect(img).toBeInTheDocument();
    expect(img.src).toContain("/filings/f1/pages/5/image");
  });
});

describe("HighlightOverlay bbox math", () => {
  it("positions the box as a percentage of the 612x792 page", () => {
    const citation: Citation = {
      filing_id: "f1",
      page_no: 5,
      section: "Statements of Operations",
      bbox: [61.2, 79.2, 306, 396], // 10%,10% -> 50%,50%
    };
    const { container } = render(<HighlightOverlay citation={citation} />);
    const box = container.querySelector("div[style]") as HTMLElement;
    expect(box.style.left).toBe("10%");
    expect(box.style.top).toBe("10%");
    // width = (306-61.2)/612 ≈ 40%
    expect(parseFloat(box.style.width)).toBeCloseTo(40, 0);
  });

  it("falls back to a full-page highlight with the section label when bbox is null", () => {
    const citation: Citation = {
      filing_id: "f1",
      page_no: 5,
      section: "Risk Factors",
      bbox: null,
    };
    render(<HighlightOverlay citation={citation} />);
    expect(screen.getByText(/risk factors/i)).toBeInTheDocument();
  });
});
