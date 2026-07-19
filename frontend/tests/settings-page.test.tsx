import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "@/app/settings/page";
import * as api from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof api>();
  return {
    ...original,
    getSettings: vi.fn(),
    updateEnrichmentSettings: vi.fn(),
    updateAiSettings: vi.fn(),
  };
});

const mockedGetSettings = vi.mocked(api.getSettings);
const mockedUpdate = vi.mocked(api.updateEnrichmentSettings);
const mockedUpdateAi = vi.mocked(api.updateAiSettings);

function settingsFixture(overrides: Partial<api.SettingsRead> = {}): api.SettingsRead {
  return {
    enrichment_enabled: false,
    enrichment_consent_at: null,
    ai_provider: "mock",
    model_overrides: {},
    monthly_budget_usd: null,
    ...overrides,
  };
}

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
    mockedUpdateAi.mockReset();
  });

  it("shows the disclosure dialog before enabling, and does not call the API until confirmed", async () => {
    mockedGetSettings.mockResolvedValue(settingsFixture());
    renderWithClient();

    const toggle = await screen.findByTestId("enrichment-toggle");
    await userEvent.click(toggle);

    expect(screen.getByText("Enable metadata enrichment?")).toBeInTheDocument();
    expect(mockedUpdate).not.toHaveBeenCalled();

    mockedUpdate.mockResolvedValue(
      settingsFixture({
        enrichment_enabled: true,
        enrichment_consent_at: "2026-01-01T00:00:00Z",
      }),
    );
    await userEvent.click(screen.getByTestId("consent-confirm"));
    expect(mockedUpdate).toHaveBeenCalledWith(true);
  });

  it("cancelling the dialog never calls the API", async () => {
    mockedGetSettings.mockResolvedValue(settingsFixture());
    renderWithClient();

    const toggle = await screen.findByTestId("enrichment-toggle");
    await userEvent.click(toggle);
    await userEvent.click(screen.getByTestId("dialog-cancel"));

    expect(screen.queryByText("Enable metadata enrichment?")).not.toBeInTheDocument();
    expect(mockedUpdate).not.toHaveBeenCalled();
  });

  it("disabling does not show the consent dialog", async () => {
    mockedGetSettings.mockResolvedValue(
      settingsFixture({
        enrichment_enabled: true,
        enrichment_consent_at: "2026-01-01T00:00:00Z",
      }),
    );
    mockedUpdate.mockResolvedValue(
      settingsFixture({ enrichment_consent_at: "2026-01-01T00:00:00Z" }),
    );
    renderWithClient();

    const toggle = await screen.findByTestId("enrichment-toggle");
    await userEvent.click(toggle);

    expect(mockedUpdate).toHaveBeenCalledWith(false);
    expect(screen.queryByText("Enable metadata enrichment?")).not.toBeInTheDocument();
  });

  it("initializes the AI form from settings and saves edits", async () => {
    mockedGetSettings.mockResolvedValue(
      settingsFixture({
        ai_provider: "anthropic",
        model_overrides: { fast: "claude-tiny" },
        monthly_budget_usd: 7.5,
      }),
    );
    mockedUpdateAi.mockResolvedValue(settingsFixture({ ai_provider: "openai" }));
    renderWithClient();

    const providerSelect = await screen.findByTestId<HTMLSelectElement>("ai-provider-select");
    expect(providerSelect.value).toBe("anthropic");
    expect(screen.getByTestId<HTMLInputElement>("ai-model-fast").value).toBe("claude-tiny");
    expect(screen.getByTestId<HTMLInputElement>("ai-budget-input").value).toBe("7.5");

    await userEvent.selectOptions(providerSelect, "openai");
    await userEvent.clear(screen.getByTestId("ai-budget-input"));
    await userEvent.type(screen.getByTestId("ai-budget-input"), "3");
    await userEvent.click(screen.getByTestId("ai-save"));

    expect(mockedUpdateAi).toHaveBeenCalledWith({
      ai_provider: "openai",
      model_overrides: { generation: null, fast: "claude-tiny" },
      monthly_budget_usd: 3,
    });
    expect(await screen.findByTestId("ai-saved")).toBeInTheDocument();
  });

  it("never renders API key input fields", async () => {
    mockedGetSettings.mockResolvedValue(settingsFixture());
    renderWithClient();
    await screen.findByTestId("ai-provider-select");
    expect(screen.queryByLabelText(/api key/i)).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/key/i)).not.toBeInTheDocument();
    expect(
      screen.getByText(/API keys are read from environment variables only/),
    ).toBeInTheDocument();
  });
});
