import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ImportList } from "@/components/import-list";
import * as api from "@/lib/api";
import type { ImportRead } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof api>();
  return { ...original, listImports: vi.fn() };
});

const mockedList = vi.mocked(api.listImports);

function makeImport(overrides: Partial<ImportRead>): ImportRead {
  return {
    id: 1,
    source: "instagram",
    filename: "export.zip",
    size_bytes: 1234,
    checksum_sha256: "0".repeat(64),
    export_format: "json",
    status: "uploaded",
    counts: {},
    error: null,
    created_at: "2026-07-15T00:00:00Z",
    ...overrides,
  };
}

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("ImportList", () => {
  beforeEach(() => {
    mockedList.mockReset();
  });

  it("renders rows with status, counts, and detail links", async () => {
    mockedList.mockResolvedValue([
      makeImport({
        id: 2,
        filename: "scanned.zip",
        status: "scanned",
        counts: { total_entries: 12, message_files: 3 },
      }),
      makeImport({
        id: 1,
        filename: "rejected.zip",
        status: "failed",
        export_format: "html_detected",
        error: "This export is in HTML format, which cannot be parsed.",
      }),
    ]);

    renderWithClient(<ImportList />);

    const rows = await screen.findAllByTestId("import-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("scanned.zip");
    expect(rows[0]).toHaveTextContent("scanned");
    expect(rows[0]).toHaveTextContent("12 entries · 3 message files");
    expect(rows[1]).toHaveTextContent("failed");
    expect(rows[1]).toHaveTextContent("HTML format");
    expect(screen.getByRole("link", { name: "scanned.zip" })).toHaveAttribute(
      "href",
      "/import/2",
    );
  });

  it("shows an empty state", async () => {
    mockedList.mockResolvedValue([]);
    renderWithClient(<ImportList />);
    expect(await screen.findByText("No imports yet.")).toBeInTheDocument();
  });
});
