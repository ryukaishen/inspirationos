import { describe, expect, it } from "vitest";

import {
  DEFAULT_FILTERS,
  filtersToListParams,
  filtersToSearchParams,
  parseFilters,
  type ItemFilters,
} from "@/lib/item-filters";

describe("parseFilters", () => {
  it("returns defaults for an empty query string", () => {
    expect(parseFilters(new URLSearchParams())).toEqual(DEFAULT_FILTERS);
  });

  it("ignores unknown status/type values", () => {
    const params = new URLSearchParams("status=bogus&type=nonsense&status=reviewed");
    const filters = parseFilters(params);
    expect(filters.status).toEqual(["reviewed"]);
    expect(filters.itemType).toEqual([]);
  });

  it("falls back to page 1 for invalid page values", () => {
    expect(parseFilters(new URLSearchParams("page=0")).page).toBe(1);
    expect(parseFilters(new URLSearchParams("page=abc")).page).toBe(1);
  });
});

describe("filtersToSearchParams / parseFilters round trip", () => {
  it("round-trips a fully populated filter set", () => {
    const filters: ItemFilters = {
      page: 3,
      status: ["new", "reviewed"],
      itemType: ["reel"],
      tags: ["fun", "travel"],
      conversationId: 42,
      dateFrom: "2026-01-01",
      dateTo: "2026-01-31",
      search: "cats",
    };
    expect(parseFilters(filtersToSearchParams(filters))).toEqual(filters);
  });

  it("omits page from the query string when it is 1", () => {
    const params = filtersToSearchParams({ ...DEFAULT_FILTERS, page: 1 });
    expect(params.has("page")).toBe(false);
  });
});

describe("filtersToListParams", () => {
  it("omits empty arrays/fields as undefined", () => {
    expect(filtersToListParams(DEFAULT_FILTERS, 20)).toEqual({ page: 1, page_size: 20 });
  });

  it("expands the date range to inclusive UTC day boundaries", () => {
    const params = filtersToListParams(
      { ...DEFAULT_FILTERS, dateFrom: "2026-01-01", dateTo: "2026-01-02" },
      20,
    );
    expect(params.date_from).toBe("2026-01-01T00:00:00.000Z");
    expect(params.date_to).toBe("2026-01-02T23:59:59.999Z");
  });
});
