import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ExportPanel } from "@/components/projects/export-panel";
import * as api from "@/lib/api";
import type { ExportRead, JobRead } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof api>();
  return {
    ...original,
    requestExport: vi.fn(),
    getJob: vi.fn(),
    getExport: vi.fn(),
  };
});

const mockedRequest = vi.mocked(api.requestExport);
const mockedGetJob = vi.mocked(api.getJob);
const mockedGetExport = vi.mocked(api.getExport);

function makeJob(overrides: Partial<JobRead> = {}): JobRead {
  return {
    id: 5,
    rq_job_id: "rq-5",
    kind: "export_bundle",
    status: "succeeded",
    progress: 1,
    total: 1,
    payload: {},
    error: null,
    created_at: "2026-07-20T00:00:00Z",
    started_at: "2026-07-20T00:00:01Z",
    finished_at: "2026-07-20T00:00:02Z",
    ...overrides,
  };
}

function makeExport(overrides: Partial<ExportRead> = {}): ExportRead {
  return {
    id: 3,
    project_id: 42,
    format: "markdown",
    ready: true,
    size_bytes: 128,
    error: null,
    created_at: "2026-07-20T00:00:00Z",
    ...overrides,
  };
}

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("ExportPanel", () => {
  beforeEach(() => {
    mockedRequest.mockReset();
    mockedGetJob.mockReset();
    mockedGetExport.mockReset();
  });

  it("requests a project-scoped markdown export and reveals a download link once ready", async () => {
    mockedRequest.mockResolvedValue({ export_id: 3, job_id: 5 });
    mockedGetJob.mockResolvedValue(makeJob());
    mockedGetExport.mockResolvedValue(makeExport());

    renderWithClient(<ExportPanel projectId={42} />);
    await userEvent.click(screen.getByTestId("export-markdown-request"));

    expect(mockedRequest).toHaveBeenCalledWith("markdown", 42);
    const link = await screen.findByTestId("export-markdown-download");
    expect(link).toHaveAttribute("href", "/api/exports/3/download");
  });

  it("requests a library-wide export with no project id", async () => {
    mockedRequest.mockResolvedValue({ export_id: 4, job_id: 6 });
    mockedGetJob.mockResolvedValue(makeJob({ id: 6 }));
    mockedGetExport.mockResolvedValue(makeExport({ id: 4, project_id: null }));

    renderWithClient(<ExportPanel />);
    await userEvent.click(screen.getByTestId("export-json-request"));

    expect(mockedRequest).toHaveBeenCalledWith("json", undefined);
  });

  it("surfaces a failed export job", async () => {
    mockedRequest.mockResolvedValue({ export_id: 3, job_id: 5 });
    mockedGetJob.mockResolvedValue(makeJob({ status: "failed", error: "OSError" }));

    renderWithClient(<ExportPanel projectId={42} />);
    await userEvent.click(screen.getByTestId("export-markdown-request"));

    expect(await screen.findByTestId("export-markdown-error")).toHaveTextContent("OSError");
  });
});
