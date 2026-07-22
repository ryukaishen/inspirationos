import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DemoJobPanel } from "@/components/demo-job-panel";
import * as api from "@/lib/api";
import type { JobRead } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof api>();
  return { ...original, enqueueDemoJob: vi.fn(), getJob: vi.fn() };
});

const mockedEnqueue = vi.mocked(api.enqueueDemoJob);
const mockedGetJob = vi.mocked(api.getJob);

function makeJob(overrides: Partial<JobRead>): JobRead {
  return {
    id: 1,
    rq_job_id: "rq-1",
    kind: "demo",
    status: "queued",
    progress: 0,
    total: 3,
    payload: {},
    error: null,
    created_at: "2026-07-14T00:00:00Z",
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("DemoJobPanel", () => {
  beforeEach(() => {
    mockedEnqueue.mockReset();
    mockedGetJob.mockReset();
  });

  it("enqueues on click and renders the polled running state", async () => {
    mockedEnqueue.mockResolvedValue(makeJob({ status: "queued" }));
    mockedGetJob.mockResolvedValue(makeJob({ status: "running", progress: 1, started_at: "x" }));

    renderWithClient(<DemoJobPanel />);
    await userEvent.click(screen.getByRole("button", { name: "Run demo job" }));

    expect(await screen.findByTestId("job-status")).toHaveTextContent("running");
    expect(screen.getByTestId("job-progress")).toHaveTextContent("1 / 3");
    expect(mockedEnqueue).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Running…" })).toBeDisabled();
  });

  it("shows the terminal succeeded state and re-enables the button", async () => {
    mockedEnqueue.mockResolvedValue(makeJob({ status: "queued" }));
    mockedGetJob.mockResolvedValue(
      makeJob({ status: "succeeded", progress: 3, started_at: "x", finished_at: "y" }),
    );

    renderWithClient(<DemoJobPanel />);
    await userEvent.click(screen.getByRole("button", { name: "Run demo job" }));

    expect(await screen.findByTestId("job-status")).toHaveTextContent("succeeded");
    expect(screen.getByTestId("job-progress")).toHaveTextContent("3 / 3");
    expect(screen.getByRole("button", { name: "Run demo job" })).toBeEnabled();
  });

  it("surfaces a redacted job error on failure", async () => {
    mockedEnqueue.mockResolvedValue(makeJob({ status: "queued" }));
    mockedGetJob.mockResolvedValue(
      makeJob({ status: "failed", progress: 1, error: "RuntimeError", finished_at: "y" }),
    );

    renderWithClient(<DemoJobPanel />);
    await userEvent.click(screen.getByRole("button", { name: "Run demo job" }));

    expect(await screen.findByTestId("job-status")).toHaveTextContent("failed");
    expect(screen.getByText("RuntimeError")).toBeInTheDocument();
  });
});
