// Pure, framework-free URL <-> filter-state conversion for the inbox. Kept
// separate from any React/Next code so it's unit-testable without mocking
// next/navigation, and so `inbox/page.tsx` is the only place that touches
// `useSearchParams`/`router.replace`.

import { ITEM_STATUSES, ITEM_TYPES, type ItemsListParams, type ItemStatus, type ItemType } from "@/lib/api";

export interface ItemFilters {
  page: number;
  status: ItemStatus[];
  itemType: ItemType[];
  tags: string[];
  conversationId: number | null;
  dateFrom: string; // "yyyy-mm-dd" (native <input type="date"> value), "" when unset
  dateTo: string;
  search: string;
}

export const DEFAULT_FILTERS: ItemFilters = {
  page: 1,
  status: [],
  itemType: [],
  tags: [],
  conversationId: null,
  dateFrom: "",
  dateTo: "",
  search: "",
};

function isItemStatus(value: string): value is ItemStatus {
  return (ITEM_STATUSES as readonly string[]).includes(value);
}

function isItemType(value: string): value is ItemType {
  return (ITEM_TYPES as readonly string[]).includes(value);
}

export function parseFilters(searchParams: URLSearchParams): ItemFilters {
  const pageRaw = Number(searchParams.get("page") ?? "1");
  const conversationRaw = searchParams.get("conversation");
  const conversationId = conversationRaw !== null ? Number(conversationRaw) : null;

  return {
    page: Number.isInteger(pageRaw) && pageRaw > 0 ? pageRaw : 1,
    status: searchParams.getAll("status").filter(isItemStatus),
    itemType: searchParams.getAll("type").filter(isItemType),
    tags: searchParams.getAll("tag"),
    conversationId:
      conversationId !== null && Number.isInteger(conversationId) ? conversationId : null,
    dateFrom: searchParams.get("from") ?? "",
    dateTo: searchParams.get("to") ?? "",
    search: searchParams.get("q") ?? "",
  };
}

export function filtersToSearchParams(filters: ItemFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.page > 1) params.set("page", String(filters.page));
  for (const status of filters.status) params.append("status", status);
  for (const itemType of filters.itemType) params.append("type", itemType);
  for (const tag of filters.tags) params.append("tag", tag);
  if (filters.conversationId !== null) {
    params.set("conversation", String(filters.conversationId));
  }
  if (filters.dateFrom) params.set("from", filters.dateFrom);
  if (filters.dateTo) params.set("to", filters.dateTo);
  if (filters.search) params.set("q", filters.search);
  return params;
}

/** `date_to` is inclusive of the whole day the user picked. */
export function filtersToListParams(filters: ItemFilters, pageSize: number): ItemsListParams {
  return {
    page: filters.page,
    page_size: pageSize,
    status: filters.status.length > 0 ? filters.status : undefined,
    item_type: filters.itemType.length > 0 ? filters.itemType : undefined,
    tags: filters.tags.length > 0 ? filters.tags : undefined,
    conversation_id: filters.conversationId ?? undefined,
    date_from: filters.dateFrom ? new Date(`${filters.dateFrom}T00:00:00.000Z`).toISOString() : undefined,
    date_to: filters.dateTo ? new Date(`${filters.dateTo}T23:59:59.999Z`).toISOString() : undefined,
    search: filters.search || undefined,
  };
}
