"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  ApiError,
  ITEM_STATUSES,
  bulkUpdateItems,
  enrichItems,
  generateProjects,
  getSettings,
  type ItemEntry,
  type ItemStatus,
} from "@/lib/api";
import { STATUS_LABELS } from "@/lib/item-labels";

export interface BulkToolbarProps {
  selectedIds: number[];
  entries: ItemEntry[];
  onClearSelection: () => void;
}

export function BulkToolbar({ selectedIds, entries, onClearSelection }: BulkToolbarProps) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<ItemStatus>("reviewed");
  const [tagInput, setTagInput] = useState("");
  const [noteInput, setNoteInput] = useState("");
  const [includeDuplicates, setIncludeDuplicates] = useState(false);

  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: getSettings });

  // Duplicate-group ids of the selected (canonical) entries — expanded
  // server-side to every member, so one bulk action can cover a whole
  // "shared again" group, not just its visible canonical row.
  const duplicateGroupIds = useMemo(() => {
    if (!includeDuplicates) return undefined;
    const ids = entries
      .filter(
        (entry) => selectedIds.includes(entry.item.id) && entry.item.duplicate_group_id !== null,
      )
      .map((entry) => entry.item.duplicate_group_id as number);
    return ids.length > 0 ? ids : undefined;
  }, [entries, selectedIds, includeDuplicates]);

  const applyStatus = useMutation({
    mutationFn: () =>
      bulkUpdateItems({ item_ids: selectedIds, status, duplicate_group_ids: duplicateGroupIds }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["items"] });
      onClearSelection();
    },
  });

  const addTag = useMutation({
    mutationFn: () =>
      bulkUpdateItems({
        item_ids: selectedIds,
        add_tags: [tagInput.trim()],
        duplicate_group_ids: duplicateGroupIds,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["items"] });
      setTagInput("");
    },
  });

  const applyNote = useMutation({
    mutationFn: () =>
      bulkUpdateItems({
        item_ids: selectedIds,
        context_note: noteInput,
        duplicate_group_ids: duplicateGroupIds,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["items"] });
      setNoteInput("");
    },
  });

  const enrichSelection = useMutation({
    mutationFn: () =>
      enrichItems({ item_ids: selectedIds, duplicate_group_ids: duplicateGroupIds }),
  });

  // The "selected items" half of M7 generation — clusters are picked on the
  // Projects page; this grounds a generation batch in an explicit selection.
  const generateFromSelection = useMutation({
    mutationFn: () => generateProjects({ item_ids: selectedIds }),
  });

  if (selectedIds.length === 0) {
    return null;
  }

  return (
    <div
      data-testid="bulk-toolbar"
      className="flex flex-wrap items-center gap-3 rounded-lg border bg-card p-3 text-sm"
    >
      <span data-testid="bulk-selection-count" className="font-medium">
        {selectedIds.length} selected
      </span>
      <label className="flex items-center gap-1 text-xs text-muted-foreground">
        <Checkbox
          data-testid="bulk-include-duplicates"
          checked={includeDuplicates}
          onChange={(event) => setIncludeDuplicates(event.target.checked)}
        />
        Include duplicate members
      </label>
      <select
        value={status}
        onChange={(event) => setStatus(event.target.value as ItemStatus)}
        className="rounded-md border border-input bg-background px-2 py-1"
        aria-label="Bulk status"
      >
        {ITEM_STATUSES.map((s) => (
          <option key={s} value={s}>
            {STATUS_LABELS[s]}
          </option>
        ))}
      </select>
      <Button
        size="sm"
        data-testid="bulk-apply-status"
        onClick={() => applyStatus.mutate()}
        disabled={applyStatus.isPending}
      >
        Apply status
      </Button>
      <Input
        aria-label="Add tag to selection"
        placeholder="Add tag…"
        value={tagInput}
        onChange={(event) => setTagInput(event.target.value)}
        className="w-40"
      />
      <Button
        size="sm"
        variant="outline"
        onClick={() => addTag.mutate()}
        disabled={!tagInput.trim() || addTag.isPending}
      >
        Add tag
      </Button>
      <Input
        aria-label="Add note to selection"
        placeholder="Add note…"
        value={noteInput}
        onChange={(event) => setNoteInput(event.target.value)}
        className="w-40"
      />
      <Button
        size="sm"
        variant="outline"
        data-testid="bulk-apply-note"
        onClick={() => applyNote.mutate()}
        disabled={!noteInput.trim() || applyNote.isPending}
      >
        Add note
      </Button>
      {settings?.enrichment_enabled && (
        <Button
          size="sm"
          variant="outline"
          data-testid="bulk-enrich"
          onClick={() => enrichSelection.mutate()}
          disabled={enrichSelection.isPending}
        >
          {enrichSelection.isPending ? "Enriching…" : "Enrich selection"}
        </Button>
      )}
      <Button
        size="sm"
        variant="outline"
        data-testid="bulk-generate-projects"
        onClick={() => generateFromSelection.mutate()}
        disabled={generateFromSelection.isPending}
      >
        {generateFromSelection.isPending ? "Starting…" : "Generate projects"}
      </Button>
      {generateFromSelection.isSuccess && (
        <span className="text-xs text-muted-foreground" data-testid="bulk-generate-status">
          Generation job #{generateFromSelection.data.job_id} started — see Projects.
        </span>
      )}
      {generateFromSelection.isError && (
        <span className="text-xs text-destructive" data-testid="bulk-generate-error">
          {generateFromSelection.error instanceof ApiError
            ? generateFromSelection.error.message
            : "Generation request failed."}
        </span>
      )}
      <Button size="sm" variant="ghost" onClick={onClearSelection}>
        Clear selection
      </Button>
    </div>
  );
}
