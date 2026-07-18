"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ITEM_STATUSES, ITEM_TYPES, type ItemFacets, type ItemStatus, type ItemType } from "@/lib/api";
import { STATUS_LABELS, TYPE_LABELS } from "@/lib/item-labels";
import { DEFAULT_FILTERS, type ItemFilters } from "@/lib/item-filters";

export interface FilterBarProps {
  value: ItemFilters;
  onChange: (filters: ItemFilters) => void;
  facets?: ItemFacets;
}

/** Plain controlled component — no next/navigation access, so it's testable
 * with a simple callback mock. `inbox/page.tsx` owns the URL sync. */
export function FilterBar({ value, onChange, facets }: FilterBarProps) {
  function update(partial: Partial<ItemFilters>) {
    onChange({ ...value, ...partial, page: partial.page ?? 1 });
  }

  function toggleStatus(status: ItemStatus) {
    const next = value.status.includes(status)
      ? value.status.filter((s) => s !== status)
      : [...value.status, status];
    update({ status: next });
  }

  function toggleType(itemType: ItemType) {
    const next = value.itemType.includes(itemType)
      ? value.itemType.filter((t) => t !== itemType)
      : [...value.itemType, itemType];
    update({ itemType: next });
  }

  function toggleTag(tag: string) {
    const next = value.tags.includes(tag)
      ? value.tags.filter((t) => t !== tag)
      : [...value.tags, tag];
    update({ tags: next });
  }

  return (
    <div className="space-y-4 rounded-lg border bg-card p-4 text-sm" data-testid="filter-bar">
      <label className="block space-y-1">
        <span className="text-xs font-medium text-muted-foreground">Search</span>
        <Input
          data-testid="search-input"
          value={value.search}
          placeholder="Search share text, adjacent text, notes…"
          onChange={(event) => update({ search: event.target.value })}
        />
      </label>

      <fieldset className="space-y-1">
        <legend className="text-xs font-medium text-muted-foreground">Status</legend>
        <div className="flex flex-wrap gap-3">
          {ITEM_STATUSES.map((status) => (
            <label key={status} className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={value.status.includes(status)}
                onChange={() => toggleStatus(status)}
              />
              {STATUS_LABELS[status]}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="space-y-1">
        <legend className="text-xs font-medium text-muted-foreground">Type</legend>
        <div className="flex flex-wrap gap-3">
          {ITEM_TYPES.map((itemType) => (
            <label key={itemType} className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={value.itemType.includes(itemType)}
                onChange={() => toggleType(itemType)}
              />
              {TYPE_LABELS[itemType]}
            </label>
          ))}
        </div>
      </fieldset>

      {facets && facets.tags.length > 0 && (
        <fieldset className="space-y-1">
          <legend className="text-xs font-medium text-muted-foreground">Tags</legend>
          <div className="flex flex-wrap gap-3">
            {facets.tags.map(({ tag, item_count: itemCount }) => (
              <label key={tag} className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={value.tags.includes(tag)}
                  onChange={() => toggleTag(tag)}
                />
                {tag} ({itemCount})
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {facets && facets.conversations.length > 0 && (
        <label className="block space-y-1">
          <span className="text-xs font-medium text-muted-foreground">Conversation</span>
          <select
            data-testid="conversation-filter"
            className="w-full rounded-md border border-input bg-background px-2 py-1"
            value={value.conversationId ?? ""}
            onChange={(event) =>
              update({
                conversationId: event.target.value ? Number(event.target.value) : null,
              })
            }
          >
            <option value="">All conversations</option>
            {facets.conversations.map((conversation) => (
              <option key={conversation.id} value={conversation.id}>
                {conversation.title ?? `Conversation ${conversation.id}`} (
                {conversation.item_count})
              </option>
            ))}
          </select>
        </label>
      )}

      <div className="flex gap-3">
        <label className="flex-1 space-y-1">
          <span className="text-xs font-medium text-muted-foreground">From</span>
          <Input
            type="date"
            value={value.dateFrom}
            onChange={(event) => update({ dateFrom: event.target.value })}
          />
        </label>
        <label className="flex-1 space-y-1">
          <span className="text-xs font-medium text-muted-foreground">To</span>
          <Input
            type="date"
            value={value.dateTo}
            onChange={(event) => update({ dateTo: event.target.value })}
          />
        </label>
      </div>

      <Button variant="ghost" size="sm" onClick={() => onChange(DEFAULT_FILTERS)}>
        Clear filters
      </Button>
    </div>
  );
}
