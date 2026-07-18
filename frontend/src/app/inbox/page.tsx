"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { BulkToolbar } from "@/components/inbox/bulk-toolbar";
import { FilterBar } from "@/components/inbox/filter-bar";
import { ItemCard } from "@/components/inbox/item-card";
import { Pagination } from "@/components/inbox/pagination";
import { getItemFacets, listItems } from "@/lib/api";
import {
  filtersToListParams,
  filtersToSearchParams,
  parseFilters,
  type ItemFilters,
} from "@/lib/item-filters";

const PAGE_SIZE = 20;

function InboxContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const filters = parseFilters(searchParams);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);

  function applyFilters(next: ItemFilters) {
    setSelectedIds([]);
    const query = filtersToSearchParams(next).toString();
    router.replace(query ? `/inbox?${query}` : "/inbox");
  }

  const { data: page, isLoading } = useQuery({
    queryKey: ["items", filters],
    queryFn: () => listItems(filtersToListParams(filters, PAGE_SIZE)),
  });

  const { data: facets } = useQuery({
    queryKey: ["item-facets"],
    queryFn: getItemFacets,
  });

  function toggleSelect(itemId: number) {
    setSelectedIds((prev) =>
      prev.includes(itemId) ? prev.filter((id) => id !== itemId) : [...prev, itemId],
    );
  }

  return (
    <main className="mx-auto w-full max-w-4xl flex-1 space-y-6 px-6 py-12">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Inbox</h1>
        <p className="text-sm text-muted-foreground">
          Browse, search, and review extracted reels and posts.{" "}
          <Link className="underline" href="/review">
            Fast review →
          </Link>
        </p>
      </div>

      <FilterBar value={filters} onChange={applyFilters} facets={facets} />

      <BulkToolbar
        selectedIds={selectedIds}
        entries={page?.entries ?? []}
        onClearSelection={() => setSelectedIds([])}
      />

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {page && page.entries.length === 0 && (
        <p className="text-sm text-muted-foreground">No items match these filters.</p>
      )}
      {page && page.entries.length > 0 && (
        <div className="space-y-3" data-testid="item-list">
          {page.entries.map((entry) => (
            <ItemCard
              key={entry.item.id}
              entry={entry}
              selected={selectedIds.includes(entry.item.id)}
              onToggleSelect={toggleSelect}
            />
          ))}
        </div>
      )}

      {page && page.total > 0 && (
        <Pagination
          page={page.page}
          pageSize={page.page_size}
          total={page.total}
          onPageChange={(nextPage) => applyFilters({ ...filters, page: nextPage })}
        />
      )}
    </main>
  );
}

export default function InboxPage() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-12 text-sm text-muted-foreground">
          Loading…
        </main>
      }
    >
      <InboxContent />
    </Suspense>
  );
}
