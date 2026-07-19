"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ClusterCard } from "@/components/clusters/cluster-card";
import { Button } from "@/components/ui/button";
import {
  getClusterRun,
  getJob,
  listClusterRuns,
  triggerCluster,
  triggerEmbed,
  triggerTopics,
} from "@/lib/api";
import {
  AnalysisStepFailedError,
  runAnalysisPipeline,
  type AnalysisProgress,
} from "@/lib/analysis-pipeline";

const STEP_LABELS: Record<AnalysisProgress["step"], string> = {
  embed: "Embedding item texts",
  cluster: "Clustering",
  topics: "Extracting topics & labels",
};

export default function ClustersPage() {
  const queryClient = useQueryClient();
  const [progress, setProgress] = useState<AnalysisProgress | null>(null);

  const runs = useQuery({ queryKey: ["cluster-runs"], queryFn: listClusterRuns });
  const latestRun = runs.data?.[0];

  const runDetail = useQuery({
    queryKey: ["cluster-run", latestRun?.id],
    queryFn: () => getClusterRun(latestRun!.id),
    enabled: latestRun !== undefined,
  });

  const analysis = useMutation({
    mutationFn: () =>
      runAnalysisPipeline({
        triggerEmbed,
        triggerCluster,
        triggerTopics,
        getJob,
        onProgress: setProgress,
      }),
    onSettled: async () => {
      setProgress(null);
      await queryClient.invalidateQueries({ queryKey: ["cluster-runs"] });
      await queryClient.invalidateQueries({ queryKey: ["cluster-run"] });
    },
  });

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 space-y-6 px-6 py-12">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Clusters</h1>
        <p className="text-sm text-muted-foreground">
          Semantic clusters over your saved items — run analysis before manual review so a
          whole group of related reels can be described once. Everything runs locally: with
          the local embedding model the first run downloads the model once; your item texts
          never leave your machine unless you have explicitly configured a cloud AI
          provider in Settings.
        </p>
      </div>

      <div className="space-y-2 rounded-lg border bg-card p-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="font-medium">Run analysis</p>
            <p className="text-sm text-muted-foreground">
              Embeds item texts, clusters them, then labels each cluster and extracts
              topics ({latestRun ? `latest run #${latestRun.id}` : "no runs yet"}).
            </p>
          </div>
          <Button
            data-testid="run-analysis"
            disabled={analysis.isPending}
            onClick={() => analysis.mutate()}
          >
            {analysis.isPending ? "Running…" : "Run analysis"}
          </Button>
        </div>
        {progress && (
          <p className="text-sm text-muted-foreground" data-testid="analysis-status">
            {STEP_LABELS[progress.step]} — {progress.job.status}
            {progress.job.total > 0 && ` (${progress.job.progress}/${progress.job.total})`}
          </p>
        )}
        {analysis.isError && (
          <p className="text-sm text-destructive" data-testid="analysis-error">
            {analysis.error instanceof AnalysisStepFailedError
              ? `The ${analysis.error.step} step failed (job #${analysis.error.job.id}).`
              : "Analysis failed — check the backend logs."}
          </p>
        )}
        {analysis.isSuccess && !progress && (
          <p className="text-sm text-muted-foreground" data-testid="analysis-done">
            Analysis complete.
          </p>
        )}
      </div>

      {runs.isLoading && <p className="text-sm text-muted-foreground">Loading runs…</p>}
      {runs.data && runs.data.length === 0 && (
        <p className="text-sm text-muted-foreground" data-testid="no-runs">
          No cluster runs yet. Extract some items, then run analysis.
        </p>
      )}

      {runDetail.data && (
        <section className="space-y-3" data-testid="cluster-list">
          <h2 className="text-lg font-medium">
            Run #{runDetail.data.id} — {runDetail.data.cluster_count} clusters
            <span className="ml-2 text-sm font-normal text-muted-foreground">
              {runDetail.data.embedding_model}
            </span>
          </h2>
          {runDetail.data.clusters.length === 0 && (
            <p className="text-sm text-muted-foreground" data-testid="no-clusters">
              No clusters of two or more related items were found in this run.
            </p>
          )}
          {runDetail.data.clusters.map((cluster) => (
            <ClusterCard key={cluster.id} cluster={cluster} />
          ))}
        </section>
      )}
    </main>
  );
}
