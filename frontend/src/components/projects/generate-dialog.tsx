"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  ApiError,
  generateProjects,
  getClusterRun,
  listClusterRuns,
} from "@/lib/api";

export interface GenerateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStarted: (jobId: number) => void;
}

/** Cluster picker over the latest succeeded run + idea count. */
export function GenerateDialog({ open, onOpenChange, onStarted }: GenerateDialogProps) {
  const [selectedClusterIds, setSelectedClusterIds] = useState<number[]>([]);
  const [countInput, setCountInput] = useState("3");

  const runs = useQuery({
    queryKey: ["cluster-runs"],
    queryFn: listClusterRuns,
    enabled: open,
  });
  const latestSucceeded = runs.data?.find((run) => run.status === "succeeded");

  const runDetail = useQuery({
    queryKey: ["cluster-run", latestSucceeded?.id],
    queryFn: () => getClusterRun(latestSucceeded!.id),
    enabled: open && latestSucceeded !== undefined,
  });

  const generate = useMutation({
    mutationFn: () =>
      generateProjects({
        cluster_ids: selectedClusterIds,
        count: Number(countInput) || undefined,
      }),
    onSuccess: (accepted) => {
      setSelectedClusterIds([]);
      onOpenChange(false);
      onStarted(accepted.job_id);
    },
  });

  function toggleCluster(clusterId: number) {
    setSelectedClusterIds((current) =>
      current.includes(clusterId)
        ? current.filter((id) => id !== clusterId)
        : [...current, clusterId],
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange} className="max-w-lg">
      <DialogHeader>
        <DialogTitle>Generate project ideas</DialogTitle>
        <DialogDescription>
          Pick the clusters to ground the ideas in. Only items with real text (share text,
          adjacent messages, enrichment, or your notes) ever reach the AI provider — every
          generated idea cites its source items, verified server-side.
        </DialogDescription>
      </DialogHeader>
      <div className="space-y-3">
        {runs.isLoading && <p className="text-sm text-muted-foreground">Loading clusters…</p>}
        {runs.data && latestSucceeded === undefined && (
          <p className="text-sm text-muted-foreground" data-testid="generate-no-clusters">
            No cluster run yet —{" "}
            <Link className="underline" href="/clusters">
              run analysis
            </Link>{" "}
            first, or generate from an inbox selection instead.
          </p>
        )}
        {runDetail.data && (
          <ul className="max-h-64 space-y-1 overflow-y-auto" data-testid="generate-cluster-list">
            {runDetail.data.clusters.map((cluster) => (
              <li key={cluster.id}>
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    data-testid="generate-cluster-checkbox"
                    checked={selectedClusterIds.includes(cluster.id)}
                    onChange={() => toggleCluster(cluster.id)}
                  />
                  <span className="truncate">
                    {cluster.label ?? `Cluster #${cluster.id}`}{" "}
                    <span className="text-muted-foreground">({cluster.size} items)</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
        <label className="block text-sm">
          Number of ideas
          <Input
            data-testid="generate-count"
            className="mt-1 max-w-24"
            type="number"
            min="1"
            max="10"
            value={countInput}
            onChange={(event) => setCountInput(event.target.value)}
          />
        </label>
        {generate.isError && (
          <p className="text-sm text-destructive" data-testid="generate-error">
            {generate.error instanceof ApiError
              ? generate.error.message
              : "Generation request failed."}
          </p>
        )}
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button
          data-testid="generate-start"
          disabled={generate.isPending || selectedClusterIds.length === 0}
          onClick={() => generate.mutate()}
        >
          {generate.isPending ? "Starting…" : "Generate"}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
