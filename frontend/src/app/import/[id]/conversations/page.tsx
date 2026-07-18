"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ApiError,
  FINISHED_JOB_STATUSES,
  getJob,
  listConversations,
  selectConversations,
  type ConversationRead,
} from "@/lib/api";

function countsSummary(conversation: ConversationRead): string {
  return `${conversation.message_count} messages · ${conversation.link_count} links`;
}

export default function ConversationSelectorPage() {
  const params = useParams<{ id: string }>();
  const importId = Number(params.id);

  const { data: conversations, isError } = useQuery({
    queryKey: ["conversations", importId],
    queryFn: () => listConversations(importId),
    enabled: Number.isInteger(importId) && importId > 0,
  });

  // Initialized once per importId from each conversation's own `is_selected`
  // — every conversation (self-DM or not) defaults unchecked server-side, so
  // "never pre-assume a self-DM candidate" needs no special-case logic here.
  // A prior partial selection (e.g. retry after a failed extract) is
  // restored as-is. Set during render (React's documented pattern for
  // deriving state from props) rather than in an effect, so a background
  // refetch of the same import's conversations never clobbers in-progress
  // checkbox edits.
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [initializedForImportId, setInitializedForImportId] = useState<number | null>(null);
  if (conversations && initializedForImportId !== importId) {
    setInitializedForImportId(importId);
    setSelected(new Set(conversations.filter((c) => c.is_selected).map((c) => c.id)));
  }

  const [jobId, setJobId] = useState<number | null>(null);

  const extract = useMutation({
    mutationFn: () => selectConversations(importId, Array.from(selected)),
    onSuccess: (accepted) => setJobId(accepted.job_id),
  });

  const { data: job } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId as number),
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status !== undefined && FINISHED_JOB_STATUSES.includes(status) ? false : 2000;
    },
  });

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  return (
    <main className="mx-auto w-full max-w-2xl flex-1 space-y-6 px-6 py-12">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Select conversations</h1>
        <p className="text-sm text-muted-foreground">
          <Link className="underline" href={`/import/${importId}`}>
            ← Back to import
          </Link>
        </p>
      </div>
      <Card data-testid="conversation-selector">
        <CardHeader>
          <CardTitle>Conversations</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {isError && <p className="text-destructive">Import not found or not yet scanned.</p>}
          {conversations === undefined ? (
            <p className="text-muted-foreground">Loading…</p>
          ) : conversations.length === 0 ? (
            <p className="text-muted-foreground">No conversations found.</p>
          ) : (
            <ul className="divide-y">
              {conversations.map((conversation) => {
                const checkboxId = `conversation-${conversation.id}`;
                return (
                  <li
                    key={conversation.id}
                    data-testid="conversation-row"
                    className="flex items-start gap-3 py-3"
                  >
                    <Checkbox
                      id={checkboxId}
                      checked={selected.has(conversation.id)}
                      onChange={() => toggle(conversation.id)}
                      className="mt-1"
                    />
                    <label htmlFor={checkboxId} className="flex-1 cursor-pointer space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">
                          {conversation.title ?? conversation.thread_path}
                        </span>
                        {conversation.is_self_dm_candidate && (
                          <Badge data-testid="self-dm-badge" variant="secondary">
                            Self-DM candidate
                          </Badge>
                        )}
                      </div>
                      <p className="text-muted-foreground">
                        {conversation.participant_names.join(", ")}
                      </p>
                      <p className="text-muted-foreground">{countsSummary(conversation)}</p>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      <div className="space-y-3">
        <Button
          data-testid="extract-button"
          onClick={() => extract.mutate()}
          disabled={selected.size === 0 || extract.isPending || jobId !== null}
        >
          {extract.isPending ? "Starting extraction…" : "Start extraction"}
        </Button>
        {extract.error && (
          <p className="text-destructive">
            {extract.error instanceof ApiError ? extract.error.message : "Extraction failed."}
          </p>
        )}
        {job && (
          <p data-testid="extract-job-status" className="text-sm">
            Extraction: {job.status} ({job.progress}/{job.total})
          </p>
        )}
        {job?.status === "succeeded" && (
          <p>
            <Link className="underline" href="/inbox">
              Go to inbox →
            </Link>
          </p>
        )}
      </div>
    </main>
  );
}
