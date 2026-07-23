import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VerificationReport } from "@/components/imports/verification-report";
import type { ImportVerificationReport } from "@/lib/api";

function makeReport(overrides: Partial<ImportVerificationReport>): ImportVerificationReport {
  return {
    import_id: 1,
    status: "scanned",
    raw_message_json_entries: 5,
    matched_message_json_entries: 4,
    conversations_found: 3,
    messages_parsed: 10,
    messages_skipped: 2,
    skip_breakdown: [
      {
        category: "unrecognized_message_path",
        count: 1,
        description: "A message_N.json file under an unrecognized category.",
      },
    ],
    extracted_messages: null,
    items_extracted: null,
    duplicate_summary: [],
    ...overrides,
  };
}

describe("VerificationReport", () => {
  it("renders raw-vs-parsed counts and the skip breakdown", () => {
    render(<VerificationReport report={makeReport({})} />);

    expect(screen.getByTestId("verification-raw-entries")).toHaveTextContent("5");
    expect(screen.getByTestId("verification-matched-entries")).toHaveTextContent("4");
    expect(screen.getByTestId("verification-conversations")).toHaveTextContent("3");
    expect(screen.getByTestId("verification-messages-parsed")).toHaveTextContent("10");
    expect(screen.getByTestId("verification-messages-skipped")).toHaveTextContent("2");
    expect(screen.queryByTestId("verification-extracted-messages")).not.toBeInTheDocument();

    const skipRow = screen.getByTestId("verification-skip-unrecognized_message_path");
    expect(skipRow).toHaveTextContent("1");
    expect(skipRow).toHaveTextContent("unrecognized category");
  });

  it("shows extracted counts once extraction has run", () => {
    render(
      <VerificationReport
        report={makeReport({ extracted_messages: 10, items_extracted: 4 })}
      />,
    );
    expect(screen.getByTestId("verification-extracted-messages")).toHaveTextContent("10");
    expect(screen.getByTestId("verification-items-extracted")).toHaveTextContent("4");
  });

  it("renders a duplicate-reason summary by counts only, never a URL", () => {
    render(
      <VerificationReport
        report={makeReport({
          duplicate_summary: [{ reason: "same_shortcode", group_count: 1, item_count: 2 }],
        })}
      />,
    );
    const row = screen.getByTestId("verification-duplicate-same_shortcode");
    expect(row).toHaveTextContent("same_shortcode");
    expect(row).toHaveTextContent("1 group");
    expect(row).toHaveTextContent("2 items");
    expect(screen.queryByText(/instagram\.com/i)).not.toBeInTheDocument();
  });

  it("explains an empty duplicate summary before extraction", () => {
    render(<VerificationReport report={makeReport({})} />);
    expect(screen.getByText(/built by the extract pass/i)).toBeInTheDocument();
  });
});
