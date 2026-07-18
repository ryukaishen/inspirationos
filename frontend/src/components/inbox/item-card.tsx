"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Textarea } from "@/components/ui/textarea";
import {
  ITEM_STATUSES,
  enrichItems,
  getSettings,
  updateItem,
  type ItemEntry,
  type ItemStatus,
} from "@/lib/api";
import { STATUS_LABELS, STATUS_VARIANT, TYPE_LABELS } from "@/lib/item-labels";

function formatTimestamp(value: string | null): string {
  if (!value) return "Unknown date";
  return new Date(value).toLocaleString();
}

export interface ItemCardProps {
  entry: ItemEntry;
  selected: boolean;
  onToggleSelect: (itemId: number) => void;
}

export function ItemCard({ entry, selected, onToggleSelect }: ItemCardProps) {
  const { item, duplicate_count: duplicateCount } = entry;
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draftStatus, setDraftStatus] = useState<ItemStatus>(item.status);
  const [draftTags, setDraftTags] = useState(item.tags.join(", "));
  const [draftNote, setDraftNote] = useState(item.context_note ?? "");

  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: getSettings });
  const enrich = useMutation({
    mutationFn: () => enrichItems({ item_ids: [item.id] }),
  });

  const save = useMutation({
    mutationFn: () =>
      updateItem(item.id, {
        status: draftStatus,
        tags: draftTags
          .split(",")
          .map((tag) => tag.trim())
          .filter((tag) => tag.length > 0),
        context_note: draftNote,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["items"] });
      setEditing(false);
    },
  });

  function cancelEdit() {
    setDraftStatus(item.status);
    setDraftTags(item.tags.join(", "));
    setDraftNote(item.context_note ?? "");
    setEditing(false);
  }

  const previewText = item.share_text ?? item.adjacent_text;

  return (
    <Card data-testid="item-card" data-item-id={item.id}>
      <CardContent className="space-y-3 p-4 text-sm">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2">
            <Checkbox
              aria-label={`Select item ${item.id}`}
              checked={selected}
              onChange={() => onToggleSelect(item.id)}
            />
            <Badge variant="outline">{TYPE_LABELS[item.item_type]}</Badge>
            {duplicateCount > 1 && (
              <Badge data-testid="duplicate-badge" variant="secondary">
                ×{duplicateCount}
              </Badge>
            )}
          </div>
          <span className="text-muted-foreground">{formatTimestamp(item.shared_at)}</span>
        </div>

        {previewText && <p className="line-clamp-3 text-foreground">{previewText}</p>}

        {editing ? (
          <div className="space-y-2">
            <label className="block space-y-1">
              <span className="text-xs font-medium text-muted-foreground">Status</span>
              <select
                value={draftStatus}
                onChange={(event) => setDraftStatus(event.target.value as ItemStatus)}
                className="w-full rounded-md border border-input bg-background px-2 py-1 text-sm"
              >
                {ITEM_STATUSES.map((status) => (
                  <option key={status} value={status}>
                    {STATUS_LABELS[status]}
                  </option>
                ))}
              </select>
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-muted-foreground">
                Tags (comma-separated)
              </span>
              <input
                value={draftTags}
                onChange={(event) => setDraftTags(event.target.value)}
                className="w-full rounded-md border border-input bg-background px-2 py-1 text-sm"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-muted-foreground">Note</span>
              <Textarea
                value={draftNote}
                onChange={(event) => setDraftNote(event.target.value)}
              />
            </label>
            <div className="flex gap-2">
              <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
                {save.isPending ? "Saving…" : "Save"}
              </Button>
              <Button size="sm" variant="ghost" onClick={cancelEdit}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge data-testid="item-status" variant={STATUS_VARIANT[item.status]}>
                {STATUS_LABELS[item.status]}
              </Badge>
              {item.tags.map((tag) => (
                <Badge key={tag} variant="muted">
                  {tag}
                </Badge>
              ))}
            </div>
            <p className="text-muted-foreground">{item.context_note || "No note yet."}</p>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
                Edit
              </Button>
              <a
                href={item.url_raw}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="open-original"
                className="text-xs underline"
              >
                Open original ↗
              </a>
              {settings?.enrichment_enabled && (
                <Button
                  size="sm"
                  variant="outline"
                  data-testid="enrich-button"
                  onClick={() => enrich.mutate()}
                  disabled={enrich.isPending}
                >
                  {enrich.isPending ? "Enriching…" : "Enrich"}
                </Button>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
