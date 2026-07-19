import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ClusterCard } from "@/components/clusters/cluster-card";
import * as api from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof api>();
  return {
    ...original,
    getClusterItems: vi.fn(),
    updateCluster: vi.fn(),
    bulkUpdateItems: vi.fn(),
    enrichItems: vi.fn(),
  };
});

const mockedGetItems = vi.mocked(api.getClusterItems);
const mockedUpdateCluster = vi.mocked(api.updateCluster);
const mockedBulkUpdate = vi.mocked(api.bulkUpdateItems);
const mockedEnrich = vi.mocked(api.enrichItems);

const CLUSTER: api.ClusterRead = {
  id: 5,
  run_id: 2,
  label: "Pasta Cooking",
  description_md: "Reels about pasta.",
  size: 2,
  topics: ["pasta", "cooking"],
};

function item(id: number): api.ItemRead {
  return {
    id,
    source: "instagram",
    import_id: 1,
    conversation_id: 1,
    message_id: id,
    url_raw: `https://www.instagram.com/reel/T${id}/`,
    url_canonical: `https://www.instagram.com/reel/T${id}/`,
    shortcode: `T${id}`,
    item_type: "reel",
    shared_at: "2026-07-01T00:00:00Z",
    share_text: `share ${id}`,
    adjacent_text: null,
    enriched_title: null,
    enriched_caption: null,
    enriched_author: null,
    enriched_source: null,
    context_note: null,
    status: "new",
    tags: [],
    duplicate_group_id: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
  };
}

function renderCard(cluster: api.ClusterRead = CLUSTER) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ClusterCard cluster={cluster} />
    </QueryClientProvider>,
  );
}

describe("ClusterCard", () => {
  beforeEach(() => {
    mockedGetItems.mockReset();
    mockedUpdateCluster.mockReset();
    mockedBulkUpdate.mockReset();
    mockedEnrich.mockReset();
  });

  it("renders label, size, and topic chips", () => {
    renderCard();
    expect(screen.getByTestId("cluster-label")).toHaveTextContent("Pasta Cooking");
    expect(screen.getByTestId("cluster-size")).toHaveTextContent("2 items");
    expect(screen.getAllByTestId("topic-chip").map((chip) => chip.textContent)).toEqual([
      "pasta",
      "cooking",
    ]);
  });

  it("shows a fallback for unlabeled clusters", () => {
    renderCard({ ...CLUSTER, label: null, topics: [] });
    expect(screen.getByTestId("cluster-label")).toHaveTextContent("Unlabeled cluster");
  });

  it("saves label/description edits", async () => {
    mockedUpdateCluster.mockResolvedValue({ ...CLUSTER, label: "Renamed" });
    renderCard();

    await userEvent.click(screen.getByTestId("cluster-edit"));
    const labelInput = screen.getByTestId("cluster-label-input");
    await userEvent.clear(labelInput);
    await userEvent.type(labelInput, "Renamed");
    await userEvent.click(screen.getByTestId("cluster-save"));

    expect(mockedUpdateCluster).toHaveBeenCalledWith(5, {
      label: "Renamed",
      description_md: "Reels about pasta.",
    });
  });

  it("expands to load members and applies a bulk note to all of them", async () => {
    mockedGetItems.mockResolvedValue({ items: [item(21), item(22)] });
    mockedBulkUpdate.mockResolvedValue({ updated: 2 });
    renderCard();

    await userEvent.click(screen.getByTestId("cluster-expand"));
    expect(await screen.findAllByTestId("cluster-member")).toHaveLength(2);

    await userEvent.type(screen.getByTestId("bulk-note-input"), "all about pasta");
    await userEvent.click(screen.getByTestId("bulk-apply"));

    expect(mockedBulkUpdate).toHaveBeenCalledWith({
      item_ids: [21, 22],
      context_note: "all about pasta",
    });
    expect(await screen.findByTestId("cluster-action-status")).toHaveTextContent(
      "Note applied to 2 items.",
    );
  });

  it("enriches the whole cluster via the member item ids", async () => {
    mockedGetItems.mockResolvedValue({ items: [item(21), item(22)] });
    mockedEnrich.mockResolvedValue({ job_id: 42 });
    renderCard();

    await userEvent.click(screen.getByTestId("cluster-expand"));
    await screen.findAllByTestId("cluster-member");
    await userEvent.click(screen.getByTestId("cluster-enrich"));

    expect(mockedEnrich).toHaveBeenCalledWith({ item_ids: [21, 22] });
    expect(await screen.findByTestId("cluster-action-status")).toHaveTextContent(
      "Enrichment job #42 started.",
    );
  });

  it("surfaces the enrichment-disabled error message", async () => {
    mockedGetItems.mockResolvedValue({ items: [item(21)] });
    mockedEnrich.mockRejectedValue(
      new api.ApiError(403, "enrichment_disabled", "enrichment is disabled"),
    );
    renderCard();

    await userEvent.click(screen.getByTestId("cluster-expand"));
    await screen.findAllByTestId("cluster-member");
    await userEvent.click(screen.getByTestId("cluster-enrich"));

    expect(await screen.findByTestId("cluster-action-status")).toHaveTextContent(
      "enrichment is disabled",
    );
  });
});
