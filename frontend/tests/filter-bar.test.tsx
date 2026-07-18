import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FilterBar } from "@/components/inbox/filter-bar";
import type { ItemFacets } from "@/lib/api";
import { DEFAULT_FILTERS } from "@/lib/item-filters";

function makeFacets(): ItemFacets {
  return {
    conversations: [{ id: 1, title: "Friend", item_count: 3 }],
    tags: [{ tag: "fun", item_count: 2 }],
  };
}

describe("FilterBar", () => {
  it("calls onChange with updated search text and page reset to 1", async () => {
    const onChange = vi.fn();
    render(<FilterBar value={{ ...DEFAULT_FILTERS, page: 4 }} onChange={onChange} />);
    await userEvent.type(screen.getByTestId("search-input"), "c");
    expect(onChange).toHaveBeenCalledWith({ ...DEFAULT_FILTERS, page: 1, search: "c" });
  });

  it("toggles a status filter on and off", async () => {
    const onChange = vi.fn();
    const { rerender } = render(<FilterBar value={DEFAULT_FILTERS} onChange={onChange} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "New" }));
    expect(onChange).toHaveBeenLastCalledWith({ ...DEFAULT_FILTERS, status: ["new"], page: 1 });

    onChange.mockClear();
    rerender(<FilterBar value={{ ...DEFAULT_FILTERS, status: ["new"] }} onChange={onChange} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "New" }));
    expect(onChange).toHaveBeenLastCalledWith({ ...DEFAULT_FILTERS, status: [], page: 1 });
  });

  it("renders facet options and filters by tag/conversation", async () => {
    const onChange = vi.fn();
    render(<FilterBar value={DEFAULT_FILTERS} onChange={onChange} facets={makeFacets()} />);

    await userEvent.click(screen.getByRole("checkbox", { name: "fun (2)" }));
    expect(onChange).toHaveBeenLastCalledWith({ ...DEFAULT_FILTERS, tags: ["fun"], page: 1 });

    await userEvent.selectOptions(screen.getByTestId("conversation-filter"), "1");
    expect(onChange).toHaveBeenLastCalledWith({
      ...DEFAULT_FILTERS,
      conversationId: 1,
      page: 1,
    });
  });

  it("clears all filters", async () => {
    const onChange = vi.fn();
    render(
      <FilterBar
        value={{ ...DEFAULT_FILTERS, search: "cats", status: ["new"], page: 3 }}
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(onChange).toHaveBeenCalledWith(DEFAULT_FILTERS);
  });
});
