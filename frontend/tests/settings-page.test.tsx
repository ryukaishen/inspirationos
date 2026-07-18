import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "@/app/settings/page";
import * as api from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof api>();
  return { ...original, getSettings: vi.fn(), updateEnrichmentSettings: vi.fn() };
});

const mockedGetSettings = vi.mocked(api.getSettings);
const mockedUpdate = vi.mocked(api.updateEnrichmentSettings);

function renderWithClient() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SettingsPage />
    </QueryClientProvider>,
  );
}

describe("SettingsPage", () => {
  beforeEach(() => {
    mockedGetSettings.mockReset();
    mockedUpdate.mockReset();
  });

  it("shows the disclosure dialog before enabling, and does not call the API until confirmed", async () => {
    mockedGetSettings.mockResolvedValue({
      enrichment_enabled: false,
      enrichment_consent_at: null,
    });
    renderWithClient();

    const toggle = await screen.findByTestId("enrichment-toggle");
    await userEvent.click(toggle);

    expect(screen.getByText("Enable metadata enrichment?")).toBeInTheDocument();
    expect(mockedUpdate).not.toHaveBeenCalled();

    mockedUpdate.mockResolvedValue({
      enrichment_enabled: true,
      enrichment_consent_at: "2026-01-01T00:00:00Z",
    });
    await userEvent.click(screen.getByTestId("consent-confirm"));
    expect(mockedUpdate).toHaveBeenCalledWith(true);
  });

  it("cancelling the dialog never calls the API", async () => {
    mockedGetSettings.mockResolvedValue({
      enrichment_enabled: false,
      enrichment_consent_at: null,
    });
    renderWithClient();

    const toggle = await screen.findByTestId("enrichment-toggle");
    await userEvent.click(toggle);
    await userEvent.click(screen.getByTestId("dialog-cancel"));

    expect(screen.queryByText("Enable metadata enrichment?")).not.toBeInTheDocument();
    expect(mockedUpdate).not.toHaveBeenCalled();
  });

  it("disabling does not show the consent dialog", async () => {
    mockedGetSettings.mockResolvedValue({
      enrichment_enabled: true,
      enrichment_consent_at: "2026-01-01T00:00:00Z",
    });
    mockedUpdate.mockResolvedValue({
      enrichment_enabled: false,
      enrichment_consent_at: "2026-01-01T00:00:00Z",
    });
    renderWithClient();

    const toggle = await screen.findByTestId("enrichment-toggle");
    await userEvent.click(toggle);

    expect(mockedUpdate).toHaveBeenCalledWith(false);
    expect(screen.queryByText("Enable metadata enrichment?")).not.toBeInTheDocument();
  });
});
