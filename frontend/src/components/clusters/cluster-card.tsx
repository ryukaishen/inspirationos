"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  ApiError,
  bulkUpdateItems,
  enrichItems,
  getClusterItems,
  updateCluster,
  type ClusterRead,
} from "@/lib/api";

export function ClusterCard({ cluster }: { cluster: ClusterRead }) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [labelDraft, setLabelDraft] = useState("");
  const [descriptionDraft, setDescriptionDraft] = useState("");
  const [bulkNote, setBulkNote] = useState("");
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const members = useQuery({
    queryKey: ["cluster-items", cluster.id],
    queryFn: () => getClusterItems(cluster.id),
    enabled: expanded,
  });
  const memberIds = members.data?.items.map((item) => item.id) ?? [];

  const invalidateRun = async () => {
    await queryClient.invalidateQueries({ queryKey: ["cluster-run", cluster.run_id] });
  };

  const saveEdit = useMutation({
    mutationFn: () =>
      updateCluster(cluster.id, {
        label: labelDraft.trim() || undefined,
        description_md: descriptionDraft,
      }),
    onSuccess: async () => {
      setEditing(false);
      await invalidateRun();
    },
  });

  const bulkDescribe = useMutation({
    mutationFn: () => bulkUpdateItems({ item_ids: memberIds, context_note: bulkNote }),
    onSuccess: (result) => {
      setActionMessage(`Note applied to ${result.updated} items.`);
      setBulkNote("");
    },
  });

  const enrich = useMutation({
    mutationFn: () => enrichItems({ item_ids: memberIds }),
    onSuccess: (accepted) => setActionMessage(`Enrichment job #${accepted.job_id} started.`),
    onError: (error) => {
      setActionMessage(
        error instanceof ApiError ? error.message : "Enrichment request failed.",
      );
    },
  });

  function startEditing() {
    setLabelDraft(cluster.label ?? "");
    setDescriptionDraft(cluster.description_md ?? "");
    setEditing(true);
  }

  return (
    <div className="space-y-3 rounded-lg border bg-card p-4" data-testid="cluster-card">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <p className="font-medium" data-testid="cluster-label">
            {cluster.label ?? "Unlabeled cluster"}
          </p>
          <p className="text-xs text-muted-foreground" data-testid="cluster-size">
            {cluster.size} items
          </p>
          {cluster.topics.length > 0 && (
            <div className="flex flex-wrap gap-1" data-testid="cluster-topics">
              {cluster.topics.map((topic) => (
                <Badge key={topic} variant="secondary" data-testid="topic-chip">
                  {topic}
                </Badge>
              ))}
            </div>
          )}
        </div>
        <div className="flex shrink-0 gap-2">
          <Button
            size="sm"
            variant="ghost"
            data-testid="cluster-edit"
            onClick={() => (editing ? setEditing(false) : startEditing())}
          >
            {editing ? "Cancel" : "Edit"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            data-testid="cluster-expand"
            onClick={() => setExpanded((current) => !current)}
          >
            {expanded ? "Hide items" : "Show items"}
          </Button>
        </div>
      </div>

      {!editing && cluster.description_md && (
        <p className="text-sm text-muted-foreground" data-testid="cluster-description">
          {cluster.description_md}
        </p>
      )}

      {editing && (
        <div className="space-y-2">
          <Input
            aria-label="Cluster label"
            data-testid="cluster-label-input"
            value={labelDraft}
            onChange={(event) => setLabelDraft(event.target.value)}
            placeholder="Cluster label"
          />
          <Textarea
            aria-label="Cluster description"
            data-testid="cluster-description-input"
            value={descriptionDraft}
            onChange={(event) => setDescriptionDraft(event.target.value)}
            placeholder="What this cluster is about"
          />
          <Button
            size="sm"
            data-testid="cluster-save"
            disabled={saveEdit.isPending}
            onClick={() => saveEdit.mutate()}
          >
            Save
          </Button>
        </div>
      )}

      {expanded && (
        <div className="space-y-3 border-t pt-3">
          {members.isLoading && <p className="text-sm text-muted-foreground">Loading items…</p>}
          {members.data && (
            <>
              <ul className="space-y-1">
                {members.data.items.map((item) => (
                  <li
                    key={item.id}
                    className="truncate text-sm"
                    data-testid="cluster-member"
                  >
                    <a
                      className="underline"
                      href={item.url_canonical}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {item.shortcode ?? item.url_canonical}
                    </a>{" "}
                    <span className="text-muted-foreground">
                      {item.share_text ?? item.adjacent_text ?? item.context_note ?? ""}
                    </span>
                  </li>
                ))}
              </ul>
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  aria-label="Cluster note"
                  data-testid="bulk-note-input"
                  className="max-w-xs"
                  value={bulkNote}
                  onChange={(event) => setBulkNote(event.target.value)}
                  placeholder="Describe all items in this cluster…"
                />
                <Button
                  size="sm"
                  data-testid="bulk-apply"
                  disabled={bulkDescribe.isPending || !bulkNote.trim() || memberIds.length === 0}
                  onClick={() => bulkDescribe.mutate()}
                >
                  Apply note to all
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  data-testid="cluster-enrich"
                  disabled={enrich.isPending || memberIds.length === 0}
                  onClick={() => enrich.mutate()}
                >
                  Enrich cluster
                </Button>
              </div>
              {actionMessage && (
                <p className="text-xs text-muted-foreground" data-testid="cluster-action-status">
                  {actionMessage}
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
