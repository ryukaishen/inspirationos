import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ItemCard } from "@/components/inbox/item-card";
import * as api from "@/lib/api";
import type { ItemEntry, ItemRead } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof api>();
  return {
    ...original,
    updateItem: vi.fn(),
    enrichItems: vi.fn(),
    getSettings: vi.fn(),
  };
});

const mockedUpdate = vi.mocked(api.updateItem);
const mockedEnrichItems = vi.mocked(api.enrichItems);
const mockedGetSettings = vi.mocked(api.getSettings);

function makeItem(overrides: Partial<ItemRead> = {}): ItemRead {
  return {
    id: 1,
    source: "instagram",
    import_id: 1,
    conversation_id: 1,
    message_id: 1,
    url_raw: "https://www.instagram.com/reel/ABC123/",
    url_canonical: "https://www.instagram.com/reel/ABC123/",
    shortcode: "ABC123",
    item_type: "reel",
    shared_at: "2026-01-05T12:00:00Z",
    share_text: "cool reel about cats",
    adjacent_text: null,
    enriched_title: null,
    enriched_caption: null,
    enriched_author: null,
    enriched_source: null,
    context_note: null,
    transcript: null,
    visual_text: null,
    status: "new",
    tags: ["fun", "travel"],
    duplicate_group_id: null,
    created_at: "2026-01-05T12:00:00Z",
    updated_at: "2026-01-05T12:00:00Z",
    ...overrides,
  };
}

function makeEntry(itemOverrides: Partial<ItemRead> = {}, duplicateCount = 1): ItemEntry {
  return { item: makeItem(itemOverrides), duplicate_count: duplicateCount };
}

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("ItemCard", () => {
  beforeEach(() => {
    mockedUpdate.mockReset();
    mockedEnrichItems.mockReset();
    mockedGetSettings.mockReset();
    mockedGetSettings.mockResolvedValue({
      enrichment_enabled: false,
      enrichment_consent_at: null,
      ai_provider: "mock",
      model_overrides: {},
      monthly_budget_usd: null,
      scoring_weights: {},
    });
  });

  it("renders type, share text, status, and tags", () => {
    renderWithClient(
      <ItemCard entry={makeEntry()} selected={false} onToggleSelect={vi.fn()} />,
    );
    expect(screen.getByText("Reel")).toBeInTheDocument();
    expect(screen.getByText("cool reel about cats")).toBeInTheDocument();
    expect(screen.getByTestId("item-status")).toHaveTextContent("New");
    expect(screen.getByText("fun")).toBeInTheDocument();
    expect(screen.getByText("travel")).toBeInTheDocument();
    expect(screen.getByText("No note yet.")).toBeInTheDocument();
  });

  it("shows reel transcript and on-screen text collapsed, with word counts", () => {
    renderWithClient(
      <ItemCard
        entry={makeEntry({
          share_text: null,
          transcript: "first validate the idea with five interviews",
          visual_text: "STEP 1 interview",
        })}
        selected={false}
        onToggleSelect={vi.fn()}
      />,
    );
    const transcript = screen.getByTestId("reel-transcript");
    expect(transcript).not.toHaveAttribute("open");
    expect(transcript).toHaveTextContent("Transcript (7 words)");
    expect(transcript).toHaveTextContent("first validate the idea with five interviews");
    expect(screen.getByTestId("reel-visual")).toHaveTextContent("On-screen text (3 words)");
  });

  it("renders no reel-text block for items without extracted text", () => {
    renderWithClient(
      <ItemCard entry={makeEntry()} selected={false} onToggleSelect={vi.fn()} />,
    );
    expect(screen.queryByTestId("reel-text")).not.toBeInTheDocument();
  });

  it("always shows an Open original link to the raw URL", () => {
    renderWithClient(
      <ItemCard
        entry={makeEntry({ url_raw: "https://www.instagram.com/reel/XYZ999/" })}
        selected={false}
        onToggleSelect={vi.fn()}
      />,
    );
    expect(screen.getByTestId("open-original")).toHaveAttribute(
      "href",
      "https://www.instagram.com/reel/XYZ999/",
    );
  });

  it("hides the Enrich button when enrichment is disabled", async () => {
    renderWithClient(
      <ItemCard entry={makeEntry()} selected={false} onToggleSelect={vi.fn()} />,
    );
    await screen.findByTestId("open-original"); // wait for the settings query to settle
    expect(screen.queryByTestId("enrich-button")).not.toBeInTheDocument();
  });

  it("shows the Enrich button and triggers a per-item request when enabled", async () => {
    mockedGetSettings.mockResolvedValue({
      enrichment_enabled: true,
      enrichment_consent_at: "2026-01-01T00:00:00Z",
      ai_provider: "mock",
      model_overrides: {},
      monthly_budget_usd: null,
      scoring_weights: {},
    });
    mockedEnrichItems.mockResolvedValue({ job_id: 42 });
    renderWithClient(
      <ItemCard entry={makeEntry({ id: 9 })} selected={false} onToggleSelect={vi.fn()} />,
    );

    const enrichButton = await screen.findByTestId("enrich-button");
    await userEvent.click(enrichButton);
    expect(mockedEnrichItems).toHaveBeenCalledWith({ item_ids: [9] });
  });

  it("shows a duplicate-count badge only when the group has more than one member", () => {
    const { rerender } = renderWithClient(
      <ItemCard entry={makeEntry({}, 3)} selected={false} onToggleSelect={vi.fn()} />,
    );
    expect(screen.getByTestId("duplicate-badge")).toHaveTextContent("×3");

    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <ItemCard entry={makeEntry({}, 1)} selected={false} onToggleSelect={vi.fn()} />
      </QueryClientProvider>,
    );
    expect(screen.queryByTestId("duplicate-badge")).not.toBeInTheDocument();
  });

  it("calls onToggleSelect with the item id when the checkbox is clicked", async () => {
    const onToggleSelect = vi.fn();
    renderWithClient(
      <ItemCard entry={makeEntry({ id: 7 })} selected={false} onToggleSelect={onToggleSelect} />,
    );
    await userEvent.click(screen.getByLabelText("Select item 7"));
    expect(onToggleSelect).toHaveBeenCalledWith(7);
  });

  it("edits and saves, calling updateItem with the expected patch", async () => {
    mockedUpdate.mockResolvedValue(makeItem({ status: "reviewed" }));
    renderWithClient(
      <ItemCard entry={makeEntry({ id: 5 })} selected={false} onToggleSelect={vi.fn()} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    await userEvent.selectOptions(screen.getByRole("combobox"), "reviewed");
    const tagsInput = screen.getByDisplayValue("fun, travel");
    await userEvent.clear(tagsInput);
    await userEvent.type(tagsInput, "fun, new-tag");
    const noteInput = screen.getByLabelText("Note");
    await userEvent.type(noteInput, "context here");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(mockedUpdate).toHaveBeenCalledWith(5, {
      status: "reviewed",
      tags: ["fun", "new-tag"],
      context_note: "context here",
    });
  });
});
