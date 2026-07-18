"use client";

import { useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import {
  ITEM_STATUSES,
  enrichItems,
  getSettings,
  listItems,
  updateItem,
  type ItemEntry,
  type ItemStatus,
} from "@/lib/api";
import { STATUS_LABELS, STATUS_VARIANT, TYPE_LABELS } from "@/lib/item-labels";
import type { ReviewAction } from "@/lib/review-keyboard";
import { useReviewKeyboard } from "@/lib/use-review-keyboard";

const REVIEW_PAGE_SIZE = 100;
const LEGEND = ITEM_STATUSES.map((s, i) => `${i + 1}=${STATUS_LABELS[s]}`).join(", ");

export default function ReviewPage() {
  const queryClient = useQueryClient();
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const [index, setIndex] = useState(0);
  const [draftNote, setDraftNote] = useState("");
  const [editingNote, setEditingNote] = useState(false);

  const { data: page, isLoading } = useQuery({
    queryKey: ["review-queue"],
    queryFn: () =>
      listItems({
        status: ["new", "needs_context"],
        order: "needs_context_first",
        page_size: REVIEW_PAGE_SIZE,
      }),
  });

  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: getSettings });

  const entries = useMemo<ItemEntry[]>(() => page?.entries ?? [], [page]);
  const current = entries[index];
  const currentItemId = current?.item.id;

  // "Adjusting state when a prop changes" during render (not in an effect):
  // reset the draft note whenever the reviewed item changes, not on every
  // keystroke — tracked by id so a re-fetch with the same entries is a no-op.
  const [trackedItemId, setTrackedItemId] = useState(currentItemId);
  if (trackedItemId !== currentItemId) {
    setTrackedItemId(currentItemId);
    setDraftNote(current?.item.context_note ?? "");
    setEditingNote(false);
  }

  const save = useMutation({
    mutationFn: (vars: { itemId: number; status: ItemStatus; note: string }) =>
      updateItem(vars.itemId, { status: vars.status, context_note: vars.note }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["items"] });
    },
  });

  const enrich = useMutation({
    mutationFn: (itemId: number) => enrichItems({ item_ids: [itemId] }),
  });

  function advance() {
    setIndex((i) => Math.min(i + 1, entries.length));
  }

  function goPrev() {
    setIndex((i) => Math.max(i - 1, 0));
  }

  function handleAction(action: ReviewAction) {
    if (!current) return;
    switch (action.type) {
      case "next":
        advance();
        return;
      case "prev":
        goPrev();
        return;
      case "open":
        window.open(current.item.url_raw, "_blank", "noopener,noreferrer");
        return;
      case "focus_note":
        noteRef.current?.focus();
        return;
      case "save_and_advance":
        save.mutate({ itemId: current.item.id, status: "reviewed", note: draftNote });
        noteRef.current?.blur();
        advance();
        return;
      case "cancel_edit":
        setDraftNote(current.item.context_note ?? "");
        noteRef.current?.blur();
        return;
      case "skip":
        advance();
        return;
      case "set_status":
        save.mutate({ itemId: current.item.id, status: action.status, note: draftNote });
        advance();
        return;
    }
  }

  useReviewKeyboard({ isEditingNote: editingNote, onAction: handleAction, enabled: Boolean(current) });

  if (isLoading) {
    return (
      <main className="mx-auto w-full max-w-2xl flex-1 px-6 py-12 text-sm text-muted-foreground">
        Loading…
      </main>
    );
  }

  if (entries.length === 0 || !current) {
    return (
      <main className="mx-auto w-full max-w-2xl flex-1 space-y-6 px-6 py-12">
        <h1 className="text-2xl font-semibold tracking-tight">Review</h1>
        <p className="text-sm text-muted-foreground" data-testid="review-empty">
          {entries.length === 0
            ? "Nothing to review right now."
            : "You've reached the end of this review batch."}
        </p>
        <Link className="underline" href="/inbox">
          ← Back to inbox
        </Link>
      </main>
    );
  }

  const item = current.item;
  const enrichedSourceLabel = item.enriched_source === "oembed" ? "oEmbed" : "OpenGraph";

  return (
    <main
      className="mx-auto w-full max-w-2xl flex-1 space-y-6 px-6 py-12"
      data-testid="review-page"
    >
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Review</h1>
        <span className="text-sm text-muted-foreground" data-testid="review-progress">
          {index + 1} of {entries.length}
        </span>
      </div>

      <Card data-testid="review-card" data-item-id={item.id}>
        <CardContent className="space-y-4 p-5 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">{TYPE_LABELS[item.item_type]}</Badge>
            <Badge data-testid="review-status" variant={STATUS_VARIANT[item.status]}>
              {STATUS_LABELS[item.status]}
            </Badge>
            {item.tags.map((tag) => (
              <Badge key={tag} variant="muted">
                {tag}
              </Badge>
            ))}
          </div>

          {item.share_text && <p>{item.share_text}</p>}
          {item.adjacent_text && (
            <p className="text-muted-foreground">Nearby: {item.adjacent_text}</p>
          )}
          {item.enriched_caption && (
            <p data-testid="enriched-caption">
              {item.enriched_caption}{" "}
              <span className="text-xs text-muted-foreground">(via {enrichedSourceLabel})</span>
            </p>
          )}
          {!item.share_text && !item.adjacent_text && !item.enriched_caption && (
            <p className="text-muted-foreground">No context yet — describe it below.</p>
          )}

          <div className="flex items-center gap-2">
            <a
              href={item.url_raw}
              target="_blank"
              rel="noopener noreferrer"
              data-testid="open-original"
              className="underline"
            >
              Open original ↗
            </a>
            {settings?.enrichment_enabled && (
              <Button
                size="sm"
                variant="outline"
                data-testid="enrich-button"
                onClick={() => enrich.mutate(item.id)}
                disabled={enrich.isPending}
              >
                {enrich.isPending ? "Enriching…" : "Enrich"}
              </Button>
            )}
          </div>

          <label className="block space-y-1">
            <span className="text-xs font-medium text-muted-foreground">
              Note (Enter saves and advances)
            </span>
            <Textarea
              ref={noteRef}
              data-testid="review-note"
              value={draftNote}
              onChange={(event) => setDraftNote(event.target.value)}
              onFocus={() => setEditingNote(true)}
              onBlur={() => setEditingNote(false)}
            />
          </label>
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground" data-testid="review-legend">
        j/k navigate · o open original · e edit note · Enter save &amp; advance · s skip · 1–5 set
        status ({LEGEND})
      </p>
    </main>
  );
}
