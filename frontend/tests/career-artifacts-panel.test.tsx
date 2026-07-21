import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CareerArtifactsPanel } from "@/components/projects/career-artifacts-panel";
import * as api from "@/lib/api";
import type { ArtifactRead, JobRead } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof api>();
  return {
    ...original,
    listCareerArtifacts: vi.fn(),
    requestCareerArtifact: vi.fn(),
    getJob: vi.fn(),
  };
});

const mockedList = vi.mocked(api.listCareerArtifacts);
const mockedRequest = vi.mocked(api.requestCareerArtifact);
const mockedGetJob = vi.mocked(api.getJob);

function makeArtifact(overrides: Partial<ArtifactRead> = {}): ArtifactRead {
  return {
    id: 1,
    project_id: 42,
    kind: "readme",
    version: 1,
    content_md: "# Hello project",
    payload: {},
    claims_flags: [],
    provider: "mock",
    model: "mock-llm-v1",
    prompt_version: "v1",
    created_at: "2026-07-20T00:00:00Z",
    ...overrides,
  };
}

function makeJob(overrides: Partial<JobRead> = {}): JobRead {
  return {
    id: 9,
    rq_job_id: "rq-9",
    kind: "generate_artifact",
    status: "succeeded",
    progress: 2,
    total: 2,
    error: null,
    created_at: "2026-07-20T00:00:00Z",
    started_at: "2026-07-20T00:00:01Z",
    finished_at: "2026-07-20T00:00:02Z",
    ...overrides,
  };
}

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("CareerArtifactsPanel", () => {
  beforeEach(() => {
    mockedList.mockReset();
    mockedRequest.mockReset();
    mockedGetJob.mockReset();
  });

  it("shows the empty state for a kind with no versions yet", async () => {
    mockedList.mockResolvedValue([]);
    renderWithClient(<CareerArtifactsPanel projectId={42} />);

    expect(await screen.findByTestId("career-artifact-empty")).toBeInTheDocument();
    expect(mockedList).toHaveBeenCalledWith(42, "readme");
  });

  it("requests generation and renders the result once the job finishes", async () => {
    mockedList.mockResolvedValue([]);
    mockedRequest.mockResolvedValue({ job_id: 9 });
    mockedGetJob.mockResolvedValue(makeJob());

    renderWithClient(<CareerArtifactsPanel projectId={42} />);
    await screen.findByTestId("career-artifact-empty");

    mockedList.mockResolvedValue([makeArtifact()]);
    await userEvent.click(screen.getByTestId("career-artifact-request"));

    expect(mockedRequest).toHaveBeenCalledWith(42, "readme");
    expect(await screen.findByTestId("career-artifact-content")).toHaveTextContent(
      "# Hello project",
    );
  });

  it("switching the kind tab fetches that kind's own versions", async () => {
    mockedList.mockResolvedValue([]);
    renderWithClient(<CareerArtifactsPanel projectId={42} />);
    await screen.findByTestId("career-artifact-empty");

    await userEvent.click(screen.getByTestId("career-artifact-tab-resume_bullets"));
    await waitFor(() => expect(mockedList).toHaveBeenCalledWith(42, "resume_bullets"));
  });

  it("renders a claims warning when the shown version was flagged", async () => {
    mockedList.mockResolvedValue([makeArtifact({ claims_flags: ["achieved 97%"] })]);
    renderWithClient(<CareerArtifactsPanel projectId={42} />);

    expect(await screen.findByTestId("career-artifact-claims-warning")).toHaveTextContent(
      "achieved 97%",
    );
  });

  it("does not render a claims warning when nothing was flagged", async () => {
    mockedList.mockResolvedValue([makeArtifact({ claims_flags: [] })]);
    renderWithClient(<CareerArtifactsPanel projectId={42} />);

    await screen.findByTestId("career-artifact-content");
    expect(screen.queryByTestId("career-artifact-claims-warning")).not.toBeInTheDocument();
  });
});
