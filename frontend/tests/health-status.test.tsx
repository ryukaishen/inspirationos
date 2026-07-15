import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HealthStatus } from "@/components/health-status";
import * as api from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof api>();
  return { ...original, getHealth: vi.fn() };
});

const mockedGetHealth = vi.mocked(api.getHealth);

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("HealthStatus", () => {
  beforeEach(() => {
    mockedGetHealth.mockReset();
  });

  it("shows healthy services when the API reports ok", async () => {
    mockedGetHealth.mockResolvedValue({ status: "ok", db: "healthy", redis: "healthy" });
    renderWithClient(<HealthStatus />);

    expect(await screen.findByText("All services healthy")).toBeInTheDocument();
    expect(screen.getAllByText("healthy")).toHaveLength(2);
  });

  it("shows degraded state when a service is unreachable", async () => {
    mockedGetHealth.mockResolvedValue({ status: "degraded", db: "healthy", redis: "unreachable" });
    renderWithClient(<HealthStatus />);

    expect(await screen.findByText("Degraded")).toBeInTheDocument();
    expect(screen.getByText("unreachable")).toBeInTheDocument();
    expect(screen.getByText("healthy")).toBeInTheDocument();
  });

  it("marks everything unreachable when the API itself is down", async () => {
    mockedGetHealth.mockRejectedValue(new Error("connection refused"));
    renderWithClient(<HealthStatus />);

    expect(await screen.findByText("API unreachable")).toBeInTheDocument();
    expect(screen.getAllByText("unreachable")).toHaveLength(2);
  });
});
